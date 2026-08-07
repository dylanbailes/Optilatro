"""test_tags.py — Phase 1: the 24 real skip-blind Tags.

Covers the catalogue + ante gates, seed-deterministic rolling, and every tag
effect (money, free packs, editions, free-rarity jokers, Investment, Negative,
Juggle, Coupon, D6, Voucher, Boss reroll, Double copy), plus the booster-state
fix that the free-pack tags depend on.
"""
from __future__ import annotations

import pytest

from balatro_sim.game import BalatroGame, State
from balatro_sim.tags import (
    TAG_CATALOGUE, TAG_ORDER, TAG_NAMES, roll_tag, apply_tag,
)
from balatro_sim.shop import generate_shop, JOKER_CATALOGUE
from balatro_sim.constants import STARTING_MONEY, HAND_SIZE


def _skip(game, tag=None):
    """Skip the current blind, optionally forcing the offered tag."""
    if tag is not None:
        game.current_tag = tag
    game.step({"type": "skip_blind"})
    return game.state


class TestCatalogue:
    def test_all_24_real_tags_present(self):
        assert len(TAG_CATALOGUE) == 24
        # The real 1.0 tag set, by key
        expected = {
            "t_uncommon", "t_rare", "t_investment", "t_voucher", "t_boss",
            "t_speed", "t_economy", "t_coupon", "t_d6", "t_double",
            "t_juggle", "t_foil", "t_holographic", "t_polychrome",
            "t_charm", "t_buffoon", "t_ethereal", "t_meteor", "t_standard",
            "t_top_up", "t_garbage", "t_handy", "t_orbital", "t_negative",
        }
        assert set(TAG_CATALOGUE) == expected
        assert TAG_ORDER == sorted(TAG_CATALOGUE)

    def test_nine_tags_ante_gated(self):
        gated = {k for k, v in TAG_CATALOGUE.items() if v[1] > 1}
        assert gated == {
            "t_buffoon", "t_ethereal", "t_garbage", "t_handy", "t_meteor",
            "t_negative", "t_orbital", "t_standard", "t_top_up",
        }
        assert len(gated) == 9

    def test_ante1_never_rolls_gated_tag(self):
        gated = {k for k, v in TAG_CATALOGUE.items() if v[1] > 1}
        for seed in range(80):
            g = BalatroGame(seed=seed, rng_mode="seed")
            assert g.current_tag is not None
            assert g.current_tag not in gated
            assert TAG_CATALOGUE[g.current_tag][1] == 1

    def test_ante2_gated_tags_become_available(self):
        gated = {k for k, v in TAG_CATALOGUE.items() if v[1] > 1}
        seen = set()
        for seed in range(300):
            g = BalatroGame(seed=seed, rng_mode="seed")
            g.ante = 2
            g._prepare_next_blind()
            assert g.current_tag is not None
            seen.add(g.current_tag)
        # Every gated tag is reachable (uniform weights among 24)
        assert seen >= gated

    def test_boss_blind_offers_no_tag_and_cannot_be_skipped(self):
        g = BalatroGame(seed=2, rng_mode="seed")
        g.blind_idx = 2
        g._prepare_next_blind()
        assert g.current_blind.is_boss
        assert g.current_tag is None
        dollars = g.dollars
        g.step({"type": "skip_blind"})
        assert g.state == State.BLIND_SELECT
        assert g.dollars == dollars


class TestRollDeterminism:
    def test_tag_roll_is_seed_deterministic(self):
        a = [BalatroGame(seed=s, rng_mode="seed").current_tag for s in range(12)]
        b = [BalatroGame(seed=s, rng_mode="seed").current_tag for s in range(12)]
        assert a == b

    def test_tag_node_does_not_disturb_boss_node(self):
        def bosses():
            out = []
            for s in range(12):
                g = BalatroGame(seed=s, rng_mode="seed")
                g.blind_idx = 2
                g._prepare_next_blind()
                out.append(g.current_blind.boss_key)
            return out
        assert bosses() == bosses()


