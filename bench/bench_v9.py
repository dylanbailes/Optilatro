"""bench/bench_v9.py — V9 benchmark: win-rate A/B + per-run statistics report.

Measures White-Stake full-run win rate + death-by-ante histogram over a fixed
deterministic seed bank, in seed mode (the deterministic mode Layers 0-2 build
on). Each policy runs the SAME seeds for an honest A/B.

Aggregates observation-only run statistics per policy (tarot/planet/spectral
usage, most-bought jokers, money spent, max score, rerolls, packs) and writes
a self-contained HTML report + JSON sidecar (see --report).

Usage:
  .venv/Scripts/python.exe bench/bench_v9.py [--games N] [--workers W]
      [--policies search_shop_v9,random] [--rng-mode seed] [--seed-start 0]
      [--search-shops 1] [--params '{...}'] [--report PATH] [--no-report]
      [--batch-size 25] [--progress PATH] [--resume]

Live progress: every --batch-size completed runs the bench flushes a progress
line (wins, win rate, mean ante, games/s, ETA) and writes a pollable JSON
checkpoint (<report>.progress.json). With --telemetry-dir, per-run JSON is
written as runs COMPLETE (not at policy end), and --resume reloads existing
run_<seed>.json files into the aggregate instead of re-running them — so a
killed bench can be picked up where it left off.

BENCHMARKS ARE HUMAN-FAIR: policies may only use information a human has
access to — which cards remain in the deck (composition), the current shop,
the revealed boss — never the draw order, future shop contents, or future
bosses. The default search_shop_v9 compares shop items by mean measures
(score delta on best/typical drawable hands, econ $/ante, tarot/spectral
gen/ante), NOT by rollout lookahead.

--lookahead enables the legacy rollout-verified shop search, which exploits
the seed-exact sim as a perfect forward model. RESEARCH ONLY — not
human-fair, not a valid benchmark; reserved for prior-refinement and
search-method runs.

Reference: random-agent baseline (bench_sim.py, generic mode) is 0.10% win,
~94.8% dying at ante 1. Older lookahead reference: L1 35/300 = 11.67%
(2026-08-17 build) vs L0 heuristic 20/300 = 6.67%.
"""
from __future__ import annotations

import argparse
import html
import json
import multiprocessing as mp
import os
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from statistics import mean, median

ROOT = Path(__file__).resolve().parent.parent
VENDOR = ROOT / "vendor" / "balatro-rl"
sys.path.insert(0, str(VENDOR))

from balatro_sim.agent_l1 import SearchShopV9
from balatro_sim.agent_v9 import HeuristicV9, RandomPolicy
from balatro_sim.consumables import PLANET_NAME, SPECTRAL_NAME, TAROT_NAME
from balatro_sim.game import BalatroGame
from balatro_sim.rollout import rollout
from balatro_sim.shop import JOKER_CATALOGUE

_NAME_MAP = {
    "tarot": TAROT_NAME, "planet": PLANET_NAME, "spectral": SPECTRAL_NAME,
}
_COLORS = ["#e63946", "#4dabf7", "#2a9d8f", "#e9c46a", "#a78bfa", "#f472b6"]


def _key_name(kind: str, key: str) -> str:
    """Human-readable name for a tracked key (fall back to the raw key)."""
    if kind == "joker":
        return JOKER_CATALOGUE.get(key, {}).get("name", key)
    return _NAME_MAP.get(kind, {}).get(key, key)


def _run_one(args) -> dict:
    policy_name, seed, rng_mode, params, search_shops, lookahead = args
    game = BalatroGame(seed=seed, rng_mode=rng_mode)
    if policy_name == "heuristic_v9":
        policy = HeuristicV9(params=params)
    elif policy_name == "search_shop_v9":
        policy = SearchShopV9(params=params, search_shops=search_shops,
                              lookahead=lookahead)
    else:
        policy = RandomPolicy()
    result = rollout(game, policy)
    result["seed"] = seed  # keys per-run telemetry writes (imap_unordered order)
    return result


