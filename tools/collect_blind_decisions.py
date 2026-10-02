from __future__ import annotations

import argparse
import hashlib
import json
import math
import multiprocessing
import os
import signal
import sys
from concurrent.futures import ProcessPoolExecutor, wait, FIRST_COMPLETED
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "vendor" / "balatro-rl"))

from balatro_sim import blind_dataset as DS
from balatro_sim.game import BalatroGame, State


DEFAULT_DECISIONS_PER_ANTE = {"1": None, "2": None, "3": 2, "4": 2, "5": 2, "6": 1, "7": 1, "8": 1}
BALANCED_STRATA = {"1": 1, "2": 2, "3": 3, "4": 3, "5": 3, "6": 3, "7": 3, "8": 3}


def is_trivial_root(game: BalatroGame) -> bool:
    if game.state != State.SELECTING_HAND:
        return False
    target = game.current_blind.chips_target
    needed = target - game.chips_scored
    if needed <= 0:
        return True
    if game.hands_left > 2:
        plays = DS.V9.scored_plays(game, topk=1)
        if plays and plays[0][0] >= 2.0 * needed:
            return True
    return False


def is_trivial_row(row: dict) -> bool:
    arms = row.get("arms", [])
    if not arms:
        return False
    all_trials = [t for a in arms for t in a.get("trials", []) if not t.get("censored", False)]
    if not all_trials:
        return False
    if all(t.get("clear") is True and t.get("steps") == 1 and t.get("score", 0) >= 2.0 * t.get("target", 1) for t in all_trials):
        return True
    if all(t.get("clear") is False and t.get("score", 0) < 0.2 * t.get("target", 1) for t in all_trials):
        return True
    return False


def parse_decisions_per_ante(value):
    if isinstance(value, str):
        text = value.strip()
        if text.lower() == "balanced":
            return dict(BALANCED_STRATA)
        if text.startswith("{") or text.startswith("["):
            value = json.loads(text)
        else:
            value = {}
            for part in text.split(","):
                key, quota = (token.strip() for token in part.split(":"))
                if key in value:
                    raise ValueError("duplicate ante range")
                value[key] = None if quota in ("all", "null") else int(quota)
    if not isinstance(value, dict):
        raise ValueError("decisions-per-ante must be a JSON object")
    result = {}
    for key, quota in value.items():
        if quota == "all":
            quota = None
        if quota is not None and (type(quota) is not int or quota < 0):
            raise ValueError("ante quotas must be nonnegative integers, null or all")
        bounds = str(key).split("-")
        if len(bounds) not in (1, 2):
            raise ValueError("invalid ante range")
        lo, hi = int(bounds[0]), int(bounds[-1])
        if not 1 <= lo <= hi <= 8:
            raise ValueError("ante range must be within 1..8")
        for ante in range(lo, hi + 1):
            if str(ante) in result:
                raise ValueError("overlapping ante ranges")
            result[str(ante)] = quota
    return result


def coverage_selected(seed, decision_id, fraction):
    if not math.isfinite(fraction) or not 0 <= fraction <= 1:
        raise ValueError("coverage-fraction must be within 0..1")
    value = int.from_bytes(hashlib.sha256(f"v14:coverage:{seed}:{decision_id}".encode()).digest()[:8], "big")
    return value < fraction * (1 << 64)


def validate_schedule(decision_offset, decision_stride):
    if type(decision_offset) is not int or decision_offset < 0:
        raise ValueError("decision-offset must be an integer >= 0")
    if type(decision_stride) is not int or decision_stride < 1:
        raise ValueError("decision-stride must be an integer >= 1")


def decision_diagnostics(rows):
    visits = Counter()
    informative = 0
    for row in rows:
        visits[str(row.get("visit_index", "unknown"))] += 1
        means = []
        for arm in row["arms"]:
            trials = arm["trials"]
            if not trials or any(t.get("censored", False) or type(t.get("clear")) is not bool for t in trials):
                break
            means.append(sum(t["clear"] for t in trials) / len(trials))
        else:
            informative += int(len(means) >= 2 and max(means) > min(means))
    return {"decision_visit_counts": dict(visits), "informative_decisions": informative}


