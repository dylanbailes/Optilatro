# Handoff Report: Requirement R1 (Late-Game Capital Deployment & Urgent Rerolls)

**Role:** Survey Explorer 1 (R1 Focus)  
**Date:** 2026-09-04  
**Working Directory:** `D:/Optilatro/.agents/teamwork_preview_explorer_survey_1_gen3`  
**Handoff Type:** Hard (Survey/Exploration Complete)

---

## 1. Observation

1. **Benchmark Telemetry on Seeds 0–299**:
   - File: `vendor/balatro-rl/results/bench_0_299_search_shop_v10.json`
   - Baseline results: 26 wins (8.67%), 11 Ante-1 deaths (3.67%).
   - Late-game mortality: **88 out of 300 runs (29.3%) died in Antes 6–8** (Ante 6: 38 deaths, Ante 7: 33 deaths, Ante 8: 17 deaths).
   - Capital hoarding at death:
     - Seed 229 died in Ante 8 Boss with **$28** holding `['j_photograph', 'j_hanging_chad', 'j_gros_michel', 'j_cavendish', 'j_smiley']`.
     - Seed 215 died in Ante 7 Boss with **$27** holding `['j_cavendish', 'j_erosion', 'j_constellation', 'j_stuntman', 'j_swashbuckler']`.
     - Seed 61 died in Ante 8 Boss with **$24** holding `['j_photograph', 'j_erosion', 'j_family', 'j_seeing_double', 'j_ice_cream']`.
     - Seeds 137, 197, 173, 195, 283 all died holding **$23**.
     - Seed 286 died in Ante 7 holding **three economy jokers** (`j_egg`, `j_todo_list`, `j_ticket`).
     - Seed 195 died in Ante 7 Boss holding **two economy jokers** (`j_faceless`, `j_delayed_grat`).

2. **Absence of Round Scoring Forecast in `agent_v10.py`**:
   - `vendor/balatro-rl/balatro_sim/agent_v10.py` line 71 reuses `forecast_beatable` from `agent_v9.py`.
   - `vendor/balatro-rl/balatro_sim/agent_v9.py` lines 2216–2227:
     ```python
     def forecast_beatable(game, margin: float, ref=None) -> bool:
         if ref is None:
             ref = reference_hand(game)
         ceiling, typical, reach, base_c, base_t = ref
         expected = reach * base_c + (1.0 - reach) * base_t
         return expected >= next_blind_target(game) * margin
     ```
   - Only scores a **single hand** and checks against only `next_blind_target(game)` (immediate blind). In Ante 6 Boss and Ante 7 Small Blind, `next_blind_target` is 35k; a build scoring 42k triggers `save_mode = True`, falsely believing the build is safe from the 70k/140k Boss and 100k/300k Ante 8 Boss.

3. **Shop Capital Hoarding & Hard Reroll Cap**:
   - `vendor/balatro-rl/balatro_sim/agent_v10.py` lines 1424–1434:
     ```python
     reroll_cost = max(0, game.reroll_cost - game.reroll_discount)
     eff_max = p["reroll_max"] # = 2
     if (not save_mode
             and game.dollars >= max(reroll_cost, p["reroll_min_money"])
             and rerolls_used < eff_max):
         return {"type": "reroll"}

     return {"type": "leave_shop"}
     ```
   - Rerolls in Antes 6–8 are hard-capped at 2 (`p["reroll_max"] = 2`). Even with $50+, the agent rerolls twice and exits the shop.

4. **`SearchShopV10` Post-Reroll Blindness**:
   - `vendor/balatro-rl/balatro_sim/agent_v10.py` lines 2989–2995:
     ```python
     if (self._searches_done < self._search_shops
             and not self._searched_this_visit):
         self._searched_this_visit = True
         act = (self._search_shop_rollout(game) if self._lookahead
                else self._search_shop(game))
     ```
   - `self._searched_this_visit` is set to `True` on the very first shop interaction. If a reroll happens, subsequent decisions in that shop visit bypass `_search_shop` entirely, so counterfactual swap evaluations never inspect the freshly rerolled shop items.

5. **Full-Slot Item Pruning Bug in `_v10_rank_shop_items`**:
   - `vendor/balatro-rl/balatro_sim/agent_v10.py` lines 1264–1270:
     ```python
     allowance = game.dollars - reserve
     for i, item in enumerate(game.current_shop):
         if item.sold:
             continue
         price = item.discounted_price(game.shop_discount)
         if price > allowance:
             continue
     ```
   - When slots are full, if `price > game.dollars`, the item is skipped before line 1308 (`elif not has_room:`) can evaluate whether selling the worst joker would afford it.

6. **Exact Blind Targets (`vendor/balatro-rl/balatro_sim/constants.py`, line 58)**:
   - Ante 6: Small 20k, Big 30k, Boss 40k (Wall 80k, Needle 20k).
   - Ante 7: Small 35k, Big 52.5k, Boss 70k (Wall 140k, Needle 35k).
   - Ante 8: Small 50k, Big 75k, Boss 100k (Violet Vessel 300k).

---

## 2. Logic Chain

