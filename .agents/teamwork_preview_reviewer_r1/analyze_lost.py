import json

with open('vendor/balatro-rl/results/bench_10500_10799_paired.json') as f:
    data = json.load(f)

v10 = {r['seed']: r for r in data['search_shop_v10']['results']}
v11 = {r['seed']: r for r in data['search_shop_v11']['results']}

s = 10503
print("V10 on 10503:", v10[s])
print("V11 on 10503:", v11[s])
