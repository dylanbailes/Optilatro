"""test_phase0.py — Phase 0 fidelity fixes (2026-08-06).

Covers:
  1. Dead shop jokers — Supernova registered with its real effect (+Mult per
     run-play-count), Oops! All 6s registered under its catalogue key (j_oops),
     Ring Master corrected to real "Showman" semantics (its presence lifts the
     duplicate-suppression rule — M2 P1 #7).
  2. Boss-hook jokers wired in game.py — Chicot (presence-based permanent
     disable), Luchador (sell-to-disable game-level override), Matador (+$8 per
     Boss Blind ability trigger).
  3. Glass shatter — 1-in-4 per scored Glass card (doubled by Oops), shattered
     cards removed permanently (never return to the deck).
  4. Red Deck — +1 discard per round by default (spec lock); deck="white" = base.
"""
from __future__ import annotations

from types import SimpleNamespace

from balatro_sim.card import Card
from balatro_sim.constants import STARTING_MONEY, STARTING_DISCARDS, BLIND_CHIPS
from balatro_sim.game import BalatroGame, State, BlindInfo
from balatro_sim.jokers.base import JokerInstance, JOKER_REGISTRY, ScoreContext
from balatro_sim.shop import (
    sell_joker, generate_shop, _random_shop_item, _open_booster, random_joker_key,
    _roll_standard_card,
)
from balatro_sim.consumables import apply_voucher


class _FixedNode:
    """Deterministic RNG-node stand-in (forces shatter / survive rolls)."""

    def __init__(self, value: float):
        self.value = value

    def random(self) -> float:
        return self.value

    def randint(self, lo, hi):
        return lo

    def randrange(self, *args):
        return 0

    def choice(self, seq):
        return seq[0]

    def choices(self, population, weights, k=1):
        return [population[0]] * k

    def shuffle(self, seq):
        pass


def _game_with_rng(value: float) -> BalatroGame:
    g = BalatroGame(seed=1)
    g.rng.node = lambda key: _FixedNode(value)
    return g


def _enter_blind_hand(g: BalatroGame, boss_key: str) -> BalatroGame:
    """Put the game into SELECTING_HAND against a specific boss, bypassing the
    deck reset in _start_blind so a crafted hand survives."""
    g.current_blind = BlindInfo(
        name=f"Test {boss_key}", kind="Boss", chips_target=100_000,
        is_boss=True, boss_key=boss_key,
    )
    g.state = State.SELECTING_HAND
    g.hands_left = g.base_hands
    g.discards_left = g.base_discards
    return g


def _start_boss(boss_key: str, joker_keys=()) -> BalatroGame:
    g = BalatroGame(seed=1)
    for k in joker_keys:
        g.jokers.append(JokerInstance(k, game=g))
    g.ante = 1
    g.blind_idx = 2
    g.current_blind = BlindInfo(f"T {boss_key}", "Boss", 1000, True, boss_key)
    g.state = State.BLIND_SELECT
    g.step({"type": "play_blind"})
    return g


class TestRedDeck:
    def test_default_is_red_deck_plus_one_discard(self):
        assert BalatroGame().base_discards == STARTING_DISCARDS + 1

    def test_white_deck_has_base_discards(self):
        assert BalatroGame(deck="white").base_discards == STARTING_DISCARDS

    def test_start_blind_uses_deck_discards(self):
        g = BalatroGame()
        g.step({"type": "play_blind"})
        assert g.discards_left == g.base_discards == STARTING_DISCARDS + 1


class TestDeadJokers:
    def test_supernova_registered(self):
        assert "j_supernova" in JOKER_REGISTRY

    def test_supernova_adds_run_count_as_mult(self):
        fake = SimpleNamespace(run_hand_counts={"Pair": 3})
        inst = JokerInstance("j_supernova", game=fake)
        ctx = ScoreContext(hand_type="Pair")
        JOKER_REGISTRY["j_supernova"].on_hand_scored(inst, ctx)
        assert ctx.mult == 3

    def test_supernova_noop_without_game(self):
        # Direct-call jokers (no game) fall back safely instead of crashing
        inst = JokerInstance("j_supernova")
        ctx = ScoreContext(hand_type="Pair")
        JOKER_REGISTRY["j_supernova"].on_hand_scored(inst, ctx)
        assert ctx.mult == 0

    def test_oops_registered_under_catalogue_key(self):
        assert "j_oops" in JOKER_REGISTRY
        # The legacy j_oops_all_sixes spelling was a dead key — removed by the
        # joker-fidelity de-duplication; scoring.py keys off j_oops alone.
        assert "j_oops_all_sixes" not in JOKER_REGISTRY

    def test_ring_master_resolves(self):
        # Real game: "Showman" — duplicates already allowed, so a registered no-op
        assert "j_ring_master" in JOKER_REGISTRY


