"""test_vouchers.py — Remaining-voucher phase: the 11 buyable no-ops + 5
missing vouchers, the pair-unlock rule, and the boss-reroll action."""
from __future__ import annotations

import pytest

from balatro_sim.consumables import (
    ALL_VOUCHERS, VOUCHER_BASE, apply_voucher,
    ALL_TAROTS, ALL_SPECTRALS, ALL_PLANETS,
)
from balatro_sim.game import BalatroGame, State, BLIND_CHIPS
from balatro_sim.shop import (
    generate_shop, _random_voucher, _consumable_weights, _shop_card_item,
    _roll_edition, _open_booster, ShopItem,
)
from balatro_sim.scoring import score_hand
from balatro_sim.card import Card
from balatro_sim.seed_rng import OMEN_NODE, ILLUSION_NODE
from balatro_sim.constants import STARTING_MONEY


class _FakeNode:
    """Stub RNG node returning a fixed random() value."""

    def __init__(self, r: float):
        self.r = r

    def random(self) -> float:
        return self.r


class TestCatalogue:
    def test_full_32_voucher_set(self):
        assert len(ALL_VOUCHERS) == 32
        for key in ["v_seed_money", "v_money_tree", "v_blank",
                    "v_antimatter", "v_retcon"]:
            assert key in ALL_VOUCHERS
        assert len(VOUCHER_BASE) == 15

    def test_pairs_point_at_real_bases(self):
        for upgrade, base in VOUCHER_BASE.items():
            assert base in ALL_VOUCHERS and upgrade in ALL_VOUCHERS
            assert base != upgrade
        assert VOUCHER_BASE["v_money_tree"] == "v_seed_money"
        assert VOUCHER_BASE["v_antimatter"] == "v_blank"
        assert VOUCHER_BASE["v_retcon"] == "v_directors_cut"


class TestPairUnlock:
    def test_initial_shop_pool_excludes_upgrades(self):
        g = BalatroGame(seed=5, rng_mode="seed")
        seen = {_random_voucher(g) for _ in range(400)}
        assert not (seen & set(VOUCHER_BASE))  # no upgrade before its base
        assert "v_seed_money" in seen
        assert "v_blank" in seen
        assert "v_crystal_ball" in seen or "v_omen_globe" in seen  # standalone

    def test_upgrade_appears_after_base_owned(self):
        g = BalatroGame(seed=5, rng_mode="seed")
        apply_voucher(g, "v_seed_money")
        seen = {_random_voucher(g) for _ in range(600)}
        assert "v_money_tree" in seen
        g2 = BalatroGame(seed=5, rng_mode="seed")
        apply_voucher(g2, "v_directors_cut")
        seen2 = {_random_voucher(g2) for _ in range(600)}
        assert "v_retcon" in seen2


class TestEconomyVouchers:
    def test_seed_money_and_money_tree_interest_cap(self):
        g = BalatroGame(seed=5, rng_mode="seed")
        assert g.interest_cap == 5
        apply_voucher(g, "v_seed_money")
        assert g.interest_cap == 10
        apply_voucher(g, "v_money_tree")
        assert g.interest_cap == 20

    def test_interest_pays_to_cap(self):
        def interest_with(cap_voucher=None):
            g = BalatroGame(seed=5, rng_mode="seed")
            if cap_voucher:
                apply_voucher(g, cap_voucher)
            g.dollars = 100
            g.hands_left = 0          # no hand payout
            g._end_round()
            return g.dollars - 100
        assert interest_with() == 5          # base cap $5 (20 // 5 = 20 -> 5)
        assert interest_with("v_seed_money") == 10
        assert interest_with("v_money_tree") == 20

    def test_blank_does_nothing_and_antimatter_adds_slot(self):
        g = BalatroGame(seed=5, rng_mode="seed")
        state_before = (g.joker_slots, g.dollars, g.base_hands, g.hand_size)
        apply_voucher(g, "v_blank")
        assert (g.joker_slots, g.dollars, g.base_hands, g.hand_size) == state_before
        apply_voucher(g, "v_antimatter")
        assert g.joker_slots == state_before[0] + 1

    def test_petroglyph_minus_one_discard(self):
        g = BalatroGame(seed=5, rng_mode="seed")
        before = g.base_discards
        apply_voucher(g, "v_petroglyph")
        assert g.base_discards == max(1, before - 1)


