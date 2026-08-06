"""Tests for balatro_sim.card_selection — V7 subset enumeration and scoring."""
import numpy as np
import pytest

from balatro_sim.card import Card
from balatro_sim.card_selection import (
    INTENT_PLAY, INTENT_DISCARD, INTENT_USE_CONSUMABLE, N_INTENTS,
    enumerate_subsets, subset_count,
    compute_subset_logits,
    validate_play_subset, get_valid_play_mask,
    apply_action,
)


# ════════════════════════════════════════════════════════════════════════════
# Subset enumeration
# ════════════════════════════════════════════════════════════════════════════

class TestEnumerateSubsets:
    def test_empty(self):
        assert enumerate_subsets(0) == []

    def test_one_card(self):
        subsets = enumerate_subsets(1)
        assert subsets == [(0,)]

    def test_two_cards(self):
        subsets = enumerate_subsets(2)
        assert subsets == [(0,), (1,), (0, 1)]

    def test_three_cards(self):
        subsets = enumerate_subsets(3)
        # 1-card: 3, 2-card: 3, 3-card: 1 = 7
        assert len(subsets) == 7
        assert (0,) in subsets
        assert (0, 1, 2) in subsets

    def test_five_cards(self):
        subsets = enumerate_subsets(5)
        # C(5,1)+C(5,2)+C(5,3)+C(5,4)+C(5,5) = 5+10+10+5+1 = 31
        assert len(subsets) == 31

    def test_eight_cards(self):
        subsets = enumerate_subsets(8)
        # C(8,1)+C(8,2)+C(8,3)+C(8,4)+C(8,5) = 8+28+56+70+56 = 218
        assert len(subsets) == 218

    def test_max_subset_size_is_five(self):
        """No subset should have more than 5 cards."""
        subsets = enumerate_subsets(8)
        assert all(len(s) <= 5 for s in subsets)

    def test_six_cards_no_six_card_subsets(self):
        subsets = enumerate_subsets(6)
        assert all(len(s) <= 5 for s in subsets)
        # C(6,1)+C(6,2)+C(6,3)+C(6,4)+C(6,5) = 6+15+20+15+6 = 62
        assert len(subsets) == 62

    def test_cached(self):
        """Same object returned on repeated calls."""
        a = enumerate_subsets(8)
        b = enumerate_subsets(8)
        assert a is b

    def test_subset_count_matches(self):
        for n in range(0, 9):
            assert subset_count(n) == len(enumerate_subsets(n))


# ════════════════════════════════════════════════════════════════════════════
# Subset scoring
# ════════════════════════════════════════════════════════════════════════════

class TestComputeSubsetLogits:
    def test_play_intent_sums_scores(self):
        scores = np.array([0.9, 0.1, 0.5], dtype=np.float32)
        subsets = enumerate_subsets(3)
        logits = compute_subset_logits(scores, subsets, INTENT_PLAY)
        # Subset (0,) should have logit 0.9
        idx_0 = subsets.index((0,))
        assert abs(logits[idx_0] - 0.9) < 1e-5
        # Subset (0, 2) should have logit 0.9 + 0.5 = 1.4
        idx_02 = subsets.index((0, 2))
        assert abs(logits[idx_02] - 1.4) < 1e-5
        # Subset (0, 1, 2) should have logit 0.9 + 0.1 + 0.5 = 1.5
        idx_012 = subsets.index((0, 1, 2))
        assert abs(logits[idx_012] - 1.5) < 1e-5

    def test_discard_intent_sums_inverted_scores(self):
        scores = np.array([0.9, 0.1, 0.5], dtype=np.float32)
        subsets = enumerate_subsets(3)
        logits = compute_subset_logits(scores, subsets, INTENT_DISCARD)
        # Subset (1,) should have logit 1-0.1 = 0.9 (discard the low-scored card)
        idx_1 = subsets.index((1,))
        assert abs(logits[idx_1] - 0.9) < 1e-5
        # Subset (0,) should have logit 1-0.9 = 0.1 (don't discard the high-scored card)
        idx_0 = subsets.index((0,))
        assert abs(logits[idx_0] - 0.1) < 1e-5

    def test_temperature_scaling(self):
        scores = np.array([0.8, 0.2], dtype=np.float32)
        subsets = enumerate_subsets(2)
        logits_t1 = compute_subset_logits(scores, subsets, INTENT_PLAY, temperature=1.0)
        logits_t05 = compute_subset_logits(scores, subsets, INTENT_PLAY, temperature=0.5)
        # Temperature 0.5 should double the logits
        np.testing.assert_allclose(logits_t05, logits_t1 / 0.5, atol=1e-5)

    def test_empty_subsets(self):
        scores = np.array([0.5], dtype=np.float32)
        logits = compute_subset_logits(scores, [], INTENT_PLAY)
        assert len(logits) == 0

    def test_use_consumable_returns_uniform(self):
        scores = np.array([0.9, 0.1, 0.5], dtype=np.float32)
        subsets = enumerate_subsets(3)
        logits = compute_subset_logits(scores, subsets, INTENT_USE_CONSUMABLE)
        assert all(l == 0.0 for l in logits)

    def test_play_highest_scores_get_highest_logits(self):
        """The subset of the two highest-scored cards should have the highest 2-card logit."""
        scores = np.array([0.9, 0.1, 0.8, 0.2], dtype=np.float32)
        subsets = enumerate_subsets(4)
        logits = compute_subset_logits(scores, subsets, INTENT_PLAY)
        # Best 2-card subset: (0, 2) with logit 0.9+0.8 = 1.7
        two_card_subsets = [(i, s) for i, s in enumerate(subsets) if len(s) == 2]
        best_2card = max(two_card_subsets, key=lambda x: logits[x[0]])
        assert best_2card[1] == (0, 2)


