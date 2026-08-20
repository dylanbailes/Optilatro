"""test_agent_v9.py — V9 Layer-0 heuristic solver + rollout primitives.

Covers:
  - the evaluation oracle is side-effect-free (never mutates the live game or
    consumes the run's seed stream) — the core correctness invariant;
  - rollout determinism (same seed + policy -> identical outcome);
  - clone_game fork independence;
  - per-hand "just enough" play (cheapest clearing combo, not the greediest);
  - exact-discard EV (discard set -> known resulting hand);
  - shop buy / money-gate / boss-reroll decisions;
  - booster picks;
  - run-level sanity: the heuristic beats random on a small seed bank.
"""
from __future__ import annotations

import pytest

from balatro_sim.game import BalatroGame, State
from balatro_sim.card import Card
from balatro_sim.constants import BLIND_CHIPS
from balatro_sim.shop import ShopItem
from balatro_sim.rollout import clone_game, rollout
from balatro_sim.agent_v9 import (
    ACTIVE_PARAMS, HeuristicV9, RandomPolicy, _structure_pool, best_discard,
    decide_booster, decide_consumable, decide_hand, decide_shop,
    enumerate_combos, deck_condition_bonus, eval_hand_score, joker_value,
    lifecycle_bonus, maybe_use_planet, next_blind_target, pack_value,
    power_tilt, scored_plays, spectral_value, tarot_value, worth_spending,
)


# ── eval oracle correctness ─────────────────────────────────────────────────

def test_eval_oracle_never_mutates_or_draws():
    """Evaluations must not change joker state, cards, or consume RNG draws."""
    g = BalatroGame(seed=11, rng_mode="seed")
    g.grant_joker("j_green_joker")   # a scaling joker whose hooks mutate state
    g.grant_joker("j_hiker")         # on_score_card writes card.bonus_chips
    g.step({"type": "play_blind"})
    assert g.state == State.SELECTING_HAND

    g.rng.enable_tracing()
    hand = list(g.hand)
    joker_states = [(j.key, dict(j.state)) for j in g.jokers]
    hand_bonus = {id(c): getattr(c, "bonus_chips", 0) for c in hand}

    for combo, ht, sc, cards in enumerate_combos(hand, ""):
        held = [c for c in hand if c not in cards]
        eval_hand_score(g, ht, sc, cards, held_cards=held)

    assert g.rng.records == []                      # no RNG draws consumed
    assert [(j.key, dict(j.state)) for j in g.jokers] == joker_states
    assert {id(c): getattr(c, "bonus_chips", 0) for c in g.hand} == hand_bonus


def test_eval_oracle_deterministic():
    """Same inputs -> same score (isolated throwaway RNG is seeded)."""
    g = BalatroGame(seed=3, rng_mode="seed")
    g.step({"type": "play_blind"})
    hand = list(g.hand)
    combo, ht, sc, cards = enumerate_combos(hand, "")[0]
    held = [c for c in hand if c not in cards]
    a = eval_hand_score(g, ht, sc, cards, held_cards=held)
    b = eval_hand_score(g, ht, sc, cards, held_cards=held)
    assert a == b


# ── rollout / fork primitives ───────────────────────────────────────────────

def test_rollout_deterministic():
    o1 = rollout(BalatroGame(seed=7, rng_mode="seed"), HeuristicV9())
    o2 = rollout(BalatroGame(seed=7, rng_mode="seed"), HeuristicV9())
    assert o1 == o2
    assert o1["truncated"] is False


def test_clone_game_is_independent():
    g = BalatroGame(seed=5, rng_mode="seed")
    g.step({"type": "play_blind"})
    fork = clone_game(g)
    g.rng.enable_tracing()

    # Play the fork to GAME_OVER with a random policy (rollout has the step
    # caps); the original must not move at all.
    rollout(fork, RandomPolicy(), max_steps=50_000)

    assert g.state == State.SELECTING_HAND
    assert g.rng.records == []
    assert g.dollars == BalatroGame(seed=5, rng_mode="seed").dollars


# ── per-hand decisions ──────────────────────────────────────────────────────

def _game_in_hand():
    g = BalatroGame(seed=11, rng_mode="seed")
    g.step({"type": "play_blind"})
    assert g.state == State.SELECTING_HAND
    return g


def test_just_enough_plays_cheapest_clearing():
    """When both a Pair (2 cards) and a Flush (5 cards) clear, play the Pair."""
    g = _game_in_hand()
    g.jokers = []
    g.current_blind.chips_target = 50
    g.hand = [
        Card(14, "Hearts"), Card(2, "Hearts"), Card(3, "Hearts"),
        Card(4, "Hearts"), Card(5, "Hearts"), Card(14, "Spades"),
        Card(7, "Clubs"), Card(9, "Diamonds"),
    ]
    act = decide_hand(g)
    assert act["type"] == "play"
    assert len(act["cards"]) == 2, f"expected cheapest clearing play, got {act}"


def test_greedy_play_when_nothing_clears():
    """Unreachable target -> play the highest-scoring combo (the flush)."""
    g = _game_in_hand()
    g.jokers = []
    g.current_blind.chips_target = 10_000
    g.hand = [
        Card(14, "Hearts"), Card(2, "Hearts"), Card(3, "Hearts"),
        Card(4, "Hearts"), Card(5, "Hearts"), Card(14, "Spades"),
        Card(7, "Clubs"), Card(9, "Diamonds"),
    ]
    act = decide_hand(g)
    assert act["type"] == "play"
    assert len(act["cards"]) == 5, f"expected the flush, got {act}"


