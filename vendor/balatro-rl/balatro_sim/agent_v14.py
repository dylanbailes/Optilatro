"""agent_v14.py — V14: in-blind action evaluation with learned structured evaluator.

HYBRID ANALYTICAL SCORING + RESIDUAL STATE EVALUATION
=====================================================
Neural networks struggle to approximate exact combinatorial scoring math (chips x mult),
leading to approximation noise when evaluating whether a hand clears the blind.
V14 solves this by analytical decomposition:

1. EXACT ANALYTICAL SCORING (Deterministic Fast-Path):
   - For candidate plays, evaluate immediate score via the exact engine (eval_hand_score).
   - If any play clears the blind (immediate_score >= chips_target - chips_scored),
     it is guaranteed to clear.
   - Guaranteed clearing plays are sorted by HAND CONSERVATION:
     fewest cards consumed (len(combo)), then lowest overkill score.
   - This executes with 0 ms neural inference latency, 100% mathematical precision,
     and optimal preservation of deck resources.

2. LEARNED RESIDUAL STATE EVALUATION (Sub-clearing & Discards):
   - When no single play clears the blind, candidate actions (plays, EV discards,
     quality discards) are evaluated.
   - For each candidate action a, evaluate the post-action residual state S' = T(S, a)
     under the calibrated multi-head evaluator V_theta(S').
   - Residual state value combines surplus return (hand conservation + economy)
     and clear probability:
       Q_hat(S, a) = surplus(S') + 2.0 * P_clear(S')

3. MARGIN-GATED OVERRIDE RULE:
   - Evaluator only overrides the heuristic anchor action if:
       V_hat(a*) - V_hat(a_anchor) > v14_margin
   - This prevents spurious overrides on hairline near-ties where model noise
     could degrade performance.

PARITY CONTROL & SAFETY
=======================
* v14_evaluator is OFF by default: with it off, decide is byte-identical to SearchShopV11.
* Evaluator is human-fair: state encoding is composition-only (deck + hand + spent,
  revealed boss), isolated eval uses throwaway RNG, and never consumes live run RNG.
* Missing checkpoint falls back gracefully to heuristic play.
"""
from __future__ import annotations

import math
from copy import deepcopy
from pathlib import Path
from typing import Any, Optional, Sequence

import torch
import torch.nn.functional as F

from .agent_v9 import scored_plays
from .agent_v10 import V10_DEFAULTS
from .agent_v11 import SearchShopV11
from .blind_dataset import action_key, candidate_actions, sample_world
from .eval_encoder import encode_state, schema
from .evaluator import EvaluatorConfig, StructuredEvaluator, collate_states
from .game import BalatroGame, State
from .rollout import clone_game


# ────────────────────────────────────────────────────────────────────────────
# V14 Tunables
# ────────────────────────────────────────────────────────────────────────────

V14_DEFAULTS = {
    # Master switch. OFF by default for strict byte-parity with SearchShopV11.
    "v14_evaluator": False,
    # Margin above anchor required for evaluator override (prevents tie churn).
    "v14_margin": 0.05,
    # Maximum candidate actions evaluated per decision.
    "v14_candidate_cap": 6,
    # Weight on surplus head (hand conservation + economy return).
    "v14_surplus_weight": 1.0,
    # Weight on P(clear) sigmoid head.
    "v14_clear_weight": 2.0,
    # Independent composition samples to average over (1 = fast, 2 = denoised).
    "v14_samples": 1,
    # Explicit path to model checkpoint (.pt). None = default location.
    "v14_checkpoint_path": None,
}

V14_PARAMS = dict(V14_DEFAULTS)

_DEFAULT_CHECKPOINT_PATHS = [
    Path(__file__).resolve().parents[3] / "results" / "evaluator" / "v14_surplus_model.pt",
    Path(__file__).resolve().parents[3] / "results" / "evaluator" / "evaluator_model.pt",
    Path(__file__).resolve().parents[3] / "results" / "evaluator_model.pt",
]


def _normalize_batch(states: list[dict], normalization: dict) -> dict[str, torch.Tensor]:
    """Normalize state tokens using checkpoint normalization statistics."""
    batch = collate_states(states)
    for block in ("context", "cards", "jokers"):
        mean = batch[block].new_tensor(normalization[block]["mean"])
        scale = batch[block].new_tensor(normalization[block]["scale"])
        batch[block] = (batch[block] - mean) / scale
        if block != "context":
            batch[block] = batch[block].masked_fill(~batch[f"{block}_mask"].unsqueeze(-1), 0)
    return batch


