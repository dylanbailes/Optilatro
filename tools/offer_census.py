"""offer_census.py — how often does the agent actually SEE each item?

WHY
===
`audit_value_coverage.py` enumerates every item x ante cell and asks which are
short of evidence. That denominator is honest but unprioritised: a rare voucher
seen in 0 of 300 runs contributes exactly as much unfilled "coverage debt" as a
common joker, so a work order driven by shortfall alone spends its budget
equally on both. Measured context for this decision: the required evidence is
~10 rows per cell and there are ~3,300 uncovered cells, i.e. ~33,000 rows
against a collection budget of ~2,600 rows per iteration — about 13 iterations
of uniform spend.

Cells nobody is offered cannot be filled at any budget. This tool measures
which ones those are, cheaply: it drives the frozen policy through live runs and
records every shop item and pack offer it is shown. No rollouts, no forking —
just the offers, at roughly the cost of a plain benchmark run.

OUTPUT
    results/offer_census.json
      {"runs": N, "offers": {"key|a3": count, ...},
       "keys": {"key": count, ...}, "total_offers": T}

`audit_value_coverage.py --census results/offer_census.json` then weights each
cell by how often it can be reached, and reports coverage both raw and
reachability-weighted.
"""
from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "vendor" / "balatro-rl"))

from balatro_sim.game import BalatroGame, State            # noqa: E402
from balatro_sim.agent_v10 import SearchShopV10            # noqa: E402
from balatro_sim.rollout import rollout                    # noqa: E402


class CensusPolicy:
    """Records what the policy is offered, without changing what it does.

    Offers are recorded once per shop/pack *visit*, not once per decision:
    `decide` is called repeatedly inside a single shop, so counting every call
    would scale a shop's offer count by how many decisions it took.
    """

    def __init__(self, inner):
        self.inner = inner
        self.offers: Counter = Counter()
        self._was_shop = False
        self._was_pack = False

    def decide(self, game) -> dict:
        state = game.state
        is_shop = state == State.SHOP
        is_pack = state == State.BOOSTER_OPEN
        if is_shop and not self._was_shop:
            ante = int(getattr(game, "ante", 1) or 1)
            for item in getattr(game, "current_shop", []) or []:
                key = str(getattr(item, "key", "") or "")
                if key:
                    self.offers[f"{key}|a{ante}"] += 1
        if is_pack and not self._was_pack:
            ante = int(getattr(game, "ante", 1) or 1)
            for choice in getattr(game, "booster_choices", []) or []:
                key = choice[1] if isinstance(choice, tuple) and len(choice) >= 2 \
                    else choice
                if isinstance(key, str) and key:
                    self.offers[f"{key}|a{ante}"] += 1
        self._was_shop = is_shop
        self._was_pack = is_pack
        return self.inner.decide(game)


def _worker(seed: int) -> dict:
    p = CensusPolicy(SearchShopV10())
    rollout(BalatroGame(seed=seed, rng_mode="seed"), p)
    return dict(p.offers)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed-start", type=int, default=50000)
    ap.add_argument("--n-seeds", type=int, default=300)
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--out", default="results/offer_census.json")
    args = ap.parse_args()

    seeds = range(args.seed_start, args.seed_start + args.n_seeds)
    total: Counter = Counter()
    with mp.Pool(args.workers) as pool:
        for part in pool.imap_unordered(_worker, seeds, chunksize=2):
            total.update(part)

    by_key: Counter = Counter()
    for cell, n in total.items():
        by_key[cell.split("|")[0]] += n

    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "runs": args.n_seeds,
        "seed_start": args.seed_start,
        "offers": dict(total),
        "keys": dict(by_key),
        "total_offers": int(sum(total.values())),
    }, indent=1, sort_keys=True) + "\n", encoding="utf-8")

    print(f"census: {args.n_seeds} runs, {sum(total.values())} offers, "
          f"{len(by_key)} distinct keys, {len(total)} key|ante cells")
    print(f"  most offered: " + ", ".join(
        f"{k}={v}" for k, v in by_key.most_common(8)))
    never = sum(1 for k in by_key if by_key[k] == 0)
    print(f"  wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