def test_discard_ev_chases_flush_from_composition():
    """4 hearts + 4 junk with MANY hearts remaining in the deck: a 1-2 card
    junk discard is +EV (the 5th heart arrives with high probability) — the
    human-fair expected-value discard over the KNOWN composition (a human
    knows which cards remain, never the draw order)."""
    g = _game_in_hand()
    g.jokers = []
    g.current_blind.chips_target = 10_000  # nothing clears -> discard branch
    g.discards_left = 3
    g.hand = [
        Card(14, "Hearts"), Card(13, "Hearts"), Card(12, "Hearts"),
        Card(11, "Hearts"), Card(2, "Spades"), Card(3, "Clubs"),
        Card(4, "Diamonds"), Card(5, "Clubs"),
    ]
    # 20 hearts + 24 junk in the deck: a random draw finds a heart ~45% of
    # the time, so the flush EV dominates the current best hand.
    g.deck = ([Card(r, "Hearts", id=f"H{i}") for i, r in
               enumerate([2, 3, 4, 5, 6, 7, 8, 9, 10] * 2 + [14, 13])]
              + [Card(r, s, id=f"J{i}") for i, (r, s) in enumerate(
                  (r, s) for r in range(2, 10)
                  for s in ("Spades", "Clubs", "Diamonds"))])

    dset, dscore = best_discard(g)
    # Structure-aware v3: the pool is ONLY the 4 junk cards (the flush suit
    # is kept intact — never discarded), and a flush chase can discard ALL
    # of them (the old quality-weakest pool capped at 2 and broke the suit).
    assert 1 <= len(dset) <= 4, f"expected a 1-4 card discard, got {dset}"
    # only junk cards are discarded — never one of the 4 hearts
    assert all(g.hand[i].suit != "Hearts" for i in dset)
    assert dscore >= 100, f"expected the flush-chase EV, got {dscore}"


def test_discard_target_aware_gambles_when_short():
    """Short of the round target (base < per-hand share), the target-aware
    term values a discard by P(clear) too — the gamble fires — and the
    target-aware value is never below the plain mean value. This recovers
    the exact-draw agent's aggressive discarding without the draw order."""
    import balatro_sim.agent_v9 as A
    g = _game_in_hand()
    g.jokers = []
    g.discards_left = 3
    g.hands_left = 3
    g.chips_scored = 0
    g.current_blind.chips_target = 300   # per-hand share 100 > base ~60 -> short
    g.hand = [
        Card(14, "Hearts"), Card(13, "Hearts"), Card(12, "Hearts"),
        Card(11, "Hearts"), Card(2, "Spades"), Card(3, "Clubs"),
        Card(4, "Diamonds"), Card(5, "Clubs"),
    ]
    g.deck = ([Card(r, "Hearts", id=f"H{i}") for i, r in
               enumerate([2, 3, 4, 5, 6, 7, 8, 9, 10] * 2 + [14, 13])]
              + [Card(r, s, id=f"J{i}") for i, (r, s) in enumerate(
                  (r, s) for r in range(2, 10)
                  for s in ("Spades", "Clubs", "Diamonds"))])

    old = A.ACTIVE_PARAMS["discard_target_aware"]
    try:
        A.ACTIVE_PARAMS["discard_target_aware"] = True
        dset, dscore = best_discard(g)
        assert dset, "target-aware: the flush gamble should fire when short"
        assert all(g.hand[i].suit != "Hearts" for i in dset)

        A.ACTIVE_PARAMS["discard_target_aware"] = False
        _, dscore_plain = best_discard(g)
    finally:
        A.ACTIVE_PARAMS["discard_target_aware"] = old
    # target-aware value = p*share + (1-p)*mean >= plain mean value
    assert dscore >= dscore_plain


def test_structure_pool_never_breaks_pairs():
    """Three pairs + a singleton: the structural pool is the singletons
    ONLY — a full-house chase never breaks a pair (seed 65 held
    8C 8D AH AS KD KS and the old flush-first ordering discarded the 8s and
    As to chase a 1-card spade flush, dying playing High Card 16)."""
    g = _game_in_hand()
    g.hand = [
        Card(8, "Clubs"), Card(8, "Diamonds"), Card(14, "Hearts"),
        Card(14, "Spades"), Card(13, "Diamonds"), Card(13, "Spades"),
        Card(7, "Hearts"), Card(11, "Diamonds"),
    ]
    sp = _structure_pool(g.hand, 4, 4, 2)
    assert sp is not None and sp[1][0] == "full_house"
    kept = {i for i in range(len(g.hand)) if i not in sp[0]}
    # every pair card is kept
    for i in kept:
        assert sum(1 for c in g.hand if c.rank == g.hand[i].rank) >= 2
    dset, _ = best_discard(g)
    assert all(sum(1 for c in g.hand if c.rank == g.hand[i].rank) < 2
               for i in dset), f"discard broke a pair: {dset}"


def test_good_hand_plays_instead_of_discarding():
    """A hand scoring >= discard_play_good_hand of the REMAINING TARGET is
    played, not held to chase a bigger hand (seed 228 held a 240 straight
    while its flush line discarded 4H 5H 6S 8H to chase a 5-heart flush,
    broke the straight, and died 298/300)."""
    g = _game_in_hand()
    g.jokers = []
    g.discards_left = 3
    g.hands_left = 4
    g.chips_scored = 0
    g.current_blind.chips_target = 300
    g.hand = [
        Card(4, "Hearts"), Card(5, "Hearts"), Card(6, "Diamonds"),
        Card(6, "Hearts"), Card(6, "Spades"), Card(7, "Spades"),
        Card(8, "Hearts"), Card(12, "Spades"),
    ]
    # best hand is the straight 4-5-6-7-8 (240/300 = 80% >= 0.50)
    act = decide_hand(g)
    assert act["type"] == "play", f"a 240 straight must be played, got {act}"
    assert len(act["cards"]) == 5


