import copy
import json
import pickle
import time

import pytest

from balatro_sim import agent_v9 as V9
from balatro_sim import agent_v10 as V10
from balatro_sim.game import BalatroGame, State
from balatro_sim.hand_eval import evaluate_hand
from balatro_sim.eval_encoder import encode_state, schema


def game_root(seed=70123):
    game = BalatroGame(seed=seed, rng_mode="seed")
    game.step({"type": "play_blind"})
    return game


def dataset():
    from balatro_sim import blind_dataset
    return blind_dataset


def test_sample_world_real_state_purity_reproducibility_and_reversal():
    ds = dataset()
    game = game_root()
    game.grant_joker("j_castle")
    game.deck[0].bonus_chips = 17
    game.deck[1].enhancement = "Glass"
    game.deck[2].seal = "Purple"
    before = pickle.dumps(game)
    world = ds.sample_world(game, "sample:1")
    assert pickle.dumps(game) == before
    assert pickle.dumps(world) == pickle.dumps(ds.sample_world(game, "sample:1"))
    game.deck.reverse()
    assert pickle.dumps(world) == pickle.dumps(ds.sample_world(game, "sample:1"))
    other = ds.sample_world(game, "sample:2")
    assert [c.id for c in world.deck] != [c.id for c in other.deck]
    world.step({"type": "discard", "cards": [0, 1, 2]})
    other.step({"type": "discard", "cards": [0, 1, 2]})
    assert encode_state(world) != encode_state(other)
    assert world.jokers[0].game is world


def test_sampler_sort_includes_modifications_and_observable_history():
    ds = dataset()
    game = game_root()
    a = copy.deepcopy(game.deck[0])
    a.id += 100000
    a.bonus_chips = 23
    game.deck.append(a)
    b = copy.deepcopy(game.deck[1])
    b.id += 100001
    game.ante_played_ids.add(b.id)
    game.deck.append(b)
    first = ds.sample_world(game, "same")
    game.deck.reverse()
    assert pickle.dumps(first) == pickle.dumps(ds.sample_world(game, "same"))


def test_candidates_are_unique_full_payload_ordered_and_superset(monkeypatch):
    ds = dataset()
    game = game_root()
    anchor = {"type": "play", "cards": [1, 0], "payload": {"keep": True}}
    monkeypatch.setattr(V9, "scored_plays", lambda *a, **k: [(12, (1, 0), "Pair"), (11, (0, 1), "Pair"), (10, (0, 0), "Pair")])
    before = pickle.dumps(game)
    restricted = ds.candidate_actions(game, anchor)
    extended = ds.candidate_actions(game, anchor, extended=True)
    assert pickle.dumps(game) == before
    assert restricted[0] == {"action": anchor, "source": "anchor"}
    keys = [ds.action_key(a["action"]) for a in extended]
    assert len(keys) == len(set(keys))
    assert set(ds.action_key(a["action"]) for a in restricted) <= set(keys)
    assert ds.action_key({"type": "play", "cards": [1, 0]}) in keys
    assert ds.action_key({"type": "play", "cards": [0, 1]}) in keys
    for entry in extended:
        indices = entry["action"]["cards"]
        assert 1 <= len(indices) <= 5
        assert len(indices) == len(set(indices))
        assert all(0 <= i < len(game.hand) for i in indices)
    assert {a["action"]["type"] for a in restricted} == {"play", "discard"}


@pytest.mark.parametrize("boss", ["bl_psychic", "bl_mouth", "bl_eye", "bl_cerulean"])
def test_candidates_recheck_boss_legality(boss):
    ds = dataset()
    game = game_root()
    game.current_blind.boss_key = boss
    game.current_blind.is_boss = True
    if boss in ("bl_mouth", "bl_eye"):
        game.played_hand_types_this_round = {"Pair"}
    if boss == "bl_cerulean":
        game.bell_card = game.hand[-1]
    candidates = ds.candidate_actions(game, {"type": "discard", "cards": [0]}, extended=True)
    for entry in candidates:
        action = entry["action"]
        if action["type"] == "play":
            cards = [game.hand[i] for i in action["cards"]]
            ht, _ = evaluate_hand(cards)
            assert V9._boss_play_filter(game, action["cards"], ht, cards)
            assert boss != "bl_psychic" or len(cards) == 5


@pytest.mark.parametrize("anchor", [{"type": "use_consumable", "consumable_idx": 0, "target_cards": [1, 0]}, {"type": "sell_joker", "joker_idx": 0}])
def test_unsupported_anchors_have_explicit_reason(anchor):
    ds = dataset()
    with pytest.raises(ds.UnsupportedRoot, match="unsupported_anchor"):
        ds.collect_decision(game_root(), anchor, ["sample"])


@pytest.mark.parametrize("where", ["hand", "deck", "joker"])
def test_hidden_roots_rejected(where):
    ds = dataset()
    game = game_root()
    if where == "joker":
        game.grant_joker("j_joker")
        game.jokers_flipped = True
    else:
        getattr(game, where)[0].flipped = True
    with pytest.raises(ds.UnsupportedRoot, match="hidden"):
        ds.collect_decision(game, {"type": "play", "cards": [0]}, ["sample"])


def test_collect_reproducible_independent_parent_post_alignment_and_globals():
    ds = dataset()
    game = game_root()
    anchor = {"type": "discard", "cards": [0, 1]}
    before = pickle.dumps(game)
    globals_before = copy.deepcopy((V9.ACTIVE_PARAMS, V10.V10_PARAMS))
    arms = ds.collect_decision(game, anchor, ["a", "b"], max_steps=2)
    assert arms == ds.collect_decision(game, anchor, ["a", "b"], max_steps=2)
    assert pickle.dumps(game) == before
    assert (V9.ACTIVE_PARAMS, V10.V10_PARAMS) == globals_before
    for arm in arms:
        assert len(arm["trials"]) == 2
        for trial in arm["trials"]:
            post = ds.sample_world(game, trial["seed"])
            post.step(arm["action"])
            assert trial["state"] == encode_state(post)
            assert trial["target"] == 300
            assert trial["steps"] <= 2
            assert trial["terminal"] is None


