import json

with open('vendor/balatro-rl/results/bench_0_299_search_shop_v10.json', 'r', encoding='utf-8') as f:
    base298 = [r for r in json.load(f)['search_shop_v10']['results'] if r['seed'] == 298][0]

print("Seed 298 Base stats:")
print("Jokers bought:", base298['stats']['jokers_bought'])
print("Jokers sold:", base298['stats']['jokers_sold'])
print("Tarots:", base298['stats']['tarots'])
print("Planets:", base298['stats']['planets'])
print("Packs opened:", base298['stats']['packs_opened'])
print("Rerolls:", base298['stats']['rerolls'])
print("Best score:", base298['stats']['best_score'])
