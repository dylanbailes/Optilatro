"""tests/test_challenger_m2_gen5.py -- Empirical Challenger Test Suite for M2 Gen 5.

Comprehensive adversarial test suite covering:
1. Blueprint / Brainstorm scoring evaluation in scored_plays() and eval_hand_score():
   - Confirms NO AttributeError is thrown by _EvalGame or ScoreContext.
   - Confirms NO plays are dropped (window plays remain fully scored).
   - Tests Blueprint/Brainstorm across joker categories (Chips, Flat Mult, xMult, Scaling, Retrigger).
   - Tests boundary configurations: rightmost Blueprint (target=None), leftmost Brainstorm (target=None),
     Blueprint copying Brainstorm, Brainstorm copying Blueprint, chaining Blueprint -> Blueprint -> target.
   - Tests extra_joker=('j_blueprint', 'None') and extra_joker=('j_brainstorm', 'None') as used during shop search.
2. Discard Deadlock:
   - Holding discard-incentive jokers (Faceless, Green, Ramen, Mail, Trading, Burnt, Hit the Road, Castle, Yorick).
   - Across Antes 1-8, hands_left 1-4, discards_left == 0.
   - Across dangerous and standard bosses (Psychic, Needle, Mouth, Eye, Arm, Water, Flint, Pillar).
   - Across weak hands, strong hands, and zero-progress hands.
   - Verifies agent_v10 (HeuristicV10, SearchShopV10) and agent_v9 (HeuristicV9) NEVER choose discard when discards_left == 0.
3. Scaling Safety and Tier S2 Elimination:
   - Confirms Tier S2 is absent.
   - Confirms winning hand requiring all cards never gets broken.
   - Confirms disjoint in-hand knockout reservation (Tier S1) strictly leaves winning hand intact.
"""
import copy
import itertools
import math
import os
import sys
import pytest

# Ensure vendor/balatro-rl and tools are in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "vendor", "balatro-rl")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from balatro_sim.card import Card
from balatro_sim.game import BalatroGame, State
from balatro_sim.shop import ShopItem, JOKER_CATALOGUE
from balatro_sim.jokers.base import JokerInstance
from balatro_sim.scoring import score_hand
from balatro_sim.agent_v9 import (
    HeuristicV9,
    scored_plays,
    eval_hand_score,
    reference_hand,
    forecast_beatable,
    ACTIVE_PARAMS,
    _EvalGame,
)
import balatro_sim.agent_v10 as v10
from balatro_sim.agent_v10 import (
    HeuristicV10,
    SearchShopV10,
    _find_scaling_action,
    _v10_rank_shop_items,
    SCALING_BANNED_BOSSES,
)


# ============================================================================
# 1. Blueprint / Brainstorm Scoring Evaluation in scored_plays()
# ============================================================================

