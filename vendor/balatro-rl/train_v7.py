"""
train_v7.py — PPO training with hierarchical intent + learned card selection.

Architecture:
  - N worker processes, each running M envs (true parallelism via multiprocessing)
  - Main process handles GPU PPO updates and weight broadcasting
  - SELECTING_HAND: intent head (Discrete(3)) + card scoring head (8-dim)
    -> card scores define distribution over 218 subsets -> sample subset
    -> factored log_prob = log_prob(intent) + log_prob(subset|intent)
  - Other phases: phase head (Discrete(17)) for blind/shop actions

Default: 16 workers x 1 env x 256 steps = 4096 steps/batch

Usage:
    python train_v7.py
    python train_v7.py --workers 16 --iterations 1000
    python train_v7.py --resume checkpoints_v7/iter_0100.pt
    python train_v7.py --migrate-v6 checkpoints_sim/iter_0280.pt
"""

import argparse
import json
import multiprocessing as mp
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim

from balatro_sim.env_v7 import (
    BalatroV7Env, OBS_DIM, N_PHASE_ACTIONS, N_HAND_SLOTS,
    PHASE_SELECTING_HAND, PHASE_BLIND_SELECT, PHASE_SHOP, PHASE_GAME_OVER,
)
from balatro_sim.card_selection import (
    INTENT_PLAY, INTENT_DISCARD, INTENT_USE_CONSUMABLE, N_INTENTS,
    enumerate_subsets, compute_subset_logits,
)


# ════════════════════════════════════════════════════════════════════════════
# Precomputed subset masks for vectorized logit computation
# ════════════════════════════════════════════════════════════════════════════

# For each n_cards value, precompute a binary matrix of shape (n_subsets, n_cards)
# where mask[i][j] = 1 if card j is in subset i. This lets us compute all subset
# logits with a single matmul: subset_logits = subset_mask @ card_scores.
_SUBSET_MASKS: dict[int, np.ndarray] = {}

def _get_subset_mask(n_cards: int) -> np.ndarray:
    """Get or create a (n_subsets, N_HAND_SLOTS) binary mask for subset scoring."""
    if n_cards not in _SUBSET_MASKS:
        subsets = enumerate_subsets(n_cards)
        mask = np.zeros((len(subsets), N_HAND_SLOTS), dtype=np.float32)
        for i, subset in enumerate(subsets):
            for j in subset:
                mask[i, j] = 1.0
        _SUBSET_MASKS[n_cards] = mask
    return _SUBSET_MASKS[n_cards]

# Pre-warm for common sizes
for _nc in range(1, N_HAND_SLOTS + 1):
    _get_subset_mask(_nc)

# ════════════════════════════════════════════════════════════════════════════
# Hyperparameters
# ════════════════════════════════════════════════════════════════════════════

LR             = 3e-4
GAMMA          = 0.99
LAMBDA         = 0.95
CLIP           = 0.2
ENTROPY_COEFF  = 0.01   # for phase actions
INTENT_ENTROPY_COEFF = 0.05  # higher for intent to encourage discard exploration
SUBSET_ENTROPY_COEFF = 0.005  # for subset distribution
VF_COEFF       = 0.5
GRAD_CLIP      = 0.5
N_EPOCHS       = 10
MINIBATCH_SIZE = 128
SUBSET_TEMPERATURE = 1.0  # softmax temperature for subset distribution

LOG_DIR  = Path("logs_v7")
CKPT_DIR = Path("checkpoints_v7")
LOG_DIR.mkdir(exist_ok=True)
CKPT_DIR.mkdir(exist_ok=True)


# ════════════════════════════════════════════════════════════════════════════
# Network
# ════════════════════════════════════════════════════════════════════════════

class ResidualBlock(nn.Module):
    def __init__(self, width: int):
        super().__init__()
        self.fc1  = nn.Linear(width, width)
        self.fc2  = nn.Linear(width, width)
        self.norm = nn.LayerNorm(width)
        nn.init.orthogonal_(self.fc1.weight, gain=np.sqrt(2))
        nn.init.orthogonal_(self.fc2.weight, gain=np.sqrt(2))
        nn.init.constant_(self.fc1.bias, 0)
        nn.init.constant_(self.fc2.bias, 0)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.norm(x + torch.relu(self.fc2(torch.relu(self.fc1(x)))))