def aggregate(results: list[dict]) -> dict:
    """Collapse outcomes into the report's per-policy statistics."""
    n = len(results)
    wins = sum(1 for r in results if r["won"])
    death = {}
    for r in results:
        bucket = 9 if r["won"] else min(r["ante"], 8)
        death[bucket] = death.get(bucket, 0) + 1
    c_tarot, c_planet, c_spec, c_joker = Counter(), Counter(), Counter(), Counter()
    spent = 0
    scores = []
    rerolls = packs = 0
    for r in results:
        st = r.get("stats") or {}
        c_tarot.update(st.get("tarots", ()))
        c_planet.update(st.get("planets", ()))
        c_spec.update(st.get("spectrals", ()))
        c_joker.update(st.get("jokers_bought", ()))
        spent += st.get("money_spent", 0)
        scores.append(st.get("best_score", 0))
        rerolls += st.get("rerolls", 0)
        packs += st.get("packs_bought", 0)
    return {
        "n": n,
        "wins": wins,
        "win_rate": 100.0 * wins / n,
        "death": death,
        "mean_ante": mean(r["ante"] for r in results),
        "median_ante": median(r["ante"] for r in results),
        "mean_steps": mean(r["steps"] for r in results),
        "mean_dollars": mean(r["dollars"] for r in results),
        "mean_jokers": mean(len(r["jokers"]) for r in results),
        "tarots": c_tarot.most_common(),
        "planets": c_planet.most_common(),
        "spectrals": c_spec.most_common(),
        "jokers": c_joker.most_common(),
        "money_spent": spent,
        "mean_spent": spent / n,
        "best_scores": scores,
        "max_score": max(scores, default=0),
        "mean_score": mean(scores) if scores else 0.0,
        "mean_rerolls": rerolls / n,
        "mean_packs": packs / n,
    }


def _print_usage_stats(label: str, agg: dict) -> None:
    print(f"  mean $ {agg['mean_dollars']:6.1f} | spent ${agg['mean_spent']:6.1f} "
          f"| max score {agg['max_score']:>7,} (mean {agg['mean_score']:,.0f}) "
          f"| rerolls {agg['mean_rerolls']:.1f} | packs {agg['mean_packs']:.1f}")
    for kind, top in (("tarot", agg["tarots"]), ("planet", agg["planets"]),
                      ("spectral", agg["spectrals"])):
        if top:
            names = ", ".join(f"{_key_name(kind, k)} x{c}" for k, c in top[:5])
            print(f"  {kind}s:  {names}")
    if agg["jokers"]:
        names = ", ".join(f"{_key_name('joker', k)} x{c}"
                          for k, c in agg["jokers"][:8])
        print(f"  jokers: {names}")


def summarize(results: list[dict], label: str) -> dict:
    n = len(results)
    agg = aggregate(results)
    wins, death = agg["wins"], agg["death"]
    print(f"\n=== {label}: {wins}/{n} wins = {agg['win_rate']:.2f}% "
          f"(mean ante {agg['mean_ante']:.2f}, mean steps {agg['mean_steps']:.0f}) ===")
    for ante in range(1, 10):
        cnt = death.get(ante, 0)
        if cnt:
            bar = "#" * int(60 * cnt / n)
            print(f"  ante {ante}: {cnt:>5} ({100.0 * cnt / n:5.2f}%) {bar}")
    _print_usage_stats(label, agg)
    return agg


def _fmt_eta(seconds: float) -> str:
    """H:MM:SS (or M:SS) for an ETA in seconds."""
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _write_progress(progress_path: Path, pname: str, results: list[dict],
                    total: int, t0: float, resumed: int = 0) -> dict:
    """Persist a live per-policy checkpoint (JSON) — pollable mid-run.

    Written every `--batch-size` completed runs so a long bench is trackable
    (win rate, mean ante, usage stats, games/s, ETA). Everything is derived
    from finished-run outcomes only; the final report remains authoritative.
    games/s + ETA are computed from NEW runs only (`resumed` runs loaded from
    the telemetry corpus are instant and would skew the rate). JSON keys are
    strings (death histogram included) — pollers must int() them.
    """
    agg = aggregate(results)
    elapsed = time.perf_counter() - t0
    new_done = len(results) - resumed
    rate = new_done / elapsed if elapsed and new_done else 0.0
    prog = {
        "policy": pname,
        "updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "runs_done": len(results),
        "runs_total": total,
        "wins": agg["wins"],
        "win_rate": agg["win_rate"],
        "death": agg["death"],
        "mean_ante": agg["mean_ante"],
        "median_ante": agg["median_ante"],
        "mean_steps": agg["mean_steps"],
        "mean_dollars": agg["mean_dollars"],
        "mean_spent": agg["mean_spent"],
        "max_score": agg["max_score"],
        "mean_score": agg["mean_score"],
        "tarots": agg["tarots"],
        "planets": agg["planets"],
        "spectrals": agg["spectrals"],
        "jokers": agg["jokers"],
        "elapsed_s": round(elapsed, 1),
        "games_per_s": round(rate, 2),
        "eta_s": round((total - len(results)) / rate) if rate else None,
    }
    progress_path.write_text(json.dumps(prog, indent=1), encoding="utf-8")
    return prog