class TestShopOddsVouchers:
    def test_consumable_weights(self):
        g = BalatroGame(seed=5, rng_mode="seed")
        assert _consumable_weights(g) == (["planet", "tarot", "spectral"], [40, 50, 10])
        apply_voucher(g, "v_tarot_merchant")
        pool, w = _consumable_weights(g)
        assert dict(zip(pool, w))["tarot"] == 100
        apply_voucher(g, "v_tarot_tycoon")
        _, w = _consumable_weights(g)
        assert dict(zip(pool, w))["tarot"] == 200
        apply_voucher(g, "v_planet_merchant")
        apply_voucher(g, "v_planet_tycoon")
        _, w = _consumable_weights(g)
        # Telescope affects Celestial PACK contents (not shop weights)
        assert dict(zip(pool, w))["planet"] == 40 * 2 * 2

    @pytest.mark.parametrize("boost,r,expected", [
        (1.0, 0.005, "Polychrome"),
        (1.0, 0.03, "Foil"),
        (1.0, 0.05, "None"),
        (2.0, 0.03, "Holographic"),   # base would be Foil — Hone shifts it
        (2.0, 0.05, "Foil"),          # base would be None
        (4.0, 0.05, "Holographic"),
        (4.0, 0.10, "Foil"),
        (4.0, 0.20, "None"),
    ])
    def test_roll_edition_boost_table(self, boost, r, expected):
        assert _roll_edition(_FakeNode(r), boost) == expected

    def test_magic_trick_adds_shop_cards(self):
        g = BalatroGame(seed=8, rng_mode="seed")
        apply_voucher(g, "v_magic_trick")
        seen = 0
        for _ in range(300):
            seen += sum(1 for i in generate_shop(g) if i.kind == "card")
        assert seen > 0

    def test_buy_shop_card_adds_to_deck(self):
        g = BalatroGame(seed=8, rng_mode="seed")
        g.dollars = 100
        g.current_shop = [ShopItem("card", "card_10_Spades", "10 of Spades", 4,
                                   card=Card(10, "Spades"))]
        g.state = State.SHOP
        deck_before = len(g.deck)
        g.step({"type": "buy", "item_idx": 0})
        assert len(g.deck) == deck_before + 1
        assert g.current_shop[0].sold

    def test_illusion_adds_enhancement_and_edition(self):
        g = BalatroGame(seed=8, rng_mode="seed")
        apply_voucher(g, "v_illusion")
        g.rng.node(ILLUSION_NODE).chance = lambda p: True
        g.rng.node(ILLUSION_NODE).choice = lambda seq: seq[0]
        item = _shop_card_item(g)
        assert item.kind == "card" and item.card is not None
        assert item.card.enhancement != "None"
        assert item.card.edition != "None"
        assert item.card.seal == "None"   # seals bugged off in the real game


class TestPackVouchers:
    def test_omen_globe_replaces_tarots_in_arcana_packs(self):
        g = BalatroGame(seed=8, rng_mode="seed")
        apply_voucher(g, "v_omen_globe")
        g.rng.node(OMEN_NODE).chance = lambda p: True
        _open_booster(g, "p_arcana")
        assert all(c in ALL_SPECTRALS for c in g.booster_choices)
        g.rng.node(OMEN_NODE).chance = lambda p: False
        _open_booster(g, "p_arcana")
        assert all(c in ALL_TAROTS for c in g.booster_choices)

    def test_telescope_forces_most_played_planet(self):
        g = BalatroGame(seed=8, rng_mode="seed")
        apply_voucher(g, "v_telescope")
        g.run_hand_counts["Flush"] = 5
        g.run_hand_counts["Pair"] = 3
        _open_booster(g, "p_celestial")
        assert g.booster_choices[0] == "pl_jupiter"  # Flush's planet
        # higher-tier tie-break: Flush Five (index 11) beats High Card (index 0)
        g2 = BalatroGame(seed=8, rng_mode="seed")
        apply_voucher(g2, "v_telescope")
        g2.run_hand_counts["High Card"] = 2
        g2.run_hand_counts["Flush Five"] = 2
        _open_booster(g2, "p_celestial")
        assert g2.booster_choices[0] == "pl_eris"  # Flush Five's planet


