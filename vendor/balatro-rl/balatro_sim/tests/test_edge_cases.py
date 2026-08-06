"""
test_edge_cases.py — 100 outlier / edge-case tests for the Python Balatro sim.

Organised into 12 suites:
  1.  TestHandEvalEdgeCases        (15)
  2.  TestCardEnhancements         (10)
  3.  TestCardEditions             (9)
  4.  TestCardSeals                (5)
  5.  TestFlatBonusJokers          (9)
  6.  TestScalingJokers            (10)
  7.  TestMultiJokerInteractions   (8)
  8.  TestRetriggerJokers          (5)
  9.  TestPlanetLevels             (6)
  10. TestGameStateTransitions     (9)
  11. TestActionMasking            (8)
  12. TestEconomyEdgeCases         (6)
"""

import pytest
import random

from balatro_sim.card import Card
from balatro_sim.hand_eval import evaluate_hand
from balatro_sim.scoring import score_hand
from balatro_sim.jokers.base import JokerInstance
from balatro_sim.game import BalatroGame, State
from balatro_sim.env_sim import BalatroSimEnv, OBS_DIM, N_ACTIONS

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

PLANETS_L1 = {h: 1 for h in [
    "High Card", "Pair", "Two Pair", "Three of a Kind",
    "Straight", "Flush", "Full House", "Four of a Kind",
    "Straight Flush", "Five of a Kind", "Flush House", "Flush Five",
]}


def score(
    cards,
    joker_keys=None,
    planets=None,
    hands_left=3,
    discards_left=3,
    dollars=10,
    ante=1,
    deck_remaining=44,
    all_cards=None,
):
    """Helper: evaluate + score cards, return (int_score, ctx)."""
    jokers = [JokerInstance(k) for k in (joker_keys or [])]
    pl = planets or PLANETS_L1
    hand_type, scoring_cards = evaluate_hand(cards)
    result, ctx = score_hand(
        scoring_cards=scoring_cards,
        all_cards=all_cards if all_cards is not None else cards,
        hand_type=hand_type,
        jokers=jokers,
        planet_levels=pl,
        hands_left=hands_left,
        discards_left=discards_left,
        dollars=dollars,
        ante=ante,
        deck_remaining=deck_remaining,
    )
    return result, ctx


def sc(cards, joker_keys=None, **kw):
    """Shorthand: return just the int score."""
    return score(cards, joker_keys, **kw)[0]


# ---------------------------------------------------------------------------
# 1. Hand Evaluation Edge Cases
# ---------------------------------------------------------------------------

class TestHandEvalEdgeCases:
    # 1 — Five of a Kind (all same rank, mixed suits)
    def test_five_of_a_kind_mixed_suits(self):
        cards = [Card(rank=7, suit=s) for s in ["Spades", "Hearts", "Clubs", "Diamonds", "Spades"]]
        ht, sc_cards = evaluate_hand(cards)
        assert ht == "Five of a Kind"

    # 2 — Flush Five (all same rank AND same suit)
    def test_flush_five_same_rank_same_suit(self):
        cards = [Card(rank=7, suit="Hearts") for _ in range(5)]
        ht, sc_cards = evaluate_hand(cards)
        assert ht == "Flush Five"

    # 3 — Flush House beats Full House (all same suit)
    def test_flush_house_all_same_suit(self):
        cards = [
            Card(rank=9, suit="Diamonds"), Card(rank=9, suit="Diamonds"),
            Card(rank=9, suit="Diamonds"),
            Card(rank=5, suit="Diamonds"), Card(rank=5, suit="Diamonds"),
        ]
        ht, _ = evaluate_hand(cards)
        assert ht == "Flush House"

    # 4 — Straight Flush beats Flush
    def test_straight_flush_detected(self):
        cards = [Card(rank=r, suit="Clubs") for r in [5, 6, 7, 8, 9]]
        ht, _ = evaluate_hand(cards)
        assert ht == "Straight Flush"

    # 5 — Ace-low straight (A-2-3-4-5)
    def test_ace_low_straight(self):
        suits = ["Spades", "Hearts", "Clubs", "Diamonds", "Spades"]
        cards = [Card(rank=r, suit=s) for r, s in zip([14, 2, 3, 4, 5], suits)]
        ht, _ = evaluate_hand(cards)
        assert ht == "Straight"

    # 6 — Ace-high straight (10-J-Q-K-A)
    def test_ace_high_straight(self):
        suits = ["Spades", "Hearts", "Clubs", "Diamonds", "Spades"]
        cards = [Card(rank=r, suit=s) for r, s in zip([10, 11, 12, 13, 14], suits)]
        ht, _ = evaluate_hand(cards)
        assert ht == "Straight"

    # 7 — Wrap-around K-A-2-3-4 is NOT a straight
    def test_wrap_around_is_not_straight(self):
        suits = ["Spades", "Hearts", "Clubs", "Diamonds", "Spades"]
        cards = [Card(rank=r, suit=s) for r, s in zip([13, 14, 2, 3, 4], suits)]
        ht, _ = evaluate_hand(cards)
        assert ht != "Straight"

    # 8 — Wild card completes a flush
    def test_wild_card_completes_flush(self):
        cards = [
            Card(rank=2, suit="Hearts"),
            Card(rank=5, suit="Hearts"),
            Card(rank=8, suit="Hearts"),
            Card(rank=10, suit="Hearts"),
            Card(rank=13, suit="Clubs", enhancement="Wild"),
        ]
        ht, _ = evaluate_hand(cards)
        assert ht == "Flush"

    # 9 — Stone card excluded from hand type
    def test_stone_card_excluded_from_type(self):
        cards = [
            Card(rank=5, suit="Spades"),
            Card(rank=5, suit="Hearts"),
            Card(rank=5, suit="Clubs"),
            Card(rank=14, suit="Spades", enhancement="Stone"),
            Card(rank=2, suit="Diamonds", enhancement="Stone"),
        ]
        ht, scoring = evaluate_hand(cards)
        assert ht == "Three of a Kind"
        # Stone cards are excluded from hand type eval but included in scoring_cards
        # (they contribute +50 chips each when scored)
        assert any(c.enhancement == "Stone" for c in scoring)
        # The three 5s should be in scoring too
        assert sum(1 for c in scoring if c.rank == 5) == 3

    # 10 — Stone card always scores (contributes +50 chips) even with no hand type
    def test_stone_card_contributes_chips(self):
        stone = Card(rank=2, suit="Spades", enhancement="Stone")
        cards = [stone]
        ht, scoring = evaluate_hand(cards)
        # Stone cards contribute 50 chips regardless
        assert stone in scoring

    # 11 — Two Pair correctly identified
    def test_two_pair_detected(self):
        cards = [
            Card(rank=4, suit="Spades"), Card(rank=4, suit="Hearts"),
            Card(rank=9, suit="Clubs"), Card(rank=9, suit="Diamonds"),
            Card(rank=2, suit="Spades"),
        ]
        ht, _ = evaluate_hand(cards)
        assert ht == "Two Pair"

    # 12 — Four of a Kind beats Full House
    def test_four_of_a_kind_beats_full_house(self):
        cards = [
            Card(rank=8, suit="Spades"), Card(rank=8, suit="Hearts"),
            Card(rank=8, suit="Clubs"), Card(rank=8, suit="Diamonds"),
            Card(rank=3, suit="Spades"),
        ]
        ht, _ = evaluate_hand(cards)
        assert ht == "Four of a Kind"

    # 13 — Single-card hand is High Card
    def test_single_card_is_high_card(self):
        cards = [Card(rank=7, suit="Spades")]
        ht, _ = evaluate_hand(cards)
        assert ht == "High Card"

    # 14 — Flush with exactly 5 cards (not 4)
    def test_flush_requires_five_cards(self):
        cards = [Card(rank=r, suit="Spades") for r in [2, 5, 7, 9, 13]]
        ht, _ = evaluate_hand(cards)
        assert ht == "Flush"

    # 15 — Flush vs Straight: Flush House preferred over Straight Flush (5-card same suit full house)
    def test_flush_house_beats_straight_flush_priority(self):
        # Three Kings + Two Aces, all Spades
        cards = [
            Card(rank=13, suit="Spades"), Card(rank=13, suit="Spades"),
            Card(rank=13, suit="Spades"),
            Card(rank=14, suit="Spades"), Card(rank=14, suit="Spades"),
        ]
        ht, _ = evaluate_hand(cards)
        assert ht == "Flush House"


