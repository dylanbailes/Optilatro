import sys
from pathlib import Path
ROOT = Path("D:/Optilatro")
VENDOR = ROOT / "vendor" / "balatro-rl"
sys.path.insert(0, str(VENDOR))
sys.path.insert(0, str(ROOT))

from balatro_sim.game import BalatroGame, State
from balatro_sim.agent_v10 import HeuristicV10
from balatro_sim.agent_v9 import scored_plays

for seed in [205, 275]:
    print(f"\n==================== SEED {seed} ====================")
    game = BalatroGame(seed=seed, rng_mode="seed")
    policy = HeuristicV10()

    step_cnt = 0
    while game.ante == 1 and game.blind_idx == 0 and game.state != State.GAME_OVER:
        st = game.state
        if st == State.SELECTING_HAND:
            plays = scored_plays(game)
            best_sc, best_combo, best_ht = plays[0] if plays else (0, (), "")
            target = game.current_blind.chips_target
            remaining = target - game.chips_scored
            pace = remaining / max(1, game.hands_left)
            played_cards = [game.hand[i] for i in best_combo]
            print(f"[Step {step_cnt}] Hands={game.hands_left} Discards={game.discards_left} "
                  f"Score={game.chips_scored}/{target} (Rem={remaining}, Pace={pace:.1f})")
            print(f"  Hand: {[(c.rank, c.suit[:1]) for c in game.hand]}")
            print(f"  Best play: {best_ht} score={best_sc} (cards: {[(c.rank, c.suit[:1]) for c in played_cards]})")
            act = policy.decide(game)
            print(f"  Action chosen: {act}")
            game.step(act)
        elif st == State.BLIND_SELECT:
            act = policy.decide(game)
            print(f"[Blind select] Action: {act}")
            game.step(act)
        elif st == State.ROUND_EVAL:
            print(f"[Round eval] Won blind! Scored={game.chips_scored}")
            act = policy.decide(game)
            game.step(act)
            break
        step_cnt += 1
        if game.state == State.GAME_OVER:
            print(f"[GAME OVER] Died on Ante {game.ante} Blind {game.blind_idx} ({game.current_blind.kind})! Total scored: {game.chips_scored}/{game.current_blind.chips_target}")
            break
