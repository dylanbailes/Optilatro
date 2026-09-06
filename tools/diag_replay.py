"""tools/diag_replay.py — replay death seeds and dump end-of-run board state.

Usage:
  python tools/diag_replay.py --report vendor/balatro-rl/results/goal_base.json
      [--policy heuristic_v10] [--antes 1,2] [--detail-antes 1]
      [--params '{"k": v}']

Prints one line per death for --antes antes (full detail for --detail-antes),
plus aggregate boss-key / close-miss histograms for the rest.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "vendor" / "balatro-rl"))

from balatro_sim.agent_v10 import HeuristicV10  # noqa: E402
from balatro_sim.game import BalatroGame  # noqa: E402
from balatro_sim.rollout import rollout  # noqa: E402


def replay(seed: int, params=None) -> dict:
    game = BalatroGame(seed=seed, rng_mode="seed")
    policy = HeuristicV10(params=params)
    res = rollout(game, policy)
    blind = game.current_blind
    return {
        "seed": seed,
        "won": res["won"],
        "ante": game.ante,
        "kind": blind.kind if game.state.name != "GAME_OVER" else res["death_kind"],
        "boss": blind.boss_key or blind.name,
        "target": blind.chips_target,
        "scored": game.chips_scored,
        "hands": game.hands_left,
        "discards": game.discards_left,
        "dollars": game.dollars,
        "jokers": [j.key for j in game.jokers],
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", required=True)
    ap.add_argument("--policy", default="heuristic_v10")
    ap.add_argument("--antes", default="1")
    ap.add_argument("--detail-antes", default="1")
    ap.add_argument("--params", default=None)
    args = ap.parse_args()

    raw = json.load(open(args.report, encoding="utf-8"))
    runs = raw[args.policy]["results"]
    params = json.loads(args.params) if args.params else None
    want = {int(a) for a in args.antes.split(",")}
    detail = {int(a) for a in args.detail_antes.split(",")}

    deaths = [r for r in runs if not r["won"] and r["ante"] in want]
    rows = [replay(r["seed"], params) for r in sorted(deaths, key=lambda x: x["seed"])]

    bosses = Counter()
    close = 0
    stuck_hands = Counter()
    for row in rows:
        ratio = row["scored"] / max(1, row["target"])
        bosses[row["boss"]] += 1
        if ratio >= 0.7:
            close += 1
        if row["ante"] not in detail:
            continue
        tag = "CLOSE" if ratio >= 0.7 else "blown"
        print(f"seed {row['seed']:>3} | {row['kind']:<5} {row['boss']:<12} "
              f"{row['scored']}/{row['target']} ({ratio:.2f}, {tag}) "
              f"hands {row['hands']} disc {row['discards']} $ {row['dollars']} "
              f"| {','.join(row['jokers'])}")
    print(f"\nboss keys: {dict(bosses.most_common())}")
    print(f"close misses (>=70% of target): {close}/{len(rows)}")


if __name__ == "__main__":
    main()
