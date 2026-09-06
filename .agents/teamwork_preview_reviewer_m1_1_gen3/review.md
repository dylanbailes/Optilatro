# Milestone M1 Review: Correctness, Human-Fairness & Adversarial Challenge Report

**Reviewer**: Reviewer 1 (Correctness & Human-Fairness Reviewer)  
**Working Directory**: `D:/Optilatro/.agents/teamwork_preview_reviewer_m1_1_gen3`  
**Date**: 2026-09-04  
**Target Code**: `vendor/balatro-rl/balatro_sim/agent_v10.py`, `vendor/balatro-rl/tests/test_scaling_acceleration.py`

---

## 1. Executive Summary

**Verdict**: **APPROVE**  
**Integrity Status**: CLEAN — Zero integrity violations detected.  
**Human-Fairness Guarantee**: FULLY COMPLIANT — Zero draw order peeking, zero future RNG consumption, zero live game mutation during evaluation.  
**Baseline Compatibility**: FULLY PRESERVED — `agent_v9.py` baseline is untouched, and `TestFarmOffReproducesV9::test_farm_off_matches_v9` passes byte-identically.  
**Test Suite Verification**: 1,621 passed, 3 skipped, 4 deselected in 254.85s. All 4 static audits CLEAN. CI seed exactness gate 4/4 PASSED.

---

## 2. Requirement Verification & Findings

### R1. Late-Game Capital Deployment & Urgent Rerolls
- **Forecasting & Boss Target Alignment**:
  - `_forecast_round_score(game, ref)` computes expected round scoring output based on typical/reach scores and base hands discounted for variance (`* 0.85`).
  - `_ante_boss_target(game)` tracks upcoming boss chips requirements (handling `bl_wall` and `bl_violet` scaling multipliers).
- **Adaptive Interest Floor Relaxation**:
  - In `_v10_decide_shop`:
    - Ante 8: `interest_target = 0` and `force_no_save = True` (complete capital liquidation into shop items).
    - Ante 7: `interest_target = 0` if `forecast_score < boss_target * 1.25` (deficit liquidation).
    - Ante 6: `interest_target = min(interest_target, 15)` if lacking xMult (`n_xmult == 0`) or `forecast_score < boss_target`.
- **Urgent Reroll Pacing & Liquidation Accounting**:
  - Late-game reroll limits: Ante 8 cap 10, Ante 7 cap 6, Ante 6 cap 4.
  - Safe capital reservation: requires `capital_after_reroll >= 6`, factoring in worst-joker liquidation value `worst_sell_val` when slots are full (5/5).
  - In `SearchShopV10.decide`: Upon executing a reroll, `self._searched_this_visit = False` is set, properly invalidating the search cache so the newly rolled shop offerings are actively evaluated by the counterfactual shop search.
  - In `_v10_rank_shop_items`: When joker slots are full, `worst_sell` is credited to `eff_allowance`, enabling candidate scoring jokers to be recognized as purchasable via room-making swaps.

### R2. Synergistic Deck Reshaping & Targeted Consumable Flow
- **Tiered Portfolio Target Hand Selection**:
  - `portfolio_target_hand(game)` structures target hand priority using `_HAND_ENGINE_PRIORITY`:
    1. Tier 1: Premier xMult engines (`j_tribe` -> Flush, `j_trio` -> Three of a Kind, `j_duo` -> Pair).
    2. Tier 2: Scaling hand engines (`j_spare_trousers` -> Two Pair, `j_runner` -> Straight).
    3. Tier 3: Suit/chip engines (`j_bloodstone` -> Flush, `j_clever` -> Two Pair, etc.).
    4. Tier 4: Held-in-hand engines (`j_baron` -> High Card).
    5. Fallback: `main_hand_type(game)` / High Card.
- **Deck Reshaping Target Extensions**:
  - `deck_reshape_target` incorporates `j_trio`, `j_duo`, and face-dependent jokers (`j_photograph`, `j_face_joker`, `j_scary_face`, `j_smiley`) targeting `rank_set = {11, 12, 13}`.
