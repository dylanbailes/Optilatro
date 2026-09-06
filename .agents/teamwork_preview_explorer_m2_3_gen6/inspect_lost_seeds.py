import json

lost_seeds = [21, 40, 43, 54, 60, 80, 95, 131, 139, 155, 188, 198, 211, 298]

with open('vendor/balatro-rl/results/bench_0_299_search_shop_v10.json', 'r') as f:
    base_data = json.load(f)['search_shop_v10']

with open('vendor/balatro-rl/results/bench_0_299_search_shop_v10_gen5.json', 'r') as f:
    gen5_data = json.load(f)['search_shop_v10']

print(f"Base data type: {type(base_data)}, length: {len(base_data) if isinstance(base_data, list) else list(base_data.keys())}")

# If it's a list or dict
if isinstance(base_data, list):
    sample = base_data[0]
    print("Sample record keys:", sample.keys())
    # find lost seeds
    base_by_seed = {r['seed']: r for r in base_data}
    gen5_by_seed = {r['seed']: r for r in gen5_data}
elif isinstance(base_data, dict):
    # maybe dict keyed by seed or runs
    print("Keys:", list(base_data.keys())[:10])
    if 'runs' in base_data:
        base_by_seed = {r['seed']: r for r in base_data['runs']}
        gen5_by_seed = {r['seed']: r for r in gen5_data['runs']}
    else:
        base_by_seed = {int(k): v for k, v in base_data.items() if k.isdigit()}
        gen5_by_seed = {int(k): v for k, v in gen5_data.items() if k.isdigit()}

print("\n--- LOST SEEDS SUMMARY ---")
for s in lost_seeds:
    b = base_by_seed.get(s, {})
    g = gen5_by_seed.get(s, {})
    print(f"Seed {s}:")
    print(f"  Base: won={b.get('won', b.get('win'))}, ante={b.get('ante')}, round={b.get('round')}, dollars={b.get('dollars')}, jokers={b.get('jokers')}")
    print(f"  Gen5: won={g.get('won', g.get('win'))}, ante={g.get('ante')}, round={g.get('round')}, dollars={g.get('dollars')}, jokers={g.get('jokers')}")
