import sys
from pathlib import Path
sys.path.insert(0, str(Path('vendor/balatro-rl').resolve()))

from balatro_sim.game import BalatroGame
from balatro_sim.agent_v10 import SearchShopV10
from balatro_sim.rollout import rollout

game = BalatroGame(seed=298, rng_mode='seed')
policy = SearchShopV10(search_shops=1, lookahead=False)
res = rollout(game, policy)

print("Seed 298 with current code:")
print("Won:", res['won'], "Ante:", res['ante'], "Death blind:", res.get('death_blind'), "Dollars:", res.get('dollars'), "Jokers:", res.get('jokers'))
