from __future__ import annotations

import math
from dataclasses import dataclass, field

import torch
from torch import Tensor, nn
from torch.nn import functional as F

from .eval_encoder import FLAT_JOKER_SLOTS, schema, validate_state


QUANTILE_LEVELS = (0.1, 0.25, 0.5, 0.75, 0.9)
DEFAULT_LOSS_WEIGHTS = {"clear": 1.0, "ratio": 0.1, "horizons": 0.05, "dense": 0.05, "final_ante": 0.05, "win": 0.05}


@dataclass
class EvaluatorConfig:
    architecture: str = "attention"
    context_dim: int = field(default_factory=lambda: schema()["context_dim"])
    card_dim: int = field(default_factory=lambda: schema()["card_dim"])
    joker_dim: int = field(default_factory=lambda: schema()["joker_dim"])
    d_model: int = 128
    num_layers: int = 2
    num_heads: int = 4
    dropout: float = 0.0
    loss_weights: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_LOSS_WEIGHTS))

    def __post_init__(self):
        if self.architecture not in ("attention", "pooled", "mlp"):
            raise ValueError("architecture must be attention, pooled or mlp")
        if any(not isinstance(value, int) or value <= 0 for value in (self.context_dim, self.card_dim, self.joker_dim, self.d_model, self.num_heads)):
            raise ValueError("dimensions and head count must be positive integers")
        if self.num_layers not in (1, 2):
            raise ValueError("num_layers must be 1 or 2")
        if self.architecture == "attention" and self.d_model % self.num_heads:
            raise ValueError("d_model must be divisible by num_heads")
        if not 0 <= self.dropout < 1:
            raise ValueError("dropout must be in [0, 1)")
        _validate_weights(self.loss_weights)


def _validate_weights(weights):
    allowed = set(DEFAULT_LOSS_WEIGHTS) | {"surplus"}
    if set(weights) - allowed:
        raise ValueError("unknown loss weight")
    if any(not math.isfinite(value) or value < 0 for value in weights.values()):
        raise ValueError("loss weights must be finite and nonnegative")


def collate_states(states: list[dict]) -> dict[str, Tensor]:
    if not states:
        raise ValueError("cannot collate an empty batch")
    for state in states:
        validate_state(state)
    dimensions = schema()
    result = {"context": torch.tensor([state["context"] for state in states], dtype=torch.float32)}
    for block, dim in (("cards", dimensions["card_dim"]), ("jokers", dimensions["joker_dim"])):
        size = max(len(state[block]) for state in states)
        result[block] = torch.zeros(len(states), size, dim, dtype=torch.float32)
        result[f"{block}_mask"] = torch.zeros(len(states), size, dtype=torch.bool)
        for index, state in enumerate(states):
            count = len(state[block])
            if count:
                result[block][index, :count] = torch.tensor(state[block], dtype=torch.float32)
                result[f"{block}_mask"][index, :count] = True
    if any(not torch.isfinite(value).all() for value in result.values()):
        raise ValueError("encoded values must remain finite in float32")
    return result


def _pool(values: Tensor, mask: Tensor) -> tuple[Tensor, Tensor, Tensor, Tensor]:
    clean = values.masked_fill(~mask.unsqueeze(-1), 0)
    count = mask.sum(1, keepdim=True).to(values.dtype)
    total = clean.sum(1)
    mean = total / count.clamp_min(1)
    if values.shape[1]:
        maximum = values.masked_fill(~mask.unsqueeze(-1), -torch.inf).amax(1)
        maximum = torch.where(count > 0, maximum, torch.zeros_like(maximum))
    else:
        maximum = total
    return count, total, mean, maximum


def _flat_batch(batch: dict[str, Tensor]) -> Tensor:
    count, total, mean, maximum = _pool(batch["cards"], batch["cards_mask"])
    parts = [batch["context"], count, total, mean, maximum]
    jokers, mask = batch["jokers"], batch["jokers_mask"]
    parts.append(mask.sum(1, keepdim=True).to(jokers.dtype))
    for slot in range(FLAT_JOKER_SLOTS):
        parts.append(_pool(jokers, mask & (jokers[:, :, 0] == slot))[1])
    overflow = mask & (jokers[:, :, 0] >= FLAT_JOKER_SLOTS)
    clean = jokers.masked_fill(~overflow.unsqueeze(-1), 0)
    parts.extend([clean.sum(1), (clean * (clean[:, :, :1] + 1)).sum(1)])
    return torch.cat(parts, dim=-1)