def test_clear_failure_truncation_hidden_and_root_target(monkeypatch):
    ds = dataset()
    game = game_root()
    game.current_blind.chips_target = 1
    trial = ds.collect_decision(game, {"type": "play", "cards": [0]}, ["a", "b"], max_steps=1)[0]["trials"][0]
    assert trial["clear"] is True and not trial["censored"]
    assert trial["target"] == 1 and trial["steps"] == 1
    assert trial["state"]["context"][schema()["context_names"].index("phase_ROUND_EVAL")] == 1
    game.current_blind.chips_target = 10**9
    game.hands_left = 1
    trial = ds.collect_decision(game, {"type": "play", "cards": [0]}, ["a", "b"], max_steps=1, terminal=True)[0]["trials"][0]
    assert trial["clear"] is False and not trial["censored"]
    assert trial["terminal"]["won"] is False
    game.hands_left = 4
    trial = ds.collect_decision(game, {"type": "play", "cards": [0]}, ["a", "b"], max_steps=1)[0]["trials"][0]
    assert trial["clear"] is None and trial["censored"]
    game.current_blind.boss_key = "bl_fish"
    game.current_blind.is_boss = True
    def forbidden(self, game):
        raise AssertionError("H10 called on hidden observation")
    monkeypatch.setattr(V10.HeuristicV10, "decide", forbidden)
    monkeypatch.setattr(ds, "candidate_actions", lambda *a, **k: [{"action": {"type": "play", "cards": [0]}, "source": "anchor"}])
    trial = ds.collect_decision(game, {"type": "play", "cards": [0]}, ["a", "b"], max_steps=10)[0]["trials"][0]
    assert trial["clear"] is None and trial["censor_reason"] == "hidden_observation"


def test_terminal_horizons_are_root_relative_and_mask_beyond_eight():
    ds = dataset()
    game = game_root()
    game.ante = 7
    game.blind_idx = 2
    game.current_blind.chips_target = 1
    game.current_blind.is_boss = True
    game.current_blind.kind = "Boss"
    trial = ds.collect_decision(game, {"type": "play", "cards": [0]}, ["a", "b"], max_steps=1, terminal=True)[0]["trials"][0]
    assert trial["clear"] is True
    assert trial["terminal"]["censored"] is True
    assert trial["terminal"]["horizons"] == [None, None, None]
    game.ante = 8
    trial = ds.collect_decision(game, {"type": "play", "cards": [0]}, ["a", "b"], max_steps=1, terminal=True)[0]["trials"][0]
    assert trial["terminal"] == {"won": True, "final_ante": 9, "dense": 17, "horizons": [None, None, None], "censored": False}


def test_policy_globals_restored_on_exception_and_each_trial_reset(monkeypatch):
    ds = dataset()
    game = game_root()
    game.current_blind.chips_target = 10**9
    before = copy.deepcopy((V9.ACTIVE_PARAMS, V10.V10_PARAMS))
    identities = (id(V9.ACTIVE_PARAMS), id(V10.V10_PARAMS))
    starts = []
    def decide(self, world):
        starts.append(V9.ACTIVE_PARAMS.get("sentinel"))
        V9.ACTIVE_PARAMS["sentinel"] = 99
        V10.V10_PARAMS["sentinel"] = 99
        raise RuntimeError("test continuation")
    monkeypatch.setattr(V10.HeuristicV10, "decide", decide)
    arms = ds.collect_decision(game, {"type": "discard", "cards": [0]}, ["a", "b"], max_steps=2)
    assert len(starts) == 2 * len(arms)
    assert all(value is None for value in starts)
    assert (V9.ACTIVE_PARAMS, V10.V10_PARAMS) == before
    assert (id(V9.ACTIVE_PARAMS), id(V10.V10_PARAMS)) == identities
    assert all(t["censored"] and t["clear"] is None for a in arms for t in a["trials"])


def test_anchor_once_matches_baseline_including_decide_mutations():
    ds = dataset()
    game = game_root()
    game.grant_joker("j_brainstorm")
    game.grant_joker("j_joker")
    baseline = copy.deepcopy(game)
    with ds.policy_scope():
        policy = V10.HeuristicV10()
        expected = policy.decide(baseline)
        baseline.step(expected)
    class CountingPolicy(V10.HeuristicV10):
        calls = 0
        def decide(self, root):
            self.calls += 1
            return super().decide(root)
    with ds.policy_scope():
        policy = CountingPolicy()
        row = ds.trajectory_step(game, policy, 70123, 0, ["a", "b"], max_steps=1)
    assert policy.calls == 1
    assert row["arms"][0]["action"] == expected
    assert pickle.dumps(game) == pickle.dumps(baseline)
    assert row["seed"] == 70123 and row["anchor"] == 0
    assert row["split"] == ds.seed_split(70123)


def test_independent_sampling_and_coupling_undefined_variance():
    ds = dataset()
    game = game_root()
    arms = ds.collect_decision(game, {"type": "discard", "cards": [0]}, ["a", "b"], max_steps=1, independent=True)
    seeds = [t["seed"] for a in arms for t in a["trials"]]
    assert len(set(seeds)) == len(seeds)
    fake = [{"action": {"type": "play", "cards": [i]}, "trials": [{"clear": True, "censored": False} for _ in range(3)]} for i in range(2)]
    report = ds.coupling_report(fake, fake)
    assert report["pairs"][0]["outcome_correlation"] is None
    assert report["pairs"][0]["variance_ratio"] is None


def test_reference_coverage_tie_aware_and_censored_not_failure():
    ds = dataset()
    def arm(i, values):
        return {"action": {"type": "play", "cards": [i]}, "trials": [{"clear": v, "censored": v is None} for v in values]}
    pool = [arm(0, [False, False]), arm(1, [True, True]), arm(2, [True, True]), arm(3, [None, None])]
    report = ds.coverage_report(pool[:2], pool)
    assert report["top1_coverage"] == 0.5
    assert report["top3_coverage"] == pytest.approx(2 / 3)
    assert report["regret"] == 0
    assert report["excluded_censored_arms"] == 1
    assert report["noisy_reference_pool"] is True


def test_seed_split_stable_and_disjoint():
    ds = dataset()
    sets = {name: {s for s in range(1000) if ds.seed_split(s) == name} for name in ("train", "validation", "test")}
    assert all(sets.values())
    assert len(set.union(*sets.values())) == 1000
    assert not sets["train"] & sets["test"]