class TestInstantTags:
    def test_economy_doubles_capped_40(self):
        g = BalatroGame(seed=5, rng_mode="seed")
        g.dollars = 15
        _skip(g, "t_economy")
        assert g.dollars == 30
        g = BalatroGame(seed=5, rng_mode="seed")
        g.dollars = 25
        _skip(g, "t_economy")
        assert g.dollars == 40  # 50 → capped at 40
        g = BalatroGame(seed=5, rng_mode="seed")
        g.dollars = 30
        _skip(g, "t_economy")
        assert g.dollars == 40  # 60 → capped at 40

    def test_speed_pays_5_per_skipped_blind(self):
        g = BalatroGame(seed=5, rng_mode="seed")
        g.skipped_blinds = 3
        _skip(g, "t_speed")
        assert g.skipped_blinds == 4
        assert g.dollars == STARTING_MONEY + 20

    def test_handy_pays_run_hands_played(self):
        g = BalatroGame(seed=5, rng_mode="seed")
        g.run_hands_played = 7
        _skip(g, "t_handy")
        assert g.dollars == STARTING_MONEY + 7

    def test_garbage_pays_run_unused_discards(self):
        g = BalatroGame(seed=5, rng_mode="seed")
        g.run_unused_discards = 9
        _skip(g, "t_garbage")
        assert g.dollars == STARTING_MONEY + 9

    def test_orbital_upgrades_highest_hand_3(self):
        g = BalatroGame(seed=5, rng_mode="seed")
        g.planet_levels["Pair"] = 5
        g.planet_levels["Flush"] = 4
        _skip(g, "t_orbital")
        assert g.planet_levels["Pair"] == 8
        assert g.planet_levels["Flush"] == 4

    def test_top_up_adds_up_to_2_commons(self):
        g = BalatroGame(seed=5, rng_mode="seed")
        _skip(g, "t_top_up")
        assert len(g.jokers) == 2
        for j in g.jokers:
            assert JOKER_CATALOGUE[j.key]["rarity"] == "Common"
        # Respects the joker-slot cap
        g2 = BalatroGame(seed=5, rng_mode="seed")
        common = next(k for k, v in JOKER_CATALOGUE.items()
                      if v["rarity"] == "Common")
        from balatro_sim.jokers.base import JokerInstance
        for _ in range(4):
            g2.jokers.append(JokerInstance(common, "None", game=g2))
        _skip(g2, "t_top_up")
        assert len(g2.jokers) == 5

    def test_skip_no_longer_gives_flat_5(self):
        # A tag with no immediate money leaves dollars untouched
        g = BalatroGame(seed=5, rng_mode="seed")
        _skip(g, "t_uncommon")
        assert g.dollars == STARTING_MONEY


class TestFreePackTags:
    @pytest.mark.parametrize("tag,kind", [
        ("t_charm", "tarot"), ("t_buffoon", "joker"),
        ("t_ethereal", "spectral"), ("t_meteor", "planet"),
        ("t_standard", "card"),
    ])
    def test_pack_tag_opens_pack_then_shop(self, tag, kind):
        g = BalatroGame(seed=8, rng_mode="seed")
        g.current_tag = tag
        g.step({"type": "skip_blind"})
        assert g.state == State.BOOSTER_OPEN
        assert g._shop_after_pack
        assert g.booster_choices
        if kind == "card":
            assert isinstance(g.booster_choices[0], tuple)
            assert g.booster_choices[0][0] == "card"
        elif kind == "joker":
            # Buffoon-pack jokers carry their rolled edition: ("joker", key, edition)
            assert all(isinstance(c, tuple) and c[0] == "joker" and len(c) == 3
                       for c in g.booster_choices)
        else:
            assert all(isinstance(c, str) for c in g.booster_choices)
        g.step({"type": "pick_booster", "indices": [0]})
        assert g.state == State.SHOP
        assert not g._shop_after_pack
        assert g.current_shop

    def test_pack_tag_skip_booster_still_enters_shop(self):
        g = BalatroGame(seed=8, rng_mode="seed")
        g.current_tag = "t_ethereal"
        g.step({"type": "skip_blind"})
        assert g.state == State.BOOSTER_OPEN
        g.step({"type": "skip_booster"})
        assert g.state == State.SHOP

    def test_double_pack_tag_grants_both_packs(self):
        """Double Tag copying a pack tag must open BOTH packs, not overwrite
        the first one's contents (regression for the overwrite bug)."""
        g = BalatroGame(seed=3, rng_mode="seed")
        _skip(g, "t_double")
        assert g.double_tag_active
        assert g.state == State.SHOP
        g.step({"type": "leave_shop"})
        _skip(g, "t_ethereal")
        assert g.state == State.BOOSTER_OPEN
        assert len(g.pending_packs) == 1   # first opened, second queued
        g.step({"type": "pick_booster", "indices": [0]})
        assert g.state == State.BOOSTER_OPEN   # second pack opened
        assert len(g.pending_packs) == 0
        assert g.booster_choices
        g.step({"type": "pick_booster", "indices": [0]})
        assert g.state == State.SHOP
        assert not g._shop_after_pack


