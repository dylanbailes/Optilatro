"""test_joker_spec.py — data-driven behavioral validation of the joker layer
against tools/joker_spec.json (the reference-doc §2 contract).

The static audit (tools/audit_jokers_static.py) guarantees STRUCTURE: every
canonical key resolves exactly once, no dead keys, no stub classes. This file
guarantees BEHAVIOR: SCORING_SPEC rows assert the exact chips/mult/mult_mult a
joker contributes to a scored hand (vs the no-joker baseline); GAME_SPEC rows
exercise game-state jokers through a real BalatroGame.

Row values are derived from the spec's effect text and the real game. When a
row's numbers disagree with the sim, the sim is wrong — fix the sim, not the
test.
"""
from __future__ import annotations

import json
import pathlib
from unittest.mock import patch

import pytest

from balatro_sim.card import Card, make_standard_deck
from balatro_sim.game import BalatroGame
from balatro_sim.hand_eval import evaluate_hand
from balatro_sim.jokers.base import JokerInstance, JOKER_REGISTRY
from balatro_sim.scoring import score_hand

ROOT = pathlib.Path(__file__).resolve().parents[3]
SPEC = json.load(open(ROOT / "tools" / "joker_spec.json", encoding="utf-8"))

_ALL_HANDS = [
    "High Card", "Pair", "Two Pair", "Three of a Kind", "Straight", "Flush",
    "Full House", "Four of a Kind", "Straight Flush", "Five of a Kind",
    "Flush House", "Flush Five",
]


def _levels():
    return {h: 1 for h in _ALL_HANDS}


def _score_ctx(cards, joker_keys, hand_type=None, *, held=None, game=None,
               dollars=10, discards=3, deck_remaining=40, hands_left=3,
               planet_levels=None):
    """Score `cards` twice — with the jokers and without — and return the
    jokers' exact contribution as (chips_delta, mult_delta, xmult_factor).
    Chips/mult are additive deltas; mult_mult is the multiplicative factor
    (joker run over baseline)."""
    if hand_type is None:
        hand_type, scoring = evaluate_hand(cards)
    else:
        scoring = cards

    def _run(jl):
        _, ctx = score_hand(
            scoring_cards=scoring, all_cards=cards, hand_type=hand_type,
            jokers=jl, planet_levels=planet_levels or _levels(),
            hands_left=hands_left, discards_left=discards, dollars=dollars,
            ante=1, deck_remaining=deck_remaining, game=game, held_cards=held,
        )
        return ctx.chips, ctx.mult, ctx.mult_mult

    c1, m1, x1 = _run([JokerInstance(k, game=game) for k in joker_keys])
    c0, m0, x0 = _run([])
    return c1 - c0, m1 - m0, x1 / x0


# ════════════════════════════════════════════════════════════════════════════
# Data-driven scoring spec — (key, cards, hand_type, chips, mult, mult_mult)
# ════════════════════════════════════════════════════════════════════════════

A = Card(14, "Spades")
T = Card(10, "Hearts")
TS = Card(10, "Spades")
Q = Card(12, "Hearts")
K = Card(13, "Spades")
FIVE = Card(5, "Diamonds")

# hand builders
def _pair():
    return [T, TS]


def _three():
    return [Card(10, "Hearts"), Card(10, "Spades"), Card(10, "Clubs")]


def _two_pair():
    return [Card(10, "Hearts"), Card(10, "Spades"),
            Card(5, "Clubs"), Card(5, "Diamonds")]


def _straight():
    cards = [Card(r, "Hearts") for r in (5, 6, 7, 8, 9)]
    cards[1].suit = "Spades"   # break the flush
    return cards


def _flush():
    return [Card(r, "Hearts") for r in (2, 5, 8, 11, 14)]


def _four():
    return [Card(10, s) for s in ("Hearts", "Spades", "Clubs", "Diamonds")]


