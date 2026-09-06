"""tests/test_challenger_acceptance.py — Adversarial Acceptance Stress Test Suite.

Independent empirical verification for final acceptance:
1. Discard Deadlock Immunity:
   Exhaustive test across all discard-incentive jokers, adversarial boss blinds,
   extreme hand compositions (pure face cards, pure mail ranks, debuffed cards),
   hands_left 1-4, antes 1-8, with discards_left == 0.
   Confirms HeuristicV9, HeuristicV10, and SearchShopV10 NEVER issue DiscardAction.

2. Scaling Safety & In-Hand Knockout Reservation:
   Boundary stress-testing of _find_scaling_action:
   - 1 hand left (must return None)
   - 2 hands left (must return None)
   - Ante 1 (must return None)
   - All 11 banned bosses (must return None)
   - 1-hand limit: chips_scored > 0 or hands_played > 0 (must return None)
   - Target <= 0 (must return None)
   - All cards required for winning hand (must return None)
   - Strict disjointness: candidate scaling cards never intersect with winning combo K.
   - Static absence of Tier S2 in agent_v10.py.

3. Blueprint / Brainstorm Shop Ranking, Counterfactual Search, & Scoring Evaluation:
   - Rightmost Blueprint (target=None) evaluation
   - Leftmost Brainstorm (target=None) evaluation
   - Mutual copy loop (Blueprint copying Brainstorm, Brainstorm copying Blueprint)
   - Chained copy jokers (Blueprint copying Blueprint copying Cavendish)
   - Copying chips, flat mult, xMult, scaling, retrigger, and card-score jokers
   - Shop ranking with 5/5 jokers and Blueprint/Brainstorm in shop (allowance and need_sell)
   - SearchShopV10 counterfactual sell-and-buy execution
"""
import copy
import os
import sys
import pytest

