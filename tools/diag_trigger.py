"""tools/diag_trigger.py — why doesn't the endgame switch fire on seed 87?"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "vendor" / "balatro-rl"))

import balatro_sim.agent_v10 as a10
from balatro_sim.agent_v9 import reference_hand, scored_plays
from balatro_sim.agent_v10 import HeuristicV10
from balatro_sim.game import BalatroGame, State

g = BalatroGame(seed=87, rng_mode="seed")
pol = HeuristicV10(params={"survive_greedy_hands": 2})
print("knob =", a10.V10_PARAMS["survive_greedy_hands"], flush=True)
while (g.state != State.GAME_OVER
       and not (g.ante == 4 and g.blind_idx == 2
                and g.state == State.SELECTING_HAND)):
    g.step(pol.decide(g))
while g.state == State.SELECTING_HAND:
    plays = scored_plays(g)
    rem = g.current_blind.chips_target - g.chips_scored
    spent = g.hands_played_blind
    if spent > 0:
        rate = g.chips_scored / spent
        proj = g.chips_scored + rate * g.hands_left
        trig = proj < rem
        print(f"hands {g.hands_left} disc {g.discards_left} rem {rem} "
              f"scored {g.chips_scored} rate {rate:.0f} proj {proj:.0f} "
              f"trig={trig}", flush=True)
    else:
        print(f"hands {g.hands_left} disc {g.discards_left} rem {rem} "
              f"opening best {plays[0][0] if plays else 0}", flush=True)
    g.step(pol.decide(g))
print("end", g.state, g.chips_scored, flush=True)
