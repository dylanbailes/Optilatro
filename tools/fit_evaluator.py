from __future__ import annotations

import argparse
import copy
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import platform
import sys
import time

import numpy as np
import torch
from torch.nn import functional as F

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "vendor" / "balatro-rl"))

from balatro_sim.blind_dataset import read_dataset, seed_split, SPLIT_VERSION, VERSION
from balatro_sim.eval_encoder import flatten_state, schema, validate_state
from balatro_sim.eval_metrics import clear_mask, trial_targets
from balatro_sim.evaluator import EvaluatorConfig, StructuredEvaluator, collate_states, evaluator_loss


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


SEMANTIC_FIELDS = ("version", "policy", "policy_params", "policy_overrides", "world_sampler",
                   "rng_mode", "evaluation_protocol", "selection_rule", "interfaces")


def load_data(path, split):
    split = "validation" if split == "val" else split
    if split not in ("train", "validation", "test"):
        raise ValueError("unknown split")
    with Path(path).open(encoding="utf-8") as stream:
        header = json.loads(stream.readline())
    if header.get("schema") != schema():
        raise ValueError("dataset encoder schema mismatch")
    if header.get("split_version") != SPLIT_VERSION:
        raise ValueError("dataset split version mismatch")
    if header.get("version") != VERSION:
        raise ValueError("dataset version mismatch")
    rows = []
    seen = set()
    for row in read_dataset(path):
        identity = row["seed"], row["decision_id"]
        if identity in seen:
            raise ValueError("duplicate decision identity")
        seen.add(identity)
        if row["split"] != seed_split(row["seed"]):
            raise ValueError("seed hash split mismatch")
        if row.get("version") != 1 or type(row.get("anchor")) is not int or not 0 <= row["anchor"] < len(row.get("arms", [])):
            raise ValueError("invalid decision contract")
        actions = [json.dumps(a["action"], sort_keys=True) for a in row["arms"]]
        if len(actions) != len(set(actions)):
            raise ValueError("duplicate candidate action")
        if row["split"] == split:
            for pool in ("coverage_arms", "independent_arms"):
                for arm in row.get(pool, []):
                    for trial in arm["trials"]:
                        trial.pop("state", None)
            rows.append(row)
    return header, rows


def source_manifest(path, header):
    return {"path": str(path.resolve()), "sha256": sha256_file(path), "metadata": header}


def load_training(paths):
    paths = [path.resolve() for path in paths]
    if len(paths) != len(set(paths)):
        raise ValueError("duplicate training source path")
    rows, sources, semantics = [], [], {}
    seen = set()
    for path in paths:
        header, selected = load_data(path, "train")
        for field in SEMANTIC_FIELDS:
            if field in header:
                if field in semantics and header[field] != semantics[field]:
                    raise ValueError(f"training source {field} mismatch: {path}")
                semantics[field] = header[field]
        for row in selected:
            identity = row["seed"], row["decision_id"]
            if identity in seen:
                raise ValueError(f"duplicate decision identity across training sources: {identity}")
            seen.add(identity)
        rows.extend(selected)
        sources.append(source_manifest(path, header))
    provenance = {"sources": sources}
    if len(sources) == 1:
        provenance.update(sources[0])
    return rows, provenance


def guard_splits(train, val, test):
    banks = [{r["seed"] for r in rows} for rows in (train, val, test)]
    if any(banks[i] & banks[j] for i, j in ((0, 1), (0, 2), (1, 2))):
        raise ValueError("train/validation/test seed overlap")
    for rows, split in zip((train, val, test), ("train", "validation", "test")):
        identities = [(r["seed"], r["decision_id"]) for r in rows]
        if len(identities) != len(set(identities)):
            raise ValueError("duplicate decision identity")
        if any(r["split"] != split or seed_split(r["seed"]) != split for r in rows):
            raise ValueError("incorrect seed split")


def usable_decisions(rows):
    groups = []
    for row in rows:
        samples = []
        for arm_index, arm in enumerate(row["arms"]):
            for trial_index, trial in enumerate(arm["trials"]):
                if not clear_mask([trial])[0] or trial.get("state") is None:
                    continue
                validate_state(trial["state"])
                samples.append({"state": trial["state"], "targets": trial_targets(trial, row["ante"]),
                                "arm": arm_index, "trial": trial_index})
        if samples:
            groups.append({"seed": row["seed"], "decision_id": row["decision_id"], "samples": samples})
    return groups


def _statistics(rows, width):
    if not rows:
        return {"mean": [0.0] * width, "scale": [1.0] * width}
    array = np.asarray(rows, dtype=np.float64)
    mean, scale = array.mean(0), array.std(0)
    scale = np.where(scale < 1e-8, 1.0, scale)
    if not np.isfinite(mean).all() or not np.isfinite(scale).all():
        raise ValueError("normalization overflow")
    return {"mean": mean.tolist(), "scale": scale.tolist()}


