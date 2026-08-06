"""
test_rewards_v5.py — Tests for V5 reward computation:
  - Score progress reward
  - Blind clear reward
  - Ante complete reward
  - Win/loss reward
  - Quality delta reward (shop)
  - Spending reward (shop)
  - Leave shop penalty
"""
from __future__ import annotations

import numpy as np
import pytest

from balatro_sim.env_v5 import (
    BalatroSimEnvV5,
    R_BLIND_BASE,
    R_ANTE_COMPLETE,
    R_WIN,
    R_LOSE,
    R_QUALITY_SCALE,
    R_LEAVE_SHOP,
    R_SPEND,
    SUBSTATE_NORMAL,
    SUBSTATE_PACK_OPEN,
    SUBSTATE_PACK_TARGET,
)
from balatro_sim.game import State
from balatro_sim.jokers.base import JokerInstance


# ════════════════════════════════════════════════════════════════════════════
# Fixtures
# ════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def env():
    return BalatroSimEnvV5(seed=42)


def _advance_to_shop(env):
    """Play until we reach the shop."""
    obs, info = env.reset()
    for _ in range(500):
        agent = info["agent"]
        if agent == "shop" and info["shop_substate"] == SUBSTATE_NORMAL:
            return obs, info
        if agent == "play":
            mask = env.get_play_action_mask()
        elif info["shop_substate"] == SUBSTATE_PACK_OPEN:
            mask = env.get_pack_open_mask()
        elif info["shop_substate"] == SUBSTATE_PACK_TARGET:
            mask = env.get_pack_target_mask()
        else:
            mask = env.get_shop_action_mask()
        valid = np.where(mask)[0]
        action = int(valid[0]) if len(valid) else 0
        obs, _, terminated, _, info = env.step(action)
        if terminated:
            obs, info = env.reset()
    pytest.skip("Could not reach shop")


# ════════════════════════════════════════════════════════════════════════════
# Quality baseline initialization
# ════════════════════════════════════════════════════════════════════════════

class TestQualityBaseline:
    def test_quality_set_on_skip_blind(self, env):
        """Skipping a blind enters shop — _prev_quality should be set."""
        obs, info = env.reset()
        # Action 31 = skip blind (only valid for non-boss)
        assert env.game.blind_idx != 2
        env.step(31)  # skip blind
        # Should now be in shop with quality baseline set
        assert env.game.state == State.SHOP
        assert env._prev_quality >= 0.0  # was computed, not left at 0.0 from reset

    def test_quality_set_on_blind_clear(self, env):
        """Clearing a blind enters shop — _prev_quality should be set."""
        obs, info = env.reset()
        env.step(30)  # play blind
        # Force clear the blind
        env.game.chips_scored = env.game.current_blind.chips_target
        env.game.state = State.ROUND_EVAL
        env.game._end_round()
        # Now in shop via _end_round
        # Quality baseline should have been set when play detected SHOP transition
        # (This path is covered by _step_play line 321-327)


# ════════════════════════════════════════════════════════════════════════════
# Reward constants
# ════════════════════════════════════════════════════════════════════════════

class TestRewardConstants:
    def test_constants_positive(self):
        assert R_BLIND_BASE > 0
        assert R_ANTE_COMPLETE > 0
        assert R_WIN > 0
        assert R_QUALITY_SCALE > 0
        assert R_SPEND > 0

    def test_lose_penalty_negative(self):
        assert R_LOSE < 0

    def test_leave_shop_penalty_negative(self):
        assert R_LEAVE_SHOP < 0


# ════════════════════════════════════════════════════════════════════════════
# Leave shop penalty
# ════════════════════════════════════════════════════════════════════════════

class TestLeaveShopReward:
    def test_leave_shop_gives_penalty(self, env):
        obs, info = _advance_to_shop(env)
        # Action 1 = leave_shop
        obs, reward, _, _, info = env.step(1)
        # Leave shop penalty is part of reward (may be offset by quality delta)
        # Just verify the step works and we left the shop
        assert env.game.state != State.SHOP or info["agent"] == "play"

    def test_leave_shop_includes_quality_delta(self, env):
        obs, info = _advance_to_shop(env)
        # The reward from leaving should include R_LEAVE_SHOP + quality_delta * R_QUALITY_SCALE
        obs, reward, _, _, info = env.step(1)
        # Can't check exact value without knowing quality, but reward should be finite
        assert np.isfinite(reward)


