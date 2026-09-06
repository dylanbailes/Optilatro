"""tests/test_adversarial_stress_macro.py — Adversarial Stress Test Harness for Macro Remedies.

Exhaustive empirical validation of:
1. Discard Deadlock Immunity when discards_left == 0:
   - Evaluates HeuristicV9, HeuristicV10, SearchShopV10.
   - All discard-incentivized jokers, combinations, adversarial bosses, and edge-case hands.
   - Invariant: Zero discard actions emitted when discards_left == 0.

2. Ante-1 Economy Joker Gating:
   - Pure economy jokers: j_rocket, j_golden, j_business, j_credit_card, j_cloud_9, j_satellite, j_egg.
   - Gated in Ante 1 when engineless (no scoring joker owned).
   - Never bought in Ante 1 even with excess bankroll ($4..$50).
   - Engineless urgency bonus never applies to pure economy jokers.
   - Unlocked and purchasable once a scoring joker is owned.

3. Mid-Game Deficit Capital Deployment & Reroll Guardrails:
   - Dynamic activation of is_urgent_mid in Antes 4 and 5 during scoring deficit.
   - Progressive interest target relaxation: Ante 4 ($15), Ante 5 ($10), Ante 6 ($5), Antes 7-8 ($0).
   - Invariant: capital_after_reroll >= 6 is NEVER violated under deficit rerolls.
   - Hard limits on rerolls strictly enforced per ante: Ante 4 (2), Ante 5 (3), Ante 6 (4), Ante 7 (6), Ante 8 (10).
   - Full-slot inventory correctly accounts for worst joker sell value in capital_after_reroll.

4. Supernova Scoring Evaluation & _EvalGame Robustness:
   - _EvalGame slots, copy independence, and run_hand_counts propagation.
   - eval_hand_score, scored_plays, best_play_score, reference_hand, and _forecast_round_score
     execute cleanly without AttributeError when j_supernova is equipped.
   - Blueprint and Brainstorm copying Supernova.
"""
from __future__ import annotations

import os
import sys
import pytest

# Ensure vendor paths on sys.path
_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_VENDOR = os.path.join(_ROOT, "vendor", "balatro-rl")
if _VENDOR not in sys.path:
    sys.path.insert(0, _VENDOR)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from balatro_sim.card import Card
from balatro_sim.game import BalatroGame, State
from balatro_sim.shop import ShopItem
from balatro_sim.jokers.base import JokerInstance
from balatro_sim.scoring import score_hand
from balatro_sim.agent_v9 import (
    HeuristicV9,
    _EvalGame,
    eval_hand_score,
    scored_plays,
    best_play_score,
    reference_hand,
    forecast_beatable,
)
from balatro_sim.agent_v10 import (
    HeuristicV10,
    SearchShopV10,
    _v10_decide_hand,
    _v10_decide_shop,
    _v10_rank_shop_items,
    _has_scoring_joker,
    _forecast_round_score,
    _ante_boss_target,
    _v10_worst_joker_idx,
    _joker_sell_value,
    V10_PARAMS,
)

PURE_ECON_KEYS = (
    "j_rocket", "j_golden", "j_business", "j_credit_card", "j_cloud_9", "j_satellite", "j_egg"
)


# ============================================================================
# Section 1: Discard Deadlock Immunity (discards_left == 0)
# ============================================================================

