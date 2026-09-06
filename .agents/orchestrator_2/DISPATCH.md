## 2026-09-03T20:10:17Z
You are the Project Orchestrator (teamwork_preview_orchestrator) for the Optilatro project.

Your assigned working directory is: D:/Optilatro/.agents/orchestrator_2
Workspace root: D:/Optilatro

Read the verbatim user request and requirements at: D:/Optilatro/.agents/ORIGINAL_REQUEST.md (specifically the latest follow-up under `## 2026-09-03T20:10:17Z`).
Also strictly adhere to the contract in: D:/Optilatro/AGENTS.md and docs/STATUS.md.

Task Overview:
Optimize and advance the Optilatro Balatro AI agent to break through the 7.0% win rate ceiling (> 21 wins / 300) and maintain Ante 1 mortality below 4.67% (< 14 deaths / 300) on Red Deck / White Stake under strict human-fair constraints.

Context & Current State:
- Phase 1 (Ante-1 Pace Rule): Implemented in vendor/balatro-rl/balatro_sim/agent_v10.py (ante1_pace_rule). Seeds 205 and 275 clear Ante 1.
- Phase 2 (Portfolio Classification): Implemented in tools/portfolio.py with 6 strategic joker roles and 50 state features.
- Phase 3 (Offline Value Model): Trained on 67,860 samples (holdout AUC 0.7822) in vendor/balatro-rl/balatro_sim/shop_model.json. Pure Python/NumPy inference in <10 µs.
- Phase 4 (L1 Counterfactual Search): Implemented in SearchShopV10._search_shop evaluating ΔV = V(s') - V(s) on _v10_worst_joker_idx.
- Verified Suite: All 1,600+ tests pass (test_agent_v10.py, test_e2e_v10_requirements.py, test_m13_ante1.py), CI exactness gate is clean, and all 4 static audits are clean.
- Empirical Baseline: On Seeds 0–99, Ante 1 death rate dropped to 4.00% and search_shop_v10 won 5/100 (5.00%). Across Seeds 0–299, baseline goal_iter7_final_D.json achieved 20 wins (6.67%) with 14 Ante-1 deaths (4.67%).

Requirements:
- R1. Win-Rate Bridge & Search Tuning: Tune SearchShopV10 swap delta threshold, candidate selection, and synergies with _v10_decide_shop to ensure high-leverage scoring jokers (e.g. Cavendish, Baseball Card, Duo/Trio/Family, Ramen, Stuntman) are consistently secured and transitioned into without selling essential portfolio anchors.
- R2. Deck Reshaping Synergy & Consumable Utilization: Ensure tarot deck-reshaping and spectral/planet usage harmonize with the acquired joker portfolio (e.g. prioritizing Death/Strength on target ranks and Planet cards on primary hand types).
- R3. Human-Fair & Isolation Guarantees: Maintain strict human-fairness: zero peeking at draw order, zero future RNG stream consumption, zero live game mutation during evaluation. test_seed_exactness.py -m ci_gate must stay green.

Acceptance Criteria:
1. Baseline & Integrity:
   - All 1,600+ simulator unit tests pass: `python -m pytest vendor/balatro-rl/tests vendor/balatro-rl/balatro_sim/tests -q`
   - CI seed exactness gate passes: `python -m pytest vendor/balatro-rl/tests/test_seed_exactness.py -m ci_gate -v`
   - All 4 static audits remain clean: `python tools/audit_jokers_static.py`, `python tools/audit_consumables_static.py`, `python tools/audit_bosses_static.py`, `python tools/audit_tags_static.py`
2. Benchmark & Performance Targets:
   - Full benchmark bank (Seeds 0–299 paired against goal_iter7_final_D.json baseline of 20W / 14D):
     - Win rate > 7.0% (> 21 wins out of 300).
     - Ante 1 deaths < 14 (< 4.67%).
   - Out-of-sample holdout bank (Seeds 300–499):
     - Verified generalization showing consistent win rate and low Ante 1 mortality without bank overfitting.

