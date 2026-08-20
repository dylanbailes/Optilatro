"""test_tag_spec.py — data-driven behavioral validation of the skip-blind Tag
layer against tools/tag_spec.json (the reference-doc §14 contract, generated
by tools/gen_tag_spec.py).

The static audit (tools/audit_tags_static.py) guarantees STRUCTURE: names,
counts, the 9 ante-2 gates, and that each tag's apply/consumption code matches
the doc. This file guarantees BEHAVIOR: every tag applies without error, the
ante gates hold at roll time, and the instant/shop/queue kinds behave. When a
row's expectation disagrees with the sim, the sim is wrong — fix the sim, not
the test. (Deep per-tag effect assertions live in test_tags.py.)
"""
from __future__ import annotations

import json
import pathlib

import pytest

from balatro_sim.game import BalatroGame
from balatro_sim.seed_rng import node_tag
from balatro_sim.tags import TAG_CATALOGUE, TAG_NAMES, apply_tag, roll_tag

ROOT = pathlib.Path(__file__).resolve().parents[3]
SPEC = json.load(open(ROOT / "tools" / "tag_spec.json", encoding="utf-8"))
TAGS = SPEC["tags"]

VALID_KINDS = {"instant", "shop", "queue"}


def _eligible_pool(game: BalatroGame, ante: int) -> list[str]:
    """The tag pool roll_tag(ante) would draw from (captured without
    consuming the pick)."""
    captured: list[list[str]] = []
    game.ante = ante
    game.rng.node(node_tag(ante)).choices = (
        lambda seq, weights, k: (captured.append(list(seq)), seq[0])[1])
    roll_tag(game)
    return captured[0] if captured else []


# ── Spec vs sim tables (structure, data-driven) ─────────────────────────────

@pytest.mark.parametrize("key", sorted(TAGS), ids=lambda k: k)
def test_spec_matches_sim_tables(key):
    entry = TAGS[key]
    assert key in TAG_CATALOGUE, f"{key} missing from TAG_CATALOGUE"
    sim_name, sim_ante, sim_kind = TAG_CATALOGUE[key]
    assert sim_name == entry["name"], \
        f"{key}: sim {sim_name!r} != doc {entry['name']!r}"
    assert sim_ante == entry["ante"], \
        f"{key}: sim ante {sim_ante} != spec {entry['ante']}"
    assert sim_kind == entry["kind"], \
        f"{key}: sim kind {sim_kind} != spec {entry['kind']}"
    assert sim_kind in VALID_KINDS
    assert TAG_NAMES[key] == entry["name"]


def test_spec_counts():
    assert len(TAGS) == 24
    assert len(SPEC["gated"]) == 9
    assert len(SPEC["packs"]) == 5
    kinds = {e["kind"] for e in TAGS.values()}
    assert kinds == VALID_KINDS


# ── Every tag applies without error (behavior, data-driven) ─────────────────

def _snapshot(g: BalatroGame) -> tuple:
    return (g.dollars, list(g.pending_packs), g.double_tag_active,
            g.hand_size_bonus_next_round, dict(g.planet_levels),
            len(g.jokers))


@pytest.mark.parametrize("key", sorted(TAGS), ids=lambda k: k)
def test_every_tag_applies(key):
    g = BalatroGame(seed=7, rng_mode="seed")
    kind = TAGS[key]["kind"]
    if kind == "instant":
        # Run-counter tags pay $0 on a fresh game (wiki: "Will give $0") —
        # seed the counters so the payment is real.
        if key == "t_handy":
            g.run_hands_played = 7
        elif key == "t_speed":
            g.skipped_blinds = 3
        elif key == "t_garbage":
            g.run_unused_discards = 5
        # Instant tags must mutate something real (money / pack queue / planet
        # level / hand-size / jokers). A before/after snapshot — not a
        # one-sided probe — so a no-op apply_tag fails this test.
        before = _snapshot(g)
        apply_tag(g, key)                    # must not raise
        assert _snapshot(g) != before, f"instant tag {key} had no effect"
    else:
        apply_tag(g, key)                    # must not raise
        # shop/queue tags set exactly one pending modifier.
        pending = {
            "t_uncommon": g.pending_free_rarity == "Uncommon",
            "t_rare": g.pending_free_rarity == "Rare",
            "t_foil": g.pending_free_edition == "Foil",
            "t_holographic": g.pending_free_edition == "Holographic",
            "t_polychrome": g.pending_free_edition == "Polychrome",
            "t_negative": g.pending_free_edition == "Negative",
            "t_coupon": g.pending_coupon,
            "t_d6": g.pending_reroll_free,
            "t_voucher": g.pending_voucher,
            "t_investment": g.investment_pending,
            "t_boss": g.boss_reroll_pending,
            "t_juggle": g.hand_size_bonus_next_round == 3,
            "t_double": g.double_tag_active,
        }
        assert pending.get(key, False), f"{key} did not set its pending modifier"


# ── Ante gates (behavior, data-driven) ──────────────────────────────────────

@pytest.mark.parametrize("key", SPEC["gated"], ids=lambda k: k)
def test_gated_tag_never_rolls_at_ante1(key):
    g = BalatroGame(seed=11)
    assert key not in _eligible_pool(g, 1), \
        f"{key} offered at ante 1 (should be gated to ante 2+)"


@pytest.mark.parametrize("key", SPEC["gated"], ids=lambda k: k)
def test_gated_tag_rolls_at_ante2(key):
    g = BalatroGame(seed=11)
    assert key in _eligible_pool(g, 2), \
        f"{key} not offered at ante 2"


@pytest.mark.parametrize("key", [k for k in TAGS if k not in SPEC["gated"]],
                         ids=lambda k: k)
def test_ungated_tag_rolls_at_ante1(key):
    g = BalatroGame(seed=11)
    assert key in _eligible_pool(g, 1), f"{key} missing from the ante-1 pool"


def test_boss_blind_offers_no_tag():
    g = BalatroGame(seed=11)
    g.current_blind = type(g.current_blind)(  # a Boss blind
        name="Boss", kind="Boss", chips_target=1000, is_boss=True,
        boss_key="bl_goad")
    assert roll_tag(g) is None
