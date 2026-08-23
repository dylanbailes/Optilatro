"""bench/diag_ante1_m14.py — M14 targeting-layer diagnostic over a seed bank.

Runs heuristic_v10 paired with heuristic_v9 on the same bank and, for every
seed, instruments the M14 decision points (worker-local monkeypatching, no
production-code changes):

  plans_ok / plans_none      _blind_plan verdicts across the whole run
  chase_ok / r_keep / r_ev / r_prob
                             _chase_discard commits vs rejection reasons
  buffoon_opens              _buffoon_open_action pre-buys
  plan_hts                   multiset of planned hand types

Prints: win rates, ante-1 deaths per arm, and for the v10 deaths a breakdown
(joker count, planned-type distribution, chase counts, rejection reasons)
plus the seed list, so a follow-up trace can jump straight at the right
seeds. Human-fair: composition-only reads, no lookahead.

Usage:
  python3 bench/diag_ante1_m14.py [--games N] [--seed-start S] [--workers W]
"""
from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import os
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENDOR = ROOT / "vendor" / "balatro-rl"
sys.path.insert(0, str(VENDOR))

from balatro_sim.agent_v9 import HeuristicV9          # noqa: E402
from balatro_sim.agent_v10 import HeuristicV10         # noqa: E402
from balatro_sim.game import BalatroGame               # noqa: E402
from balatro_sim.rollout import rollout                # noqa: E402
from balatro_sim import agent_v10 as v10               # noqa: E402


def _instrument():
    """Wrap the three M14 entry points, tallying verdicts into a dict."""
    tally = {
        "plans_ok": 0, "plans_none": 0, "chase_ok": 0,
        "r_keep": 0, "r_ev": 0, "r_prob": 0,
        "buffoon_opens": 0, "plan_hts": Counter(), "plan_probs": [],
    }

    orig_plan = v10._blind_plan
    orig_chase = v10._chase_discard
    orig_open = v10._buffoon_open_action

    def plan(game, ts):
        p = orig_plan(game, ts)
        if p is None:
            tally["plans_none"] += 1
        else:
            tally["plans_ok"] += 1
            tally["plan_hts"][p["ht"]] += 1
            tally["plan_probs"].append(round(p["prob"], 3))
        return p

    def chase(game, pl, base):
        keep = v10._plan_keep_indices(game.hand, pl)
        if game.discards_left <= 0 or not game.deck or len(game.hand) < 2:
            return orig_chase(game, pl, base)
        if not keep:
            tally["r_keep"] += 1
            return None
        act = orig_chase(game, pl, base)
        if act is None:
            # distinguish EV vs PROB rejections the way the source does
            if pl["prob"] * pl["S"] < base * v10.V10_PARAMS[
                    "chase_min_ev_gain"]:
                tally["r_ev"] += 1
            else:
                tally["r_prob"] += 1
        else:
            tally["chase_ok"] += 1
        return act

    def opengame(game):
        a = orig_open(game)
        if a is not None:
            tally["buffoon_opens"] += 1
        return a

    return tally, plan, chase, opengame


def _run_one(args):
    policy_name, seed, params = args
    tally, f_plan, f_chase, f_open = _instrument()
    v10._blind_plan, v10._chase_discard, v10._buffoon_open_action = \
        f_plan, f_chase, f_open
    game = BalatroGame(seed=seed, rng_mode="seed")
    pol = (HeuristicV10(params=params) if policy_name == "heuristic_v10"
           else HeuristicV9())
    res = rollout(game, pol)
    res["seed"] = seed
    st = res.get("stats") or {}
    res["_m14"] = {
        **{k: v for k, v in tally.items() if k != "plan_hts"},
        "plan_hts": dict(tally["plan_hts"]),
        "jokers": len(st.get("jokers_bought", ()) or ()),
        "packs": st.get("packs_bought", 0),
        "dollars": res.get("dollars", 0),
        "death_blind": getattr(getattr(game, "current_blind", None),
                               "key", None),
        "target": getattr(getattr(game, "current_blind", None),
                          "chips_target", 0),
        "scored": getattr(getattr(game, "current_blind", None),
                          "chips_scored", 0),
    }
    return res


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=200)
    ap.add_argument("--seed-start", type=int, default=0)
    ap.add_argument("--workers", type=int,
                    default=max(1, (os.cpu_count() or 1) // 2))
    ap.add_argument("--params", type=str, default=None)
    args = ap.parse_args()
    params = json.loads(args.params) if args.params else None

    jobs = [("heuristic_v10", s, params)
            for s in range(args.seed_start, args.seed_start + args.games)]
    ctx = mp.get_context("spawn")
    results = []
    with ctx.Pool(args.workers) as pool:
        for i, r in enumerate(pool.imap_unordered(_run_one, jobs)):
            results.append(r)
            if (i + 1) % 50 == 0:
                print(f"  {i + 1}/{len(jobs)}", flush=True)

    deaths = [r for r in results if not r["won"] and r["ante"] <= 1]
    wins = sum(1 for r in results if r["won"])
    print(f"\nv10+M14: wins {wins}/{len(results)} = "
          f"{100.0 * wins / len(results):.2f}% | "
          f"ante-1 deaths {len(deaths)}")

    def agg(rs, key, default=0):
        vals = [r["_m14"][key] for r in rs]
        return sum(vals) / max(1, len(vals))

    print("\nM14 activity, deaths vs survivors:")
    print(f"  {'':16}{'deaths':>10}{'survivors':>11}")
    for k in ("plans_ok", "plans_none", "chase_ok", "r_keep", "r_ev",
              "r_prob", "buffoon_opens"):
        print(f"  {k:16}{agg(deaths, k):>10.2f}"
              f"{agg([r for r in results if r not in deaths], k):>11.2f}")

    ht_deaths = Counter()
    for r in deaths:
        ht_deaths.update(r["_m14"]["plan_hts"])
    print(f"\nplanned types overall (deaths): {dict(ht_deaths)}")
    print(f"joker-count of deaths: "
          f"{dict(Counter(min(r['_m14']['jokers'], 4) for r in deaths))}")
    print(f"death blinds: "
          f"{dict(Counter(r['_m14']['death_blind'] for r in deaths))}")
    print(f"mean $ at death: {agg(deaths, 'dollars'):.1f}, "
          f"mean shortfall: "
          f"{[max(0, r['_m14']['target'] - r['_m14']['scored']) for r in deaths] and sum(max(0, r['_m14']['target'] - r['_m14']['scored']) for r in deaths) / len(deaths):.0f}")
    print(f"\ndeath seeds: {sorted(r['seed'] for r in deaths)}")


if __name__ == "__main__":
    main()
