import sys
sys.path.insert(0, 'vendor/balatro-rl')
from balatro_sim.game import BalatroGame, State
from balatro_sim.agent_v10 import HeuristicV10

for seed in [205, 275]:
    g = BalatroGame(seed=seed, rng_mode="seed")
    p = HeuristicV10(params={"ante1_pace_rule": False})
    step = 0
    while g.state != State.GAME_OVER and g.ante <= 1 and step < 50:
        act = p.decide(g)
        g.step(act)
        step += 1
    print(f"Seed {seed} with pace_rule=False -> state={g.state.name}, ante={g.ante}, blind_idx={g.blind_idx}, scored={g.chips_scored}")