class ActorCriticV7(nn.Module):
    """
    V7 hierarchical actor-critic, parameterized for scaling experiments.

    Architecture (with default hidden=512, n_res_blocks=4):
      input (obs_dim) -> embed(H) -> N x ResBlock(H) -> trunk(H)
      trunk -> intent_head(H, 3)
      trunk + intent_embed(3, 32) -> card_head(H+32, H/2, 8, sigmoid)
      trunk -> phase_head(H, 17)
      trunk -> critic(H, 1)

    Default: ~2.5M params (hidden=512, blocks=4)
    Scaling: hidden=1024, blocks=6 → ~12.5M params (5x for V7 Run 7)
    """
    INTENT_EMBED_DIM = 32

    def __init__(self, obs_dim: int = OBS_DIM, hidden: int = 512, n_res_blocks: int = 4):
        super().__init__()
        H = hidden
        self.obs_dim = obs_dim
        self.hidden = hidden
        self.n_res_blocks = n_res_blocks
        # Card head's middle layer scales with hidden (was hard-coded 256 for H=512)
        card_hidden = max(H // 2, 64)

        # Shared trunk
        self.embed = nn.Sequential(nn.Linear(obs_dim, H), nn.ReLU())
        self.res_blocks = nn.Sequential(*[
            ResidualBlock(H) for _ in range(n_res_blocks)
        ])

        # Intent head (SELECTING_HAND)
        self.intent_head = nn.Linear(H, N_INTENTS)

        # Card scoring head (conditioned on intent)
        self.intent_embed = nn.Embedding(N_INTENTS, self.INTENT_EMBED_DIM)
        self.card_head = nn.Sequential(
            nn.Linear(H + self.INTENT_EMBED_DIM, card_hidden),
            nn.ReLU(),
            nn.Linear(card_hidden, N_HAND_SLOTS),
            nn.Sigmoid(),
        )

        # Phase head (BLIND_SELECT + SHOP)
        self.phase_head = nn.Linear(H, N_PHASE_ACTIONS)

        # Critic
        self.critic = nn.Linear(H, 1)

        # Initialize
        nn.init.orthogonal_(self.embed[0].weight, gain=np.sqrt(2))
        nn.init.constant_(self.embed[0].bias, 0)
        nn.init.orthogonal_(self.intent_head.weight, gain=0.01)
        nn.init.constant_(self.intent_head.bias, 0)
        nn.init.orthogonal_(self.phase_head.weight, gain=0.01)
        nn.init.constant_(self.phase_head.bias, 0)
        nn.init.orthogonal_(self.critic.weight, gain=1.0)
        nn.init.constant_(self.critic.bias, 0)
        # Card head — small init for stable start
        nn.init.orthogonal_(self.card_head[0].weight, gain=0.1)
        nn.init.constant_(self.card_head[0].bias, 0)
        nn.init.orthogonal_(self.card_head[2].weight, gain=0.1)
        nn.init.constant_(self.card_head[2].bias, 0)

    def get_trunk(self, obs: torch.Tensor) -> torch.Tensor:
        return self.res_blocks(self.embed(obs))

    def forward_intent(self, trunk: torch.Tensor,
                       intent_mask: torch.Tensor | None = None):
        """Return intent distribution."""
        logits = self.intent_head(trunk)
        if intent_mask is not None:
            logits = logits.masked_fill(~intent_mask, float("-inf"))
        return torch.distributions.Categorical(logits=logits)

    def forward_card_scores(self, trunk: torch.Tensor,
                            intent_idx: torch.Tensor) -> torch.Tensor:
        """Return card scores (B, 8) conditioned on intent."""
        ie = self.intent_embed(intent_idx)  # (B, 32)
        card_input = torch.cat([trunk, ie], dim=-1)  # (B, 544)
        return self.card_head(card_input)  # (B, 8), sigmoid bounded [0,1]

    def forward_phase(self, trunk: torch.Tensor,
                      phase_mask: torch.Tensor | None = None):
        """Return phase action distribution."""
        logits = self.phase_head(trunk)
        if phase_mask is not None:
            logits = logits.masked_fill(~phase_mask, float("-inf"))
        return torch.distributions.Categorical(logits=logits)

    def forward_value(self, trunk: torch.Tensor) -> torch.Tensor:
        return self.critic(trunk).squeeze(-1)

    @torch.no_grad()
    def get_hand_action(self, obs: torch.Tensor, intent_mask: torch.Tensor,
                        n_cards: int, temperature: float = SUBSET_TEMPERATURE):
        """
        Sample intent + subset for SELECTING_HAND phase.
        Returns: (intent, subset_idx, log_prob, value, card_scores_np)
        """
        trunk = self.get_trunk(obs)
        value = self.forward_value(trunk).item()

        # Sample intent
        intent_dist = self.forward_intent(trunk, intent_mask)
        intent = intent_dist.sample()
        log_prob_intent = intent_dist.log_prob(intent).item()

        # Card scores
        card_scores = self.forward_card_scores(trunk, intent)  # (1, 8)
        card_scores_np = card_scores.squeeze(0).numpy()

        # Subset distribution (only for PLAY/DISCARD)
        intent_val = intent.item()
        if intent_val in (INTENT_PLAY, INTENT_DISCARD) and n_cards > 0:
            subsets = enumerate_subsets(n_cards)
            subset_logits = compute_subset_logits(
                card_scores_np[:n_cards], subsets, intent_val, temperature
            )
            subset_logits_t = torch.FloatTensor(subset_logits)
            subset_dist = torch.distributions.Categorical(logits=subset_logits_t)
            subset_idx = subset_dist.sample()
            log_prob_subset = subset_dist.log_prob(subset_idx).item()
            subset_idx = subset_idx.item()
        else:
            subset_idx = 0
            log_prob_subset = 0.0

        total_log_prob = log_prob_intent + log_prob_subset

        return intent_val, subset_idx, total_log_prob, value, card_scores_np

    @torch.no_grad()
    def get_phase_action(self, obs: torch.Tensor, phase_mask: torch.Tensor):
        """Sample phase action for BLIND_SELECT/SHOP."""
        trunk = self.get_trunk(obs)
        value = self.forward_value(trunk).item()
        phase_dist = self.forward_phase(trunk, phase_mask)
        action = phase_dist.sample()
        log_prob = phase_dist.log_prob(action).item()
        return action.item(), log_prob, value

    @torch.no_grad()
    def get_value(self, obs: torch.Tensor) -> float:
        trunk = self.get_trunk(obs)
        return self.forward_value(trunk).item()


# ════════════════════════════════════════════════════════════════════════════
# GAE
# ════════════════════════════════════════════════════════════════════════════

def compute_gae(rewards, values, dones, next_value):
    T = len(rewards)
    adv = np.zeros(T, dtype=np.float32)
    gae = 0.0
    for t in reversed(range(T)):
        nv       = next_value if t == T - 1 else values[t + 1]
        not_done = 1.0 - dones[t]
        delta    = rewards[t] + GAMMA * nv * not_done - values[t]
        adv[t] = gae = delta + GAMMA * LAMBDA * not_done * gae
    return adv, adv + values


# ════════════════════════════════════════════════════════════════════════════
# Worker process
# ════════════════════════════════════════════════════════════════════════════

def _worker_fn(worker_id: int, n_envs: int, steps_target: int,
               conn: mp.connection.Connection, seed_base: int,
               hidden: int = 512, n_res_blocks: int = 4):
    """
    Worker process that runs n_envs in lockstep with batched inference.

    Optimization (Run 5+): Instead of sequential per-env inference, we collect
    obs from all n_envs at once, batch them, and do a SINGLE forward pass per
    step. CPU batched inference is ~10x faster per env-step than sequential calls.

    hidden / n_res_blocks: network architecture (must match main policy).
    """
    import os, random as _random_mod
    os.environ["CUDA_VISIBLE_DEVICES"] = ""
    _rng = _random_mod.Random(seed_base + worker_id * 1000)

    envs = [BalatroV7Env(seed=_rng.randint(0, 2**31 - 1)) for _ in range(n_envs)]
    policy = ActorCriticV7(hidden=hidden, n_res_blocks=n_res_blocks).cpu().eval()

    obs_list = [e.reset()[0] for e in envs]
    ep_steps = [0] * n_envs
    ep_reward = [0.0] * n_envs

    while True:
        msg = conn.recv()
        if msg is None:
            break
        policy.load_state_dict({k: v.cpu() for k, v in msg.items()})
        policy.eval()

        rollout: list[dict] = []
        episodes: list[dict] = []
        deadline = time.time() + 60

        steps_per_env = max(1, steps_target // n_envs)

        for _ in range(steps_per_env):
            if time.time() > deadline:
                break

            # ── Gather all envs into batched inputs ──────────────────────────
            phases = [env.get_phase() for env in envs]
            obs_batch = torch.from_numpy(np.stack(obs_list)).float()  # (n_envs, OBS_DIM)

            # Compute trunk + value for ALL envs in one batched call
            with torch.no_grad():
                trunk = policy.get_trunk(obs_batch)  # (n_envs, HIDDEN)
                values_b = policy.forward_value(trunk).cpu().numpy()  # (n_envs,)

            # Split into hand vs phase indices for separate sampling
            hand_indices = [i for i, p in enumerate(phases) if p == PHASE_SELECTING_HAND]
            phase_indices = [i for i, p in enumerate(phases) if p != PHASE_SELECTING_HAND]

            # Pre-sample for hand envs (batched)
            hand_intents = {}     # i -> intent
            hand_log_probs = {}   # i -> log_prob
            hand_subset_idxs = {} # i -> subset_idx
            hand_card_scores = {} # i -> card_scores np
            hand_n_cards = {}     # i -> n_cards
            hand_intent_masks = {}# i -> mask

            if hand_indices:
                # Build masks
                hand_masks_np = np.stack([envs[i].get_intent_mask() for i in hand_indices])
                hand_mask_t = torch.from_numpy(hand_masks_np).bool()
                hand_trunk = trunk[hand_indices]

                with torch.no_grad():
                    intent_dist = policy.forward_intent(hand_trunk, hand_mask_t)
                    intents_t = intent_dist.sample()
                    intent_lp = intent_dist.log_prob(intents_t).cpu().numpy()
                    intents_np = intents_t.cpu().numpy()

                    # Card scores conditioned on sampled intent
                    card_scores_t = policy.forward_card_scores(hand_trunk, intents_t)  # (H, 8)
                    card_scores_np = card_scores_t.cpu().numpy()

                # Per-env subset sampling (varying n_cards, can't fully batch)
                for j, i in enumerate(hand_indices):
                    intent_val = int(intents_np[j])
                    n_cards = min(len(envs[i].game.hand), N_HAND_SLOTS)
                    log_prob = float(intent_lp[j])
                    subset_idx = 0

                    if intent_val in (INTENT_PLAY, INTENT_DISCARD) and n_cards > 0:
                        subsets = enumerate_subsets(n_cards)
                        cs = card_scores_np[j, :n_cards]
                        subset_logits = compute_subset_logits(cs, subsets, intent_val)
                        sl_t = torch.from_numpy(subset_logits).float()
                        sub_dist = torch.distributions.Categorical(logits=sl_t)
                        si_t = sub_dist.sample()
                        subset_idx = int(si_t.item())
                        log_prob += float(sub_dist.log_prob(si_t).item())

                    hand_intents[i] = intent_val
                    hand_log_probs[i] = log_prob
                    hand_subset_idxs[i] = subset_idx
                    hand_card_scores[i] = card_scores_np[j]
                    hand_n_cards[i] = n_cards
                    hand_intent_masks[i] = hand_masks_np[j]

            # Pre-sample for phase envs (batched)
            phase_actions = {}    # i -> action
            phase_log_probs = {}  # i -> log_prob
            phase_masks_dict = {} # i -> mask

            if phase_indices:
                phase_masks_np = np.stack([envs[i].get_phase_mask() for i in phase_indices])
                phase_mask_t = torch.from_numpy(phase_masks_np).bool()
                phase_trunk = trunk[phase_indices]

                with torch.no_grad():
                    phase_dist = policy.forward_phase(phase_trunk, phase_mask_t)
                    actions_t = phase_dist.sample()
                    phase_lp = phase_dist.log_prob(actions_t).cpu().numpy()
                    actions_np = actions_t.cpu().numpy()

                for j, i in enumerate(phase_indices):
                    phase_actions[i] = int(actions_np[j])
                    phase_log_probs[i] = float(phase_lp[j])
                    phase_masks_dict[i] = phase_masks_np[j]

            # ── Apply actions and collect rollout records ────────────────────
            for i, env in enumerate(envs):
                phase = phases[i]
                value = float(values_b[i])

                if phase == PHASE_SELECTING_HAND:
                    intent = hand_intents[i]
                    subset_idx = hand_subset_idxs[i]
                    log_prob = hand_log_probs[i]
                    n_cards = hand_n_cards[i]

                    if intent in (INTENT_PLAY, INTENT_DISCARD) and n_cards > 0:
                        subsets = enumerate_subsets(n_cards)
                        subset_idx_clamped = min(subset_idx, len(subsets) - 1)
                        subset = subsets[subset_idx_clamped]
                    else:
                        subset = (0,)

                    obs_next, reward, terminated, truncated, info = \
                        env.step_hand(intent, subset)

                    rollout.append({
                        "obs": obs_list[i].copy(),
                        "log_prob": log_prob,
                        "value": value,
                        "reward": float(reward),
                        "done": float(terminated or truncated),
                        "phase_id": PHASE_SELECTING_HAND,
                        "intent": intent,
                        "subset_idx": subset_idx,
                        "n_cards": n_cards,
                        "intent_mask": hand_intent_masks[i].copy(),
                    })
                else:
                    action = phase_actions[i]
                    log_prob = phase_log_probs[i]

                    obs_next, reward, terminated, truncated, info = \
                        env.step_phase(action)

                    rollout.append({
                        "obs": obs_list[i].copy(),
                        "log_prob": log_prob,
                        "value": value,
                        "reward": float(reward),
                        "done": float(terminated or truncated),
                        "phase_id": phase,
                        "phase_action": action,
                        "phase_mask": phase_masks_dict[i].copy(),
                    })

                done = terminated or truncated
                ep_steps[i] += 1
                ep_reward[i] += reward

                if not done and ep_steps[i] >= 2000:
                    done = True

                if done:
                    episodes.append({
                        "steps": ep_steps[i],
                        "ante": info.get("ante", 1),
                        "reward": ep_reward[i],
                        "dollars": info.get("dollars", 0),
                        "won": info.get("ante", 1) > 8,
                    })
                    env._seed = _rng.randint(0, 2**31 - 1)
                    obs_next, _ = env.reset()
                    ep_steps[i] = 0
                    ep_reward[i] = 0.0

                obs_list[i] = obs_next

        # Bootstrap values (batched)
        with torch.no_grad():
            obs_batch = torch.from_numpy(np.stack(obs_list)).float()
            trunk = policy.get_trunk(obs_batch)
            next_values = policy.forward_value(trunk).cpu().numpy().tolist()

        conn.send({
            "rollout": rollout,
            "next_values": next_values,
            "episodes": episodes,
        })


# ════════════════════════════════════════════════════════════════════════════
# PPO update
# ════════════════════════════════════════════════════════════════════════════

def ppo_update(policy, optimizer, rollout_batch, device, minibatch_size=MINIBATCH_SIZE):
    """
    V7 PPO update with factored log_prob reconstruction.

    For SELECTING_HAND steps: reconstruct log_prob = log_prob(intent) + log_prob(subset)
    For other steps: reconstruct log_prob = log_prob(phase_action)
    """
    obs_b    = torch.FloatTensor(rollout_batch["obs"]).to(device)
    ret_b    = torch.FloatTensor(rollout_batch["returns"]).to(device)
    adv_b    = torch.FloatTensor(rollout_batch["advantages"]).to(device)
    logp_b   = torch.FloatTensor(rollout_batch["log_probs"]).to(device)
    phase_b  = torch.LongTensor(rollout_batch["phase_ids"]).to(device)

    # Per-step data for hand/phase reconstruction
    intents_b     = torch.LongTensor(rollout_batch["intents"]).to(device)
    subset_idxs_b = torch.LongTensor(rollout_batch["subset_idxs"]).to(device)
    n_cards_b     = rollout_batch["n_cards"]  # numpy, used for subset enumeration
    intent_masks_b = torch.BoolTensor(rollout_batch["intent_masks"]).to(device)
    phase_actions_b = torch.LongTensor(rollout_batch["phase_actions"]).to(device)
    phase_masks_b   = torch.BoolTensor(rollout_batch["phase_masks"]).to(device)

    adv_b = (adv_b - adv_b.mean()) / (adv_b.std() + 1e-8)
    ret_b = (ret_b - ret_b.mean()) / (ret_b.std() + 1e-8)

    is_hand = (phase_b == PHASE_SELECTING_HAND)

    total_loss = pg_loss_sum = vf_loss_sum = 0.0
    ent_intent_sum = ent_phase_sum = 0.0
    n_batches = 0
    N = len(obs_b)
    idx = np.arange(N)

    for _ in range(N_EPOCHS):
        np.random.shuffle(idx)
        for start in range(0, N, minibatch_size):
            mb = idx[start:start + minibatch_size]
            mb_t = torch.from_numpy(mb).to(device)

            obs_mb = obs_b[mb]
            trunk = policy.get_trunk(obs_mb)
            values = policy.forward_value(trunk)

            # Reconstruct new log_probs for each step
            new_logp = torch.zeros(len(mb), device=device)
            entropy = torch.zeros(len(mb), device=device)

            hand_mask_mb = is_hand[mb]
            phase_mask_mb = ~hand_mask_mb

            # ── SELECTING_HAND steps ──
            if hand_mask_mb.any():
                h_idx = hand_mask_mb.nonzero(as_tuple=True)[0]
                h_trunk = trunk[h_idx]

                h_intent_masks = intent_masks_b[mb[h_idx.cpu().numpy()]]
                intent_dist = policy.forward_intent(h_trunk, h_intent_masks)
                h_intents = intents_b[mb[h_idx.cpu().numpy()]]
                lp_intent = intent_dist.log_prob(h_intents)
                ent_intent = intent_dist.entropy()

                # Reconstruct subset log_prob via card scores (vectorized)
                card_scores = policy.forward_card_scores(h_trunk, h_intents)  # (H, 8)

                h_mb_indices = mb[h_idx.cpu().numpy()]  # numpy array
                h_subset_idxs = subset_idxs_b[h_mb_indices]  # tensor
                h_n_cards = n_cards_b[h_mb_indices]  # numpy array

                lp_subset = torch.zeros(len(h_idx), device=device)
                ent_subset = torch.zeros(len(h_idx), device=device)

                # Batch by n_cards (most steps have n_cards=8, so this is ~1 batch)
                for nc_val in np.unique(h_n_cards):
                    nc_val = int(nc_val)
                    if nc_val <= 0:
                        continue
                    nc_mask = (h_n_cards == nc_val)
                    nc_idx = np.where(nc_mask)[0]
                    if len(nc_idx) == 0:
                        continue

                    # Get precomputed subset mask: (n_subsets, 8)
                    smask = torch.FloatTensor(_get_subset_mask(nc_val)).to(device)
                    n_subsets = smask.shape[0]

                    # Card scores for this batch: (batch, 8)
                    nc_idx_t = torch.from_numpy(nc_idx).to(device)
                    cs_batch = card_scores[nc_idx_t]  # (batch, 8)

                    # For DISCARD: invert scores
                    nc_intents = h_intents[nc_idx_t]
                    is_discard = (nc_intents == INTENT_DISCARD).float().unsqueeze(1)  # (batch, 1)
                    cs_adjusted = cs_batch * (1 - is_discard) + (1 - cs_batch) * is_discard  # (batch, 8)

                    # Compute all subset logits at once: (batch, n_subsets)
                    subset_logits = cs_adjusted @ smask.T  # (batch, 8) @ (8, n_subsets) = (batch, n_subsets)

                    if SUBSET_TEMPERATURE != 1.0:
                        subset_logits = subset_logits / SUBSET_TEMPERATURE

                    # Mask out USE_CONSUMABLE steps (no subset needed)
                    is_consumable = (nc_intents == INTENT_USE_CONSUMABLE)

                    sub_dist = torch.distributions.Categorical(logits=subset_logits)
                    si_batch = h_subset_idxs[nc_idx_t].clamp(0, n_subsets - 1)
                    lp_batch = sub_dist.log_prob(si_batch)
                    ent_batch = sub_dist.entropy()

                    # Zero out log_prob/entropy for consumable steps
                    lp_batch[is_consumable] = 0.0
                    ent_batch[is_consumable] = 0.0

                    lp_subset[nc_idx_t] = lp_batch
                    ent_subset[nc_idx_t] = ent_batch

                new_logp[h_idx] = lp_intent + lp_subset
                entropy[h_idx] = INTENT_ENTROPY_COEFF * ent_intent + \
                                 SUBSET_ENTROPY_COEFF * ent_subset
                ent_intent_sum += ent_intent.mean().item()

            # ── Phase steps ──
            if phase_mask_mb.any():
                p_idx = phase_mask_mb.nonzero(as_tuple=True)[0]
                p_trunk = trunk[p_idx]
                p_masks = phase_masks_b[mb[p_idx.cpu().numpy()]]
                phase_dist = policy.forward_phase(p_trunk, p_masks)
                p_actions = phase_actions_b[mb[p_idx.cpu().numpy()]]
                lp_phase = phase_dist.log_prob(p_actions)
                ent_phase = phase_dist.entropy()

                new_logp[p_idx] = lp_phase
                entropy[p_idx] = ENTROPY_COEFF * ent_phase
                ent_phase_sum += ent_phase.mean().item()

            # ── PPO loss ──
            ratio = torch.exp(new_logp - logp_b[mb])
            adv_mb = adv_b[mb]
            loss_pg = -torch.min(
                ratio * adv_mb,
                torch.clamp(ratio, 1 - CLIP, 1 + CLIP) * adv_mb
            ).mean()
            loss_vf = F.mse_loss(values, ret_b[mb])
            loss_ent = -entropy.mean()

            loss = loss_pg + VF_COEFF * loss_vf + loss_ent

            optimizer.zero_grad()
            loss.backward()
            nn.utils.clip_grad_norm_(policy.parameters(), GRAD_CLIP)
            optimizer.step()

            total_loss += loss.item()
            pg_loss_sum += loss_pg.item()
            vf_loss_sum += loss_vf.item()
            n_batches += 1

    n = max(n_batches, 1)
    return {
        "loss": total_loss / n,
        "pg_loss": pg_loss_sum / n,
        "vf_loss": vf_loss_sum / n,
        "ent_intent": ent_intent_sum / n,
        "ent_phase": ent_phase_sum / n,
    }


# ════════════════════════════════════════════════════════════════════════════
# Weight migration from V6
# ════════════════════════════════════════════════════════════════════════════

def migrate_v6_weights(v6_path: str, model: ActorCriticV7):
    """Transfer compatible weights from V6 checkpoint to V7 model."""
    ckpt = torch.load(v6_path, map_location="cpu")
    v6_sd = ckpt["policy"]
    v7_sd = model.state_dict()

    transferred = []

    # Embed: V6 is (512, 402), V7 is (512, 434). Copy first 402 cols.
    old_w = v6_sd["embed.0.weight"]  # (512, 402)
    v7_sd["embed.0.weight"][:, :old_w.shape[1]] = old_w
    v7_sd["embed.0.bias"] = v6_sd["embed.0.bias"]
    transferred.append("embed")

    # Residual blocks: identical shape, copy directly
    for key in v6_sd:
        if key.startswith("res_blocks."):
            if key in v7_sd and v6_sd[key].shape == v7_sd[key].shape:
                v7_sd[key] = v6_sd[key]
                transferred.append(key)

    # Critic: same shape
    if v6_sd["critic.weight"].shape == v7_sd["critic.weight"].shape:
        v7_sd["critic.weight"] = v6_sd["critic.weight"]
        v7_sd["critic.bias"] = v6_sd["critic.bias"]
        transferred.append("critic")

    model.load_state_dict(v7_sd)
    print(f"  Migrated {len(transferred)} weight groups from V6")
    return model


# ════════════════════════════════════════════════════════════════════════════
# Main training loop
# ════════════════════════════════════════════════════════════════════════════

def train(num_workers: int, envs_per_worker: int, steps_per_worker: int,
          num_iterations: int, resume_path: str | None,
          migrate_v6_path: str | None, minibatch_size: int = MINIBATCH_SIZE,
          hidden: int = 512, n_res_blocks: int = 4, lr: float = LR):

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    batch_size = num_workers * envs_per_worker * steps_per_worker

    policy = ActorCriticV7(hidden=hidden, n_res_blocks=n_res_blocks).to(device)
    optimizer = optim.Adam(policy.parameters(), lr=lr, eps=1e-5)

    start_iter = 0
    total_steps = 0
    best_ante = 1
    episode_log: list[dict] = []

    if resume_path and Path(resume_path).exists():
        ckpt = torch.load(resume_path, map_location=device)
        policy.load_state_dict(ckpt["policy"])
        optimizer.load_state_dict(ckpt["optimizer"])
        start_iter = ckpt.get("iteration", 0)
        total_steps = ckpt.get("total_steps", 0)
        best_ante = ckpt.get("best_ante", 1)
        print(f"Resumed from {resume_path} (iter {start_iter}, {total_steps:,} steps)")
    elif migrate_v6_path and Path(migrate_v6_path).exists():
        migrate_v6_weights(migrate_v6_path, policy)
        policy = policy.to(device)
        print(f"Migrated V6 weights from {migrate_v6_path}")

    # Spawn workers
    seed_base = int(time.time()) % 100000
    workers: list[mp.Process] = []
    conns_main: list[mp.connection.Connection] = []

    for wid in range(num_workers):
        conn_main, conn_worker = mp.Pipe()
        p = mp.Process(
            target=_worker_fn,
            args=(wid, envs_per_worker, steps_per_worker, conn_worker, seed_base,
                  hidden, n_res_blocks),
            daemon=True,
        )
        p.start()
        workers.append(p)
        conns_main.append(conn_main)

    n_params = sum(p.numel() for p in policy.parameters())
    print(f"\n{'='*70}")
    print(f"train_v7.py — V7 Hierarchical Intent + Learned Card Selection")
    print(f"  workers={num_workers}  envs/worker={envs_per_worker}  "
          f"steps/worker={steps_per_worker}")
    print(f"  batch_size={batch_size:,}  minibatch={minibatch_size}  epochs={N_EPOCHS}")
    print(f"  obs={OBS_DIM}  intents={N_INTENTS}  phase_actions={N_PHASE_ACTIONS}")
    print(f"  network: hidden={hidden} blocks={n_res_blocks} params={n_params:,}")
    print(f"  device={device}  lr={lr}")
    print(f"  intent_ent={INTENT_ENTROPY_COEFF}  subset_ent={SUBSET_ENTROPY_COEFF}  "
          f"phase_ent={ENTROPY_COEFF}")
    print(f"{'='*70}\n")

    log_path = LOG_DIR / "training_v7.log"
    t_start = time.time()
    t_iter = t_start

    weights = {k: v.cpu() for k, v in policy.state_dict().items()}

    for iteration in range(start_iter, start_iter + num_iterations):

        # Send weights to workers
        for conn in conns_main:
            conn.send(weights)

        # Collect rollouts
        all_obs, all_ret, all_adv, all_logp = [], [], [], []
        all_phase_ids, all_intents, all_subset_idxs, all_n_cards = [], [], [], []
        all_intent_masks, all_phase_actions, all_phase_masks = [], [], []
        iter_episodes: list[dict] = []
        intent_counts = [0, 0, 0]

        for conn in conns_main:
            data = conn.recv()
            r = data["rollout"]
            nvs = data["next_values"]
            eps = data["episodes"]
            iter_episodes.extend(eps)

            if not r:
                continue

            rewards = np.array([s["reward"]  for s in r], dtype=np.float32)
            values  = np.array([s["value"]   for s in r], dtype=np.float32)
            dones   = np.array([s["done"]    for s in r], dtype=np.float32)
            logps   = np.array([s["log_prob"] for s in r], dtype=np.float32)
            obs_arr = np.stack([s["obs"]     for s in r])

            phase_ids = np.array([s["phase_id"] for s in r], dtype=np.int64)
            intents = np.array([s.get("intent", 0) for s in r], dtype=np.int64)
            subset_idxs = np.array([s.get("subset_idx", 0) for s in r], dtype=np.int64)
            n_cards = np.array([s.get("n_cards", 0) for s in r], dtype=np.int64)

            # Masks: fill with defaults for steps of wrong phase
            intent_masks = np.zeros((len(r), N_INTENTS), dtype=bool)
            phase_masks = np.zeros((len(r), N_PHASE_ACTIONS), dtype=bool)
            phase_actions = np.zeros(len(r), dtype=np.int64)

            for j, s in enumerate(r):
                if s["phase_id"] == PHASE_SELECTING_HAND:
                    intent_masks[j] = s.get("intent_mask", np.ones(N_INTENTS, dtype=bool))
                    intent_counts[s.get("intent", 0)] += 1
                else:
                    phase_masks[j] = s.get("phase_mask", np.ones(N_PHASE_ACTIONS, dtype=bool))
                    phase_actions[j] = s.get("phase_action", 0)

            # GAE per env
            n_per_env = len(r) // envs_per_worker
            for ei in range(envs_per_worker):
                sl = slice(ei * n_per_env, (ei + 1) * n_per_env)
                nv = nvs[ei] if ei < len(nvs) else 0.0
                adv, ret = compute_gae(rewards[sl], values[sl], dones[sl], nv)
                all_obs.append(obs_arr[sl])
                all_ret.append(ret)
                all_adv.append(adv)
                all_logp.append(logps[sl])
                all_phase_ids.append(phase_ids[sl])
                all_intents.append(intents[sl])
                all_subset_idxs.append(subset_idxs[sl])
                all_n_cards.append(n_cards[sl])
                all_intent_masks.append(intent_masks[sl])
                all_phase_actions.append(phase_actions[sl])
                all_phase_masks.append(phase_masks[sl])

        if not all_obs:
            continue

        rollout_batch = {
            "obs":           np.concatenate(all_obs),
            "returns":       np.concatenate(all_ret),
            "advantages":    np.concatenate(all_adv),
            "log_probs":     np.concatenate(all_logp),
            "phase_ids":     np.concatenate(all_phase_ids),
            "intents":       np.concatenate(all_intents),
            "subset_idxs":   np.concatenate(all_subset_idxs),
            "n_cards":       np.concatenate(all_n_cards),
            "intent_masks":  np.concatenate(all_intent_masks),
            "phase_actions": np.concatenate(all_phase_actions),
            "phase_masks":   np.concatenate(all_phase_masks),
        }

        total_steps += len(rollout_batch["obs"])

        # PPO update
        metrics = ppo_update(policy, optimizer, rollout_batch, device, minibatch_size)
        weights = {k: v.cpu() for k, v in policy.state_dict().items()}

        # Logging
        t_now = time.time()
        iter_sec = max(t_now - t_iter, 1e-6)
        t_iter = t_now
        sps = len(rollout_batch["obs"]) / iter_sec
        eps = len(iter_episodes)

        if iter_episodes:
            iter_best = max(e["ante"] for e in iter_episodes)
            if iter_best > best_ante:
                best_ante = iter_best
                tag = f"  *** NEW BEST ante={best_ante} ***"
            else:
                tag = ""
            mean_reward = np.mean([e["reward"] for e in iter_episodes])
            wins = sum(1 for e in iter_episodes if e["won"])
        else:
            iter_best = best_ante
            tag = ""
            mean_reward = 0.0
            wins = 0

        total_intents = sum(intent_counts)
        if total_intents > 0:
            pct_play = intent_counts[0] / total_intents * 100
            pct_disc = intent_counts[1] / total_intents * 100
            pct_cons = intent_counts[2] / total_intents * 100
            intent_str = f"P={pct_play:.0f}% D={pct_disc:.0f}% C={pct_cons:.0f}%"
        else:
            intent_str = "N/A"

        status = (
            f"[{total_steps/1e6:.3f}M] iter={iteration+1:<5d} "
            f"sps={sps:<8.0f} eps={eps:<5d} wins={wins:<3d} "
            f"rew={mean_reward:<7.2f} "
            f"loss={metrics['loss']:.4f} pg={metrics['pg_loss']:.4f} "
            f"vf={metrics['vf_loss']:.4f} "
            f"ent_i={metrics['ent_intent']:.3f} ent_p={metrics['ent_phase']:.3f} "
            f"intents=[{intent_str}] "
            f"best={best_ante} ({iter_sec:.1f}s){tag}"
        )
        print(status)
        with open(log_path, "a") as f:
            f.write(status + "\n")

        for ep in iter_episodes:
            ep["iteration"] = iteration + 1
        episode_log.extend(iter_episodes)

        # Checkpoint every 10 iters
        if (iteration + 1) % 10 == 0:
            ckpt_path = CKPT_DIR / f"iter_{iteration+1:04d}.pt"
            torch.save({
                "policy": policy.state_dict(),
                "optimizer": optimizer.state_dict(),
                "iteration": iteration + 1,
                "total_steps": total_steps,
                "best_ante": best_ante,
            }, ckpt_path)
            with open(CKPT_DIR / "episode_log.jsonl", "a") as f:
                for ep in episode_log:
                    f.write(json.dumps(ep) + "\n")
            episode_log.clear()
            print(f"  -> checkpoint saved: {ckpt_path}")

    # Shutdown
    for conn in conns_main:
        conn.send(None)
    for p in workers:
        p.join(timeout=5)

    total_time = time.time() - t_start
    print(f"\nDone. {num_iterations} iters | {total_steps:,} steps | "
          f"{total_time/60:.1f} min | best ante: {best_ante}")


# ════════════════════════════════════════════════════════════════════════════
# Entry point
# ════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    mp.set_start_method("spawn", force=True)

    parser = argparse.ArgumentParser()
    parser.add_argument("--workers",          type=int, default=16)
    parser.add_argument("--envs-per-worker",  type=int, default=1)
    parser.add_argument("--steps-per-worker", type=int, default=256)
    parser.add_argument("--iterations",       type=int, default=1000)
    parser.add_argument("--resume",           type=str, default=None)
    parser.add_argument("--migrate-v6",       type=str, default=None,
                        help="Path to V6 checkpoint for weight migration")
    parser.add_argument("--minibatch",        type=int, default=MINIBATCH_SIZE)
    # Run 7 scaling experiment: bigger network parameters
    parser.add_argument("--hidden",           type=int, default=512,
                        help="Hidden dim for trunk (default 512). Try 1024 for ~5x params.")
    parser.add_argument("--res-blocks",       type=int, default=4,
                        help="Number of residual blocks (default 4). Try 6 for ~5x params with hidden=1024.")
    parser.add_argument("--lr",               type=float, default=LR,
                        help="Learning rate (default 3e-4). Lower (e.g. 2e-4) for bigger networks.")
    args = parser.parse_args()

    train(
        num_workers      = args.workers,
        envs_per_worker  = args.envs_per_worker,
        steps_per_worker = args.steps_per_worker,
        num_iterations   = args.iterations,
        resume_path      = args.resume,
        migrate_v6_path  = args.migrate_v6,
        minibatch_size   = args.minibatch,
        hidden           = args.hidden,
        n_res_blocks     = args.res_blocks,
        lr               = args.lr,
    )