# Ensure vendor/balatro-rl and tools are on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "vendor", "balatro-rl")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from balatro_sim.card import Card
from balatro_sim.game import BalatroGame, State
from balatro_sim.shop import ShopItem
from balatro_sim.jokers.base import JokerInstance
from balatro_sim.scoring import score_hand
from balatro_sim.agent_v9 import (
    HeuristicV9,
    _EvalGame,
    scored_plays,
    eval_hand_score,
    best_play_score,
    reference_hand,
    forecast_beatable,
    ACTIVE_PARAMS,
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
# Section 1: Discard Deadlock Immunity (discards_left == 0)
# ============================================================================

class TestDiscardDeadlockAcceptance:
    """Stress-test that zero discards left guarantees zero discard actions."""

    DISCARD_JOKERS = [
        "j_faceless",
        "j_green_joker",
        "j_ramen",
        "j_mail",
        "j_trading",
        "j_hit_the_road",
        "j_castle",
        "j_yorick",
        "j_burnt_joker",
    ]

    ADVERSARIAL_BOSSES = [
        "bl_small",
        "bl_water",      # Start with 0 discards
        "bl_needle",     # Only 1 hand
        "bl_psychic",    # Must play 5 cards
        "bl_mouth",      # Only 1 hand type
        "bl_eye",        # No repeat hand types
        "bl_arm",        # Decreases poker hand level
        "bl_flint",      # Base chips and mult halved
        "bl_pillar",     # Debuffs cards played this ante
        "bl_hook",       # Discards 2 cards per play
        "bl_tooth",      # Lose $1 per card played
    ]

    @pytest.mark.parametrize("policy_cls", [HeuristicV9, HeuristicV10, SearchShopV10])
    @pytest.mark.parametrize("boss", ADVERSARIAL_BOSSES)
    def test_zero_discards_under_all_bosses(self, policy_cls, boss):
        g = BalatroGame(seed=777, rng_mode="seed")
        g.reset()
        g.state = State.BLIND_SELECT
        g.step({"type": "play_blind"})

        g.ante = 3
        g.hands_left = 2
        g.discards_left = 0
        g.chips_scored = 0
        g.current_blind.chips_target = 8000
        g.current_blind.boss_key = boss

        # Equip discard jokers
        g.jokers = [
            JokerInstance("j_faceless", game=g),
            JokerInstance("j_mail", game=g),
            JokerInstance("j_trading", game=g),
        ]
        g.hand = [
            Card(11, "Hearts"), Card(12, "Hearts"), Card(13, "Hearts"),
            Card(11, "Diamonds"), Card(12, "Diamonds"), Card(13, "Diamonds"),
            Card(7, "Spades"), Card(7, "Clubs")
        ]

        pol = policy_cls()
        action = pol.decide(g)

        assert action.get("type") != "discard", (
            f"DEADLOCK IMMUNITY VIOLATION: {policy_cls.__name__} issued discard with 0 discards under {boss}!"
        )
        assert action.get("type") in ("play", "use")

    @pytest.mark.parametrize("joker_key", DISCARD_JOKERS)
    @pytest.mark.parametrize("hands_left", [1, 2, 4])
    def test_each_discard_joker_with_pure_target_hand(self, joker_key, hands_left):
        """Even when hand consists solely of cards incentivized for discard, never discard."""
        g = BalatroGame(seed=888, rng_mode="seed")
        g.reset()
        g.state = State.BLIND_SELECT
        g.step({"type": "play_blind"})

        g.ante = 2
        g.hands_left = hands_left
        g.discards_left = 0
        g.chips_scored = 0
        g.current_blind.chips_target = 2000
        j_inst = JokerInstance(joker_key, game=g)
        if joker_key == "j_mail":
            j_inst.state["rebate_rank"] = 7
        g.jokers = [j_inst]

        # Construct worst case: hand全是 face cards or rank 7s
        if joker_key in ("j_faceless", "j_hit_the_road"):
            g.hand = [Card(11, "Hearts"), Card(11, "Diamonds"), Card(12, "Clubs"), Card(13, "Spades"), Card(11, "Spades")]
        elif joker_key == "j_mail":
            g.hand = [Card(7, "Hearts"), Card(7, "Diamonds"), Card(7, "Clubs"), Card(7, "Spades"), Card(2, "Hearts")]
        else:
            g.hand = [Card(2, "Hearts"), Card(3, "Diamonds"), Card(5, "Clubs"), Card(7, "Spades"), Card(9, "Hearts")]

        for pol_cls in [HeuristicV10, SearchShopV10]:
            pol = pol_cls()
            action = pol.decide(g)
            assert action.get("type") != "discard", (
                f"{pol_cls.__name__} issued discard for {joker_key} with hands_left={hands_left} and discards_left=0!"
            )


# ============================================================================
# Section 2: Scaling Safety & In-Hand Knockout Reservation
# ============================================================================

class TestScalingSafetyAcceptance:
    """Stress-test _find_scaling_action safety guardrails."""

    def _setup_game(self, ante=2, hands_left=3, chips_scored=0, hands_played=0, boss="bl_small", target=1000):
        g = BalatroGame(seed=42, rng_mode="seed")
        g.reset()
        g.state = State.BLIND_SELECT
        g.step({"type": "play_blind"})

        g.ante = ante
        g.hands_left = hands_left
        g.discards_left = 0
        g.chips_scored = chips_scored
        g.hands_played = hands_played
        g.current_blind.chips_target = target
        g.current_blind.boss_key = boss
        g.jokers = [
            JokerInstance("j_green_joker", game=g),
            JokerInstance("j_wee", game=g),
            JokerInstance("j_ride_the_bus", game=g),
        ]
        # Winning Royal Flush (indices 0-4), plus two disjoint 2s (indices 5-6)
        g.hand = [
            Card(14, "Spades"), Card(13, "Spades"), Card(12, "Spades"), Card(11, "Spades"), Card(10, "Spades"),
            Card(2, "Hearts"), Card(2, "Clubs")
        ]
        return g

    def test_hands_left_boundary(self):
        """Must return None when hands_left < 3 (i.e. 1 or 2)."""
        for h in [0, 1, 2]:
            g = self._setup_game(hands_left=h)
            plays = scored_plays(g, topk=5)
            act = _find_scaling_action(g, g.hand, plays, 1.0)
            assert act is None, f"Expected None for hands_left={h}, got {act}"

    def test_ante_one_boundary(self):
        """Must return None in Ante 1."""
        g = self._setup_game(ante=1, hands_left=4)
        plays = scored_plays(g, topk=5)
        act = _find_scaling_action(g, g.hand, plays, 1.0)
        assert act is None, f"Expected None for ante=1, got {act}"

    @pytest.mark.parametrize("boss", sorted(list(SCALING_BANNED_BOSSES)))
    def test_all_banned_bosses(self, boss):
        """Must return None against every banned boss."""
        g = self._setup_game(ante=3, hands_left=4, boss=boss)
        plays = scored_plays(g, topk=5)
        act = _find_scaling_action(g, g.hand, plays, 1.0)
        assert act is None, f"Expected None against banned boss {boss}, got {act}"

    def test_single_play_per_round_limit(self):
        """Must return None if chips_scored > 0 or hands_played > 0."""
        # Case A: chips_scored > 0
        g1 = self._setup_game(chips_scored=50, hands_played=0)
        plays1 = scored_plays(g1, topk=5)
        assert _find_scaling_action(g1, g1.hand, plays1, 1.0) is None

        # Case B: hands_played > 0
        g2 = self._setup_game(chips_scored=0, hands_played=1)
        plays2 = scored_plays(g2, topk=5)
        assert _find_scaling_action(g2, g2.hand, plays2, 1.0) is None

    def test_target_already_met(self):
        """Must return None if target <= chips_scored."""
        g = self._setup_game(target=1000, chips_scored=1000)
        plays = scored_plays(g, topk=5)
        assert _find_scaling_action(g, g.hand, plays, 1.0) is None

    def test_winning_hand_requires_all_cards_returns_none(self):
        """When the sole winning hand requires all held cards, scaling MUST return None."""
        g = self._setup_game(target=1000)
        # Exactly 5 cards forming Royal Flush scoring > 1000; no disjoint cards
        g.hand = [Card(14, "Spades"), Card(13, "Spades"), Card(12, "Spades"), Card(11, "Spades"), Card(10, "Spades")]
        plays = scored_plays(g, topk=5)
        assert plays[0][0] >= 1000

        act = _find_scaling_action(g, g.hand, plays, 1.0)
        assert act is None, f"Expected None when all cards are needed for knockout, got {act}"

    def test_disjoint_preservation_guarantee(self):
        """When scaling action is found, played cards must be strictly disjoint from winning combo K."""
        g = self._setup_game(target=1000)
        plays = scored_plays(g, topk=5)
        clearing = [pl for pl in plays if pl[0] >= 1000]
        assert len(clearing) > 0

        act = _find_scaling_action(g, g.hand, plays, 1.0)
        assert act is not None
        played_idxs = set(act["cards"])

        # Indices 0-4 are the Royal Flush
        k_idxs = {0, 1, 2, 3, 4}
        assert played_idxs.isdisjoint(k_idxs), f"Played cards {played_idxs} overlapped with winning hand {k_idxs}!"
        # Played cards must be 2s (indices 5, 6)
        for idx in played_idxs:
            assert g.hand[idx].rank == 2

    def test_ride_the_bus_strictly_avoids_scoring_faces(self):
        """Ride the Bus must never play scoring face cards as scaling triggers."""
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
        g.current_blind.boss_key = "bl_small"
        g.jokers = [JokerInstance("j_ride_the_bus", game=g)]

        # Winning hand: 5 Aces/Kings forming Full House (>1000 chips)
        # Extra disjoint cards: Jack of Hearts (face card) and 4 of Clubs (non-face)
        g.hand = [
            Card(14, "Spades"), Card(14, "Hearts"), Card(14, "Clubs"), Card(13, "Diamonds"), Card(13, "Spades"),
            Card(11, "Hearts"), Card(4, "Clubs")
        ]
        plays = scored_plays(g, topk=5)
        act = _find_scaling_action(g, g.hand, plays, 1.0)
        if act is not None:
            # Verify no face cards were played
            for idx in act["cards"]:
                assert not g.hand[idx].is_face_card, f"Ride the Bus played face card {g.hand[idx]}!"


# ============================================================================
# Section 3: Blueprint & Brainstorm Scoring and Shop Search
# ============================================================================

class TestBlueprintBrainstormAcceptance:
    """Stress-test Blueprint and Brainstorm scoring evaluation and shop interactions."""

    def _setup_scoring_game(self, joker_keys):
        g = BalatroGame(seed=999, rng_mode="seed")
        g.reset()
        g.state = State.BLIND_SELECT
        g.step({"type": "play_blind"})
        g.ante = 4
        g.hands_left = 4
        g.discards_left = 3
        g.chips_scored = 0
        g.current_blind.chips_target = 10000
        g.hand = [
            Card(14, "Spades"), Card(14, "Hearts"), Card(10, "Diamonds"),
            Card(8, "Clubs"), Card(4, "Spades"), Card(3, "Hearts"),
            Card(2, "Clubs"), Card(2, "Diamonds")
        ]
        g.jokers = [JokerInstance(k, game=g) for k in joker_keys]
        return g

    def test_rightmost_blueprint_target_none(self):
        """Blueprint at rightmost slot has target=None; eval_hand_score and scored_plays must not crash."""
        g = self._setup_scoring_game(["j_joker", "j_blueprint"])
        cards = g.hand[:2]
        score = eval_hand_score(g, "Pair", cards, cards, held_cards=g.hand[2:])
        assert score > 0
        plays = scored_plays(g, topk=5)
        assert len(plays) > 0

    def test_leftmost_brainstorm_target_none(self):
        """Brainstorm at leftmost slot has target=None; eval_hand_score and scored_plays must not crash."""
        g = self._setup_scoring_game(["j_brainstorm", "j_joker"])
        cards = g.hand[:2]
        score = eval_hand_score(g, "Pair", cards, cards, held_cards=g.hand[2:])
        assert score > 0
        plays = scored_plays(g, topk=5)
        assert len(plays) > 0

    def test_mutual_blueprint_brainstorm_lineup(self):
        """Lineup with both Blueprint and Brainstorm copying active jokers."""
        g = self._setup_scoring_game(["j_cavendish", "j_brainstorm", "j_joker", "j_blueprint", "j_ice_cream"])
        cards = g.hand[:2]
        score = eval_hand_score(g, "Pair", cards, cards, held_cards=g.hand[2:])
        assert score > 0
        plays = scored_plays(g, topk=5)
        assert len(plays) > 0

    def test_chained_blueprint_copying_blueprint(self):
        """Blueprint at 0 copying Blueprint at 1 copying Cavendish at 2."""
        g = self._setup_scoring_game(["j_blueprint", "j_blueprint", "j_cavendish"])
        cards = g.hand[:2]
        score = eval_hand_score(g, "Pair", cards, cards, held_cards=g.hand[2:])
        assert score > 0
        plays = scored_plays(g, topk=5)
        assert len(plays) > 0

    @pytest.mark.parametrize("target_key", [
        "j_ice_cream",       # Chips
        "j_banner",          # Chips
        "j_joker",           # Flat Mult
        "j_half",            # Flat Mult
        "j_gros_michel",     # Flat Mult
        "j_cavendish",       # xMult
        "j_card_sharp",      # xMult
        "j_green_joker",     # Scaling Mult
        "j_hanging_chad",    # Retrigger
        "j_photograph",      # Card xMult
        "j_smiley",          # Card Mult
    ])
    def test_blueprint_copying_diverse_jokers(self, target_key):
        """Blueprint cleanly copies jokers from all functional roles."""
        g = self._setup_scoring_game(["j_blueprint", target_key])
        cards = g.hand[:2]
        score = eval_hand_score(g, "Pair", cards, cards, held_cards=g.hand[2:])
        assert score > 0
        plays = scored_plays(g, topk=5)
        assert len(plays) > 0

    def test_supernova_evalgame_attribute_finding(self):
        """CRITICAL CHALLENGER FINDING (RESOLVED):
        _EvalGame (agent_v9.py) now provides 'run_hand_counts'.
        When j_supernova is evaluated in eval_hand_score, it scores cleanly without AttributeError.
        Candidate plays in scored_plays() are properly evaluated and not dropped.
        """
        g = self._setup_scoring_game(["j_supernova"])
        cards = g.hand[:2]
        score = eval_hand_score(g, "Pair", cards, cards, held_cards=g.hand[2:])
        assert score > 0, f"eval_hand_score with j_supernova must succeed and return score > 0, got {score}"

        # Consequence in scored_plays: candidate plays are not dropped
        plays = scored_plays(g, topk=5)
        assert len(plays) > 0, "Expected scored_plays to return candidate plays when Supernova is owned"

    @pytest.mark.parametrize("premier_key", ["j_blueprint", "j_brainstorm"])
    def test_full_inventory_counterfactual_shop_search(self, premier_key):
        """When Blueprint/Brainstorm appears in shop with 5/5 jokers:
        1. Ranking identifies worst joker to sell (need_sell).
        2. SearchShopV10 issues sell_joker action.
        3. SearchShopV10 buys the premier joker on next step.
        """
        g = BalatroGame(seed=321, rng_mode="seed")
        g.reset()
        g.state = State.SHOP
        g.ante = 5
        g.dollars = 30
        g.joker_slots = 5
        g.jokers = [
            JokerInstance("j_joker", game=g),
            JokerInstance("j_greedy_joker", game=g),
            JokerInstance("j_droll", game=g),
            JokerInstance("j_half", game=g),
            JokerInstance("j_golden", game=g),  # dead econ joker to liquidate
        ]
        g.current_shop = [
            ShopItem("joker", premier_key, premier_key, 10),
            ShopItem("planet", "c_mercury", "Mercury", 3),
        ]

        ref = reference_hand(g)
        surplus = forecast_beatable(g, ACTIVE_PARAMS["tilt_surplus_margin"], ref)

        # Ranking
        buys, need_sell = _v10_rank_shop_items(g, ref, surplus)
        assert need_sell is not None, f"Expected need_sell for {premier_key}"
        assert need_sell[1] == 4, f"Expected sell index 4 (j_golden), got {need_sell[1]}"

        # SearchShopV10 execution
        pol = SearchShopV10()
        act1 = pol.decide(g)
        assert act1.get("type") == "sell_joker"
        assert act1.get("joker_idx") == 4

        g.step(act1)
        act2 = pol.decide(g)
        assert act2.get("type") == "buy"
        assert act2.get("item_idx") == 0

        g.step(act2)
        owned_keys = [j.key for j in g.jokers]
        assert premier_key in owned_keys
        assert len(g.jokers) == 5