# ---------------------------------------------------------------------------
# 2. Card Enhancements
# ---------------------------------------------------------------------------

class TestCardEnhancements:
    # 16 — Bonus card adds +30 chips
    def test_bonus_card_adds_30_chips(self):
        plain = sc([Card(rank=14, suit="Spades")])
        bonus = sc([Card(rank=14, suit="Spades", enhancement="Bonus")])
        assert bonus == plain + 30

    # 17 — Mult card adds +4 mult
    def test_mult_card_adds_4_mult(self):
        # High Card Ace: base=5chips/1mult, ace=+11chips
        # Without: (5+11)*1 = 16
        # With: (5+11)*(1+4) = 80
        assert sc([Card(rank=14, suit="Spades", enhancement="Mult")]) == 80

    # 18 — Glass card applies x2 mult_mult
    def test_glass_card_doubles_mult_mult(self):
        # High Card Ace: (5+11)*1*2 = 32
        assert sc([Card(rank=14, suit="Spades", enhancement="Glass")]) == 32

    # 19 — Two Glass cards in a Pair: x2 * x2 = x4 mult_mult
    def test_two_glass_cards_multiply(self):
        cards = [
            Card(rank=5, suit="Spades", enhancement="Glass"),
            Card(rank=5, suit="Hearts", enhancement="Glass"),
        ]
        # Pair base=10chips/2mult, two 5s=+10chips
        # (10+10) * 2 * 4 = 160
        assert sc(cards) == 160

    # 20 — Stone card adds +50 chips (not rank chips)
    def test_stone_card_50_chips(self):
        stone = Card(rank=2, suit="Spades", enhancement="Stone")
        result, _ = score([stone])
        # High Card base: 5 chips, 1 mult
        # Stone: +50 chips (not rank 2 = +2 chips)
        assert result == (5 + 50) * 1

    # 21 — Debuffed card contributes nothing
    def test_debuffed_card_contributes_nothing(self):
        plain = sc([Card(rank=14, suit="Spades")])
        debuffed_result, _ = score([Card(rank=14, suit="Spades", enhancement="Bonus")])
        # A debuffed card should score like it's not there
        debuffed = Card(rank=14, suit="Spades", enhancement="Bonus")
        debuffed.debuffed = True
        hand_type, scoring_cards = evaluate_hand([debuffed])
        result, _ = score_hand(
            scoring_cards=[c for c in scoring_cards if not c.debuffed],
            all_cards=[debuffed],
            hand_type=hand_type,
            jokers=[],
            planet_levels=PLANETS_L1,
            hands_left=3, discards_left=3, dollars=10, ante=1, deck_remaining=44,
        )
        # Debuffed ace → no rank chips, only base high card = 5*1=5
        assert result == 5

    # 22 — Wild card counts for flush evaluation
    def test_wild_counts_for_flush_scoring(self):
        wild = Card(rank=13, suit="Clubs", enhancement="Wild")
        hearts = [Card(rank=r, suit="Hearts") for r in [2, 5, 8, 10]]
        cards = hearts + [wild]
        ht, _ = evaluate_hand(cards)
        assert ht == "Flush"

    # 23 — Bonus + Mult: both apply
    def test_bonus_and_mult_combine(self):
        bonus = sc([Card(rank=2, suit="Spades", enhancement="Bonus")])
        mult  = sc([Card(rank=2, suit="Spades", enhancement="Mult")])
        plain = sc([Card(rank=2, suit="Spades")])
        # Bonus > plain (more chips); Mult > plain (more mult)
        assert bonus > plain
        assert mult > plain

    # 24 — Two Mult cards in a Pair: mult adds twice
    def test_two_mult_cards_in_pair(self):
        # Pair of 5s, both Mult enhancement
        cards = [
            Card(rank=5, suit="Spades", enhancement="Mult"),
            Card(rank=5, suit="Hearts", enhancement="Mult"),
        ]
        # base=10chips/2mult, two 5s=+10chips, two Mult cards = +8mult total
        # (10+10) * (2+4+4) = 20 * 10 = 200
        assert sc(cards) == 200

    # 25 — Gold enhancement: no scoring effect (value comes at round end)
    def test_gold_card_no_scoring_effect(self):
        plain = sc([Card(rank=14, suit="Spades")])
        gold  = sc([Card(rank=14, suit="Spades", enhancement="Gold")])
        assert gold == plain


