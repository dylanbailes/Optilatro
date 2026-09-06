"""tests/test_challenger_m2_gen4.py — Empirical Challenger Test Suite for M2.

Tests:
1. Discard Deadlock:
   Holding Faceless Joker and Green Joker with discards_left == 0.
   Verify agent_v10.decide() never chooses DiscardAction across varied hands and game states.
2. Scaling Safety:
   Stress-test _find_scaling_action across boundary edge cases:
   - 1 hand left (must return None)
   - 2 hands left (must return None)
   - Ante 1 (must return None)
   - Dangerous bosses (bl_needle, bl_mouth, etc. must return None)
   - Hand that cannot beat blind without using all cards:
     Empirical test to verify if Tier S2 risks losing the round.
3. Blueprint/Brainstorm Shop Swapping:
   When Blueprint or Brainstorm appears in the shop with 5/5 jokers,
   ranking and counterfactual swap execute cleanly without throwing exceptions.
"""
import copy
import math
import os
import sys
import pytest

# Ensure vendor/balatro-rl and tools are in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "vendor", "balatro-rl")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from balatro_sim.card import Card
from balatro_sim.game import BalatroGame, State
from balatro_sim.shop import ShopItem
from balatro_sim.jokers.base import JokerInstance
from balatro_sim.agent_v9 import scored_plays, reference_hand, forecast_beatable, ACTIVE_PARAMS
import balatro_sim.agent_v10 as v10
from balatro_sim.agent_v10 import (
    HeuristicV10,
    SearchShopV10,
    _find_scaling_action,
    _v10_rank_shop_items,
    SCALING_BANNED_BOSSES,
)


class TestDiscardDeadlock:
    """Simulate blind state holding Faceless Joker and Green Joker with discards_left == 0.
    Verify agent_v10.decide() never chooses DiscardAction.
    """

    @pytest.mark.parametrize("pol_cls", [HeuristicV10, SearchShopV10])
    @pytest.mark.parametrize("hand_faces", [0, 3, 5])
    @pytest.mark.parametrize("ante", [1, 2, 5, 8])
    @pytest.mark.parametrize("hands_left", [1, 2, 3, 4])
    def test_no_discard_when_zero_discards_left(self, pol_cls, hand_faces, ante, hands_left):
        g = BalatroGame(seed=42, rng_mode="seed")
        g.reset()
        g.state = State.BLIND_SELECT
        g.step({"type": "play_blind"})

        g.ante = ante
        g.hands_left = hands_left
        g.discards_left = 0
        g.chips_scored = 0
        g.current_blind.chips_target = 1000

        g.jokers = [
            JokerInstance("j_faceless", game=g),
            JokerInstance("j_green_joker", game=g),
        ]

        if hand_faces == 0:
            g.hand = [Card(r, "Hearts") for r in range(2, 10)]
        elif hand_faces == 3:
            g.hand = [Card(11, "Hearts"), Card(12, "Spades"), Card(13, "Clubs")] + [Card(r, "Diamonds") for r in range(2, 7)]
        elif hand_faces == 5:
            g.hand = [Card(11, "Hearts"), Card(12, "Spades"), Card(13, "Clubs"), Card(11, "Diamonds"), Card(12, "Clubs")] + [Card(r, "Hearts") for r in range(2, 5)]

        pol = pol_cls()
        action = pol.decide(g)

        assert action.get("type") != "discard", (
            f"{pol_cls.__name__} selected DiscardAction when discards_left == 0! "
            f"Hand faces: {hand_faces}, Ante: {ante}, Hands left: {hands_left}, Action: {action}"
        )
        assert action.get("type") in ("play", "use"), (
            f"Expected play or consumable action, got {action}"
        )


