"""Tests for balatro_sim.env_v7 — V7 environment with hierarchical actions."""
import numpy as np
import pytest

from balatro_sim.env_v7 import (
    BalatroV7Env, OBS_DIM, N_PHASE_ACTIONS, N_INTENTS,
    CARD_FEATURES, N_HAND_SLOTS,
    PHASE_SELECTING_HAND, PHASE_BLIND_SELECT, PHASE_SHOP, PHASE_GAME_OVER,
)
from balatro_sim.card_selection import INTENT_PLAY, INTENT_DISCARD, INTENT_USE_CONSUMABLE
from balatro_sim.game import State


# ════════════════════════════════════════════════════════════════════════════
# Observation
# ════════════════════════════════════════════════════════════════════════════

class TestObservation:
    def test_obs_shape(self):
        env = BalatroV7Env(seed=42)
        obs, _ = env.reset()
        assert obs.shape == (OBS_DIM,), f"Expected {OBS_DIM}, got {obs.shape}"

    def test_obs_dim(self):
        assert OBS_DIM == 481   # 476 + 5 (vouchers 27 -> 32)

    def test_card_features_is_30(self):
        assert CARD_FEATURES == 30

    def test_obs_values_in_range(self):
        env = BalatroV7Env(seed=42)
        obs, _ = env.reset()
        assert obs.min() >= -1.0
        assert obs.max() <= 10.0

    def test_new_card_features_populated(self):
        """The 4 new per-card features should be non-zero for present cards."""
        env = BalatroV7Env(seed=42)
        obs, _ = env.reset()
        # Advance to SELECTING_HAND
        if env.get_phase() == PHASE_BLIND_SELECT:
            env.step_phase(0)  # play_blind

        obs = env._encode_obs()
        # Card block starts at idx 14, each card is 30 features
        # New features are at offsets 26-29 within each card
        for slot in range(min(len(env.game.hand), N_HAND_SLOTS)):
            base = 14 + slot * CARD_FEATURES
            suit_match = obs[base + 26]
            rank_match = obs[base + 27]
            straight_conn = obs[base + 28]
            chip_value = obs[base + 29]
            # chip_value should always be positive for present cards
            assert chip_value > 0, f"Card {slot} chip_value should be > 0"
            # At least some cards should have suit matches in a hand of 8
            # (can't assert individual cards, but the feature should be set)
            assert suit_match >= 0
            assert rank_match >= 0
            assert straight_conn >= 0

    def test_present_flag_at_offset_25(self):
        """Present flag should be 1.0 for filled slots, 0.0 for empty."""
        env = BalatroV7Env(seed=42)
        obs, _ = env.reset()
        if env.get_phase() == PHASE_BLIND_SELECT:
            env.step_phase(0)
        obs = env._encode_obs()
        n_cards = len(env.game.hand)
        for slot in range(N_HAND_SLOTS):
            base = 14 + slot * CARD_FEATURES
            if slot < n_cards:
                assert obs[base + 25] == 1.0
            else:
                assert obs[base + 25] == 0.0


# ════════════════════════════════════════════════════════════════════════════
# Phase detection
# ════════════════════════════════════════════════════════════════════════════

class TestPhase:
    def test_initial_phase(self):
        env = BalatroV7Env(seed=42)
        env.reset()
        phase = env.get_phase()
        assert phase in (PHASE_BLIND_SELECT, PHASE_SELECTING_HAND)

    def test_blind_select_to_selecting_hand(self):
        env = BalatroV7Env(seed=42)
        env.reset()
        if env.get_phase() == PHASE_BLIND_SELECT:
            env.step_phase(0)  # play_blind
            assert env.get_phase() == PHASE_SELECTING_HAND


# ════════════════════════════════════════════════════════════════════════════
# Intent masking
# ════════════════════════════════════════════════════════════════════════════

class TestIntentMask:
    def test_play_always_available_in_hand_phase(self):
        env = BalatroV7Env(seed=42)
        env.reset()
        if env.get_phase() == PHASE_BLIND_SELECT:
            env.step_phase(0)
        mask = env.get_intent_mask()
        assert mask[INTENT_PLAY]

    def test_discard_available_with_discards(self):
        env = BalatroV7Env(seed=42)
        env.reset()
        if env.get_phase() == PHASE_BLIND_SELECT:
            env.step_phase(0)
        if env.game.discards_left > 0 and len(env.game.hand) > 1:
            mask = env.get_intent_mask()
            assert mask[INTENT_DISCARD]

    def test_intent_mask_wrong_phase(self):
        env = BalatroV7Env(seed=42)
        env.reset()
        if env.get_phase() == PHASE_BLIND_SELECT:
            mask = env.get_intent_mask()
            assert not mask.any()  # no intents in blind_select