class TestGlassShatter:
    def _play_glass(self, value: float, extra_jokers=()):
        g = _game_with_rng(value)
        for k in extra_jokers:
            g.jokers.append(JokerInstance(k, game=g))
        g.deck = []
        g.hand = [Card(10, "Spades", enhancement="Glass")]
        _enter_blind_hand(g, "bl_goad")
        g.step({"type": "play", "cards": [0]})
        return g

    def _glass_anywhere(self, g) -> bool:
        return any(c.enhancement == "Glass" for c in g.hand + g.spent + g.deck)

    def test_shatters_when_roll_fails(self):
        g = self._play_glass(0.0)      # 0.0 < 0.25 -> shattered
        assert not self._glass_anywhere(g)

    def test_survives_when_roll_succeeds(self):
        g = self._play_glass(0.99)     # >= 0.25 -> survives, stays in the run
        assert self._glass_anywhere(g)
        # Played (not destroyed): the card sits in the round's pool — spent,
        # or redrawn to hand once the empty deck triggers the mid-round
        # reshuffle (real game).
        assert any(c.enhancement == "Glass" for c in g.hand + g.spent)

    def test_oops_doubles_shatter_chance(self):
        # 0.3 is below the doubled 0.5 but above the base 0.25
        with_oops = self._play_glass(0.3, extra_jokers=("j_oops",))
        assert not self._glass_anywhere(with_oops)
        without_oops = self._play_glass(0.3)
        assert self._glass_anywhere(without_oops)