def test_jsonl_resume_metadata_complete_markers_partial_recovery(tmp_path):
    ds = dataset()
    path = tmp_path / "data.jsonl"
    metadata = ds.metadata({"samples": 2, "seed_start": 10, "n_seeds": 3})
    writer = ds.DatasetWriter(path, metadata)
    row = validation_row()
    writer.write_seed(10, [row], {"stop_reason": "decision_cap"})
    assert ds.DatasetWriter(path, metadata, resume=True).completed == {10}
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(dict(row, seed=11, split=ds.seed_split(11))) + "\n")
    resumed = ds.DatasetWriter(path, metadata, resume=True)
    assert resumed.completed == {10}
    assert len(path.read_text().splitlines()) == 3
    resumed.write_seed(11, [dict(row, seed=11, split=ds.seed_split(11))], {})
    assert ds.DatasetWriter(path, metadata, resume=True).completed == {10, 11}
    with pytest.raises(ValueError, match="metadata"):
        ds.DatasetWriter(path, ds.metadata({"samples": 3}), resume=True)
    with pytest.raises(ValueError, match="complete"):
        resumed.write_seed(10, [row], {})
    assert json.loads(path.read_text().splitlines()[0])["schema"] == schema()


def test_extended_keeps_restricted_legal_fallback(monkeypatch):
    ds = dataset()
    game = game_root()
    game.current_blind.boss_key = "bl_psychic"
    monkeypatch.setattr(V9, "scored_plays", lambda game, topk, **kwargs: [] if topk == 8 else [(1, (1, 2, 3, 4, 5), "High Card")])
    anchor = {"type": "discard", "cards": [0]}
    restricted = ds.candidate_actions(game, anchor)
    extended = ds.candidate_actions(game, anchor, extended=True)
    assert set(ds.action_key(a["action"]) for a in restricted) <= set(ds.action_key(a["action"]) for a in extended)
    assert all(a in extended for a in restricted)


def test_reader_is_read_only_and_ignores_incomplete_seed(tmp_path):
    ds = dataset()
    path = tmp_path / "read.jsonl"
    writer = ds.DatasetWriter(path, ds.metadata({}))
    row = validation_row()
    writer.write_seed(10, [row], {})
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(dict(row, seed=11, split=ds.seed_split(11))) + "\n")
    before = path.read_bytes()
    assert list(ds.read_dataset(path)) == [row]
    assert path.read_bytes() == before


def test_instrumentation_error_discards_row_but_executes_original_anchor(monkeypatch):
    ds = dataset()
    game = game_root()
    expected = copy.deepcopy(game)
    with ds.policy_scope():
        expected.step(V10.HeuristicV10().decide(expected))
    def broken(*args, **kwargs):
        raise RuntimeError("probe failed")
    monkeypatch.setattr(ds, "coverage_report", broken)
    with ds.policy_scope():
        row = ds.trajectory_step(game, V10.HeuristicV10(), 1, 0, ["a", "b"], max_steps=1, extended=True)
    assert row is None
    assert pickle.dumps(game) == pickle.dumps(expected)


def test_candidate_globals_restored_after_scoring_exception(monkeypatch):
    ds = dataset()
    game = game_root()
    before = copy.deepcopy((V9.ACTIVE_PARAMS, V10.V10_PARAMS))
    def broken(*args, **kwargs):
        V9.ACTIVE_PARAMS["sentinel"] = 1
        V10.V10_PARAMS["sentinel"] = 2
        raise RuntimeError("score failed")
    monkeypatch.setattr(V9, "scored_plays", broken)
    with pytest.raises(RuntimeError):
        ds.candidate_actions(game, {"type": "play", "cards": [0]})
    assert (V9.ACTIVE_PARAMS, V10.V10_PARAMS) == before


def validation_row(samples=2):
    ds = dataset()
    return {"version": 1, "seed": 10, "decision_id": 0, "split": ds.seed_split(10),
            "ante": 1, "blind_idx": 0, "anchor": 0,
            "arms": [{"action": {"type": "play", "cards": [i]}, "source": "anchor" if i == 0 else "scored_play",
                      "trials": [{"sample_index": k, "seed": f"world:{k}"} for k in range(samples)]} for i in range(2)]}


@pytest.mark.parametrize("fault", ["missing_index", "missing_seed", "duplicate_pair", "duplicate_index", "duplicate_seed", "cross_index", "gap", "bool_index", "empty_seed", "empty_trials", "count", "unequal_count", "single_world"])
def test_validate_row_rejects_invalid_worlds(fault):
    ds = dataset()
    row = validation_row()
    trials = row["arms"][0]["trials"]
    if fault == "missing_index":
        del trials[0]["sample_index"]
    elif fault == "missing_seed":
        del trials[0]["seed"]
    elif fault == "duplicate_pair":
        trials[1] = copy.deepcopy(trials[0])
    elif fault == "duplicate_index":
        trials[1]["sample_index"] = 0
    elif fault == "duplicate_seed":
        trials[1]["seed"] = trials[0]["seed"]
    elif fault == "cross_index":
        row["arms"][1]["trials"].reverse()
        for k, trial in enumerate(row["arms"][1]["trials"]):
            trial["sample_index"] = k
    elif fault == "gap":
        trials[1]["sample_index"] = 2
    elif fault == "bool_index":
        trials[0]["sample_index"] = False
    elif fault == "empty_seed":
        trials[0]["seed"] = ""
    elif fault == "empty_trials":
        trials.clear()
    elif fault in ("count", "unequal_count"):
        trials.append({"sample_index": 2, "seed": "world:2"})
    else:
        row = validation_row(1)
    header = None if fault in ("unequal_count", "single_world") else {"config": {"samples": 2}}
    with pytest.raises(ValueError):
        ds.validate_row(row, header)


def test_validate_row_accepts_shared_indices_and_metrics_parity():
    ds = dataset()
    from balatro_sim.eval_metrics import split_world_trials
    row = validation_row(3)
    assert ds.validate_row(row, {"config": {"samples": 3}})
    worlds, reason = split_world_trials(row)
    assert reason is None
    assert [t["sample_index"] for t in worlds[0][0]] == [0, 2]
    assert [t["sample_index"] for t in worlds[0][1]] == [1]


