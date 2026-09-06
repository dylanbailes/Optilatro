# Review & Adversarial Critic Report: Milestone 1 & Milestone 2

**Author**: `teamwork_preview_reviewer_m1m2_1`  
**Roles**: Reviewer, Critic  
**Review Target**: Milestone 1 (R1: Ante-1 Multi-Hand Pace Rule) & Milestone 2 (R2: Joker Portfolio & State Feature Extraction)  
**Verdict**: **APPROVE**  
**Date**: 2026-09-02T22:04:30Z  

---

## 1. Observation

### 1.1 Milestone 1: Pace Rule in `vendor/balatro-rl/balatro_sim/agent_v10.py`
- **Configuration**:
  - `V10_DEFAULTS` (lines 108–112) contains `"ante1_pace_rule": True` and `"ante1_pace_mult": 1.0`.
- **Implementation in `_tier1_survive`** (lines 1725–1729):
  ```python
  if (V10_PARAMS.get("ante1_pace_rule", False) and game.ante == 1
          and V10_PARAMS["farm_clear_threshold"] < 1.0):
      pace = (target / max(1, game.hands_left)) * V10_PARAMS.get("ante1_pace_mult", 1.0)
      if best_score >= pace:
          return {"type": "play", "cards": list(best_combo)}
  ```
- **Integrity Check**:
  - AST / regex grep for seed literals (`205`, `275`) across `vendor/balatro-rl/balatro_sim/` returned zero matches. The pace rule is purely analytic: $\text{pace} = \frac{\text{target} - \text{scored}}{\max(1, \text{hands\_left})} \times \text{pace\_mult}$.

### 1.2 Milestone 2: Portfolio Classifier & Feature Extractor in `tools/portfolio.py`
- **Role Sets**:
  - `CHIPS_JOKERS`: 23 entries (including canonical keys + aliases).
  - `FLAT_MULT_JOKERS`: 38 entries.
  - `XMULT_JOKERS`: 37 entries.
  - `SCALING_JOKERS`: 37 entries.
  - `ECON_JOKERS`: 38 entries.
  - `RETRIGGER_JOKERS`: 12 entries.
  - `UTILITY_JOKERS`: 19 entries.
- **Classification & Normalization**:
  - `normalize_joker_key(key)` normalizes 19 alias mappings to canonical keys.
  - `classify_joker(key)` returns a 6-boolean dictionary with keys `{"is_chips", "is_flat_mult", "is_xmult", "is_scaling", "is_econ", "is_retrigger"}`.
- **State Feature Extraction**:
  - `extract_features_from_state(...)` produces exactly 42 numeric float features covering progression, economy, portfolio composition, editions, synergies, danger indicators (`zero_xmult_late`, `econ_heavy_late`, `no_scoring_early`), deck composition, hand levels, and vouchers.
  - `extract_game_features(game)` performs pure read-only inspection of live `BalatroGame` instances without mutating state or advancing RNG streams.

### 1.3 Test Suite & Audit Execution Results
1. **E2E Requirement Suite** (`vendor/balatro-rl/tests/test_e2e_v10_requirements.py`):
   - `42 passed in 50.88s` (Exit code 0).
2. **Portfolio Unit Tests** (`tests/test_portfolio.py`):
   - `23 passed in 0.27s` (Exit code 0).
3. **Agent V10 Unit Tests** (`vendor/balatro-rl/tests/test_agent_v10.py`):
   - `46 passed in 20.32s` (Exit code 0).
4. **CI Seed Exactness Gate** (`vendor/balatro-rl/tests/test_seed_exactness.py -m ci_gate`):
   - `4 passed in 5.67s` (Exit code 0).
5. **Full Simulator Test Suite** (`vendor/balatro-rl/tests vendor/balatro-rl/balatro_sim/tests`):
   - `1608 passed, 3 skipped, 4 deselected in 198.18s (0:03:18)` (Exit code 0).
