"""Tests for balatro_sim.mp_game — Multiplayer Balatro coordinator."""
import pytest

from balatro_sim.mp_game import (
    MultiplayerBalatro, MPPhase, DEFAULT_LIVES, COMEBACK_MONEY_PER_LIFE,
)
from balatro_sim.game import State


# ════════════════════════════════════════════════════════════════════════════
# Initialization
# ════════════════════════════════════════════════════════════════════════════

class TestInit:
    def test_default_lives(self):
        mp = MultiplayerBalatro(seed=42)
        assert mp.p1_lives == DEFAULT_LIVES
        assert mp.p2_lives == DEFAULT_LIVES

    def test_custom_lives(self):
        mp = MultiplayerBalatro(seed=42, lives=2)
        assert mp.p1_lives == 2
        assert mp.p2_lives == 2

    def test_initial_phase(self):
        mp = MultiplayerBalatro(seed=42)
        assert mp.phase == MPPhase.SMALL_BLIND
        assert mp.current_ante == 1

    def test_not_game_over_at_start(self):
        mp = MultiplayerBalatro(seed=42)
        assert not mp.game_over
        assert mp.winner is None


# ════════════════════════════════════════════════════════════════════════════
# Same-seed determinism — both players get same cards
# ════════════════════════════════════════════════════════════════════════════

class TestSameSeed:
    def test_starting_decks_identical_after_play_blind(self):
        """Both players should draw identical hands after playing blind (same seed)."""
        mp = MultiplayerBalatro(seed=42)
        mp.p1_game.step({"type": "play_blind"})
        mp.p2_game.step({"type": "play_blind"})
        # Compare drawn hands + remaining deck
        p1_state = ([(c.rank, c.suit) for c in mp.p1_game.hand] +
                    [(c.rank, c.suit) for c in mp.p1_game.deck])
        p2_state = ([(c.rank, c.suit) for c in mp.p2_game.hand] +
                    [(c.rank, c.suit) for c in mp.p2_game.deck])
        assert p1_state == p2_state

    def test_different_seeds_different_hands(self):
        """Different seeds should produce different drawn hands."""
        mp_a = MultiplayerBalatro(seed=42)
        mp_b = MultiplayerBalatro(seed=9999)
        mp_a.p1_game.step({"type": "play_blind"})
        mp_b.p1_game.step({"type": "play_blind"})
        a_hand = [(c.rank, c.suit) for c in mp_a.p1_game.hand]
        b_hand = [(c.rank, c.suit) for c in mp_b.p1_game.hand]
        assert a_hand != b_hand

    def test_starting_hands_match_when_played_identically(self):
        """If both players play the blind identically, they should draw same cards."""
        mp = MultiplayerBalatro(seed=42)
        # Both play blind
        mp.p1_game.step({"type": "play_blind"})
        mp.p2_game.step({"type": "play_blind"})
        p1_hand = [(c.rank, c.suit) for c in mp.p1_game.hand]
        p2_hand = [(c.rank, c.suit) for c in mp.p2_game.hand]
        assert p1_hand == p2_hand


# ════════════════════════════════════════════════════════════════════════════
# Life management
# ════════════════════════════════════════════════════════════════════════════

class TestLives:
    def test_blind_failure_costs_life(self):
        mp = MultiplayerBalatro(seed=42, lives=3)
        mp.apply_blind_failure(1)
        assert mp.p1_lives == 2
        assert mp.p2_lives == 3

    def test_multiple_failures(self):
        mp = MultiplayerBalatro(seed=42, lives=4)
        mp.apply_blind_failure(1)
        mp.apply_blind_failure(1)
        mp.apply_blind_failure(2)
        assert mp.p1_lives == 2
        assert mp.p2_lives == 3

    def test_zero_lives_ends_game(self):
        mp = MultiplayerBalatro(seed=42, lives=1)
        assert not mp.game_over
        mp.apply_blind_failure(1)
        assert mp.game_over
        assert mp.winner == 2

    def test_winner_when_one_alive(self):
        mp = MultiplayerBalatro(seed=42, lives=2)
        mp.apply_blind_failure(1)
        mp.apply_blind_failure(1)
        assert mp.p1_lives == 0
        assert mp.winner == 2

    def test_invalid_player(self):
        mp = MultiplayerBalatro(seed=42)
        with pytest.raises(ValueError):
            mp.apply_blind_failure(3)


# ════════════════════════════════════════════════════════════════════════════
# PvP resolution
# ════════════════════════════════════════════════════════════════════════════

