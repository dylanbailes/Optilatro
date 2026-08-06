"""test_seed_rng.py — Two-mode RNG port (balatro-seed per-node LuaRandom).

The algorithm tests are ported from balatro-seed's own Rust unit tests
(vendor/balatro-rs/balatro-seed/src/{rng.rs, instance.rs, node_id.rs}), which
are verified byte-accurate against the real game. The two-mode tests pin that:

  - generic mode reproduces the legacy single-stream behavior exactly, and
  - seed mode is deterministic per seed (per-node LuaRandom, Balatro's real
    scheme), and diverges from generic.
"""
from __future__ import annotations

import random

from balatro_sim.seed_rng import (
    pseudohash, round13, LuaRandom,
    make_source, GenericSource, SeedSource,
    node_boss, node_cdt, node_rarity, node_edition, node_joker,
    node_tarot, node_planet, node_spectral, node_soul_tarot,
    node_voucher, node_tag, node_shop_pack, node_stdset,
)
from balatro_sim.game import (
    BalatroGame, BOSS_MIN_ANTE, SHOWDOWN_BOSSES, UNIMPLEMENTED_BOSSES,
)
from balatro_sim.tags import TAG_CATALOGUE, TAG_ORDER
from balatro_sim.card import make_standard_deck
from balatro_sim.shop import generate_shop


class TestPortedPrimitives:
    """Ported from balatro-seed/src/rng.rs tests."""

    def test_pseudohash_empty_is_identity(self):
        assert pseudohash("") == 1.0

    def test_pseudohash_is_deterministic(self):
        assert pseudohash("ABCDEFGH") == pseudohash("ABCDEFGH")
        assert pseudohash("ABCDEFGH") != pseudohash("ABCDEFGI")

    def test_pseudohash_stays_in_unit_interval(self):
        for s in ["A", "SEED1234", "Joker1sho3", "boss"]:
            h = pseudohash(s)
            assert 0.0 <= h < 1.0, f"{s} -> {h}"

    def test_round13_fixed_points(self):
        assert round13(0.5) == 0.5
        assert round13(0.0) == 0.0

    def test_lua_random_deterministic_given_same_seed(self):
        a, b = LuaRandom(0.5), LuaRandom(0.5)
        for _ in range(20):
            assert a.next_u64() == b.next_u64()

    def test_lua_random_random_in_unit_interval(self):
        rng = LuaRandom(pseudohash("SEED1234"))
        for _ in range(1000):
            v = rng.random()
            assert 0.0 <= v < 1.0, v

    def test_lua_random_randint_respects_bounds(self):
        rng = LuaRandom(pseudohash("SEED1234"))
        for _ in range(1000):
            v = rng.randint(0, 9)
            assert 0 <= v <= 9, v

    def test_lua_random_different_seeds_diverge(self):
        assert (LuaRandom(pseudohash("seedA")).random()
                != LuaRandom(pseudohash("seedB")).random())


class TestNodeStrings:
    """Pin the exact strings Balatro hashes (balatro-seed/src/node_id.rs)."""

    def test_boss_node(self):
        assert node_boss() == "boss"

    def test_shop_joker_nodes(self):
        assert node_cdt(3) == "cdt3"
        assert node_rarity("sho", 3) == "rarity3sho"
        assert node_edition("sho", 3) == "edisho3"
        assert node_joker("1", "sho", 3) == "Joker1sho3"
        assert node_joker("2", "sho", 3) == "Joker2sho3"
        assert node_joker("3", "buf", 1) == "Joker3buf1"
        # Legendary node has NO source/ante suffix in the real game.
        assert node_joker("4", "sou", 2) == "Joker4"

    def test_consumable_nodes(self):
        assert node_tarot("sho", 3) == "Tarotsho3"
        assert node_tarot("ar1", 2) == "Tarotar12"
        assert node_planet("pl1", 2) == "Planetpl12"
        assert node_spectral("spe", 2) == "Spectralspe2"
        assert node_soul_tarot(3) == "soul_Tarot3"

    def test_voucher_tag_pack_nodes(self):
        assert node_voucher(3) == "Voucher3"
        assert node_tag(3) == "Tag3"
        assert node_shop_pack(3) == "shop_pack3"
        assert node_stdset(3) == "stdset3"


class TestNodeTable:
    """Ported from balatro-seed/src/instance.rs tests."""

    def test_get_node_advances_on_repeated_access(self):
        src = SeedSource("TESTSEED")
        a = src.node("cdt1").random()
        b = src.node("cdt1").random()
        assert a != b

    def test_get_node_deterministic_across_instances(self):
        a = SeedSource("TESTSEED").node("cdt1").random()
        b = SeedSource("TESTSEED").node("cdt1").random()
        assert a == b

    def test_seed_normalization_matches_explore_cli(self):
        # balatro-seed's explore CLI uppercases and maps 0 -> O.
        src = SeedSource("wy3h3s0e")
        assert src.table.seed == "WY3H3SOE"


