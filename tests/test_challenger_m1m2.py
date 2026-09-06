"""tests/test_challenger_m1m2.py — Empirical Challenger Test Suite for M1 & M2.

Stress-tests:
1. Farm-off exactness invariant (HeuristicV10 farm_clear_threshold >= 1.0 vs HeuristicV9).
2. Pace rule boundary conditions (target=0, large target, hands=0, hands=1, discards=0, exact threshold boundaries).
3. CI seed exactness stability & determinism across 20+ varied seeds.
4. Portfolio classification & feature extractor adversarial inputs (150 jokers, aliases, extreme game states, zero mutation).
"""
import copy
import math
import sys
import pytest

# Ensure vendor/balatro-rl and tools are in sys.path
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "vendor", "balatro-rl")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from balatro_sim.card import Card
from balatro_sim.game import BalatroGame, State
from balatro_sim.agent_v9 import HeuristicV9
import balatro_sim.agent_v10 as v10
from balatro_sim.rollout import rollout
from balatro_sim.shop import JOKER_CATALOGUE
from balatro_sim.jokers import _CANONICAL_JOKER_ALIASES

from tools.portfolio import (
    classify_joker,
    extract_features_from_state,
    extract_game_features,
    CHIPS_JOKERS,
    FLAT_MULT_JOKERS,
    XMULT_JOKERS,
    SCALING_JOKERS,
    ECON_JOKERS,
    RETRIGGER_JOKERS,
    ALIAS_TO_CANONICAL,
    normalize_joker_key,
)


def _std_deck():
    """A standard 52-card deck (deterministic suit/rank order)."""
    cards = []
    for suit in ("Spades", "Hearts", "Clubs", "Diamonds"):
        for rank in range(2, 15):
            cards.append(Card(rank, suit))
    return cards


def _game(hand=None, deck=None, jokers=()):
    """A fresh seed-mode game in SELECTING_HAND with a controlled hand/deck."""
    g = BalatroGame(seed=7, rng_mode="seed")
    g.reset()
    if g.state != State.SELECTING_HAND:
        g.state = State.BLIND_SELECT
        g.step({"type": "play_blind"})
    if hand is not None:
        g.hand = list(hand)
    g.deck = list(deck) if deck is not None else _std_deck()
    from balatro_sim.jokers.base import JokerInstance
    g.jokers = [JokerInstance(k, game=g) if isinstance(k, str) else k
                for k in jokers]
    g.current_blind.chips_target = 600
    g.chips_scored = 0
    g.hands_left = 4
    g.discards_left = 3
    return g


class TestFarmOffExactnessChallenger:
    """Adversarial stress-testing of the Farm-Off Exactness Invariant."""

    @pytest.mark.parametrize("seed", list(range(20)))
    def test_step_by_step_exactness_v9_vs_v10_farm_off_20_seeds(self, seed):
        """Step-by-step exact decision match between V9 and V10 (farm_clear_threshold=1.0)."""
        g9 = BalatroGame(seed=seed, rng_mode="seed")
        g10 = BalatroGame(seed=seed, rng_mode="seed")

        pol9 = HeuristicV9()
        # V10 with farm_clear_threshold=1.0 (default ante1_pace_rule is True in DEFAULTS,
        # but the code guards it with farm_clear_threshold < 1.0).
        pol10 = v10.HeuristicV10(params={"farm_clear_threshold": 1.0})

        max_steps = 200
        steps = 0
        while g9.state != State.GAME_OVER and g10.state != State.GAME_OVER and steps < max_steps:
            assert g9.state == g10.state, f"Seed {seed} step {steps}: state mismatch {g9.state} vs {g10.state}"
            assert g9.ante == g10.ante, f"Seed {seed} step {steps}: ante mismatch {g9.ante} vs {g10.ante}"
            assert g9.chips_scored == g10.chips_scored, f"Seed {seed} step {steps}: chips mismatch {g9.chips_scored} vs {g10.chips_scored}"
            assert g9.dollars == g10.dollars, f"Seed {seed} step {steps}: dollars mismatch {g9.dollars} vs {g10.dollars}"

            act9 = pol9.decide(g9)
            act10 = pol10.decide(g10)

            assert act9 == act10, f"Seed {seed} step {steps} at {g9.state}: action mismatch V9={act9} vs V10={act10}"

            g9.step(act9)
            g10.step(act10)
            steps += 1

        assert g9.state == g10.state, f"Final state mismatch seed {seed}"
        assert g9.ante == g10.ante, f"Final ante mismatch seed {seed}"
        assert g9.chips_scored == g10.chips_scored, f"Final chips mismatch seed {seed}"

    def test_farm_clear_threshold_above_one(self):
        """farm_clear_threshold=1.5 or 2.0 also reproduces V9 identically."""
        for threshold in (1.0, 1.5, 2.0):
            g9 = BalatroGame(seed=42, rng_mode="seed")
            g10 = BalatroGame(seed=42, rng_mode="seed")
            pol9 = HeuristicV9()
            pol10 = v10.HeuristicV10(params={"farm_clear_threshold": threshold})
            r9 = rollout(g9, pol9)
            r10 = rollout(g10, pol10)
            for k in ("won", "ante", "steps", "dollars", "jokers"):
                assert r9[k] == r10[k], f"Mismatch for threshold {threshold} on {k}"


