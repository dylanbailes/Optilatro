# BRIEFING — 2026-09-05T00:44:40Z

## Mission
Investigate hand-type specialization traps with xMult jokers (j_family, j_order, j_duo, etc.) and portfolio_target_hand in tools/portfolio.py and agent_v10.py, and recommend deck-aware targeting and joker valuation fixes.

## 🔒 My Identity
- Archetype: explorer
- Roles: investigation, synthesis
- Working directory: D:/Optilatro/.agents/teamwork_preview_explorer_m2_2_gen6
- Original parent: ae7f41b5-88b7-4891-99ec-90a2e8f71801
- Milestone: m2_2_gen6

## 🔒 Key Constraints
- Read-only investigation — do NOT implement in production code
- White Stake / Red Deck / Antes 1-8 scope
- Output report in D:/Optilatro/.agents/teamwork_preview_explorer_m2_2_gen6/handoff.md
- Send result to parent via send_message

## Current Parent
- Conversation ID: ae7f41b5-88b7-4891-99ec-90a2e8f71801
- Updated: not yet

## Investigation State
- **Explored paths**:
  - `D:/Optilatro/.agents/ORIGINAL_REQUEST.md`
  - `D:/Optilatro/PROJECT.md`
  - `vendor/balatro-rl/balatro_sim/agent_v10.py` (lines 130-160, 400-610, 718-850, 995-1050, 1280-1310, 1445-1465, 1560-1670, 2509-2625, 3174-3245)
  - `tools/portfolio.py` (lines 595-678)
  - `vendor/balatro-rl/balatro_sim/agent_v9.py` (lines 295-315, 889-920, 971-1079, 1181-1400, 1438-1470, 1925-1965, 2096-2200)
  - `vendor/balatro-rl/balatro_sim/jokers/mult.py` (lines 134-163)
  - `vendor/balatro-rl/results/bench_0_299_search_shop_v10_gen5.json` (runs telemetry)
- **Key findings**:
  - `bench_0_299_search_shop_v10_gen5.json` confirms: `j_family` 0/14 wins (0.0%), `j_order` 0/8 wins (0.0%), `j_duo` 0/8 wins (0.0%).
  - Across 14 runs holding `j_family`, Four of a Kind was played in ONLY ONE RUN (Seed 118, which still died in Ante 6); in the other 13 runs, 4OAK was played ZERO times while buying 4+ Mars planets.
  - Natural 4OAK probability in a 52-card deck is 0.33% in opening hand and only 3.27% for the target rank across 23 cards.
  - `_HAND_ENGINE_PRIORITY` unconditionally overrides `main_hand_type` the instant `j_family`, `j_order`, or `j_duo` is bought, suppressing planet leveling of working base hands (Flush/Two Pair).
  - `j_duo` (x2 Mult) triggers on any hand containing a pair (including Two Pair and Full House), but `portfolio_target_hand` forcibly demotes target hand to "Pair" (lowest base stats, worst planet scaling), and `SearchShopV10` sells essential flat-mult anchors (e.g. Green Joker in Seed 281) because `j_duo` is listed under `PREMIER_XMULT_FINISHERS`.
  - `j_order` (x3 Mult) requires Straights which have 1.7% natural frequency and are ruined by rank-duplicating Tarots unless `j_shortcut` or `j_four_fingers` is owned.
- **Unexplored areas**: None remaining for this scope.

## Key Decisions Made
- Formulating deck-gated `portfolio_target_hand`:
  - `j_family`: target 4OAK ONLY IF `max_rank_count >= 6` in deck; otherwise maintain high-frequency base hand (`main_hand_type`).
  - `j_order`: target Straight ONLY IF `j_shortcut` or `j_four_fingers` owned or `Straight` played >= 2 times.
  - `j_duo`: map to `main_hand_type` (if Two Pair, Full House, Trips) or "Two Pair"; NEVER force "Pair".
- Formulating valuation gating:
  - Remove `j_family`, `j_order`, `j_duo` from unconditional `PREMIER_XMULT_FINISHERS` and `RELIABLE_XMULT_JOKERS`.
  - Tighten anchor protection in `_v10_worst_joker_idx` so flat mult / scaling anchors are never liquidated for pure xMult when `n_flat <= 1`.

## Artifact Index
- `D:/Optilatro/.agents/teamwork_preview_explorer_m2_2_gen6/DISPATCH.md` — Incoming dispatch log
- `D:/Optilatro/.agents/teamwork_preview_explorer_m2_2_gen6/BRIEFING.md` — Situational awareness
- `D:/Optilatro/.agents/teamwork_preview_explorer_m2_2_gen6/progress.md` — Heartbeat log
- `D:/Optilatro/.agents/teamwork_preview_explorer_m2_2_gen6/analyze_gen5.py` — Benchmark extraction script
- `D:/Optilatro/.agents/teamwork_preview_explorer_m2_2_gen6/inspect_duo.py` — Seed 281 deep dive script
- `D:/Optilatro/.agents/teamwork_preview_explorer_m2_2_gen6/diagnose_traps.py` — Complete 30-run telemetry script
- `D:/Optilatro/.agents/teamwork_preview_explorer_m2_2_gen6/handoff.md` — Final 5-component report
