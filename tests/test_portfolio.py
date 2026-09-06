"""tests/test_portfolio.py — Comprehensive unit tests for joker portfolio classification
and state feature extraction (Milestone 2).

Verifies:
1. All 150 canonical spec jokers and their aliases are recognized and correctly categorized.
2. Dual-role and scaling jokers are correctly mapped.
3. Feature extractor produces 42 numeric features with correct value ranges and types.
4. Editions (Foil, Holographic, Polychrome, Negative) correctly increment edition & role counts.
5. Synergy and danger indicators (is_balanced, zero_xmult_late, econ_heavy_late, no_scoring_early) work accurately.
6. Deck statistics, hand levels, and voucher features are calculated correctly.
7. Feature extraction from live BalatroGame instances never mutates state or RNG streams.
"""
from __future__ import annotations

import copy
import json
import math
import pathlib
import sys
from typing import Any

import pytest

# Ensure vendor/balatro-rl and root are on path
ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT / "vendor" / "balatro-rl") not in sys.path:
    sys.path.insert(0, str(ROOT / "vendor" / "balatro-rl"))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from balatro_sim.game import BalatroGame, State
from balatro_sim.jokers.base import JokerInstance, JOKER_REGISTRY
from tools.portfolio import (
    CHIPS_JOKERS,
    FLAT_MULT_JOKERS,
    XMULT_JOKERS,
    SCALING_JOKERS,
    ECON_JOKERS,
    RETRIGGER_JOKERS,
    UTILITY_JOKERS,
    ALIAS_TO_CANONICAL,
    CANONICAL_TO_ALIAS,
    normalize_joker_key,
    classify_joker,
    extract_features_from_state,
    extract_game_features,
)

SPEC_PATH = ROOT / "tools" / "joker_spec.json"
with open(SPEC_PATH, "r", encoding="utf-8") as f:
    JOKER_SPEC: dict[str, Any] = json.load(f)


# ════════════════════════════════════════════════════════════════════════════
# 1. Joker Categorization Tests
# ════════════════════════════════════════════════════════════════════════════