def committed_diagnostics(writer):
    splits = {name: {"seeds": 0, "decisions": 0, "informative_seeds": 0, "informative_decisions": 0}
              for name in ("train", "validation", "test")}
    visits = Counter()
    missing = {marker["seed"]: [] for marker in writer.summaries
               if not {"decision_visit_counts", "informative_decisions"} <= marker["summary"].keys()}
    if missing:
        for row in DS.read_dataset(writer.path):
            if row["seed"] in missing:
                missing[row["seed"]].append(row)
    for marker in writer.summaries:
        summary = decision_diagnostics(missing[marker["seed"]]) if marker["seed"] in missing else marker["summary"]
        counts = splits[DS.seed_split(marker["seed"])]
        counts["seeds"] += 1
        counts["decisions"] += marker["rows"]
        counts["informative_decisions"] += summary["informative_decisions"]
        counts["informative_seeds"] += int(summary["informative_decisions"] > 0)
        visits.update(summary["decision_visit_counts"])
    return {"split_counts": splits, "decision_visit_counts": dict(visits),
            "diagnostics_scope": "all committed seeds; raw complete primary-arm mean clear differences only; posthoc, never selection"}


def seed_manifest(args, completed=()):
    counts = Counter()
    selected = []
    for seed in range(args.seed_start, args.seed_start + args.n_seeds):
        split = DS.seed_split(seed)
        counts[split] += 1
        if args.collect_split == "all" or split == args.collect_split:
            selected.append(seed)
    pending = [seed for seed in selected if seed not in completed]
    return {"collect_split": args.collect_split,
            "requested_range": {"start": args.seed_start, "stop": args.seed_start + args.n_seeds, "count": args.n_seeds},
            "range_split_counts": {name: counts[name] for name in ("train", "validation", "test")},
            "selected_seeds": len(selected), "planned_seed_ids": selected,
            "pending_selected_seeds": len(pending), "pending_seed_ids": pending}


def collect_seed(seed, samples=10, max_decisions=10, max_steps=100, *, extended=False,
                 terminal_every=0, deadline=None, coupling_probe=False, policy_params=None,
                 max_trajectory_steps=4000, decisions_per_ante=None, coverage_fraction=0.0,
                 decision_offset=0, decision_stride=1, filter_trivial=False):
    DS.check_budget(deadline)
    if type(samples) is not int or samples < 2:
        raise ValueError("samples must be an integer >= 2")
    validate_schedule(decision_offset, decision_stride)
    coverage_selected(seed, 0, coverage_fraction)
    strata = parse_decisions_per_ante(DEFAULT_DECISIONS_PER_ANTE if decisions_per_ante is None else decisions_per_ante)
    rows, counters, visits, scheduled = [], Counter(), Counter(), Counter()
    with DS.policy_scope(policy_params):
        game = BalatroGame(seed=seed, rng_mode="seed")
        policy = DS.GuardedH10()
        stop = "trajectory_cap"
        for step in range(max_trajectory_steps):
            DS.check_budget(deadline)
            if game.state == State.GAME_OVER or DS._exact_win(game):
                stop = "win" if DS._exact_win(game) else "death"
                break
            if DS.hidden_observation(game):
                counters["excluded:hidden_root"] += 1
                stop = "hidden_trajectory"
                break
            eligible = False
            if game.state == State.SELECTING_HAND:
                key = (game.ante, game.blind_idx)
                quota = strata.get(str(game.ante), 0)
                visit_index = visits[key]
                visits[key] += 1
                counters["visits"] += 1
                if filter_trivial and is_trivial_root(game):
                    counters["skipped:trivial"] += 1
                elif len(rows) >= max_decisions:
                    counters["skipped:cap"] += 1
                elif visit_index < decision_offset or (visit_index - decision_offset) % decision_stride:
                    counters["skipped:schedule"] += 1
                elif quota is not None and scheduled[key] >= quota:
                    counters["skipped:stratum"] += 1
                else:
                    eligible = True
                    scheduled_slot = scheduled[key]
                    scheduled[key] += 1
                    counters["scheduled"] += 1
            if not eligible:
                game.step(policy.decide(game))
                continue
            trial_seeds = [f"v14:{seed}:{step}:{k}" for k in range(samples)]
            try:
                row = DS.trajectory_step(
                    game, policy, seed, step, trial_seeds, counters=counters, max_steps=max_steps,
                    terminal=bool(terminal_every and len(rows) % terminal_every == 0),
                    extended=bool(extended or coverage_selected(seed, step, coverage_fraction)),
                    deadline=deadline, coupling_probe=coupling_probe,
                    policy_params=policy_params,
                )
                if row is not None:
                    if filter_trivial and is_trivial_row(row):
                        counters["skipped:trivial_post"] += 1
                        scheduled[key] -= 1
                    else:
                        row["visit_index"] = visit_index
                        row["sampling"] = {"decision_offset": decision_offset, "decision_stride": decision_stride,
                                           "blind_quota": quota, "scheduled_slot": scheduled_slot}
                        rows.append(row)
            except DS.BudgetExceeded:
                raise
            except DS.HiddenObservation:
                counters["censored:hidden_trajectory"] += 1
                stop = "hidden_trajectory"
                break
            except Exception as exc:
                counters["error:trajectory:" + type(exc).__name__] += 1
                stop = "trajectory_error"
                break
        DS.check_budget(deadline)
        return rows, {"stop_reason": stop, "counters": dict(counters), "ante": game.ante,
                      "ante_decisions": dict(Counter(str(row["ante"]) for row in rows)),
                      **decision_diagnostics(rows),
                      "won": True if stop == "win" else False if stop == "death" else None,
                      "censored": stop not in ("win", "death")}