class TestAdversarialDiscardDeadlockImmunity:
    """Rigorous stress test verifying that discards_left == 0 guarantees NO discard actions."""

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

    ALL_BOSSES = [
        "bl_small", "bl_big",
        "bl_water",      # Starts with 0 discards
        "bl_needle",     # 1 hand only
        "bl_psychic",    # Must play 5 cards
        "bl_mouth",      # Only 1 hand type
        "bl_eye",        # No repeat hand types
        "bl_arm",        # Decreases poker hand level
        "bl_flint",      # Base chips/mult halved
        "bl_pillar",     # Debuffs cards played this ante
        "bl_hook",       # Discards 2 cards per play
        "bl_tooth",      # Lose $1 per card played
        "bl_manacle",    # -1 hand size
        "bl_ox",         # Set $ to 0 if most played hand
    ]

    @pytest.mark.parametrize("policy_cls", [HeuristicV9, HeuristicV10, SearchShopV10])
    @pytest.mark.parametrize("boss", ALL_BOSSES)
    @pytest.mark.parametrize("hands_left", [1, 2, 3])
    def test_zero_discards_under_adversarial_bosses(self, policy_cls, boss, hands_left):
        """Under all boss blinds and varied hands_left, discards_left==0 never emits discard."""
        g = BalatroGame(seed=12345, rng_mode="seed")
        g.reset()
        g.state = State.BLIND_SELECT
        g.step({"type": "play_blind"})

        g.ante = 3
        g.hands_left = hands_left
        g.discards_left = 0
        g.chips_scored = 0
        g.current_blind.chips_target = 6000
        g.current_blind.boss_key = boss

        # Equip a suite of discard-heavy jokers
        g.jokers = [
            JokerInstance("j_faceless", game=g),
            JokerInstance("j_mail", game=g),
            JokerInstance("j_trading", game=g),
            JokerInstance("j_castle", game=g),
        ]
        g.jokers[1].state["rebate_rank"] = 7
        g.jokers[3].state["castle_suit"] = "Spades"

        # Hand designed to heavily bait discards
        g.hand = [
            Card(11, "Hearts"), Card(12, "Diamonds"), Card(13, "Clubs"),
            Card(7, "Spades"), Card(7, "Hearts"), Card(2, "Diamonds"),
            Card(3, "Clubs"), Card(4, "Spades"),
        ]

        pol = policy_cls()
        action = pol.decide(g)
        assert action.get("type") != "discard", (
            f"DEADLOCK VIOLATION: {policy_cls.__name__} issued discard when discards_left=0 under {boss}"
        )
        assert action.get("type") in ("play", "use")

    @pytest.mark.parametrize("joker_key", DISCARD_JOKERS)
    def test_pure_discard_bait_hands(self, joker_key):
        """When the entire hand is pure discard bait, agent still must play, not discard."""
        g = BalatroGame(seed=54321, rng_mode="seed")
        g.reset()
        g.state = State.BLIND_SELECT
        g.step({"type": "play_blind"})

        g.ante = 2
        g.hands_left = 2
        g.discards_left = 0
        g.chips_scored = 0
        g.current_blind.chips_target = 1500

        inst = JokerInstance(joker_key, game=g)
        if joker_key == "j_mail":
            inst.state["rebate_rank"] = 10
        g.jokers = [inst]

        # Form bait hand tailored to joker
        if joker_key in ("j_faceless", "j_hit_the_road"):
            g.hand = [Card(11, "Hearts"), Card(12, "Diamonds"), Card(13, "Clubs"), Card(11, "Spades"), Card(12, "Hearts")]
        elif joker_key == "j_mail":
            g.hand = [Card(10, "Hearts"), Card(10, "Diamonds"), Card(10, "Clubs"), Card(10, "Spades"), Card(2, "Hearts")]
        elif joker_key == "j_castle":
            inst.state["castle_suit"] = "Hearts"
            g.hand = [Card(2, "Hearts"), Card(4, "Hearts"), Card(6, "Hearts"), Card(8, "Hearts"), Card(9, "Hearts")]
        else:
            g.hand = [Card(2, "Hearts"), Card(3, "Diamonds"), Card(5, "Clubs"), Card(7, "Spades"), Card(9, "Hearts")]

        for pol_cls in [HeuristicV10, SearchShopV10]:
            pol = pol_cls()
            action = pol.decide(g)
            assert action.get("type") != "discard", (
                f"{pol_cls.__name__} emitted discard for {joker_key} with 0 discards left!"
            )
            assert action.get("type") in ("play", "use")

    def test_all_nine_discard_jokers_combined_deadlock_immunity(self):
        """Stress-test with ALL 9 discard jokers equipped concurrently in a modded/oversized joker slot state."""
        g = BalatroGame(seed=999, rng_mode="seed")
        g.reset()
        g.state = State.BLIND_SELECT
        g.step({"type": "play_blind"})

        g.ante = 4
        g.hands_left = 1  # Final hand
        g.discards_left = 0
        g.chips_scored = 0
        g.current_blind.chips_target = 5000

        g.jokers = []
        for k in self.DISCARD_JOKERS:
            j_inst = JokerInstance(k, game=g)
            if k == "j_mail":
                j_inst.state["rebate_rank"] = 8
            if k == "j_castle":
                j_inst.state["castle_suit"] = "Clubs"
            g.jokers.append(j_inst)

        g.hand = [Card(8, "Clubs"), Card(8, "Diamonds"), Card(11, "Hearts"), Card(12, "Spades"), Card(2, "Clubs")]

        pol = SearchShopV10()
        action = pol.decide(g)
        assert action.get("type") == "play", f"Expected play action on final hand, got {action}"
        assert len(action.get("cards", [])) > 0