@pytest.mark.parametrize("samples", [0, 1, True, 2.5])
def test_metadata_rejects_invalid_samples(samples):
    with pytest.raises(ValueError, match="samples"):
        dataset().metadata({"samples": samples})


def test_collect_requires_disjoint_world_halves():
    ds = dataset()
    with pytest.raises(ValueError, match="two|2"):
        ds.collect_decision(game_root(), {"type": "play", "cards": [0]}, ["one"], max_steps=1)
    from tools.collect_blind_decisions import collect_seed
    with pytest.raises(ValueError, match="samples"):
        collect_seed(10, samples=1, max_decisions=1, max_steps=1)


def test_writer_rejects_k_mismatch_without_appending(tmp_path):
    ds = dataset()
    path = tmp_path / "k.jsonl"
    writer = ds.DatasetWriter(path, ds.metadata({"samples": 3}))
    before = path.read_bytes()
    with pytest.raises(ValueError, match="samples"):
        writer.write_seed(10, [validation_row(2)], {})
    assert path.read_bytes() == before
    assert not writer.completed


def test_resume_and_reader_reject_committed_k_mismatch(tmp_path):
    ds = dataset()
    path = tmp_path / "k.jsonl"
    header = ds.metadata({"samples": 2})
    ds.DatasetWriter(path, header).write_seed(10, [validation_row()], {})
    header["config"]["samples"] = 3
    lines = path.read_bytes().splitlines(keepends=True)
    path.write_bytes((ds.action_key(header) + "\n").encode() + b"".join(lines[1:]))
    before = path.read_bytes()
    with pytest.raises(ValueError, match="samples"):
        ds.DatasetWriter(path, header, resume=True)
    with pytest.raises(ValueError, match="samples"):
        list(ds.read_dataset(path))
    assert path.read_bytes() == before


@pytest.mark.parametrize("ending", ["header", "marker", "row", "broken"])
def test_unterminated_line_refused_without_truncation(tmp_path, ending):
    ds = dataset()
    path = tmp_path / "newline.jsonl"
    header = ds.metadata({"samples": 2})
    writer = ds.DatasetWriter(path, header)
    if ending != "header":
        writer.write_seed(10, [validation_row()], {})
    if ending in ("header", "marker"):
        path.write_bytes(path.read_bytes()[:-1])
    else:
        with path.open("ab") as stream:
            stream.write(b'{"seed":11}' if ending == "row" else b'{"seed":11')
    before = path.read_bytes()
    with pytest.raises(ValueError, match="unterminated"):
        ds.DatasetWriter(path, header, resume=True)
    with pytest.raises(ValueError, match="unterminated"):
        list(ds.read_dataset(path))
    assert path.read_bytes() == before


def test_cli_split_protocol_and_real_world_indices(tmp_path, capsys):
    ds = dataset()
    from tools.collect_blind_decisions import main
    from balatro_sim.eval_metrics import SPLIT_PROTOCOL, SELECTION_RULE, split_world_trials
    path = tmp_path / "smoke.jsonl"
    argv = ["--seed-start", "70123", "--n-seeds", "1", "--samples", "2", "--max-decisions-per-seed", "1", "--max-steps", "1", "--out", str(path), "--time-budget-seconds", "30"]
    assert main(argv) == 0
    report = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert report["evaluation_protocol"] == SPLIT_PROTOCOL
    assert report["selection_rule"] == SELECTION_RULE
    header = json.loads(path.read_text().splitlines()[0])
    assert header["config"]["samples"] == 2
    assert header["evaluation_protocol"] == SPLIT_PROTOCOL
    assert path.read_bytes().endswith(b"\n")
    rows = list(ds.read_dataset(path))
    assert len(rows) == 1
    assert split_world_trials(rows[0])[1] is None
    for arm in rows[0]["arms"]:
        assert [t["sample_index"] for t in arm["trials"]] == [0, 1]
        assert len({t["seed"] for t in arm["trials"]}) == 2
    before = path.read_bytes()
    assert main(argv + ["--resume"]) == 0
    assert path.read_bytes() == before


def test_cli_rejects_k1_before_creating_output(tmp_path):
    from tools.collect_blind_decisions import main
    path = tmp_path / "invalid.jsonl"
    with pytest.raises(SystemExit) as exc:
        main(["--seed-start", "1", "--samples", "1", "--out", str(path), "--time-budget-seconds", "0.001"])
    assert exc.value.code == 2
    assert not path.exists()


def test_parallel_options_and_strata_parser():
    import os
    from tools.collect_blind_decisions import parser, parse_decisions_per_ante
    args = parser().parse_args(["--seed-start", "1", "--out", "unused"])
    assert args.workers == max(1, (os.cpu_count() or 1) - 1)
    assert args.coverage_fraction == 0
    assert args.decisions_per_ante == {"1": None, "2": None, "3": 2, "4": 2, "5": 2, "6": 1, "7": 1, "8": 1}
    assert parse_decisions_per_ante('{"1":"all","3-5":2}') == {"1": None, "3": 2, "4": 2, "5": 2}
    for bad in ('{"9":1}', '{"3-1":2}', '{"1":-1}', '{"1":true}', '[]'):
        with pytest.raises(ValueError):
            parse_decisions_per_ante(bad)


def test_shell_friendly_strata_parser():
    from tools.collect_blind_decisions import parse_decisions_per_ante
    assert parse_decisions_per_ante("1:2,2:2,3-8:1") == {
        "1": 2, "2": 2, "3": 1, "4": 1, "5": 1, "6": 1, "7": 1, "8": 1}
    assert parse_decisions_per_ante("1:all,2:null") == {"1": None, "2": None}
    assert parse_decisions_per_ante("balanced") == {"1": 1, "2": 2, "3": 3, "4": 3, "5": 3, "6": 3, "7": 3, "8": 3}
    for bad in ("1:2,1:3", "1:2,", "1:true", "", "1:2,1-3:1"):
        with pytest.raises(ValueError):
            parse_decisions_per_ante(bad)


