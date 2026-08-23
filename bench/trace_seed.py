"""bench/trace_seed.py — step-by-step decision trace for one seed (M14).

Runs heuristic_v10 on a single seed with logging wrappers around the shop /
hand deciders and the M14 targeting layer, printing per-decision state so an
audited death can be attributed to a specific gate or ranking choice.

Usage:
  python3 bench/trace_seed.py --seed 52 [--params '{}']
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENDOR = ROOT / "vendor" / "balatro-rl"
sys.path.insert(0, str(VENDOR))

from balatro_sim.game import BalatroGame               # noqa: E402
from balatro_sim.rollout import rollout                 # noqa: E402
from balatro_sim.agent_v10 import HeuristicV10          # noqa: E402
from balatro_sim import agent_v10 as v10                # noqa: E402


def _cards(cards):
    out = []
    for c in cards:
        mark = {"Bonus": "B", "Mult": "M", "Wild": "W", "Glass": "G",
                "Steel": "S", "Gold": "$", "Lucky": "L", "Stone": "#"}.get(
                    c.enhancement, "")
        ed = {"foil": "f", "holo": "h", "polychrome": "p"}.get(c.edition, "")
        out.append(f"{c.rank}{c.suit[0]}{mark}{ed}")
    return " ".join(out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--params", type=str, default=None)
    args = ap.parse_args()
    if args.params:
        v10.V10_PARAMS.update(json.loads(args.params))

    g = BalatroGame(seed=args.seed, rng_mode="seed")

    orig_hand = v10._v10_decide_hand
    orig_shop = v10._v10_decide_shop
    orig_plan = v10._blind_plan
    orig_chase = v10._chase_discard

    ctx = {}

    def shop(game, rerolls):
        act = orig_shop(game, rerolls)
        items = [f"{it.kind}:{it.key}:${it.discounted_price(game.shop_discount)}"
                 for it in game.current_shop if not it.sold]
        print(f"[SHOP a{game.ante} ${game.dollars} rr{rerolls}] "
              f"{' | '.join(items)} -> {act}")
        return act

    def plan(game, ts):
        p = orig_plan(game, ts)
        ctx["plan"] = p
        T = game.current_blind.chips_target - game.chips_scored
        top = sorted(ts.items(), key=lambda kv: -kv[1])[:4]
        print(f"  [plan] T={T} h={game.hands_left} d={game.discards_left} "
              f"S(top)={top} -> {p}")
        return p

    def chase(game, pl, base):
        keep = v10._plan_keep_indices(game.hand, pl) if pl else []
        act = orig_chase(game, pl, base)
        why = "commit"
        if act is None and pl:
            p_ = v10.V10_PARAMS
            if not keep:
                why = "no-keep"
            elif pl["prob"] * pl["S"] < base * p_["chase_min_ev_gain"]:
                why = "ev"
            else:
                why = "prob"
        print(f"  [chase] best={base:.0f} plan={pl and pl['ht']} "
              f"keep={[g.hand[i].rank for i in keep]} "
              f"deb={sum(1 for c in g.hand if c.debuffed)} -> {act or why}")
        return act

    def hand(game):
        b = game.current_blind
        print(f"\n[HAND a{game.ante} {b.kind}/{b.name}({b.boss_key}) T="
              f"{b.chips_target - game.chips_scored} "
              f"h={game.hands_left} d={game.discards_left}] "
              f"hand: {_cards(game.hand)}")
        ctx["plan"] = None
        act = orig_hand(game)
        idx = act.get("cards", [])
        print(f"  -> {act['type']} {[game.hand[i].rank for i in idx]}")
        return act

    v10._v10_decide_shop = shop
    v10._blind_plan = plan
    v10._chase_discard = chase
    v10._v10_decide_hand = hand
    try:
        res = rollout(g, HeuristicV10())
    finally:
        v10._v10_decide_shop, v10._blind_plan = orig_shop, orig_plan
        v10._chase_discard, v10._v10_decide_hand = orig_chase, orig_hand

    print(f"\n== seed {args.seed}: won={res['won']} ante={res['ante']} "
          f"death_kind={res.get('death_kind')} jokers={res['jokers']} "
          f"${res['dollars']} packs={res['stats']['packs_bought']}")


if __name__ == "__main__":
    main()
