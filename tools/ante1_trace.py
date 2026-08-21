import pathlib, sys, json
ROOT = pathlib.Path(__file__).resolve().parent.parent
VENDOR = ROOT / "vendor" / "balatro-rl"
sys.path.insert(0, str(VENDOR))

from balatro_sim.game import BalatroGame, State
from balatro_sim.agent_v10 import HeuristicV10
from balatro_sim.shop import JOKER_CATALOGUE

death_seeds = [0, 50, 52, 54, 63]
for seed in death_seeds:
    print(f"\n=== Seed {seed} STEP TRACE ===")
    game = BalatroGame(seed=seed, rng_mode="seed")
    pol = HeuristicV10()
    # Hook decide to log
    orig_decide = pol.decide
    def logged_decide(g):
        # Log state before decision
        if g.state == State.BLIND_SELECT:
            print(f" BLIND_SELECT ante {g.ante} blind {g.blind_idx} {g.current_blind.kind} chips {g.current_blind.chips_target} tag {g.current_tag} dollars {g.dollars} jokers {[j.key for j in g.jokers]}")
        elif g.state == State.SELECTING_HAND:
            from balatro_sim.agent_v9 import scored_plays, best_play_score
            plays = scored_plays(g)
            best = plays[0][0] if plays else 0
            remaining = g.current_blind.chips_target - g.chips_scored
            print(f" SELECTING_HAND ante {g.ante} {g.current_blind.kind} hands {g.hands_left} discards {g.discards_left} chips {g.chips_scored}/{g.current_blind.chips_target} remaining {remaining} best_play {best} hand {[ (c.rank,c.suit) for c in g.hand[:3]]}...")
        elif g.state == State.SHOP:
            print(f" SHOP ante {g.ante} dollars {g.dollars} jokers {[j.key for j in g.jokers]} shop {[(it.kind,it.key,it.price) for it in g.current_shop]}")
        elif g.state == State.BOOSTER_OPEN:
            print(f" BOOSTER_OPEN choices {g.booster_choices[:2]} picks {g.booster_picks_remaining}")
        elif g.state == State.ROUND_EVAL:
            print(f" ROUND_EVAL chips {g.chips_scored} dollars {g.dollars}")
        return orig_decide(g)
    pol.decide = logged_decide
    # Run step loop manually to capture per step
    obs = game._obs()
    steps=0
    while not obs.done and steps<50:
        act = pol.decide(game)
        print(f"  -> act {act}")
        obs = game.step(act)
        steps+=1
        if game.state == State.GAME_OVER:
            print(f" GAME_OVER won {obs.won} ante {game.ante} dollars {game.dollars} jokers {[j.key for j in game.jokers]}")
            break
        if game.ante>1 and obs.won==False and game.ante==2:
            # survived ante1
            break
    print(f" Final: won {obs.won} ante {game.ante} jokers {[j.key for j in game.jokers]} money {game.dollars} stats {game.run_stats['jokers_bought']} packs {game.run_stats['packs_bought']}")
