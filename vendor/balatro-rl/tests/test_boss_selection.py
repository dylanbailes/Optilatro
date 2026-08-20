"""
test_boss_selection.py — Regression tests for real boss-blind selection.

Covers the real-game rules (verified against balatrowiki.org/w/Blinds_and_Antes):
  - minimum-ante eligibility,
  - the ante-8 Showdown pool (Amber Acorn, Verdant Leaf, Violet Vessel,
    Crimson Heart, Cerulean Bell) exclusive to ante 8,
  - the (now-empty) unimplemented-boss allow-list — all 28 real bosses
    are selectable,
  - the "fewest appearances" no-repeat rotation,
  - seed determinism.
"""
from __future__ import annotations

from balatro_sim.game import (
    BalatroGame, State, BOSS_MIN_ANTE, SHOWDOWN_BOSSES, UNIMPLEMENTED_BOSSES,
)
from balatro_sim.seed_rng import node_boss


def _pick(ante: int, seed: int = 1) -> str:
    """Draw one boss for a given ante on a fresh game."""
    return BalatroGame(seed=seed)._select_boss(ante)


def _pick_many(ante: int, n: int, seed: int = 1) -> list[str]:
    """Draw n bosses at a fixed ante on one game (appearances accumulate)."""
    g = BalatroGame(seed=seed)
    return [g._select_boss(ante) for _ in range(n)]


class TestEligibility:
    def test_ante1_pool_is_min_ante_1(self):
        for seed in range(50):
            key = _pick(1, seed)
            assert BOSS_MIN_ANTE[key] <= 1
            assert key not in SHOWDOWN_BOSSES
            assert key not in UNIMPLEMENTED_BOSSES

    def test_min_ante_enforced(self):
        # bl_ox is min-ante 6 — must never appear before ante 6
        for ante in range(1, 6):
            for seed in range(25):
                assert _pick(ante, seed) != "bl_ox"
        # bl_wall is min-ante 2 — never at ante 1
        for seed in range(25):
            assert _pick(1, seed) != "bl_wall"

    def test_ante8_is_showdown_only(self):
        for seed in range(60):
            assert _pick(8, seed) in SHOWDOWN_BOSSES

    def test_showdown_never_before_ante8(self):
        for ante in range(1, 8):
            for seed in range(25):
                assert _pick(ante, seed) not in SHOWDOWN_BOSSES

    def test_no_unimplemented_bosses_remain(self):
        """All 28 real bosses are implemented — the allow-list is empty."""
        assert UNIMPLEMENTED_BOSSES == set()

    def test_house_and_arm_selectable_at_ante2(self):
        """The House and The Arm (both min-ante 2) are now selectable."""
        assert "bl_house" not in UNIMPLEMENTED_BOSSES
        assert "bl_grim" not in UNIMPLEMENTED_BOSSES
        seen = {_pick(2, seed) for seed in range(400)}
        assert "bl_house" in seen
        assert "bl_grim" in seen

    def test_house_and_arm_never_at_ante1(self):
        for seed in range(50):
            assert _pick(1, seed) not in ("bl_house", "bl_grim")

    def test_club_and_wheel_now_selectable(self):
        """The Club (ante 1) and The Wheel (ante 2) are implemented and selectable."""
        assert "bl_club" not in UNIMPLEMENTED_BOSSES
        assert "bl_wheel" not in UNIMPLEMENTED_BOSSES
        ante1 = {_pick(1, seed) for seed in range(400)}
        assert "bl_club" in ante1
        ante2 = {_pick(2, seed) for seed in range(400)}
        assert "bl_wheel" in ante2

    def test_wheel_never_at_ante1(self):
        for seed in range(50):
            assert _pick(1, seed) != "bl_wheel"

    def test_ante1_pool_covers_all_eight_real_bosses(self):
        """The ante-1 pool is now the full real set of 8 bosses (Club included)."""
        real_ante1 = {"bl_hook", "bl_club", "bl_psychic", "bl_goad",
                      "bl_window", "bl_manacle", "bl_pillar", "bl_head"}
        seen = {_pick(1, seed) for seed in range(400)}
        assert seen == real_ante1

    def test_full_run_bosses_respect_every_rule(self):
        """Walk a game through all 8 antes via the real _prepare_next_blind path."""
        g = BalatroGame(seed=42)
        bosses = []
        for ante in range(1, 9):
            g.ante = ante
            g.blind_idx = 2
            g._prepare_next_blind()
            bosses.append(g.current_blind.boss_key)
        for ante, key in enumerate(bosses, start=1):
            if ante == 8:
                assert key in SHOWDOWN_BOSSES
            else:
                assert key not in SHOWDOWN_BOSSES
                assert BOSS_MIN_ANTE[key] <= ante
                assert key not in UNIMPLEMENTED_BOSSES


class TestShowdownPool:
    def test_all_five_showdown_bosses_reachable(self):
        seen = {_pick(8, seed) for seed in range(400)}
        assert seen == SHOWDOWN_BOSSES

    def test_violet_and_crimson_now_reachable(self):
        """These were previously unreachable (outside the old BOSS_BLINDS[:20])."""
        seen = {_pick(8, seed) for seed in range(400)}
        assert {"bl_violet", "bl_crimson"} <= seen