class TestScalingSafetyEdgeCases:
    """Test _find_scaling_action across edge cases:
    - 1 hand left
    - 2 hands left
    - Ante 1
    - Dangerous bosses
    - Hand that cannot beat blind without using all cards
    """

    def _setup_scaling_game(self, ante=2, hands_left=3, boss_key="bl_small"):
        g = BalatroGame(seed=42, rng_mode="seed")
        g.reset()
        g.state = State.BLIND_SELECT
        g.step({"type": "play_blind"})
        g.ante = ante
        g.hands_left = hands_left
        g.discards_left = 0
        g.chips_scored = 0
        g.hands_played = 0
        g.current_blind.chips_target = 1000
        g.current_blind.boss_key = boss_key
        g.jokers = [JokerInstance("j_green_joker", game=g)]
        g.hand = [Card(14, "Spades"), Card(13, "Spades"), Card(12, "Spades"), Card(11, "Spades"), Card(10, "Spades")]
        return g

    def test_one_hand_left_returns_none(self):
        g = self._setup_scaling_game(hands_left=1)
        plays = scored_plays(g, topk=ACTIVE_PARAMS["eval_topk_play"])
        act = _find_scaling_action(g, g.hand, plays, 1.0)
        assert act is None, f"Expected None when hands_left == 1, got {act}"

    def test_two_hands_left_returns_none(self):
        g = self._setup_scaling_game(hands_left=2)
        plays = scored_plays(g, topk=ACTIVE_PARAMS["eval_topk_play"])
        act = _find_scaling_action(g, g.hand, plays, 1.0)
        assert act is None, f"Expected None when hands_left == 2, got {act}"

    def test_ante_one_returns_none(self):
        g = self._setup_scaling_game(ante=1, hands_left=4)
        plays = scored_plays(g, topk=ACTIVE_PARAMS["eval_topk_play"])
        act = _find_scaling_action(g, g.hand, plays, 1.0)
        assert act is None, f"Expected None when ante == 1, got {act}"

    @pytest.mark.parametrize("banned_boss", sorted(list(SCALING_BANNED_BOSSES)))
    def test_dangerous_bosses_return_none(self, banned_boss):
        g = self._setup_scaling_game(ante=3, hands_left=3, boss_key=banned_boss)
        plays = scored_plays(g, topk=ACTIVE_PARAMS["eval_topk_play"])
        act = _find_scaling_action(g, g.hand, plays, 1.0)
        assert act is None, f"Expected None against banned boss {banned_boss}, got {act}"

    def test_hand_cannot_beat_blind_at_all_returns_none(self):
        g = self._setup_scaling_game(ante=2, hands_left=3)
        g.current_blind.chips_target = 100000  # unmeetable target
        plays = scored_plays(g, topk=ACTIVE_PARAMS["eval_topk_play"])
        act = _find_scaling_action(g, g.hand, plays, 1.0)
        assert act is None, f"Expected None when hand cannot clear blind, got {act}"

    def test_hand_requires_all_cards_tier_s2_failure_mode(self):
        """CRITICAL FAILURE MODE REPRODUCTION:
        When player holds a 5-card winning hand (score >= target), but no cards outside
        the winning hand can clear, Tier S2 erroneously breaks the winning hand to
        scale Green Joker (+20 scale_val), resulting in a game loss.
        """
        g = BalatroGame(seed=42, rng_mode="seed")
        g.reset()
        g.state = State.BLIND_SELECT
        g.step({"type": "play_blind"})

        g.ante = 2
        g.hands_left = 3
        g.discards_left = 0
        g.chips_scored = 0
        g.hands_played = 0

        # Blind target: 1000 chips
        g.current_blind.chips_target = 1000
        g.jokers = [JokerInstance("j_green_joker", game=g)]

        # Hand has 5 cards forming Royal Flush scoring 1359 chips (> 1000)
        g.hand = [Card(14, "Spades"), Card(13, "Spades"), Card(12, "Spades"), Card(11, "Spades"), Card(10, "Spades")]
        # Deck has only low rank cards that score < 250 chips per hand
        g.deck = [Card(r, s) for r in (2, 3, 4) for s in ("Hearts", "Clubs", "Diamonds")]

        plays = scored_plays(g, topk=ACTIVE_PARAMS["eval_topk_play"])
        assert plays[0][0] >= 1000, f"Setup error: Royal Flush should score >= 1000, got {plays[0][0]}"

        # Calling _find_scaling_action:
        act = _find_scaling_action(g, g.hand, plays, 1.0)

        # Tier S1 disjoint check should NOT allow scaling here because all 5 cards
        # are required for the winning hand (non_k_indices is empty).
        # But Tier S2 triggers and breaks the Royal Flush!
        # If act is returned, let's step the policy through the round and record outcome.
        if act is not None:
            pol = HeuristicV10()
            # Step the round to completion
            while g.state == State.SELECTING_HAND and g.hands_left > 0:
                step_act = pol.decide(g)
                g.step(step_act)

            # Check whether the game survived or lost
            survived = (g.state != State.GAME_OVER)
            # This assertion documents whether scaling risked/caused losing the round:
            assert survived, (
                f"SCALING SAFETY VIOLATION: Agent broke a 100% winning hand ({plays[0][0]} >= 1000) "
                f"to scale a joker (act={act}), and subsequently died (State.GAME_OVER, "
                f"chips_scored={g.chips_scored}/{g.current_blind.chips_target})!"
            )