class TestBossHooks:
    def test_chicot_disables_goad_debuff(self):
        g = _start_boss("bl_goad", ("j_chicot",))
        assert not any(c.debuffed for c in g.hand)

    def test_goad_debuffs_spades_normally(self):
        g = _start_boss("bl_goad")
        assert any(c.debuffed for c in g.hand + g.deck)

    def test_chicot_disables_wall_scaling(self):
        g = BalatroGame(seed=1)
        g.jokers.append(JokerInstance("j_chicot", game=g))
        g.ante = 2
        g.blind_idx = 2
        g._select_boss = lambda ante: "bl_wall"
        g._prepare_next_blind()
        assert g.current_blind.chips_target == BLIND_CHIPS[2][2]

    def test_wall_scales_without_chicot(self):
        g = BalatroGame(seed=1)
        g.ante = 2
        g.blind_idx = 2
        g._select_boss = lambda ante: "bl_wall"
        g._prepare_next_blind()
        assert g.current_blind.chips_target == BLIND_CHIPS[2][0] * 4

    def test_luchador_sell_sets_override(self):
        g = BalatroGame(seed=1)
        g.jokers.append(JokerInstance("j_luchador", game=g))
        sell_joker(g, 0)
        assert g.boss_disabled_override is True

    def test_luchador_disables_next_boss(self):
        g = BalatroGame(seed=1)
        g.jokers.append(JokerInstance("j_luchador", game=g))
        sell_joker(g, 0)
        g.ante = 1
        g.blind_idx = 2
        g.current_blind = BlindInfo("T goad", "Boss", 1000, True, "bl_goad")
        g.state = State.BLIND_SELECT
        g.step({"type": "play_blind"})
        assert not any(c.debuffed for c in g.hand)

    def test_chicot_disables_in_play_tooth(self):
        # In-play boss effects must also be skipped when abilities are disabled
        g = _start_boss("bl_tooth", ("j_chicot",))
        g.hand = [Card(10, "Spades")]
        g.deck = []
        money_before = g.dollars
        g.step({"type": "play", "cards": [0]})
        assert g.dollars == money_before     # The Tooth: no $1/card lost

    def test_tooth_costs_money_normally(self):
        g = _start_boss("bl_tooth")
        g.hand = [Card(10, "Spades")]
        g.deck = []
        money_before = g.dollars
        g.step({"type": "play", "cards": [0]})
        assert g.dollars == money_before - 1

    # ── Matador: 13 triggering blinds, per-hand timing (M2 P0) ─────────────

    def test_matador_no_payout_at_blind_start(self):
        # Matador is strictly per-hand — no blind-start payout (real game).
        g = _start_boss("bl_goad", ("j_matador",))
        assert g.dollars == STARTING_MONEY

    def test_matador_pays_when_debuffed_card_scores(self):
        g = _start_boss("bl_goad", ("j_matador",))
        spade = Card(10, "Spades")
        spade.debuffed = True          # The Goad: Spades are debuffed
        g.hand = [spade]
        g.deck = []
        g.step({"type": "play", "cards": [0]})
        assert g.dollars == STARTING_MONEY + 8

    def test_matador_ignores_non_scoring_debuffed_cards(self):
        # Wiki: a debuffed card OUTSIDE the hand's scoring cards (High Card
        # with a non-scoring debuffed card) does not trigger Matador.
        g = _start_boss("bl_goad", ("j_matador",))
        best = Card(10, "Hearts")        # scores as the High Card
        off = Card(5, "Spades")
        off.debuffed = True              # in the played set but not scoring
        g.hand = [best, off]
        g.deck = []
        g.step({"type": "play", "cards": [0, 1]})
        assert g.dollars == STARTING_MONEY

    def test_matador_flint_triggers_every_hand(self):
        g = _start_boss("bl_flint", ("j_matador",))
        g.hand = [Card(10, "Spades")]
        g.deck = []
        g.step({"type": "play", "cards": [0]})
        assert g.dollars == STARTING_MONEY + 8

    def test_matador_never_triggers_on_crimson(self):
        # Crimson Heart is one of the 15 no-trigger blinds (real-game oversight
        # — the flag is set with the wrong timing).
        g = _start_boss("bl_crimson", ("j_matador",))
        assert g.dollars == STARTING_MONEY
        g.hand = [Card(10, "Spades")]
        g.deck = []
        g.step({"type": "play", "cards": [0]})
        assert g.dollars == STARTING_MONEY

    def test_matador_never_triggers_on_hook(self):
        g = _start_boss("bl_hook", ("j_matador",))
        g.hand = [Card(10, "Spades"), Card(9, "Hearts")]
        g.deck = []
        g.step({"type": "play", "cards": [0, 1]})
        assert g.dollars == STARTING_MONEY

    def test_matador_arm_only_when_level_2(self):
        g = _start_boss("bl_grim", ("j_matador",))
        g.hand = [Card(10, "Spades")]
        g.deck = []
        g.step({"type": "play", "cards": [0]})
        assert g.dollars == STARTING_MONEY        # level 1: no decrease possible
        g.planet_levels["High Card"] = 3
        g.hand = [Card(10, "Spades")]
        g.deck = []
        g.step({"type": "play", "cards": [0]})
        assert g.dollars == STARTING_MONEY + 8    # level 3: Arm can decrease

    def test_matador_ox_when_money_zeroed(self):
        g = _start_boss("bl_ox", ("j_matador",))
        g.run_hand_counts["Pair"] = 5   # make Pair the most-played hand
        g.dollars = 50
        g.hand = [Card(10, "Spades"), Card(10, "Hearts")]
        g.deck = []
        g.step({"type": "play", "cards": [0, 1]})
        # The Ox zeroes money, then Matador pays $8 on top (wiki ordering).
        assert g.dollars == 8

    def test_matador_verdant_until_joker_sold(self):
        g = _start_boss("bl_verdant", ("j_matador", "j_joker"))
        g.hand = [Card(10, "Spades")]
        g.deck = []
        g.step({"type": "play", "cards": [0]})
        assert g.dollars == STARTING_MONEY + 8
        # Selling a joker mid-blind lifts Verdant's debuff (game.step handles
        # the lift) — Matador stops paying.
        sell_value = g.jokers[1].state.get("sell_value", 2)
        g.step({"type": "sell_joker", "joker_idx": 1})
        assert not g.verdant_debuff
        g.hand = [Card(10, "Spades")]
        g.deck = []
        g.step({"type": "play", "cards": [0]})
        assert g.dollars == STARTING_MONEY + 8 + sell_value

    def test_matador_eye_on_non_scoring_hand(self):
        g = _start_boss("bl_eye", ("j_matador",))
        g.hand = [Card(10, "Spades")]
        g.deck = []
        g.played_hand_types_this_round.add("High Card")
        g.step({"type": "play", "cards": [0]})
        assert g.dollars == STARTING_MONEY + 8

    def test_matador_psychic_non_scoring_hand(self):
        g = _start_boss("bl_psychic", ("j_matador",))
        g.hand = [Card(10, "Spades"), Card(5, "Hearts")]
        g.deck = []
        g.step({"type": "play", "cards": [0, 1]})   # <5 cards: non-scoring
        assert g.dollars == STARTING_MONEY + 8