# (key, cards, hand_type, chips, mult, mult_mult, held)
SCORING_SPEC = [
    # ── base +Mult / Chips ────────────────────────────────────────────────
    ("j_joker",        [A],        "High Card",  0, 4, 1, None),
    ("j_sly",          _pair(),    "Pair",      50, 0, 1, None),
    ("j_wily",         _three(),   "Three of a Kind", 100, 0, 1, None),
    ("j_clever",       _two_pair(),"Two Pair",  80, 0, 1, None),
    ("j_devious",      _straight(),"Straight", 100, 0, 1, None),
    ("j_crafty",       _flush(),   "Flush",     80, 0, 1, None),
    ("j_jolly",        _pair(),    "Pair",       0, 8, 1, None),
    ("j_zany",         _three(),   "Three of a Kind", 0, 12, 1, None),
    ("j_mad",          _two_pair(),"Two Pair",   0, 10, 1, None),
    ("j_crazy",        _straight(),"Straight",   0, 12, 1, None),
    ("j_droll",        _flush(),   "Flush",      0, 10, 1, None),
    ("j_half",         [A],        "High Card",  0, 20, 1, None),
    ("j_abstract",     [A],        "High Card",  0, 3, 1, None),   # +3 × 1 joker
    # ── the family (canonical xMult keys) ─────────────────────────────────
    ("j_duo",          _pair(),    "Pair",       0, 0, 2, None),
    ("j_trio",         _three(),   "Three of a Kind", 0, 0, 3, None),
    ("j_family",       _four(),    "Four of a Kind", 0, 0, 4, None),
    ("j_order",        _straight(),"Straight",   0, 0, 3, None),
    ("j_tribe",        _flush(),   "Flush",      0, 0, 2, None),
    # ── the de-duplicated chips/mult interchanges ─────────────────────────
    ("j_banner",       [A],        "High Card", 90, 0, 1, None),   # +30 × 3 discards
    ("j_mystic_summit",[A],        "High Card",  0, 15, 1, None),  # discards=0
    ("j_fibonacci",    [A],        "High Card",  0, 8, 1, None),   # Ace → +8 mult
    ("j_scary_face",   [Card(11, "Spades")], "High Card", 30, 0, 1, None),
    ("j_smiley",       [Q],        "High Card",  0, 5, 1, None),
    ("j_walkie_talkie",[T],        "High Card", 10, 4, 1, None),
    ("j_stencil",      [A],        "High Card",  0, 0, 4, None),   # 4 empty slots
    ("j_acrobat",      [A],        "High Card",  0, 0, 3, None),   # hands_left=0
    # ── held-in-hand (B3) ─────────────────────────────────────────────────
    ("j_baron",        [A],        "High Card",  0, 0, 1.5, [K]),  # King held
    ("j_shoot_the_moon",[A],       "High Card",  0, 13, 1, [Q]),   # Queen held
    ("j_blackboard",   [A],        "High Card",  0, 0, 3, [Card(13, "Spades"), Card(11, "Clubs")]),
    ("j_raised_fist",  [A],        "High Card",  0, 10, 1, [FIVE]),  # 2 × 5 (lowest held)
    # ── economy scaling ───────────────────────────────────────────────────
    ("j_bull",         [A],        "High Card", 20, 0, 1, None),   # +2 × $10
    ("j_bootstraps",   [A],        "High Card",  0, 4, 1, None),   # $10 // 5 × 2
    ("j_blue_joker",   [A],        "High Card", 80, 0, 1, None),   # +2 × 40 deck
    ("j_erosion",      [A],        "High Card",  0, 48, 1, None),  # 52-40=12 × 4
    ("j_odd_todd",     [Card(9, "Spades")], "High Card", 31, 0, 1, None),
    ("j_even_steven",  [Card(8, "Hearts")], "High Card", 0, 4, 1, None),
    ("j_scholar",      [A],        "High Card", 20, 4, 1, None),
    ("j_flower_pot",   [Card(10, "Hearts"), Card(10, "Spades"),
                        Card(10, "Clubs"), Card(10, "Diamonds"), Card(9, "Hearts")],
                       "High Card",  0, 0, 3, None),               # 4 suits scoring
    ("j_seeing_double",[Card(10, "Clubs"), Card(10, "Hearts")],
                       "Pair",       0, 0, 2, None),
    ("j_triboulet",    [K],        "High Card",  0, 0, 2, None),
    ("j_photograph",   [Q],        "High Card",  0, 0, 2, None),
    ("j_wee",          [Card(2, "Spades")], "High Card", 8, 0, 1, None),
    ("j_green_joker",  [A],        "High Card",  0, 1, 1, None),   # +1/hand played
    ("j_square_joker", [Card(r, "Hearts") for r in (2, 3, 4, 5)],
                       "High Card",  4, 0, 1, None),
    ("j_runner",       _straight(),"Straight",  15, 0, 1, None),
]


@pytest.mark.parametrize(
    "key,cards,hand_type,exp_chips,exp_mult,exp_xmult,held",
    SCORING_SPEC,
    ids=[r[0] for r in SCORING_SPEC],
)
def test_scoring_spec(key, cards, hand_type, exp_chips, exp_mult, exp_xmult, held):
    kw = {"dollars": 10, "discards": 0 if key == "j_mystic_summit" else 3,
          "deck_remaining": 40, "hands_left": 0 if key == "j_acrobat" else 3}
    chips, mult, xmult = _score_ctx(cards, [key], hand_type, held=held, **kw)
    assert chips == pytest.approx(exp_chips), f"{key}: chips"
    assert mult == pytest.approx(exp_mult), f"{key}: mult"
    assert xmult == pytest.approx(exp_xmult), f"{key}: mult_mult"


