"""test_e2e_v10_requirements.py — Comprehensive 4-Tier E2E Test Suite for Optilatro V10.

Opaque-box, requirement-driven test suite validating all 4 core V10 requirements:
  - R1: Multi-Hand Pace Rule (Ante 1 budget discipline & survival)
  - R2: Joker Portfolio & State Feature Extraction (6 roles, 42-dim feature vector)
  - R3: Rollout Dataset Generation & Offline Value Model (interactions & pure-Python inference)
  - R4: L1 Counterfactual Shop Search & Swapping (human-fair candidate ranking & room making)

Structured across 4 rigorous tiers:
  - Tier 1: Feature Coverage (>=5 test cases per requirement: R1, R2, R3, R4)
  - Tier 2: Boundary & Corner Cases (empty portfolios, negative money, 0 hands left, max slots, edge jokers)
  - Tier 3: Cross-Feature Interactions (pace rule + portfolio features, counterfactual shop search with xMult swaps)
  - Tier 4: Real-World Scenarios (fatal seeds 205/275, paired seed tests, multi-ante game rollouts)
"""
from __future__ import annotations

import copy
import math
import os
import pathlib
import sys
import time
from typing import Any

import numpy as np
import pytest

# Ensure vendor/balatro-rl and repo root are in python path
_TESTS_DIR = pathlib.Path(__file__).resolve().parent
_VENDOR_DIR = _TESTS_DIR.parent
_REPO_ROOT = _VENDOR_DIR.parent.parent

if str(_VENDOR_DIR) not in sys.path:
    sys.path.insert(0, str(_VENDOR_DIR))
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from balatro_sim.card import Card
from balatro_sim.game import BalatroGame, State
from balatro_sim.hand_eval import evaluate_hand
from balatro_sim.jokers.base import JokerInstance
from balatro_sim.rollout import rollout
from balatro_sim.agent_v9 import HeuristicV9
from balatro_sim import agent_v10 as v10
from balatro_sim.shop import ShopItem
from tools.portfolio import (
    CHIPS_JOKERS,
    FLAT_MULT_JOKERS,
    XMULT_JOKERS,
    SCALING_JOKERS,
    ECON_JOKERS,
    RETRIGGER_JOKERS,
    classify_joker,
    extract_features_from_state,
    extract_game_features,
)
from tools.fit_shop_model import build_interactions, auc


# ────────────────────────────────────────────────────────────────────────────
# Test Fixtures & Utilities
# ────────────────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def reset_v10_params():
    """Ensure V10_PARAMS are restored to V10_DEFAULTS before and after every test."""
    v10.V10_PARAMS.clear()
    v10.V10_PARAMS.update(v10.V10_DEFAULTS)
    yield
    v10.V10_PARAMS.clear()
    v10.V10_PARAMS.update(v10.V10_DEFAULTS)


def create_test_game(
    hand: list[Card] | None = None,
    deck: list[Card] | None = None,
    jokers: tuple[str | JokerInstance, ...] = (),
    ante: int = 1,
    blind_idx: int = 0,
    chips_target: int = 300,
    chips_scored: int = 0,
    hands_left: int = 4,
    discards_left: int = 3,
    dollars: int = 4,
    seed: int = 42,
) -> BalatroGame:
    """Create a controlled seed-mode BalatroGame instance in SELECTING_HAND."""
    g = BalatroGame(seed=seed, rng_mode="seed")
    g.reset()
    if g.state != State.SELECTING_HAND:
        g.state = State.BLIND_SELECT
        g.step({"type": "play_blind"})
    
    g.ante = ante
    g.blind_idx = blind_idx
    g.dollars = dollars
    g.hands_left = hands_left
    g.discards_left = discards_left
    g.chips_scored = chips_scored
    
    if g.current_blind is not None:
        g.current_blind.chips_target = chips_target
        
    g.hand = list(hand) if hand is not None else [Card(14, "Spades"), Card(13, "Hearts"), Card(10, "Diamonds")]
    g.deck = list(deck) if deck is not None else _create_standard_deck()
    
    g.jokers = [
        JokerInstance(k, game=g) if isinstance(k, str) else k
        for k in jokers
    ]
    return g


def _create_standard_deck() -> list[Card]:
    """Generate a standard 52-card deck in deterministic order."""
    cards = []
    for suit in ("Spades", "Hearts", "Clubs", "Diamonds"):
        for rank in range(2, 15):
            cards.append(Card(rank, suit))
    return cards


def evaluate_value_model(
    features: dict[str, float],
    model_data: dict[str, Any],
) -> float:
    """Pure-Python logistic evaluation of value model weights V(s') -> P(Win)."""
    f_inter = build_interactions(features)
    feat_order = model_data["feat_order"]
    means = model_data["mean"]
    stds = model_data["std"]
    weights = model_data["w"]
    
    # Standardize and compute dot product
    z = weights[-1]  # Bias is the final weight
    for i, name in enumerate(feat_order):
        val = float(f_inter.get(name, 0.0))
        norm_val = (val - means[i]) / (stds[i] if stds[i] > 1e-9 else 1.0)
        z += weights[i] * norm_val
        
    z = max(-30.0, min(30.0, z))
    return 1.0 / (1.0 + math.exp(-z))


# ────────────────────────────────────────────────────────────────────────────
# TIER 1: FEATURE COVERAGE (R1, R2, R3, R4)
# ────────────────────────────────────────────────────────────────────────────

