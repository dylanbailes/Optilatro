# Handoff Report — Survey Explorer 3 (R3: Scaling Joker Acceleration During Safe Blinds)

## 1. Observation
1. **Premature Knockout Termination in `_tier1_survive`**:
   In `vendor/balatro-rl/balatro_sim/agent_v10.py` lines 2190–2193:
   ```python
   best_score, best_combo, best_hand_type = plays[0]
   target = game.current_blind.chips_target - game.chips_scored
   if best_score >= target:
       clearing = [pl for pl in plays if pl[0] >= target]
       clearing.sort(key=lambda e: (len(e[1]), e[0]))
       return {"type": "play", "cards": list(clearing[0][1])}
   ```
   When `best_score >= target`, the agent terminates the blind immediately on Hand 1, discarding 2–3 surplus hands and wasting 30–45 permanent scaling opportunities across the run.
2. **Tier 2 Value Farming Omits Scaling Jokers**:
   In `agent_v10.py` lines 2428–2433 and 1646–1670 (`_value_play_combos` and `play_trigger_value`), only Gold cards, Lucky cards, Business card, Rough Gem, Golden Ticket, and To Do List are scored. Scaling jokers (`j_green_joker`, `j_ride_the_bus`, `j_supernova`, `j_wee`, `j_square_joker`) receive value 0.0 and are completely ignored.
3. **Green Joker Discard Penalty**:
   In `vendor/balatro-rl/balatro_sim/jokers/scaling.py` lines 77–78:
   `on_discard` subtracts 1 from mult: `inst.state["mult"] = max(0, inst.state.get("mult", 0) - 1)`.
   In `_tier1_survive` lines 2261–2277, the policy executes discards to seek hands even on safe blinds, needlessly reducing Green Joker mult.
4. **Ride the Bus Face Reset Hazard**:
   In `vendor/balatro-rl/balatro_sim/jokers/scaling.py` lines 301–304:
   `has_face = any(c.is_face_card for c in ctx.scoring_cards if not c.debuffed)`
   `if has_face: inst.state["mult"] = 0`.
   Playing any non-debuffed Jack, Queen, or King among scoring cards completely wipes out accumulated mult.
5. **Square Joker Implementation Quirk**:
   In `vendor/balatro-rl/balatro_sim/jokers/chips.py` line 58:
   `if len(ctx.scoring_cards) == 4: inst.state["chips"] = inst.state.get("chips", 0) + 4`.
   The simulator checks `len(scoring_cards) == 4` rather than `len(all_cards) == 4`. Thus, only Two Pair and Four of a Kind trigger it in the simulator.
6. **Wee Joker Retrigger Potential**:
   In `vendor/balatro-rl/balatro_sim/jokers/misc.py` lines 255–257:
   `if card.rank == 2 and not card.debuffed: inst.state["chips"] += 8`.
   Positioning rank 2 cards in index 0 under Hanging Chad yields 3 triggers (+24 permanent Chips).
7. **Baseline CI Exactness Clean**:
   `vendor/balatro-rl/tests/test_seed_exactness.py -m ci_gate` passes 4/4 clean in 6.67s.

## 2. Logic Chain
1. **Bottleneck Identification**: Optilatro current win rate is 8.67% (26/300) with a target of $\ge 10.0\%$ ($\ge 30/300$). Late-ante losses in Antes 6–8 occur because flat mult and chip baselines are insufficient to reach 100k–200k targets.
2. **Growth Reservoir in Safe Blinds**: In Antes 2–6, Small and Big Blinds are easily cleared in 1 hand. Surviving them with 3 hands unspent yields only $3 round payout, but forfeits +2 to +3 permanent scaling triggers per blind. Across 15 safe blinds, banking 2 extra triggers per blind yields +30 permanent Mult (Green/Bus), +60 Mult (Spare Trousers), or +240 Chips (Wee Joker).
3. **Safety Guarantee via Disjoint In-Hand Knockout Reservation (Tier S1)**:
   If hand $H$ contains a clearing combination $K$ ($score(K) \ge target$), and cards $C \subseteq H \setminus K$ are played, $K$ remains untouched in hand. With $hands\_left \ge 2$, survival on the next turn is 100% deterministic (Risk = 0.0%).
