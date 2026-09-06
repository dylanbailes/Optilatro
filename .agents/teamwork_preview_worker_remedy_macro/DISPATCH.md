## 2026-09-04T23:23:49Z

You are teamwork_preview_worker_remedy_macro.
Working directory: D:/Optilatro/.agents/teamwork_preview_worker_remedy_macro
Your parent is orchestrator_4 (conversation ID: ae7f41b5-88b7-4891-99ec-90a2e8f71801).
Authoritative request: D:/Optilatro/.agents/ORIGINAL_REQUEST.md (YOU MUST READ THIS FIRST).
Scope document: D:/Optilatro/PROJECT.md

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A teamwork_preview_auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

Task:
Implement targeted macro remedies in vendor/balatro-rl/balatro_sim/agent_v10.py and vendor/balatro-rl/balatro_sim/agent_v9.py to address the failure modes identified from the 300-seed loss telemetry:

1. Macro Remedy 1: Ante-1 Economy Joker Gating (agent_v10.py)
In `_v10_rank_shop_items`:
When `game.ante == 1`:
The agent must NOT purchase non-scoring / pure economy jokers (`j_rocket`, `j_golden`, `j_business`, `j_credit_card`, `j_cloud_9`, `j_satellite`, `j_egg`) unless the player already owns at least one combat scoring joker (`_has_scoring_joker(game, ref)`).
If `game.ante == 1 and not _has_scoring_joker(game, ref)` and `item.key in ("j_rocket", "j_golden", "j_business", "j_credit_card", "j_cloud_9", "j_satellite", "j_egg")`:
assign negative value (e.g. `value = -1.0` or `continue`).
Ensure pure economy jokers never receive an engineless urgency bonus in Ante 1.
(This directly fixes the Ante-1 economy trap where 11/17 Ante-1 deaths occurred from buying useless economy cards before securing combat chips/mult).

2. Macro Remedy 2: Mid-Game Deficit Capital Deployment (agent_v10.py)
In `_v10_decide_shop`:
Currently, `is_urgent_late = game.ante >= 6`.
Extend adaptive deficit capital deployment to Antes 4 and 5 when the engine is in a scoring deficit (`forecast_score < boss_target * 1.15` and lacking strong xmult):
Define `is_urgent_mid = (game.ante in (4, 5)) and (forecast_score < boss_target * 1.15)`.
- When `is_urgent_mid`:
  - In Ante 4: relax interest floor to $15 (instead of $25), allow up to 2-3 rerolls down to `min_reserve = 6`.
  - In Ante 5: relax interest floor to $10 (instead of $25), allow up to 3-4 rerolls down to `min_reserve = 6`.
  - Ensure `if (not save_mode or is_urgent_late or is_urgent_mid) and ...` allows rerolling and shopping when in deficit.
- In Ante 6: relax interest floor to $5 when in deficit.
- In Ante 7-8: relax interest floor to $0 when in deficit (or in Ante 8 always).
(This directly fixes the Mid-Game Scaling Cliff where 110 runs died across Antes 4-5 hoarding $25 cash without shopping).

3. Macro Remedy 3: Latent `_EvalGame` Defect (agent_v9.py)
In `vendor/balatro-rl/balatro_sim/agent_v9.py`:
In class `_EvalGame`:
- Add `'run_hand_counts'` to `__slots__`.
- In `__init__`, add:
  `self.run_hand_counts = dict(game.run_hand_counts) if hasattr(game, 'run_hand_counts') and game.run_hand_counts else {}`
- In `.copy()`, add:
  `c.run_hand_counts = dict(self.run_hand_counts)`
(This prevents crashes during hand scoring evaluation if `j_supernova` is owned).

4. Run Verification Suite:
- `python -m pytest tests/test_challenger_m2_gen4.py tests/test_challenger_m2_gen5.py -v`
- `python -m pytest vendor/balatro-rl/tests vendor/balatro-rl/balatro_sim/tests -q`
- `python -m pytest vendor/balatro-rl/tests/test_seed_exactness.py -m ci_gate -v`
- Run all 4 static audits:
  `python tools/audit_jokers_static.py`
  `python tools/audit_consumables_static.py`
  `python tools/audit_bosses_static.py`
  `python tools/audit_tags_static.py`

Write your comprehensive implementation report to D:/Optilatro/.agents/teamwork_preview_worker_remedy_macro/handoff.md and report back with your findings and test output.
