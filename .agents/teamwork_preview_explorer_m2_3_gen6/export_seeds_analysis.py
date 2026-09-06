import json

with open('.agents/teamwork_preview_explorer_m2_3_gen6/trace_results.json', 'r') as f:
    traces = json.load(f)

with open('vendor/balatro-rl/results/bench_0_299_search_shop_v10.json', 'r') as f:
    base_res = {r['seed']: r for r in json.load(f)['search_shop_v10']['results']}

with open('.agents/teamwork_preview_explorer_m2_3_gen6/seeds_analysis.txt', 'w') as out:
    for s, d in traces.items():
        s_int = int(s)
        b = base_res[s_int]
        out.write("="*80 + "\n")
        out.write(f"SEED {s}:\n")
        out.write(f"  BASELINE: WON={b['won']}, Ante={b['ante']}, $={b['dollars']}, Rerolls={b['stats']['rerolls']}, Spent=${b['stats']['money_spent']}\n")
        out.write(f"    Jokers held at end: {b['jokers']}\n")
        out.write(f"  GEN5:     WON={d['won']}, Died Ante={d['ante']} Blind={d['death_blind']} ({d['death_kind']}), $={d['dollars']}, Rerolls={d['rerolls']}, Spent=${d['money_spent']}\n")
        out.write(f"    Jokers at death: {d['jokers']}\n")
        out.write(f"    Target hand: {d['target_hand']}\n")
        out.write(f"    Planets: {d['planets']}\n")
        out.write(f"    Tarots: {d['tarots']}\n")
        out.write("  Gen5 Last Actions in Shop:\n")
        for t in d['trace_tail']:
            out.write(f"    {t}\n")
        out.write("  Gen5 Last Played Hands:\n")
        for h in d['death_round_hands']:
            out.write(f"    {h}\n")
        out.write("\n")

print("Wrote seeds_analysis.txt")