def fit_normalization(states, architecture):
    if not states:
        raise ValueError("no training states for normalization")
    for state in states:
        validate_state(state)
    if architecture == "histgbm":
        return {"kind": "flat", "flat": _statistics([flatten_state(s) for s in states], schema()["flat_dim"])}
    result = {"kind": "tokens"}
    for block, dim in (("context", "context_dim"), ("cards", "card_dim"), ("jokers", "joker_dim")):
        rows = [s[block] for s in states] if block == "context" else [r for s in states for r in s[block]]
        result[block] = _statistics(rows, schema()[dim])
    result["jokers"]["mean"][0] = 0.0
    result["jokers"]["scale"][0] = 1.0
    return result


def normalized_batch(states, normalization):
    if normalization["kind"] == "flat":
        stats = normalization["flat"]
        return (np.asarray([flatten_state(s) for s in states]) - stats["mean"]) / stats["scale"]
    batch = collate_states(states)
    for block in ("context", "cards", "jokers"):
        mean = batch[block].new_tensor(normalization[block]["mean"])
        scale = batch[block].new_tensor(normalization[block]["scale"])
        if not torch.isfinite(mean).all() or not torch.isfinite(scale).all() or (scale <= 0).any():
            raise ValueError("invalid normalization")
        batch[block] = (batch[block] - mean) / scale
        if block != "context":
            batch[block] = batch[block].masked_fill(~batch[f"{block}_mask"].unsqueeze(-1), 0)
    return batch


def grouped_loss(outputs, targets, groups, weights=None, arms=None, pairwise_weight=0.0):
    if pairwise_weight < 0 or not np.isfinite(pairwise_weight):
        raise ValueError("pairwise weight must be finite and nonnegative")
    losses = []
    for group in dict.fromkeys(groups):
        indices = [i for i, value in enumerate(groups) if value == group]
        prediction = {key: value[indices] for key, value in outputs.items()}
        target = {key: value[indices] for key, value in targets.items()}
        loss = evaluator_loss(prediction, target, weights=weights)
        if pairwise_weight:
            if arms is None:
                raise ValueError("pairwise loss requires arm groups")
            arm_ids = [arms[i] for i in indices]
            values = []
            for arm in dict.fromkeys(arm_ids):
                positions = [i for i, a in enumerate(arm_ids) if a == arm and torch.isfinite(target["clear"][i])]
                if positions:
                    values.append((prediction["clear_logit"][positions].sigmoid().mean(), target["clear"][positions].mean()))
            contrasts = []
            for i, (p, y) in enumerate(values):
                for q, z in values[i + 1:]:
                    if abs(float(y - z)) > 1e-12:
                        contrasts.append(F.softplus(-(p - q) * torch.sign(y - z)) * torch.abs(y - z))
            if contrasts:
                loss = loss + pairwise_weight * torch.stack(contrasts).mean()
        losses.append(loss)
    if not losses:
        raise ValueError("empty decision batch")
    return torch.stack(losses).mean()


def group_batch(groups, normalization):
    samples = [s for group in groups for s in group["samples"]]
    target_names = [n for n in ("clear", "ratio", "horizons", "dense", "final_ante", "win", "surplus")
                    if samples and n in samples[0]["targets"]]
    targets = {name: torch.tensor([s["targets"][name] for s in samples], dtype=torch.float32)
               for name in target_names}
    ids = [i for i, group in enumerate(groups) for _ in group["samples"]]
    return normalized_batch([s["state"] for s in samples], normalization), targets, ids, [s["arm"] for s in samples]


def validation_bce(model, groups, normalization):
    model.eval()
    losses = []
    with torch.no_grad():
        for group in groups:
            batch, targets, _, _ = group_batch([group], normalization)
            logits = model(batch)["clear_logit"]
            losses.append(float(F.binary_cross_entropy_with_logits(logits, targets["clear"])))
    return float(np.mean(losses)) if losses else None


def _export_gbm(model):
    trees = []
    for iteration in model._predictors:
        nodes = iteration[0].nodes
        trees.append({name: nodes[name].tolist() for name in
                      ("value", "feature_idx", "num_threshold", "missing_go_to_left", "left", "right", "is_leaf", "is_categorical")})
    return {"baseline": float(model._baseline_prediction[0, 0]), "trees": trees}


