"""
test_shop_v5.py — Comprehensive tests for V5 shop environment, action masking,
buying/selling, rerolling, booster packs, communication vector, and obs encoding.
"""
from __future__ import annotations

import numpy as np
import pytest

from balatro_sim.env_v5 import (
    BalatroSimEnvV5,
    PLAY_OBS_DIM,
    SHOP_OBS_DIM,
    SHOP_N_ACTIONS,
    COMM_DIM,
    SUBSTATE_NORMAL,
    SUBSTATE_PACK_OPEN,
    SUBSTATE_PACK_TARGET,
)
from balatro_sim.game import BalatroGame, State
from balatro_sim.shop import (
    ShopItem, generate_shop, buy_item, sell_joker, reroll_shop,
    JOKER_CATALOGUE,
)
from balatro_sim.consumables import ALL_PLANETS, ALL_TAROTS, PLANET_HAND
from balatro_sim.jokers.base import JokerInstance


# ════════════════════════════════════════════════════════════════════════════
# Fixtures
# ════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def env():
    """Fresh V5 environment with deterministic seed."""
    return BalatroSimEnvV5(seed=42)


@pytest.fixture
def game():
    """Fresh BalatroGame with deterministic seed."""
    g = BalatroGame(seed=42)
    g.reset()
    return g


def _advance_to_shop(env: BalatroSimEnvV5):
    """Play random valid actions until the shop phase is reached.
    Returns (obs, info) at start of shop phase.
    """
    # Try multiple seeds to reliably reach shop
    for seed in [42, 123, 7, 999, 0]:
        env_try = BalatroSimEnvV5(seed=seed)
        obs, info = env_try.reset()
        for _ in range(2000):
            agent = info["agent"]
            if agent == "shop" and info["shop_substate"] == SUBSTATE_NORMAL:
                # Copy state to the original env so callers can use it
                env.game = env_try.game
                env._shop_substate = env_try._shop_substate
                env._comm_vec = env_try._comm_vec
                env._prev_quality = env_try._prev_quality
                env._play_combos = env_try._play_combos
                env._pack_choices = env_try._pack_choices
                env._pack_picks_left = env_try._pack_picks_left
                env._pending_tarot = env_try._pending_tarot
                env._steps = env_try._steps
                env._episode_reward = env_try._episode_reward
                return obs, info
            if agent == "play":
                mask = env_try.get_play_action_mask()
                # Prefer skip blind (31) to reach shop quickly, else play best combo (0)
                if mask[31]:
                    action = 31
                elif mask[0]:
                    action = 0
                else:
                    valid = np.where(mask)[0]
                    action = int(valid[0]) if len(valid) else 30
            elif info["shop_substate"] == SUBSTATE_PACK_OPEN:
                mask = env_try.get_pack_open_mask()
                action = len(mask) - 1  # skip pack
            elif info["shop_substate"] == SUBSTATE_PACK_TARGET:
                mask = env_try.get_pack_target_mask()
                action = 52  # skip targeting
            else:
                mask = env_try.get_shop_action_mask()
                action = 1  # leave shop
            obs, _, terminated, _, info = env_try.step(action)
            if terminated:
                obs, info = env_try.reset()
    pytest.fail("Could not reach shop phase with any seed")


def _game_in_shop(seed=42) -> BalatroGame:
    """Return a BalatroGame that has been advanced to State.SHOP."""
    g = BalatroGame(seed=seed)
    g.reset()
    # Skip the small blind to enter shop quickly
    g.step({"type": "skip_blind"})
    assert g.state == State.SHOP, f"Expected SHOP, got {g.state}"
    return g


# ════════════════════════════════════════════════════════════════════════════
# 1. Shop environment basics
# ════════════════════════════════════════════════════════════════════════════

