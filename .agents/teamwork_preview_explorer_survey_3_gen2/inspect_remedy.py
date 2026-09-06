import json

for fname in ["bench_0_299_eval.json", "bench_0_299_remedy.json", "bench_300_499_holdout.json", "bench_500_699_holdout.json"]:
    data = json.load(open(f"D:/Optilatro/vendor/balatro-rl/results/{fname}"))
    print(f"=== {fname} ===")
    for p, info in data.items():
        agg = info["aggregate"]
        print(f"  {p}: n={agg['n']}, wins={agg['wins']} ({agg['win_rate']:.2f}%), ante1_deaths={agg['ante1_deaths']} ({agg['ante1_death_rate']:.2f}%)")