def predict_gbm(state_dict, features):
    logits = np.full(len(features), state_dict["baseline"], dtype=float)
    for tree in state_dict["trees"]:
        for i, row in enumerate(features):
            node = 0
            while not tree["is_leaf"][node]:
                if tree["is_categorical"][node]:
                    raise ValueError("categorical GBM trees are unsupported")
                value = row[tree["feature_idx"][node]]
                left = tree["missing_go_to_left"][node] if np.isnan(value) else value <= tree["num_threshold"][node]
                node = tree["left" if left else "right"][node]
            logits[i] += tree["value"][node]
    return 1 / (1 + np.exp(-np.clip(logits, -700, 700)))


def profile_weights(loss_profile, pairwise_weight=0.0):
    if loss_profile not in ("multitask", "clear-only"):
        raise ValueError("unknown loss profile")
    if loss_profile == "clear-only" and pairwise_weight != 0:
        raise ValueError("clear-only does not support nonzero pairwise weight")
    weights = EvaluatorConfig().loss_weights
    return weights if loss_profile == "multitask" else {key: float(key == "clear") for key in weights}


def train_model(train_rows, val_rows, test_rows, *, arch="attention", epochs=10, hidden=128,
                seed=0, batch_decisions=8, lr=0.001, pairwise_weight=0.0, loss_profile="multitask"):
    loss_weights = profile_weights(loss_profile, pairwise_weight)
    if epochs < 1 or batch_decisions < 1 or hidden < 1 or not np.isfinite(lr) or lr <= 0:
        raise ValueError("invalid training parameters")
    if not np.isfinite(pairwise_weight) or pairwise_weight < 0:
        raise ValueError("invalid pairwise weight")
    guard_splits(train_rows, val_rows, test_rows)
    train, val = usable_decisions(train_rows), usable_decisions(val_rows)
    if not train or not val:
        raise ValueError("training and validation need usable uncensored Bernoulli samples")
    if not test_rows:
        raise ValueError("zero holdout decisions")
    torch.manual_seed(seed)
    rng = np.random.default_rng(seed)
    requested, fallback = arch, None
    classifier = None
    if arch == "histgbm":
        if pairwise_weight:
            raise ValueError("HistGBM does not support pairwise loss")
        try:
            from sklearn.ensemble import HistGradientBoostingClassifier
            classifier = HistGradientBoostingClassifier
        except ImportError:
            arch, fallback = "mlp", "sklearn unavailable; flat MLP control used"
    arch = "mlp" if arch == "flat" else arch
    states = [s["state"] for group in train for s in group["samples"]]
    normalization = fit_normalization(states, arch)
    samples = [s for group in train for s in group["samples"]]
    history, best_state, best_loss, best_epoch = [], None, float("inf"), None
    if arch == "histgbm":
        labels = np.asarray([s["targets"]["clear"] for s in samples])
        weights = np.asarray([1 / len(g["samples"]) for g in train for _ in g["samples"]])
        x = normalized_batch(states, normalization)
        if len(set(labels.tolist())) < 2:
            probability = float(np.average(labels, weights=weights))
            probability = min(1 - 1e-7, max(1e-7, probability))
            best_state = {"baseline": float(np.log(probability / (1 - probability))), "trees": []}
            best_epoch = 0
            scores = []
            for group in val:
                y = np.asarray([s["targets"]["clear"] for s in group["samples"]])
                scores.append(float(-(y * np.log(probability) + (1 - y) * np.log1p(-probability)).mean()))
            best_loss = float(np.mean(scores))
        else:
            model = classifier(max_iter=1, warm_start=True, early_stopping=False, random_state=seed, learning_rate=0.1)
            for epoch in range(1, epochs + 1):
                model.set_params(max_iter=epoch)
                model.fit(x, labels, sample_weight=weights)
                state = _export_gbm(model)
                scores = []
                for group in val:
                    p = predict_gbm(state, normalized_batch([s["state"] for s in group["samples"]], normalization))
                    p = np.clip(p, 1e-7, 1 - 1e-7)
                    y = np.asarray([s["targets"]["clear"] for s in group["samples"]])
                    scores.append(float(-(y * np.log(p) + (1 - y) * np.log1p(-p)).mean()))
                score = float(np.mean(scores))
                history.append({"epoch": epoch, "validation_bce": score})
                if score < best_loss:
                    best_state, best_loss, best_epoch = state, score, epoch
        loss_profile = "clear-only"
        loss_weights = profile_weights(loss_profile)
        config = {"architecture": "histgbm", "pairwise_weight": 0.0, "loss_weights": loss_weights}
    else:
        config_object = EvaluatorConfig(architecture=arch, d_model=hidden, loss_weights=loss_weights)
        model = StructuredEvaluator(config_object)
        optimizer = torch.optim.AdamW(model.parameters(), lr=lr)
        for epoch in range(1, epochs + 1):
            model.train()
            order = rng.permutation(len(train)).tolist()
            train_losses = []
            for start in range(0, len(order), batch_decisions):
                groups = [train[i] for i in order[start:start + batch_decisions]]
                batch, targets, ids, arms = group_batch(groups, normalization)
                optimizer.zero_grad(set_to_none=True)
                loss = grouped_loss(model(batch), targets, ids, weights=config_object.loss_weights,
                                    arms=arms, pairwise_weight=pairwise_weight)
                if not torch.isfinite(loss):
                    raise ValueError("nonfinite training loss")
                loss.backward()
                torch.nn.utils.clip_grad_norm_(model.parameters(), 5.0, error_if_nonfinite=True)
                optimizer.step()
                train_losses.extend([float(loss.detach())] * len(groups))
            score = validation_bce(model, val, normalization)
            if not np.isfinite(score):
                raise ValueError("nonfinite validation BCE")
            history.append({"epoch": epoch, "train_loss": float(np.mean(train_losses)), "validation_bce": score})
            if score < best_loss:
                best_state, best_loss, best_epoch = copy.deepcopy(model.state_dict()), score, epoch
        config = dict(asdict(config_object), pairwise_weight=pairwise_weight)
    identities = [[g["seed"], g["decision_id"], s["arm"], s["trial"]] for g in train for s in g["samples"]]
    checkpoint = {
        "version": 1, "state_dict": best_state, "config": config, "schema": schema(),
        "seed_ids": {name: sorted({r["seed"] for r in rows}) for name, rows in
                     (("train", train_rows), ("validation", val_rows), ("test", test_rows))},
        "split_version": SPLIT_VERSION, "normalization": normalization,
        "env": {"python": platform.python_version(), "torch": str(torch.__version__), "numpy": str(np.__version__), "platform": platform.platform()},
        "samples": {"train": len(samples), "validation": sum(len(g["samples"]) for g in val)},
        "usable_sample_fingerprint": hashlib.sha256(json.dumps(identities).encode()).hexdigest(),
        "selection": {"metric": "validation_bce", "value": best_loss, "epoch": best_epoch, "test_used": False},
        "history": history, "requested_arch": requested, "fallback": fallback,
        "training": {"seed": seed, "epochs": epochs, "batch_decisions": batch_decisions, "lr": lr, "loss_profile": loss_profile,
                     "weighting": "equal decision weight; raw trial Bernoulli targets", "optimizer": "AdamW" if arch != "histgbm" else "HistGradientBoostingClassifier"},
    }
    if arch == "histgbm":
        import sklearn
        checkpoint["env"]["sklearn"] = str(sklearn.__version__)
    return checkpoint


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--train", required=True, type=Path, action="append",
                        help="training dataset; repeat to concatenate train splits in argument order")
    for name in ("val", "test", "out"):
        parser.add_argument(f"--{name}", required=True, type=Path)
    parser.add_argument("--arch", choices=("attention", "pooled", "mlp", "flat", "histgbm"), default="attention")
    parser.add_argument("--epochs", type=int, default=10)
    parser.add_argument("--hidden", type=int, default=128)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--batch-decisions", type=int, default=8)
    parser.add_argument("--lr", type=float, default=0.001)
    parser.add_argument("--pairwise-weight", type=float, default=0.0)
    parser.add_argument("--loss-profile", choices=("multitask", "clear-only"), default="multitask")
    args = parser.parse_args(argv)
    try:
        profile_weights(args.loss_profile, args.pairwise_weight)
    except ValueError as error:
        parser.error(str(error))
    if not args.out.parent.is_dir():
        parser.error("output parent directory must exist")
    if args.out.exists():
        parser.error("refusing to overwrite checkpoint")
    torch.set_num_threads(1)
    started = time.monotonic()
    train_rows, train_provenance = load_training(args.train)
    rows, provenance = [train_rows], {"train": train_provenance}
    for path, split in ((args.val, "validation"), (args.test, "test")):
        header, selected = load_data(path, split)
        rows.append(selected)
        provenance[split] = source_manifest(path, header)
    checkpoint = train_model(*rows, arch=args.arch, epochs=args.epochs, hidden=args.hidden, seed=args.seed,
                             batch_decisions=args.batch_decisions, lr=args.lr, pairwise_weight=args.pairwise_weight,
                             loss_profile=args.loss_profile)
    checkpoint["provenance"] = provenance
    checkpoint["elapsed_seconds"] = time.monotonic() - started
    with args.out.open("xb") as stream:
        torch.save(checkpoint, stream)
    torch.load(args.out, map_location="cpu", weights_only=True)
    print(json.dumps({"checkpoint": str(args.out), "selection": checkpoint["selection"], "samples": checkpoint["samples"],
                      "fallback": checkpoint["fallback"], "elapsed_seconds": checkpoint["elapsed_seconds"]}, allow_nan=False))


if __name__ == "__main__":
    main()
