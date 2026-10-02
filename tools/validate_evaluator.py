from __future__ import annotations

import argparse
import copy
import json
import math
from pathlib import Path
import sys
import time

import numpy as np
import torch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "vendor" / "balatro-rl"))

from tools.fit_evaluator import load_data, normalized_batch, predict_gbm
from balatro_sim.blind_dataset import seed_split, SPLIT_VERSION
from balatro_sim.eval_encoder import schema
from balatro_sim.eval_metrics import (
    bootstrap_seed_ci, brier, clear_mask, finite, gate_verdict, paired_improvement,
    quantile_coverage, reference_coverage, trial_targets, split_world_trials, SPLIT_PROTOCOL, SELECTION_RULE,
)
from balatro_sim.evaluator import EvaluatorConfig, StructuredEvaluator, QUANTILE_LEVELS


def validate_checkpoint(checkpoint, rows, split):
    if split not in ("test", "validation"):
        raise ValueError("validation only accepts heldout test or validation split, never train")
    if checkpoint.get("schema") != schema() or checkpoint.get("split_version") != SPLIT_VERSION:
        raise ValueError("checkpoint schema or split mismatch")
    seeds = checkpoint.get("seed_ids", {})
    banks = {name: set(seeds.get(name, [])) for name in ("train", "validation", "test")}
    if any(banks[a] & banks[b] for a, b in (("train", "validation"), ("train", "test"), ("validation", "test"))):
        raise ValueError("checkpoint seed overlap")
    actual = {r["seed"] for r in rows}
    forbidden = banks["train"] | (banks["validation"] if split == "test" else banks["test"])
    if actual & forbidden:
        raise ValueError("holdout overlaps training/selection seeds")
    if any(r["split"] != split or seed_split(r["seed"]) != split for r in rows):
        raise ValueError("holdout split mismatch")
    if checkpoint.get("selection", {}).get("test_used") is not False:
        raise ValueError("checkpoint lacks test isolation evidence")
    if not seeds.get("train") or not seeds.get("validation"):
        raise ValueError("checkpoint lacks training/validation seed provenance")


def head_availability(checkpoint):
    config = checkpoint["config"]
    weights = {**EvaluatorConfig().loss_weights, **config.get("loss_weights", {})}
    clear_only = (config["architecture"] == "histgbm" or
                  checkpoint.get("training", {}).get("loss_profile") == "clear-only")
    mapping = {"clear": "clear", "quantiles": "ratio", "horizons": "horizons",
               "dense": "dense", "final_ante": "final_ante", "win": "win"}
    return {head: weights.get(loss, 0.0) > 0 and (not clear_only or head == "clear") for head, loss in mapping.items()}


def predict_rows(checkpoint, rows, batch_size=256):
    available = head_availability(checkpoint)
    clear_only = (checkpoint["config"]["architecture"] == "histgbm" or
                  checkpoint.get("training", {}).get("loss_profile") == "clear-only")
    result = copy.deepcopy(rows)
    for row in result:
        for arm in row["arms"]:
            for item in arm["trials"]:
                item.pop("prediction", None)
                item.pop("prediction_surplus", None)
    trials = [t for r in result for a in r["arms"] for t in a["trials"]
              if not t.get("censored", False) and t.get("state") is not None]
    config = dict(checkpoint["config"])
    config.pop("pairwise_weight", None)
    arch = config["architecture"]
    model = None
    if arch != "histgbm":
        model = StructuredEvaluator(EvaluatorConfig(**config))
        model.load_state_dict(checkpoint["state_dict"], strict=True)
        model.eval()
    with torch.no_grad():
        for start in range(0, len(trials), batch_size):
            batch_trials = trials[start:start + batch_size]
            batch = normalized_batch([t["state"] for t in batch_trials], checkpoint["normalization"])
            if arch == "histgbm":
                probabilities = predict_gbm(checkpoint["state_dict"], batch)
                for item, probability in zip(batch_trials, probabilities):
                    item["prediction"] = {"clear": float(probability)}
            else:
                outputs = model(batch)
                if any(not torch.isfinite(value).all() for value in outputs.values()):
                    raise ValueError("nonfinite evaluator output")
                for i, item in enumerate(batch_trials):
                    pred = {
                        "clear": float(outputs["clear_logit"][i].sigmoid()),
                        "quantiles": outputs["quantiles"][i].tolist(),
                        "horizons": outputs["horizon_logits"][i].sigmoid().tolist(),
                        "dense": float(outputs["dense"][i]), "final_ante": float(outputs["final_ante"][i]),
                        "win": float(outputs["win_logit"][i].sigmoid()),
                    }
                    item["prediction"] = {key: value for key, value in pred.items() if available[key]}
                    if "surplus" in outputs and not clear_only:
                        item["prediction_surplus"] = float(outputs["surplus"][i])
    return result