def test_filter_trivial_option():
    from tools.collect_blind_decisions import parser, is_trivial_row
    args = parser().parse_args(["--seed-start", "1", "--out", "unused", "--filter-trivial"])
    assert args.filter_trivial is True

    trivial_row = {
        "arms": [
            {"trials": [{"clear": True, "steps": 1, "score": 2000, "target": 800, "censored": False}]}
        ]
    }
    assert is_trivial_row(trivial_row) is True

    informative_row = {
        "arms": [
            {"trials": [{"clear": True, "steps": 3, "score": 850, "target": 800, "censored": False}]}
        ]
    }
    assert is_trivial_row(informative_row) is False


def test_shell_friendly_strata_cli(tmp_path):
    import subprocess
    import sys
    from tools.collect_blind_decisions import ROOT
    path = tmp_path / "compact.jsonl"
    result = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "collect_blind_decisions.py"),
         "--seed-start", "70200", "--n-seeds", "1", "--samples", "2",
         "--decisions-per-ante", "1:2,2:2,3-8:1", "--workers", "1",
         "--time-budget-seconds", ".01", "--out", str(path)],
        cwd=ROOT, capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    header = json.loads(path.read_text().splitlines()[0])
    assert header["config"]["decisions_per_ante"]["8"] == 1


def test_coverage_hash_deterministic_and_bounded():
    from tools.collect_blind_decisions import coverage_selected
    assert not any(coverage_selected(1, i, 0) for i in range(100))
    assert all(coverage_selected(1, i, 1) for i in range(100))
    first = [coverage_selected(70200, i, 0.2) for i in range(100)]
    assert first == [coverage_selected(70200, i, 0.2) for i in range(100)]
    assert 5 < sum(first) < 40


def test_coverage_pool_separate_primary_unchanged():
    ds = dataset()
    game = game_root()
    baseline = copy.deepcopy(game)
    with ds.policy_scope():
        plain = ds.trajectory_step(game, V10.HeuristicV10(), 70123, 0, ["a", "b"], max_steps=1)
    with ds.policy_scope():
        covered = ds.trajectory_step(baseline, V10.HeuristicV10(), 70123, 0, ["a", "b"], max_steps=1, extended=True)
    assert len(plain["arms"]) == 8
    assert plain["arms"] == covered["arms"]
    assert len(covered["coverage_arms"]) > len(covered["arms"])
    assert {ds.action_key(a["action"]) for a in covered["arms"]} <= {ds.action_key(a["action"]) for a in covered["coverage_arms"]}
    assert all(len(a["trials"]) == 2 for a in covered["coverage_arms"])
    assert covered["coverage"] == ds.coverage_report(covered["arms"], covered["coverage_arms"])
    assert {a["action"]["type"] for a in plain["arms"]} == {"play", "discard"}
    assert pickle.dumps(game) == pickle.dumps(baseline)


def test_real_strata_reach_later_ante_and_keep_global_cap():
    from tools.collect_blind_decisions import collect_seed
    from collections import Counter
    rows, summary = collect_seed(70123, samples=2, max_decisions=4, max_steps=1,
                                 decisions_per_ante={"1": 1, "2": 1})
    assert len(rows) <= 4
    assert any(row["ante"] >= 2 for row in rows)
    counts = Counter((row["ante"], row["blind_idx"]) for row in rows)
    assert max(counts.values()) == 1
    assert summary["ante_decisions"] == dict(Counter(str(row["ante"]) for row in rows))
    assert summary["counters"]["skipped:stratum"] > 0
    assert summary["stop_reason"] != "decision_cap"


def test_spawn_seed_worker_matches_serial_and_discards_budget():
    import multiprocessing
    import time
    from concurrent.futures import ProcessPoolExecutor
    from tools.collect_blind_decisions import collect_seed, seed_worker
    options = dict(samples=2, max_decisions=1, max_steps=1, max_trajectory_steps=3)
    expected, summary = collect_seed(70123, **options)
    with ProcessPoolExecutor(max_workers=2, mp_context=multiprocessing.get_context("spawn")) as pool:
        result = pool.submit(seed_worker, (70123, options)).result(timeout=60)
    assert result["rows"] == expected
    assert result["summary"] == summary
    assert result["elapsed_seconds"] > 0
    assert seed_worker((70123, dict(options, deadline=time.monotonic() - 1))) is None


def test_worker_count_resume_compatible(tmp_path, capsys):
    ds = dataset()
    from tools.collect_blind_decisions import main
    path = tmp_path / "parallel.jsonl"
    common = ["--seed-start", "70123", "--n-seeds", "2", "--samples", "2", "--max-decisions-per-seed", "1",
              "--max-steps", "1", "--max-trajectory-steps", "3", "--out", str(path), "--time-budget-seconds", "60"]
    assert main(common + ["--workers", "2"]) == 0
    report = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert report["workers"] == 2 and report["new_seeds"] == 2
    assert report["ante_decisions"] == {"1": 2}
    assert report["per_worker"]
    before = path.read_bytes()
    header = json.loads(before.splitlines()[0])
    assert "workers" not in header["config"]
    assert main(common + ["--workers", "1", "--resume"]) == 0
    assert path.read_bytes() == before
    rows = list(ds.read_dataset(path))
    assert len({r["seed"] for r in rows}) == 2
    serial_path = tmp_path / "serial.jsonl"
    serial_args = [str(serial_path) if value == str(path) else value for value in common]
    assert main(serial_args + ["--workers", "1"]) == 0
    assert sorted(serial_path.read_bytes().splitlines()) == sorted(before.splitlines())


def test_interrupt_preserves_only_completed_seed(tmp_path, monkeypatch, capsys):
    from tools import collect_blind_decisions as cli
    original = cli.seed_worker
    calls = []
    def interrupted(task):
        calls.append(task[0])
        if len(calls) == 2:
            raise KeyboardInterrupt()
        return original(task)
    monkeypatch.setattr(cli, "seed_worker", interrupted)
    path = tmp_path / "interrupt.jsonl"
    args = ["--seed-start", "70123", "--n-seeds", "2", "--workers", "1", "--samples", "2", "--max-steps", "1",
            "--max-decisions-per-seed", "1", "--max-trajectory-steps", "3", "--out", str(path)]
    assert cli.main(args) == 130
    report = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert report["interrupted"] is True
    assert report["complete_seeds"] == [70123]
    assert len(list(dataset().read_dataset(path))) == 1


