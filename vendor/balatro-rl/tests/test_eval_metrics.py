import copy
import importlib.util
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import numpy as np
import pytest
import torch


ROOT = Path(__file__).resolve().parents[3]


def tool(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def trial(clear, value=0.0, censored=False, terminal=None):
    from balatro_sim.eval_encoder import schema

    return {
        "seed": "world", "state": {"context": [value] * schema()["context_dim"], "cards": [], "jokers": []},
        "clear": clear, "score": 600, "target": 100, "steps": 2,
        "censored": censored, "terminal": terminal,
    }


def decision(seed=1, values=(False, True), predictions=(0.1, 0.9), decision_id=0, samples=2):
    from balatro_sim.blind_dataset import seed_split

    return {
        "version": 1, "seed": seed, "decision_id": decision_id, "split": seed_split(seed),
        "ante": 1, "blind_idx": 0, "anchor": 0,
        "arms": [{"action": {"type": "play", "cards": [i]}, "source": "anchor" if i == 0 else "scored_play",
                  "pred": p, "trials": [dict(trial(v, float(v)), pred=p, sample_index=k,
                                              seed=f"world:{seed}:{decision_id}:{k}") for k in range(samples)]}
                 for i, (v, p) in enumerate(zip(values, predictions))],
    }


def test_bootstrap_resamples_whole_seed_clusters():
    from balatro_sim.eval_metrics import bootstrap_seed_ci

    values = [0.0] * 100 + [1.0]
    lo, mean, hi = bootstrap_seed_ci(values, [1] * 100 + [2], n=4000)
    assert (lo, mean, hi) == pytest.approx((0, 1 / 101, 1))
    assert bootstrap_seed_ci(values, [1] * 100 + [2], n=4000) == (lo, mean, hi)
    assert bootstrap_seed_ci([], []) == (None, None, None)
    assert bootstrap_seed_ci([1], [1]) == (None, 1.0, None)
    with pytest.raises(ValueError):
        bootstrap_seed_ci([1], [])


def test_paired_improvement_is_per_decision_and_keeps_nulls():
    from balatro_sim.eval_metrics import paired_improvement

    rows = [decision(1), decision(2, (True, False)), decision(3, (True, True))]
    result = paired_improvement(rows, "pred")
    assert result["advantage"] == pytest.approx(0)
    assert result["decisions"] == 3
    assert result["informative_decisions"] == 2
    assert result["null_decisions"] == 1
    assert result["ci"][0] <= 0 <= result["ci"][2]


def test_trial_predictions_are_averaged_not_logits_or_first_trial():
    from balatro_sim.eval_metrics import paired_improvement

    row = decision(samples=4)
    for arm in row["arms"]:
        del arm["pred"]
    for item in row["arms"][0]["trials"]:
        item["pred"] = 0.8
    row["arms"][1]["trials"][0]["pred"] = 0.99
    row["arms"][1]["trials"][2]["pred"] = 0.01
    assert paired_improvement([row], "pred")["advantage"] == 0


def test_tie_aware_topsets_pairwise_and_regret():
    from balatro_sim.eval_metrics import top1_top3

    result = top1_top3([1, 1, 0, 0], [1, 1, 1, 1])
    assert result["top1"] == pytest.approx(0.5)
    assert result["top3"] == 1
    assert result["regret"] == pytest.approx(0.5)
    assert result["normalized_regret"] == pytest.approx(0.5)
    assert result["pairwise"] == pytest.approx(0.5)
    tied = top1_top3([1, 1], [0, 1])
    assert tied["top1"] == 1
    assert tied["pairwise"] is None
    assert tied["normalized_regret"] is None


def test_prediction_ties_never_use_label_for_choice():
    from balatro_sim.eval_metrics import paired_improvement

    result = paired_improvement([decision(predictions=(0.5, 0.5))], "pred")
    assert result["advantage"] == pytest.approx(0.5)
    assert result["prediction_ties"] == 1


def test_censored_and_unknown_targets_are_not_failures():
    from balatro_sim.eval_metrics import clear_mask, trial_targets, paired_improvement

    trials = [trial(True), trial(None), trial(False, censored=True), trial(0.5)]
    assert clear_mask(trials).tolist() == [True, False, False, False]
    assert np.isnan(trial_targets(trials[2])["ratio"])
    assert trial_targets(trials[0])["ratio"] == 6
    row = decision()
    row["arms"][1]["trials"].append(trials[2])
    result = paired_improvement([row], "pred")
    assert result["decisions"] == 0
    assert result["excluded_decisions"] == 1


def test_terminal_masking_and_beyond_ante_eight():
    from balatro_sim.eval_metrics import trial_targets

    item = trial(True, terminal={"won": False, "final_ante": 3, "dense": 3,
                                "horizons": [True, None, None], "censored": True})
    targets = trial_targets(item, ante=7)
    assert np.isnan(targets["win"])
    assert np.isnan(targets["dense"])
    assert targets["horizons"][0] == 1
    assert np.isnan(targets["horizons"][1:]).all()
    assert np.isnan(trial_targets(trial(True))["horizons"]).all()


def test_brier_uses_raw_bernoulli_and_ten_reliability_bins():
    from balatro_sim.eval_metrics import brier

    result = brier([False, True, None], [0.5, 0.5, 0.9])
    assert result["brier"] == 0.25
    assert result["n"] == 2
    assert len(result["reliability"]) == 10
    assert result["reliability"][5]["count"] == 2
    assert result["reliability"][5]["observed"] == 0.5
    assert brier([True], [1.0])["reliability"][9]["count"] == 1
    assert brier([], [])["brier"] is None


def test_quantile_coverage_is_per_raw_ratio_not_clipped():
    from balatro_sim.eval_metrics import quantile_coverage

    result = quantile_coverage([1, 10, None], [[1, 5], [5, 10], [1, 2]], [0.5, 0.9])
    assert result["coverage"] == [0.5, 1.0]
    assert result["counts"] == [2, 2]


def test_all_ties_small_samples_and_empty_holdout_gate():
    from balatro_sim.eval_metrics import gate_verdict, paired_improvement

    result = paired_improvement([decision(i, (True, True)) for i in range(300)], "pred")
    assert gate_verdict(result)["verdict"] == "INCONCLUSIVE"
    assert gate_verdict(paired_improvement([], "pred"))["verdict"] == "FAILED"
    positive = paired_improvement([decision(i) for i in range(200)], "pred")
    assert gate_verdict(positive)["verdict"] == "PASSED"
    negative = paired_improvement([decision(i, (True, False)) for i in range(200)], "pred")
    assert gate_verdict(negative)["verdict"] == "FAILED"
    repeated = paired_improvement([decision(1, decision_id=i) for i in range(200)], "pred")
    assert gate_verdict(repeated)["verdict"] == "INCONCLUSIVE"


def test_train_normalization_excludes_holdouts_and_preserves_slots():
    fit = tool("fit_evaluator")
    from balatro_sim.eval_encoder import schema

    states = [trial(True, 1)["state"], trial(False, 3)["state"]]
    states[0]["jokers"] = [[0.0] * schema()["joker_dim"]]
    states[1]["jokers"] = [[1.0] + [2.0] * (schema()["joker_dim"] - 1)]
    norm = fit.fit_normalization(states, "pooled")
    assert norm["context"]["mean"][0] == 2
    heldout = trial(True, 999)["state"]
    frozen = copy.deepcopy(norm)
    fit.normalized_batch([heldout], norm)
    assert norm == frozen
    batch = fit.normalized_batch(states, norm)
    assert batch["jokers"][:, 0, 0].tolist() == [0, 1]
    assert not batch["cards_mask"].any()


def test_grouped_loss_weights_decisions_not_trial_count_and_masks_nan():
    fit = tool("fit_evaluator")
    outputs = {
        "clear_logit": torch.tensor([2.0, 2.0, 2.0, -2.0], requires_grad=True),
        "quantiles": torch.ones(4, 5, requires_grad=True),
        "horizon_logits": torch.zeros(4, 3, requires_grad=True),
        "dense": torch.zeros(4, requires_grad=True), "final_ante": torch.zeros(4, requires_grad=True),
        "win_logit": torch.zeros(4, requires_grad=True),
    }
    targets = {"clear": torch.tensor([1.0, 1.0, 1.0, 1.0]), "dense": torch.full((4,), float("nan"))}
    loss = fit.grouped_loss(outputs, targets, [0, 0, 0, 1], weights={"ratio": 0, "horizons": 0, "dense": 0, "final_ante": 0, "win": 0})
    expected = (torch.nn.functional.softplus(torch.tensor(-2.0)) + torch.nn.functional.softplus(torch.tensor(2.0))) / 2
    assert loss.item() == pytest.approx(expected.item())
    loss.backward()
    assert torch.isfinite(outputs["clear_logit"].grad).all()


def seeds_for(split, n=2):
    from balatro_sim.blind_dataset import seed_split

    return [s for s in range(70000, 71000) if seed_split(s) == split][:n]


def write_dataset(path, rows, metadata=None):
    from balatro_sim.blind_dataset import DatasetWriter, SPLIT_VERSION
    from balatro_sim.eval_encoder import schema

    header = {"type": "metadata", "version": 1, "schema": schema(), "split_version": SPLIT_VERSION,
              "config": {"samples": 2}}
    header.update(metadata or {})
    writer = DatasetWriter(path, header)
    for seed in sorted({r["seed"] for r in rows}):
        writer.write_seed(seed, [r for r in rows if r["seed"] == seed], {})


def test_split_guard_rejects_overlap_duplicates_and_schema_mismatch(tmp_path):
    fit = tool("fit_evaluator")
    row = decision(seeds_for("train")[0])
    with pytest.raises(ValueError, match="overlap"):
        fit.guard_splits([row], [row], [])
    path = tmp_path / "bad.jsonl"
    write_dataset(path, [row])
    header, rows = fit.load_data(path, "train")
    assert rows == [row]
    assert fit.load_data(path, "test")[1] == []
    content = path.read_text()
    content = content.replace('"context_dim":', '"incorrect_context_dim":', 1)
    path.write_text(content)
    with pytest.raises(ValueError, match="schema"):
        fit.load_data(path, "train")


def test_load_data_compacts_reference_states_without_changing_primary(tmp_path):
    fit = tool("fit_evaluator")
    row = decision(seeds_for("train")[0])
    row["coverage_arms"] = copy.deepcopy(row["arms"])
    row["independent_arms"] = copy.deepcopy(row["arms"])
    path = tmp_path / "coverage.jsonl"
    write_dataset(path, [row])
    _, loaded = fit.load_data(path, "train")
    assert loaded[0]["arms"] == row["arms"]
    for pool in ("coverage_arms", "independent_arms"):
        for actual, original in zip(loaded[0][pool], row[pool]):
            assert actual["action"] == original["action"]
            for compact, full in zip(actual["trials"], original["trials"]):
                assert "state" not in compact
                assert compact == {key: value for key, value in full.items() if key != "state"}


def test_validation_reports_missing_score_baseline_and_reference_honestly():
    validate = tool("validate_evaluator")
    rows = [decision(s) for s in seeds_for("test")]
    for row in rows:
        for arm in row["arms"]:
            for item in arm["trials"]:
                item["prediction"] = {"clear": arm["pred"], "quantiles": [0.1, 0.2, 0.3, 0.4, 0.5]}
    report = validate.report_predictions(rows, "test")
    assert report["verdict"] == "INCONCLUSIVE"
    assert report["paired"]["advantage"] == 1
    assert report["ranking_protocol"]["name"] == "split_world_parity_v1"
    assert report["paired"]["evaluation_protocol"] == "split_world_parity_v1"
    assert report["scored_source_order_proxy"]["comparison"]["decisions"] == 2
    assert report["calibration"]["n"] == 8
    assert report["score_baseline"]["decisions"] == 0
    assert report["score_baseline"]["advantage"] is None
    assert report["coverage"]["decisions"] == 0
    assert report["coverage"]["top1"] is None
    assert report["by_ante"]["1"]["paired"]["decisions"] == 2
    assert report["quantiles"]["counts"] == [8] * 5
    assert report["terminal"]["dense"]["n"] == 0
    json.dumps(report, allow_nan=False)


@pytest.mark.parametrize("arch,loss_profile", [("mlp", "multitask"), ("pooled", "multitask"),
                                                ("attention", "multitask"), ("histgbm", "multitask"),
                                                ("attention", "clear-only")])
def test_fit_validate_cli_roundtrip_and_test_never_selects_checkpoint(tmp_path, arch, loss_profile):
    train = tmp_path / "train.jsonl"
    val = tmp_path / "val.jsonl"
    test = tmp_path / "test.jsonl"
    for path, split in ((train, "train"), (val, "validation"), (test, "test")):
        write_dataset(path, [decision(s) for s in seeds_for(split)])
    out = tmp_path / "model.pt"
    command = [sys.executable, str(ROOT / "tools" / "fit_evaluator.py"), "--train", str(train),
               "--val", str(val), "--test", str(test), "--arch", arch, "--epochs", "1", "--hidden", "8", "--out", str(out)]
    if loss_profile != "multitask":
        command.extend(["--loss-profile", loss_profile])
    result = subprocess.run(command, capture_output=True, text=True, cwd=ROOT, timeout=90)
    assert result.returncode == 0, result.stderr
    checkpoint = torch.load(out, weights_only=True)
    effective = "clear-only" if arch == "histgbm" and checkpoint["fallback"] is None else loss_profile
    assert checkpoint["training"]["loss_profile"] == effective
    assert checkpoint["config"]["loss_weights"]["clear"] == 1.0
    assert all((weight == 0) == (effective == "clear-only") for name, weight in
               checkpoint["config"]["loss_weights"].items() if name != "clear")
    assert set(("state_dict", "config", "schema", "seed_ids", "normalization", "env")) <= checkpoint.keys()
    assert checkpoint["selection"]["metric"] == "validation_bce"
    assert checkpoint["selection"]["test_used"] is False
    assert checkpoint["config"]["pairwise_weight"] == 0
    assert checkpoint["samples"]["train"] == 8
    provenance = checkpoint["provenance"]["train"]
    assert provenance["path"] == str(train.resolve())
    assert provenance["sha256"] == hashlib.sha256(train.read_bytes()).hexdigest()
    assert provenance["sources"] == [{key: provenance[key] for key in ("path", "sha256", "metadata")}]
    report_path = tmp_path / "report.json"
    command = [sys.executable, str(ROOT / "tools" / "validate_evaluator.py"), "--model", str(out), "--dataset", str(test),
               "--split", "test", "--out", str(report_path)]
    result = subprocess.run(command, capture_output=True, text=True, cwd=ROOT, timeout=90)
    assert result.returncode == 0, result.stderr
    report = json.loads(report_path.read_text())
    assert report["verdict"] == "INCONCLUSIVE"
    assert report["paired"]["decisions"] == 2
    assert report["evidence"]["holdout_seeds"] == 2
    assert report["calibration"]["n"] == 8
    assert report["model"]["training"]["loss_profile"] == effective
    assert report["model"]["head_availability"]["quantiles"] == (effective != "clear-only")
    if effective == "clear-only":
        assert report["quantiles"]["coverage"] == [None] * 5
        assert all(value["n"] == 0 for value in report["terminal"].values())
    validate = tool("validate_evaluator")
    with pytest.raises(ValueError, match="train|overlap"):
        validate.validate_checkpoint(checkpoint, [decision(seeds_for("train")[0])], "test")


@pytest.fixture
def training_sources(tmp_path):
    from balatro_sim.blind_dataset import INTERFACE, SAMPLER_VERSION
    from balatro_sim.eval_metrics import SPLIT_PROTOCOL, SELECTION_RULE

    header = {"policy": "heuristic_v10", "policy_params": {"active": {}, "v10": {}},
              "policy_overrides": {}, "world_sampler": SAMPLER_VERSION, "rng_mode": "seed",
              "evaluation_protocol": SPLIT_PROTOCOL, "selection_rule": SELECTION_RULE,
              "interfaces": copy.deepcopy(INTERFACE), "fingerprints": {"collector.py": "original"},
              "config": {"samples": 2, "decision_offset": 0, "decision_stride": 1,
                         "decisions_per_ante": {"1": 2}, "max_steps": 100}}
    train = decision(seeds_for("train")[0])
    later = decision(train["seed"], decision_id=10, values=(True, True))
    val, test = (decision(seeds_for(split)[0]) for split in ("validation", "test"))
    paths = [tmp_path / name for name in ("original.jsonl", "later.jsonl", "val.jsonl", "test.jsonl")]
    enriched_header = copy.deepcopy(header)
    enriched_header["fingerprints"]["collector.py"] = "later-sampling-options"
    enriched_header["config"].update(decision_offset=10, decision_stride=2, decisions_per_ante={"3-8": 3})
    extra_holdouts = [decision(row["seed"], decision_id=99, values=(True, True)) for row in (val, test)]
    for path, rows, metadata in zip(paths, ([train], [later] + extra_holdouts, [val], [test]),
                                    (header, enriched_header, header, header)):
        write_dataset(path, rows, metadata)
    return paths, (header, enriched_header), (train, later, val, test)


def fit_source_args(paths, out):
    train, later, val, test = paths
    return ["--train", str(train), "--train", str(later), "--val", str(val), "--test", str(test),
            "--arch", "attention", "--epochs", "1", "--hidden", "8", "--seed", "0", "--out", str(out)]


def test_repeated_train_adds_only_new_training_decisions_with_ordered_provenance(training_sources, tmp_path, monkeypatch):
    fit = tool("fit_evaluator")
    paths, headers, (train, later, val, test) = training_sources
    expected_sources = [{"path": str(path.resolve()), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                         "metadata": json.loads(path.read_text().splitlines()[0])} for path in paths]
    original_train_model = fit.train_model
    original_read_bytes = Path.read_bytes
    dataset_paths = {path.resolve() for path in paths}
    received = []

    def record_training(train_rows, val_rows, test_rows, **kwargs):
        received.append(copy.deepcopy((train_rows, val_rows, test_rows)))
        return original_train_model(train_rows, val_rows, test_rows, **kwargs)

    def refuse_full_read(path):
        if path.resolve() in dataset_paths:
            raise AssertionError("dataset hashing must stream, not read_bytes")
        return original_read_bytes(path)

    monkeypatch.setattr(fit, "train_model", record_training)
    monkeypatch.setattr(Path, "read_bytes", refuse_full_read)
    baseline_out = tmp_path / "baseline.pt"
    baseline_args = fit_source_args(paths, baseline_out)
    del baseline_args[2:4]
    fit.main(baseline_args)
    baseline = torch.load(baseline_out, weights_only=True)
    out = tmp_path / "enriched.pt"
    fit.main(fit_source_args(paths, out))
    checkpoint = torch.load(out, weights_only=True)
    repeat_out = tmp_path / "repeat.pt"
    fit.main(fit_source_args(paths, repeat_out))
    repeated = torch.load(repeat_out, weights_only=True)
    assert received == [([train], [val], [test]), ([train, later], [val], [test]), ([train, later], [val], [test])]
    assert baseline["samples"] == {"train": 4, "validation": 4}
    assert checkpoint["samples"] == {"train": 8, "validation": 4}
    assert checkpoint["normalization"]["context"]["mean"][0] == 0.75
    identities = [[train["seed"], d, a, k] for d in (0, 10) for a in (0, 1) for k in (0, 1)]
    assert checkpoint["usable_sample_fingerprint"] == hashlib.sha256(json.dumps(identities).encode()).hexdigest()
    assert checkpoint["seed_ids"] == baseline["seed_ids"]
    assert checkpoint["config"] == baseline["config"]
    assert checkpoint["selection"]["test_used"] is False
    assert checkpoint["provenance"]["train"] == {"sources": expected_sources[:2]}
    for name, expected in zip(("validation", "test"), expected_sources[2:]):
        assert checkpoint["provenance"][name] == baseline["provenance"][name] == expected
    assert checkpoint["selection"] == repeated["selection"]
    assert checkpoint["usable_sample_fingerprint"] == repeated["usable_sample_fingerprint"]
    assert all(torch.equal(value, repeated["state_dict"][key]) for key, value in checkpoint["state_dict"].items())


@pytest.mark.parametrize("duplicate", ["identity", "path", "resolved_path"])
def test_repeated_train_rejects_duplicate_sources_and_decisions(training_sources, tmp_path, duplicate):
    fit = tool("fit_evaluator")
    paths, headers, rows = training_sources
    paths = list(paths)
    if duplicate == "identity":
        paths[1] = tmp_path / "duplicate.jsonl"
        write_dataset(paths[1], [rows[0]], headers[1])
        message = "duplicate decision identity"
    else:
        paths[1] = paths[0] if duplicate == "path" else paths[0].parent / ".." / paths[0].parent.name / paths[0].name
        message = "duplicate training source path"
    out = tmp_path / "rejected.pt"
    with pytest.raises(ValueError, match=message):
        fit.main(fit_source_args(paths, out))
    assert not out.exists()


@pytest.mark.parametrize("field,value", [
    ("schema", {}), ("split_version", "other"), ("version", 2),
    ("policy", "other"), ("world_sampler", "other"), ("policy_params", {"v10": {"farm_rate_share": 0.5}}),
    ("policy_overrides", {"farm_rate_share": 0.5}), ("rng_mode", "generic"),
    ("evaluation_protocol", "same_world"), ("selection_rule", "same_world"),
    ("interfaces", {"evaluation": "same_world"}),
])
def test_repeated_train_rejects_incompatible_semantics(training_sources, tmp_path, field, value):
    fit = tool("fit_evaluator")
    paths, headers, rows = training_sources
    paths = list(paths)
    paths[1] = tmp_path / "incompatible.jsonl"
    header = copy.deepcopy(headers[1])
    header[field] = value
    write_dataset(paths[1], [rows[1]], header)
    out = tmp_path / "rejected.pt"
    with pytest.raises(ValueError, match=field.replace("_", "[_ ]")):
        fit.main(fit_source_args(paths, out))
    assert not out.exists()


def test_repeated_train_checks_optional_semantics_across_all_declaring_sources(training_sources, tmp_path):
    fit = tool("fit_evaluator")
    paths, headers, rows = training_sources
    paths = list(paths)
    paths[0] = tmp_path / "legacy.jsonl"
    write_dataset(paths[0], [rows[0]])
    third = tmp_path / "third.jsonl"
    header = dict(headers[1], policy="other")
    write_dataset(third, [decision(rows[0]["seed"], decision_id=20)], header)
    out = tmp_path / "rejected.pt"
    args = ["--train", str(third)] + fit_source_args(paths, out)
    with pytest.raises(ValueError, match="policy"):
        fit.main(args)
    assert not out.exists()


def test_histgbm_export_matches_sklearn_nonconstant_trees():
    fit = tool("fit_evaluator")
    pytest.importorskip("sklearn")
    from sklearn.ensemble import HistGradientBoostingClassifier
    from threadpoolctl import threadpool_limits

    features = np.arange(160, dtype=float).reshape(80, 2)
    labels = (features[:, 0] > 70).astype(int)
    with threadpool_limits(limits=1):
        reference = HistGradientBoostingClassifier(max_iter=3, min_samples_leaf=2, early_stopping=False, random_state=0)
        reference.fit(features, labels)
        state = fit._export_gbm(reference)
        prediction = fit.predict_gbm(state, features)
        assert np.ptp(prediction) > 0.05
        assert prediction == pytest.approx(reference.predict_proba(features)[:, 1])


def test_numpy_inputs_and_partial_prediction_do_not_fall_back_to_arm_average():
    from balatro_sim.eval_metrics import top1_top3, paired_improvement

    assert top1_top3(np.asarray([0.0, 1.0]), np.asarray([0.1, 0.9]))["top1"] == 1
    row = decision()
    row["arms"][1]["trials"] = [dict(trial(True), pred=0.9), dict(trial(True), pred=None)]
    assert paired_improvement([row], "pred")["decisions"] == 0


def test_report_masks_invalid_probabilities_and_rejects_duplicate_evidence():
    validate = tool("validate_evaluator")
    rows = [decision(s) for s in seeds_for("test", 3)]
    for row in rows:
        for arm in row["arms"]:
            for item in arm["trials"]:
                item["prediction"] = {"clear": arm["pred"]}
    rows[0]["arms"][0]["trials"][0]["prediction"] = {}
    rows[1]["arms"][1]["trials"][0]["prediction"] = {"clear": 2.0}
    report = validate.report_predictions(rows, "test")
    assert report["paired"]["decisions"] == 1
    assert report["calibration"]["excluded"] == 2
    assert report["evidence"]["predicted_trials"] == 10
    assert report["verdict"] == "INCONCLUSIVE"
    with pytest.raises(ValueError, match="duplicate"):
        validate.report_predictions([rows[2], rows[2]], "test")
    with pytest.raises(ValueError, match="split"):
        validate.report_predictions([decision(seeds_for("train")[0])], "test")


def test_censored_terminal_unreached_horizons_are_unknown():
    from balatro_sim.eval_metrics import trial_targets

    partial = trial(True, terminal={"won": False, "final_ante": 2, "dense": 2,
                                   "horizons": [True, None, False], "censored": True})
    horizons = trial_targets(partial)["horizons"]
    assert horizons[0] == 1
    assert np.isnan(horizons[1:]).all()
    assert np.isnan(trial_targets(dict(trial(True), score=None))["ratio"])


def test_reference_pool_is_separate_and_boundary_ties_are_fractional():
    validate = tool("validate_evaluator")
    row = decision(seeds_for("test")[0], (False, False, True, True), (0.1, 0.2, 1.0, 1.0))
    for arm in row["arms"][2:]:
        arm["source"] = "extended_single"
    for arm in row["arms"]:
        arm["trials"][0]["prediction"] = {"clear": arm["pred"]}
    report = validate.report_predictions([row], "test")
    assert report["paired"]["advantage"] == 0
    assert report["paired"]["null_decisions"] == 1
    assert report["coverage"]["top1"] == 0
    assert report["coverage"]["top3"] == pytest.approx(1 / 3)
    assert report["coverage"]["regret"] == 1
    assert report["calibration"]["n"] == 2


def test_test_labels_do_not_affect_fit_and_controls_use_identical_samples(monkeypatch):
    import builtins

    fit = tool("fit_evaluator")
    torch.set_num_threads(1)
    train, val, test = ([decision(s) for s in seeds_for(split)] for split in ("train", "validation", "test"))
    train[0]["arms"][0]["trials"].append(trial(None, 999, censored=True))
    before = copy.deepcopy((train, val, test))
    checkpoint = fit.train_model(train, val, test, arch="mlp", epochs=1, hidden=8)
    changed = copy.deepcopy(test)
    for row in changed:
        for arm in row["arms"]:
            arm["trials"][0]["clear"] = not arm["trials"][0]["clear"]
            arm["trials"][0]["state"]["context"] = [999] * len(arm["trials"][0]["state"]["context"])
    second = fit.train_model(train, val, changed, arch="mlp", epochs=1, hidden=8)
    assert checkpoint["normalization"] == second["normalization"]
    assert checkpoint["selection"] == second["selection"]
    assert all(torch.equal(value, second["state_dict"][key]) for key, value in checkpoint["state_dict"].items())
    real_import = builtins.__import__

    def missing_sklearn(name, *args, **kwargs):
        if name.startswith("sklearn"):
            raise ImportError("optional dependency unavailable")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", missing_sklearn)
    fallback = fit.train_model(train, val, test, arch="histgbm", epochs=1, hidden=8)
    assert fallback["config"]["architecture"] == "mlp"
    assert "unavailable" in fallback["fallback"]
    assert fallback["samples"] == checkpoint["samples"]
    assert fallback["usable_sample_fingerprint"] == checkpoint["usable_sample_fingerprint"]
    assert before == (train, val, test)


def test_split_world_equal_arm_outcome_predictor_has_no_selection_gain():
    from itertools import product
    from balatro_sim.eval_metrics import paired_improvement, gate_verdict

    rows, biased = [], []
    for seed, outcomes in enumerate(list(product((False, True), repeat=4)) * 20):
        row = decision(seed)
        for a, arm in enumerate(row["arms"]):
            for k, item in enumerate(arm["trials"]):
                item["clear"] = outcomes[2 * a + k]
                item["pred"] = float(item["clear"])
        means = [np.mean([t["clear"] for t in arm["trials"]]) for arm in row["arms"]]
        biased.append(max(means) - means[0])
        rows.append(row)
    assert np.mean(biased) > 0.15
    result = paired_improvement(rows, "pred")
    assert result["advantage"] == pytest.approx(0)
    assert result["evaluation_protocol"] == "split_world_parity_v1"
    assert gate_verdict(result)["verdict"] == "INCONCLUSIVE"


def test_split_world_selection_ignores_evaluation_predictions_and_selection_labels():
    from balatro_sim.eval_metrics import decision_values, paired_improvement

    row = decision(samples=4)
    for arm in row["arms"]:
        for item in arm["trials"]:
            if item["sample_index"] % 2:
                item["pred"] = None
            else:
                item["clear"] = None
    assert decision_values(row, "pred") == ([0.0, 1.0], [0.1, 0.9])
    changed = copy.deepcopy(row)
    for arm in changed["arms"]:
        for item in arm["trials"]:
            if item["sample_index"] % 2:
                item["pred"] = 999
                item["clear"] = not item["clear"]
            else:
                item["clear"] = True
        arm["trials"].reverse()
    assert decision_values(changed, "pred") == ([1.0, 0.0], [0.1, 0.9])
    record = paired_improvement([row], "pred")["records"][0]
    assert record["selection_trials_per_arm"] == 2
    assert record["evaluation_trials_per_arm"] == 2


@pytest.mark.parametrize("corruption", ["k1", "duplicate_index", "duplicate_seed", "cross_arm_overlap", "missing_index", "missing_seed", "arm_average"])
def test_split_world_refuses_unverifiable_or_single_world_decisions(corruption):
    from balatro_sim.eval_metrics import paired_improvement, gate_verdict

    row = decision()
    if corruption == "k1":
        for arm in row["arms"]:
            arm["trials"] = arm["trials"][:1]
    elif corruption == "duplicate_index":
        row["arms"][0]["trials"][1]["sample_index"] = 0
    elif corruption == "duplicate_seed":
        row["arms"][0]["trials"][1]["seed"] = row["arms"][0]["trials"][0]["seed"]
    elif corruption == "cross_arm_overlap":
        row["arms"][1]["trials"][1]["seed"] = row["arms"][0]["trials"][0]["seed"]
    elif corruption == "missing_index":
        del row["arms"][0]["trials"][1]["sample_index"]
    elif corruption == "missing_seed":
        del row["arms"][0]["trials"][1]["seed"]
    else:
        for arm in row["arms"]:
            for item in arm["trials"]:
                del item["pred"]
    result = paired_improvement([row], "pred")
    assert result["decisions"] == 0
    assert result["excluded_decisions"] == 1
    assert gate_verdict(result)["verdict"] == "INCONCLUSIVE"


def test_split_world_counts_one_arm_and_full_calibration(capsys):
    from balatro_sim.eval_metrics import split_world_trials, decision_values

    validate = tool("validate_evaluator")
    row = decision(seeds_for("test")[0])
    for arm in row["arms"]:
        for item in arm["trials"]:
            item["prediction"] = {"clear": item["pred"]}
    row["arms"][1]["trials"][1]["pred"] = 0.0
    worlds, reason = split_world_trials(row)
    assert reason is None
    selection, evaluation = worlds[1]
    actual = (len(row["arms"][1]["trials"]), len(selection), len(evaluation))
    with capsys.disabled():
        print(f"one arm (all, selection, evaluation): actual={actual}, expected=(2, 1, 1)")
    assert actual == (2, 1, 1)
    assert decision_values(row, "pred")[1][1] == 0.9
    assert validate._calibration([dict(row, arms=[row["arms"][1]])])["n"] == 2
    assert validate._calibration([row])["n"] == 4


def test_split_world_checks_extended_arm_seed_overlap_before_candidate_filter():
    validate = tool("validate_evaluator")
    row = decision(seeds_for("test")[0], (False, True, True), (0.1, 0.9, 0.8))
    row["arms"][2]["source"] = "extended_single"
    row["arms"][2]["trials"][1]["seed"] = row["arms"][0]["trials"][0]["seed"]
    for arm in row["arms"]:
        for item in arm["trials"]:
            item["prediction"] = {"clear": item["pred"]}
    report = validate.report_predictions([row], "test")
    assert report["paired"]["decisions"] == 0
    assert report["verdict"] == "INCONCLUSIVE"


def test_split_world_inference_does_not_require_selection_outcomes():
    validate = tool("validate_evaluator")
    fit = tool("fit_evaluator")
    from balatro_sim.evaluator import EvaluatorConfig, StructuredEvaluator
    from dataclasses import asdict

    row = decision(seeds_for("test")[0])
    config = EvaluatorConfig(architecture="mlp", d_model=8)
    model = StructuredEvaluator(config)
    states = [t["state"] for a in row["arms"] for t in a["trials"]]
    checkpoint = {"config": asdict(config), "state_dict": model.state_dict(),
                  "normalization": fit.fit_normalization(states, "mlp")}
    original = validate.predict_rows(checkpoint, [row])
    for arm in row["arms"]:
        arm["trials"][0]["clear"] = None
        arm["trials"][0]["prediction"] = {"clear": 999}
    predicted = validate.predict_rows(checkpoint, [row])
    for arm, expected in zip(predicted[0]["arms"], original[0]["arms"]):
        assert arm["trials"][0]["prediction"] == expected["trials"][0]["prediction"]
    assert validate.report_predictions(predicted, "test")["paired"]["decisions"] == 1


def test_clear_only_ignores_auxiliary_targets_in_gradients_and_training(monkeypatch):
    fit = tool("fit_evaluator")
    torch.set_num_threads(1)
    rows = [[decision(s) for s in seeds_for(split)] for split in ("train", "validation", "test")]
    changed = copy.deepcopy(rows)
    for bank in changed[:2]:
        for row in bank:
            for arm in row["arms"]:
                for item in arm["trials"]:
                    item["score"] = 100000
                    item["terminal"] = {"won": True, "final_ante": 8, "dense": 16,
                                        "horizons": [True, False, True]}
    captured = []
    original_step = torch.optim.AdamW.step

    def record_step(optimizer, *args, **kwargs):
        captured.append([None if p.grad is None else p.grad.clone() for group in optimizer.param_groups
                         for p in group["params"]])
        return original_step(optimizer, *args, **kwargs)

    monkeypatch.setattr(torch.optim.AdamW, "step", record_step)
    first = fit.train_model(*rows, epochs=2, hidden=8, batch_decisions=1, loss_profile="clear-only")
    first_grads, captured[:] = captured[:], []
    second = fit.train_model(*changed, epochs=2, hidden=8, batch_decisions=1, loss_profile="clear-only")
    assert first["history"] == second["history"]
    assert first["normalization"] == second["normalization"]
    assert first["usable_sample_fingerprint"] == second["usable_sample_fingerprint"]
    assert first["config"]["loss_weights"] == {"clear": 1.0, "ratio": 0.0, "horizons": 0.0,
                                               "dense": 0.0, "final_ante": 0.0, "win": 0.0}
    assert len(first_grads) == len(captured) == 4
    for before, after in zip(first_grads, captured):
        assert all(a is b if a is None or b is None else torch.equal(a, b) for a, b in zip(before, after))
        assert torch.count_nonzero(after[-2][1:]) == 0
        assert torch.count_nonzero(after[-1][1:]) == 0
    assert all(torch.equal(value, second["state_dict"][key]) for key, value in first["state_dict"].items())
    default = fit.train_model(*rows, epochs=1, hidden=8)
    explicit = fit.train_model(*rows, epochs=1, hidden=8, loss_profile="multitask")
    assert default["training"]["loss_profile"] == "multitask"
    assert default["config"] == explicit["config"]
    assert all(torch.equal(value, explicit["state_dict"][key]) for key, value in default["state_dict"].items())


@pytest.mark.parametrize("metadata", ["profile", "weights", "partial_weights"])
def test_validator_suppresses_untrained_heads_from_profile_or_legacy_weights(metadata):
    from dataclasses import asdict
    from balatro_sim.evaluator import EvaluatorConfig, StructuredEvaluator

    fit, validate = tool("fit_evaluator"), tool("validate_evaluator")
    torch.set_num_threads(1)
    row = decision(seeds_for("validation")[0])
    for arm in row["arms"]:
        for item in arm["trials"]:
            item["terminal"] = {"won": True, "final_ante": 8, "dense": 16, "horizons": [True] * 3}
            item["prediction"] = {"dense": 999}
    config = EvaluatorConfig(d_model=8)
    model = StructuredEvaluator(config)
    checkpoint = {"config": asdict(config), "state_dict": model.state_dict(),
                  "normalization": fit.fit_normalization([t["state"] for a in row["arms"] for t in a["trials"]], "attention")}
    if metadata == "profile":
        checkpoint["training"] = {"loss_profile": "clear-only"}
        del checkpoint["config"]["loss_weights"]
    elif metadata == "weights":
        checkpoint["config"]["loss_weights"] = {key: float(key == "clear") for key in config.loss_weights}
    else:
        checkpoint["config"]["loss_weights"] = {"dense": 0.0}
    predicted = validate.predict_rows(checkpoint, [row])
    expected = {"clear"} if metadata != "partial_weights" else {"clear", "quantiles", "horizons", "final_ante", "win"}
    assert all(set(t["prediction"]) == expected for a in predicted[0]["arms"] for t in a["trials"])
    report = validate.report_predictions(predicted, "validation")
    assert report["terminal"]["dense"]["mse"] is None
    assert report["terminal"]["dense"]["n"] == 0
    if metadata != "partial_weights":
        assert report["quantiles"]["coverage"] == [None] * 5
        assert report["terminal"]["final_ante"]["mse"] is None
        assert report["terminal"]["win"]["brier"] is None
        assert all(report["terminal"][f"horizon_{i}"]["brier"] is None for i in (1, 2, 3))
    assert row["arms"][0]["trials"][0]["prediction"] == {"dense": 999}


@pytest.mark.parametrize("profile,pairwise,message", [("invalid", 0.0, "loss profile"),
                                                       ("clear-only", 0.1, "clear-only.*pairwise")])
def test_loss_profile_rejects_incompatible_settings_before_loading(profile, pairwise, message, tmp_path, monkeypatch):
    fit = tool("fit_evaluator")
    with pytest.raises(ValueError, match=message):
        fit.train_model([], [], [], loss_profile=profile, pairwise_weight=pairwise)

    def refuse_load(*args):
        raise AssertionError("invalid loss settings must fail before dataset loading")

    monkeypatch.setattr(fit, "load_training", refuse_load)
    args = ["--train", "unused", "--val", "unused", "--test", "unused", "--out", str(tmp_path / "bad.pt"),
            "--loss-profile", profile, "--pairwise-weight", str(pairwise)]
    with pytest.raises(SystemExit) as error:
        fit.main(args)
    assert error.value.code == 2
    assert not (tmp_path / "bad.pt").exists()


def test_split_world_gate_refuses_legacy_protocol():
    from balatro_sim.eval_metrics import paired_improvement, gate_verdict

    result = paired_improvement([decision(i) for i in range(200)], "pred")
    result["evaluation_protocol"] = "same_world_biased"
    assert gate_verdict(result)["verdict"] == "INCONCLUSIVE"
