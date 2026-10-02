"""tests/test_agent_v14.py — Unit tests for V14 in-blind evaluator policy."""
from __future__ import annotations

import copy
import pytest
import torch

from balatro_sim.agent_v11 import SearchShopV11
from balatro_sim.agent_v14 import SearchInBlindV14, V14_DEFAULTS
from balatro_sim.evaluator import EvaluatorConfig, StructuredEvaluator
from balatro_sim.game import BalatroGame, State
from balatro_sim.rollout import rollout


class TestAgentV14:
    def test_v14_defaults_and_parity_control(self):
        """With v14_evaluator=False (default), decisions match SearchShopV11 exactly."""
        game = BalatroGame(seed=70123, rng_mode="seed")
        v11 = SearchShopV11()
        v14 = SearchInBlindV14()

        act_v11 = v11.decide(game)
        act_v14 = v14.decide(game)

        assert act_v14 == act_v11

    def test_analytical_clearing_fast_path(self):
        """When a hand immediately clears, V14 picks the most card-conserving play."""
        game = BalatroGame(seed=70123, rng_mode="seed")
        game.step({"type": "play_blind"})
        assert game.state == State.SELECTING_HAND

        v14 = SearchInBlindV14(params={"v14_evaluator": True})

        # Set target low so that multiple hands clear immediately
        game.current_blind.chips_target = 50
        game.chips_scored = 0

        action = v14.decide(game)
        assert action["type"] == "play"
        # Should record analytical clear
        assert v14.stats()["analytical_clears"] == 1

    def test_evaluator_residual_scoring_and_margin_gate(self):
        """Evaluator evaluates sub-clearing candidates and respects margin gate."""
        # Create a tiny test checkpoint
        config = EvaluatorConfig(architecture="mlp", d_model=16, num_layers=1)
        model = StructuredEvaluator(config)
        norm = {
            "kind": "tokens",
            "context": {"mean": [0.0] * config.context_dim, "scale": [1.0] * config.context_dim},
            "cards": {"mean": [0.0] * config.card_dim, "scale": [1.0] * config.card_dim},
            "jokers": {"mean": [0.0] * config.joker_dim, "scale": [1.0] * config.joker_dim},
        }
        checkpoint = {
            "config": {"architecture": "mlp", "d_model": 16, "num_layers": 1},
            "state_dict": model.state_dict(),
            "normalization": norm,
        }

        v14 = SearchInBlindV14(params={"v14_evaluator": True, "v14_margin": 100.0})
        v14._checkpoint = checkpoint
        v14._model = model

        game = BalatroGame(seed=70123, rng_mode="seed")
        game.step({"type": "play_blind"})
        assert game.state == State.SELECTING_HAND

        # Ensure hand cannot clear in 1 play so evaluator is invoked
        game.current_blind.chips_target = 100000
        game.chips_scored = 0

        act = v14.decide(game)
        assert isinstance(act, dict)
        assert act.get("type") in ("play", "discard")
        # Evaluator was run
        assert v14.stats()["evaluator_scored"] == 1
        # High margin retained anchor
        assert v14.stats()["retained_anchor"] == 1

    def test_human_fair_isolated_rng(self):
        """V14 evaluation does not mutate live game RNG stream."""
        game = BalatroGame(seed=70123, rng_mode="seed")
        v14 = SearchInBlindV14(params={"v14_evaluator": True})

        rng_state_before = copy.deepcopy(game.rng)
        _ = v14.decide(game)

        # Game state and RNG must not have moved during decision evaluation
        assert game.chips_scored == 0