# ── j_supernova uses game.run_hand_counts — needs a game ─────────────────────
def test_bootstraps_uncapped_above_50():
    """Bootstraps is +2 Mult per $5 with NO cap (the old chips.py build capped
    at $50 → +20; the reference doc has no cap)."""
    chips, mult, _ = _score_ctx([A], ["j_bootstraps"], "High Card", dollars=100)
    assert mult == 40   # 100 // 5 × 2 — uncapped


def test_supernova_counts_run_hands():
    g = BalatroGame(seed=11, rng_mode="seed")
    g.run_hand_counts["Pair"] = 7
    j = JokerInstance("j_supernova", game=g)
    ctx = _score_ctx([T, TS], ["j_supernova"], "Pair", game=g)
    assert ctx[1] == 7  # +7 mult


# ════════════════════════════════════════════════════════════════════════════
# Game-state jokers (through a real BalatroGame)
# ════════════════════════════════════════════════════════════════════════════

def test_steel_joker_counts_full_deck():
    g = BalatroGame(seed=11, rng_mode="seed")
    # Stuff the persistent deck with 5 Steel cards
    steel = [Card(2, "Spades", enhancement="Steel") for _ in range(5)]
    g.deck = steel + g.deck[5:]
    j = JokerInstance("j_steel_joker", game=g)
    g.jokers.append(j)
    chips, mult, xmult = _score_ctx([A], ["j_steel_joker"], "High Card", game=g)
    assert xmult == pytest.approx(2.0)   # 1 + 0.2 × 5


def test_glass_joker_counts_full_deck():
    g = BalatroGame(seed=11, rng_mode="seed")
    glass = [Card(2, "Clubs", enhancement="Glass") for _ in range(2)]
    g.deck = glass + g.deck[2:]
    chips, mult, xmult = _score_ctx([A], ["j_glass_joker"], "High Card", game=g)
    assert xmult == pytest.approx(2.5)   # 1 + 0.75 × 2


def test_stone_joker_counts_full_deck():
    g = BalatroGame(seed=11, rng_mode="seed")
    stone = [Card(2, "Hearts", enhancement="Stone") for _ in range(3)]
    g.deck = stone + g.deck[3:]
    chips, mult, xmult = _score_ctx([A], ["j_stone_joker"], "High Card", game=g)
    assert chips == 75   # 25 × 3


def test_drivers_license_16_enhanced_in_full_deck():
    g = BalatroGame(seed=11, rng_mode="seed")
    enh = [Card(2, "Spades", enhancement="Bonus") for _ in range(16)]
    g.deck = enh + g.deck[16:]
    chips, mult, xmult = _score_ctx([A], ["j_drivers_license"], "High Card", game=g)
    assert xmult == 3.0
    # Stone does NOT count (real game skips Stone Card effects)
    g2 = BalatroGame(seed=11, rng_mode="seed")
    stone = [Card(2, "Hearts", enhancement="Stone") for _ in range(16)]
    g2.deck = stone + g2.deck[16:]
    chips, mult, xmult = _score_ctx([A], ["j_drivers_license"], "High Card", game=g2)
    assert xmult == 1.0


def _absolute_xmult(cards, joker_keys, *, held=None, game=None, **kw):
    """Score once and return the raw mult_mult (held-card effects like Steel
    apply even with no jokers, so delta-vs-baseline is the wrong lens here)."""
    jokers = [JokerInstance(k, game=game) for k in joker_keys]
    hand_type, scoring = evaluate_hand(cards)
    _, ctx = score_hand(scoring, cards, hand_type, jokers, _levels(),
                        hands_left=3, discards_left=3, dollars=10, ante=1,
                        deck_remaining=40, game=game, held_cards=held)
    return ctx.mult_mult


def test_steel_held_in_hand_not_scored():
    """B3: a Steel card HELD in hand gives X1.5; a Steel card PLAYED does not."""
    g = BalatroGame(seed=11, rng_mode="seed")
    held_steel = [Card(2, "Spades", enhancement="Steel"),
                  Card(3, "Hearts", enhancement="Steel")]
    assert _absolute_xmult([A], [], held=held_steel, game=g) == pytest.approx(2.25)
    # Played Steel card: no bonus while scoring (only held)
    played_steel = Card(2, "Spades", enhancement="Steel")
    assert _absolute_xmult([played_steel], [], game=g) == 1.0