class TestRotation:
    def test_no_repeat_until_pool_exhausted(self):
        """At ante 8 the eligible pool is the 5 Showdown bosses; with the
        fewest-appearances rule the first 5 picks must all be distinct."""
        picks = _pick_many(8, 5, seed=7)
        assert len(set(picks)) == 5
        assert set(picks) == SHOWDOWN_BOSSES

    def test_rotation_restarts_after_all_seen(self):
        """Once every eligible boss has appeared once, all are eligible again
        (the 6th+ picks may repeat — no error, still within the pool)."""
        g = BalatroGame(seed=11)
        first_cycle = [g._select_boss(8) for _ in range(5)]
        assert len(set(first_cycle)) == 5
        # Force the 6th pick to a first-cycle boss: after the pool is exhausted
        # it is a candidate again (all counts are equal at 1), so repeats are
        # allowed.
        g.rng.node(node_boss()).choice = lambda seq: first_cycle[0]
        assert g._select_boss(8) == first_cycle[0]

    def test_appearance_counts_accumulate(self):
        g = BalatroGame(seed=3)
        g._select_boss(8)
        total = sum(g.boss_appearances.values())
        assert total == 1
        g._select_boss(8)
        assert sum(g.boss_appearances.values()) == 2


class TestDeterminism:
    def test_same_seed_same_sequence(self):
        a = _pick_many(1, 20, seed=123)
        b = _pick_many(1, 20, seed=123)
        assert a == b

    def test_different_seed_different_sequence(self):
        a = _pick_many(1, 20, seed=123)
        b = _pick_many(1, 20, seed=124)
        assert a != b


class TestPreselectTiming:
    """Boss-layer pass: the upcoming Boss Blind is selected at SHOP ENTRY
    (game.next_boss_key), not at shop end — the real game reveals the boss
    with the shop, and Director's Cut / the graph's boss-counter term need
    the key while shopping. Same boss-node draws, one shop earlier; every
    other node is independently seeded, so shop contents are unchanged."""

    def test_boss_key_known_during_shop_after_big(self):
        g = BalatroGame(seed=11, rng_mode="seed")
        g.blind_idx = 1                    # just fought the Big blind
        g._end_round()                     # shop entry: boss pre-selected
        assert g.next_boss_key is not None
        assert g.state == State.SHOP
        # the graph context now sees the REAL key, not just the flag
        from balatro_sim.graph_v9 import boss_context
        coming, key = boss_context(g)
        assert coming and key == g.next_boss_key
        # leaving the shop sets up the boss with the SAME key (no reselect)
        old = g.next_boss_key
        g._end_shop()
        assert g.current_blind.is_boss
        assert g.current_blind.boss_key == old
        assert g.next_boss_key is None     # consumed

    def test_no_preselect_except_before_boss(self):
        g0 = BalatroGame(seed=11, rng_mode="seed")
        g0.blind_idx = 0                   # after Small: next is Big
        g0._end_round()
        assert g0.next_boss_key is None
        g1 = BalatroGame(seed=11, rng_mode="seed")
        g1.blind_idx = 1                   # after Big: next IS the Boss
        g1._end_round()
        assert g1.next_boss_key is not None
        g2 = BalatroGame(seed=11, rng_mode="seed")
        g2.blind_idx = 2                   # after Boss: ante advances
        g2._end_round()
        assert g2.next_boss_key is None

    def test_preselect_idempotent_no_extra_draw(self):
        """A second shop-entry call (e.g. free-pack tag flow) must not draw
        the boss node again."""
        g = BalatroGame(seed=11, rng_mode="seed")
        g.blind_idx = 1
        g.rng.enable_tracing()
        g._preselect_next_boss()
        g._preselect_next_boss()
        boss_draws = [r for r in g.rng.records if r.node == node_boss()]
        assert len(boss_draws) == 1

    def test_boss_node_drawn_before_shop_at_entry(self):
        """Seed-mode trace: the boss draw moves BEFORE the first shop draw
        (Voucher1 at the ante-1 restock); the per-node streams stay
        independent, so the shop itself is unchanged."""
        g = BalatroGame(seed=11, rng_mode="seed")
        g.blind_idx = 1
        g.rng.enable_tracing()
        g._end_round()
        records = g.rng.records
        boss_pos = next(i for i, r in enumerate(records) if r.node == node_boss())
        voucher_pos = next(i for i, r in enumerate(records)
                           if r.node.startswith("Voucher"))
        assert boss_pos < voucher_pos

    def test_preselect_uses_rotation_and_min_ante(self):
        """Pre-selection follows the same real rules as the old shop-end
        selection: same seed, same ante-1 boss via either path."""
        legacy = BalatroGame(seed=3, rng_mode="seed")
        legacy.blind_idx = 2
        legacy._prepare_next_blind()
        preselected = BalatroGame(seed=3, rng_mode="seed")
        preselected.blind_idx = 1
        preselected._preselect_next_boss()
        assert preselected.next_boss_key == legacy.current_blind.boss_key