def test_weak_hand_holds_until_clear():
    """A hand far below the target (a 40 pair vs 300) with hands AND
    discards remaining is held — the agent discards instead of burning a
    hand on a non-clearing play (seed 202 played its 200/300 straight while
    2 hands + 1 discard remained and died 290/300)."""
    g = _game_in_hand()
    g.jokers = []
    g.discards_left = 3
    g.hands_left = 4
    g.chips_scored = 0
    g.current_blind.chips_target = 300
    g.hand = [
        Card(3, "Spades"), Card(4, "Diamonds"), Card(5, "Clubs"),
        Card(5, "Diamonds"), Card(6, "Hearts"), Card(11, "Hearts"),
        Card(13, "Spades"), Card(10, "Diamonds"),
    ]
    act = decide_hand(g)
    assert act["type"] == "discard", f"a 40 pair vs 300 must be held, got {act}"


def test_discard_ev_is_order_independent():
    """The discard EV must depend ONLY on the deck's composition: two decks
    with the SAME cards in DIFFERENT orders give a BYTE-IDENTICAL decision
    and EV. A draw-order peek (the old deck[-i-1] exact draw) breaks this."""
    def decision(deck):
        g = _game_in_hand()
        g.jokers = []
        g.current_blind.chips_target = 10_000
        g.discards_left = 3
        g.hand = [
            Card(14, "Hearts"), Card(13, "Hearts"), Card(12, "Hearts"),
            Card(11, "Hearts"), Card(2, "Spades"), Card(3, "Clubs"),
            Card(4, "Diamonds"), Card(5, "Clubs"),
        ]
        g.deck = list(deck)
        return best_discard(g)

    hearts = [Card(r, "Hearts", id=f"H{i}") for i, r in
              enumerate([2, 3, 4, 5, 6, 7, 8, 9, 10] * 2 + [14, 13])]
    junk = [Card(r, s, id=f"J{i}") for i, (r, s) in enumerate(
        (r, s) for r in range(2, 10) for s in ("Spades", "Clubs", "Diamonds"))]
    deck = hearts + junk
    a = decision(deck)
    b = decision(list(reversed(deck)))
    assert a == b, f"discard decision depends on deck ORDER: {a} vs {b}"
    assert a[0], "expected a discard in the heart-rich fixture"


def test_planet_used_for_intended_play():
    g = _game_in_hand()
    g.jokers = []
    g.consumable_hand = ["pl_saturn"]  # Saturn levels Straights (pl_* keys)
    # hand with a straight available
    g.hand = [Card(10, "Hearts"), Card(9, "Spades"), Card(8, "Clubs"),
              Card(7, "Diamonds"), Card(6, "Hearts"), Card(2, "Spades"),
              Card(3, "Clubs"), Card(4, "Diamonds")]
    g.current_blind.chips_target = 10_000
    act = decide_hand(g)
    assert act["type"] == "use_consumable", f"expected planet use, got {act}"


# ── shop decisions ──────────────────────────────────────────────────────────

def _shop_game():
    g = BalatroGame(seed=5, rng_mode="seed")
    g.state = State.SHOP
    g.dollars = 20
    return g


def test_shop_buys_high_value_joker():
    g = _shop_game()
    g.current_shop = [
        ShopItem("joker", "j_joker", "Joker", 2),
        ShopItem("joker", "j_egg", "Egg", 4),
    ]
    act = decide_shop(g, 0)
    assert act["type"] == "buy"
    assert act["item_idx"] == 0  # Joker (+4 mult) beats Egg's value


def test_shop_leaves_when_nothing_worth_buying():
    g = _shop_game()
    g.dollars = 3
    g.current_shop = [ShopItem("joker", "j_joker", "Joker", 20)]  # unaffordable
    act = decide_shop(g, 0)
    assert act["type"] in ("leave_shop", "reroll")


def test_shop_boss_reroll_against_counter_boss():
    """The reroll fires in the shop BEFORE the boss: the upcoming boss is
    pre-selected (game.next_boss_key), and a BAD_BOSSES key triggers the
    Director's Cut reroll — not the old post-boss (current_blind.kind ==
    "Boss") timing."""
    g = _shop_game()
    g.vouchers.add("v_directors_cut")
    g.blind_idx = 1
    g.next_boss_key = "bl_needle"   # 1 hand — hard counter, upcoming
    g.current_shop = []
    act = decide_shop(g, 0)
    assert act["type"] == "reroll_boss"

    # no upcoming boss -> no reroll (not even after a beaten boss)
    g2 = _shop_game()
    g2.vouchers.add("v_directors_cut")
    g2.current_blind.kind = "Boss"
    g2.current_blind.boss_key = "bl_needle"   # beaten boss: not the target
    g2.current_shop = []
    assert decide_shop(g2, 0)["type"] != "reroll_boss"


def test_shop_matador_buy_respects_upcoming_boss():
    """Boss-layer pass: Matador is bought only before a boss that actually
    triggers him (key-specific boss_counter_value at decide_shop level)."""
    import balatro_sim.agent_v9 as A
    old_b = A.ACTIVE_PARAMS["boss_buy_bonus"]
    old_w = A.ACTIVE_PARAMS["graph_weight"]
    try:
        A.ACTIVE_PARAMS["boss_buy_bonus"] = 0.35
        A.ACTIVE_PARAMS["graph_weight"] = 0.0
        # The Wall never triggers Matador -> not bought
        g = _shop_game()
        g.blind_idx = 1
        g.next_boss_key = "bl_wall"
        g.current_shop = [ShopItem("joker", "j_matador", "Matador", 5)]
        assert decide_shop(g, 0)["type"] != "buy"
        # The Ox triggers Matador -> the boss term pushes it over the threshold
        g2 = _shop_game()
        g2.blind_idx = 1
        g2.next_boss_key = "bl_ox"
        g2.current_shop = [ShopItem("joker", "j_matador", "Matador", 5)]
        act = decide_shop(g2, 0)
        assert act["type"] == "buy" and act["item_idx"] == 0
    finally:
        A.ACTIVE_PARAMS["boss_buy_bonus"] = old_b
        A.ACTIVE_PARAMS["graph_weight"] = old_w


