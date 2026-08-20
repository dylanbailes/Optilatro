"""test_agent_l1.py — Layer-1 shop search policy.

Default (human-fair): comparative mean-measure evaluation — ranks shop items
by score delta on the best/typical drawable hands + econ $/ante + tarot/
spectral gen/ante, plays the argmax, and NEVER consults the deck's draw
order or the future (no rollouts). lookahead=True is the RESEARCH-ONLY
rollout mode (not human-fair); its boundedness is still pinned here.

Covered: determinism, L0 equivalence when search is off, purity (no RNG
consumption), no rollout calls in the default mode, bounded rollouts in
lookahead mode, argmax selection, and valid actions.
"""
from __future__ import annotations

import pytest

import balatro_sim.agent_l1 as L1
from balatro_sim.agent_l1 import SearchShopV9
from balatro_sim.agent_v9 import HeuristicV9
from balatro_sim.game import State, BalatroGame
from balatro_sim.rollout import rollout
from balatro_sim.shop import ShopItem


def _outcome(seed: int, search_shops: int, candidate_cap: int = 1,
             lookahead: bool = False):
    game = BalatroGame(seed=seed, rng_mode="seed")
    return rollout(game, SearchShopV9(search_shops=search_shops,
                                      candidate_cap=candidate_cap,
                                      lookahead=lookahead))


def test_search_shops_0_is_pure_l0():
    """search_shops=0 must behave EXACTLY like the L0 heuristic."""
    seed = 42
    l0 = rollout(BalatroGame(seed=seed, rng_mode="seed"), HeuristicV9())
    l1 = _outcome(seed, search_shops=0)
    for k in ("won", "ante", "death_blind", "dollars", "jokers"):
        assert l1[k] == l0[k], f"seed {seed}: {k} differs with search off"


def test_deterministic_and_valid():
    """The comparative search is deterministic per seed AND produces a valid
    outcome — one computed pair (a searched run twice) covers both."""
    seed = 42
    a = _outcome(seed, search_shops=1)
    b = _outcome(seed, search_shops=1)
    assert a == b, f"seed {seed}: searched run not deterministic"
    assert isinstance(a["won"], bool)
    assert 1 <= a["ante"] <= 20
    assert a["steps"] > 0
    assert not a["truncated"], f"seed {seed} truncated the run"


def test_comparative_search_never_rolls_out(monkeypatch):
    """The DEFAULT search is human-fair: it must NEVER fork/roll out the
    future — that is the exact-future predictor the rework removed."""
    def forbidden(*args, **kwargs):
        pytest.fail("comparative search called rollout (exact future)")

    monkeypatch.setattr(L1, "rollout", forbidden)
    out = _outcome(seed=42, search_shops=1)
    assert out["steps"] > 0


def test_lookahead_mode_rolls_out_with_plain_l0(monkeypatch):
    """lookahead=True is the RESEARCH-ONLY mode: it rolls out with a PLAIN
    HeuristicV9 (no recursion) and fires a bounded number of forks."""
    calls = []
    dummy = {"won": False, "ante": 1, "death_blind": 0, "dollars": 0,
             "jokers": []}

    def counting_rollout(game, policy, max_steps=100_000):
        calls.append(1)
        assert type(policy) is HeuristicV9
        assert not isinstance(policy, SearchShopV9)
        return dict(dummy)

    monkeypatch.setattr(L1, "rollout", counting_rollout)
    _outcome(seed=42, search_shops=1, candidate_cap=1, lookahead=True)
    assert 1 <= len(calls) <= 2, \
        f"lookahead search fired {len(calls)} rollouts, expected 1-2 (cap 1 + leave)"


def test_search_action_is_valid():
    """The search's chosen first-shop action must be a legal action (buy of
    an affordable item, or leave)."""
    game = BalatroGame(seed=11, rng_mode="seed")
    pol = SearchShopV9(search_shops=1, candidate_cap=1)
    act = None
    for _ in range(300):
        if game.state == State.GAME_OVER:
            pytest.fail("run ended before reaching a shop")
        if game.state == State.SHOP:
            act = pol.decide(game)           # the search fires here
            break
        game.step(pol.decide(game))
    assert act is not None and act["type"] in ("buy", "leave_shop")
    if act["type"] == "buy":
        item = game.current_shop[act["item_idx"]]
        assert not item.sold
        assert item.discounted_price(game.shop_discount) <= game.dollars


def test_comparative_search_picks_the_highest_value_item():
    """The comparative search plays the argmax of the mean-measure composite:
    a clearly-strong joker beats a weak one regardless of shop order."""
    game = BalatroGame(seed=5, rng_mode="seed")
    game.state = State.SHOP
    game.dollars = 30
    game.ante = 3
    game.grant_joker("j_blue_joker")   # a build exists -> buy threshold applies
    game.grant_joker("j_blue_joker")
    # A +4 Mult baseline joker vs Egg's econ: the composite ranks the scoring
    # joker first at this stage (marginal score delta dominates).
    game.current_shop = [
        ShopItem("joker", "j_egg", "Egg", 3),
        ShopItem("joker", "j_joker", "Joker", 4),
    ]
    pol = SearchShopV9(search_shops=1, candidate_cap=2)
    act = pol.decide(game)
    assert act["type"] == "buy"
    assert game.current_shop[act["item_idx"]].key == "j_joker"


def test_comparative_search_is_pure():
    """The search's decide must not consume the run's RNG (the isolated eval
    oracle uses a throwaway stream)."""
    game = BalatroGame(seed=11, rng_mode="seed")
    for _ in range(300):
        if game.state == State.SHOP:
            break
        game.step(HeuristicV9().decide(game))
    assert game.state == State.SHOP
    game.rng.enable_tracing()
    pol = SearchShopV9(search_shops=1)
    pol.decide(game)
    assert game.rng.records == [], "search consumed the run's RNG stream"


def test_search_save_mode_holds_money(monkeypatch):
    """Below the interest cap with nothing strong and a beatable upcoming
    blind, the search must leave instead of burning money on junk."""
    import balatro_sim.agent_l1 as L1
    import balatro_sim.agent_v9 as A
    # both bindings matter: _search_shop calls L1.forecast_beatable directly
    # and _rank_shop_items (agent_v9) calls A.joker_value.
    monkeypatch.setattr(L1, "forecast_beatable",
                        lambda game, m, ref=None: True)
    monkeypatch.setattr(A, "forecast_beatable",
                        lambda game, m, ref=None: True)
    monkeypatch.setattr(A, "joker_value",
                        lambda game, key, edition, ref=None,
                        surplus=None: 0.10)  # weak (< save_strong_value)
    game = BalatroGame(seed=5, rng_mode="seed")
    game.state = State.SHOP
    game.ante = 5
    game.dollars = 20
    game.current_shop = [ShopItem("joker", "j_golden", "Golden Joker", 6)]
    pol = SearchShopV9(search_shops=1, candidate_cap=2)
    act = pol.decide(game)
    assert act["type"] == "leave_shop"
