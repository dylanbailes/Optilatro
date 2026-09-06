"""tools/gen_clear_dataset.py — generate training data for the clear-model.

Replays games with the current policy and logs, at every ante<=2
SELECTING_HAND decision, composition-only features plus whether that blind
eventually cleared. Output: JSONL rows {y, f:{...}} for the logistic
clear-model fit (tools/fit_clear_model.py).

Usage:
  python tools/gen_clear_dataset.py --out tools/clear_dataset.jsonl
      [--start 0] [--games 300] [--params '{"...": ...}']
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "vendor" / "balatro-rl"))

from balatro_sim.agent_v10 import HeuristicV10, main_hand_type  # noqa: E402
from balatro_sim.agent_v9 import scored_plays  # noqa: E402
from balatro_sim.game import BalatroGame, State  # noqa: E402

BOSS_FLAGS = ["bl_manacle", "bl_hook", "bl_club", "bl_window", "bl_wall",
              "bl_needle", "bl_mouth", "bl_arm", "bl_plant", "bl_goad",
              "bl_head", "bl_serpent", "bl_pillar", "bl_flute"]


def features(game, plays) -> dict:
    target = game.current_blind.chips_target
    rem = target - game.chips_scored
    top = plays[0][0] if plays else 0
    main = main_hand_type(game)
    keys = [j.key for j in game.jokers]
    f = {
        "rem_ratio": round(rem / max(1, target), 4),
        "top_share": round(top / max(1, rem), 4),
        "proj_ratio": round(top * max(1, game.hands_left)
                            / max(1, rem), 4),
        "hands": game.hands_left,
        "discards": game.discards_left,
        "n_jokers": len(keys),
        "chips_j": sum(1 for k in keys if k in (
            "j_sly", "j_wily", "j_clever", "j_devious", "j_crafty",
            "j_half", "j_banner", "j_mystic_summit", "j_scary_face",
            "j_odd_todd", "j_scholar", "j_even_steven")),
        "econ_j": sum(1 for k in keys if k in (
            "j_business", "j_cloud_9", "j_credit_card", "j_delayed_grat",
            "j_egg", "j_faceless", "j_gift", "j_golden", "j_mail",
            "j_reserved_parking", "j_rocket", "j_rough_gem", "j_satellite",
            "j_ticket", "j_to_the_moon", "j_todo_list", "j_trading")),
        "money": game.dollars,
        "planet_main": game.planet_levels.get(main, 1),
        "ante": game.ante,
        "is_boss": int(game.current_blind.is_boss),
    }
    for b in BOSS_FLAGS:
        f["b_" + b] = int(game.current_blind.boss_key == b)
    return f


def replay_game(seed: int, params) -> list[dict]:
    game = BalatroGame(seed=seed, rng_mode="seed")
    policy = HeuristicV10(params=params)
    pending = []   # undecided rows for the current blind
    rows = []
    while game.state != State.GAME_OVER:
        st = game.state
        if st == State.SELECTING_HAND and game.ante <= 2:
            plays = scored_plays(game, topk=8)
            pending.append({"y": None,
                            "f": features(game, plays)})
            game.step(policy.decide(game))
            # blind resolved?
            if game.state in (State.ROUND_EVAL, State.GAME_OVER):
                cleared = int(game.state == State.ROUND_EVAL)
                for row in pending:
                    row["y"] = cleared
                rows.extend(pending)
                pending = []
            continue
        game.step(policy.decide(game))
        if pending and game.state != State.SELECTING_HAND:
            cleared = int(game.state == State.ROUND_EVAL)
            for row in pending:
                row["y"] = cleared
            rows.extend(pending)
            pending = []
    return rows


def _worker(job):
    seed, params = job
    return replay_game(seed, params)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="tools/clear_dataset.jsonl")
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--games", type=int, default=300)
    ap.add_argument("--params", default=None)
    args = ap.parse_args()
    params = json.loads(args.params) if args.params else None

    import multiprocessing as mp
    jobs = [(s, params) for s in range(args.start, args.start + args.games)]
    ctx = mp.get_context("spawn")
    n = 0
    with open(args.out, "w", encoding="utf-8") as fh, \
            ctx.Pool(8) as pool:
        for rows in pool.imap_unordered(_worker, jobs, chunksize=4):
            for row in rows:
                fh.write(json.dumps(row) + "\n")
                n += 1
    print(f"wrote {n} rows -> {args.out}")


if __name__ == "__main__":
    main()