class TestJokerClassification:
    """Test classification of all 150 canonical jokers into 6 strategic roles."""

    def test_all_150_spec_jokers_present_and_recognized(self):
        """Every joker in joker_spec.json must be recognized and return valid 6-role booleans."""
        assert len(JOKER_SPEC) == 150, f"Expected 150 jokers in spec, found {len(JOKER_SPEC)}"
        expected_keys = {"is_chips", "is_flat_mult", "is_xmult", "is_scaling", "is_econ", "is_retrigger"}

        for key, info in JOKER_SPEC.items():
            roles = classify_joker(key)
            assert isinstance(roles, dict), f"classify_joker({key}) did not return a dict"
            assert set(roles.keys()) == expected_keys, f"Invalid keys in classify_joker({key}): {set(roles.keys())}"
            for role_name, is_member in roles.items():
                assert isinstance(is_member, bool), f"{role_name} for {key} is {type(is_member)}, expected bool"

    def test_canonical_chips_jokers(self):
        """Verify representative chips jokers are classified as chips."""
        expected_chips = [
            "j_blue_joker", "j_bull", "j_stuntman", "j_arrowhead",
            "j_ice_cream", "j_runner", "j_square", "j_wee",
            "j_sly", "j_wily", "j_clever", "j_crafty", "j_devious",
            "j_odd_todd", "j_scary_face", "j_banner", "j_stone",
        ]
        for key in expected_chips:
            roles = classify_joker(key)
            assert roles["is_chips"] is True, f"Expected {key} to be classified as chips"

    def test_canonical_flat_mult_jokers(self):
        """Verify representative flat mult jokers are classified as flat mult."""
        expected_flat_mult = [
            "j_joker", "j_half", "j_gros_michel", "j_abstract",
            "j_fibonacci", "j_bootstraps", "j_even_steven", "j_smiley",
            "j_misprint", "j_raised_fist", "j_popcorn", "j_mystic_summit",
            "j_lusty_joker", "j_greedy_joker", "j_wrathful_joker", "j_gluttenous_joker",
            "j_onyx_agate", "j_shoot_the_moon",
        ]
        for key in expected_flat_mult:
            roles = classify_joker(key)
            assert roles["is_flat_mult"] is True, f"Expected {key} to be classified as flat mult"

    def test_canonical_xmult_jokers(self):
        """Verify representative xMult jokers are classified as xMult."""
        expected_xmult = [
            "j_cavendish", "j_baron", "j_constellation", "j_steel_joker",
            "j_photograph", "j_baseball", "j_card_sharp", "j_triboulet",
            "j_duo", "j_trio", "j_family", "j_order", "j_tribe",
            "j_acrobat", "j_ancient", "j_blackboard", "j_bloodstone",
            "j_caino", "j_campfire", "j_drivers_license", "j_flower_pot",
            "j_glass", "j_hit_the_road", "j_hologram", "j_idol",
            "j_loyalty_card", "j_lucky_cat", "j_madness", "j_obelisk",
            "j_ramen", "j_seeing_double", "j_stencil", "j_throwback",
            "j_vampire", "j_yorick",
        ]
        for key in expected_xmult:
            roles = classify_joker(key)
            assert roles["is_xmult"] is True, f"Expected {key} to be classified as xMult"

    def test_canonical_scaling_jokers(self):
        """Verify representative scaling jokers are classified as scaling."""
        expected_scaling = [
            "j_green_joker", "j_ride_the_bus", "j_red_card", "j_trousers",
            "j_supernova", "j_constellation", "j_fortune_teller", "j_wee",
            "j_hiker", "j_vampire", "j_hologram", "j_lucky_cat",
            "j_flash", "j_obelisk", "j_erosion", "j_castle",
            "j_swashbuckler", "j_campfire", "j_caino", "j_yorick",
            "j_glass", "j_runner", "j_square", "j_burnt", "j_space",
            "j_rocket", "j_egg", "j_gift", "j_satellite", "j_steel_joker",
            "j_madness", "j_hit_the_road", "j_throwback",
        ]
        for key in expected_scaling:
            roles = classify_joker(key)
            assert roles["is_scaling"] is True, f"Expected {key} to be classified as scaling"

    def test_canonical_econ_jokers(self):
        """Verify representative econ and consumable generation jokers are classified as econ."""
        expected_econ = [
            "j_golden", "j_delayed_grat", "j_to_the_moon", "j_rocket",
            "j_business", "j_ticket", "j_egg", "j_faceless",
            "j_mail", "j_rough_gem", "j_reserved_parking", "j_todo_list",
            "j_cloud_9", "j_credit_card", "j_satellite", "j_trading",
            "j_gift", "j_matador", "j_astronomer", "j_chaos",
            "j_diet_cola", "j_midas_mask", "j_riff_raff",
            "j_8_ball", "j_cartomancer", "j_certificate", "j_hallucination",
            "j_perkeo", "j_seance", "j_sixth_sense", "j_superposition", "j_vagabond",
        ]
        for key in expected_econ:
            roles = classify_joker(key)
            assert roles["is_econ"] is True, f"Expected {key} to be classified as econ"

    def test_canonical_retrigger_jokers(self):
        """Verify representative retrigger and copy jokers are classified as retrigger."""
        expected_retrigger = [
            "j_dusk", "j_hack", "j_hanging_chad", "j_mime",
            "j_selzer", "j_sock_and_buskin", "j_blueprint", "j_brainstorm",
            "j_invisible", "j_dna",
        ]
        for key in expected_retrigger:
            roles = classify_joker(key)
            assert roles["is_retrigger"] is True, f"Expected {key} to be classified as retrigger"

    def test_dual_role_jokers(self):
        """Verify jokers with multiple strategic capabilities have both roles set."""
        # Scholar: +20 Chips and +4 Mult per Ace
        scholar = classify_joker("j_scholar")
        assert scholar["is_chips"] is True
        assert scholar["is_flat_mult"] is True

        # Walkie Talkie: +10 Chips and +4 Mult per 10/4
        wt = classify_joker("j_walkie_talkie")
        assert wt["is_chips"] is True
        assert wt["is_flat_mult"] is True

        # Wee Joker: Chips + Scaling (+8 Chips per 2)
        wee = classify_joker("j_wee")
        assert wee["is_chips"] is True
        assert wee["is_scaling"] is True

        # Constellation: xMult + Scaling (+0.1 xMult per Planet)
        const = classify_joker("j_constellation")
        assert const["is_xmult"] is True
        assert const["is_scaling"] is True

        # Rocket: Econ + Scaling ($1 + $2 per boss)
        rocket = classify_joker("j_rocket")
        assert rocket["is_econ"] is True
        assert rocket["is_scaling"] is True

    def test_alias_normalization(self):
        """Verify all aliases normalize to their canonical counterparts and yield identical classifications."""
        for alias, canonical in ALIAS_TO_CANONICAL.items():
            assert normalize_joker_key(alias) == canonical
            alias_roles = classify_joker(alias)
            canonical_roles = classify_joker(canonical)
            assert alias_roles == canonical_roles, f"Mismatch for {alias} vs {canonical}: {alias_roles} != {canonical_roles}"


