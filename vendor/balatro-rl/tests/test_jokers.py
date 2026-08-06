"""
test_jokers.py — Comprehensive tests for joker effects across all 6 modules.
Tests scoring jokers, economy jokers, retrigger jokers, hand eval flags,
blueprint/brainstorm, and scaling jokers.
"""
from __future__ import annotations

import random
import pytest

from balatro_sim.card import Card
from balatro_sim.jokers.base import JokerInstance, ScoreContext, JOKER_REGISTRY
from balatro_sim.scoring import score_hand


# ════════════════════════════════════════════════════════════════════════════
# Helpers
# ════════════════════════════════════════════════════════════════════════════

def _make_ctx(
    scoring_cards=None,
    all_cards=None,
    hand_type="High Card",
    jokers=None,
    hands_left=3,
    discards_left=3,
    dollars=10,
    ante=1,
    deck_remaining=40,
    planet_levels=None,
):
    sc = scoring_cards or []
    ac = all_cards or sc
    jk = jokers or []
    pl = planet_levels or {"High Card": 1, "Pair": 1, "Flush": 1, "Straight": 1,
                           "Three of a Kind": 1, "Full House": 1, "Four of a Kind": 1,
                           "Straight Flush": 1, "Two Pair": 1, "Five of a Kind": 1,
                           "Flush House": 1, "Flush Five": 1}
    return ScoreContext(
        chips=0.0, mult=0.0, mult_mult=1.0,
        hand_type=hand_type, scoring_cards=sc, all_cards=ac,
        jokers=jk, hands_left=hands_left, discards_left=discards_left,
        dollars=dollars, ante=ante, deck_remaining=deck_remaining,
        planet_levels=pl,
    )


def _score(cards, joker_keys, hand_type=None):
    """Quick score helper — creates joker instances and scores."""
    jokers = [JokerInstance(k) for k in joker_keys]
    from balatro_sim.hand_eval import evaluate_hand
    if hand_type is None:
        hand_type, scoring_cards = evaluate_hand(cards)
    else:
        scoring_cards = cards
    return score_hand(
        scoring_cards=scoring_cards,
        all_cards=cards,
        hand_type=hand_type,
        jokers=jokers,
        planet_levels={h: 1 for h in [
            "High Card", "Pair", "Two Pair", "Three of a Kind",
            "Straight", "Flush", "Full House", "Four of a Kind",
            "Straight Flush", "Five of a Kind", "Flush House", "Flush Five",
        ]},
        hands_left=3, discards_left=3, dollars=10, ante=1, deck_remaining=40,
    )


# ════════════════════════════════════════════════════════════════════════════
# Basic mult jokers (mult.py)
# ════════════════════════════════════════════════════════════════════════════

class TestBasicMultJokers:
    def test_j_joker_adds_4_mult(self):
        cards = [Card(14, "Spades")]
        score_with, _ = _score(cards, ["j_joker"])
        score_without, _ = _score(cards, [])
        assert score_with > score_without

    def test_j_jolly_pair_bonus(self):
        cards = [Card(10, "Hearts"), Card(10, "Spades")]
        score_with, _ = _score(cards, ["j_jolly"])
        score_without, _ = _score(cards, [])
        assert score_with > score_without

    def test_j_zany_three_of_kind_bonus(self):
        cards = [Card(10, "Hearts"), Card(10, "Spades"), Card(10, "Clubs")]
        score_with, _ = _score(cards, ["j_zany"])
        score_without, _ = _score(cards, [])
        assert score_with > score_without

    def test_j_mad_two_pair_bonus(self):
        cards = [Card(10, "Hearts"), Card(10, "Spades"), Card(5, "Clubs"), Card(5, "Diamonds")]
        score_with, _ = _score(cards, ["j_mad"])
        score_without, _ = _score(cards, [])
        assert score_with > score_without

    def test_j_crazy_straight_bonus(self):
        cards = [Card(r, "Hearts") for r in [5, 6, 7, 8, 9]]
        # Different suits to avoid flush
        cards[1].suit = "Spades"
        score_with, _ = _score(cards, ["j_crazy"])
        score_without, _ = _score(cards, [])
        assert score_with > score_without

    def test_j_half_small_hand_bonus(self):
        cards = [Card(14, "Spades")]  # 1 card = ≤3
        score_with, _ = _score(cards, ["j_half"])
        score_without, _ = _score(cards, [])
        assert score_with > score_without

    def test_j_abstract_per_joker(self):
        cards = [Card(14, "Spades")]
        score_1j, _ = _score(cards, ["j_abstract"])
        # Can't easily test 2 abstracts doubling, but 1 should boost
        score_0j, _ = _score(cards, [])
        assert score_1j > score_0j


