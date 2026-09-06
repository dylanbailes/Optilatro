"""tools/diag_solve.py — beam-search solver for fatal blinds.

Replays each death seed to the start of the fatal blind, then runs a
beam search over play/discard/consumable action sequences (outcome-
optimized, no policy heuristics) to measure TRUE winnability. Reports
the solver's first action vs the policy's actual first action so the
divergence point is visible.

Usage:
  python tools/diag_solve.py --report vendor/balatro-rl/results/goal_chip08.json
      [--policy heuristic_v10] [--antes 1] [--beam 40]
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "vendor" / "balatro-rl"))

from balatro_sim.agent_v9 import best_discard, scored_plays  # noqa: E402
from balatro_sim.agent_v10 import (  # noqa: E402
    HeuristicV10, _v10_decide_consumable, maybe_use_planet,
)
from balatro_sim.game import BalatroGame, State  # noqa: E402


def candidate_actions(g) -> list[tuple[str, dict]]:
    """Diverse candidate actions for the solver: consumables, top plays,
    best discard, plus a couple of cheap structural discards."""
    cands: list[tuple[str, dict]] = []
    act = maybe_use_planet(g)
    if act is not None:
        cands.append(("planet", act))
    tact = _v10_decide_consumable(g)
    if tact is not None:
        cands.append(("tarot", tact))
    plays = scored_plays(g, topk=10)
    seen: set[int] = set()
    for score, cards, ht in plays:
        key = frozenset(cards)
        if id(key) in seen:
            continue
        seen.add(id(key))
        cands.append((f"play:{ht}:{score}", {"type": "play", "cards": list(cards)}))
        if len(cands) >= 13:
            break
    if g.discards_left > 0 and len(g.deck) > 0:
        dset, _ = best_discard(g)
        if dset:
            cands.append(("discard:ev", {"type": "discard", "cards": list(dset)}))
        # quality discards: drop 1-2 lowest-value cards (index order = quality)
        n = len(g.hand)
        if n > 5:
            cands.append(("discard:w1", {"type": "discard",
                                         "cards": [n - 1]}))
            cands.append(("discard:w2", {"type": "discard",
                                         "cards": [n - 1, n - 2]}))
    return cands


def beam_rank(g):
    """Beam priority: projected finish + resource bonus."""
    rem = g.current_blind.chips_target - g.chips_scored
    plays = scored_plays(g, topk=1)
    best = plays[0][0] if plays else 0
    proj = g.chips_scored + best * max(0, g.hands_left)
    return proj + 30 * g.hands_left + 8 * g.discards_left


def solve(seed_game, beam: int):
    """Return (cleared, first_action, actions) for the best beam line."""
    layer = [(seed_game, None, [])]
    first_map: dict[int, object] = {}
    for _depth in range(24):
        alive = [(g, fa, seq) for (g, fa, seq) in layer
                 if g.state == State.SELECTING_HAND]
        done = [(g, fa, seq) for (g, fa, seq) in layer
                if g.state != State.SELECTING_HAND]
        if not alive:
            break
        nxt = list(done)
        for g, fa, seq in alive:
            for label, act in candidate_actions(g):
                g2 = copy.deepcopy(g)
                g2.step(act)
                nxt.append((g2, fa if fa is not None else act,
                            seq + [label]))
        # keep best `beam` by rank, but always keep some finished lines
        nxt.sort(key=lambda t: (t[0].state == State.GAME_OVER,
                                -beam_rank(t[0])))
        layer = nxt[:beam]
    # best terminal overall
    best = None
    for g, fa, seq in layer:
        cleared = (g.state == State.ROUND_EVAL
                   or g.chips_scored >= g.current_blind.chips_target)
        score = (1 if cleared else 0, g.chips_scored)
        if best is None or score > best[0]:
            best = (score, fa, seq, g)
    (cleared_flag, chips), fa, seq, g = best
    return bool(cleared_flag), chips, fa, seq


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", required=True)
    ap.add_argument("--policy", default="heuristic_v10")
    ap.add_argument("--antes", default="1")
    ap.add_argument("--beam", type=int, default=40)
    args = ap.parse_args()

    raw = json.load(open(args.report, encoding="utf-8"))
    runs = raw[args.policy]["results"]
    want = {int(a) for a in args.antes.split(",")}
    deaths = [r for r in runs if not r["won"] and r["ante"] in want]

    solvable = 0
    for r in sorted(deaths, key=lambda x: x["seed"]):
        game = BalatroGame(seed=r["seed"], rng_mode="seed")
        policy = HeuristicV10()
        while (game.state != State.GAME_OVER
               and not (game.ante == r["ante"]
                        and game.blind_idx == r["death_blind"]
                        and game.state == State.SELECTING_HAND)):
            game.step(policy.decide(game))
        if game.state == State.GAME_OVER:
            print(f"seed {r['seed']:>3}: never reached fatal blind")
            continue
        target = game.current_blind.chips_target
        pol_act = policy.decide(copy.deepcopy(game))
        cleared, chips, fa, seq = solve(game, args.beam)
        solvable += cleared
        print(f"seed {r['seed']:>3} {game.current_blind.boss_key:<12} "
              f"solver {'CLEARS' if cleared else 'short'} {chips}/{target} | "
              f"policy 1st: {pol_act.get('type')} | "
              f"solver 1st: {fa.get('type') if fa else '-'} | {seq[:6]}",
              flush=True)
    print(f"\nsolver clears {solvable}/{len(deaths)} fatal blinds")


if __name__ == "__main__":
    main()