class TestBlindRewards:
    """M2 P0: flat blind rewards — Small $3 / Big $4 / Boss $5 / Showdown $8."""

    def _beat(self, kind: str) -> BalatroGame:
        g = BalatroGame(seed=1)
        g.ante = 1
        g.blind_idx = {"Small": 0, "Big": 1, "Boss": 2}[kind]
        g._prepare_next_blind()
        g.chips_scored = g.current_blind.chips_target
        g.hands_left = 2
        g.dollars = 10
        g.state = State.ROUND_EVAL
        g._end_round()
        return g

    def test_small_pays_3(self):
        # 10 + $3 reward + 2 hand payouts + $2 interest (10 // 5)
        assert self._beat("Small").dollars == 10 + 3 + 2 + 2

    def test_big_pays_4(self):
        assert self._beat("Big").dollars == 10 + 4 + 2 + 2

    def test_boss_pays_5(self):
        assert self._beat("Boss").dollars == 10 + 5 + 2 + 2

    def test_showdown_boss_pays_8(self):
        g = BalatroGame(seed=1)
        g.ante = 8
        g.blind_idx = 2
        g._prepare_next_blind()
        assert g.current_blind.is_boss
        g.state = State.ROUND_EVAL
        g.hands_left = 0
        g.dollars = 0
        g.chips_scored = g.current_blind.chips_target
        g._end_round()
        assert g.dollars == 8   # Showdown reward only (no hands, no interest)


class TestShopSlots:
    """M2 P0: real shop structure — 2 cdt-polled random slots (Joker 20 /
    Tarot 4 / Planet 4), +1 per Overstock, plus voucher and 2 packs."""

    @staticmethod
    def _random_items(shop):
        return sum(1 for i in shop if i.kind not in ("voucher", "booster"))

    def test_two_random_slots_by_default(self):
        g = BalatroGame(seed=1, rng_mode="seed")
        shop = generate_shop(g)
        assert self._random_items(shop) == 2
        assert sum(1 for i in shop if i.kind == "voucher") == 1
        assert sum(1 for i in shop if i.kind == "booster") == 2

    def test_overstock_adds_one_random_slot(self):
        g = BalatroGame(seed=1, rng_mode="seed")
        apply_voucher(g, "v_overstock")
        assert g.shop_item_slots == 3
        assert self._random_items(generate_shop(g)) == 3

    def test_overstock_plus_adds_two(self):
        g = BalatroGame(seed=1, rng_mode="seed")
        apply_voucher(g, "v_overstock")
        apply_voucher(g, "v_overstock_plus")
        assert g.shop_item_slots == 4
        assert self._random_items(generate_shop(g)) == 4

    def test_cdt_weights_match_real_game(self):
        # 20/28 = 71.4% joker, 4/28 = 14.3% tarot, 4/28 = 14.3% planet.
        from collections import Counter
        g = BalatroGame(seed=1, rng_mode="seed")
        counts = Counter()
        for _ in range(2000):
            counts[_random_shop_item(g).kind] += 1
        total = sum(counts.values())
        assert abs(counts["joker"] / total - 20 / 28) < 0.03
        assert abs(counts["tarot"] / total - 4 / 28) < 0.02
        assert abs(counts["planet"] / total - 4 / 28) < 0.02
        assert counts["spectral"] == 0   # no spectrals without Ghost Deck

    def test_first_shop_pack_is_buffoon(self):
        """The first pack generated in a run is always a normal Buffoon Pack
        (real game: G.GAME.first_shop_buffoon in get_pack)."""
        g = BalatroGame(seed=11, rng_mode="seed")
        shop = generate_shop(g)
        packs = [i for i in shop if i.kind == "booster"]
        assert len(packs) == 2
        assert packs[0].key == "p_buffoon"   # guaranteed normal Buffoon Pack
        assert g.first_shop_buffoon is True

    def test_subsequent_shops_draw_normally(self):
        """Only the first pack of the run is forced to Buffoon; later shops
        draw pack type from the normal pool again."""
        g = BalatroGame(seed=11, rng_mode="seed")
        generate_shop(g)                       # consumes the first-shop flag
        shop2 = generate_shop(g)
        packs = [i for i in shop2 if i.kind == "booster"]
        assert len(packs) == 2
        # seed-11 second shop: first pack is a Celestial, not forced Buffoon
        assert packs[0].key != "p_buffoon"

    def test_first_shop_buffoon_consumes_no_seed_draw(self):
        """The forced Buffoon Pack does not consume a shop_pack draw (the
        real game uses unseeded math.random for the variant), so the second
        pack slot of the first shop gets draw #1 (p_standard_jumbo for seed
        11) — the golden-pin shift captured in test_seed_rng.EXPECTED_SHOP."""
        g = BalatroGame(seed=11, rng_mode="seed")
        shop = generate_shop(g)
        packs = [i for i in shop if i.kind == "booster"]
        assert packs[1].key == "p_standard_jumbo"


