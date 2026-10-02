import copy
import io
import json
import math
from dataclasses import asdict

import pytest
import torch
import torch.nn.functional as F

from balatro_sim.game import BalatroGame


def states():
    from balatro_sim.eval_encoder import encode_state

    game = BalatroGame(seed=70123, rng_mode="seed")
    empty = encode_state(game)
    game.step({"type": "play_blind"})
    game.grant_joker("j_blueprint")
    game.grant_joker("j_baron")
    return [empty, encode_state(game)]


def targets(batch=2):
    return {
        "clear": torch.tensor([1.0, float("nan")])[:batch],
        "surplus": torch.tensor([1.5, float("nan")])[:batch],
        "ratio": torch.tensor([100.0, float("nan")])[:batch],
        "horizons": torch.tensor([[1.0, float("nan"), 0.0], [float("nan")] * 3])[:batch],
        "dense": torch.tensor([8.0, float("nan")])[:batch],
        "final_ante": torch.tensor([8.0, float("nan")])[:batch],
        "win": torch.tensor([0.0, float("nan")])[:batch],
    }


@pytest.mark.parametrize("architecture", ["attention", "pooled", "mlp"])
def test_outputs_monotone_finite_and_backprop(architecture):
    from balatro_sim.evaluator import EvaluatorConfig, StructuredEvaluator, collate_states, evaluator_loss

    model = StructuredEvaluator(EvaluatorConfig(architecture=architecture))
    batch = collate_states(states())
    output = model(batch)
    shapes = {"clear_logit": (2,), "surplus": (2,), "quantiles": (2, 5), "horizon_logits": (2, 3), "dense": (2,), "final_ante": (2,), "win_logit": (2,)}
    assert set(output) == set(shapes)
    for key, shape in shapes.items():
        assert output[key].shape == shape
        assert torch.isfinite(output[key]).all()
    assert (output["quantiles"][:, 1:] >= output["quantiles"][:, :-1]).all()
    assert (output["quantiles"] >= 0).all()
    loss = evaluator_loss(output, targets())
    assert loss.ndim == 0 and torch.isfinite(loss)
    loss.backward()
    grads = [p.grad for p in model.parameters() if p.requires_grad]
    assert all(g is not None and torch.isfinite(g).all() for g in grads)
    assert sum(g.abs().sum().item() for g in grads) > 0


@pytest.mark.parametrize("architecture", ["attention", "pooled", "mlp"])
def test_padding_batching_and_token_permutations(architecture):
    from balatro_sim.evaluator import EvaluatorConfig, StructuredEvaluator, collate_states

    model = StructuredEvaluator(EvaluatorConfig(architecture=architecture)).eval()
    encoded = states()
    batch = collate_states(encoded)
    expected = model(batch)
    padded = {key: value.clone() for key, value in batch.items()}
    for block in ("cards", "jokers"):
        padded[block] = F.pad(padded[block], (0, 0, 0, 4), value=9999)
        padded[f"{block}_mask"] = F.pad(padded[f"{block}_mask"], (0, 4), value=False)
    actual = model(padded)
    for key in expected:
        torch.testing.assert_close(expected[key], actual[key], atol=2e-5, rtol=2e-5)
        for index, state in enumerate(encoded):
            single = model(collate_states([state]))
            torch.testing.assert_close(expected[key][index], single[key][0], atol=2e-5, rtol=2e-5)
    permuted = copy.deepcopy(encoded)
    for state in permuted:
        state["cards"].reverse()
        state["jokers"].reverse()
    result = model(collate_states(permuted))
    for key in expected:
        torch.testing.assert_close(expected[key], result[key], atol=2e-5, rtol=2e-5)


def test_joker_slots_affect_attention_prediction():
    from balatro_sim.evaluator import StructuredEvaluator, collate_states
    from balatro_sim.eval_encoder import schema

    torch.manual_seed(1)
    model = StructuredEvaluator().eval()
    state = states()[1]
    swapped = copy.deepcopy(state)
    slot = schema()["joker_names"].index("slot")
    swapped["jokers"][0][slot], swapped["jokers"][1][slot] = swapped["jokers"][1][slot], swapped["jokers"][0][slot]
    output = model(collate_states([state, swapped]))
    assert not torch.equal(output["clear_logit"][0], output["clear_logit"][1])


