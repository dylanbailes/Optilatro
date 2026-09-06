## 2026-09-04T23:39:19-07:00
Perform independent code review of vendor/balatro-rl/balatro_sim/agent_v10.py and vendor/balatro-rl/balatro_sim/agent_v9.py for Correctness, Unit Test Compliance, and Strict Human-Fairness.
1. Read D:/Optilatro/.agents/ORIGINAL_REQUEST.md and D:/Optilatro/PROJECT.md.
2. Review the macro remedies implemented:
   - Ante-1 pure economy joker gating in _v10_rank_shop_items (when not _has_scoring_joker, j_rocket, j_golden, j_business, j_credit_card, j_cloud_9, j_satellite, j_egg are excluded).
   - Mid-game deficit capital deployment in _v10_decide_shop (is_urgent_mid in Antes 4-5 when forecast_score < boss_target * 1.15; relaxed interest floors  and  with min_reserve = 6).
   - _EvalGame run_hand_counts attribute completeness in agent_v9.py.
3. Verify strict human-fairness: zero peeking at future draw order, zero future shop/boss RNG consumption, zero live game mutation during evaluation.
4. Run all simulator unit tests:
   python -m pytest vendor/balatro-rl/tests vendor/balatro-rl/balatro_sim/tests -q
5. Run CI seed exactness gate:
   python -m pytest vendor/balatro-rl/tests/test_seed_exactness.py -m ci_gate -v
6. Run 4 static audits:
   python tools/audit_jokers_static.py
   python tools/audit_consumables_static.py
   python tools/audit_bosses_static.py
   python tools/audit_tags_static.py
7. Write your detailed review and findings to D:/Optilatro/.agents/teamwork_preview_reviewer_final_macro/handoff.md.
8. State an explicit verdict at the top of your handoff: APPROVE or REQUEST_CHANGES.
9. Send message to parent with your verdict and summary.
