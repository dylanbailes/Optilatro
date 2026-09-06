import json

with open("D:/Optilatro/vendor/balatro-rl/results/goal_iter7_final_D.json", "r", encoding="utf-8") as f:
    results = json.load(f)["heuristic_v10"]["results"]

wins = [r for r in results if r.get("won")]
ante1_deaths = [r for r in results if r.get("ante") == 1 and not r.get("won")]

print(f"Total Runs: {len(results)}")
print(f"Wins Count: {len(wins)}")
print("=== EXACT 20 WINS ===")
for r in wins:
    print(f"Seed {r['seed']:3d} | Steps: {r.get('steps'):3d} | $:{r.get('dollars'):2d} | Jokers: {r.get('jokers')} | BestScore: {r.get('stats', {}).get('best_score')}")

print("\n=== EXACT 14 ANTE-1 DEATHS ===")
for r in ante1_deaths:
    blind_name = {0: "Small", 1: "Big", 2: "Boss"}.get(r.get("death_blind"), str(r.get("death_blind")))
    print(f"Seed {r['seed']:3d} | Blind: {blind_name} ({r.get('death_kind')}) | Steps: {r.get('steps')} | $:{r.get('dollars')} | Jokers: {r.get('jokers')} | BestScore: {r.get('stats', {}).get('best_score')}")