# ════════════════════════════════════════════════════════════════════════════
# Boss blind validation
# ════════════════════════════════════════════════════════════════════════════

def _make_hand(*specs):
    """Helper: _make_hand((14, "Spades"), (13, "Hearts"), ...)"""
    return [Card(rank=r, suit=s) for r, s in specs]


class TestBossValidation:
    def test_no_boss_always_valid(self):
        hand = _make_hand((14, "Spades"), (13, "Hearts"), (12, "Clubs"))
        assert validate_play_subset((0, 1), hand, "", set())

    def test_psychic_requires_five(self):
        hand = _make_hand(*[(r, "Spades") for r in range(2, 10)])  # 8 cards
        assert not validate_play_subset((0, 1), hand, "bl_psychic", set())
        assert validate_play_subset((0, 1, 2, 3, 4), hand, "bl_psychic", set())

    def test_eye_no_repeat_types(self):
        hand = _make_hand((14, "Spades"), (14, "Hearts"), (7, "Clubs"))
        # First play: Pair is fine
        assert validate_play_subset((0, 1), hand, "bl_eye", set())
        # Second play: Pair already played
        assert not validate_play_subset((0, 1), hand, "bl_eye", {"Pair"})
        # Different type still ok
        assert validate_play_subset((2,), hand, "bl_eye", {"Pair"})

    def test_mouth_same_type_only(self):
        hand = _make_hand((14, "Spades"), (14, "Hearts"), (7, "Clubs"))
        # First play: anything goes (no played types yet)
        assert validate_play_subset((0, 1), hand, "bl_mouth", set())
        # After playing Pair: must play Pair
        assert validate_play_subset((0, 1), hand, "bl_mouth", {"Pair"})
        # High Card not allowed after Pair
        assert not validate_play_subset((2,), hand, "bl_mouth", {"Pair"})

    def test_empty_hand(self):
        assert not validate_play_subset((0,), [], "", set())

    def test_out_of_range_index(self):
        hand = _make_hand((14, "Spades"),)
        assert not validate_play_subset((5,), hand, "", set())

    def test_valid_play_mask_non_restrictive_boss(self):
        hand = _make_hand(*[(r, "Spades") for r in range(2, 10)])
        subsets = enumerate_subsets(len(hand))
        mask = get_valid_play_mask(subsets, hand, "", set())
        assert mask.all()  # all valid for non-restrictive boss

    def test_valid_play_mask_psychic(self):
        hand = _make_hand(*[(r, "Spades") for r in range(2, 10)])
        subsets = enumerate_subsets(len(hand))
        mask = get_valid_play_mask(subsets, hand, "bl_psychic", set())
        # Only 5-card subsets should be valid
        for i, s in enumerate(subsets):
            if len(s) == 5:
                assert mask[i], f"5-card subset {s} should be valid"
            else:
                assert not mask[i], f"{len(s)}-card subset {s} should be invalid"

    def test_valid_play_mask_always_has_fallback(self):
        """Even if all subsets are invalid, at least one should be masked valid."""
        hand = _make_hand((14, "Spades"), (14, "Hearts"))
        subsets = enumerate_subsets(len(hand))
        # bl_eye with Pair already played, and only pairs possible
        mask = get_valid_play_mask(subsets, hand, "bl_eye", {"Pair", "High Card"})
        assert mask.any()


# ════════════════════════════════════════════════════════════════════════════
# Action application
# ════════════════════════════════════════════════════════════════════════════

class TestApplyAction:
    def test_play_action(self):
        hand = _make_hand((14, "Spades"), (13, "Hearts"), (12, "Clubs"))
        action = apply_action(INTENT_PLAY, (0, 2), hand, None)
        assert action == {"type": "play", "cards": [0, 2]}

    def test_discard_action(self):
        hand = _make_hand((14, "Spades"), (13, "Hearts"), (12, "Clubs"))
        action = apply_action(INTENT_DISCARD, (1,), hand, None)
        assert action == {"type": "discard", "cards": [1]}

    def test_consumable_action(self):
        action = apply_action(INTENT_USE_CONSUMABLE, (), [], None)
        assert action == {"type": "use_consumable", "consumable_idx": 0, "target_cards": []}

    def test_out_of_range_filtered(self):
        hand = _make_hand((14, "Spades"),)
        action = apply_action(INTENT_PLAY, (0, 5, 10), hand, None)
        assert action == {"type": "play", "cards": [0]}

    def test_empty_subset_fallback(self):
        hand = _make_hand((14, "Spades"),)
        action = apply_action(INTENT_PLAY, (), hand, None)
        assert action["type"] == "play"
        assert len(action["cards"]) > 0
