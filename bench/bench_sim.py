"""
bench/bench_sim.py — M0 baseline benchmark for the vendored balatro-rl sim.

Measures:
  1. Env steps/s (random agent, single process) — the throughput baseline that
     every search/learning speedup will be compared against.
  2. Random-agent win rate over N games (baseline: balatro-rl reports <0.01%).

Usage:
  .venv/Scripts/python.exe bench/bench_sim.py [--games N] [--seconds S]

Run from the project root (D:\\Optilatro). The vendored sim lives in
vendor/balatro-rl and is imported via sys.path insertion (no install needed).
"""
from __future__ import annotations

import argparse
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENDOR = ROOT / "vendor" / "balatro-rl"
sys.path.insert(0, str(VENDOR))

from balatro_sim.env_sim import BalatroSimEnv  # noqa: E402


def bench_throughput(seconds: float = 5.0) -> tuple[int, float]:
    """Random actions for `seconds` seconds; return (steps, steps_per_second)."""
    env = BalatroSimEnv()
    env.reset()
    steps = 0
    games = 0
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < seconds:
        act = random.randrange(env.action_space.n)
        _, _, terminated, truncated, _ = env.step(act)
        steps += 1
        if terminated or truncated:
            env.reset()
            games += 1
    dt = time.perf_counter() - t0
    return steps, steps / dt


def bench_winrate(n_games: int = 100) -> tuple[int, int, int]:
    """Random-agent win rate over n_games full runs (ante-8 completion)."""
    wins = 0
    losses = 0
    ante_reached: dict[int, int] = {}
    for _ in range(n_games):
        env = BalatroSimEnv(seed=random.randrange(1_000_000_000))
        obs, _ = env.reset()
        steps = 0
        while True:
            act = random.randrange(env.action_space.n)
            obs, _, terminated, truncated, _ = env.step(act)
            steps += 1
            if steps > 100_000:
                # Safety cap: a pathological state must never hang the benchmark.
                # Count the stalled run as a loss and move on.
                ante_reached[env.game.ante] = ante_reached.get(env.game.ante, 0) + 1
                losses += 1
                break
            if terminated or truncated:
                # env_sim exposes the underlying game for inspection
                g = env.game
                won = getattr(g, "won", False) or (g.ante > 8)
                ante_reached[g.ante] = ante_reached.get(g.ante, 0) + 1
                if won:
                    wins += 1
                else:
                    losses += 1
                break
    return wins, losses, max(ante_reached, default=1)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=100, help="games for win-rate bench")
    ap.add_argument("--seconds", type=float, default=5.0, help="seconds for throughput bench")
    args = ap.parse_args()

    steps, sps = bench_throughput(args.seconds)
    print(f"throughput: {steps} steps in {args.seconds:.1f}s -> {sps:.0f} steps/s (single env, random agent)")

    t0 = time.perf_counter()
    wins, losses, max_ante = bench_winrate(args.games)
    dt = time.perf_counter() - t0
    total = wins + losses
    print(
        f"random-agent win rate: {wins}/{total} = "
        f"{100.0 * wins / total:.2f}% (losses: {losses}, max ante reached: {max_ante}) "
        f"in {dt:.1f}s"
    )


if __name__ == "__main__":
    main()
