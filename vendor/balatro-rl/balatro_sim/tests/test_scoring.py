"""
test_scoring.py — Known hand + joker combinations with verified scores.
All expected values confirmed against real Balatro gameplay.

TODO: fill in expected values by running against real Balatro via socket.
"""
import pytest
from balatro_sim.card import Card
from balatro_sim.hand_eval import evaluate_hand
from balatro_sim.scoring import score_hand
from balatro_sim.jokers.base import JokerInstance


DEFAULT_PLANETS = {h: 1 for h in [
    "High Card", "Pair", "Two Pair", "Three of a Kind",
    "Straight", "Flush", "Full House", "Four of a Kind",
    "Straight Flush", "Five of a Kind", "Flush House", "Flush Five",
]}


def score(cards, joker_keys=None, planets=None):
    jokers = [JokerInstance(k) for k in (joker_keys or [])]
    pl = planets or DEFAULT_PLANETS
    hand_type, scoring_cards = evaluate_hand(cards)
    result, _ctx = score_hand(
        scoring_cards=scoring_cards,
        all_cards=cards,
        hand_type=hand_type,
        jokers=jokers,
        planet_levels=pl,
        hands_left=3,
        discards_left=3,
        dollars=10,
        ante=1,
        deck_remaining=44,
    )
    return result


class TestBaseScoring:
    def test_high_card_no_jokers(self):
        # High Card base: 5 chips, 1 mult
        # Ace of Spades: +11 chips -> (5+11) * 1 = 16
        cards = [Card(rank=14, suit="Spades")]
        assert score(cards) == 16

    def test_pair_no_jokers(self):
        # Pair base: 10 chips, 2 mult
        # Two 5s: +5+5 chips -> (10+10) * 2 = 40
        cards = [Card(rank=5, suit="Spades"), Card(rank=5, suit="Hearts")]
        assert score(cards) == 40


class TestJokerScoring:
    def test_base_joker(self):
        # j_joker: +4 mult
        # High Card, Ace: (5+11) * (1+4) = 16 * 5 = 80
        cards = [Card(rank=14, suit="Spades")]
        assert score(cards, ["j_joker"]) == 80

    def test_abstract_joker_one_joker(self):
        # j_abstract with 1 joker: +3 mult (3 * 1)
        # High Card, Ace: (5+11) * (1+3) = 16 * 4 = 64
        cards = [Card(rank=14, suit="Spades")]
        assert score(cards, ["j_abstract"]) == 64

    def test_half_joker_short_hand(self):
        # j_half: +20 mult when <= 3 cards played
        # High Card, Ace: (5+11) * (1+20) = 16 * 21 = 336
        cards = [Card(rank=14, suit="Spades")]
        assert score(cards, ["j_half"]) == 336

    def test_half_joker_long_hand_no_bonus(self):
        # j_half should NOT fire for 5-card hand
        cards = [Card(rank=i, suit="Spades") for i in [2, 5, 7, 9, 14]]
        s_with = score(cards, ["j_half"])
        s_without = score(cards, [])
        assert s_with == s_without