class TestPvPResolution:
    def test_higher_score_wins(self):
        mp = MultiplayerBalatro(seed=42)
        mp.resolve_pvp(p1_score=1000, p2_score=500)
        # P2 loses a life
        assert mp.p1_lives == DEFAULT_LIVES
        assert mp.p2_lives == DEFAULT_LIVES - 1

    def test_p2_wins_pvp(self):
        mp = MultiplayerBalatro(seed=42)
        mp.resolve_pvp(p1_score=200, p2_score=800)
        assert mp.p1_lives == DEFAULT_LIVES - 1
        assert mp.p2_lives == DEFAULT_LIVES

    def test_tie_no_lives_lost(self):
        mp = MultiplayerBalatro(seed=42)
        mp.resolve_pvp(p1_score=500, p2_score=500)
        assert mp.p1_lives == DEFAULT_LIVES
        assert mp.p2_lives == DEFAULT_LIVES

    def test_comeback_money_on_pvp_loss(self):
        mp = MultiplayerBalatro(seed=42, lives=3)
        p2_starting_dollars = mp.p2_game.dollars
        mp.resolve_pvp(p1_score=1000, p2_score=500)
        # P2 lost 1 life this round, gets COMEBACK_MONEY_PER_LIFE
        assert mp.p2_game.dollars == p2_starting_dollars + COMEBACK_MONEY_PER_LIFE

    def test_pvp_score_stored(self):
        mp = MultiplayerBalatro(seed=42)
        mp.resolve_pvp(p1_score=1200, p2_score=900)
        assert mp._p1_pvp_score == 1200
        assert mp._p2_pvp_score == 900


# ════════════════════════════════════════════════════════════════════════════
# Blind resolution (house rule: regular blind failure costs life)
# ════════════════════════════════════════════════════════════════════════════

class TestBlindResolution:
    def test_small_blind_both_clear(self):
        mp = MultiplayerBalatro(seed=42)
        mp.resolve_small_blind(p1_cleared=True, p2_cleared=True)
        assert mp.p1_lives == DEFAULT_LIVES
        assert mp.p2_lives == DEFAULT_LIVES
        assert mp.phase == MPPhase.BIG_BLIND

    def test_small_blind_p1_fails(self):
        """HOUSE RULE: failing small blind costs a life."""
        mp = MultiplayerBalatro(seed=42)
        mp.resolve_small_blind(p1_cleared=False, p2_cleared=True)
        assert mp.p1_lives == DEFAULT_LIVES - 1
        assert mp.p2_lives == DEFAULT_LIVES
        assert mp.phase == MPPhase.BIG_BLIND

    def test_small_blind_both_fail(self):
        mp = MultiplayerBalatro(seed=42)
        mp.resolve_small_blind(p1_cleared=False, p2_cleared=False)
        assert mp.p1_lives == DEFAULT_LIVES - 1
        assert mp.p2_lives == DEFAULT_LIVES - 1

    def test_big_blind_advances_to_pvp(self):
        mp = MultiplayerBalatro(seed=42)
        mp.resolve_small_blind(True, True)
        mp.resolve_big_blind(True, True)
        assert mp.phase == MPPhase.PVP_BLIND

    def test_pvp_blind_advances_to_shop(self):
        mp = MultiplayerBalatro(seed=42)
        mp.resolve_small_blind(True, True)
        mp.resolve_big_blind(True, True)
        mp.resolve_pvp_blind(p1_score=500, p2_score=400)
        assert mp.phase == MPPhase.SHOP

    def test_game_over_on_small_blind_kill(self):
        """Player can die on small blind (HOUSE RULE)."""
        mp = MultiplayerBalatro(seed=42, lives=1)
        mp.resolve_small_blind(p1_cleared=False, p2_cleared=True)
        assert mp.game_over
        assert mp.winner == 2

    def test_phase_doesnt_advance_when_game_over(self):
        """If game ends on blind resolution, don't advance phase."""
        mp = MultiplayerBalatro(seed=42, lives=1)
        mp.resolve_small_blind(p1_cleared=False, p2_cleared=True)
        # Phase should stay at SMALL_BLIND because game ended
        assert mp.phase == MPPhase.SMALL_BLIND


# ════════════════════════════════════════════════════════════════════════════
# Full game flow
# ════════════════════════════════════════════════════════════════════════════

