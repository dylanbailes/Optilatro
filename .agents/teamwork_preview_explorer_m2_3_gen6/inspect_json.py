import json

lost_seeds = [21, 40, 43, 54, 60, 80, 95, 131, 139, 155, 188, 198, 211, 298]

with open('vendor/balatro-rl/results/bench_0_299_search_shop_v10.json', 'r') as f:
    base_data = json.load(f)

with open('vendor/balatro-rl/results/bench_0_299_search_shop_v10_gen5.json', 'r') as f:
    gen5_data = json.load(f)

print("Base keys:", list(base_data.keys()))
print("Gen5 keys:", list(gen5_data.keys()))

# Check format of results
base_results = base_data.get('results', base_data)
gen5_results = gen5_data.get('results', gen5_data)

if isinstance(base_results, dict):
    print("Base results sample keys:", list(base_results.keys())[:5])
elif isinstance(base_results, list):
    print("Base results count:", len(base_results))
    print("Sample base item:", base_results[0])
