import json

with open("vendor/balatro-rl/results/bench_0_299_search_shop_v10_gen5.json") as f:
    d = json.load(f)

k = list(d.keys())[0]
results = d[k]["results"]

for jk in ["j_duo", "j_order", "j_family"]:
    print(f"\n==================== {jk} ====================")
    runs = [r for r in results if jk in str(r.get("jokers", []))]
    for r in runs:
        seed = r["seed"]
        ante = r["ante"]
        blind = r.get("death_blind")
        jokers = r["jokers"]
        stats = r.get("stats", {})
        co_owned = stats.get("co_owned", [])
        # find when jk was acquired
        first_ante = None
        for entry in co_owned:
            # entry: [ante, hand_type, jokers_list, score]
            if len(entry) >= 3 and jk in entry[2]:
                first_ante = entry[0]
                break
        planets_used = [c[1] for c in stats.get("consumable_uses", []) if c[1].startswith("pl_")]
        hands_played = [c[1] for c in co_owned if len(c) >= 3 and jk in c[2]]
        print(f"Seed {seed:3d}: Died Ante {ante} ({blind}) | Acquired Ante {first_ante} | Final Jokers: {jokers}")
        print(f"   Planets used: {planets_used}")
        print(f"   Hands played with {jk}: {set(hands_played)}")
