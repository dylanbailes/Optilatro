import json

with open("D:/Optilatro/vendor/balatro-rl/results/goal_iter7_final_D.json", "r", encoding="utf-8") as f:
    results = json.load(f)["heuristic_v10"]["results"]

ante1_deaths = [r for r in results if r.get("ante") == 1 and not r.get("won")]
ante8_deaths = [r for r in results if r.get("ante") == 8 and not r.get("won")]
ante7_deaths = [r for r in results if r.get("ante") == 7 and not r.get("won")]

print("=== DETAILED BREAKDOWN: 14 ANTE-1 DEATHS ===")
for r in sorted(ante1_deaths, key=lambda x: x["seed"]):
    seed = r["seed"]
    blind = {0: "Small (300)", 1: "Big (450)", 2: "Boss (600+)"}.get(r.get("death_blind"), str(r.get("death_blind")))
    kind = r.get("death_kind")
    jokers = r.get("jokers", [])
    bought = r.get("stats", {}).get("jokers_bought", [])
    plays = r.get("stats", {}).get("co_owned", [])
    uses = r.get("stats", {}).get("consumable_uses", [])
    best = r.get("stats", {}).get("best_score")
    print(f"\n--- Seed {seed} ---")
    print(f"  Death on: Ante 1, {blind}, kind: {kind}")
    print(f"  Jokers owned at death: {jokers}")
    print(f"  Jokers bought total: {bought}")
    print(f"  Dollars: {r.get('dollars')}, Steps: {r.get('steps')}, Best score: {best}")
    print(f"  Consumable uses: {uses}")
    print(f"  Plays (ante, hand_name, jokers, score):")
    for p in plays:
        print(f"    {p}")

print("\n\n=== ANTE 8 NEAR MISSES (Lost on Ante 8) ===")
for r in sorted(ante8_deaths, key=lambda x: x["seed"]):
    seed = r["seed"]
    blind = {0: "Small", 1: "Big", 2: "Boss"}.get(r.get("death_blind"), str(r.get("death_blind")))
    kind = r.get("death_kind")
    jokers = r.get("jokers", [])
    best = r.get("stats", {}).get("best_score")
    print(f"Seed {seed:3d} | Blind: {blind:5s} ({kind:12s}) | BestScore: {best:10d} | Jokers: {jokers}")

print("\n\n=== ANTE 7 DEATHS COUNT ===", len(ante7_deaths))