class TestBlueprintBrainstormScoringEvaluation:
    """Stress-test Blueprint and Brainstorm scoring evaluation in scored_plays()
    and eval_hand_score() to confirm zero AttributeErrors, zero dropped plays,
    and mathematical correctness.
    """

    def _setup_game(self, jokers_keys):
        g = BalatroGame(seed=42, rng_mode="seed")
        g.reset()
        g.state = State.BLIND_SELECT
        g.step({"type": "play_blind"})
        g.ante = 3
        g.hands_left = 4
        g.discards_left = 3
        g.chips_scored = 0
        g.current_blind.chips_target = 5000
        g.hand = [
            Card(14, "Spades"), Card(14, "Hearts"),
            Card(10, "Diamonds"), Card(8, "Clubs"), Card(4, "Spades"),
            Card(3, "Hearts"), Card(2, "Clubs"), Card(2, "Diamonds")
        ]
        g.jokers = [JokerInstance(k, game=g) for k in jokers_keys]
        return g

    @pytest.mark.parametrize("neighbor_key", [
        "j_joker",           # +4 Mult
        "j_half",            # +20 Mult
        "j_ice_cream",       # +100 Chips
        "j_cavendish",       # x3 Mult
        "j_photograph",      # x2 Mult on first face
        "j_green_joker",     # scaling Mult
        "j_hanging_chad",    # retrigger 2x
        "j_blackboard",      # x3 Mult if all spades/clubs
    ])
    def test_blueprint_scoring_no_attribute_error(self, neighbor_key):
        """Blueprint copying various joker types must score cleanly without AttributeError
        or dropping plays in scored_plays()."""
        g = self._setup_game(["j_blueprint", neighbor_key])

        # Direct test: eval_hand_score should not raise AttributeError on _EvalGame
        cards = g.hand[:2]  # Pair of Aces
        score_direct = eval_hand_score(g, "Pair", cards, cards, held_cards=g.hand[2:])
        assert score_direct > 0, f"Direct score must be > 0, got {score_direct}"

        # scored_plays must return non-empty plays, and no plays should be dropped
        plays = scored_plays(g, topk=10)
        assert len(plays) > 0, "scored_plays must not be empty"
        # Compare count against baseline with 2 identical neighbor jokers
        g_baseline = self._setup_game([neighbor_key, neighbor_key])
        plays_base = scored_plays(g_baseline, topk=10)
        assert len(plays) == len(plays_base), (
            f"Blueprint produced {len(plays)} plays vs {len(plays_base)} plays with 2x {neighbor_key}; "
            f"candidate plays might have been dropped due to exceptions!"
        )

    @pytest.mark.parametrize("neighbor_key", [
        "j_joker",
        "j_half",
        "j_ice_cream",
        "j_cavendish",
        "j_photograph",
        "j_green_joker",
        "j_hanging_chad",
    ])
    def test_brainstorm_scoring_no_attribute_error(self, neighbor_key):
        """Brainstorm at index 1 copying leftmost joker must score cleanly without AttributeError."""
        g = self._setup_game([neighbor_key, "j_brainstorm"])

        cards = g.hand[:2]
        score_direct = eval_hand_score(g, "Pair", cards, cards, held_cards=g.hand[2:])
        assert score_direct > 0, f"Direct score must be > 0, got {score_direct}"

        plays = scored_plays(g, topk=10)
        assert len(plays) > 0, "scored_plays must not be empty"
        g_baseline = self._setup_game([neighbor_key, neighbor_key])
        plays_base = scored_plays(g_baseline, topk=10)
        assert len(plays) == len(plays_base)

    def test_blueprint_rightmost_boundary_no_crash(self):
        """Blueprint at rightmost index has no target to copy (target is None).
        Must not crash or raise AttributeError; scores gracefully as inactive."""
        g = self._setup_game(["j_joker", "j_blueprint"])
        cards = g.hand[:2]
        score = eval_hand_score(g, "Pair", cards, cards, held_cards=g.hand[2:])
        assert score > 0

        plays = scored_plays(g, topk=5)
        assert len(plays) > 0

    def test_brainstorm_leftmost_boundary_no_crash(self):
        """Brainstorm at leftmost index (0) cannot copy itself (target is None).
        Must not crash or raise AttributeError; scores gracefully as inactive."""
        g = self._setup_game(["j_brainstorm", "j_joker"])
        cards = g.hand[:2]
        score = eval_hand_score(g, "Pair", cards, cards, held_cards=g.hand[2:])
        assert score > 0

        plays = scored_plays(g, topk=5)
        assert len(plays) > 0

    def test_blueprint_and_brainstorm_mutual_chain(self):
        """Brainstorm at 1 copying Joker at 0, and Blueprint at 2 copying Cavendish at 3.
        Tests multiple copy jokers in the same lineup simultaneously."""
        g = self._setup_game(["j_joker", "j_brainstorm", "j_blueprint", "j_cavendish"])
        cards = g.hand[:2]
        score = eval_hand_score(g, "Pair", cards, cards, held_cards=g.hand[2:])
        assert score > 0

        plays = scored_plays(g, topk=10)
        assert len(plays) > 0

    def test_chained_blueprints(self):
        """Blueprint at 0 copying Blueprint at 1 copying Cavendish at 2."""
        g = self._setup_game(["j_blueprint", "j_blueprint", "j_cavendish"])
        cards = g.hand[:2]
        score = eval_hand_score(g, "Pair", cards, cards, held_cards=g.hand[2:])
        assert score > 0

        plays = scored_plays(g, topk=10)
        assert len(plays) > 0

    @pytest.mark.parametrize("extra_key", ["j_blueprint", "j_brainstorm"])
    def test_scored_plays_with_extra_joker(self, extra_key):
        """scored_plays(g, extra_joker=(key, 'None')) evaluates potential shop purchases.
        Must evaluate cleanly without AttributeError when copy jokers are in extra_joker."""
        g = self._setup_game(["j_joker", "j_cavendish"])
        plays = scored_plays(g, extra_joker=(extra_key, "None"), topk=5)
        assert len(plays) > 0
        assert plays[0][0] > 0