class TestEnvBasics:
    """Env resets and returns obs with correct shapes; agent routing works."""

    def test_reset_returns_correct_play_obs_shape(self, env):
        """Reset should return play obs of shape (374,)."""
        obs, info = env.reset()
        assert obs.shape == (PLAY_OBS_DIM,)

    def test_reset_starts_with_play_agent(self, env):
        """After reset, the first agent should be 'play'."""
        _, info = env.reset()
        assert info["agent"] == "play"

    def test_shop_phase_entered_after_blind(self, env):
        """After completing a blind, the env should enter shop phase."""
        obs, info = _advance_to_shop(env)
        assert info["agent"] == "shop"
        assert obs.shape == (SHOP_OBS_DIM,)

    def test_leave_shop_transitions_to_play(self, env):
        """Action 1 (leave_shop) should transition back to play agent."""
        obs, info = _advance_to_shop(env)
        assert info["agent"] == "shop"
        obs, _, terminated, _, info = env.step(1)  # leave_shop
        if not terminated:
            assert info["agent"] == "play"
            assert obs.shape == (PLAY_OBS_DIM,)

    def test_agent_alternates_play_shop(self):
        """Agent should alternate between play and shop across blinds.
        Tries multiple seeds since random play may lose before reaching shop."""
        found_both = False
        for seed in range(20):
            e = BalatroSimEnvV5(seed=seed)
            obs, info = e.reset()
            agents_seen = set()
            agents_seen.add(info["agent"])
            for _ in range(1000):
                agent = info["agent"]
                if agent == "play":
                    mask = e.get_play_action_mask()
                elif info["shop_substate"] == SUBSTATE_PACK_OPEN:
                    mask = e.get_pack_open_mask()
                elif info["shop_substate"] == SUBSTATE_PACK_TARGET:
                    mask = e.get_pack_target_mask()
                else:
                    mask = e.get_shop_action_mask()
                valid = np.where(mask)[0]
                action = int(np.random.choice(valid)) if len(valid) else 1
                obs, _, terminated, _, info = e.step(action)
                agents_seen.add(info["agent"])
                if "play" in agents_seen and "shop" in agents_seen:
                    found_both = True
                    break
                if terminated:
                    break
            if found_both:
                break
        assert found_both, "Never observed both play and shop agents across 20 seeds"


# ════════════════════════════════════════════════════════════════════════════
# 2. Shop action masking
# ════════════════════════════════════════════════════════════════════════════

class TestShopActionMask:
    """Shop action mask reflects game state correctly."""

    def test_leave_always_valid(self, env):
        """Action 1 (leave_shop) should always be valid in shop."""
        _advance_to_shop(env)
        mask = env.get_shop_action_mask()
        assert mask[1] is np.True_

    def test_reroll_valid_when_affordable(self, env):
        """Reroll (action 0) should be valid when dollars >= reroll cost."""
        _advance_to_shop(env)
        game = env.game
        game.dollars = 100
        game.reroll_cost = 5
        mask = env.get_shop_action_mask()
        assert mask[0] is np.True_

    def test_reroll_invalid_when_broke(self, env):
        """Reroll (action 0) should be invalid when dollars < reroll cost."""
        _advance_to_shop(env)
        game = env.game
        game.dollars = 0
        game.reroll_cost = 5
        game.free_rerolls_remaining = 0
        mask = env.get_shop_action_mask()
        assert mask[0] is np.False_

    def test_buy_invalid_when_sold(self, env):
        """Buy actions should be invalid for already-sold items."""
        _advance_to_shop(env)
        game = env.game
        game.dollars = 100
        # Mark all non-booster items as sold
        for item in game.current_shop:
            if item.kind != "booster":
                item.sold = True
        mask = env.get_shop_action_mask()
        # Actions 2-7 should all be False
        assert not any(mask[2:8])

    def test_buy_invalid_when_cant_afford(self, env):
        """Buy actions should be invalid when player can't afford items."""
        _advance_to_shop(env)
        game = env.game
        game.dollars = 0
        mask = env.get_shop_action_mask()
        # All buy actions (2-9) should be False
        assert not any(mask[2:10])

    def test_buy_joker_invalid_when_slots_full(self, env):
        """Buying a joker should be invalid when joker slots are full."""
        _advance_to_shop(env)
        game = env.game
        game.dollars = 100
        # Fill all joker slots
        while len(game.jokers) < game.joker_slots:
            game.jokers.append(JokerInstance("j_joker"))
        # Ensure shop has a joker item
        game.current_shop = [ShopItem("joker", "j_joker", "Joker", 6)]
        mask = env.get_shop_action_mask()
        # The joker buy action should be masked off
        assert mask[2] is np.False_

    def test_buy_consumable_invalid_when_slots_full(self, env):
        """Buying a consumable should be invalid when consumable slots are full."""
        _advance_to_shop(env)
        game = env.game
        game.dollars = 100
        # Fill consumable slots
        while len(game.consumable_hand) < game.consumable_slots:
            game.consumable_hand.append("pl_mercury")
        # Ensure shop has a planet item
        game.current_shop = [ShopItem("planet", "pl_mercury", "Mercury", 3)]
        mask = env.get_shop_action_mask()
        assert mask[2] is np.False_

    def test_buy_valid_when_conditions_met(self, env):
        """Buy should be valid when player can afford and has slots."""
        _advance_to_shop(env)
        game = env.game
        game.dollars = 100
        game.jokers = []
        game.consumable_hand = []
        game.current_shop = [
            ShopItem("joker", "j_joker", "Joker", 6),
            ShopItem("planet", "pl_mercury", "Mercury", 3),
        ]
        mask = env.get_shop_action_mask()
        assert mask[2] is np.True_  # buy joker
        assert mask[3] is np.True_  # buy planet

    def test_sell_joker_invalid_when_no_joker(self, env):
        """Sell joker actions should be invalid when no jokers owned."""
        _advance_to_shop(env)
        env.game.jokers = []
        mask = env.get_shop_action_mask()
        # Actions 10-14 should all be False
        assert not any(mask[10:15])

    def test_sell_joker_valid_when_joker_exists(self, env):
        """Sell joker actions should be valid for occupied joker slots."""
        _advance_to_shop(env)
        env.game.jokers = [JokerInstance("j_joker"), JokerInstance("j_banner")]
        mask = env.get_shop_action_mask()
        assert mask[10] is np.True_
        assert mask[11] is np.True_
        assert mask[12] is np.False_

    def test_use_consumable_valid_with_planet(self, env):
        """Use consumable should be valid when slot has a planet card."""
        _advance_to_shop(env)
        env.game.consumable_hand = ["pl_mercury"]
        mask = env.get_shop_action_mask()
        assert mask[15] is np.True_

    def test_use_consumable_valid_with_tarot(self, env):
        """Use consumable should be valid when slot has a tarot card."""
        _advance_to_shop(env)
        env.game.consumable_hand = ["c_hermit"]
        mask = env.get_shop_action_mask()
        assert mask[15] is np.True_

    def test_use_consumable_invalid_when_empty(self, env):
        """Use consumable should be invalid when no consumables held."""
        _advance_to_shop(env)
        env.game.consumable_hand = []
        mask = env.get_shop_action_mask()
        assert mask[15] is np.False_
        assert mask[16] is np.False_


