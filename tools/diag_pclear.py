"""tools/diag_pclear.py — trace P(clear) estimates through a fatal blind.

Replays death seeds with HeuristicV10 and prints, at every SELECTING_HAND
decision inside the fatal blind: hands/discards left, remaining target,
best play score now, and the composition-only P(clear) the cascade uses.

Usage:
  python tools/diag_pclear.py --report vendor/balatro-rl/results/goal_base.json
      [--seeds 87,122,159] [--antes 4]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "vendor" / "balatro-rl"))

from balatro_sim.agent_v10 import (  # noqa: E402
    HeuristicV10, _compute_type_scores, estimate_clear_probability,
)
from balatro_sim.agent_v9 import scored_plays  # noqa: E402
from balatro_sim.game import BalatroGame, State  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", required=True)
    ap.add_argument("--policy", default="heuristic_v10")
    ap.add_argument("--seeds", default="")
    ap.add_argument("--antes", default="4")
    args = ap.parse_args()

    raw = json.load(open(args.report, encoding="utf-8"))
    runs = raw[args.policy]["results"]
    want = {int(a) for a in args.antes.split(",")}
    if args.seeds:
        keep = {int(s) for s in args.seeds.split(",")}
        deaths = [r for r in runs if not r["won"] and r["seed"] in keep]
    else:
        deaths = [r for r in runs if not r["won"] and r["ante"] in want]

    for r in sorted(deaths, key=lambda x: x["seed"])[:12]:
        game = BalatroGame(seed=r["seed"], rng_mode="seed")
        policy = HeuristicV10()
        while (game.state != State.GAME_OVER
               and not (game.ante == r["ante"]
                        and game.blind_idx == r["death_blind"]
                        and game.state == State.SELECTING_HAND)):
            game.step(policy.decide(game))
        if game.state == State.GAME_OVER:
            continue
        print(f"-- seed {r['seed']} {game.current_blind.boss_key} "
              f"target {game.current_blind.chips_target}")
        while game.state == State.SELECTING_HAND:
            plays = scored_plays(game)
            ts = _compute_type_scores(game, plays)
            pc = estimate_clear_probability(game, type_scores=ts)
            best = plays[0][0] if plays else 0
            rem = game.current_blind.chips_target - game.chips_scored
            print(f"  hands {game.hands_left} disc {game.discards_left} "
                  f"rem {rem:>6} best_now {best:>6} P(clear) {pc:.3f}")
            game.step(policy.decide(game))


if __name__ == "__main__":
    main()
