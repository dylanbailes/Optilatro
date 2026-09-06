import json
import sys
sys.path.insert(0, "vendor/balatro-rl")
from balatro_sim.game import BalatroGame
from balatro_sim.agent_v10 import SearchShopV10
from balatro_sim.rollout import rollout

seeds = [9300, 9323, 9378, 9379, 9397, 9438, 9460, 9470, 9512, 9549, 9575, 9577]

for s in seeds:
    game = BalatroGame(seed=s, rng_mode="seed")
    policy = SearchShopV10()
    res = rollout(game, policy)
    b_name = game.current_blind.name if game.current_blind else "N/A"
    b_boss = game.current_blind.boss_key if game.current_blind else "N/A"
    target = game.current_blind.chips_target if game.current_blind else 0
    scored = game.chips_scored
    jokers = [j.key for j in game.jokers]
    print(f"Seed {s}: Blind={b_name} (boss={b_boss}) | Scored={scored}/{target} | HandsLeft={game.hands_left} | DiscardsLeft={game.discards_left} | Jokers={jokers} | Dollars=${game.dollars}")