class TestPaceRuleBoundaryConditionsChallenger:
    """Adversarial stress-testing of Ante-1 Pace Rule edge cases and boundaries."""

    def test_exact_threshold_boundary_ante1(self):
        """Verify step behavior right below, exactly at, and right above pace threshold."""
        # Ante 1 Small Blind: Target = 300, Hands = 4, Pace = 75.0
        g = _game([Card(10, "Hearts"), Card(10, "Spades"), Card(4, "Clubs"), Card(2, "Diamonds")], deck=_std_deck())
        g.ante = 1
        g.current_blind.chips_target = 300
        g.chips_scored = 0
        g.hands_left = 4
        g.discards_left = 3

        v10.V10_PARAMS["farm_clear_threshold"] = 0.90
        v10.V10_PARAMS["ante1_pace_rule"] = True
        v10.V10_PARAMS["ante1_pace_mult"] = 1.0

        combo_pair = (0, 1)

        # Case A: 40 chips (< 75.0 pace). Must NOT trigger pace rule -> discards.
        plays_40 = [(40, combo_pair, "Pair")]
        act_40 = v10._tier1_survive(g, plays_40)
        assert act_40["type"] == "discard", f"Expected discard for 40 chips on 75 pace, got {act_40}"

        # Case B: 75 chips (== 75.0 pace). Pace rule MUST trigger -> plays immediately.
        plays_75 = [(75, combo_pair, "Pair")]
        act_75 = v10._tier1_survive(g, plays_75)
        assert act_75["type"] == "play", f"Expected immediate play for 75 chips on 75 pace, got {act_75}"
        assert act_75["cards"] == list(combo_pair)

        # Case C: 76 chips (> 75.0 pace). Pace rule MUST trigger -> plays immediately.
        plays_76 = [(76, combo_pair, "Pair")]
        act_76 = v10._tier1_survive(g, plays_76)
        assert act_76["type"] == "play", f"Expected immediate play for 76 chips on 75 pace, got {act_76}"
        assert act_76["cards"] == list(combo_pair)

    def test_boundary_hands_left_zero_and_one(self):
        """Boundary when hands_left = 0 or 1."""
        g = _game([Card(10, "Hearts"), Card(10, "Spades"), Card(4, "Clubs"), Card(2, "Diamonds")], deck=_std_deck())
        g.ante = 1
        g.current_blind.chips_target = 300
        g.chips_scored = 0

        # hands_left = 1: pace = target / 1 = 300.
        g.hands_left = 1
        combo = (0, 1)
        plays_100 = [(100, combo, "Two Pair")]
        act = v10._tier1_survive(g, plays_100)
        assert act["type"] == "play"

        # hands_left = 0 (guard against division by zero: max(1, 0) == 1)
        g.hands_left = 0
        act_0 = v10._tier1_survive(g, plays_100)
        assert act_0["type"] == "play"

    def test_boundary_target_zero_and_large(self):
        """Boundary when remaining target is 0, negative, or massive."""
        g = _game([Card(10, "Hearts"), Card(8, "Spades"), Card(4, "Clubs"), Card(2, "Diamonds")], deck=_std_deck())
        g.ante = 1
        combo = (0,)

        # Target = 0 (chips_scored >= target)
        g.current_blind.chips_target = 300
        g.chips_scored = 300
        plays = [(50, combo, "High Card")]
        act_cleared = v10._tier1_survive(g, plays)
        # Should clear immediately
        assert act_cleared["type"] == "play"

        # Target massive (100,000,000)
        g.chips_scored = 0
        g.current_blind.chips_target = 100_000_000
        g.hands_left = 4
        g.discards_left = 3
        plays_40 = [(40, combo, "High Card")]
        # Pace = 25,000,000. 40 < pace -> should discard to seek upgrades
        act_huge = v10._tier1_survive(g, plays_40)
        assert act_huge["type"] == "discard"

    def test_boundary_discards_left_zero(self):
        """When discards_left is 0 and hand is below pace, must play rather than discard."""
        g = _game([Card(10, "Hearts"), Card(8, "Spades"), Card(4, "Clubs"), Card(2, "Diamonds")], deck=_std_deck())
        g.ante = 1
        g.current_blind.chips_target = 300
        g.chips_scored = 0
        g.hands_left = 4
        g.discards_left = 0
        combo = (0,)
        plays_50 = [(50, combo, "High Card")]  # below 75 pace
        act = v10._tier1_survive(g, plays_50)
        assert act["type"] == "play"
        assert act["cards"] == list(combo)

    def test_ante_scope_gate(self):
        """Pace rule must ONLY fire at ante 1, never at ante 2+."""
        # Standard 8-card hand:
        hand = [
            Card(10, "Hearts"), Card(10, "Spades"), Card(9, "Clubs"), Card(8, "Diamonds"),
            Card(7, "Clubs"), Card(4, "Diamonds"), Card(3, "Hearts"), Card(2, "Spades")
        ]
        g = _game(hand, deck=_std_deck())
        g.ante = 2
        g.current_blind.chips_target = 600
        g.chips_scored = 0
        g.hands_left = 4  # pace would be 150 if ante 1
        g.discards_left = 3

        v10.V10_PARAMS["farm_clear_threshold"] = 0.90
        v10.V10_PARAMS["ante1_pace_rule"] = True
        v10.V10_PARAMS["ante1_pace_mult"] = 1.0

        combo = (0, 1)
        # Pair of 10s scores ~40 chips in base deck.
        # At Ante 1 (pace 75), 80 chips would play under pace rule.
        # At Ante 2 (target 600, pace rule disabled):
        # 40 chips < 600 * 0.50 (good_hand=300). Pace rule must NOT fire, so it discards.
        plays_40 = [(40, combo, "Pair")]
        act = v10._tier1_survive(g, plays_40)
        assert act["type"] == "discard", f"Pace rule leaked to Ante 2! Got {act}"

    def test_fatal_seeds_205_275_step_by_step_trace(self):
        """Trace fatal seeds 205 and 275 to confirm pace rule clears Ante 1."""
        for seed in (205, 275):
            game = BalatroGame(seed=seed, rng_mode="seed")
            agent = v10.HeuristicV10()
            for _ in range(100):
                if game.state == State.GAME_OVER or game.ante > 1:
                    break
                game.step(agent.decide(game))
            assert game.ante > 1, f"Seed {seed} failed to clear Ante 1 (state: {game.state})"


