import json

lost_seeds = [21, 40, 43, 54, 60, 80, 95, 131, 139, 155, 188, 198, 211, 298]

with open('vendor/balatro-rl/results/bench_0_299_search_shop_v10.json', 'r') as f:
    base_res = json.load(f)['search_shop_v10']['results']

with open('vendor/balatro-rl/results/bench_0_299_search_shop_v10_gen5.json', 'r') as f:
    gen5_res = json.load(f)['search_shop_v10']['results']

base_by_seed = {r['seed']: r for r in base_res}
gen5_by_seed = {r['seed']: r for r in gen5_res}

print("="*80)
print(f"{'Seed':<5} | {'Base Result':<15} | {'Gen5 Result':<15} | {'Death Blind':<15} | {'Gen5 $':<6} | {'Gen5 Jokers'}")
print("="*80)

for s in lost_seeds:
    b = base_by_seed[s]
    g = gen5_by_seed[s]
    b_str = f"Won (Ante {b['ante']})" if b['won'] else f"Died Ante {b['ante']}"
    g_str = f"Won (Ante {g['ante']})" if g['won'] else f"Died Ante {g['ante']}"
    death_blind = f"Ante {g['ante']} B{g['death_blind']} ({g['death_kind']})"
    jokers_str = ", ".join(g['jokers'])
    print(f"{s:<5} | {b_str:<15} | {g_str:<15} | {death_blind:<15} | ${g['dollars']:<5} | {jokers_str}")

print("\n" + "="*80)
print("DETAILED COMPARISON FOR EACH LOST SEED")
print("="*80)

for s in lost_seeds:
    b = base_by_seed[s]
    g = gen5_by_seed[s]
    print(f"\n### SEED {s}:")
    print(f"BASELINE: Won={b['won']}, Ante={b['ante']}, Dollars=${b['dollars']}, Steps={b['steps']}")
    print(f"  Jokers Held: {b['jokers']}")
    print(f"  Jokers Bought: {b['stats']['jokers_bought']}")
    print(f"  Jokers Sold: {b['stats']['jokers_sold']}")
    print(f"  Rerolls: {b['stats']['rerolls']}, Money Spent: ${b['stats']['money_spent']}, Econ: ${b['stats']['econ_source']}, Interest: ${b['stats']['interest_collected']}")
    print(f"  Tarots: {b['stats']['tarots']}")
    print(f"  Planets: {b['stats']['planets']}")
    
    print(f"GEN5:     Won={g['won']}, Ante={g['ante']}, Blind={g['death_blind']} ({g['death_kind']}), Dollars=${g['dollars']}, Steps={g['steps']}")
    print(f"  Jokers Held: {g['jokers']}")
    print(f"  Jokers Bought: {g['stats']['jokers_bought']}")
    print(f"  Jokers Sold: {g['stats']['jokers_sold']}")
    print(f"  Rerolls: {g['stats']['rerolls']}, Money Spent: ${g['stats']['money_spent']}, Econ: ${g['stats']['econ_source']}, Interest: ${g['stats']['interest_collected']}")
    print(f"  Tarots: {g['stats']['tarots']}")
    print(f"  Planets: {g['stats']['planets']}")
