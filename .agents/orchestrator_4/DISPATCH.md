## 2026-09-04T23:54:50Z

<USER_REQUEST>
You are orchestrator_4, the Project Orchestrator for Optilatro search-first Balatro AI agent advancement project.

Working directory: D:/Optilatro/.agents/orchestrator_4
Authoritative Request: D:/Optilatro/.agents/ORIGINAL_REQUEST.md
Project Root: D:/Optilatro

## Mission & Goal
Advance the Optilatro search-first Balatro AI agent to break through the 10.0%+ win rate threshold (>= 30 wins / 300) while keeping Ante 1 mortality below 4.0% (< 12 deaths / 300) on Red Deck / White Stake under strict human-fair constraints.

## Requirements
### R1. Late-Game Capital Deployment & Urgent Rerolls
Implement adaptive bankroll liquidation in vendor/balatro-rl/balatro_sim/agent_v10.py:
- In Antes 6–8, when current scoring forecast falls below upcoming blind targets, relax the $25 interest floor and aggressively hunt reliable xMult finishers (Cavendish, Duo, Trio, Family, Baseball Card, Acrobat, Constellation).

### R2. Synergistic Deck Reshaping & Targeted Consumables
Direct Tarot/Planet conversions and usages towards engine synergies in agent_v10.py / portfolio helpers.

### R3. Scaling Joker Acceleration
Safe in-blind scaling acceleration when knockout is reserved.

### R4. Human-Fair & Isolation Guarantees
Strict human-fairness: zero peeking at future draw order, zero future shop/boss RNG stream consumption, zero live game mutation during evaluation. `python -m pytest vendor/balatro-rl/tests/test_seed_exactness.py -m ci_gate -v` must remain 100% green.

## Acceptance Criteria
- 300-seed benchmark >= 30 wins (>= 10.0%) and < 12 Ante-1 deaths (< 4.0%).
- All simulator unit tests pass: `python -m pytest vendor/balatro-rl/tests vendor/balatro-rl/balatro_sim/tests -q`.
- CI seed exactness gate passes: `python -m pytest vendor/balatro-rl/tests/test_seed_exactness.py -m ci_gate -v`.
- All 4 static audits remain clean: `python tools/audit_jokers_static.py`, `python tools/audit_consumables_static.py`, `python tools/audit_bosses_static.py`, `python tools/audit_tags_static.py`.

## Orchestrator Discipline & Protocols
- Maintain your own BRIEFING.md and progress.md in D:/Optilatro/.agents/orchestrator_4/.
- Never write or edit code directly; dispatch specialists (explorers, workers, reviewers, challengers, test-writers).
- Ensure every subagent writes to its own isolated directory under D:/Optilatro/.agents/<subagent_id>/.
- When all milestones and acceptance criteria are satisfied, report completion with full evidence to Sentinel.
</USER_REQUEST>

## 2026-09-05T06:02:04Z

URGENT COURSE CORRECTION FROM USER (2026-09-05T06:01:08Z):
1. Do not focus on converting specific close games or individual seed traces. Trace macro patterns across losses across all failed runs to determine systemic fixes that minimize widespread failure modes.
2. All verification and benchmark acceptance runs MUST be conducted on completely fresh, never-before-seen seed banks. Never reuse verification seeds across iterations.
3. Use seeds 9000–9299 for the current verification run. Ensure zero overlap with any previously examined seeds.

Please immediately pivot the verification panel and benchmark challenger to execute the acceptance evaluation on Seeds 9000–9299. Target criteria remain >= 30 wins (>= 10.0%) and < 12 Ante-1 deaths (< 4.0%) under strict human-fair constraints. ORIGINAL_REQUEST.md has been updated.

## 2026-09-05T06:17:12Z

URGENT DIRECTIVE FROM USER / PARENT (2026-09-05T06:16:45Z):
In accordance with the user's strict instruction ("seeds should never be reused in verification runs, make sure we never reuse verification seeds"):
1. Seeds 9000–9299 have been utilized for the previous verification run (REJECT: 24W / 17D).
2. For the upcoming verification run following the implementation of the macro remedies (Ante-1 pure economy gating and mid-game deficit capital deployment), the verification panel MUST evaluate on the next completely pristine, never-before-seen seed bank: Seeds 9300–9599.
3. NEVER reuse seeds 9000–9299 or 0–299 for verification.
4. Acceptance criteria remain: >= 30 wins (>= 10.0%) and < 12 Ante-1 deaths (< 4.0%) on Seeds 9300–9599.

Please immediately register Seeds 9300–9599 as the target acceptance bank for the verification panel and benchmark challenger once the macro remedies are applied. ORIGINAL_REQUEST.md has been updated.
