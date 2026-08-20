"""test_synergy_tree.py — empirical synergy tree: telemetry, mining, scoring.

Covers:
  - telemetry capture: co_owned (scored-hand loadouts), consumable_uses (with
    targeted-card features), jokers_sold — all observation-only plain data;
  - the miner (tools/gen_synergy_tree.py): deterministic, support-floored,
    correct pair-lift math on a fixture corpus;
  - the scorer (balatro_sim/synergy_tree.py): 0.5 neutral without a tree,
    sensible edge-driven scores with one, pure reads;
  - the agent term (agent_v9.joker_value): synergy_weight boosts a candidate
    with a mined positive edge, contributes exactly 0 when neutral/missing.
"""
from __future__ import annotations

import importlib.util
import json
import pathlib

import pytest

from balatro_sim.game import BalatroGame, State
from balatro_sim.card import Card
from balatro_sim.shop import ShopItem

# tools/ is at the repo root (pytest runs from vendor/balatro-rl/), so load
# the miner module by file path rather than package import.
_ROOT = pathlib.Path(__file__).resolve().parents[3]
_spec = importlib.util.spec_from_file_location(
    "gen_synergy_tree", _ROOT / "tools" / "gen_synergy_tree.py")
_gen = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_gen)
mine = _gen.mine


def _game(seed: int = 7) -> BalatroGame:
    return BalatroGame(seed=seed, rng_mode="seed")


# ── telemetry capture ───────────────────────────────────────────────────────

def test_co_owned_recorded_on_scored_hands():
    g = _game()
    g.jokers = []
    g.grant_joker("j_joker")
    g.state = State.SELECTING_HAND
    g.hand = [Card(r, s) for r, s in
              [(14, "Hearts"), (12, "Hearts"), (10, "Hearts"), (8, "Hearts"),
               (6, "Hearts"), (2, "Spades"), (3, "Clubs"), (4, "Diamonds")]]
    g.current_blind.chips_target = 100
    g.discards_left = 0
    g.step({"type": "play", "cards": [0, 1, 2, 3, 4]})
    assert g.run_stats["co_owned"], "scored hand must be recorded"
    ante, ht, keys, score = g.run_stats["co_owned"][-1]
    assert ante == 1 and ht == "Flush"
    assert keys == ("j_joker",) and score > 0
    # joker keys are always a sorted tuple (JSON-friendly, deterministic)
    assert isinstance(keys, tuple) and keys == tuple(sorted(keys))


def test_consumable_uses_recorded_with_context():
    g = _game()
    g.state = State.SELECTING_HAND
    g.hand = [Card(14, "Spades"), Card(13, "Spades"), Card(2, "Clubs"),
              Card(3, "Diamonds"), Card(4, "Hearts"), Card(5, "Clubs"),
              Card(6, "Diamonds"), Card(7, "Hearts")]
    g.jokers = []
    g.grant_joker("j_hanging_chad")
    g.consumable_hand = ["c_empress"]
    g.step({"type": "use_consumable", "consumable_idx": 0,
            "target_cards": [0, 1]})
    assert g.run_stats["consumable_uses"]
    ante, key, keys, targets = g.run_stats["consumable_uses"][-1]
    assert key == "c_empress" and keys == ("j_hanging_chad",)
    assert targets == [{"rank": 14, "suit": "Spades", "enh": "None",
                        "edition": "None", "seal": "None"},
                       {"rank": 13, "suit": "Spades", "enh": "None",
                        "edition": "None", "seal": "None"}]


def test_jokers_sold_recorded():
    g = _game()
    g.jokers = []
    g.grant_joker("j_joker")
    g.grant_joker("j_egg")
    g.state = State.SHOP
    g.current_shop = []
    g.step({"type": "sell_joker", "joker_idx": 0})
    assert g.run_stats["jokers_sold"] == [(1, "j_joker")]


def test_telemetry_is_json_serializable_plain_data():
    """The telemetry lists must hold plain JSON data only (no RNG/card
    objects) — the bench --telemetry-dir dump serializes them directly."""
    g = _game()
    g.step({"type": "play_blind"})
    g.hand = [Card(14, "Hearts"), Card(13, "Hearts"), Card(12, "Hearts"),
              Card(11, "Hearts"), Card(10, "Hearts"), Card(2, "Spades"),
              Card(3, "Clubs"), Card(4, "Diamonds")]
    g.current_blind.chips_target = 60
    g.discards_left = 0
    g.step({"type": "play", "cards": [0, 1, 2, 3, 4]})
    g.grant_joker("j_egg")
    g.consumable_hand = ["c_sun"]
    g.step({"type": "sell_joker", "joker_idx": 0})
    json.dumps(g.run_stats)   # must not raise


