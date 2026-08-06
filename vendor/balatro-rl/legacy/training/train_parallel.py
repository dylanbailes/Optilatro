"""
train_parallel.py
Parallel PPO training with multiple Balatro instances.

Usage:
    python train_parallel.py --instances 4              # Fresh start with 4 instances
    python train_parallel.py --instances 4 --resume     # Resume from checkpoint
"""

import argparse
import json
import time
import os
import subprocess
from pathlib import Path
from multiprocessing import Process

from sb3_contrib import MaskablePPO
from sb3_contrib.common.wrappers import ActionMasker
from stable_baselines3.common.vec_env import SubprocVecEnv
from stable_baselines3.common.callbacks import BaseCallback

from balatro_rl.env_parallel import BalatroEnvParallel

# Paths
CHECKPOINT_DIR = Path("checkpoints_parallel")
LOG_DIR = Path("logs_parallel")
BALATRO_EXE = os.environ.get(
    "BALATRO_EXE",
    r"C:\Program Files (x86)\Steam\steamapps\common\Balatro\Balatro.exe"
)
MOD_SOURCE = Path("mod_v2/BalatroRL_parallel.lua")
MOD_DEST_BASE = Path.home() / "AppData/Roaming/Balatro/Mods/BalatroRL"


def mask_fn(env):
    return env.action_masks()


def make_env(instance_id: int):
    """Factory function for creating environments."""
    def _init():
        env = BalatroEnvParallel(instance_id=instance_id)
        env = ActionMasker(env, mask_fn)
        return env
    return _init


class ParallelLoggerCallback(BaseCallback):
    """Log episodes from all parallel environments."""
    
    def __init__(self, n_instances: int, verbose=0):
        super().__init__(verbose)
        LOG_DIR.mkdir(exist_ok=True)
        self.n_instances = n_instances
        self.ep_log = LOG_DIR / "episode_log.jsonl"
        self.episode_counts = [0] * n_instances
        self.episode_rewards = [0.0] * n_instances
        self.episode_lengths = [0] * n_instances
        self.total_episodes = 0
        self._training_start = time.time()
    
    def _on_step(self) -> bool:
        # Check for episode completions
        for i, done in enumerate(self.locals["dones"]):
            self.episode_rewards[i] += self.locals["rewards"][i]
            self.episode_lengths[i] += 1
            
            if done:
                self.episode_counts[i] += 1
                self.total_episodes += 1
                
                # Get info from the environment
                info = self.locals["infos"][i]
                
                ep_record = {
                    "episode": self.total_episodes,
                    "instance": i,
                    "timestep": self.num_timesteps,
                    "reward": round(self.episode_rewards[i], 3),
                    "length": self.episode_lengths[i],
                    "ante": info.get("ante", 1),
                    "blind": info.get("blind", "?"),
                    "score": info.get("score", 0),
                    "terminal": info.get("terminal_reason", "unknown"),
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
                }
                
                with self.ep_log.open("a") as f:
                    f.write(json.dumps(ep_record) + "\n")
                
                # Print progress every 10 episodes
                if self.total_episodes % 10 == 0:
                    elapsed = (time.time() - self._training_start) / 60
                    rate = self.total_episodes / elapsed * 60 if elapsed > 0 else 0
                    print(f"[{elapsed:.0f}m] Episodes: {self.total_episodes} | "
                          f"Rate: {rate:.0f}/hr | Last: ante={info.get('ante',1)}, "
                          f"reward={self.episode_rewards[i]:.1f}")
                
                # Reset trackers
                self.episode_rewards[i] = 0.0
                self.episode_lengths[i] = 0
        
        return True


class CheckpointCallback(BaseCallback):
    """Save model periodically."""
    
    def __init__(self, save_freq: int = 10_000, verbose=0):
        super().__init__(verbose)
        self.save_freq = save_freq
        CHECKPOINT_DIR.mkdir(exist_ok=True)
    
    def _on_step(self) -> bool:
        if self.num_timesteps % self.save_freq == 0:
            path = CHECKPOINT_DIR / f"ppo_parallel_{self.num_timesteps}.zip"
            self.model.save(str(path))
            print(f"[SAVE] Checkpoint: {path.name}")
        return True


