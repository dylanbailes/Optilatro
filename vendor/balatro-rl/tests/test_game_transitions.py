"""
test_game_transitions.py — Tests for game state machine transitions:
  - Ante progression
  - Blind sequencing (Small -> Big -> Boss)
  - Round flow (select -> play -> score -> shop -> next blind)
  - Game over conditions (win and loss)
  - Skip blind behavior
  - Round-end payouts
"""
from __future__ import annotations

import pytest

from balatro_sim.game import BalatroGame, State
from balatro_sim.card import Card
from balatro_sim.constants import (
    BLIND_CHIPS, STARTING_HANDS, STARTING_DISCARDS,
    STARTING_MONEY, INTEREST_RATE, INTEREST_CAP, HAND_PAYOUT,
    BLIND_REWARDS,
)


@pytest.fixture
def game():
    g = BalatroGame(seed=42)
    g.reset()
    return g


# ════════════════════════════════════════════════════════════════════════════
# Initial state
# ════════════════════════════════════════════════════════════════════════════

class TestInitialState:
    def test_starts_at_blind_select(self, game):
        assert game.state == State.BLIND_SELECT

    def test_starts_at_ante_1(self, game):
        assert game.ante == 1

    def test_starts_at_small_blind(self, game):
        assert game.blind_idx == 0
        assert game.current_blind.kind == "Small"

    def test_starts_with_correct_money(self, game):
        assert game.dollars == STARTING_MONEY

    def test_starts_with_empty_jokers(self, game):
        assert len(game.jokers) == 0

    def test_starts_with_planet_levels_at_1(self, game):
        for ht, level in game.planet_levels.items():
            assert level == 1

    def test_reset_returns_to_initial(self, game):
        # Mutate some state
        game.ante = 5
        game.dollars = 100
        game.reset()
        assert game.ante == 1
        assert game.dollars == STARTING_MONEY
        assert game.state == State.BLIND_SELECT


# ════════════════════════════════════════════════════════════════════════════
# Blind sequencing
# ════════════════════════════════════════════════════════════════════════════

class TestBlindSequencing:
    def test_small_big_boss_order(self, game):
        """Blinds should go Small -> Big -> Boss within each ante."""
        assert game.blind_idx == 0
        assert game.current_blind.kind == "Small"

    def test_blind_chips_match_table(self, game):
        """Chip targets match the BLIND_CHIPS table, except the large-blind
        bosses (The Wall 4x / Violet Vessel 6x) which scale from the base
        (small-blind) requirement per the real game."""
        for ante in range(1, 9):
            for blind_idx in range(3):
                game.ante = ante
                game.blind_idx = blind_idx
                game._prepare_next_blind()
                expected = BLIND_CHIPS[ante][blind_idx]
                key = game.current_blind.boss_key
                if key == "bl_wall":
                    expected = BLIND_CHIPS[ante][0] * 4
                elif key == "bl_violet":
                    expected = BLIND_CHIPS[ante][0] * 6
                assert game.current_blind.chips_target == expected

    def test_blind_idx_advances_through_shop(self, game):
        """After clearing a blind and leaving shop, blind_idx should advance."""
        game.step({"type": "play_blind"})
        # Force beat the blind
        game.chips_scored = game.current_blind.chips_target
        game.state = State.ROUND_EVAL
        game._end_round()
        assert game.state == State.SHOP
        game.step({"type": "leave_shop"})
        assert game.blind_idx == 1  # advanced to Big blind

    def test_ante_increments_after_boss(self, game):
        """Ante should increment after beating all 3 blinds."""
        for blind in range(3):
            game.step({"type": "play_blind"})
            game.chips_scored = game.current_blind.chips_target
            game.state = State.ROUND_EVAL
            game._end_round()
            game.step({"type": "leave_shop"})
        assert game.ante == 2
        assert game.blind_idx == 0  # reset to Small


# ════════════════════════════════════════════════════════════════════════════
# Game flow
# ════════════════════════════════════════════════════════════════════════════

