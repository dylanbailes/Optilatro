"""replay.py — replay-diff harness.

Runs a seed in seed mode with a deterministic action sequence, captures the
per-node RNG draw log (node id, value, method, result) via the SeedSource
tracing hook, and diffs two runs bit-for-bit.

Usage as a library:

    records, summary = capture_game(seed=1234, steps=2000)
    assert summary["sha256"] == log_sha(records)      # bit-for-bit fingerprint
    diff = ReplayDiff(records_a, records_b)
    diff.identical  /  diff.first_divergence()  /  print(diff.report(...))

CLI:

    python -m balatro_sim.replay --seed 1234 --steps 2000 [--action-seed 12345]

Exits 0 when the two runs are bit-identical, 1 on divergence. The first
divergence pinpoints exactly which node draw went off the rails — e.g. a
consumer still reading module `random` instead of the game's source.

NOTE: tracing is seed-mode only. Generic mode shares one Python stream with no
per-node values, so its draws aren't captured (see seed_rng.py).
"""
from __future__ import annotations

import argparse
import hashlib
import random as _random
from dataclasses import dataclass
from typing import Optional

from .seed_rng import DrawRecord


def capture_game(
    seed,
    steps: int = 2000,
    action_seed: int = 12345,
    actions: Optional[list[int]] = None,
    trace: bool = True,
):
    """Run env_sim in seed mode with a deterministic policy.

    Returns (draw_log, summary). The draw log survives episode resets: reset()
    recreates the game (and its SeedSource), so tracing is re-armed on each
    new source and its records appended to the same master list.
    """
    from .env_sim import BalatroSimEnv

    env = BalatroSimEnv(seed=seed, rng_mode="seed")
    env.reset()
    records: list[DrawRecord] = []
    if trace:
        records.extend(env.game.rng.enable_tracing())

    action_rng = _random.Random(action_seed)
    total = 0.0
    episodes = 0
    max_ante = 0

    if actions == []:
        actions = None
    for step in range(steps):
        if actions is not None:
            action = actions[step % len(actions)]
        else:
            action = action_rng.randrange(env.action_space.n)
        _, reward, terminated, truncated, _ = env.step(action)
        total += reward
        max_ante = max(max_ante, env.game.ante)
        if terminated or truncated:
            episodes += 1
            if trace:
                records.extend(env.game.rng.disable_tracing())
            env.reset()
            if trace:
                records.extend(env.game.rng.enable_tracing())

    if trace:
        records.extend(env.game.rng.disable_tracing())

    summary = {
        "seed": str(seed),
        "steps": steps,
        "total_reward": round(total, 6),
        "episodes": episodes,
        "max_ante": max_ante,
    }
    if trace:
        summary["records"] = len(records)
        summary["sha256"] = log_sha(records)
    return records, summary


def log_sha(records: list[DrawRecord]) -> str:
    """Bit-for-bit fingerprint of a draw log."""
    h = hashlib.sha256()
    for r in records:
        h.update(r.as_text().encode("utf-8"))
    return h.hexdigest()


@dataclass
class ReplayDiff:
    """Result of diffing two draw logs."""

    a: list[DrawRecord]
    b: list[DrawRecord]

    @property
    def identical(self) -> bool:
        return len(self.a) == len(self.b) and all(
            x.as_text() == y.as_text() for x, y in zip(self.a, self.b)
        )

    def first_divergence(self):
        """(index, record_a, record_b) at the first difference, or None."""
        n = min(len(self.a), len(self.b))
        for i in range(n):
            if self.a[i].as_text() != self.b[i].as_text():
                return (i, self.a[i], self.b[i])
        if len(self.a) != len(self.b):
            return (n, self.a[n] if n < len(self.a) else None,
                    self.b[n] if n < len(self.b) else None)
        return None

    def report(self, sa=None, sb=None, context: int = 5) -> str:
        lines = [f"run A: {sa or {}}", f"run B: {sb or {}}"]
        if self.identical:
            lines.append(f"IDENTICAL: {len(self.a)} draws, sha256 {log_sha(self.a)}")
            return "\n".join(lines)
        lines.append(f"DIVERGED: A={len(self.a)} draws, B={len(self.b)} draws")
        fd = self.first_divergence()
        if fd:
            i, ra, rb = fd
            lines.append(f"first divergence at draw #{i}:")
            lines.append(f"  A: {ra.as_text()}")
            lines.append(f"  B: {rb.as_text()}")
            lo = max(0, i - context)
            hi = min(len(self.b), i + context)
            lines.append("  B context:")
            for j in range(lo, hi):
                mark = ">>>" if j == i else "   "
                lines.append(f"  {mark} #{j}: {self.b[j].as_text()}")
        return "\n".join(lines)


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m balatro_sim.replay",
        description="Replay-diff harness: run a seed twice in seed mode and "
                    "diff the per-node RNG draw logs bit-for-bit.",
    )
    ap.add_argument("--seed", default="1234", help="run seed (default 1234)")
    ap.add_argument("--steps", type=int, default=2000)
    ap.add_argument("--action-seed", type=int, default=12345,
                    help="seed for the random-policy action sequence")
    ap.add_argument("--sha", action="store_true",
                    help="single-run mode: print one machine-readable line with the "
                         "draw-log sha256 + run summary, exit 0. Useful for cross-process "
                         "seed-exactness gates (run under several PYTHONHASHSEED values "
                         "and diff the line).")
    args = ap.parse_args(argv)

    if args.sha:
        _, summary = capture_game(args.seed, args.steps, args.action_seed)
        print(f"{summary['sha256']} seed={summary['seed']} steps={summary['steps']} "
              f"total={summary['total_reward']} episodes={summary['episodes']} "
              f"max_ante={summary['max_ante']} records={summary['records']}")
        return 0

    a, sa = capture_game(args.seed, args.steps, args.action_seed)
    b, sb = capture_game(args.seed, args.steps, args.action_seed)
    diff = ReplayDiff(a, b)
    print(diff.report(sa, sb))
    return 0 if diff.identical else 1


if __name__ == "__main__":
    raise SystemExit(main())
