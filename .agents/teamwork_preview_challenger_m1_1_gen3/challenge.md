# Adversarial Challenge Report — Milestone M1 Policy Verification

## Challenge Summary

**Overall risk assessment**: CRITICAL
**Verdict**: REJECT

An empirical critical defect was discovered during adversarial stress testing:
In endor/balatro-rl/balatro_sim/agent_v10.py, function 	ier2_value fails to check whether game.discards_left > 0 before evaluating discard levers (j_faceless, j_mail_in_rebate, j_trading_card, purple seals). When discards_left == 0 and a discard lever is active with high clear probability, 	ier2_value outputs an illegal {'type': 'discard'} action. Because BalatroGame._discard is a no-op when discards_left <= 0, the game state never updates and the agent enters an **infinite deadlock loop**, permanently freezing rollouts.

In a 25-game empirical rollout (seeds 10000–10024), this defect caused **immediate infinite deadlocks in 3 out of 25 games (Seed 10001, Seed 10004, and Seed 10024)**.

---

## Confirmed Critical Failure Mode

### [Critical] Defect 1: `tier2_value` Issues Illegal Discards When `discards_left == 0`, Causing Simulation Deadlock
- **Location**: `vendor/balatro-rl/balatro_sim/agent_v10.py`, lines 2824–2840.
- **Root Cause**:
  ```python
  # ── Discard candidates ─────────────────────────────────────────────────
  for dcombo, committed in _value_discard_candidates(game, hand):
      if not dcombo:
          continue
      val = _discard_value(game, dcombo)
  ```
  `tier2_value` does NOT verify `if game.discards_left > 0:` before generating discard candidates.
  Furthermore, `_guard` evaluates `d = game.discards_left - 1 = -1`. In `estimate_clear_probability`, `d = -1` with `hands_left >= 2` still evaluates to `P(clear) = 1.0 >= abandon_clear_floor`.
  Consequently, `tier2_value` prioritizes the high positive value of the discard lever (e.g. Faceless Joker +$5 = 0.50 value points) and returns `{'type': 'discard', 'cards': [1, 2, 4]}`.
- **Engine Behavior**:
  In `vendor/balatro-rl/balatro_sim/game.py`, line 1069:
  ```python
  def _discard(self, card_indices: list[int]):
      if self.discards_left <= 0:
          return
  ```
  The engine rejects the discard silently, consuming 0 cards, 0 hands, and remaining in `State.SELECTING_HAND`.
- **Failure Manifestation**:
  On the subsequent decision step, the agent sees the identical hand, identical board state, identical `discards_left == 0`, and issues the exact same discard action again. The simulation **deadlocks infinitely**.
- **Empirical Reproduction**:
  - **Seed 10001**: Deadlocked at step 105 (Ante 3, discards_left 0, holding Faceless Joker).
  - **Seed 10004**: Deadlocked at Ante 6 with discards_left 0.
  - **Seed 10024**: Deadlocked at Ante 4 with discards_left 0.
- **Blast Radius**:
  Any game that acquires Faceless Joker, Mail-in Rebate, Trading Card, or Purple Seals and exhausts its discards while holding winning hands will deadlock and crash/hang the evaluation or training harness.
- **Recommended Remediation**:
  In endor/balatro-rl/balatro_sim/agent_v10.py, wrap line 2824 in an explicit check:
  `python
  # ── Discard candidates ─────────────────────────────────────────────────
  if game.discards_left > 0:
      for dcombo, committed in _value_discard_candidates(game, hand):
          ...
  `

---

## Adversarial Stress Tests for Non-Failing Components

### [Low] Challenge 1: Ride the Bus Face Card Safety & Guardrails
- **Tested**: Mixed hands, all-face hands, non-scoring face card kickers ([2, 2, K]), and dual clearing hands (Kings vs Twos).
- **Result**: _find_scaling_action avoided scoring face cards; _tier1_survive preferred safe non-face clearing plays. **PASS**.

### [Low] Challenge 2: Green Joker Pacing Under Valid Discards
- **Tested**: Suppressed discard on safe blinds (p_clear >= 0.98), allowed discard on unsafe blinds (p_clear = 0.30), and joint Ride the Bus + Green Joker interaction.
- **Result**: Pacing behaved correctly when discards_left > 0. **PASS**.

