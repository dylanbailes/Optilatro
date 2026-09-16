"""tools/diag_v11_shop.py — per-shop decision trace for V10 vs V11.

Runs one seed under both policies and prints, for every shop visit, the
action the policy took together with the state that produced it. Used to
explain macro behavioural gaps (e.g. V11 buys 7.0 jokers/run vs V10's 11.2).

Usage:
  python tools/diag_v11_shop.py --seed 10503
  python tools/diag_v11_shop.py --seed 10503 --policy search_shop_v11
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "vendor" / "balatro-rl"))

from balatro_sim.agent_v10 import SearchShopV10   # noqa: E402
from balatro_sim.agent_v11 import SearchShopV11  # noqa: E402
from balatro_sim.game import BalatroGame, State  # noqa: E402
from balatro_sim.rollout import rollout          # noqa: E402


class TracingPolicyMixin:
    """Records every action taken and the shop it was taken in."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.trace: list[dict] = []
        self._visit = 0

    def decide(self, game):
        act = super().decide(game)
        if game.state == State.SHOP:
            if not getattr(self, "_in_prev", False):
                self._visit += 1
            shop = []
            for i, it in enumerate(getattr(game, "current_shop", [])):
                shop.append({
                    "i": i,
                    "kind": getattr(it, "kind", "?"),
                    "key": getattr(it, "key", None) or getattr(getattr(it, "card", None), "key", None),
                    "price": it.discounted_price(game.shop_discount) if not it.sold else None,
                    "sold": bool(it.sold),
                })
            self.trace.append({
                "visit": self._visit,
                "ante": game.ante,
                "blind": getattr(game, "blind_idx", None),
                "dollars": game.dollars,
                "jokers": [j.key for j in game.jokers],
                "consumables": list(game.consumable_hand),
                "shop": shop,
                "action": act,
            })
        self._in_prev = game.state == State.SHOP
        return act


class TraceV10(TracingPolicyMixin, SearchShopV10):
    pass


class TraceV11(TracingPolicyMixin, SearchShopV11):
    pass


def _fmt(act: dict, shop: list[dict]) -> str:
    t = act.get("type")
    if t == "buy":
        i = act.get("item_idx")
        it = next((s for s in shop if s["i"] == i), None)
        return f"buy[{i}] {it['kind']} {it['key']} ${it['price']}" if it else f"buy[{i}]"
    if t == "sell_joker":
        return f"sell[{act.get('joker_idx')}]"
    if t == "reroll":
        return "reroll"
    if t == "pick_booster":
        return f"pick_booster{act.get('indices')}"
    return str(t)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=10503)
    ap.add_argument("--policy", default=None, help="Only trace this policy")
    ap.add_argument("--params", default=None, help="JSON params for V11")
    ap.add_argument("--dump", default=None, help="Write full trace JSON here")
    args = ap.parse_args()

    params = json.loads(args.params) if args.params else None
    policies = []
    if args.policy in (None, "search_shop_v10"):
        policies.append(("search_shop_v10", TraceV10()))
    if args.policy in (None, "search_shop_v11"):
        policies.append(("search_shop_v11", TraceV11(params=params)))

    dumps = {}
    for name, pol in policies:
        game = BalatroGame(seed=args.seed, rng_mode="seed")
        r = rollout(game, pol)
        dumps[name] = {"trace": pol.trace, "result": {k: v for k, v in r.items() if k != "jokers"}}
        print(f"\n===== {name} seed {args.seed}: "
              f"{'WON' if r['won'] else 'lost'} at ante {r['ante']} "
              f"({r.get('death_kind')}) dollars ${r['dollars']}")
        buys = 0
        for rec in pol.trace:
            tag = f"ante{rec['ante']}.{rec['blind']} v{rec['visit']}"
            print(f"  {tag:<12} ${rec['dollars']:>4} | {_fmt(rec['action'], rec['shop']):<34}"
                  f" | jokers={rec['jokers']}")
            if rec["action"].get("type") == "buy":
                buys += 1
        print(f"  total shop actions: {len(pol.trace)}  buys: {buys}")

    if args.dump:
        Path(args.dump).write_text(json.dumps(dumps, indent=1, default=str), encoding="utf-8")
        print(f"\nwrote {args.dump}")


if __name__ == "__main__":
    main()
