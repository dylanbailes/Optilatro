from __future__ import annotations

import math
from collections import defaultdict
from itertools import combinations

import numpy as np


TIE_ATOL = 1e-12
SPLIT_PROTOCOL = "split_world_parity_v1"
SELECTION_RULE = "even sample_index = selection; odd sample_index = evaluation; disjoint halves, no same-world fallback"


def finite(value):
    return isinstance(value, (int, float, np.number)) and math.isfinite(float(value))


def clear_mask(trials):
    return np.asarray([type(t.get("clear")) is bool and not t.get("censored", False) for t in trials], dtype=bool)


def trial_targets(trial, ante=None):
    result = {name: float("nan") for name in ("clear", "surplus", "ratio", "dense", "final_ante", "win")}
    result["horizons"] = [float("nan")] * 3
    if clear_mask([trial])[0]:
        result["clear"] = float(trial["clear"])
        if finite(trial.get("surplus")):
            result["surplus"] = float(trial["surplus"])
        score, target = trial.get("score"), trial.get("target")
        if finite(score) and finite(target) and score >= 0 and target > 0:
            ratio = score / target
            if finite(ratio):
                result["ratio"] = ratio
    terminal = trial.get("terminal")
    if isinstance(terminal, dict):
        if not terminal.get("censored", False) and not trial.get("censored", False):
            for name in ("dense", "final_ante"):
                if finite(terminal.get(name)):
                    result[name] = float(terminal[name])
            if type(terminal.get("won")) is bool:
                result["win"] = float(terminal["won"])
        for index, value in enumerate(terminal.get("horizons", [])[:3]):
            resolved = value is True or not (terminal.get("censored", False) or trial.get("censored", False))
            if type(value) is bool and resolved and (ante is None or ante + index + 1 <= 8):
                result["horizons"][index] = float(value)
    return result


def bootstrap_seed_ci(values, clusters, n=2000, alpha=0.05, seed=0):
    if len(values) != len(clusters):
        raise ValueError("values and clusters must have equal lengths")
    if not isinstance(n, int) or n < 1 or not 0 < alpha < 1:
        raise ValueError("invalid bootstrap parameters")
    grouped = defaultdict(list)
    for value, cluster in zip(values, clusters):
        if finite(value):
            grouped[cluster].append(float(value))
    if not grouped:
        return None, None, None
    totals = np.asarray([sum(v) for v in grouped.values()])
    counts = np.asarray([len(v) for v in grouped.values()])
    mean = float(totals.sum() / counts.sum())
    if len(grouped) < 2:
        return None, mean, None
    rng = np.random.default_rng(seed)
    estimates = []
    for start in range(0, n, 128):
        indices = rng.integers(len(grouped), size=(min(128, n - start), len(grouped)))
        estimates.extend((totals[indices].sum(1) / counts[indices].sum(1)).tolist())
    lo, hi = np.quantile(estimates, [alpha / 2, 1 - alpha / 2])
    return float(lo), mean, float(hi)


def _top_weights(values, k):
    values = np.asarray(values, dtype=float)
    k = min(k, len(values))
    weights = np.zeros(len(values))
    if not k:
        return weights
    boundary = np.sort(values)[-k]
    tied = np.isclose(values, boundary, atol=TIE_ATOL, rtol=0)
    above = (values > boundary) & ~tied
    weights[above] = 1
    weights[tied] = (k - int(above.sum())) / int(tied.sum())
    return weights


def top1_top3(values, predictions):
    if len(values) != len(predictions):
        raise ValueError("values and predictions must have equal lengths")
    result = dict(top1=None, top3=None, pairwise=None, pairs=0, label_ties=0,
                  prediction_ties=0, regret=None, normalized_regret=None, gap=None)
    if len(values) == 0 or not all(finite(v) for v in list(values) + list(predictions)):
        return result
    values, predictions = np.asarray(values, dtype=float), np.asarray(predictions, dtype=float)
    choice = _top_weights(predictions, 1)
    best = np.isclose(values, values.max(), atol=TIE_ATOL, rtol=0)
    result["top1"] = float(choice[best].sum())
    boundary = np.sort(values)[-min(3, len(values))]
    result["top3"] = float(choice[values >= boundary - TIE_ATOL].sum())
    result["regret"] = float(max(0, values.max() - choice @ values))
    result["gap"] = float(values.max() - values.min())
    if result["gap"] > TIE_ATOL:
        result["normalized_regret"] = result["regret"] / result["gap"]
    concordance = []
    for i, j in combinations(range(len(values)), 2):
        if abs(values[i] - values[j]) <= TIE_ATOL:
            result["label_ties"] += 1
            continue
        if abs(predictions[i] - predictions[j]) <= TIE_ATOL:
            concordance.append(0.5)
            result["prediction_ties"] += 1
        else:
            concordance.append(float((values[i] > values[j]) == (predictions[i] > predictions[j])))
    result["pairs"] = len(concordance)
    result["pairwise"] = float(np.mean(concordance)) if concordance else None
    return result


