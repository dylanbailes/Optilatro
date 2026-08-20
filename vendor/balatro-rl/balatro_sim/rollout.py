"""rollout.py — V9 search primitives: deterministic state forking + rollouts.

The seed-exact sim is a perfect forward model: from any state, an action
sequence determines the future exactly (seed mode). This module provides the
two primitives Layer 1 (macro search) and the Layer-2b distillation collector
build on:

  clone_game(game)   — deep-fork a game for search branching. The fork's RNG
                       and state are fully independent; replaying identical
                       actions from the fork matches the original, while
                       diverging actions never leak back to it.
  rollout(game, policy) — run a policy object (anything with
                       `decide(game) -> action dict`) from a game state until
                       GAME_OVER, returning an outcome dict.
"""
from __future__ import annotations

from copy import deepcopy

from .game import BalatroGame, State


def clone_game(game: BalatroGame) -> BalatroGame:
    """Deep-fork a game for search/rollout (Layer 1 tree node).

    Verified: SeedSource/NodeTable/LuaRandom state is fully copied, so the
    fork's per-node RNG is independent (~1 ms per copy).
    """
    return deepcopy(game)


def _force_progress(game: BalatroGame) -> dict:
    """A safe action that always moves a stuck state forward (rollout safety
    net — the heuristic policy should never trigger this). Note: with an empty
    hand at SELECTING_HAND nothing CAN progress; rollout burns to max_steps in
    that pathological case (only reachable via extreme card destruction)."""
    st = game.state
    if st == State.SELECTING_HAND:
        return {"type": "play", "cards": [0]} if game.hand else {"type": "noop"}
    if st == State.BLIND_SELECT:
        return {"type": "play_blind"}
    if st == State.SHOP:
        return {"type": "leave_shop"}
    if st == State.BOOSTER_OPEN:
        return {"type": "skip_booster"}
    return {"type": "noop"}  # ROUND_EVAL / GAME_OVER


def _progress_sig(game: BalatroGame) -> tuple:
    """State signature for stall detection: changes whenever ANY real game
    progress happened (play/discard/buy/draw/money move/state change).

    STATE ALONE IS NOT ENOUGH: during SELECTING_HAND every play/discard keeps
    the state at SELECTING_HAND (it only leaves when the blind clears or the
    run ends), so a state-only stall counter would fire on normal play."""
    return (
        game.state,
        len(game.hand),
        game.hands_left,
        game.discards_left,
        game.chips_scored,
        game.dollars,
        len(game.jokers),
        len(game.consumable_hand),
        game.blind_idx,
        game.ante,
    )


def rollout(
    game: BalatroGame,
    policy,
    max_steps: int = 100_000,
    stall_guard: int = 3,
) -> dict:
    """Run `policy` from a game state until GAME_OVER (or the step cap).

    policy: any object with `decide(game) -> action dict` (see agent_v9).
    Returns an outcome dict:
        won, ante, death_blind, death_kind, steps, truncated, dollars, jokers
    `won` mirrors bench_sim: the ante-8 boss is beaten when ante > 8 at
    GAME_OVER (the ante-8 shop -> GAME_OVER transition increments ante past 8).
    """
    steps = 0
    stalled = 0
    sig = _progress_sig(game)
    while game.state != State.GAME_OVER and steps < max_steps:
        steps += 1
        game.step(policy.decide(game))
        new_sig = _progress_sig(game)
        if new_sig == sig:
            stalled += 1
            if stalled >= stall_guard:
                game.step(_force_progress(game))
                stalled = 0
        else:
            stalled = 0
        sig = new_sig
    return outcome(game, steps, truncated=steps >= max_steps)


def outcome(
    game: BalatroGame,
    steps: int,
    truncated: bool = False,
) -> dict:
    """Summarize a finished (or capped) run."""
    won = bool(game.ante > 8 and game.state == State.GAME_OVER)
    return {
        "won": won,
        "ante": game.ante,
        "death_blind": game.blind_idx,  # 0/1/2 at death; 0/1/2 also valid when won
        "death_kind": (game.current_blind.kind
                       if game.state == State.GAME_OVER else ""),
        "steps": steps,
        "truncated": truncated,
        "dollars": game.dollars,
        "jokers": [j.key for j in game.jokers],
        # Observation-only run statistics (game.run_stats + consumable usage
        # lists — never part of the RNG stream, so forks and the seed-exactness
        # gate are unaffected). Aggregated by bench/bench_v9.py reports.
        "stats": {
            "tarots": list(game.tarots_used),
            "planets": list(game.planets_used),
            "spectrals": list(game.spectrals_used),
            "jokers_bought": list(game.run_stats["jokers_bought"]),
            "money_spent": game.run_stats["money_spent"],
            "best_score": game.run_stats["best_score"],
            "rerolls": game.run_stats["rerolls"],
            "packs_bought": game.run_stats["packs_bought"],
            "packs_opened": game.run_stats["packs_opened"],
            "interest_collected": game.run_stats["interest_collected"],
            "econ_source": game.run_stats["econ_source"],
            # Synergy-tree telemetry (per-run detail; the bench --telemetry-dir
            # dump feeds tools/gen_synergy_tree.py — NOT aggregated in the
            # report's counters). Observation-only, zero RNG.
            "jokers_sold": list(game.run_stats["jokers_sold"]),
            "co_owned": list(game.run_stats["co_owned"]),
            "consumable_uses": list(game.run_stats["consumable_uses"]),
        },
    }
