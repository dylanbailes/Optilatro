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
from balatro_sim.shop import sell_joker


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

    def test_matador_earns_8_on_start_boss(self):
        g = _start_boss("bl_goad", ("j_matador",))
        assert g.dollars == STARTING_MONEY + 8

    def test_matador_pays_per_hand_on_crimson(self):
        g = _start_boss("bl_crimson", ("j_matador",))
        assert g.dollars == STARTING_MONEY   # no start payout for in-play boss
        g.hand = [Card(10, "Spades")]
        g.deck = []
        g.step({"type": "play", "cards": [0]})
        assert g.dollars == STARTING_MONEY + 8