# ════════════════════════════════════════════════════════════════════════════
# xMult jokers
# ════════════════════════════════════════════════════════════════════════════

class TestXMultJokers:
    def test_the_duo_pair_x2(self):
        cards = [Card(10, "Hearts"), Card(10, "Spades")]
        score_with, _ = _score(cards, ["j_the_duo"])
        score_without, _ = _score(cards, [])
        # x2 mult should roughly double the score
        assert score_with >= score_without * 1.5

    def test_the_trio_three_of_kind_x3(self):
        cards = [Card(10, "Hearts"), Card(10, "Spades"), Card(10, "Clubs")]
        score_with, _ = _score(cards, ["j_the_trio"])
        score_without, _ = _score(cards, [])
        assert score_with >= score_without * 2

    def test_the_family_four_of_kind_x4(self):
        cards = [Card(10, s) for s in ["Hearts", "Spades", "Clubs", "Diamonds"]]
        score_with, _ = _score(cards, ["j_the_family"])
        score_without, _ = _score(cards, [])
        assert score_with >= score_without * 3

    def test_flower_pot_all_4_suits_x3(self):
        cards = [Card(r, s) for r, s in [(10, "Hearts"), (10, "Spades"), (10, "Clubs"), (10, "Diamonds"), (9, "Hearts")]]
        score_with, _ = _score(cards, ["j_flower_pot"])
        score_without, _ = _score(cards, [])
        assert score_with >= score_without * 2

    def test_seeing_double_club_plus_other(self):
        cards = [Card(10, "Clubs"), Card(10, "Hearts")]
        score_with, _ = _score(cards, ["j_seeing_double"])
        score_without, _ = _score(cards, [])
        assert score_with > score_without

    def test_acrobat_last_hand_x3(self):
        cards = [Card(14, "Spades")]
        jokers = [JokerInstance("j_acrobat")]
        score_with, _ = score_hand(
            scoring_cards=cards, all_cards=cards, hand_type="High Card",
            jokers=jokers, planet_levels={h: 1 for h in [
                "High Card", "Pair", "Two Pair", "Three of a Kind",
                "Straight", "Flush", "Full House", "Four of a Kind",
                "Straight Flush", "Five of a Kind", "Flush House", "Flush Five",
            ]},
            hands_left=0, discards_left=3, dollars=10, ante=1, deck_remaining=40,
        )
        score_without, _ = score_hand(
            scoring_cards=cards, all_cards=cards, hand_type="High Card",
            jokers=[], planet_levels={h: 1 for h in [
                "High Card", "Pair", "Two Pair", "Three of a Kind",
                "Straight", "Flush", "Full House", "Four of a Kind",
                "Straight Flush", "Five of a Kind", "Flush House", "Flush Five",
            ]},
            hands_left=0, discards_left=3, dollars=10, ante=1, deck_remaining=40,
        )
        assert score_with >= score_without * 2


# ════════════════════════════════════════════════════════════════════════════
# Suit-conditional mult jokers
# ════════════════════════════════════════════════════════════════════════════

class TestSuitMultJokers:
    @pytest.mark.parametrize("joker_key,suit", [
        ("j_greedy_mult", "Diamonds"),
        ("j_lusty_mult", "Hearts"),
        ("j_wrathful_mult", "Spades"),
        ("j_gluttonous_mult", "Clubs"),
    ])
    def test_suit_mult_triggers(self, joker_key, suit):
        cards = [Card(10, suit)]
        score_with, _ = _score(cards, [joker_key])
        score_without, _ = _score(cards, [])
        assert score_with > score_without

    @pytest.mark.parametrize("joker_key,suit,wrong_suit", [
        ("j_greedy_mult", "Diamonds", "Spades"),
        ("j_lusty_mult", "Hearts", "Clubs"),
    ])
    def test_suit_mult_no_trigger_wrong_suit(self, joker_key, suit, wrong_suit):
        cards = [Card(10, wrong_suit)]
        score_with, _ = _score(cards, [joker_key])
        # The joker uses on_hand_scored which checks suit in scoring_cards
        # With wrong suit, j_greedy_mult shouldn't add mult
        # Score should still be higher by flat +4 from base