- **Dynamic Tarot Synergy Bonuses & Shop Flow**:
  - `_reshape_tarot_bonus` awards value bonuses: Death (+0.22), Strength (+0.10), Hanged Man (+0.05 suit / +0.04 face / +0.03 rank), Justice (+0.16 for Glass synergies), Magician (+0.12 for Lucky synergies).
  - `_v10_tarot_action` directs:
    - `c_death`: duplicates highest-ranking target card onto the weakest non-target card, while protecting engine ranks (Wee 2s, Hack 2-5, Fibonacci 2/3/5/8/14, majority ranks).
    - `c_strength`: promotes cards immediately below target rank (`r == target - 1`) or rank 10 cards to Jacks (11) for face engines.
    - `c_hanged_man`: strictly purges non-engine junk while protecting all active engine cards.
  - `_v10_maybe_use_planet`: in shop, immediately uses held planets to upgrade levels and free consumable slots. In combat, uses if slots are full, matches target hand, matches top plays, or Constellation owned.
  - Consumable pack purchasing respects consumable hand limits, preventing wasted capital when slots are congested.

### R3. Scaling Joker Acceleration During Safe Blinds
- **Catalogs & Banned Boss Blinds**:
  - `SCALING_ACCEL_KEYS`: `{"j_green_joker", "j_ride_the_bus", "j_supernova", "j_wee", "j_square_joker", "j_spare_trousers"}`.
  - `SCALING_BANNED_BOSSES`: `{"bl_needle", "bl_mouth", "bl_eye", "bl_grim", "bl_hook", "bl_tooth", "bl_pillar", "bl_psychic"}`.
- **Safety Preconditions & Pacing Architecture**:
  - Minimum `game.hands_left >= 2` (never risks final hand).
  - Target chips remaining > 0.
  - Boss key not in `SCALING_BANNED_BOSSES`.
  - Strict Ante 1 isolation: requires `p_clear >= 0.99`.
- **Tier S1 Deterministic Knockout Reservation**:
  - Discovers minimal-card clearing plays `k_combo` from `clearing_plays`.
  - Searches combinations among disjoint cards `non_k_indices = [i for i in range(len(hand)) if i not in set(k_combo)]`.
  - Guarantees 100% deterministic survival: the clearing combo `k_combo` remains completely untouched in hand for the subsequent hand.
- **Scaling Value Optimization**:
  - `j_ride_the_bus`: strictly verifies `not _has_scoring_face(...)` (rejects any combination where scored cards contain face cards).
  - `j_wee`: awards +100 per rank 2 card; automatically orders 2s to index 0 for double retriggering when `j_hanging_chad` is owned.
  - `j_square_joker`: awards +40 for 4-scoring-card hands.
  - `j_spare_trousers`: awards +50 for Two Pair / Full House.
  - `j_green_joker`: suppresses discards in `_tier1_survive` when blind is safe (`p_clear >= 0.98` / `0.99` in Ante 1), playing safe hands instead of discarding to bank +1 Mult and avoid the -1 Mult penalty.
  - `j_supernova`: awards +10 for incremental hand increments.

---

## 3. Human-Fairness & Isolation Verification

| Check | Requirement | Verification Method | Result |
|---|---|---|---|
| **Draw Order Peeking** | Zero peek at future draw order in default policies | Code inspection of `agent_v10.py` and `test_agent_v10.py`. Only composition multisets (`_value_multiset`) and card properties inspected. | **PASS** |
| **RNG Stream Isolation** | Zero consumption of live game RNG during evaluation | Inspection of all RNG references; throwaway seed-0 RNG used only for Monte Carlo sampling. Ran `test_seed_exactness.py -m ci_gate`. | **PASS** (4/4 passed) |
| **Live Game Mutation** | Zero mutation of live game state during scoring/search | Inspected `formulate_counterfactual_state` and `_find_scaling_action`. Pure read-only feature extraction and scoring. | **PASS** |
| **Baseline Preservation** | `agent_v9.py` preserved as frozen baseline | Verified `TestFarmOffReproducesV9::test_farm_off_matches_v9` reproduces V9 byte-identically when `farm_clear_threshold = 1.0`. | **PASS** |

---

## 4. Adversarial Review & Stress-Testing

