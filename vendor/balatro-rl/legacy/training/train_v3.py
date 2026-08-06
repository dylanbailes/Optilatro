"""
train_v3.py — Custom Threaded PPO Training Loop

8 env threads collect rollouts concurrently (GIL releases on socket recv).
Main thread runs PPO update after all threads finish each cycle.
No Ray, no VectorEnv overhead.

Expected throughput: ~90 steps/sec (8 envs × 11.7 steps/sec @ 128x game speed)

Usage:
    python train_v3.py --envs 8 --iterations 500
    python train_v3.py --envs 8 --iterations 500 --resume checkpoints_v3/iter_050.pt
"""

import argparse
import json
import threading
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim

from balatro_rl.env_socket import BalatroSocketEnv
from balatro_rl.state_v2 import OBS_SIZE
from balatro_rl.env_socket import ACTION_SIZE

# ── Hyperparameters ────────────────────────────────────────────────────────────
LR             = 3e-4
GAMMA          = 0.99
LAMBDA         = 0.95    # GAE lambda
CLIP           = 0.2     # PPO clip epsilon
ENTROPY_COEFF  = 0.01
VF_COEFF       = 0.5
GRAD_CLIP      = 0.5
N_EPOCHS       = 10
BATCH_SIZE     = 2048    # total steps per PPO update (across all envs)
MINIBATCH_SIZE = 64

LOG_DIR   = Path("logs_ray_socket")
CKPT_DIR  = Path("checkpoints_v3")
LOG_DIR.mkdir(exist_ok=True)
CKPT_DIR.mkdir(exist_ok=True)


# ── Actor-Critic Network ───────────────────────────────────────────────────────
class ActorCritic(nn.Module):
    def __init__(self):
        super().__init__()
        self.shared = nn.Sequential(
            nn.Linear(OBS_SIZE, 256), nn.ReLU(),
            nn.Linear(256, 256),      nn.ReLU(),
            nn.Linear(256, 128),      nn.ReLU(),
        )
        self.actor  = nn.Linear(128, ACTION_SIZE)
        self.critic = nn.Linear(128, 1)

    def forward(self, obs: torch.Tensor, mask: torch.Tensor | None = None):
        x      = self.shared(obs)
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


# ── GAE Advantage Estimation ───────────────────────────────────────────────────
def compute_gae(rewards, values, dones, next_value):
    T = len(rewards)
    advantages = np.zeros(T, dtype=np.float32)
    last_adv   = 0.0
    for t in reversed(range(T)):
        next_v    = next_value if t == T - 1 else values[t + 1]
        not_done  = 1.0 - dones[t]
        delta     = rewards[t] + GAMMA * next_v * not_done - values[t]
        advantages[t] = last_adv = delta + GAMMA * LAMBDA * not_done * last_adv
    returns = advantages + values
    return advantages, returns


# ── Rollout Collector Thread ───────────────────────────────────────────────────
class RolloutCollector(threading.Thread):
    """
    One thread per Balatro instance. Collects steps_per_env steps, then
    signals the main thread and waits for the PPO update to complete.
    """

    def __init__(self, env_id: int, policy: ActorCritic, policy_lock: threading.Lock,
                 steps_per_env: int, stop_event: threading.Event, device: torch.device):
        super().__init__(daemon=True, name=f"env-{env_id}")
        self.env_id        = env_id
        self.policy        = policy       # GPU policy (for weight sync)
        self.policy_lock   = policy_lock
        self.steps_per_env = steps_per_env
        self.stop_event    = stop_event
        self.device        = device
        # Each thread has its own CPU copy for inference — avoids CUDA thread-safety issues
        self.cpu_policy    = ActorCritic().cpu()
        self.cpu_policy.eval()

        # Synchronization: thread sets ready when rollout done; main sets go to resume
        self.ready_event  = threading.Event()
        self.go_event     = threading.Event()
        self.go_event.set()   # initially allowed to run

        self.rollout      = []   # populated each cycle
        self.next_value   = 0.0  # bootstrap value for GAE
        self.episode_info = []   # (steps, ante, reward, blind_name, blind_boss) per completed episode

    def sync_weights(self):
        """Copy current GPU policy weights to this thread's CPU inference policy."""
        with self.policy_lock:
            cpu_state = {k: v.cpu() for k, v in self.policy.state_dict().items()}
        self.cpu_policy.load_state_dict(cpu_state)

    def _get_action(self, obs: np.ndarray, mask: np.ndarray):
        obs_t  = torch.FloatTensor(obs).unsqueeze(0)   # CPU
        mask_t = torch.BoolTensor(mask).unsqueeze(0)    # CPU
        return self.cpu_policy.get_action(obs_t, mask_t)

    def _get_value(self, obs: np.ndarray, mask: np.ndarray) -> float:
        obs_t  = torch.FloatTensor(obs).unsqueeze(0)   # CPU
        mask_t = torch.BoolTensor(mask).unsqueeze(0)    # CPU
        with torch.no_grad():
            _, value = self.cpu_policy.forward(obs_t, mask_t)
        return value.item()

    def run(self):
        env = BalatroSocketEnv(self.env_id)
        obs, _ = env.reset()
        ep_steps = 0
        ep_reward = 0.0

        while not self.stop_event.is_set():
            self.go_event.wait()
            self.go_event.clear()
            if self.stop_event.is_set():
                break

            self.sync_weights()   # pull latest GPU weights to CPU inference copy
            rollout      = []
            ep_info_cycle = []
            iter_deadline = time.time() + 120   # 2-min hard cap per thread iteration

            for _ in range(self.steps_per_env):
                if time.time() > iter_deadline:
                    break  # bail early, use partial rollout
                mask = env.action_masks()
                action, log_prob, value = self._get_action(obs, mask)

                next_obs, reward, terminated, truncated, info = env.step(action)
                done = terminated or truncated
                ep_steps  += 1
                ep_reward += reward

                rollout.append({
                    "obs":      obs.copy(),
                    "action":   action,
                    "reward":   float(reward),
                    "done":     float(done),
                    "log_prob": log_prob,
                    "value":    value,
                    "mask":     mask.copy(),
                })

                if done:
                    ante       = info.get("ante", 1)
                    blind_name = info.get("blind_name", "unknown")
                    blind_boss = info.get("blind_boss", False)
                    ep_info_cycle.append((ep_steps, ante, ep_reward, blind_name, blind_boss))
                    obs, _ = env.reset()
                    ep_steps  = 0
                    ep_reward = 0.0
                else:
                    obs = next_obs

            # Bootstrap value for GAE
            mask         = env.action_masks()
            self.next_value   = self._get_value(obs, mask)
            self.rollout      = rollout
            self.episode_info = ep_info_cycle
            self.ready_event.set()