class SearchInBlindV14(SearchShopV11):
    """V14 Policy: SearchShopV11 shop search + hybrid analytical / learned evaluator in-blind."""

    policy_name = "search_inblind_v14"

    def __init__(self, params=None, checkpoint_path: Optional[Path | str] = None, **kwargs):
        given = dict(params or {})
        v14_keys = {k: v for k, v in given.items() if k in V14_DEFAULTS}
        non_v14 = {k: v for k, v in given.items() if k not in V14_DEFAULTS}

        super().__init__(params=non_v14, **kwargs)
        V14_PARAMS.update(v14_keys)

        path = checkpoint_path or V14_PARAMS.get("v14_checkpoint_path")
        self._checkpoint = self._load_checkpoint(path)
        self._model = self._init_model(self._checkpoint)

        self._stats = {
            "decisions": 0,
            "analytical_clears": 0,
            "evaluator_scored": 0,
            "overrides": 0,
            "retained_anchor": 0,
            "no_model_fallback": 0,
        }

    @staticmethod
    def _load_checkpoint(path: Optional[Path | str]) -> Optional[dict]:
        """Load trained evaluator checkpoint. Returns None if not found (graceful fallback)."""
        paths = [Path(path)] if path else _DEFAULT_CHECKPOINT_PATHS
        for p in paths:
            try:
                if p.is_file():
                    return torch.load(p, map_location="cpu", weights_only=True)
            except Exception:
                continue
        return None

    @staticmethod
    def _init_model(checkpoint: Optional[dict]) -> Optional[StructuredEvaluator]:
        """Initialize and return PyTorch model from checkpoint."""
        if not checkpoint:
            return None
        try:
            config_dict = dict(checkpoint.get("config", {}))
            config_dict.pop("pairwise_weight", None)
            config = EvaluatorConfig(**config_dict)
            model = StructuredEvaluator(config)
            model.load_state_dict(checkpoint["state_dict"], strict=False)
            model.eval()
            return model
        except Exception:
            return None

    def _evaluate_states(self, states: list[dict]) -> list[float]:
        """Evaluate a batch of post-action states using the learned evaluator."""
        if not self._model or not self._checkpoint:
            return [0.0] * len(states)
        try:
            norm = self._checkpoint.get("normalization")
            if not norm:
                return [0.0] * len(states)
            batch = _normalize_batch(states, norm)
            with torch.no_grad():
                outputs = self._model(batch)
                clear_p = outputs["clear_logit"].sigmoid().cpu().numpy()
                surplus = outputs.get("surplus", outputs["clear_logit"]).cpu().numpy()

            w_surplus = float(V14_PARAMS.get("v14_surplus_weight", 1.0))
            w_clear = float(V14_PARAMS.get("v14_clear_weight", 2.0))
            return [float(w_surplus * s + w_clear * c) for s, c in zip(surplus, clear_p)]
        except Exception:
            return [0.0] * len(states)

    def _decide_hand_v14(self, game: BalatroGame) -> dict:
        """In-blind hand decision using analytical decomposition + learned residual evaluation."""
        self._stats["decisions"] += 1

        # Compute heuristic anchor action
        anchor = super().decide(game)

        # ── 1. PRE-ACTIONS & GUARANTEED CLEARS ────────────────────────────────
        # Never override consumable use, planet use, or Verdant joker sells.
        if anchor.get("type") in ("use_consumable", "sell_joker"):
            return anchor

        target = game.current_blind.chips_target - game.chips_scored
        if target <= 0:
            return anchor

        # If a play clears immediately, _tier1_survive already selected the
        # exact optimal hand-conserving play. Preserve it!
        plays = scored_plays(game, topk=1)
        if plays and plays[0][0] >= target:
            self._stats["analytical_clears"] += 1
            return anchor

        # ── 2. SUB-CLEARING RESIDUAL STATE EVALUATION ────────────────────────
        # At this point, NO play clears the blind immediately.
        # Evaluate whether playing or discarding yields higher expected surplus.
        if not bool(V14_PARAMS.get("v14_evaluator", False)):
            return anchor

        if self._model is None or self._checkpoint is None:
            self._stats["no_model_fallback"] += 1
            return anchor

        try:
            candidates = candidate_actions(game, anchor)
        except Exception:
            return anchor

        if not candidates:
            return anchor

        cap = int(V14_PARAMS.get("v14_candidate_cap", 6))
        candidates = candidates[:cap]

        k_samples = max(1, int(V14_PARAMS.get("v14_samples", 1)))
        scores = [0.0] * len(candidates)

        for s_idx in range(k_samples):
            world_base = sample_world(game, f"v14:eval:{s_idx}")
            states_to_eval = []
            eval_indices = []

            for i, cand in enumerate(candidates):
                try:
                    world = clone_game(world_base)
                    world.step(deepcopy(cand["action"]))
                    if world.state == State.ROUND_EVAL or world.chips_scored >= target:
                        # Immediate clear on continuation
                        scores[i] += 10.0 + 0.25 * float(world.hands_left)
                    elif world.state == State.SELECTING_HAND:
                        states_to_eval.append(encode_state(world))
                        eval_indices.append(i)
                    else:
                        # Dead or stuck
                        scores[i] -= 5.0
                except Exception:
                    scores[i] -= 5.0

            if states_to_eval:
                eval_vals = self._evaluate_states(states_to_eval)
                for idx, val in zip(eval_indices, eval_vals):
                    scores[idx] += val

        # Normalize across samples
        scores = [s / k_samples for s in scores]
        self._stats["evaluator_scored"] += 1

        # ── 3. MARGIN-GATED OVERRIDE RULE ────────────────────────────────────
        anchor_key = action_key(anchor)
        anchor_score = None
        best_score = -float("inf")
        best_action = anchor

        for cand, score in zip(candidates, scores):
            if action_key(cand["action"]) == anchor_key and anchor_score is None:
                anchor_score = score
            if score > best_score:
                best_score = score
                best_action = cand["action"]

        if anchor_score is None:
            anchor_score = scores[0]

        margin = float(V14_PARAMS.get("v14_margin", 0.05))
        if best_score - anchor_score > margin:
            self._stats["overrides"] += 1
            return best_action
        else:
            self._stats["retained_anchor"] += 1
            return anchor

    def decide(self, game: BalatroGame) -> dict:
        """Dispatches in-blind decisions to V14 evaluator, shop/booster to SearchShopV11."""
        if game.state == State.SELECTING_HAND:
            return self._decide_hand_v14(game)
        return super().decide(game)

    def stats(self) -> dict[str, int]:
        """Return decision counters for inspection and telemetry."""
        return dict(self._stats)
