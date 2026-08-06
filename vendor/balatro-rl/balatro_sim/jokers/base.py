"""
base.py — Joker base class and registry.
"""
from dataclasses import dataclass, field
from typing import Callable, Optional, TYPE_CHECKING

import random as _random

from ..seed_rng import CHANCE_NODE

if TYPE_CHECKING:
    from ..game import ScoreContext

JOKER_REGISTRY: dict[str, "JokerInstance"] = {}


def register_joker(key: str):
    """Decorator to register a joker effect by its game key (e.g. 'j_joker')."""
    def decorator(cls):
        JOKER_REGISTRY[key] = cls
        cls.key = key
        return cls
    return decorator


@dataclass
class ScoreContext:
    """Passed to joker trigger functions. Mutated as jokers fire."""
    chips: float = 0.0
    mult: float = 0.0
    mult_mult: float = 1.0      # Multiplicative mult (xMult jokers)
    hand_type: str = ""
    scoring_cards: list = field(default_factory=list)
    all_cards: list = field(default_factory=list)   # full hand (including non-scoring)
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

    # ── Pending side-effects (collected, applied post-score) ─────────────────
    pending_money: int = 0             # dollars to award after round
    prevent_loss: bool = False         # Mr. Bones
    pending_consumables: list = field(default_factory=list)  # created tarots/planets

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
    """
    def __init__(self, key: str, edition: str = "None", game=None):
        self.key = key
        self.edition = edition
        self.state: dict = {}   # runtime state (e.g. {"mult": 0} for scaling jokers)
        self.game = game        # owning BalatroGame (for per-node RNG); None in tests

    def chance(self):
        """RNG for probability triggers: the game's per-node 'chance' source
        (deterministic per seed in seed mode); module random when the joker was
        constructed without a game (direct-call tests / legacy).
        """
        if self.game is not None:
            return self.game.rng.node(CHANCE_NODE)
        return _random

    def on_score_card(self, card, ctx: ScoreContext):
        """Fires for each scoring card."""
        effect = JOKER_REGISTRY.get(self.key)
        if effect and hasattr(effect, "on_score_card"):
            effect.on_score_card(self, card, ctx)

    def on_hand_scored(self, ctx: ScoreContext):
        """Fires after all scoring cards processed."""
        effect = JOKER_REGISTRY.get(self.key)
        if effect and hasattr(effect, "on_hand_scored"):
            effect.on_hand_scored(self, ctx)

    def on_discard(self, cards, ctx: ScoreContext):
        effect = JOKER_REGISTRY.get(self.key)
        if effect and hasattr(effect, "on_discard"):
            effect.on_discard(self, cards, ctx)

    def on_round_end(self, ctx: ScoreContext):
        effect = JOKER_REGISTRY.get(self.key)
        if effect and hasattr(effect, "on_round_end"):
            effect.on_round_end(self, ctx)

    def __repr__(self):
        return f"Joker({self.key}, state={self.state}, ed={self.edition})"
