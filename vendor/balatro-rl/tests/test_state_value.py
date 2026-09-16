"""Tests for the V13 portfolio-aware state encoder.

The failure this file exists to prevent is *silent column loss*. The encoder
returns a dict of named features and the collector freezes an ordered layout from
`layout_keys`; anything the encoder produces that the layout does not contain is
dropped by the collector with a counter and no error. That happened for real: the
voucher pool declared no reductions in the layout while `_pool` emitted `max`
unconditionally, so 46 `vo_max_*` columns were dropped for every state owning a
voucher -- 463,450 feature instances over one 500-seed collection, invisibly.

The properties pinned here:

  layout_complete  -- every name the encoder can produce is in `layout_keys`,
                      for the prefixes that exist and for the item-independent
                      aggregates alike. Derived names, so adding a pool or a
                      reduction cannot quietly reintroduce the gap.
  catalogue_fixed  -- the pooled vocabulary does not depend on data, which is
                      what lets the layout be frozen before collection starts.
  purity           -- encoding mutates no game state and consumes no RNG, so
                      instrumentation can never move the seed-exact stream.
  projection       -- `encode` reads a missing name as 0 rather than raising,
                      which is the contract the fitter relies on when it unions
                      layouts written by different encoder versions.
"""
from __future__ import annotations

from copy import deepcopy

from balatro_sim.game import BalatroGame, State
from balatro_sim.agent_v11 import SearchShopV11
from balatro_sim import catalogue as CAT
from balatro_sim import state_value as SV


def _play(seed: int, max_steps: int = 4000):
    """Play one run, yielding the game at each state the encoder would see."""
    game = BalatroGame(seed=seed, rng_mode="seed")
    policy = SearchShopV11()
    steps = 0
    while game.state != State.GAME_OVER and steps < max_steps:
        steps += 1
        yield game
        try:
            game.step(policy.decide(game))
        except Exception:
            return


def test_pooled_names_cover_every_reduction_the_pool_emits():
    """The direct form of the invariant, per prefix.

    Built from synthetic entity vectors rather than a game, so it pins the
    naming contract itself instead of whatever one seed happened to exercise.
    The keys must come from the catalogue: the pooled vocabulary is spec-derived
    on purpose, since a vocabulary that depended on observed data could not be
    frozen before collection.
    """
    k0, k1 = CAT.FEATURE_NAMES[0], CAT.FEATURE_NAMES[1]
    vecs = [{k0: 1.0, k1: 0.0}, {k0: 0.0, k1: 2.0}]
    for prefix in (SV._JOKER_PREFIX, SV._CONSUMABLE_PREFIX,
                   SV._VOUCHER_PREFIX):
        out: dict = {}
        SV._pool(vecs, prefix, out)
        declared = set(SV.pooled_names(prefix))
        missing = sorted(set(out) - declared)
        assert not missing, (
            f"prefix {prefix!r} emits {missing} which pooled_names does not "
            f"declare; the layout would drop these columns silently")
        assert f"{prefix}n" in out


def test_voucher_pool_declares_max_regression():
    """The exact columns the shipped bug lost.

    Named rather than generic so a future edit that re-declares the voucher pool
    with no reductions fails here with the reason instead of in a collection log
    hours later.
    """
    declared = set(SV.pooled_names(SV._VOUCHER_PREFIX))
    assert f"{SV._VOUCHER_PREFIX}max_cost_frac" in declared or any(
        n.startswith(f"{SV._VOUCHER_PREFIX}max_") for n in declared)
    assert f"{SV._VOUCHER_PREFIX}n" in declared


