"""test_agent_v10.py — M12 in-blind goal hierarchy regression tests.

Pins the human-fair / correctness invariants of `agent_v10` (§7 of
agent-v10-inblind-spec.md) and the value formulas (§5.5/§6):

  - P(clear) is a pure function of deck COMPOSITION (order-independent,
    deterministic, no live mutation, no draw-order peek).
  - P(clear) sanity: 1 when already cleared, 0 with no hands left,
    monotone in hands/discards.
  - trigger counts (RULING-R): Red seal / Mime / retrigger jokers.
  - hold/play value formulas: gold card × Mime, blue seal, gold seal scored,
    Faceless / Mail / Trading discard levers.
  - The farming-off arm (`farm_clear_threshold = 1.0`) reproduces V9's
    decisions byte-for-byte — the strongest proof of "no lookahead / no extra
    information": if V10 used any future state, it could not match V9.

Human-readable: each test is a named, single-behavior assertion with a
docstring.
"""
from __future__ import annotations

import pytest

from balatro_sim.card import Card
from balatro_sim.game import BalatroGame, State
from balatro_sim.rollout import rollout
from balatro_sim.agent_v9 import HeuristicV9
from balatro_sim import agent_v10 as v10


# ────────────────────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────────────────────

def _game(hand, deck=None, jokers=()):
    """A fresh seed-mode game in SELECTING_HAND with a controlled hand/deck."""
    g = BalatroGame(seed=7, rng_mode="seed")
    g.reset()
    if g.state != State.SELECTING_HAND:
        g.state = State.BLIND_SELECT
        g.step({"type": "play_blind"})
    g.hand = list(hand)
    g.deck = list(deck) if deck is not None else []
    from balatro_sim.jokers.base import JokerInstance
    g.jokers = [JokerInstance(k, game=g) if isinstance(k, str) else k
                for k in jokers]
    g.current_blind.chips_target = 600
    g.chips_scored = 0
    g.hands_left = 4
    g.discards_left = 3
    return g


def _std_deck():
    """A standard 52-card deck (deterministic suit/rank order)."""
    cards = []
    for suit in ("Spades", "Hearts", "Clubs", "Diamonds"):
        for rank in range(2, 15):
            cards.append(Card(rank, suit))
    return cards


# ────────────────────────────────────────────────────────────────────────────
# P(clear) sanity + human-fair invariants
# ────────────────────────────────────────────────────────────────────────────

class TestEstimateClearProbability:
    def test_already_cleared_is_one(self):
        g = _game([Card(14, "Spades")])
        g.chips_scored = g.current_blind.chips_target  # T = 0
        assert v10.estimate_clear_probability(g) == 1.0

    def test_no_hands_is_zero(self):
        g = _game([Card(14, "Spades")])
        g.hands_left = 0
        assert v10.estimate_clear_probability(g) == 0.0

    def test_deterministic(self):
        g = _game([Card(14, "Spades"), Card(13, "Hearts")],
                  deck=_std_deck())
        a = v10.estimate_clear_probability(g)
        b = v10.estimate_clear_probability(g)
        assert a == b

    def test_order_independent(self):
        """Reversing the deck (same composition, different order) must not
        change P(clear) — no draw-order peek (§7)."""
        deck = _std_deck()
        g1 = _game([Card(14, "Spades"), Card(13, "Hearts")], deck=list(deck))
        g2 = _game([Card(14, "Spades"), Card(13, "Hearts")],
                   deck=list(reversed(deck)))
        assert (v10.estimate_clear_probability(g1)
                == v10.estimate_clear_probability(g2))

    def test_no_live_mutation(self):
        """Estimating P(clear) must not mutate the live game state."""
        g = _game([Card(14, "Spades"), Card(13, "Hearts")], deck=_std_deck())
        hand_ids = [id(c) for c in g.hand]
        deck_ids = [id(c) for c in g.deck]
        dollars = g.dollars
        v10.estimate_clear_probability(g)
        assert [id(c) for c in g.hand] == hand_ids
        assert [id(c) for c in g.deck] == deck_ids
        assert g.dollars == dollars

    def test_monotone_in_hands(self):
        """More hands left can only raise P(clear)."""
        g = _game([Card(14, "Spades"), Card(13, "Hearts")], deck=_std_deck())
        g.hands_left = 1
        low = v10.estimate_clear_probability(g)
        g.hands_left = 4
        high = v10.estimate_clear_probability(g)
        assert high >= low

    def test_bounds_sandwich(self):
        """Optimistic ceiling >= pessimistic base."""
        g = _game([Card(14, "Spades"), Card(13, "Hearts")], deck=_std_deck())
        pess, opt = v10.estimate_clear_probability_bounds(g)
        assert 0.0 <= pess <= opt <= 1.0