def test_worth_spending_money_gate():
    g = _shop_game()
    g.ante = 5
    g.dollars = 12
    # $10 spend drops two interest bands with low value -> blocked
    assert worth_spending(g, 10, 0.05) is False
    # ...but high value passes
    assert worth_spending(g, 10, 0.30) is True
    # one-band spend always fine
    assert worth_spending(g, 2, 0.0) is True
    # broke -> spend freely
    g.dollars = 4
    assert worth_spending(g, 4, 0.0) is True


def test_booster_picks_good_jokers():
    g = BalatroGame(seed=5, rng_mode="seed")
    g.state = State.BOOSTER_OPEN
    g.booster_choices = [("joker", "j_joker", "None"),
                         ("joker", "j_egg", "None")]
    g.booster_picks_remaining = 2
    act = decide_booster(g)
    assert act["type"] == "pick_booster"
    assert sorted(act["indices"]) == [0, 1]


# ── tarot / spectral usage ─────────────────────────────────────────────────

HAND8 = [Card(14, "Spades"), Card(13, "Spades"), Card(2, "Clubs"),
         Card(3, "Diamonds"), Card(4, "Hearts"), Card(5, "Clubs"),
         Card(6, "Diamonds"), Card(7, "Hearts")]


def _cons_game(state=State.SELECTING_HAND, hand=None):
    g = BalatroGame(seed=11, rng_mode="seed")
    g.state = state
    g.jokers = []
    g.hand = list(hand) if hand is not None else list(HAND8)
    return g


def test_tarot_enhance_targets_best_cards():
    g = _cons_game()
    g.consumable_hand = ["c_empress"]  # Mult on up to 2 cards
    act = decide_consumable(g)
    assert act is not None and act["type"] == "use_consumable"
    assert act["consumable_idx"] == 0
    assert act["target_cards"] == [0, 1]  # A♠ and K♠ are the best two


def test_tarot_suit_conversion_toward_majority():
    g = _cons_game(hand=[Card(14, "Hearts"), Card(13, "Hearts"),
                         Card(12, "Hearts"), Card(2, "Spades"),
                         Card(3, "Clubs"), Card(4, "Diamonds"),
                         Card(5, "Clubs"), Card(6, "Diamonds")])
    g.consumable_hand = ["c_sun"]  # converts up to 3 cards to Hearts
    act = decide_consumable(g)
    assert act is not None
    # the top 3 off-suit cards (by quality) become the conversion targets
    assert sorted(act["target_cards"]) == [5, 6, 7]


def test_tarot_suit_conversion_needs_majority():
    g = _cons_game(hand=[Card(14, "Spades"), Card(13, "Hearts"),
                         Card(12, "Clubs"), Card(11, "Diamonds"),
                         Card(2, "Spades"), Card(3, "Clubs"),
                         Card(4, "Diamonds"), Card(5, "Hearts")])
    g.consumable_hand = ["c_sun"]
    assert decide_consumable(g) is None  # only 2 Hearts < threshold 3


def test_tarot_hanged_man_shop_only():
    g = _cons_game(hand=HAND8)
    g.consumable_hand = ["c_hanged_man"]
    assert decide_consumable(g) is None  # mid-blind: would hurt the hand

    g2 = _cons_game(state=State.SHOP, hand=HAND8)
    g2.consumable_hand = ["c_hanged_man"]
    act = decide_consumable(g2)
    assert act is not None
    assert len(act["target_cards"]) == 2  # destroy the 2 weakest (deck thinning)


def test_tarot_strength_avoids_aces():
    g = _cons_game(hand=[Card(14, "Spades"), Card(14, "Hearts"),
                         Card(2, "Clubs"), Card(3, "Diamonds"),
                         Card(4, "Hearts"), Card(5, "Clubs"),
                         Card(6, "Diamonds"), Card(7, "Hearts")])
    g.consumable_hand = ["c_strength"]
    act = decide_consumable(g)
    assert act is not None
    assert all(g.hand[i].rank < 14 for i in act["target_cards"])


def test_tarot_hermit_money_gate():
    g = _cons_game()
    g.consumable_hand = ["c_hermit"]
    g.dollars = 3
    assert decide_consumable(g) is None  # gain 3 < hermit_min_gain
    g.dollars = 10
    assert decide_consumable(g) is not None
    # Gain = min(dollars, 20) is monotonic — dollars >= 20 is the MAX-gain
    # case and must NOT be skipped by an upper bound.
    g.dollars = 20
    assert decide_consumable(g) is not None
    g.dollars = 35
    assert decide_consumable(g) is not None


def test_tarot_temperance_no_dollar_bound():
    g = _cons_game()
    g.consumable_hand = ["c_temperance"]
    g.jokers = []
    g.dollars = 25
    assert decide_consumable(g) is None  # no sell value -> nothing
    j = g.grant_joker("j_half")
    j.state["sell_value"] = 6  # buy-time field; set it directly
    assert decide_consumable(g) is not None


def test_decide_never_perturbs_run_rng():
    """A full decide() call (hand + shop + consumable inspection) must not
    consume or perturb the run's seed stream — only the isolated eval oracle
    touches RNG, and only on throwaway copies."""
    for setup in ("hand", "shop"):
        g = BalatroGame(seed=11, rng_mode="seed")
        g.step({"type": "play_blind"})
        g.rng.enable_tracing()
        pol = HeuristicV9()
        if setup == "hand":
            act = pol.decide(g)
            assert act.get("type") in ("play", "discard", "use_consumable")
        else:
            # force SHOP: jump to the end of the round
            g.consumable_hand = ["c_hermit"]
            g.dollars = 12
            g.state = State.SHOP
            g.current_shop = []
            act = pol.decide(g)
            # pin the interesting path: the consumable inspection fired
            assert act.get("type") == "use_consumable"
        assert g.rng.records == [], f"decide perturbed the stream in {setup}"


