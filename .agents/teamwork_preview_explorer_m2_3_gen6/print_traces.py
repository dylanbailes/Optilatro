import json

with open('.agents/teamwork_preview_explorer_m2_3_gen6/trace_results.json', 'r') as f:
    traces = json.load(f)

for s, d in traces.items():
    print("="*80)
    print(f"SEED {s}: won={d['won']}, ante={d['ante']}, blind={d['death_blind']} ({d['death_kind']}), $={d['dollars']}")
    print(f"Jokers at death: {d['jokers']}")
    print(f"Target hand: {d['target_hand']}")
    print(f"Rerolls: {d['rerolls']}, Money Spent: ${d['money_spent']}")
    print(f"Tarots used: {d['tarots']}")
    print(f"Planets used: {d['planets']}")
    print("Last actions in shop:")
    for t in d['trace_tail']:
        print("  ", t)
    print("Last hands played in round:")
    for h in d['death_round_hands']:
        print("  ", h)