def initialize_worker():
    signal.signal(signal.SIGINT, signal.SIG_IGN)


def seed_worker(task):
    seed, options = task
    options = dict(options)
    if "max_decisions_per_seed" in options:
        options["max_decisions"] = options.pop("max_decisions_per_seed")
    start = time.monotonic()
    try:
        rows, summary = collect_seed(seed, **options)
    except DS.BudgetExceeded:
        return None
    return {"rows": rows, "summary": summary, "elapsed_seconds": time.monotonic() - start,
            "worker_id": os.getpid()}


def parser():
    result = argparse.ArgumentParser(description="V14 serial offline in-blind collector; no seed freshness or CRN assumption.")
    result.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 1) - 1))
    result.add_argument("--decisions-per-ante", type=parse_decisions_per_ante, default=DEFAULT_DECISIONS_PER_ANTE)
    result.add_argument("--coverage-fraction", type=float, default=0.0)
    result.add_argument("--collect-split", choices=("all", "train", "validation", "test"), default="all",
                        help="schedule only seeds whose existing DS.seed_split bucket matches; selects a "
                             "different decision distribution, not an unbiased all-state sample and no "
                             "guaranteed informativeness gain; does not relabel seeds or change split hashing")
    result.add_argument("--decision-offset", type=int, default=0,
                        help="0-based in-blind visit index a blind must reach before slots become schedulable; "
                             "with --decision-stride this targets a different decision distribution (e.g. later "
                             "in-blind states), not an unbiased all-state sample and no guaranteed informativeness gain")
    result.add_argument("--decision-stride", type=int, default=1,
                        help="take every Nth eligible visit after the offset (1 = every visit); see --decision-offset")
    result.add_argument("--dry-run", action="store_true",
                        help="print the seed manifest and planned schedule without running games or creating output")
    result.add_argument("--seed-start", type=int, required=True)
    result.add_argument("--n-seeds", type=int, default=1)
    result.add_argument("--samples", type=int, default=10)
    result.add_argument("--max-decisions-per-seed", type=int, default=10)
    result.add_argument("--max-steps", type=int, default=100, help="per trial, includes forced action and optional terminal continuation")
    result.add_argument("--out", type=Path, required=True)
    result.add_argument("--time-budget-seconds", type=float, default=60)
    result.add_argument("--resume", action="store_true")
    result.add_argument("--extended", action="store_true", help="superset pool, same K; noisy top1/top3 coverage/regret")
    result.add_argument("--terminal-every", type=int, default=0, help="anchor auxiliary every N collected decisions; 0 disables")
    result.add_argument("--coupling-probe", action="store_true", help="also run and retain independently seeded arms; report correlation and difference-variance ratio")
    result.add_argument("--filter-trivial", action="store_true", help="skip trivial blowout decisions (e.g. hand 1 clears >= 2x target with > 2 hands left) to sample informative decision states")
    result.add_argument("--max-trajectory-steps", type=int, default=4000)
    return result


