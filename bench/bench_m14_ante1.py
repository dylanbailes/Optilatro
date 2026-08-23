"""bench/bench_m14_ante1.py — chunked paired A/B for the M14 ante-1 work.

The full 200-seed bank does not fit one sandbox command, so this runner does
ONE chunk per invocation and APPENDS per-seed outcomes (both policies, paired
on the same seed) to a JSONL file. Aggregate with --summarize.

Usage:
  python3 bench/bench_m14_ante1.py --seed-start 0  --seeds 50 --out /tmp/m14.jsonl
  python3 bench/bench_m14_ante1.py --summarize --out /tmp/m14.jsonl
"""
from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENDOR = ROOT / "vendor" / "balatro-rl"
sys.path.insert(0, str(VENDOR))

from balatro_sim.agent_v9 import HeuristicV9          # noqa: E402
from balatro_sim.agent_v10 import HeuristicV10         # noqa: E402
from balatro_sim.game import BalatroGame               # noqa: E402
from balatro_sim.rollout import rollout                # noqa: E402


def _run_one(job):
    seed, name, params, tag = job
    if name == "heuristic_v10" and params:
        # Params apply to the v10 arm ONLY - the v9 baseline must stay frozen
        # (an earlier version reassigned cls for both arms and silently ran
        # the "v9" rows as v10, invalidating paired comparisons).
        from balatro_sim import agent_v10 as v10
        v10.V10_PARAMS.update(v10.V10_DEFAULTS)
        v10.V10_PARAMS.update(params)
        cls = HeuristicV10
    else:
        cls = HeuristicV9 if name == "heuristic_v9" else HeuristicV10
    g = BalatroGame(seed=seed, rng_mode="seed")
    r = rollout(g, cls())
    r["seed"] = seed
    r["policy"] = name
    r["tag"] = tag
    # ante-1 death: died during ante 1 (never reached ante 2)
    r["ante1_death"] = (not r["won"]) and r.get("ante", 1) <= 1
    return r


def run_chunk(seed_start: int, n: int, out: Path, workers: int,
              target_off: bool = False, params=None, tag: str = "base") -> None:
    if params is None:
        params = {"target_enabled": False} if target_off else {}
    jobs = [(s, p, params, tag) for s in range(seed_start, seed_start + n)
            for p in ("heuristic_v9", "heuristic_v10")]
    with mp.Pool(workers) as pool:
        rows = pool.map(_run_one, jobs)
    with out.open("a") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    print(f"wrote {len(rows)} rows ({n} seeds x 2, tag={tag}) -> {out}")


def summarize(out: Path) -> None:
    rows = [json.loads(ln) for ln in out.read_text().splitlines() if ln.strip()]
    seen = {}
    for r in rows:                       # dedupe retried chunks (deterministic)
        seen[(r.get("tag", "base"), r["seed"], r["policy"])] = r
    rows = list(seen.values())
    by = {}
    for r in rows:
        by.setdefault((r.get("tag", "base"), r["policy"]), []).append(r)
    for (tag, name), rs in sorted(by.items()):
        n = len(rs)
        wins = sum(r["won"] for r in rs)
        a1 = sum(r["ante1_death"] for r in rs)
        seeds = sorted({r["seed"] for r in rs})
        other_pol = ("heuristic_v10" if name == "heuristic_v9"
                     else "heuristic_v9")
        o = {r["seed"]: r for r in by.get((tag, other_pol), [])}
        fixed = sum(1 for r in rs if r["ante1_death"]
                    and not o.get(r["seed"], r).get("ante1_death", True))
        broke = sum(1 for r in rs if not r["ante1_death"]
                    and o.get(r["seed"], {}).get("ante1_death", False))
        print(f"[{tag}] {name}: n={n} seeds {seeds[0]}..{seeds[-1]}  "
              f"wins {wins}/{n} = {wins / n:.1%}  "
              f"ante1_deaths {a1}/{n} = {a1 / n:.1%}  "
              f"(fixed {fixed}, newly-broke {broke})")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed-start", type=int, default=0)
    ap.add_argument("--seeds", type=int, default=50)
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--out", type=str, default="/tmp/m14_ante1.jsonl")
    ap.add_argument("--target-off", action="store_true",
                    help="control arm: V10_PARAMS['target_enabled']=False")
    ap.add_argument("--params", type=str, default=None,
                    help="JSON dict of V10_PARAMS overrides for the v10 arm")
    ap.add_argument("--tag", type=str, default="base",
                    help="arm label stored in each row")
    ap.add_argument("--summarize", action="store_true")
    a = ap.parse_args()
    out = Path(a.out)
    if a.summarize:
        summarize(out)
    else:
        params = json.loads(a.params) if a.params else (
            {"target_enabled": False} if a.target_off else {})
        run_chunk(a.seed_start, a.seeds, out, a.workers,
                  params=params, tag=a.tag)