class TestObservatory:
    def test_planet_in_consumables_boosts_mult(self):
        g = BalatroGame(seed=7, rng_mode="seed")
        apply_voucher(g, "v_observatory")
        g.consumable_hand = ["pl_jupiter"]  # Flush planet held
        cards = [Card(10, "Spades"), Card(9, "Hearts"), Card(8, "Clubs"),
                 Card(7, "Diamonds"), Card(6, "Spades")]
        levels = {h: 1 for h in ["Flush"]}
        sc, _ = score_hand(cards, cards, "Flush", [], levels,
                           4, 3, 20, 1, 40, game=g)
        sc_no, _ = score_hand(cards, cards, "Flush", [], levels,
                              4, 3, 20, 1, 40, game=None)
        assert sc == int(sc_no * 1.5)
        # Not active when the planet is NOT held
        g.consumable_hand = []
        sc2, _ = score_hand(cards, cards, "Flush", [], levels,
                            4, 3, 20, 1, 40, game=g)
        assert sc2 == sc_no


class TestBossReroll:
    def _shop_before_boss(self, seed=11):
        g = BalatroGame(seed=seed, rng_mode="seed")
        g.ante = 3   # gives access to wall/violet for scaling checks
        g.blind_idx = 2
        g._prepare_next_blind()
        g.state = State.SHOP
        return g

    def test_directors_cut_rerolls_once_per_ante(self):
        g = self._shop_before_boss()
        apply_voucher(g, "v_directors_cut")
        assert g.current_blind.kind == "Boss"
        g.dollars = 100
        old = g.current_blind.boss_key
        g.step({"type": "reroll_boss"})
        assert g.current_blind.boss_key != old
        assert g.dollars == 90
        old2 = g.current_blind.boss_key
        g.step({"type": "reroll_boss"})
        assert g.current_blind.boss_key == old2   # blocked: once per Ante
        assert g.dollars == 90

    def test_retcon_unlimited(self):
        g = self._shop_before_boss()
        apply_voucher(g, "v_directors_cut")
        apply_voucher(g, "v_retcon")
        g.dollars = 100
        seen = {g.current_blind.boss_key}
        for _ in range(4):
            g.step({"type": "reroll_boss"})
            seen.add(g.current_blind.boss_key)
        assert len(seen) > 1
        assert g.dollars == 60

    def test_reroll_boss_not_available_without_voucher(self):
        g = self._shop_before_boss()
        g.dollars = 100
        old = g.current_blind.boss_key
        g.step({"type": "reroll_boss"})
        assert g.current_blind.boss_key == old
        assert g.dollars == 100

    def test_reroll_to_wall_scales_chips(self):
        g = self._shop_before_boss()
        apply_voucher(g, "v_directors_cut")
        apply_voucher(g, "v_retcon")
        g.dollars = 500
        for _ in range(30):
            if g.current_blind.boss_key == "bl_wall":
                break
            g.step({"type": "reroll_boss"})
        if g.current_blind.boss_key == "bl_wall":
            assert g.current_blind.chips_target == BLIND_CHIPS[g.ante][0] * 4
        else:
            assert g.current_blind.chips_target in (
                BLIND_CHIPS[g.ante][2],
                BLIND_CHIPS[g.ante][0] * 6,   # violet
            )


class TestObservation:
    def test_obs_dims_updated(self):
        from balatro_sim.env_sim import BalatroSimEnv, OBS_DIM as E
        from balatro_sim.env_v7 import BalatroV7Env, OBS_DIM as V7
        from balatro_sim.env_mp import OBS_DIM as MP
        assert E == 449    # 444 + 5 (vouchers 27 -> 32)
        assert V7 == 481
        assert MP == 485
        env = BalatroSimEnv(seed=1, rng_mode="seed")
        obs, _ = env.reset()
        assert obs.shape == (449,)
        env7 = BalatroV7Env(seed=1, rng_mode="seed")
        obs7, _ = env7.reset()
        assert obs7.shape == (481,)
