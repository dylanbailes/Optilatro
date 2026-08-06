"""
train_v2.py
V2 PPO training with MaskablePPO and Discrete(20) action space.

Usage:
    python train_v2.py              # Fresh start
    python train_v2.py --resume     # Resume from latest checkpoint
"""

import argparse
import json
import heapq
import time
import subprocess
import os
from pathlib import Path

# Check for sb3-contrib
try:
    from sb3_contrib import MaskablePPO
    from sb3_contrib.common.wrappers import ActionMasker
except ImportError:
    print("ERROR: sb3-contrib not installed. Run: pip install sb3-contrib")
    print("Then restart this script.")
    exit(1)

from stable_baselines3.common.callbacks import BaseCallback
from stable_baselines3.common.vec_env import DummyVecEnv

from balatro_rl.env_v2 import BalatroEnvV2

# -- Paths ---------------------------------------------------------------------

CHECKPOINT_DIR = Path("checkpoints_v2")
LOG_DIR = Path("logs_v2")
BALATRO_EXE = os.environ.get(
    "BALATRO_EXE",
    r"C:\Program Files (x86)\Steam\steamapps\common\Balatro\Balatro.exe"
)
STATE_JSON = Path.home() / "AppData/Roaming/Balatro/balatro_rl/state.json"

# -- Action masking wrapper ----------------------------------------------------

def mask_fn(env):
    """Return action mask from the underlying BalatroEnvV2."""
    return env.action_masks()

# -- Callbacks -----------------------------------------------------------------

class EpisodeLoggerV2(BaseCallback):
    """Log episode stats and save best runs."""
    
    SAMPLE_EVERY = 10
    TOP_N = 10
    RECENT_WINDOW = 1000
    
    def __init__(self, verbose=0):
        super().__init__(verbose)
        LOG_DIR.mkdir(exist_ok=True)
        
        self.ep_log = LOG_DIR / "episode_log.jsonl"
        self.detail_log = LOG_DIR / "run_detail_log.jsonl"
        self.best_log = LOG_DIR / "best_runs.jsonl"
        self.top_log = LOG_DIR / "top_runs_recent.jsonl"
        
        self.episode_count = 0
        self.best_reward = float("-inf")
        self._ep_reward = 0.0
        self._ep_steps = []
        self._recent_buf = []
        
        # Timing tracking
        self._training_start = time.time()
        self._last_rate_check = time.time()
        self._last_rate_eps = 0
    
    def _on_step(self) -> bool:
        action = int(self.locals["actions"][0])
        reward = float(self.locals["rewards"][0])
        done = bool(self.locals["dones"][0])
        
        env = self.training_env.envs[0]
        # ActionMasker wraps the actual env
        actual_env = env.env if hasattr(env, 'env') else env
        
        step_detail = {
            "action": action,
            "reward": round(reward, 4),
            "action_type": getattr(actual_env, "_last_action_type", "unknown"),
            "hand_type": getattr(actual_env, "_last_hand_type", "unknown"),
            "jokers": getattr(actual_env, "_last_joker_names", []),
        }
        self._ep_steps.append(step_detail)
        self._ep_reward += reward
        
        if done:
            self.episode_count += 1
            ep_len = len(self._ep_steps)
            seed = getattr(actual_env, "_last_seed", "unknown")
            ante = getattr(actual_env, "_last_ante", 1)
            round_num = getattr(actual_env, "_last_round", 0)
            blind = getattr(actual_env, "_last_blind", "Small Blind")
            score = getattr(actual_env, "_last_score", 0)
            terminal_reason = getattr(actual_env, "_terminal_reason", "unknown")
            
            # Calculate timing stats
            elapsed_total = time.time() - self._training_start
            elapsed_min = elapsed_total / 60
            eps_per_hour = (self.episode_count / elapsed_total) * 3600 if elapsed_total > 0 else 0
            
            # Recent rate (last 100 episodes)
            if self.episode_count % 100 == 0:
                recent_elapsed = time.time() - self._last_rate_check
                recent_eps = self.episode_count - self._last_rate_eps
                recent_rate = (recent_eps / recent_elapsed) * 3600 if recent_elapsed > 0 else 0
                self._last_rate_check = time.time()
                self._last_rate_eps = self.episode_count
                
                # Estimate time to 25k
                remaining_eps = max(0, 25000 - self.episode_count)
                eta_hours = remaining_eps / recent_rate if recent_rate > 0 else float('inf')
                
                print(f"\n[STATS] [{elapsed_min:.0f}m] Rate: {recent_rate:.0f} eps/hr | "
                      f"ETA to 25k: {eta_hours:.1f}h")
            
            ep_record = {
                "episode": self.episode_count,
                "timestep": self.num_timesteps,
                "reward": round(self._ep_reward, 3),
                "length": ep_len,
                "seed": seed,
                "ante": ante,
                "round": round_num,
                "blind": blind,
                "score": score,
                "terminal": terminal_reason,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "elapsed_min": round(elapsed_min, 1),
                "eps_per_hour": round(eps_per_hour, 1),
            }
            
            # Always: summary log
            with self.ep_log.open("a") as f:
                f.write(json.dumps(ep_record) + "\n")
            
            # Every 10th: detail log
            if self.episode_count % self.SAMPLE_EVERY == 0:
                detail_record = {**ep_record, "steps": self._ep_steps}
                with self.detail_log.open("a") as f:
                    f.write(json.dumps(detail_record) + "\n")
            
            # Best ever
            if self._ep_reward > self.best_reward:
                self.best_reward = self._ep_reward
                best_record = {**ep_record, "steps": self._ep_steps}
                with self.best_log.open("a") as f:
                    f.write(json.dumps(best_record) + "\n")
                print(f"\n* New best! Episode {self.episode_count} | "
                      f"reward={self._ep_reward:.1f} | ante={ante} | seed={seed}")
            
            # Rolling top-10
            self._recent_buf.append({**ep_record, "steps": self._ep_steps})
            if len(self._recent_buf) > self.RECENT_WINDOW:
                self._recent_buf.pop(0)
            top10 = heapq.nlargest(self.TOP_N, self._recent_buf, key=lambda r: r["reward"])
            self.top_log.write_text("\n".join(json.dumps(r) for r in top10) + "\n")
            
            # Reset
            self._ep_reward = 0.0
            self._ep_steps = []
        
        return True