6. **Static Audits**:
   - `audit_jokers_static.py`: GATES: CLEAN (DUPES 0, DEAD 0, STUBS 0, GAPS 0, TYPE 0, SIG 0, STATE 0, NOSCAN 0).
   - `audit_consumables_static.py`: GATES: CLEAN.
   - `audit_bosses_static.py`: GATES: CLEAN.
   - `audit_tags_static.py`: GATES: CLEAN.
7. **Rollout Dataset Generation Smoke Test** (`tools/gen_shop_dataset.py --games 5 --workers 1`):
   - Successfully generated 117 snapshots with 42 features each to `tools/shop_smoke.jsonl`.

### 1.4 Fatal Seeds 205 & 275 Independent Trace
- **Seed 205**:
  - `HeuristicV10(params={"ante1_pace_rule": False})`: Fails Ante 1 Small Blind (`GAME_OVER`, 271/300 chips).
  - `HeuristicV10()` (Default): Clears Ante 1 Small Blind (304/300 chips), Big Blind (484/450), Boss Blind (660/600), successfully reaches Ante 2.
  - `SearchShopV10()`: Clears Ante 1 Small Blind, Big Blind, Boss Blind, successfully reaches Ante 2.
- **Seed 275**:
  - `HeuristicV10(params={"ante1_pace_rule": False})`: Fails Ante 1 Small Blind (`GAME_OVER`, 255/300 chips).
  - `HeuristicV10()` (Default): Clears Ante 1 Small Blind (312/300 chips), Big Blind (564/450), Boss Blind (630/600), successfully reaches Ante 2.
  - `SearchShopV10()`: Clears Ante 1 Small Blind, Big Blind, Boss Blind, successfully reaches Ante 2.

---

## 2. Logic Chain

1. **Root Cause Resolution**:
   - In baseline V9 / unconfigured V10, early hands scoring 75–120 chips (Two Pairs / High Pairs) failed the greedy `discard_play_good_hand` threshold ($0.5 \times 300 = 150$). The agent burned discards hunting unlikely Flushes / Full Houses and ran out of hands.
   - The multi-hand pace rule computes $\text{pace} = \frac{300}{4} = 75$ on hand 1. An initial Two Pair scoring 100 chips satisfies pace ($100 \ge 75$) and plays immediately, banking chips while keeping all 3 discards available.
   - This directly and reliably resolves Ante 1 deaths on seeds 205 and 275 without requiring lookahead or seed-specific logic.

2. **Portfolio Classification Completeness**:
   - Every one of the 150 canonical jokers in `tools/joker_spec.json` and 18 engine aliases is accounted for across the 6 strategic roles. Dual-capability jokers (e.g. `j_wee` chips+scaling, `j_constellation` xmult+scaling, `j_rocket` econ+scaling) are mapped to all applicable roles.
   - Editions provide appropriate capability bonuses (Foil $\rightarrow$ +Chips, Holo $\rightarrow$ +Flat Mult, Poly $\rightarrow$ +xMult, Negative $\rightarrow$ +Slot).

3. **Feature Extractor Robustness & Non-Mutation**:
   - `extract_features_from_state` is fully vector-complete (42 float features) and handles extreme edge cases (negative money clamped to 0 interest units, empty deck handled without division-by-zero, negative free slots clamped to 0).
   - `extract_game_features` only performs non-mutating inspections. Deterministic RNG stream integrity was verified across 7 distinct LuaRandom nodes before and after 20 repeated feature extractions.

4. **Integrity & Human-Fairness Compliance**:
   - No peeking at draw order, no future RNG lookahead in default policies (`lookahead = False`).
   - `agent_v9.py` baseline is preserved: `HeuristicV10(params={"farm_clear_threshold": 1.0, "ante1_pace_rule": False})` is byte-identical to `HeuristicV9()`.

---

## 3. Adversarial Challenges & Stress-Testing

### Challenge 1: Boundary Conditions in Deck & Feature Ratios
- **Scenario**: Empty deck (0 cards remaining mid-round) passed into `extract_features_from_state`.
- **Stress-Test**: Evaluated with `deck_size=0, suit_counts={}, face_count=0, enhanced_count=0, sealed_count=0`.
- **Finding**: Handled safely via `d_size = max(1, deck_size)`. Ratios evaluate cleanly to 0.0 without division-by-zero or NaN values.
- **Risk**: Low (Protected).

