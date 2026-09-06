"""tools/diag_trace.py — trace policy decisions inside a fatal blind.

Usage:
  python tools/diag_trace.py --seed 116 --ante 1 --blind 1
      [--params '{"...": ...}']
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "vendor" / "balatro-rl"))

from balatro_sim.agent_v9 import scored_plays  # noqa: E402
from balatro_sim.agent_v10 import HeuristicV10  # noqa: E402
from balatro_sim.game import BalatroGame, State  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--ante", type=int, default=1)
    ap.add_argument("--blind", type=int, default=2)
    ap.add_argument("--params", default=None)
    args = ap.parse_args()
    params = json.loads(args.params) if args.params else None

    game = BalatroGame(seed=args.seed, rng_mode="seed")
    policy = HeuristicV10(params=params)
    while (game.state != State.GAME_OVER
           and not (game.ante == args.ante
                    and game.blind_idx == args.blind
                    and game.state == State.SELECTING_HAND)):
        act = policy.decide(game)
        game.step(act)
        if game.state == State.SELECTING_HAND or True:
            pass
    if game.state == State.GAME_OVER:
        print("never reached fatal blind")
        return
    print(f"fatal blind: {game.current_blind.name} "
          f"{game.current_blind.boss_key} target "
          f"{game.current_blind.chips_target}")
    while game.state == State.SELECTING_HAND:
        plays = scored_plays(game, topk=5)
        rem = game.current_blind.chips_target - game.chips_scored
        top = ", ".join(f"{ht}:{s}" for s, _c, ht in plays[:3])
        act = policy.decide(game)
        print(f"hands {game.hands_left} disc {game.discards_left} "
              f"rem {rem} | top: {top} | -> {act.get('type')} "
              f"{act.get('cards', '')}", flush=True)
        game.step(act)


if __name__ == "__main__":
    main()
