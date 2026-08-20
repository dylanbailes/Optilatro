"""tools/sweep_v10.py — run the agent-v10 §10.3 farm-parameter sweep.

Executes the spec's calibration ladder over the farm knobs
(farm_spare_hands -> farm_clear_threshold -> abandon_clear_floor), then the
2x2 interaction check and a 1000-seed confirm of the overall winner. Each
config is run as a separate `bench_agent_v10.py` subprocess (fresh process
per config -> no V10_PARAMS leakage), and the aggregate is read back from the
JSON sidecar the bench writes.

Selection rule (the §10.3 success gate, encoded deterministically):
  1. Drop any config whose ante-1 deaths EXCEED the heuristic_v9 baseline
     (fewer ante-1 deaths is the #1 outcome and is non-negotiable).
  2. Among survivors, pick the highest win rate; tie-break by mean econ-source
     $, then mean ante.

Output: vendor/balatro-rl/results/sweep_v10.md (+ per-config JSON sidecars in
vendor/balatro-rl/results/sweep_v10/).

Usage:
  .venv/Scripts/python.exe tools/sweep_v10.py [--games 300] [--confirm-games 1000]
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENDOR = ROOT / "vendor" / "balatro-rl"
BENCH = ROOT / "bench" / "bench_agent_v10.py"
OUT_DIR = VENDOR / "results" / "sweep_v10"
OUT_DIR.mkdir(parents=True, exist_ok=True)

PY = sys.executable


# ──────────────────────────────────────────────────────────────────────────
# §10.2 defaults + the sweep grids
# ──────────────────────────────────────────────────────────────────────────
DEFAULT_THRESHOLD = 0.90
DEFAULT_FLOOR = 0.75
DEFAULT_SPARE = 1

SPARE_GRID = [0, 1, 2]
THRESHOLD_GRID = [0.70, 0.80, 0.90, 0.95]
FLOOR_GRID = [0.50, 0.60, 0.70, 0.80]
# tier2 knobs (defaults 0.02 / 0.0). opp is a value-point tie-break bonus
# for opportunistic actions; min_value gates how small a value action is
# worth spending a hand/discard on (typical single-action value ~0.25 vp).
OPP_GRID = [0.0, 0.02, 0.05, 0.10]     # tier2_opp_bonus
MINV_GRID = [0.0, 0.1, 0.25, 0.5]      # tier2_min_value


def _fmt_eta(seconds: float) -> str:
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def run_config(name: str, params: dict | None, games: int) -> dict:
    """Run one config (single policy) via the bench subprocess; return its aggregate."""
    sidecar = OUT_DIR / f"{name}.json"
    cmd = [PY, str(BENCH), "--games", str(games),
           "--policies", "heuristic_v10",
           "--report", str(sidecar),
           "--batch-size", "50"]
    # ^ `--report sidecar.json` makes the bench write the aggregate JSON there.
    if params:
        cmd += ["--params", json.dumps(params)]
    print(f"\n### {name}: params={params} games={games}", flush=True)
    t0 = time.perf_counter()
    proc = subprocess.run(cmd, cwd=str(ROOT), text=True,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    dt = time.perf_counter() - t0
    # Surface the tail of the bench's own progress for a live read.
    lines = proc.stdout.splitlines()
    for line in lines[-6:]:
        print("   ", line, flush=True)
    if proc.returncode != 0 or not sidecar.exists():
        raise RuntimeError(f"{name} failed (rc={proc.returncode}); "
                           f"no sidecar at {sidecar}")
    raw = json.loads(sidecar.read_text(encoding="utf-8"))
    agg = raw["heuristic_v10"]["aggregate"]
    agg["_seconds"] = round(dt)
    agg["_params"] = params or {}
    print(f"    -> win {agg['win_rate']:.2f}% | ante1 {agg['ante1_deaths']} | "
          f"econ ${agg['mean_econ_source']:.1f} | interest "
          f"${agg['mean_interest']:.1f} | mean ante {agg['mean_ante']:.2f} "
          f"({_fmt_eta(dt)})", flush=True)
    return agg


def pick_winner(rows: list[tuple[str, dict]], baseline: dict) -> tuple[str, dict]:
    """Apply the §10.3 gate and return (name, agg) of the winner."""
    eligible = [(n, a) for n, a in rows
                if a["ante1_deaths"] <= baseline["ante1_deaths"]]
    pool = eligible or rows  # if all regress, still report a best (flag it)
    best = max(pool, key=lambda t: (t[1]["win_rate"],
                                    t[1]["mean_econ_source"],
                                    t[1]["mean_ante"]))
    return best


def table(rows: list[tuple[str, dict]], baseline: dict) -> list[str]:
    out = []
    out.append("| config | win % | ante-1 deaths | econ-source $ | interest $ | "
               "mean ante | mean steps |")
    out.append("|---|---|---|---|---|---|---|")
    for name, a in rows:
        gate = "OK " if a["ante1_deaths"] <= baseline["ante1_deaths"] else "REJ"
        out.append(f"| {name} {gate} | {a['win_rate']:.2f} | {a['ante1_deaths']} "
                   f"| {a['mean_econ_source']:.1f} | {a['mean_interest']:.1f} "
                   f"| {a['mean_ante']:.2f} | {a['mean_steps']:.0f} |")
    return out


def load_sidecar(name: str) -> dict:
    """Read a bench aggregate from an existing sidecar (v9 or v10)."""
    path = OUT_DIR / f"{name}.json"
    if not path.exists():
        raise SystemExit(f"missing sidecar {path} — run the full sweep first")
    raw = json.loads(path.read_text(encoding="utf-8"))
    key = "heuristic_v9" if "heuristic_v9" in raw else "heuristic_v10"
    return raw[key]["aggregate"]


def run_v9(games: int, name: str) -> dict:
    """Run (or reuse) the heuristic_v9 baseline at `games`; return its aggregate.

    The cached sidecar is reused only when its recorded game count matches
    (the aggregate stores `n`), so a stale baseline from a different sample
    size is never silently reused."""
    sidecar = OUT_DIR / f"{name}.json"
    if sidecar.exists():
        try:
            raw = json.loads(sidecar.read_text(encoding="utf-8"))
            key = "heuristic_v9" if "heuristic_v9" in raw else "heuristic_v10"
            if raw[key]["aggregate"].get("n") == games:
                return raw[key]["aggregate"]
        except (json.JSONDecodeError, KeyError):
            pass  # corrupt/stale sidecar -> re-run below
        print(f"  (re-running {name}: cached sidecar is not a {games}-game "
              f"baseline)", flush=True)
    subprocess.run([PY, str(BENCH), "--games", str(games),
                    "--policies", "heuristic_v9",
                    "--report", str(sidecar), "--batch-size", "50"],
                   cwd=str(ROOT), text=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    return load_sidecar(name)


def run_tier2_sweep(args) -> None:
    """Phase 1d/1e/2b/3b — the tier2_opp_bonus / tier2_min_value knobs.

    Farm defaults are fixed at the §10.3 winner (0.90/0.75/1). Reuses the
    recorded v9 baselines (baseline_v9.json, confirm_v9.json) and the
    farmoff==v9 byte-for-byte identity for the attribution arm."""
    lines: list[str] = []
    t0 = time.perf_counter()
    baseline = run_v9(args.games, "baseline_v9")

    farm_fixed = {"farm_clear_threshold": DEFAULT_THRESHOLD,
                  "abandon_clear_floor": DEFAULT_FLOOR,
                  "farm_spare_hands": DEFAULT_SPARE}

    # ── Phase 1d: tier2_opp_bonus (min_value 0.0 fixed) ──
    opp_rows = []
    for b in OPP_GRID:
        p = dict(farm_fixed)
        p["tier2_opp_bonus"] = b
        p["tier2_min_value"] = 0.0
        opp_rows.append((f"opp={b:.2f}",
                         run_config(f"opp_{int(b*100)}", p, args.games)))
    opp_name, opp_agg = pick_winner(opp_rows, baseline)
    opp_bonus = opp_agg["_params"]["tier2_opp_bonus"]

    # ── Phase 1e: tier2_min_value (opp_bonus = winner) ──
    minv_rows = []
    for m in MINV_GRID:
        p = dict(farm_fixed)
        p["tier2_opp_bonus"] = opp_bonus
        p["tier2_min_value"] = m
        minv_rows.append((f"minv={m:.2f}",
                          run_config(f"minv_{int(m*100)}", p, args.games)))
    minv_name, minv_agg = pick_winner(minv_rows, baseline)
    min_value = minv_agg["_params"]["tier2_min_value"]

    # ── Phase 2b: opp_bonus x min_value interaction ──
    opp_top2 = sorted(opp_rows,
                      key=lambda t: (t[1]["win_rate"], t[1]["mean_econ_source"]),
                      reverse=True)[:2]
    minv_top2 = sorted(minv_rows,
                       key=lambda t: (t[1]["win_rate"], t[1]["mean_econ_source"]),
                       reverse=True)[:2]
    x2b_rows = []
    for (on, oa), (mn, ma) in [(a, b) for a in opp_top2 for b in minv_top2]:
        p = dict(farm_fixed)
        p["tier2_opp_bonus"] = oa["_params"]["tier2_opp_bonus"]
        p["tier2_min_value"] = ma["_params"]["tier2_min_value"]
        nm = f"x2b_{int(p['tier2_opp_bonus']*100)}_{int(p['tier2_min_value']*100)}"
        x2b_rows.append((nm, run_config(nm, p, args.games)))
    x2b_name, x2b_agg = pick_winner(x2b_rows, baseline)

    # ── Phase 3b: 1000-seed confirm (farmoff == v9 byte-for-byte) ──
    confirm = {}
    if not args.skip_confirm:
        winner_params = x2b_agg["_params"]
        confirm["v9_1000"] = run_v9(args.confirm_games, "confirm_v9")
        confirm["winner_1000"] = run_config("confirm_tier2_winner",
                                            winner_params, args.confirm_games)
        confirm["farmoff_1000"] = confirm["v9_1000"]  # threshold=1.0 == v9

    lines.append("# agent-v10 tier2-knob sweep "
                 "(tier2_opp_bonus / tier2_min_value)")
    lines.append("")
    lines.append(f"Run {time.strftime('%Y-%m-%d %H:%M:%S')} · calibration "
                 f"{args.games} seeds · confirm {args.confirm_games} seeds · "
                 f"farm defaults fixed at the §10.3 winner "
                 f"({DEFAULT_THRESHOLD}/{DEFAULT_FLOOR}/{DEFAULT_SPARE}) · "
                 f"seed-mode, per-seed paired vs `heuristic_v9`.")
    lines.append("")
    lines.append(f"**Baseline (heuristic_v9, {args.games} seeds):** win "
                 f"{baseline['win_rate']:.2f}% · ante-1 deaths "
                 f"{baseline['ante1_deaths']} · econ-source "
                 f"${baseline['mean_econ_source']:.1f} · interest "
                 f"${baseline['mean_interest']:.1f} · mean ante "
                 f"{baseline['mean_ante']:.2f}")
    lines.append("")
    lines.append("Selection rule: drop configs with MORE ante-1 deaths than the "
                 "baseline (non-negotiable); among survivors pick the highest "
                 "win rate (tie-break econ-source $, then mean ante).")
    lines.append("")

    lines.append("## Phase 1d — tier2_opp_bonus (min_value 0.0 fixed)")
    lines += table(opp_rows, baseline)
    lines.append(f"\n**Winner: {opp_name}** (opp_bonus={opp_bonus:.2f})\n")

    lines.append("## Phase 1e — tier2_min_value (opp_bonus fixed)")
    lines += table(minv_rows, baseline)
    lines.append(f"\n**Winner: {minv_name}** (min_value={min_value:.2f})\n")

    lines.append("## Phase 2b — opp_bonus × min_value interaction")
    lines += table(x2b_rows, baseline)
    lines.append(f"\n**Winner: {x2b_name}** (opp_bonus="
                 f"{x2b_agg['_params']['tier2_opp_bonus']:.2f}, min_value="
                 f"{x2b_agg['_params']['tier2_min_value']:.2f})\n")

    if confirm:
        lines.append(f"## Phase 3b — {args.confirm_games}-seed confirm")
        lines.append("")
        lines.append("| arm | win % | ante-1 deaths | econ-source $ | interest $ | "
                     "mean ante |")
        lines.append("|---|---|---|---|---|---|")
        for name, a in confirm.items():
            lines.append(f"| {name} | {a['win_rate']:.2f} | {a['ante1_deaths']} "
                         f"| {a['mean_econ_source']:.1f} | "
                         f"{a['mean_interest']:.1f} | {a['mean_ante']:.2f} |")
        lines.append("")
        lines.append("`farmoff_1000` == `v9_1000` (threshold=1.0 disables farming "
                     "and the survive tier reproduces v9 byte-for-byte), so the "
                     "row doubles as the farming-attribution control.")
        lines.append("")

    final = x2b_agg
    lines.append("## Final winning config")
    lines.append("")
    lines.append("```")
    lines.append(json.dumps(final["_params"], indent=2))
    lines.append("```")
    lines.append("")
    lines.append(f"- win {final['win_rate']:.2f}% vs baseline "
                 f"{baseline['win_rate']:.2f}%")
    lines.append(f"- ante-1 deaths {final['ante1_deaths']} vs baseline "
                 f"{baseline['ante1_deaths']}")
    lines.append(f"- econ-source ${final['mean_econ_source']:.1f}/run vs "
                 f"${baseline['mean_econ_source']:.1f}/run")
    lines.append(f"- interest ${final['mean_interest']:.1f}/run vs "
                 f"${baseline['mean_interest']:.1f}/run")
    lines.append(f"- mean ante {final['mean_ante']:.2f} vs "
                 f"{baseline['mean_ante']:.2f}")
    lines.append("")

    report = VENDOR / "results" / "sweep_v10_tier2.md"
    report.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines), flush=True)
    print(f"\nWrote {report} "
          f"({_fmt_eta(time.perf_counter() - t0)})", flush=True)


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=300)
    ap.add_argument("--confirm-games", type=int, default=1000)
    ap.add_argument("--skip-confirm", action="store_true")
    ap.add_argument("--tier2-only", action="store_true",
                    help="run only the tier2_opp_bonus / tier2_min_value phase "
                         "(farm defaults fixed at the §10.3 winner; reuses the "
                         "recorded v9 baselines)")
    args = ap.parse_args()

    if args.tier2_only:
        run_tier2_sweep(args)
        return


    lines: list[str] = []
    t_total = time.perf_counter()

    # ── Baseline: heuristic_v9 (the frozen control; ignores the v10 knobs) ──
    print("== baseline: heuristic_v9 ==", flush=True)
    base_sidecar = OUT_DIR / "baseline_v9.json"
    subprocess.run([PY, str(BENCH), "--games", str(args.games),
                    "--policies", "heuristic_v9",
                    "--report", str(base_sidecar), "--batch-size", "50"],
                   cwd=str(ROOT), text=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    baseline = json.loads(base_sidecar.read_text(encoding="utf-8"))[
        "heuristic_v9"]["aggregate"]

    # ── Phase 1a: farm_spare_hands (threshold 0.90 / floor 0.75 fixed) ──
    spare_rows = []
    for s in SPARE_GRID:
        p = {"farm_clear_threshold": DEFAULT_THRESHOLD,
             "abandon_clear_floor": DEFAULT_FLOOR,
             "farm_spare_hands": s}
        spare_rows.append((f"spare={s}", run_config(f"spare_{s}", p, args.games)))
    spare_name, spare_agg = pick_winner(spare_rows, baseline)
    spare = spare_agg["_params"]["farm_spare_hands"]

    # ── Phase 1b: farm_clear_threshold (floor = threshold - 0.15; spare fixed) ──
    thr_rows = []
    for t in THRESHOLD_GRID:
        floor = round(t - 0.15, 2)
        p = {"farm_clear_threshold": t, "abandon_clear_floor": floor,
             "farm_spare_hands": spare}
        thr_rows.append((f"thr={t:.2f}",
                         run_config(f"thr_{int(t*100)}", p, args.games)))
    thr_name, thr_agg = pick_winner(thr_rows, baseline)
    threshold = thr_agg["_params"]["farm_clear_threshold"]

    # ── Phase 1c: abandon_clear_floor (threshold + spare fixed) ──
    floor_rows = []
    for f in FLOOR_GRID:
        p = {"farm_clear_threshold": threshold, "abandon_clear_floor": f,
             "farm_spare_hands": spare}
        floor_rows.append((f"floor={f:.2f}",
                           run_config(f"floor_{int(f*100)}", p, args.games)))
    floor_name, floor_agg = pick_winner(floor_rows, baseline)
    floor = floor_agg["_params"]["abandon_clear_floor"]

    # ── Phase 2: 2x2 threshold x floor interaction ──
    thr_top2 = sorted(thr_rows, key=lambda t: (t[1]["win_rate"],
                                               t[1]["mean_econ_source"]),
                      reverse=True)[:2]
    floor_top2 = sorted(floor_rows, key=lambda t: (t[1]["win_rate"],
                                                   t[1]["mean_econ_source"]),
                        reverse=True)[:2]
    x2_rows = []
    for (tn, ta), (fn, fa) in [(a, b) for a in thr_top2 for b in floor_top2]:
        p = {"farm_clear_threshold": ta["_params"]["farm_clear_threshold"],
             "abandon_clear_floor": fa["_params"]["abandon_clear_floor"],
             "farm_spare_hands": spare}
        nm = f"x2_{int(p['farm_clear_threshold']*100)}_{int(p['abandon_clear_floor']*100)}"
        x2_rows.append((nm, run_config(nm, p, args.games)))
    x2_name, x2_agg = pick_winner(x2_rows, baseline)

    # ── Phase 3: 1000-seed confirm of the overall winner vs baseline + farm-off ──
    confirm = {}
    if not args.skip_confirm:
        winner_params = x2_agg["_params"]
        off_params = dict(winner_params)
        off_params["farm_clear_threshold"] = 1.0
        # run_config always runs heuristic_v10; run the v9 baseline manually:
        subprocess.run([PY, str(BENCH), "--games", str(args.confirm_games),
                        "--policies", "heuristic_v9",
                        "--report", str(OUT_DIR / "confirm_v9.json"),
                        "--batch-size", "50"],
                       cwd=str(ROOT), text=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
        confirm["v9_1000"] = json.loads(
            (OUT_DIR / "confirm_v9.json").read_text(encoding="utf-8"))[
                "heuristic_v9"]["aggregate"]
        confirm["winner_1000"] = run_config("confirm_winner", winner_params,
                                            args.confirm_games)
        confirm["farmoff_1000"] = run_config("confirm_farmoff", off_params,
                                             args.confirm_games)

    # ── Report ──
    lines.append("# agent-v10 farm-parameter sweep (§10.3)")
    lines.append("")
    lines.append(f"Run {time.strftime('%Y-%m-%d %H:%M:%S')} · "
                 f"calibration {args.games} seeds · confirm "
                 f"{args.confirm_games} seeds · seed-mode, per-seed paired vs "
                 f"`heuristic_v9`.")
    lines.append("")
    lines.append(f"**Baseline (heuristic_v9):** win {baseline['win_rate']:.2f}% · "
                 f"ante-1 deaths {baseline['ante1_deaths']} · econ-source "
                 f"${baseline['mean_econ_source']:.1f} · interest "
                 f"${baseline['mean_interest']:.1f} · mean ante "
                 f"{baseline['mean_ante']:.2f}")
    lines.append("")
    lines.append("Selection rule: drop configs with MORE ante-1 deaths than the "
                 "baseline (non-negotiable); among survivors pick the highest "
                 "win rate (tie-break econ-source $, then mean ante).")
    lines.append("")

    lines.append("## Phase 1a — farm_spare_hands")
    lines += table(spare_rows, baseline)
    lines.append(f"\n**Winner: {spare_name}** (spare={spare})\n")

    lines.append("## Phase 1b — farm_clear_threshold")
    lines += table(thr_rows, baseline)
    lines.append(f"\n**Winner: {thr_name}** (threshold={threshold:.2f})\n")

    lines.append("## Phase 1c — abandon_clear_floor")
    lines += table(floor_rows, baseline)
    lines.append(f"\n**Winner: {floor_name}** (floor={floor:.2f})\n")

    lines.append("## Phase 2 — threshold × floor interaction")
    lines += table(x2_rows, baseline)
    lines.append(f"\n**Winner: {x2_name}** (threshold="
                 f"{x2_agg['_params']['farm_clear_threshold']:.2f}, floor="
                 f"{x2_agg['_params']['abandon_clear_floor']:.2f})\n")

    if confirm:
        lines.append(f"## Phase 3 — {args.confirm_games}-seed confirm")
        lines.append("")
        lines.append("| arm | win % | ante-1 deaths | econ-source $ | interest $ | "
                     "mean ante |")
        lines.append("|---|---|---|---|---|---|")
        for name, a in confirm.items():
            lines.append(f"| {name} | {a['win_rate']:.2f} | {a['ante1_deaths']} "
                         f"| {a['mean_econ_source']:.1f} | "
                         f"{a['mean_interest']:.1f} | {a['mean_ante']:.2f} |")
        lines.append("")

    final = x2_agg
    lines.append("## Final winning config")
    lines.append("")
    lines.append("```")
    lines.append(json.dumps(final["_params"], indent=2))
    lines.append("```")
    lines.append("")
    lines.append(f"- win {final['win_rate']:.2f}% vs baseline "
                 f"{baseline['win_rate']:.2f}%")
    lines.append(f"- ante-1 deaths {final['ante1_deaths']} vs baseline "
                 f"{baseline['ante1_deaths']}")
    lines.append(f"- econ-source ${final['mean_econ_source']:.1f}/run vs "
                 f"${baseline['mean_econ_source']:.1f}/run")
    lines.append(f"- interest ${final['mean_interest']:.1f}/run vs "
                 f"${baseline['mean_interest']:.1f}/run")
    lines.append(f"- mean ante {final['mean_ante']:.2f} vs "
                 f"{baseline['mean_ante']:.2f}")
    lines.append("")

    report = VENDOR / "results" / "sweep_v10.md"
    report.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines), flush=True)
    print(f"\nWrote {report} "
          f"({_fmt_eta(time.perf_counter() - t_total)})", flush=True)


if __name__ == "__main__":
    main()