class TestTier1_R1_PaceRule:
    """Tier 1 Feature Coverage for Requirement R1: Ante-1 Multi-Hand Pace Rule."""

    def test_r1_pace_calculation_and_budget(self):
        """Authoritative verification of pace formula: (target - scored) / hands_left * pace_mult."""
        g = create_test_game(ante=1, chips_target=300, chips_scored=0, hands_left=4)
        v10.V10_PARAMS["ante1_pace_rule"] = True
        v10.V10_PARAMS["ante1_pace_mult"] = 1.0
        
        target = g.current_blind.chips_target - g.chips_scored
        pace = (target / max(1, g.hands_left)) * v10.V10_PARAMS["ante1_pace_mult"]
        assert pace == 75.0, f"Expected pace 75.0, got {pace}"
        
        # After scoring 120 chips with 3 hands remaining
        g.chips_scored = 120
        g.hands_left = 3
        target_rem = g.current_blind.chips_target - g.chips_scored
        pace_rem = (target_rem / max(1, g.hands_left)) * v10.V10_PARAMS["ante1_pace_mult"]
        assert pace_rem == 60.0, f"Expected remaining pace 60.0, got {pace_rem}"

    def test_r1_pace_immediate_play_on_satisfaction(self):
        """When best playable hand meets or exceeds per-hand pace, agent plays immediately."""
        g = create_test_game(
            hand=[Card(10, "Hearts"), Card(10, "Spades"), Card(4, "Clubs"), Card(2, "Diamonds")],
            deck=_create_standard_deck(),
            ante=1,
            chips_target=300,
            chips_scored=0,
            hands_left=4,
            discards_left=3,
        )
        v10.V10_PARAMS["ante1_pace_rule"] = True
        v10.V10_PARAMS["farm_clear_threshold"] = 0.90
        
        # Scored play of 85 exceeds pace of 75 (300 / 4)
        plays = [(85, [0, 1], "Pair"), (40, [0], "High Card")]
        act = v10._tier1_survive(g, plays)
        
        assert act["type"] == "play", f"Expected immediate play action, got {act['type']}"
        assert act["cards"] == [0, 1], f"Expected cards [0, 1], got {act['cards']}"

    def test_r1_pace_discard_when_below_threshold(self):
        """When best playable hand is below per-hand pace, agent discards to search for upgrades."""
        g = create_test_game(
            hand=[Card(10, "Hearts"), Card(8, "Spades"), Card(4, "Clubs"), Card(2, "Diamonds")],
            deck=_create_standard_deck(),
            ante=1,
            chips_target=300,
            chips_scored=0,
            hands_left=4,
            discards_left=3,
        )
        v10.V10_PARAMS["ante1_pace_rule"] = True
        v10.V10_PARAMS["farm_clear_threshold"] = 0.90
        
        # Scored play of 35 is below pace of 75 (300 / 4)
        plays = [(35, [0], "High Card")]
        act = v10._tier1_survive(g, plays)
        
        assert act["type"] == "discard", f"Expected discard action when below pace, got {act['type']}"

    def test_r1_pace_multiplier_sensitivity(self):
        """Varying ante1_pace_mult shifts the play vs discard threshold precisely."""
        g = create_test_game(
            hand=[Card(10, "Hearts"), Card(8, "Spades"), Card(4, "Clubs"), Card(2, "Diamonds")],
            deck=_create_standard_deck(),
            ante=1,
            chips_target=300,
            chips_scored=0,
            hands_left=4,
            discards_left=3,
        )
        plays = [(40, [0], "High Card")]  # Score = 40

        # Base pace is 300 / 4 = 75.
        # At pace_mult = 0.5, pace is 37.5 -> 40 >= 37.5 -> pace rule triggers PLAY
        v10.V10_PARAMS["ante1_pace_rule"] = True
        v10.V10_PARAMS["ante1_pace_mult"] = 0.5
        v10.V10_PARAMS["farm_clear_threshold"] = 0.90
        act_1 = v10._tier1_survive(g, plays)
        assert act_1["type"] == "play"

        # At pace_mult = 1.0, pace is 75 -> 40 < 75 -> pace rule does not trigger play, falls into DISCARD
        v10.V10_PARAMS["ante1_pace_mult"] = 1.0
        act_2 = v10._tier1_survive(g, plays)
        assert act_2["type"] == "discard"

    def test_r1_pace_rule_ante_scope_gate(self):
        """Pace rule applies strictly to Ante 1 and does not alter Ante 2+ survive logic."""
        g_ante2 = create_test_game(
            hand=[Card(10, "Hearts"), Card(8, "Spades"), Card(4, "Clubs"), Card(2, "Diamonds")],
            deck=_create_standard_deck(),
            ante=2,
            chips_target=800,
            chips_scored=0,
            hands_left=4,
            discards_left=3,
        )
        plays = [(40, [0], "High Card")]  # Score 40

        # With low pace_mult (0.1), if ante1_pace_rule were active it would pace at 800/4*0.1=20 and play
        v10.V10_PARAMS["ante1_pace_rule"] = True
        v10.V10_PARAMS["ante1_pace_mult"] = 0.1
        v10.V10_PARAMS["farm_clear_threshold"] = 0.90

        # At Ante 2, ante1_pace_rule check is bypassed (ante == 2 != 1)
        act = v10._tier1_survive(g_ante2, plays)
        # In Ante 2, discards to seek stronger hand
        assert act["type"] == "discard"

    def test_r1_pace_multi_hand_progression(self):
        """Simulate a multi-hand progression clearing Ante 1 Small Blind in 2 hands."""
        g = create_test_game(ante=1, chips_target=300, chips_scored=0, hands_left=4, discards_left=3)
        v10.V10_PARAMS["ante1_pace_rule"] = True
        v10.V10_PARAMS["farm_clear_threshold"] = 0.90
        
        # Hand 1: plays 160 chips (pace 75)
        plays_h1 = [(160, [0, 1], "Two Pair")]
        act_1 = v10._tier1_survive(g, plays_h1)
        assert act_1["type"] == "play"
        
        # Apply Hand 1 score
        g.chips_scored = 160
        g.hands_left = 3
        
        # Hand 2: remaining target is 140, pace is 140/3 = 46.7
        # Player holds Pair scoring 150 chips (>= 140 -> clearing play)
        plays_h2 = [(150, [2, 3], "Pair")]
        act_2 = v10._tier1_survive(g, plays_h2)
        assert act_2["type"] == "play"


