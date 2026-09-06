import json
import os

results_dir = "D:/Optilatro/vendor/balatro-rl/results"

def inspect_file(filename):
    path = os.path.join(results_dir, filename)
    if not os.path.exists(path):
        print(f"File not found: {filename}")
        return
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    print(f"=== {filename} ===")
    if isinstance(data, dict):
        for k, v in data.items():
            if isinstance(v, dict) and "aggregate" in v:
                agg = v["aggregate"]
                print(f"Policy '{k}': n={agg.get('n')}, wins={agg.get('wins')}, ante1_deaths={agg.get('ante1_deaths')}")
            else:
                print(f"Key '{k}': type={type(v).__name__}")
    else:
        print(f"List with {len(data)} items")

for fname in [
    "goal_iter7_final_D.json",
    "goal_final_tuned.json",
    "goal_final_defaults.json",
    "goal_iter4_300.json",
    "bench_0_299_eval.json",
    "bench_0_299_remedy.json",
    "bench_300_499_holdout.json",
    "bench_500_699_holdout.json"
]:
    inspect_file(fname)
