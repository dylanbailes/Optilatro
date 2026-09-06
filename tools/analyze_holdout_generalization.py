"""tools/analyze_holdout_generalization.py — Deep statistical and generalization analysis
of Agent V10 across benchmark and out-of-sample holdout seed banks.
"""
from __future__ import annotations

import json
import math
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

def mcnemar_test(results_a: list[dict], results_b: list[dict]) -> dict:
    by_a = {r["seed"]: r for r in results_a}
    by_b = {r["seed"]: r for r in results_b}
    shared = sorted(set(by_a) & set(by_b))
    
    b_only = 0 # a lost, b won
    c_only = 0 # a won, b lost
    both_win = 0
    both_loss = 0
    
    ante1_b_only_surv = 0 # a died in ante 1, b survived ante 1
    ante1_c_only_surv = 0 # a survived ante 1, b died in ante 1
    
    for s in shared:
        ra, rb = by_a[s], by_b[s]
        wa, wb = bool(ra["won"]), bool(rb["won"])
        if wa and wb: both_win += 1
        elif (not wa) and (not wb): both_loss += 1
        elif (not wa) and wb: b_only += 1
        elif wa and (not wb): c_only += 1
        
        a_a1_death = (not wa) and ra["ante"] <= 1
        b_a1_death = (not wb) and rb["ante"] <= 1
        if a_a1_death and not b_a1_death:
            ante1_b_only_surv += 1
        elif not a_a1_death and b_a1_death:
            ante1_c_only_surv += 1
            
    # Continuity corrected McNemar chi2
    discordant = b_only + c_only
    chi2 = ((abs(b_only - c_only) - 1.0) ** 2) / discordant if discordant > 0 else 0.0
    
    return {
        "shared": len(shared),
        "both_win": both_win,
        "both_loss": both_loss,
        "b_only_win": b_only,
        "a_only_win": c_only,
        "chi2": chi2,
        "ante1_saved": ante1_b_only_surv,
        "ante1_regressed": ante1_c_only_surv,
    }

def summarize_bank(name: str, data: dict):
    print(f"\n=================================================================")
    print(f"BANK: {name}")
    print(f"=================================================================")
    for policy, content in data.items():
        results = content["results"]
        agg = content["aggregate"]
        n = len(results)
        wins = sum(1 for r in results if r["won"])
        a1_deaths = sum(1 for r in results if not r["won"] and r["ante"] <= 1)
        w_lo, w_hi = wilson_ci(wins, n)
        a1_lo, a1_hi = wilson_ci(a1_deaths, n)
        mean_ante = mean(r["ante"] for r in results)
        med_ante = median(r["ante"] for r in results)
        mean_econ = mean(r.get("stats", {}).get("econ_source", 0) for r in results)
        mean_interest = mean(r.get("stats", {}).get("interest_collected", 0) for r in results)
        
        print(f"[{policy}] N={n} | Wins={wins} ({wins/n*100:.2f}% [{w_lo:.2f}%, {w_hi:.2f}%]) | "
              f"Ante1Deaths={a1_deaths} ({a1_deaths/n*100:.2f}% [{a1_lo:.2f}%, {a1_hi:.2f}%]) | "
              f"MeanAnte={mean_ante:.2f} | MedAnte={med_ante:.0f} | Econ=${mean_econ:.1f} | Int=${mean_interest:.1f}")
        
        # Ante death breakdown
        deaths = {}
        for r in results:
            bucket = 9 if r["won"] else min(r["ante"], 8)
            deaths[bucket] = deaths.get(bucket, 0) + 1
        d_str = " ".join(f"A{k}:{deaths.get(k,0)}" for k in range(1, 10))
        print(f"   Deaths: {d_str}")

def main():
    root = Path(__file__).resolve().parent.parent
    results_dir = root / "vendor" / "balatro-rl" / "results"
    
    b0_299_path = results_dir / "bench_0_299_eval.json"
    b1_path = results_dir / "holdout_bank1_300_499.json"
    b2_path = results_dir / "holdout_bank2_500_699.json"
    
    b1 = json.loads(b1_path.read_text(encoding="utf-8")) if b1_path.exists() else None
    b2 = json.loads(b2_path.read_text(encoding="utf-8")) if b2_path.exists() else None
    b0 = json.loads(b0_299_path.read_text(encoding="utf-8")) if b0_299_path.exists() else None
    
    if b0:
        summarize_bank("Benchmark Bank (Seeds 0-299)", b0)
    if b1:
        summarize_bank("Holdout Bank 1 (Seeds 300-499)", b1)
    if b2:
        summarize_bank("Holdout Bank 2 (Seeds 500-699)", b2)
        
    # Combined Holdouts 300-699
    if b1 and b2:
        combined_holdout = {}
        for pol in ["heuristic_v9", "heuristic_v10", "search_shop_v10"]:
            if pol in b1 and pol in b2:
                res = b1[pol]["results"] + b2[pol]["results"]
                combined_holdout[pol] = {"results": res, "aggregate": {}}
        summarize_bank("Combined Holdout Banks (Seeds 300-699, N=400)", combined_holdout)

    # Combined All 0-699
    if b0 and b1 and b2:
        combined_all = {}
        for pol in ["heuristic_v9", "heuristic_v10", "search_shop_v10"]:
            if pol in b0 and pol in b1 and pol in b2:
                res = b0[pol]["results"] + b1[pol]["results"] + b2[pol]["results"]
                combined_all[pol] = {"results": res, "aggregate": {}}
        summarize_bank("Global Combined Banks (Seeds 0-699, N=700)", combined_all)

    # Paired comparisons on holdouts
    if b1 and b2:
        print("\n=================================================================")
        print("PAIRED COMPARISONS: Combined Holdouts (Seeds 300-699)")
        print("=================================================================")
        res_v9 = b1["heuristic_v9"]["results"] + b2["heuristic_v9"]["results"]
        res_v10_heur = b1["heuristic_v10"]["results"] + b2["heuristic_v10"]["results"]
        res_v10_search = b1["search_shop_v10"]["results"] + b2["search_shop_v10"]["results"]
        
        pair_v9_v10s = mcnemar_test(res_v9, res_v10_search)
        print(f"heuristic_v9 -> search_shop_v10:")
        print(f"  Shared Seeds: {pair_v9_v10s['shared']}")
        print(f"  Wins: v9={sum(1 for r in res_v9 if r['won'])}, search_v10={sum(1 for r in res_v10_search if r['won'])}")
        print(f"  Win Flips: both_win={pair_v9_v10s['both_win']}, both_loss={pair_v9_v10s['both_loss']}, "
              f"v9_only={pair_v9_v10s['a_only_win']}, search_v10_only={pair_v9_v10s['b_only_win']}")
        print(f"  Ante 1 Deaths: v9={sum(1 for r in res_v9 if not r['won'] and r['ante']<=1)}, "
              f"search_v10={sum(1 for r in res_v10_search if not r['won'] and r['ante']<=1)}")
        print(f"  Ante 1 Flips: saved={pair_v9_v10s['ante1_saved']}, regressed={pair_v9_v10s['ante1_regressed']}")

if __name__ == "__main__":
    main()
