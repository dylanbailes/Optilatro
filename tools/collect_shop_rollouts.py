"""collect_shop_rollouts.py — Counterfactual buy-outcome dataset builder.

WHAT IT COLLECTS
================
At every SHOP decision of a shipped-parity SearchShopV11 run where an open
joker slot exists and at least one shop joker is affordable, this tool forks
the seed-exact game:

  buy fork   : step {"type": "buy", "item_idx": i}, then rollout(fresh policy)
  skip fork  : rollout(fresh policy) from the same state directly
               (the policy does whatever it would have done without i)

and emits one row per (decision, candidate) pair:

  label delta = won(buy) - won(skip)          in {-1, 0, +1}
  label ante_delta = ante(buy) - ante(skip)   (secondary signal)

The skip fork is computed ONCE per decision and shared across candidates, so
a decision with C affordable jokers costs 1 + C rollouts.

Both forks continue with the SHIPPED policy config (v11_shop_v10_l1 parity),
so the labels measure "what does committing to this candidate do to the run
this policy actually plays" — exactly the quantity the open-slot buy hook
wants to rank.

Human-fair / seed-exact: forks are deepcopy-forks of the seed-exact sim; the
COLLECTED features are observable-state only (buy_model.extract_buy_features).

Output: JSONL rows under results/buy_rollouts/<split>.jsonl
  {seed, dec_id, item_idx, key, edition, price, ante, label, ante_delta,
   v10_before, feats}
"""
from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import random
import sys
import time
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENDOR = ROOT / "vendor" / "balatro-rl"
sys.path.insert(0, str(VENDOR))

from balatro_sim.game import BalatroGame, State           # noqa: E402
from balatro_sim.rollout import rollout                    # noqa: E402
from balatro_sim.agent_v11 import SearchShopV11            # noqa: E402
from balatro_sim.agent_v10 import (                        # noqa: E402
    evaluate_shop_value, extract_game_features,
    formulate_counterfactual_state)
from balatro_sim.buy_model import extract_buy_features     # noqa: E402
from balatro_sim.agent_v9 import joker_value, reference_hand  # noqa: E402

OUT_DIR = ROOT / "results" / "buy_rollouts"


def _affordable_joker_candidates(game) -> list[int]:
    """Indices of unsold, affordable shop jokers (the hook's eligibility)."""
    out = []
    for i, item in enumerate(getattr(game, "current_shop", []) or []):
        if getattr(item, "sold", False) or getattr(item, "kind", "") != "joker":
            continue
        if item.discounted_price(game.shop_discount) > game.dollars:
            continue
        out.append(i)
    return out


def _policy():
    # Shipped-parity config (v11_shop_v10_l1=True default, others off).
    return SearchShopV11()


