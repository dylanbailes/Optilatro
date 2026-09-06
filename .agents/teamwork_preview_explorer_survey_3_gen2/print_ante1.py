import json

with open("D:/Optilatro/vendor/balatro-rl/results/goal_iter7_final_D.json", "r", encoding="utf-8") as f:
    results = json.load(f)["heuristic_v10"]["results"]

ante1_deaths = [r for r in results if r.get("ante") == 1 and not r.get("won")]
for r in sorted(ante1_deaths, key=lambda x: x["seed"]):
    seed = r["seed"]
    blind = {0: "Small (300)", 1: "Big (450)", 2: "Boss (600+)"}.get(r.get("death_blind"), str(r.get("death_blind")))
    kind = r.get("death_kind")
    jokers = r.get("jokers", [])
    plays = r.get("stats", {}).get("co_owned", [])
    best = r.get("stats", {}).get("best_score")
    print(f"Seed {seed:3d} | Blind: {blind:15s} | Jokers: {jokers} | Best: {best}")
    for p in plays:
        if p[0] == 1:
            print(f"    play: hand={p[1]:15s} jokers={p[2]} score={p[3]}")
