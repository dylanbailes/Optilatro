"""Tests for balatro_sim.env_mp — Multiplayer Balatro environment."""
import numpy as np
import pytest

from balatro_sim.env_mp import (
    MultiplayerBalatroEnv,
    MULTIPLAYER_BANNED_JOKERS, OBS_DIM,
    R_PVP_WIN, R_PVP_LOSS, R_GAME_WIN, R_GAME_LOSS, R_DRAW_BONUS,
)
from balatro_sim.shop import random_joker_key, BANNED_JOKERS, generate_shop
from balatro_sim.env_v7 import PHASE_SELECTING_HAND, PHASE_BLIND_SELECT
from balatro_sim.card_selection import INTENT_PLAY, INTENT_DISCARD


class TestBannedJokers:
    """Multiplayer ruleset bans 4 boss-blind-interaction jokers."""

    def test_banned_set_contains_expected(self):
        assert "j_chicot" in MULTIPLAYER_BANNED_JOKERS
        assert "j_matador" in MULTIPLAYER_BANNED_JOKERS
        assert "j_mr_bones" in MULTIPLAYER_BANNED_JOKERS
        assert "j_luchador" in MULTIPLAYER_BANNED_JOKERS
        assert len(MULTIPLAYER_BANNED_JOKERS) == 4

    def test_banned_jokers_active_when_mp_imported(self):
        """Importing env_mp should activate the ban list."""
        assert MULTIPLAYER_BANNED_JOKERS.issubset(BANNED_JOKERS)

    def test_random_joker_key_excludes_banned(self):
        """Random joker generation should never produce banned jokers."""
        seen = set()
        for _ in range(2000):
            seen.add(random_joker_key())
        for banned in MULTIPLAYER_BANNED_JOKERS:
            assert banned not in seen, f"{banned} appeared in random joker generation"

    def test_random_joker_key_with_rarity_excludes_banned(self):
        """Rarity-restricted joker generation should also exclude banned."""
        # Mr. Bones is Common rarity
        common_seen = set()
        for _ in range(1000):
            common_seen.add(random_joker_key("Common"))
        assert "j_mr_bones" not in common_seen

    def test_shop_excludes_banned_jokers(self):
        """Generated shops should never contain banned jokers."""
        env = MultiplayerBalatroEnv(seed=42)
        env.reset()
        # Trigger many shop generations by checking many seeds
        for seed in range(100):
            env_test = MultiplayerBalatroEnv(seed=seed)
            env_test.reset()
            shop = env_test.mp.p1_game.current_shop
            for item in shop:
                if item.kind == "joker":
                    assert item.key not in MULTIPLAYER_BANNED_JOKERS


class TestMPObsExtension:
    """V8 Run 3: obs is extended with 4 multiplayer state features (447 → 451; tag features push to 480)."""

    def test_obs_dim_is_449(self):
        assert OBS_DIM == 480   # 476 (V7 + 29 tag features) + 4 MP features

    def test_self_lives_in_obs(self):
        env = MultiplayerBalatroEnv(seed=42, lives=4)
        env.reset()
        p1_obs, _ = env.p1.encode_obs(), env.p2.encode_obs()
        assert p1_obs[476] == 1.0  # 4/4 lives
        # After losing a life
        env.mp.apply_blind_failure(1)
        p1_obs = env.p1.encode_obs()
        assert p1_obs[476] == 0.75  # 3/4 lives

    def test_opponent_lives_in_obs(self):
        env = MultiplayerBalatroEnv(seed=42, lives=4)
        env.reset()
        env.mp.apply_blind_failure(2)  # P2 loses a life
        p1_obs = env.p1.encode_obs()
        assert p1_obs[476] == 1.0      # P1 own lives full
        assert p1_obs[477] == 0.75     # P2 lives at 3/4

    def test_is_pvp_flag(self):
        """The is_pvp flag should be 1.0 when the current blind is a boss."""
        env = MultiplayerBalatroEnv(seed=42)
        env.reset()
        # Not on PvP blind initially (small blind)
        p1_obs = env.p1.encode_obs()
        assert p1_obs[479] == 0.0

    def test_obs_has_no_nan(self):
        env = MultiplayerBalatroEnv(seed=42)
        env.reset()
        p1_obs, p2_obs = env.p1.encode_obs(), env.p2.encode_obs()
        assert not np.isnan(p1_obs).any()
        assert not np.isnan(p2_obs).any()