def arm_prediction(arm, pred_key):
    trials = arm.get("trials", [])
    if any(pred_key in t for t in trials):
        if not all(finite(t.get(pred_key)) for t in trials):
            return None
        return float(np.mean([t[pred_key] for t in trials]))
    value = arm.get(pred_key)
    return float(value) if finite(value) else None


def split_world_trials(row):
    arms = row.get("arms", [])
    if not arms:
        return None, "missing_arms"
    count = len(arms[0].get("trials", []))
    if count < 2:
        return None, "fewer_than_two_worlds"
    expected = set(range(count))
    worlds, seed_indices = [], {}
    for arm in arms:
        trials = arm.get("trials", [])
        indices = [t.get("sample_index") for t in trials]
        seeds = [t.get("seed") for t in trials]
        if len(trials) != count or any(type(i) is not int for i in indices):
            return None, "invalid_sample_indices"
        if set(indices) != expected or len(set(indices)) != count:
            return None, "invalid_sample_indices"
        if any(not isinstance(s, str) or not s for s in seeds) or len(set(seeds)) != count:
            return None, "invalid_trial_seeds"
        for index, world_seed in zip(indices, seeds):
            if world_seed in seed_indices and seed_indices[world_seed] != index:
                return None, "cross_index_seed_reuse"
            seed_indices[world_seed] = index
        selection = sorted((t for t in trials if t["sample_index"] % 2 == 0), key=lambda t: t["sample_index"])
        evaluation = sorted((t for t in trials if t["sample_index"] % 2 == 1), key=lambda t: t["sample_index"])
        worlds.append((selection, evaluation))
    selection_seeds = {t["seed"] for selection, _ in worlds for t in selection}
    evaluation_seeds = {t["seed"] for _, evaluation in worlds for t in evaluation}
    if selection_seeds & evaluation_seeds:
        return None, "overlapping_world_halves"
    return worlds, None


def _decision_values(row, pred_key):
    if row.get("world_split_error"):
        return None, row["world_split_error"], None
    arms = row.get("arms", [])
    if len(arms) < 2 or type(row.get("anchor")) is not int or not 0 <= row["anchor"] < len(arms):
        return None, "invalid_candidates_or_anchor", None
    worlds, reason = split_world_trials(row)
    if reason is not None:
        return None, reason, None
    values, predictions = [], []
    for selection, evaluation in worlds:
        if any(t.get("censored", False) for t in selection) or not clear_mask(evaluation).all():
            return None, "censored_or_missing_evaluation_labels", None
        if not all(finite(t.get(pred_key)) for t in selection):
            return None, "missing_selection_predictions", None
        predictions.append(float(np.mean([t[pred_key] for t in selection])))
        values.append(float(np.mean([t["clear"] for t in evaluation])))
    return (values, predictions), None, worlds


def decision_values(row, pred_key):
    return _decision_values(row, pred_key)[0]


def paired_improvement(decisions, pred_key, n=2000, alpha=0.05, seed=0):
    records, exclusions = [], defaultdict(int)
    for row in decisions:
        pair, reason, worlds = _decision_values(row, pred_key)
        if pair is None:
            exclusions[reason] += 1
            continue
        values, predictions = pair
        choice = _top_weights(predictions, 1)
        record = top1_top3(values, predictions)
        record.update(seed=row["seed"], decision_id=row.get("decision_id"), ante=row.get("ante"),
                      advantage=float(choice @ values - values[row["anchor"]]),
                      evaluation=SPLIT_PROTOCOL,
                      selection_trials_per_arm=len(worlds[0][0]), evaluation_trials_per_arm=len(worlds[0][1]),
                      selection_predictions=predictions, evaluation_values=values, choice_weights=choice.tolist(),
                      choice_tied=int((choice > 0).sum()) > 1,
                      anchor_value=values[row["anchor"]], model_value=float(choice @ values),
                      random_value=float(np.mean(values)))
        records.append(record)
    clusters = [r["seed"] for r in records]
    ci = bootstrap_seed_ci([r["advantage"] for r in records], clusters, n, alpha, seed)
    informative = [r for r in records if r["gap"] > TIE_ATOL]
    result = {
        "advantage": ci[1], "ci": ci, "decisions": len(records), "total_decisions": len(decisions),
        "excluded_decisions": len(decisions) - len(records), "seeds": len(set(clusters)),
        "informative_decisions": len(informative), "informative_seeds": len({r["seed"] for r in informative}),
        "null_decisions": len(records) - len(informative), "prediction_ties": sum(r["choice_tied"] for r in records),
        "records": records, "exclusion_rule": "complete verified world splits only; censored selection or unknown/censored evaluation excludes the decision; selection labels and evaluation predictions unused",
        "tie_rule": "uniform prediction argmax ties; all label maxima accepted; no SE gap filtering",
        "evaluation_protocol": SPLIT_PROTOCOL, "selection_rule": SELECTION_RULE,
        "exclusion_counts": dict(exclusions),
    }
    for key in ("top1", "top3", "pairwise", "regret", "normalized_regret", "anchor_value", "model_value", "random_value"):
        interval = bootstrap_seed_ci([r[key] for r in records], clusters, n, alpha, seed)
        result[key] = interval[1]
        result[f"{key}_ci"] = interval
    result["pairs"] = sum(r["pairs"] for r in records)
    result["label_tied_pairs"] = sum(r["label_ties"] for r in records)
    return result


