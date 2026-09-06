"""tools/analyze_bench_9000.py — Deep telemetry analysis for seeds 9000-9299 benchmark.
"""
from __future__ import annotations

import json
import math
from collections import Counter
from pathlib import Path
from statistics import mean, median

def wilson_ci(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    denom = 1.0 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half) * 100.0, min(1.0, centre + half) * 100.0)

def main():
    json_path = Path("vendor/balatro-rl/results/bench_9000_9299_search_shop_v10.json")
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    policy_key = "search_shop_v10"
    pdata = data[policy_key]
    results = pdata["results"]
    agg = pdata["aggregate"]
    n = len(results)

    wins = [r for r in results if r["won"]]
    losses = [r for r in results if not r["won"]]
    a1_deaths = [r for r in losses if r["ante"] <= 1]

    win_rate = 100.0 * len(wins) / n
    a1_death_rate = 100.0 * len(a1_deaths) / n
    win_ci = wilson_ci(len(wins), n)
    a1_ci = wilson_ci(len(a1_deaths), n)

    print("=" * 80)
    print("BENCHMARK TELEMETRY ANALYSIS: SEEDS 9000-9299 (search_shop_v10)")
    print("=" * 80)
    print(f"Total Runs:           {n} seeds (Range: {min(r['seed'] for r in results)} - {max(r['seed'] for r in results)})")
    print(f"Wins:                 {len(wins)} / {n} ({win_rate:.2f}%)  [95% CI: {win_ci[0]:.2f}% - {win_ci[1]:.2f}%]")
    print(f"Ante 1 Deaths:        {len(a1_deaths)} / {n} ({a1_death_rate:.2f}%)  [95% CI: {a1_ci[0]:.2f}% - {a1_ci[1]:.2f}%]")
    print(f"Mean Ante Achieved:   {mean(r['ante'] for r in results):.2f} (Median: {median(r['ante'] for r in results):.1f})")
    print(f"Mean Steps:           {mean(r['steps'] for r in results):.1f}")
    print(f"Mean Ending $:        ${mean(r['dollars'] for r in results):.2f}")
    print(f"Mean Econ $:          ${agg.get('mean_econ_source', 0):.2f}")
    print(f"Mean Interest:        ${agg.get('mean_interest', 0):.2f}")
    print(f"Mean Tarots Used:     {agg.get('mean_tarots', 0):.2f}")
    print(f"Mean Planets Used:    {agg.get('mean_planets', 0):.2f}")
    print(f"Mean Spectrals Used:  {agg.get('mean_spectrals', 0):.2f}")

    print("\n" + "-" * 80)
    print("MORTALITY BREAKDOWN BY ANTE")
    print("-" * 80)
    ante_counts = Counter(9 if r["won"] else min(r["ante"], 8) for r in results)
    for a in range(1, 9):
        cnt = ante_counts[a]
        pct = 100.0 * cnt / n
        bar = "#" * int(cnt)
        print(f"Ante {a}: {cnt:3d} deaths ({pct:5.2f}%) | {bar}")
    print(f"Ante 8 Cleared (Wins): {ante_counts[9]:3d} ({100.0 * ante_counts[9] / n:5.2f}%) | {'#' * ante_counts[9]}")

    print("\n" + "-" * 80)
    print("ANTE 1 DEATH CAUSE AUDIT")
    print("-" * 80)
    BLIND_NAMES = {0: "Small", 1: "Big", 2: "Boss"}
    for r in sorted(a1_deaths, key=lambda x: x["seed"]):
        st = r.get("stats", {})
        db = r.get("death_blind", "N/A")
        db_str = BLIND_NAMES.get(db, str(db))
        print(f"Seed {r['seed']:4d} | Blind: {db_str:10s} | Held Jokers: {str(r.get('jokers', [])):30s} | Bought: {str(st.get('jokers_bought', [])):30s} | End $: {r.get('dollars', 0)}")

    blind_counter = Counter(BLIND_NAMES.get(r.get("death_blind"), str(r.get("death_blind"))) for r in a1_deaths)
    print(f"\nAnte 1 Deaths by Blind: {dict(blind_counter)}")

    # Finisher & High-leverage scoring jokers
    PREMIER_4 = ["j_cavendish", "j_baseball", "j_constellation", "j_acrobat"]
    RELIABLE_XMULT = [
        "j_cavendish", "j_trio", "j_tribe",
        "j_card_sharp", "j_ramen", "j_constellation", "j_hologram",
        "j_baseball", "j_acrobat", "j_stuntman", "j_photograph",
        "j_blueprint", "j_brainstorm", "j_baron", "j_ancient"
    ]
    HIGH_LEVERAGE = [
        "j_cavendish", "j_duo", "j_trio", "j_family", "j_order", "j_tribe",
        "j_card_sharp", "j_baseball", "j_acrobat", "j_constellation", "j_hologram",
        "j_blueprint", "j_brainstorm", "j_baron", "j_ancient", "j_ramen", "j_stuntman", "j_photograph"
    ]

    def joker_in_run(r, jkey):
        bought = r.get("stats", {}).get("jokers_bought", [])
        held = [j.split()[0] for j in r.get("jokers", [])]
        co_owned = []
        for co in r.get("stats", {}).get("co_owned", []):
            co_owned.extend(co[2] if len(co) > 2 else [])
        all_jokers = set(bought) | set(held) | set(co_owned)
        return any(k.startswith(jkey) for k in all_jokers)

    print("\n" + "-" * 80)
    print("FINISHER & HIGH-LEVERAGE JOKER ACQUISITION AND CONVERSION")
    print("-" * 80)
    print(f"{'Joker Key':<20} | {'Acquired Runs':<14} | {'Acq Rate %':<11} | {'Won Runs':<9} | {'Win Conversion %':<17}")
    print("-" * 80)

    for jk in HIGH_LEVERAGE:
        acq_runs = [r for r in results if joker_in_run(r, jk)]
        n_acq = len(acq_runs)
        n_won = sum(1 for r in acq_runs if r["won"])
        conv = (100.0 * n_won / n_acq) if n_acq > 0 else 0.0
        acq_rate = 100.0 * n_acq / n
        print(f"{jk:<20} | {n_acq:<14} | {acq_rate:<10.2f}% | {n_won:<9} | {conv:<16.2f}%")

    # Grouped metrics
    def group_metrics(jset, label):
        acq_runs = [r for r in results if any(joker_in_run(r, jk) for jk in jset)]
        n_acq = len(acq_runs)
        n_won = sum(1 for r in acq_runs if r["won"])
        conv = (100.0 * n_won / n_acq) if n_acq > 0 else 0.0
        acq_rate = 100.0 * n_acq / n
        print(f"{label:<20} | {n_acq:<14} | {acq_rate:<10.2f}% | {n_won:<9} | {conv:<16.2f}%")

    print("-" * 80)
    group_metrics(PREMIER_4, "Core 4 Premier")
    group_metrics(RELIABLE_XMULT, "Reliable xMult Pool")
    group_metrics(HIGH_LEVERAGE, "All High-Leverage")

    print("\n" + "-" * 80)
    print("ACCEPTANCE CRITERIA EVALUATION")
    print("-" * 80)
    win_pass = len(wins) >= 30
    a1_pass = len(a1_deaths) < 12
    print(f"Criteria 1: Win Rate >= 10.0% (>= 30 wins / 300):    {'PASS' if win_pass else 'FAIL'} (Actual: {len(wins)}/300 = {win_rate:.2f}%)")
    print(f"Criteria 2: Ante 1 Deaths < 12 (< 4.00% mortality): {'PASS' if a1_pass else 'FAIL'} (Actual: {len(a1_deaths)}/300 = {a1_death_rate:.2f}%)")
    verdict = "APPROVE" if (win_pass and a1_pass) else "REJECT"
    print(f"\nFINAL VERDICT: {verdict}")

if __name__ == "__main__":
    main()
