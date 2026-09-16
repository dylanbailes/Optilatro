"""bench/bench_agent_v10.py — M12 in-blind goal-hierarchy A/B benchmark.

Measures White-Stake full-run win rate + the §8 telemetry bundle (ante-1
deaths, econ-source $, interest collected, tarots/planets/spectrals
generated) over a fixed deterministic seed bank, in seed mode, per-seed
paired across policies (each policy runs the SAME seeds for an honest A/B).

Human-fair by construction: heuristic_v10 / search_shop_v10 use only
deck-composition P(clear) + value estimates (no draw-order peek, no rollout
lookahead by default — search_shop_v10's shop search is the comparative
mean-measure search, NOT --lookahead).

Usage:
  .venv/Scripts/python.exe bench/bench_agent_v10.py [--games N] [--workers W]
      [--policies heuristic_v9,heuristic_v10,search_shop_v9,search_shop_v10]
      [--seed-start 0] [--search-shops 1] [--params '{...}']
      [--report PATH] [--no-report] [--batch-size 25]

The §10.3 sweep: farm_spare_hands -> farm_clear_threshold ->
abandon_clear_floor -> 2x2 -> 1000-seed confirm. The key control arm is
`--params '{"farm_clear_threshold": 1.0}'` (value-farming OFF) to isolate
the farming contribution from the rest of the rework.
"""
from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parent.parent
VENDOR = ROOT / "vendor" / "balatro-rl"
sys.path.insert(0, str(VENDOR))

from balatro_sim.agent_v9 import HeuristicV9
from balatro_sim.agent_v10 import HeuristicV10, SearchShopV10
from balatro_sim.agent_v11 import SearchShopV11
from balatro_sim.agent_v12 import SearchShopV12
from balatro_sim.agent_l1 import SearchShopV9
from balatro_sim.game import BalatroGame
from balatro_sim.rollout import rollout


_POLICIES = {
    "heuristic_v9": HeuristicV9,
    "heuristic_v10": HeuristicV10,
    "search_shop_v9": SearchShopV9,
    "search_shop_v10": SearchShopV10,
    "search_shop_v11": SearchShopV11,
    "search_shop_v12": SearchShopV12,
}


def _make_policy(name: str, params, search_shops: int, lookahead: bool):
    if name in ("search_shop_v9", "search_shop_v10", "search_shop_v11",
                "search_shop_v12"):
        return _POLICIES[name](params=params, search_shops=search_shops,
                               lookahead=lookahead)
    return _POLICIES[name](params=params)


def _run_one(args) -> dict:
    policy_name, seed, rng_mode, params, search_shops, lookahead = args
    game = BalatroGame(seed=seed, rng_mode=rng_mode)
    policy = _make_policy(policy_name, params, search_shops, lookahead)
    result = rollout(game, policy)
    result["seed"] = seed
    return result


def _ante1_deaths(results: list[dict]) -> int:
    return sum(1 for r in results if not r["won"] and r["ante"] <= 1)


def aggregate(results: list[dict]) -> dict:
    n = len(results)
    wins = sum(1 for r in results if r["won"])
    death = {}
    for r in results:
        bucket = 9 if r["won"] else min(r["ante"], 8)
        death[bucket] = death.get(bucket, 0) + 1
    econ = interest = 0
    c_tarot = c_planet = c_spec = 0
    for r in results:
        st = r.get("stats") or {}
        econ += st.get("econ_source", 0)
        interest += st.get("interest_collected", 0)
        c_tarot += len(st.get("tarots", ()))
        c_planet += len(st.get("planets", ()))
        c_spec += len(st.get("spectrals", ()))
    return {
        "n": n,
        "wins": wins,
        "win_rate": 100.0 * wins / n,
        "ante1_deaths": _ante1_deaths(results),
        "ante1_death_rate": 100.0 * _ante1_deaths(results) / n,
        "death": death,
        "mean_ante": mean(r["ante"] for r in results),
        "mean_steps": mean(r["steps"] for r in results),
        "mean_dollars": mean(r["dollars"] for r in results),
        "mean_econ_source": econ / n,
        "total_econ_source": econ,
        "mean_interest": interest / n,
        "total_interest": interest,
        "mean_tarots": c_tarot / n,
        "mean_planets": c_planet / n,
        "mean_spectrals": c_spec / n,
    }


def summarize(results: list[dict], label: str) -> dict:
    agg = aggregate(results)
    print(f"\n=== {label} ===")
    print(f"  wins {agg['wins']}/{agg['n']} = {agg['win_rate']:.2f}% | "
          f"ante-1 deaths {agg['ante1_deaths']} "
          f"({agg['ante1_death_rate']:.2f}%) | "
          f"mean ante {agg['mean_ante']:.2f} | mean steps {agg['mean_steps']:.0f}")
    print(f"  econ-source ${agg['mean_econ_source']:.1f}/run | "
          f"interest ${agg['mean_interest']:.1f}/run | "
          f"tarots {agg['mean_tarots']:.1f} planets {agg['mean_planets']:.1f} "
          f"spectrals {agg['mean_spectrals']:.1f} | end ${agg['mean_dollars']:.1f}")
    for ante in range(1, 10):
        cnt = agg["death"].get(ante, 0)
        if cnt:
            bar = "#" * int(50 * cnt / agg["n"])
            print(f"  ante {ante}: {cnt:>5} ({100.0 * cnt / agg['n']:5.2f}%) {bar}")
    return agg


