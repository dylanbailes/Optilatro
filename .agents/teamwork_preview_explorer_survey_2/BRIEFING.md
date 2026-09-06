# BRIEFING — 2026-09-02T21:40:43Z

## Mission
Investigate Jokers, Portfolio & Shop Search architecture for Optilatro, surveying joker categorization/metadata, shop search implementation (agent_v9, agent_l1, agent_v10), rollout engine, counterfactual shop state evaluation, and contract compliance.

## 🔒 My Identity
- Archetype: explorer
- Roles: investigation, synthesis
- Working directory: D:/Optilatro/.agents/teamwork_preview_explorer_survey_2
- Original parent: 33771d4d-7ec7-45ea-b68e-fcd71b668242
- Milestone: Step 0 Survey

## 🔒 Key Constraints
- Read-only investigation — do NOT implement
- Decorator-only joker registration, no engine scans
- Human-fair shop evaluation (no peeking at draw order, isolated eval uses throwaway seed-0 RNG, no mutating live game)
- agent_v9.py is frozen baseline, new in-blind behavior in agent_v10.py

## Current Parent
- Conversation ID: 33771d4d-7ec7-45ea-b68e-fcd71b668242
- Updated: 2026-09-02T21:40:43Z

## Investigation State
- **Explored paths**:
  - `vendor/balatro-rl/balatro_sim/jokers/` (`base.py`, `__init__.py`, `chips.py`, `mult.py`, `misc.py`, etc.)
  - `tools/portfolio.py`
  - `tools/gen_shop_dataset.py`, `tools/fit_shop_model.py`
  - `vendor/balatro-rl/balatro_sim/agent_v9.py`, `agent_l1.py`, `agent_v10.py`
  - `vendor/balatro-rl/balatro_sim/rollout.py`
  - `tools/audit_*_static.py` and `vendor/balatro-rl/tests/test_seed_exactness.py`
- **Key findings**:
  - Joker capability flags (`retriggers_held`, `free_planets`, `disables_bosses`, `doubles_lucky`, `debt`, `allow_dupes`) replace engine scans; NOSCAN and all 8 static audit gates clean.
  - `tools/portfolio.py` implements 6-role classification and 42-feature state vector extraction from explicit parameters, enabling sub-microsecond counterfactual $f(s')$ evaluation without cloning games.
  - Previous L1 shop search in `agent_l1.py` / `agent_v10.py` was byte-identical to L0 because both used greedy first-accept over `_rank_shop_items`.
  - Offline logistic value model $V(s') \to P(\text{Win})$ trained on rollout transitions with non-linear interaction terms provides the missing counterfactual evaluation metric $\Delta V(a) = V(s') - V(s)$.
- **Unexplored areas**: None for this survey scope.

## Key Decisions Made
- Structured the complete findings into `handoff.md` with 5 standard sections.

## Artifact Index
- D:/Optilatro/.agents/teamwork_preview_explorer_survey_2/DISPATCH.md — Incoming request record
- D:/Optilatro/.agents/teamwork_preview_explorer_survey_2/progress.md — Liveness & progress tracker
- D:/Optilatro/.agents/teamwork_preview_explorer_survey_2/handoff.md — Final structured report
