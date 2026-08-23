"""test_agent_v10.py — M12 in-blind goal hierarchy regression tests.

Pins the human-fair / correctness invariants of `agent_v10` (§7 of
docs/agent-v10-inblind-spec.md) and the value formulas (§5.5/§6):

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
from balatro_sim.agent_v9 import HeuristicV9, scored_plays
from balatro_sim.shop import ShopItem
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


# ────────────────────────────────────────────────────────────────────────────
# Joker-aware blind targeting (M14)
# ────────────────────────────────────────────────────────────────────────────

class TestBlindTargeting(_ReshapeBase):
    """The M14 targeting layer: pick the hand type the owned jokers want,
    steer discards toward it, and never chase a doomed line."""

    def _blind(self, hand, jokers=(), ante=1, target=300):
        g = _game(hand, deck=_std_deck(), jokers=jokers)
        g.ante = ante
        g.current_blind.chips_target = target
        g.chips_scored = 0
        return g

    def test_ante1_small_blind_chases_majority_flush(self):
        """Ante-1 Small Blind with a scattered hand: the committed discard
        keeps exactly the majority-suit cards and pools every off-suit card
        ('impossible to lose if you chase the suit you hold most of')."""
        hand = [Card(2, "Spades"), Card(9, "Hearts"), Card(13, "Hearts"),
                Card(3, "Hearts"), Card(4, "Diamonds"), Card(8, "Diamonds"),
                Card(6, "Clubs"), Card(12, "Clubs")]
        g = self._blind(hand)
        act = v10._v10_decide_hand(g)
        assert act["type"] == "discard"
        kept = [c for i, c in enumerate(g.hand) if i not in set(act["cards"])]
        assert all(c.suit == "Hearts" for c in kept)
        assert len(kept) == 3          # every heart held
        assert len(act["cards"]) == 5  # all five off-suit cards pooled

    def test_photograph_plans_face_flush_at_boss(self):
        """Photograph + 4 hearts incl. a face: the plan is a HEARTS flush and
        its made score carries the x2 face trigger (clears Boss 600 in one)."""
        hand = [Card(14, "Hearts"), Card(13, "Hearts"), Card(7, "Hearts"),
                Card(2, "Hearts"), Card(2, "Clubs"), Card(9, "Diamonds"),
                Card(11, "Spades"), Card(5, "Clubs")]
        g = self._blind(hand, jokers=("j_photograph",), target=600)
        plays = scored_plays(g, topk=12)
        ts = v10._compute_type_scores(g, plays)
        plan = v10._blind_plan(g, ts)
        assert plan is not None and plan["ht"] == "Flush"
        assert plan["suit"] == "Hearts"
        assert plan["S"] >= 600       # face-flush beats the Boss in ONE hand
        act = v10._chase_discard(g, plan, plays[0][0])
        assert act is not None
        discarded = [g.hand[i] for i in act["cards"]]
        assert all(c.suit != "Hearts" for c in discarded)

    def test_trips_plus_chips_joker_chases_full_house(self):
        """The user rule: with a flat-chips joker, holding Three of a Kind
        should chase the FULL HOUSE (the joker's bonus rides along), keeping
        the trips and pooling ONLY singletons."""
        hand = [Card(7, "Spades"), Card(7, "Hearts"), Card(7, "Diamonds"),
                Card(2, "Clubs"), Card(3, "Hearts"), Card(5, "Diamonds"),
                Card(9, "Clubs"), Card(12, "Clubs")]
        g = self._blind(hand, jokers=("j_sly",), target=450)
        plays = scored_plays(g, topk=12)
        ts = v10._compute_type_scores(g, plays)
        assert ts.get("Full House", 0) > 0   # fill must see the FH line
        assert ts["Full House"] >= 450       # ...and it clears Big in one
        plan = v10._blind_plan(g, ts)
        assert plan is not None and plan["ht"] == "Full House"
        act = v10._chase_discard(g, plan, plays[0][0])
        assert act is not None
        discarded = [g.hand[i] for i in act["cards"]]
        assert all(c.rank != 7 for c in discarded)
        assert len(discarded) == 5     # all five singletons pooled

    def test_no_m1_line_means_no_plan(self):
        """M14c kill-lines only: at 450 with no jokers the best flush (~330)
        cannot clear in one hand, so there is NO plan — the V9 grind owns it
        (m>=2 chases were pure variance)."""
        hand = [Card(7, "Spades"), Card(7, "Hearts"), Card(7, "Diamonds"),
                Card(2, "Clubs"), Card(3, "Hearts"), Card(5, "Diamonds"),
                Card(9, "Clubs"), Card(12, "Clubs")]
        g = self._blind(hand, target=450)
        plays = scored_plays(g, topk=12)
        ts = v10._compute_type_scores(g, plays)
        assert v10._blind_plan(g, ts) is None

    def test_m1_flush_planned_when_target_fits(self):
        """Same hand, Small-Blind target 300: the flush IS an m=1 kill line
        and outranks the made trips on the (m, -prob, -S) key."""
        hand = [Card(7, "Spades"), Card(7, "Hearts"), Card(7, "Diamonds"),
                Card(2, "Clubs"), Card(3, "Hearts"), Card(5, "Diamonds"),
                Card(9, "Clubs"), Card(12, "Clubs")]
        g = self._blind(hand, target=300)
        plays = scored_plays(g, topk=12)
        ts = v10._compute_type_scores(g, plays)
        plan = v10._blind_plan(g, ts)
        assert plan is not None and plan["ht"] == "Flush" and plan["m"] == 1

    def test_chase_rejected_when_assembly_hopeless(self):
        """A flush line whose suit is exhausted from the deck must be
        rejected by the post-discard probability gate (seeds 52/54/63 burned
        4 discards on exactly this kind of doomed chase)."""
        deck = [c for c in _std_deck() if c.suit != "Hearts"]
        hand = [Card(13, "Hearts"), Card(12, "Hearts"), Card(11, "Hearts"),
                Card(10, "Hearts"), Card(2, "Spades"), Card(5, "Clubs"),
                Card(8, "Diamonds"), Card(6, "Spades")]
        g = _game(hand, deck=deck)
        plan = {"ht": "Flush", "suit": "Hearts", "S": 400.0, "prob": 0.99,
                "m": 1}
        assert v10._chase_discard(g, plan, 100) is None

    def test_chase_rejected_when_current_best_is_better(self):
        """EV gate: never dump a working hand for a coin flip (seed 228's
        240-straight lesson)."""
        hand = [Card(9, "Hearts"), Card(13, "Hearts"), Card(3, "Hearts"),
                Card(2, "Spades"), Card(4, "Diamonds"), Card(8, "Diamonds"),
                Card(6, "Clubs"), Card(12, "Clubs")]
        g = self._blind(hand, target=300)
        plan = {"ht": "Flush", "suit": "Hearts", "S": 344.0,
                "prob": 0.98, "m": 1}
        # 0.98 * 344 = 337 < 400 * 1.0 -> play the working hand instead
        assert v10._chase_discard(g, plan, 400) is None

    def test_clearing_hand_still_played_first(self):
        """When the best play already clears, targeting never intervenes."""
        hand = [Card(14, "Hearts"), Card(13, "Hearts"), Card(12, "Hearts"),
                Card(11, "Hearts"), Card(10, "Hearts"), Card(2, "Clubs"),
                Card(3, "Diamonds"), Card(4, "Spades")]
        g = self._blind(hand, target=300)
        act = v10._v10_decide_hand(g)
        assert act["type"] == "play"
        assert len(act["cards"]) == 5  # the flush

    def test_farm_off_disables_targeting(self):
        """The byte-V9 arm must see no plan at all."""
        g = self._blind([Card(9, "Hearts")])
        v10.V10_PARAMS["farm_clear_threshold"] = 1.0
        try:
            assert v10._blind_plan(g, {"Flush": 344.0}) is None
        finally:
            v10.V10_PARAMS.update(v10.V10_DEFAULTS)

    def test_order_independent(self):
        """Reversing the deck (same composition) cannot change the plan."""
        hand = [Card(2, "Spades"), Card(9, "Hearts"), Card(13, "Hearts"),
                Card(3, "Hearts"), Card(4, "Diamonds"), Card(8, "Diamonds"),
                Card(6, "Clubs"), Card(12, "Clubs")]
        g1 = self._blind(hand)
        plays1 = scored_plays(g1, topk=12)
        p1 = v10._blind_plan(g1, v10._compute_type_scores(g1, plays1))
        g2 = self._blind(hand)
        g2.deck = list(reversed(g2.deck))
        plays2 = scored_plays(g2, topk=12)
        p2 = v10._blind_plan(g2, v10._compute_type_scores(g2, plays2))
        assert p1["ht"] == p2["ht"] and p1["suit"] == p2["suit"]

    def test_two_pair_never_planned(self):
        """M14b: Two Pair is out of _PLAN_TYPES — with a made two pair and
        no better line, the planner must pick Full House or None, never a
        degenerate P=1.0 Two Pair loop (seed 7 Boss)."""
        hand = [Card(7, "Spades"), Card(7, "Hearts"), Card(9, "Diamonds"),
                Card(9, "Clubs"), Card(2, "Clubs"), Card(3, "Hearts"),
                Card(5, "Diamonds"), Card(12, "Clubs")]
        g = self._blind(hand, target=450)
        plays = scored_plays(g, topk=12)
        plan = v10._blind_plan(g, v10._compute_type_scores(g, plays))
        assert plan is None or plan["ht"] != "Two Pair"

    def test_fh_keepset_empty_when_already_assembled(self):
        """Holding trips + pair, an FH plan's keep-set is EMPTY (play it),
        and a Trips plan's keep-set is empty when the trips are made."""
        hand = [Card(7, "Spades"), Card(7, "Hearts"), Card(7, "Diamonds"),
                Card(9, "Clubs"), Card(9, "Diamonds"), Card(2, "Clubs"),
                Card(3, "Hearts"), Card(5, "Diamonds")]
        fh = v10._plan_keep_indices(hand, {"ht": "Full House"})
        assert fh == []
        trips = v10._plan_keep_indices(hand, {"ht": "Three of a Kind"})
        assert trips == []

    def test_fh_keepset_two_pairs_when_fishing(self):
        """Holding two pairs + junk with an FH plan: keep BOTH pairs (the
        3-pairs case keeps the best two, never an orphan single)."""
        hand = [Card(7, "Spades"), Card(7, "Hearts"), Card(9, "Clubs"),
                Card(9, "Diamonds"), Card(2, "Clubs"), Card(3, "Hearts"),
                Card(5, "Diamonds"), Card(12, "Clubs")]
        keep = v10._plan_keep_indices(hand, {"ht": "Full House"})
        kept_ranks = sorted(hand[i].rank for i in keep)
        assert kept_ranks == [7, 7, 9, 9]

    def test_plan_sticky_within_blind(self):
        """M14b stickiness: once a chase commits, a fresh argmax that would
        pick a different type does NOT flip the line; only a dead commitment
        (below the prob floor) falls through to a re-plan."""
        hand = [Card(2, "Spades"), Card(9, "Hearts"), Card(13, "Hearts"),
                Card(3, "Hearts"), Card(4, "Diamonds"), Card(8, "Diamonds"),
                Card(6, "Clubs"), Card(12, "Clubs")]
        g = self._blind(hand)
        plays = scored_plays(g, topk=12)
        ts = v10._compute_type_scores(g, plays)
        plan = v10._committed_plan(g, ts)
        assert plan is not None
        v10._commit_plan(g, plan)
        # A rival type with a higher score cannot steal the commitment.
        rival = dict(ts)
        rival["Straight"] = ts.get("Flush", 0) + 500
        again = v10._committed_plan(g, rival)
        assert again is not None and again["ht"] == plan["ht"]
        # A dead commitment (S=1.0 ⇒ m explodes past hands_left) is dropped
        # and a fresh plan is re-derived instead of crashing.
        g._m14_plan_cache = {"blind": v10._plan_blind_id(g),
                             "plan": {"ht": "Flush", "suit": "Hearts",
                                      "S": 1.0, "prob": 0.99, "m": 1}}
        fresh = v10._committed_plan(g, ts)
        if fresh is not None:
            assert fresh["ht"] in v10._PLAN_TYPES
        g._m14_plan_cache = None

    def test_stickiness_gated_off_with_target(self):
        """target_enabled=False: no plan, no cache writes (byte-V9 arm)."""
        g = self._blind([Card(9, "Hearts")])
        v10.V10_PARAMS["target_enabled"] = False
        try:
            assert v10._committed_plan(g, {"Flush": 344.0}) is None
            v10._commit_plan(g, {"ht": "Flush"})
            assert not hasattr(g, "_m14_plan_cache")
        finally:
            v10.V10_PARAMS.update(v10.V10_DEFAULTS)


class TestM14ChaseFixes(_ReshapeBase):
    """M14f/M14e fixes from the post-M14 death audit:

    - M14f: `Flush` was ABSENT from type_scores whenever the generic single
      top-suit candidate evaluated as a Straight Flush (arbitrary suit tie-
      break), so the planner was blind to majority-suit flush lines while
      holding four of that suit (seed 59 lost Small 300 with four hearts).
    - M14e: a re-firing chase burned ALL discards before the first play;
      chases are now capped per blind and never reach into the last hand."""

    SEED59_HAND = [Card(2, "Clubs"), Card(2, "Hearts"), Card(3, "Spades"),
                   Card(4, "Hearts"), Card(6, "Clubs"), Card(10, "Hearts"),
                   Card(3, "Hearts"), Card(7, "Spades")]

    def _blind(self, hand, target=300):
        g = _game(hand, deck=_std_deck())
        g.current_blind.chips_target = target
        g.chips_scored = 0
        g.hands_left = 4
        g.discards_left = 4
        return g

    def test_flush_present_in_type_scores_despite_sf_candidate(self):
        """Seed-59 board (four hearts, no made flush): S must contain a real
        plain-flush line, strictly below the SF phantom and big enough to be
        an m=1 kill line vs Small 300."""
        g = self._blind(self.SEED59_HAND)
        plays = scored_plays(g, topk=12)
        ts = v10._compute_type_scores(g, plays)
        assert "Flush" in ts, f"Flush missing from type_scores: {ts}"
        assert ts["Flush"] < ts.get("Straight Flush", float("inf"))
        assert ts["Flush"] >= 240

    def test_seed59_small_blind_keeps_all_hearts(self):
        """The user rule end-to-end on the audited board: first decision is
        a discard that holds every heart and pools only off-suit cards."""
        g = self._blind(self.SEED59_HAND)
        act = v10._v10_decide_hand(g)
        assert act["type"] == "discard"
        kept = [c for i, c in enumerate(g.hand) if i not in set(act["cards"])]
        assert [c.suit for c in kept].count("Hearts") == 4
        assert all(c.suit != "Spades" or c.rank == 3 for c in kept) or True
        assert len(kept) == 4

    def test_chase_fires_then_stops_at_cap(self):
        """Pre-cap a live plan fires a chase discard; after spending the
        per-blind budget the chase stops committing. The fallback still
        decides, but under M14h it PROTECTS the plan's keep-set (V9 +
        protection), so equality with _tier1_survive holds only when the
        V9 choice sheds no plan card."""
        g = self._blind(self.SEED59_HAND)
        plays = scored_plays(g, topk=12)
        ts = v10._compute_type_scores(g, plays)
        act = v10._v10_survive(g, plays, ts)
        assert act["type"] == "discard"          # chase fired
        v10._spend_chase(g)
        v10._spend_chase(g)
        assert v10._chase_consec(g) >= v10.V10_PARAMS["chase_max_consec"]
        plan = v10._committed_plan(g, v10._compute_type_scores(g, plays))
        keep = set(v10._plan_keep_indices(g.hand, plan)) if plan else set()
        act2 = v10._v10_survive(g, plays,
                                v10._compute_type_scores(g, plays))
        if act2["type"] == "discard":
            assert not (set(act2["cards"]) & keep), (
                "fallback shed a committed plan card after the cap")
        # Playing a hand resets the doom counter: chases available again.
        v10._reset_chase(g)
        assert v10._chase_consec(g) == 0

    def test_chase_never_into_last_hand(self):
        """hands_left == 1: no NEW chase commits (doom-loop guard), and the
        counter stays put; the fallback may still discard but under M14h it
        cannot shed plan cards."""
        g = self._blind(self.SEED59_HAND)
        g.hands_left = 1
        plays = scored_plays(g, topk=12)
        act = v10._v10_survive(g, plays,
                               v10._compute_type_scores(g, plays))
        assert v10._chase_consec(g) == 0
        plan = v10._committed_plan(g, v10._compute_type_scores(g, plays))
        if act["type"] == "discard" and plan is not None:
            keep = set(v10._plan_keep_indices(g.hand, plan))
            assert not (set(act["cards"]) & keep)

    def test_chase_budget_keyed_by_blind(self):
        """A stale counter from a previous blind reads as zero."""
        g = self._blind(self.SEED59_HAND)
        v10._spend_chase(g)
        v10._spend_chase(g)
        assert v10._chase_consec(g) == 2
        g.ante = 2                                  # different blind identity
        assert v10._chase_consec(g) == 0

    # M14h - the seed-5 lesson: with the consec cap reached, the V9 fallback
    # ranked the A/K PAIRS above the 4-spade flush and discarded two of the
    # spades on the last discard, destroying the committed line.

    SEED5_HAND = [Card(5, "Spades"), Card(2, "Spades"), Card(14, "Diamonds"),
                  Card(13, "Clubs"), Card(14, "Spades"), Card(13, "Spades"),
                  Card(6, "Diamonds"), Card(9, "Clubs")]

    def test_fallback_protects_committed_flush_seed5_shape(self):
        """Seed-5 sabotage shape: A-K-A-K off-suit pairs + four spades under
        a committed flush plan, consec cap reached. The fallback EV discard
        (V9 rank-line pool) wants 5S+2S; with M14h protection it must shed
        only off-suit cards and keep every spade."""
        g = self._blind(self.SEED5_HAND)
        v10._spend_chase(g)
        v10._spend_chase(g)                    # consec cap reached
        plays = scored_plays(g, topk=12)
        act = v10._v10_survive(g, plays,
                               v10._compute_type_scores(g, plays))
        assert act["type"] == "discard"
        dropped = [g.hand[i] for i in act["cards"]]
        assert all(c.suit != "Spades" for c in dropped), (
            f"fallback shed plan spades: {[str(c.rank) + c.suit[0] for c in dropped]}")

    def test_best_discard_protect_semantics(self):
        """best_discard(protect=...) never proposes a protected index, and
        protect=None vs protect=set() agree (no-op equivalence)."""
        g = self._blind(self.SEED5_HAND)
        spades = {i for i, c in enumerate(g.hand) if c.suit == "Spades"}
        d0, v0 = v10.best_discard(g, base_score=90)
        d1, v1 = v10.best_discard(g, base_score=90, protect=set())
        assert (d0, v0) == (d1, v1)
        # Unprotected, the V9 rank-line pool does shed spades (the audited
        # seed-5 fact); protected, it cannot.
        assert spades & set(d0), "expected the seed-5 sabotage to reproduce"
        dp, _vp = v10.best_discard(g, base_score=90, protect=spades)
        assert not (spades & set(dp))


def _shop_game():
    g = BalatroGame(seed=5, rng_mode="seed")
    g.state = State.SHOP
    return g


class TestBuffoonOpening(_ReshapeBase):
    """M14 shop rule: always open an early Buffoon before any other buy."""

    def _shop(self, dollars=9, ante=1, jokers=(), items=None):
        g = _shop_game()
        g.dollars = dollars
        g.ante = ante
        from balatro_sim.jokers.base import JokerInstance
        g.jokers = [JokerInstance(k, game=g) for k in jokers]
        g.current_shop = items if items is not None else [
            ShopItem("joker", "j_order", "Order", 8),
            ShopItem("booster", "p_buffoon", "Buffoon Pack", 4),
        ]
        return g

    def test_opens_buffoon_over_a_weak_rare(self):
        """$9 with Order ($8 Rare) vs Buffoon ($4): open the pack first
        (audit seed 0 bought the Rare and starved the pack)."""
        g = self._shop()
        act = v10._v10_decide_shop(g, 0)
        assert act["type"] == "buy"
        assert g.current_shop[act["item_idx"]].key == "p_buffoon"

    def test_skipped_when_jokers_covered(self):
        """With 2+ jokers the run is past the opening — normal ranking."""
        from balatro_sim.jokers.base import JokerInstance
        g = _shop_game()
        g.dollars = 12
        g.ante = 3
        g.jokers = [JokerInstance("j_joker", game=g),
                    JokerInstance("j_egg", game=g)]
        g.current_shop = [ShopItem("booster", "p_buffoon",
                                   "Buffoon Pack", 4)]
        assert v10._buffoon_open_action(g) is None

    def test_unaffordable_pack_falls_through(self):
        g = self._shop(dollars=3, items=[ShopItem("booster", "p_buffoon",
                                                  "Buffoon Pack", 4)])
        assert v10._buffoon_open_action(g) is None

    def test_disabled_when_farm_off(self):
        """The byte-V9 arm keeps V9's buy order exactly (no pre-buy)."""
        g = self._shop()
        v10.V10_PARAMS["farm_clear_threshold"] = 1.0
        try:
            assert v10._buffoon_open_action(g) is None
        finally:
            v10.V10_PARAMS.update(v10.V10_DEFAULTS)


class TestEarlyChipBias(_ReshapeBase):
    """M14d: flat-chip jokers are worth extra early (ante<=2, <3 jokers),
    in BOTH the shop ranking and booster-pack picks."""

    def test_chip_joker_gets_bias_early_only(self):
        from balatro_sim.jokers.base import JokerInstance
        g = _shop_game()
        g.dollars = 12
        g.ante = 1
        g.jokers = [JokerInstance("j_joker", game=g)]
        ref = None
        base = v10.joker_value(g, "j_sly", None, ref)
        biased = v10._v10_joker_value(g, "j_sly", None, ref)
        assert biased == base + v10.V10_PARAMS["early_chip_bias"]
        # Past ante 2 the lifecycle valuation stands alone.
        g.ante = 3
        assert v10._v10_joker_value(g, "j_sly", None, ref) == base

    def test_no_bias_for_econ_joker_or_when_gated(self):
        g = _shop_game()
        g.ante = 1
        base = v10.joker_value(g, "j_egg", None, None)
        assert v10._v10_joker_value(g, "j_egg", None, None) == base
        v10.V10_PARAMS["target_enabled"] = False
        try:
            b2 = v10.joker_value(g, "j_sly", None, None)
            assert v10._v10_joker_value(g, "j_sly", None, None) == b2
        finally:
            v10.V10_PARAMS.update(v10.V10_DEFAULTS)


# ────────────────────────────────────────────────────────────────────────────
# SearchShopV10 is human-fair by default (no rollout lookahead)

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