class CheckpointCallback(BaseCallback):
    """Save model every N steps."""
    
    def __init__(self, save_freq: int = 10_000, verbose=0):
        super().__init__(verbose)
        self.save_freq = save_freq
        CHECKPOINT_DIR.mkdir(exist_ok=True)
    
    def _on_step(self) -> bool:
        if self.num_timesteps % self.save_freq == 0:
            path = CHECKPOINT_DIR / f"ppo_v2_{self.num_timesteps}.zip"
            self.model.save(str(path))
            print(f"\n[SAVE] Checkpoint saved: {path.name}")
        return True


class RestartCallback(BaseCallback):
    """Restart Balatro periodically to prevent memory leaks."""
    
    RESTART_EVERY = 6_000  # steps
    
    def __init__(self, verbose=0):
        super().__init__(verbose)
        self._last_restart = None  # Set on first step
    
    def _on_step(self) -> bool:
        # Initialize on first step (handles resume correctly)
        if self._last_restart is None:
            self._last_restart = self.num_timesteps
            return True
        
        if self.num_timesteps - self._last_restart >= self.RESTART_EVERY:
            self._last_restart = self.num_timesteps
            print(f"\n[RESTART] Periodic restart at step {self.num_timesteps}...")
            restart_balatro()
        return True


class WatchdogCallback(BaseCallback):
    """Detect stuck training and force restart if no progress."""
    
    STALE_SECONDS = 120  # 2 minutes with no steps = stuck
    
    def __init__(self, verbose=0):
        super().__init__(verbose)
        self._last_step_time = time.time()
        self._last_timesteps = 0
    
    def _on_step(self) -> bool:
        now = time.time()
        
        # Check if we've made progress
        if self.num_timesteps > self._last_timesteps:
            self._last_step_time = now
            self._last_timesteps = self.num_timesteps
        
        # Check for staleness
        stale_time = now - self._last_step_time
        if stale_time > self.STALE_SECONDS:
            print(f"\n[WARN] WATCHDOG: No progress for {stale_time:.0f}s -- forcing restart...")
            restart_balatro()
            self._last_step_time = time.time()
        
        return True


# -- Balatro management --------------------------------------------------------