# ── HTML report ─────────────────────────────────────────────────────────────

def _bars_html(rows, color: str, fmt=str) -> str:
    """Horizontal bar rows: label, proportional bar, count."""
    if not rows:
        return '<div class="empty">none</div>'
    maxv = max(c for _, c in rows)
    out = []
    for key, cnt in rows:
        pct = 100.0 * cnt / maxv
        out.append(
            f'<div class="brow"><span class="blabel">{html.escape(fmt(key))}</span>'
            f'<span class="btrack"><span class="bfill" style="width:{pct:.1f}%;'
            f'background:{color}"></span></span>'
            f'<span class="bval">{cnt}</span></div>')
    return "\n".join(out)


def _synergy_tree_html() -> str:
    """Top mined synergy edges rendered from tools/synergy_tree.json (empty
    when the tree is absent) — the empirical counterpart to the static graph.
    Surfaces all four edge families: joker↔joker lift, joker↔consumable lift,
    joker↔hand activation, joker↔card target features."""
    try:
        from balatro_sim.synergy_tree import load_tree
    except Exception:
        return ""
    tree = load_tree()
    if not tree:
        return ""
    meta = tree.get("meta", {})
    head = (f"<div class='meta'>mined from {meta.get('runs', 0)} runs "
            f"(min-support {meta.get('min_support', 3)})")

    jj = tree.get("joker_joker", {})
    rows = []
    for a, others in jj.items():
        for b, e in others.items():
            rows.append((e.get("lift_ante", 0.0), a, b, e.get("n", 0)))
    rows.sort(key=lambda t: (-t[0], -t[3]))
    cells = []
    for lift, a, b, n in rows[:12]:
        cells.append(
            f"<tr><td>{html.escape(_key_name('joker', a))}</td>"
            f"<td>{html.escape(_key_name('joker', b))}</td>"
            f"<td class='big'>{lift:+.2f}</td><td>{n}</td></tr>")
    jj_html = ("<h2>Top mined joker-joker synergies</h2><table><tr><th>joker</th>"
               "<th>with</th><th>ante lift</th><th>runs</th></tr>"
               + "".join(cells) + "</table>") if cells else ""

    jc = tree.get("joker_consumable", {})
    crows = []
    for j, cons in jc.items():
        for c, e in cons.items():
            lift = e.get("mean_ante", 0.0) - e.get("base_mean_ante", 0.0)
            crows.append((lift, j, c, e.get("n", 0)))
    crows.sort(key=lambda t: (-t[0], -t[3]))
    ccells = []
    for lift, j, c, n in crows[:10]:
        cname = (_key_name("tarot", c) if c.startswith("c_")
                 else _key_name("planet", c) if c.startswith("pl_")
                 else _key_name("spectral", c))
        ccells.append(
            f"<tr><td>{html.escape(_key_name('joker', j))}</td>"
            f"<td>{html.escape(cname)}</td>"
            f"<td class='big'>{lift:+.2f}</td><td>{n}</td></tr>")
    jc_html = ("<h2>Top mined joker-consumable pairs</h2><table><tr><th>joker</th>"
               "<th>consumable</th><th>ante lift</th><th>runs</th></tr>"
               + "".join(ccells) + "</table>") if ccells else ""

    jh = tree.get("joker_hand", {})
    hrows = []
    for j, hands in jh.items():
        for ht, e in hands.items():
            hrows.append((e.get("n", 0), j, ht, e.get("share", 0.0)))
    hrows.sort(key=lambda t: (-t[0], -t[3]))
    hcells = []
    for n, j, ht, share in hrows[:10]:
        hcells.append(
            f"<tr><td>{html.escape(_key_name('joker', j))}</td>"
            f"<td>{html.escape(ht)}</td>"
            f"<td class='big'>{share:.0%}</td><td>{n}</td></tr>")
    jh_html = ("<h2>Top mined joker-hand activations</h2><table><tr><th>joker</th>"
               "<th>hand type</th><th>share of its hands</th><th>hands</th></tr>"
               + "".join(hcells) + "</table>") if hcells else ""

    jcard = tree.get("joker_card", {})
    frows = []
    for j, feats in jcard.items():
        for feat, n in feats.items():
            frows.append((n, j, feat))
    frows.sort(key=lambda t: -t[0])
    fcells = []
    for n, j, feat in frows[:10]:
        fname = (f"Rank {feat[5:]}" if feat.startswith("rank_")
                 else feat[5:] if feat.startswith("suit_")
                 else feat[4:] if feat.startswith("enh_") else feat)
        fcells.append(
            f"<tr><td>{html.escape(_key_name('joker', j))}</td>"
            f"<td>{html.escape(fname)}</td><td class='big'>{n}</td></tr>")
    jcard_html = ("<h2>Top mined joker-card targets</h2><table><tr><th>joker</th>"
                  "<th>card feature</th><th>targets</th></tr>"
                  + "".join(fcells) + "</table>") if fcells else ""

    counts = (f" · joker↔joker {sum(len(v) for v in jj.values())} edges · "
              f"joker↔consumable {sum(len(v) for v in jc.values())} · "
              f"joker↔hand {sum(len(v) for v in jh.values())} · "
              f"joker↔card {sum(len(v) for v in jcard.values())}")
    if not (jj_html or jc_html or jh_html or jcard_html):
        return ""
    return (head + counts + "</div>" + jj_html + jc_html + jh_html
            + jcard_html)