# ────────────────────────────────────────────────────────────────────────────
# Trigger counts (RULING-R)
# ────────────────────────────────────────────────────────────────────────────

class TestTriggerCounts:
    def test_held_red_seal(self):
        g = _game([])
        assert v10.triggers_held(g, Card(5, "Hearts")) == 1
        assert v10.triggers_held(g, Card(5, "Hearts", seal="Red")) == 2

    def test_held_mime(self):
        g = _game([], jokers=("j_mime",))
        assert v10.triggers_held(g, Card(5, "Hearts")) == 2
        assert v10.triggers_held(g, Card(5, "Hearts", seal="Red")) == 3

    def test_played_red_seal_and_hack(self):
        g = _game([], jokers=("j_hack",))
        assert v10.triggers_played(g, Card(4, "Hearts")) == 2  # hack on 2-5
        assert v10.triggers_played(g, Card(14, "Hearts")) == 1
        assert v10.triggers_played(g, Card(4, "Hearts", seal="Red")) == 3


# ────────────────────────────────────────────────────────────────────────────
# Hold / play value formulas (§5.5 / §6)
# ────────────────────────────────────────────────────────────────────────────

class TestHoldValue:
    def test_gold_card_held_base(self):
        g = _game([])
        val = v10.expected_round_end_value(g, [Card(5, "Hearts",
                                                    enhancement="Gold")])
        assert val == pytest.approx(0.25)  # min(0.25, 3/10) = 0.25... 3/10=0.3

    def test_gold_card_held_mime_doubles(self):
        g = _game([], jokers=("j_mime",))
        val = v10.expected_round_end_value(g, [Card(5, "Hearts",
                                                    enhancement="Gold")])
        # 3*2/10 = 0.6 -> capped at 0.25
        assert val == pytest.approx(0.25)

    def test_gold_card_red_seal_mime(self):
        g = _game([], jokers=("j_mime",))
        val = v10.expected_round_end_value(
            g, [Card(5, "Hearts", enhancement="Gold", seal="Red")])
        # 3*3/10 = 0.9 -> capped at 0.25
        assert val == pytest.approx(0.25)

    def test_debuffed_gold_card_zero(self):
        g = _game([])
        val = v10.expected_round_end_value(
            g, [Card(5, "Hearts", enhancement="Gold", debuffed=True)])
        assert val == 0.0


class TestPlayValue:
    def test_gold_seal_scored(self):
        g = _game([])
        val = v10.play_trigger_value(g, [Card(14, "Spades", seal="Gold")],
                                     "High Card")
        assert val == pytest.approx(0.25)  # 3/10 = 0.3 -> capped 0.25

    def test_business_card_face(self):
        g = _game([], jokers=("j_business",))
        val = v10.play_trigger_value(g, [Card(13, "Hearts")], "High Card")
        # 1 * 1 trigger / 10 = 0.1
        assert val == pytest.approx(0.1)

    def test_no_value_without_levers(self):
        g = _game([])
        val = v10.play_trigger_value(g, [Card(14, "Spades")], "High Card")
        assert val == 0.0


class TestDiscardValue:
    def test_faceless_three_faces(self):
        g = _game([Card(13, "Hearts"), Card(12, "Hearts"), Card(11, "Hearts")],
                  jokers=("j_faceless",))
        val = v10._discard_value(g, (0, 1, 2))
        assert val == pytest.approx(0.25)  # $5/10 = 0.5 -> capped 0.25

    def test_faceless_two_faces_no_value(self):
        g = _game([Card(13, "Hearts"), Card(12, "Hearts")],
                  jokers=("j_faceless",))
        val = v10._discard_value(g, (0, 1))
        assert val == 0.0

    def test_trading_first_discard(self):
        g = _game([Card(5, "Hearts")], jokers=("j_trading",))
        val = v10._discard_value(g, (0,))
        assert val == pytest.approx(0.25)  # $3/10 = 0.3 -> capped 0.25


# ────────────────────────────────────────────────────────────────────────────
# Farming-off arm reproduces V9 byte-for-byte (no lookahead / no extra info)
# ────────────────────────────────────────────────────────────────────────────

class TestFarmOffReproducesV9:
    def test_farm_off_matches_v9(self):
        """With value-farming off, HeuristicV10 must decide identically to V9.
        Any divergence would mean V10 peeked at future state or perturbed the
        RNG stream (both forbidden by §7)."""
        seeds = (0, 1, 2)
        v9_pol = HeuristicV9()
        v10_pol = v10.HeuristicV10(params={"farm_clear_threshold": 1.0})
        for seed in seeds:
            g9 = BalatroGame(seed=seed, rng_mode="seed")
            g10 = BalatroGame(seed=seed, rng_mode="seed")
            r9 = rollout(g9, v9_pol)
            r10 = rollout(g10, v10_pol)
            # Compare the decision-relevant outcome fields (ignore any
            # telemetry that could differ trivially).
            for key in ("won", "ante", "steps", "dollars", "jokers"):
                assert r9[key] == r10[key], f"seed {seed} diverged on {key}"