### Challenge 1: Ride the Bus Reset Risk under Scaling Acceleration
- **Assumption Challenged**: Can `_find_scaling_action` or `_tier1_survive` accidentally play a face card that resets Ride the Bus mult back to +0?
- **Attack Scenario**: Player holds Ride the Bus and plays a multi-card hand containing a Jack, Queen, or King.
- **Mitigation & Verification**:
  - `_has_scoring_face(hand, combo)` evaluates the exact played combination using `evaluate_hand(cards)[1]` and checks `any(c.is_face_card for c in scoring_cards if not c.debuffed)`.
  - In `_find_scaling_action`: combinations with scoring face cards are discarded immediately (`if has_bus and any(...): continue`).
  - In `_tier1_survive`: safe clearing filters out any plays scoring face cards (`safe_clearing = [pl for pl in clearing if not _has_scoring_face(...)]`).
  - Verified by `test_ride_the_bus_never_plays_scoring_face`.
  - **Verdict**: RESILIENT.

### Challenge 2: Accidental Death on Blind Misses During Scaling
- **Assumption Challenged**: Does banking scaling triggers in Tier S1 or S2 ever cause the agent to fall short of clearing the blind?
- **Attack Scenario**: Low draw quality after a scaling hand burns a hand counter.
- **Mitigation & Verification**:
  - In Tier S1: The clearing combo $K$ is retained *completely in hand* ($C_{\text{scale}} \cap K = \emptyset$). Because no cards from $K$ are played, $K$ remains held in hand on the very next turn with 100% certainty, guaranteeing an immediate knockout without needing any draws.
  - In Tier S2: Probabilistic threshold requires $P(\text{clear}) \ge 0.98$ ($0.99$ in Ante 1) AND the top scoring hand can clear the remaining deficit within remaining hands with a 25% safety margin (`best_score * (hands_left - 1) >= target * 1.25`).
  - Strict suppression on last hand (`hands_left < 2`).
  - Strict suppression on all 8 dangerous boss blinds (`bl_needle`, `bl_mouth`, `bl_eye`, `bl_grim`, `bl_hook`, `bl_tooth`, `bl_pillar`, `bl_psychic`).
  - **Verdict**: RESILIENT.

### Challenge 3: Inadvertent Full-Slot Joker Destruction
- **Assumption Challenged**: In full-slot joker liquidation for R1 rerolls, could the agent liquidate a vital scaling or engine joker?
- **Attack Scenario**: Agent has 5 jokers in Ante 5 and needs cash for rerolling.
- **Mitigation & Verification**:
  - `SearchShopV10._search_shop` protects economy jokers before Ante 6, protects key retriggers (`j_hanging_chad`, `j_dusk`, `j_mime`, `j_sock_and_buskin`), protects premier xMult anchors (`j_cavendish`, `j_ramen`), and strictly protects the sole xMult, sole chips, sole flat mult, and combat scaling jokers before Ante 7.
  - `_joker_sell_value` safely falls back to standard half-cost if `sell_value` is missing.
  - **Verdict**: RESILIENT.

---

## 5. Test Suite Execution Log

| Command | Status | Output Details |
|---|---|---|
| `python -m pytest vendor/balatro-rl/tests/test_scaling_acceleration.py -v` | **PASSED** | 9 passed in 0.29s |
| `python -m pytest vendor/balatro-rl/tests/test_agent_v10.py -v` | **PASSED** | 50 passed in 29.93s |
| `python -m pytest vendor/balatro-rl/tests/test_seed_exactness.py -m ci_gate -v` | **PASSED** | 4 passed in 7.34s |
| `python tools/audit_jokers_static.py` | **PASSED** | GATES: CLEAN (0 dupes, 0 stubs, 0 gaps) |
| `python tools/audit_consumables_static.py` | **PASSED** | GATES: CLEAN (0 errors, 0 dead) |
| `python tools/audit_bosses_static.py` | **PASSED** | GATES: CLEAN (0 errors, 0 wired) |
| `python tools/audit_tags_static.py` | **PASSED** | GATES: CLEAN (0 errors, 0 wired) |
| `python -m pytest vendor/balatro-rl/tests vendor/balatro-rl/balatro_sim/tests -q` | **PASSED** | 1,621 passed, 3 skipped, 4 deselected in 254.85s |

---

## 6. Conclusion

The implementation of Milestone M1 across R1, R2, and R3 in `vendor/balatro-rl/balatro_sim/agent_v10.py` and `vendor/balatro-rl/tests/test_scaling_acceleration.py` is verified to be correct, mathematically sound, human-fair, robustly tested, and fully aligned with all acceptance criteria.