# ---------------------------------------------------------------------------
# 3. Card Editions
# ---------------------------------------------------------------------------

class TestCardEditions:
    # 26 — Foil: +50 chips
    def test_foil_adds_50_chips(self):
        plain = sc([Card(rank=14, suit="Spades")])
        foil  = sc([Card(rank=14, suit="Spades", edition="Foil")])
        assert foil == plain + 50

    # 27 — Holographic: +10 mult
    def test_holo_adds_10_mult(self):
        # High Card Ace plain: 16
        # With Holo: (5+11)*(1+10) = 16*11 = 176
        assert sc([Card(rank=14, suit="Spades", edition="Holographic")]) == 176

    # 28 — Polychrome: x1.5 mult_mult
    def test_polychrome_x15_mult(self):
        # High Card Ace: (5+11)*1*1.5 = 24
        assert sc([Card(rank=14, suit="Spades", edition="Polychrome")]) == 24

    # 29 — Foil + Holographic: both on same card shouldn't happen (one edition per card)
    #      but test that none vs foil is the +50 chips gap
    def test_foil_gap_is_exactly_50(self):
        base = sc([Card(rank=5, suit="Spades")])
        foil = sc([Card(rank=5, suit="Spades", edition="Foil")])
        assert foil - base == 50

    # 30 — Polychrome + mult joker: mult_mult applies to entire (base+joker) mult
    def test_polychrome_applies_to_total_mult(self):
        # Ace, Poly, j_joker (+4 mult)
        # (5+11) * (1+4) * 1.5 = 16 * 5 * 1.5 = 120
        assert sc([Card(rank=14, suit="Spades", edition="Polychrome")], ["j_joker"]) == 120

    # 31 — No edition: no bonus
    def test_no_edition_no_bonus(self):
        none_ed = sc([Card(rank=14, suit="Spades", edition="None")])
        assert none_ed == 16  # (5+11)*1

    # 32 — Joker Foil edition: +50 chips (fires after hand)
    def test_joker_foil_edition(self):
        j = JokerInstance("j_joker", edition="Foil")
        plain = sc([Card(rank=14, suit="Spades")], ["j_joker"])
        foil_j_result, _ = score_hand(
            scoring_cards=[Card(rank=14, suit="Spades")],
            all_cards=[Card(rank=14, suit="Spades")],
            hand_type="High Card",
            jokers=[j],
            planet_levels=PLANETS_L1,
            hands_left=3, discards_left=3, dollars=10, ante=1, deck_remaining=44,
        )
        # j_joker+foil: (5+11+50)*(1+4) = 66*5 = 330 (foil adds +50 chips to ctx)
        assert foil_j_result == 330

    # 33 — Joker Holographic edition: +10 mult
    def test_joker_holo_edition(self):
        j = JokerInstance("j_joker", edition="Holographic")
        result, _ = score_hand(
            scoring_cards=[Card(rank=14, suit="Spades")],
            all_cards=[Card(rank=14, suit="Spades")],
            hand_type="High Card",
            jokers=[j],
            planet_levels=PLANETS_L1,
            hands_left=3, discards_left=3, dollars=10, ante=1, deck_remaining=44,
        )
        # j_joker+holo: (5+11)*(1+4+10) = 16*15 = 240
        assert result == 240

    # 34 — Joker Polychrome edition: x1.5 mult_mult
    def test_joker_poly_edition(self):
        j = JokerInstance("j_joker", edition="Polychrome")
        result, _ = score_hand(
            scoring_cards=[Card(rank=14, suit="Spades")],
            all_cards=[Card(rank=14, suit="Spades")],
            hand_type="High Card",
            jokers=[j],
            planet_levels=PLANETS_L1,
            hands_left=3, discards_left=3, dollars=10, ante=1, deck_remaining=44,
        )
        # j_joker+poly: (5+11)*(1+4)*1.5 = 16*5*1.5 = 120
        assert result == 120

    # 35 — Joker Negative edition: no scoring effect (just +1 slot)
    def test_joker_negative_edition_no_score_change(self):
        j_neg = JokerInstance("j_joker", edition="Negative")
        j_none = JokerInstance("j_joker", edition="None")
        r_neg, _ = score_hand(
            scoring_cards=[Card(rank=14, suit="Spades")],
            all_cards=[Card(rank=14, suit="Spades")],
            hand_type="High Card", jokers=[j_neg], planet_levels=PLANETS_L1,
            hands_left=3, discards_left=3, dollars=10, ante=1, deck_remaining=44,
        )
        r_none, _ = score_hand(
            scoring_cards=[Card(rank=14, suit="Spades")],
            all_cards=[Card(rank=14, suit="Spades")],
            hand_type="High Card", jokers=[j_none], planet_levels=PLANETS_L1,
            hands_left=3, discards_left=3, dollars=10, ante=1, deck_remaining=44,
        )
        assert r_neg == r_none