def test_telemetry_deterministic_across_replays():
    def run(seed):
        g = _game(seed)
        from balatro_sim.agent_v9 import HeuristicV9
        from balatro_sim.rollout import rollout
        out = rollout(g, HeuristicV9(), max_steps=20_000)
        return out["stats"]["co_owned"], out["stats"]["consumable_uses"]
    assert run(11) == run(11)
    assert run(11) != run(12)


# ── miner (fixture corpus) ──────────────────────────────────────────────────

def _fixture_runs():
    """4 synthetic runs: {a,b} co-owned twice (one win, one deep loss),
    {a} alone once, {b} alone once."""
    return [
        {"won": True, "ante": 8, "stats": {
            "co_owned": [(1, "Pair", ("j_a", "j_b"), 100)],
            "consumable_uses": [(1, "c_sun", ("j_a",), [])]}},
        {"won": False, "ante": 4, "stats": {
            "co_owned": [(1, "Flush", ("j_a", "j_b"), 80)]}},
        {"won": False, "ante": 3, "stats": {
            "co_owned": [(1, "Pair", ("j_a",), 50)]}},
        {"won": False, "ante": 2, "stats": {
            "co_owned": [(1, "Pair", ("j_b",), 40)]}},
    ]


def test_mine_pair_lift_math():
    tree = mine(_fixture_runs(), min_support=2)
    meta = tree["meta"]
    assert meta["runs"] == 4
    edge = tree["joker_joker"]["j_a"]["j_b"]
    # mean ante: both = (8+4)/2 = 6; a alone = 3; b alone = 2
    # lift_ante = 6 - max(3, 2) = 3
    assert edge["n"] == 2 and edge["lift_ante"] == 3.0
    assert edge["mean_ante"] == 6.0
    assert edge["win_rate"] == 0.5


def test_mine_support_floor():
    runs = _fixture_runs()
    full = mine(runs, min_support=1)
    assert "j_a" in full["joker_joker"] and "j_b" in full["joker_joker"]["j_a"]
    # with min_support=3 the (a,b) pair (n=2) is dropped
    strict = mine(runs, min_support=3)
    assert "joker_joker" not in strict or not strict["joker_joker"]


def test_mine_consumable_and_hand_and_card():
    tree = mine(_fixture_runs(), min_support=1)
    # joker↔consumable: c_sun used while j_a owned in run 1 (won, ante 8)
    assert tree["joker_consumable"]["j_a"]["c_sun"]["n"] == 1
    assert tree["joker_consumable"]["j_a"]["c_sun"]["win_rate"] == 1.0
    # joker↔hand: j_a scored a Pair twice (runs 1, 3) and a Flush once
    assert tree["joker_hand"]["j_a"]["Pair"]["n"] == 2
    assert tree["joker_hand"]["j_a"]["Flush"]["n"] == 1
    assert tree["joker_hand"]["j_a"]["Pair"]["share"] == pytest.approx(2 / 3, abs=0.01)
    # joker↔card: no tarot targets in the fixture -> empty table
    assert "joker_card" in tree


def test_mine_deterministic():
    a = mine(_fixture_runs(), min_support=1)
    b = mine(_fixture_runs(), min_support=1)
    assert a == b


# ── miner: min-lift gate + policy filter ───────────────────────────────────

def test_mine_min_lift_gate():
    """Edges with |lift_ante| below --min-lift are dropped entirely."""
    runs = _fixture_runs()
    # pair (a,b): lift_ante = 3.0 (see test_mine_pair_lift_math)
    strict = mine(runs, min_support=2, min_lift=4.0)
    assert "joker_joker" not in strict or not strict["joker_joker"]
    loose = mine(runs, min_support=2, min_lift=2.0)
    assert loose["joker_joker"]["j_a"]["j_b"]["lift_ante"] == 3.0
    # a strong NEGATIVE lift survives the gate too (|lift| is what matters)
    runs_neg = [dict(r) for r in runs]
    runs_neg[0]["ante"] = 1
    runs_neg[1]["ante"] = 1
    tree = mine(runs_neg, min_support=2, min_lift=1.0)
    assert tree["joker_joker"]["j_a"]["j_b"]["lift_ante"] < 0