### [Low] Challenge 3: Dangerous Boss Blind Defense
- **Tested**: All 8 banned bosses (l_needle, l_mouth, l_eye, l_psychic, l_tooth, l_hook, l_pillar, l_grim).
- **Result**: Scaling strictly suppressed across all 8 bosses; Psychic enforced 5-card plays. **PASS**.

### [Low] Challenge 4: Late-Game Capital Deployment & Liquidation
- **Tested**: Ante 8 interest floor (), boundary bankrolls ( through ), full-slot portfolio swaps (selling worst joker to buy finisher), and urgent reroll caps (Ante 6 cap 4, Ante 7 cap 6, Ante 8 cap 10).
- **Result**: Terminated cleanly without deadlocks or index errors. 
eserve_ok prevented bankrupting rerolls. **PASS**.

---

## Stress Harness Execution Log
`	ext
=== TEST 1: Ride the Bus Face Safety & Guardrails ===
  [PASS] 1.A: Scaling action avoided scoring face cards in mixed hand.
  [PASS] 1.B: All-face hand returned None from scaling action without crash.
  [PASS] 1.B: _tier1_survive safely returned action: play
  [PASS] 1.C: King kicker in Pair of 2s is correctly non-scoring.
  [PASS] 1.D: _tier1_survive safely preferred Twos over Kings when clearing.
=== TEST 2: Green Joker Low Hands & Discard Pacing ===
  [PASS] 2.A: Scaling properly suppressed when hands_left == 1.
  [PASS] 2.B: Discard successfully suppressed to preserve Green Joker mult on safe blind.
  [PASS] 2.C: Discard correctly allowed on unsafe blind to dig for survival.
  [PASS] 2.D: Joint Green + Bus suppressed discard AND avoided scoring face cards.
  [FAIL] 2.E [CRITICAL BUG]: tier2_value returned discard action when discards_left == 0! Triggers infinite deadlock loop.
=== TEST 3: Banned Boss Blinds Defense ===
  [PASS] 3: Scaling suppressed under The Needle (1 hand only).
  [PASS] 3: Scaling suppressed under The Mouth (only 1 hand type).
  [PASS] 3: Scaling suppressed under The Eye (no repeat hand types).
  [PASS] 3: Scaling suppressed under The Psychic (must play 5 cards).
  [PASS] 3: Scaling suppressed under The Tooth (lose  per card).
  [PASS] 3: Scaling suppressed under The Hook (discards 2 cards on play).
  [PASS] 3: Scaling suppressed under The Pillar (cards debuffed).
  [PASS] 3: Scaling suppressed under The Grim (discards 2 random cards).
=== TEST 4: Late-Game Capital Deployment & Liquidation ===
  [PASS] 4.A: Shop terminated cleanly in 12 steps (buys=8, rerolls=3).
  [PASS] 4.B: At , policy safely returned: leave_shop
  [PASS] 4.B: At , policy safely returned: leave_shop
  [PASS] 4.B: At , policy safely returned: leave_shop
  [PASS] 4.B: At , policy safely returned: buy
  [PASS] 4.B: At , policy safely returned: buy
  [PASS] 4.B: At , policy safely returned: buy
  [PASS] 4.B: At , policy safely returned: buy
  [PASS] 4.C: Full slots successfully initiated swap by selling joker 3 (j_lusty_joker).
  [PASS] 4.D: Ante 6 respects cap of 4 rerolls.
  [PASS] 4.D: Ante 7 respects cap of 6 rerolls.
  [PASS] 4.D: Ante 8 respects cap of 10 rerolls.
=== TEST 5: End-to-End Game Rollouts (25 Games) ===
  End-to-end rollouts: 25 games, 0 wins, 3 crashes/deadlocks.
  [FAIL] Game seed 10001 exceeded max steps (deadlock)! Current state: State.SELECTING_HAND ante: 3 discards_left: 0
  [FAIL] Game seed 10004 exceeded max steps (deadlock)! Current state: State.SELECTING_HAND ante: 6 discards_left: 0
  [FAIL] Game seed 10024 exceeded max steps (deadlock)! Current state: State.SELECTING_HAND ante: 4 discards_left: 0
`