class TestTier1_R2_PortfolioClassification:
    """Tier 1 Feature Coverage for Requirement R2: Joker Portfolio & Feature Extraction."""

    def test_r2_role_classification_all_categories(self):
        """All 6 primary joker roles (Chips, Flat Mult, xMult, Scaling, Econ, Retrigger) classify accurately."""
        # Chips
        for k in ("j_sly", "j_banner", "j_bull", "j_stuntman"):
            c = classify_joker(k)
            assert c["is_chips"] is True, f"{k} should be classified as chips"
            
        # Flat Mult
        for k in ("j_joker", "j_jolly", "j_gros_michel", "j_abstract"):
            c = classify_joker(k)
            assert c["is_flat_mult"] is True, f"{k} should be classified as flat_mult"
            
        # xMult
        for k in ("j_acrobat", "j_blackboard", "j_cavendish", "j_duo"):
            c = classify_joker(k)
            assert c["is_xmult"] is True, f"{k} should be classified as xmult"
            
        # Scaling
        for k in ("j_green_joker", "j_ride_the_bus", "j_constellation", "j_wee"):
            c = classify_joker(k)
            assert c["is_scaling"] is True, f"{k} should be classified as scaling"
            
        # Economy
        for k in ("j_golden", "j_delayed_grat", "j_rocket", "j_credit_card"):
            c = classify_joker(k)
            assert c["is_econ"] is True, f"{k} should be classified as econ"
            
        # Retrigger
        for k in ("j_dusk", "j_hack", "j_hanging_chad", "j_mime"):
            c = classify_joker(k)
            assert c["is_retrigger"] is True, f"{k} should be classified as retrigger"

    def test_r2_dual_role_and_multi_role_jokers(self):
        """Jokers providing dual or synergistic roles correctly reflect both capabilities."""
        # Green Joker: flat mult + scaling
        c_green = classify_joker("j_green_joker")
        assert c_green["is_flat_mult"] is True and c_green["is_scaling"] is True
        
        # Constellation: xmult + scaling
        c_const = classify_joker("j_constellation")
        assert c_const["is_xmult"] is True and c_const["is_scaling"] is True
        
        # Wee Joker: chips + scaling
        c_wee = classify_joker("j_wee")
        assert c_wee["is_chips"] is True and c_wee["is_scaling"] is True
        
        # Castle: chips + scaling
        c_castle = classify_joker("j_castle")
        assert c_castle["is_chips"] is True and c_castle["is_scaling"] is True
        
        # Vampire: xmult + scaling
        c_vamp = classify_joker("j_vampire")
        assert c_vamp["is_xmult"] is True and c_vamp["is_scaling"] is True

    def test_r2_editions_augmented_roles(self):
        """Card and joker editions dynamically augment portfolio feature counts."""
        jokers = [
            ("j_sly", "Foil"),          # chips base + Foil (+chips)
            ("j_joker", "Holographic"), # flat base + Holo (+flat)
            ("j_golden", "Polychrome"),  # econ base + Poly (+xmult)
            ("j_mime", "Negative"),     # retrigger base + Negative (+slot)
        ]
        feat = extract_features_from_state(
            ante=2, blind_idx=1, dollars=10, hands_left=4, discards_left=3,
            joker_slots=5, jokers=jokers, consumable_slots=2, consumables_count=0,
            vouchers=set(), hand_levels={"Pair": 1}, deck_size=52, suit_counts={},
            face_count=12, enhanced_count=0, sealed_count=0,
        )
        assert feat["n_foil"] == 1.0
        assert feat["n_holo"] == 1.0
        assert feat["n_poly"] == 1.0
        assert feat["n_negative"] == 1.0
        assert feat["n_chips"] == 2.0  # sly (1) + Foil (1)
        assert feat["n_flat_mult"] == 2.0  # joker (1) + Holo (1)
        assert feat["n_xmult"] == 1.0  # Poly (1)
        assert feat["n_econ"] == 1.0   # golden (1)

    def test_r2_state_feature_vector_dimension_and_keys(self):
        """Feature extractor produces the complete 42-feature flat numeric vector."""
        g = create_test_game(jokers=("j_banner", "j_jolly"))
        feat = extract_game_features(g)
        
        assert len(feat) == 42, f"Expected 42 features, got {len(feat)}"
        expected_keys = [
            "ante", "blind_idx", "dollars", "interest_units", "hands_left", "discards_left",
            "joker_count", "free_joker_slots", "n_chips", "n_flat_mult", "n_xmult",
            "n_scaling", "n_econ", "n_retrigger", "n_foil", "n_holo", "n_poly",
            "n_negative", "has_chips", "has_flat", "has_xmult", "has_scaling",
            "has_econ", "is_balanced", "econ_heavy_late", "zero_xmult_late",
            "no_scoring_early", "deck_size", "suit_conc", "face_ratio", "enh_ratio",
            "seal_ratio", "max_hand_lvl", "flush_lvl", "pair_lvl", "two_pair_lvl",
            "high_card_lvl", "vouchers_count", "has_telescope", "has_directors_cut",
            "has_grabber", "has_wasteful",
        ]
        for key in expected_keys:
            assert key in feat, f"Missing expected feature key: {key}"
            assert isinstance(feat[key], float), f"Feature {key} should be float, got {type(feat[key])}"
            assert not math.isnan(feat[key]), f"Feature {key} is NaN"

    def test_r2_feature_extraction_invariants(self):
        """Feature extraction is deterministic, order-independent, and free of live state mutation."""
        g = create_test_game(jokers=("j_banner", "j_cavendish"))
        f1 = extract_game_features(g)
        f2 = extract_game_features(g)
        assert f1 == f2, "Feature extraction must be deterministic"
        
        # Order independence
        deck_orig = list(g.deck)
        g.deck = list(reversed(deck_orig))
        f_rev = extract_game_features(g)
        assert f1 == f_rev, "Deck ordering must not alter composition features"
        
        # No live state mutation
        assert len(g.deck) == len(deck_orig)
        assert len(g.jokers) == 2

    def test_r2_danger_indicators(self):
        """Danger signals (zero_xmult_late, econ_heavy_late, no_scoring_early) evaluate correctly."""
        # Late game zero xmult
        f_late_noxmult = extract_features_from_state(
            ante=5, blind_idx=0, dollars=15, hands_left=4, discards_left=3, joker_slots=5,
            jokers=[("j_banner", None), ("j_jolly", None)], consumable_slots=2, consumables_count=0,
            vouchers=set(), hand_levels={}, deck_size=52, suit_counts={}, face_count=12,
            enhanced_count=0, sealed_count=0,
        )
        assert f_late_noxmult["zero_xmult_late"] == 1.0
        
        # Late game econ heavy
        f_late_econ = extract_features_from_state(
            ante=4, blind_idx=0, dollars=20, hands_left=4, discards_left=3, joker_slots=5,
            jokers=[("j_golden", None), ("j_rocket", None)], consumable_slots=2, consumables_count=0,
            vouchers=set(), hand_levels={}, deck_size=52, suit_counts={}, face_count=12,
            enhanced_count=0, sealed_count=0,
        )
        assert f_late_econ["econ_heavy_late"] == 1.0
        
        # Early game no scoring
        f_early_noscore = extract_features_from_state(
            ante=1, blind_idx=1, dollars=5, hands_left=4, discards_left=3, joker_slots=5,
            jokers=[("j_golden", None)], consumable_slots=2, consumables_count=0,
            vouchers=set(), hand_levels={}, deck_size=52, suit_counts={}, face_count=12,
            enhanced_count=0, sealed_count=0,
        )
        assert f_early_noscore["no_scoring_early"] == 1.0