# ── PPO Update ────────────────────────────────────────────────────────────────
def ppo_update(policy: ActorCritic, optimizer: optim.Optimizer,
               obs_b, act_b, ret_b, adv_b, logp_b, mask_b, device):
    obs_b  = torch.FloatTensor(obs_b).to(device)
    act_b  = torch.LongTensor(act_b).to(device)
    ret_b  = torch.FloatTensor(ret_b).to(device)
    adv_b  = torch.FloatTensor(adv_b).to(device)
    logp_b = torch.FloatTensor(logp_b).to(device)
    mask_b = torch.BoolTensor(mask_b).to(device)

    adv_b = (adv_b - adv_b.mean()) / (adv_b.std() + 1e-8)
    ret_b = (ret_b - ret_b.mean()) / (ret_b.std() + 1e-8)  # normalize returns to stabilize VF loss

    total_loss = pg_loss = vf_loss = ent_loss = 0.0
    n_batches  = 0

    idx = np.arange(len(obs_b))
    for _ in range(N_EPOCHS):
        np.random.shuffle(idx)
        for start in range(0, len(idx), MINIBATCH_SIZE):
            mb = idx[start:start + MINIBATCH_SIZE]

            dist, values = policy.forward(obs_b[mb], mask_b[mb])
            new_logp = dist.log_prob(act_b[mb])
            entropy  = dist.entropy().mean()

            ratio    = torch.exp(new_logp - logp_b[mb])
            adv_mb   = adv_b[mb]
            pg1      = ratio * adv_mb
            pg2      = torch.clamp(ratio, 1 - CLIP, 1 + CLIP) * adv_mb
            loss_pg  = -torch.min(pg1, pg2).mean()
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
    return total_loss / n, pg_loss / n, vf_loss / n, ent_loss / n