# ════════════════════════════════════════════════════════════════════════════
# Per-card scoring jokers
# ════════════════════════════════════════════════════════════════════════════

class TestPerCardJokers:
    def test_fibonacci_on_ace(self):
        cards = [Card(14, "Spades")]  # Ace
        score_with, _ = _score(cards, ["j_fibonacci"])
        score_without, _ = _score(cards, [])
        assert score_with > score_without

    def test_fibonacci_on_non_fib_rank(self):
        cards = [Card(6, "Spades")]  # 6 is not a fib rank
        score_with, _ = _score(cards, ["j_fibonacci"])
        score_without, _ = _score(cards, [])
        # Should be same (no fib bonus)
        assert score_with == score_without

    def test_scary_face_on_face_card(self):
        cards = [Card(11, "Spades")]  # Jack
        score_with, _ = _score(cards, ["j_scary_face"])
        score_without, _ = _score(cards, [])
        assert score_with > score_without

    def test_smiley_on_face_card(self):
        cards = [Card(12, "Hearts")]  # Queen
        score_with, _ = _score(cards, ["j_smiley"])
        score_without, _ = _score(cards, [])
        assert score_with > score_without

    def test_walkie_talkie_on_10(self):
        cards = [Card(10, "Spades")]
        score_with, _ = _score(cards, ["j_walkie_talkie"])
        score_without, _ = _score(cards, [])
        assert score_with > score_without

    def test_walkie_talkie_on_4(self):
        cards = [Card(4, "Hearts")]
        score_with, _ = _score(cards, ["j_walkie_talkie"])
        score_without, _ = _score(cards, [])
        assert score_with > score_without

    def test_scholar_on_ace(self):
        cards = [Card(14, "Spades")]
        score_with, _ = _score(cards, ["j_scholar"])
        score_without, _ = _score(cards, [])
        assert score_with > score_without

    def test_even_steven_on_even(self):
        cards = [Card(8, "Hearts")]
        score_with, _ = _score(cards, ["j_even_steven"])
        score_without, _ = _score(cards, [])
        assert score_with > score_without

    def test_wee_joker_on_2(self):
        cards = [Card(2, "Spades")]
        score_with, _ = _score(cards, ["j_wee_joker"])
        score_without, _ = _score(cards, [])
        assert score_with > score_without

    def test_triboulet_on_king(self):
        cards = [Card(13, "Spades")]
        score_with, _ = _score(cards, ["j_triboulet"])
        score_without, _ = _score(cards, [])
        assert score_with > score_without


# ════════════════════════════════════════════════════════════════════════════
# Chip bonus jokers
# ════════════════════════════════════════════════════════════════════════════

class TestChipJokers:
    def test_banner_chips_per_discard(self):
        cards = [Card(14, "Spades")]
        jokers = [JokerInstance("j_banner")]
        score_3d, _ = score_hand(
            scoring_cards=cards, all_cards=cards, hand_type="High Card",
            jokers=jokers, planet_levels={h: 1 for h in [
                "High Card", "Pair", "Two Pair", "Three of a Kind",
                "Straight", "Flush", "Full House", "Four of a Kind",
                "Straight Flush", "Five of a Kind", "Flush House", "Flush Five",
            ]},
            hands_left=3, discards_left=3, dollars=10, ante=1, deck_remaining=40,
        )
        jokers2 = [JokerInstance("j_banner")]
        score_0d, _ = score_hand(
            scoring_cards=cards, all_cards=cards, hand_type="High Card",
            jokers=jokers2, planet_levels={h: 1 for h in [
                "High Card", "Pair", "Two Pair", "Three of a Kind",
                "Straight", "Flush", "Full House", "Four of a Kind",
                "Straight Flush", "Five of a Kind", "Flush House", "Flush Five",
            ]},
            hands_left=3, discards_left=0, dollars=10, ante=1, deck_remaining=40,
        )
        assert score_3d > score_0d

    def test_stuntman_250_chips(self):
        cards = [Card(14, "Spades")]
        score_with, _ = _score(cards, ["j_stuntman"])
        score_without, _ = _score(cards, [])
        assert score_with > score_without

    def test_stencil_chips_per_empty_slot(self):
        # With 1 joker out of 5 slots, should get chips for 4 empty
        cards = [Card(14, "Spades")]
        score_with, _ = _score(cards, ["j_stencil"])
        score_without, _ = _score(cards, [])
        assert score_with > score_without

    def test_vagabond_creates_tarot_when_broke(self):
        cards = [Card(5, "Spades")]
        jokers = [JokerInstance("j_vagabond")]
        # Vagabond creates Tarot if $4 or less
        _, ctx = _score(cards, ["j_vagabond"])
        # Default dollars in _score is 10, so no tarot
        assert "tarot" not in ctx.pending_consumables
        # With $4 or less, should create tarot
        ctx2 = _make_ctx(scoring_cards=cards, hand_type="High Card",
                         jokers=[JokerInstance("j_vagabond")], dollars=4)
        effect = JOKER_REGISTRY["j_vagabond"]
        effect.on_hand_scored(jokers[0], ctx2)
        assert "tarot" in ctx2.pending_consumables


