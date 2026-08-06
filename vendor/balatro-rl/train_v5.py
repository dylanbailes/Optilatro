"""
train_v5.py — Dual-agent PPO training on the Python Balatro simulation (V5).

Architecture:
  - Two ActorCritic networks: PlayActorCritic (374->46) and ShopActorCritic (188->17)
  - N worker processes collecting TWO rollout buffers (play + shop) per iteration
  - Main process handles GPU PPO updates for both agents
  - ShopActorCritic produces a 32-dim communication vector fed to play obs

Phase A (default): frozen play agent (loaded from v4 run 6), train shop only
Phase B: both agents train jointly

Usage:
    python train_v5.py
    python train_v5.py --training-phase A --workers 16 --steps 4096
    python train_v5.py --training-phase B --resume-play ckpt_play.pt --resume-shop ckpt_shop.pt
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
import torch.optim as optim

from balatro_sim.env_v5 import (
    BalatroSimEnvV5,
    PLAY_OBS_DIM, PLAY_OBS_BASE, SHOP_OBS_DIM, PLAY_N_ACTIONS, SHOP_N_ACTIONS, COMM_DIM,
    SUBSTATE_NORMAL, SUBSTATE_PACK_OPEN, SUBSTATE_PACK_TARGET,
    HAND_TYPES,
)
from balatro_sim.game import State
from balatro_sim.consumables import ALL_PLANETS

# ════════════════════════════════════════════════════════════════════════════
# Hyperparameters
# ════════════════════════════════════════════════════════════════════════════

LR             = 3e-4
GAMMA          = 0.99
LAMBDA         = 0.95
CLIP           = 0.2
ENTROPY_COEFF       = 0.03   # shop agent — higher to prevent early collapse with sparse data
ENTROPY_COEFF_PLAY  = 0.01   # play agent — low is fine, best combo is the right action
ENTROPY_FLOOR_SHOP  = 0.3    # minimum shop entropy — prevents collapse to deterministic policy
ENTROPY_FLOOR_PLAY  = 0.0    # no play floor — let it exploit best combo
VF_COEFF       = 0.5
GRAD_CLIP      = 0.5
N_EPOCHS       = 10
MINIBATCH_SIZE = 128

LOG_DIR  = Path("logs_sim")
CKPT_DIR = Path("checkpoints_v5")
LOG_DIR.mkdir(exist_ok=True)
CKPT_DIR.mkdir(exist_ok=True)


# ════════════════════════════════════════════════════════════════════════════
# Action masking
# ════════════════════════════════════════════════════════════════════════════

def get_play_action_mask(env: BalatroSimEnvV5) -> np.ndarray:
    """Return bool mask of shape (PLAY_N_ACTIONS,) — True = action is valid."""
    mask = np.zeros(PLAY_N_ACTIONS, dtype=bool)
    gs = env.game

    if gs.state == State.BLIND_SELECT:
        mask[30] = True
        mask[31] = (gs.current_blind.kind != "Boss")

    elif gs.state == State.SELECTING_HAND:
        n_combos = len(env._play_combos)
        mask[0:min(n_combos, 20)] = True
        if gs.discards_left > 0:
            for i in range(min(len(gs.hand), 8)):
                mask[20 + i] = True
        for i, key in enumerate(gs.consumable_hand[:2]):
            if key in ALL_PLANETS:
                mask[28 + i] = True

    elif gs.state == State.GAME_OVER:
        mask[45] = True

    if not mask.any():
        mask[45] = True

    return mask


def get_shop_action_mask(env: BalatroSimEnvV5, info: dict) -> np.ndarray:
    """Return bool mask for the shop agent, handling all substates."""
    substate = info["shop_substate"]

    if substate == SUBSTATE_PACK_OPEN:
        n = len(info["pack_choices"])
        mask = np.ones(n + 1, dtype=bool)
        # Pad to SHOP_N_ACTIONS for the rollout buffer
        full_mask = np.zeros(SHOP_N_ACTIONS, dtype=bool)
        full_mask[:min(n + 1, SHOP_N_ACTIONS)] = mask[:SHOP_N_ACTIONS]
        return full_mask

    if substate == SUBSTATE_PACK_TARGET:
        full_mask = np.zeros(SHOP_N_ACTIONS, dtype=bool)
        deck_len = len(env.game.deck)
        for i in range(min(deck_len, min(52, SHOP_N_ACTIONS))):
            full_mask[i] = True
        if SHOP_N_ACTIONS > 52:
            full_mask[52] = True
        # For pack_target, all valid actions are 0..52; we clamp in worker
        # Just mark leave as fallback
        if not full_mask.any():
            full_mask[1] = True
        return full_mask

    # Normal shop substate
    mask = env.get_shop_action_mask()
    # Safety: leave (action 1) is always valid — prevents all-masked NaN logits
    if not mask.any():
        mask[1] = True
    return mask


# ════════════════════════════════════════════════════════════════════════════
# Networks
# ════════════════════════════════════════════════════════════════════════════

class ResidualBlock(nn.Module):
    """Two-layer residual block with LayerNorm."""
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


class PlayActorCritic(nn.Module):
    """Play agent: 374-dim obs -> 46 actions."""
    HIDDEN = 512

    def __init__(self):
        super().__init__()
        H = self.HIDDEN
        self.embed = nn.Sequential(nn.Linear(PLAY_OBS_DIM, H), nn.ReLU())
        self.res_blocks = nn.Sequential(
            ResidualBlock(H), ResidualBlock(H),
            ResidualBlock(H), ResidualBlock(H),
        )
        self.actor  = nn.Linear(H, PLAY_N_ACTIONS)
        self.critic = nn.Linear(H, 1)
        self.comm_head = nn.Linear(H, COMM_DIM)

        nn.init.orthogonal_(self.embed[0].weight, gain=np.sqrt(2))
        nn.init.constant_(self.embed[0].bias, 0)
        # Zero-init the comm vector columns so all-zero comm input = no effect
        with torch.no_grad():
            self.embed[0].weight[:, PLAY_OBS_BASE:] = 0.0
        nn.init.orthogonal_(self.actor.weight,  gain=0.01)
        nn.init.constant_(self.actor.bias,  0)
        nn.init.orthogonal_(self.critic.weight, gain=1.0)
        nn.init.constant_(self.critic.bias, 0)

    def forward(self, obs, mask=None):
        x      = self.res_blocks(self.embed(obs))
        logits = self.actor(x)
        logits = torch.nan_to_num(logits, nan=0.0, posinf=10.0, neginf=-10.0)
        if mask is not None:
            safe_mask = mask.clone()
            all_invalid = ~safe_mask.any(dim=-1, keepdim=True)
            if all_invalid.any():
                safe_mask[all_invalid.squeeze(-1), 45] = True  # action 45 = leave/noop
            logits = logits.masked_fill(~safe_mask, float("-inf"))
        dist  = torch.distributions.Categorical(logits=logits)
        value = self.critic(x).squeeze(-1)
        return dist, value

    @torch.no_grad()
    def get_action(self, obs, mask=None):
        dist, value = self.forward(obs, mask)
        action = dist.sample()
        return action.item(), dist.log_prob(action).item(), value.item()

    @torch.no_grad()
    def get_value(self, obs, mask=None):
        _, value = self.forward(obs, mask)
        return value.item()


class ShopActorCritic(nn.Module):
    """Shop agent: 188-dim obs -> 17 actions + 32-dim comm vector."""
    HIDDEN = 512

    def __init__(self):
        super().__init__()
        H = self.HIDDEN
        self.embed = nn.Sequential(nn.Linear(SHOP_OBS_DIM, H), nn.ReLU())
        self.res_blocks = nn.Sequential(
            ResidualBlock(H), ResidualBlock(H),
            ResidualBlock(H), ResidualBlock(H),
        )
        self.actor  = nn.Linear(H, SHOP_N_ACTIONS)
        self.critic = nn.Linear(H, 1)
        self.comm_head = nn.Linear(H, COMM_DIM)

        nn.init.orthogonal_(self.embed[0].weight, gain=np.sqrt(2))
        nn.init.constant_(self.embed[0].bias, 0)
        nn.init.orthogonal_(self.actor.weight,  gain=0.01)
        nn.init.constant_(self.actor.bias,  0)
        nn.init.orthogonal_(self.critic.weight, gain=1.0)
        nn.init.constant_(self.critic.bias, 0)

    def forward(self, obs, mask=None):
        x      = self.res_blocks(self.embed(obs))
        logits = self.actor(x)
        logits = torch.nan_to_num(logits, nan=0.0, posinf=10.0, neginf=-10.0)
        if mask is not None:
            safe_mask = mask.clone()
            all_invalid = ~safe_mask.any(dim=-1, keepdim=True)
            safe_mask = safe_mask | (all_invalid.expand_as(safe_mask) & (torch.arange(safe_mask.shape[-1], device=safe_mask.device) == 1).unsqueeze(0))
            logits = logits.masked_fill(~safe_mask, float("-inf"))
        dist     = torch.distributions.Categorical(logits=logits)
        value    = self.critic(x).squeeze(-1)
        comm_vec = self.comm_head(x)
        return dist, value, comm_vec

    @torch.no_grad()
    def get_action(self, obs, mask=None):
        dist, value, comm_vec = self.forward(obs, mask)
        action = dist.sample()
        return action.item(), dist.log_prob(action).item(), value.item(), comm_vec.squeeze(0)

    @torch.no_grad()
    def get_value(self, obs, mask=None):
        _, value, _ = self.forward(obs, mask)
        return value.item()


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

def _heuristic_play_action(env):
    """Scripted play policy: always play the best combo, skip non-boss blinds.
    Used by shop-focused workers to blaze through play phases and reach shops."""
    gs = env.game
    if gs.state == State.BLIND_SELECT:
        return 30  # always play blind (don't skip — we want to reach shop via clearing)
    elif gs.state == State.SELECTING_HAND:
        mask = get_play_action_mask(env)
        if mask[0]:
            return 0   # play best combo
        # Fallback: first valid action
        valid = np.where(mask)[0]
        return int(valid[0]) if len(valid) else 30
    return 30


def _worker_fn(worker_id: int, steps_target: int,
               conn: mp.connection.Connection, seed_base: int,
               min_shop_steps: int = 0, shop_focused: bool = False):
    """
    Runs in a separate process. Collects play and shop rollouts, sends both to main.
    Receives updated weight dicts for both policies each iteration.

    If shop_focused=True, uses a heuristic play policy (no neural net) to blaze
    through play phases and maximize shop data collection. Play rollouts from
    shop-focused workers are discarded (not sent to PPO).
    """
    import os
    os.environ["CUDA_VISIBLE_DEVICES"] = ""

    env = BalatroSimEnvV5(seed=seed_base + worker_id * 100)
    play_policy = PlayActorCritic().cpu().eval() if not shop_focused else None
    shop_policy = ShopActorCritic().cpu().eval()

    obs, info = env.reset()
    ep_steps  = 0
    ep_reward = 0.0

    while True:
        msg = conn.recv()
        if msg is None:
            break
        if play_policy is not None:
            play_policy.load_state_dict({k: v.cpu() for k, v in msg["play"].items()})
            play_policy.eval()
        shop_policy.load_state_dict({k: v.cpu() for k, v in msg["shop"].items()})
        shop_policy.eval()

        play_rollout: list[dict] = []
        shop_rollout: list[dict] = []
        episodes: list[dict] = []
        deadline = time.time() + 180  # 3 min timeout
        MAX_EP_STEPS = 4000
        total_collected = 0

        # Shop-focused workers collect more shop steps, normal workers cap play data
        target_shop = min_shop_steps * (4 if shop_focused else 1)
        play_cap = steps_target * 2  # cap play rollout size for PPO efficiency

        while True:
            have_enough_shop = len(shop_rollout) >= target_shop
            have_enough_play = len(play_rollout) >= steps_target or shop_focused
            if have_enough_play and have_enough_shop:
                break
            if total_collected >= steps_target * 16:
                break
            if time.time() > deadline:
                break

            agent = info["agent"]

            if agent == "play":
                if shop_focused:
                    # Heuristic: no neural net, no rollout data
                    action = _heuristic_play_action(env)
                    next_obs, reward, terminated, truncated, info = env.step(action)
                    done = terminated or truncated
                else:
                    mask   = get_play_action_mask(env)
                    obs_t  = torch.FloatTensor(obs).unsqueeze(0)
                    mask_t = torch.BoolTensor(mask).unsqueeze(0)
                    action, log_prob, value = play_policy.get_action(obs_t, mask_t)

                    next_obs, reward, terminated, truncated, info = env.step(action)
                    done = terminated or truncated

                    # Only append play data up to the cap
                    if len(play_rollout) < play_cap:
                        play_rollout.append({
                            "obs":      obs.copy(),
                            "action":   action,
                            "reward":   float(reward),
                            "done":     float(done),
                            "log_prob": log_prob,
                            "value":    value,
                            "mask":     mask.copy(),
                        })

            else:  # shop agent
                substate = info["shop_substate"]
                mask = get_shop_action_mask(env, info)
                obs_t  = torch.FloatTensor(obs).unsqueeze(0)
                mask_t = torch.BoolTensor(mask).unsqueeze(0)
                action, log_prob, value, comm_vec = shop_policy.get_action(obs_t, mask_t)

                # Clamp action for pack substates
                if substate == SUBSTATE_PACK_OPEN:
                    n_cards = len(info["pack_choices"])
                    action = action % (n_cards + 1)
                elif substate == SUBSTATE_PACK_TARGET:
                    action = action % 53

                next_obs, reward, terminated, truncated, info = env.step(action)
                done = terminated or truncated

                # Set comm vec after each shop forward pass
                env.set_comm_vec(comm_vec.detach().cpu().numpy())

                shop_rollout.append({
                    "obs":      obs.copy(),
                    "action":   action,
                    "reward":   float(reward),
                    "done":     float(done),
                    "log_prob": log_prob,
                    "value":    value,
                    "mask":     mask.copy(),
                })

            ep_steps  += 1
            ep_reward += reward
            total_collected += 1

            if ep_steps >= MAX_EP_STEPS:
                done = True
                terminated = True

            if done:
                episodes.append({
                    "steps":   ep_steps,
                    "ante":    info.get("ante", getattr(env.game, "ante", 1)),
                    "reward":  ep_reward,
                    "dollars": info.get("dollars", getattr(env.game, "dollars", 0)),
                    "won":     getattr(env.game, "won", False),
                })
                next_obs, info = env.reset()
                ep_steps  = 0
                ep_reward = 0.0

            obs = next_obs

        # Trim play rollout to cap for PPO efficiency (keep most recent)
        if len(play_rollout) > play_cap:
            play_rollout = play_rollout[-play_cap:]

        # Bootstrap values for GAE
        agent = info["agent"]
        play_next_val = 0.0
        shop_next_val = 0.0
        if agent == "play" and play_policy is not None:
            mask_t = torch.BoolTensor(get_play_action_mask(env)).unsqueeze(0)
            obs_t  = torch.FloatTensor(obs).unsqueeze(0)
            play_next_val = play_policy.get_value(obs_t, mask_t)
        elif agent != "play":
            mask_t = torch.BoolTensor(get_shop_action_mask(env, info)).unsqueeze(0)
            obs_t  = torch.FloatTensor(obs).unsqueeze(0)
            shop_next_val = shop_policy.get_value(obs_t, mask_t)
        # If shop_focused and agent=="play", both bootstrap to 0.0 (no play data anyway)

        conn.send({
            "play_rollout":   play_rollout,
            "shop_rollout":   shop_rollout,
            "play_next_val":  play_next_val,
            "shop_next_val":  shop_next_val,
            "episodes":       episodes,
        })


# ════════════════════════════════════════════════════════════════════════════
# PPO update
# ════════════════════════════════════════════════════════════════════════════

def ppo_update(policy, optimizer, obs_b, act_b, ret_b, adv_b, logp_b, mask_b, device,
               minibatch_size: int = MINIBATCH_SIZE, is_shop: bool = False,
               entropy_coeff: float = ENTROPY_COEFF,
               entropy_floor: float = 0.0):
    """Run PPO update. Returns (total_loss, pg_loss, vf_loss, entropy)."""
    obs_b  = torch.FloatTensor(obs_b).to(device)
    act_b  = torch.LongTensor(act_b).to(device)
    ret_b  = torch.FloatTensor(ret_b).to(device)
    adv_b  = torch.FloatTensor(adv_b).to(device)
    logp_b = torch.FloatTensor(logp_b).to(device)
    mask_b = torch.BoolTensor(mask_b).to(device)

    adv_b = (adv_b - adv_b.mean()) / (adv_b.std() + 1e-8)
    ret_b = (ret_b - ret_b.mean()) / (ret_b.std() + 1e-8)

    # Clamp any inf/nan that crept in before sending to GPU
    adv_b = torch.nan_to_num(adv_b, nan=0.0, posinf=5.0, neginf=-5.0)
    ret_b = torch.nan_to_num(ret_b, nan=0.0, posinf=5.0, neginf=-5.0)

    # Safety: ensure no all-False mask rows (would cause all-inf logits -> NaN)
    # Force action 1 (leave/noop) valid on any row with no valid action
    all_invalid = ~mask_b.any(dim=-1, keepdim=True)  # (N, 1)
    if all_invalid.any():
        fallback = torch.zeros_like(mask_b)
        fallback[:, 1] = True
        mask_b = mask_b | (all_invalid & fallback)

    total_loss = pg_loss = vf_loss = ent_loss = 0.0
    n_batches  = 0
    idx        = np.arange(len(obs_b))

    for _ in range(N_EPOCHS):
        np.random.shuffle(idx)
        for start in range(0, len(idx), minibatch_size):
            mb = idx[start:start + minibatch_size]
            if is_shop:
                dist, values, _ = policy.forward(obs_b[mb], mask_b[mb])
            else:
                dist, values = policy.forward(obs_b[mb], mask_b[mb])
            new_logp = dist.log_prob(act_b[mb])
            entropy  = dist.entropy().mean()
            ratio    = torch.exp(new_logp - logp_b[mb])
            adv_mb   = adv_b[mb]
            loss_pg  = -torch.min(ratio * adv_mb,
                                  torch.clamp(ratio, 1-CLIP, 1+CLIP) * adv_mb).mean()
            loss_vf  = nn.functional.mse_loss(values, ret_b[mb])
            # Entropy bonus with floor: scale coefficient based on how far below
            ent_coeff = entropy_coeff
            if entropy_floor > 0 and entropy.item() < entropy_floor:
                # Scale from 1x (at floor) to 10x (at zero), smooth ramp
                ratio_below = 1.0 - (entropy.item() / max(entropy_floor, 1e-6))
                ent_coeff = entropy_coeff * (1.0 + 9.0 * ratio_below)
            loss     = loss_pg + VF_COEFF * loss_vf - ent_coeff * entropy
            optimizer.zero_grad()
            loss.backward()
            nn.utils.clip_grad_norm_(policy.parameters(), GRAD_CLIP)
            optimizer.step()
            total_loss += loss.item()
            pg_loss    += loss_pg.item()
            vf_loss    += loss_vf.item()
            ent_loss   += entropy.item()
            n_batches  += 1

    n = max(n_batches, 1)
    return total_loss/n, pg_loss/n, vf_loss/n, ent_loss/n


# ════════════════════════════════════════════════════════════════════════════
# Main training loop
# ════════════════════════════════════════════════════════════════════════════

def train(num_workers: int, steps_total: int, num_iterations: int,
          training_phase: str, resume_play: str | None, resume_shop: str | None,
          minibatch_size: int = MINIBATCH_SIZE,
          min_shop_steps: int = 0,
          early_stop_patience: int = 0):

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    steps_per_worker = max(1, steps_total // num_workers)

    play_net = PlayActorCritic().to(device)
    shop_net = ShopActorCritic().to(device)

    start_iter  = 0
    total_steps = 0
    best_ante   = 1
    best_reward = -float("inf")
    iters_without_improvement = 0

    # ── Load / init weights ───────────────────────────────────────────────
    if training_phase == "A":
        # Load play weights from v4 run 6
        v4_path = Path("checkpoints_sim/iter_1000.pt")
        if resume_play:
            v4_path = Path(resume_play)
        if v4_path.exists():
            ckpt = torch.load(v4_path, map_location=device)
            # v4 checkpoint has "policy" key with OBS_DIM=342, N_ACTIONS=46
            # We need to adapt embed layer (342->512 vs 374->512) and keep the rest
            v4_sd = ckpt["policy"] if "policy" in ckpt else ckpt
            play_sd = play_net.state_dict()
            loaded = 0
            for k, v in v4_sd.items():
                if k in play_sd and play_sd[k].shape == v.shape:
                    play_sd[k] = v
                    loaded += 1
            # embed.0.weight: v4 is (512, 342), v5 is (512, 374)
            # Copy first 342 cols from v4, leave last 32 cols as initialized
            embed_key = "embed.0.weight"
            if embed_key in v4_sd and embed_key in play_sd:
                v4_w = v4_sd[embed_key]  # (512, 342)
                play_sd[embed_key][:, :v4_w.shape[1]] = v4_w
                loaded += 1
            play_net.load_state_dict(play_sd)
            print(f"Phase A: loaded play weights from {v4_path} ({loaded} tensors matched)")
        else:
            print(f"WARNING: Phase A play checkpoint not found at {v4_path}, init from scratch")

        # Freeze play network
        for p in play_net.parameters():
            p.requires_grad = False
        print("Phase A: play network frozen")

        # Load shop weights if resuming
        if resume_shop and Path(resume_shop).exists():
            ckpt = torch.load(resume_shop, map_location=device)
            shop_sd = ckpt["shop_policy"] if "shop_policy" in ckpt else ckpt.get("policy", ckpt)
            shop_net.load_state_dict(shop_sd)
            start_iter  = ckpt.get("iteration", 0)
            total_steps = ckpt.get("total_steps", 0)
            best_ante   = ckpt.get("best_ante", 1)
            print(f"Phase A: resumed shop from {resume_shop} (iter {start_iter})")

    elif training_phase == "B":
        if resume_play and Path(resume_play).exists():
            ckpt = torch.load(resume_play, map_location=device)
            sd = ckpt["play_policy"] if "play_policy" in ckpt else ckpt.get("policy", ckpt)
            # Handle v4->v5 weight migration:
            # 1. embed.0.weight: v4=512x342, v5=512x374 (extra 32 comm dims)
            # 2. comm_head: new in v5, skip if missing
            if "embed.0.weight" in sd and sd["embed.0.weight"].shape[1] == 342:
                old_embed = sd["embed.0.weight"]           # (512, 342)
                new_embed = play_net.embed[0].weight.data.clone()  # (512, 374) random init
                new_embed[:, :342] = old_embed             # copy v4 weights, zeros for comm dims
                sd["embed.0.weight"] = new_embed
                print("Phase B: resized embed 342->374 (comm dims init to 0)")
            play_net.load_state_dict(sd, strict=False)     # strict=False skips missing comm_head
            print(f"Phase B: loaded play from {resume_play}")
        if resume_shop and Path(resume_shop).exists():
            ckpt = torch.load(resume_shop, map_location=device)
            sd = ckpt["shop_policy"] if "shop_policy" in ckpt else ckpt.get("policy", ckpt)
            shop_net.load_state_dict(sd)
            print(f"Phase B: loaded shop from {resume_shop}")
        if resume_play and Path(resume_play).exists():
            ckpt = torch.load(resume_play, map_location=device)
            start_iter  = ckpt.get("iteration", 0)
            total_steps = ckpt.get("total_steps", 0)
            best_ante   = ckpt.get("best_ante", 1)

    # Optimizers
    shop_optimizer = optim.Adam(shop_net.parameters(), lr=LR, eps=1e-5)
    play_optimizer = None
    if training_phase == "B":
        play_optimizer = optim.Adam(play_net.parameters(), lr=LR, eps=1e-5)

    episode_log: list[dict] = []

    # ── Spawn workers ─────────────────────────────────────────────────────
    # Split workers: half normal (play+shop), half shop-focused (heuristic play)
    seed_base = int(time.time()) % 100000
    workers: list[mp.Process] = []
    conns_main: list[mp.connection.Connection] = []

    n_shop_workers = num_workers // 2  # half dedicated to shop data
    n_play_workers = num_workers - n_shop_workers
    min_shop_per_worker = max(1, min_shop_steps // num_workers)

    for wid in range(num_workers):
        conn_main, conn_worker = mp.Pipe()
        is_shop_focused = (wid >= n_play_workers)
        p = mp.Process(
            target=_worker_fn,
            args=(wid, steps_per_worker, conn_worker, seed_base,
                  min_shop_per_worker, is_shop_focused),
            daemon=True,
        )
        p.start()
        workers.append(p)
        conns_main.append(conn_main)

    play_params = sum(p.numel() for p in play_net.parameters())
    shop_params = sum(p.numel() for p in shop_net.parameters())
    print(f"\n{'='*60}")
    print(f"train_v5.py — Dual-Agent PPO (Phase {training_phase})")
    print(f"  workers={num_workers} ({n_play_workers} play + {n_shop_workers} shop-focused)  "
          f"steps/iter={steps_total}  steps/worker={steps_per_worker}")
    print(f"  minibatch={minibatch_size}  epochs={N_EPOCHS}")
    print(f"  play: obs={PLAY_OBS_DIM} act={PLAY_N_ACTIONS} params={play_params:,}"
          f"  {'(frozen)' if training_phase == 'A' else '(training)'}")
    print(f"  shop: obs={SHOP_OBS_DIM} act={SHOP_N_ACTIONS} params={shop_params:,}"
          f"  comm={COMM_DIM}")
    print(f"  device={device}")
    print(f"{'='*60}\n")

    log_path = LOG_DIR / "training_v5.log"
    t_start  = time.time()
    t_iter   = t_start

    play_weights = {k: v.cpu() for k, v in play_net.state_dict().items()}
    shop_weights = {k: v.cpu() for k, v in shop_net.state_dict().items()}

    for iteration in range(start_iter, start_iter + num_iterations):

        # ── Send weights to workers ───────────────────────────────────────
        for conn in conns_main:
            conn.send({"play": play_weights, "shop": shop_weights})

        # ── Collect rollouts ──────────────────────────────────────────────
        all_play = {"obs": [], "act": [], "ret": [], "adv": [], "logp": [], "mask": []}
        all_shop = {"obs": [], "act": [], "ret": [], "adv": [], "logp": [], "mask": []}
        iter_episodes: list[dict] = []

        for conn in conns_main:
            data = conn.recv()
            iter_episodes.extend(data["episodes"])

            # Process play rollout
            pr = data["play_rollout"]
            if pr:
                rewards = np.array([s["reward"]   for s in pr], dtype=np.float32)
                values  = np.array([s["value"]    for s in pr], dtype=np.float32)
                dones   = np.array([s["done"]     for s in pr], dtype=np.float32)
                adv, ret = compute_gae(rewards, values, dones, data["play_next_val"])
                all_play["obs"].append(np.stack([s["obs"]    for s in pr]))
                all_play["act"].append(np.array([s["action"] for s in pr], dtype=np.int64))
                all_play["ret"].append(ret)
                all_play["adv"].append(adv)
                all_play["logp"].append(np.array([s["log_prob"] for s in pr], dtype=np.float32))
                all_play["mask"].append(np.stack([s["mask"]  for s in pr]))

            # Process shop rollout
            sr = data["shop_rollout"]
            if sr:
                rewards = np.array([s["reward"]   for s in sr], dtype=np.float32)
                values  = np.array([s["value"]    for s in sr], dtype=np.float32)
                dones   = np.array([s["done"]     for s in sr], dtype=np.float32)
                adv, ret = compute_gae(rewards, values, dones, data["shop_next_val"])
                all_shop["obs"].append(np.stack([s["obs"]    for s in sr]))
                all_shop["act"].append(np.array([s["action"] for s in sr], dtype=np.int64))
                all_shop["ret"].append(ret)
                all_shop["adv"].append(adv)
                all_shop["logp"].append(np.array([s["log_prob"] for s in sr], dtype=np.float32))
                all_shop["mask"].append(np.stack([s["mask"]  for s in sr]))

        play_steps = sum(len(a) for a in all_play["obs"])
        shop_steps = sum(len(a) for a in all_shop["obs"])
        total_steps += play_steps + shop_steps

        # ── PPO updates ───────────────────────────────────────────────────
        play_loss = play_ent = 0.0
        shop_loss = shop_ent = 0.0

        # Play agent update (Phase B only)
        if training_phase == "B" and play_steps > 0 and play_optimizer is not None:
            obs_b  = np.concatenate(all_play["obs"])
            act_b  = np.concatenate(all_play["act"])
            ret_b  = np.concatenate(all_play["ret"])
            adv_b  = np.concatenate(all_play["adv"])
            logp_b = np.concatenate(all_play["logp"])
            mask_b = np.concatenate(all_play["mask"])
            play_loss, _, _, play_ent = ppo_update(
                play_net, play_optimizer, obs_b, act_b, ret_b, adv_b, logp_b, mask_b,
                device, minibatch_size=minibatch_size, is_shop=False,
                entropy_coeff=ENTROPY_COEFF_PLAY,
                entropy_floor=ENTROPY_FLOOR_PLAY,
            )
            play_weights = {k: v.cpu() for k, v in play_net.state_dict().items()}

        # Shop agent update (always)
        if shop_steps > 0:
            obs_b  = np.concatenate(all_shop["obs"])
            act_b  = np.concatenate(all_shop["act"])
            ret_b  = np.concatenate(all_shop["ret"])
            adv_b  = np.concatenate(all_shop["adv"])
            logp_b = np.concatenate(all_shop["logp"])
            mask_b = np.concatenate(all_shop["mask"])
            shop_loss, _, _, shop_ent = ppo_update(
                shop_net, shop_optimizer, obs_b, act_b, ret_b, adv_b, logp_b, mask_b,
                device, minibatch_size=minibatch_size, is_shop=True,
                entropy_floor=ENTROPY_FLOOR_SHOP,
            )
            shop_weights = {k: v.cpu() for k, v in shop_net.state_dict().items()}

        # ── Logging ───────────────────────────────────────────────────────
        t_now    = time.time()
        iter_sec = max(t_now - t_iter, 1e-6)
        t_iter   = t_now
        sps      = (play_steps + shop_steps) / iter_sec
        eps      = len(iter_episodes)

        ante_dist = {}
        win_rate  = 0.0
        mean_reward = 0.0
        iter_best = 1
        if iter_episodes:
            mean_reward = np.mean([e["reward"] for e in iter_episodes])
            wins = sum(1 for e in iter_episodes if e.get("won", False))
            win_rate = wins / len(iter_episodes)
            for e in iter_episodes:
                a = e["ante"]
                ante_dist[a] = ante_dist.get(a, 0) + 1
            iter_best = max(e["ante"] for e in iter_episodes)
            if iter_best > best_ante:
                best_ante = iter_best
                tag = f"  *** NEW BEST ante={best_ante} ***"
            else:
                tag = ""
        else:
            tag = ""

        ante_str = " ".join(f"a{k}:{v}" for k, v in sorted(ante_dist.items()))

        # ── Action distribution logging every 10 iters ────────────────────
        action_log_str = ""
        if (iteration + 1) % 10 == 0:
            play_net.eval()
            shop_net.eval()
            with torch.no_grad():
                # Sample 256 obs from current rollout to get action probs
                if all_play["obs"]:
                    sample_obs = torch.FloatTensor(
                        np.concatenate(all_play["obs"])[:256]
                    ).to(device)
                    sample_mask = torch.BoolTensor(
                        np.concatenate(all_play["mask"])[:256]
                    ).to(device)
                    dist_p, _ = play_net.forward(sample_obs, sample_mask)
                    play_probs = dist_p.probs.mean(0).cpu().numpy()
                    top5_play = sorted(enumerate(play_probs), key=lambda x: -x[1])[:5]
                    play_dist_str = " ".join(f"a{i}:{p:.2f}" for i,p in top5_play)
                    action_log_str += f"\n  PLAY top5:  {play_dist_str}"

                if all_shop["obs"]:
                    sample_obs = torch.FloatTensor(
                        np.concatenate(all_shop["obs"])[:256]
                    ).to(device)
                    sample_mask = torch.BoolTensor(
                        np.concatenate(all_shop["mask"])[:256]
                    ).to(device)
                    dist_s, _, _ = shop_net.forward(sample_obs, sample_mask)
                    shop_probs = dist_s.probs.mean(0).cpu().numpy()
                    shop_action_names = {
                        0:"reroll", 1:"leave", 2:"buy0", 3:"buy1", 4:"buy2",
                        5:"buy3", 6:"buy4", 7:"buy5", 8:"pack0", 9:"pack1",
                        10:"sell0",11:"sell1",12:"sell2",13:"sell3",14:"sell4",
                        15:"use0", 16:"use1"
                    }
                    top5_shop = sorted(enumerate(shop_probs), key=lambda x: -x[1])[:5]
                    shop_dist_str = " ".join(f"{shop_action_names.get(i,i)}:{p:.2f}" for i,p in top5_shop)
                    action_log_str += f"\n  SHOP top5:  {shop_dist_str}"

        shop_pct = shop_steps / max(play_steps + shop_steps, 1) * 100
        status = (
            f"[{total_steps/1e6:.3f}M] iter={iteration+1:<5d} "
            f"sps={sps:<8.0f} steps=({play_steps}p+{shop_steps}s={shop_pct:.0f}%s) eps={eps:<4d} "
            f"rew={mean_reward:<6.2f} wr={win_rate:.2f} "
            f"p_loss={play_loss:.4f} s_loss={shop_loss:.4f} "
            f"p_ent={play_ent:.4f} s_ent={shop_ent:.4f} "
            f"best={best_ante} ({iter_sec:.1f}s) [{ante_str}]{tag}"
        )
        print(status + action_log_str)
        with open(log_path, "a") as f:
            f.write(status + action_log_str + "\n")

        for ep in iter_episodes:
            ep["iteration"] = iteration + 1
        episode_log.extend(iter_episodes)

        # ── Early stopping ────────────────────────────────────────────────
        if early_stop_patience > 0:
            improved = False
            if iter_best > best_ante:
                improved = True
            elif mean_reward > best_reward + 0.1:  # meaningful reward improvement
                improved = True
            if mean_reward > best_reward:
                best_reward = mean_reward
            if improved:
                iters_without_improvement = 0
            else:
                iters_without_improvement += 1
            if iters_without_improvement >= early_stop_patience:
                print(f"\n*** EARLY STOP: no improvement for {early_stop_patience} iters "
                      f"(best_ante={best_ante}, best_reward={best_reward:.2f}) ***")
                break

        # ── Checkpoint every 10 iters ─────────────────────────────────────
        if (iteration + 1) % 10 == 0:
            play_ckpt = CKPT_DIR / f"iter_{iteration+1:04d}_play.pt"
            shop_ckpt = CKPT_DIR / f"iter_{iteration+1:04d}_shop.pt"
            torch.save({
                "play_policy":  play_net.state_dict(),
                "iteration":    iteration + 1,
                "total_steps":  total_steps,
                "best_ante":    best_ante,
            }, play_ckpt)
            torch.save({
                "shop_policy":  shop_net.state_dict(),
                "optimizer":    shop_optimizer.state_dict(),
                "iteration":    iteration + 1,
                "total_steps":  total_steps,
                "best_ante":    best_ante,
            }, shop_ckpt)
            with open(CKPT_DIR / "episode_log.jsonl", "a") as f:
                for ep in episode_log:
                    f.write(json.dumps(ep) + "\n")
            episode_log.clear()
            print(f"  -> checkpoints saved: {play_ckpt}, {shop_ckpt}")

    # ── Shutdown ──────────────────────────────────────────────────────────
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

    parser = argparse.ArgumentParser(description="V5 dual-agent PPO training")
    parser.add_argument("--workers",         type=int, default=16,
                        help="Number of worker processes (default: 16)")
    parser.add_argument("--steps",           type=int, default=4096,
                        help="Total rollout steps per iteration (default: 4096)")
    parser.add_argument("--iterations",      type=int, default=500)
    parser.add_argument("--training-phase",  type=str, default="A", choices=["A", "B"],
                        help="Training phase: A=frozen play, B=joint (default: A)")
    parser.add_argument("--resume-play",     type=str, default=None,
                        help="Path to play agent checkpoint")
    parser.add_argument("--resume-shop",     type=str, default=None,
                        help="Path to shop agent checkpoint")
    parser.add_argument("--minibatch",       type=int, default=MINIBATCH_SIZE,
                        help="Minibatch size for PPO update (default: 128)")
    parser.add_argument("--min-shop-steps", type=int, default=200,
                        help="Minimum shop steps to collect per iteration across all workers (default: 200)")
    parser.add_argument("--early-stop", type=int, default=0,
                        help="Stop if no improvement for N iters (0=disabled, default: 0)")
    args = parser.parse_args()

    train(
        num_workers     = args.workers,
        steps_total     = args.steps,
        num_iterations  = args.iterations,
        training_phase  = args.training_phase,
        resume_play     = args.resume_play,
        resume_shop     = args.resume_shop,
        minibatch_size  = args.minibatch,
        min_shop_steps  = args.min_shop_steps,
        early_stop_patience = args.early_stop,
    )