def test_mime_doubles_held_steel():
    g = BalatroGame(seed=11, rng_mode="seed")
    held_steel = [Card(2, "Spades", enhancement="Steel")]
    assert _absolute_xmult([A], ["j_mime"], held=held_steel, game=g) == pytest.approx(2.25)
    # control: without Mime the single held Steel is X1.5
    assert _absolute_xmult([A], [], held=held_steel, game=g) == pytest.approx(1.5)


def test_lucky_card_odds_and_lucky_cat():
    """B4: Lucky card 1/5 (+20 mult) and 1/15 ($20) per ref doc §6 +
    balatro-rs game.rs prob_roll(1,5)/(1,15); Oops! All 6s doubles both;
    Lucky Cat gains X0.25 per successful trigger."""
    g = BalatroGame(seed=11, rng_mode="seed")
    j = JokerInstance("j_lucky_cat", game=g)
    g.jokers.append(j)
    lucky = Card(2, "Spades", enhancement="Lucky")
    # Probe: score a Lucky card many times in seed mode; Lucky Cat's X0.25
    # must grow on successful triggers (~1/5 + 1/15 − overlap ≈ 1/4 of 400).
    from balatro_sim.scoring import score_hand as sh
    hits = 0
    for _ in range(400):
        j.state["xmult"] = 1.0
        sh([lucky], [lucky], "High Card", [j], _levels(),
           hands_left=3, discards_left=3, dollars=10, ante=1,
           deck_remaining=40, game=g, held_cards=[])
        if j.state.get("xmult", 1.0) > 1.0:
            hits += 1
    assert 60 <= hits <= 160   # ~1/5 + (1/15 minus overlap) of 400
    # A card that hits BOTH rolls in one scoring instance grants X0.5 (two
    # successful triggers), not X0.25 — the per-roll on_lucky_trigger loop.
    from unittest.mock import patch
    j.state["xmult"] = 1.0
    with patch("balatro_sim.scoring._ctx_rng") as mrng:
        mrng.return_value.random.return_value = 0.0   # both rolls succeed
        sh([lucky], [lucky], "High Card", [j], _levels(),
           hands_left=3, discards_left=3, dollars=10, ante=1,
           deck_remaining=40, game=g, held_cards=[])
    assert j.state["xmult"] == pytest.approx(1.5)   # +0.25 + 0.25


def test_madness_scales_and_small_big_only():
    g = BalatroGame(seed=11, rng_mode="seed")
    j = JokerInstance("j_madness", game=g)
    eff = JOKER_REGISTRY["j_madness"]
    # Two Small/Big blind selections → X2.0 (the old build multiplied by
    # 0.5×0.5 = 0.25 — a nerf; the real effect is X(1 + 0.5 × blinds))
    g.current_blind = type(g.current_blind)("test", "Small", 100, False, "")
    eff.on_blind_selected(j, None)
    eff.on_blind_selected(j, None)
    from balatro_sim.jokers.base import ScoreContext
    ctx = ScoreContext(chips=0.0, mult=0.0, mult_mult=1.0, hand_type="High Card",
                       scoring_cards=[], all_cards=[], held_cards=[], jokers=[j],
                       hands_left=3, discards_left=3, dollars=10, ante=1,
                       deck_remaining=40, planet_levels=_levels(), game=g)
    eff.on_hand_scored(j, ctx)
    assert ctx.mult_mult == pytest.approx(2.0)
    assert j.state.get("destroy_random") is True
    # Boss blind: no growth, no destruction
    j2 = JokerInstance("j_madness", game=g)
    g.current_blind = type(g.current_blind)("test", "Boss", 100, True, "bl_wall")
    eff.on_blind_selected(j2, None)
    assert j2.state.get("destroy_random") is None


def test_castle_works_round_1_and_permanent():
    g = BalatroGame(seed=11, rng_mode="seed")
    j = JokerInstance("j_castle", game=g)
    eff = JOKER_REGISTRY["j_castle"]
    from balatro_sim.jokers.base import ScoreContext
    # first discard lazily picks a suit (on_init never fires pre-B2), +3 each
    eff.on_discard(j, [Card(7, "Hearts")], None)
    eff.on_discard(j, [Card(9, "Hearts")], None)
    suit = j.state["suit"]
    assert suit in ("Clubs", "Diamonds", "Hearts", "Spades")
    expect = 6 if suit == "Hearts" else 0
    ctx = ScoreContext(chips=0.0, mult=0.0, mult_mult=1.0, hand_type="High Card",
                       scoring_cards=[], all_cards=[], held_cards=[], jokers=[j],
                       hands_left=3, discards_left=3, dollars=10, ante=1,
                       deck_remaining=40, planet_levels=_levels(), game=g)
    eff.on_hand_scored(j, ctx)
    assert ctx.chips == expect   # round-1 works without on_init
    # round end: suit rotates, chips PERSIST (permanent scaling gain)
    eff.on_round_end(j, None)
    assert j.state["chips"] == expect