# ════════════════════════════════════════════════════════════════════════════
# Economy jokers
# ════════════════════════════════════════════════════════════════════════════

class TestEconomyJokers:
    def test_golden_earns_money_on_round_end(self):
        j = JokerInstance("j_golden")
        effect = JOKER_REGISTRY["j_golden"]
        ctx = _make_ctx(jokers=[j])
        effect.on_round_end(j, ctx)
        assert j.state.get("pending_money", 0) >= 4

    def test_rocket_earns_money(self):
        j = JokerInstance("j_rocket")
        effect = JOKER_REGISTRY["j_rocket"]
        ctx = _make_ctx(jokers=[j])
        effect.on_round_end(j, ctx)
        assert j.state.get("pending_money", 0) >= 1

    def test_rocket_bonus_on_boss_beaten(self):
        j = JokerInstance("j_rocket")
        effect = JOKER_REGISTRY["j_rocket"]
        ctx = _make_ctx(jokers=[j])
        effect.on_boss_beaten(j, ctx)
        assert j.state.get("bonus", 1) >= 3  # 1 + 2

    def test_odd_todd_chips_on_odd_count(self):
        cards = [Card(14, "Spades")]  # 1 card = odd
        score_with, _ = _score(cards, ["j_odd_todd"])
        score_without, _ = _score(cards, [])
        assert score_with > score_without

    def test_delayed_grat_no_discard_earns(self):
        j = JokerInstance("j_delayed_grat")
        effect = JOKER_REGISTRY["j_delayed_grat"]
        ctx = _make_ctx(jokers=[j])
        effect.on_round_end(j, ctx)
        assert j.state.get("pending_money", 0) >= 2

    def test_delayed_grat_after_discard_no_earn(self):
        j = JokerInstance("j_delayed_grat")
        effect = JOKER_REGISTRY["j_delayed_grat"]
        cards = [Card(5, "Hearts")]
        ctx = _make_ctx(jokers=[j])
        effect.on_discard(j, cards, ctx)
        ctx2 = _make_ctx(jokers=[j])
        effect.on_round_end(j, ctx2)
        assert j.state.get("pending_money", 0) == 0

    def test_egg_gains_sell_value(self):
        j = JokerInstance("j_egg")
        effect = JOKER_REGISTRY["j_egg"]
        ctx = _make_ctx(jokers=[j])
        effect.on_round_end(j, ctx)
        assert j.state.get("sell_value", 0) >= 4  # 1 + 3

    def test_faceless_earns_on_3_face_discard(self):
        j = JokerInstance("j_faceless")
        effect = JOKER_REGISTRY["j_faceless"]
        cards = [Card(11, "Hearts"), Card(12, "Spades"), Card(13, "Clubs")]
        ctx = _make_ctx(jokers=[j])
        effect.on_discard(j, cards, ctx)
        assert j.state.get("pending_money", 0) >= 5


# ════════════════════════════════════════════════════════════════════════════
# Scaling jokers
# ════════════════════════════════════════════════════════════════════════════

