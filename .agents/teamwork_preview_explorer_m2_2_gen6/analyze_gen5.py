import json

with open("vendor/balatro-rl/results/bench_0_299_search_shop_v10_gen5.json") as f:
    d = json.load(f)

k = list(d.keys())[0]
results = d[k]["results"]

for target_joker in ["j_family", "j_order", "j_duo"]:
    print(f"\n*** TARGET: {target_joker} ***")
    matching = [r for r in results if target_joker in str(r.get("jokers", []))]
    print(f"Total runs: {len(matching)}")
    for r in matching:
        print(f"seed {r['seed']}: ante {r['ante']} ({r.get('death_blind')}), won={r.get('won')}, jokers={r['jokers']}")
