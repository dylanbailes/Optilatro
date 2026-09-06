"""tools/verify_bench_acceptance.py — Comprehensive acceptance and paired verification
for Optilatro V10 benchmark runs against baseline goal_iter7_final_D.json.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from statistics import mean, median

ROOT = Path(__file__).resolve().parent.parent
VENDOR = ROOT / "vendor" / "balatro-rl"


def wilson_ci(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% Wilson score interval in percentage."""
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    denom = 1.0 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half) * 100.0, min(1.0, centre + half) * 100.0)


def extract_metrics(results: list[dict]) -> dict:
    n = len(results)
    wins = sum(1 for r in results if r["won"])
    a1_deaths = sum(1 for r in results if not r["won"] and r["ante"] <= 1)
    w_rate = (wins / n) * 100.0 if n else 0.0
    a1_rate = (a1_deaths / n) * 100.0 if n else 0.0
    w_ci = wilson_ci(wins, n)
    a1_ci = wilson_ci(a1_deaths, n)
    m_ante = mean(r["ante"] for r in results) if n else 0.0
    med_ante = median(r["ante"] for r in results) if n else 0.0
    m_steps = mean(r["steps"] for r in results) if n else 0.0
    m_dollars = mean(r["dollars"] for r in results) if n else 0.0

    econ = sum(r.get("stats", {}).get("econ_source", 0) for r in results)
    interest = sum(r.get("stats", {}).get("interest_collected", 0) for r in results)
    tarots = sum(len(r.get("stats", {}).get("tarots", ())) for r in results)
    planets = sum(len(r.get("stats", {}).get("planets", ())) for r in results)
    spectrals = sum(len(r.get("stats", {}).get("spectrals", ())) for r in results)

    deaths = {}
    for r in results:
        bucket = 9 if r["won"] else min(r["ante"], 8)
        deaths[bucket] = deaths.get(bucket, 0) + 1

    return {
        "n": n,
        "wins": wins,
        "win_rate": w_rate,
        "win_ci": w_ci,
        "ante1_deaths": a1_deaths,
        "ante1_death_rate": a1_rate,
        "ante1_ci": a1_ci,
        "mean_ante": m_ante,
        "median_ante": med_ante,
        "mean_steps": m_steps,
        "mean_dollars": m_dollars,
        "mean_econ_source": econ / n if n else 0.0,
        "mean_interest": interest / n if n else 0.0,
        "mean_tarots": tarots / n if n else 0.0,
        "mean_planets": planets / n if n else 0.0,
        "mean_spectrals": spectrals / n if n else 0.0,
        "deaths": deaths,
    }


def paired_compare(results_base: list[dict], results_eval: list[dict]) -> dict:
    b_map = {r["seed"]: r for r in results_base}
    e_map = {r["seed"]: r for r in results_eval}
    shared = sorted(set(b_map.keys()) & set(e_map.keys()))

    concordant_wins = []
    concordant_losses = []
    baseline_only_wins = []
    eval_only_wins = []

    a1_saved = []       # died in baseline ante 1, survived in eval
    a1_regressed = []   # survived in baseline, died in eval ante 1

    for s in shared:
        rb = b_map[s]
        re = e_map[s]
        wb, we = bool(rb["won"]), bool(re["won"])

        if wb and we:
            concordant_wins.append(s)
        elif (not wb) and (not we):
            concordant_losses.append(s)
        elif wb and (not we):
            baseline_only_wins.append(s)
        elif (not wb) and we:
            eval_only_wins.append(s)

        b_a1 = (not wb) and rb["ante"] <= 1
        e_a1 = (not we) and re["ante"] <= 1
        if b_a1 and not e_a1:
            a1_saved.append(s)
        elif not b_a1 and e_a1:
            a1_regressed.append(s)

    discordant = len(baseline_only_wins) + len(eval_only_wins)
    chi2 = 0.0
    if discordant > 0:
        b_cnt = len(eval_only_wins)
        c_cnt = len(baseline_only_wins)
        chi2 = ((abs(b_cnt - c_cnt) - 1.0) ** 2) / discordant

    return {
        "shared": len(shared),
        "concordant_wins": concordant_wins,
        "concordant_losses": concordant_losses,
        "baseline_only_wins": baseline_only_wins,
        "eval_only_wins": eval_only_wins,
        "net_gain": len(eval_only_wins) - len(baseline_only_wins),
        "a1_saved": a1_saved,
        "a1_regressed": a1_regressed,
        "chi2": chi2,
    }


