"""
base.py — Joker effect protocol, registry, and runtime instance.

Architecture (joker-fidelity refactor R1–R5):

- JOKER_REGISTRY maps a canonical key -> the SINGLETON EFFECT INSTANCE (one
  `_X()` object per joker; all per-run state lives on JokerInstance.state, so
  effect objects are stateless besides class-level config like suit pools).
- Effects are registered with the @register_joker("j_x") decorator, colocated
  with the class. Registering a key twice raises at import time — the
  import-order lottery is impossible, and the audit's DUPES gate is a backup.
- JokerEffect defines EVERY hook as a typed no-op, so dispatch needs no
  `hasattr` probe: JokerInstance.fire("on_x", ...) calls a method that is
  guaranteed to exist. Wrong arities crash loudly at first dispatch (and the
  audit AST-checks signatures).
- Capability flags (JokerEffect.flags) replace engine-side key-string scans:
  scoring/game/shop query `j.has_flag("doubles_lucky")`, never `j.key == "j_oops"`.
- Per-effect STATE_DEFAULTS seed JokerInstance.state, giving every joker a
  known initial state the spec tests can assert and the audit can check.
"""
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Optional, TYPE_CHECKING

import random as _random

from ..seed_rng import CHANCE_NODE

if TYPE_CHECKING:
    from ..game import ScoreContext

JOKER_REGISTRY: dict[str, "JokerEffect"] = {}

# fire() cache sentinel: the effect does not override this hook (the base
# hook is a `...` no-op) — dispatch skips the call entirely.
_NOOP = object()


def full_deck(game) -> list:
    """The run's full deck (undrawn + in-hand + spent). The real game's "full
    deck" counts for jokers like Steel Joker / Driver's License / Stone Joker
    / Glass Joker cover every card in the run, including those currently in
    hand or played — not just the undrawn pile. Empty when no game is attached
    (direct-call tests)."""
    if game is None:
        return []
    return list(game.deck) + list(game.hand) + list(game.spent)


def register_joker(key: str):
    """Decorator: register a joker effect by its canonical game key.

    Raises ValueError on duplicate registration so a second definition of the
    same key can never silently win the import-order lottery.
    """
    def decorator(cls):
        if key in JOKER_REGISTRY:
            raise ValueError(
                f"duplicate joker registration: {key!r} already registered "
                f"as {JOKER_REGISTRY[key]!r} — every key must be defined once"
            )
        JOKER_REGISTRY[key] = cls()
        cls.key = key
        return cls
    return decorator


class JokerEffect:
    """Base class for all joker effects.

    Subclasses override the hooks they care about; the base no-ops keep
    dispatch uniform (`hasattr` is never needed). The first argument to every
    hook is the owning JokerInstance (the effect object itself is a shared
    singleton), so hooks read/write per-run state via `inst.state`.
    """

    #: Capability flags the engine queries instead of key-string scans
    #: (e.g. "doubles_lucky" on Oops! All 6s, "disables_bosses" on Chicot).
    flags: frozenset = frozenset()

    #: Per-run state seeded into JokerInstance.state at construction.
    state_defaults: dict = {}

    # ── Scoring hooks ───────────────────────────────────────────────────────
    def pre_score(self, inst, ctx): ...
    def on_score_card(self, inst, card, ctx): ...
    def on_hand_scored(self, inst, ctx): ...

    # ── Round / blind hooks ─────────────────────────────────────────────────
    def on_discard(self, inst, cards, ctx): ...
    def on_round_end(self, inst, ctx): ...
    def on_blind_selected(self, inst, ctx): ...
    def on_blind_skipped(self, inst, ctx): ...
    def on_boss_beaten(self, inst, ctx): ...
    def on_boss_ability_triggered(self, inst, ctx): ...

    # ── Shop / acquisition hooks ────────────────────────────────────────────
    def on_init(self, inst): ...
    def on_sell(self, inst, ctx): ...
    def on_other_sold(self, inst, ctx): ...
    def on_shop_enter(self, inst, ctx): ...
    def on_shop_leave(self, inst, ctx): ...
    def on_reroll(self, inst, ctx): ...
    def on_booster_opened(self, inst, ctx): ...
    def on_booster_skipped(self, inst, ctx): ...

    # ── Consumable / card-lifecycle hooks ───────────────────────────────────
    def on_planet_used(self, inst, planet_name): ...
    def on_tarot_used(self, inst, tarot_key): ...
    def on_lucky_trigger(self, inst, ctx): ...
    def on_card_added(self, inst, ctx): ...
    def on_card_destroyed(self, inst, card, ctx): ...

    # ── Game-state passives (replaces key-scans in game._start_blind) ───────
    def passives(self, inst) -> dict:
        """Constant-while-owned game modifiers, e.g. {"hand_size": +1},
        {"discards": +1}, {"hands": -1}. Summed by game._start_blind."""
        return {}


