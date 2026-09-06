import json

with open('vendor/balatro-rl/results/bench_0_299_search_shop_v10.json', 'r') as f:
    base_data = json.load(f)['search_shop_v10']

res = base_data['results']
print(f"Results type: {type(res)}")
if isinstance(res, list):
    print("Length:", len(res))
    print("Item 0:", res[0])
elif isinstance(res, dict):
    print("Keys sample:", list(res.keys())[:5])
    print("Item 0:", res[list(res.keys())[0]])