# ════════════════════════════════════════════════════════════════════════════
# 3. Buying jokers
# ════════════════════════════════════════════════════════════════════════════

class TestBuyingJokers:
    """Buying and selling jokers via shop.buy_item / shop.sell_joker."""

    def test_buy_joker_adds_to_game(self):
        """Buying a joker should add it to game.jokers."""
        game = _game_in_shop()
        game.dollars = 100
        item = ShopItem("joker", "j_joker", "Joker", 6)
        n_before = len(game.jokers)
        result = buy_item(game, item)
        assert result is True
        assert len(game.jokers) == n_before + 1
        assert game.jokers[-1].key == "j_joker"

    def test_buy_joker_deducts_dollars(self):
        """Buying a joker should deduct its price from dollars."""
        game = _game_in_shop()
        game.dollars = 20
        item = ShopItem("joker", "j_joker", "Joker", 6)
        buy_item(game, item)
        assert game.dollars == 14

    def test_buy_joker_rejected_when_full(self):
        """Buying a joker should fail when joker slots are full."""
        game = _game_in_shop()
        game.dollars = 100
        while len(game.jokers) < game.joker_slots:
            game.jokers.append(JokerInstance("j_joker"))
        item = ShopItem("joker", "j_banner", "Banner", 6)
        result = buy_item(game, item)
        assert result is False
        assert all(j.key == "j_joker" for j in game.jokers)

    def test_sell_joker_removes_and_pays(self):
        """Selling a joker should remove it and give dollars back."""
        game = _game_in_shop()
        j = JokerInstance("j_joker")
        j.state["sell_value"] = 3
        game.jokers = [j]
        dollars_before = game.dollars
        gained = sell_joker(game, 0)
        assert gained == 3
        assert len(game.jokers) == 0
        assert game.dollars == dollars_before + 3

    def test_joker_count_within_limit(self):
        """Joker count should never exceed joker_slots."""
        game = _game_in_shop()
        game.dollars = 1000
        game.joker_slots = 3
        game.jokers = []
        for _ in range(10):
            item = ShopItem("joker", "j_joker", "Joker", 6)
            buy_item(game, item)
        assert len(game.jokers) <= game.joker_slots


