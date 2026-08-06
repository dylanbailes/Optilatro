"""
test_play_env_v5.py — Tests for V5 play agent environment:
  - Play observation encoding
  - Play action masking
  - Discard / play hand logic
  - Blind select actions
  - Consumable usage during play
"""
from __future__ import annotations

import numpy as np
import pytest

from balatro_sim.env_v5 import (
    BalatroSimEnvV5,
    PLAY_OBS_DIM,
    PLAY_N_ACTIONS,
    COMM_DIM,
    SUBSTATE_NORMAL,
)
from balatro_sim.game import BalatroGame, State
from balatro_sim.consumables import ALL_PLANETS, PLANET_HAND
from balatro_sim.jokers.base import JokerInstance


# ════════════════════════════════════════════════════════════════════════════
# Fixtures
# ════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def env():
    return BalatroSimEnvV5(seed=42)


def _advance_to_selecting(env):
    """Advance until play agent is in SELECTING_HAND state."""
    obs, info = env.reset()
    for _ in range(200):
        if info["agent"] == "play" and env.game.state == State.SELECTING_HAND:
            return obs, info
        agent = info["agent"]
        if agent == "play":
            mask = env.get_play_action_mask()
            valid = np.where(mask)[0]
            action = int(valid[0]) if len(valid) else 30
        else:
            from balatro_sim.env_v5 import SUBSTATE_PACK_OPEN, SUBSTATE_PACK_TARGET
            if info["shop_substate"] == SUBSTATE_PACK_OPEN:
                mask = env.get_pack_open_mask()
            elif info["shop_substate"] == SUBSTATE_PACK_TARGET:
                mask = env.get_pack_target_mask()
            else:
                mask = env.get_shop_action_mask()
            valid = np.where(mask)[0]
            action = int(valid[0]) if len(valid) else 1
        obs, _, terminated, _, info = env.step(action)
        if terminated:
            obs, info = env.reset()
    pytest.skip("Could not reach SELECTING_HAND state")


# ════════════════════════════════════════════════════════════════════════════
# Play observation encoding
# ════════════════════════════════════════════════════════════════════════════

class TestPlayObsEncoding:
    def test_play_obs_shape(self, env):
        obs, info = env.reset()
        assert info["agent"] == "play"
        assert obs.shape == (PLAY_OBS_DIM,)

    def test_play_obs_dtype(self, env):
        obs, _ = env.reset()
        assert obs.dtype == np.float32

    def test_play_obs_finite(self, env):
        obs, _ = env.reset()
        assert np.all(np.isfinite(obs))

    def test_play_obs_comm_vec_is_zeros_initially(self, env):
        obs, _ = env.reset()
        comm_portion = obs[-COMM_DIM:]
        np.testing.assert_array_equal(comm_portion, np.zeros(COMM_DIM))

    def test_play_obs_comm_vec_updates_after_set(self, env):
        obs, _ = env.reset()
        test_vec = np.ones(COMM_DIM, dtype=np.float32) * 0.5
        env.set_comm_vec(test_vec)
        obs2, _ = env._get_obs_and_info()
        comm_portion = obs2[-COMM_DIM:]
        np.testing.assert_array_almost_equal(comm_portion, test_vec)

    def test_play_obs_changes_after_action(self, env):
        obs1, info = env.reset()
        mask = env.get_play_action_mask()
        valid = np.where(mask)[0]
        obs2, _, _, _, _ = env.step(int(valid[0]))
        # Obs should change (new game state)
        assert not np.array_equal(obs1, obs2)


# ════════════════════════════════════════════════════════════════════════════
# Play action masking
# ════════════════════════════════════════════════════════════════════════════

