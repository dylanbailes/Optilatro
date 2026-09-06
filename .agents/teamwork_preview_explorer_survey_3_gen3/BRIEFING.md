# BRIEFING — 2026-09-04T06:53:00Z

## Mission
Investigate scaling joker acceleration during safe blinds (R3) for Optilatro agent_v10.

## 🔒 My Identity
- Archetype: explorer
- Roles: investigation, synthesis
- Working directory: D:/Optilatro/.agents/teamwork_preview_explorer_survey_3_gen3
- Original parent: a6fe01c1-9f17-4c3f-adcb-a097f699dab4
- Milestone: gen3-r3-scaling-joker-acceleration

## 🔒 Key Constraints
- Read-only investigation — do NOT implement
- Do not peek at draw order
- Never consume run RNG from evaluation
- Do not mutate live game from scoring/valuation
- Do not modify source code or tests

## Current Parent
- Conversation ID: a6fe01c1-9f17-4c3f-adcb-a097f699dab4
- Updated: 2026-09-04T06:53:00Z

## Investigation State
- **Explored paths**:
  - `vendor/balatro-rl/balatro_sim/agent_v10.py` (`_v10_decide_hand`, `_tier1_survive`, `tier2_value`, `estimate_clear_probability_bounds`, `scored_plays`, `_guard`, `V10_DEFAULTS`)
  - `vendor/balatro-rl/balatro_sim/agent_v9.py` (`scored_plays`, `eval_hand_score`, `joker_value`)
  - `vendor/balatro-rl/balatro_sim/game.py` (`BalatroGame._play_hand`, boss blind triggers, `run_hand_counts`, round payout)
  - `vendor/balatro-rl/balatro_sim/scoring.py` (`score_hand`, joker hooks execution, `ScoreContext`)
  - `vendor/balatro-rl/balatro_sim/jokers/scaling.py` (`_GreenJoker`, `_RideTheBus`, `_SpareTrousers`, `_Runner`, `_Hiker`)
  - `vendor/balatro-rl/balatro_sim/jokers/mult.py` (`_Supernova`)
  - `vendor/balatro-rl/balatro_sim/jokers/misc.py` (`_Wee`, `_HangingChad`, `_Hack`)
  - `vendor/balatro-rl/balatro_sim/jokers/chips.py` (`_SquareJoker`)
  - `tools/portfolio.py` (`SCALING_JOKERS`, feature extraction)
  - `vendor/balatro-rl/tests/test_agent_v10.py`, `vendor/balatro-rl/tests/test_seed_exactness.py`
- **Key findings**:
  - Premature knockout termination in `_tier1_survive:2190` ends safe blinds on Hand 1, discarding 2–3 surplus hands and wasting 30–45 permanent scaling opportunities across the run.
  - Tier 2 value farming (`tier2_value`, `play_trigger_value`) omits scaling jokers entirely.
  - Green Joker suffers a -1 Mult penalty per discard, yet `_tier1_survive` discards to hunt hands instead of playing safe hands.
  - Ride the Bus faces a catastrophic mult reset to 0 if any scoring face card is played.
  - Square Joker in simulator checks `len(ctx.scoring_cards) == 4` (Two Pair / FoK) rather than `len(all_cards) == 4`.
  - Formulated a robust 3-Tier Safety Hierarchy:
    - Tier S1: Deterministic In-Hand Knockout Reservation (Risk = 0.000%, disjoint cards $C \subseteq H \setminus K$).
    - Tier S2: Single-Hand Clear Projection with Surplus Hands ($S_{top} 	imes (h - 1) \ge T 	imes 2.0$).
    - Tier S3: Compositional & Calibrated Model Bounds ($P(	ext{clear}) \ge 0.98$, model $\ge 0.95$).
  - Identified critical boss banlist (`bl_needle`, `bl_mouth`, `bl_eye`, `bl_grim`, `bl_hook`, `bl_tooth`, `bl_pillar`).
- **Unexplored areas**: None within R3 survey scope.

## Key Decisions Made
- Fully designed Scaling Joker Acceleration policy for `agent_v10.py` with deterministic safety guarantees and discard suppression.
- Authored comprehensive `analysis.md` (24 KB) and 5-component `handoff.md` (7 KB).
- Validated CI seed exactness gate (4/4 passed).

## Artifact Index
- `D:/Optilatro/.agents/teamwork_preview_explorer_survey_3_gen3/analysis.md` — Detailed findings & architectural blueprint
- `D:/Optilatro/.agents/teamwork_preview_explorer_survey_3_gen3/handoff.md` — Structured 5-component handoff report
- `D:/Optilatro/.agents/teamwork_preview_explorer_survey_3_gen3/progress.md` — Liveness heartbeat
