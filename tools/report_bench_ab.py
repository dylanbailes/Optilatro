"""tools/report_bench_ab.py — organize bench telemetry into a self-contained
results folder: raw per-run data, per-arm aggregates (with 95% Wilson CIs),
paired seed-level comparisons, and a human-readable README for deciding the
next experiment.

Each arm is a policy subdir written by bench/bench_v9.py --telemetry-dir
(e.g. results/<tel>/<policy>/run_<seed>.json). The tool:

  - copies every run_<seed>.json into <out>/raw/<slug>/ (raw data),
  - aggregates each arm (win rate + CI, mean/median ante, death-by-ante,
    survival-by-ante, dollars/spent, best scores, rerolls/packs, usage tops,
    end-of-run joker composition: xMult/econ/tarot-gen shares, death blind
    kinds),
  - pairs arms seed-by-seed (win flips, mean-ante deltas, survival),
  - writes <out>/stats/{aggregates,paired}.json (machine-readable) and
    <out>/README.md (human-readable), with auto-derived observations.

Usage (from the repo root):
  python tools/report_bench_ab.py --out vendor/balatro-rl/results/bench_<date>_<name> \
      --arm "heuristic_v9 (human-fair)" \
            vendor/balatro-rl/results/hf_ab_tel/heuristic_v9 \
            "python vendor/balatro-rl/bench/bench_v9.py --games 300 --policies heuristic_v9 ..." \
      --arm "search_shop_v9 --lookahead (oracle)" \
            vendor/balatro-rl/results/lookahead_tel/search_shop_v9 \
            "python vendor/balatro-rl/bench/bench_v9.py --games 300 --policies search_shop_v9 --lookahead ..." \
      --note "free-text context line (repeatable)"

Pair bench/bench_v9.py --resume --report runs first so <out>/reports/ holds
the per-arm HTML reports (+ JSON sidecars); this tool fills in the rest.
"""
from __future__ import annotations

import argparse
import datetime
import json
import math
import statistics
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENDOR = ROOT / "vendor" / "balatro-rl"
sys.path.insert(0, str(VENDOR))

from balatro_sim.agent_v9 import ECONOMY_JOKERS, TAROTGEN_JOKERS, XMULT_JOKERS
from balatro_sim.consumables import PLANET_NAME, SPECTRAL_NAME, TAROT_NAME
from balatro_sim.shop import JOKER_CATALOGUE

# ── name maps ───────────────────────────────────────────────────────────────

def _key_name(kind: str, key: str) -> str:
    """Human-readable name for a tracked key (fall back to the raw key)."""
    if kind == "joker":
        return JOKER_CATALOGUE.get(key, {}).get("name", key)
    return {"tarot": TAROT_NAME, "planet": PLANET_NAME,
            "spectral": SPECTRAL_NAME}.get(kind, {}).get(key, key)


# ── stats helpers ───────────────────────────────────────────────────────────

