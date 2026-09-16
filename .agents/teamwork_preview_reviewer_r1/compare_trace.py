import sys
from pathlib import Path
sys.path.insert(0, str(Path("vendor/balatro-rl").resolve()))

from balatro_sim.game import BalatroGame, State
from balatro_sim.agent_v10 import SearchShopV10
from balatro_sim.agent_v11 import SearchShopV11

def trace_shops(policy_cls, seed, name):
    game = BalatroGame(seed=seed, rng_mode="seed")
    agent = policy_cls(lookahead=False)
    steps = 0
    print(f"\n=== TRACING {name} on SEED {seed} ===")
    while not (game.state == State.GAME_OVER or getattr(game, "won", False)) and steps < 600:
        steps += 1
        st = game.state
        act = agent.decide(game)
        if st == State.SHOP:
            j_keys = [j.key for j in game.jokers]
            if act.get("type") != "leave_shop":
                shop_items = [(it.kind, it.key) for it in game.current_shop if not it.sold]
                print(f"Ante {game.ante} b_idx {game.blind_idx} $ {game.dollars}: act={act} shop={shop_items} jokers={j_keys}")
        elif st == State.BOOSTER_OPEN:
            print(f"Ante {game.ante} b_idx {game.blind_idx} $ {game.dollars}: BOOSTER choices={game.booster_choices} act={act}")
        game.step(act)
    print(f"{name} ended: won={game.won} ante={game.ante} jokers={[j.key for j in game.jokers]}")

trace_shops(SearchShopV10, 10503, "V10")
trace_shops(SearchShopV11, 10503, "V11")
