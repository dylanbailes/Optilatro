import sys
from pathlib import Path
sys.path.insert(0, str(Path('vendor/balatro-rl').resolve()))

from balatro_sim.game import BalatroGame
from balatro_sim.agent_v9 import joker_value, reference_hand
from balatro_sim.agent_v10 import _v10_worst_joker_idx

g = BalatroGame(seed=80, rng_mode='seed')
# Let's inspect joker_value of j_blueprint
ref = reference_hand(g)
print("joker_value of blueprint:", joker_value(g, "j_blueprint", None, ref))
print("joker_value of brainstorm:", joker_value(g, "j_brainstorm", None, ref))