class TestBlueprintBrainstormShopSwapping:
    """Verify that when Blueprint or Brainstorm appears in the shop with 5/5 jokers,
    ranking and counterfactual swap execute cleanly without throwing exceptions.
    """

    @pytest.mark.parametrize("premier_key", ["j_blueprint", "j_brainstorm"])
    def test_ranking_and_counterfactual_swap_execution(self, premier_key):
        g = BalatroGame(seed=123, rng_mode="seed")
        g.reset()
        g.state = State.SHOP
        g.ante = 5
        g.dollars = 25
        g.joker_slots = 5
        g.jokers = [
            JokerInstance("j_joker", game=g),
            JokerInstance("j_greedy_joker", game=g),
            JokerInstance("j_droll", game=g),
            JokerInstance("j_half", game=g),
            JokerInstance("j_egg", game=g),  # dead econ joker to sell
        ]
        g.current_shop = [
            ShopItem("joker", premier_key, premier_key, 10),
            ShopItem("tarot", "c_fool", "The Fool", 3),
        ]

        ref = reference_hand(g)
        surplus = forecast_beatable(g, ACTIVE_PARAMS["tilt_surplus_margin"], ref)

        # 1. Ranking executes cleanly
        buys, need_sell = _v10_rank_shop_items(g, ref, surplus)
        assert need_sell is not None, f"Expected need_sell to be populated for {premier_key}"
        assert need_sell[1] == 4, f"Expected worst joker index 4 (j_egg) to be selected for sell, got {need_sell[1]}"

        # 2. SearchShopV10 decides counterfactual swap
        agent = SearchShopV10()
        act1 = agent.decide(g)
        assert act1.get("type") == "sell_joker", f"Expected sell_joker, got {act1}"
        assert act1.get("joker_idx") == 4, f"Expected to sell j_egg at index 4, got {act1}"

        # 3. Step sell and verify buy of premier joker
        g.step(act1)
        act2 = agent.decide(g)
        assert act2.get("type") == "buy", f"Expected buy action on step 2, got {act2}"
        assert act2.get("item_idx") == 0, f"Expected to buy premier joker at item_idx 0, got {act2}"

        # 4. Step buy and verify final joker inventory
        g.step(act2)
        joker_keys = [j.key for j in g.jokers]
        assert premier_key in joker_keys, f"Expected {premier_key} in jokers, got {joker_keys}"
        assert len(g.jokers) == 5, f"Expected 5 jokers, got {len(g.jokers)}"