def test_coverage_trials_validated_without_changing_primary_contract():
    ds = dataset()
    row = validation_row()
    row["coverage_arms"] = copy.deepcopy(row["arms"])
    row["coverage_arms"][0]["trials"].pop()
    with pytest.raises(ValueError):
        ds.validate_row(row, {"config": {"samples": 2}})


def test_budget_does_not_poison_seed(tmp_path):
    ds = dataset()
    from tools.collect_blind_decisions import collect_seed
    with pytest.raises(ds.BudgetExceeded):
        collect_seed(12, samples=1, max_decisions=1, max_steps=1, deadline=0)


@pytest.mark.parametrize("flag,value", [("--workers", "0"), ("--workers", "-3"),
                                       ("--time-budget-seconds", "inf"), ("--time-budget-seconds", "nan")])
def test_deadline_reaches_worker_and_validates_cli_scalars(tmp_path, flag, value):
    ds = dataset()
    from tools.collect_blind_decisions import collect_seed, parser, main
    args = parser().parse_args(["--seed-start", "1", "--out", "unused"])
    assert args.time_budget_seconds == 60
    with pytest.raises(SystemExit):
        main(["--seed-start", "1", "--out", str(tmp_path / "x.jsonl"), flag, value])
    with pytest.raises(ds.BudgetExceeded):
        collect_seed(70123, samples=2, max_decisions=1, max_steps=1, deadline=0)


@pytest.mark.parametrize("workers", [1, 2])
def test_cli_tiny_budget_bounded(tmp_path, workers):
    import subprocess
    import sys
    from tools.collect_blind_decisions import ROOT
    path = tmp_path / f"bounded{workers}.jsonl"
    started = time.monotonic()
    result = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "collect_blind_decisions.py"),
         "--seed-start", "70200", "--n-seeds", "50", "--samples", "10",
         "--workers", str(workers), "--time-budget-seconds", ".01", "--out", str(path)],
        cwd=ROOT, capture_output=True, text=True, timeout=20,
    )
    assert result.returncode == 0, result.stderr
    assert "Traceback" not in result.stderr
    assert time.monotonic() - started < 20
    report = json.loads(result.stdout.splitlines()[-1])
    assert report["new_seeds"] == report["new_decisions"] == report["new_trials"] == 0
    assert report["complete_seeds"] == []
    assert 0 <= report["discarded_budget_seeds"] <= workers
    assert report["submitted_seeds"] == report["discarded_budget_seeds"]
    assert report["budget_exhausted"] is True
    assert len(path.read_text().splitlines()) == 1
    assert list(dataset().read_dataset(path)) == []


def test_dry_run_filters_finite_range_without_game_or_output(tmp_path, monkeypatch, capsys):
    from tools import collect_blind_decisions as cli
    def forbidden(*args, **kwargs):
        raise AssertionError("dry run must not start games or workers")
    monkeypatch.setattr(cli, "BalatroGame", forbidden)
    monkeypatch.setattr(cli, "ProcessPoolExecutor", forbidden)
    path = tmp_path / "absent" / "dry.jsonl"
    assert cli.main(["--seed-start", "71000", "--n-seeds", "40", "--collect-split", "test",
                     "--dry-run", "--out", str(path)]) == 0
    report = json.loads(capsys.readouterr().out)
    expected = [s for s in range(71000, 71040) if dataset().seed_split(s) == "test"]
    assert report["requested_range"] == {"start": 71000, "stop": 71040, "count": 40}
    assert report["range_split_counts"] == {"train": 34, "validation": 3, "test": 3}
    assert report["selected_seeds"] == len(expected) == 3
    assert report["planned_seed_ids"] == expected
    assert report["pending_seed_ids"] == expected
    assert report["new_seeds"] == report["new_decisions"] == 0
    assert not path.parent.exists()


@pytest.fixture
def synthetic_collector(monkeypatch):
    from tools import collect_blind_decisions as cli
    class SyntheticGame:
        def __init__(self, seed, rng_mode):
            self.seed = seed
            self.ante = 1
            self.blind_idx = 0
            self.steps = 0
            self.state = State.SELECTING_HAND
        def step(self, action):
            self.steps += 1
            self.blind_idx = self.steps // 6
            if self.steps == 12:
                self.state = State.GAME_OVER
    class Policy:
        def decide(self, game):
            return {"type": "play", "cards": [0]}
    def trajectory(game, policy, seed, decision_id, seeds, **kwargs):
        row = validation_row(len(seeds))
        row.update(seed=seed, split=dataset().seed_split(seed), decision_id=decision_id,
                   blind_idx=game.blind_idx)
        for i, arm in enumerate(row["arms"]):
            for k, trial in enumerate(arm["trials"]):
                trial.update(seed=seeds[k], clear=bool(i), censored=False, pred=float(i))
        game.step(policy.decide(game))
        return row
    monkeypatch.setattr(cli, "BalatroGame", SyntheticGame)
    monkeypatch.setattr(cli.DS, "GuardedH10", Policy)
    monkeypatch.setattr(cli.DS, "hidden_observation", lambda game: False)
    monkeypatch.setattr(cli.DS, "_exact_win", lambda game: False)
    monkeypatch.setattr(cli.DS, "trajectory_step", trajectory)
    return cli


@pytest.mark.parametrize("offset,stride,expected,skipped", [(0, 1, [0, 1], 0), (0, 2, [0, 2], 3), (1, 2, [1, 3], 3), (2, 1, [2, 3], 2)])
def test_visit_schedule_counts_slots_not_visits(synthetic_collector, offset, stride, expected, skipped):
    rows, summary = synthetic_collector.collect_seed(
        71000, samples=2, max_decisions=10, max_trajectory_steps=6,
        decisions_per_ante={"1": 2}, decision_offset=offset, decision_stride=stride)
    assert [row["visit_index"] for row in rows] == expected
    assert [row["decision_id"] for row in rows] == expected
    assert summary["decision_visit_counts"] == {str(j): 1 for j in expected}
    assert summary["counters"]["visits"] == 6
    assert summary["counters"]["scheduled"] == 2
    assert summary["counters"].get("skipped:schedule", 0) == skipped
    assert summary["counters"].get("skipped:stratum", 0) == 4 - skipped
    assert all(row["sampling"] == {"decision_offset": offset, "decision_stride": stride,
                                   "blind_quota": 2, "scheduled_slot": i}
               for i, row in enumerate(rows))