def deploy_mods(n_instances: int):
    """Deploy mod files with different instance IDs."""
    print(f"Deploying mods for {n_instances} instances...")
    
    mod_template = MOD_SOURCE.read_text(encoding='utf-8')
    
    for i in range(1, n_instances + 1):
        # Create instance-specific mod
        mod_content = mod_template.replace(
            "local INSTANCE_ID = 1",
            f"local INSTANCE_ID = {i}"
        )
        
        # Write to mod folder (we'll use a single mod folder but different state dirs)
        # For true parallel, we'd need separate game installs or use the same mod
        # that reads instance ID from environment or file
        
        # Create state directory
        state_dir = Path.home() / f"AppData/Roaming/Balatro/balatro_rl_{i}"
        state_dir.mkdir(exist_ok=True)
        
        print(f"  Instance {i}: {state_dir}")
    
    print("Mod deployment complete.")


def launch_balatro_instances(n_instances: int):
    """Launch multiple Balatro instances."""
    print(f"Launching {n_instances} Balatro instances...")
    
    processes = []
    for i in range(n_instances):
        # Launch with a slight delay to avoid conflicts
        proc = subprocess.Popen(
            [BALATRO_EXE],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        processes.append(proc)
        print(f"  Instance {i+1}: PID {proc.pid}")
        time.sleep(2)  # Stagger launches
    
    # Wait for all instances to initialize
    print("Waiting for instances to initialize...")
    time.sleep(10)
    
    return processes


def find_latest_checkpoint():
    """Find most recent checkpoint."""
    if not CHECKPOINT_DIR.exists():
        return None
    checkpoints = list(CHECKPOINT_DIR.glob("ppo_parallel_*.zip"))
    if not checkpoints:
        # Also check single-instance checkpoints for transfer
        single_dir = Path("checkpoints_v2")
        if single_dir.exists():
            single_ckpts = list(single_dir.glob("ppo_v2_*.zip"))
            if single_ckpts:
                return max(single_ckpts, key=lambda p: p.stat().st_mtime)
        return None
    return max(checkpoints, key=lambda p: p.stat().st_mtime)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--instances", type=int, default=4, help="Number of parallel instances")
    parser.add_argument("--resume", action="store_true", help="Resume from checkpoint")
    parser.add_argument("--total-timesteps", type=int, default=2_000_000)
    parser.add_argument("--deploy-mods", action="store_true", help="Deploy mod files")
    parser.add_argument("--launch", action="store_true", help="Launch Balatro instances")
    args = parser.parse_args()
    
    n_instances = args.instances
    
    # Optional: deploy mods
    if args.deploy_mods:
        deploy_mods(n_instances)
        return
    
    # Optional: launch instances
    if args.launch:
        launch_balatro_instances(n_instances)
        return
    
    LOG_DIR.mkdir(exist_ok=True)
    
    # Create vectorized environment
    print(f"Creating {n_instances} parallel environments...")
    env_fns = [make_env(i+1) for i in range(n_instances)]
    vec_env = SubprocVecEnv(env_fns)
    
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
                batch_size=64 * n_instances,  # Scale batch with instances
                n_epochs=10,
                gamma=0.99,
                gae_lambda=0.95,
                clip_range=0.2,
                ent_coef=0.01,
                policy_kwargs=dict(net_arch=[256, 256, 128]),
                tensorboard_log=str(LOG_DIR / "tensorboard"),
            )
    else:
        print("[NEW] Starting fresh parallel training")
        model = MaskablePPO(
            "MlpPolicy",
            vec_env,
            verbose=1,
            learning_rate=3e-4,
            n_steps=2048,
            batch_size=64 * n_instances,
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
        ParallelLoggerCallback(n_instances),
        CheckpointCallback(save_freq=10_000),
    ]
    
    print(f"\n{'='*60}")
    print(f"Parallel Training Started")
    print(f"  Instances: {n_instances}")
    print(f"  Total timesteps: {args.total_timesteps:,}")
    print(f"  Checkpoints: {CHECKPOINT_DIR}")
    print(f"  Logs: {LOG_DIR}")
    print(f"{'='*60}\n")
    
    try:
        model.learn(
            total_timesteps=args.total_timesteps,
            callback=callbacks,
            progress_bar=True,
        )
    except KeyboardInterrupt:
        print("\n[INTERRUPT] Saving checkpoint...")
        model.save(str(CHECKPOINT_DIR / f"ppo_parallel_interrupted_{model.num_timesteps}.zip"))
        print("Saved.")
    finally:
        vec_env.close()


if __name__ == "__main__":
    main()
