# Review & Adversarial Challenge Report: M1 Architecture & Robustness

## Review Summary

**Verdict**: APPROVE

Worker M1's implementation of the M1 scaling acceleration (R3), late-game capital deployment & urgent rerolls (R1), and synergistic deck reshaping & consumable utilization (R2) in `vendor/balatro-rl/balatro_sim/agent_v10.py` and `vendor/balatro-rl/tests/test_scaling_acceleration.py`is architecturally robust, mathematically sound, human-fair, and fully backwards-compatible.

All safety guardrails (Ride the Bus non-face, Green Joker discard suppression, Wee Joker rank-2 prioritization, and banned boss deactivation) operate with strict, defensive validation.

## Detailed Review by Dimensions

### 1. Safety Guardrails on Scaling Jokers (R3)
- [Correctness] *Ride the Bus (`j_ride_the_bus`)*:
  - In `_find_scaling_action`: Tier S1 (lines 2429-2431) and Tier S2 (lines 2480-2481) strictly execute `if has_bus and any(c.is_face_card for c in sc_c if not getattr(c, 'debuffed', False)): continue`. Any combination containing a scoring non-debuffed face card is disqualified.
  - In `_tier1_survive` (lines 2539-2545): When clearing hands exist, `safe_clearing = [pl for pl in clearing if not _has_scoring_face(game.hand, pl[1])]` is selected if available, preserving mult while surviving.
  - In discard suppression (lines 2618-2622): If `has_bus` is held during safe discard suppression, non-face plays are strictly filtered first.
- [Correctness] *Green Joker (`jg_green_joker`)*:
  - In `_tier1_survive` (lines 2613-2623): Discard suppression requires `safe_for_green = (p_clear is not None and (p_clear >= 0.99 if game.ante == 1 else p_clear >= 0.98))` AND `game.hands_left >= 2`.
  - Discard suppression is strictly inhibited on the final hand (hands_left == 1) and whenever P(clear) < 0.98, preventing premature defeat or unnecessary penalty.
- [Correctness] *Wee Joker (`j_wee`)*:
  - Both Tier S1 (lines 2436-2442) and Tier S2 (lines 2486-2492) filter twos: `twos = [i for i in combo if hand[i].rank == 2 and not getattr(hand[i], 'debuffed', False)]`.
  - The ordered combo is constructed as `ordered_combo = twos + others`, placing rank-2 cards at index 0. When Hanging Chad (`j_hanging_chad`) is owned, index 0 triggers twice more, tripling the +8 chip acceleration to +24 chips per played 2.
- [Conformance] *Banned Bosses*:
  - Lines 2350-2359 define `SCALING_BANNED_BOSSES =  {'bl_needle', 'bl_mouth', 'bl_eye', 'bl_grim', 'bl_hook', 'bl_tooth', 'bl_pillar', 'bl_psychic'}`.
  - Line 2384-2386 deactivates scaling immediately if `_boss_key(game) in SCALING_BANNED_BOSSES`.
- [Robustness] *Ante 1 Isolation*:
  - Line 2393-2394 imposes an elevated threshold P(clear) >= 0.99 in Ante 1, preventing risk during fragile opening rounds.


### 2. Architecture & Stability (R1 & R2)
- [Design & Robustness] *Multi-Hand Scoring Forecast (`_forecast_round_score`*):
  - Lines 1449-1456: Computes E[single] = reach * base_c + (1 - reach) * base_t, then scales by `base_hands * 0.85` (a 15% safety discount against variance).
  - Pure read-only computation; zero live game mutation; composition-only reasoning (strictly human-fair).
- [Economy Design] *Adaptive Interest Floor Relaxation*:
  - Ante 8: interest_target = 0, force_no_save = True. Correctly recognizes that interest after Ante 8 has zero terminal value in White Stake.
  - Ante 7: Under deficit (forecast_score < boss_target * 1.25), interest_target = 0, force_no_save = True. Prevents hoarding cash into fatal boss rounds.
  - Ante 6: Lacking xMult (n_xmult == 0 or forecast_score < boss_target), relaxes interest_target = min(interest_target, 15).
- [Capital Preservation] *Urgent Reroll Limits & $6 Capital Buffer*:
  - Reroll caps expanded to 10 (Ante 8), 6 (Ante 7), 4 (Ante 6).
  - Lines 1580-1588: Computes capital_after_reroll = game.dollars - reroll_cost + (worst_sell_val if slots_full else 0).
  - Enforces capital_after_reroll >= 6 in late urgent states. This guarantees that if a high-leverage joker appears in the rerolled shop, the agent actually has sufficient liquid capital to purchase it, avoiding wasted rerolls.
