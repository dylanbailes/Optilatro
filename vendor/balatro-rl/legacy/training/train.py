"""
train.py
PPO training on live Balatro via BalatroEnv.

Usage:
  python train.py               # train from scratch (auto-launches Balatro)
  python train.py --resume      # resume from latest checkpoint
  python train.py --no-launch   # skip auto-launch (Balatro already open)
"""

import argparse
import heapq
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
from stable_baselines3 import PPO
from stable_baselines3.common.callbacks import BaseCallback, CheckpointCallback
from stable_baselines3.common.monitor import Monitor

sys.path.insert(0, ".")
from balatro_rl.env import BalatroEnv

# ── Config ───────────────────────────────────────────────────────────────────

CHECKPOINT_DIR = Path("checkpoints")
LOG_DIR        = Path("logs")
CHECKPOINT_DIR.mkdir(exist_ok=True)
LOG_DIR.mkdir(exist_ok=True)

# Balatro auto-launch / restart config
BALATRO_EXE   = Path(os.environ.get(
    "BALATRO_EXE",
    r"C:\Program Files (x86)\Steam\steamapps\common\Balatro\Balatro.exe"
))
STATE_JSON    = Path(os.environ["APPDATA"]) / "Balatro" / "balatro_rl" / "state.json"
RESTART_EVERY = 6_000   # steps (~450 episodes); keeps Balatro memory usage in check

PPO_KWARGS = dict(
    policy          = "MlpPolicy",
    learning_rate   = 3e-4,
    n_steps         = 512,
    batch_size      = 64,
    n_epochs        = 10,
    gamma           = 0.99,
    gae_lambda      = 0.95,
    clip_range      = 0.2,
    ent_coef        = 0.01,
    vf_coef         = 0.5,
    max_grad_norm   = 0.5,
    verbose         = 1,
    tensorboard_log = None,
    policy_kwargs   = dict(net_arch=[256, 256, 128]),
)

TOTAL_TIMESTEPS = 100_000

# ── Balatro Process Management ───────────────────────────────────────────────

def _balatro_pid():
    """Return PID of running Balatro.exe, or None."""
    r = subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq Balatro.exe", "/FO", "CSV", "/NH"],
        capture_output=True, text=True
    )
    for line in r.stdout.splitlines():
        if "Balatro.exe" in line:
            try:
                return int(line.split(",")[1].strip('"'))
            except (IndexError, ValueError):
                pass
    return None


def kill_balatro():
    pid = _balatro_pid()
    if pid:
        print(f"[balatro] Killing PID {pid}...")
        subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True)
        time.sleep(2)


def launch_balatro(wait_timeout=40):
    """Launch Balatro and block until the mod writes a fresh state.json."""
    if not BALATRO_EXE.exists():
        print(f"[balatro] Exe not found: {BALATRO_EXE}")
        print("[balatro] Set BALATRO_EXE env var or use --no-launch")
        return False

    mtime_before = STATE_JSON.stat().st_mtime if STATE_JSON.exists() else 0
    print(f"[balatro] Launching {BALATRO_EXE.name}...")
    subprocess.Popen([str(BALATRO_EXE)])

    deadline = time.time() + wait_timeout
    while time.time() < deadline:
        time.sleep(2)
        if STATE_JSON.exists() and STATE_JSON.stat().st_mtime > mtime_before:
            print("[balatro] Mod active — starting training\n")
            return True
        remaining = int(deadline - time.time())
        print(f"[balatro] Waiting for mod... ({remaining}s)", end="\r")

    print("\n[balatro] Warning: timed out waiting for mod. Proceeding anyway.")
    return False


def restart_balatro():
    print("\n[balatro] Restarting to clear memory leak...")
    kill_balatro()
    time.sleep(2)
    launch_balatro()


# ── Best-Run Logger ───────────────────────────────────────────────────────────