# ════════════════════════════════════════════════════════════════════════════
# 2. State Feature Extraction Tests
# ════════════════════════════════════════════════════════════════════════════

class TestExtractFeaturesFromState:
    """Test feature extraction from synthetic and counterfactual state components."""

    @pytest.fixture
    def baseline_state(self) -> dict[str, Any]:
        """Provide a standard clean state dictionary."""
        return {
            "ante": 1,
            "blind_idx": 0,
            "dollars": 10,
            "hands_left": 4,
            "discards_left": 3,
            "joker_slots": 5,
            "jokers": [],
            "consumable_slots": 2,
            "consumables_count": 0,
            "vouchers": set(),
            "hand_levels": {"Flush": 1, "Pair": 1, "Two Pair": 1, "High Card": 1},
            "deck_size": 52,
            "suit_counts": {"Spades": 13, "Hearts": 13, "Clubs": 13, "Diamonds": 13},
            "face_count": 12,
            "enhanced_count": 0,
            "sealed_count": 0,
            "chips_target": 300,
        }

    def test_feature_vector_keys_and_types(self, baseline_state):
        """Verify all 42 features are present and purely numeric float values."""
        features = extract_features_from_state(**baseline_state)
        assert len(features) == 42, f"Expected 42 features, got {len(features)}"

        for key, val in features.items():
            assert isinstance(val, float), f"Feature {key} has type {type(val)}, expected float"
            assert not math.isnan(val), f"Feature {key} is NaN"
            assert not math.isinf(val), f"Feature {key} is Inf"

    def test_empty_and_zero_boundary_state(self):
        """Verify extraction handles zero deck, empty collections, and extreme numbers without crash."""
        features = extract_features_from_state(
            ante=0,
            blind_idx=0,
            dollars=-20,
            hands_left=0,
            discards_left=0,
            joker_slots=0,
            jokers=[],
            consumable_slots=0,
            consumables_count=0,
            vouchers=[],
            hand_levels={},
            deck_size=0,
            suit_counts={},
            face_count=0,
            enhanced_count=0,
            sealed_count=0,
            chips_target=0,
        )
        assert features["ante"] == 0.0
        assert features["dollars"] == -20.0
        assert features["interest_units"] == 0.0
        assert features["deck_size"] == 0.0
        assert features["suit_conc"] == 0.0
        assert features["face_ratio"] == 0.0
        assert features["free_joker_slots"] == 0.0

    def test_portfolio_role_and_edition_counting(self, baseline_state):
        """Verify role counts and edition modifiers are accurately calculated."""
        # Add 1 Chips joker (Foil), 1 Flat mult (Holo), 1 xMult (Poly), 1 Negative Econ
        baseline_state["jokers"] = [
            ("j_blue_joker", "Foil"),          # chips + 1, foil + 1, chips + 1 (from foil)
            ("j_gros_michel", "Holographic"),   # flat + 1, holo + 1, flat + 1 (from holo)
            ("j_cavendish", "Polychrome"),      # xmult + 1, poly + 1, xmult + 1 (from poly)
            ("j_golden", "Negative"),           # econ + 1, negative + 1
        ]
        f = extract_features_from_state(**baseline_state)

        assert f["joker_count"] == 4.0
        assert f["free_joker_slots"] == 1.0  # 5 - 4
        assert f["n_chips"] == 2.0           # Blue Joker + Foil
        assert f["n_flat_mult"] == 2.0       # Gros Michel + Holographic
        assert f["n_xmult"] == 2.0           # Cavendish + Polychrome
        assert f["n_econ"] == 1.0            # Golden Joker
        assert f["n_foil"] == 1.0
        assert f["n_holo"] == 1.0
        assert f["n_poly"] == 1.0
        assert f["n_negative"] == 1.0

    def test_synergy_and_balance_metrics(self, baseline_state):
        """Verify is_balanced requires chips, flat/scaling, and xmult."""
        # Unbalanced: only chips and flat
        baseline_state["jokers"] = [("j_blue_joker", None), ("j_gros_michel", None)]
        f = extract_features_from_state(**baseline_state)
        assert f["has_chips"] == 1.0
        assert f["has_flat"] == 1.0
        assert f["has_xmult"] == 0.0
        assert f["is_balanced"] == 0.0

        # Balanced: chips, flat, and xmult
        baseline_state["jokers"].append(("j_cavendish", None))
        f_balanced = extract_features_from_state(**baseline_state)
        assert f_balanced["has_xmult"] == 1.0
        assert f_balanced["is_balanced"] == 1.0

        # Balanced with scaling instead of flat
        baseline_state["jokers"] = [("j_blue_joker", None), ("j_green_joker", None), ("j_cavendish", None)]
        f_scaling_balanced = extract_features_from_state(**baseline_state)
        assert f_scaling_balanced["has_scaling"] == 1.0
        assert f_scaling_balanced["is_balanced"] == 1.0

    def test_danger_signals(self, baseline_state):
        """Verify danger indicator flags activate under specific failing conditions."""
        # no_scoring_early: ante <= 2 and no chips/flat scoring
        baseline_state["ante"] = 1
        baseline_state["jokers"] = [("j_golden", None)]  # Econ only
        f_early_danger = extract_features_from_state(**baseline_state)
        assert f_early_danger["no_scoring_early"] == 1.0

        # Safe early: has chips
        baseline_state["jokers"] = [("j_sly", None)]
        f_early_safe = extract_features_from_state(**baseline_state)
        assert f_early_safe["no_scoring_early"] == 0.0

        # zero_xmult_late: ante >= 4 with zero xmult
        baseline_state["ante"] = 4
        baseline_state["jokers"] = [("j_blue_joker", None), ("j_gros_michel", None)]
        f_late_no_xmult = extract_features_from_state(**baseline_state)
        assert f_late_no_xmult["zero_xmult_late"] == 1.0

        # Safe late: has xmult
        baseline_state["jokers"].append(("j_cavendish", None))
        f_late_with_xmult = extract_features_from_state(**baseline_state)
        assert f_late_with_xmult["zero_xmult_late"] == 0.0

        # econ_heavy_late: ante >= 3 with >= 2 econ jokers
        baseline_state["ante"] = 3
        baseline_state["jokers"] = [("j_golden", None), ("j_delayed_grat", None)]
        f_econ_heavy = extract_features_from_state(**baseline_state)
        assert f_econ_heavy["econ_heavy_late"] == 1.0

        # Not econ heavy: only 1 econ joker
        baseline_state["jokers"] = [("j_golden", None)]
        f_econ_ok = extract_features_from_state(**baseline_state)
        assert f_econ_ok["econ_heavy_late"] == 0.0

    def test_financial_health_and_interest(self, baseline_state):
        """Verify interest units cap at 5 for $25+."""
        for dollars, expected_interest in [(0, 0.0), (4, 0.0), (5, 1.0), (14, 2.0), (25, 5.0), (100, 5.0)]:
            baseline_state["dollars"] = dollars
            f = extract_features_from_state(**baseline_state)
            assert f["interest_units"] == expected_interest

    def test_vouchers_and_deck_ratios(self, baseline_state):
        """Verify voucher flags and deck concentration metrics."""
        baseline_state["vouchers"] = {"v_telescope", "v_grabber"}
        baseline_state["deck_size"] = 50
        baseline_state["suit_counts"] = {"Spades": 25, "Hearts": 25}
        baseline_state["face_count"] = 15
        baseline_state["enhanced_count"] = 10
        baseline_state["sealed_count"] = 5

        f = extract_features_from_state(**baseline_state)
        assert f["vouchers_count"] == 2.0
        assert f["has_telescope"] == 1.0
        assert f["has_grabber"] == 1.0
        assert f["has_directors_cut"] == 0.0
        assert f["has_wasteful"] == 0.0
        assert f["suit_conc"] == pytest.approx(0.5)
        assert f["face_ratio"] == pytest.approx(0.3)
        assert f["enh_ratio"] == pytest.approx(0.2)
        assert f["seal_ratio"] == pytest.approx(0.1)


