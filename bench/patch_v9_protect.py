"""bench/patch_v9_protect.py - one-shot M14h patch for agent_v9.py.

The Vly str_replace tool cannot match inside agent_v9.py (byte-exact anchors
verified present fail), so this script applies the three additive edits with
hard assertions: every anchor must occur EXACTLY once or nothing is written.
Idempotent: re-running on an already-patched file is a no-op.
"""
from pathlib import Path

P = Path("vendor/balatro-rl/balatro_sim/agent_v9.py")
src = P.read_text()

SIG_OLD = ("def best_discard(game, max_size=None, pool_size=None, "
           "base_score=None):")
SIG_NEW = ("def best_discard(game, max_size=None, pool_size=None, "
           "base_score=None,\n                 protect=None):")

DOC_ANCHOR = ("costs one full scored_plays per discard decision (~141/run, "
              "the biggest\n    redundancy in the hot loop).\n    \"\"\"")
DOC_NEW = ("costs one full scored_plays per discard decision (~141/run, "
           "the biggest\n    redundancy in the hot loop).\n\n"
           "    `protect`: optional set of hand indices that must NEVER enter "
           "a discard\n    candidate. V10 M14h plan protection: with a chase "
           "line committed, the\n    fallback EV discard must not shed the "
           "plan's own cards (seed 5 held\n    four spades under a committed "
           "flush plan; the rank-line structure pool\n    won priority and "
           "the fallback dropped 5S2S on the last discard). None\n"
           "    (default) keeps V9 behaviour byte-identical.\n    \"\"\"")

POOL_OLD = ("        pool = sorted(range(len(hand)),\n"
            "                      key=lambda i: _card_quality(hand[i]))[:pool]\n"
            "    if max_size < 1 or not pool:")
POOL_NEW = ("        pool = sorted(range(len(hand)),\n"
            "                      key=lambda i: _card_quality(hand[i]))[:pool]\n"
            "    if protect:\n"
            "        pool = [i for i in pool if i not in protect]\n"
            "    if max_size < 1 or not pool:")


def apply(s: str, old: str, new: str, what: str) -> str:
    n_old, n_new = s.count(old), s.count(new)
    if n_new and not n_old:
        print(f"  = {what}: already patched")
        return s
    if s.count(old) != 1:
        raise SystemExit(f"FAIL {what}: anchor count={s.count(old)} (want 1)")
    print(f"  + {what}")
    return s.replace(old, new, 1)


src = apply(src, SIG_OLD, SIG_NEW, "signature protect kwarg")
src = apply(src, DOC_ANCHOR, DOC_NEW, "docstring")
src = apply(src, POOL_OLD, POOL_NEW, "pool filter")

P.write_text(src)
print("written", P)
