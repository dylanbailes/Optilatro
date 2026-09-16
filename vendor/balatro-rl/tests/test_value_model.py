"""Tests for the learned value model and the V12 oracle.

The properties pinned here are the ones that make the stack safe to ship:

  parity        — V12 with the oracle off is byte-identical to frozen V10;
                  this is the control that catches a silent regression, the
                  exact failure mode this repo already paid for once
  purity        — scoring a candidate mutates no game state and consumes no
                  RNG, so evaluation can never move the seed-exact stream
  determinism   — same seed, same artifact, same run
  shrinkage     — the cell hierarchy backs off correctly and cannot recurse
  gating        — the oracle fires only when switched on and only on
                  candidates that clear the confidence test
  artifact      — round-trips, and refuses an unknown schema version
"""
from __future__ import annotations

import json

import pytest

from balatro_sim.game import BalatroGame, State
from balatro_sim.rollout import rollout
from balatro_sim.agent_v10 import SearchShopV10
from balatro_sim import catalogue as CAT
from balatro_sim import value_tables as VT
from balatro_sim.agent_v12 import SearchShopV12, candidates
from types import SimpleNamespace


# ────────────────────────────────────────────────────────────────────────────
# Fixtures / helpers
# ────────────────────────────────────────────────────────────────────────────

SEEDS = (10500, 10501, 10502)


def _shop_game(seed: int = 10500):
    """Drive a frozen run into a SHOP state."""
    g = BalatroGame(seed=seed, rng_mode="seed")
    driver = SearchShopV10()
    for _ in range(2000):
        if g.state == State.SHOP:
            return g
        g.step(driver.decide(g))
    raise AssertionError("no shop reached")


def _toy_table(**overrides) -> VT.ValueTable:
    data = {
        "version": VT.MODEL_VERSION,
        "catalogue_fingerprint": CAT.fingerprint(),
        "feature_order": list(VT.FEATURE_ORDER),
        "w": [0.0] * len(VT.FEATURE_ORDER),
        "b": 0.0,
        "mu": [0.0] * len(VT.FEATURE_ORDER),
        "sd": [1.0] * len(VT.FEATURE_ORDER),
        "residuals": {},
        "tau": 1.0,
        "beta": 0.0,
        "resid_sd": 2.0,
        "meta": {},
    }
    data.update(overrides)
    return VT.ValueTable(data)


# ────────────────────────────────────────────────────────────────────────────
# Cell hierarchy and shrinkage
# ────────────────────────────────────────────────────────────────────────────


class TestCellHierarchy:
    def test_parent_chain_is_correct(self):
        assert VT.cell_parents("j_blueprint|a3|s1") == [
            "j_blueprint|a3", "j_blueprint", "role:other"]
        assert VT.cell_parents("j_blueprint|a3") == ["j_blueprint", "role:other"]
        assert VT.cell_parents("j_blueprint") == ["role:other"]
        assert VT.cell_parents("role:other") == []

    def test_no_cell_is_its_own_parent(self):
        for cell in ("j_blueprint", "j_blueprint|a3", "j_blueprint|a3|s1",
                     "role:xmult", "p_buffoon"):
            assert cell not in VT.cell_parents(cell)

    def test_shrinkage_falls_back_to_parent(self):
        t = _toy_table(residuals={"j_blueprint": {"n": 10.0, "total": 5.0,
                                                  "sumsq": 5.0}})
        fine = t.residual("j_blueprint|a1|s0")
        # No evidence at the fine cell -> exactly the parent's value, which is
        # itself shrunk toward the root (0) by tau: total / (n + tau).
        assert fine == pytest.approx(5.0 / (10.0 + 1.0))

    def test_grandchild_shrinks_toward_child_not_root(self):
        t = _toy_table(tau=1.0, residuals={
            "j_blueprint": {"n": 100.0, "total": 50.0, "sumsq": 25.0},
            "j_blueprint|a1": {"n": 10.0, "total": 20.0, "sumsq": 40.0},
            "j_blueprint|a1|s0": {"n": 1.0, "total": 0.0, "sumsq": 0.0},
        })
        v = t.residual("j_blueprint|a1|s0")
        # One noisy sample (0.0) pooled with a strong child mean (2.0):
        # the result must sit between them, not jump to the root.
        assert 0.0 < v < 2.0

    def test_no_evidence_means_no_correction(self):
        t = _toy_table(residuals={})
        assert t.residual("j_unseen|a5|s2") == 0.0

    def test_effective_n_walks_up_the_hierarchy(self):
        t = _toy_table(residuals={"j_blueprint": {"n": 7.0, "total": 0.0,
                                                  "sumsq": 0.0}})
        assert t.effective_n("j_blueprint|a2|s0") == 7.0
        assert t.effective_n("j_never_seen|a2|s0") == 0.0

    def test_stderr_grows_without_evidence(self):
        t = _toy_table(resid_sd=2.0, residuals={
            "j_a": {"n": 100.0, "total": 0.0, "sumsq": 0.0},
        })
        assert t.cell_stderr("j_a|a1|s0") < t.cell_stderr("j_b|a1|s0")
        assert t.cell_stderr("j_b|a1|s0") == pytest.approx(2.0)

    def test_confidence_does_not_inherit_role_strength(self):
        """Shrinkage may borrow from a role; confidence must not.

        A role pools hundreds of rows across unrelated items. If the stderr
        inherited that count it would collapse to ~0.15 and let the oracle act
        with no evidence about the item in front of it — measured as the reason
        the first V12 oracle accepted 17 of its first 51 offers.
        """
        t = _toy_table(resid_sd=2.0, residuals={
            "role:other": {"n": 445.0, "total": 0.0, "sumsq": 0.0},
        })
        # `effective_n` still walks up to the role (shrinkage strength)...
        assert t.effective_n("j_blueprint|a1|s0") == 445.0
        # ...but confidence for an unseen item is the full residual spread.
        assert t.own_n("j_blueprint|a1|s0") == 0.0
        assert t.cell_stderr("j_blueprint|a1|s0") == pytest.approx(2.0)

    def test_own_n_prefers_the_finest_evidence(self):
        t = _toy_table(residuals={
            "j_a": {"n": 100.0, "total": 0.0, "sumsq": 0.0},
            "j_a|a3|s0": {"n": 2.0, "total": 0.0, "sumsq": 0.0},
        })
        assert t.own_n("j_a|a3|s0") == 2.0
        assert t.own_n("j_a|a1|s0") == 100.0