class TestReset:
    def test_returns_two_observations(self):
        env = MultiplayerBalatroEnv(seed=42)
        p1_obs, p2_obs = env.reset()
        assert p1_obs.shape == (OBS_DIM,)
        assert p2_obs.shape == (OBS_DIM,)

    def test_both_observations_initially_same(self):
        """Both players start on same seed → initial observations should be identical."""
        env = MultiplayerBalatroEnv(seed=42)
        p1_obs, p2_obs = env.reset()
        # May differ slightly if one player enters SELECTING_HAND earlier, but
        # at reset both should be in BLIND_SELECT or SELECTING_HAND
        # (not rigorously identical because of RNG state drift in game init)
        # But scalars like ante, dollars, etc. should be same
        np.testing.assert_array_almost_equal(p1_obs[:14], p2_obs[:14])

    def test_reset_clears_episode_reward(self):
        env = MultiplayerBalatroEnv(seed=42)
        env.reset()
        assert env._episode_reward == [0.0, 0.0]

    def test_initial_lives(self):
        env = MultiplayerBalatroEnv(seed=42, lives=3)
        env.reset()
        assert env.mp.p1_lives == 3
        assert env.mp.p2_lives == 3


class TestStep:
    def test_step_returns_valid_shapes(self):
        env = MultiplayerBalatroEnv(seed=42)
        env.reset()
        # Both start in BLIND_SELECT → use phase action 0 (play_blind)
        (p1_obs, p2_obs), (p1_r, p2_r), done, info = env.step(
            {"type": "phase", "action": 0},
            {"type": "phase", "action": 0},
        )
        assert p1_obs.shape == (OBS_DIM,)
        assert p2_obs.shape == (OBS_DIM,)
        assert isinstance(p1_r, float)
        assert isinstance(p2_r, float)
        assert isinstance(done, bool)
        assert "p1_lives" in info
        assert "p2_lives" in info

    def test_step_advances_phase(self):
        """Playing blind should transition from BLIND_SELECT to SELECTING_HAND."""
        env = MultiplayerBalatroEnv(seed=42)
        env.reset()
        # Both play blind
        env.step(
            {"type": "phase", "action": 0},
            {"type": "phase", "action": 0},
        )
        # Now both should be in SELECTING_HAND
        assert env.p1.get_phase() == PHASE_SELECTING_HAND
        assert env.p2.get_phase() == PHASE_SELECTING_HAND

    def test_play_action(self):
        env = MultiplayerBalatroEnv(seed=42)
        env.reset()
        env.step({"type": "phase", "action": 0}, {"type": "phase", "action": 0})
        # Both in SELECTING_HAND, play a hand
        (p1_obs, p2_obs), (p1_r, p2_r), done, info = env.step(
            {"type": "hand", "intent": INTENT_PLAY, "subset": (0, 1, 2, 3, 4)},
            {"type": "hand", "intent": INTENT_PLAY, "subset": (0, 1, 2, 3, 4)},
        )
        # Both should have scored something (even if it's small)
        assert env.mp.p1_game.chips_scored > 0
        assert env.mp.p2_game.chips_scored > 0


class TestIdentity:
    def test_same_action_same_seed_same_scores(self):
        """If both players take identical actions on identical game states, scores match."""
        env = MultiplayerBalatroEnv(seed=42)
        env.reset()
        env.step({"type": "phase", "action": 0}, {"type": "phase", "action": 0})
        env.step(
            {"type": "hand", "intent": INTENT_PLAY, "subset": (0, 1, 2, 3, 4)},
            {"type": "hand", "intent": INTENT_PLAY, "subset": (0, 1, 2, 3, 4)},
        )
        assert env.mp.p1_game.chips_scored == env.mp.p2_game.chips_scored

    def test_different_actions_different_scores(self):
        env = MultiplayerBalatroEnv(seed=42)
        env.reset()
        env.step({"type": "phase", "action": 0}, {"type": "phase", "action": 0})
        env.step(
            {"type": "hand", "intent": INTENT_PLAY, "subset": (0, 1, 2, 3, 4)},  # 5 cards
            {"type": "hand", "intent": INTENT_PLAY, "subset": (0,)},              # 1 card
        )
        assert env.mp.p1_game.chips_scored != env.mp.p2_game.chips_scored


