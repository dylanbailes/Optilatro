"""test_graph_v9.py — L2 graph-connectivity features for shop joker valuation.

Covers: spec-derived affinity extraction (pinned against real effect text),
deck-group composition, the heterogeneous run graph (joker/hand/deck/boss
nodes + affinity/support/counter edges), the four [0,1] connectivity features,
and the joker_value integration (boost for coherent candidates, purity — no
RNG consumption, no mutation).
"""
from __future__ import annotations

from balatro_sim.card import Card
from balatro_sim.game import State, BalatroGame
from balatro_sim.graph_v9 import (
    boss_counter_value, build_run_graph, connectivity_features,
    connectivity_score, deck_groups, joker_affinity,
)
from balatro_sim.jokers.base import JokerInstance

SUITS = ("Spades", "Hearts", "Clubs", "Diamonds")


def _game(seed: int = 7) -> BalatroGame:
    return BalatroGame(seed=seed, rng_mode="seed")


# ── affinity extraction (spec-derived) ─────────────────────────────────────

def test_affinity_pins():
    a = joker_affinity
    assert "Spades" in a("j_arrowhead")["suits"]
    assert 13 in a("j_baron")["ranks"] and "held" in a("j_baron")["flags"]
    assert 8 in a("j_8_ball")["ranks"]
    assert "Steel" in a("j_steel_joker")["enhs"]
    assert "deck" in a("j_steel_joker")["flags"]
    assert {12, 13} <= a("j_triboulet")["ranks"]
    assert {4, 10} <= a("j_walkie_talkie")["ranks"]
    assert "Pair" in a("j_duo")["hands"]
    assert "boss" in a("j_chicot")["flags"]
    assert "boss" in a("j_luchador")["flags"]
    assert "discard" in a("j_banner")["flags"]
    assert {12} <= a("j_shoot_the_moon")["ranks"]
    assert "held" in a("j_shoot_the_moon")["flags"]
    assert set(SUITS) <= a("j_smeared")["suits"]
    assert {14, 2, 3, 5, 8} <= a("j_fibonacci")["ranks"]  # Ace, 2, 3, 5, 8


def test_affinity_empty_for_unknown_key():
    aff = joker_affinity("j_nope")
    assert not any(aff[k] for k in ("hands", "suits", "ranks", "enhs", "flags"))


# ── deck composition ────────────────────────────────────────────────────────

def test_deck_groups_counts():
    g = _game()
    dg = deck_groups(g)
    assert dg["n"] == len(g.deck) + len(g.hand) + len(g.spent)
    assert sum(dg["suits"].values()) == dg["n"]
    assert sum(dg["ranks"].values()) == dg["n"]
    assert all(s in SUITS for s in dg["suits"])


# ── graph structure ─────────────────────────────────────────────────────────

def test_build_run_graph_edges():
    g = _game()
    g.grant_joker("j_duo", "None")                      # Pair affinity
    gr = build_run_graph(g, extra_jokers=("j_sly",))    # Pair/TwoPair/FH
    assert "j:j_duo" in gr.nodes and "j:j_sly" in gr.nodes
    assert "h:Pair" in gr.nodes
    # affinity edges into the hand-type node
    assert ("j:j_duo", "h:Pair", 1.0, "affinity") in gr.edges
    assert any(e[0] == "j:j_sly" and e[1] == "h:Pair"
               and e[3] == "affinity" for e in gr.edges)
    # shared-affinity joker↔joker edge
    assert any(e[0] == "j:j_duo" and e[1] == "j:j_sly"
               and e[3] == "affinity" for e in gr.edges)
    # support edges (joker→deck group) carry the normalized deck count — a
    # deck-affinity joker like Arrowhead (Spades) produces them
    gr2 = build_run_graph(g, extra_jokers=("j_arrowhead",))
    sup = [e for e in gr2.edges if e[3] == "support"]
    assert sup and all(0.0 < w <= 1.0 for _, _, w, _ in sup)
    assert any(e[0] == "j:j_arrowhead" and e[1] == "d:suit:Spades"
               for e in sup)


def test_build_run_graph_boss_node():
    g = _game()
    g.blind_idx = 1                                     # just fought Big → boss next
    g.state = State.SHOP
    gr = build_run_graph(g, extra_jokers=("j_chicot",))
    assert "boss" in gr.nodes
    assert ("j:j_chicot", "boss", 1.0, "counter") in gr.edges
    g.blind_idx = 0                                     # next blind is Big, no boss
    gr2 = build_run_graph(g, extra_jokers=("j_chicot",))
    assert "boss" not in gr2.nodes


# ── connectivity features ───────────────────────────────────────────────────

def test_coherence():
    g = _game()
    assert connectivity_features(g, "j_sly")["coherence"] == 0.5  # neutral
    g.grant_joker("j_duo", "None")                      # Pair build
    assert connectivity_features(g, "j_sly")["coherence"] > 0.0  # shares Pair
    assert connectivity_features(g, "j_crazy")["coherence"] == 0.0  # Straight vs Pair