def test_mine_consumable_stores_lift_ante_and_gate():
    """joker↔consumable edges store lift_ante (mean ante vs the exclusive
    owned-without-used baseline) and respect the same min-lift gate."""
    runs = _fixture_runs()
    tree = mine(runs, min_support=1, min_lift=0.0)
    edge = tree["joker_consumable"]["j_a"]["c_sun"]
    assert "lift_ante" in edge
    # run 1 (j_a owned, c_sun used): ante 8. baseline = runs owning j_a
    # without ever using c_sun = runs 2+3 (antes 4, 3) -> mean 3.5.
    # lift = 8 - 3.5 = 4.5.
    assert edge["lift_ante"] == pytest.approx(4.5)
    strict = mine(runs, min_support=1, min_lift=6.0)
    assert "c_sun" not in strict["joker_consumable"].get("j_a", {})


def test_load_runs_policy_filter(tmp_path):
    """--policy mines only that policy's subdir (per-policy trees)."""
    (tmp_path / "heuristic_v9").mkdir()
    (tmp_path / "search_shop_v9").mkdir()
    (tmp_path / "heuristic_v9" / "run_0.json").write_text(
        '{"won": false, "ante": 2, "stats": {}}', encoding="utf-8")
    (tmp_path / "search_shop_v9" / "run_0.json").write_text(
        '{"won": true, "ante": 8, "stats": {}}', encoding="utf-8")
    h = _gen._load_runs(tmp_path, "heuristic_v9")
    s = _gen._load_runs(tmp_path, "search_shop_v9")
    assert len(h) == 1 and h[0]["won"] is False
    assert len(s) == 1 and s[0]["won"] is True


# ── scorer: explicit per-path trees ────────────────────────────────────────

def test_load_tree_explicit_path(tmp_path):
    """load_tree(path) reads + caches an explicit tree per path."""
    import balatro_sim.synergy_tree as ST
    ST.clear_tree_cache()
    p = tmp_path / "tree.json"
    p.write_text(json.dumps({"joker_joker": {"j_a": {"j_b": {
        "n": 9, "lift_ante": 1.5}}}}), encoding="utf-8")
    tree = ST.load_tree(str(p))
    assert tree["joker_joker"]["j_a"]["j_b"]["lift_ante"] == 1.5
    assert ST.load_tree(str(p)) is tree  # cached


def test_scorer_explicit_tree_arg():
    """empirical_synergy_score(game, key, tree) uses the GIVEN tree — the
    per-policy-tree mechanism."""
    import balatro_sim.synergy_tree as ST
    good = _fixture_tree()
    g = _game()
    g.grant_joker("j_joker")
    assert ST.empirical_synergy_score(g, "j_hanging_chad", good) > 0.5
    # an unrelated tree (no edges for the candidate) is neutral
    assert ST.empirical_synergy_score(g, "j_hanging_chad",
                                      {"meta": {},
                                       "joker_joker": {}}) == 0.5


# ── scorer ──────────────────────────────────────────────────────────────────

def _fixture_tree():
    """Candidate j_hanging_chad pairs well with owned j_joker; fires on
    Flush; King-targeting; c_sun co-uses. j_unknown has no edges."""
    return {
        "meta": {"runs": 100, "mean_ante": 4.0},
        "joker_joker": {"j_hanging_chad": {
            "j_joker": {"n": 20, "lift_ante": 3.0}}},
        "joker_consumable": {"j_hanging_chad": {
            "c_sun": {"n": 15, "mean_ante": 6.0}}},
        "joker_hand": {"j_hanging_chad": {
            "Flush": {"n": 10, "mean_score": 1000, "share": 0.8}}},
        "joker_card": {"j_hanging_chad": {"rank_13": 8}},
    }


def test_scorer_neutral_without_tree(monkeypatch):
    import balatro_sim.synergy_tree as ST
    monkeypatch.setattr(ST, "_TREE", {})
    g = _game()
    g.grant_joker("j_joker")
    assert ST.empirical_synergy_score(g, "j_hanging_chad") == 0.5
    comps = ST.empirical_synergy(g, "j_hanging_chad")
    assert comps == {"joker": 0.5, "consumable": 0.5, "hand": 0.5, "card": 0.5}


