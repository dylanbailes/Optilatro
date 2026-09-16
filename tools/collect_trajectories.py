"""collect_trajectories.py — V13 trajectory collector: states + final outcome.

WHY THIS EXISTS ALONGSIDE THE FORK COLLECTOR
============================================
The paired-fork collector buys one counterfactual number for two rollouts — 1,468
rows per 30 minutes at 12 workers — and it is the only way to attribute an effect
to a single item. But it is a terrible way to learn the *value of a state*: every
run it plays already passes through ~168 decision states (measured: 68 SHOP, 55
SELECTING_HAND, 16 BLIND_SELECT, 15 ROUND_EVAL, 14 BOOSTER_OPEN), and those come
free with the rollout.

At 12 workers a run costs well under a second of wall clock, so trajectories yield
hundreds of labelled states per second against ~0.8 fork rows per second. Both
collectors stay: the fork collector is repurposed as the *active learning*
instrument for the decisions where V is genuinely uncertain, which is what paid-for
counterfactuals are actually for.

WHAT A ROW IS
=============
A state (encoded by `state_value.state_features`), the action the shipped policy
took there, and the OUTCOME OF THE WHOLE RUN — stamped onto every row at the end,
because the outcome is only known then. The target is `value_tables.run_return`
(ante reached + win bonus), so a run that reaches ante 6 instead of 3 carries
signal even though it lost.

FORMAT AND THE ALIGNMENT RULE
=============================
Line 1 is a header carrying the frozen feature layout; every later line is one
state with its vector as a float list aligned to that layout. The layout is
probed from one run BEFORE any worker starts, because the alternative — growing
the layout as keys appear — silently misaligns every row written before the
growth. A key that the probe did not produce is counted and reported rather than
dropped quietly; a nonzero count means the encoding changed underneath the run
and the file should not be trusted.
"""
from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENDOR = ROOT / "vendor" / "balatro-rl"
sys.path.insert(0, str(VENDOR))

from balatro_sim.game import BalatroGame, State              # noqa: E402
from balatro_sim.agent_v11 import SearchShopV11              # noqa: E402
from balatro_sim import state_value as SV                     # noqa: E402
from balatro_sim import value_tables as VT                    # noqa: E402
from balatro_sim import catalogue as CAT                      # noqa: E402

OUT_DIR = ROOT / "results" / "trajectories"
COLLECTOR_VERSION = 1
STATE_KINDS = tuple(s.name for s in State)


def _policy():
    """Shipped-parity policy: the same policy the fork collector and arms use.

    Measured identical per seed to `SearchShopV10()` and to
    `SearchShopV12(v12_oracle=False)`, so a trajectory captured here describes the
    same behaviour the frozen search exhibits.
    """
    return SearchShopV11()


def trajectory(seed: int, every: int = 1, kinds: tuple | None = None,
               max_steps: int = 100_000) -> tuple[list[dict], dict]:
    """Play one run, recording every `every`-th state (all of them by default)."""
    game = BalatroGame(seed=seed, rng_mode="seed")
    policy = _policy()
    rows: list[dict] = []
    steps = 0
    while game.state != State.GAME_OVER and steps < max_steps:
        steps += 1
        if steps % max(1, every) == 0 and (kinds is None or game.state.name in kinds):
            try:
                feats = SV.state_features(game)
                act = policy.decide(game)
            except Exception as exc:  # never lose a run to instrumentation
                rows.append({"step": steps, "phase": game.state.name,
                             "ante": int(getattr(game, "ante", 1) or 1),
                             "blind_idx": int(getattr(game, "blind_idx", 0) or 0),
                             "act": "", "feats": {},
                             "error": type(exc).__name__})
            else:
                rows.append({
                    "step": steps,
                    "phase": game.state.name,
                    "ante": int(getattr(game, "ante", 1) or 1),
                    "blind_idx": int(getattr(game, "blind_idx", 0) or 0),
                    "act": (str(act.get("type", "")) if isinstance(act, dict) else ""),
                    "feats": feats,
                })
        try:
            game.step(policy.decide(game))
        except Exception:
            break
    return rows, {
        "won": bool(game.ante > 8 and game.state == State.GAME_OVER),
        "ante": int(getattr(game, "ante", 1) or 1),
        "steps": steps,
    }


def _worker(args):
    seed, every, kinds = args
    try:
        return seed, *trajectory(seed, every, kinds)
    except Exception as exc:  # a dead seed must not kill the sweep
        return seed, [], {"error": f"{type(exc).__name__}: {exc}"}


def _is_holdout(seed: int, seed_start: int, every: int) -> bool:
    """Seed-keyed split, so an early stop (time budget) cannot corrupt it."""
    e = max(1, every)
    return ((seed - seed_start) % e) == (e - 1)


