"""tools/trace_run.py — per-blind run tracer + interest bookkeeping.

Replays a deterministic seed against a V9 policy and prints, for every blind:
target chips vs the score achieved, hands/discards used, jokers owned, the
dollars held when the round ended (=> interest actually collected), and --hands
prints every play. Final summary: outcome + interest collected vs possible +
peak dollars + played-hand distribution.

Usage:
  python tools/trace_run.py --seed 12 [--policy heuristic|search]
      [--search-shops N] [--params '{...}'] [--hands] [--ante-limit N]
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "vendor" / "balatro-rl"))

from balatro_sim.agent_l1 import SearchShopV9
from balatro_sim.agent_v9 import HeuristicV9
from balatro_sim.game import BalatroGame, State
from balatro_sim.rollout import outcome


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--agents", default="heuristic")
    ap.add_argument("--search-shops", type=int, default=1)
    ap.add_argument("--params", default=None)
    ap.add_argument("--hands", action="store_true")
    ap.add_argument("--shop", action="store_true")
    ap.add_argument("--state", action="store_true",
                    help="print joker keys + planet levels at each blind")
    ap.add_argument("--ante-limit", type=int, default=0,
                    help="stop PRINTING after ante N (run continues)")
    args = ap.parse_args()

    params = json.loads(args.params) if args.params else None
    game = BalatroGame(seed=args.seed, rng_mode="seed")
    if args.agents == "search":
        policy = SearchShopV9(params=params, search_shops=args.search_shops)
    else:
        policy = HeuristicV9(params=params)

    # Interest bookkeeping: _end_round pays `min(dollars//5, cap)` on the money
    # held when the blind cleared (~= dollars entering that blind).
    collected = 0
    possible = 0
    orig_end_round = game._end_round

    def traced_end_round():
        nonlocal collected, possible
        d = game.dollars
        cap = game.interest_cap
        collected += min(d // 5, cap)
        possible += min(cap, 5)
        orig_end_round()
    game._end_round = traced_end_round

    last_blind = -1
    peak = 0
    blind_score = 0.0
    entry_chips = 0
    plays = []
    steps = 0
    while game.state != State.GAME_OVER:
        st = game.state
        if st == State.BLIND_SELECT and game.blind_idx != last_blind:
            if last_blind >= 0:
                # previous blind just cleared with `blind_score` chips
                mark = "OK " if blind_score >= game.current_blind.chips_target else "?? "
                print(f"  -> scored {blind_score:>10,.0f}")
            last_blind = game.blind_idx
            kind = game.current_blind.kind
            target = game.current_blind.chips_target
            entry_chips = game.chips_scored
            boss = (" boss=" + game.current_blind.boss_key) if kind == "Boss" else ""
            print(f"blind ante{game.ante}/{game.blind_idx} {kind:<5} "
                  f"target {target:>8,}{boss} | $ {game.dollars:>3} | jokers "
                  f"{len(game.jokers)} | hands {game.hands_left} "
                  f"discards {game.discards_left}")
            if args.state:
                jk = [j.key for j in game.jokers]
                pl = {h: lv for h, lv in game.planet_levels.items()
                      if lv > 1}
                print(f"     jokers: {jk}")
                print(f"     planets>1: {pl}")
            if args.ante_limit and game.ante > args.ante_limit:
                print("... (trace truncated by --ante-limit)")
                break
        peak = max(peak, game.dollars)
        if st == State.SHOP and args.shop:
            print(f"  SHOP entry: $ {game.dollars} | " +
                  ", ".join(f"{i.kind}:{i.key}(${i.discounted_price(game.shop_discount)})"
                          for i in game.current_shop))
        if st == State.SELECTING_HAND:
            before = game.chips_scored
            hl = game.hands_left
            game.step(policy.decide(game))
            if game.hands_left < hl:  # a play happened
                blind_score = game.chips_scored
                if args.hands:
                    blind_chips = game.chips_scored - before
                    plays.append((game.last_hand_played, blind_chips))
        else:
            game.step(policy.decide(game))
            if game.current_blind is not None:
                blind_score = game.chips_scored
        steps += 1
        if steps > 200_000:
            print("STALL: step cap")
            break

    print(f"final state: GAME_OVER (won={game.ante > 8}), ante {game.ante}, "
          f"steps {steps}")
    if plays:
        print("plays:", ", ".join(f"{h} {s:,.0f}" for h, s in plays))
    dist = Counter(h for h, _ in plays)
    print("played distribution:", dict(dist))
    print(f"interest: ${collected} collected / ${possible} possible "
          f"({collected / possible * 100:.0f}%)")

    o = outcome(game, steps)
    print("outcome:", {k: o[k] for k in ("won", "ante", "death_blind",
                                         "death_kind")})


if __name__ == "__main__":
    main()