def _candidate_rows(rows):
    result = []
    for row in rows:
        anchor = row.get("anchor")
        indexed = [(i, a) for i, a in enumerate(row["arms"]) if not str(a.get("source", "")).startswith("extended_")]
        positions = [i for i, _ in indexed]
        if anchor not in positions:
            continue
        _, world_split_error = split_world_trials(row)
        result.append(dict(row, anchor=positions.index(anchor), arms=[a for _, a in indexed],
                           world_split_error=world_split_error))
    return result


def _calibration(rows):
    outcomes, probabilities, clusters = [], [], []
    for row in rows:
        for arm in row["arms"]:
            for item in arm["trials"]:
                if clear_mask([item])[0]:
                    outcomes.append(item["clear"])
                    probabilities.append(item.get("prediction", {}).get("clear"))
                    clusters.append(row["seed"])
    return brier(outcomes, probabilities, clusters=clusters)


def _quantiles(rows):
    ratios, predictions, clusters = [], [], []
    for row in rows:
        for arm in row["arms"]:
            for item in arm["trials"]:
                ratio = trial_targets(item, row["ante"])["ratio"]
                quantiles = item.get("prediction", {}).get("quantiles")
                if quantiles is not None:
                    ratios.append(math.log1p(ratio) if finite(ratio) else None)
                    predictions.append(quantiles)
                    clusters.append(row["seed"])
    result = quantile_coverage(ratios, predictions, QUANTILE_LEVELS, clusters=clusters)
    result["comparison_space"] = "log1p raw score/target; monotone transform preserves coverage; no ratio clipping"
    return result


def _terminal(rows):
    targets = {key: [] for key in ("dense", "final_ante", "win", "horizon_1", "horizon_2", "horizon_3")}
    predictions = {key: [] for key in targets}
    clusters = {key: [] for key in targets}
    for row in rows:
        for arm in row["arms"]:
            for item in arm["trials"]:
                observed = trial_targets(item, row["ante"])
                predicted = item.get("prediction", {})
                for key in targets:
                    if key.startswith("horizon_"):
                        index = int(key[-1]) - 1
                        value = observed["horizons"][index]
                        pred = predicted.get("horizons", [None] * 3)[index]
                    else:
                        value, pred = observed[key], predicted.get(key)
                    if finite(value) and finite(pred):
                        targets[key].append(value)
                        predictions[key].append(pred)
                        clusters[key].append(row["seed"])
    result = {}
    for key in targets:
        if key in ("dense", "final_ante"):
            errors = [(p - y) ** 2 for p, y in zip(predictions[key], targets[key])]
            absolute = [abs(p - y) for p, y in zip(predictions[key], targets[key])]
            interval = bootstrap_seed_ci(errors, clusters[key])
            result[key] = {"n": len(errors), "mse": interval[1], "mse_ci": interval,
                           "mae": float(np.mean(absolute)) if absolute else None}
        else:
            result[key] = brier(targets[key], predictions[key], clusters=clusters[key])
    return result


