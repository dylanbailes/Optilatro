"""test_seal_fidelity.py — seal/enhancement fidelity regression tests.

Pins the Phase-0 sim fixes from `docs/agent-v10-inblind-spec.md` §3:
  - Gold seal pays $3 when SCORED (not when held at round end).
  - Purple seal creates a Tarot when DISCARDED (not when played).
  - Blue seal is retriggered by Mime (2 planets per held Blue seal).
  - Red seal retriggers HELD abilities too (Steel X2.25, Gold card $6).
  - Debuffed cards are worthless in both score and held value.

Human-readable: each test is a named, single-behavior assertion with a
docstring, so a failing test points at exactly which mechanic regressed.
"""
from __future__ import annotations

from balatro_sim.card import Card
from balatro_sim.consumables import ALL_TAROTS, PLANET_HAND
from balatro_sim.game import BalatroGame, State
from balatro_sim.jokers.base import JokerInstance
from balatro_sim.scoring import score_hand


def _game(hand, deck=None, jokers=()):
    """A fresh seed-mode game in SELECTING_HAND with a controlled hand/deck."""
    g = BalatroGame(seed=7, rng_mode="seed")
    g.reset()
    if g.state != State.SELECTING_HAND:
        g.state = State.BLIND_SELECT
        g.step({"type": "play_blind"})
    g.hand = list(hand)
    g.deck = list(deck) if deck is not None else []
    g.jokers = [JokerInstance(k, game=g) if isinstance(k, str) else k
                for k in jokers]
    g.current_blind.chips_target = 10_000_000
    g.hands_left = 4
    g.discards_left = 3
    return g


def _round_end_dollars(held, jokers=()):
    """Dollars added by one _end_round call for a given held hand + jokers."""
    g = _game(held, jokers=jokers)
    before = g.dollars
    g._end_round()
    return g.dollars - before


# ────────────────────────────────────────────────────────────────────────────
# Gold seal — $3 when SCORED (doc §8), not when held at round end.
# ────────────────────────────────────────────────────────────────────────────

class TestGoldSeal:
    def test_gold_seal_pays_when_scored(self):
        """Playing a Gold-sealed card awards $3 (pending_money in the score)."""
        played = [Card(14, "Spades", seal="Gold")]
        _, ctx = score_hand(
            scoring_cards=played, all_cards=played, hand_type="High Card",
            jokers=[], planet_levels={"High Card": 1}, hands_left=3,
            discards_left=3, dollars=10, ante=1, deck_remaining=40,
            held_cards=[],
        )
        assert ctx.pending_money == 3

    def test_gold_seal_pays_via_game_play(self):
        """Playing a Gold-sealed card in the real game path awards $3."""
        g = _game([Card(14, "Spades", seal="Gold"), Card(5, "Hearts")])
        g.hands_left = 2
        before = g.dollars
        g._play_hand([0])
        assert g.dollars == before + 3

    def test_gold_seal_not_paid_when_merely_held(self):
        """A Gold-sealed card HELD (not played) at round end awards nothing."""
        base = _round_end_dollars([Card(5, "Hearts")])
        gold_held = _round_end_dollars([Card(5, "Hearts", seal="Gold")])
        assert gold_held - base == 0


# ────────────────────────────────────────────────────────────────────────────
# Purple seal — Tarot when DISCARDED (doc §8), not when played.
# ────────────────────────────────────────────────────────────────────────────

class TestPurpleSeal:
    def test_purple_seal_creates_tarot_on_discard(self):
        """Discarding a Purple-sealed card adds one Tarot."""
        g = _game([Card(5, "Hearts", seal="Purple")])
        g.discards_left = 1
        before = len(g.consumable_hand)
        g._discard([0])
        assert len(g.consumable_hand) == before + 1
        assert g.consumable_hand[-1] in ALL_TAROTS

    def test_purple_seal_not_on_play(self):
        """Playing a Purple-sealed card does NOT add a Tarot."""
        g = _game([Card(14, "Spades", seal="Purple")])
        g.hands_left = 2
        before = len(g.consumable_hand)
        g._play_hand([0])
        assert len(g.consumable_hand) == before