def test_scorer_edge_driven(monkeypatch):
    import balatro_sim.synergy_tree as ST
    monkeypatch.setattr(ST, "_TREE", _fixture_tree())
    g = _game()
    g.grant_joker("j_joker")
    # strong positive pair edge + aligned hand -> above neutral
    score = ST.empirical_synergy_score(g, "j_hanging_chad")
    assert 0.5 < score <= 1.0
    # a joker with no edges stays neutral
    assert ST.empirical_synergy_score(g, "j_unknown") == 0.5
    # purity: repeated calls agree, nothing on the game moved
    dollars, deck_n = g.dollars, len(g.deck)
    assert ST.empirical_synergy_score(g, "j_hanging_chad") == score
    assert g.dollars == dollars and len(g.deck) == deck_n


def test_scorer_hand_mismatch_scores_low(monkeypatch):
    """Data says the candidate fires on Flush; a Pair build is anti-aligned."""
    import balatro_sim.synergy_tree as ST
    monkeypatch.setattr(ST, "_TREE", _fixture_tree())
    g = _game()
    g.run_hand_counts["Pair"] = 5
    g.planet_levels["Pair"] = 3
    comps = ST.empirical_synergy(g, "j_hanging_chad")
    assert comps["hand"] < 0.5


# ── agent integration ───────────────────────────────────────────────────────

def test_joker_value_synergy_term(monkeypatch):
    import balatro_sim.agent_v9 as A
    import balatro_sim.synergy_tree as ST
    monkeypatch.setattr(ST, "_TREE", _fixture_tree())
    monkeypatch.setattr(ST, "_PRIOR", {})   # isolate from the real wiki prior
    old_w = A.ACTIVE_PARAMS["synergy_weight"]
    try:
        g = _game()
        g.grant_joker("j_joker")
        ref = A.reference_hand(g)
        A.ACTIVE_PARAMS["graph_weight"] = 0.0
        A.ACTIVE_PARAMS["boss_buy_bonus"] = 0.0
        A.ACTIVE_PARAMS["synergy_weight"] = 0.0
        v_off = A.joker_value(g, "j_hanging_chad", "None", ref)
        A.ACTIVE_PARAMS["synergy_weight"] = 0.2
        v_on = A.joker_value(g, "j_hanging_chad", "None", ref)
        assert v_on == v_off + 0.2 * (
            ST.combined_synergy_score(g, "j_hanging_chad") - 0.5)
        assert v_on > v_off
        # a neutral candidate (no edges) gets exactly 0 contribution
        v_neutral = A.joker_value(g, "j_unknown", "None", ref)
        A.ACTIVE_PARAMS["synergy_weight"] = 0.0
        v_neutral_off = A.joker_value(g, "j_unknown", "None", ref)
        assert v_neutral == v_neutral_off
    finally:
        A.ACTIVE_PARAMS["synergy_weight"] = old_w


def test_joker_value_per_policy_tree(monkeypatch, tmp_path):
    """ACTIVE_PARAMS['synergy_tree'] points joker_value at a specific
    per-policy tree file."""
    import balatro_sim.agent_v9 as A
    from balatro_sim.synergy_tree import clear_tree_cache
    clear_tree_cache()
    p = tmp_path / "policy_tree.json"
    p.write_text(json.dumps({
        "meta": {"runs": 50, "mean_ante": 5.0},
        "joker_joker": {"j_hanging_chad": {
            "j_joker": {"n": 30, "lift_ante": 4.0}}}}), encoding="utf-8")
    old_w = A.ACTIVE_PARAMS["synergy_weight"]
    old_t = A.ACTIVE_PARAMS.get("synergy_tree")
    try:
        g = _game()
        g.grant_joker("j_joker")
        ref = A.reference_hand(g)
        A.ACTIVE_PARAMS["graph_weight"] = 0.0
        A.ACTIVE_PARAMS["boss_buy_bonus"] = 0.0
        A.ACTIVE_PARAMS["synergy_weight"] = 0.2
        A.ACTIVE_PARAMS["synergy_tree"] = str(p)
        v_policy = A.joker_value(g, "j_hanging_chad", "None", ref)
        A.ACTIVE_PARAMS["synergy_weight"] = 0.0
        A.ACTIVE_PARAMS["synergy_tree"] = None
        v_off = A.joker_value(g, "j_hanging_chad", "None", ref)
        assert v_policy > v_off  # strong edge in the policy tree boosted it
    finally:
        A.ACTIVE_PARAMS["synergy_weight"] = old_w
        A.ACTIVE_PARAMS["synergy_tree"] = old_t


# ── wiki prior (combined scorer) ────────────────────────────────────────────