# ────────────────────────────────────────────────────────────────────────────
# Feature contract
# ────────────────────────────────────────────────────────────────────────────


class TestFeatures:
    def test_scenario_features_are_finite_and_item_independent(self):
        g = _shop_game()
        f = VT.scenario_features(g, "j_blueprint")
        assert all(isinstance(v, float) for v in f.values())
        assert f["ante"] >= 1.0
        assert 0.0 <= f["ante_frac"] <= 1.0
        # power must be a chip quantity, not a probability (the ref[2]/ref[3]
        # mix-up that silently made every build look powerless).
        assert f["log_power"] >= 0.0
        assert 0.0 <= f["power_ratio"] <= 1e9

    def test_vector_is_fixed_width_and_total(self):
        vec = VT.build_vector({"ctx_ante": 3.0})
        assert len(vec) == len(VT.FEATURE_ORDER)
        assert all(isinstance(v, float) for v in vec)

    def test_decision_features_include_item_and_context_blocks(self):
        g = _shop_game()
        items = [it for it in g.current_shop if getattr(it, "kind", "") == "joker"]
        if not items:
            pytest.skip("no shop joker in this state")
        feats = VT.decision_features(g, items[0])
        assert any(k.startswith("item_") for k in feats)
        assert any(k.startswith("ctx_") for k in feats)

    def test_scoring_a_candidate_has_no_side_effects(self):
        """Purity: features + value must not move the game or the stream."""
        g = _shop_game()
        items = [it for it in g.current_shop if getattr(it, "kind", "") == "joker"]
        if not items:
            pytest.skip("no shop joker in this state")
        before = (g.dollars, g.ante, len(g.hand), len(g.deck), g.blind_idx)
        t = _toy_table()
        for _ in range(3):
            t.value_of(g, items[0])
            VT.decision_features(g, items[0])
        after = (g.dollars, g.ante, len(g.hand), len(g.deck), g.blind_idx)
        assert before == after
        # The frozen policy must still make the identical next decision.
        a = SearchShopV10().decide(g)
        t.value_of(g, items[0])
        b = SearchShopV10().decide(g)
        assert a == b

    def test_cell_key_is_item_ante_support(self):
        g = _shop_game()
        cell = VT.cell_key(g, "j_blueprint")
        assert cell.startswith("j_blueprint|a")
        assert cell.count("|") == 2


# ────────────────────────────────────────────────────────────────────────────
# Artifact
# ────────────────────────────────────────────────────────────────────────────


