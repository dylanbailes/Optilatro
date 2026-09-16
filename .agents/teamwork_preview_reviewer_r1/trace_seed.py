import sys
from pathlib import Path
sys.path.insert(0, str(Path("vendor/balatro-rl").resolve()))

from balatro_sim.game import BalatroGame
from balatro_sim.rollout import rollout
from balatro_sim.agent_v10 import SearchShopV10
from balatro_sim.agent_v11 import SearchShopV11

def test_seed(seed):
    g10 = BalatroGame(seed=seed, rng_mode="seed")
    p10 = SearchShopV10(lookahead=False)
    r10 = rollout(g10, p10)

    g11 = BalatroGame(seed=seed, rng_mode="seed")
    p11 = SearchShopV11(lookahead=False)
    r11 = rollout(g11, p11)

    print(f"Seed {seed}:")
    print(f"  V10: won={r10['won']} ante={r10['ante']} jokers={r10['jokers']} steps={r10['steps']}")
    print(f"  V11: won={r11['won']} ante={r11['ante']} jokers={r11['jokers']} steps={r11['steps']}")

test_seed(10503)