# ────────────────────────────────────────────────────────────────────────────
# Blue seal — planet of the FINAL hand, held at round end; Mime doubles it.
# ────────────────────────────────────────────────────────────────────────────

class TestBlueSeal:
    def test_blue_seal_grants_one_planet(self):
        g = _game([Card(5, "Hearts", seal="Blue")])
        g.last_hand_played = "Pair"
        g._end_round()
        assert len(g.consumable_hand) == 1
        assert g.consumable_hand[0] in PLANET_HAND

    def test_blue_seal_doubled_by_mime(self):
        g = _game([Card(5, "Hearts", seal="Blue")], jokers=("j_mime",))
        g.last_hand_played = "Pair"
        g._end_round()
        assert len(g.consumable_hand) == 2
        assert all(c in PLANET_HAND for c in g.consumable_hand)

    def test_blue_seal_debuffed_grants_nothing(self):
        g = _game([Card(5, "Hearts", seal="Blue", debuffed=True)])
        g.last_hand_played = "Pair"
        g._end_round()
        assert len(g.consumable_hand) == 0


# ────────────────────────────────────────────────────────────────────────────
# Red seal — retriggers HELD abilities too (RULING-R): Steel X2.25, Gold $6.
# ────────────────────────────────────────────────────────────────────────────

class TestRedSealHeld:
    def test_plain_held_steel_x1_5(self):
        played = [Card(14, "Spades")]
        held = [Card(13, "Hearts", enhancement="Steel")]
        _, ctx = score_hand(
            scoring_cards=played, all_cards=played + held, hand_type="High Card",
            jokers=[], planet_levels={"High Card": 1}, hands_left=3,
            discards_left=3, dollars=10, ante=1, deck_remaining=40,
            held_cards=held,
        )
        assert abs(ctx.mult_mult - 1.5) < 1e-9

    def test_red_seal_held_steel_x2_25(self):
        """A Red-sealed Steel card held in hand gives X1.5 twice = X2.25."""
        played = [Card(14, "Spades")]
        held = [Card(13, "Hearts", enhancement="Steel", seal="Red")]
        _, ctx = score_hand(
            scoring_cards=played, all_cards=played + held, hand_type="High Card",
            jokers=[], planet_levels={"High Card": 1}, hands_left=3,
            discards_left=3, dollars=10, ante=1, deck_remaining=40,
            held_cards=held,
        )
        assert abs(ctx.mult_mult - 1.5 * 1.5) < 1e-9

    def test_red_seal_held_gold_card_doubles(self):
        """A Red-sealed Gold card held at round end pays $6 (retriggered)."""
        base = _round_end_dollars([Card(5, "Hearts")])
        gold_red = _round_end_dollars(
            [Card(5, "Hearts", enhancement="Gold", seal="Red")])
        assert gold_red - base == 6


# ────────────────────────────────────────────────────────────────────────────
# Gold card (enhancement) — $3 held at round end, Mime/Red retrigger, debuff.
# ────────────────────────────────────────────────────────────────────────────

class TestGoldCardHeld:
    def test_gold_card_pays_3(self):
        base = _round_end_dollars([Card(5, "Hearts")])
        gold = _round_end_dollars([Card(5, "Hearts", enhancement="Gold")])
        assert gold - base == 3

    def test_gold_card_doubled_by_mime(self):
        base = _round_end_dollars([Card(5, "Hearts")], jokers=("j_mime",))
        gold = _round_end_dollars([Card(5, "Hearts", enhancement="Gold")],
                                  jokers=("j_mime",))
        assert gold - base == 6

    def test_debuffed_gold_card_not_paid(self):
        base = _round_end_dollars([Card(5, "Hearts")])
        debuffed = _round_end_dollars(
            [Card(5, "Hearts", enhancement="Gold", debuffed=True)])
        assert debuffed - base == 0