def probe_layout(seed: int, every: int, kinds: tuple | None) -> tuple[list[str], int]:
    """Freeze the layout from one complete run, then complete it from the spec.

    `SV.layout_keys` unions the probe's observed names with every name the
    catalogue can produce, because a layout built from observations alone is
    incomplete by construction -- pooled names only exist when a pool is
    non-empty, and `st_boss_*` only for the boss the probe happened to face.
    A state whose items differ from the probe's would then fall outside the layout
    and be dropped silently. Returns (layout, states_probed).
    """
    rows, _out = trajectory(seed, every, kinds)
    feats: dict = {}
    for r in rows:
        feats.update(r.get("feats") or {})
    hands = sorted(k.split("hlvl_", 1)[1] for k in feats if k.startswith("hlvl_"))
    return SV.layout_keys(feats, hands), len(rows)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed-start", type=int, default=48000)
    ap.add_argument("--n-seeds", type=int, default=400)
    ap.add_argument("--time-budget-min", type=float, default=25.0)
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--holdout-every", type=int, default=5,
                    help="every Nth seed is holdout, keyed on the seed value")
    ap.add_argument("--every", type=int, default=1,
                    help="record 1 state in N (SELECTING_HAND dominates a run's "
                         "state count; raising this trades data volume for runs)")
    ap.add_argument("--states", type=str, default="",
                    help="comma-separated State names to record (default: all)")
    ap.add_argument("--out-tag", type=str, default="")
    args = ap.parse_args()

    every = max(1, args.every)
    kinds = tuple(k.strip() for k in args.states.split(",") if k.strip()) or None
    if kinds:
        unknown = [k for k in kinds if k not in STATE_KINDS]
        if unknown:
            sys.exit(f"unknown state(s) {unknown}; have {list(STATE_KINDS)}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    tag = f"_{args.out_tag}" if args.out_tag else ""
    seeds = list(range(args.seed_start, args.seed_start + args.n_seeds))

    print(f"trajectories v{COLLECTOR_VERSION} | catalogue {CAT.fingerprint()} | "
          f"seeds {seeds[0]}..{seeds[-1]} ({len(seeds)}) | every={every} "
          f"| states={kinds or 'all'} | workers={args.workers} "
          f"| budget {args.time_budget_min:.0f}m", flush=True)
    t0 = time.time()

    # Probe a seed that is not part of the sweep, so the layout cannot be fitted
    # to the data it will describe.
    layout, n_probe = probe_layout(seeds[-1] + 1, every, kinds)
    if not layout:
        sys.exit("layout probe produced no features -- refusing to write a corpus")
    layout_set = set(layout)
    print(f"layout: {len(layout)} features from a {n_probe}-state probe of seed "
          f"{seeds[-1] + 1}, completed with the catalogue's pool vocabulary "
          f"({time.time()-t0:.0f}s)", flush=True)

    paths = {s: OUT_DIR / f"{s}{tag}.jsonl" for s in ("train", "holdout")}
    handles = {}
    for split, path in paths.items():
        fh = open(path, "w", encoding="utf-8")
        fh.write(json.dumps({
            "collector": COLLECTOR_VERSION,
            "catalogue": CAT.fingerprint(),
            "layout": layout,
            "target": "value_tables.run_return",
            "policy": "search_shop_v11 (== SearchShopV10, measured)",
        }) + "\n")
        handles[split] = fh

    work = [(s, every, kinds) for s in seeds]
    done = n_rows = n_err = n_unknown = 0
    n_won = 0
    try:
        with mp.Pool(args.workers) as pool:
            for seed, rows, out in pool.imap_unordered(_worker, work, chunksize=1):
                if (args.time_budget_min
                        and (time.time() - t0) / 60.0 > args.time_budget_min):
                    print(f"time budget reached after {done}/{len(seeds)} seeds; "
                          f"stopping cleanly (the split is seed-keyed, so the "
                          f"holdout stays valid)", flush=True)
                    break
                if out.get("error"):
                    n_err += 1
                    print(f"[seed {seed}] ERROR {out['error']}", flush=True)
                    continue
                done += 1
                ret = VT.run_return({"ante": out["ante"], "won": out["won"]})
                n_won += int(out["won"])
                split = ("holdout" if _is_holdout(seed, args.seed_start,
                                                  args.holdout_every) else "train")
                fh = handles[split]
                for r in rows:
                    feats = r.get("feats") or {}
                    extra = [k for k in feats if k not in layout_set]
                    n_unknown += len(extra)
                    fh.write(json.dumps({
                        "seed": seed, "step": r["step"], "phase": r["phase"],
                        "ante": r["ante"], "blind_idx": r["blind_idx"],
                        "act": r["act"], "ret": round(ret, 6),
                        "won": int(out["won"]), "ante_final": out["ante"],
                        "v": [round(float(feats.get(k, 0.0)), 5) for k in layout],
                    }) + "\n")
                    n_rows += 1
                if done % 10 == 0:
                    rate = done / max(1e-9, time.time() - t0)
                    print(f"[{done}/{len(seeds)}] states={n_rows} "
                          f"({n_rows/max(1,done):.0f}/run) wins={n_won} err={n_err} "
                          f"{rate:.2f} runs/s "
                          f"ETA {(len(seeds)-done)/max(1e-9,rate)/60:.1f}m", flush=True)
                    fh.flush()
    finally:
        for fh in handles.values():
            fh.close()

    print(f"DONE runs={done} states={n_rows} wins={n_won} errors={n_err} "
          f"unknown_keys={n_unknown} features={len(layout)} "
          f"in {time.time()-t0:.0f}s", flush=True)
    if n_unknown:
        print(f"WARNING: {n_unknown} feature instances were not in the probed "
              f"layout and were DROPPED; the file may be incomplete", flush=True)
    for split, path in paths.items():
        if path.exists() and path.stat().st_size > 0:
            with open(path, encoding="utf-8") as fh:
                n = sum(1 for _ in fh) - 1
            print(f"  {split}: {n} states -> {path}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
