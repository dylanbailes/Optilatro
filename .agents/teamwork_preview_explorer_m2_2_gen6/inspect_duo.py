import json

with open("vendor/balatro-rl/results/bench_0_299_search_shop_v10_gen5.json") as f:
    d = json.load(f)

k = list(d.keys())[0]
results = d[k]["results"]

duo_runs = [r for r in results if "j_duo" in str(r.get("jokers", []))]
for r in duo_runs:
    print(f"Seed {r['seed']}: Ante {r['ante']} ({r.get('death_blind')}), won={r.get('won')}")
    print(f"  Jokers: {r['jokers']}")
    print(f"  Stats: {r.get('stats')}")