class TestPortfolioAdversarialChallenger:
    """Adversarial stress-testing of Portfolio classification and feature extraction."""

    def test_all_150_canonical_jokers_classified(self):
        """All 150 catalogue jokers must have valid, non-throwing role classifications."""
        assert len(JOKER_CATALOGUE) == 150
        for key in JOKER_CATALOGUE:
            roles = classify_joker(key)
            assert isinstance(roles, dict)
            assert len(roles) == 6
            for rk, rv in roles.items():
                assert isinstance(rv, bool)

    def test_all_canonical_aliases_classified_identically(self):
        """All aliases must match their canonical spec key classifications."""
        for alias, canonical in _CANONICAL_JOKER_ALIASES.items():
            roles_alias = classify_joker(alias)
            roles_canonical = classify_joker(canonical)
            assert roles_alias == roles_canonical, f"Alias {alias} != Canonical {canonical}"

    def test_unknown_and_malformed_keys(self):
        """Unknown or malformed joker keys must return all False safely without error."""
        for key in ("j_unknown_fake", "", "xyz"):
            roles = classify_joker(key)
            assert all(not v for v in roles.values())

    def test_feature_extractor_adversarial_states(self):
        """Feature extraction must return 42 valid, finite float features under extreme states."""
        feats = extract_features_from_state(
            ante=16,
            blind_idx=2,
            dollars=-20,
            hands_left=0,
            discards_left=0,
            joker_slots=0,
            jokers=[],
            consumable_slots=0,
            consumables_count=0,
            vouchers=["v_unknown_voucher", "v_telescope"],
            hand_levels={"High Card": 999},
            deck_size=0,
            suit_counts={},
            face_count=0,
            enhanced_count=0,
            sealed_count=0,
            chips_target=100_000_000,
        )
        assert len(feats) == 42
        for k, v in feats.items():
            assert isinstance(v, float), f"Key {k} is not float: {type(v)}"
            assert math.isfinite(v), f"Key {k} is not finite: {v}"
            assert not math.isnan(v), f"Key {k} is NaN: {v}"

        assert feats["interest_units"] == 0.0
        assert feats["free_joker_slots"] == 0.0
        assert feats["suit_conc"] == 0.0
        assert feats["zero_xmult_late"] == 1.0
        assert feats["has_telescope"] == 1.0

    def test_feature_extractor_zero_game_mutation(self):
        """extract_game_features must not mutate any game attribute or consume RNG."""
        g = BalatroGame(seed=777, rng_mode="seed")
        # Advance to blind
        g.step({"type": "play_blind"})

        deck_before = [(c.suit, c.rank, c.enhancement, c.seal) for c in g.deck]
        hand_before = [(c.suit, c.rank, c.enhancement, c.seal) for c in g.hand]
        dollars_before = g.dollars
        ante_before = g.ante
        hands_before = g.hands_left
        discards_before = g.discards_left

        # Extract features 50 times
        for _ in range(50):
            feats = extract_game_features(g)
            assert len(feats) == 42

        deck_after = [(c.suit, c.rank, c.enhancement, c.seal) for c in g.deck]
        hand_after = [(c.suit, c.rank, c.enhancement, c.seal) for c in g.hand]
        assert deck_before == deck_after
        assert hand_before == hand_after
        assert g.dollars == dollars_before
        assert g.ante == ante_before
        assert g.hands_left == hands_before
        assert g.discards_left == discards_before


class TestCISeedExactnessChallenger:
    """Adversarial stress-testing of CI seed exactness and isolated RNG."""

    @pytest.mark.parametrize("seed", [10, 42, 99, 123, 205, 275, 500, 999])
    def test_multi_seed_repeatability(self, seed):
        """Two separate game instances with same seed and HeuristicV10 produce 100% bitwise identical rollouts."""
        g1 = BalatroGame(seed=seed, rng_mode="seed")
        g2 = BalatroGame(seed=seed, rng_mode="seed")
        pol1 = v10.HeuristicV10()
        pol2 = v10.HeuristicV10()

        r1 = rollout(g1, pol1)
        r2 = rollout(g2, pol2)

        assert r1["won"] == r2["won"]
        assert r1["ante"] == r2["ante"]
        assert r1["steps"] == r2["steps"]
        assert r1["dollars"] == r2["dollars"]
        assert r1["jokers"] == r2["jokers"]