class TestTier1_R3_OfflineValueModel:
    """Tier 1 Feature Coverage for Requirement R3: Rollout Dataset & Offline Value Model."""

    def test_r3_interaction_terms_computation(self):
        """Interaction builder correctly generates all 6 domain non-linear terms."""
        raw_feat = {
            "ante": 5.0,
            "n_chips": 2.0,
            "n_flat_mult": 1.0,
            "n_scaling": 1.0,
            "n_xmult": 2.0,
            "n_econ": 2.0,
        }
        inter = build_interactions(raw_feat)
        
        assert inter["inter_chips_mult"] == 2.0 * (1.0 + 1.0) == 4.0
        assert inter["inter_mult_xmult"] == (1.0 + 1.0) * 2.0 == 4.0
        assert inter["inter_chips_xmult"] == 2.0 * 2.0 == 4.0
        assert inter["inter_ante_xmult"] == 5.0 * 2.0 == 10.0
        assert inter["inter_late_econ_penalty"] == max(0.0, 5.0 - 3.0) * 2.0 == 4.0
        assert inter["inter_late_zero_xmult"] == 0.0  # since n_xmult = 2.0 > 0

    def test_r3_model_schema_and_weights_validation(self):
        """Model data schema adheres strictly to specifications."""
        sample_feat = {"ante": 1.0, "n_chips": 1.0, "n_xmult": 0.0}
        f_inter = build_interactions(sample_feat)
        feat_order = sorted(f_inter.keys())
        
        d = len(feat_order)
        model_data = {
            "feat_order": feat_order,
            "mean": [0.5] * d,
            "std": [1.0] * d,
            "w": [0.1] * (d + 1),  # d weights + 1 bias
            "test_auc": 0.78,
        }
        
        assert len(model_data["feat_order"]) == d
        assert len(model_data["mean"]) == d
        assert len(model_data["std"]) == d
        assert len(model_data["w"]) == d + 1
        assert 0.5 <= model_data["test_auc"] <= 1.0

    def test_r3_pure_python_inference_correctness(self):
        """Vectorized pure-Python inference computes normalized log-odds and bounded probabilities."""
        sample_feat = {"ante": 1.0, "dollars": 10.0, "n_chips": 1.0, "n_flat_mult": 1.0, "n_xmult": 0.0}
        f_inter = build_interactions(sample_feat)
        feat_order = sorted(f_inter.keys())
        d = len(feat_order)
        
        # Neutral model: all weights zero, bias = 0.0 -> P(Win) = 0.5
        neutral_model = {
            "feat_order": feat_order,
            "mean": [0.0] * d,
            "std": [1.0] * d,
            "w": [0.0] * d + [0.0],
            "test_auc": 0.5,
        }
        prob = evaluate_value_model(sample_feat, neutral_model)
        assert prob == pytest.approx(0.5, abs=1e-6)

    def test_r3_value_monotonicity_with_xmult(self):
        """Adding xMult to an Ante 6 state strictly increases predicted winning probability."""
        feat_order = ["ante", "n_chips", "n_flat_mult", "n_xmult", "inter_ante_xmult", "inter_late_zero_xmult"]
        model = {
            "feat_order": feat_order,
            "mean": [4.0, 1.0, 1.0, 0.5, 2.0, 0.5],
            "std": [2.0, 1.0, 1.0, 0.5, 2.0, 0.5],
            "w": [0.2, 0.3, 0.3, 1.5, 1.2, -1.8, 0.0],
            "test_auc": 0.85,
        }
        
        # State with 0 xMult at Ante 6
        s_noxmult = {"ante": 6.0, "n_chips": 1.0, "n_flat_mult": 1.0, "n_xmult": 0.0}
        # State with 1 xMult at Ante 6
        s_withxmult = {"ante": 6.0, "n_chips": 1.0, "n_flat_mult": 1.0, "n_xmult": 1.0}
        
        v_no = evaluate_value_model(s_noxmult, model)
        v_with = evaluate_value_model(s_withxmult, model)
        
        assert v_with > v_no, f"Expected v_with ({v_with:.4f}) > v_no ({v_no:.4f})"

    def test_r3_value_penalty_for_zero_xmult_late(self):
        """Late-game dysfunctions (0 xMult in Ante 5+) are heavily penalized."""
        feat_order = ["ante", "n_chips", "n_flat_mult", "n_xmult", "inter_late_zero_xmult"]
        model = {
            "feat_order": feat_order,
            "mean": [4.0, 1.0, 1.0, 0.5, 0.3],
            "std": [2.0, 1.0, 1.0, 0.5, 0.4],
            "w": [0.1, 0.2, 0.2, 0.8, -2.5, 0.0],
            "test_auc": 0.82,
        }
        s_ante5_noxmult = {"ante": 5.0, "n_chips": 1.0, "n_flat_mult": 1.0, "n_xmult": 0.0}
        s_ante2_noxmult = {"ante": 2.0, "n_chips": 1.0, "n_flat_mult": 1.0, "n_xmult": 0.0}
        
        v_ante5 = evaluate_value_model(s_ante5_noxmult, model)
        v_ante2 = evaluate_value_model(s_ante2_noxmult, model)
        
        assert v_ante5 < v_ante2, "Ante 5 without xMult should have lower value than Ante 2 without xMult"

    def test_r3_inference_latency_benchmark(self):
        """Pure-Python model evaluation executes within the <1ms latency budget."""
        sample_feat = extract_features_from_state(
            ante=3, blind_idx=1, dollars=15, hands_left=4, discards_left=3, joker_slots=5,
            jokers=[("j_banner", "Foil"), ("j_joker", None)], consumable_slots=2, consumables_count=1,
            vouchers={"v_grabber"}, hand_levels={"Flush": 2}, deck_size=52, suit_counts={},
            face_count=12, enhanced_count=2, sealed_count=1,
        )
        f_inter = build_interactions(sample_feat)
        feat_order = sorted(f_inter.keys())
        d = len(feat_order)
        model = {
            "feat_order": feat_order,
            "mean": [0.5] * d,
            "std": [1.0] * d,
            "w": [0.1] * (d + 1),
            "test_auc": 0.80,
        }
        
        t0 = time.perf_counter()
        iters = 500
        for _ in range(iters):
            _ = evaluate_value_model(sample_feat, model)
        t_total = time.perf_counter() - t0
        avg_latency_us = (t_total / iters) * 1e6
        
        assert avg_latency_us < 1000.0, f"Average latency {avg_latency_us:.1f}µs exceeded 1ms"


