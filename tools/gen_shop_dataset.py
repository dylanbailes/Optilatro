"""tools/gen_shop_dataset.py — Generate state-outcome dataset for shop value function.

Runs rollouts with exploratory perturbations (buying xMult/scaling jokers and
selling redundant economy/flat jokers) across random seeds. At each shop state,
extracts portfolio features. When the game terminates, labels every snapshot with
the final run outcome (won=1.0, ante_reached / 8.0).

Parallelized across CPU workers for high throughput.

Usage:
  python tools/gen_shop_dataset.py --games 3000 --output tools/shop_dataset.jsonl --workers 8
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "vendor" / "balatro-rl"))
sys.path.insert(0, str(ROOT))

from balatro_sim.game import BalatroGame, State
from balatro_sim.agent_v10 import HeuristicV10, _v10_worst_joker_idx
from tools.portfolio import extract_game_features, XMULT_JOKERS, SCALING_JOKERS, ECON_JOKERS


def explore_shop_action(game, policy, rerolls_used: int, epsilon: float = 0.15) -> dict:
    """Exploration-augmented shop policy: occasionally buys xMult/scaling jokers
    and sells redundant economy jokers to sample transitions."""
    if random.random() < epsilon and 2 <= game.ante <= 5 and game.current_shop:
        candidates = []
        for idx, item in enumerate(game.current_shop):
            if item.kind == "joker":
                price = item.discounted_price(game.shop_discount)
                if price <= game.dollars:
                    if item.key in XMULT_JOKERS or item.key in SCALING_JOKERS:
                        candidates.append((idx, item, price))

        if candidates:
            if len(game.jokers) >= game.joker_slots:
                sell_idx = None
                for j_idx, j in enumerate(game.jokers):
                    if j.key in ECON_JOKERS:
                        sell_idx = j_idx
                        break
                if sell_idx is None:
                    sell_idx = _v10_worst_joker_idx(game)
                    if sell_idx is None:
                        sell_idx = 0
                return {"type": "sell_joker", "joker_idx": sell_idx}
            else:
                idx, item, _ = random.choice(candidates)
                return {"type": "buy", "item_idx": idx}

    return policy.decide(game)


def _worker_run(seed_and_args: tuple[int, float, bool]) -> tuple[list[dict], bool, int, int]:
    seed, epsilon, pace_rule = seed_and_args
    params = {
        "ante1_chip_bias": 0.8,
        "early_struct_ante": 2,
        "ante2_chip_bias": 0.5,
        "farm_rate_share": 0.75,
        "sampled_pick_ante": 0,  # fast bulk collection
        "engineless_urgency_ante": 2,
        "ante1_pace_rule": pace_rule,
    }
    game = BalatroGame(seed=seed, rng_mode="seed")
    policy = HeuristicV10(params=params)

    snapshots = []
    rerolls_this_shop = 0
    in_shop = False

    for _step in range(1200):
        if game.state == State.GAME_OVER:
            break

        st = game.state
        if st == State.SHOP:
            if not in_shop:
                in_shop = True
                rerolls_this_shop = 0
                snapshots.append(extract_game_features(game))

            act = explore_shop_action(game, policy, rerolls_this_shop, epsilon=epsilon)
            if act.get("type") == "reroll":
                rerolls_this_shop += 1
            elif act.get("type") == "leave_shop":
                in_shop = False
        else:
            in_shop = False
            act = policy.decide(game)

        game.step(act)

    won = (game.state == State.ROUND_EVAL and game.ante > 8) or (game.ante > 8)
    final_ante = game.ante
    return snapshots, won, final_ante, seed


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--games", type=int, default=3000)
    parser.add_argument("--start-seed", type=int, default=1000)
    parser.add_argument("--epsilon", type=float, default=0.15)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--output", default="tools/shop_dataset.jsonl")
    args = parser.parse_args()

    out_path = ROOT / args.output
    total_snapshots = 0
    wins = 0
    tasks = [(args.start_seed + i, args.epsilon, True) for i in range(args.games)]

    print(f"Generating {args.games} games with {args.workers} workers...")
    sys.stdout.flush()

    with open(out_path, "w", encoding="utf-8") as f:
        with concurrent.futures.ProcessPoolExecutor(max_workers=args.workers) as executor:
            completed = 0
            for snapshots, won, final_ante, seed in executor.map(_worker_run, tasks, chunksize=16):
                completed += 1
                if won:
                    wins += 1
                y_win = 1.0 if won else 0.0
                y_ante = min(1.0, final_ante / 8.0)
                for feat in snapshots:
                    row = {
                        "seed": seed,
                        "won": y_win,
                        "ante_norm": y_ante,
                        "final_ante": final_ante,
                        "f": feat,
                    }
                    f.write(json.dumps(row) + "\n")
                    total_snapshots += 1

                if completed % 250 == 0 or completed == args.games:
                    win_pct = wins / completed * 100
                    print(f"  [{completed}/{args.games}] wins: {wins} ({win_pct:.1f}%) | snapshots: {total_snapshots}", flush=True)

    print(f"Done! Wrote {total_snapshots} snapshots to {out_path}", flush=True)


if __name__ == "__main__":
    main()