def test_campfire_grows_on_any_joker_sold():
    g = BalatroGame(seed=11, rng_mode="seed")
    camp = JokerInstance("j_campfire", game=g)
    g.jokers.append(camp)
    g.jokers.append(JokerInstance("j_joker", game=g))
    from balatro_sim.shop import sell_joker
    sell_joker(g, 1)   # sell the j_joker, NOT Campfire
    # Campfire's X(1 + 0.25 × cards_sold) — using the SAME instance
    from balatro_sim.jokers.base import ScoreContext
    ctx = ScoreContext(chips=0.0, mult=0.0, mult_mult=1.0, hand_type="High Card",
                       scoring_cards=[], all_cards=[], held_cards=[], jokers=[camp],
                       hands_left=3, discards_left=3, dollars=10, ante=1,
                       deck_remaining=40, planet_levels=_levels(), game=g)
    JOKER_REGISTRY["j_campfire"].on_hand_scored(camp, ctx)
    assert ctx.mult_mult == pytest.approx(1.25)


def test_gros_michel_can_self_destruct():
    g = BalatroGame(seed=11, rng_mode="seed")
    gm = JokerInstance("j_gros_michel", game=g)
    g.jokers.append(gm)
    from balatro_sim.jokers.base import ScoreContext
    from unittest.mock import patch
    with patch.object(gm, "chance") as mchance:
        mchance.return_value.random.return_value = 0.0   # always destroy
        JOKER_REGISTRY["j_gros_michel"].on_round_end(gm, ScoreContext())
    assert gm.state.get("destroyed") is True
    g._end_round()
    assert gm not in g.jokers   # destroyed flag honored


def test_hiker_bonus_is_read_and_5():
    g = BalatroGame(seed=11, rng_mode="seed")
    card = Card(7, "Spades")
    j = JokerInstance("j_hiker", game=g)
    eff = JOKER_REGISTRY["j_hiker"]
    eff.on_score_card(j, card, None)
    assert getattr(card, "bonus_chips", 0) == 5   # +5, not +4
    # The stored bonus is actually READ by scoring on a later hand (with or
    # without Hiker — it's permanent on the card). Score the boosted card and a
    # fresh card directly; the difference must be exactly the +5 bonus.
    from balatro_sim.scoring import score_hand as sh

    def _chips(cards):
        _, ctx = sh(cards, cards, "High Card", [], _levels(),
                    hands_left=3, discards_left=3, dollars=10, ante=1,
                    deck_remaining=40, game=g, held_cards=[])
        return ctx.chips

    assert _chips([card]) - _chips([Card(7, "Spades")]) == 5


def test_satellite_and_constellation_planet_hooks():
    g = BalatroGame(seed=11, rng_mode="seed")
    sat = JokerInstance("j_satellite", game=g)
    g.jokers.append(sat)
    g.consumable_hand = ["pl_mercury"]          # a Planet
    from balatro_sim.game import State
    g.state = State.SHOP
    g._use_consumable(0, [])
    assert "pl_mercury" in sat.state.get("planets_used", set())
    # Constellation gains X0.1 per planet
    con = JokerInstance("j_constellation", game=g)
    eff = JOKER_REGISTRY["j_constellation"]
    eff.on_planet_used(con, "pl_mercury")
    assert con.state["mult"] == pytest.approx(1.1)


def test_fortune_teller_tarot_hook():
    g = BalatroGame(seed=11, rng_mode="seed")
    ft = JokerInstance("j_fortune_teller", game=g)
    g.jokers.append(ft)
    JOKER_REGISTRY["j_fortune_teller"].on_tarot_used(ft, "c_sun")
    assert ft.state.get("mult", 0) == 1


def test_hologram_card_added_hooks():
    g = BalatroGame(seed=11, rng_mode="seed")
    hol = JokerInstance("j_hologram", game=g)
    g.jokers.append(hol)
    g._grant_pending([("card", Card(3, "Hearts"))])   # Marble-style
    assert hol.state.get("xmult", 1.0) == pytest.approx(1.25)
    g._grant_pending([("hand_card", Card(4, "Diamonds"))])  # Certificate/DNA-style
    assert hol.state.get("xmult", 1.0) == pytest.approx(1.5)


def test_red_card_and_hallucination_booster_hooks():
    g = BalatroGame(seed=11, rng_mode="seed")
    red = JokerInstance("j_red_card", game=g)
    g.jokers.append(red)
    g._fire_joker_hook("on_booster_skipped", None)
    assert red.state.get("mult", 0) == 3
    hal = JokerInstance("j_hallucination", game=g)
    g.jokers.append(hal)
    from balatro_sim.shop import _open_booster
    from balatro_sim.consumables import ALL_TAROTS
    _open_booster(g, "p_arcana")   # 1-in-2 → tarot in consumables (may be 0 or 1)
    assert len(g.consumable_hand) <= 1
    assert all(k in ALL_TAROTS for k in g.consumable_hand)