4. **Safety Guarantee via Projection Margin (Tier S2)**:
   If top play $S_{top} \ge target$ and $S_{top} \times (h - 1) \ge target \times 2.0$, playing a single scaling hand leaves abundant clearance headroom.
5. **Boss Blind Risk Elimination**:
   Banning scaling on dangerous bosses (`bl_needle`, `bl_mouth`, `bl_eye`, `bl_grim`, `bl_hook`, `bl_tooth`, `bl_pillar`) prevents all known edge-case failures.
6. **Conclusion**:
   Scaling Joker Acceleration in safe blinds safely compounds portfolio engine strength without risking round failure, directly enabling the win rate expansion to 10.0%+.

## 3. Concrete Code Locations & Recommendations
1. **Target File**: `vendor/balatro-rl/balatro_sim/agent_v10.py`
2. **Locations**:
   - `V10_DEFAULTS` (line 238): Add `scaling_accel_enabled: True`, `scaling_clear_threshold: 0.98`, `scaling_min_hands: 2`, `scaling_safe_blinds_only: True`.
   - Helper definitions (around line 1672): Add `_get_active_scaling_jokers(game)` and `_find_scaling_action(game, hand, plays, scaling_keys, target)`.
   - In-blind decision hook in `_v10_decide_hand(game)` (line 2640): Check scaling conditions and return `scale_act` before calling `_tier1_survive`.
   - Discard suppression in `_tier1_survive` (line 2261): If `j_green_joker` is owned and $P(\text{clear}) \ge 0.98$, prefer low safe plays over discarding.
3. **Simulation Alignment (Optional)**:
   In `vendor/balatro-rl/balatro_sim/jokers/chips.py` line 58:
   Change `if len(ctx.scoring_cards) == 4:` to `if len(ctx.all_cards) == 4 or len(ctx.scoring_cards) == 4:` to align Square Joker with Balatro rules.

## 4. Caveats
1. **Ante 1 Policy Isolation**: In Ante 1, survival (< 4.0% mortality) takes absolute precedence. Scaling acceleration should only activate in Ante 1 if a scoring joker is owned and $P(\text{clear}) \ge 0.99$.
2. **Interest Threshold Economics**: Each remaining hand awards $1 round-end payout. In early game (Antes 1–3), if cash is near an interest boundary ($5, $10, $15, $20, $25), limit scaling plays to 1 per blind to preserve interest compounding.
3. **Boss Blind Debuffs**: In Boss Blinds with card debuffs (e.g. suit debuff bosses `bl_goad`, `bl_club`, `bl_window`, `bl_head`), debuffed cards do not trigger scaling (e.g. debuffed 2 does not trigger Wee Joker).

## 5. Verification Method
1. **Unit & Integration Suite**:
   `python -m pytest vendor/balatro-rl/tests vendor/balatro-rl/balatro_sim/tests -q`
2. **CI Seed Exactness Gate**:
   `python -m pytest vendor/balatro-rl/tests/test_seed_exactness.py -m ci_gate -v`
3. **Static Mechanics Audits**:
   `python tools/audit_jokers_static.py`
   `python tools/audit_consumables_static.py`
   `python tools/audit_bosses_static.py`
   `python tools/audit_tags_static.py`
4. **Dedicated Scaling Acceleration Regression Suite**:
   Create `vendor/balatro-rl/tests/test_scaling_acceleration.py` verifying:
   - Ride the Bus plays non-face cards on safe blinds and never plays scoring face cards.
   - Green Joker plays safe hands instead of discarding when safe.
   - Wee Joker banks 2s, prioritizing Hanging Chad index 0 positioning.
   - Square Joker banks 4-scoring-card hands.
   - Scaling is completely suppressed when `hands_left == 1` and under banned bosses (`bl_needle`, `bl_mouth`, `bl_eye`, `bl_grim`).
