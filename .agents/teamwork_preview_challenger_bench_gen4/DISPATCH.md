## 2026-09-04T23:55:57Z
You are teamwork_preview_challenger_bench_gen4.
Working directory: D:/Optilatro/.agents/teamwork_preview_challenger_bench_gen4
Your parent is orchestrator_4 (conversation ID: ae7f41b5-88b7-4891-99ec-90a2e8f71801).
Authoritative request: D:/Optilatro/.agents/ORIGINAL_REQUEST.md (YOU MUST READ THIS FIRST).
Scope document: D:/Optilatro/PROJECT.md

Task:
Execute the full 300-seed benchmark (Seeds 0–299) on Red Deck / White Stake to empirically verify win rate and mortality acceptance criteria.
1. Read D:/Optilatro/.agents/ORIGINAL_REQUEST.md and D:/Optilatro/PROJECT.md.
2. Run the 300-seed benchmark:
   Check `python bench/bench_agent_v10.py --help` to inspect arguments.
   Run: `python bench/bench_agent_v10.py --seeds 0-299 --workers 8` (or appropriate concurrency for this machine).
3. Evaluate against acceptance criteria:
   - Target: >= 30 wins / 300 (>= 10.0% win rate)
   - Target: < 12 Ante-1 deaths (< 4.0% mortality)
   - Compare with frozen baseline V9 (26 wins, 11 Ante-1 deaths).
4. Analyze telemetry:
   - Report wins, win rate %, Ante 1 deaths, mortality %.
   - Breakdown of deaths by Ante (Ante 1 to Ante 8).
   - Frequency of premier finishers acquired (Cavendish, Duo, Trio, Family, Baseball Card, Acrobat, Constellation).
5. Write comprehensive benchmark report to D:/Optilatro/.agents/teamwork_preview_challenger_bench_gen4/handoff.md.
6. State an explicit verdict: APPROVE (if >= 30 wins and < 12 Ante-1 deaths) or REJECT.
7. Send message to parent with your verdict and summary.