class TestShowmanSuppression:
    """M2 P1 #7: the real duplicate-suppression rule — without Showman, any
    Joker/Tarot/Planet/Spectral already in the player's possession is excluded
    from the pool in the Shop and Booster Packs alike (balatro-seed's
    lock-triggered resample on {node_id}_resample{n} nodes). Showman lifts the
    rule entirely, and selling/using a card re-allows it (possession is the
    lock source)."""

    @staticmethod
    def _game_with(seed=11, joker_keys=(), consumables=()):
        g = BalatroGame(seed=seed, rng_mode="seed")
        for k in joker_keys:
            g.jokers.append(JokerInstance(k, game=g))
        g.consumable_hand.extend(consumables)
        return g

    @staticmethod
    def _shop_jokers(g, n=800):
        return {i.key for _ in range(n)
                for i in generate_shop(g) if i.kind == "joker"}

    def test_owned_joker_excluded_from_shop(self):
        g = self._game_with(joker_keys=["j_joker"])
        assert "j_joker" not in self._shop_jokers(g)

    def test_showman_allows_owned_joker_again(self):
        g = self._game_with(joker_keys=["j_ring_master", "j_joker"])
        assert "j_joker" in self._shop_jokers(g)

    def test_sold_joker_can_reappear(self):
        # Possession is the lock source: selling re-allows the card.
        g = self._game_with(joker_keys=["j_joker"])
        g.jokers.pop()
        assert "j_joker" in self._shop_jokers(g)

    def test_owned_tarot_and_planet_excluded_from_shop(self):
        g = self._game_with(consumables=["c_sun", "pl_jupiter"])
        seen = {(i.kind, i.key) for _ in range(600) for i in generate_shop(g)}
        assert ("tarot", "c_sun") not in seen
        assert ("planet", "pl_jupiter") not in seen

    def test_used_consumable_can_reappear(self):
        g = self._game_with(consumables=["c_sun"])
        g.consumable_hand.remove("c_sun")   # used — no longer possessed
        seen = {(i.kind, i.key) for _ in range(600) for i in generate_shop(g)}
        assert ("tarot", "c_sun") in seen

    def test_buffoon_pack_excludes_owned_joker(self):
        g = self._game_with(joker_keys=["j_mystic_summit"])
        seen = set()
        for _ in range(60):
            _open_booster(g, "p_buffoon_jumbo")
            # Buffoon-pack choices are ("joker", key, edition) tuples
            seen.update(c[1] for c in g.booster_choices)
        assert "j_mystic_summit" not in seen

    def test_arcana_pack_excludes_owned_tarot(self):
        g = self._game_with(consumables=["c_sun"])
        _open_booster(g, "p_arcana_jumbo")
        assert len(g.booster_choices) == 5
        assert "c_sun" not in g.booster_choices

    def test_pack_never_repeats_a_card(self):
        # The real game temporarily locks each drawn card until the pack is
        # fully generated, so a pack holds no duplicates (bypassed by Showman).
        for _ in range(40):
            g = self._game_with()
            _open_booster(g, "p_arcana_jumbo")
            assert len(set(g.booster_choices)) == 5

    def test_showman_allows_within_pack_duplicates(self):
        seen_packs = []
        for _ in range(60):
            g = self._game_with(joker_keys=["j_ring_master"])
            _open_booster(g, "p_arcana_jumbo")
            seen_packs.append(g.booster_choices)
        assert any(len(set(p)) < len(p) for p in seen_packs)

    def test_draw_excluding_resamples_on_locked(self):
        from balatro_sim.shop import _draw_excluding
        g = BalatroGame(seed=11, rng_mode="seed")
        got = {_draw_excluding(g.rng, "Tarotsho1", ["a", "b"], {"a"})
               for _ in range(60)}
        assert got == {"b"}

    def test_fully_owned_rarity_falls_back_to_duplicate(self):
        # Owning every Common exhausts the 1000-resample loop; the real game
        # then re-offers a duplicate rather than failing — no crash, valid key.
        from balatro_sim.shop import JOKER_CATALOGUE
        commons = [k for k, v in JOKER_CATALOGUE.items() if v["rarity"] == "Common"]
        g = self._game_with(joker_keys=commons)
        key = random_joker_key(rarity="Common", rng=g.rng, ante=g.ante,
                               source="sho", game=g)
        assert key in commons


