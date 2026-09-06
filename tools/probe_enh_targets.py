"""Probe: does scoring-aware enhancement targeting fire?"""
import sys
sys.path.insert(0, "vendor/balatro-rl")

import balatro_sim.agent_v10 as A
from balatro_sim.game import BalatroGame
from balatro_sim.rollout import rollout

KEYS = ("c_empress", "c_hierophant", "c_lovers")
fires = [0]
uses = [0]
orig = A._v10_scoring_enhance_targets


def wrapped(gm, hand, key):
    r = orig(gm, hand, key)
    if r:
        fires[0] += 1
    return r


A._v10_scoring_enhance_targets = wrapped


class Probe(A.HeuristicV10):
    def decide(self, game):
        act = super().decide(game)
        if act.get("type") == "use_consumable":
            ci = act.get("consumable_idx")
            if 0 <= ci < len(game.consumable_hand) \
                    and game.consumable_hand[ci] in KEYS:
                uses[0] += 1
        return act


def main():
    for seed in range(30):
        g = BalatroGame(seed=seed)
        rollout(g, Probe({"enhance_into_play_ante": 8}))
    print("scoring-target firings over 30 seeds:", fires[0])
    print("use_consumable actions on empress/hiero/lovers:", uses[0])


if __name__ == "__main__":
    main()
