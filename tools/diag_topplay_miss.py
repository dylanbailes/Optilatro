"""Diagnostic: does scored_plays' priority-pruned window contain the TRUE
best engine-scored play? Brute-force all C(n,1..5) combos at every hand
decision and compare against scored_plays top-1."""
import itertools
import sys

sys.path.insert(0, "vendor/balatro-rl")

from balatro_sim.agent_v10 import HeuristicV10
from balatro_sim.agent_v9 import (_boss_play_filter, eval_hand_score,
                                  evaluate_hand, scored_plays)
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


misses = {"n": 0, "gaps": [], "examples": []}


class Probe(HeuristicV10):
    def decide(self, game):
        if game.state == State.SELECTING_HAND and len(game.hand) >= 5:
            fb = full_best(game)
            sp = scored_plays(game)
            if fb and sp and sp[0][0] < fb[0]:
                misses["n"] += 1
                misses["gaps"].append(fb[0] - sp[0][0])
                if len(misses["examples"]) < 6:
                    misses["examples"].append(
                        (game.ante, game.current_blind.boss_key,
                         [j.key for j in game.jokers],
                         [(c.rank, c.suit, c.enhancement, c.seal)
                          for c in game.hand],
                         int(sp[0][0]), int(fb[0]), fb[2]))
        return super().decide(game)


def main():
    seeds = range(int(sys.argv[1]) if len(sys.argv) > 1 else 12)
    decisions = 0
    for seed in seeds:
        g = BalatroGame(seed=seed)
        rollout(g, Probe({"engineless_urgency_ante": 2,
                          "singles_window": True}))
        decisions += 1
    gaps = misses["gaps"]
    print("seeds:", decisions, "decisions-with-miss:", misses["n"])
    if gaps:
        gaps.sort(reverse=True)
        print("gap distribution: max %d p50 %d" %
              (gaps[0], gaps[len(gaps) // 2]))
        for e in misses["examples"]:
            print("  a%d %s jokers=%s" % (e[0], e[1], e[2]))
            print("    hand:", e[3])
            print("    scored_plays=%d true_best=%d (%s)" % (e[4], e[5], e[6]))


if __name__ == "__main__":
    main()
