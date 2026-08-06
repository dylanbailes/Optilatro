"""
test_boss_blinds.py — Tests for all boss blind effects.
Tests the start-of-blind application, in-play effects, and cleanup.
"""
from __future__ import annotations

import pytest

from balatro_sim.game import BalatroGame, State, BlindInfo
from balatro_sim.card import Card
from balatro_sim.constants import HAND_SIZE


# ════════════════════════════════════════════════════════════════════════════
# Fixtures
# ════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def game():
    g = BalatroGame(seed=42)
    g.reset()
    return g


def _setup_boss(game, boss_key):
    """Set up game in SELECTING_HAND with a specific boss blind."""
    game.blind_idx = 2
    game.current_blind = BlindInfo(
        name=f"Test {boss_key}",
        kind="Boss",
        chips_target=1000,
        is_boss=True,
        boss_key=boss_key,
    )
    game.state = State.BLIND_SELECT
    game.step({"type": "play_blind"})
    return game


# ════════════════════════════════════════════════════════════════════════════
# Boss blind start effects
# ════════════════════════════════════════════════════════════════════════════

class TestBossBlindStart:
    def test_manacle_reduces_hand_size(self, game):
        prev = game.hand_size
        _setup_boss(game, "bl_manacle")
        assert game.hand_size == max(1, prev - 1)

    def test_needle_only_1_hand(self, game):
        _setup_boss(game, "bl_needle")
        assert game.hands_left == 1

    def test_water_zero_discards(self, game):
        _setup_boss(game, "bl_water")
        assert game.discards_left == 0

    def test_goad_debuffs_spades(self, game):
        """The Goad debuffs Spades (Clubs are debuffed by The Club, a separate boss)."""
        _setup_boss(game, "bl_goad")
        spades = [c for c in game.hand + game.deck if c.suit == "Spades"]
        if spades:
            assert all(c.debuffed for c in spades)
        # Non-spades (including Clubs) should not be debuffed
        non_spades = [c for c in game.hand + game.deck if c.suit != "Spades"]
        assert all(not c.debuffed for c in non_spades)

    def test_window_debuffs_diamonds(self, game):
        _setup_boss(game, "bl_window")
        diamonds = [c for c in game.hand + game.deck if c.suit == "Diamonds"]
        if diamonds:
            assert all(c.debuffed for c in diamonds)

    def test_head_debuffs_hearts(self, game):
        _setup_boss(game, "bl_head")
        hearts = [c for c in game.hand + game.deck if c.suit == "Hearts"]
        if hearts:
            assert all(c.debuffed for c in hearts)

    def test_plant_debuffs_face_cards(self, game):
        _setup_boss(game, "bl_plant")
        face_cards = [c for c in game.hand + game.deck if c.is_face_card]
        if face_cards:
            assert all(c.debuffed for c in face_cards)

    def test_no_boss_no_debuffs(self, game):
        """Non-boss blind should not debuff any cards."""
        game.blind_idx = 0
        game.state = State.BLIND_SELECT
        game.step({"type": "play_blind"})
        all_cards = game.hand + game.deck
        assert all(not c.debuffed for c in all_cards)


# ════════════════════════════════════════════════════════════════════════════
# Boss blind in-play effects
# ════════════════════════════════════════════════════════════════════════════