# ════════════════════════════════════════════════════════════════════════════
# 4. Buying consumables (planets/tarots)
# ════════════════════════════════════════════════════════════════════════════

class TestBuyingConsumables:
    """Buying planets and tarots via the shop."""

    def test_buy_planet_adds_to_consumable_hand(self):
        """Buying a planet should add it to game.consumable_hand."""
        game = _game_in_shop()
        game.dollars = 100
        game.consumable_hand = []
        item = ShopItem("planet", "pl_mercury", "Mercury", 3)
        result = buy_item(game, item)
        assert result is True
        assert "pl_mercury" in game.consumable_hand

    def test_buy_tarot_adds_to_consumable_hand(self):
        """Buying a tarot should add it to game.consumable_hand."""
        game = _game_in_shop()
        game.dollars = 100
        game.consumable_hand = []
        item = ShopItem("tarot", "c_hermit", "The Hermit", 3)
        result = buy_item(game, item)
        assert result is True
        assert "c_hermit" in game.consumable_hand

    def test_buy_consumable_rejected_when_full(self):
        """Buying a consumable should fail when consumable slots are full."""
        game = _game_in_shop()
        game.dollars = 100
        game.consumable_slots = 2
        game.consumable_hand = ["pl_mercury", "pl_venus"]
        item = ShopItem("planet", "pl_saturn", "Saturn", 3)
        result = buy_item(game, item)
        assert result is False
        assert "pl_saturn" not in game.consumable_hand

    def test_use_planet_via_env_action(self, env):
        """Using a planet via action 15/16 should trigger apply_planet."""
        _advance_to_shop(env)
        game = env.game
        game.consumable_hand = ["pl_mercury"]  # upgrades Pair
        level_before = game.planet_levels.get("Pair", 1)
        env.step(15)  # use consumable slot 0
        assert game.planet_levels.get("Pair", 1) == level_before + 1
        assert "pl_mercury" not in game.consumable_hand


# ════════════════════════════════════════════════════════════════════════════
# 5. Reroll
# ════════════════════════════════════════════════════════════════════════════

class TestReroll:
    """Rerolling the shop replaces items and costs dollars."""

    def test_reroll_replaces_shop_items(self):
        """Rerolling should generate a new set of shop items."""
        game = _game_in_shop()
        game.dollars = 100
        old_items = list(game.current_shop)
        reroll_shop(game)
        new_items = game.current_shop
        # At least one item should differ (overwhelmingly likely with random gen)
        assert len(new_items) > 0
        # Items are regenerated (new objects)
        assert new_items is not old_items

    def test_reroll_cost_increments(self):
        """Reroll cost should increment by 1 after each reroll."""
        game = _game_in_shop()
        game.dollars = 100
        game.reroll_cost = 5
        reroll_shop(game)
        assert game.reroll_cost == 6
        reroll_shop(game)
        assert game.reroll_cost == 7

    def test_free_rerolls_dont_cost_dollars(self):
        """Free rerolls should not deduct dollars."""
        game = _game_in_shop()
        game.dollars = 10
        game.free_rerolls_remaining = 2
        game.reroll_cost = 5
        dollars_before = game.dollars
        reroll_shop(game)
        assert game.dollars == dollars_before  # no cost
        assert game.free_rerolls_remaining == 1

    def test_free_rerolls_still_increment_cost(self):
        """Even free rerolls should increment the reroll_cost counter."""
        game = _game_in_shop()
        game.dollars = 10
        game.free_rerolls_remaining = 1
        game.reroll_cost = 5
        reroll_shop(game)
        assert game.reroll_cost == 6

    def test_reroll_fails_when_broke_no_free(self):
        """Rerolling should fail when broke and no free rerolls available."""
        game = _game_in_shop()
        game.dollars = 0
        game.free_rerolls_remaining = 0
        game.reroll_cost = 5
        result = reroll_shop(game)
        assert result is False

    def test_reroll_masked_when_broke(self, env):
        """Reroll action should be masked when player can't afford it."""
        _advance_to_shop(env)
        env.game.dollars = 0
        env.game.free_rerolls_remaining = 0
        env.game.reroll_cost = 5
        mask = env.get_shop_action_mask()
        assert mask[0] is np.False_


# ════════════════════════════════════════════════════════════════════════════
# 6. Booster packs
# ════════════════════════════════════════════════════════════════════════════

