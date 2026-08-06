"""
Gradient-based feature importance analysis for V8 checkpoints.

For a set of real observations, compute the gradient of each head's output
with respect to input observations. Features with high gradient magnitude
are the ones the policy is actually using to make decisions.

Groups:
  game_scalars [0:14]
  hand_cards [14:254] (30 features × 8 slots)
  joker_slots [254:304] (10 features × 5 slots)
  shop_items [304:346] (6 features × 7 slots)
  planet_levels [346:358]
  consumables [358:374] (8 features × 2 slots)
  shop_context [374:434]
  mp_state [434:438]  ← the new V8 features

Usage:
  python scripts/analyze_feature_importance.py <checkpoint_path> [--n-samples 500]
"""
import argparse
import numpy as np
import torch
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from balatro_sim.env_mp import MultiplayerBalatroEnv, OBS_DIM
from balatro_sim.env_v7 import (
    PHASE_SELECTING_HAND, N_HAND_SLOTS,
    GAME_SCALARS, CARD_FEATURES, N_JOKER_SLOTS, JOKER_FEATURES,
    N_SHOP_SLOTS, SHOP_FEATURES, PLANET_FEATURES, N_CONS_SLOTS, CONS_FEATURES,
)
from balatro_sim.card_selection import INTENT_PLAY, INTENT_DISCARD, enumerate_subsets
from train_v7 import ActorCriticV7


# Feature group boundaries
GROUPS = [
    ("game_scalars", 0, 14),
    ("hand_cards", 14, 254),       # 8 × 30
    ("joker_slots", 254, 304),     # 5 × 10
    ("shop_items", 304, 346),      # 7 × 6
    ("planet_levels", 346, 358),   # 12
    ("consumables", 358, 374),     # 2 × 8
    ("shop_context", 374, 434),    # reroll, vouchers, boss, deck comp, enhancements
    ("mp_state", 434, 438),        # self_lives, opp_lives, opp_pvp_score, is_pvp
]


def collect_observations(n_samples: int, seed: int = 42) -> np.ndarray:
    """Collect diverse observations by running random policy on MP env."""
    import random as _r
    rng = _r.Random(seed)
    env = MultiplayerBalatroEnv(seed=seed, lives=4)
    env.reset()

    observations = []
    while len(observations) < n_samples:
        # Random play for diverse states
        phase_p1 = env.get_phase(1)
        if phase_p1 == PHASE_SELECTING_HAND:
            n_cards = min(len(env.mp.p1_game.hand), N_HAND_SLOTS)
            if n_cards == 0:
                action_p1 = {"type": "hand", "intent": INTENT_PLAY, "subset": (0,)}
            else:
                k = rng.randint(1, min(5, n_cards))
                action_p1 = {
                    "type": "hand",
                    "intent": rng.choice([INTENT_PLAY, INTENT_DISCARD]),
                    "subset": tuple(rng.sample(range(n_cards), k)),
                }
        else:
            mask = env.get_phase_mask(1)
            valid = [i for i in range(len(mask)) if mask[i]]
            action_p1 = {"type": "phase", "action": valid[0] if valid else 15}

        phase_p2 = env.get_phase(2)
        if phase_p2 == PHASE_SELECTING_HAND:
            n_cards = min(len(env.mp.p2_game.hand), N_HAND_SLOTS)
            if n_cards == 0:
                action_p2 = {"type": "hand", "intent": INTENT_PLAY, "subset": (0,)}
            else:
                k = rng.randint(1, min(5, n_cards))
                action_p2 = {
                    "type": "hand",
                    "intent": rng.choice([INTENT_PLAY, INTENT_DISCARD]),
                    "subset": tuple(rng.sample(range(n_cards), k)),
                }
        else:
            mask = env.get_phase_mask(2)
            valid = [i for i in range(len(mask)) if mask[i]]
            action_p2 = {"type": "phase", "action": valid[0] if valid else 15}

        (p1_obs, p2_obs), _, done, _ = env.step(action_p1, action_p2)
        observations.append(p1_obs)
        observations.append(p2_obs)

        if done:
            env._seed = rng.randint(0, 2**31 - 1)
            env.reset()

    return np.array(observations[:n_samples])