class TestBuffoonPackEditions:
    """M2 P1 #9 — Buffoon-pack jokers roll the same edition poll as shop
    jokers (real game: functions.hpp next_joker reads G.GAME.edition_rate for
    every joker regardless of source; mirrored by balatro-seed draws.rs)."""

    @staticmethod
    def _pack_editions(g: BalatroGame, n_packs: int = 60) -> list:
        """Open n Jumbo Buffoon packs, asserting the tuple representation, and
        return every rolled (key, edition) pair."""
        rolled = []
        for _ in range(n_packs):
            _open_booster(g, "p_buffoon_jumbo")
            assert g.booster_choices
            for c in g.booster_choices:
                assert isinstance(c, tuple) and c[0] == "joker" and len(c) == 3
                rolled.append((c[1], c[2]))
        return rolled

    def test_pack_jokers_carry_editions(self):
        """Base edition odds apply to pack jokers: ~2% Foil / 1.4% Holo /
        0.3% Poly / 0.3% Neg, ~96% base (verified over 4800 draws)."""
        from collections import Counter
        g = BalatroGame(seed=1)
        rolled = self._pack_editions(g, n_packs=1200)
        assert len(rolled) == 4800
        counts = Counter(e for _, e in rolled)
        n = len(rolled)
        assert counts["None"] / n > 0.94
        assert 0.02 < counts.get("Foil", 0) / n < 0.06
        assert 0.005 < counts.get("Holographic", 0) / n < 0.04
        assert counts.get("Polychrome", 0) >= 5      # expect ~14
        assert counts.get("Negative", 0) >= 5        # expect ~14

    def test_hone_boosts_pack_editions(self):
        """Hone's 2x edition rate applies to pack jokers too (~8% non-base vs
        ~4% base), with Polychrome's real 3x quirk (~0.9%)."""
        from collections import Counter
        g = BalatroGame(seed=1)
        apply_voucher(g, "v_hone")
        rolled = self._pack_editions(g, n_packs=1200)
        counts = Counter(e for _, e in rolled)
        n = len(rolled)
        non_base = (n - counts["None"]) / n
        assert 0.05 < non_base < 0.12
        assert 0.004 < counts.get("Polychrome", 0) / n < 0.022

    def test_pick_booster_places_edition_joker(self):
        """Picking a Buffoon-pack joker via game.step adds a JokerInstance with
        the rolled edition to the joker slots — never the consumable hand
        (regression for the old string-key misrouting)."""
        g = BalatroGame(seed=11, rng_mode="seed")
        _open_booster(g, "p_buffoon")
        assert g.booster_choices
        key, edition = g.booster_choices[0][1], g.booster_choices[0][2]
        g.state = State.BOOSTER_OPEN
        g.step({"type": "pick_booster", "indices": [0]})
        assert g.state == State.SHOP
        assert len(g.jokers) == 1
        assert g.jokers[0].key == key
        assert g.jokers[0].edition == edition
        assert g.consumable_hand == []

    def test_env_v5_pack_pick_handles_tuple(self):
        """env_v5's legacy pack-open path picks a tuple joker into the slots."""
        from balatro_sim.env_v5 import BalatroSimEnvV5
        env = BalatroSimEnvV5(seed=11)
        g = env.game
        _open_booster(g, "p_buffoon")
        g.state = State.BOOSTER_OPEN
        env._enter_pack_open(g)
        assert env._pack_choices and env._pack_choices[0][0] == "joker"
        _, key, edition = env._pack_choices[0]
        n_jokers = len(g.jokers)
        env._step_pack_open(0)
        assert len(g.jokers) == n_jokers + 1
        assert g.jokers[-1].key == key
        assert g.jokers[-1].edition == edition

    def test_seed_mode_pack_editions_are_deterministic(self):
        """Same seed + same pack → identical (joker, edition) draws; different
        seeds differ (draws come from the edibuf{ante} node)."""
        def open_once(seed):
            g = BalatroGame(seed=seed, rng_mode="seed")
            _open_booster(g, "p_buffoon_jumbo")
            return list(g.booster_choices)
        assert open_once(11) == open_once(11)
        assert open_once(11) != open_once(12)

    def test_pack_never_repeats_joker_key_with_tuples(self):
        """The within-pack duplicate lock keys on the joker KEY (not the
        (key, edition) tuple) — a pack still never holds the same joker twice."""
        for _ in range(60):
            g = BalatroGame(seed=1)
            _open_booster(g, "p_buffoon_jumbo")
            keys = [c[1] for c in g.booster_choices]
            assert len(set(keys)) == len(keys)

    def test_mega_buffoon_is_8_dollars_four_jokers(self):
        """M2 P1 #12 — Mega Buffoon costs $8 (not $10) and holds 4 jokers
        (choose 2), matching the real catalogue (§15: Buffoon 2/4/4 jokers at
        $4/$6/$8, picks 1/1/2). Tag-only in the sim but must be correct."""
        from balatro_sim.shop import BOOSTER_CATALOGUE
        assert BOOSTER_CATALOGUE["p_buffoon_mega"] == ("Mega Buffoon", 8, "joker", 4)
        g = BalatroGame(seed=11, rng_mode="seed")
        _open_booster(g, "p_buffoon_mega")
        assert len(g.booster_choices) == 4
        assert g.booster_picks_remaining == 2
        assert all(isinstance(c, tuple) and c[0] == "joker" and len(c) == 3
                   for c in g.booster_choices)


