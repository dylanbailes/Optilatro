import sys
from pathlib import Path
sys.path.insert(0, str(Path('vendor/balatro-rl').resolve()))

from balatro_sim.game import BalatroGame
from balatro_sim.agent_v10 import joker_target_hand_type, portfolio_target_hand

for s in [198, 211, 131, 40, 188]:
    g = BalatroGame(seed=s, rng_mode='seed')
    # Let's see what joker_target_hand_type returns if jokers are set