class BestRunCallback(BaseCallback):
    """
    Tracks every episode. Logs:
    - episode_log.jsonl: summary of every episode
    - best_runs.jsonl: all-time best reward runs (full detail)
    - run_detail_log.jsonl: full play-by-play for every 10th episode
    - top_runs_recent.jsonl: top 10 by reward from last 1000 episodes
    """
    SAMPLE_EVERY   = 10    # log full detail every Nth episode
    TOP_N          = 10    # keep top N from recent window
    RECENT_WINDOW  = 1000  # window size for rolling top-N

    def __init__(self, verbose=0):
        super().__init__(verbose)
        self.best_reward   = -np.inf
        self.episode_count = 0
        self._ep_steps     = []   # list of {action, reward, hand_type, jokers}
        self._ep_reward    = 0.0
        self._recent_buf   = []   # ring buffer for rolling top-N (list of ep records)

        self.best_log   = LOG_DIR / "best_runs.jsonl"
        self.ep_log     = LOG_DIR / "episode_log.jsonl"
        self.detail_log = LOG_DIR / "run_detail_log.jsonl"
        self.top_log    = LOG_DIR / "top_runs_recent.jsonl"

    def _on_step(self) -> bool:
        raw    = self.locals["actions"]
        action = raw[0].tolist() if hasattr(raw, "__len__") else [int(raw)]
        reward = float(self.locals["rewards"][0])
        done   = bool(self.locals["dones"][0])

        # Capture per-step detail from the env
        env = self.training_env.envs[0].env
        step_detail = {
            "action":    action,
            "reward":    round(reward, 4),
            "hand_type": getattr(env, "_last_hand_type", "unknown"),
            "jokers":    getattr(env, "_last_joker_names", []),
        }
        self._ep_steps.append(step_detail)
        self._ep_reward += reward

        if done:
            self.episode_count += 1
            ep_len = len(self._ep_steps)
            seed   = getattr(env, "_last_seed",  "unknown")
            ante   = getattr(env, "_last_ante",  1)
            score  = getattr(env, "_last_score", 0)

            ep_record = {
                "episode":   self.episode_count,
                "timestep":  self.num_timesteps,
                "reward":    round(self._ep_reward, 3),
                "length":    ep_len,
                "seed":      seed,
                "ante":      ante,
                "score":     score,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            }

            # Always: summary log
            with self.ep_log.open("a") as f:
                f.write(json.dumps(ep_record) + "\n")

            # Every 10th episode: full play-by-play detail
            if self.episode_count % self.SAMPLE_EVERY == 0:
                detail_record = {**ep_record, "steps": self._ep_steps}
                with self.detail_log.open("a") as f:
                    f.write(json.dumps(detail_record) + "\n")

            # All-time best: full detail
            if self._ep_reward > self.best_reward:
                self.best_reward = self._ep_reward
                best_record = {**ep_record, "steps": self._ep_steps}
                with self.best_log.open("a") as f:
                    f.write(json.dumps(best_record) + "\n")
                print(f"\n★ New best! Episode {self.episode_count} | "
                      f"reward={self._ep_reward:.1f} | ante={ante} | seed={seed}")

            # Rolling top-10 from last 1000
            self._recent_buf.append({**ep_record, "steps": self._ep_steps})
            if len(self._recent_buf) > self.RECENT_WINDOW:
                self._recent_buf.pop(0)
            top10 = heapq.nlargest(self.TOP_N, self._recent_buf,
                                   key=lambda r: r["reward"])
            self.top_log.write_text(
                "\n".join(json.dumps(r) for r in top10) + "\n"
            )

            # Reset episode state
            self._ep_steps  = []
            self._ep_reward = 0.0

        return True


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--resume",    action="store_true")
    parser.add_argument("--no-launch", action="store_true",
                        help="Skip auto-launch (Balatro already running)")
    parser.add_argument("--steps",     type=int, default=TOTAL_TIMESTEPS)
    args = parser.parse_args()

    # ── Launch Balatro ──────────────────────────────────────────────────────
    if not args.no_launch:
        kill_balatro()   # clean slate if already open
        time.sleep(1)
        launch_balatro()

    # ── Env + Model ─────────────────────────────────────────────────────────
    base_env = BalatroEnv()
    env      = Monitor(base_env, filename=str(LOG_DIR / "monitor"))

    checkpoint_cb = CheckpointCallback(
        save_freq   = 2000,
        save_path   = str(CHECKPOINT_DIR),
        name_prefix = "balatro_ppo",
        verbose     = 1,
    )
    best_run_cb = BestRunCallback(verbose=1)

    def _ckpt_step(p):
        try:
            return int(p.stem.split("_")[-2])
        except (ValueError, IndexError):
            return -1

    latest = sorted(CHECKPOINT_DIR.glob("balatro_ppo_*.zip"), key=_ckpt_step)
    if args.resume and latest:
        model_path = str(latest[-1])
        print(f"Resuming from {model_path}")
        model = PPO.load(model_path, env=env)
    else:
        print("Starting fresh PPO model")
        model = PPO(env=env, **PPO_KWARGS)

    print(f"\nPolicy network:\n{model.policy}\n")
    print(f"Training for {args.steps:,} timesteps (restart every {RESTART_EVERY:,} steps)...")
    print("=" * 60)

    # ── Chunked training loop with periodic Balatro restarts ────────────────
    trained       = 0
    first_chunk   = True
    while trained < args.steps:
        chunk = min(RESTART_EVERY, args.steps - trained)
        model.learn(
            total_timesteps     = chunk,
            callback            = [checkpoint_cb, best_run_cb],
            reset_num_timesteps = (first_chunk and not args.resume),
        )
        trained     += chunk
        first_chunk  = False

        if trained < args.steps:
            # Save checkpoint before restart so nothing is lost
            mid_path = str(CHECKPOINT_DIR / f"balatro_ppo_{trained}_steps")
            model.save(mid_path)
            print(f"\n[restart] Saved checkpoint: {mid_path}.zip")
            restart_balatro()
            # Re-wrap env after restart (env itself persists, just Balatro relaunched)
            print("[restart] Resuming training...\n")

    model.save(str(CHECKPOINT_DIR / "balatro_ppo_final"))
    print("\nTraining complete. Saved to checkpoints/balatro_ppo_final.zip")

if __name__ == "__main__":
    main()