def _fmt_eta(seconds: float) -> str:
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=300)
    ap.add_argument("--workers", type=int, default=max(1, os.cpu_count() or 1))
    ap.add_argument("--policies",
                    default="heuristic_v9,heuristic_v10",
                    help="comma-separated policies from: " + ", ".join(_POLICIES))
    ap.add_argument("--rng-mode", default="seed", choices=["seed", "generic"])
    ap.add_argument("--seed-start", type=int, default=0)
    ap.add_argument("--seeds", default=None,
                    help="Seed range like '0-299' or '300-499' (overrides --games and --seed-start)")
    ap.add_argument("--search-shops", type=int, default=999)
    ap.add_argument("--lookahead", action="store_true",
                    help="RESEARCH ONLY (not human-fair): rollout shop search")
    ap.add_argument("--params", default=None,
                    help="JSON dict overridden into the policy params "
                         "(v10 farm knobs: farm_clear_threshold, "
                         "abandon_clear_floor, farm_spare_hands)")
    ap.add_argument("--report", default=None)
    ap.add_argument("--no-report", action="store_true")
    ap.add_argument("--batch-size", type=int, default=25)
    args = ap.parse_args()

    params = json.loads(args.params) if args.params else None
    policies = [p.strip() for p in args.policies.split(",")]
    for p in policies:
        if p not in _POLICIES:
            sys.exit(f"unknown policy {p!r} (choose from {list(_POLICIES)})")

    if args.seeds:
        parts = args.seeds.split("-")
        s_start = int(parts[0])
        s_end = int(parts[1])
        seeds = list(range(s_start, s_end + 1))
        args.games = len(seeds)
        args.seed_start = s_start
    else:
        seeds = list(range(args.seed_start, args.seed_start + args.games))

    if args.report is None:
        args.report = str(VENDOR / "results" / f"bench_{seeds[0]}_{seeds[-1]}_{'_'.join(policies)}.html")

    print(f"bench_agent_v10: {args.games} seeds ({seeds[0]}..{seeds[-1]}), "
          f"rng_mode={args.rng_mode}, workers={args.workers}, "
          f"policies={policies}, search_shops={args.search_shops}, "
          f"lookahead={args.lookahead}, params={params}", flush=True)
    if args.lookahead:
        print("WARNING: --lookahead is RESEARCH ONLY (not human-fair).", flush=True)

    policy_results = []
    sidecar_path = Path(args.report).with_suffix(".json")
    for pname in policies:
        if pname == "search_shop_v10" and sidecar_path.exists():
            try:
                prev_data = json.loads(sidecar_path.read_text(encoding="utf-8"))
                if pname in prev_data and len(prev_data[pname].get("results", [])) == len(seeds):
                    prev_seeds = {r["seed"] for r in prev_data[pname]["results"]}
                    if prev_seeds == set(seeds):
                        results = prev_data[pname]["results"]
                        agg = prev_data[pname]["aggregate"]
                        print(f"  [{pname}] Reused {len(results)} runs from {sidecar_path.name}")
                        policy_results.append((pname, agg, results))
                        continue
            except Exception:
                pass

        t0 = time.perf_counter()
        results: list[dict] = []
        jobs = [(pname, s, args.rng_mode, params, args.search_shops,
                 args.lookahead) for s in seeds]
        batch = args.batch_size or len(seeds)

        def _on_result(r):
            results.append(r)
            done = len(results)
            if done % batch == 0 or done == len(seeds):
                agg = aggregate(results)
                elapsed = time.perf_counter() - t0
                rate = done / elapsed if elapsed else 0.0
                eta = (len(seeds) - done) / rate if rate else 0.0
                print(f"  [{pname}] {done}/{len(seeds)} | {agg['wins']} wins "
                      f"({agg['win_rate']:.2f}%) | ante-1 deaths "
                      f"{agg['ante1_deaths']} | econ ${agg['mean_econ_source']:.1f} "
                      f"| {rate:.1f} games/s | ETA {_fmt_eta(eta)}", flush=True)

        if args.workers > 1 and jobs:
            ctx = mp.get_context("spawn")
            with ctx.Pool(args.workers) as pool:
                for r in pool.imap_unordered(_run_one, jobs, chunksize=1):
                    _on_result(r)
        else:
            for j in jobs:
                _on_result(_run_one(j))

        dt = time.perf_counter() - t0
        agg = summarize(results, f"{pname} ({dt:.0f}s, {len(results) / dt:.1f} games/s)")
        policy_results.append((pname, agg, results))

    if not args.no_report:
        raw = {label: {"aggregate": agg, "results": results}
               for label, agg, results in policy_results}
        path = Path(args.report)
        path.parent.mkdir(parents=True, exist_ok=True)
        sidecar = path.with_suffix(".json")
        sidecar.write_text(json.dumps(raw, indent=1, default=str),
                           encoding="utf-8")
        print(f"\nreport sidecar: {sidecar}")

        try:
            sys.path.insert(0, str(ROOT))
            from tools.generate_paired_report import generate_html_report
            generate_html_report(raw, path, title=f"Optilatro: Paired Benchmark ({seeds[0]}..{seeds[-1]}, N={len(seeds)})")
            print(f"report html: {path}")
        except Exception as e:
            print(f"Warning: HTML report generation failed: {e}")


if __name__ == "__main__":
    main()
