"""Regression: JokerInstance._hook_cache must not survive deepcopy.

fire() memoizes the module-level _NOOP sentinel for unoverridden hooks.
deepcopy copies that sentinel into a fresh object, the `m is _NOOP`
identity check misses it, and dispatch calls a plain object() ->
TypeError: 'object' object is not callable. Found via the L1 lookahead
rollout (clone_game fork steps leave_shop). Fix: __getstate__ drops the
cache on copy; forks repopulate lazily.
"""
import copy

from balatro_sim.game import BalatroGame
from balatro_sim.jokers.base import JokerInstance


def test_noop_hook_cache_dropped_on_deepcopy():
    inst = JokerInstance("j_crafty")   # suit joker: no on_shop_leave override
    inst.fire("on_shop_leave", None)   # caches _NOOP
    assert inst._hook_cache["on_shop_leave"] is not None
    fork = copy.deepcopy(inst)
    assert fork._hook_cache == {}      # dropped by __getstate__
    fork.fire("on_shop_leave", None)   # TypeError before the fix


def test_clone_game_fires_hooks_after_parent_did():
    g = BalatroGame(seed=1, rng_mode="seed")
    g.grant_joker("j_crafty")
    g._fire_joker_hook("on_shop_leave", None)   # parent populates cache
    fork = copy.deepcopy(g)
    fork._fire_joker_hook("on_shop_leave", None)  # crashed before the fix