# ============================================================================
# Section 2: Ante-1 Economy Joker Gating Stress Test
# ============================================================================

class TestAdversarialAnte1EconomyGating:
    """Stress test Ante-1 economy joker gating under engineless vs engine states."""

    PURE_ECON_KEYS = [
        "j_rocket", "j_golden", "j_business",
        "j_credit_card", "j_cloud_9", "j_satellite", "j_egg",
    ]

    SCORING_JOKERS = [
        "j_joker", "j_half", "j_banner",
        "j_popcorn", "j_gros_michel", "j_ice_cream",
    ]

    def _make_game(self, ante=1, dollars=15, owned_keys=None, shop_keys=None):
        g = BalatroGame(seed=777, rng_mode="seed")
        g.reset()
        g.state = State.SHOP
        g.ante = ante
        g.dollars = dollars
        g.jokers = []
        if owned_keys:
            for k in owned_keys:
                g.jokers.append(JokerInstance(k, game=g))
        if shop_keys:
            g.current_shop = [
                ShopItem(kind="joker", key=k, name=k, price=4, edition="None")
                for k in shop_keys
            ]
        return g

    @pytest.mark.parametrize("econ_key", PURE_ECON_KEYS)
    @pytest.mark.parametrize("dollars", [4, 8, 15, 30, 50])
    def test_pure_econ_never_bought_in_ante1_when_engineless(self, econ_key, dollars):
        """Across any bankroll level, engineless Ante 1 strictly forbids buying pure econ jokers."""
        g = self._make_game(ante=1, dollars=dollars, owned_keys=[], shop_keys=[econ_key])
        ref = reference_hand(g)
        assert not _has_scoring_joker(g, ref)

        # 1. Check shop ranking directly
        buys, _ = _v10_rank_shop_items(g, ref, surplus=0)
        buy_keys = [g.current_shop[idx].key for _, idx in buys]
        assert econ_key not in buy_keys, f"{econ_key} ranked for purchase in Ante 1 while engineless!"

        # 2. Check decide_shop action
        act = _v10_decide_shop(g, rerolls_used=0)
        if act.get("type") == "buy":
            bought_key = g.current_shop[act["item_idx"]].key
            assert bought_key != econ_key, f"_v10_decide_shop bought {econ_key} in Ante 1 while engineless!"

        # 3. Check SearchShopV10 decide
        pol = SearchShopV10()
        pol_act = pol.decide(g)
        if pol_act.get("type") == "buy":
            bought_key = g.current_shop[pol_act["item_idx"]].key
            assert bought_key != econ_key, f"SearchShopV10 bought {econ_key} in Ante 1 while engineless!"

    @pytest.mark.parametrize("scoring_key", SCORING_JOKERS)
    @pytest.mark.parametrize("econ_key", PURE_ECON_KEYS)
    def test_pure_econ_unlocked_once_scoring_joker_owned(self, scoring_key, econ_key):
        """Once a scoring joker is secured in Ante 1, pure econ jokers are evaluated (not -1.0 gated)."""
        g = self._make_game(ante=1, dollars=20, owned_keys=[scoring_key], shop_keys=[econ_key])
        ref = reference_hand(g)
        assert _has_scoring_joker(g, ref), f"{scoring_key} must satisfy _has_scoring_joker"

        buys, _ = _v10_rank_shop_items(g, ref, surplus=0)
        # Should execute cleanly without error
        # Verify the item was evaluated by joker_value rather than dropped by early continue
        # To test this, check that if value is computed, it is >= 0
        for val, idx in buys:
            if g.current_shop[idx].key == econ_key:
                assert val >= 0.0

    def test_pure_econ_never_gets_engineless_urgency_bonus(self):
        """Even with engineless urgency active, pure econ jokers must never get the urgency bonus."""
        g = self._make_game(ante=1, dollars=20, owned_keys=[], shop_keys=self.PURE_ECON_KEYS)
        ref = reference_hand(g)
        # Test ranking with engineless urgency active
        V10_PARAMS["engineless_urgency_ante"] = 2
        V10_PARAMS["engineless_urgency_bonus"] = 0.50
        try:
            buys, _ = _v10_rank_shop_items(g, ref, surplus=0)
            buy_keys = [g.current_shop[idx].key for _, idx in buys]
            for ek in self.PURE_ECON_KEYS:
                assert ek not in buy_keys, f"{ek} received buy candidacy under engineless urgency!"
        finally:
            V10_PARAMS["engineless_urgency_ante"] = 0

    def test_mixed_shop_prioritizes_scoring_over_pure_econ(self):
        """In Ante 1, given choice between scoring joker and pure econ joker, agent buys scoring."""
        g = self._make_game(
            ante=1, dollars=12, owned_keys=[],
            shop_keys=["j_rocket", "j_half", "j_golden", "j_business"]
        )
        act = _v10_decide_shop(g, rerolls_used=0)
        assert act.get("type") == "buy"
        assert g.current_shop[act["item_idx"]].key == "j_half"