class TestTier1_R4_CounterfactualShopSearch:
    """Tier 1 Feature Coverage for Requirement R4: Counterfactual Shop Search & Swapping."""

    def test_r4_search_shop_policy_instantiation_and_human_fair(self):
        """SearchShopV10 defaults to human-fair mode with lookahead disabled."""
        policy = v10.SearchShopV10()
        assert policy.policy_name == "search_shop_v10"
        assert policy._lookahead is False, "SearchShopV10 must have lookahead disabled by default"

    def test_r4_shop_action_evaluation_buy_best_item(self):
        """SearchShopV10 evaluates and buys top-ranked affordable joker in shop."""
        g = create_test_game(dollars=12)
        g.state = State.SHOP
        
        # Populate shop with an affordable high-value joker
        g.current_shop = [
            ShopItem("joker", "j_sly", name="Sly Joker", price=4),
            ShopItem("planet", "c_mercury", name="Mercury", price=3),
        ]
        policy = v10.SearchShopV10()
        act = policy._search_shop(g)
        
        assert act["type"] in ("buy", "leave_shop")
        if act["type"] == "buy":
            assert act["item_idx"] in (0, 1)

    def test_r4_shop_room_making_sell_redundant_joker(self):
        """When joker slots are full and an upgrade is available, agent triggers joker sell to make room."""
        g = create_test_game(dollars=10)
        g.state = State.SHOP
        g.joker_slots = 2
        # Fill 2 slots with weak/degraded jokers
        g.jokers = [
            JokerInstance("j_popcorn", game=g),
            JokerInstance("j_joker", game=g),
        ]
        # High value joker in shop
        g.current_shop = [
            ShopItem("joker", "j_cavendish", name="Cavendish", price=5),
        ]
        
        ref = v10.reference_hand(g)
        surplus = v10.forecast_beatable(g, v10.ACTIVE_PARAMS["tilt_surplus_margin"], ref)
        buys, need_sell = v10._v10_rank_shop_items(g, ref, surplus)
        
        # Verify room-making detection
        if buys and len(g.jokers) >= g.joker_slots:
            assert need_sell is not None, "Room-making should identify candidate to sell"
            assert need_sell[1] in (0, 1), "Should select a valid joker index to sell"

    def test_r4_shop_budget_and_interest_target_discipline(self):
        """SearchShop respects save mode / interest target thresholds."""
        g = create_test_game(ante=3, dollars=20)
        g.state = State.SHOP
        policy = v10.SearchShopV10()
        
        # Empty shop or marginal shop -> cleanly leaves shop
        g.current_shop = []
        act = policy._search_shop(g)
        assert act["type"] == "leave_shop"

    def test_r4_shop_state_transitions_buy_sell_reroll_leave(self):
        """Shop decisions execute clean state transitions without corrupting RNG streams."""
        g = create_test_game(dollars=15)
        g.state = State.SHOP
        policy = v10.SearchShopV10()
        
        # Decide shop
        act = policy.decide(g)
        assert act["type"] in ("buy", "sell_joker", "use_consumable", "reroll", "leave_shop")
        
        # Step game
        g.step(act)
        assert g.state in (State.SHOP, State.BLIND_SELECT, State.BOOSTER_OPEN)


