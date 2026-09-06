"""Check singles_window injection vs brute-force best."""
import itertools
import sys
sys.path.insert(0, "vendor/balatro-rl")

from balatro_sim.agent_v9 import (_boss_play_filter, eval_hand_score,
                                  evaluate_hand, scored_plays)
from balatro_sim.agent_v10 import HeuristicV10
from balatro_sim.game import BalatroGame, State
from balatro_sim.rollout import rollout


def full_best(game):
    hand = game.hand
    n = len(hand)
    boss = game.current_blind.boss_key if game._boss_effects_on() else ""
    best = None
    for m in range(1, min(6, n + 1)):
        for combo in itertools.combinations(range(n), m):
            cards = [hand[i] for i in combo]
            try:
                ht, sc = evaluate_hand(cards)
            except Exception:
                continue
            if boss and not _boss_play_filter(game, combo, ht, cards, boss):
                continue
            cset = set(combo)
            held = [hand[i] for i in range(n) if i not in cset]
            try:
                s = eval_hand_score(game, ht, sc, cards, held_cards=held)
            except Exception:
                continue
            if best is None or s > best[0]:
                best = (s, combo, ht)
    return best


seen = {"n": 0, "miss": 0, "hc_top": 0}
orig_decide = HeuristicV10.decide


def decide(self, game):
    if game.state == State.SELECTING_HAND and len(game.hand) >= 5:
        pl = scored_plays(game)
        fb = full_best(game)
        seen["n"] += 1
        if pl and pl[0][2] == "High Card":
            seen["hc_top"] += 1
        if fb and pl and pl[0][0] < fb[0]:
            seen["miss"] += 1
            if seen["miss"] <= 3:
                print("MISS gap=%d fb_ht=%s fb_size=%d sp_top=%d" %
                      (fb[0] - pl[0][0], fb[2], len(fb[1]), pl[0][0]))
    return orig_decide(self, game)


HeuristicV10.decide = decide

g = BalatroGame(seed=4)
rollout(g, HeuristicV10({"singles_window": True}))
print("decisions:", seen["n"], "| misses:", seen["miss"],
      "| HC as top play:", seen["hc_top"])