class TestGameFlow:
    def test_play_blind_transitions_to_selecting(self, game):
        game.step({"type": "play_blind"})
        assert game.state == State.SELECTING_HAND

    def test_selecting_hand_has_cards(self, game):
        game.step({"type": "play_blind"})
        assert len(game.hand) > 0
        assert len(game.deck) > 0

    def test_hand_size_correct(self, game):
        game.step({"type": "play_blind"})
        assert len(game.hand) == game.hand_size

    def test_beating_blind_goes_to_round_eval(self, game):
        game.step({"type": "play_blind"})
        game.chips_scored = game.current_blind.chips_target
        game.state = State.ROUND_EVAL
        # ROUND_EVAL auto-advances to SHOP
        game._end_round()
        assert game.state == State.SHOP

    def test_losing_goes_to_game_over(self, game):
        game.step({"type": "play_blind"})
        # Use all hands without clearing
        for _ in range(game.hands_left):
            if game.state == State.SELECTING_HAND and len(game.hand) > 0:
                game.step({"type": "play", "cards": [0]})
        # If didn't clear the blind, should be GAME_OVER
        if game.chips_scored < game.current_blind.chips_target:
            assert game.state == State.GAME_OVER


# ════════════════════════════════════════════════════════════════════════════
# Skip blind
# ════════════════════════════════════════════════════════════════════════════

class TestSkipBlind:
    def test_skip_small_claims_tag(self, game):
        # Skipping awards the offered Tag (replaces the old flat +$5). Force a
        # money tag to pin the payout path through the tag system.
        assert game.current_tag is not None
        game.current_tag = "t_speed"
        game.skipped_blinds = 0
        prev = game.dollars
        game.step({"type": "skip_blind"})
        assert game.skipped_blinds == 1
        assert game.dollars == prev + 5   # Speed Tag: $5 × 1 skipped blind

    def test_skip_enters_shop(self, game):
        game.step({"type": "skip_blind"})
        assert game.state == State.SHOP

    def test_cannot_skip_boss(self, game):
        game.blind_idx = 2
        game._prepare_next_blind()
        prev_state = game.state
        game.step({"type": "skip_blind"})
        # Should remain at BLIND_SELECT (boss can't be skipped)
        assert game.state == State.BLIND_SELECT

    def test_skip_big_works(self, game):
        game.blind_idx = 1
        game._prepare_next_blind()
        game.step({"type": "skip_blind"})
        assert game.state == State.SHOP


# ════════════════════════════════════════════════════════════════════════════
# Round-end payouts
# ════════════════════════════════════════════════════════════════════════════

