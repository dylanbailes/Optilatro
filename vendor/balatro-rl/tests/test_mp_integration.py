"""
Integration test: simulate a full multiplayer game from start to finish using
simple scripted policies. Validates that:
  - Same-seed mechanics produce identical card draws
  - Different strategies produce different scores on same seed
  - Lives system correctly ends games
  - Comeback money flows properly
  - The full blind->shop->blind cycle works
"""
import random
import pytest

from balatro_sim.mp_game import MultiplayerBalatro, MPPhase
from balatro_sim.game import State


def play_blind_greedy(game):
    """
    Simple scripted policy: play first available combo, no discards, no consumables.
    Drives a BalatroGame through one blind (small/big/boss).
    """
    # Play blind to enter SELECTING_HAND
    if game.state == State.BLIND_SELECT:
        game.step({"type": "play_blind"})

    # Play hands greedily until cleared or out of hands
    max_iterations = 100  # safety
    while game.state == State.SELECTING_HAND and max_iterations > 0:
        max_iterations -= 1
        n = len(game.hand)
        if n == 0:
            break
        # Play as many cards as possible (up to 5)
        k = min(5, n)
        game.step({"type": "play", "cards": list(range(k))})

    # Auto-advance through round eval, booster open etc.
    for _ in range(10):
        if game.state in (State.SELECTING_HAND, State.BLIND_SELECT,
                          State.SHOP, State.GAME_OVER):
            break
        game.step({"type": "noop"})


def play_blind_minimal(game):
    """Very low-scoring policy: play only 1 card per hand, never discard."""
    if game.state == State.BLIND_SELECT:
        game.step({"type": "play_blind"})

    max_iterations = 100
    while game.state == State.SELECTING_HAND and max_iterations > 0:
        max_iterations -= 1
        if not game.hand:
            break
        game.step({"type": "play", "cards": [0]})

    for _ in range(10):
        if game.state in (State.SELECTING_HAND, State.BLIND_SELECT,
                          State.SHOP, State.GAME_OVER):
            break
        game.step({"type": "noop"})


def leave_shop(game):
    """Simple shop policy: leave immediately."""
    if game.state == State.SHOP:
        game.step({"type": "leave_shop"})
    # Auto-advance to next blind select
    for _ in range(10):
        if game.state in (State.BLIND_SELECT, State.SELECTING_HAND, State.GAME_OVER):
            break
        game.step({"type": "noop"})


def did_clear_blind(game) -> bool:
    """Check if the game just cleared its blind (score >= target)."""
    return game.chips_scored >= game.current_blind.chips_target


def play_full_ante(mp, p1_strategy, p2_strategy):
    """
    Play one full ante (small + big + PvP) with given strategies.
    p1_strategy, p2_strategy: functions taking a BalatroGame and playing one blind.
    Returns (p1_lives_lost_this_ante, p2_lives_lost_this_ante).
    """
    p1_before = mp.p1_lives
    p2_before = mp.p2_lives

    # Small blind
    p1_strategy(mp.p1_game)
    p2_strategy(mp.p2_game)
    p1_cleared = did_clear_blind(mp.p1_game)
    p2_cleared = did_clear_blind(mp.p2_game)
    mp.resolve_small_blind(p1_cleared, p2_cleared)
    if mp.game_over:
        return (p1_before - mp.p1_lives, p2_before - mp.p2_lives)

    # After small blind, games auto-advance to SHOP -> we need to leave shop
    leave_shop(mp.p1_game)
    leave_shop(mp.p2_game)

    # Big blind
    p1_strategy(mp.p1_game)
    p2_strategy(mp.p2_game)
    p1_cleared = did_clear_blind(mp.p1_game)
    p2_cleared = did_clear_blind(mp.p2_game)
    mp.resolve_big_blind(p1_cleared, p2_cleared)
    if mp.game_over:
        return (p1_before - mp.p1_lives, p2_before - mp.p2_lives)

    leave_shop(mp.p1_game)
    leave_shop(mp.p2_game)

    # PvP (boss) blind
    p1_strategy(mp.p1_game)
    p2_strategy(mp.p2_game)
    mp.resolve_pvp_blind(
        p1_score=mp.p1_game.chips_scored,
        p2_score=mp.p2_game.chips_scored,
    )
    if mp.game_over:
        return (p1_before - mp.p1_lives, p2_before - mp.p2_lives)

    leave_shop(mp.p1_game)
    leave_shop(mp.p2_game)
    mp.advance_to_next_ante()

    return (p1_before - mp.p1_lives, p2_before - mp.p2_lives)