class TestFullFlow:
    def test_multi_round_game(self):
        """Simulate several rounds of clean PvP play."""
        mp = MultiplayerBalatro(seed=42)
        # Round 1
        mp.resolve_small_blind(True, True)
        mp.resolve_big_blind(True, True)
        mp.resolve_pvp_blind(p1_score=500, p2_score=300)  # P2 loses life
        assert mp.p1_lives == 4
        assert mp.p2_lives == 3
        # Next ante
        mp.advance_to_next_ante()
        assert mp.current_ante == 2
        assert mp.phase == MPPhase.SMALL_BLIND

    def test_p1_wins_by_attrition(self):
        mp = MultiplayerBalatro(seed=42, lives=2)
        # Both clear small/big, then p1 wins pvp 3 times in a row
        for _ in range(2):
            mp.resolve_small_blind(True, True)
            mp.resolve_big_blind(True, True)
            mp.resolve_pvp_blind(p1_score=1000, p2_score=500)
            if not mp.game_over:
                mp.advance_to_next_ante()
        assert mp.game_over
        assert mp.winner == 1

    def test_comeback_money_across_rounds(self):
        """Comeback money should reset each round."""
        mp = MultiplayerBalatro(seed=42, lives=5)
        p1_start = mp.p1_game.dollars
        # Round 1: P1 loses
        mp.resolve_small_blind(True, True)
        mp.resolve_big_blind(True, True)
        mp.resolve_pvp_blind(p1_score=300, p2_score=800)
        # P1 lost 1 life this round, got +$4
        assert mp.p1_game.dollars == p1_start + 4
        mp.advance_to_next_ante()
        # Round 2: P1 loses again (separate round, counter reset)
        mp.resolve_small_blind(True, True)
        mp.resolve_big_blind(True, True)
        mp.resolve_pvp_blind(p1_score=300, p2_score=800)
        # Another +$4, not +$8
        assert mp.p1_game.dollars == p1_start + 8

    def test_multiple_blind_failures_stack_comeback(self):
        """Failing small AND big AND PvP should give comeback money for all 3."""
        mp = MultiplayerBalatro(seed=42, lives=5)
        p1_start = mp.p1_game.dollars
        # P1 fails small (life -1), big (life -1), then loses PvP (life -1)
        mp.resolve_small_blind(p1_cleared=False, p2_cleared=True)
        mp.resolve_big_blind(p1_cleared=False, p2_cleared=True)
        mp.resolve_pvp_blind(p1_score=100, p2_score=500)
        # P1 lost 3 lives this round, gets +$12 comeback money
        assert mp.p1_lives == 2
        assert mp.p1_game.dollars == p1_start + 12


# ════════════════════════════════════════════════════════════════════════════
# Game state queries
# ════════════════════════════════════════════════════════════════════════════

class TestGameState:
    def test_get_state_ongoing(self):
        mp = MultiplayerBalatro(seed=42)
        state = mp.get_state()
        assert state.ante == 1
        assert state.phase == MPPhase.SMALL_BLIND
        assert state.p1_lives == 4
        assert state.p2_lives == 4
        assert not state.game_over
        assert state.winner is None

    def test_get_state_game_over(self):
        mp = MultiplayerBalatro(seed=42, lives=1)
        mp.apply_blind_failure(1)
        state = mp.get_state()
        assert state.game_over
        assert state.winner == 2

    def test_get_player_game(self):
        mp = MultiplayerBalatro(seed=42)
        assert mp.get_player_game(1) is mp.p1_game
        assert mp.get_player_game(2) is mp.p2_game
        with pytest.raises(ValueError):
            mp.get_player_game(3)

    def test_get_lives(self):
        mp = MultiplayerBalatro(seed=42)
        mp.apply_blind_failure(1)
        assert mp.get_lives(1) == 3
        assert mp.get_lives(2) == 4


# ════════════════════════════════════════════════════════════════════════════
# Integration: play actual blinds with the underlying BalatroGame
# ════════════════════════════════════════════════════════════════════════════

class TestIntegration:
    def test_both_players_can_play_identical_games(self):
        """
        Both players on same seed should be able to play identical game states.
        This validates that the two BalatroGame instances don't share state.
        """
        mp = MultiplayerBalatro(seed=42)
        # P1 plays blind, P2 plays blind — should both work independently
        mp.p1_game.step({"type": "play_blind"})
        mp.p2_game.step({"type": "play_blind"})
        assert mp.p1_game.state == State.SELECTING_HAND
        assert mp.p2_game.state == State.SELECTING_HAND
        # Hands should match (same seed)
        assert len(mp.p1_game.hand) == len(mp.p2_game.hand)

    def test_p1_action_doesnt_affect_p2(self):
        """P1 playing cards shouldn't change P2's game state."""
        mp = MultiplayerBalatro(seed=42)
        mp.p1_game.step({"type": "play_blind"})
        mp.p2_game.step({"type": "play_blind"})
        p2_hand_before = [(c.rank, c.suit) for c in mp.p2_game.hand]
        # P1 plays cards
        mp.p1_game.step({"type": "play", "cards": [0, 1]})
        # P2's hand should be unchanged
        p2_hand_after = [(c.rank, c.suit) for c in mp.p2_game.hand]
        assert p2_hand_before == p2_hand_after