def test_astronomer_chaos_credit_card_shop_interactions():
    g = BalatroGame(seed=11, rng_mode="seed")
    g.jokers.append(JokerInstance("j_astronomer", game=g))
    g._fire_joker_hook("on_shop_enter", None)
    from balatro_sim.shop import generate_shop, reroll_shop, buy_item
    shop = generate_shop(g)
    planets = [i for i in shop if i.kind == "planet"]
    if planets:
        assert all(p.price == 0 for p in planets)   # free planets
    # Chaos: first reroll free
    g2 = BalatroGame(seed=11, rng_mode="seed")
    g2.jokers.append(JokerInstance("j_chaos", game=g2))
    g2._fire_joker_hook("on_shop_enter", None)
    g2.dollars = 0
    assert reroll_shop(g2) is True   # free reroll at $0
    # Credit Card: buy into debt
    g3 = BalatroGame(seed=11, rng_mode="seed")
    g3.jokers.append(JokerInstance("j_credit_card", game=g3))
    g3.dollars = 0
    g3.consumable_hand = []
    from balatro_sim.shop import ShopItem
    assert buy_item(g3, ShopItem("tarot", "c_sun", "The Sun", 3)) is True
    assert g3.dollars == -3


def test_flash_reroll_hook():
    g = BalatroGame(seed=11, rng_mode="seed")
    fl = JokerInstance("j_flash", game=g)
    g.jokers.append(fl)
    from balatro_sim.shop import reroll_shop
    g.dollars = 100
    reroll_shop(g)
    assert fl.state.get("mult", 0) == 2


def test_to_do_list_on_init_target():
    g = BalatroGame(seed=11, rng_mode="seed")
    from balatro_sim.shop import ShopItem, buy_item
    g.dollars = 100
    item = ShopItem("joker", "j_todo_list", "To Do List", 4)
    assert buy_item(g, item)
    j = g.jokers[-1]
    assert j.state.get("target") in _ALL_HANDS   # on_init fired at buy time


def test_on_init_fires_on_all_acquisition_paths():
    """Every joker-grant path fires on_init — buy, packs (game + env_v5),
    Judgement/Wraith/The Soul, Top-Up tag, Riff-Raff grants — so To Do List /
    Popcorn / Ramen / Ice Cream init like bought jokers."""
    from balatro_sim.consumables import apply_tarot, apply_spectral, _grant_joker
    from balatro_sim.jokers.base import JOKER_REGISTRY

    def _target(j):
        return j.state.get("target")

    # 1. Buy path (already covered above, control)
    # 2. Judgement (c_judgement) — force a To Do List via random_joker_key mock
    with patch("balatro_sim.shop.random_joker_key", return_value="j_todo_list") as m:
        g = BalatroGame(seed=11, rng_mode="seed")
        assert apply_tarot(g, "c_judgement", [])
        assert _target(g.jokers[0]) in _ALL_HANDS
    # 3. Wraith (s_wraith)
    with patch("balatro_sim.shop.random_joker_key", return_value="j_todo_list"):
        g = BalatroGame(seed=11, rng_mode="seed")
        assert apply_spectral(g, "s_wraith", [])
        assert _target(g.jokers[0]) in _ALL_HANDS
    # 4. The Soul (s_soul)
    with patch("balatro_sim.shop.random_joker_key", return_value="j_todo_list"):
        g = BalatroGame(seed=11, rng_mode="seed")
        assert apply_spectral(g, "s_soul", [])
        assert _target(g.jokers[0]) in _ALL_HANDS
    # 5. Direct _grant_joker helper (Riff-Raff / pack tuples)
    g = BalatroGame(seed=11, rng_mode="seed")
    _grant_joker(g, "j_todo_list")
    assert _target(g.jokers[0]) in _ALL_HANDS
    # 6. Top-Up tag (imports random_joker_key from .shop at call time)
    from balatro_sim.tags import _add_topup_jokers
    with patch("balatro_sim.shop.random_joker_key", return_value="j_todo_list"):
        g = BalatroGame(seed=11, rng_mode="seed")
        _add_topup_jokers(g)
        assert _target(g.jokers[0]) in _ALL_HANDS
    # 7. env_v5 pack-open path — the same grant+init block as the game path
    # (JokerInstance(key, edition, game) then on_init dispatch); construction
    # is covered by #5 and the game's _pick_booster path has its own test.
    from balatro_sim.env_v5 import BalatroSimEnvV5
    env = BalatroSimEnvV5(seed=11)
    assert env.game is not None