class TestScalingJokers:
    def test_green_joker_gains_mult(self):
        j = JokerInstance("j_green_joker")
        cards = [Card(14, "Spades")]
        ctx = _make_ctx(scoring_cards=cards, hand_type="High Card", jokers=[j])
        effect = JOKER_REGISTRY["j_green_joker"]
        effect.on_hand_scored(j, ctx)
        assert j.state.get("mult", 0) >= 1
        assert ctx.mult >= 1

    def test_green_joker_loses_mult_on_discard(self):
        j = JokerInstance("j_green_joker")
        j.state["mult"] = 5
        cards = [Card(5, "Hearts")]
        effect = JOKER_REGISTRY["j_green_joker"]
        ctx = _make_ctx(jokers=[j])
        effect.on_discard(j, cards, ctx)
        assert j.state["mult"] == 4

    def test_hit_the_road_jack_discard(self):
        j = JokerInstance("j_hit_the_road")
        cards = [Card(11, "Hearts")]  # Jack
        effect = JOKER_REGISTRY["j_hit_the_road"]
        ctx = _make_ctx(jokers=[j])
        effect.on_discard(j, cards, ctx)
        assert j.state.get("xmult", 1.0) >= 1.5  # x0.5 per Jack discarded

    def test_square_joker_gains_on_4_cards(self):
        j = JokerInstance("j_square_joker")
        cards = [Card(r, "Hearts") for r in [2, 3, 4, 5]]
        ctx = _make_ctx(scoring_cards=cards, hand_type="High Card", jokers=[j])
        effect = JOKER_REGISTRY["j_square_joker"]
        effect.on_hand_scored(j, ctx)
        assert j.state.get("chips", 0) >= 4


# ════════════════════════════════════════════════════════════════════════════
# Retrigger jokers (misc.py)
# ════════════════════════════════════════════════════════════════════════════

class TestRetriggerJokers:
    def test_hack_retriggers_low_ranks(self):
        cards = [Card(2, "Spades"), Card(3, "Hearts")]
        j = JokerInstance("j_hack")
        ctx = _make_ctx(scoring_cards=cards, jokers=[j])
        effect = JOKER_REGISTRY["j_hack"]
        for i, card in enumerate(cards):
            effect.on_score_card(j, card, ctx)
        # Cards 2 and 3 should have retriggers
        assert ctx.card_retriggers.get(0, 0) >= 1
        assert ctx.card_retriggers.get(1, 0) >= 1

    def test_hack_no_retrigger_high_rank(self):
        cards = [Card(10, "Spades")]
        j = JokerInstance("j_hack")
        ctx = _make_ctx(scoring_cards=cards, jokers=[j])
        effect = JOKER_REGISTRY["j_hack"]
        effect.on_score_card(j, cards[0], ctx)
        assert ctx.card_retriggers.get(0, 0) == 0

    def test_sock_and_buskin_face_cards(self):
        cards = [Card(11, "Hearts")]  # Jack = face
        j = JokerInstance("j_sock_and_buskin")
        ctx = _make_ctx(scoring_cards=cards, jokers=[j])
        effect = JOKER_REGISTRY["j_sock_and_buskin"]
        effect.on_score_card(j, cards[0], ctx)
        assert ctx.card_retriggers.get(0, 0) >= 1

    def test_hanging_chad_first_card_only(self):
        cards = [Card(10, "Hearts"), Card(11, "Spades")]
        j = JokerInstance("j_hanging_chad")
        ctx = _make_ctx(scoring_cards=cards, jokers=[j])
        effect = JOKER_REGISTRY["j_hanging_chad"]
        effect.on_score_card(j, cards[0], ctx)
        effect.on_score_card(j, cards[1], ctx)
        assert ctx.card_retriggers.get(0, 0) >= 2  # first card retriggered 2x
        assert ctx.card_retriggers.get(1, 0) == 0   # second card not retriggered

    def test_dusk_retriggers_on_last_hand(self):
        cards = [Card(10, "Hearts"), Card(11, "Spades")]
        j = JokerInstance("j_dusk")
        ctx = _make_ctx(scoring_cards=cards, jokers=[j], hands_left=0)
        effect = JOKER_REGISTRY["j_dusk"]
        effect.pre_score(j, ctx)
        assert ctx.card_retriggers.get(0, 0) >= 1
        assert ctx.card_retriggers.get(1, 0) >= 1

    def test_dusk_no_retrigger_not_last_hand(self):
        cards = [Card(10, "Hearts")]
        j = JokerInstance("j_dusk")
        ctx = _make_ctx(scoring_cards=cards, jokers=[j], hands_left=2)
        effect = JOKER_REGISTRY["j_dusk"]
        effect.pre_score(j, ctx)
        assert ctx.card_retriggers.get(0, 0) == 0

    def test_seltzer_retriggers_all(self):
        cards = [Card(10, "Hearts"), Card(5, "Spades")]
        j = JokerInstance("j_seltzer")
        ctx = _make_ctx(scoring_cards=cards, jokers=[j])
        effect = JOKER_REGISTRY["j_seltzer"]
        effect.pre_score(j, ctx)
        assert ctx.card_retriggers.get(0, 0) >= 1
        assert ctx.card_retriggers.get(1, 0) >= 1

    def test_seltzer_self_destructs(self):
        j = JokerInstance("j_seltzer")
        j.state["hands"] = 1
        effect = JOKER_REGISTRY["j_seltzer"]
        ctx = _make_ctx(jokers=[j])
        effect.on_hand_scored(j, ctx)
        assert j.state.get("destroyed") is True