1. **Premise**: To break the 10.0% win rate threshold (>= 30 wins / 300), the agent must convert 4 to 10 of the 88 late-game deaths in Antes 6–8 into wins.
2. **Analysis of Late-Game Deaths**: Telemetry proves agents frequently die in Ante 7 and Ante 8 holding $20 to $28 in cash and holding dead economy jokers.
3. **Root Cause 1 (Interest Floor)**: The agent treats $25 interest preservation as invariant even in Ante 8 (where interest earned has zero post-game value) and Ante 7 (where dying loses 100% of runs).
4. **Root Cause 2 (Reroll Cap)**: Hardcoding `eff_max = 2` prevents spending excess capital in late game, leaving large bankrolls unutilized.
5. **Root Cause 3 (Forecast Blindness)**: Using single-hand `forecast_beatable` against only the immediate blind blinds the agent to upcoming 70k–300k Boss targets, prematurely engaging `save_mode` and blocking rerolls.
6. **Root Cause 4 (Execution Gaps)**: `SearchShopV10` skips counterfactual swaps after rerolls, and `_v10_rank_shop_items` drops full-slot candidate items whose price exceeds pocket cash before factoring in joker sell values.
7. **Conclusion**: Introducing a multi-hand round scoring forecast (`_forecast_round_score`), dynamically relaxing the $25 interest floor in Antes 6–8 when in scoring deficit (and dropping to $0 in Ante 8), increasing rerolls with a purchase reserve buffer, and fixing post-reroll swap execution will directly allow agents to acquire premier xMult finishers (Cavendish, Duo, Trio, Baseball, Acrobat, etc.) and clear Ante 8.

---

## 3. Concrete Code Locations & Recommendations

All edits must be confined to `vendor/balatro-rl/balatro_sim/agent_v10.py`:

1. **Implement `_forecast_round_score(game, ref=None) -> float`** (co-located around line 2200):
   - Compute `single_hand_ev = reach * base_c + (1.0 - reach) * base_t` from `ref = reference_hand(game)`.
   - Multiply by `game.base_hands` (default 4) and apply a conservative 0.85 discount for discard variance.
   - Compare against `_ante_boss_target(game)` (Ante 6: 40k/80k, Ante 7: 70k/140k, Ante 8: 100k/300k).

2. **Implement Dynamic Interest Floor & Save Mode Relaxation** (in `_v10_decide_shop`):
   - In Ante 8: `interest_target = 0`, `save_mode = False`.
   - In Ante 7: If `_forecast_round_score(game) < boss_target * 1.25`, `interest_target = 0`, `save_mode = False`.
   - In Ante 6: If `n_xmult == 0` or `forecast < boss_target`, `interest_target = 15`.

3. **Implement Urgent Reroll Pacing with Purchase Buffer** (in `_v10_decide_shop`):
   - Allow `eff_max` up to 10 in Ante 8, 6 in Ante 7 (urgent), 4 in Ante 6 (urgent).
   - Check purchase reserve:
     `dollars_after_reroll = game.dollars - reroll_cost + (worst_joker_sell_val if slots_full else 0)`
     Only reroll if `dollars_after_reroll >= 6` (guaranteeing ability to buy Cavendish or premier xMult).

4. **Fix Full-Slot Allowance in `_v10_rank_shop_items`** (around line 1269):
   - Replace `if price > allowance: continue` with:
     ```python
     eff_allowance = allowance + (worst_sell if len(game.jokers) >= game.joker_slots else 0)
     if price > eff_allowance:
         continue
     ```

5. **Enable Post-Reroll Search in `SearchShopV10.decide`** (around line 3007):
   - When a reroll is executed, reset `self._searched_this_visit = False` so the next shop action allows `_search_shop` to evaluate counterfactual swaps on the newly rolled items.

6. **Include All Premier Finishers in Catalog**:
   - Add `"j_blueprint"`, `"j_brainstorm"`, `"j_baron"`, `"j_ancient"` to `RELIABLE_XMULT_JOKERS` and `HIGH_LEVERAGE_SCORING_JOKERS`.

---

## 4. Caveats

1. **Do not over-reroll in Ante 6**: If an agent starts rerolling aggressively in Ante 6 without hitting an xMult joker, it could bankrupt its economy heading into Ante 7. The relaxation in Ante 6 must strictly gate on lacking xMult (`n_xmult == 0`) and maintain at least $15 bankroll.
2. **Ante 1-2 Isolation**: Ensure none of the late-game capital deployment logic touches Ante 1–2 behavior, protecting the < 4.0% Ante-1 mortality requirement.
3. **No RNG Peeking**: All decisions must rely purely on visible state. Never look ahead into future shop draws.

---

## 5. Verification Method

1. **Unit Test Suite**:
   ```bash
   python -m pytest vendor/balatro-rl/tests vendor/balatro-rl/balatro_sim/tests -q
   ```
   All 1,600+ tests must pass.

2. **CI Seed Exactness Gate**:
   ```bash
   python -m pytest vendor/balatro-rl/tests/test_seed_exactness.py -m ci_gate -v
   ```
   Must remain 4/4 passing.

3. **Static Audits**:
   ```bash
   python tools/audit_jokers_static.py
   python tools/audit_consumables_static.py
   python tools/audit_bosses_static.py
   python tools/audit_tags_static.py
   ```
   All 4 gates must remain CLEAN.

4. **Benchmark Verification**:
   Run paired A/B evaluation on Seeds 0–299 against baseline `bench_0_299_search_shop_v10.json` (26W / 11D):
   Verify that win count increases to $\ge 30$ ($10.0\%+$) and Ante 1 deaths remain $< 12$ ($< 4.0\%$).
