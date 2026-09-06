import json

with open('vendor/balatro-rl/results/bench_0_299_search_shop_v10.json', 'r', encoding='utf-8') as f:
    base = {r['seed']: r for r in json.load(f)['search_shop_v10']['results']}

with open('vendor/balatro-rl/results/bench_0_299_search_shop_v10_gen5.json', 'r', encoding='utf-8') as f:
    gen5 = {r['seed']: r for r in json.load(f)['search_shop_v10']['results']}

for s in [21, 40]:
    b = base[s]
    g = gen5[s]
    print("="*80)
    print(f"SEED {s}")
    print(f"Base: won={b['won']} ante={b['ante']} $={b['dollars']} rerolls={b['stats']['rerolls']} spent={b['stats']['money_spent']}")
    print(f"  Base jokers: {b['jokers']}")
    print(f"  Base bought: {b['stats']['jokers_bought']}")
    print(f"  Base sold:   {b['stats']['jokers_sold']}")
    print(f"Gen5: won={g['won']} ante={g['ante']} blind={g['death_blind']} ({g['death_kind']}) $={g['dollars']} rerolls={g['stats']['rerolls']} spent={g['stats']['money_spent']}")
    print(f"  Gen5 jokers: {g['jokers']}")
    print(f"  Gen5 bought: {g['stats']['jokers_bought']}")
    print(f"  Gen5 sold:   {g['stats']['jokers_sold']}")