class TestRewards:
    def test_reward_constants_sane(self):
        """V8 Run 4 reward structure: PvP rewards bigger, no life loss penalty."""
        assert R_PVP_WIN > 0
        assert R_PVP_LOSS < 0
        assert R_GAME_WIN > R_PVP_WIN   # Game win worth more than PvP win
        assert R_GAME_LOSS < R_PVP_LOSS # Game loss worse than PvP loss
        assert R_DRAW_BONUS > 0         # Mutual survival bonus is positive


class TestGameTermination:
    def test_terminates_when_player_dies_on_regular_blind(self):
        """V8 Run 4: regular blind failure = game over, survivor wins."""
        env = MultiplayerBalatroEnv(seed=42)
        env.reset()
        # Force override to simulate a game-over state
        from balatro_sim.mp_game import MPPhase
        env.mp.phase = MPPhase.GAME_OVER
        env._winner_override = 2
        # Next step should report done=True
        (p1_obs, p2_obs), (p1_r, p2_r), done, info = env.step(
            {"type": "phase", "action": 0},
            {"type": "phase", "action": 0},
        )
        assert done
        assert info["winner"] == 2


class TestIntegration:
    def test_scripted_full_game(self):
        """
        Play a full multiplayer game with scripted policies.
        Both players play first 5 cards every hand.
        """
        env = MultiplayerBalatroEnv(seed=42, lives=2)
        env.reset()
        max_steps = 500
        done = False
        for _ in range(max_steps):
            if done:
                break
            # Determine action types based on phase
            p1_action = self._scripted_action(env, 1)
            p2_action = self._scripted_action(env, 2)
            (p1_obs, p2_obs), (p1_r, p2_r), done, info = env.step(p1_action, p2_action)
        # Game should have terminated
        assert done or max_steps == 0

    def _scripted_action(self, env, player: int) -> dict:
        """Simple policy: play 5 cards if in SELECTING_HAND, leave shop, play blind."""
        phase_id = env.get_phase(player)
        if phase_id == PHASE_SELECTING_HAND:
            game = env.mp.get_player_game(player)
            k = min(5, len(game.hand))
            if k == 0:
                return {"type": "hand", "intent": INTENT_PLAY, "subset": (0,)}
            return {
                "type": "hand",
                "intent": INTENT_PLAY,
                "subset": tuple(range(k)),
            }
        else:
            # Blind select or shop — find a valid action
            mask = env.get_phase_mask(player)
            valid = [i for i in range(len(mask)) if mask[i]]
            if not valid:
                return {"type": "phase", "action": 15}  # leave shop fallback
            # Prefer leave_shop (15) or play_blind (0)
            if 15 in valid:
                return {"type": "phase", "action": 15}
            if 0 in valid:
                return {"type": "phase", "action": 0}
            return {"type": "phase", "action": valid[0]}

    def test_p1_greedy_beats_p2_minimal_over_many_games(self):
        """Greedy (5-card plays) should consistently outscore minimal (1-card plays)."""
        p1_wins = 0
        p2_wins = 0
        draws = 0
        unterminated = 0
        for seed in range(50, 70):
            env = MultiplayerBalatroEnv(seed=seed, lives=1)
            env.reset()
            max_steps = 200
            done = False
            for _ in range(max_steps):
                if done:
                    break
                p1_action = self._scripted_action(env, 1)
                p2_action = self._minimal_action(env, 2)
                _, _, done, info = env.step(p1_action, p2_action)
            if not done:
                unterminated += 1
            elif info["winner"] == 1:
                p1_wins += 1
            elif info["winner"] == 2:
                p2_wins += 1
            else:
                draws += 1
        # Greedy should win at least as many as minimal
        assert p1_wins >= p2_wins, (
            f"p1={p1_wins}, p2={p2_wins}, draws={draws}, unterminated={unterminated}"
        )

    def _minimal_action(self, env, player: int) -> dict:
        """Play 1 card per hand."""
        phase_id = env.get_phase(player)
        if phase_id == PHASE_SELECTING_HAND:
            return {"type": "hand", "intent": INTENT_PLAY, "subset": (0,)}
        else:
            mask = env.get_phase_mask(player)
            if mask[15]:
                return {"type": "phase", "action": 15}
            if mask[0]:
                return {"type": "phase", "action": 0}
            valid = [i for i in range(len(mask)) if mask[i]]
            return {"type": "phase", "action": valid[0] if valid else 15}