class TestStandardPackModifiers:
    """M2 P1 #10 — Standard-Pack cards roll the real modifiers (balatro-seed
    draws.rs::next_standard_card / functions.hpp::nextStandardCard):
    Enhancement 40%, Edition Foil 4% / Holographic 2.8% / Polychrome 1.2%
    (never Negative, not boosted by Hone/Glow Up), Seal 20% evenly split."""

    def test_base_modifier_odds(self):
        """Statistical check over 6000 cards: ~40% enhanced, ~4/2.8/1.2%
        editions (no Negative), ~20% sealed with an even 4-way seal split."""
        from collections import Counter
        g = BalatroGame(seed=1)
        n, enh, ed, seal = 6000, 0, 0, 0
        editions: Counter = Counter()
        seals: Counter = Counter()
        enhancements = set()
        for _ in range(n):
            c = _roll_standard_card(g)
            if c.enhancement != "None":
                enh += 1
                enhancements.add(c.enhancement)
            if c.edition != "None":
                ed += 1
                editions[c.edition] += 1
            if c.seal != "None":
                seal += 1
                seals[c.seal] += 1
        assert 0.35 <= enh / n <= 0.45                       # Enhancement 40%
        assert 0.15 <= seal / n <= 0.25                      # Seal 20%
        assert 0.025 <= editions["Foil"] / n <= 0.055        # Foil 4%
        assert 0.015 <= editions["Holographic"] / n <= 0.045  # Holo 2.8%
        assert 0.005 <= editions["Polychrome"] / n <= 0.025   # Poly 1.2%
        assert editions.get("Negative", 0) == 0             # never Negative
        assert enhancements <= {"Bonus", "Mult", "Wild", "Glass", "Steel",
                                "Stone", "Gold", "Lucky"}  # the 8 real ones
        for k in ("Red", "Blue", "Gold", "Purple"):
            assert 0.15 <= seals[k] / seal <= 0.35           # ~even split

    def test_base_cards_cover_all_52(self):
        """The frontsta{ante} base-card pool is the full 52 (rank, suit) set."""
        g = BalatroGame(seed=1)
        seen = {(c.rank, c.suit) for _ in range(6000)
                for c in [_roll_standard_card(g)]}
        assert len(seen) == 52

    def test_pick_through_game_carries_modifiers(self):
        """Buying a Standard Pack and picking a card adds it to the deck with
        its enhancement / edition / seal intact (tuple convention preserved)."""
        g = BalatroGame(seed=11, rng_mode="seed")
        _open_booster(g, "p_standard")
        assert len(g.booster_choices) == 3
        for c in g.booster_choices:
            assert isinstance(c, tuple) and c[0] == "card"
            assert isinstance(c[1], Card)
        card = g.booster_choices[0][1]
        n_deck = len(g.deck)
        g.state = State.BOOSTER_OPEN
        g.step({"type": "pick_booster", "indices": [0]})
        assert g.state == State.SHOP
        assert len(g.deck) == n_deck + 1
        added = g.deck[0]
        assert (added.rank, added.suit) == (card.rank, card.suit)
        assert added.enhancement == card.enhancement
        assert added.edition == card.edition
        assert added.seal == card.seal

    def test_seed_mode_uses_real_nodes(self):
        """Standard-Pack draws come from the real node names (balatro-seed
        node_id.rs): stdset{ante} / Enhancedsta{ante} / frontsta{ante} /
        standard_edition{ante} / stdseal{ante} / stdsealtype{ante}, one
        enhancement-poll + base-card + edition-poll + seal-poll per card."""
        from collections import Counter
        g = BalatroGame(seed=11, rng_mode="seed")
        g.rng.enable_tracing()
        _open_booster(g, "p_standard_jumbo")
        records = g.rng.disable_tracing()
        nodes = Counter(r.node for r in records)
        assert nodes["stdset1"] == 5
        assert nodes["frontsta1"] == 5
        assert nodes["standard_edition1"] == 5
        assert nodes["stdseal1"] == 5
        # enhancement-type / seal-type rolls fire only when a card qualifies
        assert nodes["Enhancedsta1"] + nodes["stdsealtype1"] <= 10
        for name in ("stdset1", "frontsta1", "standard_edition1", "stdseal1"):
            assert [r.seq for r in records if r.node == name] == [1, 2, 3, 4, 5]

    def test_hone_does_not_boost_standard_editions(self):
        """Hone/Glow Up boost Joker editions only — the Standard-Pack edition
        poll has fixed thresholds (the real next_standard_card reads no
        edition_rate), so every standard-card draw is identical with and
        without Hone."""
        def std_draws(hone: bool):
            g = BalatroGame(seed=11, rng_mode="seed")
            if hone:
                g.vouchers.add("v_hone")
            g.rng.enable_tracing()
            _open_booster(g, "p_standard_jumbo")
            records = g.rng.disable_tracing()
            std_nodes = ("stdset1", "Enhancedsta1", "frontsta1",
                         "standard_edition1", "stdseal1", "stdsealtype1")
            return [(r.node, r.seq, r.value, r.method, repr(r.result))
                    for r in records if r.node in std_nodes]
        assert std_draws(True) == std_draws(False)

    def test_duplicates_allowed_within_standard_pack(self):
        """Standard Packs never lock drawn cards — duplicate base cards within
        one pack are expected (unlike every other pack type)."""
        seen = []
        for _ in range(200):
            g = BalatroGame(seed=1)
            _open_booster(g, "p_standard_jumbo")
            seen.append([(c[1].rank, c[1].suit) for c in g.booster_choices])
        assert any(len(set(p)) < len(p) for p in seen)


