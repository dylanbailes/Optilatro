"""Tests for balatro_sim/catalogue.py — the spec-derived source of truth.

The catalogue replaces four hand-maintained role taxonomies. These tests pin
the properties that make that safe:

  * completeness  — every item in the generated spec files is present, and
                    nothing extra (drift between spec and code fails)
  * derivation    — roles/flags follow the documented spec-type and
                    effect-phrase rules, not a hand-written set
  * stability     — the fingerprint is content-derived and reproducible
  * encoding      — the model's item feature vector is complete and finite
  * gate          — catalogue.py itself passes the magic-number audit
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import pytest

from balatro_sim import catalogue as C

ROOT = Path(__file__).resolve().parents[3]
SPECS = ROOT / "tools"

needs_specs = pytest.mark.skipif(
    not (SPECS / "joker_spec.json").is_file(),
    reason="generated spec files are not present",
)


def _spec(name: str) -> dict:
    return json.loads((SPECS / name).read_text(encoding="utf-8"))


@needs_specs
class TestCompleteness:
    def test_every_joker_present(self):
        spec = _spec("joker_spec.json")
        assert set(spec) == set(C.keys("joker"))

    def test_every_consumable_present(self):
        spec = _spec("consumable_spec.json")
        expected = set()
        for group in ("tarots", "spectrals", "planets", "vouchers"):
            expected |= set(spec[group])
        got = set(C.keys("tarot")) | set(C.keys("spectral")) \
            | set(C.keys("planet")) | set(C.keys("voucher"))
        assert got == expected

    def test_every_boss_and_tag_present(self):
        assert set(_spec("boss_spec.json")["bosses"]) == set(C.keys("boss"))
        assert set(_spec("tag_spec.json")["tags"]) == set(C.keys("tag"))

    def test_packs_come_from_the_sim(self):
        from balatro_sim.shop import BOOSTER_CATALOGUE
        assert set(BOOSTER_CATALOGUE) == set(C.keys("pack"))

    def test_no_key_is_two_kinds(self):
        """A key appearing under two kinds would silently shadow in dicts."""
        kinds: dict[str, str] = {}
        for key, kind in C.coverage_cells():
            assert key not in kinds, f"{key} in both {kinds.get(key)} and {kind}"
            kinds[key] = kind

    def test_counts_are_spec_consistent(self):
        s = C.summary()
        assert s["total"] == sum(s["by_kind"].values())
        assert s["by_kind"]["joker"] == len(_spec("joker_spec.json"))

    def test_fingerprint_is_content_derived_and_stable(self):
        fp = C.fingerprint()
        assert len(fp) == 16 and int(fp, 16) >= 0
        C.load(force=True)
        assert C.fingerprint() == fp, "fingerprint must not depend on call order"


@needs_specs
class TestDerivation:
    TYPE_TO_ROLE = {
        "Chips": {"chips"}, "+Mult": {"flat_mult"}, "xMult": {"xmult"},
        "Economy": {"econ"}, "Retrigger": {"retrigger"},
        "Chips+Mult": {"chips", "flat_mult"}, "Effect": {"other"},
    }

    def test_roles_follow_declared_spec_type(self):
        spec = _spec("joker_spec.json")
        for key, row in spec.items():
            want = self.TYPE_TO_ROLE[row["type"]]
            assert want.issubset(set(C.item(key).roles)), (key, row["type"])

    def test_cost_and_rarity_come_from_the_shop_catalogue(self):
        from balatro_sim.shop import JOKER_CATALOGUE
        for key, meta in JOKER_CATALOGUE.items():
            it = C.item(key)
            assert it.cost == meta["price"], key
            assert it.rarity == meta["rarity"], key

    def test_scaling_is_parsed_from_the_effect_string(self):
        # Documented phrase rules. These are Balatro's own wordings, so a
        # change in the generated spec must show up here.
        for key in ("j_green_joker", "j_runner", "j_constellation",
                    "j_hologram", "j_ride_the_bus", "j_obelisk"):
            assert C.item(key).scaling, f"{key} should parse as scaling"
        for key in ("j_joker", "j_blueprint", "j_mime"):
            assert not C.item(key).scaling, f"{key} must not parse as scaling"

    def test_planets_level_real_hand_types(self):
        from balatro_sim.agent_v9 import HAND_TYPES
        mapping = C.hand_types_leveled_by_planets()
        assert len(mapping) == len(C.keys("planet"))
        for planet, hand in mapping.items():
            assert hand in HAND_TYPES, (planet, hand)

    def test_xmult_flag_agrees_with_role(self):
        for key in C.keys("joker"):
            it = C.item(key)
            if "xmult" in it.roles:
                assert it.flags["xmult"] == 1.0, key

    def test_legacy_taxonomies_resolve_to_real_keys(self):
        """The curated sets must not name keys the spec doesn't know.

        This check found two real instances of drift on first run:
        ``tools/portfolio.py`` CHIPS_JOKERS lists ``j_square_joker`` and
        ``j_stone_joker``, which are *aliases* — the canonical spec keys are
        ``j_square``/``j_stone``. A policy matching on the alias while the
        shop sells the canonical key silently mis-scores the joker. So the
        hard requirement is: after alias normalisation, every legacy key must
        exist in the catalogue.
        """
        sys.path.insert(0, str(ROOT))
        try:
            from tools import portfolio
        except Exception:  # pragma: no cover — tools/ not importable
            pytest.skip("tools.portfolio unavailable")
        normalize = getattr(portfolio, "normalize_joker_key", lambda k: k)
        for name in ("CHIPS_JOKERS", "FLAT_MULT_JOKERS", "XMULT_JOKERS",
                     "SCALING_JOKERS", "ECON_JOKERS", "RETRIGGER_JOKERS"):
            legacy = {normalize(k) for k in getattr(portfolio, name)}
            phantom = {k for k in legacy if C.item(k) is None}
            assert not phantom, f"{name} names unknown keys: {sorted(phantom)[:5]}"

    def test_declared_aliases_resolve_into_the_catalogue(self):
        sys.path.insert(0, str(ROOT))
        try:
            from tools.portfolio import ALIAS_TO_CANONICAL
        except Exception:  # pragma: no cover
            pytest.skip("tools.portfolio unavailable")
        for alias, canonical in ALIAS_TO_CANONICAL.items():
            if canonical.startswith("j_"):
                assert C.item(canonical) is not None, (alias, canonical)

    def test_curated_sets_disagree_with_the_spec_where_expected(self):
        """Document the known curated-vs-derived disagreement.

        ``j_business`` is listed as BOTH an economy joker and a dead economy
        joker in agent_v10 — proof the hand-maintained copies drifted. The
        catalogue gives it exactly one derived role.
        """
        from balatro_sim.agent_v10 import DEAD_ECONOMY_JOKERS, ECON_JOKERS
        assert "j_business" in ECON_JOKERS and \
            "j_business" in DEAD_ECONOMY_JOKERS, \
            "drift was repaired upstream; update this test"
        it = C.item("j_business")
        assert it.kind == "joker"
        assert it.rarity in C.RARITIES


@needs_specs
class TestFeatureEncoding:
    def test_vector_shape_is_fixed(self):
        f = C.item_features("j_blueprint")
        assert set(f) == set(C.FEATURE_NAMES)
        assert all(isinstance(v, float) and math.isfinite(v) for v in f.values())

    def test_identity_blocks_are_one_hot(self):
        f = C.item_features("j_blueprint")
        assert f["kind_joker"] == 1.0
        assert sum(f[f"role_{r}"] for r in C.ROLES) == 1.0
        assert sum(f[f"timing_{t}"] for t in C.TIMINGS) <= 1.0
        assert sum(f[f"rarity_{r}"] for r in C.RARITIES) == 1.0

    def test_unknown_item_is_marked_not_silently_zero(self):
        f = C.item_features("j_does_not_exist")
        assert f["cost_frac"] == -1.0
        assert sum(v for k, v in f.items() if k != "cost_frac") == 0.0

    def test_live_state_can_be_merged_without_clobbering_spec(self):
        f = C.item_features("j_blueprint", present={"price_frac": 0.25})
        assert f["price_frac"] == 0.25
        assert f["kind_joker"] == 1.0

    def test_costs_are_normalised_by_the_observed_maximum(self):
        cmax = C.cost_max()
        assert cmax > 0
        assert C.item_features("j_blueprint")["cost_frac"] <= 1.0


class TestMagicNumberGate:
    def test_catalogue_has_no_unledgered_constants(self):
        sys.path.insert(0, str(ROOT))
        try:
            from tools.audit_magic_numbers import (
                forbidden_imports, load_ledger, module_constants)
        except Exception:  # pragma: no cover
            pytest.skip("audit tool unavailable")
        path = Path(C.__file__)
        rel = "vendor/balatro-rl/balatro_sim/catalogue.py"
        known = load_ledger()["constants"]
        named, _in_func = module_constants(path)
        unledgered = []
        for c in named:
            if (f"{rel}::{c['name']}@L{c['line']}" not in known
                    and f"{rel}::{c['name']}" not in known):
                unledgered.append(c["name"])
        assert not unledgered, f"unledgered constants: {unledgered}"
        assert not forbidden_imports(path)