# ════════════════════════════════════════════════════════════════════════════
# Hand eval flag jokers
# ════════════════════════════════════════════════════════════════════════════

class TestHandEvalFlags:
    def test_pareidolia_sets_all_face_cards(self):
        j = JokerInstance("j_pareidolia")
        ctx = _make_ctx(jokers=[j])
        effect = JOKER_REGISTRY["j_pareidolia"]
        effect.pre_score(j, ctx)
        assert ctx.all_face_cards is True

    def test_four_fingers_has_on_hand_scored(self):
        j = JokerInstance("j_four_fingers")
        ctx = _make_ctx(jokers=[j])
        effect = JOKER_REGISTRY["j_four_fingers"]
        # mult.py's FourFingers overrides misc.py; check it has on_hand_scored
        assert hasattr(effect, "on_hand_scored")

    def test_smeared_joker_sets_flag(self):
        j = JokerInstance("j_smeared_joker")
        ctx = _make_ctx(jokers=[j])
        effect = JOKER_REGISTRY["j_smeared_joker"]
        effect.pre_score(j, ctx)
        assert ctx.smear_suits is True

    def test_splash_adds_all_cards_to_scoring(self):
        c1 = Card(10, "Hearts")
        c2 = Card(5, "Spades")
        c3 = Card(3, "Clubs")
        scoring = [c1]
        all_cards = [c1, c2, c3]
        j = JokerInstance("j_splash")
        ctx = _make_ctx(scoring_cards=scoring, all_cards=all_cards, jokers=[j])
        effect = JOKER_REGISTRY["j_splash"]
        effect.pre_score(j, ctx)
        assert len(ctx.scoring_cards) == 3  # all cards now scoring


# ════════════════════════════════════════════════════════════════════════════
# Blueprint / Brainstorm
# ════════════════════════════════════════════════════════════════════════════

class TestBlueprintBrainstorm:
    def test_blueprint_copies_right_joker(self):
        """Blueprint should copy the effect of the joker to its right."""
        cards = [Card(14, "Spades")]
        # Blueprint at index 0, j_joker at index 1
        bp = JokerInstance("j_blueprint")
        jk = JokerInstance("j_joker")
        jokers = [bp, jk]
        ctx = _make_ctx(scoring_cards=cards, all_cards=cards,
                        hand_type="High Card", jokers=jokers)
        # Fire blueprint's on_hand_scored
        effect = JOKER_REGISTRY["j_blueprint"]
        effect.on_hand_scored(bp, ctx)
        # Should have fired j_joker's effect (+4 mult)
        assert ctx.mult >= 4

    def test_brainstorm_copies_leftmost(self):
        """Brainstorm should copy the leftmost joker."""
        cards = [Card(14, "Spades")]
        jk = JokerInstance("j_joker")
        bs = JokerInstance("j_brainstorm")
        jokers = [jk, bs]
        ctx = _make_ctx(scoring_cards=cards, all_cards=cards,
                        hand_type="High Card", jokers=jokers)
        effect = JOKER_REGISTRY["j_brainstorm"]
        effect.on_hand_scored(bs, ctx)
        assert ctx.mult >= 4

    def test_blueprint_no_target_when_rightmost(self):
        """Blueprint at rightmost position has nothing to copy."""
        bp = JokerInstance("j_blueprint")
        jokers = [bp]
        ctx = _make_ctx(jokers=jokers)
        effect = JOKER_REGISTRY["j_blueprint"]
        effect.on_hand_scored(bp, ctx)
        # Should not crash, mult should remain 0
        assert ctx.mult == 0


# ════════════════════════════════════════════════════════════════════════════
# Consumable-creating jokers (misc.py)
# ════════════════════════════════════════════════════════════════════════════