class TestPackWeights:
    """M2 P2 #13 — Booster-Pack type/size draws are weighted, not uniform,
    using the real rates (wiki Booster Packs page; balatro-seed pools.rs
    PACKS): Arcana/Celestial/Standard 4/2/0.5, Buffoon 1.2/0.6/0.15, Spectral
    0.6/0.3/0.07 (Normal/Jumbo/Mega) — 22.42 total, all sizes shop-legal."""

    @staticmethod
    def _pack_counts(n_shops: int = 2500):
        from collections import Counter
        g = BalatroGame(seed=1)
        counts = Counter()
        for _ in range(n_shops):
            for i in generate_shop(g):
                if i.kind == "booster":
                    counts[i.key] += 1
        return counts, sum(counts.values())

    @staticmethod
    def _family(counts, prefix):
        return sum(v for k, v in counts.items() if k.startswith(prefix))

    def test_shop_pack_rates_match_real_game(self):
        """~5000 pack draws: Standard/Arcana/Celestial each ~29%, Buffoon
        ~8.7%, Spectral ~4.3% (the real 22.42-weight table)."""
        counts, total = self._pack_counts()
        # 29% families (4+2+0.5)/22.42 — ±3% keeps CI flake risk near zero
        for prefix in ("p_standard", "p_arcana", "p_celestial"):
            assert abs(self._family(counts, prefix) / total - 29.0 / 100) < 0.03
        # Buffoon (1.95/22.42 ≈ 8.7%) and Spectral (0.97/22.42 ≈ 4.3%)
        assert abs(self._family(counts, "p_buffoon") / total - 1.95 / 22.42) < 0.02
        assert abs(self._family(counts, "p_spectral") / total - 0.97 / 22.42) < 0.015

    def test_size_split_normal_outweighs_jumbo_outweighs_mega(self):
        """Within every family the Normal weight beats Jumbo beats Mega (4/2/
        0.5, 1.2/0.6/0.15, 0.6/0.3/0.07) — visible over ~5000 draws."""
        counts, total = self._pack_counts()
        for prefix in ("p_standard", "p_arcana", "p_celestial",
                       "p_buffoon", "p_spectral"):
            n = counts[f"{prefix}"]
            j = counts[f"{prefix}_jumbo"]
            m = counts[f"{prefix}_mega"]
            assert n > j > m, f"{prefix}: {n}/{j}/{m} not strictly ordered"

    def test_mega_buffoon_and_standard_are_shop_legal(self):
        """All 15 real packs — including Mega Buffoon (0.15) and Mega
        Standard (0.5) — can appear in the shop (they are tag-grantable AND
        shop-legal in the real game, unlike the old tag-only exclusion)."""
        from balatro_sim.shop import SHOP_PACK_POOL
        assert "p_buffoon_mega" in SHOP_PACK_POOL
        assert "p_standard_mega" in SHOP_PACK_POOL
        counts, _ = self._pack_counts()
        assert counts["p_buffoon_mega"] >= 5    # expect ~27
        assert counts["p_standard_mega"] >= 20  # expect ~89

    def test_shop_pack_draw_is_weighted_choices(self):
        """Seed-mode trace pin: shop-pack slots draw via the weighted
        .choices() on the real shop_pack{ante} node — 15 packs totalling
        22.42 (balatro-seed PACKS) — one draw per slot (the run's first slot
        is the forced Buffoon, which consumes no draw)."""
        g = BalatroGame(seed=11, rng_mode="seed")
        g.rng.enable_tracing()
        generate_shop(g)
        records = g.rng.disable_tracing()
        draws = [r for r in records if r.node == "shop_pack1"]
        assert len(draws) == 1
        assert draws[0].method == "choices"
        assert draws[0].args == (15, 22.42)