- [Slot Accounting] *Full-Slot Allowance Accounting*:
  - Lines 1333-1346: Evaluates eff_allowance = allowance + (worst_sell if slots_full and item.kind == 'joker').
  - Enables evaluating high-impact replacement jokers whose nominal price exceeds current cash but is affordable once the worst joker is liquidated, initiating a clean two-step atomic swap.


### 3. Backward Compatibility
- All modifications are conditioned on `V10_PARAMS.get('farm_clear_threshold', 0.90) < 1.0`.
- In `decide_blind`, `if p['farm_clear_threshold'] >= 1.0: return _tier1_survive(game, plays)`.
- Verified independently: `TestFarmOffReproducesV9:test_farm_off_matches_v9` PASSED cleanly (23.20s), confirming byte-identical decision reproducibility against the frozen V9 baseline.


## Adversarial Challenge & Stress-Testing

Overall Risk Assessment: LOW

### Challenge 1: Debuffed Face Cards with Ride the Bus
- *Assumption Challenged*: Debuffed face cards do not count as face cards for Ride the Bus.
- *Attack Scenario*: A debuffed Jack or King is played while scaling with Ride the Bus.
- *Analysis*: In `balatro_sim/jokers/scaling.py:301`, `has_face = any(c.is_face_card for c in ctx.scoring_cards if not c.debuffed)`. Debuffed face cards do not reset Ride the Bus. In `agent_v10.py:2430`, `if not getattr(c, 'debuffed', False)` correctly aligns with the engine hook.
- *Mitigation & Verdict*: PASS. No reset risk.

### Challenge 2: Non-Scoring Kickers with Wee Joker
- *Assumption Challenged*: Twos in candidate combos score chips for Wee Joker.
- *Attack Scenario*: A 2 is included in a 5-card combo as a kicker (e.g. Three 8s + 2 + 4). The 2 would not score in Three of a Kind.
- *Analysis*: Combos are sorted by `(scale_val, -score)`. Minimal hands (like High Card 2, r=1) score lower chips than 5-card hands, meaning minimal plays where the 2 is guaranteed to score are always ranked ahead of 5-card hands with kickers.
- *Mitigation & Verdict*: PASS. Natural minimal-combo prevention.

### Challenge 3: Reroll Termination & Capital Depletion
- *Asumption Challenged*: Urgent rerolls terminate without risking infinite loops or rerolling into poverty.
- *Attack Scenario*: Reroll cost is low and capital buffer is met repeatedly.
- *Analysis*: Every reroll increments `rerolls_used` and increases `reroll_cost` by $1. Strict cap `rerolls_used < eff_max` (max 10 in Ante 8) guarantees finite termination. Additionally, the `capital_after_reroll >= 6` limit ensures rerolling ceases before the agent cannot afford an uncommon joker.
- *Mitigation & Verdict*: PASSES stress test.


## Verified Claims & Test Executions

| Claim / Target | Verification Command | Result |
|---|---|---|
| R3 Scaling Regression (9 tests) | `python -m pytest vendor/balatro-rl/tests/test_scaling_acceleration.py -v` | **9 passed in 0.32s** |
| V10 Full Suite (50 tests) | python -m pytest vendor/balatro-rl/tests/test_agent_v10.py -v | **50 passed in 30.79s** |
| V9 Baseline Reproduction | python -m pytest vendor/balatro-rl/tests/test_agent_v10.py -k "test_farm_off_matches_v9" -v | **1 passed in 23.20s** |
| CI Seed Exactness Gate | python -m pytest vendor/balatro-rl/tests/test_seed_exactness.py -m ci_gate -v | **4 passed in 7.53s** |
| Static Audit Gates | python tools/audit_jokers_static.py (and consumables, bosses, tags) | **All 4 gates CLEAN** |
| Simulator Full Suite | python -m pytest vendor/balatro-rl/tests vendor/balatro-rl/balatro_sim/tests -q | **1621 passed, 3 skipped, 4 deselected in 239.62s** |

## Integrity Verification
- Hardcoded outputs/seeds: NONE. Verified that `agent_v10.py` contains zero seed-specific hardcoding or shortcuts.
- Dummy/facade logic: NONE. Tests in `test_scaling_acceleration.py` construct live game environments and exercise genuine hand evaluations.
- Human-fair constraints: Strict composition-only evaluation; zero peeking at future RNG draw orders; zero live game mutation.
