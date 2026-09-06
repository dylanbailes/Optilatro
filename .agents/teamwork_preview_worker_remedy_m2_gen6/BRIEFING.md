# BRIEFING — 2026-09-04T17:57:00Z

## Mission
Implement targeted, high-leverage policy enhancements in vendor/balatro-rl/balatro_sim/agent_v10.py and tools/portfolio.py to close the 3-win gap (27 -> >=30 wins) and eliminate known early/mid-game traps, based on Explorer synthesis.

## 🔒 My Identity
- Archetype: worker
- Roles: implementer, qa, specialist
- Working directory: D:/Optilatro/.agents/teamwork_preview_worker_remedy_m2_gen6
- Original parent: ae7f41b5-88b7-4891-99ec-90a2e8f71801 (orchestrator_4)
- Milestone: M2 remedy gen6

## 🔒 Key Constraints
- Strict human-fairness: zero peeking at draw order, zero future shop/boss RNG stream consumption, zero live game mutation during evaluation.
- `tests/test_seed_exactness.py -m ci_gate` must remain 100% green.
- Do not mutate live game from scoring/valuation.
- Follow minimal change principle.
- No dummy/facade implementations or hardcoding test results.

## Current Parent
- Conversation ID: ae7f41b5-88b7-4891-99ec-90a2e8f71801
- Updated: not yet

## Task Summary
- **What to build**:
  1. Early Copier Gating & Protection in agent_v10.py (Blueprint/Brainstorm gating in shop rank and protection from immediate sell in worst_joker_idx).
  2. Deck-Aware Hand Specialization in tools/portfolio.py (j_family, j_order, j_duo hand target adjustments) and agent_v10.py (PREMIER_XMULT_FINISHERS update).
  3. Trap Jokers & Late-Game Capital Unlocking in agent_v10.py (j_obelisk ban, j_idol monoculture gating, prevent selling combat jokers for economy in Ante >= 5, unblock rerolls down to $6 when is_urgent_late).
  4. Verification & Validation (test suites, CI exactness, 4 static audits, Seed 298 & 80 validation).
- **Success criteria**: All tests pass, CI exactness passes, static audits clean, targeted seed behaviors fixed.
- **Interface contracts**: D:/Optilatro/PROJECT.md
- **Code layout**: vendor/balatro-rl/balatro_sim/agent_v10.py, tools/portfolio.py

## Key Decisions Made
- Adhere strictly to the 4 task directives from Explorer synthesis.

## Artifact Index
- D:/Optilatro/.agents/teamwork_preview_worker_remedy_m2_gen6/DISPATCH.md — Assignment instructions
- D:/Optilatro/.agents/teamwork_preview_worker_remedy_m2_gen6/BRIEFING.md — Situational awareness
- D:/Optilatro/.agents/teamwork_preview_worker_remedy_m2_gen6/progress.md — Liveness & progress tracking
- D:/Optilatro/.agents/teamwork_preview_worker_remedy_m2_gen6/handoff.md — Final 5-component handoff report

## Change Tracker
- **Files modified**: None yet
- **Build status**: Not run yet
- **Pending issues**: None

## Quality Status
- **Build/test result**: Untested
- **Lint status**: Clean
- **Tests added/modified**: None yet

## Loaded Skills
- None
