"""tools/diag_ceiling.py — research-only ceiling probe for specific seeds.

Replays the given seeds with the lookahead shop search (draw-order peek,
NOT human-fair) to measure how many death seeds are winnable at all.

Usage:
  python tools/diag_ceiling.py --report vendor/balatro-rl/results/goal_base.json
      [--policy heuristic_v10] [--antes 1] [--search-shops 3]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "vendor" / "balatro-rl"))

from balatro_sim.agent_l1 import SearchShopV9  # noqa: E402
from balatro_sim.agent_v10 import SearchShopV10  # noqa: E402
from balatro_sim.game import BalatroGame  # noqa: E402
from balatro_sim.rollout import rollout  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", required=True)
    ap.add_argument("--policy", default="heuristic_v10")
    ap.add_argument("--antes", default="1")
    ap.add_argument("--search-shops", type=int, default=3)
    args = ap.parse_args()

    raw = json.load(open(args.report, encoding="utf-8"))
    runs = raw[args.policy]["results"]
    want = {int(a) for a in args.antes.split(",")}
    seeds = sorted(r["seed"] for r in runs if not r["won"] and r["ante"] in want)

    wins = 0
    for seed in seeds:
        game = BalatroGame(seed=seed, rng_mode="seed")
        policy = SearchShopV10(search_shops=args.search_shops, lookahead=True)
        res = rollout(game, policy)
        wins += res["won"]
        print(f"seed {seed:>3}: {'WIN' if res['won'] else 'loss'} "
              f"(ante {res['ante']})", flush=True)
    print(f"\nceiling: {wins}/{len(seeds)} winnable with lookahead")


if __name__ == "__main__":
    main()