def compute_gradients(policy, obs_np: np.ndarray):
    """Compute gradient magnitudes for each head."""
    obs = torch.from_numpy(obs_np).float()
    obs.requires_grad = True

    trunk = policy.get_trunk(obs)

    # Value head gradient
    value = policy.forward_value(trunk).sum()
    value.backward(retain_graph=True)
    value_grad = obs.grad.abs().mean(dim=0).detach().numpy()
    obs.grad = None

    # Intent head gradient (sum of all logits)
    intent_logits = policy.intent_head(trunk)
    intent_output = intent_logits.abs().sum()
    intent_output.backward(retain_graph=True)
    intent_grad = obs.grad.abs().mean(dim=0).detach().numpy()
    obs.grad = None

    # Phase head gradient
    phase_logits = policy.phase_head(trunk)
    phase_output = phase_logits.abs().sum()
    phase_output.backward()
    phase_grad = obs.grad.abs().mean(dim=0).detach().numpy()

    return {"value": value_grad, "intent": intent_grad, "phase": phase_grad}


def group_importance(feature_grad: np.ndarray) -> dict:
    """Aggregate feature gradients into category groups."""
    result = {}
    total = feature_grad.sum() + 1e-12
    for name, start, end in GROUPS:
        group_sum = feature_grad[start:end].sum()
        group_size = end - start
        result[name] = {
            "total": float(group_sum),
            "pct_of_total": float(group_sum / total * 100),
            "per_feature": float(group_sum / group_size),
            "size": group_size,
            "max_feature": float(feature_grad[start:end].max()),
            "max_idx": int(start + feature_grad[start:end].argmax()),
        }
    return result


def print_report(grad_dict: dict, obs_sample: np.ndarray):
    """Pretty-print feature importance report."""
    print(f"\n{'='*70}")
    print(f"Feature Importance Analysis")
    print(f"{'='*70}")
    print(f"Sampled {len(obs_sample)} observations from random MP play\n")

    for head_name in ["value", "intent", "phase"]:
        print(f"\n--- {head_name.upper()} HEAD ---")
        groups = group_importance(grad_dict[head_name])
        print(f"{'Group':<20} {'Total grad':>12} {'% of total':>12} {'Per-feat':>12} {'Max':>12}")
        print("-" * 70)
        sorted_groups = sorted(groups.items(), key=lambda x: -x[1]['pct_of_total'])
        for name, info in sorted_groups:
            print(f"{name:<20} {info['total']:>12.5f} {info['pct_of_total']:>11.1f}% "
                  f"{info['per_feature']:>12.5f} {info['max_feature']:>12.5f}")

    # MP feature detail
    print(f"\n--- MP STATE DETAIL ({head_name} head gradients) ---")
    mp_names = ["self_lives", "opp_lives", "opp_pvp_score", "is_pvp_blind"]
    for head_name in ["value", "intent", "phase"]:
        mp_grads = grad_dict[head_name][434:438]
        print(f"{head_name:<10}: ", end="")
        for i, name in enumerate(mp_names):
            print(f"{name}={mp_grads[i]:.5f} ", end="")
        print()

    # Sanity check: are the MP features actually being set to non-zero?
    mp_slice = obs_sample[:, 434:438]
    print(f"\n--- MP FEATURE VALUES IN SAMPLED OBS ---")
    for i, name in enumerate(mp_names):
        vals = mp_slice[:, i]
        print(f"{name:<20}: mean={vals.mean():.3f}, std={vals.std():.3f}, "
              f"min={vals.min():.3f}, max={vals.max():.3f}, "
              f"nonzero={100*(vals != 0).mean():.1f}%")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("checkpoint", type=str, help="Path to V8 checkpoint")
    parser.add_argument("--n-samples", type=int, default=500)
    args = parser.parse_args()

    # Load policy
    print(f"Loading checkpoint: {args.checkpoint}")
    ckpt = torch.load(args.checkpoint, map_location="cpu")
    policy = ActorCriticV7(obs_dim=OBS_DIM).cpu().eval()
    policy.load_state_dict(ckpt["policy"])

    # Collect observations
    print(f"Collecting {args.n_samples} observations...")
    obs = collect_observations(args.n_samples)
    print(f"Obs shape: {obs.shape}")

    # Compute gradients
    print("Computing gradients...")
    grads = compute_gradients(policy, obs)

    # Print report
    print_report(grads, obs)


if __name__ == "__main__":
    main()