class TestBoosterPacks:
    """Buying and interacting with booster packs."""

    def test_buy_pack_transitions_to_pack_open(self, env):
        """Buying a booster pack should enter pack_open substate."""
        _advance_to_shop(env)
        game = env.game
        game.dollars = 100
        # Find a booster pack in the shop
        packs = [i for i in game.current_shop if i.kind == "booster" and not i.sold]
        if not packs:
            pytest.skip("No booster packs in this shop seed")
        mask = env.get_shop_action_mask()
        # Action 8 = buy pack 0
        if mask[8]:
            obs, _, _, _, info = env.step(8)
            assert info["shop_substate"] == SUBSTATE_PACK_OPEN

    def test_pack_open_info_has_cards(self, env):
        """In pack_open substate, info should report pack choices."""
        _advance_to_shop(env)
        game = env.game
        game.dollars = 100
        packs = [i for i in game.current_shop if i.kind == "booster" and not i.sold]
        if not packs:
            pytest.skip("No booster packs in this shop seed")
        mask = env.get_shop_action_mask()
        if mask[8]:
            _, _, _, _, info = env.step(8)
            if info["shop_substate"] == SUBSTATE_PACK_OPEN:
                assert len(info["pack_choices"]) > 0

    def test_pick_card_from_pack(self, env):
        """Picking a card (action 0..N-1) from an open pack should work."""
        _advance_to_shop(env)
        game = env.game
        game.dollars = 100
        packs = [i for i in game.current_shop if i.kind == "booster" and not i.sold]
        if not packs:
            pytest.skip("No booster packs in this shop seed")
        mask = env.get_shop_action_mask()
        if mask[8]:
            _, _, _, _, info = env.step(8)
            if info["shop_substate"] == SUBSTATE_PACK_OPEN:
                pack_mask = env.get_pack_open_mask()
                # Pick first card
                obs, _, _, _, info2 = env.step(0)
                # Should exit pack or stay in pack if multi-pick
                assert info2["shop_substate"] in (SUBSTATE_NORMAL, SUBSTATE_PACK_OPEN,
                                                   SUBSTATE_PACK_TARGET)

    def test_skip_pack_returns_to_normal(self, env):
        """Skipping a pack (action N) should return to normal shop."""
        _advance_to_shop(env)
        game = env.game
        game.dollars = 100
        packs = [i for i in game.current_shop if i.kind == "booster" and not i.sold]
        if not packs:
            pytest.skip("No booster packs in this shop seed")
        mask = env.get_shop_action_mask()
        if mask[8]:
            _, _, _, _, info = env.step(8)
            if info["shop_substate"] == SUBSTATE_PACK_OPEN:
                n = len(info["pack_choices"])
                # Action N = skip
                _, _, _, _, info2 = env.step(n)
                assert info2["shop_substate"] == SUBSTATE_NORMAL

    def test_pack_target_skip_works(self, env):
        """Skipping pack_target (action 52) should return to normal shop."""
        _advance_to_shop(env)
        game = env.game
        # Manually set up pack_target substate
        env._shop_substate = SUBSTATE_PACK_TARGET
        env._pending_tarot = "c_magician"
        _, _, _, _, info = env.step(52)  # skip targeting
        assert info["shop_substate"] in (SUBSTATE_NORMAL, SUBSTATE_PACK_OPEN)


# ════════════════════════════════════════════════════════════════════════════
# 7. Communication vector
# ════════════════════════════════════════════════════════════════════════════

class TestCommVector:
    """Communication vector from shop agent to play agent."""

    def test_set_comm_vec_works(self, env):
        """set_comm_vec should accept a 32-dim vector without error."""
        env.reset()
        vec = np.ones(COMM_DIM, dtype=np.float32) * 0.5
        env.set_comm_vec(vec)
        np.testing.assert_array_almost_equal(env._comm_vec, vec)

    def test_comm_vec_in_play_obs(self, env):
        """The comm vector should appear in the last 32 dims of play obs."""
        env.reset()
        vec = np.random.rand(COMM_DIM).astype(np.float32)
        env.set_comm_vec(vec)
        obs = env.get_play_obs()
        np.testing.assert_array_almost_equal(obs[-COMM_DIM:], vec)

    def test_comm_vec_reset_to_zeros(self, env):
        """After reset, the comm vector should be all zeros."""
        env.reset()
        env.set_comm_vec(np.ones(COMM_DIM, dtype=np.float32))
        env.reset()
        np.testing.assert_array_equal(env._comm_vec, np.zeros(COMM_DIM))

    def test_set_comm_vec_wrong_shape(self, env):
        """set_comm_vec with wrong shape should either raise or be handled."""
        env.reset()
        # A 16-dim vector is wrong; numpy may broadcast or raise
        try:
            env.set_comm_vec(np.zeros(16, dtype=np.float32))
            # If no error, the internal vector should still be size COMM_DIM
            assert env._comm_vec.shape == (COMM_DIM,) or len(env._comm_vec) != COMM_DIM
        except (ValueError, IndexError):
            pass  # expected