def write_report(policy_data: list[tuple[str, dict, list[dict]]], args,
                 path: Path) -> None:
    """Write a self-contained HTML report (inline CSS, no JS/network deps)
    plus a JSON sidecar with the raw results + aggregates."""
    n = len(policy_data[0][2])
    cells = []
    for label, agg, _ in policy_data:
        cells.append(
            f"<tr><td><b>{html.escape(label)}</b></td>"
            f"<td>{agg['wins']}/{agg['n']}</td>"
            f"<td class='big'>{agg['win_rate']:.2f}%</td>"
            f"<td>{agg['mean_ante']:.2f}</td><td>{agg['median_ante']:.0f}</td>"
            f"<td>{agg['mean_steps']:.0f}</td>"
            f"<td>${agg['mean_dollars']:.1f}</td>"
            f"<td>${agg['mean_spent']:.1f}</td>"
            f"<td>{agg['max_score']:,}</td><td>{agg['mean_score']:,.0f}</td>"
            f"<td>{agg['mean_rerolls']:.1f}</td><td>{agg['mean_packs']:.1f}</td>"
            f"</tr>")
    rows = "\n".join(cells)

    sections = []
    for label, agg, _ in policy_data:
        color = _COLORS[len(sections) % len(_COLORS)]
        death_rows = [(f"Ante {a}", cnt)
                      for a, cnt in sorted(agg["death"].items())]
        # Bar HTML is computed OUTSIDE any f-string: multi-line expressions are
        # illegal inside single-quoted f-strings.
        bar_death = _bars_html(death_rows, color)
        bar_tarot = _bars_html(agg["tarots"], color,
                               lambda k: _key_name("tarot", k))
        bar_planet = _bars_html(agg["planets"], color,
                                lambda k: _key_name("planet", k))
        bar_spec = _bars_html(agg["spectrals"], color,
                              lambda k: _key_name("spectral", k))
        bar_joker = _bars_html(agg["jokers"], color,
                               lambda k: _key_name("joker", k))
        h = ('<div class="card"><h3>' + html.escape(label)
             + f" — {agg['wins']}/{agg['n']} wins ({agg['win_rate']:.2f}%)</h3>"
             + "<h4>Death by ante</h4>" + bar_death
             + "<h4>Most-used tarots</h4>" + bar_tarot
             + "<h4>Most-used planets</h4>" + bar_planet
             + "<h4>Most-used spectrals</h4>" + bar_spec
             + "<h4>Most-bought jokers</h4>" + bar_joker
             + "</div>")
        sections.append(h)

    raw = {label: {"results": results, "aggregate": agg}
           for label, agg, results in policy_data}
    syn_html = _synergy_tree_html()   # computed outside the f-string
    cmd = " ".join(sys.argv)
    doc = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>V9 benchmark report</title>