def _coverage(rows):
    records = [value for row in rows if (value := reference_coverage(row)) is not None]
    result = {"decisions": len(records), "seeds": len({r["seed"] for r in records}),
              "requested_decisions": sum(any(str(a.get("source", "")).startswith("extended_") for a in row["arms"]) for row in rows),
              "reference": "extended finite-sample optimistic proxy, not a legal-action oracle",
              "independent_reference_repetitions": 0, "records": records}
    for key in ("top1", "top3", "regret"):
        interval = bootstrap_seed_ci([r[key] for r in records], [r["seed"] for r in records])
        result[key], result[f"{key}_ci"] = interval[1], interval
    return result


def _stratum(rows):
    return {"paired": paired_improvement(rows, "model_clear"), "calibration": _calibration(rows), "quantiles": _quantiles(rows)}


def report_predictions(rows, split):
    if split not in ("test", "validation"):
        raise ValueError("report requires a heldout split")
    identities = [(row["seed"], row["decision_id"]) for row in rows]
    if len(identities) != len(set(identities)):
        raise ValueError("duplicate holdout decision identity")
    if any(row["split"] != split or seed_split(row["seed"]) != split for row in rows):
        raise ValueError("holdout split mismatch")
    rows = copy.deepcopy(rows)
    for row in rows:
        for arm in row["arms"]:
            arm.pop("model_clear", None)
            arm.pop("model_surplus", None)
            for item in arm["trials"]:
                probability = item.get("prediction", {}).get("clear")
                item["model_clear"] = probability if finite(probability) and 0 <= probability <= 1 else None
                surplus = item.get("prediction_surplus")
                item["model_surplus"] = surplus if finite(surplus) else None
    candidates = _candidate_rows(rows)
    paired = paired_improvement(candidates, "model_clear")
    paired["total_decisions"] = len(rows)
    paired["excluded_decisions"] = len(rows) - paired["decisions"]
    paired_surplus = paired_improvement(candidates, "model_surplus")
    gate = gate_verdict(paired, split=split)
    trials = [t for r in rows for a in r["arms"] for t in a["trials"]]
    candidate_trials = [t for r in candidates for a in r["arms"] for t in a["trials"]]
    records = {(r["seed"], r["decision_id"]): r for r in paired["records"]}
    gaps = {"tie": [], "(0,0.1]": [], "(0.1,0.25]": [], "(0.25,0.5]": [], "(0.5,1]": []}
    for row in candidates:
        record = records.get((row["seed"], row["decision_id"]))
        if record is None:
            continue
        gap = record["gap"]
        bucket = "tie" if gap <= 1e-12 else "(0,0.1]" if gap <= 0.1 else "(0.1,0.25]" if gap <= 0.25 else "(0.25,0.5]" if gap <= 0.5 else "(0.5,1]"
        gaps[bucket].append(row)
    score_baseline = {"decisions": 0, "advantage": None, "ci": (None, None, None),
                      "reason": "row contract has no observable immediate-score baseline value; continuation score is an outcome and is not used as a baseline feature"}
    order_rows = []
    for row in candidates:
        if any(a.get("source") == "scored_play" for a in row["arms"]):
            arms = [dict(a, scored_order=1.0 if a.get("source") == "scored_play" and
                         i == next(j for j, b in enumerate(row["arms"]) if b.get("source") == "scored_play") else 0.0)
                    for i, a in enumerate(row["arms"])]
            for arm in arms:
                arm["trials"] = [dict(t, scored_order=arm["scored_order"]) for t in arm["trials"]]
            order_rows.append(dict(row, arms=arms))
    report = {
        **gate, "split": split, "paired": paired, "paired_surplus": paired_surplus, "calibration": _calibration(candidates),
        "ranking_protocol": {"name": SPLIT_PROTOCOL, "rule": SELECTION_RULE,
                             "minimum_trials_per_arm": 2, "selection": "mean P(clear) on even indices only",
                             "evaluation": "raw Bernoulli mean on odd indices only",
                             "seed_check": "unique seeds per arm; shared cross-arm seeds must have the same index; halves disjoint",
                             "calibration": "all usable trials, not split",
                             "arm_average_fallback": False},
        "quantiles": _quantiles(candidates), "terminal": _terminal(candidates), "coverage": _coverage(rows),
        "score_baseline": score_baseline,
        "scored_source_order_proxy": {"comparison": paired_improvement(order_rows, "scored_order"),
                                      "limitation": "first non-anchor scored_play source only; not exact immediate-score baseline because anchor deduplication removes its original rank"},
        "by_ante": {str(ante): _stratum([r for r in candidates if r["ante"] == ante]) for ante in sorted({r["ante"] for r in candidates})},
        "by_gap": {key: _stratum(value) for key, value in gaps.items()},
        "evidence": {"holdout_decisions": len(rows), "holdout_seeds": len({r["seed"] for r in rows}),
                     "trials": len(trials), "candidate_trials": len(candidate_trials),
                     "censored_trials": sum(bool(t.get("censored", False)) for t in trials),
                     "unknown_clear_trials": sum(type(t.get("clear")) is not bool for t in trials),
                     "usable_clear_trials": int(clear_mask(trials).sum()),
                     "predicted_trials": sum(finite(t.get("model_clear")) for t in trials),
                     "terminal_trials": sum(t.get("terminal") is not None for t in trials)},
        "limitations": ["supported observable domain only; root eligibility requires collector summary",
                        "no fresh-bank claim without provenance audit", "small-K reference maxima are optimistic and noisy",
                        "prediction ties use uniform randomization expectation, not outcome-informed tie-breaking",
                        "calibration uses individual raw Bernoulli trials; ranking uses trial-mean probabilities",
                        "all candidate decisions containing censored/missing arms excluded, not silently reranked",
                        "untrained heads (zero loss weight, clear-only profile, or HistGBM auxiliaries) are omitted; unavailable diagnostics remain null",
                        "Gate 3 verdict is not certification of collector Gate 1 or live-policy improvement"],
    }
    return report