def test_tarot_judgement_slot_gate():
    g = _cons_game()
    g.consumable_hand = ["c_judgement"]
    g.joker_slots = 0
    assert decide_consumable(g) is None       # no room
    g.joker_slots = 5
    assert decide_consumable(g) is not None   # room -> random joker


def test_spectral_black_hole_and_soul():
    g = _cons_game()
    g.consumable_hand = ["s_black_hole"]
    assert decide_consumable(g) is not None   # always worth it

    g2 = _cons_game()
    g2.consumable_hand = ["s_soul"]
    g2.joker_slots = 0
    assert decide_consumable(g2) is None      # slot gate
    g2.joker_slots = 5
    assert decide_consumable(g2) is not None


# ── pack/consumable valuation (V9 heuristic v2) ────────────────────────────

def test_booster_picks_best_tarot():
    """Arcana packs must actually be picked from (the old code skipped every
    tarot choice, wasting the pack) — and the BEST tarot wins."""
    g = BalatroGame(seed=5, rng_mode="seed")
    g.state = State.BOOSTER_OPEN
    g.dollars = 20
    g.booster_choices = ["c_moon", "c_hermit", "c_death"]
    g.booster_picks_remaining = 1
    act = decide_booster(g)
    assert act["type"] == "pick_booster"
    assert act["indices"] == [1]  # Hermit > Death > Moon


def test_booster_picks_spectral_and_skips_risky():
    """Spectral packs must actually yield a spectral (the old code never
    acquired them) — but Ankh/Hex/Ouija/Sigil stay skipped."""
    g = BalatroGame(seed=5, rng_mode="seed")
    g.state = State.BOOSTER_OPEN
    g.booster_choices = ["s_ankh", "s_black_hole"]
    g.booster_picks_remaining = 1
    act = decide_booster(g)
    assert act["type"] == "pick_booster"
    assert act["indices"] == [1]   # Black Hole; Ankh is 0

    g2 = BalatroGame(seed=5, rng_mode="seed")
    g2.state = State.BOOSTER_OPEN
    g2.booster_choices = ["s_ankh", "s_hex", "s_ouija", "s_sigil"]
    g2.booster_picks_remaining = 1
    assert decide_booster(g2)["type"] == "skip_booster"


def test_tarot_suit_conversion_respects_tarot_suit():
    """The Moon (Clubs) must NOT convert cards toward a Hearts majority — the
    old code ignored the tarot's own suit and fragmented the flush build."""
    g = _cons_game(hand=[Card(14, "Hearts"), Card(13, "Hearts"),
                         Card(12, "Hearts"), Card(2, "Spades"),
                         Card(3, "Clubs"), Card(4, "Diamonds"),
                         Card(5, "Clubs"), Card(6, "Diamonds")])
    g.consumable_hand = ["c_moon"]
    assert decide_consumable(g) is None

    # When Clubs IS the majority, The Moon converts the off-suit cards to it.
    g2 = _cons_game(hand=[Card(14, "Clubs"), Card(13, "Clubs"),
                          Card(12, "Clubs"), Card(2, "Spades"),
                          Card(3, "Hearts"), Card(4, "Diamonds"),
                          Card(5, "Hearts"), Card(6, "Diamonds")])
    g2.consumable_hand = ["c_moon"]
    act = decide_consumable(g2)
    assert act is not None
    assert all(g2.hand[i].suit != "Clubs" for i in act["target_cards"])


def test_tarot_value_ranks_hermit_death_above_suit():
    g = _cons_game()
    g.dollars = 20
    assert tarot_value(g, "c_hermit") > tarot_value(g, "c_death")
    assert tarot_value(g, "c_death") > tarot_value(g, "c_magician")
    assert tarot_value(g, "c_magician") > tarot_value(g, "c_moon")
    assert tarot_value(g, "c_justice") == 0.0
    assert tarot_value(g, "c_tower") == 0.0


def test_spectral_value_ranks_black_hole_and_gates_soul():
    g = _cons_game()
    assert spectral_value(g, "s_black_hole") > spectral_value(g, "s_aura")
    assert spectral_value(g, "s_ankh") == 0.0
    g.joker_slots = 0
    assert spectral_value(g, "s_soul") == 0.0      # slot gate
    g.joker_slots = 5
    assert spectral_value(g, "s_soul") > 0.0


def test_joker_value_discounts_consumables_and_values_economy():
    g = _cons_game()
    old = (ACTIVE_PARAMS["graph_weight"], ACTIVE_PARAMS["boss_buy_bonus"],
           ACTIVE_PARAMS["synergy_weight"])
    try:
        ACTIVE_PARAMS["graph_weight"] = 0.0
        ACTIVE_PARAMS["boss_buy_bonus"] = 0.0
        ACTIVE_PARAMS["synergy_weight"] = 0.0
        g.ante = 1
        v_early = joker_value(g, "j_popcorn", "None")
        g.ante = 8
        v_late = joker_value(g, "j_popcorn", "None")
        assert v_late < v_early            # consumable discount grows with ante
        # economy lifecycle: strong EARLY (compounding), decays by ante 8
        g.ante = 1
        v_mail_early = joker_value(g, "j_mail", "None")
        assert v_mail_early > 0.05          # economy term early
        g.ante = 8
        v_mail_late = joker_value(g, "j_mail", "None")
        assert v_mail_late <= v_mail_early  # economy decays late
    finally:
        ACTIVE_PARAMS["graph_weight"], ACTIVE_PARAMS["boss_buy_bonus"], \
            ACTIVE_PARAMS["synergy_weight"] = old


# ── human-fair mean measures: econ / generator per ante ────────────────────

