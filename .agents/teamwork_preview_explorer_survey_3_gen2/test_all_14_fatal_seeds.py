import sys
sys.path.insert(0, "D:/Optilatro/vendor/balatro-rl")

from balatro_sim.agent_v10 import HeuristicV10, SearchShopV10
from balatro_sim.game import BalatroGame
from balatro_sim.rollout import rollout

fatal_seeds = [82, 100, 118, 164, 174, 205, 224, 242, 250, 260, 262, 267, 269, 275]

print("=== EVALUATION OF ALL 14 FATAL ANTE-1 SEEDS UNDER CURRENT AGENTS ===")
for s in fatal_seeds:
    for name, policy_cls in [("HeuristicV10", HeuristicV10), ("SearchShopV10", SearchShopV10)]:
        g = BalatroGame(seed=s, rng_mode="seed")
        res = rollout(g, policy_cls())
        print(f"Seed {s:3d} | {name:15s} | Won: {str(res['won']):5s} | Ante: {res['ante']} | Blind: {res.get('death_blind')} ({res.get('death_kind')}) | Jokers: {res.get('jokers')}")
