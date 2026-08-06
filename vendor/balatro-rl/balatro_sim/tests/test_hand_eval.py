"""
test_hand_eval.py — Unit tests for hand evaluation.
All expected values verified against real Balatro.
"""
import pytest
from balatro_sim.card import Card
from balatro_sim.hand_eval import evaluate_hand


def c(rank, suit="Spades"):
    return Card(rank=rank, suit=suit)


class TestBasicHands:
    def test_high_card(self):
        hand = [c(2), c(5, "Hearts"), c(7, "Diamonds"), c(9, "Clubs"), c(11)]
        ht, _ = evaluate_hand(hand)
        assert ht == "High Card"

    def test_pair(self):
        hand = [c(5), c(5, "Hearts"), c(7), c(9), c(11)]
        ht, scoring = evaluate_hand(hand)
        assert ht == "Pair"
        assert all(card.rank == 5 for card in scoring)

    def test_two_pair(self):
        hand = [c(5), c(5, "Hearts"), c(9), c(9, "Hearts"), c(11)]
        ht, _ = evaluate_hand(hand)
        assert ht == "Two Pair"

    def test_three_of_a_kind(self):
        hand = [c(7), c(7, "Hearts"), c(7, "Diamonds"), c(2), c(4)]
        ht, _ = evaluate_hand(hand)
        assert ht == "Three of a Kind"

    def test_straight(self):
        hand = [c(5), c(6, "Hearts"), c(7, "Diamonds"), c(8, "Clubs"), c(9)]
        ht, _ = evaluate_hand(hand)
        assert ht == "Straight"

    def test_straight_wheel(self):
        hand = [c(14), c(2, "Hearts"), c(3, "Diamonds"), c(4, "Clubs"), c(5)]
        ht, _ = evaluate_hand(hand)
        assert ht == "Straight"

    def test_flush(self):
        hand = [c(2), c(5), c(8), c(11), c(13)]  # all Spades
        ht, _ = evaluate_hand(hand)
        assert ht == "Flush"

    def test_full_house(self):
        hand = [c(7), c(7, "Hearts"), c(7, "Diamonds"), c(9), c(9, "Hearts")]
        ht, _ = evaluate_hand(hand)
        assert ht == "Full House"

    def test_four_of_a_kind(self):
        hand = [c(9), c(9, "Hearts"), c(9, "Diamonds"), c(9, "Clubs"), c(2)]
        ht, _ = evaluate_hand(hand)
        assert ht == "Four of a Kind"

    def test_straight_flush(self):
        hand = [c(5), c(6), c(7), c(8), c(9)]  # all Spades
        ht, _ = evaluate_hand(hand)
        assert ht == "Straight Flush"

    def test_five_of_a_kind(self):
        # Requires Wild or modified deck — use Wild enhancement
        cards = [Card(rank=7, suit=s) for s in ["Spades", "Hearts", "Diamonds", "Clubs"]]
        wild = Card(rank=7, suit="Spades", enhancement="Wild")
        ht, _ = evaluate_hand(cards + [wild])
        assert ht == "Five of a Kind"

    def test_flush_five(self):
        hand = [c(7) for _ in range(5)]  # 5 x 7 of Spades
        ht, _ = evaluate_hand(hand)
        assert ht == "Flush Five"


class TestWildCards:
    def test_wild_completes_flush(self):
        # 4 Spades + 1 Wild should be flush
        hand = [c(2), c(5), c(8), c(11)]
        wild = Card(rank=3, suit="Hearts", enhancement="Wild")
        ht, _ = evaluate_hand(hand + [wild])
        assert ht == "Flush"


class TestStoneCards:
    def test_stone_card_excluded_from_hand_type(self):
        # Stone cards don't contribute to hand evaluation
        stone = Card(rank=7, suit="Spades", enhancement="Stone")
        hand = [c(2), c(5), c(8), c(11), stone]
        ht, _ = evaluate_hand(hand)
        assert ht == "High Card"
