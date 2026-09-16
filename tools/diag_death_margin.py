"""tools/diag_death_margin.py — how close are the deaths?

Replays a policy over a deterministic seed bank and, for every lost run,
records the *fatal blind*: its chip target, the chips actually reached, the
hands/discards spent, and the largest single-hand score in that blind.

The point is to size the prize: if most deaths land at 80-99% of the target, a
modest board-power gain converts them into wins; if they land at 10-40%, the
fix has to be structural (shop/build quality), not endgame tuning.

Usage:
  python tools/diag_death_margin.py [--policy v10|v11] [--seeds 10500-10799]
                                    [--workers 16]
"""
from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import sys
from collections import Counter
from pathlib import Path
from statistics import mean, median

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "vendor" / "balatro-rl"))


def _trace(job) -> dict:
    policy_name, seed = job
    from balatro_sim.game import BalatroGame
    from balatro_sim.agent_v10 import SearchShopV10
    from balatro_sim.agent_v11 import SearchShopV11

    pol = SearchShopV10() if policy_name == "v10" else SearchShopV11()
    g = BalatroGame(seed=seed, rng_mode="seed")

    fatal = None
    cur = None          # (ante, blind_idx) of the blind being played
    hands_used = 0
    discards_used = 0
    best_hand = 0
    step = 0
    while g.state.name != "GAME_OVER" and step < 100_000:
        step += 1
        key = (g.ante, g.blind_idx)
        if g.state.name == "SELECTING_HAND":
            if cur != key:
                cur, hands_used, discards_used, best_hand = key, 0, 0, 0
                fatal = {
                    "ante": g.ante, "blind": g.blind_idx,
                    "kind": g.current_blind.kind,
                    "target": g.current_blind.chips_target,
                    "hands_base": g.hands_left, "disc_base": g.discards_left,
                }
            act = pol.decide(g)
            before = g.chips_scored
            hands_used += 1
            g.step(act)
            best_hand = max(best_hand, g.chips_scored - before)
        else:
            g.step(pol.decide(g))

    if fatal is None:
        return {"seed": seed, "won": g.ante > 8, "ante": g.ante}
    won = bool(g.ante > 8 and g.state.name == "GAME_OVER")
    fatal["reached"] = g.chips_scored
    fatal["hands_used"] = hands_used
    fatal["discards_used"] = discards_used
    fatal["best_hand"] = best_hand
    fatal["dollars"] = g.dollars
    return {"seed": seed, "won": won, "ante": g.ante, "fatal": fatal}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--policy", default="v10", choices=("v10", "v11"))
    ap.add_argument("--seeds", default="10500-10799")
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    lo, hi = (int(x) for x in args.seeds.split("-"))
    seeds = list(range(lo, hi + 1))
    jobs = [(args.policy, s) for s in seeds]
    ctx = mp.get_context("spawn")
    with ctx.Pool(args.workers) as pool:
        out = list(pool.imap_unordered(_trace, jobs, chunksize=1))
    out.sort(key=lambda r: r["seed"])

    deaths = [r for r in out if not r["won"]]
    print(f"policy={args.policy} n={len(out)} wins={len(out)-len(deaths)} "
          f"({100.0*(len(out)-len(deaths))/len(out):.1f}%)")

    # Shortfall buckets by ante
    print("\nfatal-blind completion (reached / target), all deaths")
    print(f"  {'ante':>4} {'n':>4} {'median%':>8} {'mean%':>7} "
          f"{'>=90%':>6} {'>=75%':>6} {'<50%':>6}")
    for a in range(1, 9):
        g = [r for r in deaths if r["fatal"]["ante"] == a]
        if not g:
            continue
        pcts = [100.0 * r["fatal"]["reached"] / r["fatal"]["target"] for r in g]
        print(f"  {a:>4} {len(g):>4} {median(pcts):>8.1f} {mean(pcts):>7.1f} "
              f"{sum(1 for p in pcts if p>=90):>6} "
              f"{sum(1 for p in pcts if p>=75):>6} "
              f"{sum(1 for p in pcts if p<50):>6}")

    # One-hand-short analysis: could an extra hand of the best observed score clear it?
    print("\ncould ONE more hand (at the fatal blind's best single-hand score) clear it?")
    for a in range(1, 9):
        g = [r for r in deaths if r["fatal"]["ante"] == a]
        if not g:
            continue
        need_hand = [r["fatal"]["target"] - r["fatal"]["reached"] for r in g]
        yes = sum(1 for r in g
                  if r["fatal"]["best_hand"] * 1.25 >= r["fatal"]["target"] - r["fatal"]["reached"])
        yes1 = sum(1 for r in g
                   if r["fatal"]["best_hand"] >= r["fatal"]["target"] - r["fatal"]["reached"])
        print(f"  ante {a:>2} n={len(g):>3}  short by median {median(need_hand):>8.0f} "
              f"(best hand median {median(r['fatal']['best_hand'] for r in g):>8.0f})  "
              f"reachable with +1 best hand: {yes1:>3}  with +1.25x best hand: {yes:>3}")

    print("\nhands/discards actually used on the fatal blind (mean)")
    for a in range(1, 9):
        g = [r for r in deaths if r["fatal"]["ante"] == a]
        if not g:
            continue
        print(f"  ante {a:>2} n={len(g):>3} hands_base {mean(r['fatal']['hands_base'] for r in g):.1f} "
              f"used {mean(r['fatal']['hands_used'] for r in g):.1f} | "
              f"disc_base {mean(r['fatal']['disc_base'] for r in g):.1f} "
              f"used {mean(r['fatal']['discards_used'] for r in g):.1f} | "
              f"$ {mean(r['fatal']['dollars'] for r in g):.1f}")

    print("\ndeath kind x ante (largest buckets)")
    c = Counter((r["fatal"]["ante"], r["fatal"]["kind"]) for r in deaths)
    for k, n in c.most_common(12):
        print(f"   ante {k[0]} {k[1]:<5} {n}")

    if args.out:
        Path(args.out).write_text(json.dumps(out, indent=1, default=str),
                                  encoding="utf-8")
        print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
