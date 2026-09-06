## 2026-09-02T21:44:16Z
You are teamwork_preview_worker for Milestone 1: Ante-1 In-Blind Multi-Hand Pace Rule (R1).
Your working directory is: D:/Optilatro/.agents/teamwork_preview_worker_m1_1

Read ORIGINAL_REQUEST.md at: D:/Optilatro/ORIGINAL_REQUEST.md
Read PROJECT.md at: D:/Optilatro/PROJECT.md
Read survey findings at: D:/Optilatro/.agents/teamwork_preview_explorer_survey_1/handoff.md
Also review AGENTS.md at: D:/Optilatro/AGENTS.md.

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A teamwork_preview_auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

Scope & Tasks:
1. You exclusively own: vendor/balatro-rl/balatro_sim/agent_v10.py (do NOT edit agent_v9.py which is the frozen baseline).
2. Configure V10_DEFAULTS in agent_v10.py so that "ante1_pace_rule": True is enabled by default for V10 policies.
3. Verify that _tier1_survive computes pace = (target / max(1, game.hands_left)) * V10_PARAMS.get("ante1_pace_mult", 1.0) and triggers immediate play when best_score >= pace during Ante 1.
4. Verify that fatal seeds 205 and 275 clear Ante 1 Small Blind with ante1_pace_rule=True (test using BalatroGame(seed=205, rng_mode="seed") and seed=275).
5. Run the full unit test suite, CI seed exactness gate, and all 4 static audits to ensure everything passes cleanly.
6. Write your handoff report to D:/Optilatro/.agents/teamwork_preview_worker_m1_1/handoff.md with full command outputs and send a completion message to parent.