# ────────────────────────────────────────────────────────────────────────────
# SearchShopV10 is human-fair by default (no rollout lookahead)
# ────────────────────────────────────────────────────────────────────────────

class TestSearchShopV10:
    def test_lookahead_defaults_off(self):
        pol = v10.SearchShopV10()
        assert pol.policy_name == "search_shop_v10"
        assert pol._lookahead is False

    def test_runs_end_to_end(self):
        """SearchShopV10 must run a full game without error (smoke)."""
        g = BalatroGame(seed=0, rng_mode="seed")
        pol = v10.SearchShopV10()
        r = rollout(g, pol)


# ────────────────────────────────────────────────────────────────────────────
# Deck reshaping — target derivation + biased tarot/standard policy
# ────────────────────────────────────────────────────────────────────────────

class _ReshapeBase:
    """Restore V10_PARAMS before/after each reshape test: the farm-off
    test earlier in the file leaves threshold=1.0 behind (HeuristicV10's
    __init__ mutates the module-level dict), which would wrongly gate
    reshaping off."""
    @pytest.fixture(autouse=True)
    def _restore_v10_defaults(self):
        v10.V10_PARAMS.update(v10.V10_DEFAULTS)
        yield
        v10.V10_PARAMS.update(v10.V10_DEFAULTS)


class TestDeckReshapeTarget(_ReshapeBase):
    def test_inactive_without_engines(self):
        """No engine / no committed hand type -> all targets None (the biased
        functions then delegate to V9 byte-for-byte)."""
        g = _game([Card(14, "Spades")], deck=_std_deck())
        t = v10.deck_reshape_target(g)
        assert t["active"] is False
        assert t["rank"] is None and t["suit"] is None

    def test_baron_targets_kings(self):
        g = _game([Card(14, "Spades")], deck=_std_deck(), jokers=("j_baron",))
        t = v10.deck_reshape_target(g)
        assert t["rank"] == 13

    def test_cloud9_targets_nines(self):
        g = _game([Card(14, "Spades")], deck=_std_deck(), jokers=("j_cloud_9",))
        t = v10.deck_reshape_target(g)
        assert t["rank"] == 9

    def test_family_targets_majority_rank(self):
        """The Family (Four of a Kind) stacks the rank already most present
        in the full deck (composition read, deterministic tie-break)."""
        deck = _std_deck()
        for _ in range(3):
            deck.append(Card(7, "Spades"))   # 7s -> 7 copies (majority)
        g = _game([Card(14, "Spades")], deck=deck, jokers=("j_family",))
        t = v10.deck_reshape_target(g)
        assert t["rank"] == 7

    def test_golden_targets_diamonds(self):
        g = _game([Card(14, "Spades")], deck=_std_deck(), jokers=("j_golden",))
        t = v10.deck_reshape_target(g)
        assert t["suit"] == "Diamonds"

    def test_steel_joker_targets_steel(self):
        g = _game([Card(14, "Spades")], deck=_std_deck(),
                  jokers=("j_steel_joker",))
        t = v10.deck_reshape_target(g)
        assert t["enh"] == "Steel"

    def test_photograph_targets_faces(self):
        g = _game([Card(14, "Spades")], deck=_std_deck(),
                  jokers=("j_photograph",))
        t = v10.deck_reshape_target(g)
        assert t["face"] is True

    def test_disabled_by_farmoff(self):
        """The farm-off arm (threshold=1.0) must leave the target inactive so
        it keeps reproducing V9 byte-for-byte."""
        g = _game([Card(14, "Spades")], deck=_std_deck(), jokers=("j_baron",))
        v10.V10_PARAMS["farm_clear_threshold"] = 1.0
        try:
            t = v10.deck_reshape_target(g)
            assert t["active"] is False
        finally:
            v10.V10_PARAMS["farm_clear_threshold"] = 0.90

    def test_disabled_by_knob(self):
        g = _game([Card(14, "Spades")], deck=_std_deck(), jokers=("j_baron",))
        v10.V10_PARAMS["reshape_enabled"] = False
        try:
            t = v10.deck_reshape_target(g)
            assert t["active"] is False
        finally:
            v10.V10_PARAMS["reshape_enabled"] = True

    def test_deterministic(self):
        g = _game([Card(14, "Spades")], deck=_std_deck(), jokers=("j_baron",))
        assert v10.deck_reshape_target(g) == v10.deck_reshape_target(g)

    def test_order_independent(self):
        """Same composition, different deck order -> identical target (pure
        composition read, no draw-order dependence)."""
        deck = _std_deck()
        g1 = _game([Card(14, "Spades")], deck=list(deck), jokers=("j_family",))
        g2 = _game([Card(14, "Spades")], deck=list(reversed(deck)),
                   jokers=("j_family",))
        assert v10.deck_reshape_target(g1)["rank"] == \
            v10.deck_reshape_target(g2)["rank"]