class TestTwoMode:
    def test_factory_modes(self):
        assert isinstance(make_source(42), GenericSource)
        assert isinstance(make_source(42, "seed"), SeedSource)
        assert isinstance(make_source(42, "generic"), GenericSource)

    def test_generic_nodes_share_one_stream(self):
        r = random.Random(42)
        src = make_source(42)
        assert src.node("a").random() == r.random()
        assert src.node("b").random() == r.random()
        assert src.node("a").random() == r.random()

    def test_seed_source_diverges_from_generic(self):
        a = SeedSource("ABC").node("boss").random()
        b = GenericSource("ABC").node("boss").random()
        assert a != b

    def test_seed_choice_and_shuffle_deterministic(self):
        def shuffled():
            s = SeedSource("XYZ")
            items = list(range(20))
            s.node("shuffle").shuffle(items)
            return items
        assert shuffled() == shuffled()

    def test_seed_choices_weighted_respects_weights(self):
        s = SeedSource("W")
        picks = [s.node("cdt1").choices(["a", "b"], weights=[1, 99])[0]
                 for _ in range(200)]
        assert picks.count("b") > picks.count("a")


class TestGenericMatchesLegacy:
    """generic mode must reproduce the pre-port single-stream behavior exactly."""

    def _legacy_boss_seq(self, seed: int, antes):
        """The exact old _select_boss algorithm: self.rng.choice over sorted
        fewest-appearance candidates, rotation tracked in boss_appearances.

        BalatroGame._prepare_next_blind() now rolls the ante-1 skip tag on the
        shared generic stream (one weighted pick) before any boss selection, so
        the legacy simulation consumes that draw first."""
        rng = random.Random(seed)
        eligible = [k for k in TAG_ORDER if TAG_CATALOGUE[k][1] <= 1]
        rng.choices(eligible, weights=[1.0] * len(eligible))
        appearances: dict[str, int] = {}
        seq = []
        for ante in antes:
            if ante >= 8 and ante % 8 == 0:
                pool = set(SHOWDOWN_BOSSES)
            else:
                pool = {k for k, m in BOSS_MIN_ANTE.items()
                        if m <= ante and k not in SHOWDOWN_BOSSES
                        and k not in UNIMPLEMENTED_BOSSES}
            mc = min(appearances.get(k, 0) for k in pool)
            cands = [k for k in sorted(pool) if appearances.get(k, 0) == mc]
            boss = rng.choice(cands)
            appearances[boss] = appearances.get(boss, 0) + 1
            seq.append(boss)
        return seq

    def test_boss_sequence_identical_to_legacy(self):
        g = BalatroGame(seed=11)
        got = [g._select_boss(a) for a in range(1, 9)]
        assert got == self._legacy_boss_seq(11, range(1, 9))

    def test_deck_shuffle_identical_to_legacy(self):
        # Card.id is a global counter (card.py), not RNG-derived — compare
        # rank/suit identity instead.
        def legacy_hand(seed: int):
            r = random.Random(seed)
            # Ante-1 skip-tag roll happens at _prepare_next_blind (init) on the
            # shared stream before the deck shuffle.
            eligible = [k for k in TAG_ORDER if TAG_CATALOGUE[k][1] <= 1]
            r.choices(eligible, weights=[1.0] * len(eligible))
            deck = make_standard_deck()
            r.shuffle(deck)
            # _draw_to_full pops from the END of the deck, so the opening hand
            # is the last 8 cards in draw order (deck[-8:] reversed).
            return [(c.rank, c.suit) for c in deck[-8:][::-1]]
        g = BalatroGame(seed=7)
        g._start_blind()
        assert [(c.rank, c.suit) for c in g.hand] == legacy_hand(7)


