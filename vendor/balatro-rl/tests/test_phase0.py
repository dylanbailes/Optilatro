"""test_phase0.py — Phase 0 fidelity fixes (2026-08-06).

Covers:
  1. Dead shop jokers — Supernova registered with its real effect (+Mult per
     run-play-count), Oops! All 6s registered under its catalogue key (j_oops),
     Ring Master corrected to real "Showman" semantics (no-op in this sim).
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
from balatro_sim.shop import sell_joker, generate_shop, _random_shop_item
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
        assert "j_oops_all_sixes" in JOKER_REGISTRY

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
        g = self._play_glass(0.99)     # >= 0.25 -> survives, returns to deck later
        assert self._glass_anywhere(g)
        assert any(c.enhancement == "Glass" for c in g.spent)

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