class TestNextShopTags:
    def test_coupon_makes_items_free_except_vouchers(self):
        g = BalatroGame(seed=8, rng_mode="seed")
        _skip(g, "t_coupon")
        assert g.state == State.SHOP
        for item in g.current_shop:
            if item.kind == "voucher":
                assert item.price == 10
            else:
                assert item.price == 0
        # One-shot: a later shop is normal
        g.current_shop = generate_shop(g)
        assert any(i.price > 0 for i in g.current_shop if i.kind != "voucher")

    def test_d6_makes_next_reroll_free(self):
        g = BalatroGame(seed=8, rng_mode="seed")
        _skip(g, "t_d6")
        assert g.reroll_cost == 0
        g.dollars = 100
        g.step({"type": "reroll"})
        assert g.dollars == 100  # first reroll free
        assert g.reroll_cost == 1

    @pytest.mark.parametrize("tag,rarity", [
        ("t_uncommon", "Uncommon"), ("t_rare", "Rare"),
    ])
    def test_free_rarity_tag(self, tag, rarity):
        g = BalatroGame(seed=8, rng_mode="seed")
        _skip(g, tag)
        jokers = [i for i in g.current_shop if i.kind == "joker"]
        assert jokers
        assert jokers[0].price == 0
        assert JOKER_CATALOGUE[jokers[0].key]["rarity"] == rarity

    @pytest.mark.parametrize("tag,edition", [
        ("t_foil", "Foil"), ("t_holographic", "Holographic"),
        ("t_polychrome", "Polychrome"), ("t_negative", "Negative"),
    ])
    def test_free_edition_tag(self, tag, edition):
        g = BalatroGame(seed=8, rng_mode="seed")
        _skip(g, tag)
        jokers = [i for i in g.current_shop if i.kind == "joker"]
        assert jokers
        assert jokers[0].price == 0
        assert jokers[0].edition == edition

    def test_voucher_tag_adds_extra_voucher_slot(self):
        g = BalatroGame(seed=8, rng_mode="seed")
        _skip(g, "t_voucher")
        vouchers = [i for i in g.current_shop if i.kind == "voucher"]
        assert len(vouchers) == 2


class TestQueuedTags:
    def test_investment_pays_after_next_boss(self):
        g = BalatroGame(seed=5, rng_mode="seed")
        apply_tag(g, "t_investment")
        assert g.investment_pending
        g.blind_idx = 2
        g._prepare_next_blind()
        assert g.current_blind.is_boss
        g.chips_scored = g.current_blind.chips_target
        g.hands_left = 0
        g.dollars = 4  # no interest ($4 < $5), no hand payout
        g.state = State.ROUND_EVAL
        g.step({"type": "noop"})
        # +25 Investment Tag, plus the $5 Boss-blind reward (M2 P0)
        assert g.dollars == 4 + 25 + 5
        assert not g.investment_pending

    def test_juggle_hand_size_next_round_only(self):
        g = BalatroGame(seed=5, rng_mode="seed")
        apply_tag(g, "t_juggle")
        assert g.hand_size_bonus_next_round == 3
        g._start_blind()
        assert g.hand_size == HAND_SIZE + 3
        assert g.hand_size_bonus_next_round == 0
        g._start_blind()
        assert g.hand_size == HAND_SIZE

    def test_double_copies_next_tag(self):
        g = BalatroGame(seed=3, rng_mode="seed")
        _skip(g, "t_double")
        assert g.double_tag_active
        assert g.state == State.SHOP
        g.step({"type": "leave_shop"})          # big blind prepared
        g.dollars = 10
        _skip(g, "t_economy")                    # doubled economy: ×2 twice
        assert g.dollars == 40
        assert not g.double_tag_active

    def test_boss_tag_rerolls_next_boss(self):
        g = BalatroGame(seed=11, rng_mode="seed")
        apply_tag(g, "t_boss")
        assert g.boss_reroll_pending
        calls = []
        orig = g._select_boss

        def spy(ante, exclude=None):
            calls.append(exclude)
            return orig(ante, exclude=exclude)

        g._select_boss = spy
        g.blind_idx = 2
        g._prepare_next_blind()
        assert g.current_blind.is_boss
        assert not g.boss_reroll_pending
        # two selection draws: the original pick (no exclude) then the reroll
        assert len(calls) == 2
        assert calls[0] is None
        assert calls[1] is not None


