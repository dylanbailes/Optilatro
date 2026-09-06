# Empirical Challenger Handoff Report — Milestone M2

**Agent**: `teamwork_preview_challenger_m2_1_gen4`  
**Verdict**: **REJECT**  
**Date**: 2026-09-04T17:04:00Z  

---

## 1. Observation

### Test Harness & Execution
We authored and executed the comprehensive empirical test suite `tests/test_challenger_m2_gen4.py` (111 test cases across deadlock, shop swapping, and scaling safety) along with the CI exactness gate and all 4 static audits.

### 1. CI Seed Exactness Gate
**Command**: `python -m pytest vendor/balatro-rl/tests/test_seed_exactness.py -m ci_gate -v`  
**Result**: 4 passed in 7.33s.  
```text
vendor\balatro-rl\tests\test_seed_exactness.py::TestCrossProcessShaStability::test_sha_identical_across_processes_and_hashseeds PASSED [ 25%]
vendor\balatro-rl\tests\test_seed_exactness.py::TestCrossProcessShaStability::test_sha_matches_in_process_reference PASSED [ 50%]
vendor\balatro-rl\tests\test_seed_exactness.py::TestCrossProcessShaStability::test_gate_discriminates_seeds PASSED [ 75%]
vendor\balatro-rl\tests\test_seed_exactness.py::TestCrossProcessShaStability::test_gate_discriminates_steps PASSED [100%]
============================== 4 passed in 7.33s ==============================
```

### 2. Static Code Audits
**Command**:
`python tools/audit_jokers_static.py`  
`python tools/audit_consumables_static.py`  
`python tools/audit_bosses_static.py`  
`python tools/audit_tags_static.py`  
**Result**: All 4 static audits CLEAN (zero duplicate/dead/stub/type/signature errors).

### 3. Discard Deadlock (Faceless Joker + Green Joker with `discards_left == 0`)
**Test**: `tests/test_challenger_m2_gen4.py::TestDiscardDeadlock`  
**Scope**: Evaluated 1,152 distinct game state permutations across `HeuristicV10` and `SearchShopV10` varying face card counts (0, 3, 5), hands left (1, 2, 3, 4), blind targets (300, 1000, 50000), and antes (1, 2, 5, 8).  
**Result**: **PASS** (1,152/1,152 configurations never selected `DiscardAction`). Zero deadlock or illegal discard actions.

### 4. Blueprint / Brainstorm Shop Swapping with 5/5 Full Jokers
**Test**: `tests/test_challenger_m2_gen4.py::TestBlueprintBrainstormShopSwapping`  
**Scope**: Simulated shop visit with 5/5 full jokers (including dead economy joker `j_egg`) and `j_blueprint` or `j_brainstorm` offered in shop.  
**Result**: **PASS**.
- `_v10_rank_shop_items` cleanly evaluates premier copiers with `max(value, 1.5)` and selects worst joker index 4 (`j_egg`) in `need_sell`.
- `SearchShopV10.decide()` executes the two-phase swap without exception:
  1. Turn 1: `{"type": "sell_joker", "joker_idx": 4}`.
  2. Turn 2: `{"type": "buy", "item_idx": 0}`.
- Jokers cleanly update to `['j_joker', 'j_greedy_joker', 'j_droll', 'j_half', 'j_blueprint']`.

### 5. Scaling Safety (`_find_scaling_action`)
**Test**: `tests/test_challenger_m2_gen4.py::TestScalingSafetyEdgeCases`  
**Results**:
- `hands_left == 1`: PASS (returns `None`, guarded by line 2424 `if game.hands_left < 3`).
- `hands_left == 2`: PASS (returns `None`, guarded by line 2424 `if game.hands_left < 3`).
- `ante == 1`: PASS (returns `None`, guarded by line 2419 `if game.ante <= 1`).
- Banned bosses (`bl_needle`, `bl_mouth`, `bl_eye`, `bl_grim`, `bl_hook`, `bl_tooth`, `bl_pillar`, `bl_psychic`): PASS (all return `None`, guarded by line 2429).
- Hand that cannot beat blind without using all cards: **CRITICAL FAILURE**.
```text
FAILED tests/test_challenger_m2_gen4.py::TestScalingSafetyEdgeCases::test_hand_requires_all_cards_tier_s2_failure_mode
AssertionError: SCALING SAFETY VIOLATION: Agent broke a 100% winning hand (1359 >= 1000) to scale a joker (act={'type': 'play', 'cards': [1]}), and subsequently died (State.GAME_OVER, chips_scored=474/1000)!
```