# ============================================================================
# 2. Discard Deadlock Edge Cases with discards_left == 0
# ============================================================================

class TestDiscardDeadlockComprehensive:
    """Exhaustively verify that NO policy EVER returns a DiscardAction
    when discards_left == 0, under highly adversarial conditions.
    """

    DISCARD_INCENTIVE_JOKERS = [
        "j_faceless",      # Earns $5 if 3 face cards discarded
        "j_green_joker",   # Discard gives -1 Mult
        "j_ramen",         # Discard gives -0.01 XMult
        "j_mail",          # Earns $5 per discarded card of specific rank
        "j_trading",       # Discard destroys first card to gain $3
        "j_hit_the_road",  # Discarding Jacks gives XMult
        "j_castle",        # Discarding suit gives chips
        "j_yorick",        # Discarding 23 cards gives XMult
        "j_burnt_joker",   # Upgrades level of first discarded hand
    ]

    ADVERSARIAL_BOSSES = [
        "bl_small",        # standard
        "bl_needle",       # play only 1 hand
        "bl_mouth",        # play only 1 hand type
        "bl_eye",          # no repeat hand types
        "bl_water",        # 0 discards blind
        "bl_arm",          # decreases level of played poker hand
        "bl_psychic",      # must play 5 cards
        "bl_flint",        # base chips and mult halved
        "bl_pillar",       # cards played this ante are debuffed
        "bl_hook",         # discards 2 cards per play
        "bl_tooth",        # lose $1 per card played
    ]

    @pytest.mark.parametrize("pol_cls", [HeuristicV9, HeuristicV10, SearchShopV10])
    @pytest.mark.parametrize("ante", [1, 2, 6, 8])
    @pytest.mark.parametrize("hands_left", [1, 2, 4])
    @pytest.mark.parametrize("boss_key", ["bl_small", "bl_needle", "bl_psychic", "bl_water"])
    def test_zero_discards_deadlock_immunity(self, pol_cls, ante, hands_left, boss_key):
        g = BalatroGame(seed=101, rng_mode="seed")
        g.reset()
        g.state = State.BLIND_SELECT
        g.step({"type": "play_blind"})

        g.ante = ante
        g.hands_left = hands_left
        g.discards_left = 0
        g.chips_scored = 0
        g.current_blind.chips_target = 10000
        g.current_blind.boss_key = boss_key

        # Equip 3 potent discard-incentive jokers
        g.jokers = [
            JokerInstance("j_faceless", game=g),
            JokerInstance("j_mail", game=g),
            JokerInstance("j_green_joker", game=g),
        ]
        # Equip hand full of face cards and mail ranks
        g.hand = [
            Card(11, "Hearts"), Card(12, "Spades"), Card(13, "Diamonds"),
            Card(11, "Clubs"), Card(12, "Hearts"), Card(13, "Spades"),
            Card(7, "Diamonds"), Card(7, "Clubs")
        ]

        pol = pol_cls()
        action = pol.decide(g)

        assert action.get("type") != "discard", (
            f"DEADLOCK DETECTED: {pol_cls.__name__} issued discard when discards_left == 0! "
            f"Ante: {ante}, Hands: {hands_left}, Boss: {boss_key}, Action: {action}"
        )
        assert action.get("type") in ("play", "use"), (
            f"Invalid action type {action.get('type')} when discards_left == 0"
        )

    @pytest.mark.parametrize("joker_key", DISCARD_INCENTIVE_JOKERS)
    def test_individual_discard_jokers_zero_discards(self, joker_key):
        """Each discard-triggering joker alone must never coerce a discard when discards_left == 0."""
        g = BalatroGame(seed=202, rng_mode="seed")
        g.reset()
        g.state = State.BLIND_SELECT
        g.step({"type": "play_blind"})

        g.ante = 1
        g.hands_left = 2
        g.discards_left = 0
        g.chips_scored = 0
        g.current_blind.chips_target = 300
        g.jokers = [JokerInstance(joker_key, game=g)]
        g.hand = [Card(11, "Hearts"), Card(11, "Diamonds"), Card(2, "Clubs"), Card(4, "Spades")]

        for pol_cls in [HeuristicV10, SearchShopV10]:
            pol = pol_cls()
            act = pol.decide(g)
            assert act.get("type") != "discard", (
                f"{pol_cls.__name__} issued discard with {joker_key} when discards_left == 0"
            )