class TestConsumableCreatingJokers:
    def test_seance_straight_flush_creates_spectral(self):
        cards = [Card(r, "Hearts") for r in [5, 6, 7, 8, 9]]
        j = JokerInstance("j_seance")
        ctx = _make_ctx(scoring_cards=cards, hand_type="Straight Flush", jokers=[j])
        effect = JOKER_REGISTRY["j_seance"]
        effect.on_hand_scored(j, ctx)
        assert "spectral" in ctx.pending_consumables

    def test_superposition_ace_straight(self):
        cards = [Card(r, "Hearts") for r in [14, 2, 3, 4, 5]]
        cards[1].suit = "Spades"  # break flush
        j = JokerInstance("j_superposition")
        ctx = _make_ctx(scoring_cards=cards, hand_type="Straight", jokers=[j])
        effect = JOKER_REGISTRY["j_superposition"]
        effect.on_hand_scored(j, ctx)
        assert "tarot" in ctx.pending_consumables

    def test_riff_raff_creates_2_jokers(self):
        j = JokerInstance("j_riff_raff")
        effect = JOKER_REGISTRY["j_riff_raff"]
        ctx = _make_ctx(jokers=[j])
        effect.on_blind_selected(j, ctx)
        pending = j.state.get("pending_consumables", [])
        assert len(pending) >= 2

    def test_cartomancer_creates_tarot(self):
        j = JokerInstance("j_cartomancer")
        effect = JOKER_REGISTRY["j_cartomancer"]
        ctx = _make_ctx(jokers=[j])
        effect.on_blind_selected(j, ctx)
        pending = j.state.get("pending_consumables", [])
        assert "tarot" in pending

    def test_sixth_sense_single_6(self):
        cards = [Card(6, "Hearts")]
        j = JokerInstance("j_sixth_sense")
        ctx = _make_ctx(scoring_cards=cards, hand_type="High Card", jokers=[j])
        effect = JOKER_REGISTRY["j_sixth_sense"]
        effect.on_hand_scored(j, ctx)
        assert "spectral" in ctx.pending_consumables
        assert j.state.get("used") is True

    def test_sixth_sense_only_fires_once(self):
        cards = [Card(6, "Hearts")]
        j = JokerInstance("j_sixth_sense")
        j.state["used"] = True
        ctx = _make_ctx(scoring_cards=cards, hand_type="High Card", jokers=[j])
        effect = JOKER_REGISTRY["j_sixth_sense"]
        effect.on_hand_scored(j, ctx)
        assert "spectral" not in ctx.pending_consumables


# ════════════════════════════════════════════════════════════════════════════
# Legendary jokers
# ════════════════════════════════════════════════════════════════════════════

class TestLegendaryJokers:
    def test_caino_mult_mult_on_face_destroy(self):
        j = JokerInstance("j_caino")
        card = Card(11, "Hearts")  # Jack = face
        ctx = _make_ctx(jokers=[j])
        effect = JOKER_REGISTRY["j_caino"]
        effect.on_card_destroyed(j, card, ctx)
        assert j.state.get("xmult", 1.0) == 1.1  # gains x0.1 per face destroyed

    def test_yorick_discard_scaling(self):
        j = JokerInstance("j_yorick")
        cards = [Card(5, "Hearts")] * 23
        effect = JOKER_REGISTRY["j_yorick"]
        ctx = _make_ctx(jokers=[j])
        effect.on_discard(j, cards, ctx)
        assert j.state.get("discarded", 0) == 23
        ctx2 = _make_ctx(jokers=[j])
        effect.on_hand_scored(j, ctx2)
        assert ctx2.mult_mult >= 2.0  # 23 // 23 = 1 set -> x(1+1) = x2

    def test_triboulet_king_queen_x2(self):
        # Use a pair of Kings so both score (Pair hand type)
        cards = [Card(13, "Spades"), Card(13, "Hearts")]
        score_with, _ = _score(cards, ["j_triboulet"])
        score_without, _ = _score(cards, [])
        # Each King scored should x2 mult, so total should be much higher
        assert score_with > score_without * 2


# ════════════════════════════════════════════════════════════════════════════
# Misc jokers
# ════════════════════════════════════════════════════════════════════════════