@dataclass
class ScoreContext:
    """Passed to joker trigger functions. Mutated as jokers fire."""
    chips: float = 0.0
    mult: float = 0.0
    mult_mult: float = 1.0      # Multiplicative mult (xMult jokers)
    hand_type: str = ""
    scoring_cards: list = field(default_factory=list)
    all_cards: list = field(default_factory=list)   # full hand (including non-scoring)
    held_cards: list = field(default_factory=list)  # cards still held in hand after the play
    jokers: list = field(default_factory=list)
    hands_left: int = 0
    discards_left: int = 0
    dollars: int = 0
    ante: int = 1
    deck_remaining: int = 0
    planet_levels: dict = field(default_factory=dict)   # hand_type -> level

    # ── Retrigger system ──────────────────────────────────────────────────────
    # Maps scoring_card index -> extra retrigger count (0 = score once, 1 = twice, etc.)
    card_retriggers: dict = field(default_factory=dict)

    # ── Hand eval modification flags (set by jokers before scoring) ───────────
    all_face_cards: bool = False        # Pareidolia: treat all cards as face cards
    four_finger_mode: bool = False      # FourFingers: Flush/Straight valid with 4 cards
    smear_suits: bool = False           # SmearedJoker: Hearts=Diamonds, Spades=Clubs
    all_scoring_mode: bool = False      # Splash: all played cards score
    shortcut_mode: bool = False         # Shortcut: straights allow 1-rank gaps

    # ── Pending side-effects (collected, applied post-score) ─────────────────
    pending_money: int = 0             # dollars to award after round
    prevent_loss: bool = False         # Mr. Bones
    # created rewards: real consumable keys, or ("joker"|"card"|"hand_card", ...)
    # object tuples — materialized by game._grant_pending (M1 B1)
    pending_consumables: list = field(default_factory=list)
    destroyed: list = field(default_factory=list)  # Glass cards shattered this hand

    # The game driving this hand — lets scoring-time code (Lucky card) and
    # joker probability triggers reach the game's RNG source. None when built
    # directly (tests): fall back to module random, as before.
    game: Optional[object] = None

    @property
    def n_jokers(self) -> int:
        return len(self.jokers)

    def is_face_card(self, card) -> bool:
        """Respects Pareidolia flag."""
        return self.all_face_cards or card.is_face_card


class JokerInstance:
    """
    A joker in the player's joker slots.
    Holds the joker key, runtime state (ability.mult, extra, etc.), and edition.
    Resolves its effect object once at construction (no per-call registry
    lookups) and seeds state from the effect's STATE_DEFAULTS.
    """

    def __init__(self, key: str, edition: str = "None", game=None,
                 state=None):
        self.key = key
        self.edition = edition
        self.game = game        # owning BalatroGame (for per-node RNG); None in tests
        self.effect: JokerEffect = JOKER_REGISTRY.get(key)  # type: ignore[assignment]
        if self.effect is None:
            raise KeyError(f"no effect registered for joker key {key!r}")
        if state is not None:
            # Caller-supplied state (eval oracle): already an isolated copy
            # (R4) — skip the state_defaults deepcopy it would replace.
            self.state: dict = state
        else:
            # Deep-copied: state_defaults may hold mutable values (sets,
            # dicts), and the effect object is a shared singleton — each
            # instance must get its own copy (R4).
            self.state: dict = deepcopy(self.effect.state_defaults)
        self._hook_cache: dict = {}

    def chance(self):
        """RNG for probability triggers: the game's per-node 'chance' source
        (deterministic per seed in seed mode); module random when the joker was
        constructed without a game (direct-call tests / legacy)."""
        if self.game is not None:
            return self.game.rng.node(CHANCE_NODE)
        return _random

    def fire(self, hook: str, *args):
        """Dispatch a hook to this joker's effect (base class guarantees the
        method exists — no hasattr probe). The bound hook is cached per
        instance: `getattr(effect, hook)` was ~450k dict lookups per run for
        the same methods (fire is the engine's hottest dispatch path). Base
        hooks are `...` no-ops, so an effect that doesn't override a hook
        gets the NOOP sentinel and the call is skipped entirely — most
        (joker, hook) pairs are unoverridden and the Python call frame is
        the real cost (~1.3M fires/run)."""
        m = self._hook_cache.get(hook)
        if m is None:
            raw = getattr(self.effect, hook)
            m = raw if raw.__func__ is not getattr(JokerEffect, hook) else _NOOP
            self._hook_cache[hook] = m
        if m is _NOOP:
            return
        m(self, *args)

    def has_flag(self, flag: str) -> bool:
        """Capability check used by the engine instead of key-string scans."""
        return flag in self.effect.flags

    # ── Convenience wrappers (kept for tests / external callers) ────────────
    def on_score_card(self, card, ctx: ScoreContext):
        self.fire("on_score_card", card, ctx)

    def on_hand_scored(self, ctx: ScoreContext):
        self.fire("on_hand_scored", ctx)

    def on_discard(self, cards, ctx: ScoreContext):
        self.fire("on_discard", cards, ctx)

    def on_round_end(self, ctx: ScoreContext):
        self.fire("on_round_end", ctx)

    def __repr__(self):
        return f"Joker({self.key}, state={self.state}, ed={self.edition})"