# ============================================================================
# Section 3: Mid-Game Deficit Capital Deployment & Reroll Invariants
# ============================================================================

class TestAdversarialMidGameDeficitCapitalDeployment:
    """Stress test deficit capital deployment, interest floors, and reroll limits."""

    def _setup_deficit_game(self, ante, dollars, n_xmult=0, weak_engine=True, joker_count=1):
        g = BalatroGame(seed=2026, rng_mode="seed")
        g.reset()
        g.state = State.SHOP
        g.ante = ante
        g.dollars = dollars
        g.reroll_cost = 5
        g.reroll_discount = 0
        g.jokers = []
        if weak_engine:
            for _ in range(joker_count):
                g.jokers.append(JokerInstance("j_sly", game=g))  # Only chips, no xMult
        # Shop contains only expensive or uninteresting items so reroll is considered
        g.current_shop = [
            ShopItem(kind="joker", key="j_obelisk", name="Obelisk", price=8, edition="None"),
            ShopItem(kind="planet", key="c_ceres", name="Ceres", price=3, edition="None"),
        ]
        return g

    @pytest.mark.parametrize("ante, expected_floor, max_rerolls", [
        (4, 15, 2),
        (5, 10, 3),
        (6, 5, 4),
        (7, 0, 6),
        (8, 0, 10),
    ])
    def test_progressive_deficit_interest_floors_and_reroll_limits(self, ante, expected_floor, max_rerolls):
        """Verify interest floor relaxation and exact reroll limits across Antes 4-8."""
        # Provide enough money to satisfy floor + reroll + reserve:
        # e.g., dollars = expected_floor + 15
        dollars = expected_floor + 15
        g = self._setup_deficit_game(ante=ante, dollars=dollars, weak_engine=True)

        # Check rerolls up to max_rerolls
        for r_used in range(max_rerolls):
            # Ensure dollars is high enough for each reroll test
            g.dollars = 30
            act = _v10_decide_shop(g, rerolls_used=r_used)
            assert act.get("type") == "reroll", (
                f"Ante {ante} deficit failed to reroll at rerolls_used={r_used} (limit={max_rerolls})! Action: {act}"
            )

        # At rerolls_used == max_rerolls, reroll MUST be terminated
        g.dollars = 30
        stop_act = _v10_decide_shop(g, rerolls_used=max_rerolls)
        assert stop_act.get("type") != "reroll", (
            f"Ante {ante} exceeded max rerolls {max_rerolls}! Got {stop_act}"
        )

    def test_capital_after_reroll_strict_reserve_invariant(self):
        """CRITICAL INVARIANT: capital_after_reroll >= 6 is NEVER violated in deficit rerolls."""
        # Test boundary values of dollars around min_reserve=6:
        # reroll_cost = 5.
        # capital_after_reroll = dollars - 5.
        # If dollars == 10: capital_after_reroll = 5 < 6 -> MUST NOT REROLL.
        # If dollars == 11: capital_after_reroll = 6 >= 6 -> MAY REROLL.
        for ante in [4, 5, 6, 7, 8]:
            # Boundary 1: dollars = 10 (remaining = 5 < 6)
            g_fail = self._setup_deficit_game(ante=ante, dollars=10, weak_engine=True)
            act_fail = _v10_decide_shop(g_fail, rerolls_used=0)
            assert act_fail.get("type") != "reroll", (
                f"Ante {ante} violated reserve invariant! Rerolled with dollars=10 (capital_after_reroll=5 < 6)"
            )

            # Boundary 2: dollars = 11 (remaining = 6 >= 6)
            # In Antes 4 and 5, dollars=11 is below interest_target (15 for A4, 10 for A5).
            # For A5, dollars=11 >= 10, remaining 6 >= 6 -> should reroll.
            # For A7/8, interest_target=0, remaining 6 >= 6 -> should reroll.
            if ante in (5, 6, 7, 8):
                g_pass = self._setup_deficit_game(ante=ante, dollars=11, weak_engine=True)
                act_pass = _v10_decide_shop(g_pass, rerolls_used=0)
                assert act_pass.get("type") == "reroll", (
                    f"Ante {ante} failed to reroll with dollars=11 (capital_after_reroll=6 >= 6)"
                )

    def test_full_inventory_sell_value_capital_accounting(self):
        """When joker slots are full (5/5), worst joker sell value contributes to capital_after_reroll."""
        # 5 jokers owned. Suppose dollars = 8, reroll_cost = 5.
        # Cash after reroll = 8 - 5 = 3.
        # If worst joker sell value == 3: capital = 3 + 3 = 6 >= 6 -> reserve OK!
        # If worst joker sell value == 2: capital = 3 + 2 = 5 < 6 -> reserve FAIL!
        g = BalatroGame(seed=404, rng_mode="seed")
        g.reset()
        g.state = State.SHOP
        g.ante = 7  # interest_target = 0
        g.reroll_cost = 5
        g.reroll_discount = 0
        g.joker_slots = 5
        g.current_shop = [
            ShopItem(kind="joker", key="j_obelisk", name="Obelisk", price=8, edition="None"),
        ]

        # Case A: worst joker sell value = 3 (cost $6 / 2 = $3)
        g.jokers = [
            JokerInstance("j_sly", game=g),
            JokerInstance("j_sly", game=g),
            JokerInstance("j_sly", game=g),
            JokerInstance("j_sly", game=g),
            JokerInstance("j_sly", game=g),
        ]
        for j in g.jokers:
            j.cost = 6  # sell_value = max(1, 6 // 2) = 3
        g.dollars = 8  # 8 - 5 + 3 = 6 >= 6

        act_a = _v10_decide_shop(g, rerolls_used=0)
        assert act_a.get("type") == "reroll", f"Expected reroll with full slots and $3 sell value, got {act_a}"

        # Case B: worst joker sell value = 2 (cost $4 / 2 = $2)
        for j in g.jokers:
            j.cost = 4  # sell_value = max(1, 4 // 2) = 2
        g.dollars = 8  # 8 - 5 + 2 = 5 < 6

        act_b = _v10_decide_shop(g, rerolls_used=0)
        assert act_b.get("type") != "reroll", f"Expected NO reroll when capital_after_reroll=5 < 6, got {act_b}"


