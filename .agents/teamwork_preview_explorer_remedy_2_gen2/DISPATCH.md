## 2026-09-03T20:58:24Z
You are Remedy Explorer 2 (teamwork_preview_explorer).
Your assigned working directory is: D:/Optilatro/.agents/teamwork_preview_explorer_remedy_2_gen2

MANDATORY FIRST STEP: Read the full, verbatim user request at:
D:/Optilatro/.agents/ORIGINAL_REQUEST.md (specifically under `## 2026-09-03T20:10:17Z`).
Also read:
- D:/Optilatro/.agents/orchestrator_2/SCOPE.md
- D:/Optilatro/AGENTS.md and docs/STATUS.md
- Challenger 2 Handoff: D:/Optilatro/.agents/teamwork_preview_challenger_bench_gen2/handoff.md (specifically Root Cause 1)

Objective:
Formulate exact code fixes for the Ante 1 Pace Rule Hand-Burning defect in `vendor/balatro-rl/balatro_sim/agent_v10.py`:
1. Challenger 2 observed that 19 previously surviving seeds regressed to Ante 1 deaths because `ante1_pace_rule` (line ~2180) plays immediately whenever `best_score >= (target - scored) / hands_left`.
   - On Seed 249, it burned hands on weak pairs without using any discards, dying on Small Blind with 3 unused discards left (in baseline it used discards, cleared, and won Ante 9).
   - On Seed 30, it burned hands on Two Pairs while holding `j_tribe` (+X3 for Flush), dying on Big Blind with 412/450 (in baseline it discarded for a Flush, scored 2000, and reached Ante 5).
2. Deeply inspect lines 2170–2220 in `agent_v10.py` (`ante1_pace_rule` and in-blind play logic).
   - Why did the pace rule bypass discard digging when discards were available?
   - How should the pace rule condition on:
     a) Discards left: if discards remain and the hand does not clear the blind or beat a substantial safety threshold, should we discard to dig for stronger hands (Flushes, Straights, Full Houses)?
     b) Active joker target hand: if `joker_target_hand_type(game)` is set (e.g. Flush for `j_tribe`, Straight for `j_runner`), we MUST NOT burn hands on off-target low hands while discards remain!
     c) Fatal seeds 205 & 275: verify that any fix still deterministically clears Small Blind on fatal seeds 205 and 275!
3. Formulate the exact, drop-in replacement logic for `ante1_pace_rule` in `agent_v10.py`.

Deliverables:
- Write comprehensive fix plan to D:/Optilatro/.agents/teamwork_preview_explorer_remedy_2_gen2/handoff.md.
- Send message to parent when done.
