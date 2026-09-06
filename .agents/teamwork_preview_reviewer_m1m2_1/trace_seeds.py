import sys
sys.path.insert(0, 'vendor/balatro-rl')
from balatro_sim.game import BalatroGame, State
from balatro_sim.agent_v10 import HeuristicV10, SearchShopV10

for seed in [205, 275]:
    print(f"=== TRACING SEED {seed} ===")
    g = BalatroGame(seed=seed, rng_mode="seed")
    p = HeuristicV10()
    step = 0
    while g.state != State.GAME_OVER and g.ante <= 1 and step < 50:
        act = p.decide(g)
        tgt = g.current_blind.chips_target if g.current_blind else 0
        print(f"Step {step:02d}: state={g.state.name}, ante={g.ante}, blind_idx={g.blind_idx}, scored={g.chips_scored}/{tgt}, hands={g.hands_left}, discards={g.discards_left}, act={act}")
        g.step(act)
        step += 1
    print(f"Final: state={g.state.name}, ante={g.ante}, blind_idx={g.blind_idx}, scored={g.chips_scored}\n")