def test_econ_per_ante_uses_documented_rates_and_composition():
    from balatro_sim.agent_v9 import econ_per_ante
    g = _shop_game()   # full 52-card deck, dollars=20, state=SHOP
    # Golden Joker: $4 end of round -> $12/ante regardless of the deck
    assert econ_per_ante(g, "j_golden") == 12.0
    # Cloud 9: $1 per 9 in the full deck per round -> 3 x nines
    nines = sum(1 for c in g.deck if c.rank == 9)
    assert econ_per_ante(g, "j_cloud_9") == 3.0 * nines
    # Business Card: 1/2 x $2 per played face -> scales with the face share
    assert econ_per_ante(g, "j_business") > 0
    # To the Moon: +$1 per $5 held -> dollars=20 gives $12/ante
    assert econ_per_ante(g, "j_to_the_moon") == 12.0
    # no standing cash rate for sell-value / debt jokers
    assert econ_per_ante(g, "j_egg") == 0.0
    assert econ_per_ante(g, "j_credit_card") == 0.0
    # unknown keys are neutral
    assert econ_per_ante(g, "j_joker") == 0.0


def test_gen_per_ante_rates():
    from balatro_sim.agent_v9 import gen_per_ante
    g = _shop_game()
    assert gen_per_ante(g, "j_cartomancer") == 3.0    # 1 Tarot per Blind
    assert gen_per_ante(g, "j_certificate") == 3.0    # 1 sealed card per round
    assert gen_per_ante(g, "j_marble") == 3.0         # 1 Stone per round
    assert gen_per_ante(g, "j_8_ball") >= 0           # composition-based
    assert gen_per_ante(g, "j_joker") == 0.0          # unknown keys neutral


def test_pack_value_spectral_ramps_and_buffoon_fades():
    g = _cons_game()
    g.ante = 1
    assert pack_value(g, "p_spectral") < 0.06   # risky early
    g.ante = 6
    assert pack_value(g, "p_spectral") > 0.06   # strong mid-to-late
    g.ante = 1
    empty = pack_value(g, "p_buffoon")
    g.jokers = [object()] * 5
    g.joker_slots = 5
    assert pack_value(g, "p_buffoon") < empty   # fades as slots fill


# ── run-level sanity (small bank, fast config) ──────────────────────────────

def test_heuristic_beats_random_on_small_bank():
    fast = {"eval_topk_play": 8, "eval_topk_ev": 4, "discard_max_size": 1}
    ACTIVE_PARAMS.update(fast)
    try:
        seeds = range(12)
        h = [rollout(BalatroGame(seed=s, rng_mode="seed"), HeuristicV9())
             for s in seeds]
        r = [rollout(BalatroGame(seed=s, rng_mode="seed"), RandomPolicy())
             for s in seeds]
        h_mean = sum(o["ante"] for o in h) / len(h)
        r_mean = sum(o["ante"] for o in r) / len(r)
        assert h_mean > r_mean
        assert sum(o["won"] for o in h) >= sum(o["won"] for o in r)
        assert sum(o["ante"] >= 2 for o in h) >= sum(o["ante"] >= 2 for o in r)
    finally:
        ACTIVE_PARAMS.update({"eval_topk_play": 12, "eval_topk_ev": 6,
                              "discard_max_size": 2})


# ── interest / save-mode / voucher-gate / forecast ─────────────────────────

def test_next_blind_target_mid_ante():
    """During a shop, current_blind is the JUST-BEATEN blind; the forecast
    computes the upcoming blind's target (with boss scaling)."""
    g = BalatroGame(seed=5, rng_mode="seed")
    g.state = State.SHOP
    # shop after the ante-1 Small blind -> upcoming Big = 450
    g.ante = 1
    g.blind_idx = 0
    assert next_blind_target(g) == 450.0
    # shop after the ante-2 Big blind -> upcoming Boss, The Needle = 1x base
    g.ante = 2
    g.blind_idx = 1
    g.next_boss_key = "bl_needle"
    assert next_blind_target(g) == float(BLIND_CHIPS[2][0])
    g.next_boss_key = "bl_wall"
    assert next_blind_target(g) == float(BLIND_CHIPS[2][0] * 4)
    g.next_boss_key = "bl_violet"
    assert next_blind_target(g) == float(BLIND_CHIPS[2][0] * 6)
    g.next_boss_key = "bl_hook"
    assert next_blind_target(g) == float(BLIND_CHIPS[2][2])
    # post-Boss shop -> next ante's Small (ante 8+ -> 0, banked win)
    g.ante = 3
    g.blind_idx = 2
    assert next_blind_target(g) == float(BLIND_CHIPS[4][0])
    g.ante = 8
    g.blind_idx = 2
    assert next_blind_target(g) == 0.0


def test_worth_spending_above_interest_cap():
    g = _shop_game()
    g.ante = 5
    g.dollars = 30
    # $4 spend keeps >= 1 band above the $25 cap -> allowed
    assert worth_spending(g, 4, 0.0) is True
    # $12 spend crosses below the cap by 2 bands with low value -> blocked
    assert worth_spending(g, 12, 0.05) is False
    # ...but exceptional value passes
    assert worth_spending(g, 12, 0.30) is True


def test_voucher_gated_out_early_and_without_build():
    g = _shop_game()
    g.jokers = []
    g.current_shop = [
        ShopItem("voucher", "v_seed_money", "Seed Money", 10),
        ShopItem("joker", "j_egg", "Egg", 4),
    ]
    act = decide_shop(g, 2)  # rerolls exhausted -> a buy or leave
    # ante-1 with an empty build: the $10 voucher must NEVER beat the pack/joker
    assert act["type"] == "buy" and act["item_idx"] == 1


