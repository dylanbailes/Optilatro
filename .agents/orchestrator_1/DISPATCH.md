## 2026-09-02T21:38:11Z
You are the Project Orchestrator (teamwork_preview_orchestrator) for the Optilatro project.

Your assigned working directory is: D:/Optilatro/.agents/orchestrator_1
Workspace root: D:/Optilatro

Read the verbatim user request and requirements at: D:/Optilatro/.agents/ORIGINAL_REQUEST.md
Also strictly adhere to the contract in: D:/Optilatro/AGENTS.md and docs/STATUS.md.

Task Overview:
Implement an end-to-end improvement for Optilatro search-first Balatro AI to break the 7% win rate and 5% Ante 1 death ceiling on Red Deck / White Stake under strict human-fair constraints.
- R1. Ante-1 In-Blind Multi-Hand Pace Rule in vendor/balatro-rl/balatro_sim/agent_v10.py
- R2. Joker Portfolio Classification & State Feature Extraction in tools/portfolio.py
- R3. Rollout Dataset Generation & Offline Value Model in tools/gen_shop_dataset.py, tools/fit_shop_model.py, vendor/balatro-rl/balatro_sim/shop_model.json
- R4. True L1 Counterfactual Shop Search (SearchShopV10) in agent_v10.py / agent_l1.py

Acceptance Criteria:
1. Baseline & Integrity:
   - All 1,562+ simulator unit tests pass: `python -m pytest vendor/balatro-rl/tests vendor/balatro-rl/balatro_sim/tests -q`
   - CI seed exactness gate passes: `python -m pytest vendor/balatro-rl/tests/test_seed_exactness.py -m ci_gate -v`
   - Static audits remain clean: `python tools/audit_jokers_static.py`, `python tools/audit_consumables_static.py`, `python tools/audit_bosses_static.py`, `python tools/audit_tags_static.py`
   - Strictly human-fair: no peeking at deck draw order or future shop/boss RNG streams.
2. Benchmark & Performance Targets:
   - Ante 1 Small Blind fatal seeds (seed 205 and seed 275) clear Ante 1 successfully.
   - Dev bank (seeds 0–199 paired A/B): Win rate >= 8.0% and Ante 1 death rate < 5.0%.
   - Full benchmark bank (seeds 0–299 paired against goal_iter7_final_D.json baseline of 20W / 14D): Win rate > 7.0% (> 21 wins) and Ante 1 deaths < 14 (< 4.67%).
   - Out-of-sample holdout bank (seeds 300–499 and 500–699): Verified generalization.