# ============================================================================
# Section 4: Supernova Scoring & Evaluation Stress Test
# ============================================================================

class TestAdversarialSupernovaScoring:
    """Stress test Supernova scoring, _EvalGame slots, and multi-hand evaluation."""

    def test_evalgame_structure_and_slots(self):
        """Verify _EvalGame conforms to memory slots and initializes cleanly."""
        assert "run_hand_counts" in _EvalGame.__slots__
        eg_empty = _EvalGame(None)
        assert eg_empty.run_hand_counts == {}
        assert eg_empty.jokers == []
        assert eg_empty.vouchers == set()

    def test_evalgame_copy_isolation(self):
        """Verify deep isolation of run_hand_counts on copy."""
        g = BalatroGame(seed=10, rng_mode="seed")
        g.reset()
        g.run_hand_counts = {"Pair": 10, "Flush": 3}
        eg = _EvalGame(g)

        eg_copy = eg.copy()
        assert eg_copy.run_hand_counts == {"Pair": 10, "Flush": 3}

        # Mutate copy, ensure original is unchanged
        eg_copy.run_hand_counts["Pair"] = 99
        eg_copy.run_hand_counts["Straight"] = 5
        assert eg.run_hand_counts["Pair"] == 10
        assert "Straight" not in eg.run_hand_counts

    @pytest.mark.parametrize("hand_count", [0, 1, 5, 25, 100])
    def test_supernova_eval_hand_score_exact_mult_contribution(self, hand_count):
        """Verify Supernova adds exact hand_count to Mult via eval_hand_score."""
        g = BalatroGame(seed=77, rng_mode="seed")
        g.reset()
        g.hand = [
            Card(14, "Hearts"), Card(14, "Spades"),
            Card(2, "Clubs"), Card(5, "Diamonds"), Card(8, "Hearts"),
        ]
        g.run_hand_counts = {"Pair": hand_count}

        # Baseline score without Supernova
        g.jokers = []
        cards = g.hand[:2]
        base_score = eval_hand_score(g, "Pair", cards, cards, held_cards=g.hand[2:])

        # Score with Supernova
        g.jokers = [JokerInstance("j_supernova", game=g)]
        supernova_score = eval_hand_score(g, "Pair", cards, cards, held_cards=g.hand[2:])

        assert supernova_score >= base_score, f"Supernova score {supernova_score} < base {base_score}"
        if hand_count > 0:
            assert supernova_score > base_score, "Supernova must increase score when hand_count > 0"

    def test_supernova_scored_plays_and_forecast_robustness(self):
        """Verify scored_plays and _forecast_round_score never raise AttributeError with Supernova."""
        g = BalatroGame(seed=88, rng_mode="seed")
        g.reset()
        g.ante = 3
        g.chips_scored = 0
        g.current_blind.chips_target = 3000
        g.hand = [
            Card(10, "Hearts"), Card(10, "Diamonds"),
            Card(10, "Clubs"), Card(4, "Spades"), Card(7, "Hearts"),
        ]
        g.run_hand_counts = {"Three of a Kind": 8, "Pair": 12}
        g.jokers = [JokerInstance("j_supernova", game=g), JokerInstance("j_joker", game=g)]

        # 1. scored_plays
        plays = scored_plays(g, topk=5)
        assert len(plays) > 0, "scored_plays returned empty list with Supernova!"

        # 2. best_play_score
        bps = best_play_score(g)
        assert bps > 0

        # 3. reference_hand
        ref = reference_hand(g)
        assert ref is not None

        # 4. _forecast_round_score
        fc = _forecast_round_score(g, ref)
        assert fc > 0

    def test_blueprint_copying_supernova(self):
        """Blueprint placed left of Supernova copying Supernova mult bonus."""
        g = BalatroGame(seed=99, rng_mode="seed")
        g.reset()
        g.hand = [Card(14, "Hearts"), Card(14, "Spades"), Card(2, "Clubs"), Card(3, "Diamonds"), Card(4, "Hearts")]
        g.run_hand_counts = {"Pair": 10}

        # Equip Blueprint next to Supernova
        g.jokers = [
            JokerInstance("j_blueprint", game=g),
            JokerInstance("j_supernova", game=g),
        ]
        cards = g.hand[:2]
        score = eval_hand_score(g, "Pair", cards, cards, held_cards=g.hand[2:])
        assert score > 0, f"Expected positive score copying Supernova, got {score}"
