"""A/B harness: random-agent win rate with the mid-round reshuffle disabled.

Monkey-patches BalatroGame._draw_to_full back to the pre-reshuffle version
(deck exhausted -> no draw) so we can isolate the reshuffle's effect on the
random baseline. Same methodology as bench_sim.py --games N.
"""
from __future__ import annotations

import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENDOR = ROOT / "vendor" / "balatro-rl"
sys.path.insert(0, str(VENDOR))

from balatro_sim.env_sim import BalatroSimEnv  # noqa: E402
from balatro_sim.game import BalatroGame  # noqa: E402


def _old_draw_to_full(self):
    """Pre-reshuffle behavior: no mid-round deck refill."""
    target = self.hand_size
    if self._boss_effects_on() and self.current_blind.boss_key == "bl_fish":
        played = self.base_hands - self.hands_left
        target = max(1, self.hand_size - played)
    while len(self.hand) < target and self.deck:
        c = self.deck.pop()
        self._on_card_drawn(c)
        self.hand.append(c)


def _fmt_eta(seconds: float) -> str:
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def bench_winrate(n_games: int, batch_size: int = 0) -> tuple[int, int, dict[int, int]]:
    wins = 0
    losses = 0
    death_by_ante: dict[int, int] = {}
    t0 = time.perf_counter()
    for i in range(1, n_games + 1):
        env = BalatroSimEnv(seed=random.randrange(1_000_000_000))
        env.reset()
        steps = 0
        while True:
            act = random.randrange(env.action_space.n)
            _, _, terminated, truncated, _ = env.step(act)
            steps += 1
            if steps > 100_000:
                death_by_ante[env.game.ante] = death_by_ante.get(env.game.ante, 0) + 1
                losses += 1
                break
            if terminated or truncated:
                g = env.game
                won = getattr(g, "won", False) or (g.ante > 8)
                bucket = 9 if won else g.ante
                death_by_ante[bucket] = death_by_ante.get(bucket, 0) + 1
                if won:
                    wins += 1
                else:
                    losses += 1
                break
        if batch_size and i % batch_size == 0:
            total = wins + losses
            rate = i / (time.perf_counter() - t0)
            eta = (n_games - i) / rate if rate else 0.0
            pct = 100.0 * wins / total if total else 0.0
            print(f"  {i}/{n_games} games | {wins} wins ({pct:.2f}%) | "
                  f"{rate:.1f} games/s | ETA {_fmt_eta(eta)}", flush=True)
    return wins, losses, death_by_ante


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=1000)
    ap.add_argument("--no-reshuffle", action="store_true",
                    help="disable the mid-round reshuffle (A/B)")
    ap.add_argument("--batch-size", type=int, default=100,
                    help="print a flushed progress line every N games "
                         "(0 = end only)")
    args = ap.parse_args()
    if args.no_reshuffle:
        BalatroGame._draw_to_full = _old_draw_to_full

    t0 = time.perf_counter()
    wins, losses, death_by_ante = bench_winrate(args.games, args.batch_size)
    dt = time.perf_counter() - t0
    total = wins + losses
    mode = "no-reshuffle" if args.no_reshuffle else "with-reshuffle"
    print(f"[{mode}] random-agent win rate: {wins}/{total} = "
          f"{100.0 * wins / total:.2f}% (losses: {losses}) in {dt:.1f}s")
    print(f"[{mode}] death by ante (9 = won past ante 8):")
    for ante in range(1, 10):
        n = death_by_ante.get(ante, 0)
        if n:
            print(f"  ante {ante}: {n:>5} ({100.0 * n / total:5.2f}%)")


if __name__ == "__main__":
    main()
