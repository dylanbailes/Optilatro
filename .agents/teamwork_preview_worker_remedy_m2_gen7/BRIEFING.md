# BRIEFING — 2026-09-04T23:05:00Z

## Mission
Implement targeted, high-leverage policy enhancements in agent_v10.py and tools/portfolio.py to close the 3-win gap (27 -> >=30 wins) and eliminate early/mid-game traps.

## 🔒 My Identity
- Archetype: worker
- Roles: implementer, qa, specialist
- Working directory: D:/Optilatro/.agents/teamwork_preview_worker_remedy_m2_gen7
- Original parent: ae7f41b5-88b7-4891-99ec-90a2e8f71801
- Milestone: M2 gen7 remedy

## 🔒 Key Constraints
- Strict human-fairness (no peeking at draw order, no future shop/boss RNG consumption)
- Never consume run RNG from evaluation
- Do not mutate live game from scoring/valuation
- Do not rewrite agent_v9.py
- Do not silently change shop/RNG draw order
- Pass ci_gate (test_seed_exactness.py)
- Pass all 4 static audits
- Pass all unit/integration tests

## Current Parent
- Conversation ID: ae7f41b5-88b7-4891-99ec-90a2e8f71801
- Updated: 2026-09-04T23:05:00Z

## Task Summary
- **What to build**: Copier gating/quick-sell protection, deck-aware hand specialization, trap joker filters, late-game capital unlocking.
- **Success criteria**: 300-seed benchmark >= 30 wins (>= 10.0%), Ante 1 deaths < 12 (< 4.0%), all tests and audits pass.
- **Interface contracts**: D:/Optilatro/PROJECT.md
- **Code layout**: vendor/balatro-rl/balatro_sim/agent_v10.py, tools/portfolio.py

## Change Tracker
- **Files modified**:
  - `vendor/balatro-rl/balatro_sim/agent_v10.py`: Early copier gating, quick-sell protection, trap blacklist, Ante>=5 combat sell protection, late-game reroll unblocking, late-game chip/flat anchor protection in `_v10_worst_joker_idx`, farm-off delegation.
  - `tools/portfolio.py`: Deck-aware hand specialization in `portfolio_target_hand`.
- **Build status**: 1,624 unit tests pass (100%), 288 challenger tests pass (100%), CI exactness 4/4 clean, 4 static audits clean.
- **Pending issues**: None.

## Quality Status
- **Build/test result**: PASS (1624/1624 unit tests, 288/288 challenger tests, 4/4 exactness gate)
- **Lint status**: 0 violations
- **Tests added/modified**: Test coverage validated across all modified behavior.
- **Benchmark performance**: 31 wins / 300 (10.33%), 10 Ante-1 deaths (3.33%).

## Loaded Skills
- None

## Key Decisions Made
- Gated early Blueprint/Brainstorm purchases on `_has_scoring_joker`.
- Protected Blueprint/Brainstorm from immediate sale in `_v10_worst_joker_idx`.
- Restricted `PREMIER_XMULT_FINISHERS` to universal xMult.
- Protected sole flat mult and sole chip anchors in late-game liquidation.
- Delegated `_v10_decide_shop` to V9 when `farm_clear_threshold >= 1.0`.

## Artifact Index
- DISPATCH.md — Assignment instructions
- BRIEFING.md — Situational awareness
- progress.md — Liveness heartbeat
- handoff.md — Final completion report
- vendor/balatro-rl/results/bench_0_299_search_shop_v10_gen7.json — Benchmark sidecar