def collect_seed(seed: int, max_decisions: int, cand_cap: int) -> list[dict]:
    """Run one seed to GAME_OVER, emitting counterfactual rows."""
    game = BalatroGame(seed=seed, rng_mode="seed")
    policy = _policy()
    rng = random.Random(seed * 7919 + 13)
    rows: list[dict] = []
    dec_seen = 0
    steps = 0
    while game.state != State.GAME_OVER and steps < 100_000:
        steps += 1
        if (
            game.state == State.SHOP
            and len(game.jokers) < game.joker_slots
            and dec_seen < max_decisions
        ):
            cands = _affordable_joker_candidates(game)
            if cands:
                # Subsample decisions for budget control (deterministic).
                dec_seen += 1
                if rng.random() > (max_decisions / max(dec_seen, 1)):
                    cands = None
            if cands:
                # Shared skip fork: what the policy does without buying i.
                out_skip = rollout(deepcopy(game), _policy())
                v10_before = evaluate_shop_value(extract_game_features(game))
                ref = None
                jv_cache: dict[tuple[str, str], float] = {}
                chosen = cands
                if len(chosen) > cand_cap:
                    chosen = rng.sample(chosen, cand_cap)
                for i in chosen:
                    item = game.current_shop[i]
                    price = item.discounted_price(game.shop_discount)
                    g_buy = deepcopy(game)
                    g_buy.step({"type": "buy", "item_idx": i})
                    out_buy = rollout(g_buy, _policy())
                    delta = int(bool(out_buy["won"])) - int(bool(out_skip["won"]))
                    ante_delta = int(out_buy["ante"]) - int(out_skip["ante"])
                    if ref is None:
                        ref = reference_hand(game)
                    ek = (item.key, getattr(item, "edition", "None"))
                    if ek not in jv_cache:
                        jv_cache[ek] = joker_value(game, item.key, ek[1], ref=ref)
                    feats = extract_buy_features(
                        game, item, price, ref=ref, jv=jv_cache[ek],
                        dV=None)  # legacy_dv filled below
                    dv = (evaluate_shop_value(formulate_counterfactual_state(
                        game, {"type": "buy", "item_idx": i})) - v10_before)
                    feats["legacy_dv"] = float(dv)
                    feats["legacy_dv_pos"] = max(0.0, float(dv))
                    rows.append({
                        "seed": seed,
                        "dec_id": f"{seed}:{dec_seen}",
                        "item_idx": i,
                        "key": item.key,
                        "edition": getattr(item, "edition", "None"),
                        "price": price,
                        "ante": int(game.ante),
                        "blind_idx": int(game.blind_idx),
                        "label": delta,
                        "ante_delta": ante_delta,
                        "won_skip": int(bool(out_skip["won"])),
                        "ante_skip": int(out_skip["ante"]),
                        "v10_before": float(v10_before),
                        "feats": feats,
                    })
        if game.state == State.GAME_OVER:
            break
        game.step(policy.decide(game))
    return rows


def _worker(args):
    seed, max_dec, cand_cap = args
    try:
        return collect_seed(seed, max_dec, cand_cap)
    except Exception as e:  # keep the sweep alive; log and continue
        return [{"_error": f"{type(e).__name__}: {e}", "seed": seed}]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed-start", type=int, default=30000)
    ap.add_argument("--n-seeds", type=int, default=400)
    ap.add_argument("--holdout", type=int, default=60,
                    help="last N seeds go to holdout.jsonl instead")
    ap.add_argument("--max-decisions", type=int, default=10)
    ap.add_argument("--cand-cap", type=int, default=3)
    ap.add_argument("--workers", type=int, default=max(1, mp.cpu_count() - 2))
    ap.add_argument("--out-tag", type=str, default="")
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    tag = f"_{args.out_tag}" if args.out_tag else ""
    train_path = OUT_DIR / f"train{tag}.jsonl"
    hold_path = OUT_DIR / f"holdout{tag}.jsonl"

    seeds = list(range(args.seed_start, args.seed_start + args.n_seeds))
    split_at = len(seeds) - args.holdout
    train_seeds, hold_seeds = seeds[:split_at], seeds[split_at:]

    t0 = time.time()
    n_rows = n_err = 0
    with mp.Pool(args.workers) as pool, \
            open(train_path, "w", encoding="utf-8") as f_train, \
            open(hold_path, "w", encoding="utf-8") as f_hold:
        for si, rows in enumerate(
                pool.imap_unordered(_worker,
                                    [(s, args.max_decisions, args.cand_cap)
                                     for s in seeds],
                                    chunksize=1)):
            is_hold = si >= split_at
            f = f_hold if is_hold else f_train
            for r in rows:
                if "_error" in r:
                    n_err += 1
                    print(f"[seed {r.get('seed')}] ERROR {r['_error']}",
                          flush=True)
                    continue
                f.write(json.dumps(r) + "\n")
                n_rows += 1
            done = si + 1
            if done % 25 == 0 or done == len(seeds):
                rate = done / max(1e-9, time.time() - t0)
                print(f"[{done}/{len(seeds)}] rows={n_rows} err={n_err} "
                      f"{rate:.1f} seeds/s", flush=True)
    print(f"DONE rows={n_rows} errors={n_err} -> {train_path} / {hold_path} "
          f"({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
