## 2026-09-02T21:38:43Z
You are teamwork_preview_explorer for Step 0 Survey (Jokers, Portfolio & Shop Search).
Your assigned working directory is: D:/Optilatro/.agents/teamwork_preview_explorer_survey_2

Read ORIGINAL_REQUEST.md at: D:/Optilatro/ORIGINAL_REQUEST.md
Also review AGENTS.md at: D:/Optilatro/AGENTS.md and docs/STATUS.md.

Scope of Investigation:
1. Examine `vendor/balatro-rl/balatro_sim/jokers/` and `tools/portfolio.py` (check if exists or needs to be built).
2. How are jokers categorized (Chips, Flat Mult, xMult, Scaling, Economy, Retrigger)? What metadata or capability flags already exist?
3. How is shop search currently handled in `agent_v9.py`, `agent_l1.py`, and `agent_v10.py`? Check `SearchShopV10._search_shop` or current shop decision functions.
4. How do rollouts work in `vendor/balatro-rl/balatro_sim/rollout.py` and what shop actions (buy, sell, swap, reroll, leave) need counterfactual evaluation?
5. How does state feature extraction need to work for counterfactual shop states (live game state + hypothetical buys/sells)?
6. Check the contract rules: decorator-only registration, no engine scan violations, human-fair shop evaluation.

Output Requirements:
- Write your complete structured report and findings to `D:/Optilatro/.agents/teamwork_preview_explorer_survey_2/handoff.md`.
- Keep `progress.md` updated during your work.
- Use `send_message` to report back to parent when done.