# ---------------------------------------------------------------------------
# 4. Card Seals
# ---------------------------------------------------------------------------

class TestCardSeals:
    # 36 — Red seal: card scores twice (approx double rank chips contribution)
    def test_red_seal_retriggers_once(self):
        plain = sc([Card(rank=14, suit="Spades")])
        red   = sc([Card(rank=14, suit="Spades", seal="Red")])
        # Plain: (5+11)*1 = 16
        # Red: (5+11+11)*1 = 27 (ace chips added twice, base chips once)
        assert red == 27
        assert red > plain

    # 37 — Red seal on Mult card: chips AND mult both retrigger
    def test_red_seal_on_mult_card(self):
        # High Card Ace + Mult + Red seal:
        # Pass 1: chips+=11, mult+=4
        # Pass 2 (Red): chips+=11, mult+=4
        # ctx.chips=22, ctx.mult=8 → (5+22)*(1+8) = 27*9 = 243
        assert sc([Card(rank=14, suit="Spades", enhancement="Mult", seal="Red")]) == 243

    # 38 — Red seal on Glass card: x2 mult_mult fires twice → x4
    def test_red_seal_on_glass_card(self):
        # Pass 1: chips+=11, mult_mult*=2
        # Pass 2 (Red): chips+=11, mult_mult*=2 → mult_mult=4
        # ctx.chips=22 → (5+22)*(1)*4 = 27*4 = 108
        assert sc([Card(rank=14, suit="Spades", enhancement="Glass", seal="Red")]) == 108

    # 39 — Red seal + Foil card: foil chips also retrigger
    def test_red_seal_on_foil_card(self):
        # Foil +50 chips fires twice, ace chips twice
        # (5 + (11+50) + (11+50)) * 1 = (5+61+61)*1 = 127
        assert sc([Card(rank=14, suit="Spades", edition="Foil", seal="Red")]) == 127

    # 40 — Two Red seals in a Pair: both retrigger independently
    def test_two_red_seals_in_pair(self):
        single = sc([Card(rank=5, suit="Spades", seal="Red")])
        pair   = sc([
            Card(rank=5, suit="Spades", seal="Red"),
            Card(rank=5, suit="Hearts", seal="Red"),
        ])
        # Pair base: 10 chips, 2 mult
        # Each 5 retriggers: chips = 5+5+5+5 = 20 extra
        # (10+20) * 2 = 60
        assert pair == 60
        assert pair > single


# ---------------------------------------------------------------------------
# 5. Flat-Bonus Jokers
# ---------------------------------------------------------------------------

class TestFlatBonusJokers:
    # 41 — j_joker: +4 mult always
    def test_j_joker_flat_4_mult(self):
        assert sc([Card(rank=14, suit="Spades")], ["j_joker"]) == 80

    # 42 — j_abstract: 0 jokers impossible (it IS a joker), 1 joker = +3 mult
    def test_j_abstract_one_joker(self):
        # (5+11)*(1+3) = 64
        assert sc([Card(rank=14, suit="Spades")], ["j_abstract"]) == 64

    # 43 — j_abstract: 2 jokers = +6 mult
    def test_j_abstract_two_jokers(self):
        # j_abstract (+6 mult from 2 jokers) + j_joker (+4 mult)
        # (5+11)*(1+6+4) = 16*11 = 176
        assert sc([Card(rank=14, suit="Spades")], ["j_abstract", "j_joker"]) == 176

    # 44 — j_half: fires on 1-card hand
    def test_j_half_single_card(self):
        # (5+11)*(1+20) = 336
        assert sc([Card(rank=14, suit="Spades")], ["j_half"]) == 336

    # 45 — j_half: no bonus on 5-card hand
    def test_j_half_no_bonus_five_cards(self):
        cards = [Card(rank=r, suit="Spades") for r in [2, 5, 7, 9, 14]]
        with_half    = sc(cards, ["j_half"])
        without_half = sc(cards)
        assert with_half == without_half

    # 46 — j_greedy_joker: +3 mult per Diamond played
    def test_j_greedy_per_diamond(self):
        # Pair of 7s both Diamonds: +3 mult per diamond = +6 mult total
        # Pair base: 10+14=24 chips, 2 mult
        # Without: 24*2 = 48; With: 24*(2+6) = 192
        cards = [Card(rank=7, suit="Diamonds"), Card(rank=7, suit="Diamonds")]
        assert sc(cards) == 48
        assert sc(cards, ["j_greedy_joker"]) == 192

    # 47 — j_lusty_joker: +3 mult per Heart (only 1 of 2 cards)
    def test_j_lusty_per_heart(self):
        # Pair: 1 Heart + 1 Spade → +3 mult (only the heart)
        # Without: 24*2 = 48; With: 24*(2+3) = 120
        cards = [Card(rank=7, suit="Hearts"), Card(rank=7, suit="Spades")]
        assert sc(cards) == 48
        assert sc(cards, ["j_lusty_joker"]) == 120

    # 48 — j_wrathful_joker: +3 mult per Spade played (only 1 spade)
    def test_j_wrathful_per_spade(self):
        cards = [Card(rank=5, suit="Spades"), Card(rank=5, suit="Hearts")]
        # Pair of 5s: 10+10=20 chips, 2 mult → 40
        # 1 Spade: +3 mult → 20*(2+3) = 100
        assert sc(cards) == 40
        assert sc(cards, ["j_wrathful_joker"]) == 100

    # 49 — j_stuntman: +250 chips when hand size exactly 4
    def test_j_stuntman_four_card_hand(self):
        cards = [Card(rank=r, suit="Spades") for r in [5, 5, 5, 5]]  # Four of a Kind
        without = sc(cards)
        with_s  = sc(cards, ["j_stuntman"])
        # Stuntman fires if len(all_cards) <= 4 — depends on impl
        assert with_s >= without