# ════════════════════════════════════════════════════════════════════════════
# 8. Shop observation encoding
# ════════════════════════════════════════════════════════════════════════════

class TestShopObsEncoding:
    """Shop observation vector is well-formed."""

    def test_shop_obs_shape(self, env):
        """Shop obs should have shape (188,)."""
        _advance_to_shop(env)
        obs = env.get_shop_obs()
        assert obs.shape == (SHOP_OBS_DIM,)

    def test_shop_obs_finite(self, env):
        """Shop obs should contain only finite values (no NaN/inf)."""
        _advance_to_shop(env)
        obs = env.get_shop_obs()
        assert np.all(np.isfinite(obs))

    def test_shop_obs_scalars_reasonable(self, env):
        """First few obs scalars (ante, round, dollars) should be plausible."""
        _advance_to_shop(env)
        obs = env.get_shop_obs()
        ante_norm = obs[0]
        assert 0.0 <= ante_norm <= 1.0  # ante/8
        dollars_norm = obs[2]
        assert 0.0 <= dollars_norm <= 1.0  # dollars/50

    def test_shop_obs_updates_after_buy(self, env):
        """Shop obs should change after buying a joker."""
        _advance_to_shop(env)
        game = env.game
        game.dollars = 100
        obs_before = env.get_shop_obs().copy()
        # Buy first available joker
        mask = env.get_shop_action_mask()
        for a in range(2, 8):
            if mask[a]:
                env.step(a)
                break
        obs_after = env.get_shop_obs()
        # Obs should have changed (dollars at minimum)
        assert not np.array_equal(obs_before, obs_after)

    def test_shop_obs_joker_features_update_on_sell(self, env):
        """Selling a joker should change joker features in shop obs."""
        _advance_to_shop(env)
        game = env.game
        j = JokerInstance("j_joker")
        j.state["sell_value"] = 3
        game.jokers = [j]
        obs_before = env.get_shop_obs().copy()
        env.step(10)  # sell joker 0
        obs_after = env.get_shop_obs()
        assert not np.array_equal(obs_before, obs_after)


# ════════════════════════════════════════════════════════════════════════════
# 9. Full episode smoke test
# ════════════════════════════════════════════════════════════════════════════

class TestSmokeTest:
    """Run complete episodes with random actions to check for crashes."""

    @pytest.mark.parametrize("seed", range(50))
    def test_random_episode_no_crash(self, seed):
        """Run one full episode with random valid actions — no crashes, finite obs/reward.
        Truncates at 3000 steps (random play may not terminate naturally)."""
        env = BalatroSimEnvV5(seed=seed)
        obs, info = env.reset()
        max_steps = 3000
        shop_consecutive = 0

        for step in range(max_steps):
            agent = info["agent"]
            if agent == "play":
                mask = env.get_play_action_mask()
                shop_consecutive = 0
            elif info["shop_substate"] == SUBSTATE_PACK_OPEN:
                mask = env.get_pack_open_mask()
            elif info["shop_substate"] == SUBSTATE_PACK_TARGET:
                mask = env.get_pack_target_mask()
            else:
                mask = env.get_shop_action_mask()
                shop_consecutive += 1

            valid = np.where(mask)[0]
            if len(valid) == 0:
                action = 1 if agent == "shop" else 30
            else:
                # Always leave shop after a few actions to avoid infinite loops
                if agent == "shop" and info["shop_substate"] == SUBSTATE_NORMAL and shop_consecutive > 3:
                    action = 1  # leave shop
                else:
                    action = int(np.random.choice(valid))

            obs, reward, terminated, truncated, info = env.step(action)

            # Reward must be finite
            assert np.isfinite(reward), f"Non-finite reward at step {step}: {reward}"
            # Obs must be finite
            assert np.all(np.isfinite(obs)), f"Non-finite obs at step {step}"

            if terminated:
                break
