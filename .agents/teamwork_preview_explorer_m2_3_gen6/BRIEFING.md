# BRIEFING — 2026-09-04T17:49:40Z

## Mission
Investigate 14 lost seeds from Gen5 benchmark ([21, 40, 43, 54, 60, 80, 95, 131, 139, 155, 188, 198, 211, 298]), diagnose loss root causes, and identify 2-3 high-leverage policy tweaks to reach >=30 wins (10.0%) while preserving existing 27 wins.

## 🔒 My Identity
- Archetype: explorer
- Roles: explorer, investigator, synthesizer
- Working directory: D:/Optilatro/.agents/teamwork_preview_explorer_m2_3_gen6
- Original parent: ae7f41b5-88b7-4891-99ec-90a2e8f71801
- Milestone: m2_3_gen6

## 🔒 Key Constraints
- Read-only investigation — do NOT implement / modify source code directly
- Human-fair rules: do not peek at draw order in default policies
- Never consume run RNG from evaluation
- Strictly adhere to AGENTS.md rules

## Current Parent
- Conversation ID: ae7f41b5-88b7-4891-99ec-90a2e8f71801
- Updated: 2026-09-04T17:49:40Z

## Investigation State
- **Explored paths**: `bench_0_299_search_shop_v10_gen5.json`, `bench_0_299_search_shop_v10.json`, `agent_v10.py` (`_v10_rank_shop_items`, `_v10_worst_joker_idx`, `_v10_decide_shop`, `portfolio_target_hand`, `_tier1_survive`).
- **Key findings**:
  1. Solo Blueprint purchase in Ante 1 with 0 jokers caused fatal Seed 298 death on Ante 1 Big Blind.
  2. Blueprint/Brainstorm valuation bug: default `joker_value=0.075` caused `_v10_worst_joker_idx` to immediately sell Blueprint after buying it (Seed 80 in Ante 8).
  3. Trap jokers (`j_obelisk`, `j_idol`) were bought in general shop despite being skipped in counterfactual swaps (Seeds 21, 95, 198).
  4. Late-game capital hoarding: `save_mode` in `_v10_decide_shop` blocked rerolls in Ante 6–7 even with `is_urgent_late = True`, causing Seeds 139, 155, 198, 211 to die with $20–$25 unspent.
- **Unexplored areas**: None; all 14 seeds and their failure mechanisms are fully cataloged.

## Key Decisions Made
- Formulated 3 minimal, high-impact policy tweaks to recover 3 to 5 lost seeds (298, 80, 21, 43, 139/155) while preserving all 27 existing wins to hit >= 30 wins.

## Artifact Index
- DISPATCH.md — incoming dispatch instructions
- BRIEFING.md — working memory and identity
- progress.md — liveness heartbeat
- seeds_analysis.txt — comprehensive telemetry and action log for all 14 seeds
- handoff.md — final analysis report