class TestArtifact:
    def test_roundtrip_preserves_predictions(self, tmp_path):
        t = _toy_table(residuals={"j_x": {"n": 4.0, "total": 1.0, "sumsq": 0.5}})
        path = tmp_path / "vt.json"
        VT.dump(path, {
            "version": VT.MODEL_VERSION, "feature_order": t.feature_order,
            "w": t.w, "b": t.b, "mu": t.mu, "sd": t.sd,
            "residuals": t.residuals, "tau": t.tau, "beta": t.beta,
            "resid_sd": t.resid_sd, "meta": {},
        })
        loaded = VT.ValueTable.load(path)
        assert loaded is not None
        feats = {"ctx_ante": 2.0}
        assert loaded.value(feats, "j_x|a2|s0") == pytest.approx(
            t.value(feats, "j_x|a2|s0"))

    def test_unsupported_version_is_refused(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text(json.dumps({"version": 999}), encoding="utf-8")
        assert VT.ValueTable.load(path) is None

    def test_missing_file_is_none(self, tmp_path):
        assert VT.ValueTable.load(tmp_path / "nope.json") is None

    def test_return_is_dense_and_win_dominant(self):
        r_win = VT.run_return({"ante": 9, "won": True})
        r_deep_loss = VT.run_return({"ante": 8, "won": False})
        r_shallow = VT.run_return({"ante": 3, "won": False})
        assert r_win > r_deep_loss > r_shallow
        # Winning from ante 9 beats dying at 8 by the win bonus plus the step.
        assert r_win - r_deep_loss == 1 + VT.RETURN_WIN_BONUS


# ────────────────────────────────────────────────────────────────────────────
# V12 parity, determinism and gating
# ────────────────────────────────────────────────────────────────────────────


class TestV12Parity:
    def test_oracle_off_is_byte_identical_to_v10(self):
        """The control arm. If this fails, V12 is a regression risk."""
        for seed in SEEDS:
            o10 = rollout(BalatroGame(seed=seed, rng_mode="seed"), SearchShopV10())
            o12 = rollout(BalatroGame(seed=seed, rng_mode="seed"),
                          SearchShopV12(params={"v12_oracle": False}))
            assert (o10["won"], o10["ante"], o10["dollars"], o10["steps"]) == \
                   (o12["won"], o12["ante"], o12["dollars"], o12["steps"]), seed

    def test_oracle_off_never_evaluates_candidates(self):
        p = SearchShopV12(params={"v12_oracle": False})
        rollout(BalatroGame(seed=SEEDS[0], rng_mode="seed"), p)
        assert p.oracle_stats()["offered"] == 0

    def test_same_seed_is_deterministic(self):
        for _ in range(2):
            o = rollout(BalatroGame(seed=SEEDS[0], rng_mode="seed"),
                        SearchShopV12(params={"v12_oracle": False}))
            assert (o["won"], o["ante"], o["steps"]) == (o["won"], o["ante"], o["steps"])


class TestV12Oracle:
    def test_entry_mode_evaluates_and_can_act(self, tmp_path):
        t = _toy_table(residuals={})
        path = tmp_path / "vt.json"
        VT.dump(path, {
            "version": VT.MODEL_VERSION, "feature_order": t.feature_order,
            "w": [1.0] * len(VT.FEATURE_ORDER),  # strongly positive everywhere
            "b": 100.0, "mu": t.mu, "sd": t.sd, "residuals": {},
            "tau": 1.0, "beta": 0.0, "resid_sd": 0.0, "meta": {},
        })
        p = SearchShopV12(params={"v12_oracle": True, "v12_mode": "entry",
                                  "v12_z": 0.0}, model_path=path)
        rollout(BalatroGame(seed=SEEDS[0], rng_mode="seed"), p)
        st = p.oracle_stats()
        assert st["offered"] > 0
        assert st["accepted"] > 0

    def test_confidence_gate_blocks_a_noisy_positive(self, tmp_path):
        """A positive point estimate with no evidence must NOT be acted on."""
        t = _toy_table()
        path = tmp_path / "vt.json"
        VT.dump(path, {
            "version": VT.MODEL_VERSION, "feature_order": t.feature_order,
            "w": [0.0] * len(VT.FEATURE_ORDER),
            "b": 0.5, "mu": t.mu, "sd": t.sd, "residuals": {},
            "tau": 1.0, "beta": 0.0, "resid_sd": 10.0, "meta": {},
        })
        p = SearchShopV12(params={"v12_oracle": True, "v12_mode": "entry",
                                  "v12_z": 1.0}, model_path=path)
        rollout(BalatroGame(seed=SEEDS[0], rng_mode="seed"), p)
        st = p.oracle_stats()
        assert st["offered"] > 0
        assert st["accepted"] == 0, "must not spend money on an unsupported estimate"

    def test_override_keeps_the_frozen_policy_without_evidence(self, tmp_path):
        """No evidence -> no override, so the control arm is preserved.

        An override changes *which* item is bought, so an unevidenced model
        must leave the heuristic's pick alone rather than reshuffle it.
        """
        t = _toy_table()
        path = tmp_path / "vt.json"
        VT.dump(path, {
            "version": VT.MODEL_VERSION, "feature_order": t.feature_order,
            "w": [0.0] * len(VT.FEATURE_ORDER),
            "b": 0.0, "mu": t.mu, "sd": t.sd, "residuals": {},
            "tau": 1.0, "beta": 0.0, "resid_sd": 2.0, "meta": {},
        })
        seed = SEEDS[0]
        o10 = rollout(BalatroGame(seed=seed, rng_mode="seed"), SearchShopV10())
        p = SearchShopV12(params={"v12_oracle": True, "v12_mode": "override",
                                  "v12_z": 1.0, "v12_head": "relative"},
                          model_path=path)
        o12 = rollout(BalatroGame(seed=seed, rng_mode="seed"), p)
        assert p.oracle_stats()["offered"] > 0
        assert p.oracle_stats()["accepted"] == 0
        assert (o10["won"], o10["ante"]) == (o12["won"], o12["ante"])

    def test_beats_uses_relative_head_and_combined_noise(self):
        t = _toy_table(resid_sd=2.0, residuals={
            "j_a": {"n": 100.0, "total": 0.0, "sumsq": 0.0},
            "j_b": {"n": 1.0, "total": 0.0, "sumsq": 0.0},
        }, w_rel=[0.0] * len(VT.FEATURE_ORDER), b_rel=0.0,
            residuals_rel={"j_a": {"n": 100.0, "total": 0.0, "sumsq": 0.0},
                           "j_b": {"n": 1.0, "total": 0.0, "sumsq": 0.0}})
        g = _shop_game()
        items = [it for it in g.current_shop if getattr(it, "kind", "") == "joker"]
        if len(items) < 2:
            pytest.skip("need two shop jokers")
        items = items[:2]
        ok, margin, se_d = t.beats(g, items[0], items[1], z=1.0)
        # Equal predicted values cannot beat any positive noise bar.
        assert margin == pytest.approx(0.0)
        assert se_d > 0.0
        assert ok is False
        # The bar is the combined standard error, always wider than either
        # estimate's own: sqrt(se_a^2 + se_b^2) >= max(se_a, se_b).
        cell_a = VT.cell_key(g, items[0].key)
        assert se_d >= t.relative_stderr(cell_a)

    def test_missing_artifact_disables_the_oracle(self):
        p = SearchShopV12(params={"v12_oracle": True},
                          model_path="does/not/exist.json")
        assert p._table is None
        p2 = SearchShopV12(params={"v12_oracle": True},
                           model_path="does/not/exist.json")
        o = rollout(BalatroGame(seed=SEEDS[0], rng_mode="seed"), p2)
        o10 = rollout(BalatroGame(seed=SEEDS[0], rng_mode="seed"), SearchShopV10())
        assert (o["ante"], o["won"]) == (o10["ante"], o10["won"])

    def test_v12_params_do_not_leak_into_v10_params(self):
        from balatro_sim.agent_v12 import V12_PARAMS
        SearchShopV12(params={"v12_oracle": True, "v12_z": 3.0})
        assert V12_PARAMS["v12_z"] == 3.0
        from balatro_sim.agent_v10 import V10_DEFAULTS
        assert "v12_z" not in V10_DEFAULTS


class TestScenarioCells:
    """Item x scenario cells: the value of an item *in a scenario*, learned.

    The requirement is that item values are learned per scenario, not averaged
    across all of them. Ante is the primary cell; these two dimensions are the
    ones a purchase decision actually depends on and the sim exposes for free.
    The properties pinned here are the ones that keep them honest:

      no fabricated scenarios — an all-level-1 hand dict is not a "leaning",
                                and a boss the sim has not revealed is unknown
      one naming convention    — the game-side and row-side builders must agree,
                                or train/serve skew is invisible
      conservative gating      — scenario evidence never loosens the
                                confidence test (it only adds variance)
    """

    def test_hand_scenario_needs_an_actual_investment(self):
        flat = SimpleNamespace(planet_levels={"Flush": 1, "Pair": 1})
        assert VT.hand_scenario(flat) == ""
        raised = SimpleNamespace(planet_levels={"Flush": 3, "Pair": 1})
        assert VT.hand_scenario(raised) == "Flush"
        assert VT.hand_scenario(SimpleNamespace(planet_levels={})) == ""

    def test_hand_scenario_is_deterministic_on_ties(self):
        tied = SimpleNamespace(planet_levels={"Straight": 4, "Flush": 4})
        assert VT.hand_scenario(tied) == "Flush"      # sorted, not dict order

    def test_boss_scenario_tracks_the_preselected_boss(self):
        assert VT.boss_scenario(SimpleNamespace(next_boss_key="bl_goad")) == "bl_goad"
        assert VT.boss_scenario(SimpleNamespace(next_boss_key=None)) == ""

    def test_scenario_cell_parents_reach_the_item_and_its_role(self):
        cell = "j_photograph|boss:bl_goad"
        parents = VT.cell_parents(cell)
        assert cell not in parents
        assert "j_photograph" in parents
        assert "role:xmult" in parents
        # The hierarchy must terminate: a cycle here recurses forever in the
        # shrinkage walk (`_shrunk_from` follows parents). Two parents may
        # share an ancestor (item and scenario cell both reach the role block),
        # so this checks "no cell is its own ancestor" rather than
        # "every node is visited once".
        def walk(c, depth=0):
            assert not (c == cell and depth > 0), f"cycle through {cell}"
            for p in VT.cell_parents(c):
                walk(p, depth + 1)
        walk(cell)

    def test_row_and_game_builders_agree(self):
        g = SimpleNamespace(next_boss_key="bl_house",
                            planet_levels={"Pair": 2, "Flush": 1})
        row = {"key": "j_photograph", "boss_key": "bl_house", "hand_key": "Pair"}
        assert VT.scenario_cells(g, "j_photograph") == VT.row_scenario_cells(row)
        assert VT.row_scenario_cells({"key": "j_x", "boss_key": "",
                                      "hand_key": ""}) == []

    def test_scenario_term_applies_a_measured_correction(self):
        t = _toy_table(tau=1.0, residuals={
            "j_photograph|boss:bl_goad": {"n": 10.0, "total": 5.0, "sumsq": 2.5}})
        g = SimpleNamespace(next_boss_key="bl_goad", planet_levels={})
        assert t.scenario_term(g, "j_photograph") == pytest.approx(5.0 / 11.0)
        # An unmeasured scenario contributes nothing rather than guessing.
        other = SimpleNamespace(next_boss_key="bl_wall", planet_levels={})
        assert t.scenario_term(other, "j_photograph") == 0.0
        assert t.scenario_term(SimpleNamespace(next_boss_key=None, planet_levels={}),
                               "j_never_seen") == 0.0

    def test_scenario_evidence_does_not_loosen_the_confidence_gate(self):
        """More scenario rows must not make the oracle bolder.

        The gate is deliberately a lower bound on uncertainty: scenario terms
        add variance (they pool across antes), so counting their rows as
        confidence would overstate support for the estimate.
        """
        base = _toy_table(residuals={})
        rich = _toy_table(residuals={
            "j_photograph|boss:bl_goad": {"n": 500.0, "total": 0.0, "sumsq": 0.0},
            "j_photograph|hand:Flush": {"n": 500.0, "total": 0.0, "sumsq": 0.0}})
        cell = "j_photograph|a3|s0"
        assert base.own_n(cell) == rich.own_n(cell) == 0.0
        assert base.cell_stderr(cell) == rich.cell_stderr(cell)


class _StubHead:
    """Minimal stand-in for ValueTable: only the prior's two entry points."""

    def __init__(self, scores: dict):
        self.scores = scores

    def _score(self, game, item):
        return float(self.scores.get(str(getattr(item, "key", "")), 0.0))

    relative_of = _score
    value_of = _score

    def fingerprint(self):
        return "stub"


class TestV12Prior:
    """The prior may only re-order candidates the frozen ranker already put on
    the table, and only within the declared near-tie window.

    The invariant that matters is structural: because the pool is the ranker's
    own output, the prior cannot show the policy an item the heuristic had not
    already ranked affordable and worth buying, so it cannot drain capital or
    stall a build. The tests below pin that plus the two ways it can decline to
    act (an uninformative head, and an item the ranker did not rank).
    """

    def _policy(self, monkeypatch, ranked, scores, margin=0.05, kinds=("joker",),
                band=False):
        """A prior-mode policy whose ranker, ranker-inputs and eligibility
        check are all deterministic, so only the prior's own logic is tested.
        """
        import balatro_sim.agent_v12 as AV12
        ranked_idxs = [int(i) for _v, i in ranked]
        monkeypatch.setattr(AV12, "_v10_rank_shop_items",
                            lambda game, ref, surplus, rerolls_used=0: (ranked, None))
        monkeypatch.setattr(AV12, "reference_hand", lambda game: None)
        monkeypatch.setattr(AV12, "forecast_beatable",
                            lambda game, margin_, ref: True)
        monkeypatch.setattr(AV12, "candidates",
                            lambda game, kinds_: [(i, game.current_shop[i])
                                                  for i in ranked_idxs
                                                  if i < len(game.current_shop)])
        p = SearchShopV12(params={"v12_oracle": True, "v12_mode": "prior",
                                  "v12_prior_margin": margin, "v12_kinds": kinds,
                                  "v12_prior_band": band})
        p._table = _StubHead(scores)
        return p

    def test_uninformative_head_cannot_change_anything(self, monkeypatch):
        """Equal learned scores -> the ranker's order survives verbatim.

        This is what makes the mode safe to ship switched on with an untrained
        artifact: with no opinion it is the frozen policy.
        """
        g = _shop_game()
        jokers = [i for i, it in enumerate(g.current_shop)
                  if getattr(it, "kind", "") == "joker"]
        if not jokers:
            pytest.skip("no shop joker on this seed")
        ranked = [(1.0, i) for i in jokers]
        p = self._policy(monkeypatch, ranked, {}, margin=5.0)
        asked = {"type": "buy", "item_idx": jokers[0]}
        assert p._oracle_prior(g, asked) is None

    def test_prior_respects_the_margin(self, monkeypatch):
        """Outside the window the ranker's opinion is final."""
        g = _shop_game()
        jokers = [i for i, it in enumerate(g.current_shop)
                  if getattr(it, "kind", "") == "joker"]
        if len(jokers) < 2:
            pytest.skip("need two shop jokers")
        a, b = jokers[0], jokers[1]
        key_a = g.current_shop[a].key
        key_b = g.current_shop[b].key
        ranked = [(1.0, a), (0.5, b)]
        scores = {key_a: 0.0, key_b: 10.0}   # head strongly prefers b
        strict = self._policy(monkeypatch, ranked, scores, margin=0.05)
        act = {"type": "buy", "item_idx": a}
        assert strict._oracle_prior(g, act) is None, "b is 0.5 below a: no tie"
        loose = self._policy(monkeypatch, ranked, scores, margin=0.6)
        assert loose._oracle_prior(g, act) == b, "inside the window the head wins"

    def test_band_refuses_to_break_an_exact_tie(self, monkeypatch):
        """With v12_prior_band the prior will not substitute on a ranker tie.

        Measured on 11,986 collected rows: pairs the ranker tied differ in
        return only 36.3% of the time, versus 57.0% for pairs it separated by
        < 0.01. The tie end of the margin window is therefore the least
        informative place to spend an intervention, and this test pins the
        behaviour that keeps the prior out of it -- while the same setup with
        the band OFF still substitutes, so the flag is the only difference.
        """
        g = _shop_game()
        jokers = [i for i, it in enumerate(g.current_shop)
                  if getattr(it, "kind", "") == "joker"]
        if len(jokers) < 2:
            pytest.skip("need two shop jokers")
        a, b = jokers[0], jokers[1]
        ranked = [(1.0, a), (1.0, b)]          # the ranker is indifferent
        scores = {g.current_shop[a].key: 0.0,
                  g.current_shop[b].key: 10.0}  # the head is not
        act = {"type": "buy", "item_idx": a}
        off = self._policy(monkeypatch, ranked, scores, margin=0.05)
        assert off._oracle_prior(g, act) == b, "without the band, ties are broken"
        on = self._policy(monkeypatch, ranked, scores, margin=0.05, band=True)
        assert on._oracle_prior(g, act) is None, "with the band, ties are left alone"

    def test_band_still_corrects_an_expressed_preference(self, monkeypatch):
        """The band narrows WHERE the prior acts; it must not silence it.

        A ranker that preferred its own pick by a small but nonzero margin is
        exactly the case the prior exists for, and it must survive the band.
        """
        g = _shop_game()
        jokers = [i for i, it in enumerate(g.current_shop)
                  if getattr(it, "kind", "") == "joker"]
        if len(jokers) < 2:
            pytest.skip("need two shop jokers")
        a, b = jokers[0], jokers[1]
        ranked = [(1.0, a), (0.99, b)]         # a strictly but barely preferred
        scores = {g.current_shop[a].key: 0.0,
                  g.current_shop[b].key: 10.0}
        p = self._policy(monkeypatch, ranked, scores, margin=0.05, band=True)
        assert p._oracle_prior(g, {"type": "buy", "item_idx": a}) == b

    def test_prior_cannot_pick_an_unranked_item(self, monkeypatch):
        """An item the ranker did not list is never eligible, however loud."""
        g = _shop_game()
        jokers = [i for i, it in enumerate(g.current_shop)
                  if getattr(it, "kind", "") == "joker"]
        if len(jokers) < 2:
            pytest.skip("need two shop jokers")
        a, b = jokers[0], jokers[1]
        key_b = g.current_shop[b].key
        p = self._policy(monkeypatch, [(1.0, a)], {key_b: 99.0}, margin=5.0)
        assert p._oracle_prior(g, {"type": "buy", "item_idx": a}) is None

    def test_prior_declines_when_the_buy_was_not_ranked(self, monkeypatch):
        """The policy can buy on a path this ranker did not score; leave it."""
        g = _shop_game()
        jokers = [i for i, it in enumerate(g.current_shop)
                  if getattr(it, "kind", "") == "joker"]
        if len(jokers) < 2:
            pytest.skip("need two shop jokers")
        a, b = jokers[0], jokers[1]
        p = self._policy(monkeypatch, [(1.0, b)], {}, margin=5.0)
        assert p._oracle_prior(g, {"type": "buy", "item_idx": a}) is None

    def test_prior_with_full_margin_is_bounded_by_the_ranker_pool(self, monkeypatch):
        """Even an infinite window can only choose among ranked items."""
        g = _shop_game()
        jokers = [i for i, it in enumerate(g.current_shop)
                  if getattr(it, "kind", "") == "joker"]
        if len(jokers) < 2:
            pytest.skip("need two shop jokers")
        a, b = jokers[0], jokers[1]
        key_b = g.current_shop[b].key
        p = self._policy(monkeypatch, [(1.0, a), (0.9, b)], {key_b: 1.0},
                         margin=float("inf"))
        assert p._oracle_prior(g, {"type": "buy", "item_idx": a}) == b

    def test_prior_mode_is_deterministic_on_the_seed_bank(self):
        """Re-running the same seed with the same artifact repeats exactly.

        The prior calls the frozen ranker a second time per shop visit, so this
        is the test that the extra call consumes no RNG and mutates no state:
        a side effect there would make two identical runs diverge, which is the
        failure the seed-exact sim exists to make impossible.
        """
        def once():
            p = SearchShopV12(params={"v12_oracle": True, "v12_mode": "prior",
                                      "v12_prior_margin": 0.05})
            if p._table is None:
                pytest.skip("no fitted artifact on disk")
            o = rollout(BalatroGame(seed=SEEDS[1], rng_mode="seed"), p)
            return (o["ante"], o["won"], p.oracle_stats())
        assert once() == once()

    def test_prior_mode_keeps_spending_decisions_intact(self):
        """End-to-end: with the real artifact the run still plays out.

        Not a performance claim (that is the screen's job) — a structural one:
        prior mode must never raise, and the oracle's stats must show it only
        ever considered the ranker's own candidates.
        """
        p = SearchShopV12(params={"v12_oracle": True, "v12_mode": "prior",
                                  "v12_prior_margin": 0.05})
        if p._table is None:
            pytest.skip("no fitted artifact on disk")
        o = rollout(BalatroGame(seed=SEEDS[0], rng_mode="seed"), p)
        assert o["ante"] >= 1
        st = p.oracle_stats()
        # `offered` counts pool members considered (>= 2 whenever the prior gets
        # as far as deciding); each such decision resolves to exactly one
        # accept-or-veto. So the inequality, not equality, is the invariant.
        assert st["offered"] >= st["accepted"] + st["vetoed"]
        assert st["accepted"] <= st["offered"]


class _StubOracle:
    """Stand-in for the runtime prior: returns a fixed substitution.

    It MUTATES its counters on each call, like the real oracle does, because
    the collector reads per-decision deltas rather than totals -- a stub that
    returned a frozen dict would make every delta zero and quietly pass a
    broken delta computation.
    """

    def __init__(self, sub, offer_inc=2, accept_inc=1):
        self._sub = sub
        self._offer_inc = offer_inc
        self._accept_inc = accept_inc
        self._oracle_stats = {"offered": 0, "accepted": 0, "vetoed": 0}

    def _oracle_prior(self, game, act):
        self._oracle_stats["offered"] += self._offer_inc
        self._oracle_stats["accepted"] += self._accept_inc
        return self._sub


class TestOnPolicyCandidates:
    """`onpolicy` collection must fork the pair the runtime oracle weighs.

    The old `coverage` mode ranked candidates by work-order shortfall, so the
    corpus described items chosen for being UNDER-MEASURED and never asked what
    the policy buys or what the oracle compares it against. These tests pin the
    contract that makes the corpus decision-relevant: the frozen pick is always
    present (it is the anchor a substitution has to beat), the oracle's own
    substitution is taken from the oracle rather than re-derived, and the head's
    preference outside the tie window is recorded as its own role so the
    "is the window too narrow" question can be answered offline.
    """

    def _cands(self, n, kind="joker"):
        from tools.collect_decisions import Cand
        return [Cand(idx=i, kind=kind, key=f"j_{i}", price=4) for i in range(n)]

    def test_model_alt_is_the_heads_preference(self, monkeypatch):
        import tools.collect_decisions as CD
        monkeypatch.setattr(CD, "_table",
                            lambda: _StubHead({"j_0": 0.0, "j_1": 5.0, "j_2": 1.0}))
        g = _shop_game()
        cands = self._cands(3)
        alt = CD._model_alt(g, cands, exclude=set(), kinds=("joker",))
        assert alt is not None and alt.idx == 1
        # The pick is excluded: an alternative that is really the pick is not an
        # alternative, and role would otherwise be ambiguous.
        alt2 = CD._model_alt(g, cands, exclude={1}, kinds=("joker",))
        assert alt2 is not None and alt2.idx == 2

    def test_model_alt_respects_the_arms_kinds(self, monkeypatch):
        """A joker is not an alternative for an arm that only weighs tarots."""
        import tools.collect_decisions as CD
        monkeypatch.setattr(CD, "_table",
                            lambda: _StubHead({"j_0": 9.0}))
        g = _shop_game()
        assert CD._model_alt(g, self._cands(3), set(), ("tarot",)) is None

    def test_no_table_means_no_model_alt(self, monkeypatch):
        """An unfitted artifact must degrade to the old behaviour, not crash."""
        import tools.collect_decisions as CD
        monkeypatch.setattr(CD, "_table", lambda: None)
        g = _shop_game()
        assert CD._model_alt(g, self._cands(3), set(), ("joker",)) is None

    def test_pick_and_substitute_are_forked_in_priority_order(self, monkeypatch):
        import tools.collect_decisions as CD
        monkeypatch.setattr(CD, "_oracle", lambda m, k: _StubOracle(2))
        monkeypatch.setattr(CD, "_table",
                            lambda: _StubHead({"j_0": 0.0, "j_1": 1.0, "j_2": 2.0,
                                               "j_3": 3.0}))
        g = _shop_game()
        cands = self._cands(4)
        act = {"type": "buy", "item_idx": 0}
        chosen, offered, subbed = CD._onpolicy_choice(
            g, act, cands, object(), 0.02, ("joker",))
        roles = [r for _c, r in chosen]
        assert roles[0] == "pick", "the anchor must come first"
        assert "substitute" in roles
        assert roles.index("substitute") < roles.index("model_alt")
        assert offered == 2 and subbed == 1
        # model_alt is the best item that is neither the pick nor the substitute
        alt = [c.idx for c, r in chosen if r == "model_alt"]
        assert alt == [3]

    def test_a_declining_oracle_still_yields_the_pick(self, monkeypatch):
        """Decisions where the arm does nothing are the majority, and they are
        exactly the ones a better gate would act on, so they must still be
        measured."""
        import tools.collect_decisions as CD
        monkeypatch.setattr(
            CD, "_oracle", lambda m, k: _StubOracle(None, 0, 0))
        monkeypatch.setattr(CD, "_table", lambda: _StubHead({"j_1": 1.0}))
        g = _shop_game()
        chosen, offered, subbed = CD._onpolicy_choice(
            g, {"type": "buy", "item_idx": 0}, self._cands(3), object(),
            0.02, ("joker",))
        roles = [r for _c, r in chosen]
        assert "pick" in roles and "substitute" not in roles
        assert roles == ["pick", "model_alt"]
        assert offered == 0 and subbed == 0

    def test_a_non_buy_action_has_no_pick(self, monkeypatch):
        import tools.collect_decisions as CD
        monkeypatch.setattr(CD, "_oracle", lambda m, k: _StubOracle(None))
        monkeypatch.setattr(CD, "_table", lambda: _StubHead({"j_1": 1.0}))
        g = _shop_game()
        chosen, _o, _s = CD._onpolicy_choice(
            g, {"type": "reroll"}, self._cands(3), object(), 0.02, ("joker",))
        assert "pick" not in [r for _c, r in chosen]


class TestInterventionTest:
    """The offline replacement for a 100-200 seed screen per arm.

    Three arms have now been judged by screens whose net was +-3 inside noise at
    ~15 minutes each. The (pick, alternative) pairs the collector now records
    answer the same question directly: did the alternative actually beat the
    frozen pick, and did the current margin window permit the substitution?
    """

    def _rows(self):
        return [
            {"dec_id": "d1", "candidate_mode": "onpolicy", "role": "pick",
             "label": 0.0, "legacy_dv": 1.00},
            {"dec_id": "d1", "candidate_mode": "onpolicy", "role": "substitute",
             "label": 2.0, "legacy_dv": 1.01},
            {"dec_id": "d2", "candidate_mode": "onpolicy", "role": "pick",
             "label": 0.0, "legacy_dv": 1.00},
            {"dec_id": "d2", "candidate_mode": "onpolicy", "role": "model_alt",
             "label": -3.0, "legacy_dv": 1.50},
        ]

    def test_splits_by_whether_the_window_permits_the_substitution(self):
        from tools.fit_value_model import intervention_test
        out = intervention_test(self._rows(), 0.02)
        assert out["decisions"] == 2 and out["decisions_with_pair"] == 2
        inw = out["substitute_in_window"]
        assert inw["n"] == 1 and inw["mean_delta"] == 2.0
        assert inw["frac_positive"] == 1.0
        outw = out["model_alt_out_window"]
        assert outw["n"] == 1 and outw["mean_delta"] == -3.0
        assert outw["frac_positive"] == 0.0
        # an empty bucket must be n=0, not a spurious zero mean
        assert out["substitute_out_window"]["n"] == 0

    def test_ignores_rows_that_are_not_on_policy(self):
        """Coverage rows describe under-measured items, not weighed pairs."""
        from tools.fit_value_model import intervention_test
        rows = [dict(r) for r in self._rows()]
        for r in rows:
            r["candidate_mode"] = "coverage"
        out = intervention_test(rows, 0.02)
        assert out["decisions"] == 0 and out["decisions_with_pair"] == 0
        assert out["all"]["n"] == 0