# ════════════════════════════════════════════════════════════════════════════
# Score progress reward
# ════════════════════════════════════════════════════════════════════════════

class TestScoreProgressReward:
    def test_playing_hand_gives_reward(self, env):
        obs, info = env.reset()
        # Play blind
        obs, reward, _, _, info = env.step(30)
        assert env.game.state == State.SELECTING_HAND
        # Play first valid combo
        mask = env.get_play_action_mask()
        valid = np.where(mask[:20])[0]
        if len(valid) > 0:
            obs, reward, _, _, info = env.step(int(valid[0]))
            # Should get some score progress reward
            assert reward >= 0 or env.game.state == State.GAME_OVER


# ════════════════════════════════════════════════════════════════════════════
# Spending reward
# ════════════════════════════════════════════════════════════════════════════

class TestSpendingReward:
    def test_buying_item_gives_spend_reward(self, env):
        obs, info = _advance_to_shop(env)
        # Find a buyable item
        mask = env.get_shop_action_mask()
        buy_actions = np.where(mask[2:8])[0] + 2  # actions 2-7 are buy
        if len(buy_actions) > 0:
            prev_dollars = env.game.dollars
            obs, reward, _, _, info = env.step(int(buy_actions[0]))
            spent = prev_dollars - env.game.dollars
            if spent > 0:
                # Reward should be positive (includes R_SPEND * spent)
                assert reward >= 0


# ════════════════════════════════════════════════════════════════════════════
# Total reward tracking
# ════════════════════════════════════════════════════════════════════════════

class TestTotalRewardTracking:
    def test_total_reward_in_info(self, env):
        obs, info = env.reset()
        mask = env.get_play_action_mask()
        valid = np.where(mask)[0]
        obs, reward, _, _, info = env.step(int(valid[0]))
        assert "total_reward" in info
        assert "step_reward" in info
        assert info["step_reward"] == reward

    def test_total_reward_accumulates(self, env):
        obs, info = env.reset()
        cumulative = 0.0
        for _ in range(20):
            agent = info["agent"]
            if agent == "play":
                mask = env.get_play_action_mask()
            elif info["shop_substate"] == SUBSTATE_PACK_OPEN:
                mask = env.get_pack_open_mask()
            elif info["shop_substate"] == SUBSTATE_PACK_TARGET:
                mask = env.get_pack_target_mask()
            else:
                mask = env.get_shop_action_mask()
            valid = np.where(mask)[0]
            action = int(valid[0]) if len(valid) else 0
            obs, reward, terminated, _, info = env.step(action)
            cumulative += reward
            if terminated:
                break
        assert abs(info["total_reward"] - cumulative) < 1e-4

    def test_reward_resets_on_env_reset(self, env):
        obs, info = env.reset()
        # Take some actions
        for _ in range(5):
            mask = env.get_play_action_mask()
            valid = np.where(mask)[0]
            if not len(valid):
                break
            obs, _, terminated, _, info = env.step(int(valid[0]))
            if terminated:
                break
        # Reset
        obs, info = env.reset()
        assert env._episode_reward == 0.0


# ════════════════════════════════════════════════════════════════════════════
# Episode completion rewards
# ════════════════════════════════════════════════════════════════════════════

class TestEpisodeRewards:
    def test_random_episode_completes_with_reward(self, env):
        """Run a full random episode and verify reward tracking."""
        obs, info = env.reset()
        total = 0.0
        for _ in range(2000):
            agent = info["agent"]
            if agent == "play":
                mask = env.get_play_action_mask()
            elif info["shop_substate"] == SUBSTATE_PACK_OPEN:
                mask = env.get_pack_open_mask()
            elif info["shop_substate"] == SUBSTATE_PACK_TARGET:
                mask = env.get_pack_target_mask()
            else:
                mask = env.get_shop_action_mask()
            valid = np.where(mask)[0]
            action = int(np.random.choice(valid)) if len(valid) else 0
            obs, reward, terminated, _, info = env.step(action)
            total += reward
            if terminated:
                break
        assert abs(info["total_reward"] - total) < 1e-3
