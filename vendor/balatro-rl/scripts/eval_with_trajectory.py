"""
eval_with_trajectory.py

Loads a V7 checkpoint, plays N complete episodes, and writes a detailed
per-episode trajectory JSONL for replay-video generation and analysis.

Each JSONL line is one complete episode:
{
  "episode_id": 0,
  "seed": 1234567890,
  "outcome": {"ante": 9, "won": true, "reward": 245.3, "steps": 187, "dollars": 43},
  "trajectory": [
    {
      "step": 0,
      "phase": "blind_select",
      "ante": 1, "round": 1, "money": 4,
      "hand_cards": [...],
      "jokers": [...],
      "action": {"type": "phase", "action": 0, "name": "select_blind"},
      "top_probs": [["select_blind", 0.95], ["skip_blind", 0.05]],
      "reward": 0.0,
      "value_estimate": 12.3
    },
    ...
  ]
}

Usage:
    python scripts/eval_with_trajectory.py --checkpoint checkpoints_v7_run4/iter_0920.pt \
        --n-episodes 500 --output results/eval_trajectories.jsonl

Filter afterwards with scripts/find_replay_candidates.py.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import torch
import torch.nn.functional as F

# Make imports work whether invoked from repo root or scripts/
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from balatro_sim.env_v7 import (
    BalatroV7Env,
    PHASE_SELECTING_HAND, PHASE_BLIND_SELECT, PHASE_SHOP, PHASE_GAME_OVER,
    OBS_DIM, N_PHASE_ACTIONS, N_HAND_SLOTS,
)
from balatro_sim.card_selection import (
    INTENT_PLAY, INTENT_DISCARD, INTENT_USE_CONSUMABLE, N_INTENTS,
    enumerate_subsets, compute_subset_logits,
)

# Re-use the policy architecture from train_v7 without re-importing the whole
# training file (which triggers multiprocessing setup).
from train_v7 import ActorCriticV7


PHASE_NAMES = {
    PHASE_SELECTING_HAND: "hand",
    PHASE_BLIND_SELECT:   "blind_select",
    PHASE_SHOP:           "shop",
    PHASE_GAME_OVER:      "game_over",
}

INTENT_NAMES = {
    INTENT_PLAY: "play",
    INTENT_DISCARD: "discard",
    INTENT_USE_CONSUMABLE: "use_consumable",
}


def _joker_display_name(key: str) -> str:
    """Turn a joker key like 'j_mystic_summit' into 'Mystic Summit'."""
    if key.startswith("j_"):
        key = key[2:]
    return " ".join(w.capitalize() for w in key.split("_"))


def phase_action_name(env: BalatroV7Env, phase: int, action: int) -> str:
    """Human-readable name for a non-hand phase action, resolved against current state."""
    if phase == PHASE_BLIND_SELECT:
        return ["select_blind", "skip_blind"][action] if action < 2 else f"blind_action_{action}"
    if phase == PHASE_SHOP:
        gs = env.game
        if action == 14:
            return "reroll"
        if action == 15:
            return "leave_shop"
        if action == 16:
            return "use_planet"
        if 2 <= action <= 8:
            idx = action - 2
            shop = getattr(gs, "current_shop", None) or []
            if idx < len(shop):
                item = shop[idx]
                return f"buy {getattr(item, 'name', getattr(item, 'key', idx))}"
            return f"buy_slot_{idx}"
        if 9 <= action <= 13:
            j_idx = action - 9
            if j_idx < len(getattr(gs, "jokers", []) or []):
                return f"sell {_joker_display_name(gs.jokers[j_idx].key)}"
            return f"sell_slot_{j_idx}"
        return f"shop_action_{action}"
    return f"action_{action}"


def snapshot_state(env: BalatroV7Env) -> dict[str, Any]:
    """Structured game-state snapshot for each decision point."""
    gs = env.game
    hand = []
    for c in getattr(gs, "hand", []) or []:
        hand.append({
            "rank": int(getattr(c, "rank", 0)),
            "suit": str(getattr(c, "suit", "")),
            "enhancement": str(getattr(c, "enhancement", "None")),
            "edition":     str(getattr(c, "edition", "None")),
            "seal":        str(getattr(c, "seal", "None")),
            "debuffed":    bool(getattr(c, "debuffed", False)),
        })
    def _jsonable(v):
        if isinstance(v, (set, frozenset)):
            return sorted(list(v), key=str)
        if isinstance(v, dict):
            return {k: _jsonable(vv) for k, vv in v.items()}
        if isinstance(v, (list, tuple)):
            return [_jsonable(vv) for vv in v]
        return v

    jokers = []
    for j in getattr(gs, "jokers", []) or []:
        jokers.append({
            "key":     getattr(j, "key", "unknown"),
            "name":    _joker_display_name(getattr(j, "key", "unknown")),
            "edition": getattr(j, "edition", "None") or "None",
            "state":   {k: _jsonable(v) for k, v in (getattr(j, "state", {}) or {}).items()},
        })
    blind = getattr(gs, "current_blind", None)
    blind_info = None
    if blind is not None:
        blind_info = {
            "name":   getattr(blind, "name", ""),
            "kind":   getattr(blind, "kind", ""),
            "target": int(getattr(blind, "chips_target", 0)),
            "is_boss": bool(getattr(blind, "is_boss", False)),
            "boss_key": getattr(blind, "boss_key", "") or "",
        }
    shop = []
    for item in getattr(gs, "current_shop", []) or []:
        shop.append({
            "kind":  getattr(item, "kind", ""),
            "key":   getattr(item, "key", ""),
            "name":  getattr(item, "name", ""),
            "price": int(getattr(item, "price", 0)),
            "edition": getattr(item, "edition", "None") or "None",
            "sold":  bool(getattr(item, "sold", False)),
        })
    return {
        "ante":          int(getattr(gs, "ante", 1)),
        "blind_idx":     int(getattr(gs, "blind_idx", 0)),
        "money":         int(getattr(gs, "dollars", 0)),
        "chips_scored":  int(getattr(gs, "chips_scored", 0)),
        "hands_left":    int(getattr(gs, "hands_left", 0)),
        "discards_left": int(getattr(gs, "discards_left", 0)),
        "deck_size":     int(len(getattr(gs, "deck", []) or [])),
        "hand_size":     int(getattr(gs, "hand_size", 8)),
        "blind":         blind_info,
        "hand_cards":    hand,
        "jokers":        jokers,
        "shop":          shop,
        "consumables":   list(getattr(gs, "consumable_hand", []) or []),
        "planet_levels": dict(getattr(gs, "planet_levels", {}) or {}),
    }


def topk_probs(probs: np.ndarray, names: list[str], k: int = 3) -> list[list]:
    """Return top-k (name, prob) pairs."""
    idx = np.argsort(-probs)[:k]
    return [[names[int(i)], float(probs[int(i)])] for i in idx if probs[int(i)] > 1e-4]


def play_episode(policy: ActorCriticV7, seed: int, max_steps: int = 2000,
                 log_probs: bool = True, greedy: bool = False) -> dict:
    """Play one full episode deterministically from seed and return trajectory.

    greedy=True: pick argmax of each policy head instead of sampling. Gives
    deterministic, higher-WR "best deployment" performance. greedy=False (default)
    samples per the Categorical/Bernoulli heads, matching training-time stochasticity.
    """
    env = BalatroV7Env(seed=seed)
    obs, _ = env.reset()
    trajectory: list[dict] = []
    total_reward = 0.0
    final_info: dict = {}

    for step in range(max_steps):
        phase = env.get_phase()
        obs_t = torch.from_numpy(obs).float().unsqueeze(0)

        with torch.no_grad():
            trunk = policy.get_trunk(obs_t)
            value = float(policy.forward_value(trunk).item())

        record: dict[str, Any] = {
            "step":  step,
            "phase": PHASE_NAMES.get(phase, f"phase_{phase}"),
            **snapshot_state(env),
            "value_estimate": value,
        }

        if phase == PHASE_SELECTING_HAND:
            mask = env.get_intent_mask()
            mask_t = torch.from_numpy(mask).bool().unsqueeze(0)
            with torch.no_grad():
                intent_dist = policy.forward_intent(trunk, mask_t)
                intent_probs = F.softmax(intent_dist.logits.squeeze(0), dim=-1).cpu().numpy()
                intent = int(intent_dist.logits.argmax().item()) if greedy else int(intent_dist.sample().item())
                card_scores = policy.forward_card_scores(
                    trunk, torch.tensor([intent])
                ).squeeze(0).cpu().numpy()

            n_cards = min(len(env.game.hand), N_HAND_SLOTS)
            subset: tuple[int, ...] = (0,)
            if intent in (INTENT_PLAY, INTENT_DISCARD) and n_cards > 0:
                subsets = enumerate_subsets(n_cards)
                logits = compute_subset_logits(card_scores[:n_cards], subsets, intent)
                sl = torch.from_numpy(logits).float()
                sub_dist = torch.distributions.Categorical(logits=sl)
                subset_idx = int(sl.argmax().item()) if greedy else int(sub_dist.sample().item())
                subset = subsets[subset_idx]

            record["action"] = {
                "type":   "hand",
                "intent": INTENT_NAMES.get(intent, f"intent_{intent}"),
                "subset": list(subset),
            }
            if log_probs:
                intent_names = [INTENT_NAMES.get(i, str(i)) for i in range(N_INTENTS)]
                record["top_probs"] = topk_probs(intent_probs, intent_names, k=N_INTENTS)

            obs, reward, terminated, truncated, info = env.step_hand(intent, subset)

        elif phase == PHASE_GAME_OVER:
            # Should not normally reach here before terminated=True, but guard it
            break

        else:
            mask = env.get_phase_mask()
            mask_t = torch.from_numpy(mask).bool().unsqueeze(0)
            with torch.no_grad():
                phase_dist = policy.forward_phase(trunk, mask_t)
                phase_probs = F.softmax(phase_dist.logits.squeeze(0), dim=-1).cpu().numpy()
                action = int(phase_dist.logits.argmax().item()) if greedy else int(phase_dist.sample().item())

            record["action"] = {
                "type":   "phase",
                "action": action,
                "name":   phase_action_name(env, phase, action),
            }
            if log_probs:
                names = [phase_action_name(env, phase, i) for i in range(N_PHASE_ACTIONS)]
                record["top_probs"] = topk_probs(phase_probs, names, k=5)

            obs, reward, terminated, truncated, info = env.step_phase(action)

        record["reward"] = float(reward)
        total_reward += reward
        trajectory.append(record)

        if terminated or truncated:
            final_info = info
            break

    outcome = {
        "ante":    int(final_info.get("ante", 1)),
        "reward":  float(total_reward),
        "steps":   len(trajectory),
        "dollars": int(final_info.get("dollars", 0)),
        "won":     bool(final_info.get("ante", 1) > 8),
    }
    return {"seed": seed, "outcome": outcome, "trajectory": trajectory}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--checkpoint", required=True,
                    help="Path to V7 checkpoint (.pt)")
    ap.add_argument("--n-episodes", type=int, default=500)
    ap.add_argument("--output", default="results/eval_trajectories.jsonl")
    ap.add_argument("--hidden", type=int, default=512)
    ap.add_argument("--n-res-blocks", type=int, default=4)
    ap.add_argument("--seed-base", type=int, default=None,
                    help="Base seed for RNG (default: time-based)")
    ap.add_argument("--max-steps", type=int, default=2000)
    ap.add_argument("--greedy", action="store_true",
                    help="Argmax instead of sampling (deployment-style eval)")
    args = ap.parse_args()

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"Loading checkpoint: {args.checkpoint}")
    policy = ActorCriticV7(hidden=args.hidden, n_res_blocks=args.n_res_blocks).eval()
    ckpt = torch.load(args.checkpoint, map_location="cpu", weights_only=False)
    policy.load_state_dict(ckpt["policy"] if "policy" in ckpt else ckpt)
    policy.eval()

    seed_base = args.seed_base if args.seed_base is not None else int(time.time())
    rng = random.Random(seed_base)
    print(f"Seed base: {seed_base}")
    print(f"Writing: {out_path}")

    t0 = time.time()
    wins = 0
    ante_hist: dict[int, int] = {}

    with open(out_path, "w") as f:
        for ep_id in range(args.n_episodes):
            seed = rng.randint(0, 2**31 - 1)
            result = play_episode(policy, seed, max_steps=args.max_steps, greedy=args.greedy)
            result["episode_id"] = ep_id
            f.write(json.dumps(result) + "\n")
            f.flush()

            ante = result["outcome"]["ante"]
            ante_hist[ante] = ante_hist.get(ante, 0) + 1
            if result["outcome"]["won"]:
                wins += 1

            if (ep_id + 1) % 25 == 0 or ep_id == args.n_episodes - 1:
                elapsed = time.time() - t0
                rate = (ep_id + 1) / elapsed
                eta = (args.n_episodes - ep_id - 1) / max(rate, 1e-6)
                print(f"  [{ep_id+1:>5}/{args.n_episodes}] "
                      f"wins={wins} ({100*wins/(ep_id+1):.2f}%)  "
                      f"{rate:.2f} ep/s  ETA {eta/60:.1f}m")

    print(f"\nDone in {(time.time()-t0)/60:.1f} min")
    print(f"Win rate: {wins}/{args.n_episodes} = {100*wins/args.n_episodes:.2f}%")
    print(f"Ante distribution: {dict(sorted(ante_hist.items()))}")


if __name__ == "__main__":
    main()