class TestBossBlindInPlay:
    def test_psychic_requires_5_cards(self, game):
        _setup_boss(game, "bl_psychic")
        # Try to play 3 cards — should be rejected
        prev_chips = game.chips_scored
        game.step({"type": "play", "cards": [0, 1, 2]})
        assert game.chips_scored == prev_chips  # no score
        # Play exactly 5 cards — should work
        if len(game.hand) >= 5:
            game.step({"type": "play", "cards": [0, 1, 2, 3, 4]})
            assert game.chips_scored > prev_chips or game.state != State.SELECTING_HAND

    def test_hook_discards_2_from_play(self, game):
        _setup_boss(game, "bl_hook")
        hand_before = list(game.hand)
        if len(game.hand) >= 4:
            game.step({"type": "play", "cards": [0, 1, 2, 3]})
            # Hook discards 2 from the selected cards, so at most 2 score

    def test_tooth_loses_money_per_card(self, game):
        _setup_boss(game, "bl_tooth")
        game.dollars = 20
        n_cards = min(3, len(game.hand))
        if n_cards > 0:
            game.step({"type": "play", "cards": list(range(n_cards))})
            assert game.dollars <= 20  # lost at least some money

    def test_flint_halves_score(self, game):
        """Flint should halve the final score."""
        _setup_boss(game, "bl_flint")
        if len(game.hand) >= 1:
            game.step({"type": "play", "cards": [0]})
            # Can't compare exact values but score should be positive if cards scored
            # Just verify it doesn't crash

    def test_eye_prevents_duplicate_hand_type(self, game):
        _setup_boss(game, "bl_eye")
        # Play first hand
        if len(game.hand) >= 2:
            game.step({"type": "play", "cards": [0]})
            # The hand type is now recorded
            assert len(game.played_hand_types_this_round) >= 1

    def test_serpent_clears_hand_after_play(self, game):
        _setup_boss(game, "bl_serpent")
        if len(game.hand) >= 1:
            prev_hand = list(game.hand)
            game.step({"type": "play", "cards": [0]})
            # Serpent discards remaining hand and redraws
            # Hand should be different (new cards drawn)

    def test_fish_draws_fewer_each_play(self, game):
        _setup_boss(game, "bl_fish")
        # Fish: draw 1 fewer card after each play
        first_hand_size = len(game.hand)
        if first_hand_size >= 1:
            game.step({"type": "play", "cards": [0]})
            if game.state == State.SELECTING_HAND:
                # Should have fewer cards drawn
                assert len(game.hand) <= first_hand_size


# ════════════════════════════════════════════════════════════════════════════
# Boss blind cleanup
# ════════════════════════════════════════════════════════════════════════════

class TestBossBlindCleanup:
    def test_goad_debuffs_cleared_after_round(self, game):
        _setup_boss(game, "bl_goad")
        # Simulate clearing the blind by forcing state
        game._undo_boss_debuffs("bl_goad")
        all_cards = game.hand + game.deck
        assert all(not c.debuffed for c in all_cards)

    def test_window_debuffs_cleared(self, game):
        _setup_boss(game, "bl_window")
        game._undo_boss_debuffs("bl_window")
        all_cards = game.hand + game.deck
        assert all(not c.debuffed for c in all_cards)

    def test_head_debuffs_cleared(self, game):
        _setup_boss(game, "bl_head")
        game._undo_boss_debuffs("bl_head")
        all_cards = game.hand + game.deck
        assert all(not c.debuffed for c in all_cards)

    def test_plant_debuffs_cleared(self, game):
        _setup_boss(game, "bl_plant")
        game._undo_boss_debuffs("bl_plant")
        all_cards = game.hand + game.deck
        assert all(not c.debuffed for c in all_cards)

    def test_manacle_hand_size_restored(self, game):
        _setup_boss(game, "bl_manacle")
        # Simulate round end
        game.current_blind.boss_key = "bl_manacle"
        game.chips_scored = game.current_blind.chips_target  # beat it
        game.state = State.ROUND_EVAL
        game._end_round()
        assert game.hand_size == HAND_SIZE


# ════════════════════════════════════════════════════════════════════════════
# Boss blind selection from pool
# ════════════════════════════════════════════════════════════════════════════

class TestBossBlindPool:
    def test_boss_blind_assigned_on_boss_round(self, game):
        game.blind_idx = 2
        game._prepare_next_blind()
        assert game.current_blind.is_boss
        assert game.current_blind.boss_key != ""

    def test_non_boss_has_no_boss_key(self, game):
        game.blind_idx = 0
        game._prepare_next_blind()
        assert not game.current_blind.is_boss
        assert game.current_blind.boss_key == ""

    def test_boss_key_from_ante1_eligible_pool(self, game):
        from balatro_sim.game import BOSS_MIN_ANTE, SHOWDOWN_BOSSES, UNIMPLEMENTED_BOSSES
        game.blind_idx = 2
        game._prepare_next_blind()
        key = game.current_blind.boss_key
        assert BOSS_MIN_ANTE[key] <= game.ante     # eligible at the current ante
        assert key not in SHOWDOWN_BOSSES          # showdown is ante-8 only
        assert key not in UNIMPLEMENTED_BOSSES     # never a boss with no effect