def test_save_mode_holds_money_when_beatable_and_nothing_strong(monkeypatch):
    import balatro_sim.agent_v9 as agent_module
    # force the confidence gate: the upcoming blind IS comfortably beatable
    monkeypatch.setattr(agent_module, "forecast_beatable",
                        lambda game, margin, ref=None: True)

    # weak item (value 0.1 < 0.30) + beatable -> SAVE (no spend). joker_value
    # patched so graph/lifecycle terms can't push the fixture item over the
    # strong-value bar.
    monkeypatch.setattr(agent_module, "joker_value",
                        lambda game, key, edition, ref=None, surplus=None: 0.10)
    g = _shop_game()
    g.ante = 5
    g.dollars = 20
    g.current_shop = [ShopItem("joker", "j_golden", "Golden Joker", 6)]
    act = decide_shop(g, 2)
    assert act["type"] == "leave_shop"

    # a genuinely strong item (value 0.9 > 0.30) + beatable -> still SPEND
    g2 = _shop_game()
    g2.ante = 5
    g2.dollars = 20
    g2.current_shop = [ShopItem("tarot", "c_hermit", "The Hermit", 5)]
    monkeypatch.setattr(agent_module, "tarot_value", lambda game, key: 0.90)
    act = decide_shop(g2, 2)
    assert act["type"] == "buy"


# ── lifecycle valuation (L3.5): phase curves + deck-state + power tilt ─────

def test_lifecycle_xmult_ramps_late():
    g = _cons_game()
    low = lifecycle_bonus(g, "j_photograph")      # xMult curve is (0.08, 0.20)
    g.ante = 7
    high = lifecycle_bonus(g, "j_photograph")
    assert low < high


def test_lifecycle_economy_compounds_early():
    g = _cons_game()
    early = lifecycle_bonus(g, "j_mail")          # econ curve (0.20, 0.05)
    g.ante = 8
    late = lifecycle_bonus(g, "j_mail")
    assert early > 0.15 and late < early


def test_deck_condition_family_needs_rank_stack():
    from balatro_sim.card import Card
    g = _cons_game()
    assert deck_condition_bonus(g, "j_family") == 0.0
    for i in range(7):
        g.deck.append(Card(rank=7, suit="Spades", id=f"X{i}"))
    assert deck_condition_bonus(g, "j_family") == 0.30


def test_deck_condition_cloud9_counts_nines():
    from balatro_sim.card import Card
    g = _cons_game()
    # strip the deck's natural nines so the condition starts cold
    g.deck = [c for c in g.deck if c.rank != 9]
    g.hand = [c for c in g.hand if c.rank != 9]
    g.spent = [c for c in g.spent if c.rank != 9]
    assert deck_condition_bonus(g, "j_cloud_9") == 0.0
    for i in range(6):
        g.deck.append(Card(rank=9, suit="Hearts", id=f"N{i}"))
    assert deck_condition_bonus(g, "j_cloud_9") == 0.10


def test_power_tilt_engine_rush_when_tight():
    # tight next blind at ante 5+ -> xMult rush on; surplus -> economy up
    g = _shop_game()
    g.ante = 5
    assert power_tilt(g, "j_photograph", False) > 0.10
    assert power_tilt(g, "j_photograph", True) < 0
    assert power_tilt(g, "j_mail", True) > 0
    assert power_tilt(g, "j_mail", False) < 0
    # ...but NOT before ante 4 (an engine at ante 2 is dead weight)
    g.ante = 2
    assert power_tilt(g, "j_photograph", False) == 0.0


def test_worst_joker_protects_the_only_xmult():
    from balatro_sim.agent_v9 import worst_joker_idx
    g = _shop_game()
    g.jokers = []
    g.grant_joker("j_photograph")   # the engine — marginal ~0 on a face-less ref
    g.grant_joker("j_blue_joker")   # junk by comparison
    worst = worst_joker_idx(g)
    assert worst == 1  # never the sole xMult


# ── reference-hand valuation: best drawable hand, not a random slice ────────

def test_reference_hand_small_deck_is_guaranteed():
    """A deck that fits in the opening hand is GUARANTEED: reach == 1 and the
    ceiling IS the whole pool — the 'only look at the best hand' case."""
    import balatro_sim.agent_v9 as A
    from balatro_sim.card import Card
    g = _shop_game()
    g.deck = [Card(rank=14, suit="Spades", id="A1"),
              Card(rank=13, suit="Hearts", id="K1"),
              Card(rank=12, suit="Diamonds", id="Q1")]
    g.hand = []
    g.spent = []
    ref = A.reference_hand(g)
    assert ref.reach == 1.0
    assert ref.ceiling == ref.typical == g.deck
    assert ref.base_c == ref.base_t


def test_reference_hand_large_deck_blends_ceiling_and_typical():
    """A full deck can't guarantee the draw: reach < 1, the ceiling is the
    best drawable hand (out-scores the typical sample), and everything is
    deterministic + side-effect free."""
    import balatro_sim.agent_v9 as A
    g = _shop_game()  # full 52-card deck
    ref = A.reference_hand(g)
    assert 0.0 < ref.reach < 1.0
    assert len(ref.ceiling) == 8 and len(ref.typical) == 8
    # the best drawable hand must at least match an average draw
    assert ref.base_c >= ref.base_t
    # deterministic + pure
    r2 = A.reference_hand(g)
    assert ref.ceiling == r2.ceiling and ref.typical == r2.typical
    assert ref.base_c == r2.base_c and ref.reach == r2.reach
    assert len(g.deck) == 52 and g.dollars == 20


def test_reference_hand_committed_main_type_shapes_ceiling():
    """Once the run is committed to a hand type (played >= 2 times), the
    ceiling is the best hand OF that type — a Pair build must value Duo on
    pair material, not on whatever flush the deck happens to support."""
    import balatro_sim.agent_v9 as A
    g = _shop_game()
    g.run_hand_counts = {"Pair": 5, "High Card": 1}
    ref = A.reference_hand(g)
    ranks = [c.rank for c in ref.ceiling]
    assert max(ranks.count(r) for r in set(ranks)) >= 2