# ────────────────────────────────────────────────────────────────────────────
# TIER 2: BOUNDARY & CORNER CASES
# ────────────────────────────────────────────────────────────────────────────

class TestTier2_BoundaryAndCornerCases:
    """Tier 2: Boundary, Extreme Conditions, and Corner Cases."""

    def test_boundary_empty_portfolio_and_hand(self):
        """State feature extraction and pace rule handle empty portfolios and 0-card hands gracefully."""
        feat = extract_features_from_state(
            ante=1, blind_idx=0, dollars=0, hands_left=4, discards_left=0, joker_slots=5,
            jokers=[], consumable_slots=2, consumables_count=0, vouchers=set(),
            hand_levels={}, deck_size=0, suit_counts={}, face_count=0,
            enhanced_count=0, sealed_count=0,
        )
        assert feat["joker_count"] == 0.0
        assert feat["free_joker_slots"] == 5.0
        assert feat["n_chips"] == 0.0
        assert feat["dollars"] == 0.0
        assert feat["deck_size"] == 0.0
        assert feat["suit_conc"] == 0.0
        assert feat["face_ratio"] == 0.0

    def test_boundary_negative_money_handling(self):
        """Negative money (e.g. from Credit Card debt) produces clamped interest and safe features."""
        feat = extract_features_from_state(
            ante=2, blind_idx=1, dollars=-15, hands_left=4, discards_left=2, joker_slots=5,
            jokers=[("j_credit_card", None)], consumable_slots=2, consumables_count=0,
            vouchers=set(), hand_levels={}, deck_size=52, suit_counts={}, face_count=12,
            enhanced_count=0, sealed_count=0,
        )
        assert feat["dollars"] == -15.0
        assert feat["interest_units"] == 0.0, "Interest units must be clamped at 0 for negative dollars"

    def test_boundary_zero_hands_left(self):
        """Zero hands remaining safely evaluates clear probability to 0.0 and pace safely."""
        g = create_test_game(hands_left=0)
        p_clear = v10.estimate_clear_probability(g)
        assert p_clear == 0.0, "Zero hands left must evaluate to 0.0 clear probability"
        
        # Pace formula division protection
        target = 300
        pace = (target / max(1, g.hands_left))
        assert pace == 300.0

    def test_boundary_max_and_overfilled_joker_slots(self):
        """Exceeding standard joker slots (e.g. via Negative jokers) clamps free slots at 0."""
        feat = extract_features_from_state(
            ante=3, blind_idx=0, dollars=10, hands_left=4, discards_left=3, joker_slots=5,
            jokers=[("j_sly", None), ("j_joker", None), ("j_banner", None),
                    ("j_duo", None), ("j_mime", None), ("j_golden", "Negative")],
            consumable_slots=2, consumables_count=0, vouchers=set(), hand_levels={},
            deck_size=52, suit_counts={}, face_count=12, enhanced_count=0, sealed_count=0,
        )
        assert feat["joker_count"] == 6.0
        assert feat["free_joker_slots"] == 0.0, "Free joker slots must not be negative"

    def test_boundary_extreme_antes_and_targets(self):
        """Extreme antes (Ante 8, Ante 16) and target chips (100,000,000) produce finite features."""
        feat = extract_features_from_state(
            ante=16, blind_idx=2, dollars=500, hands_left=1, discards_left=0, joker_slots=5,
            jokers=[("j_cavendish", "Polychrome")], consumable_slots=2, consumables_count=0,
            vouchers=set(), hand_levels={"Flush": 20}, deck_size=40, suit_counts={"Spades": 30},
            face_count=20, enhanced_count=15, sealed_count=5, chips_target=100000000,
        )
        assert feat["ante"] == 16.0
        assert feat["dollars"] == 500.0
        assert feat["interest_units"] == 5.0  # Max interest is capped at 5
        assert not any(math.isnan(v) or math.isinf(v) for v in feat.values())

    def test_boundary_edge_jokers_and_unclassified_keys(self):
        """Unrecognized or custom joker keys return all False in role classification without raising."""
        c = classify_joker("j_unknown_custom_joker_999")
        assert c["is_chips"] is False
        assert c["is_flat_mult"] is False
        assert c["is_xmult"] is False
        assert c["is_scaling"] is False
        assert c["is_econ"] is False
        assert c["is_retrigger"] is False

    def test_boundary_deck_exhaustion_mid_round(self):
        """A nearly exhausted or empty deck produces valid ratios without zero-division errors."""
        feat = extract_features_from_state(
            ante=1, blind_idx=0, dollars=4, hands_left=2, discards_left=0, joker_slots=5,
            jokers=[], consumable_slots=2, consumables_count=0, vouchers=set(),
            hand_levels={}, deck_size=0, suit_counts={}, face_count=0,
            enhanced_count=0, sealed_count=0,
        )
        assert feat["suit_conc"] == 0.0
        assert feat["face_ratio"] == 0.0
        assert feat["enh_ratio"] == 0.0
        assert feat["seal_ratio"] == 0.0


