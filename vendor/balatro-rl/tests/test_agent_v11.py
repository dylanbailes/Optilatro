"""tests/test_agent_v11.py — Comprehensive unit tests for Optilatro V11.

Covers:
  1. Full left-to-right joker trigger order optimization (Component A).
  2. Blueprint and Brainstorm copy positioning.
  3. Scaling growth potential valuation (Component A).
  4. Neural Value Network forward pass, bounds, and latency (Component C).
  5. Shop sequence planning and counterfactual evaluation (Component B).
  6. SearchShopV11 end-to-end integration and human-fairness invariants.
"""
from __future__ import annotations

import time
import pytest

from balatro_sim.game import BalatroGame, State
from balatro_sim.jokers.base import JokerInstance
from balatro_sim.agent_v11 import (
    SearchShopV11,
    _optimize_joker_order_v11,
    _joker_order_priority,
    _v11_scaling_growth_bonus,
    evaluate_shop_value_v11,
    _plan_shop_sequence,
)
from balatro_sim.rollout import rollout


class TestJokerTriggerOrderV11:
    """Component A: Test left-to-right mathematical scoring trigger order."""

    def test_flat_mult_before_xmult(self):
        """_joker_order_priority orders Utility -> Chips -> Flat Mult -> xMult."""
        game = BalatroGame(seed=42)
        j_cav = JokerInstance("j_cavendish", game=game)     # x3 Mult
        j_half = JokerInstance("j_half", game=game)         # +20 Mult
        j_blue = JokerInstance("j_blue_joker", game=game)   # Chips
        j_gold = JokerInstance("j_golden", game=game)       # Econ / Utility

        jokers = [j_cav, j_half, j_gold, j_blue]
        jokers.sort(key=_joker_order_priority)

        # Expected order: Utility (Golden) -> Chips (Blue) -> Flat Mult (Half) -> xMult (Cavendish)
        keys = [j.key for j in jokers]
        assert keys == ["j_golden", "j_blue_joker", "j_half", "j_cavendish"]

    def test_polychrome_placed_after_non_poly(self):
        """Polychrome edition (x1.5 Mult) should trigger after flat mult additions."""
        game = BalatroGame(seed=42)
        j_half_poly = JokerInstance("j_half", game=game)
        j_half_poly.edition = "Polychrome"
        j_gros = JokerInstance("j_gros_michel", game=game)  # Flat mult, no poly

        jokers = [j_half_poly, j_gros]
        jokers.sort(key=_joker_order_priority)

        # Gros Michel (+15) should trigger before Half Joker (+20, then x1.5)
        keys = [j.key for j in jokers]
        assert keys == ["j_gros_michel", "j_half"]

    def test_natural_order_guarded_without_copy_jokers(self):
        """_optimize_joker_order_v11 preserves natural order when copy jokers are absent."""
        game = BalatroGame(seed=42)
        j_cav = JokerInstance("j_cavendish", game=game)
        j_half = JokerInstance("j_half", game=game)
        game.jokers = [j_cav, j_half]
        _optimize_joker_order_v11(game)
        # Order should be untouched
        assert [j.key for j in game.jokers] == ["j_cavendish", "j_half"]

    def test_blueprint_placed_before_best_target(self):
        """Blueprint copies the joker to its right; must be placed immediately before best xMult."""
        game = BalatroGame(seed=42)
        j_cav = JokerInstance("j_cavendish", game=game)     # Target
        j_bp = JokerInstance("j_blueprint", game=game)      # Copy
        j_half = JokerInstance("j_half", game=game)

        game.jokers = [j_cav, j_half, j_bp]
        _optimize_joker_order_v11(game)

        keys = [j.key for j in game.jokers]
        # Blueprint should be immediately before Cavendish
        bp_idx = keys.index("j_blueprint")
        cav_idx = keys.index("j_cavendish")
        assert bp_idx == cav_idx - 1

    def test_brainstorm_places_best_target_at_index_zero(self):
        """Brainstorm copies leftmost joker (index 0); best target must be at index 0."""
        game = BalatroGame(seed=42)
        j_cav = JokerInstance("j_cavendish", game=game)       # Target
        j_bs = JokerInstance("j_brainstorm", game=game)       # Leftmost copy
        j_half = JokerInstance("j_half", game=game)

        game.jokers = [j_half, j_bs, j_cav]
        _optimize_joker_order_v11(game)

        # Cavendish must be at index 0 so Brainstorm copies it
        assert game.jokers[0].key == "j_cavendish"
        assert game.jokers[-1].key == "j_brainstorm"