def analyze(eval_path: str, baseline_path: str = "vendor/balatro-rl/results/default_baseline_v10.json"):
    p_eval = Path(eval_path)
    p_base = Path(baseline_path)

    d_eval = json.loads(p_eval.read_text(encoding="utf-8"))
    d_base = json.loads(p_base.read_text(encoding="utf-8"))

    if len(d_eval.keys()) >= 2 and "search_shop_v11" in d_eval and "search_shop_v10" in d_eval:
        eval_policy = "search_shop_v11"
        base_policy = "search_shop_v10"
        eval_results = d_eval[eval_policy]["results"]
        base_results = d_eval[base_policy]["results"]
    else:
        eval_policy = list(d_eval.keys())[-1]
        base_policy = list(d_base.keys())[0]
        eval_results = d_eval[eval_policy]["results"]
        base_results = d_base[base_policy]["results"]

    eval_m = extract_metrics(eval_results)
    base_m = extract_metrics(base_results)

    paired = paired_compare(base_results, eval_results)

    print("=" * 70)
    print(f"BENCHMARK VERIFICATION REPORT")
    print(f"Eval file:     {p_eval} ({eval_policy})")
    print(f"Baseline file: {p_base} ({base_policy})")
    print("=" * 70)

    print(f"\n[Baseline - {base_policy}] (N={base_m['n']}):")
    print(f"  Wins:           {base_m['wins']} ({base_m['win_rate']:.2f}% [{base_m['win_ci'][0]:.2f}%, {base_m['win_ci'][1]:.2f}%])")
    print(f"  Ante 1 Deaths:  {base_m['ante1_deaths']} ({base_m['ante1_death_rate']:.2f}% [{base_m['ante1_ci'][0]:.2f}%, {base_m['ante1_ci'][1]:.2f}%])")
    print(f"  Mean Ante:      {base_m['mean_ante']:.2f} (Median: {base_m['median_ante']:.0f})")
    print(f"  Deaths:         " + " ".join(f"A{k}:{base_m['deaths'].get(k, 0)}" for k in range(1, 10)))

    print(f"\n[Evaluated - {eval_policy}] (N={eval_m['n']}):")
    print(f"  Wins:           {eval_m['wins']} ({eval_m['win_rate']:.2f}% [{eval_m['win_ci'][0]:.2f}%, {eval_m['win_ci'][1]:.2f}%])")
    print(f"  Ante 1 Deaths:  {eval_m['ante1_deaths']} ({eval_m['ante1_death_rate']:.2f}% [{eval_m['ante1_ci'][0]:.2f}%, {eval_m['ante1_ci'][1]:.2f}%])")
    print(f"  Mean Ante:      {eval_m['mean_ante']:.2f} (Median: {eval_m['median_ante']:.0f})")
    print(f"  Mean Econ $:    ${eval_m['mean_econ_source']:.2f} | Interest: ${eval_m['mean_interest']:.2f}")
    print(f"  Deaths:         " + " ".join(f"A{k}:{eval_m['deaths'].get(k, 0)}" for k in range(1, 10)))

    print(f"\n[Paired A/B Seed Comparison] (Shared N={paired['shared']}):")
    print(f"  Concordant Wins (both won):      {len(paired['concordant_wins'])} seeds: {paired['concordant_wins']}")
    print(f"  Baseline-only Wins (eval lost):  {len(paired['baseline_only_wins'])} seeds: {paired['baseline_only_wins']}")
    print(f"  Eval-only Wins (new wins!):      {len(paired['eval_only_wins'])} seeds: {paired['eval_only_wins']}")
    print(f"  Net Win Gain:                    {paired['net_gain']:+d} wins")
    print(f"  McNemar Chi2:                    {paired['chi2']:.3f}")
    print(f"  Ante 1 Saved (died base -> clear): {len(paired['a1_saved'])} seeds: {paired['a1_saved']}")
    print(f"  Ante 1 Regressed (surv -> died):   {len(paired['a1_regressed'])} seeds: {paired['a1_regressed']}")

    # Check acceptance criteria (New V10 Baseline bar)
    a1_bar = max(9, base_m["ante1_deaths"])
    win_pass = eval_m["wins"] >= 30
    a1_pass = eval_m["ante1_deaths"] <= a1_bar

    print(f"\n[Acceptance Criteria Check (V10 Baseline Standard)]:")
    print(f"  1. Win rate >= 10.0% (>= 30 wins / 300): {'PASS' if win_pass else 'FAIL'} ({eval_m['wins']}/300 = {eval_m['win_rate']:.2f}%)")
    print(f"  2. Ante 1 deaths <= {a1_bar} (<= {a1_bar / eval_m['n'] * 100:.2f}%): {'PASS' if a1_pass else 'FAIL'} ({eval_m['ante1_deaths']}/300 = {eval_m['ante1_death_rate']:.2f}%)")

    verdict = "APPROVE" if (win_pass and a1_pass) else "REJECT"
    print(f"\nVERDICT: {verdict}")
    return eval_m, base_m, paired, verdict


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python tools/verify_bench_acceptance.py <eval_json> [baseline_json]")
        sys.exit(1)
    base = sys.argv[2] if len(sys.argv) > 2 else "vendor/balatro-rl/results/default_baseline_v10.json"
    analyze(sys.argv[1], base)