def test_deck_support():
    g = _game()
    g.hand, g.spent = [], []
    g.deck = [Card(r, "Spades") for r in range(2, 15)] * 3   # all spades
    f_spades = connectivity_features(g, "j_arrowhead")["deck_support"]
    g.deck = [Card(r, "Hearts") for r in range(2, 15)] * 3   # no spades
    f_hearts = connectivity_features(g, "j_arrowhead")["deck_support"]
    assert f_spades > f_hearts
    assert f_spades > 0.5
    # a joker with no deck affinities is neutral
    assert connectivity_features(g, "j_joker")["deck_support"] == 0.5


def test_hand_alignment():
    g = _game()
    g.run_hand_counts["Flush"] = 10
    g.planet_levels["Flush"] = 3
    assert connectivity_features(g, "j_droll")["hand_alignment"] == 1.0
    assert connectivity_features(g, "j_crazy")["hand_alignment"] < 1.0
    assert connectivity_features(g, "j_joker")["hand_alignment"] == 0.5


def test_boss_counter_value():
    from balatro_sim.game import MATADOR_BOSSES
    g = _game()
    g.blind_idx = 1
    g.state = State.SHOP
    # The real flow pre-selects the boss at shop entry — the value is now
    # key-specific. The Ox IS a Matador-triggering boss.
    g.next_boss_key = "bl_ox"
    assert boss_counter_value(g, "j_chicot") == 1.0
    assert boss_counter_value(g, "j_luchador") == 1.0
    assert boss_counter_value(g, "j_matador") == 1.0
    assert boss_counter_value(g, "j_joker") == 0.0
    # j_mr_bones: general death-save, NOT a boss counter (spec text has no
    # "Boss" word) — pins the BOSS_INTERACTION_JOKERS doc set to behavior.
    assert boss_counter_value(g, "j_mr_bones") == 0.0
    # Non-trigger boss (The Wall): Matador's bonus drops to 0 — the whole
    # point of pre-selecting the key. Chicot/Luchador disable ANY boss, so
    # they keep the bonus.
    g.next_boss_key = "bl_wall"
    assert boss_counter_value(g, "j_matador") == 0.0
    assert boss_counter_value(g, "j_chicot") == 1.0
    assert "bl_ox" in MATADOR_BOSSES and "bl_wall" not in MATADOR_BOSSES
    # no boss coming
    g.blind_idx = 0
    assert boss_counter_value(g, "j_chicot") == 0.0
    # unknown key (hand-constructed state that skipped the shop): conservative
    # fallback keeps the old any-boss behavior
    g.blind_idx = 1
    g.next_boss_key = None
    assert boss_counter_value(g, "j_matador") == 1.0


def test_connectivity_score_bounded():
    g = _game()
    for key in ("j_joker", "j_arrowhead", "j_chicot", "j_baron", "j_duo"):
        assert 0.0 <= connectivity_score(g, key) <= 1.0


# ── joker_value integration ─────────────────────────────────────────────────

def test_joker_value_graph_term_and_purity():
    import balatro_sim.agent_v9 as A
    old = A.ACTIVE_PARAMS["graph_weight"]
    try:
        g = _game()
        g.grant_joker("j_duo", "None")                  # coherent: j_sly shares Pair
        ref = A.reference_hand(g)
        A.ACTIVE_PARAMS["graph_weight"] = 0.0
        v_off = A.joker_value(g, "j_sly", "None", ref)
        A.ACTIVE_PARAMS["graph_weight"] = 0.3
        v_on = A.joker_value(g, "j_sly", "None", ref)
        assert v_on > v_off, "coherent candidate must be boosted by the graph term"

        # purity: repeated calls agree, and nothing on the game moved
        dollars, deck_n = g.dollars, len(g.deck)
        v1 = A.joker_value(g, "j_sly", "None", ref)
        v2 = A.joker_value(g, "j_sly", "None", ref)
        assert v1 == v2
        assert g.dollars == dollars and len(g.deck) == deck_n
        assert [j.key for j in g.jokers] == ["j_duo"]
    finally:
        A.ACTIVE_PARAMS["graph_weight"] = old


def test_joker_value_boss_buy_bonus():
    """Boss-counter jokers get a dedicated buy term when a Boss is next —
    their marginal score value is ~0 so the blend alone couldn't buy them."""
    import balatro_sim.agent_v9 as A
    old_w = A.ACTIVE_PARAMS["graph_weight"]
    old_b = A.ACTIVE_PARAMS["boss_buy_bonus"]
    try:
        g = _game()
        g.blind_idx = 1
        g.state = State.SHOP
        ref = A.reference_hand(g)
        A.ACTIVE_PARAMS["graph_weight"] = 0.0
        A.ACTIVE_PARAMS["boss_buy_bonus"] = 0.0
        v_off = A.joker_value(g, "j_chicot", "None", ref)
        A.ACTIVE_PARAMS["boss_buy_bonus"] = 0.5
        v_on = A.joker_value(g, "j_chicot", "None", ref)
        assert v_on == v_off + 0.5
        # no boss coming → no bonus
        g.blind_idx = 0
        assert A.joker_value(g, "j_chicot", "None", ref) == v_off
    finally:
        A.ACTIVE_PARAMS["graph_weight"] = old_w
        A.ACTIVE_PARAMS["boss_buy_bonus"] = old_b
