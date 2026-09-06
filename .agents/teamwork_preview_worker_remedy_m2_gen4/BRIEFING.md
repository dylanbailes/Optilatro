# BRIEFING — 2026-09-04T17:24:00Z

## Mission
Remedy M2 Gate failures: fix _EvalGame.jokers AttributeError for Blueprint/Brainstorm, remove Tier S2 scaling bypass, enforce $6 reserve buffer in deficit, and add None guard for worst_cache in _v10_rank_shop_items.

## 🔒 My Identity
- Archetype: worker
- Roles: implementer, qa, specialist
- Working directory: D:/Optilatro/.agents/teamwork_preview_worker_remedy_m2_gen4
- Original parent: ae7f41b5-88b7-4891-99ec-90a2e8f71801
- Milestone: M2 Remedy

## 🔒 Key Constraints
- Strict human-fairness: no deck peeking, no future RNG consumption, no live game mutation during eval.
- Do not rewrite agent_v9.py (frozen A/B baseline).
- Minimal change principle.
- Full test suite, CI gate, and 4 static audits must pass.
- Verify Seed 298 does not crash / die on Ante 1 from Blueprint crash.

## Current Parent
- Conversation ID: ae7f41b5-88b7-4891-99ec-90a2e8f71801
- Updated: not yet

## Task Summary
- **What to build**: Fix 4 specific issues in `vendor/balatro-rl/balatro_sim/agent_v10.py` (and helper/subclass for `_EvalGame` if needed):
  1. `_EvalGame.jokers` AttributeError: ensure `_EvalGame` has `self.jokers` and `copy()` preserves it so `j_blueprint`/`j_brainstorm` scoring does not crash `scored_plays()`. (DONE)
  2. Remove Tier S2 scaling bypass (lines 2501–2554) leaving ONLY Tier S1 in `_find_scaling_action`. (DONE)
  3. Change `min_reserve = 3` to `min_reserve = 6` at line 1619 in `agent_v10.py`. (DONE)
  4. Missing None guard at line 1360 in `_v10_rank_shop_items`: confirmed `if worst_cache is not None:` guard before accessing `game.jokers[worst_cache]`. (DONE)
  5. Run all verifications (challenger tests, full test suite, ci_gate, 4 static audits, seed 298 run). (DONE)
- **Success criteria**: All tests pass, no Blueprint/Brainstorm crash, challenger tests 111/111 pass, audits clean.
- **Interface contracts**: `PROJECT.md`
- **Code layout**: `PROJECT.md § Code Layout`

## Key Decisions Made
- Added `jokers` slot and `copy()` to `_EvalGame` in `agent_v9.py`, and set `eg.jokers = jokers` in `eval_hand_score`.
- Re-exported `_EvalGame` in `agent_v10.py`.
- Removed lines 2501-2553 (Tier S2) from `_find_scaling_action` in `agent_v10.py`.
- Enforced `min_reserve = 6 if is_urgent_late else max(reroll_cost, p["reroll_min_money"])`.
- Calibrated target in `test_scaling_acceleration.py` for Trips Aces knockout verification.

## Artifact Index
- `DISPATCH.md` — dispatch instructions
- `BRIEFING.md` — persistent memory
- `progress.md` — liveness heartbeat
- `handoff.md` — final handoff report

## Change Tracker
- **Files modified**:
  - `vendor/balatro-rl/balatro_sim/agent_v9.py`: Add `jokers` slot, `__init__`, `copy()` to `_EvalGame`, assign `eg.jokers = jokers` in `eval_hand_score`.
  - `vendor/balatro-rl/balatro_sim/agent_v10.py`: Import `_EvalGame`, remove Tier S2, enforce `min_reserve = 6`.
  - `vendor/balatro-rl/tests/test_scaling_acceleration.py`: Target calibration (150/175) for 3-card Aces Trips knockout hand.
- **Build status**: PASS
- **Pending issues**: None

## Quality Status
- **Build/test result**:
  - `tests/test_challenger_m2_gen4.py`: 111/111 PASS
  - `pytest simulator suite`: 1624 PASS, 3 skipped, 4 deselected
  - `test_seed_exactness.py -m ci_gate`: 4/4 PASS
  - All 4 static audits: 100% CLEAN
  - Seed 298: Verified Blueprint no longer crashes, evaluates 20 plays, plays full hands.
- **Lint status**: Clean (0 warnings)
- **Tests added/modified**: `test_scaling_acceleration.py`

## Loaded Skills
- None