def test_schedule_does_not_replace_excluded_slots_or_change_cap(synthetic_collector, monkeypatch):
    cli = synthetic_collector
    original = cli.DS.trajectory_step
    def excluded(game, policy, seed, decision_id, seeds, **kwargs):
        row = original(game, policy, seed, decision_id, seeds, **kwargs)
        return None if decision_id == 1 else row
    monkeypatch.setattr(cli.DS, "trajectory_step", excluded)
    rows, summary = cli.collect_seed(71000, samples=2, max_decisions=1,
                                     decisions_per_ante={"1": 2}, decision_offset=1, decision_stride=2)
    assert [row["decision_id"] for row in rows] == [3]
    assert summary["counters"]["scheduled"] == 2
    assert summary["counters"]["skipped:cap"] == 8


@pytest.mark.parametrize("flag,value", [("--decision-offset", "-1"), ("--decision-stride", "0"),
                                        ("--decision-stride", "-1"), ("--decision-offset", "1.5"),
                                        ("--collect-split", "holdout")])
def test_sampling_flags_refused_before_output(tmp_path, flag, value):
    from tools.collect_blind_decisions import main
    path = tmp_path / "invalid.jsonl"
    with pytest.raises(SystemExit) as exc:
        main(["--seed-start", "1", "--out", str(path), flag, value])
    assert exc.value.code == 2
    assert not path.exists()


@pytest.mark.parametrize("options", [{"decision_offset": -1}, {"decision_stride": 0},
                                     {"decision_offset": True}, {"decision_stride": 1.5}])
def test_collect_seed_refuses_invalid_schedule(options):
    from tools.collect_blind_decisions import collect_seed
    with pytest.raises(ValueError, match="decision"):
        collect_seed(1, **options)


def test_empty_split_fails_without_output_but_dry_run_reports(tmp_path, capsys):
    from tools.collect_blind_decisions import main
    seed = next(s for s in range(100) if dataset().seed_split(s) == "train")
    path = tmp_path / "empty.jsonl"
    args = ["--seed-start", str(seed), "--n-seeds", "1", "--collect-split", "test", "--out", str(path)]
    with pytest.raises(SystemExit) as exc:
        main(args)
    assert exc.value.code == 2
    assert "no eligible seeds" in capsys.readouterr().err
    assert not path.exists()
    assert main(args + ["--dry-run"]) == 0
    assert json.loads(capsys.readouterr().out)["planned_seed_ids"] == []
    assert not path.exists()


def test_filtered_resume_manifest_is_read_only_and_totals_include_prior_seeds(synthetic_collector, tmp_path, capsys, monkeypatch):
    cli = synthetic_collector
    path = tmp_path / "filtered.jsonl"
    args = ["--seed-start", "71000", "--n-seeds", "40", "--collect-split", "test", "--samples", "2",
            "--workers", "1", "--decisions-per-ante", "1:2", "--decision-offset", "1", "--decision-stride", "2",
            "--max-decisions-per-seed", "4", "--out", str(path)]
    expected = [s for s in range(71000, 71040) if dataset().seed_split(s) == "test"]
    original = cli.seed_worker
    def interrupted(task):
        if task[0] != expected[0]:
            raise KeyboardInterrupt()
        return original(task)
    monkeypatch.setattr(cli, "seed_worker", interrupted)
    assert cli.main(args) == 130
    capsys.readouterr()
    before = path.read_bytes()
    assert cli.main(args + ["--resume", "--dry-run"]) == 0
    dry = json.loads(capsys.readouterr().out)
    assert dry["planned_seed_ids"] == expected
    assert dry["pending_seed_ids"] == expected[1:]
    assert dry["pending_selected_seeds"] == 2
    assert path.read_bytes() == before
    monkeypatch.setattr(cli, "seed_worker", original)
    assert cli.main(args + ["--resume"]) == 0
    report = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert report["new_seeds"] == report["submitted_seeds"] == 2
    assert report["selected_seeds"] == 3 and report["requested_range"]["count"] == 40
    assert report["pending_seed_ids"] == []
    assert report["split_counts"]["test"] == {"seeds": 3, "decisions": 12, "informative_seeds": 3, "informative_decisions": 12}
    assert report["decision_visit_counts"] == {"1": 6, "3": 6}
    rows = list(dataset().read_dataset(path))
    assert sorted({r["seed"] for r in rows}) == expected
    assert all(r["split"] == "test" for r in rows)
    header = json.loads(path.read_bytes().splitlines()[0])
    assert header["config"]["collect_split"] == "test"
    assert header["config"]["decision_offset"] == 1
    assert header["config"]["decision_stride"] == 2
    assert "workers" not in header["config"] and "dry_run" not in header["config"]
    before = path.read_bytes()
    assert cli.main(args + ["--resume"]) == 0
    again = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert again["split_counts"] == report["split_counts"]
    assert again["decision_visit_counts"] == report["decision_visit_counts"]
    assert again["new_decisions"] == 0 and path.read_bytes() == before


def test_real_later_visit_and_default_trajectory_byte_purity(monkeypatch):
    from tools import collect_blind_decisions as cli
    captured = []
    def capture(*args, **kwargs):
        game = BalatroGame(*args, **kwargs)
        captured.append(game)
        return game
    monkeypatch.setattr(cli, "BalatroGame", capture)
    before = copy.deepcopy((V9.ACTIVE_PARAMS, V10.V10_PARAMS))
    options = dict(samples=2, max_decisions=2, max_steps=1, max_trajectory_steps=20,
                   decisions_per_ante={"1": 2})
    plain, _ = cli.collect_seed(70123, **options)
    later, _ = cli.collect_seed(70123, **options, decision_offset=1, decision_stride=2)
    baseline = BalatroGame(seed=70123, rng_mode="seed")
    expected = []
    with dataset().policy_scope():
        policy = dataset().GuardedH10()
        for step in range(20):
            if baseline.state == State.SELECTING_HAND and len(expected) < 2:
                expected.append(dataset().trajectory_step(baseline, policy, 70123, step,
                                [f"v14:70123:{step}:{k}" for k in range(2)], max_steps=1))
            else:
                baseline.step(policy.decide(baseline))
    assert [{k: v for k, v in row.items() if k not in ("visit_index", "sampling")} for row in plain] == expected
    assert later and later[0]["visit_index"] == 1
    assert all(row["visit_index"] in (1, 3) for row in later)
    assert all(pickle.dumps(game) == pickle.dumps(baseline) for game in captured)
    assert (V9.ACTIVE_PARAMS, V10.V10_PARAMS) == before