def wilson_ci(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% Wilson score interval for a proportion k/n."""
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    denom = 1.0 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def _top(counter: Counter, k: int = 8) -> list[list]:
    """[[name, count], ...] most common entries, human-readable."""
    return [[name, cnt] for name, cnt in counter.most_common(k)]


# ── per-arm aggregation ─────────────────────────────────────────────────────

def load_runs(tel_dir: Path) -> list[dict]:
    runs = []
    for f in sorted(tel_dir.glob("run_*.json")):
        try:
            runs.append(json.loads(f.read_text(encoding="utf-8")))
        except Exception as e:
            print(f"  ! skip {f}: {e}")
    return runs


def aggregate(runs: list[dict], label: str, slug: str, source: str) -> dict:
    n = len(runs)
    wins = sum(1 for r in runs if r["won"])
    lo, hi = wilson_ci(wins, n)
    death = Counter()
    survival = Counter()
    death_kinds = Counter()
    for r in runs:
        b = 9 if r["won"] else min(r["ante"], 8)
        death[b] += 1
        for k in range(1, 10):
            if r["won"] or r["ante"] >= k:
                survival[k] += 1
        if not r["won"]:
            # death_kind is the blind KIND (Small/Big/Boss) — the boss key
            # itself is not captured by rollout.outcome().
            death_kinds[r.get("death_kind", "")] += 1
    c_tarot, c_planet, c_spec, c_joker, c_end = (Counter(), Counter(),
                                                 Counter(), Counter(), Counter())
    spent = rerolls = packs = truncated = 0
    scores = []
    n_xmult = n_econ = n_togen = 0
    for r in runs:
        st = r.get("stats") or {}
        c_tarot.update(st.get("tarots", ()))
        c_planet.update(st.get("planets", ()))
        c_spec.update(st.get("spectrals", ()))
        c_joker.update(st.get("jokers_bought", ()))
        spent += st.get("money_spent", 0)
        scores.append(st.get("best_score", 0))
        rerolls += st.get("rerolls", 0)
        packs += st.get("packs_bought", 0)
        truncated += bool(r.get("truncated"))
        c_end.update(r.get("jokers", ()))
        jk = set(r.get("jokers", ()))
        n_xmult += bool(jk & XMULT_JOKERS)
        n_econ += bool(jk & ECONOMY_JOKERS)
        n_togen += bool(jk & TAROTGEN_JOKERS)
    n_z = max(1, n)
    return {
        "label": label,
        "slug": slug,
        "source": source,
        "n": n,
        "wins": wins,
        "win_rate": 100.0 * wins / n_z,
        "ci95": [100.0 * lo, 100.0 * hi],
        "mean_ante": statistics.mean(r["ante"] for r in runs) if runs else 0.0,
        "median_ante": statistics.median(r["ante"] for r in runs) if runs else 0,
        "mean_steps": statistics.mean(r["steps"] for r in runs) if runs else 0.0,
        "truncated": truncated,
        "death": {str(k): death.get(k, 0) for k in range(1, 10)},
        "death_pct": {str(k): 100.0 * death.get(k, 0) / n_z for k in range(1, 10)},
        "survival": {str(k): survival.get(k, 0) for k in range(1, 10)},
        "survival_pct": {str(k): 100.0 * survival.get(k, 0) / n_z
                         for k in range(1, 10)},
        "death_blind_kind": [[k or "(other)", c]
                             for k, c in death_kinds.most_common(8)],
        "mean_dollars": statistics.mean(r["dollars"] for r in runs) if runs else 0.0,
        "mean_spent": spent / n_z,
        "max_score": max(scores, default=0),
        "mean_score": statistics.mean(scores) if scores else 0.0,
        "mean_rerolls": rerolls / n_z,
        "mean_packs": packs / n_z,
        "tarots": _top(c_tarot),
        "planets": _top(c_planet),
        "spectrals": _top(c_spec),
        "jokers_bought": _top(c_joker),
        "end_jokers": _top(c_end),
        "end_with_xmult_pct": 100.0 * n_xmult / n_z,
        "end_with_econ_pct": 100.0 * n_econ / n_z,
        "end_with_togen_pct": 100.0 * n_togen / n_z,
    }


# ── paired (per-seed) comparisons ───────────────────────────────────────────

def paired(a: dict, b: dict, seed_a: list, seed_b: list) -> dict:
    """Seed-by-seed comparison of two arms (shared seeds only)."""
    by_a = {r["seed"]: r for r in seed_a}
    by_b = {r["seed"]: r for r in seed_b}
    seeds = sorted(set(by_a) & set(by_b))
    if not seeds:
        return {}
    a_w = b_w = both_w = both_l = a_only = b_only = 0
    ante_deltas = []
    for s in seeds:
        ra, rb = by_a[s], by_b[s]
        wa, wb = bool(ra["won"]), bool(rb["won"])
        a_w += wa
        b_w += wb
        both_w += wa and wb
        both_l += (not wa) and (not wb)
        a_only += wa and not wb
        b_only += wb and not wa
        ante_deltas.append(rb["ante"] - ra["ante"])
    return {
        "a": a["label"],
        "b": b["label"],
        "shared_seeds": len(seeds),
        "wins_a": a_w,
        "wins_b": b_w,
        "both_win": both_w,
        "both_loss": both_l,
        "a_only_win": a_only,
        "b_only_win": b_only,
        "win_rate_diff_pp": 100.0 * (b_w - a_w) / len(seeds),
        "mean_ante_diff_b_minus_a": statistics.mean(ante_deltas),
        "discordant": a_only + b_only,
    }


# ── human-readable output ───────────────────────────────────────────────────

def _bars(counts: dict) -> str:
    mx = max(counts.values())
    out = []
    for k in sorted(counts, key=int):
        out.append(f"  ante {k}: {counts[k]:>4} "
                   f"({100.0 * counts[k] / sum(counts.values()):5.2f}%) "
                   f"{'#' * int(50 * counts[k] / mx)}")
    return "\n".join(out)


def build_readme(aggs: list[dict], pairs: list[dict], notes: list[str],
                 seed_bank: str) -> str:
    L = []
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    L.append(f"# Bench A/B results\n")
    L.append(f"\n- seed bank: **{seed_bank}** · arms: {len(aggs)} · "
             f"generated: {now}\n")

    L.append("\n## Summary\n")
    L.append("\n| arm | wins | win % (95% CI) | mean ante | median ante | "
             "mean steps | ante-1 deaths | end w/ xMult | end w/ econ | mean $ |")
    L.append("\n|---|---|---|---|---|---|---|---|---|---|")
    for a in aggs:
        L.append(f"\n| {a['label']} | {a['wins']}/{a['n']} | "
                 f"{a['win_rate']:.2f}% "
                 f"[{a['ci95'][0]:.2f}, {a['ci95'][1]:.2f}] | "
                 f"{a['mean_ante']:.2f} | {a['median_ante']:.0f} | "
                 f"{a['mean_steps']:.0f} | {a['death']['1']} "
                 f"({a['death_pct']['1']:.1f}%) | "
                 f"{a['end_with_xmult_pct']:.0f}% | "
                 f"{a['end_with_econ_pct']:.0f}% | {a['mean_dollars']:.1f} |")

    L.append("\n\n## Death by ante\n")
    for a in aggs:
        L.append(f"\n### {a['label']} — {a['wins']}/{a['n']} wins "
                 f"({a['win_rate']:.2f}%)\n")
        L.append(_bars({int(k): v for k, v in a["death"].items()}))
        L.append("\n")

    L.append("\n\n## Survival by ante (runs reaching at least ante N)\n")
    L.append("\n| arm | a1 | a2 | a3 | a4 | a5 | a6 | a7 | a8 | win |")
    L.append("\n|---|---|---|---|---|---|---|---|---|---|")
    for a in aggs:
        surv = [a["survival"][str(k)] for k in range(1, 9)] + [a["wins"]]
        L.append("\n| " + a["label"] + " | " + " | ".join(str(v) for v in surv)
                 + " |")

    L.append("\n\n## Paired comparisons (per-seed, shared bank)\n")
    for p in pairs:
        L.append(f"\n### {p['a']} → {p['b']}\n")
        L.append(f"- shared seeds: {p['shared_seeds']} · wins {p['a']}: "
                 f"{p['wins_a']} → {p['b']}: {p['wins_b']} "
                 f"(Δ {p['win_rate_diff_pp']:+.2f}pp)\n")
        L.append(f"- concordant: both-win {p['both_win']} / both-loss "
                 f"{p['both_loss']} · discordant: {p['a']}-only "
                 f"{p['a_only_win']} / {p['b']}-only {p['b_only_win']}\n")
        L.append(f"- mean ante Δ ({p['b']} − {p['a']}): "
                 f"{p['mean_ante_diff_b_minus_a']:+.2f}\n")

    L.append("\n\n## End-of-run joker composition\n")
    L.append("\n| arm | xMult % | econ % | tarot-gen % | top end jokers |")
    L.append("\n|---|---|---|---|---|")
    for a in aggs:
        tops = ", ".join(f"{n} x{c}" for n, c in a["end_jokers"][:4])
        L.append(f"\n| {a['label']} | {a['end_with_xmult_pct']:.0f}% | "
                 f"{a['end_with_econ_pct']:.0f}% | "
                 f"{a['end_with_togen_pct']:.0f}% | {tops} |")

    L.append("\n\n## Usage stats\n")
    for a in aggs:
        L.append(f"\n### {a['label']}\n")
        L.append(f"- money: mean $ {a['mean_dollars']:.1f} · spent "
                 f"${a['mean_spent']:.1f} · rerolls {a['mean_rerolls']:.1f} · "
                 f"packs {a['mean_packs']:.1f}\n")
        L.append(f"- score: max {a['max_score']:,} · mean "
                 f"{a['mean_score']:,.0f}\n")
        for kind, rows in (("tarots", a["tarots"]), ("planets", a["planets"]),
                           ("spectrals", a["spectrals"]),
                           ("jokers bought", a["jokers_bought"])):
            if rows:
                L.append(f"- {kind}: "
                         + ", ".join(f"{n} x{c}" for n, c in rows[:6]) + "\n")
        if a["death_blind_kind"]:
            L.append("- died on blind: "
                     + ", ".join(f"{n} ({c})"
                                 for n, c in a["death_blind_kind"][:6]) + "\n")

    # ── auto-derived observations ─────────────────────────────────────────
    obs = []
    if len(aggs) >= 2:
        best = max(aggs, key=lambda a: a["win_rate"])
        worst = min(aggs, key=lambda a: a["win_rate"])
        if best is not worst:
            obs.append(f"Highest win rate: {best['label']} "
                       f"({best['win_rate']:.2f}%, {best['wins']}/{best['n']}); "
                       f"lowest: {worst['label']} ({worst['win_rate']:.2f}%). "
                       f"Gap: {best['win_rate'] - worst['win_rate']:.2f}pp.")
        seen = {}
        for a in aggs:
            sig = (a["wins"], a["mean_ante"],
                   tuple(a["death"][str(k)] for k in range(1, 10)))
            seen.setdefault(sig, []).append(a["label"])
        for sig, labs in seen.items():
            if len(labs) > 1:
                obs.append("IDENTICAL results: " + " == ".join(labs)
                           + f" ({labs[0]} wins {sig[0]}/{aggs[0]['n']}, "
                             "same deaths) — these arms make the same decisions.")
        for p in pairs:
            if p.get("discordant", 0) == 0 and p["wins_a"] == p["wins_b"]:
                obs.append(f"No seed-level disagreement between '{p['a']}' "
                           f"and '{p['b']}' — byte-identical policies.")
        ante1 = [(a["label"], a["death_pct"]["1"]) for a in aggs]
        ante1.sort(key=lambda t: t[1])
        obs.append("Ante-1 death rate (low→high): "
                   + ", ".join(f"{l} {v:.1f}%" for l, v in ante1))
    if obs:
        L.append("\n\n## Observations\n")
        for o in obs:
            L.append(f"\n- {o}")

    if notes:
        L.append("\n\n## Context / notes\n")
        for nt in notes:
            L.append(f"\n- {nt}")

    L.append("\n\n## Reproduce\n")
    L.append("\nCommands (run from the repo root; each arm's telemetry was "
             "produced by its bench invocation — re-run with the same flags "
             "+ --telemetry-dir --resume to regenerate instantly):")
    for a in aggs:
        L.append(f"\n```\n# {a['label']} — {a['source']}\n{a['command']}\n```")

    return "".join(L) + "\n"


# ── main ────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, help="output results folder")
    ap.add_argument("--arm", action="append", nargs=3,
                    metavar=("LABEL", "TELDIR", "COMMAND"),
                    help="repeatable: human label + telemetry POLICY dir (the "
                         "subdir holding run_*.json) + the exact bench command "
                         "that produced it (for the Reproduce section)")
    ap.add_argument("--note", action="append", default=[],
                    help="free-text context line for the README (repeatable)")
    ap.add_argument("--seed-bank", default="0..N-1 (per arm n)")
    args = ap.parse_args()
    if not args.arm:
        print("error: at least one --arm LABEL TELDIR COMMAND required")
        sys.exit(1)

    out = Path(args.out)
    (out / "raw").mkdir(parents=True, exist_ok=True)
    (out / "stats").mkdir(parents=True, exist_ok=True)
    (out / "reports").mkdir(parents=True, exist_ok=True)

    aggs = []
    runs_by_arm = []
    for label, tel, command in args.arm:
        src = Path(tel)
        if not src.is_dir():
            print(f"error: telemetry dir not found: {src}")
            sys.exit(1)
        # slug = <telemetry-bank>_<policy> so arms from different banks that
        # share a policy subdir name never collide in raw/<slug>/
        slug = f"{src.parent.name}_{src.name}"
        runs = load_runs(src)
        if not runs:
            print(f"error: no run_*.json in {src}")
            sys.exit(1)
        runs.sort(key=lambda r: r.get("seed", 0))
        raw_dir = out / "raw" / slug
        raw_dir.mkdir(parents=True, exist_ok=True)
        for r in runs:
            (raw_dir / f"run_{r.get('seed', 0):04d}.json").write_text(
                json.dumps(r, indent=1, default=str), encoding="utf-8")
        agg = aggregate(runs, label, slug, str(src))
        agg["command"] = command
        aggs.append(agg)
        runs_by_arm.append(runs)
        print(f"[{label}] {len(runs)} runs -> raw/{slug}/")

    pairs = []
    for i in range(len(aggs)):
        for j in range(i + 1, len(aggs)):
            p = paired(aggs[i], aggs[j], runs_by_arm[i], runs_by_arm[j])
            if p:
                pairs.append(p)

    (out / "stats" / "aggregates.json").write_text(
        json.dumps(aggs, indent=1, ensure_ascii=False), encoding="utf-8")
    (out / "stats" / "paired.json").write_text(
        json.dumps(pairs, indent=1, ensure_ascii=False), encoding="utf-8")
    (out / "arms_meta.json").write_text(json.dumps({
        "seed_bank": args.seed_bank,
        "notes": args.note,
        "arms": [{"label": a["label"], "slug": a["slug"], "source": a["source"],
                  "n": a["n"], "command": a["command"]} for a in aggs],
    }, indent=1, ensure_ascii=False), encoding="utf-8")

    readme = build_readme(aggs, pairs, args.note, args.seed_bank)
    (out / "README.md").write_text(readme, encoding="utf-8")

    print(f"\nwrote {out}:")
    print(f"  README.md · stats/aggregates.json · stats/paired.json · "
          f"arms_meta.json · raw/<slug>/run_*.json (self-contained)")


if __name__ == "__main__":
    main()
