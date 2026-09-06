import json

lost_seeds = [21, 40, 43, 54, 60, 80, 95, 131, 139, 155, 188, 198, 211, 298]

with open('vendor/balatro-rl/results/bench_0_299_search_shop_v10.json', 'r') as f:
    base_res = json.load(f)['search_shop_v10']['results']

with open('vendor/balatro-rl/results/bench_0_299_search_shop_v10_gen5.json', 'r') as f:
    gen5_res = json.load(f)['search_shop_v10']['results']

base_by_seed = {r['seed']: r for r in base_res}
gen5_by_seed = {r['seed']: r for r in gen5_res}

lines = []
lines.append("="*95)
lines.append(f"{'Seed':<5} | {'Base Result':<13} | {'Gen5 Result':<14} | {'Death Blind':<16} | {'Gen5 $':<6} | {'Gen5 Jokers'}")
lines.append("="*95)

for s in lost_seeds:
    b = base_by_seed[s]
    g = gen5_by_seed[s]
    b_str = f"Won (A{b['ante']})" if b['won'] else f"Died A{b['ante']}"
    g_str = f"Won (A{g['ante']})" if g['won'] else f"Died A{g['ante']}"
    death_blind = f"A{g['ante']} B{g['death_blind']} ({g['death_kind']})"
    jokers_str = ", ".join(g['jokers'])
    lines.append(f"{s:<5} | {b_str:<13} | {g_str:<14} | {death_blind:<16} | ${g['dollars']:<5} | {jokers_str}")

with open('.agents/teamwork_preview_explorer_m2_3_gen6/lost_seeds_table.txt', 'w') as f:
    f.write("\n".join(lines) + "\n")

print("Saved lost_seeds_table.txt")
