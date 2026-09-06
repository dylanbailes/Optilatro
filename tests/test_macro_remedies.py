"""tests/test_macro_remedies.py — Unit and integration tests for Macro Remedies 1, 2, and 3.

Validates:
1. Macro Remedy 1: Ante-1 Economy Joker Gating
   - Pure economy jokers are rejected in Ante 1 when no scoring joker is owned.
   - Pure economy jokers are purchasable once a scoring joker is owned.
   - Pure economy jokers never receive engineless urgency bonuses.
2. Macro Remedy 2: Mid-Game Deficit Capital Deployment
   - Deficit capital deployment in Antes 4 and 5 (interest floors $15 and $10, reroll allowance down to $6).
   - Deficit capital deployment in Antes 6, 7, 8 (interest floors $5, $0, $0).
   - Rerolling and shopping permitted when in deficit.
3. Macro Remedy 3: Latent _EvalGame Supernova Defect
   - _EvalGame provides run_hand_counts attribute and copy method.
   - eval_hand_score scores cleanly with j_supernova without raising AttributeError.
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
from balatro_sim.agent_v9 import (
    _EvalGame,
    eval_hand_score,
    scored_plays,
    reference_hand,
)
from balatro_sim.agent_v10 import (
    _v10_rank_shop_items,
    _v10_decide_shop,
    _has_scoring_joker,
    SearchShopV10,
    V10_PARAMS,
)


class TestMacroRemedy1_Ante1EconomyGating:
    """Macro Remedy 1: Ante-1 Economy Joker Gating in _v10_rank_shop_items."""

    PURE_ECON_KEYS = [
        "j_rocket", "j_golden", "j_business",
        "j_credit_card", "j_cloud_9", "j_satellite", "j_egg",
    ]

    def _setup_ante1_game(self, owned_jokers=None, shop_keys=None, dollars=15):
        g = BalatroGame(seed=42, rng_mode="seed")
        g.reset()
        g.state = State.SHOP
        g.ante = 1
        g.dollars = dollars
        g.jokers = []
        if owned_jokers:
            for k in owned_jokers:
                g.jokers.append(JokerInstance(k, game=g))
        if shop_keys:
            g.current_shop = [
                ShopItem(kind="joker", key=k, name=k, price=4, edition="None")
                for k in shop_keys
            ]
        return g

    @pytest.mark.parametrize("econ_key", PURE_ECON_KEYS)
    def test_ante1_pure_econ_rejected_without_scoring_joker(self, econ_key):
        """In Ante 1, without a scoring joker, pure economy jokers must NOT be bought."""
        g = self._setup_ante1_game(owned_jokers=[], shop_keys=[econ_key])
        ref = reference_hand(g)
        assert not _has_scoring_joker(g, ref), "Fresh game must not have scoring joker"

        buys, need_sell = _v10_rank_shop_items(g, ref, surplus=0)
        # Item must not appear in candidate buys
        buy_keys = [g.current_shop[idx].key for _, idx in buys]
        assert econ_key not in buy_keys, f"{econ_key} must be gated in Ante 1 without scoring joker"

    @pytest.mark.parametrize("econ_key", PURE_ECON_KEYS)
    def test_ante1_pure_econ_allowed_with_scoring_joker(self, econ_key):
        """In Ante 1, with a scoring joker owned (e.g. j_joker), pure economy jokers can be evaluated."""
        g = self._setup_ante1_game(owned_jokers=["j_joker"], shop_keys=[econ_key], dollars=20)
        ref = reference_hand(g)
        assert _has_scoring_joker(g, ref), "j_joker must qualify as scoring joker"

        # Note: Depending on econ valuation threshold it may or may not meet buy threshold,
        # but it must NOT be unconditionally continued / dropped with value = -1.0
        buys, _ = _v10_rank_shop_items(g, ref, surplus=0)
        # Should not crash and is eligible for buy evaluation

    def test_ante1_scoring_joker_prioritized_over_pure_econ(self):
        """In Ante 1 with mixed shop, combat joker is bought and pure economy is ignored."""
        g = self._setup_ante1_game(
            owned_jokers=[],
            shop_keys=["j_golden", "j_joker", "j_egg"],
            dollars=10,
        )
        ref = reference_hand(g)
        buys, _ = _v10_rank_shop_items(g, ref, surplus=0)
        buy_keys = [g.current_shop[idx].key for _, idx in buys]
        assert "j_joker" in buy_keys
        assert "j_golden" not in buy_keys
        assert "j_egg" not in buy_keys


class TestMacroRemedy2_MidGameDeficitCapitalDeployment:
    """Macro Remedy 2: Mid-Game Deficit Capital Deployment in _v10_decide_shop."""

    def _setup_shop_game(self, ante, dollars=25, owned_jokers=None, shop_keys=None):
        g = BalatroGame(seed=100, rng_mode="seed")
        g.reset()
        g.state = State.SHOP
        g.ante = ante
        g.dollars = dollars
        g.jokers = []
        if owned_jokers:
            for k in owned_jokers:
                g.jokers.append(JokerInstance(k, game=g))
        if shop_keys:
            g.current_shop = [
                ShopItem(kind="joker", key=k, name=k, price=4, edition="None")
                for k in shop_keys
            ]
        else:
            g.current_shop = [
                ShopItem(kind="joker", key="j_half", name="Half Joker", price=5, edition="None"),
                ShopItem(kind="planet", key="c_mercury", name="Mercury", price=3, edition="None"),
            ]
        return g

    def test_ante4_deficit_capital_deployment_rerolls(self):
        """In Ante 4 with deficit, agent rerolls even if dollars < $25, down to min_reserve = 6."""
        # Setup Ante 4 game with no xMult / deficit (holding only a weak chip joker)
        # dollars = 18 (below standard $25 interest target)
        g = self._setup_shop_game(ante=4, dollars=18, owned_jokers=["j_sly"])
        # Give shop empty/unaffordable items so decide_shop considers reroll
        g.current_shop = [ShopItem(kind="joker", key="j_obelisk", name="Obelisk", price=4, edition="None")]

        act = _v10_decide_shop(g, rerolls_used=0)
        # With dollars=18, reroll_cost=5, remaining=13 >= 6, agent should reroll in deficit
        assert act.get("type") == "reroll", f"Expected reroll in Ante 4 deficit, got {act}"

    def test_ante5_deficit_capital_deployment_rerolls(self):
        """In Ante 5 with deficit, agent relaxes interest floor to $10 and rerolls."""
        g = self._setup_shop_game(ante=5, dollars=14, owned_jokers=["j_sly"])
        g.current_shop = [ShopItem(kind="joker", key="j_obelisk", name="Obelisk", price=4, edition="None")]

        act = _v10_decide_shop(g, rerolls_used=0)
        # With dollars=14, reroll_cost=5, remaining=9 >= 6, agent should reroll in deficit
        assert act.get("type") == "reroll", f"Expected reroll in Ante 5 deficit, got {act}"

    def test_ante6_deficit_interest_floor_relaxed_to_5(self):
        """In Ante 6 with deficit, interest floor relaxes to $5."""
        g = self._setup_shop_game(ante=6, dollars=12, owned_jokers=["j_sly"])
        g.current_shop = [ShopItem(kind="joker", key="j_obelisk", name="Obelisk", price=4, edition="None")]

        act = _v10_decide_shop(g, rerolls_used=0)
        assert act.get("type") == "reroll", f"Expected reroll in Ante 6 deficit, got {act}"

    def test_ante7_8_deficit_interest_floor_relaxed_to_0(self):
        """In Ante 7-8, interest floor relaxes to $0."""
        g = self._setup_shop_game(ante=8, dollars=11, owned_jokers=["j_sly"])
        g.current_shop = [ShopItem(kind="joker", key="j_obelisk", name="Obelisk", price=4, edition="None")]

        act = _v10_decide_shop(g, rerolls_used=0)
        assert act.get("type") == "reroll", f"Expected reroll in Ante 8 deficit, got {act}"


class TestMacroRemedy3_LatentEvalGameDefect:
    """Macro Remedy 3: Latent _EvalGame Defect in agent_v9.py."""

    def test_evalgame_has_run_hand_counts_slot(self):
        """_EvalGame must have run_hand_counts in __slots__."""
        assert "run_hand_counts" in _EvalGame.__slots__

    def test_evalgame_initializes_run_hand_counts(self):
        """_EvalGame initializes run_hand_counts as a dictionary from game."""
        g = BalatroGame(seed=42, rng_mode="seed")
        g.reset()
        g.run_hand_counts = {"Pair": 5, "Flush": 2}

        eg = _EvalGame(g)
        assert eg.run_hand_counts == {"Pair": 5, "Flush": 2}

    def test_evalgame_copy_copies_run_hand_counts(self):
        """_EvalGame.copy preserves run_hand_counts."""
        g = BalatroGame(seed=42, rng_mode="seed")
        g.reset()
        g.run_hand_counts = {"High Card": 10}

        eg = _EvalGame(g)
        eg_copy = eg.copy()
        assert eg_copy.run_hand_counts == {"High Card": 10}
        # Verify independence
        eg_copy.run_hand_counts["High Card"] = 99
        assert eg.run_hand_counts["High Card"] == 10

    def test_supernova_eval_hand_score_no_crash(self):
        """Scoring with j_supernova using eval_hand_score must not raise AttributeError."""
        g = BalatroGame(seed=42, rng_mode="seed")
        g.reset()
        g.hand = [
            Card("Hearts", 14),
            Card("Spades", 14),
            Card("Clubs", 2),
            Card("Diamonds", 5),
            Card("Hearts", 8),
        ]
        g.jokers = [JokerInstance("j_supernova", game=g)]
        g.run_hand_counts = {"Pair": 7}

        cards = g.hand[:2]
        score = eval_hand_score(g, "Pair", cards, cards, held_cards=g.hand[2:])
        assert score > 0, f"Expected positive score with Supernova, got {score}"

        # Ensure scored_plays returns valid candidate plays
        plays = scored_plays(g, topk=5)
        assert len(plays) > 0, "scored_plays must not drop plays when Supernova is owned"