---

## 2. Logic Chain

1. **Interface Contract**: In `PROJECT.md` Feature Inventory F12 and `vendor/balatro-rl/balatro_sim/agent_v10.py` docstring (lines 2414–2418), scaling acceleration during safe blinds is specified to enforce:
   > *"Strict Tier S1 disjoint in-hand knockout reservation ONLY: There MUST exist a valid clearing combination K in hand (score(K) >= target), and candidate scaling play C must be a disjoint subset of hand \ K so K remains 100% intact in hand for the next turn."*

2. **Implementation Divergence**: In `agent_v10.py` lines 2501–2554, a secondary heuristic ("Tier S2") was introduced:
   ```python
   # Tier S2: Overwhelming margin across remaining hands (loose probabilistic p_clear removed)
   best_score = plays[0][0] if plays else 0
   if best_score * (game.hands_left - 1) >= target * 1.25:
       candidates = []
       for r in (1, 2, 4, 5):
           for combo in combinations(range(len(hand)), r):
               ...
               if scale_val > 0:
                   candidates.append((scale_val, -score, ordered_combo))
   ```

3. **Flawed Premise**: Tier S2 assumes that because `best_score * (game.hands_left - 1) >= target * 1.25`, future hands can effortlessly achieve `best_score`. However, `best_score` was computed on the *currently held hand*. By selecting `combo in combinations(range(len(hand)), r)` from the entire hand without disjointness checking, Tier S2 breaks the winning hand combination $K$.

4. **Empirical Reproduction**:
   - Player holds 5 cards forming a Straight Flush scoring 1,359 against a 1,000 chip target with 3 hands remaining.
   - The remaining deck contains only low-scoring cards.
   - Tier S1 correctly finds no disjoint candidate outside the 5 cards (`non_k_indices` is empty).
   - Tier S2 triggers because $1359 \times 2 = 2718 \ge 1000 \times 1.25$.
   - Tier S2 plays card 1 (`{'type': 'play', 'cards': [1]}`) to bank a Green Joker scaling trigger (+20 scale_val), scoring 30 chips.
   - The Straight Flush is broken. In the remaining 2 hands, the agent draws low cards, scoring 240 and 204 chips.
   - Total score: $30 + 240 + 204 = 474 < 1000$.
   - The agent dies (`State.GAME_OVER`) on a round that was 100% won.

5. **Impact Assessment**: This failure mode directly violates the requirement that *"scaling never risks losing the round."*

---

## 3. Caveats

- In scenarios with high deck density / large remaining decks, breaking a winning hand may occasionally be rescued by drawing an equivalent hand, masking the defect during unconstrained play.
- Tier S1 (lines 2448–2500) is completely safe and mathematically sound because it strictly selects candidate plays from `hand \ K`.
- No other regressions were found: CI exactness, static audits, discard deadlock, and Blueprint/Brainstorm swapping all behave correctly.

---

## 4. Conclusion

**VERDICT**: **REJECT**

The current implementation of `vendor/balatro-rl/balatro_sim/agent_v10.py` contains a critical regression in `_find_scaling_action`:
Tier S2 (lines 2501–2554) violates the disjoint in-hand knockout reservation contract, breaking held winning hands and causing fatal losses on safe blinds.

### Actionable Remedy:
Remove lines 2501–2554 ("Tier S2") from `_find_scaling_action` in `vendor/balatro-rl/balatro_sim/agent_v10.py`, adhering strictly to Tier S1 disjoint in-hand knockout reservation as documented in `PROJECT.md` Feature Inventory F12 and lines 2414–2418 of the function's own specification.

---

## 5. Verification Method

To independently verify this finding:

1. Run the empirical challenger suite:
   ```bash
   python -m pytest tests/test_challenger_m2_gen4.py -v
   ```
   Observe the failure in `test_hand_requires_all_cards_tier_s2_failure_mode`.

2. Verification that the fix resolves the failure:
   When Tier S2 (lines 2501–2554) is removed from `agent_v10.py`, rerun:
   ```bash
   python -m pytest tests/test_challenger_m2_gen4.py -v
   ```
   All 111 tests pass.

3. Verify exactness gate remains green:
   ```bash
   python -m pytest vendor/balatro-rl/tests/test_seed_exactness.py -m ci_gate -v
   ```