def _fixture_prior():
    """Wiki-scraped prior: hanging_chad↔j_joker + ↔c_sun, mime↔paint_brush."""
    return {
        "meta": {"prior_strength": 3.0},
        "joker_joker": {"j_hanging_chad": {"j_joker": 1.0}},
        "joker_consumable": {"j_hanging_chad": {"c_sun": 1.0}},
        "joker_voucher": {"j_mime": {"v_paint_brush": 1.0}},
    }


def test_combined_prior_initializes_without_mined_tree(monkeypatch):
    """No mined data: the wiki prior IS the matrix (edge → 1.0)."""
    import balatro_sim.synergy_tree as ST
    monkeypatch.setattr(ST, "_TREE", {})
    monkeypatch.setattr(ST, "_PRIOR", _fixture_prior())
    g = _game()
    g.grant_joker("j_joker")
    comps = ST.combined_synergy(g, "j_hanging_chad")
    assert comps["joker"] == 1.0        # wiki prior edge, no mined data
    assert comps["consumable"] == 0.5   # no held consumable
    assert comps["voucher"] == 0.5      # no owned voucher


def test_combined_mined_overrides_prior(monkeypatch):
    """High-support mined data overrides the wiki prior (pseudo-count)."""
    import balatro_sim.synergy_tree as ST
    # wiki says synergy (1.0); mined says strong NEGATIVE lift, n=50.
    tree = {"meta": {},
            "joker_joker": {"j_hanging_chad": {
                "j_joker": {"n": 50, "lift_ante": -3.0}}}}
    monkeypatch.setattr(ST, "_TREE", tree)
    monkeypatch.setattr(ST, "_PRIOR", _fixture_prior())
    g = _game()
    g.grant_joker("j_joker")
    comps = ST.combined_synergy(g, "j_hanging_chad")
    pure = ST._pair_score(tree, "j_hanging_chad", "j_joker")
    assert pure < 0.5                         # mined says the pair is bad
    assert comps["joker"] < 0.5               # data wins over the prior
    assert abs(comps["joker"] - pure) < 0.05  # prior barely moves it (n>>s)


def test_combined_voucher_component(monkeypatch):
    import balatro_sim.synergy_tree as ST
    monkeypatch.setattr(ST, "_TREE", {})
    monkeypatch.setattr(ST, "_PRIOR", _fixture_prior())
    g = _game()
    g.vouchers = {"v_paint_brush"}
    comps = ST.combined_synergy(g, "j_mime")
    assert comps["voucher"] == 1.0


def test_combined_neutral_without_prior_or_tree(monkeypatch):
    import balatro_sim.synergy_tree as ST
    monkeypatch.setattr(ST, "_TREE", {})
    monkeypatch.setattr(ST, "_PRIOR", {})
    g = _game()
    g.grant_joker("j_joker")
    assert ST.combined_synergy_score(g, "j_hanging_chad") == 0.5
    assert ST.combined_synergy_score(g, "j_unknown") == 0.5


def test_combined_hand_prior(monkeypatch):
    import balatro_sim.synergy_tree as ST
    monkeypatch.setattr(ST, "_TREE", {})
    monkeypatch.setattr(ST, "_PRIOR", {
        "meta": {"prior_strength": 3.0},
        "joker_hand": {"j_mime": {"High Card": 1.0, "Pair": 1.0}}})
    g = _game()
    g.run_hand_counts["High Card"] = 5   # the run's main hand
    comps = ST.combined_synergy(g, "j_mime")
    assert comps["hand"] == 1.0            # wiki: Mime → High Card = main hand
    assert ST.combined_synergy(g, "j_unknown")["hand"] == 0.5   # no prior


def test_combined_card_prior(monkeypatch):
    import balatro_sim.synergy_tree as ST
    from balatro_sim.card import Card
    monkeypatch.setattr(ST, "_TREE", {})
    monkeypatch.setattr(ST, "_PRIOR", {
        "meta": {"prior_strength": 3.0},
        "joker_card": {"j_mime": {"enh_Steel": 1.0, "seal_Blue": 1.0}}})
    g = _game()
    g.deck.append(Card(14, "Spades", enhancement="Steel"))   # deck support
    mime = ST.combined_synergy(g, "j_mime")
    unknown = ST.combined_synergy(g, "j_unknown")
    assert mime["card"] > 0.5             # wiki features supported by the deck
    assert unknown["card"] == 0.5         # no prior → neutral
