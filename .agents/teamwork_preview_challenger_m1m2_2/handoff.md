# Milestone 1 & 2 Challenger Handoff Report: Empirical Verification & Adversarial Testing

**Author**: `teamwork_preview_challenger_m1m2_2`  
**Target Milestones**: Milestone 1 (Ante-1 Pace Rule) & Milestone 2 (Portfolio Classification & Features)  
**Verdict**: **`APPROVE`**  
**Date**: 2026-09-02T22:11:30Z  

---

## 1. Observation

### 1.1 Empirical Challenge Test Suite (`tests/test_challenger_m1m2.py`)
A dedicated adversarial test suite (`tests/test_challenger_m1m2.py`, 40 test cases) was written and executed to empirically verify all milestone invariants:

```text
tests/test_challenger_m1m2.py::TestFarmOffExactnessChallenger::test_step_by_step_exactness_v9_vs_v10_farm_off_20_seeds[0..19] PASSED [50%]
tests/test_challenger_m1m2.py::TestFarmOffExactnessChallenger::test_farm_clear_threshold_above_one PASSED [52%]
tests/test_challenger_m1m2.py::TestPaceRuleBoundaryConditionsChallenger::test_exact_threshold_boundary_ante1 PASSED [55%]
tests/test_challenger_m1m2.py::TestPaceRuleBoundaryConditionsChallenger::test_boundary_hands_left_zero_and_one PASSED [57%]
tests/test_challenger_m1m2.py::TestPaceRuleBoundaryConditionsChallenger::test_boundary_target_zero_and_large PASSED [60%]
tests/test_challenger_m1m2.py::TestPaceRuleBoundaryConditionsChallenger::test_boundary_discards_left_zero PASSED [62%]
tests/test_challenger_m1m2.py::TestPaceRuleBoundaryConditionsChallenger::test_ante_scope_gate PASSED [65%]
tests/test_challenger_m1m2.py::TestPaceRuleBoundaryConditionsChallenger::test_fatal_seeds_205_275_step_by_step_trace PASSED [67%]
tests/test_challenger_m1m2.py::TestPortfolioAdversarialChallenger::test_all_150_canonical_jokers_classified PASSED [70%]
tests/test_challenger_m1m2.py::TestPortfolioAdversarialChallenger::test_all_canonical_aliases_classified_identically PASSED [72%]
tests/test_challenger_m1m2.py::TestPortfolioAdversarialChallenger::test_unknown_and_malformed_keys PASSED [75%]
tests/test_challenger_m1m2.py::TestPortfolioAdversarialChallenger::test_feature_extractor_adversarial_states PASSED [77%]
tests/test_challenger_m1m2.py::TestPortfolioAdversarialChallenger::test_feature_extractor_zero_game_mutation PASSED [80%]
tests/test_challenger_m1m2.py::TestCISeedExactnessChallenger::test_multi_seed_repeatability[seeds 10,42,99,123,205,275,500,999] PASSED [100%]

======================= 40 passed in 210.02s (0:03:30) ========================
```

### 1.2 Farm-Off Exactness Invariant
Tested across 20 distinct seeds (seeds 0 through 19) comparing `HeuristicV9()` and `HeuristicV10(params={"farm_clear_threshold": 1.0})` step-by-step:
- At every single game step, `g9.state == g10.state`, `g9.ante == g10.ante`, `g9.chips_scored == g10.chips_scored`, `g9.dollars == g10.dollars`, and `pol9.decide(g9) == pol10.decide(g10)` (verbatim matching action dictionary: `type`, `cards`, `target_cards`, shop purchases, rerolls).
- Tested `farm_clear_threshold` values of `1.0`, `1.5`, and `2.0` on full rollouts; all produced byte-identical results to V9 baseline.

### 1.3 Pace Rule Boundary Invariants
In `vendor/balatro-rl/balatro_sim/agent_v10.py` (`_tier1_survive`, lines 1725–1729):
```python
    if (V10_PARAMS.get("ante1_pace_rule", False) and game.ante == 1
            and V10_PARAMS["farm_clear_threshold"] < 1.0):
        pace = (target / max(1, game.hands_left)) * V10_PARAMS.get("ante1_pace_mult", 1.0)
        if best_score >= pace:
            return {"type": "play", "cards": list(best_combo)}
```
- **Threshold Boundary**: At Ante 1 Small Blind (Target 300, Hands 4, Pace 75.0):
  - Score 74 (< 75.0) -> Discards (does not trigger pace rule).
  - Score 75 (== 75.0) -> Plays immediately.
  - Score 76 (> 75.0) -> Plays immediately.
