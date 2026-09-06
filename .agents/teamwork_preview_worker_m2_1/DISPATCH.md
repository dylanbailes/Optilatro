## 2026-09-02T21:44:16Z
You are teamwork_preview_worker for Milestone 2: Joker Portfolio Classification & State Feature Extraction (R2).
Your working directory is: D:/Optilatro/.agents/teamwork_preview_worker_m2_1

Read ORIGINAL_REQUEST.md at: D:/Optilatro/ORIGINAL_REQUEST.md
Read PROJECT.md at: D:/Optilatro/PROJECT.md
Read survey findings at: D:/Optilatro/.agents/teamwork_preview_explorer_survey_2/handoff.md
Also review AGENTS.md at: D:/Optilatro/AGENTS.md.

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A teamwork_preview_auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

Scope & Tasks:
1. You exclusively own: `tools/portfolio.py` and `tests/test_portfolio.py`.
2. Verify and finalize `tools/portfolio.py`:
   - Categorize all 150 jokers into the 6 canonical strategic roles (`CHIPS_JOKERS`, `FLAT_MULT_JOKERS`, `XMULT_JOKERS`, `SCALING_JOKERS`, `ECON_JOKERS`, `RETRIGGER_JOKERS`).
   - Implement `classify_joker(key: str) -> dict[str, bool]`.
   - Implement `extract_features_from_state(...)` extracting 41 numeric features capturing progression, economy, portfolio composition, editions, synergies, deck distribution, hand levels, and danger indicators.
   - Implement `extract_game_features(game: BalatroGame) -> dict[str, float]`.
3. Create unit tests in `tests/test_portfolio.py` verifying all 150 jokers are recognized, feature extraction works on arbitrary states, editions are properly counted, and no runtime crashes or RNG stream mutations occur.
4. Run pytest on the new tests and ensure all existing simulator tests and static audits remain green.
5. Write your handoff report to `D:/Optilatro/.agents/teamwork_preview_worker_m2_1/handoff.md` and send a completion message to parent.