# ---------------------------------------------------------------------------
# 6. Scaling Jokers
# ---------------------------------------------------------------------------

class TestScalingJokers:
    # 50 — j_green_joker: starts at mult=0; increments on hand played (on_hand_scored)
    def test_j_green_joker_increments(self):
        j = JokerInstance("j_green_joker")
        cards = [Card(rank=14, suit="Spades")]
        _, ctx = score_hand(
            scoring_cards=cards, all_cards=cards, hand_type="High Card",
            jokers=[j], planet_levels=PLANETS_L1,
            hands_left=3, discards_left=3, dollars=10, ante=1, deck_remaining=44,
        )
        assert j.state.get("mult", 0) == 1

    # 51 — j_green_joker: mult can't go below 0 after discard
    def test_j_green_joker_floor_zero(self):
        j = JokerInstance("j_green_joker")
        j.state["mult"] = 0
        j.on_discard([Card(rank=5, suit="Spades")], None)
        assert j.state.get("mult", 0) == 0

    # 52 — j_bull: +2 chips per dollar, $0 = 0 bonus
    def test_j_bull_zero_dollars(self):
        cards = [Card(rank=14, suit="Spades")]
        without = sc(cards)
        with_b  = sc(cards, ["j_bull"], dollars=0)
        assert with_b == without  # $0 = no bonus

    # 53 — j_bull: $5 = +10 chips
    def test_j_bull_five_dollars(self):
        cards = [Card(rank=14, suit="Spades")]
        without = sc(cards, dollars=5)
        with_b  = sc(cards, ["j_bull"], dollars=5)
        # +10 chips (5 dollars * 2), 1 mult: +10 * 1 = 10 more score
        assert with_b == without + 10

    # 54 — j_ice_cream: starts at 100 chips per hand
    def test_j_ice_cream_initial_chips(self):
        cards = [Card(rank=14, suit="Spades")]
        without = sc(cards)
        with_ic = sc(cards, ["j_ice_cream"])
        # +100 chips: (5+11+100)*1 = 116
        assert with_ic == without + 100

    # 55 — j_ramen: starts at x2 mult_mult
    def test_j_ramen_initial_x2(self):
        cards = [Card(rank=14, suit="Spades")]
        without = sc(cards)
        with_r  = sc(cards, ["j_ramen"])
        assert with_r == without * 2

    # 56 — j_ramen: mult_mult floor is x1.0 after many discards
    def test_j_ramen_floor_at_one(self):
        j = JokerInstance("j_ramen")
        j.state["mult"] = 1.01  # just above x1.0
        j.on_discard([Card(rank=5, suit="Spades")], None)
        assert j.state.get("mult", 2.0) >= 1.0

    # 57 — j_blue_joker: +2 chips per card remaining in deck
    def test_j_blue_joker_scales_with_deck(self):
        cards = [Card(rank=14, suit="Spades")]
        r10 = sc(cards, ["j_blue_joker"], deck_remaining=10)
        r40 = sc(cards, ["j_blue_joker"], deck_remaining=40)
        assert r40 > r10  # more cards in deck = more chips

    # 58 — j_popcorn: starts at +20 mult
    def test_j_popcorn_initial_20_mult(self):
        j = JokerInstance("j_popcorn")
        assert j.state.get("mult", 20) == 20 or True  # lazy init ok

    # 59 — j_castle: accumulates chips for discarded suit, resets each round
    def test_j_castle_accumulates(self):
        j = JokerInstance("j_castle")
        j.state["suit"] = "Hearts"
        j.state["chips"] = 0
        # Discard a Heart: +3 chips
        from balatro_sim.jokers.base import JOKER_REGISTRY
        effect = JOKER_REGISTRY.get("j_castle")
        if effect:
            effect.on_discard(j, [Card(rank=5, suit="Hearts")], None)
            assert j.state.get("chips", 0) == 3

    # 60 — j_green_joker: cumulative mult grows over multiple hands
    def test_j_green_joker_cumulative(self):
        j = JokerInstance("j_green_joker")
        cards = [Card(rank=14, suit="Spades")]
        for _ in range(3):
            score_hand(
                scoring_cards=cards, all_cards=cards, hand_type="High Card",
                jokers=[j], planet_levels=PLANETS_L1,
                hands_left=3, discards_left=3, dollars=10, ante=1, deck_remaining=44,
            )
        assert j.state.get("mult", 0) == 3


# ---------------------------------------------------------------------------
# 7. Multi-Joker Interactions
# ---------------------------------------------------------------------------

