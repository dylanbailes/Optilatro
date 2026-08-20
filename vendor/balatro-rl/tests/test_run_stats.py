"""test_run_stats.py — observation-only run statistics.

Every counter in the rollout outcome's 'stats' dict is derived from game state
with ZERO RNG consumption, so the seed-exactness gate is unaffected — these
tests also pin that the stats match the game's own counters (single source of
truth) and that buys/uses increment the right tallies.
"""
from __future__ import annotations

from balatro_sim.agent_v9 import HeuristicV9
from balatro_sim.consumables import apply_planet, apply_spectral, apply_tarot
from balatro_sim.game import BalatroGame
from balatro_sim.rollout import rollout
from balatro_sim.shop import ShopItem, buy_item


def _fresh(seed: int = 7) -> BalatroGame:
    return BalatroGame(seed=seed, rng_mode="seed")


def test_outcome_stats_present_and_consistent():
    """A full heuristic run's outcome 'stats' matches the game's own counters
    at GAME_OVER (the game is the single source of truth)."""
    game = _fresh()
    out = rollout(game, HeuristicV9())
    stats = out["stats"]
    for k in ("tarots", "planets", "spectrals", "jokers_bought", "money_spent",
              "best_score", "rerolls", "packs_bought", "packs_opened"):
        assert k in stats, f"stats missing {k}"
    assert stats["tarots"] == list(game.tarots_used)
    assert stats["planets"] == list(game.planets_used)
    assert stats["spectrals"] == list(game.spectrals_used)
    assert stats["jokers_bought"] == list(game.run_stats["jokers_bought"])
    assert stats["money_spent"] == game.run_stats["money_spent"]
    assert isinstance(stats["money_spent"], int) and stats["money_spent"] >= 0
    # best_score is the run-wide max; the final blind's score can't exceed it.
    assert stats["best_score"] >= game.chips_scored
    assert isinstance(stats["jokers_bought"], list)
    assert all(isinstance(k, str) for k in stats["jokers_bought"])


def test_run_stats_increments():
    """Direct buy/use calls increment the right counters (no RNG involved)."""
    g = _fresh()
    g.dollars = 50
    assert buy_item(g, ShopItem("joker", "j_dna", "DNA", 8))
    assert g.run_stats["jokers_bought"] == ["j_dna"]
    assert g.run_stats["money_spent"] == 8

    assert buy_item(g, ShopItem("booster", "p_arcana", "Arcana Pack", 4))
    assert g.run_stats["packs_bought"] == 1
    assert g.run_stats["money_spent"] == 12

    assert buy_item(g, ShopItem("planet", "pl_mercury", "Mercury", 3))
    assert g.run_stats["consumables_bought"] == 1
    assert g.run_stats["money_spent"] == 15

    # No-target consumables: Hermit (tarot) / Mercury (planet) / The Soul (spectral)
    assert apply_tarot(g, "c_hermit")
    assert apply_planet(g, "pl_mercury")
    assert g.tarots_used == ["c_hermit"]
    assert g.planets_used == ["pl_mercury"]

    g.joker_slots = 10
    assert apply_spectral(g, "s_soul")
    assert g.spectrals_used == ["s_soul"]


def test_best_score_updates_on_real_play():
    """A real hand play drives the PRODUCTION best_score update (run-wide max)
    — the test must not re-implement the logic it verifies."""
    from balatro_sim.game import State
    g = BalatroGame(seed=9, rng_mode="seed")
    guard = 0
    while g.state != State.SELECTING_HAND and guard < 20:
        g.step({"type": "play_blind"})
        guard += 1
    assert g.state == State.SELECTING_HAND
    g.step({"type": "play", "cards": list(range(min(5, len(g.hand))))})
    assert g.run_stats["best_score"] > 0
    assert g.run_stats["best_score"] == g.chips_scored