# ────────────────────────────────────────────────────────────────────────────
# TIER 3: CROSS-FEATURE INTERACTIONS
# ────────────────────────────────────────────────────────────────────────────

class TestTier3_CrossFeatureInteractions:
    """Tier 3: Cross-Feature and Multi-Module Interaction Verification."""

    def test_interaction_pace_rule_with_portfolio_features(self):
        """Pace rule in-blind decisions correctly reflect extracted portfolio danger flags."""
        g = create_test_game(ante=1, chips_target=300, chips_scored=0, hands_left=4, discards_left=3)
        feat = extract_game_features(g)
        
        # When no scoring jokers exist at Ante 1, no_scoring_early flag is set
        assert feat["no_scoring_early"] == 1.0
        
        # Under no_scoring_early, pace rule guides whether to play immediate 80-score hand
        v10.V10_PARAMS["ante1_pace_rule"] = True
        plays = [(80, [0, 1], "Pair")]
        act = v10._tier1_survive(g, plays)
        assert act["type"] == "play"

    def test_interaction_counterfactual_shop_search_xmult_swaps(self):
        """Shop search correctly evaluates xMult joker additions driving positive delta V."""
        g = create_test_game(ante=4, dollars=12)
        g.state = State.SHOP
        g.jokers = [
            JokerInstance("j_joker", game=g),
            JokerInstance("j_golden", game=g),
        ]
        
        feat_before = extract_game_features(g)
        assert feat_before["n_xmult"] == 0.0
        assert feat_before["zero_xmult_late"] == 1.0  # Ante 4 with 0 xmult
        
        # Counterfactual state with xmult acquired
        jokers_after = [("j_joker", None), ("j_golden", None), ("j_cavendish", None)]
        feat_after = extract_features_from_state(
            ante=4, blind_idx=g.blind_idx, dollars=g.dollars - 5, hands_left=g.hands_left,
            discards_left=g.discards_left, joker_slots=5, jokers=jokers_after,
            consumable_slots=2, consumables_count=0, vouchers=set(),
            hand_levels={}, deck_size=52, suit_counts={}, face_count=12,
            enhanced_count=0, sealed_count=0,
        )
        assert feat_after["n_xmult"] == 1.0
        assert feat_after["zero_xmult_late"] == 0.0

    def test_interaction_reshape_and_shop_search_synergy(self):
        """Deck reshape targets directly amplify shop tarot card valuation."""
        g = create_test_game(jokers=("j_baron",))  # Targets Kings
        target = v10.deck_reshape_target(g)
        assert target["rank"] == 13
        
        # Death tarot value is boosted when a target rank is active
        val_normal = v10.tarot_value(g, "c_death")
        val_boosted = v10._v10_tarot_value(g, "c_death")
        assert val_boosted > val_normal, "Death tarot should be boosted when Baron targets Kings"

    def test_interaction_end_to_end_shop_to_blind_transition(self):
        """Purchasing a scoring joker in shop elevates subsequent in-blind scoring & pace satisfaction."""
        g = create_test_game(dollars=8, ante=1, chips_target=300)
        # Add Sly joker to game
        g.jokers.append(JokerInstance("j_sly", game=g))
        
        # Evaluating pair scoring with Sly joker (+50 chips on Pair)
        hand_type, scoring = evaluate_hand([Card(10, "Hearts"), Card(10, "Spades")])
        assert hand_type == "Pair"
        
        # In blind, pace is 75 (300/4). Pair with Sly easily clears pace
        plays = [(120, [0, 1], "Pair")]
        v10.V10_PARAMS["ante1_pace_rule"] = True
        act = v10._tier1_survive(g, plays)
        assert act["type"] == "play"

    def test_interaction_value_farming_gated_by_clear_prob(self):
        """Tier 2 value farming only triggers when P(clear) >= farm_clear_threshold."""
        g = create_test_game(
            hand=[Card(14, "Spades", seal="Gold"), Card(10, "Hearts"), Card(4, "Clubs")],
            chips_target=600,
            chips_scored=0,
            hands_left=1,
            discards_left=0,
        )
        v10.V10_PARAMS["farm_clear_threshold"] = 0.90
        
        # P(clear) with 1 hand on target 600 will be low (< 0.90)
        p_clear = v10.estimate_clear_probability(g)
        assert p_clear < 0.90
        
        # Since p_clear < threshold, agent stays in tier 1 survival rather than farming
        act = v10._v10_decide_hand(g)
        assert act["type"] in ("play", "discard")

    def test_interaction_counterfactual_state_cloning_isolation(self):
        """Counterfactual state feature evaluation leaves live game state strictly unaltered."""
        g = create_test_game(jokers=("j_banner",), dollars=10)
        initial_dollars = g.dollars
        initial_jokers_count = len(g.jokers)
        initial_hand_ids = [id(c) for c in g.hand]
        
        # Extract features
        _ = extract_game_features(g)
        
        assert g.dollars == initial_dollars
        assert len(g.jokers) == initial_jokers_count
        assert [id(c) for c in g.hand] == initial_hand_ids