def restart_balatro():
    """Kill and relaunch Balatro."""
    r = subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq Balatro.exe", "/FO", "CSV", "/NH"],
        capture_output=True, text=True
    )
    for line in r.stdout.splitlines():
        if "Balatro.exe" in line:
            try:
                pid = int(line.split(",")[1].strip('"'))
                subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True)
                time.sleep(2)
            except (IndexError, ValueError):
                pass
    time.sleep(1)
    if os.path.exists(BALATRO_EXE):
        subprocess.Popen([BALATRO_EXE])
        print("[train_v2] Balatro launched. Waiting for state.json...")
        deadline = time.time() + 30
        while time.time() < deadline:
            if STATE_JSON.exists():
                mtime = STATE_JSON.stat().st_mtime
                if time.time() - mtime < 5:
                    print("[train_v2] state.json detected. Continuing...")
                    return
            time.sleep(1)
        print("[train_v2] Warning: state.json not detected in time.")


def find_latest_checkpoint():
    """Find the most recent checkpoint file."""
    if not CHECKPOINT_DIR.exists():
        return None
    checkpoints = list(CHECKPOINT_DIR.glob("ppo_v2_*.zip"))
    if not checkpoints:
        return None
    return max(checkpoints, key=lambda p: int(p.stem.split("_")[-1]))


# -- Main ----------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="V2 Balatro RL Training")
    parser.add_argument("--resume", action="store_true", help="Resume from latest checkpoint")
    parser.add_argument("--no-launch", action="store_true", help="Don't auto-launch Balatro")
    parser.add_argument("--steps", type=int, default=10_000_000, help="Total training steps")
    args = parser.parse_args()
    
    # Launch Balatro if needed
    if not args.no_launch:
        restart_balatro()
    
    # Create environment with action masking wrapper
    def make_env():
        env = BalatroEnvV2()
        env = ActionMasker(env, mask_fn)
        return env
    
    vec_env = DummyVecEnv([make_env])
    
    # Create or load model
    if args.resume:
        ckpt = find_latest_checkpoint()
        if ckpt:
            print(f"[RESUME] Loading from {ckpt.name}")
            model = MaskablePPO.load(str(ckpt), env=vec_env)
        else:
            print("[WARN] No checkpoint found, starting fresh")
            model = MaskablePPO(
                "MlpPolicy",
                vec_env,
                verbose=1,
                learning_rate=3e-4,
                n_steps=2048,
                batch_size=64,
                n_epochs=10,
                gamma=0.99,
                gae_lambda=0.95,
                clip_range=0.2,
                ent_coef=0.01,
                policy_kwargs=dict(net_arch=[256, 256, 128]),
                tensorboard_log=str(LOG_DIR / "tensorboard"),
            )
    else:
        print("[NEW] Starting fresh V2 training")
        model = MaskablePPO(
            "MlpPolicy",
            vec_env,
            verbose=1,
            learning_rate=3e-4,
            n_steps=2048,
            batch_size=64,
            n_epochs=10,
            gamma=0.99,
            gae_lambda=0.95,
            clip_range=0.2,
            ent_coef=0.01,
            policy_kwargs=dict(net_arch=[256, 256, 128]),
            tensorboard_log=str(LOG_DIR / "tensorboard"),
        )
    
    # Callbacks
    callbacks = [
        EpisodeLoggerV2(),
        CheckpointCallback(save_freq=10_000),
        RestartCallback(),
        WatchdogCallback(),  # Force restart if stuck for 2+ minutes
    ]
    
    print(f"\n{'='*60}")
    print("V2 Training Started")
    print(f"  Action space: Discrete(20)")
    print(f"  Observation size: 206")
    print(f"  Checkpoints: {CHECKPOINT_DIR}")
    print(f"  Logs: {LOG_DIR}")
    print(f"{'='*60}\n")
    
    try:
        model.learn(
            total_timesteps=args.steps,
            callback=callbacks,
            reset_num_timesteps=not args.resume,
        )
    except KeyboardInterrupt:
        print("\n[INTERRUPT] Training interrupted. Saving checkpoint...")
        model.save(str(CHECKPOINT_DIR / f"ppo_v2_interrupted_{model.num_timesteps}.zip"))
        print("Saved.")


if __name__ == "__main__":
    main()

