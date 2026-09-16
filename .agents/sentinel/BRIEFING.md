# BRIEFING — 2026-09-10T20:59:35Z

## Mission
Scale Optilatro's V11 search policy (`agent_v11.py`) from 14% toward a 20%–25% full-run win rate on Red Deck / White Stake on pristine seed bank 10500–10799 via universal Value Network shop scoring, early-game deficit capital deployment, and in-blind value squeezing.

## 🔒 My Identity
- Archetype: sentinel
- Working directory: D:/Optilatro/.agents/sentinel
- Orchestrator: a6fe01c1-9f17-4c3f-adcb-a097f699dab4
- Victory Auditor: [auditor conversation ID, to be spawned on victory claim]
- Active Orchestrator: ae7f41b5-88b7-4891-99ec-90a2e8f71801 (orchestrator_4)
- Monitoring Crons: Cron 1 (task-30, */8 * * * *), Cron 2 (task-32, */10 * * * *)
- Active Agent: 93e32bc2-862d-49bc-baee-a8cacc4934e7 (teamwork_preview_swe_1)

## 🔒 Key Constraints
- No technical decisions — relay only
- Victory Audit is MANDATORY before reporting completion
- Route: General (teamwork_preview_orchestrator)
- Human-fair constraints: no peeking at deck draw order or future shop/boss RNG streams
- All 1,562+ simulator unit tests, CI gate, and static audits must pass
- All 1,600+ simulator unit tests, CI gate, and static audits must pass
- Route: SWE Light (teamwork_preview_swe) per user explicit request ("single self-contained fix; keep it small and focused")
- Preserve V10's rock-solid Ante-1 conservative opening (`if game.ante == 1: return _v10_decide_shop(...)`)
- Restrict joker reordering strictly to copy jokers (`j_blueprint`, `j_brainstorm`) and `j_ceremonial`
- `agent_v10.py` and `default_baseline_v10.json` remain 100% frozen
- Paired benchmark on pristine seed bank 10500–10799 (N=300) achieves >= 20.0% win rate
- Seed exactness CI gate passes (`pytest vendor/balatro-rl/tests/test_seed_exactness.py -m ci_gate -v`)
- All 4 static audits pass cleanly

## User Context
- **Last user request**: Scale Optilatro's V11 search policy (`agent_v11.py`) from 14% toward 20%–25% full-run win rate on Red Deck / White Stake on seeds 10500–10799. "This is a single self-contained fix; keep it small and focused."
- **Pending clarifications**: none
- **Delivered results**: Previous iterations completed up to 9300-9599. Starting V11 search policy upgrade.

## Project Status
- **Phase**: in progress (spawning SWE Light agent)

## Victory Audit Status
- **Triggered**: no
- **Verdict**: pending
- **Retry count**: 0

## Artifact Index
- D:/Optilatro/.agents/ORIGINAL_REQUEST.md — Authoritative record of user requirements
- D:/Optilatro/ORIGINAL_REQUEST.md — Root copy of user request
- D:/Optilatro/vendor/balatro-rl/balatro_sim/agent_v11.py — Target search policy implementation
