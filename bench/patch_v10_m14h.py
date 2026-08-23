"""bench/patch_v10_m14h.py - one-shot M14h wiring for agent_v10.py.

Same rationale as patch_v9_protect.py: applies the three edits with hard
assertions (each anchor exactly once, idempotent on re-run).
"""
from pathlib import Path

P = Path("vendor/balatro-rl/balatro_sim/agent_v10.py")
src = P.read_text()

HOIST_OLD = """    if (not good_hand and chase_ok and game.discards_left > 0
            and len(game.deck) > 0):
        plan = _committed_plan(game, type_scores)
        if plan is not None:"""
HOIST_NEW = """    # Resolve the committed plan ONCE per decision (M14h): the chase branch
    # consumes it directly, and the fallback branches need its keep-set for
    # protection even when the consec guard blocks another chase commit.
    plan = None
    if (not good_hand and game.discards_left > 0 and len(game.deck) > 0
            and V10_PARAMS["target_enabled"]):
        plan = _committed_plan(game, type_scores)
    protect = None
    if plan is not None and V10_PARAMS["fallback_protect_plan"]:
        protect = set(_plan_keep_indices(game.hand, plan)) or None
    if (not good_hand and chase_ok and game.discards_left > 0
            and len(game.deck) > 0):
        if plan is not None:"""

HOLD_OLD = """                return act

    if (not good_hand and game.discards_left > 0 and len(game.deck) > 0
            and p["discard_hold_until_clear"] and game.hands_left >= 2):
        dset, dscore = best_discard(game, base_score=best_score)
        if dset:"""
HOLD_NEW = """                return act

    if (not good_hand and game.discards_left > 0 and len(game.deck) > 0
            and p["discard_hold_until_clear"] and game.hands_left >= 2):
        dset, dscore = best_discard(game, base_score=best_score,
                                    protect=protect)
        if dset:"""

SLACK_OLD = """        dset, dscore = best_discard(game, base_score=best_score)
        if dscore > best_score * p["discard_slack"]:
            return {"type": "discard", "cards": list(dset)}

    _reset_chase(game)"""
SLACK_NEW = """        dset, dscore = best_discard(game, base_score=best_score,
                                    protect=protect)
        if dscore > best_score * p["discard_slack"]:
            return {"type": "discard", "cards": list(dset)}

    _reset_chase(game)"""


def apply(s: str, old: str, new: str, what: str) -> str:
    n_old, n_new = s.count(old), s.count(new)
    if n_new and not n_old:
        print(f"  = {what}: already patched")
        return s
    if s.count(old) != 1:
        raise SystemExit(f"FAIL {what}: anchor count={s.count(old)} (want 1)")
    print(f"  + {what}")
    return s.replace(old, new, 1)


src = apply(src, HOIST_OLD, HOIST_NEW, "plan hoist + protect")
src = apply(src, HOLD_OLD, HOLD_NEW, "hold-branch protect")
src = apply(src, SLACK_OLD, SLACK_NEW, "slack-branch protect")

P.write_text(src)
print("written", P)