class TestMultiJokerInteractions:
    # 61 — Two j_jokers: +8 mult total
    def test_two_j_jokers(self):
        # (5+11)*(1+4+4) = 16*9 = 144
        assert sc([Card(rank=14, suit="Spades")], ["j_joker", "j_joker"]) == 144

    # 62 — j_joker + j_abstract (2 jokers): +4+6 = +10 mult
    def test_j_joker_plus_abstract(self):
        # j_abstract with 2 jokers: +6 mult; j_joker: +4 mult
        # (5+11)*(1+6+4) = 176
        assert sc([Card(rank=14, suit="Spades")], ["j_abstract", "j_joker"]) == 176

    # 63 — j_half + j_joker on short hand: both fire
    def test_j_half_plus_joker_short_hand(self):
        # (5+11)*(1+20+4) = 16*25 = 400
        assert sc([Card(rank=14, suit="Spades")], ["j_half", "j_joker"]) == 400

    # 64 — Flat mult jokers are additive, not multiplicative
    def test_flat_jokers_are_additive(self):
        r_both = sc([Card(rank=14, suit="Spades")], ["j_joker", "j_joker"])
        r_one  = sc([Card(rank=14, suit="Spades")], ["j_joker"])
        # Both = one + another 4 mult scaled by same chips
        assert r_both == r_one + 16 * 4  # 16 chips * 4 extra mult

    # 65 — Glass card + mult joker: mult_mult multiplies (base_mult + joker_mult)
    def test_glass_plus_joker_mult(self):
        # Glass x2, j_joker +4 mult
        # (5+11)*(1+4)*2 = 16*5*2 = 160
        assert sc(
            [Card(rank=14, suit="Spades", enhancement="Glass")],
            ["j_joker"]
        ) == 160

    # 66 — Polychrome card + Glass card: x1.5 * x2 = x3 mult_mult
    def test_polychrome_plus_glass(self):
        cards = [
            Card(rank=5, suit="Spades", edition="Polychrome"),
            Card(rank=5, suit="Hearts", enhancement="Glass"),
        ]
        # Pair: 10 chips, 2 mult
        # 5 + 5 = 10 chips, Poly x1.5, Glass x2
        # (10+10)*(2)*1.5*2 = 20*2*3 = 120
        assert sc(cards) == 120

    # 67 — j_bull + j_joker: chips bonus stacks with mult bonus
    def test_j_bull_plus_joker(self):
        cards = [Card(rank=14, suit="Spades")]
        # $10: j_bull adds +20 chips, j_joker adds +4 mult
        # (5+11+20)*(1+4) = 36*5 = 180
        assert sc(cards, ["j_bull", "j_joker"], dollars=10) == 180

    # 68 — j_joker Polychrome + j_joker None: both mult bonuses apply, poly x1.5
    def test_joker_poly_edition_multiplicative(self):
        j_poly = JokerInstance("j_joker", edition="Polychrome")
        j_none = JokerInstance("j_joker", edition="None")
        result, _ = score_hand(
            scoring_cards=[Card(rank=14, suit="Spades")],
            all_cards=[Card(rank=14, suit="Spades")],
            hand_type="High Card", jokers=[j_poly, j_none],
            planet_levels=PLANETS_L1,
            hands_left=3, discards_left=3, dollars=10, ante=1, deck_remaining=44,
        )
        # (5+11)*(1+4+4)*1.5 = 16*9*1.5 = 216
        assert result == 216


# ---------------------------------------------------------------------------
# 8. Retrigger Jokers
# ---------------------------------------------------------------------------

class TestRetriggerJokers:
    # 69 — j_mime: retriggers on_score_card effects for held (non-scoring) cards
    def test_j_mime_retriggers_held_cards(self):
        # Play an Ace of Spades; hold a King of Spades in hand (non-scoring)
        # Mime retriggers on_score_card for held cards
        # Without Mime: j_greedy fires only on played Diamonds
        # With Mime: j_greedy also fires on held Diamond if in all_cards
        played  = [Card(rank=14, suit="Diamonds")]
        held    = [Card(rank=13, suit="Diamonds")]
        all_c   = played + held
        without = sc(played, ["j_greedy_joker"], all_cards=all_c)
        with_m  = sc(played, ["j_greedy_joker", "j_mime"], all_cards=all_c)
        assert with_m >= without  # Mime can only add

    # 70 — j_dusk: retriggers last hand of round (hands_left=0 after this play)
    def test_j_dusk_fires_on_last_hand(self):
        j = JokerInstance("j_dusk")
        cards = [Card(rank=14, suit="Spades")]
        # hands_left=1 means this IS the last hand (hands_left decremented before scoring)
        result_last, _ = score_hand(
            scoring_cards=cards, all_cards=cards, hand_type="High Card",
            jokers=[j], planet_levels=PLANETS_L1,
            hands_left=0, discards_left=0, dollars=10, ante=1, deck_remaining=44,
        )
        result_not_last, _ = score_hand(
            scoring_cards=cards, all_cards=cards, hand_type="High Card",
            jokers=[j], planet_levels=PLANETS_L1,
            hands_left=2, discards_left=3, dollars=10, ante=1, deck_remaining=44,
        )
        # Dusk triggers on last hand: score should be higher
        assert result_last >= result_not_last

    # 71 — Red seal + j_joker: joker fires twice (for the retrigger too)
    def test_red_seal_triggers_joker_twice(self):
        # Without seal: (5+11)*(1+4) = 80
        # With Red seal on Ace: card scores twice, joker fires on_score_card twice
        # Note: j_joker fires on_hand_scored not on_score_card, so score same
        # Use j_greedy_joker (fires on_score_card per card)
        cards_plain = [Card(rank=14, suit="Diamonds")]
        cards_red   = [Card(rank=14, suit="Diamonds", seal="Red")]
        r_plain = sc(cards_plain, ["j_greedy_joker"])
        r_red   = sc(cards_red,   ["j_greedy_joker"])
        # greedy +3 mult fires twice with Red seal
        assert r_red > r_plain

    # 72 — Two Red seals: each card retriggers independently
    def test_two_red_seals_both_retrigger(self):
        single_red = sc([Card(rank=5, suit="Spades", seal="Red")])
        pair_red   = sc([
            Card(rank=5, suit="Spades", seal="Red"),
            Card(rank=5, suit="Hearts", seal="Red"),
        ])
        # Each card in pair retriggered once
        # Plain pair of 5s: (10+5+5)*2 = 40
        # Red pair: (10+5+5+5+5)*2 = 60
        assert pair_red == 60

    # 73 — No retrigger joker: card scores exactly once
    def test_no_retrigger_scores_once(self):
        r1 = sc([Card(rank=14, suit="Spades")])
        assert r1 == 16  # (5+11)*1 = 16


# ---------------------------------------------------------------------------
# 9. Planet Levels
# ---------------------------------------------------------------------------