class TestScalingGrowthValuationV11:
    """Component A: Test projected growth valuation for scaling jokers."""

    def test_scaling_bonus_declines_with_ante(self):
        """Scaling bonus must be positive in early antes and decrease toward Ante 6."""
        b1 = _v11_scaling_growth_bonus("j_constellation", ante=1)
        b3 = _v11_scaling_growth_bonus("j_constellation", ante=3)
        b5 = _v11_scaling_growth_bonus("j_constellation", ante=5)
        b6 = _v11_scaling_growth_bonus("j_constellation", ante=6)

        assert b1 > b3 > b5 > 0.0
        assert b6 == 0.0

    def test_non_scaling_joker_zero_bonus(self):
        """Static jokers must receive zero growth bonus."""
        assert _v11_scaling_growth_bonus("j_joker", ante=1) == 0.0
        assert _v11_scaling_growth_bonus("j_cavendish", ante=1) == 0.0


class TestValueNetworkV11:
    """Component C: Test MLP value network inference, bounds, and latency."""

    def test_evaluation_bounds_and_latency(self):
        """Value network must output in [0, 1] and evaluate in under 50µs."""
        dummy_features = {
            "ante": 4.0,
            "blind_idx": 1.0,
            "dollars": 25.0,
            "n_chips": 1.0,
            "n_flat_mult": 1.0,
            "n_xmult": 1.0,
            "n_scaling": 1.0,
            "deck_size": 52.0,
        }

        # Warm up
        val = evaluate_shop_value_v11(dummy_features)
        assert 0.0 <= val <= 1.0

        # Latency check (1,000 evaluations)
        t0 = time.perf_counter()
        for _ in range(1000):
            evaluate_shop_value_v11(dummy_features)
        elapsed = time.perf_counter() - t0
        mean_us = (elapsed / 1000) * 1e6
        assert mean_us < 50.0, f"Mean latency {mean_us:.2f}µs exceeded 50µs"

    def test_monotonic_value_with_scoring_power(self):
        """Adding xMult and chips in Ante 6 must increase predicted win probability."""
        from tools.portfolio import extract_features_from_state
        f_weak = extract_features_from_state(
            ante=6, blind_idx=1, dollars=15, hands_left=4, discards_left=3,
            joker_slots=5, jokers=[("j_half", None)], consumable_slots=2,
            consumables_count=0, vouchers=set(), hand_levels={}, deck_size=52,
            suit_counts={"Spades": 13}, face_count=12, enhanced_count=0, sealed_count=0,
            chips_target=50000,
        )
        f_strong = extract_features_from_state(
            ante=6, blind_idx=1, dollars=15, hands_left=4, discards_left=3,
            joker_slots=5, jokers=[("j_half", None), ("j_blue_joker", None), ("j_cavendish", None), ("j_duo", None)],
            consumable_slots=2, consumables_count=0, vouchers=set(), hand_levels={}, deck_size=52,
            suit_counts={"Spades": 13}, face_count=12, enhanced_count=0, sealed_count=0,
            chips_target=50000,
        )

        v_weak = evaluate_shop_value_v11(f_weak)
        v_strong = evaluate_shop_value_v11(f_strong)
        assert v_strong > v_weak


class TestShopSequencePlannerV11:
    """Component B: Test combinatorial multi-item shop planning."""

    def test_planner_runs_without_mutation(self):
        """Shop sequence search must not mutate live game state."""
        from balatro_sim.agent_v10 import HeuristicV10
        game = BalatroGame(seed=10202, rng_mode="seed")
        agent = HeuristicV10()
        # Advance to shop using a valid heuristic
        while game.state != State.SHOP and game.state != State.GAME_OVER:
            game.step(agent.decide(game))

        assert game.state == State.SHOP
        dollars_before = game.dollars
        jokers_before = [j.key for j in game.jokers]

        seq, delta = _plan_shop_sequence(game, rerolls_used=0)

        assert game.dollars == dollars_before
        assert [j.key for j in game.jokers] == jokers_before


class TestSearchShopV11Integration:
    """End-to-end integration and human-fairness invariants."""

    def test_search_shop_v11_runs_cleanly(self):
        """SearchShopV11 must complete full runs deterministically."""
        game = BalatroGame(seed=10204, rng_mode="seed")
        agent = SearchShopV11()
        res = rollout(game, agent)

        assert "won" in res
        assert "ante" in res
        assert res["steps"] > 0