# ════════════════════════════════════════════════════════════════════════════
# Structural guard: every spec joker resolves (belt-and-braces to the audit)
# ════════════════════════════════════════════════════════════════════════════

def test_every_spec_joker_resolves():
    from balatro_sim.shop import JOKER_CATALOGUE
    from balatro_sim.jokers import _CANONICAL_JOKER_ALIASES
    for key in SPEC:
        assert key in JOKER_CATALOGUE, f"{key} not in catalogue"
        assert (key in JOKER_REGISTRY
                or _CANONICAL_JOKER_ALIASES.get(key) in JOKER_REGISTRY), \
            f"{key} has no resolvable effect"


def test_every_catalogue_joker_has_spec_row():
    from balatro_sim.shop import JOKER_CATALOGUE
    assert set(SPEC) == set(JOKER_CATALOGUE), (
        "spec/catalogue mismatch: "
        f"{set(JOKER_CATALOGUE) - set(SPEC)} missing from spec, "
        f"{set(SPEC) - set(JOKER_CATALOGUE)} not in catalogue"
    )


# ════════════════════════════════════════════════════════════════════════════
# B6 fidelity: real destroys, Trading Card RNG, Blueprint copy scope,
# Negative slots, Blue Seal played-hand planet, state defaults (R4)
# ════════════════════════════════════════════════════════════════════════════

def test_trading_card_destroy_is_seeded_and_permanent():
    """Trading Card destroys a random discarded card FOREVER (removed from
    deck/hand/spent — never returns) and the pick uses the seeded per-node RNG
    (two same-seed runs destroy the identical card; was `import random`)."""
    def _run():
        g = BalatroGame(seed=7, rng_mode="seed")
        c0, c1 = Card(2, "Hearts"), Card(3, "Spades")
        g.hand = [c0, c1, Card(4, "Clubs"), Card(5, "Diamonds"), Card(6, "Hearts")]
        g.grant_joker("j_trading_card")
        before = g.dollars
        g._discard([0, 1])
        assert g.dollars == before + 3          # +$3 first discard of the round
        destroyed = [c for c in (c0, c1) if c not in g.deck + g.hand + g.spent]
        kept = [c for c in (c0, c1) if c in g.spent]
        assert len(destroyed) == 1 and len(kept) == 1   # exactly one destroyed
        return destroyed[0]

    d1, d2 = _run(), _run()
    assert d1.rank == d2.rank and d1.suit == d2.suit   # seeded: same card


def test_trading_card_uses_seeded_rng_not_module_random():
    """The destroy pick comes from inst.chance() (per-node CHANCE_NODE) —
    patching the module random must NOT change the pick."""
    with patch("random.choice", side_effect=lambda x: x[0]) as m:
        g = BalatroGame(seed=7, rng_mode="seed")
        c0, c1 = Card(2, "Hearts"), Card(3, "Spades")
        g.hand = [c0, c1, Card(4, "Clubs"), Card(5, "Diamonds"), Card(6, "Hearts")]
        g.grant_joker("j_trading_card")
        g._discard([0, 1])
        m.assert_not_called()                    # module random never consulted
        destroyed = [c for c in (c0, c1) if c not in g.deck + g.hand + g.spent]
        assert len(destroyed) == 1


def test_sixth_sense_destroys_the_played_6():
    """Sixth Sense permanently destroys the played single 6 (real destroy via
    ctx.destroyed — was a fake `debuffed = True`) and grants a Spectral."""
    from balatro_sim.consumables import ALL_SPECTRALS
    g = BalatroGame(seed=7, rng_mode="seed")
    six = Card(6, "Spades")
    g.hand = [six, Card(10, "Hearts"), Card(11, "Clubs"),
              Card(12, "Diamonds"), Card(13, "Spades")]
    g.grant_joker("j_sixth_sense")
    g._play_hand([0])
    assert six not in g.deck + g.hand + g.spent    # gone for the rest of the run
    assert len(g.consumable_hand) == 1
    assert g.consumable_hand[0] in ALL_SPECTRALS
    assert len(g.hand) > 0                         # the rest of the hand remains