def main(argv=None):
    parser = argparse.ArgumentParser()
    for name in ("model", "dataset", "out"):
        parser.add_argument(f"--{name}", required=True, type=Path)
    parser.add_argument("--split", choices=("test", "validation", "val"), default="test")
    args = parser.parse_args(argv)
    if not args.out.parent.is_dir():
        parser.error("output parent directory must exist")
    if args.out.exists():
        parser.error("refusing to overwrite report")
    split = "validation" if args.split == "val" else args.split
    torch.set_num_threads(1)
    started = time.monotonic()
    header, rows = load_data(args.dataset, split)
    checkpoint = torch.load(args.model, map_location="cpu", weights_only=True)
    validate_checkpoint(checkpoint, rows, split)
    report = report_predictions(predict_rows(checkpoint, rows), split)
    report["model"] = {"path": str(args.model.resolve()), "config": checkpoint["config"], "selection": checkpoint["selection"],
                       "samples": checkpoint["samples"], "fallback": checkpoint.get("fallback"),
                       "training": checkpoint.get("training", {}), "head_availability": head_availability(checkpoint)}
    report["dataset"] = {"path": str(args.dataset.resolve()), "metadata": header}
    report["elapsed_seconds"] = time.monotonic() - started
    with args.out.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2, allow_nan=False)
    print(json.dumps({"report": str(args.out), "verdict": report["verdict"], "reasons": report["reasons"],
                      "decisions": report["paired"]["decisions"], "seeds": report["paired"]["seeds"],
                      "elapsed_seconds": report["elapsed_seconds"]}, allow_nan=False))


if __name__ == "__main__":
    main()
