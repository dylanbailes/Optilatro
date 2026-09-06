import json

with open("vendor/balatro-rl/results/bench_0_299_search_shop_v10_gen5.json", encoding="utf-8") as f:
    g5 = {r["seed"]: r for r in json.load(f)["search_shop_v10"]["results"]}

with open("vendor/balatro-rl/results/bench_0_299_search_shop_v10.json", encoding="utf-8") as f:
    base = {r["seed"]: r for r in json.load(f)["search_shop_v10"]["results"]}

bp_seeds = [263, 9, 60, 57, 101, 106, 185, 249, 260, 272, 283, 298, 281]
print("\n=== BLUEPRINT / BRAINSTORM SEEDS DETAILS ===")
for s in bp_seeds:
    r = g5[s]
    rb = base[s]
    print(f"Seed {s:>3}: Gen5 ante {r['ante']} (won={r['won']}, {r.get('death_kind')}) | Base ante {rb['ante']} (won={rb['won']}) | dollars: ${r.get('dollars')} | jokers: {r.get('jokers')}")