class TestPlayActionMask:
    def test_mask_shape(self, env):
        env.reset()
        mask = env.get_play_action_mask()
        assert mask.shape == (PLAY_N_ACTIONS,)
        assert mask.dtype == bool

    def test_blind_select_mask(self, env):
        env.reset()
        assert env.game.state == State.BLIND_SELECT
        mask = env.get_play_action_mask()
        # Action 30 = play_blind always valid
        assert mask[30] == True
        # Action 31 = skip_blind valid for non-boss (blind_idx != 2)
        if env.game.blind_idx != 2:
            assert mask[31] == True
        else:
            assert mask[31] == False
        # Actions 0-29, 32-45 should be False in BLIND_SELECT
        assert not mask[0]
        assert not mask[20]

    def test_selecting_hand_mask_has_combos(self, env):
        obs, info = _advance_to_selecting(env)
        env._update_play_combos()
        mask = env.get_play_action_mask()
        # There should be at least 1 valid combo (action 0-19)
        assert mask[:20].any()

    def test_selecting_hand_discard_mask(self, env):
        obs, info = _advance_to_selecting(env)
        mask = env.get_play_action_mask()
        if env.game.discards_left > 0 and len(env.game.hand) > 0:
            # Discard actions 20-27 should have some valid
            assert mask[20:28].any()

    def test_boss_blind_cannot_skip(self, env):
        env.reset()
        # Force boss blind
        env.game.blind_idx = 2
        env.game.state = State.BLIND_SELECT
        env.game._prepare_next_blind()
        mask = env.get_play_action_mask()
        assert mask[30] == True   # play
        assert mask[31] == False  # can't skip boss

    def test_no_discard_when_zero_discards(self, env):
        obs, info = _advance_to_selecting(env)
        env.game.discards_left = 0
        mask = env.get_play_action_mask()
        # All discard actions should be False
        assert not mask[20:28].any()

    def test_consumable_mask_planets_only(self, env):
        obs, info = _advance_to_selecting(env)
        # Give a planet
        env.game.consumable_hand = ["pl_mercury"]
        mask = env.get_play_action_mask()
        assert mask[28] == True   # use consumable slot 0
        # Give a tarot (should NOT be usable in play)
        env.game.consumable_hand = ["c_hermit"]
        mask = env.get_play_action_mask()
        assert mask[28] == False


# ════════════════════════════════════════════════════════════════════════════
# Play hand logic
# ════════════════════════════════════════════════════════════════════════════

class TestPlayHandLogic:
    def test_play_combo_scores_chips(self, env):
        obs, info = _advance_to_selecting(env)
        prev_chips = env.game.chips_scored
        # Play first valid combo
        mask = env.get_play_action_mask()
        combo_actions = np.where(mask[:20])[0]
        if len(combo_actions) > 0:
            obs, reward, terminated, _, info = env.step(int(combo_actions[0]))
            assert env.game.chips_scored > prev_chips or env.game.state != State.SELECTING_HAND

    def test_play_reduces_hands_left(self, env):
        obs, info = _advance_to_selecting(env)
        prev_hands = env.game.hands_left
        mask = env.get_play_action_mask()
        combo_actions = np.where(mask[:20])[0]
        if len(combo_actions) > 0:
            env.step(int(combo_actions[0]))
            # Either hands reduced or state changed (blind cleared)
            assert env.game.hands_left < prev_hands or env.game.state != State.SELECTING_HAND

    def test_discard_removes_card_and_draws(self, env):
        obs, info = _advance_to_selecting(env)
        if env.game.discards_left > 0 and len(env.game.hand) > 0:
            prev_discards = env.game.discards_left
            prev_card = env.game.hand[0]
            env.step(20)  # discard card at index 0
            assert env.game.discards_left == prev_discards - 1

    def test_use_planet_during_play(self, env):
        obs, info = _advance_to_selecting(env)
        env.game.consumable_hand = ["pl_mercury"]
        prev_level = env.game.planet_levels.get("Pair", 1)
        env.step(28)  # use consumable slot 0
        assert env.game.planet_levels.get("Pair", 1) == prev_level + 1
        assert "pl_mercury" not in env.game.consumable_hand


# ════════════════════════════════════════════════════════════════════════════
# Blind select
# ════════════════════════════════════════════════════════════════════════════

class TestBlindSelect:
    def test_play_blind_starts_selecting(self, env):
        env.reset()
        assert env.game.state == State.BLIND_SELECT
        env.step(30)  # play_blind
        assert env.game.state == State.SELECTING_HAND

    def test_skip_blind_gives_money(self, env):
        env.reset()
        prev_dollars = env.game.dollars
        env.step(31)  # skip_blind
        assert env.game.dollars >= prev_dollars + 5

    def test_skip_blind_advances(self, env):
        env.reset()
        prev_blind_idx = env.game.blind_idx
        env.step(31)  # skip
        # Should either advance blind or enter shop
        assert env.game.state == State.SHOP

    def test_play_blind_deals_hand(self, env):
        env.reset()
        env.step(30)
        assert len(env.game.hand) > 0
        assert len(env.game.deck) > 0


# ════════════════════════════════════════════════════════════════════════════
# Agent routing
# ════════════════════════════════════════════════════════════════════════════

class TestAgentRouting:
    def test_initial_agent_is_play(self, env):
        _, info = env.reset()
        assert info["agent"] == "play"

    def test_info_contains_required_keys(self, env):
        _, info = env.reset()
        assert "agent" in info
        assert "shop_substate" in info
        assert "pack_choices" in info
        assert "pack_picks_left" in info

    def test_shop_substate_starts_normal(self, env):
        _, info = env.reset()
        assert info["shop_substate"] == SUBSTATE_NORMAL