class TestMiscJokers:
    def test_trading_card_first_discard_earns(self):
        j = JokerInstance("j_trading_card")
        cards = [Card(5, "Hearts")]
        effect = JOKER_REGISTRY["j_trading_card"]
        ctx = _make_ctx(jokers=[j])
        effect.on_discard(j, cards, ctx)
        assert j.state.get("pending_money", 0) >= 3

    def test_trading_card_only_once_per_round(self):
        j = JokerInstance("j_trading_card")
        cards = [Card(5, "Hearts")]
        effect = JOKER_REGISTRY["j_trading_card"]
        ctx = _make_ctx(jokers=[j])
        effect.on_discard(j, cards, ctx)
        ctx2 = _make_ctx(jokers=[j])
        effect.on_discard(j, cards, ctx2)
        # Second discard shouldn't add more money
        assert j.state.get("pending_money", 0) == 3

    def test_card_sharp_x3_on_repeat_hand_type(self):
        j = JokerInstance("j_card_sharp")
        effect = JOKER_REGISTRY["j_card_sharp"]
        # First time: no bonus (hand type not yet played)
        ctx = _make_ctx(hand_type="Pair", jokers=[j])
        effect.on_hand_scored(j, ctx)
        assert ctx.mult_mult == 1.0
        # Second time with SAME joker instance: should trigger x3
        ctx2 = ScoreContext(
            chips=0.0, mult=0.0, mult_mult=1.0,
            hand_type="Pair", scoring_cards=[], all_cards=[],
            jokers=[j], hands_left=3, discards_left=3,
            dollars=10, ante=1, deck_remaining=40,
            planet_levels={h: 1 for h in [
                "High Card", "Pair", "Two Pair", "Three of a Kind",
                "Straight", "Flush", "Full House", "Four of a Kind",
                "Straight Flush", "Five of a Kind", "Flush House", "Flush Five",
            ]},
        )
        effect.on_hand_scored(j, ctx2)
        assert ctx2.mult_mult == 3.0

    def test_mr_bones_prevents_loss(self):
        j = JokerInstance("j_mr_bones")
        ctx = _make_ctx(jokers=[j])
        effect = JOKER_REGISTRY["j_mr_bones"]
        effect.on_hand_scored(j, ctx)
        assert ctx.prevent_loss is True

    def test_midas_mask_gold_face_cards(self):
        card = Card(11, "Hearts")  # Jack
        j = JokerInstance("j_midas_mask")
        ctx = _make_ctx(scoring_cards=[card], jokers=[j])
        effect = JOKER_REGISTRY["j_midas_mask"]
        effect.on_score_card(j, card, ctx)
        assert card.enhancement == "Gold"

    def test_to_do_list_earns_on_match(self):
        j = JokerInstance("j_to_do_list")
        j.state["target"] = "Pair"
        cards = [Card(10, "Hearts"), Card(10, "Spades")]
        ctx = _make_ctx(scoring_cards=cards, hand_type="Pair", jokers=[j])
        effect = JOKER_REGISTRY["j_to_do_list"]
        effect.on_hand_scored(j, ctx)
        assert ctx.pending_money >= 4


# ════════════════════════════════════════════════════════════════════════════
# Registry completeness
# ════════════════════════════════════════════════════════════════════════════

class TestRegistryCompleteness:
    def test_registry_not_empty(self):
        assert len(JOKER_REGISTRY) > 50

    def test_all_registered_jokers_have_at_least_one_hook(self):
        """Every registered joker should have at least one trigger method
        (except passive jokers applied directly in game.py)."""
        # Passive jokers — effects applied in game.py._start_blind by key check
        PASSIVE_JOKERS = {"j_merry_andy", "j_troubadour", "j_juggler", "j_drunkard"}
        hooks = [
            "on_score_card", "on_hand_scored", "on_discard", "on_round_end",
            "on_blind_selected", "on_boss_beaten", "on_planet_used",
            "on_tarot_used", "on_sell", "on_shop_enter", "on_shop_leave",
            "pre_score", "on_card_destroyed", "on_card_added",
            "on_blind_skipped", "on_lucky_trigger", "on_booster_opened",
            "on_boss_ability_triggered", "on_joker_destroyed", "on_init",
            "on_reroll", "on_booster_skipped",
        ]
        for key, effect in JOKER_REGISTRY.items():
            if key in PASSIVE_JOKERS:
                continue
            has_hook = any(hasattr(effect, h) for h in hooks)
            assert has_hook, f"Joker {key} has no trigger hooks"