def test_posthoc_diagnostics_use_complete_raw_arm_clear_means():
    from tools.collect_blind_decisions import decision_diagnostics
    rows = []
    for decision_id in range(4):
        row = validation_row()
        row.update(decision_id=decision_id, visit_index=decision_id)
        for i, arm in enumerate(row["arms"]):
            for trial in arm["trials"]:
                trial.update(clear=bool(i), censored=False)
        rows.append(row)
    rows[1]["arms"][1]["trials"][0]["censored"] = True
    rows[2]["arms"][1]["trials"][0]["clear"] = None
    for arm in rows[3]["arms"]:
        arm["trials"][0]["clear"] = False
        arm["trials"][1]["clear"] = True
    result = decision_diagnostics(rows)
    assert result["informative_decisions"] == 1
    assert result["decision_visit_counts"] == {"0": 1, "1": 1, "2": 1, "3": 1}


def test_ten_independent_synthetic_seeds_forty_decisions_gate_inconclusive(synthetic_collector, tmp_path, capsys):
    from balatro_sim.eval_metrics import gate_verdict, paired_improvement, split_world_trials
    cli = synthetic_collector
    seeds = [s for s in range(72000, 72200) if dataset().seed_split(s) == "test"][:10]
    assert len(seeds) == len(set(seeds)) == 10
    path = tmp_path / "ten-seeds.jsonl"
    args = ["--seed-start", str(seeds[0]), "--n-seeds", str(seeds[-1] - seeds[0] + 1),
            "--collect-split", "test", "--samples", "2", "--workers", "1", "--decisions-per-ante", "1:2",
            "--decision-offset", "1", "--decision-stride", "2", "--max-decisions-per-seed", "4", "--out", str(path)]
    assert cli.main(args) == 0
    report = json.loads(capsys.readouterr().out.splitlines()[-1])
    rows = list(dataset().read_dataset(path))
    assert len(rows) == 40 and sorted({r["seed"] for r in rows}) == seeds
    assert all(r["split"] == dataset().seed_split(r["seed"]) == "test" for r in rows)
    assert report["decision_visit_counts"] == {"1": 20, "3": 20}
    assert report["split_counts"]["test"] == {"seeds": 10, "decisions": 40, "informative_seeds": 10, "informative_decisions": 40}
    assert all(split_world_trials(row)[1] is None for row in rows)
    measured = paired_improvement(rows, "pred")
    assert measured["informative_seeds"] == 10 and measured["informative_decisions"] == 40
    verdict = gate_verdict(measured)
    assert verdict["thresholds"]["min_informative_seeds"] == 30
    assert verdict["verdict"] == report["scientific_gate"] == "INCONCLUSIVE"


def test_committed_diagnostics_fallback_counts_zero_row_seeds(tmp_path):
    from tools.collect_blind_decisions import committed_diagnostics
    ds = dataset()
    path = tmp_path / "fallback.jsonl"
    writer = ds.DatasetWriter(path, ds.metadata({"samples": 2}))
    row = validation_row()
    for i, arm in enumerate(row["arms"]):
        for trial in arm["trials"]:
            trial.update(clear=bool(i), censored=False)
    writer.write_seed(10, [row], {})
    writer.write_seed(11, [], {})
    before = path.read_bytes()
    report = committed_diagnostics(writer)
    assert sum(c["seeds"] for c in report["split_counts"].values()) == 2
    assert sum(c["decisions"] for c in report["split_counts"].values()) == 1
    assert report["split_counts"][ds.seed_split(10)]["informative_seeds"] == 1
    assert report["decision_visit_counts"] == {"unknown": 1}
    assert path.read_bytes() == before


def test_filtered_parallel_real_rows_and_resume(tmp_path, capsys):
    from tools.collect_blind_decisions import main
    path = tmp_path / "filtered-parallel.jsonl"
    args = ["--seed-start", "71000", "--n-seeds", "20", "--collect-split", "test",
            "--samples", "2", "--workers", "2", "--max-steps", "1", "--max-trajectory-steps", "20",
            "--decision-offset", "1", "--decision-stride", "2", "--max-decisions-per-seed", "1",
            "--time-budget-seconds", "30", "--out", str(path)]
    assert main(args) == 0
    report = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert report["complete_seeds"] == report["planned_seed_ids"] == [71002, 71017]
    assert report["submitted_seeds"] == 2
    rows = list(dataset().read_dataset(path))
    assert rows and all(r["seed"] in (71002, 71017) and r["split"] == "test" for r in rows)
    assert all(r["visit_index"] >= 1 and r["visit_index"] % 2 == 1 for r in rows)
    before = path.read_bytes()
    assert main(args + ["--resume"]) == 0
    resumed = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert resumed["submitted_seeds"] == 0 and resumed["pending_selected_seeds"] == 0
    assert resumed["split_counts"] == report["split_counts"]
    assert path.read_bytes() == before


def test_dry_run_real_cli_creates_nothing(tmp_path):
    import subprocess
    import sys
    from tools.collect_blind_decisions import ROOT
    path = tmp_path / "absent" / "dry.jsonl"
    result = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "collect_blind_decisions.py"), "--seed-start", "71000",
         "--n-seeds", "40", "--collect-split", "test", "--dry-run", "--out", str(path)],
        cwd=ROOT, capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["planned_seed_ids"] == [71002, 71017, 71034]
    assert report["new_seeds"] == report["new_decisions"] == report["new_trials"] == 0
    assert not path.parent.exists()