def main(argv=None):
    ap = parser()
    args = ap.parse_args(argv)
    for name in ("n_seeds", "samples", "max_decisions_per_seed", "max_steps", "max_trajectory_steps", "time_budget_seconds"):
        if getattr(args, name) <= 0:
            ap.error(name + " must be positive")
    if not math.isfinite(args.time_budget_seconds):
        ap.error("time_budget_seconds must be finite")
    if args.workers <= 0:
        ap.error("workers must be positive")
    if args.samples < 2:
        ap.error("samples must be >= 2 for disjoint selection/evaluation halves")
    if args.terminal_every < 0:
        ap.error("terminal_every must be nonnegative")
    try:
        validate_schedule(args.decision_offset, args.decision_stride)
    except ValueError as exc:
        ap.error(str(exc))
    manifest = seed_manifest(args)
    if not args.dry_run and not manifest["selected_seeds"]:
        ap.error("no eligible seeds in requested range for collect-split=" + args.collect_split)
    workers = args.workers
    parallel = workers > 1
    config = {name: value for name, value in vars(args).items()
              if name not in ("out", "resume", "dry_run", "time_budget_seconds", "workers")}
    config["execution"] = "seed_isolated"
    config["budget_policy"] = "check between steps/trials; discard unfinished seed; wall budget may overrun one policy call"
    if args.dry_run:
        completed = set()
        if args.resume and args.out.exists():
            try:
                reader = DS.DatasetWriter.__new__(DS.DatasetWriter)
                reader.path = args.out
                reader.metadata = json.loads(DS.action_key(DS.metadata(config)))
                reader.completed = set()
                reader.summaries = []
                reader._resume(recover=False)
                completed = reader.completed
            except (ValueError, OSError) as exc:
                ap.error(str(exc))
        manifest = seed_manifest(args, completed)
        print(json.dumps({"type": "dry_run_report", **manifest,
                          "new_seeds": 0, "new_decisions": 0, "new_trials": 0,
                          "complete_seeds": sorted(completed),
                          "planned_schedule": {"decision_offset": args.decision_offset,
                                               "decision_stride": args.decision_stride,
                                               "decisions_per_ante": args.decisions_per_ante,
                                               "max_decisions_per_seed": args.max_decisions_per_seed,
                                               "note": "quota limits scheduled eligible slots, not raw visits"}}), flush=True)
        return 0
    try:
        writer = DS.DatasetWriter(args.out, DS.metadata(config), resume=args.resume)
    except (ValueError, OSError) as exc:
        ap.error(str(exc))
    start = time.monotonic()
    deadline = start + args.time_budget_seconds
    new_rows = new_trials = new_seeds = discarded_seeds = 0
    coverage, coupling = [], []
    counters = Counter()
    interrupted = False
    budget_exhausted = False
    per_worker = Counter()
    ante_totals = Counter()
    pending = {}
    seed_cycle = (seed for seed in manifest["planned_seed_ids"] if seed not in writer.completed)
    options = {name: value for name, value in vars(args).items() if name in (
        "samples", "max_decisions_per_seed", "max_steps", "extended", "terminal_every",
        "coupling_probe", "max_trajectory_steps", "decisions_per_ante", "coverage_fraction",
        "decision_offset", "decision_stride", "filter_trivial")}
    options["deadline"] = deadline
    submitted = set()
    if parallel:
        context = multiprocessing.get_context("spawn")
        executor = ProcessPoolExecutor(max_workers=workers, mp_context=context,
                                       initializer=initialize_worker)
    else:
        executor = None
    try:
        if parallel:
            for _ in range(min(workers, args.n_seeds)):
                seed = next(seed_cycle, None)
                if seed is None:
                    break
                DS.check_budget(deadline)
                pending[executor.submit(seed_worker, (seed, options))] = seed
                submitted.add(seed)
            while pending:
                DS.check_budget(deadline)
                done, _ = wait(pending, timeout=max(0.0, deadline - time.monotonic()),
                               return_when=FIRST_COMPLETED)
                if not done:
                    raise DS.BudgetExceeded("time_budget")
                for future in done:
                    seed = pending.pop(future)
                    result = future.result()
                    if result is None:
                        raise DS.BudgetExceeded("time_budget")
                    DS.check_budget(deadline)
                    writer.write_seed(seed, result["rows"], result["summary"])
                    per_worker[format(result["worker_id"], "x")] += 1
                    counters.update(result["summary"]["counters"])
                    ante_totals.update(result["summary"].get("ante_decisions", {}))
                    new_seeds += 1
                    new_rows += len(result["rows"])
                    new_trials += sum(len(a["trials"]) for row in result["rows"] for a in row["arms"])
                    for row in result["rows"]:
                        if "coverage" in row:
                            coverage.append({"seed": seed, "decision_id": row["decision_id"], **row["coverage"]})
                        if "coupling" in row:
                            coupling.append({"seed": seed, "decision_id": row["decision_id"], **row["coupling"]})
                    print(json.dumps({"seed_complete": seed, "rows": len(result["rows"]),
                                      "stop": result["summary"]["stop_reason"]}), flush=True)
                    next_seed = next(seed_cycle, None)
                    if next_seed is None:
                        continue
                    DS.check_budget(deadline)
                    pending[executor.submit(seed_worker, (next_seed, options))] = next_seed
                    submitted.add(next_seed)
        else:
            for seed in seed_cycle:
                DS.check_budget(deadline)
                submitted.add(seed)
                result = seed_worker((seed, options))
                if result is None:
                    raise DS.BudgetExceeded("time_budget")
                DS.check_budget(deadline)
                writer.write_seed(seed, result["rows"], result["summary"])
                counters.update(result["summary"]["counters"])
                ante_totals.update(result["summary"].get("ante_decisions", {}))
                new_seeds += 1
                new_rows += len(result["rows"])
                new_trials += sum(len(a["trials"]) for row in result["rows"] for a in row["arms"])
                for row in result["rows"]:
                    if "coverage" in row:
                        coverage.append({"seed": seed, "decision_id": row["decision_id"], **row["coverage"]})
                    if "coupling" in row:
                        coupling.append({"seed": seed, "decision_id": row["decision_id"], **row["coupling"]})
                print(json.dumps({"seed_complete": seed, "rows": len(result["rows"]),
                                  "stop": result["summary"]["stop_reason"]}), flush=True)
    except DS.BudgetExceeded:
        budget_exhausted = True
    except KeyboardInterrupt:
        interrupted = True
    finally:
        if executor is not None:
            for future in pending:
                future.cancel()
            while True:
                try:
                    executor.shutdown(wait=True, cancel_futures=True)
                    break
                except KeyboardInterrupt:
                    interrupted = True
    uncommitted = len(submitted - writer.completed)
    discarded_seeds = uncommitted if budget_exhausted else 0
    elapsed = time.monotonic() - start
    report = {
        "type": "collection_report", "version": DS.VERSION,
        **seed_manifest(args, writer.completed), **committed_diagnostics(writer),
        "evaluation_protocol": DS.SPLIT_PROTOCOL, "selection_rule": DS.SELECTION_RULE,
        "execution": "parallel" if parallel else "serial",
        "workers": workers, "per_worker": dict(per_worker),
        "interrupted": interrupted,
        "budget_exhausted": budget_exhausted,
        "submitted_seeds": len(submitted),
        "discarded_budget_seeds": discarded_seeds,
        "complete_seeds": sorted(writer.completed),
        "elapsed_seconds": elapsed, "new_seeds": new_seeds,
        "new_decisions": new_rows, "new_trials": new_trials,
        "decisions_per_second": new_rows / elapsed if elapsed else None,
        "trials_per_second": new_trials / elapsed if elapsed else None,
        "throughput_scope": "committed primary trials per invocation wall time; probe work included in time, not numerator",
        "ante_decisions": dict(ante_totals),
        "counters": dict(counters), "coverage": coverage, "coupling": coupling,
        "freshness": "not audited", "scientific_gate": "INCONCLUSIVE",
        "limitations": DS.INTERFACE,
    }
    print(json.dumps(report, allow_nan=False), flush=True)
    return 130 if interrupted else 0


if __name__ == "__main__":
    raise SystemExit(main())