# ── Training Loop ─────────────────────────────────────────────────────────────
def train(num_envs: int, num_iterations: int, resume_path: str | None):
    device        = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    steps_per_env = BATCH_SIZE // num_envs

    policy    = ActorCritic().to(device)
    optimizer = optim.Adam(policy.parameters(), lr=LR)

    start_iter   = 0
    total_steps  = 0
    best_ante    = 1
    episode_log  = []

    if resume_path and Path(resume_path).exists():
        ckpt = torch.load(resume_path, map_location=device)
        policy.load_state_dict(ckpt["policy"])
        optimizer.load_state_dict(ckpt["optimizer"])
        start_iter  = ckpt.get("iteration", 0)
        total_steps = ckpt.get("total_steps", 0)
        best_ante   = ckpt.get("best_ante", 1)
        print(f"Resumed from {resume_path} (iter {start_iter}, {total_steps} steps)")

    policy_lock  = threading.Lock()
    stop_event   = threading.Event()
    collectors   = [
        RolloutCollector(i + 1, policy, policy_lock, steps_per_env, stop_event, device)
        for i in range(num_envs)
    ]
    for c in collectors:
        c.start()

    log_path = LOG_DIR / "training_v3.log"
    run_name = datetime.now().strftime("%H%M")
    print(f"[train_v3] {num_envs} envs | {steps_per_env} steps/env | "
          f"batch={BATCH_SIZE} | device={device}")
    print(f"Log: {log_path}")

    t_start = time.time()
    t_iter  = t_start

    for iteration in range(start_iter, start_iter + num_iterations):
        # ── wait for all threads to finish their rollout ─────────────────────
        for c in collectors:
            c.ready_event.wait()
        for c in collectors:
            c.ready_event.clear()

        # ── assemble batch ───────────────────────────────────────────────────
        all_obs, all_act, all_ret, all_adv, all_logp, all_mask = [], [], [], [], [], []
        iter_episodes = []

        for c in collectors:
            r = c.rollout
            if len(r) == 0:
                continue  # skip empty rollouts from timed-out threads
            rewards   = np.array([s["reward"]   for s in r], dtype=np.float32)
            values    = np.array([s["value"]     for s in r], dtype=np.float32)
            dones     = np.array([s["done"]      for s in r], dtype=np.float32)
            log_probs = np.array([s["log_prob"]  for s in r], dtype=np.float32)
            obs_arr   = np.stack([s["obs"]       for s in r])
            act_arr   = np.array([s["action"]    for s in r], dtype=np.int64)
            mask_arr  = np.stack([s["mask"]      for s in r])

            adv, ret  = compute_gae(rewards, values, dones, c.next_value)

            all_obs.append(obs_arr)
            all_act.append(act_arr)
            all_ret.append(ret)
            all_adv.append(adv)
            all_logp.append(log_probs)
            all_mask.append(mask_arr)
            iter_episodes.extend(c.episode_info)

        obs_b  = np.concatenate(all_obs)
        act_b  = np.concatenate(all_act)
        ret_b  = np.concatenate(all_ret)
        adv_b  = np.concatenate(all_adv)
        logp_b = np.concatenate(all_logp)
        mask_b = np.concatenate(all_mask)

        total_steps += len(obs_b)

        # ── PPO update ───────────────────────────────────────────────────────
        with policy_lock:
            loss, pg_loss, vf_loss, ent = ppo_update(
                policy, optimizer, obs_b, act_b, ret_b, adv_b, logp_b, mask_b, device
            )

        # ── signal threads to resume ─────────────────────────────────────────
        for c in collectors:
            c.go_event.set()

        # ── logging ──────────────────────────────────────────────────────────
        t_now    = time.time()
        iter_sec = t_now - t_iter
        t_iter   = t_now
        sps      = len(obs_b) / max(iter_sec, 0.001)
        eps      = len(iter_episodes)
        eps_hr   = eps / max(iter_sec / 3600.0, 1e-9)

        iter_best = max((a for _, a, _, _b, _bb in iter_episodes), default=0)
        if iter_best > best_ante:
            best_ante = iter_best
            tag = f"[NEW BEST] Ante {best_ante}"
        else:
            tag = ""

        status = (
            f"[{total_steps/1e6:.2f}M] iter={iteration+1:<4d} "
            f"steps={len(obs_b):<5d} sps={sps:<6.1f} "
            f"eps={eps:<4d} eps/hr={eps_hr:<6.0f} "
            f"loss={loss:.4f} pg={pg_loss:.4f} vf={vf_loss:.4f} ent={ent:.4f} "
            f"best_ante={best_ante} ({iter_sec:.1f}s/iter) {tag}"
        )
        print(status)

        with open(log_path, "a") as f:
            f.write(status + "\n")

        episode_log.extend([
            {
                "iteration":  iteration + 1,
                "steps":      s,
                "ante":       a,
                "reward":     r,
                "died_at":    blind_name,
                "was_boss":   blind_boss,
            }
            for s, a, r, blind_name, blind_boss in iter_episodes
        ])

        # ── checkpoint every 10 iters ────────────────────────────────────────
        if (iteration + 1) % 10 == 0:
            ckpt_path = CKPT_DIR / f"iter_{iteration+1:04d}.pt"
            with policy_lock:
                torch.save({
                    "policy":     policy.state_dict(),
                    "optimizer":  optimizer.state_dict(),
                    "iteration":  iteration + 1,
                    "total_steps": total_steps,
                    "best_ante":  best_ante,
                }, ckpt_path)

            ep_log_path = CKPT_DIR / "episode_log.jsonl"
            with open(ep_log_path, "a") as f:
                for ep in episode_log:
                    f.write(json.dumps(ep) + "\n")
            episode_log.clear()
            print(f"  Saved checkpoint: {ckpt_path}")

    # ── done ─────────────────────────────────────────────────────────────────
    stop_event.set()
    for c in collectors:
        c.go_event.set()  # unblock any waiting thread

    total_time = time.time() - t_start
    print(f"\nDone. {num_iterations} iterations, {total_steps} steps, "
          f"{total_time/60:.1f} min. Best ante: {best_ante}")


# ── Entry Point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--envs",       type=int, default=8)
    parser.add_argument("--iterations", type=int, default=500)
    parser.add_argument("--resume",     type=str, default=None,
                        help="Path to checkpoint .pt file to resume from")
    args = parser.parse_args()

    train(args.envs, args.iterations, args.resume)