def gate_verdict(paired, min_decisions=200, min_seeds=30, split="test"):
    reasons = []
    verdict = "INCONCLUSIVE"
    lo, _, hi = paired["ci"]
    if paired.get("total_decisions", paired["decisions"]) == 0:
        verdict, reasons = "FAILED", ["zero holdout decisions"]
    elif paired.get("evaluation_protocol") != SPLIT_PROTOCOL:
        reasons.append("ranking requires verified disjoint selection/evaluation worlds")
    elif split != "test":
        reasons.append("validation split is tuning evidence, not an independent test gate")
    elif paired["informative_decisions"] < min_decisions or paired["informative_seeds"] < min_seeds:
        reasons.append("insufficient informative decisions or independent informative test seeds")
    elif lo is None or hi is None:
        reasons.append("seed-cluster confidence interval unavailable")
    elif lo > 0:
        verdict, reasons = "PASSED", ["paired clear advantage lower 95% bound exceeds zero"]
    elif hi < 0:
        verdict, reasons = "FAILED", ["paired clear advantage upper 95% bound is below zero"]
    else:
        reasons.append("paired clear advantage confidence interval includes zero")
    return {"verdict": verdict, "reasons": reasons,
            "thresholds": {"min_informative_decisions": min_decisions, "min_informative_seeds": min_seeds,
                           "advantage_lower_bound": 0.0, "alpha": 0.05}}


def brier(outcomes, probabilities, bins=10, clusters=None):
    if len(outcomes) != len(probabilities) or (clusters is not None and len(clusters) != len(outcomes)):
        raise ValueError("outcomes, probabilities and clusters must align")
    if type(bins) is not int or bins < 1:
        raise ValueError("bins must be positive")
    valid = [i for i, (y, p) in enumerate(zip(outcomes, probabilities))
             if finite(y) and y in (0, 1) and finite(p) and 0 <= p <= 1]
    errors = [(probabilities[i] - float(outcomes[i])) ** 2 for i in valid]
    result = {"n": len(valid), "excluded": len(outcomes) - len(valid),
              "brier": float(np.mean(errors)) if errors else None, "ci": (None, None, None), "reliability": []}
    if clusters is not None:
        result["ci"] = bootstrap_seed_ci(errors, [clusters[i] for i in valid])
    for index in range(bins):
        members = [i for i in valid if min(bins - 1, int(probabilities[i] * bins)) == index]
        labels = [float(outcomes[i]) for i in members]
        result["reliability"].append({
            "lower": index / bins, "upper": (index + 1) / bins, "count": len(members),
            "predicted": float(np.mean([probabilities[i] for i in members])) if members else None,
            "observed": float(np.mean(labels)) if members else None,
            "observed_ci": bootstrap_seed_ci(labels, [clusters[i] for i in members]) if clusters is not None else (None, None, None),
        })
    return result


def quantile_coverage(ratios, predictions, nominal, clusters=None):
    if len(ratios) != len(predictions) or (clusters is not None and len(clusters) != len(ratios)):
        raise ValueError("ratios, predictions and clusters must align")
    if any(not 0 < q < 1 for q in nominal) or any(a >= b for a, b in zip(nominal, nominal[1:])):
        raise ValueError("nominal quantiles must be increasing inside (0, 1)")
    if any(len(row) != len(nominal) for row in predictions):
        raise ValueError("quantile width mismatch")
    result = {"nominal": list(nominal), "coverage": [], "counts": [], "ci": [], "crossings": 0}
    result["crossings"] = sum(any(finite(a) and finite(b) and a > b for a, b in zip(row, row[1:])) for row in predictions)
    for index in range(len(nominal)):
        valid = [i for i, ratio in enumerate(ratios) if finite(ratio) and ratio >= 0 and finite(predictions[i][index])]
        values = [float(ratios[i] <= predictions[i][index]) for i in valid]
        result["counts"].append(len(values))
        result["coverage"].append(float(np.mean(values)) if values else None)
        result["ci"].append(bootstrap_seed_ci(values, [clusters[i] for i in valid]) if clusters is not None else (None, None, None))
    return result


def reference_coverage(row):
    arms = row.get("arms", [])
    reference = [a for a in arms if str(a.get("source", "")).startswith("extended_")]
    if not reference:
        return None
    if any(not a.get("trials") or not clear_mask(a["trials"]).all() for a in arms):
        return None
    values = np.asarray([np.mean([t["clear"] for t in a["trials"]]) for a in arms])
    included = np.asarray([not str(a.get("source", "")).startswith("extended_") for a in arms])
    if not included.any():
        return None
    result = {"seed": row["seed"], "ante": row.get("ante"), "reference_arms": len(arms),
              "candidate_arms": int(included.sum()), "regret": float(values.max() - values[included].max())}
    for k in (1, 3):
        weights = _top_weights(values, k)
        result[f"top{k}"] = float(weights[included].sum() / weights.sum())
    return result