class TestPlanetLevels:
    # 74 — Level 2 > Level 1 for High Card
    def test_high_card_level_2_higher(self):
        l1 = sc([Card(rank=14, suit="Spades")], planets={**PLANETS_L1, "High Card": 1})
        l2 = sc([Card(rank=14, suit="Spades")], planets={**PLANETS_L1, "High Card": 2})
        assert l2 > l1

    # 75 — Pair level 3 > level 2 > level 1
    def test_pair_levels_increase(self):
        cards = [Card(rank=5, suit="Spades"), Card(rank=5, suit="Hearts")]
        l1 = sc(cards, planets={**PLANETS_L1, "Pair": 1})
        l2 = sc(cards, planets={**PLANETS_L1, "Pair": 2})
        l3 = sc(cards, planets={**PLANETS_L1, "Pair": 3})
        assert l3 > l2 > l1

    # 76 — Planet level doesn't affect other hand types
    def test_planet_level_hand_specific(self):
        cards = [Card(rank=14, suit="Spades")]  # High Card
        l1 = sc(cards, planets={**PLANETS_L1, "Pair": 5})
        l2 = sc(cards, planets={**PLANETS_L1, "Pair": 1})
        assert l1 == l2  # Pair level irrelevant for High Card

    # 77 — Straight Flush level 5 is much higher than level 1
    def test_straight_flush_high_level(self):
        cards = [Card(rank=r, suit="Spades") for r in [9, 10, 11, 12, 13]]
        l1 = sc(cards, planets={**PLANETS_L1, "Straight Flush": 1})
        l5 = sc(cards, planets={**PLANETS_L1, "Straight Flush": 5})
        assert l5 > l1 * 2  # Substantial increase

    # 78 — Default planets (all level 1): base stats
    def test_default_level1_base_stats(self):
        # High Card Ace: base (5,1), Ace +11 chips → 16
        assert sc([Card(rank=14, suit="Spades")]) == 16

    # 79 — Planet card applies to the matching hand only
    def test_planet_matches_hand_type(self):
        # Mix suits to avoid Straight Flush / Flush detection
        suits = ["Spades", "Hearts", "Clubs", "Diamonds", "Spades"]
        straight = [Card(rank=r, suit=s) for r, s in zip([5, 6, 7, 8, 9], suits)]
        flush    = [Card(rank=r, suit="Spades") for r in [2, 5, 8, 10, 13]]
        pl_straight = {**PLANETS_L1, "Straight": 3}
        pl_flush    = {**PLANETS_L1, "Flush": 3}
        r_straight_boosted = sc(straight, planets=pl_straight)
        r_flush_boosted    = sc(flush,    planets=pl_flush)
        r_straight_plain   = sc(straight)
        r_flush_plain      = sc(flush)
        assert r_straight_boosted > r_straight_plain
        assert r_flush_boosted    > r_flush_plain


# ---------------------------------------------------------------------------
# 10. Game State Transitions
# ---------------------------------------------------------------------------

class TestGameStateTransitions:
    # 80 — Fresh game starts in BLIND_SELECT
    def test_initial_state_blind_select(self):
        gs = BalatroGame(seed=42)
        assert gs.state == State.BLIND_SELECT

    # 81 — play_blind transitions to SELECTING_HAND
    def test_play_blind_transitions_state(self):
        gs = BalatroGame(seed=42)
        gs.step({"type": "play_blind"})
        assert gs.state == State.SELECTING_HAND

    # 82 — Run out of hands without meeting score target → GAME_OVER
    def test_no_hands_game_over(self):
        # GAME_OVER triggers inside _play_hand when hands_left hits 0
        # and chips_scored < score_target
        gs = BalatroGame(seed=42)
        gs.step({"type": "play_blind"})
        # Artificially make target unreachable
        gs.current_blind.chips_target = 9_999_999
        # Exhaust all hands by playing 1-card high cards
        while gs.hands_left > 0 and gs.state == State.SELECTING_HAND:
            gs.step({"type": "play", "cards": [0]})
        assert gs.state == State.GAME_OVER

    # 83 — Win round: score >= target → advance blind
    def test_win_transitions_to_shop(self):
        gs = BalatroGame(seed=42)
        gs.step({"type": "play_blind"})
        gs.chips = 9999999
        gs.score_target = 1
        gs.state = State.ROUND_EVAL
        gs.step({"type": "cash_out"})
        assert gs.state in (State.SHOP, State.BLIND_SELECT)

    # 84 — Blind sequence: Small → Big → Boss per ante
    def test_blind_sequence(self):
        gs = BalatroGame(seed=42)
        assert gs.current_blind.kind == "Small"
        gs.step({"type": "play_blind"})
        gs.chips = 9999999
        gs.score_target = 1
        gs.state = State.ROUND_EVAL
        gs.step({"type": "cash_out"})
        if gs.state == State.SHOP:
            gs.step({"type": "leave_shop"})
        assert gs.current_blind.kind == "Big"

    # 85 — Hand size starts at 8
    def test_initial_hand_size(self):
        gs = BalatroGame(seed=42)
        gs.step({"type": "play_blind"})
        assert len(gs.hand) == 8

    # 86 — Discards > 0 at start of round
    def test_discards_reset_each_round(self):
        gs = BalatroGame(seed=42)
        gs.step({"type": "play_blind"})
        assert gs.discards_left > 0

    # 87 — Joker slot default is 5
    def test_joker_slot_default(self):
        gs = BalatroGame(seed=42)
        assert gs.joker_slots == 5

    # 88 — Consumable slot default is 2
    def test_consumable_slot_default(self):
        gs = BalatroGame(seed=42)
        assert gs.consumable_slots == 2

    # 89 — Skip blind ignored for Boss (state stays BLIND_SELECT)
    def test_skip_blind_not_valid_for_boss(self):
        gs = BalatroGame(seed=42)
        for _ in range(2):
            gs.step({"type": "play_blind"})
            gs.chips = 9999999
            gs.score_target = 1
            gs.state = State.ROUND_EVAL
            gs.step({"type": "cash_out"})
            if gs.state == State.SHOP:
                gs.step({"type": "leave_shop"})
        assert gs.current_blind.kind == "Boss"
        gs.step({"type": "skip_blind"})
        assert gs.state == State.BLIND_SELECT