- **Division by Zero Protection**: When `hands_left = 0`, `max(1, 0) == 1` safely evaluates without exception.
- **Hands Left = 1**: Pace equals remaining target; plays best hand safely.
- **Discards Left = 0**: Bypasses discard logic and plays best combo.
- **Target = 0 / Cleared**: Triggers immediate clear play.
- **Target = Large (100M)**: Pace evaluates to 25M, below-pace hands discard normally to seek upgrades.
- **Ante Scope Gate**: Tested at Ante 2 (Target 600, Hands 4); pace rule does not fire, standard discard logic executes.
- **Fatal Seeds 205 & 275**: Verified that both seeds clear Ante 1 Small Blind deterministically under `HeuristicV10()`.

### 1.4 Portfolio Classification & Feature Extractor Robustness (`tools/portfolio.py`)
- **Catalogue Completeness**: All 150 jokers in `shop.py:JOKER_CATALOGUE` and `tools/joker_spec.json` return a 6-boolean classification dictionary without error.
- **Alias Equivalence**: All 18 aliases in `_CANONICAL_JOKER_ALIASES` evaluate identically to their canonical counterparts.
- **Adversarial Resilience**: Malformed/unknown keys (`"j_unknown_fake"`, `""`, `"xyz"`) return all `False` safely.
- **Extreme State Features**: 42 numeric features extracted under extreme boundary inputs (negative dollars, 0 deck size, 0 hands, extreme hand levels, 100M target) are 100% finite `float` with zero `NaN` or `Inf`.
- **Zero Mutation Guarantee**: Executed `extract_game_features` 50 consecutive times on a live game instance; verified zero modification to deck order, hand, money, or game state.

### 1.5 Verification Suite Runs
1. `python -m pytest vendor/balatro-rl/tests/test_seed_exactness.py -m ci_gate -v`: **4 passed in 4.71s**.
2. `python -m pytest tests/test_portfolio.py tests/test_e2e_v10_requirements.py -v`: **65 passed in 49.60s**.
3. `python tools/audit_jokers_static.py`: **GATES: CLEAN** (DUPES 0, DEAD 0, STUBS 0, GAPS 0, TYPE 0, SIG 0, STATE 0, NOSCAN 0).
4. `python tools/audit_consumables_static.py`: **GATES: CLEAN**.
5. `python tools/audit_bosses_static.py`: **GATES: CLEAN**.
6. `python tools/audit_tags_static.py`: **GATES: CLEAN**.

---

## 2. Logic Chain

1. **Farm-off Fast Path**: `_v10_decide_hand` routes directly to `_tier1_survive` when `farm_clear_threshold >= 1.0`. All internal V10 heuristic branches (`ante1_pace_rule`, `ante1_good_hand`, `two_hand`) check `farm_clear_threshold < 1.0`. Consequently, setting `farm_clear_threshold >= 1.0` deactivates all V10 deviations and produces identical decisions to V9 across all game states.
2. **Pace Budget Safety**: The pace formula `(target / max(1, game.hands_left)) * pace_mult` is mathematically bounded. `max(1, game.hands_left)` prevents division by zero. The condition `game.ante == 1` strictly confines the pace heuristic to Ante 1 where early structural discard burning is fatal, without disrupting Ante 2+ scaling strategy.
3. **RNG Purity & Invariants**: Feature extraction only performs read-only inspection of game attributes. It does not touch `game.random`, `game.deck_order`, or any internal generator. The seed exactness gate remains 100% stable.

---

## 3. Caveats

No caveats. All boundary and cross-feature requirements have been validated empirically with tests.

---

## 4. Conclusion

**Verdict: `APPROVE`**

Milestones 1 and 2 meet all specification requirements, integrity rules, and acceptance criteria:
- **M1 (Ante-1 Pace Rule)**: Successfully breaks the Ante 1 discard-burning ceiling, clears fatal seeds 205 and 275, maintains strict Ante 1 scoping, and preserves byte-exact baseline parity when farming is disabled.
- **M2 (Portfolio & Feature Extractor)**: Accurately categorizes all 150 canonical jokers into 6 strategic roles, handles all aliases, produces 42 finite numeric features under all boundary conditions, and guarantees zero game state mutation and zero RNG consumption.

---

## 5. Verification Method

To independently execute and verify the empirical challenge suite:

```powershell
# 1. Run Challenger Test Suite (40 tests)
python -m pytest tests/test_challenger_m1m2.py -v

# 2. Run Portfolio and E2E Requirements Tests (65 tests)
python -m pytest tests/test_portfolio.py tests/test_e2e_v10_requirements.py -v

# 3. Run CI Seed Exactness Gate
python -m pytest vendor/balatro-rl/tests/test_seed_exactness.py -m ci_gate -v

# 4. Run Static Audits
python tools/audit_jokers_static.py
python tools/audit_consumables_static.py
python tools/audit_bosses_static.py
python tools/audit_tags_static.py
```
