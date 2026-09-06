# Handoff Report: Milestone M1 (Correctness & Human-Fairness Review)

## 1. Observation
- **Inspected Files**:
  - `vendor/balatro-rl/balatro_sim/agent_v10.py`:
    - Lines 133-144: `RELIABLE_XMULT_JOKERS` and `HIGH_LEVERAGE_SCORING_JOKERS` catalogs.
    - Lines 716-728: `portfolio_target_hand` implementing tiered `_HAND_ENGINE_PRIORITY`.
    - Lines 760-824: `deck_reshape_target` supporting `j_trio`, `j_duo`, and face jokers {11, 12, 13}.
    - Lines 827-860: `_reshape_tarot_bonus` dynamic synergy values (Death +0.22, Strength +0.10, Hanged Man +0.05/+0.04/+0.03, Justice +0.16, Magician +0.12).
    - Lines 1068-1178: `_v10_tarot_action` targeting Death, Strength, and Hanged Man with engine protection.
    - Lines 1258-1285: `_v10_maybe_use_planet` immediate in-shop consumption and in-combat leveling.
    - Lines 1309-1345: `_joker_sell_value` and full-slot worst-joker liquidation allowance in `_v10_rank_shop_items`.
    - Lines 1449-1478: `_forecast_round_score` and `_ante_boss_target`.
    - Lines 1516-1596: R1 interest floor relaxation ($0 in Ante 8, $0 in Ante 7 under deficit, $15 in Ante 6 without xMult) and urgent reroll limits (10 in Ante 8, 6 in Ante 7, 4 in Ante 6) with `capital_after_reroll >= 6` reserve buffer.
    - Lines 2341-2519: `SCALING_ACCEL_KEYS`, `SCALING_BANNED_BOSSES`, `_has_scoring_face`, and `_find_scaling_action` (Tier S1 minimal disjoint knockout preservation and Tier S2 probabilistic safety).
    - Lines 2613-2623: Green Joker safe-blind discard suppression in `_tier1_survive`.
    - Lines 2985-2988: Gated scaling action trigger in in-blind cascade.
    - Lines 3042-3160: `formulate_counterfactual_state` pure read-only feature extraction.
    - Lines 3358-3384: `SearchShopV10.decide` search cache reset `self._searched_this_visit = False` on rerolls.
  - `vendor/balatro-rl/tests/test_scaling_acceleration.py`: 9 targeted regression tests.
  - `vendor/balatro-rl/balatro_sim/agent_v9.py`: Baseline is preserved; V9 reproduction verified.
- **Executed Test Commands and Verbatim Results**:
  - `python -m pytest vendor/balatro-rl/tests/test_scaling_acceleration.py -v`:
    ```text
    9 passed in 0.29s
    ```
  - `python -m pytest vendor/balatro-rl/tests/test_agent_v10.py -v`:
    ```text
    50 passed in 29.93s
    (including TestFarmOffReproducesV9::test_farm_off_matches_v9 PASSED,
     TestAnte1PaceRule::test_fatal_seeds_clear_ante1 PASSED)
    ```
  - `python -m pytest vendor/balatro-rl/tests/test_seed_exactness.py -m ci_gate -v`:
    ```text
    4 passed in 7.34s
    ```
  - `python tools/audit_jokers_static.py`:
    ```text
    catalogue: 150  registry: 168  aliases: 18  spec: 150
    GATES: CLEAN
    ```
  - `python tools/audit_consumables_static.py`:
    ```text
    spec: 22 tarots / 12 planets / 18 spectrals
    GATES: CLEAN
    ```
  - `python tools/audit_bosses_static.py`:
    ```text
    boss spec: 28 bosses (23 regular + 5 finishers)
    GATES: CLEAN
    ```
  - `python tools/audit_tags_static.py`:
    ```text
    tag spec: 24 tags, 9 ante-2 gated, packs 5
    GATES: CLEAN
    ```
  - `python -m pytest vendor/balatro-rl/tests vendor/balatro-rl/balatro_sim/tests -q`:
    ```text
    1621 passed, 3 skipped, 4 deselected in 254.85s (0:04:14)
    ```