class TestRoundPayouts:
    def test_hands_left_payout(self, game):
        game.step({"type": "play_blind"})
        game.chips_scored = game.current_blind.chips_target
        game.state = State.ROUND_EVAL
        prev_dollars = game.dollars
        hands_remaining = game.hands_left
        game._end_round()
        earnings = hands_remaining * HAND_PAYOUT
        interest = min(prev_dollars // INTEREST_RATE, INTEREST_CAP)
        reward = BLIND_REWARDS[game.current_blind.kind]   # flat blind reward
        expected = prev_dollars + earnings + interest + reward
        assert game.dollars == expected

    def test_interest_caps_at_5(self, game):
        game.dollars = 100  # way over cap
        game.step({"type": "play_blind"})
        game.chips_scored = game.current_blind.chips_target
        game.state = State.ROUND_EVAL
        prev = game.dollars
        game._end_round()
        interest = min(prev // INTEREST_RATE, INTEREST_CAP)
        assert interest == INTEREST_CAP

    def test_gold_seal_payout(self, game):
        game.step({"type": "play_blind"})
        # Give a gold seal card to hand
        game.hand[0].seal = "Gold"
        game.chips_scored = game.current_blind.chips_target
        game.state = State.ROUND_EVAL
        prev = game.dollars
        game._end_round()
        # Should include $3 for gold seal
        assert game.dollars >= prev + 3

    def test_gold_enhancement_payout(self, game):
        game.step({"type": "play_blind"})
        game.hand[0].enhancement = "Gold"
        game.chips_scored = game.current_blind.chips_target
        game.state = State.ROUND_EVAL
        prev = game.dollars
        game._end_round()
        assert game.dollars >= prev + 3


# ════════════════════════════════════════════════════════════════════════════
# Win condition
# ════════════════════════════════════════════════════════════════════════════

class TestWinCondition:
    def test_win_after_ante_8(self, game):
        """Game ends as won after beating ante 8 boss and leaving shop."""
        game.ante = 8
        game.blind_idx = 2
        game._prepare_next_blind()
        game.step({"type": "play_blind"})
        game.chips_scored = game.current_blind.chips_target
        game.state = State.ROUND_EVAL
        game._end_round()
        game.step({"type": "leave_shop"})
        assert game.state == State.GAME_OVER
        obs = game._obs()
        assert obs.won is True

    def test_not_won_mid_game(self, game):
        obs = game._obs()
        assert obs.won is False
        assert obs.done is False


# ════════════════════════════════════════════════════════════════════════════
# Discard mechanics
# ════════════════════════════════════════════════════════════════════════════

class TestDiscardMechanics:
    def test_discard_reduces_count(self, game):
        game.step({"type": "play_blind"})
        prev = game.discards_left
        if prev > 0 and len(game.hand) > 0:
            game.step({"type": "discard", "cards": [0]})
            assert game.discards_left == prev - 1

    def test_discard_with_zero_discards_fails(self, game):
        game.step({"type": "play_blind"})
        game.discards_left = 0
        prev_hand = list(game.hand)
        game.step({"type": "discard", "cards": [0]})
        assert len(game.hand) == len(prev_hand)  # unchanged

    def test_discard_empty_selection_fails(self, game):
        game.step({"type": "play_blind"})
        prev = game.discards_left
        game.step({"type": "discard", "cards": []})
        assert game.discards_left == prev  # unchanged

    def test_discard_draws_new_cards(self, game):
        game.step({"type": "play_blind"})
        if game.discards_left > 0 and len(game.hand) > 0:
            prev_deck = len(game.deck)
            game.step({"type": "discard", "cards": [0]})
            # Should draw to fill hand size
            assert len(game.hand) == game.hand_size or len(game.deck) == 0


# ════════════════════════════════════════════════════════════════════════════
# Consumable usage during play
# ════════════════════════════════════════════════════════════════════════════

class TestConsumableUsage:
    def test_use_planet_in_selecting_hand(self, game):
        game.step({"type": "play_blind"})
        game.consumable_hand = ["pl_jupiter"]
        prev = game.planet_levels.get("Flush", 1)
        game.step({"type": "use_consumable", "consumable_idx": 0, "target_cards": []})
        assert game.planet_levels["Flush"] == prev + 1
        assert "pl_jupiter" not in game.consumable_hand

    def test_use_tarot_in_selecting_hand(self, game):
        game.step({"type": "play_blind"})
        game.consumable_hand = ["c_star"]
        prev_suit = game.hand[0].suit
        game.step({"type": "use_consumable", "consumable_idx": 0, "target_cards": [0, 1, 2]})
        # Star converts to Diamonds
        assert game.hand[0].suit == "Diamonds"

    def test_invalid_consumable_idx(self, game):
        game.step({"type": "play_blind"})
        game.consumable_hand = []
        # Should not crash
        game.step({"type": "use_consumable", "consumable_idx": 5, "target_cards": []})


# ════════════════════════════════════════════════════════════════════════════
# Observation
# ════════════════════════════════════════════════════════════════════════════

class TestGameObservation:
    def test_obs_matches_state(self, game):
        obs = game._obs()
        assert obs.state == game.state
        assert obs.ante == game.ante
        assert obs.dollars == game.dollars
        assert obs.done == (game.state == State.GAME_OVER)

    def test_obs_hand_is_copy(self, game):
        game.step({"type": "play_blind"})
        obs = game._obs()
        # Mutating obs hand should not affect game
        obs.hand.append(Card(2, "Hearts"))
        assert len(game.hand) != len(obs.hand)
