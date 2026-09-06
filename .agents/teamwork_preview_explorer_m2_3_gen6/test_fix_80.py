import sys
from pathlib import Path
sys.path.insert(0, str(Path('vendor/balatro-rl').resolve()))

from balatro_sim.game import BalatroGame
from balatro_sim.agent_v10 import SearchShopV10
from balatro_sim.rollout import rollout
import balatro_sim.agent_v10 as ag10

orig_worst = ag10._v10_worst_joker_idx

def custom_worst(game, ref=None):
    # Blueprint/Brainstorm shouldn't be sold if we have other jokers to copy
    # Give them value >= other best joker
    if not game.jokers:
        return None
    # Let's see what orig_worst does
    idx = orig_worst(game, ref)
    if idx is not None and idx < len(game.jokers):
        if game.jokers[idx].key in ("j_blueprint", "j_brainstorm") and len(game.jokers) > 1:
            # find another worst joker that is not blueprint/brainstorm
            other_indices = [i for i, j in enumerate(game.jokers) if j.key not in ("j_blueprint", "j_brainstorm")]
            if other_indices:
                return other_indices[0] # or lowest of others
    return idx

ag10._v10_worst_joker_idx = custom_worst

game80 = BalatroGame(seed=80, rng_mode='seed')
policy = SearchShopV10(search_shops=1, lookahead=False)
res80 = rollout(game80, policy)
print("Seed 80 with fix:")
print("Won:", res80['won'], "Ante:", res80['ante'], "Death blind:", res80.get('death_blind'), "Dollars:", res80.get('dollars'), "Jokers:", res80.get('jokers'))
