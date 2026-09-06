"""tools/diag_blind_max.py — in-blind headroom probe for death seeds.

Replays each death seed with the reference policy up to the START of the
fatal blind, then replays that blind with a pure score-greedy player
(play when it clears, else best EV discard, else best play). Compares
greedy outcome vs the actual death to measure in-blind play headroom.

Usage:
  python tools/diag_blind_max.py --report vendor/balatro-rl/results/goal_base.json
      [--policy heuristic_v10] [--antes 1]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "vendor" / "balatro-rl"))

from balatro_sim.agent_v10 import HeuristicV10  # noqa: E402
from balatro_sim.game import BalatroGame, State  # noqa: E402
from balatro_sim.agent_v9 import scored_plays, best_discard  # noqa: E402


def greedy_blind(game: BalatroGame) -> tuple[int, bool]:
    """Play the current blind greedily; return (chips_scored, cleared)."""
    target = game.current_blind.chips_target
    guard = 0
    while game.state == State.SELECTING_HAND:
        guard += 1
        if guard > 80:
            return game.chips_scored, False  # pathological: bail out
        remaining = target - game.chips_scored
        plays = scored_plays(game)
        best = plays[0] if plays else None
        if best is not None and best[0] >= remaining:
            game.step({"type": "play", "cards": list(best[1])})
        elif game.discards_left > 0:
            cards, _score = best_discard(game)
            if cards:
                game.step({"type": "discard", "cards": list(cards)})
                continue
            if best is not None:
                game.step({"type": "play", "cards": list(best[1])})
            else:
                break  # nothing playable: avoid a noop spin
        elif best is not None:
            game.step({"type": "play", "cards": list(best[1])})
        else:
            break
    return game.chips_scored, game.state != State.GAME_OVER


def probe(rdict: dict) -> str:
    r = rdict
    game = BalatroGame(seed=r["seed"], rng_mode="seed")
    policy = HeuristicV10()
    # Replay with the reference policy until the fatal blind begins.
    while (game.state != State.GAME_OVER
           and not (game.ante == r["ante"]
                    and game.blind_idx == r["death_blind"]
                    and game.state == State.SELECTING_HAND)):
        game.step(policy.decide(game))
    if game.state == State.GAME_OVER:
        return f"seed {r['seed']:>3}: never reached fatal blind"
    target = game.current_blind.chips_target
    scored, cleared = greedy_blind(game)
    return (f"seed {r['seed']:>3} {game.current_blind.boss_key:<12} "
            f"greedy {scored}/{target} "
            f"({'CLEARS' if cleared else 'still short'})")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", required=True)
    ap.add_argument("--policy", default="heuristic_v10")
    ap.add_argument("--antes", default="1")
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()

    raw = json.load(open(args.report, encoding="utf-8"))
    runs = raw[args.policy]["results"]
    want = {int(a) for a in args.antes.split(",")}
    deaths = [r for r in runs if not r["won"] and r["ante"] in want]
    deaths.sort(key=lambda x: x["seed"])

    import multiprocessing as mp
    if args.workers > 1 and len(deaths) > 2:
        ctx = mp.get_context("spawn")
        with ctx.Pool(args.workers) as pool:
            lines = []
            for ln in pool.imap_unordered(probe, deaths, chunksize=1):
                print(ln, flush=True)
                lines.append(ln)
    else:
        lines = [probe(r) for r in deaths]

    flipped = sum(1 for ln in lines if "CLEARS" in ln)
    print("\n".join(lines))
    print(f"\ngreedy clears {flipped}/{len(deaths)} fatal blinds")


if __name__ == "__main__":
    main()