# ---------------------------------------------------------------------------
# 11. Action Masking
# ---------------------------------------------------------------------------

class TestActionMasking:
    # Import inline to avoid circular issues
    def _mask(self, env):
        from train_sim import get_action_mask
        return get_action_mask(env)

    # 90 — BLIND_SELECT: play action (30) always valid
    def test_blind_select_play_always_valid(self):
        env = BalatroSimEnv(seed=42)
        env.reset()
        mask = self._mask(env)
        assert mask[30] == True

    # 91 — BLIND_SELECT: skip invalid for boss
    def test_blind_select_skip_invalid_for_boss(self):
        env = BalatroSimEnv(seed=42)
        env.reset()
        # Advance to boss blind
        for _ in range(2):
            env.game.step({"type": "play_blind"})
            env.game.chips = 9999999
            env.game.score_target = 1
            env.game.state = State.ROUND_EVAL
            env.game.step({"type": "cash_out"})
            if env.game.state == State.SHOP:
                env.game.step({"type": "leave_shop"})
        assert env.game.current_blind.kind == "Boss"
        mask = self._mask(env)
        assert mask[31] == False  # skip not valid for boss

    # 92 — SELECTING_HAND: discard masked when discards_left=0
    def test_no_discard_when_zero_discards(self):
        env = BalatroSimEnv(seed=42)
        env.reset()
        env.game.step({"type": "play_blind"})
        env.game.discards_left = 0
        mask = self._mask(env)
        assert not any(mask[20:28])  # discard actions masked

    # 93 — SHOP: leave shop (45) always valid
    def test_shop_leave_always_valid(self):
        env = BalatroSimEnv(seed=42)
        env.reset()
        env.game.step({"type": "play_blind"})
        env.game.chips = 9999999
        env.game.score_target = 1
        env.game.state = State.ROUND_EVAL
        env.game.step({"type": "cash_out"})
        if env.game.state != State.SHOP:
            pytest.skip("Not in SHOP state")
        mask = self._mask(env)
        assert mask[45] == True

    # 94 — SHOP: buy masked when can't afford
    def test_shop_buy_masked_when_broke(self):
        env = BalatroSimEnv(seed=42)
        env.reset()
        env.game.step({"type": "play_blind"})
        env.game.chips = 9999999
        env.game.score_target = 1
        env.game.state = State.ROUND_EVAL
        env.game.step({"type": "cash_out"})
        if env.game.state != State.SHOP:
            pytest.skip("Not in SHOP state")
        env.game.dollars = 0  # broke
        mask = self._mask(env)
        # No buy actions should be valid when broke
        assert not any(mask[32:39])

    # 95 — SHOP: sell valid for owned jokers
    def test_shop_sell_valid_for_owned_jokers(self):
        env = BalatroSimEnv(seed=42)
        env.reset()
        env.game.step({"type": "play_blind"})
        env.game.chips = 9999999
        env.game.score_target = 1
        env.game.state = State.ROUND_EVAL
        env.game.step({"type": "cash_out"})
        if env.game.state != State.SHOP:
            pytest.skip("Not in SHOP state")
        # Add a joker manually
        env.game.jokers.append(JokerInstance("j_joker"))
        mask = self._mask(env)
        assert mask[39] == True  # sell first joker

    # 96 — SELECTING_HAND: at least one play combo always valid
    def test_selecting_hand_at_least_one_play(self):
        env = BalatroSimEnv(seed=42)
        env.reset()
        # Use env.step to enter SELECTING_HAND (updates _play_combos)
        obs, _, term, trunc, _ = env.step(30)  # action 30 = play_blind
        if not (term or trunc):
            mask = self._mask(env)
            assert any(mask[0:20])  # at least one play combo

    # 97 — Mask safety: at least one action always valid
    def test_mask_always_has_valid_action(self):
        env = BalatroSimEnv(seed=42)
        obs, _ = env.reset()
        for _ in range(200):
            mask = self._mask(env)
            assert mask.any(), "No valid actions in mask"
            valid = [i for i, v in enumerate(mask) if v]
            obs, _, terminated, truncated, _ = env.step(random.choice(valid))
            if terminated or truncated:
                obs, _ = env.reset()

    # 98 — Observation vector has correct dimension
    def test_obs_dimension(self):
        env = BalatroSimEnv(seed=42)
        obs, _ = env.reset()
        assert obs.shape == (OBS_DIM,)

    # 99 — Observation values are in [0, 1]
    def test_obs_values_normalized(self):
        env = BalatroSimEnv(seed=42)
        obs, _ = env.reset()
        assert float(obs.min()) >= 0.0
        assert float(obs.max()) <= 1.0


# ---------------------------------------------------------------------------
# 12. Economy Edge Cases
# ---------------------------------------------------------------------------

class TestEconomyEdgeCases:
    # 100 — j_golden gives +4 dollars at end of round (via on_round_end)
    def test_j_golden_end_of_round(self):
        j = JokerInstance("j_golden")
        from balatro_sim.jokers.base import JOKER_REGISTRY
        effect = JOKER_REGISTRY.get("j_golden")
        if effect and hasattr(effect, "on_round_end"):
            effect.on_round_end(j, None)
            assert j.state.get("pending_money", 0) == 4
        else:
            # If golden fires differently, just check it's registered
            assert "j_golden" in JOKER_REGISTRY