# ════════════════════════════════════════════════════════════════════════════
# 3. Live Game Feature Extraction & Non-Mutation Tests
# ════════════════════════════════════════════════════════════════════════════

class TestExtractGameFeatures:
    """Test feature extraction from live BalatroGame instances and strict non-mutation."""

    def test_extract_from_fresh_game(self):
        """Extract features from a fresh new BalatroGame instance."""
        game = BalatroGame(seed=42, rng_mode="seed")
        feats = extract_game_features(game)

        assert isinstance(feats, dict)
        assert len(feats) == 42
        assert feats["ante"] == 1.0
        assert feats["blind_idx"] == 0.0
        assert feats["dollars"] == 4.0
        assert feats["joker_count"] == 0.0
        assert feats["free_joker_slots"] == 5.0
        assert feats["deck_size"] == 52.0

    def test_extract_with_live_jokers_and_vouchers(self):
        """Extract features from game with populated jokers, editions, and vouchers."""
        game = BalatroGame(seed=100, rng_mode="seed")
        # Populate jokers with editions
        j1 = JokerInstance("j_stuntman", edition="Foil", game=game)
        j2 = JokerInstance("j_cavendish", edition="Polychrome", game=game)
        j3 = JokerInstance("j_to_the_moon", edition=None, game=game)
        game.jokers = [j1, j2, j3]
        game.vouchers = ["v_telescope", "v_wasteful"]
        game.dollars = 35

        feats = extract_game_features(game)
        assert feats["joker_count"] == 3.0
        assert feats["free_joker_slots"] == 2.0
        assert feats["n_chips"] == 2.0  # Stuntman + Foil
        assert feats["n_xmult"] == 2.0  # Cavendish + Polychrome
        assert feats["n_econ"] == 1.0   # To the Moon
        assert feats["has_telescope"] == 1.0
        assert feats["has_wasteful"] == 1.0
        assert feats["interest_units"] == 5.0

    def test_no_rng_stream_mutation(self):
        """Extracting game features must NEVER advance or consume any RNG node."""
        game1 = BalatroGame(seed=777, rng_mode="seed")
        game2 = BalatroGame(seed=777, rng_mode="seed")

        # Run extraction multiple times on game1
        for _ in range(20):
            _ = extract_game_features(game1)

        # Confirm all RNG streams produce identical outputs
        nodes_to_test = ["boss", "shop_joker", "shop_pack", "tarot", "planet", "spectral", "misprint"]
        for node_name in nodes_to_test:
            r1 = [game1.rng.node(node_name).random() for _ in range(5)]
            r2 = [game2.rng.node(node_name).random() for _ in range(5)]
            assert r1 == r2, f"RNG stream diverged on node {node_name} after feature extraction"

    def test_no_game_state_mutation(self):
        """Extracting game features must not mutate any game attribute."""
        game = BalatroGame(seed=42, rng_mode="seed")
        game.jokers = [JokerInstance("j_joker", game=game)]
        game.dollars = 15

        orig_jokers = list(game.jokers)
        orig_dollars = game.dollars
        orig_deck_len = len(game.deck)
        orig_hand_levels = dict(getattr(game, "planet_levels", getattr(game, "hand_levels", {})))

        _ = extract_game_features(game)

        assert game.jokers == orig_jokers
        assert game.dollars == orig_dollars
        assert len(game.deck) == orig_deck_len
        assert getattr(game, "planet_levels", getattr(game, "hand_levels", {})) == orig_hand_levels

    def test_counterfactual_shop_buy_action(self):
        """Verify delta features for candidate buy action reflect accurate counterfactual state."""
        game = BalatroGame(seed=42, rng_mode="seed")
        game.dollars = 10
        base_features = extract_game_features(game)

        # Counterfactual: buy Cavendish (price $6, xMult)
        buy_jokers = [(j.key, getattr(j, "edition", None)) for j in game.jokers] + [("j_cavendish", None)]
        cf_features = extract_features_from_state(
            ante=game.ante,
            blind_idx=game.blind_idx,
            dollars=game.dollars - 6,
            hands_left=game.hands_left,
            discards_left=game.discards_left,
            joker_slots=game.joker_slots,
            jokers=buy_jokers,
            consumable_slots=game.consumable_slots,
            consumables_count=len(game.consumable_hand),
            vouchers=set(game.vouchers),
            hand_levels=dict(game.planet_levels),
            deck_size=len(game.deck),
            suit_counts={},
            face_count=0,
            enhanced_count=0,
            sealed_count=0,
        )

        assert cf_features["dollars"] == base_features["dollars"] - 6.0
        assert cf_features["joker_count"] == base_features["joker_count"] + 1.0
        assert cf_features["n_xmult"] == base_features["n_xmult"] + 1.0
        assert cf_features["free_joker_slots"] == base_features["free_joker_slots"] - 1.0

    def test_counterfactual_shop_sell_action(self):
        """Verify delta features for candidate sell action reflect accurate counterfactual state."""
        game = BalatroGame(seed=42, rng_mode="seed")
        game.dollars = 5
        game.jokers = [JokerInstance("j_golden", game=game)]
        base_features = extract_game_features(game)

        # Counterfactual: sell Golden Joker (sell value $2, econ)
        cf_features = extract_features_from_state(
            ante=game.ante,
            blind_idx=game.blind_idx,
            dollars=game.dollars + 2,
            hands_left=game.hands_left,
            discards_left=game.discards_left,
            joker_slots=game.joker_slots,
            jokers=[],
            consumable_slots=game.consumable_slots,
            consumables_count=0,
            vouchers=set(game.vouchers),
            hand_levels=dict(game.planet_levels),
            deck_size=len(game.deck),
            suit_counts={},
            face_count=0,
            enhanced_count=0,
            sealed_count=0,
        )

        assert cf_features["dollars"] == base_features["dollars"] + 2.0
        assert cf_features["joker_count"] == base_features["joker_count"] - 1.0
        assert cf_features["n_econ"] == base_features["n_econ"] - 1.0
        assert cf_features["free_joker_slots"] == base_features["free_joker_slots"] + 1.0

    def test_fit_shop_model_interaction_compatibility(self):
        """Verify extract_features_from_state output is 100% compatible with tools/fit_shop_model.py build_interactions."""
        from tools.fit_shop_model import build_interactions

        game = BalatroGame(seed=42, rng_mode="seed")
        f = extract_game_features(game)
        inter_f = build_interactions(f)

        expected_interactions = {
            "inter_chips_mult",
            "inter_mult_xmult",
            "inter_chips_xmult",
            "inter_ante_xmult",
            "inter_late_econ_penalty",
            "inter_late_zero_xmult",
        }
        for inter_key in expected_interactions:
            assert inter_key in inter_f, f"Missing interaction key {inter_key}"
            assert isinstance(inter_f[inter_key], float), f"Interaction {inter_key} is not float"

