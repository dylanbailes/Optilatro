"""bench/probe_best_discard.py — instrument best_discard during a traced seed.

Wraps the best_discard symbol AS SEEN BY agent_v10 (its own namespace import)
and logs every call: the structural pool verdict, the candidate set chosen,
and whether the choice sheds plan-relevant cards. Read-only diagnostics.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENDOR = ROOT / "vendor" / "balatro-rl"
sys.path.insert(0, str(VENDOR))

from balatro_sim.game import BalatroGame               # noqa: E402
from balatro_sim.rollout import rollout                 # noqa: E402
from balatro_sim.agent_v10 import HeuristicV10          # noqa: E402
from balatro_sim import agent_v10 as v10                # noqa: E402

ORIG_BD = v10.best_discard


def bd(game, max_size=None, pool_size=None, base_score=None):
    dset, val = ORIG_BD(game, max_size=max_size, pool_size=pool_size,
                        base_score=base_score)
    suits = {}
    for c in game.hand:
        if c.enhancement != "Stone":
            suits.setdefault(c.suit, []).append(c.rank)
    top_suit, cards = max(suits.items(), key=lambda kv: len(kv[1]))
    shed_plan_suit = sum(1 for i in (dset or ())
                         if game.hand[i].suit == top_suit)
    print(f"    [bd] T={game.current_blind.chips_target - game.chips_scored}"
          f" d={game.discards_left} best_suit={top_suit}"
          f"x{len(cards)}{cards if len(cards) <= 6 else '...'}"
          f" -> drop={[(game.hand[i].rank, game.hand[i].suit[0]) for i in (dset or ())]}"
          f" ev={val:.0f} shed_top_suit={shed_plan_suit}")
    return dset, val


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=5)
    ap.add_argument("--probe-suit", action="store_true")
    args = ap.parse_args()
    v10.best_discard = bd
    try:
        g = BalatroGame(seed=args.seed, rng_mode="seed")
        res = rollout(g, HeuristicV10())
    finally:
        v10.best_discard = ORIG_BD
    print(f"\n== seed {args.seed}: won={res['won']} ante={res['ante']}")


if __name__ == "__main__":
    main()
