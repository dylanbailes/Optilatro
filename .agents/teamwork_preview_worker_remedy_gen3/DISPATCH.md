# Dispatch Log

## 2026-09-04T07:34:56Z

You are Worker Remediation (Milestone M1 Iteration 2).
Your working directory is: D:/Optilatro/.agents/teamwork_preview_worker_remedy_gen3

MANDATORY FIRST STEP: Read the authoritative request at D:/Optilatro/.agents/ORIGINAL_REQUEST.md.

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A teamwork_preview_auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

WRITE OWNERSHIP:
You exclusively own `vendor/balatro-rl/balatro_sim/agent_v10.py` and test files.

CONTEXT & PROBLEM STATEMENT:
Iteration 1 verification revealed two specific defects:
1. **Critical Deadlock Bug (Challenger 1)**:
   In `agent_v10.py`, inside `tier2_value` (around line 2824), discard candidates are generated and returned even when `game.discards_left == 0`. When holding discard-incentive jokers (e.g. Faceless Joker) with high clear probability, `tier2_value` returns `{'type': 'discard'}`, which `BalatroGame._discard` silently drops because `discards_left <= 0`. This causes an infinite deadlock loop (empirically reproduced on seeds 10001 and 10004 in `tools/stress_m1_challenger.py`).
   **Fix**: Wrap the entire discard candidate generation block in `tier2_value` inside `if game.discards_left > 0:`.
2. **Scaling Acceleration Blind-Throw Bug (Challenger 2)**:
   In `_find_scaling_action`, Tier S2 allowed playing non-knockout scaling cards whenever `p_clear >= 0.995` without reserving a guaranteed knockout in hand. Across 300 seeds, this burned 3 consecutive hands for +1 mult and threw 23 blinds, dropping wins to 21 and causing a death on Seed 245 in Ante 1.
   **Diagnostic Ablation Proved**: Simply disabling scaling acceleration raised wins to **29 wins (9.67%)** and kept Ante 1 deaths at **11 (3.67%)**!
   **Fix**:
   - Strictly disallow scaling acceleration in Ante 1: `if game.ante <= 1: return None`.
   - Remove loose probabilistic Tier S2 scaling (`or (p_clear is not None and p_clear >= 0.995)`).
   - Enforce **strict Tier S1 disjoint in-hand knockout reservation ONLY**:
     There MUST exist a valid clearing combination $K$ in hand ($score(K) \ge target$), AND the candidate scaling play $C$ must be a subset of $\text{hand} \setminus K$ so that the clearing play $K$ remains 100% intact in hand for the next turn.
   - Enforce `game.hands_left >= 3` (so at least 2 hands remain after the scaling play).
   - Cap scaling acceleration to at most **1 scaling play per blind** (`if game.hands_left < game.base_hands: return None` or check `game.hands_played == 0`).
3. **Win-Rate Bridge (Pushing 29 to >= 30 Wins / 10.0%+)**:
   - In `_v10_decide_shop`:
     - Ensure `_v10_worst_joker_idx` aggressively identifies dead/redundant economy jokers (`j_egg`, `j_ticket`, `j_todo_list`, `j_faceless`, `j_delayed_grat`, `j_golden`, `j_business_card`) when a premier finisher or xMult is available.
     - In Ante 7 and Ante 8, if score forecast is in deficit against the upcoming boss, ensure reroll pacing aggressively pursues xMult jokers (`j_cavendish`, `j_duo`, `j_trio`, `j_family`, `j_order`, `j_tribe`, `j_card_sharp`, `j_baseball`, `j_acrobat`, `j_constellation`, `j_hologram`, `j_blueprint`, `j_brainstorm`, `j_baron`, `j_ancient`).

VERIFICATION REQUIREMENTS:
1. `python tools/stress_m1_challenger.py` must pass with 0 failures and 0 deadlocks across all 25 rollout games.
2. `python -m pytest vendor/balatro-rl/tests/test_scaling_acceleration.py -v` must pass.
3. `python -m pytest vendor/balatro-rl/tests/test_agent_v10.py -v` must pass.
4. `python -m pytest vendor/balatro-rl/tests/test_seed_exactness.py -m ci_gate -v` must pass.
5. All 4 static audits (`audit_jokers_static.py`, `audit_consumables_static.py`, `audit_bosses_static.py`, `audit_tags_static.py`) must be CLEAN.
6. Full test suite: `python -m pytest vendor/balatro-rl/tests vendor/balatro-rl/balatro_sim/tests -q` must pass.