class TestSeedMode:
    """seed mode: per-node LuaRandom, deterministic per seed."""

    def test_boss_sequence_deterministic(self):
        def seq():
            g = BalatroGame(seed=11, rng_mode="seed")
            return [g._select_boss(a) for a in range(1, 9)]
        assert seq() == seq()

    def test_shop_deterministic_per_mode(self):
        def shop_keys(seed: int, mode: str):
            g = BalatroGame(seed=seed, rng_mode=mode)
            return [(i.kind, i.key) for i in generate_shop(g)]
        assert shop_keys(42, "seed") == shop_keys(42, "seed")
        assert shop_keys(42, "generic") == shop_keys(42, "generic")

    def test_reroll_advances_shop_nodes(self):
        g = BalatroGame(seed=42, rng_mode="seed")
        s1 = [(i.kind, i.key) for i in generate_shop(g)]
        s2 = [(i.kind, i.key) for i in generate_shop(g)]
        assert s1 != s2

    def test_deck_draw_deterministic(self):
        def hand():
            g = BalatroGame(seed=7, rng_mode="seed")
            g._start_blind()
            return [(c.rank, c.suit, c.flipped) for c in g.hand]
        assert hand() == hand()

    def test_env_sim_accepts_rng_mode(self):
        from balatro_sim.env_sim import BalatroSimEnv
        env = BalatroSimEnv(seed=1, rng_mode="seed")
        obs, _ = env.reset()
        assert obs is not None
        assert isinstance(env.game.rng, SeedSource)

    def test_seed_mode_run_completes(self):
        from balatro_sim.env_sim import BalatroSimEnv
        env = BalatroSimEnv(seed=99, rng_mode="seed")
        env.reset()
        for _ in range(1500):
            action = random.randrange(env.action_space.n)
            _, _, terminated, truncated, _ = env.step(action)
            if terminated or truncated:
                env.reset()
        assert True


class TestReplayDeterminism:
    """With every RNG consumer wired through the source, a seed-mode run must
    replay identically given the same action sequence — the replay-diff seed.
    """

    def test_full_run_replays_identically(self):
        from balatro_sim.env_sim import BalatroSimEnv

        def run(seed: int):
            env = BalatroSimEnv(seed=seed, rng_mode="seed")
            env.reset()
            action_rng = random.Random(12345)   # same actions both runs
            total = 0.0
            episodes = 0
            max_ante = 0
            for _ in range(2000):
                action = action_rng.randrange(env.action_space.n)
                _, reward, terminated, truncated, _ = env.step(action)
                total += reward
                max_ante = max(max_ante, env.game.ante)
                if terminated or truncated:
                    episodes += 1
                    env.reset()
            # (total, episodes, max_ante) — a reward-sum collision can't mask
            # a diverging trajectory.
            return (round(total, 6), episodes, max_ante)

        assert run(1234) == run(1234)

    def test_joker_probability_trigger_replays_identically(self):
        from balatro_sim.jokers.base import JokerInstance
        from balatro_sim.scoring import score_hand

        def score():
            g = BalatroGame(seed=77, rng_mode="seed")
            g._start_blind()
            g.jokers.append(JokerInstance("j_misprint", game=g))
            s, _ = score_hand(
                scoring_cards=g.hand[:5], all_cards=g.hand, hand_type="High Card",
                jokers=g.jokers, planet_levels=g.planet_levels,
                hands_left=3, discards_left=3, dollars=10, ante=1,
                deck_remaining=44, game=g,
            )
            return s

        assert score() == score()

    def test_consumable_random_replays_identically(self):
        from balatro_sim.consumables import apply_tarot

        def fool_result():
            g = BalatroGame(seed=5, rng_mode="seed")
            apply_tarot(g, "c_high_priestess")
            return list(g.consumable_hand)

        assert fool_result() == fool_result()


class TestSeedModeGolden:
    """Regression pins computed from the faithful port.

    These exact values were produced by the verified algorithm (per-node
    LuaRandom + real node IDs); they pin the port against accidental drift.
    Do not "fix" them without re-deriving from balatro-seed.
    """

    # Golden: seed 11, seed mode — bosses at antes 1..8 and ante-1 shop.
    EXPECTED_BOSSES = [
        "bl_club", "bl_hook", "bl_wheel", "bl_mark",
        "bl_pillar", "bl_goad", "bl_eye", "bl_violet",
    ]
    EXPECTED_SHOP = [
        ("joker", "j_even_steven"), ("joker", "j_hologram"),
        ("tarot", "c_sun"), ("planet", "pl_venus"),
        ("voucher", "v_paint_brush"),
        ("booster", "p_standard_jumbo"), ("booster", "p_celestial"),
    ]

    def test_golden_boss_sequence(self):
        g = BalatroGame(seed=11, rng_mode="seed")
        got = [g._select_boss(a) for a in range(1, 9)]
        assert got == self.EXPECTED_BOSSES

    def test_golden_shop(self):
        from balatro_sim.shop import clear_banned_jokers
        clear_banned_jokers()  # shop contents depend on the module-level allow-list
        g = BalatroGame(seed=11, rng_mode="seed")
        got = [(i.kind, i.key) for i in generate_shop(g)]
        assert got == self.EXPECTED_SHOP