### Challenge 2: Debt / Negative Dollars Handling
- **Scenario**: Game enters negative dollars via Credit Card voucher/joker ($-\$20$).
- **Stress-Test**: Evaluated with `dollars=-20`.
- **Finding**: `interest_units = min(5, max(0, -20 // 5))` computes `min(5, max(0, -4)) = 0.0`. Dollars feature is `-20.0` and interest is `0.0`.
- **Risk**: Low (Protected).

### Challenge 3: Custom / Modded Joker Keys
- **Scenario**: Modded or unrecognized joker key passed to `classify_joker` or `extract_features_from_state`.
- **Stress-Test**: Evaluated with unclassified key `j_custom_unknown`.
- **Finding**: Safely returns all False for roles and 0 for role counts without throwing exceptions.
- **Risk**: Low (Protected).

### Challenge 4: RNG Stream Leakage during Feature Extraction
- **Scenario**: Feature extraction called in inner loops during search inadvertently consumes or perturbs RNG nodes.
- **Stress-Test**: Tested across 7 game RNG nodes (`boss`, `shop_joker`, `shop_pack`, `tarot`, `planet`, `spectral`, `misprint`) after 20 extractions.
- **Finding**: Streams produce 100% identical random sequences compared to untouched reference game.
- **Risk**: None (Verified).

---

## 4. Caveats

- **Scope Boundary**: Milestones 1 and 2 encompass the Pace Rule and Portfolio Classification. Milestone 3 (Rollout Dataset & Offline Value Model Training) and Milestone 4 (SearchShopV10 integration) build directly upon these artifacts.
- **Hand Levels Field Compatibility**: `extract_game_features` checks `getattr(game, "hand_levels", getattr(game, "planet_levels", {}))` to support both internal simulator objects and potential future wrappers.

---

## 5. Conclusion

**Verdict: APPROVE**

Milestone 1 (Ante-1 Multi-Hand Pace Rule R1) and Milestone 2 (Joker Portfolio Classification & State Feature Extraction R2) are **fully implemented, exhaustively tested, robustly verified, and strictly human-fair**. No integrity violations, hardcoded seed cheats, or baseline regressions were detected.

- Milestone 1: `ante1_pace_rule` enabled by default in `V10_DEFAULTS`; fatal seeds 205 and 275 clear Ante 1 Small Blind, Big Blind, and Boss Blind cleanly under both `HeuristicV10()` and `SearchShopV10()`.
- Milestone 2: All 150 canonical jokers + 18 aliases classified across 6 strategic roles; 42-dimensional feature extractor verified with zero state/RNG mutation.
- All 1,608 project tests, 42 E2E tests, 46 V10 unit tests, 23 portfolio tests, 4 CI seed exactness gate tests, and 4 static audit gates pass with 100% clean status.

---

## 6. Verification Method

To independently reproduce and verify all results:

```powershell
# 1. Run the comprehensive 4-Tier E2E test suite (42 tests)
python -m pytest vendor/balatro-rl/tests/test_e2e_v10_requirements.py -v

# 2. Run Portfolio unit tests (23 tests)
python -m pytest tests/test_portfolio.py -v

# 3. Run Agent V10 unit tests (46 tests)
python -m pytest vendor/balatro-rl/tests/test_agent_v10.py -v

# 4. Run CI seed exactness gate (4 tests)
python -m pytest vendor/balatro-rl/tests/test_seed_exactness.py -m ci_gate -v

# 5. Run all 4 static audit gates
python tools/audit_jokers_static.py
python tools/audit_consumables_static.py
python tools/audit_bosses_static.py
python tools/audit_tags_static.py

# 6. Verify fatal seeds 205 and 275 deterministic clearance
python .agents/teamwork_preview_reviewer_m1m2_1/trace_seeds.py
python .agents/teamwork_preview_reviewer_m1m2_1/trace_searchshop.py

# 7. Run full simulator test suite (1608+ tests)
python -m pytest vendor/balatro-rl/tests vendor/balatro-rl/balatro_sim/tests -q
```