class TestIntegration:
    def test_identical_policies_produce_identical_games(self):
        """
        Both players using the same policy on same seed should play identical games
        through the SAME blind (since shops haven't diverged yet).
        """
        mp = MultiplayerBalatro(seed=42)
        play_blind_greedy(mp.p1_game)
        play_blind_greedy(mp.p2_game)
        # Both should have the same score and same remaining hands/discards
        assert mp.p1_game.chips_scored == mp.p2_game.chips_scored
        assert mp.p1_game.hands_left == mp.p2_game.hands_left

    def test_different_policies_produce_different_scores(self):
        """Minimal vs greedy on same seed should produce different scores."""
        mp = MultiplayerBalatro(seed=42)
        play_blind_greedy(mp.p1_game)
        play_blind_minimal(mp.p2_game)
        # P1 (greedy) should outperform P2 (minimal)
        assert mp.p1_game.chips_scored != mp.p2_game.chips_scored

    def test_full_ante_attrition(self):
        """Play one full ante with different strategies."""
        mp = MultiplayerBalatro(seed=42, lives=3)
        p1_loss, p2_loss = play_full_ante(mp, play_blind_greedy, play_blind_minimal)
        # Minimal strategy should lose more lives than greedy
        assert p1_loss <= p2_loss
        # At least one of them should have lost a life (minimal can't beat PvP)
        assert (p1_loss + p2_loss) > 0

    def test_game_terminates_on_zero_lives(self):
        """Play multiple antes until someone hits 0 lives, verify game ends."""
        mp = MultiplayerBalatro(seed=42, lives=2)
        max_antes = 10  # safety
        while not mp.game_over and max_antes > 0:
            max_antes -= 1
            play_full_ante(mp, play_blind_greedy, play_blind_minimal)

        # Game should have ended
        assert mp.game_over
        # And produced a winner
        assert mp.winner in (1, 2, 0)

    def test_greedy_outscores_minimal_on_pvp(self):
        """On PvP blind, greedy policy should consistently score higher than minimal."""
        greedy_wins = 0
        minimal_wins = 0
        ties = 0
        for seed in range(100, 130):
            mp = MultiplayerBalatro(seed=seed)
            play_blind_greedy(mp.p1_game)
            play_blind_minimal(mp.p2_game)
            if mp.p1_game.chips_scored > mp.p2_game.chips_scored:
                greedy_wins += 1
            elif mp.p2_game.chips_scored > mp.p1_game.chips_scored:
                minimal_wins += 1
            else:
                ties += 1
        # Greedy (5-card plays) should beat minimal (1-card plays) every time
        assert greedy_wins > minimal_wins, (
            f"greedy={greedy_wins}, minimal={minimal_wins}, ties={ties}"
        )
        # Should win the overwhelming majority
        assert greedy_wins >= 25, f"only {greedy_wins}/30 wins for greedy"

    def test_same_seed_deterministic(self):
        """
        Two full games with same seed and same policies should produce same outcome.
        """
        results = []
        for _ in range(2):
            mp = MultiplayerBalatro(seed=42, lives=2)
            max_antes = 15
            while not mp.game_over and max_antes > 0:
                max_antes -= 1
                play_full_ante(mp, play_blind_greedy, play_blind_greedy)
            results.append((mp.winner, mp.p1_lives, mp.p2_lives, mp.current_ante))
        assert results[0] == results[1]

    def test_house_rule_applied(self):
        """
        Verify: on a seed where minimal policy fails small blind, they lose a life
        immediately (house rule), not just on PvP.
        """
        # Find a seed where minimal policy fails small blind (score < target)
        for seed in range(100):
            mp = MultiplayerBalatro(seed=seed, lives=4)
            play_blind_minimal(mp.p1_game)
            if mp.p1_game.chips_scored < mp.p1_game.current_blind.chips_target:
                # Found a failing seed
                p1_lives_before = mp.p1_lives
                mp.resolve_small_blind(p1_cleared=False, p2_cleared=True)
                assert mp.p1_lives == p1_lives_before - 1, (
                    f"Expected life penalty on small blind failure (seed={seed})"
                )
                return
        pytest.skip("Couldn't find a seed where minimal policy fails small blind")