<style>
  body {{ margin: 0; padding: 32px; background: #0f1115; color: #e6e8ee;
         font: 14px/1.5 "Segoe UI", system-ui, sans-serif; }}
  h1 {{ font-size: 22px; margin: 0 0 4px; }}
  h2 {{ font-size: 17px; margin: 28px 0 10px; border-bottom: 1px solid #2a2e39;
        padding-bottom: 6px; }}
  h3 {{ margin: 0 0 10px; font-size: 15px; }}
  h4 {{ margin: 14px 0 6px; font-size: 12px; text-transform: uppercase;
        letter-spacing: .08em; color: #8b93a7; }}
  .meta {{ color: #8b93a7; font-size: 12px; margin-bottom: 6px; }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(420px, 1fr));
          gap: 16px; }}
  .card {{ background: #1a1d24; border: 1px solid #2a2e39; border-radius: 10px;
          padding: 16px 18px; }}
  table {{ border-collapse: collapse; width: 100%; background: #1a1d24;
          border-radius: 10px; overflow: hidden; }}
  th, td {{ padding: 8px 10px; text-align: right; border-bottom: 1px solid #242834;
           font-variant-numeric: tabular-nums; }}
  th {{ background: #232733; color: #8b93a7; font-size: 11px;
        text-transform: uppercase; letter-spacing: .05em; }}
  td:first-child, th:first-child {{ text-align: left; }}
  .big {{ color: #4dabf7; font-weight: 700; }}
  .brow {{ display: flex; align-items: center; gap: 10px; margin: 4px 0; }}
  .blabel {{ width: 210px; overflow: hidden; text-overflow: ellipsis;
            white-space: nowrap; font-size: 12px; color: #c3c9d6; }}
  .btrack {{ flex: 1; background: #232733; border-radius: 4px; height: 14px; }}
  .bfill {{ display: block; height: 14px; border-radius: 4px; }}
  .bval {{ width: 44px; text-align: right; font-size: 12px; color: #8b93a7; }}
  .empty {{ color: #5c6370; font-size: 12px; }}
  pre {{ background: #12141a; border: 1px solid #2a2e39; border-radius: 8px;
        padding: 14px; overflow-x: auto; font-size: 11px; color: #9fb0c3; }}
</style></head><body>
<h1>V9 benchmark report</h1>
<div class="meta">{html.escape(cmd)} · {datetime.now().strftime("%Y-%m-%d %H:%M")} ·
{n} seeds per policy · rng_mode={args.rng_mode} · workers={args.workers}</div>
<h2>Summary</h2>
<table><tr><th>policy</th><th>wins</th><th>win %</th><th>mean ante</th>
<th>median ante</th><th>mean steps</th><th>mean $</th><th>mean spent</th>
<th>max score</th><th>mean score</th><th>rerolls</th><th>packs</th></tr>
{rows}</table>
<h2>Per-policy detail</h2>
<div class="grid">{''.join(sections)}</div>
{syn_html}
<h2>Raw data (JSON)</h2>
<pre>{html.escape(json.dumps(raw, indent=1, default=str))}</pre>
</body></html>"""
    path.write_text(doc, encoding="utf-8")
    sidecar = path.with_suffix(".json")
    sidecar.write_text(json.dumps(raw, indent=1, default=str), encoding="utf-8")
    print(f"\nreport: {path} (+ {sidecar.name})")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=200)
    ap.add_argument("--workers", type=int, default=max(1, os.cpu_count() or 1))
    ap.add_argument("--policies", default="search_shop_v9,random",
                    help="comma-separated policies (default measures the "
                         "flagship L1 agent search_shop_v9 + the random "
                         "baseline; pass heuristic_v9 for the fast L0-only "
                         "policy)")
    ap.add_argument("--rng-mode", default="seed", choices=["seed", "generic"])
    ap.add_argument("--seed-start", type=int, default=0)
    ap.add_argument("--search-shops", type=int, default=1,
                    help="L1 SearchShopV9: how many early shop visits get "
                         "searched decisions (0 = pure L0)")
    ap.add_argument("--lookahead", action="store_true",
                    help="RESEARCH ONLY (not human-fair / not a valid "
                         "benchmark): rollout-verified shop search, which "
                         "exploits the seed-exact sim as a perfect forward "
                         "model. Reserved for prior-refinement and search-"
                         "method runs.")
    ap.add_argument("--params", default=None,
                    help="JSON dict overridden into HeuristicV9 params "
                         "(e.g. '{\"use_tarots\": false}' for the A/B)")
    ap.add_argument("--report", default=str(VENDOR / "results" / "v9_report.html"),
                    help="HTML report output path (default: "
                         "vendor/balatro-rl/results/v9_report.html)")
    ap.add_argument("--no-report", action="store_true",
                    help="skip writing the HTML report + JSON sidecar")
    ap.add_argument("--telemetry-dir", default=None,
                    help="write per-run telemetry JSON (outcome + synergy "
                         "logs) under this dir, one subdir per policy — the "
                         "corpus for tools/gen_synergy_tree.py")
    ap.add_argument("--batch-size", type=int, default=25,
                    help="flush a live progress line + checkpoint every N "
                         "completed runs (0 = end-of-policy only)")
    ap.add_argument("--progress", default=None,
                    help="live progress JSON path (default: <report stem>"
                         ".progress.json)")
    ap.add_argument("--resume", action="store_true",
                    help="skip seeds whose telemetry run_<seed>.json already "
                         "exists under --telemetry-dir (reload them into the "
                         "aggregate instead of re-running)")
    ap.add_argument("--synergy-tree", default=None,
                    help="explicit synergy-tree JSON used by ALL policies "
                         "(overrides the default tools/synergy_tree.json)")
    ap.add_argument("--per-policy-trees", action="store_true",
                    help="each policy uses tools/synergy_tree_<policy>.json "
                         "(mined with --policy) when it exists, else the "
                         "default tree")
    args = ap.parse_args()

    params = json.loads(args.params) if args.params else None
    policies = [p.strip() for p in args.policies.split(",")]
    seeds = list(range(args.seed_start, args.seed_start + args.games))
    print(f"bench_v9: {args.games} seeds ({seeds[0]}..{seeds[-1]}), "
          f"rng_mode={args.rng_mode}, workers={args.workers}, "
          f"policies={policies}, search_shops={args.search_shops}, "
          f"lookahead={args.lookahead}, params={params}, "
          f"batch_size={args.batch_size}, "
          f"resume={args.resume}, per_policy_trees={args.per_policy_trees}",
          flush=True)
    if args.lookahead:
        print("WARNING: --lookahead is RESEARCH ONLY — the rollout search "
              "uses exact future knowledge (draw order, future shops, future "
              "bosses) and is NOT a valid human-fair benchmark.", flush=True)

    if args.resume and not args.telemetry_dir:
        print("WARNING: --resume needs --telemetry-dir to find existing "
              "run_<seed>.json files; running all seeds fresh.", flush=True)

    progress_path = (Path(args.progress) if args.progress
                     else Path(args.report).with_name(
                         Path(args.report).stem + ".progress.json"))

    policy_results = []
    for pname in policies:
        t0 = time.perf_counter()
        results: list[dict] = []
        tdir = (Path(args.telemetry_dir) / pname if args.telemetry_dir
                else None)
        if tdir:
            tdir.mkdir(parents=True, exist_ok=True)
        # Per-policy params: user --params, plus the synergy-tree selection
        # (explicit path, or a per-policy tree when the flag is on and the
        # file exists — per-policy trees are mined with
        # tools/gen_synergy_tree.py --policy <policy>).
        policy_params = dict(params) if params else {}
        if args.synergy_tree:
            policy_params["synergy_tree"] = args.synergy_tree
        if args.per_policy_trees:
            pt = ROOT / "tools" / f"synergy_tree_{pname}.json"
            if pt.exists():
                policy_params["synergy_tree"] = str(pt)
        if policy_params.get("synergy_tree"):
            print(f"  [{pname}] synergy tree: "
                  f"{policy_params['synergy_tree']}", flush=True)
        # Config fingerprint for the telemetry dir — --resume only reloads
        # runs that match the CURRENT config, so an A/B never silently mixes
        # two different parameterizations into one aggregate.
        cfg = {"policy": pname, "rng_mode": args.rng_mode,
               "params": policy_params, "search_shops": args.search_shops,
               "lookahead": args.lookahead,
               "seed_start": args.seed_start, "games": args.games}
        if tdir is not None:
            meta = tdir / "meta.json"
            if args.resume and meta.exists():
                try:
                    prev = json.loads(meta.read_text(encoding="utf-8"))
                    diffs = {k: (prev.get(k), v) for k, v in cfg.items()
                             if prev.get(k) != v}
                    if diffs:
                        print(f"WARNING: {tdir.name} telemetry was produced "
                              f"under a DIFFERENT config {diffs}; resuming "
                              f"only seeds whose runs match the current "
                              f"config.", flush=True)
                except Exception:
                    pass
            meta.write_text(json.dumps(cfg, indent=1), encoding="utf-8")
        # --resume: reload finished runs from the telemetry corpus instead of
        # re-running them (they carry the full outcome dict the report needs).
        jobs = []
        for s in seeds:
            if args.resume and tdir is not None:
                pf = tdir / f"run_{s}.json"
                if pf.exists():
                    try:
                        r = json.loads(pf.read_text(encoding="utf-8"))
                        if r.get("_cfg") not in (None, cfg):
                            jobs.append((pname, s, args.rng_mode,
                                         policy_params, args.search_shops,
                                         args.lookahead))
                            continue
                        results.append(r)
                        continue
                    except Exception:
                        pass  # corrupt file -> re-run the seed
            jobs.append((pname, s, args.rng_mode, policy_params,
                         args.search_shops, args.lookahead))
        resumed = len(seeds) - len(jobs)
        if resumed:
            print(f"  [{pname}] resumed {resumed}/{len(seeds)} runs from "
                  f"{tdir}", flush=True)

        batch = args.batch_size or len(seeds)

        # NOTE: `_on_result` is ONLY ever invoked synchronously within the
        # current policy iteration (by the pool loop below or the serial
        # fallback), so its closure over the loop-rebound locals
        # (pname/t0/results/tdir/resumed/...) is safe. Do not call it from a
        # thread or deferred callback.
        def _on_result(r: dict) -> None:
            results.append(r)
            if tdir is not None:
                payload = dict(r)
                payload["_cfg"] = cfg
                (tdir / f"run_{r['seed']}.json").write_text(
                    json.dumps(payload, indent=1, default=str),
                    encoding="utf-8")
            done = len(results)
            if done % batch == 0 or done == len(seeds):
                prog = _write_progress(progress_path, pname, results,
                                       len(seeds), t0, resumed)
                eta = (_fmt_eta(prog["eta_s"]) if prog["eta_s"] is not None
                       else "?")
                print(f"  [{pname}] {done}/{len(seeds)} runs | "
                      f"{prog['wins']} wins ({prog['win_rate']:.2f}%) | "
                      f"mean ante {prog['mean_ante']:.2f} | "
                      f"{prog['games_per_s']:.1f} games/s | ETA {eta} | "
                      f"{progress_path.name}", flush=True)

        if args.workers > 1 and jobs:
            ctx = mp.get_context("spawn")
            with ctx.Pool(args.workers) as pool:
                for r in pool.imap_unordered(_run_one, jobs, chunksize=1):
                    _on_result(r)
        else:
            for j in jobs:
                _on_result(_run_one(j))
        # Final checkpoint (idempotent — also covers fully-resumed policies
        # where no batch boundary fired).
        if results:
            _write_progress(progress_path, pname, results, len(seeds), t0,
                            resumed)
        dt = time.perf_counter() - t0
        agg = summarize(results, f"{pname} ({dt:.0f}s, "
                                 f"{len(results) / dt:.1f} games/s)")
        policy_results.append((pname, agg, results))
        if tdir is not None:
            print(f"telemetry: {len(results)} runs -> {tdir}")

    if not args.no_report:
        write_report(policy_results, args, Path(args.report))


if __name__ == "__main__":
    main()