def test_layout_covers_every_encoded_name_end_to_end():
    """Every key `state_features` produces must survive `layout_keys`.

    This is the collector's exact contract: the layout is frozen once from a
    probe, then every later state is projected onto it. A key outside the layout
    is a dropped feature, so the assertion is over the whole run, not one state.
    """
    probe: dict = {}
    for game in _play(48800):
        probe.update(SV.state_features(game))
    assert probe, "encoder produced nothing"
    hands = sorted(k.split("hlvl_", 1)[1] for k in probe
                   if k.startswith("hlvl_"))
    layout = set(SV.layout_keys(probe, hands))
    missing = sorted(set(probe) - layout)
    assert not missing, f"encoder emits {missing[:8]} outside the layout"


def test_pooled_vocabulary_is_data_independent():
    """Pooled names come from the spec, so the layout can be frozen first.

    `item_live_features` adds keys conditionally (only planets get
    `own_hand_level`), which is why it is deliberately excluded from the pooled
    vector: a vocabulary that depends on which items a run owns cannot be frozen
    before that run happens.
    """
    declared = set(SV.pooled_names(SV._JOKER_PREFIX))
    for name in CAT.FEATURE_NAMES:
        assert f"{SV._JOKER_PREFIX}sum_{name}" in declared
        assert f"{SV._JOKER_PREFIX}mean_{name}" in declared
    # Every declared name must be catalogue-derived, i.e. reachable without
    # observing a single game.
    extra = {n for n in declared
             if not n[len(SV._JOKER_PREFIX):].startswith(("sum_", "max_",
                                                         "mean_"))
             and n != f"{SV._JOKER_PREFIX}n"}
    assert not extra, f"undeclared vocabulary {extra}"


def test_encoding_is_pure_and_rng_free():
    """Instrumentation must not move the seed-exact stream.

    The state-value model is scored inside a decision that also has to be
    byte-reproducible across seeds, so a read that consumed RNG would break
    seed-exactness for every arm -- the same class of failure the parity test
    guards on the policy side.
    """
    game = next(iter(_play(48801)))
    before = _rng_fingerprint(game)
    snap = deepcopy(game)
    first = SV.state_features(game)
    second = SV.state_features(game)
    assert first == second
    assert _rng_fingerprint(game) == before
    assert _same_state(game, snap)


def test_encode_projects_missing_names_to_zero():
    """A name outside the layout reads 0, which is what layout-union relies on.

    Rows written before an encoder extension have no value for the new columns;
    the fitter unions layouts and expects the projection to be well-defined
    rather than an error.
    """
    feats = {"a": 1.5, "b": 2.0}
    assert SV.encode(feats, ["a", "b"]) == [1.5, 2.0]
    assert SV.encode(feats, ["a", "zz", "b"]) == [1.5, 0.0, 2.0]
    assert SV.encode({}, ["a", "b"]) == [0.0, 0.0]


def test_encode_survives_nan_and_inf():
    """Non-finite values must not reach the model as NaN.

    A single NaN makes a gradient-boosted model return NaN for every prediction
    it feeds, which would look like a policy regression rather than an encoding
    bug.
    """
    out = SV.encode({"a": float("nan"), "b": float("inf"),
                     "c": float("-inf")}, ["a", "b", "c"])
    assert out == [0.0, 0.0, 0.0]


# ── helpers ───────────────────────────────────────────────────────────────────

def _rng_fingerprint(game):
    """A stable digest of whatever RNG state the game carries."""
    src = getattr(game, "rng", None)
    if src is None:
        return None
    parts = []
    for name in sorted(vars(src)):
        if name.startswith("_"):
            continue
        val = getattr(src, name)
        if isinstance(val, (int, float, str, bool, type(None))):
            parts.append((name, val))
        elif isinstance(val, (list, tuple)):
            parts.append((name, tuple(str(v) for v in val)))
    return tuple(parts)


def _same_state(a, b) -> bool:
    """Compare the fields the encoder reads, ignoring RNG internals."""
    for attr in ("dollars", "ante", "blind_idx", "hand", "jokers",
                 "consumable_hand", "full_deck", "current_shop",
                 "planet_levels", "state"):
        if getattr(a, attr, None) != getattr(b, attr, None):
            return False
    return True