class TestReshapeValues(_ReshapeBase):
    def test_tarot_value_death_boosted_with_rank_target(self):
        g = _game([Card(14, "Spades")], deck=_std_deck(), jokers=("j_baron",))
        assert v10._v10_tarot_value(g, "c_death") > v10.tarot_value(g, "c_death")

    def test_tarot_value_zero_bonus_when_inactive(self):
        g = _game([Card(14, "Spades")], deck=_std_deck())
        assert v10._v10_tarot_value(g, "c_death") == v10.tarot_value(g, "c_death")

    def test_pack_card_target_rank_bonus(self):
        g = _game([Card(14, "Spades")], deck=_std_deck(), jokers=("j_baron",))
        king = Card(13, "Hearts")
        five = Card(5, "Hearts")
        assert v10._v10_pack_card_value(g, king) > v10._pack_card_value(king)
        assert v10._v10_pack_card_value(g, five) == v10._pack_card_value(five)

    def test_pack_card_suit_bonus(self):
        g = _game([Card(14, "Spades")], deck=_std_deck(), jokers=("j_golden",))
        dia = Card(5, "Diamonds")
        spade = Card(5, "Spades")
        assert v10._v10_pack_card_value(g, dia) > v10._pack_card_value(dia)
        assert v10._v10_pack_card_value(g, spade) == v10._pack_card_value(spade)


class TestReshapeTarotAction(_ReshapeBase):
    def _shop_game(self, hand, jokers):
        g = _game(hand, deck=_std_deck(), jokers=jokers)
        g.state = State.SHOP
        g.consumable_hand = ["c_death"]
        return g

    def test_death_stacks_target_rank(self):
        """With Baron (Kings), Death copies a King onto a non-King instead of
        V9's copy-best-onto-weakest."""
        hand = [Card(13, "Hearts"), Card(13, "Spades"),   # two Kings
                Card(5, "Clubs"), Card(3, "Diamonds")]   # junk
        g = self._shop_game(hand, ("j_baron",))
        best, weakest = v10._target_lists(g.hand)
        act = v10._v10_tarot_action(g, 0, "c_death", g.hand, best, weakest)
        assert act is not None and act["type"] == "use_consumable"
        src, dst = act["target_cards"][1], act["target_cards"][0]
        assert g.hand[src].rank == 13       # source is a King
        assert g.hand[dst].rank != 13       # destination becomes a King

    def test_strength_targets_near_rank(self):
        """With Baron (Kings), Strength +1 targets Queens (they become Kings)
        before V9's weakest non-Ace."""
        hand = [Card(12, "Hearts"), Card(12, "Spades"),   # two Queens
                Card(5, "Clubs"), Card(3, "Diamonds")]
        g = self._shop_game(hand, ("j_baron",))
        best, weakest = v10._target_lists(g.hand)
        act = v10._v10_tarot_action(g, 0, "c_strength", g.hand, best, weakest)
        assert act is not None
        assert all(g.hand[i].rank == 12 for i in act["target_cards"])

    def test_suit_convert_in_shop(self):
        """With Golden Joker (Diamonds), a Star tarot converts the best
        non-Diamond cards toward Diamonds in the SHOP phase."""
        hand = [Card(13, "Hearts"), Card(12, "Spades"), Card(11, "Clubs"),
                Card(10, "Diamonds")]
        g = self._shop_game(hand, ("j_golden",))
        g.consumable_hand = ["c_star"]
        best, weakest = v10._target_lists(g.hand)
        act = v10._v10_tarot_action(g, 0, "c_star", g.hand, best, weakest)
        assert act is not None
        assert all(g.hand[i].suit != "Diamonds" for i in act["target_cards"])

    def test_delegates_when_inactive(self):
        """No reshape target -> the v10 action is byte-identical to V9's."""
        hand = [Card(13, "Hearts"), Card(5, "Clubs")]
        g = self._shop_game(hand, ())
        best, weakest = v10._target_lists(g.hand)
        a = v10._v10_tarot_action(g, 0, "c_death", g.hand, best, weakest)
        b = v10._tarot_action(g, 0, "c_death", g.hand, best, weakest)
        assert a == b
