import sys
from pathlib import Path
sys.path.insert(0, str(Path('vendor/balatro-rl').resolve()))

from balatro_sim.game import BalatroGame
from balatro_sim.agent_v10 import SearchShopV10, _v10_rank_shop_items
from balatro_sim.rollout import rollout

# Let's test Seed 298 when blueprint is not bought with 0 jokers
class FixedSearchShop(SearchShopV10):
    pass

# We can monkeypatch _v10_rank_shop_items in agent_v10 to test
import balatro_sim.agent_v10 as ag10

orig_rank = ag10._v10_rank_shop_items
def custom_rank(game, ref, surplus, rerolls_used=0):
    buys, need_sell = orig_rank(game, ref, surplus, rerolls_used)
    # Filter out blueprint/brainstorm if len(game.jokers) == 0
    if len(game.jokers) == 0:
        new_buys = []
        for v, idx in buys:
            item = game.current_shop[idx]
            if item.key in ("j_blueprint", "j_brainstorm"):
                continue
            new_buys.append((v, idx))
        buys = new_buys
    return buys, need_sell

ag10._v10_rank_shop_items = custom_rank

game298 = BalatroGame(seed=298, rng_mode='seed')
policy = SearchShopV10(search_shops=1, lookahead=False)
res298 = rollout(game298, policy)
print("Seed 298 with fix:")
print("Won:", res298['won'], "Ante:", res298['ante'], "Death blind:", res298.get('death_blind'), "Dollars:", res298.get('dollars'), "Jokers:", res298.get('jokers'))