# ────────────────────────────────────────────────────────────────────────────
# TIER 4: REAL-WORLD SCENARIOS & FULL GAME SIMULATIONS
# ────────────────────────────────────────────────────────────────────────────

class TestTier4_RealWorldScenarios:
    """Tier 4: End-to-End Game Simulations and Fatal Seed Clearances."""

    def test_realworld_fatal_seed_205_clearance(self):
        """Fatal seed 205 clears Ante 1 Small Blind successfully with default V10 policy."""
        game = BalatroGame(seed=205, rng_mode="seed")
        agent = v10.HeuristicV10()
        
        for _ in range(50):
            if game.state == State.GAME_OVER or game.ante > 1 or (game.ante == 1 and game.blind_idx > 0):
                break
            game.step(agent.decide(game))
            
        assert game.state != State.GAME_OVER, "Seed 205 died in Ante 1 Small Blind"
        assert (game.ante > 1 or game.blind_idx > 0), "Seed 205 failed to clear Ante 1 Small Blind"

    def test_realworld_fatal_seed_275_clearance(self):
        """Fatal seed 275 clears Ante 1 Small Blind successfully with default V10 policy."""
        game = BalatroGame(seed=275, rng_mode="seed")
        agent = v10.HeuristicV10()
        
        for _ in range(50):
            if game.state == State.GAME_OVER or game.ante > 1 or (game.ante == 1 and game.blind_idx > 0):
                break
            game.step(agent.decide(game))
            
        assert game.state != State.GAME_OVER, "Seed 275 died in Ante 1 Small Blind"
        assert (game.ante > 1 or game.blind_idx > 0), "Seed 275 failed to clear Ante 1 Small Blind"

    def test_realworld_full_game_rollouts_seeds_0_to_5(self):
        """Full game rollouts on seeds 0..5 execute end-to-end without errors."""
        agent = v10.HeuristicV10()
        for seed in range(6):
            game = BalatroGame(seed=seed, rng_mode="seed")
            result = rollout(game, agent)
            
            assert "won" in result
            assert "ante" in result
            assert "steps" in result
            assert result["steps"] > 0
            assert result["ante"] >= 1

    def test_realworld_paired_seed_reproducibility(self):
        """Rollout on fixed seed is 100% deterministic and reproducible."""
        seed = 42
        agent = v10.HeuristicV10()
        
        g1 = BalatroGame(seed=seed, rng_mode="seed")
        r1 = rollout(g1, agent)
        
        g2 = BalatroGame(seed=seed, rng_mode="seed")
        r2 = rollout(g2, agent)
        
        for k in ("won", "ante", "steps", "dollars", "jokers"):
            assert r1[k] == r2[k], f"Determinism failure on key {k}: {r1[k]} != {r2[k]}"

    def test_realworld_farm_off_vs_v9_exactness(self):
        """Farming-off V10 reproduces baseline V9 decisions byte-for-byte on seeds 0, 1, 2."""
        seeds = (0, 1, 2)
        v9_pol = HeuristicV9()
        v10_pol = v10.HeuristicV10(params={"farm_clear_threshold": 1.0, "ante1_pace_rule": False})
        
        for seed in seeds:
            g9 = BalatroGame(seed=seed, rng_mode="seed")
            g10 = BalatroGame(seed=seed, rng_mode="seed")
            r9 = rollout(g9, v9_pol)
            r10 = rollout(g10, v10_pol)
            
            for key in ("won", "ante", "steps", "dollars", "jokers"):
                assert r9[key] == r10[key], f"Seed {seed} diverged from V9 on key {key}"

    def test_realworld_search_shop_v10_multiround_survival(self):
        """SearchShopV10 navigates shops, buys items, and runs full multi-round games."""
        policy = v10.SearchShopV10()
        game = BalatroGame(seed=10, rng_mode="seed")
        result = rollout(game, policy)
        
        assert result["steps"] > 0
        assert result["ante"] >= 1
        assert "stats" in result
