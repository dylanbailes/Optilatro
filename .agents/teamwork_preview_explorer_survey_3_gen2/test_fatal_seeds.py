import sys
sys.path.insert(0, "D:/Optilatro/vendor/balatro-rl")

from balatro_sim.agent_v10 import HeuristicV10, SearchShopV10
from balatro_sim.game import BalatroGame
from balatro_sim.rollout import rollout

print("Testing Seed 205 and 275...")
for seed in [205, 275]:
    for name, policy_cls in [("HeuristicV10", HeuristicV10), ("SearchShopV10", SearchShopV10)]:
        game = BalatroGame(seed=seed, rng_mode="seed")
        policy = policy_cls()
        res = rollout(game, policy)
        print(f"Seed {seed:3d} with {name:15s}: Won={res['won']}, Final Ante={res['ante']}, DeathBlind={res.get('death_blind')}, DeathKind={res.get('death_kind')}, Steps={res['steps']}")