def test_joker_value_conditional_reads_the_deck_not_a_slice():
    """Photograph (first face card x2) must read a real marginal when the
    deck is face-rich — the old next-8 slice could miss faces entirely and
    rate it ~0. Same for a face-poor deck: it stays near the floor."""
    import balatro_sim.agent_v9 as A
    from balatro_sim.card import Card
    g = _shop_game()
    g.deck = [Card(rank=r, suit=s, id=f"F{i}") for i, (r, s) in
              enumerate((r, s) for r in (11, 12, 13, 14)
                        for s in ("Spades", "Hearts", "Diamonds", "Clubs"))]
    g.hand = []
    g.spent = []
    ref = A.reference_hand(g)
    v_rich = A.joker_value(g, "j_photograph", "None", ref)

    g2 = _shop_game()
    g2.deck = [Card(rank=r, suit=s, id=f"P{i}") for i, (r, s) in
               enumerate((r, s) for r in (2, 3, 4, 5, 6, 7)
                         for s in ("Spades", "Hearts"))]
    g2.hand = []
    g2.spent = []
    ref2 = A.reference_hand(g2)
    v_poor = A.joker_value(g2, "j_photograph", "None", ref2)
    assert v_rich > v_poor + 0.5


def test_reference_hand_and_joker_value_are_pure():
    """The reference construction + blended valuation must not consume RNG
    or mutate the game (seed-exactness invariant)."""
    import balatro_sim.agent_v9 as A
    g = _shop_game()
    g.rng.enable_tracing()
    before = (len(g.deck), len(g.hand), len(g.spent), g.dollars)
    ref = A.reference_hand(g)
    A.joker_value(g, "j_photograph", "None", ref)
    A.forecast_beatable(g, 1.0, ref)
    assert g.rng.records == []
    assert (len(g.deck), len(g.hand), len(g.spent), g.dollars) == before


# ── priority-aware enumeration prune (byte-identical to full enumeration) ──

def test_scored_plays_returns_best_hand_type_first():
    """The scoring window must be the HIGHEST-priority combos — a regression
    pin for the sort key. A broken `(priority, -index)` ascending sort put the
    LOWEST-priority combos (High Cards) first, so the window never contained a
    Flush and the agent played High Cards even when a Flush was drawable."""
    g = _game_in_hand()
    g.jokers = []
    g.hand = [
        Card(14, "Hearts"), Card(2, "Hearts"), Card(3, "Hearts"),
        Card(4, "Hearts"), Card(5, "Hearts"), Card(14, "Spades"),
        Card(7, "Clubs"), Card(9, "Diamonds"),
    ]
    plays = scored_plays(g, hand=g.hand, topk=12)
    assert plays, "no plays returned"
    # the best drawable hand is the straight flush (A-2-3-4-5 of Hearts)
    assert plays[0][2] in ("Straight Flush", "Flush"), plays[0]
    assert plays[0][0] >= 500, plays[0]


def test_prune_finds_wild_completed_flush():
    """A Wild card counts as any suit in hand_eval._is_flush — the prune's
    size-priority bounds must fold Wilds into every suit's pool or it drops
    the flush size (UNSOUND bound -> regression)."""
    g = _game_in_hand()
    g.jokers = []
    # 4 Clubs + 1 Wild -> a 5-card Flush is drawable
    g.hand = [
        Card(14, "Clubs"), Card(13, "Clubs"), Card(12, "Clubs"),
        Card(11, "Clubs"), Card(2, "Diamonds"), Card(3, "Spades"),
        Card(4, "Hearts"), Card(5, "Clubs"),
    ]
    g.hand[4].enhancement = "Wild"  # the 2 of Diamonds is Wild
    plays = scored_plays(g, hand=g.hand, topk=12)
    assert plays, "no plays returned"
    assert plays[0][2] == "Flush", plays[0]
    assert len(plays[0][1]) == 5, plays[0]


def test_prune_matches_full_enumeration_on_small_hands():
    """The pruned enumeration must rank identically to the full 1..5-card
    enumeration on small (5-card) hands where the window is wide."""
    g = _game_in_hand()
    g.jokers = []
    g.hand = [
        Card(14, "Hearts"), Card(13, "Hearts"), Card(12, "Hearts"),
        Card(11, "Hearts"), Card(10, "Hearts"),
    ]
    plays = scored_plays(g, hand=g.hand, topk=12)
    assert plays[0][2] == "Straight Flush", plays[0]
    assert len(plays[0][1]) == 5, plays[0]


def test_combo_priority_matches_evaluate_hand():
    """_combo_priority (the ranking-only type test in scored_plays) must
    return the exact same HAND_PRIORITY as evaluate_hand for every combo —
    a regression pin for the split ranking path (Stones/Wilds/debuffs and
    every hand type incl. wheel straights, flush house, five of a kind)."""
    import random
    import balatro_sim.agent_v9 as A
    from balatro_sim.hand_eval import evaluate_hand as ev
    rng = random.Random(777)
    enhs = ["None", "Stone", "Wild", "Bonus", "Mult", "Glass", "Lucky"]
    for _ in range(20_000):
        k = rng.randint(1, 5)
        cards = []
        for _ in range(k):
            c = Card(rng.randint(2, 14),
                     rng.choice(["Spades", "Hearts", "Clubs", "Diamonds"]))
            c.enhancement = rng.choice(enhs)
            if rng.random() < 0.05:
                c.debuffed = True
            cards.append(c)
        ht, _ = ev(cards)
        assert A._combo_priority(cards) == A.HAND_PRIORITY[ht], \
            f"{[(c.rank, c.suit, c.enhancement, c.debuffed) for c in cards]}"