class TestBoosterFlow:
    def test_booster_buy_opens_booster_state(self):
        """Regression: buying a booster used to fill booster_choices without
        ever transitioning to BOOSTER_OPEN (pack picks unreachable)."""
        g = BalatroGame(seed=7, rng_mode="seed")
        g.dollars = 100
        g.step({"type": "skip_blind"})
        idx = next(i for i, it in enumerate(g.current_shop)
                   if it.kind == "booster")
        g.step({"type": "buy", "item_idx": idx})
        assert g.state == State.BOOSTER_OPEN
        assert g.booster_choices
        g.step({"type": "pick_booster", "indices": [0]})
        assert g.state == State.SHOP


class TestObservation:
    def test_env_sim_obs_dims_and_tag_onehot(self):
        from balatro_sim.env_sim import BalatroSimEnv, OBS_DIM
        assert OBS_DIM == 449   # 444 + 5 (vouchers 27 -> 32)
        env = BalatroSimEnv(seed=1, rng_mode="seed")
        obs, *_ = env.reset()
        assert obs.shape == (OBS_DIM,)
        tag_idx = OBS_DIM - 24 - 5
        onehot = obs[tag_idx:tag_idx + 24]
        assert onehot.sum() == pytest.approx(1.0)
        assert obs[tag_idx + TAG_ORDER.index(env.game.current_tag)] == 1.0

    def test_env_v7_obs_dim(self):
        from balatro_sim.env_v7 import BalatroV7Env, OBS_DIM
        assert OBS_DIM == 481   # 476 + 5 (vouchers 27 -> 32)
        env = BalatroV7Env(seed=1, rng_mode="seed")
        obs, *_ = env.reset()
        assert obs.shape == (OBS_DIM,)


class TestFullRun:
    def test_run_with_skips_completes(self):
        """A policy that skips some blinds and plays the rest never crashes."""
        g = BalatroGame(seed=42, rng_mode="seed")
        guard = 0
        while not g.state == State.GAME_OVER and guard < 4000:
            guard += 1
            s = g.state
            if s == State.BLIND_SELECT:
                # Skip small/big non-boss blinds about a third of the time
                if (not g.current_blind.is_boss) and (guard % 3 == 0):
                    g.step({"type": "skip_blind"})
                else:
                    g.step({"type": "play_blind"})
            elif s == State.SELECTING_HAND:
                if g.hand:
                    g.step({"type": "play", "cards": list(range(min(5, len(g.hand))))})
                else:
                    g.step({"type": "discard", "cards": []})
            elif s == State.ROUND_EVAL:
                g.step({"type": "noop"})
            elif s == State.SHOP:
                bought = False
                for i, it in enumerate(g.current_shop):
                    if it.kind == "booster" and g.dollars >= it.price:
                        g.step({"type": "buy", "item_idx": i})
                        bought = True
                        break
                if not bought:
                    g.step({"type": "leave_shop"})
            elif s == State.BOOSTER_OPEN:
                if g.booster_choices:
                    g.step({"type": "pick_booster", "indices": [0]})
                else:
                    g.step({"type": "skip_booster"})
        assert guard < 4000, "run did not terminate"
        assert g.state == State.GAME_OVER