# ════════════════════════════════════════════════════════════════════════════
# Phase masking
# ════════════════════════════════════════════════════════════════════════════

class TestPhaseMask:
    def test_blind_select_mask(self):
        env = BalatroV7Env(seed=42)
        env.reset()
        if env.get_phase() == PHASE_BLIND_SELECT:
            mask = env.get_phase_mask()
            assert mask[0]  # play_blind
            # skip may or may not be valid depending on blind type


# ════════════════════════════════════════════════════════════════════════════
# Step actions
# ════════════════════════════════════════════════════════════════════════════

class TestStepHand:
    def test_play_single_card(self):
        env = BalatroV7Env(seed=42)
        env.reset()
        if env.get_phase() == PHASE_BLIND_SELECT:
            env.step_phase(0)
        obs, reward, term, trunc, info = env.step_hand(INTENT_PLAY, (0,))
        assert obs.shape == (OBS_DIM,)
        assert isinstance(reward, float)

    def test_play_five_cards(self):
        env = BalatroV7Env(seed=42)
        env.reset()
        if env.get_phase() == PHASE_BLIND_SELECT:
            env.step_phase(0)
        obs, reward, term, trunc, info = env.step_hand(INTENT_PLAY, (0, 1, 2, 3, 4))
        assert obs.shape == (OBS_DIM,)

    def test_discard(self):
        env = BalatroV7Env(seed=42)
        env.reset()
        if env.get_phase() == PHASE_BLIND_SELECT:
            env.step_phase(0)
        hand_before = len(env.game.hand)
        discards_before = env.game.discards_left
        if discards_before > 0:
            obs, reward, term, trunc, info = env.step_hand(INTENT_DISCARD, (0, 1))
            # Hand should still be full (redrawn)
            assert len(env.game.hand) == hand_before
            assert env.game.discards_left == discards_before - 1

    def test_wrong_phase_noop(self):
        """step_hand in BLIND_SELECT should be a no-op."""
        env = BalatroV7Env(seed=42)
        env.reset()
        if env.get_phase() == PHASE_BLIND_SELECT:
            obs, reward, term, trunc, info = env.step_hand(INTENT_PLAY, (0,))
            assert env.get_phase() == PHASE_BLIND_SELECT  # didn't change


# ════════════════════════════════════════════════════════════════════════════
# Random rollout smoke test
# ════════════════════════════════════════════════════════════════════════════

class TestRandomRollout:
    def test_10k_random_steps(self):
        """Run 10k steps with random actions. Should not crash."""
        import random
        rng = random.Random(42)
        env = BalatroV7Env(seed=42)
        env.reset()

        episodes = 0
        for _ in range(10_000):
            phase = env.get_phase()

            if phase == PHASE_SELECTING_HAND:
                intent_mask = env.get_intent_mask()
                valid_intents = [i for i in range(N_INTENTS) if intent_mask[i]]
                if not valid_intents:
                    intent = INTENT_PLAY
                else:
                    intent = rng.choice(valid_intents)

                n_cards = len(env.game.hand)
                if n_cards > 0:
                    k = rng.randint(1, min(5, n_cards))
                    subset = tuple(rng.sample(range(n_cards), k))
                else:
                    subset = (0,)

                obs, reward, term, trunc, info = env.step_hand(intent, subset)
            else:
                phase_mask = env.get_phase_mask()
                valid_actions = [i for i in range(N_PHASE_ACTIONS) if phase_mask[i]]
                if not valid_actions:
                    action = 15  # leave_shop fallback
                else:
                    action = rng.choice(valid_actions)
                obs, reward, term, trunc, info = env.step_phase(action)

            assert obs.shape == (OBS_DIM,)

            if term or trunc:
                env._seed = rng.randint(0, 2**31 - 1)
                obs, _ = env.reset()
                episodes += 1

        assert episodes > 0, "Should complete at least one episode in 10k steps"