## 2. Logic Chain
1. **Observation**: R1 requires adaptive interest relaxation and aggressive late-game rerolls in Antes 6–8 when forecasted score cannot clear boss targets.
   **Inference**: `_v10_decide_shop` explicitly calculates `forecast_score` and `boss_target`, drops the interest floor to $0 in Ante 8 and Ante 7 under deficit, relaxes rerolls up to 10 with a $6 post-reroll capital check, resets `self._searched_this_visit = False` on reroll, and factors in `worst_sell` when joker slots are full. This completely satisfies R1.
2. **Observation**: R2 requires aligning deck reshaping (Death, Strength, Hanged Man) and planet usage with the active joker engine.
   **Inference**: `portfolio_target_hand` prioritizes xMult -> scaling -> chip/suit engines; `deck_reshape_target` extends rank targets for `j_trio`, `j_duo`, and face jokers; `_v10_tarot_action` targets optimal donor/recipient pairs while protecting engine ranks; and `_v10_maybe_use_planet` proactively consumes planets in the shop. This completely satisfies R2.
3. **Observation**: R3 requires accelerating scaling jokers (Wee, Ride the Bus, Green Joker, Square Joker, Spare Trousers, Supernova) during safe blinds.
   **Inference**: `_find_scaling_action` implements Tier S1 (reserving minimal disjoint knockout hand $K$, leaving $K$ 100% intact in hand for the next turn) and Tier S2 ($P(\text{clear}) \ge 0.98$ and $1.25\times$ target score capacity), with strict non-face verification for Ride the Bus, Hanging Chad index-0 ordering for Wee Joker, and discard suppression for Green Joker. This completely satisfies R3.
4. **Observation**: Human-fairness requires zero draw-order peeking, zero future RNG stream consumption, and zero live game mutation during evaluation.
   **Inference**: All deck evaluations use unordered multiset counts (`_value_multiset`), isolated seed-0 throwaway RNG for EV sampling, and pure read-only feature extraction in `formulate_counterfactual_state`. CI exactness gate passed 4/4 without RNG leaks.
5. **Observation**: Backwards compatibility requires exact reproduction of V9 when farming is off (`farm_clear_threshold = 1.0`).
   **Inference**: `TestFarmOffReproducesV9::test_farm_off_matches_v9` passed, confirming that all new V10 policies are safely gated and do not affect baseline equivalence.

## 3. Caveats
- No caveats. All core requirements (R1, R2, R3) and human-fairness invariants were inspected, mathematically checked, and tested against the full suite.

## 4. Conclusion
**Verdict**: **APPROVE**  
The implementation in `vendor/balatro-rl/balatro_sim/agent_v10.py` and `vendor/balatro-rl/tests/test_scaling_acceleration.py` is verified to be completely correct, strictly human-fair, robustly safeguarded, free of integrity violations, and clean across all unit tests, static audits, and CI gates.

## 5. Verification Method
To independently verify:
```bash
python -m pytest vendor/balatro-rl/tests/test_scaling_acceleration.py -v
python -m pytest vendor/balatro-rl/tests/test_agent_v10.py -v
python -m pytest vendor/balatro-rl/tests/test_seed_exactness.py -m ci_gate -v
python tools/audit_jokers_static.py
python tools/audit_consumables_static.py
python tools/audit_bosses_static.py
python tools/audit_tags_static.py
python -m pytest vendor/balatro-rl/tests vendor/balatro-rl/balatro_sim/tests -q
```
Invalidation conditions:
- Any test failure in `test_scaling_acceleration.py` or `test_agent_v10.py`.
- Any failure in `test_seed_exactness.py -m ci_gate`.
- Any non-zero static audit gate.
