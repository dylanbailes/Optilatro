"""
train_sim.py — PPO training on the Python Balatro simulation.

Architecture:
  - N worker processes, each running M envs sequentially (true parallelism via multiprocessing)
  - Main process handles GPU PPO updates and weight broadcasting
  - No Balatro instances, no socket IPC, no watchdogs

Default: 16 workers x 1 env x 256 steps = 4096 steps/batch
Expected throughput: 50,000-150,000 sps (vs ~100 sps ceiling in v3)

Usage:
    python train_sim.py
    python train_sim.py --workers 16 --envs-per-worker 2 --iterations 1000
    python train_sim.py --workers 8  --envs-per-worker 4 --resume checkpoints_sim/iter_0100.pt
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

from balatro_sim.env_sim import BalatroSimEnv, OBS_DIM, N_ACTIONS, HAND_TYPES

# ════════════════════════════════════════════════════════════════════════════
# Hyperparameters
# ════════════════════════════════════════════════════════════════════════════

LR             = 3e-4
GAMMA          = 0.99
LAMBDA         = 0.95
CLIP           = 0.2
ENTROPY_COEFF  = 0.01
VF_COEFF       = 0.5
GRAD_CLIP      = 0.5
N_EPOCHS       = 10
MINIBATCH_SIZE = 128  # overridden by --minibatch CLI arg

LOG_DIR  = Path("logs_sim")
CKPT_DIR = Path("checkpoints_sim")
LOG_DIR.mkdir(exist_ok=True)
CKPT_DIR.mkdir(exist_ok=True)


# ════════════════════════════════════════════════════════════════════════════
# Action masking
# ════════════════════════════════════════════════════════════════════════════

from balatro_sim.game import State

def get_action_mask(env: BalatroSimEnv) -> np.ndarray:
    """Return bool mask of shape (N_ACTIONS,) — True = action is valid."""
    mask = np.zeros(N_ACTIONS, dtype=bool)
    gs   = env.game

    if gs.state == State.BLIND_SELECT:
        mask[30] = True                             # play blind (always)
        mask[31] = (gs.current_blind.kind != "Boss")# skip (not for boss)

    elif gs.state == State.SELECTING_HAND:
        n_combos = len(env._play_combos)
        mask[0:min(n_combos, 20)] = True            # play combos
        if gs.discards_left > 0:
            for i in range(min(len(gs.hand), 8)):
                mask[20 + i] = True                 # discard card i
        for i, key in enumerate(gs.consumable_hand[:2]):
            mask[28 + i] = True                     # use consumable i

    elif gs.state == State.SHOP:
        shop = gs.current_shop
        for i, item in enumerate(shop[:7]):
            if not item.sold and gs.dollars >= item.discounted_price(gs.shop_discount):
                if item.kind == "joker" and len(gs.jokers) >= gs.joker_slots:
                    pass  # no slot
                elif item.kind in ("planet","tarot","spectral") and \
                     len(gs.consumable_hand) >= gs.consumable_slots:
                    pass  # no slot
                else:
                    mask[32 + i] = True             # buy item i
        for i in range(min(len(gs.jokers), 5)):
            mask[39 + i] = True                     # sell joker i
        reroll_cost = max(0, gs.reroll_cost - gs.reroll_discount)
        if gs.free_rerolls_remaining > 0 or gs.dollars >= reroll_cost:
            mask[44] = True                         # reroll
        mask[45] = True                             # leave shop (always valid)
        # Consumable usage in shop (planets only — safe to use without targets)
        from balatro_sim.consumables import ALL_PLANETS as _AP
        for i, key in enumerate(gs.consumable_hand[:2]):
            if key in _AP:
                mask[28 + i] = True                 # use planet in shop

    elif gs.state == State.GAME_OVER:
        mask[45] = True  # dummy action to unstick terminal state

    # Safety: ensure at least one action is valid
    if not mask.any():
        mask[45] = True

    return mask


# ════════════════════════════════════════════════════════════════════════════
# Actor-Critic network
# ════════════════════════════════════════════════════════════════════════════

class ResidualBlock(nn.Module):
    """Two-layer residual block with LayerNorm. Input and output are both `width` units."""
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


class ActorCritic(nn.Module):
    """
    6-layer network with residual connections.
    Architecture:
      input (342) -> embed (512) -> 4 residual blocks (512) -> actor/critic heads
    Total depth: 1 embed + 4 res blocks x 2 layers each = 9 linear layers.
    """
    HIDDEN = 512

    def __init__(self):
        super().__init__()
        H = self.HIDDEN
        # Input embedding
        self.embed = nn.Sequential(nn.Linear(OBS_DIM, H), nn.ReLU())
        # 4 residual blocks = 8 linear layers (+ embed = 9 total, ~6 "effective" depth)
        self.res_blocks = nn.Sequential(
            ResidualBlock(H),
            ResidualBlock(H),
            ResidualBlock(H),
            ResidualBlock(H),
        )
        self.actor  = nn.Linear(H, N_ACTIONS)
        self.critic = nn.Linear(H, 1)

        # Init heads
        nn.init.orthogonal_(self.embed[0].weight, gain=np.sqrt(2))
        nn.init.constant_(self.embed[0].bias, 0)
        nn.init.orthogonal_(self.actor.weight,  gain=0.01)
        nn.init.constant_(self.actor.bias,  0)
        nn.init.orthogonal_(self.critic.weight, gain=1.0)
        nn.init.constant_(self.critic.bias, 0)

    def forward(self, obs: torch.Tensor, mask: torch.Tensor | None = None):
        x      = self.res_blocks(self.embed(obs))
        logits = self.actor(x)
        if mask is not None:
            logits = logits.masked_fill(~mask, float("-inf"))
        dist  = torch.distributions.Categorical(logits=logits)
        value = self.critic(x).squeeze(-1)
        return dist, value

    @torch.no_grad()
    def get_action(self, obs: torch.Tensor, mask: torch.Tensor | None = None):
        dist, value = self.forward(obs, mask)
        action = dist.sample()
        return action.item(), dist.log_prob(action).item(), value.item()

    @torch.no_grad()
    def get_value(self, obs: torch.Tensor, mask: torch.Tensor | None = None) -> float:
        _, value = self.forward(obs, mask)
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

def _worker_fn(worker_id: int, n_envs: int, steps_target: int,
               conn: mp.connection.Connection, seed_base: int):
    """
    Runs in a separate process. Collects rollouts and sends them to main.
    Receives updated weights before each rollout cycle.
    """
    import os, random as _random_mod
    # Prevent worker from using CUDA
    os.environ["CUDA_VISIBLE_DEVICES"] = ""
    _rng = _random_mod.Random(seed_base + worker_id * 1000)

    envs    = [BalatroSimEnv(seed=_rng.randint(0, 2**31 - 1)) for i in range(n_envs)]
    policy  = ActorCritic().cpu().eval()

    obs_list   = [e.reset()[0] for e in envs]
    ep_steps   = [0] * n_envs
    ep_reward  = [0.0] * n_envs

    while True:
        # Receive weights or stop signal
        msg = conn.recv()
        if msg is None:
            break
        policy.load_state_dict({k: v.cpu() for k, v in msg.items()})
        policy.eval()

        rollout: list[dict] = []
        episodes: list[dict] = []
        deadline = time.time() + 60   # 60-second hard cap

        steps_per_env = max(1, steps_target // n_envs)

        for _ in range(steps_per_env):
            if time.time() > deadline:
                break
            for i, env in enumerate(envs):
                mask   = get_action_mask(env)
                obs_t  = torch.FloatTensor(obs_list[i]).unsqueeze(0)
                mask_t = torch.BoolTensor(mask).unsqueeze(0)
                action, log_prob, value = policy.get_action(obs_t, mask_t)

                next_obs, reward, terminated, truncated, info = env.step(action)
                done = terminated or truncated

                rollout.append({
                    "obs":      obs_list[i].copy(),
                    "action":   action,
                    "reward":   float(reward),
                    "done":     float(done),
                    "log_prob": log_prob,
                    "value":    value,
                    "mask":     mask.copy(),
                })

                ep_steps[i]  += 1
                ep_reward[i] += reward

                # Truncate very long episodes to ensure turnover
                if not done and ep_steps[i] >= 2000:
                    done = True

                if done:
                    episodes.append({
                        "steps":   ep_steps[i],
                        "ante":    info.get("ante", 1),
                        "reward":  ep_reward[i],
                        "dollars": info.get("dollars", 0),
                        "won":     info.get("ante", 1) > 8,
                    })
                    # Randomize seed each episode for generalization
                    env._seed = _rng.randint(0, 2**31 - 1)
                    next_obs, _ = env.reset()
                    ep_steps[i]  = 0
                    ep_reward[i] = 0.0

                obs_list[i] = next_obs

        # Bootstrap values for GAE
        next_values = []
        for i, env in enumerate(envs):
            mask_t = torch.BoolTensor(get_action_mask(env)).unsqueeze(0)
            obs_t  = torch.FloatTensor(obs_list[i]).unsqueeze(0)
            next_values.append(policy.get_value(obs_t, mask_t))

        conn.send({
            "rollout":      rollout,
            "next_values":  next_values,
            "episodes":     episodes,
        })


# ════════════════════════════════════════════════════════════════════════════
# PPO update
# ════════════════════════════════════════════════════════════════════════════

def ppo_update(policy, optimizer, obs_b, act_b, ret_b, adv_b, logp_b, mask_b, device,
               minibatch_size: int = MINIBATCH_SIZE):
    obs_b  = torch.FloatTensor(obs_b).to(device)
    act_b  = torch.LongTensor(act_b).to(device)
    ret_b  = torch.FloatTensor(ret_b).to(device)
    adv_b  = torch.FloatTensor(adv_b).to(device)
    logp_b = torch.FloatTensor(logp_b).to(device)
    mask_b = torch.BoolTensor(mask_b).to(device)

    adv_b = (adv_b - adv_b.mean()) / (adv_b.std() + 1e-8)
    ret_b = (ret_b - ret_b.mean()) / (ret_b.std() + 1e-8)

    total_loss = pg_loss = vf_loss = ent_loss = 0.0
    n_batches  = 0
    idx        = np.arange(len(obs_b))

    for _ in range(N_EPOCHS):
        np.random.shuffle(idx)
        for start in range(0, len(idx), minibatch_size):
            mb = idx[start:start + minibatch_size]
            dist, values = policy.forward(obs_b[mb], mask_b[mb])
            new_logp = dist.log_prob(act_b[mb])
            entropy  = dist.entropy().mean()
            ratio    = torch.exp(new_logp - logp_b[mb])
            adv_mb   = adv_b[mb]
            loss_pg  = -torch.min(ratio * adv_mb,
                                  torch.clamp(ratio, 1-CLIP, 1+CLIP) * adv_mb).mean()
            loss_vf  = nn.functional.mse_loss(values, ret_b[mb])
            loss     = loss_pg + VF_COEFF * loss_vf - ENTROPY_COEFF * entropy
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

def train(num_workers: int, envs_per_worker: int, steps_per_worker: int,
          num_iterations: int, resume_path: str | None, minibatch_size: int = MINIBATCH_SIZE):

    device      = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    batch_size  = num_workers * envs_per_worker * steps_per_worker

    policy    = ActorCritic().to(device)
    optimizer = optim.Adam(policy.parameters(), lr=LR, eps=1e-5)

    start_iter  = 0
    total_steps = 0
    best_ante   = 1
    episode_log: list[dict] = []

    if resume_path and Path(resume_path).exists():
        ckpt = torch.load(resume_path, map_location=device)
        policy.load_state_dict(ckpt["policy"])
        optimizer.load_state_dict(ckpt["optimizer"])
        start_iter  = ckpt.get("iteration", 0)
        total_steps = ckpt.get("total_steps", 0)
        best_ante   = ckpt.get("best_ante", 1)
        print(f"Resumed from {resume_path}  (iter {start_iter}, {total_steps:,} steps)")

    # Spawn worker processes
    seed_base = int(time.time()) % 100000
    workers: list[mp.Process] = []
    conns_main: list[mp.connection.Connection] = []

    for wid in range(num_workers):
        conn_main, conn_worker = mp.Pipe()
        p = mp.Process(
            target=_worker_fn,
            args=(wid, envs_per_worker, steps_per_worker, conn_worker, seed_base),
            daemon=True,
        )
        p.start()
        workers.append(p)
        conns_main.append(conn_main)

    n_params = sum(p.numel() for p in policy.parameters())
    print(f"\n{'='*60}")
    print(f"train_sim.py — Python Balatro Sim PPO")
    print(f"  workers={num_workers}  envs/worker={envs_per_worker}  "
          f"steps/worker={steps_per_worker}")
    print(f"  batch_size={batch_size:,}  minibatch={minibatch_size}  "
          f"epochs={N_EPOCHS}")
    print(f"  obs={OBS_DIM}  actions={N_ACTIONS}  params={n_params:,}")
    print(f"  device={device}")
    print(f"{'='*60}\n")

    log_path = LOG_DIR / "training_sim.log"
    t_start  = time.time()
    t_iter   = t_start

    weights = {k: v.cpu() for k, v in policy.state_dict().items()}

    for iteration in range(start_iter, start_iter + num_iterations):

        # ── send weights to workers ───────────────────────────────────────
        for conn in conns_main:
            conn.send(weights)

        # ── wait for rollouts ─────────────────────────────────────────────
        all_obs, all_act, all_ret, all_adv, all_logp, all_mask = [], [], [], [], [], []
        iter_episodes: list[dict] = []

        for conn in conns_main:
            data = conn.recv()
            r    = data["rollout"]
            nvs  = data["next_values"]
            eps  = data["episodes"]
            iter_episodes.extend(eps)

            if not r:
                continue

            rewards  = np.array([s["reward"]   for s in r], dtype=np.float32)
            values   = np.array([s["value"]     for s in r], dtype=np.float32)
            dones    = np.array([s["done"]      for s in r], dtype=np.float32)
            logps    = np.array([s["log_prob"]  for s in r], dtype=np.float32)
            obs_arr  = np.stack([s["obs"]       for s in r])
            act_arr  = np.array([s["action"]    for s in r], dtype=np.int64)
            mask_arr = np.stack([s["mask"]      for s in r])

            # Split by env if multiple envs per worker
            n_per_env = len(r) // envs_per_worker
            for ei in range(envs_per_worker):
                sl   = slice(ei * n_per_env, (ei+1) * n_per_env)
                nv   = nvs[ei] if ei < len(nvs) else 0.0
                adv, ret = compute_gae(rewards[sl], values[sl], dones[sl], nv)
                all_obs.append(obs_arr[sl])
                all_act.append(act_arr[sl])
                all_ret.append(ret)
                all_adv.append(adv)
                all_logp.append(logps[sl])
                all_mask.append(mask_arr[sl])

        if not all_obs:
            continue

        obs_b  = np.concatenate(all_obs)
        act_b  = np.concatenate(all_act)
        ret_b  = np.concatenate(all_ret)
        adv_b  = np.concatenate(all_adv)
        logp_b = np.concatenate(all_logp)
        mask_b = np.concatenate(all_mask)

        total_steps += len(obs_b)

        # ── PPO update ────────────────────────────────────────────────────
        loss, pg_loss, vf_loss, ent = ppo_update(
            policy, optimizer, obs_b, act_b, ret_b, adv_b, logp_b, mask_b, device,
            minibatch_size=minibatch_size,
        )
        weights = {k: v.cpu() for k, v in policy.state_dict().items()}

        # ── Logging ───────────────────────────────────────────────────────
        t_now    = time.time()
        iter_sec = max(t_now - t_iter, 1e-6)
        t_iter   = t_now
        sps      = len(obs_b) / iter_sec
        eps      = len(iter_episodes)
        eps_hr   = eps / max(iter_sec / 3600.0, 1e-9)

        if iter_episodes:
            iter_best = max(e["ante"] for e in iter_episodes)
            if iter_best > best_ante:
                best_ante = iter_best
                tag = f"  *** NEW BEST ante={best_ante} ***"
            else:
                tag = ""
            mean_reward = np.mean([e["reward"] for e in iter_episodes])
        else:
            iter_best = best_ante
            tag = ""
            mean_reward = 0.0

        status = (
            f"[{total_steps/1e6:.3f}M] iter={iteration+1:<5d} "
            f"sps={sps:<8.0f} eps={eps:<5d} eps/hr={eps_hr:<7.0f} "
            f"rew={mean_reward:<6.2f} "
            f"loss={loss:.4f} pg={pg_loss:.4f} vf={vf_loss:.4f} ent={ent:.4f} "
            f"best={best_ante} ({iter_sec:.1f}s){tag}"
        )
        print(status)
        with open(log_path, "a") as f:
            f.write(status + "\n")

        for ep in iter_episodes:
            ep["iteration"] = iteration + 1
        episode_log.extend(iter_episodes)

        # ── Checkpoint every 10 iters ─────────────────────────────────────
        if (iteration + 1) % 10 == 0:
            ckpt_path = CKPT_DIR / f"iter_{iteration+1:04d}.pt"
            torch.save({
                "policy":      policy.state_dict(),
                "optimizer":   optimizer.state_dict(),
                "iteration":   iteration + 1,
                "total_steps": total_steps,
                "best_ante":   best_ante,
            }, ckpt_path)
            with open(CKPT_DIR / "episode_log.jsonl", "a") as f:
                for ep in episode_log:
                    f.write(json.dumps(ep) + "\n")
            episode_log.clear()
            print(f"  -> checkpoint saved: {ckpt_path}")

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

    parser = argparse.ArgumentParser()
    parser.add_argument("--workers",          type=int, default=16,
                        help="Number of worker processes (default: 16)")
    parser.add_argument("--envs-per-worker",  type=int, default=1,
                        help="Envs per worker process (default: 1)")
    parser.add_argument("--steps-per-worker", type=int, default=256,
                        help="Rollout steps per worker per iteration (default: 256)")
    parser.add_argument("--iterations",       type=int, default=1000)
    parser.add_argument("--resume",           type=str, default=None)
    parser.add_argument("--minibatch",        type=int, default=MINIBATCH_SIZE,
                        help="Minibatch size for PPO update (default: 128)")
    args = parser.parse_args()

    train(
        num_workers      = args.workers,
        envs_per_worker  = args.envs_per_worker,
        steps_per_worker = args.steps_per_worker,
        num_iterations   = args.iterations,
        resume_path      = args.resume,
        minibatch_size   = args.minibatch,
    )