def test_empty_tokens_and_collate_validation():
    from balatro_sim.evaluator import StructuredEvaluator, collate_states
    from balatro_sim.eval_encoder import schema

    state = states()[0]
    state["cards"] = []
    batch = collate_states([state])
    assert batch["cards"].shape == (1, 0, schema()["card_dim"])
    assert batch["jokers"].shape == (1, 0, schema()["joker_dim"])
    assert batch["cards_mask"].dtype == torch.bool
    assert all(torch.isfinite(v).all() for v in StructuredEvaluator()(batch).values())
    with pytest.raises(ValueError):
        collate_states([])
    state["context"][0] = float("nan")
    with pytest.raises(ValueError, match="finite"):
        collate_states([state])
    state["context"] = [0.0]
    with pytest.raises(ValueError):
        collate_states([state])


def test_loss_nan_masks_and_unclipped_log1p_pinball():
    from balatro_sim.evaluator import evaluator_loss

    output = {
        "clear_logit": torch.zeros(2, requires_grad=True),
        "surplus": torch.zeros(2, requires_grad=True),
        "quantiles": torch.zeros(2, 5, requires_grad=True),
        "horizon_logits": torch.zeros(2, 3, requires_grad=True),
        "dense": torch.zeros(2, requires_grad=True),
        "final_ante": torch.zeros(2, requires_grad=True),
        "win_logit": torch.zeros(2, requires_grad=True),
    }
    missing = {key: torch.full_like(value, float("nan")) for key, value in targets().items()}
    zero = evaluator_loss(output, missing)
    assert zero.item() == 0
    zero.backward()
    assert all(value.grad is not None and (value.grad == 0).all() for value in output.values())
    missing["clear"][0] = 1
    torch.testing.assert_close(evaluator_loss(output, missing), torch.tensor(math.log(2)))
    missing["clear"][0] = float("nan")
    missing["ratio"][0] = 100
    weights = {"clear": 1.0, "surplus": 0.0, "ratio": 1.0, "horizons": 0.0, "dense": 0.0, "final_ante": 0.0, "win": 0.0}
    torch.testing.assert_close(evaluator_loss(output, missing, weights=weights), torch.tensor(0.5 * math.log1p(100)))
    loss = evaluator_loss(output, targets(), weights={key: 1.0 for key in targets()})
    for value in output.values():
        value.grad = None
    loss.backward()
    assert all((value.grad[1] == 0).all() for value in output.values())
    assert output["horizon_logits"].grad[0, 1] == 0


@pytest.mark.parametrize("key,bad", [("clear", 2.0), ("ratio", -1.0), ("dense", float("inf")), ("horizons", -1.0)])
def test_invalid_targets_rejected(key, bad):
    from balatro_sim.evaluator import StructuredEvaluator, collate_states, evaluator_loss

    target = targets()
    target[key][0] = bad
    with pytest.raises(ValueError):
        evaluator_loss(StructuredEvaluator()(collate_states(states())), target)


@pytest.mark.parametrize("architecture", ["attention", "pooled", "mlp"])
def test_config_checkpoint_roundtrip_and_parameter_count(architecture):
    from balatro_sim.evaluator import EvaluatorConfig, StructuredEvaluator, collate_states
    from balatro_sim.eval_encoder import schema

    config = EvaluatorConfig(architecture=architecture)
    assert (config.context_dim, config.card_dim, config.joker_dim) == tuple(schema()[key] for key in ("context_dim", "card_dim", "joker_dim"))
    assert config.d_model == 128 and config.num_layers == 2
    restored = EvaluatorConfig(**json.loads(json.dumps(asdict(config))))
    assert restored == config
    model = StructuredEvaluator(config).eval()
    count = sum(p.numel() for p in model.parameters())
    assert count == model.parameter_count
    assert 0 < count <= 5000000
    buffer = io.BytesIO()
    torch.save({"config": asdict(config), "state_dict": model.state_dict(), "schema": schema()}, buffer)
    buffer.seek(0)
    checkpoint = torch.load(buffer, weights_only=True)
    other = StructuredEvaluator(EvaluatorConfig(**checkpoint["config"])).eval()
    other.load_state_dict(checkpoint["state_dict"])
    assert checkpoint["schema"] == schema()
    batch = collate_states(states())
    for key, value in model(batch).items():
        torch.testing.assert_close(value, other(batch)[key], rtol=0, atol=0)
