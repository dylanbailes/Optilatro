"""test_replay.py — replay-diff harness tests.

Covers the SeedSource tracing hook (seed_rng.py) and the harness in
balatro_sim/replay.py: capture_game / log_sha / ReplayDiff / CLI.
"""
from __future__ import annotations

from balatro_sim.seed_rng import SeedSource, LuaRandom
from balatro_sim.replay import capture_game, ReplayDiff, log_sha, main


class TestTracing:
    def test_records_node_draws_with_values(self):
        s = SeedSource("ABC")
        recs = s.enable_tracing()
        s.node("boss").choice(["a", "b", "c"])
        s.node("cdt1").random()
        s.node("shuffle").shuffle([1, 2, 3, 4])
        assert len(recs) == 1 + 1 + 3
        r0 = recs[0]
        assert r0.node == "boss" and r0.method == "choice"
        assert r0.result in ("a", "b", "c")
        assert r0.seq == 1
        # per-node seq counters are independent
        assert recs[1].node == "cdt1" and recs[1].seq == 1
        # the recorded value is exactly the LuaRandom seed for that draw
        assert recs[1].result == LuaRandom(recs[1].value).random()

    def test_per_node_seq_increments(self):
        s = SeedSource("ABC")
        recs = s.enable_tracing()
        s.node("boss").random()
        s.node("boss").random()
        assert [r.seq for r in recs] == [1, 2]
        assert recs[0].value != recs[1].value   # node advances per draw

    def test_tracing_is_observation_only(self):
        def draws(traced: bool):
            s = SeedSource("XYZ")
            if traced:
                s.enable_tracing()
            return [s.node("boss").random() for _ in range(20)]
        assert draws(True) == draws(False)

    def test_disable_returns_records(self):
        s = SeedSource("Q")
        s.enable_tracing()
        s.node("boss").random()
        got = s.disable_tracing()
        assert len(got) == 1
        assert s.records is None
        # draws after disable are not recorded
        s.node("boss").random()
        assert s.disable_tracing() == []


class TestHarness:
    def test_identical_runs_are_bit_identical(self):
        a, sa = capture_game(999, steps=1500)
        b, sb = capture_game(999, steps=1500)
        assert sa["sha256"] == sb["sha256"]
        assert sa["records"] == sb["records"]
        assert ReplayDiff(a, b).identical
        # Compare canonical texts, not dataclass equality — result objects
        # (e.g. Cards) have no stable __eq__ across runs.
        assert [r.as_text() for r in a] == [r.as_text() for r in b]

    def test_tracing_does_not_perturb_the_run(self):
        _, traced = capture_game(777, steps=1500, trace=True)
        _, plain = capture_game(777, steps=1500, trace=False)
        assert traced["total_reward"] == plain["total_reward"]
        assert traced["episodes"] == plain["episodes"]
        assert traced["max_ante"] == plain["max_ante"]

    def test_divergence_detected_between_seeds(self):
        a, _ = capture_game(1, steps=400)
        b, _ = capture_game(2, steps=400)
        d = ReplayDiff(a, b)
        assert not d.identical
        assert d.first_divergence() is not None

    def test_divergence_detected_different_actions(self):
        a, _ = capture_game(1, steps=400, action_seed=1)
        b, _ = capture_game(1, steps=400, action_seed=2)
        assert not ReplayDiff(a, b).identical

    def test_scripted_actions_supported(self):
        a, sa = capture_game(5, steps=300, actions=[0, 1, 2, 3])
        b, sb = capture_game(5, steps=300, actions=[0, 1, 2, 3])
        assert sa["sha256"] == sb["sha256"]
        assert ReplayDiff(a, b).identical

    def test_report_text(self):
        a, sa = capture_game(3, steps=150)
        b, _ = capture_game(3, steps=150)
        text = ReplayDiff(a, b).report(sa)
        assert "IDENTICAL" in text and "sha256" in text

    def test_divergence_report_text(self):
        a, sa = capture_game(7, steps=400, action_seed=1)
        b, sb = capture_game(7, steps=400, action_seed=2)
        text = ReplayDiff(a, b).report(sa, sb)
        assert "DIVERGED" in text and "first divergence" in text
        assert ">>>" in text               # context marker on the divergent draw


class TestCli:
    def test_cli_exits_zero_on_identical(self):
        assert main(["--seed", "42", "--steps", "150"]) == 0