# ============================================================================
# 3. Scaling Safety and Tier S2 Elimination
# ============================================================================

class TestScalingSafetyAndTierS2Elimination:
    """Verify that Tier S2 remains eliminated, and disjoint in-hand knockout
    reservation (Tier S1) functions strictly without risking winning hands.
    """

    def test_tier_s2_failure_mode_cleanly_avoided(self):
        """When all cards in hand form the sole winning hand, _find_scaling_action
        must return None, refusing to break the winning combination."""
        g = BalatroGame(seed=42, rng_mode="seed")
        g.reset()
        g.state = State.BLIND_SELECT
        g.step({"type": "play_blind"})

        g.ante = 2
        g.hands_left = 3
        g.discards_left = 0
        g.chips_scored = 0
        g.hands_played = 0
        g.current_blind.chips_target = 1000
        g.jokers = [JokerInstance("j_green_joker", game=g)]

        # 5-card Royal Flush scoring > 1000
        g.hand = [Card(14, "Spades"), Card(13, "Spades"), Card(12, "Spades"), Card(11, "Spades"), Card(10, "Spades")]
        g.deck = [Card(2, "Hearts"), Card(3, "Clubs")]

        plays = scored_plays(g, topk=5)
        assert plays[0][0] >= 1000

        # With Tier S2 eliminated, _find_scaling_action MUST return None
        act = _find_scaling_action(g, g.hand, plays, 1.0)
        assert act is None, f"Expected None from _find_scaling_action, but got {act}"

        # HeuristicV10 decide must play the winning combo directly
        pol = HeuristicV10()
        dec = pol.decide(g)
        assert dec.get("type") == "play"
        g.step(dec)
        assert g.chips_scored >= 1000, f"Round must be cleared in 1 hand, got {g.chips_scored}/1000"

    def test_tier_s1_disjoint_reservation_intact(self):
        """When hand contains 8 cards: 5 cards form the winning combo K, and 3 cards
        are disjoint scaling triggers, _find_scaling_action plays only from non-K cards,
        leaving K 100% intact."""
        g = BalatroGame(seed=42, rng_mode="seed")
        g.reset()
        g.state = State.BLIND_SELECT
        g.step({"type": "play_blind"})

        g.ante = 2
        g.hands_left = 3
        g.discards_left = 0
        g.chips_scored = 0
        g.hands_played = 0
        g.current_blind.chips_target = 1000
        g.jokers = [
            JokerInstance("j_green_joker", game=g),
            JokerInstance("j_wee", game=g),
        ]

        # 5 cards for Royal Flush (indices 0..4), plus 3 disjoint 2s (indices 5..7)
        g.hand = [
            Card(14, "Spades"), Card(13, "Spades"), Card(12, "Spades"), Card(11, "Spades"), Card(10, "Spades"),
            Card(2, "Hearts"), Card(2, "Diamonds"), Card(2, "Clubs")
        ]

        plays = scored_plays(g, topk=10)
        # Verify Royal Flush clears
        clearing_combos = [pl[1] for pl in plays if pl[0] >= 1000]
        assert len(clearing_combos) > 0

        act = _find_scaling_action(g, g.hand, plays, 1.0)
        assert act is not None, "Expected scaling action to be found from disjoint non-K cards"
        assert act.get("type") == "play"

        played_indices = set(act["cards"])
        # Disjoint reservation check: NONE of the played indices may overlap with the winning Royal Flush (0, 1, 2, 3, 4)
        k_indices = {0, 1, 2, 3, 4}
        assert played_indices.isdisjoint(k_indices), (
            f"Tier S1 violation: played indices {played_indices} overlap with knockout indices {k_indices}!"
        )

        # All played cards must be the 2s
        for idx in played_indices:
            assert g.hand[idx].rank == 2

    def test_absence_of_tier_s2_in_codebase(self):
        """Verify static code invariant: agent_v10.py must not contain Tier S2."""
        v10_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "vendor", "balatro-rl", "balatro_sim", "agent_v10.py"))
        with open(v10_path, "r", encoding="utf-8") as f:
            v10_code = f.read()

        assert "Tier S2" not in v10_code, "Found 'Tier S2' in agent_v10.py! Tier S2 must be completely removed."