class StructuredEvaluator(nn.Module):
    def __init__(self, config: EvaluatorConfig | None = None):
        super().__init__()
        self.config = config if config is not None else EvaluatorConfig()
        c = self.config
        if c.architecture == "mlp":
            width = c.context_dim + 1 + 3 * c.card_dim + 1 + (FLAT_JOKER_SLOTS + 2) * c.joker_dim
        else:
            self.context_projection = nn.Sequential(nn.Linear(c.context_dim, c.d_model), nn.GELU(), nn.LayerNorm(c.d_model))
            self.card_projection = nn.Sequential(nn.Linear(c.card_dim, c.d_model), nn.GELU(), nn.LayerNorm(c.d_model))
            self.joker_projection = nn.Sequential(nn.Linear(c.joker_dim, c.d_model), nn.GELU(), nn.LayerNorm(c.d_model))
            if c.architecture == "attention":
                layer = nn.TransformerEncoderLayer(c.d_model, c.num_heads, dim_feedforward=4 * c.d_model, dropout=c.dropout, activation="gelu", batch_first=True)
                self.attention = nn.TransformerEncoder(layer, c.num_layers, enable_nested_tensor=False)
                width = c.d_model
            else:
                width = 7 * c.d_model + 2
        layers = [nn.Linear(width, c.d_model), nn.GELU(), nn.Dropout(c.dropout)]
        if c.architecture != "attention":
            for _ in range(c.num_layers - 1):
                layers.extend([nn.Linear(c.d_model, c.d_model), nn.GELU(), nn.Dropout(c.dropout)])
        self.trunk = nn.Sequential(*layers)
        self.heads = nn.Linear(c.d_model, 13)
        if self.parameter_count > 5000000:
            raise ValueError("evaluator exceeds the 5M parameter limit")

    @property
    def parameter_count(self) -> int:
        return sum(parameter.numel() for parameter in self.parameters())

    def forward(self, batch: dict[str, Tensor]) -> dict[str, Tensor]:
        c = self.config
        context = batch["context"]
        if context.ndim != 2 or context.shape[1] != c.context_dim:
            raise ValueError("invalid context shape")
        if not torch.isfinite(context).all():
            raise ValueError("context must be finite")
        clean = {"context": context}
        for block, width in (("cards", c.card_dim), ("jokers", c.joker_dim)):
            values, mask = batch[block], batch[f"{block}_mask"]
            if values.ndim != 3 or values.shape[0] != context.shape[0] or values.shape[2] != width:
                raise ValueError(f"invalid {block} shape")
            if mask.shape != values.shape[:2] or mask.dtype != torch.bool:
                raise ValueError(f"invalid {block} mask")
            clean[block] = values.masked_fill(~mask.unsqueeze(-1), 0)
            clean[f"{block}_mask"] = mask
            if not torch.isfinite(clean[block]).all():
                raise ValueError(f"{block} must be finite")
        if c.architecture == "mlp":
            features = _flat_batch(clean)
        else:
            context_token = self.context_projection(context)
            cards = self.card_projection(clean["cards"])
            jokers = self.joker_projection(clean["jokers"])
            if c.architecture == "attention":
                tokens = torch.cat([context_token.unsqueeze(1), cards, jokers], dim=1)
                mask = torch.cat([torch.ones(context.shape[0], 1, dtype=torch.bool, device=context.device), clean["cards_mask"], clean["jokers_mask"]], dim=1)
                features = self.attention(tokens, src_key_padding_mask=~mask)[:, 0]
            else:
                features = torch.cat([context_token, *_pool(cards, clean["cards_mask"]), *_pool(jokers, clean["jokers_mask"])], dim=-1)
        output = self.heads(self.trunk(features))
        return {
            "clear_logit": output[:, 0],
            "quantiles": F.softplus(output[:, 1:6]).cumsum(-1),
            "horizon_logits": output[:, 6:9],
            "dense": output[:, 9],
            "final_ante": output[:, 10],
            "win_logit": output[:, 11],
            "surplus": output[:, 12],
        }


def evaluator_loss(outputs: dict[str, Tensor], targets: dict[str, Tensor], *, weights: dict[str, float] | None = None) -> Tensor:
    weights = {**DEFAULT_LOSS_WEIGHTS, **(weights or {})}
    _validate_weights(weights)
    mapping = {"clear": "clear_logit", "surplus": "surplus", "ratio": "quantiles", "horizons": "horizon_logits", "dense": "dense", "final_ante": "final_ante", "win": "win_logit"}
    batch_size = outputs["clear_logit"].shape[0]
    loss = outputs["clear_logit"].new_zeros(())
    for name, key in mapping.items():
        if key not in outputs:
            continue
        prediction = outputs[key]
        shape = (batch_size, 5) if name == "ratio" else (batch_size, 3) if name == "horizons" else (batch_size,)
        if prediction.shape != shape or not torch.isfinite(prediction).all():
            raise ValueError(f"{key} must have shape {shape} and be finite")
        loss = loss + prediction.sum() * 0
        if name not in targets:
            continue
        target = targets[name].to(device=prediction.device, dtype=prediction.dtype)
        target_shape = (batch_size,) if name == "ratio" else shape
        if target.shape != target_shape or torch.isinf(target).any():
            raise ValueError(f"{name} targets must have shape {target_shape}; only NaN may indicate missing")
        mask = ~torch.isnan(target)
        observed = target[mask]
        if name in ("clear", "horizons", "win") and ((observed < 0) | (observed > 1)).any():
            raise ValueError(f"{name} targets must be in [0, 1]")
        if name == "ratio" and (observed < 0).any():
            raise ValueError("ratio targets must be nonnegative")
        if not mask.any():
            continue
        if name == "ratio":
            error = torch.log1p(observed).unsqueeze(-1) - prediction[mask]
            levels = prediction.new_tensor(QUANTILE_LEVELS)
            component = torch.maximum(levels * error, (levels - 1) * error).mean()
        elif name in ("clear", "horizons", "win"):
            component = F.binary_cross_entropy_with_logits(prediction[mask], observed)
        else:
            component = F.smooth_l1_loss(prediction[mask], observed)
        loss = loss + weights.get(name, 0.0) * component
    return loss