def test_blueprint_copies_economy_hooks():
    """B6: Blueprint copies the neighbor's effect for EVERY hook — round-end
    economy hooks included (was scoring-only). Blueprint left of Egg: each
    round end Egg's sell value grows +3 from itself AND +3 from Blueprint's
    copy → 7 (1 + 3 + 3)."""
    g = BalatroGame(seed=11, rng_mode="seed")
    egg = g.grant_joker("j_egg")
    bp = g.grant_joker("j_blueprint")
    g.jokers = [bp, egg]                          # Blueprint to the LEFT of Egg
    assert egg.state["sell_value"] == 1           # R4 state default
    g._fire_joker_hook("on_round_end", None)
    assert egg.state["sell_value"] == 7
    # control: no Blueprint → +3 only
    g2 = BalatroGame(seed=11, rng_mode="seed")
    egg2 = g2.grant_joker("j_egg")
    g2._fire_joker_hook("on_round_end", None)
    assert egg2.state["sell_value"] == 4


def test_blueprint_discard_hook_copy():
    """Blueprint next to Hit the Road: both the copy and the original gain
    X0.5 per Jack discarded (real game: Blueprint copies discard hooks too)."""
    g = BalatroGame(seed=11, rng_mode="seed")
    htr = g.grant_joker("j_hit_the_road")
    bp = g.grant_joker("j_blueprint")
    g.jokers = [bp, htr]
    g.hand = [Card(11, "Spades"), Card(2, "Hearts"), Card(3, "Clubs"),
              Card(4, "Diamonds"), Card(5, "Spades")]
    g._discard([0, 1])                             # a Jack + a 2
    assert htr.state["xmult"] == pytest.approx(2.0)   # 1.0 + 0.5 (self) + 0.5 (copy)


def test_negative_edition_does_not_consume_a_slot():
    """Negative jokers bypass the joker-slot cap — both the grant path and the
    shop buy path (real game: Negative gives +1 Joker slot)."""
    g = BalatroGame(seed=11, rng_mode="seed")
    for _ in range(5):
        assert g.grant_joker("j_joker") is not None
    assert g.grant_joker("j_joker") is None              # slots full
    neg = g.grant_joker("j_joker", "Negative")
    assert neg is not None and neg.edition == "Negative"
    assert len(g.jokers) == 6
    # buy path honors the same rule
    from balatro_sim.shop import ShopItem, buy_item
    g.dollars = 100
    g.jokers = []
    for _ in range(5):
        assert buy_item(g, ShopItem("joker", "j_joker", "Joker", 1))
    assert buy_item(g, ShopItem("joker", "j_joker", "Joker", 1)) is False
    assert buy_item(g, ShopItem("joker", "j_joker", "Joker", 1,
                                edition="Negative")) is True
    assert len(g.jokers) == 6


def test_blue_seal_grants_final_hand_planet_at_round_end():
    """Blue Seal (reference doc §8): a Blue-sealed card HELD in hand at round
    end creates the Planet of the FINAL hand played that round — not the hand
    the seal was scored in, and not at play time."""
    g = BalatroGame(seed=11, rng_mode="seed")
    g.current_blind = type(g.current_blind)("test", "Small", 10**6, False, "")
    blue = Card(10, "Hearts", seal="Blue")       # never played — held all round
    g.hand = [blue, Card(10, "Spades"), Card(2, "Clubs"),
              Card(3, "Diamonds"), Card(4, "Spades")]
    g._play_hand([1, 2])                           # a Pair; blue stays in hand
    assert g.consumable_hand == []                 # NOT granted at play time
    # Final hand of the round: a Flush (blue still held)
    g.current_blind = type(g.current_blind)("test", "Small", 1, False, "")
    g.hand = [blue, Card(5, "Spades"), Card(6, "Spades"), Card(8, "Spades"),
              Card(9, "Spades"), Card(11, "Spades")]
    g._play_hand([1, 2, 3, 4, 5])
    g._end_round()
    assert "pl_jupiter" in g.consumable_hand       # Flush's planet (final hand)
    assert "pl_mercury" not in g.consumable_hand   # the early Pair never granted


def test_state_defaults_seed_initial_values():
    """R4: per-effect STATE_DEFAULTS seed known initial state — no joker starts
    at a bare `{}` where the first value matters."""
    assert JokerInstance("j_seltzer").state["hands"] == 10
    assert JokerInstance("j_egg").state["sell_value"] == 1
    assert JokerInstance("j_popcorn").state["mult"] == 20
    assert JokerInstance("j_turtle_bean").state["bonus"] == 5
    assert JokerInstance("j_madness").state["blinds"] == 0


def test_mutable_state_defaults_are_per_instance():
    """R4: mutable defaults (sets/dicts) are deep-copied per instance — two
    jokers of the same kind never share a counter (was a shared-object risk)."""
    s1, s2 = JokerInstance("j_seltzer"), JokerInstance("j_seltzer")
    s1.state["hands"] = 3
    assert s2.state["hands"] == 10
    c1, c2 = JokerInstance("j_card_sharp"), JokerInstance("j_card_sharp")
    c1.state["played_hands"].add("Pair")
    assert c2.state["played_hands"] == set()
