"""
card.py — Card representation.

A Card is immutable in identity (rank/suit) but mutable in state
(debuffed, selected, enhancement, edition, seal).
"""
from dataclasses import dataclass, field
from typing import Optional
from .constants import RANK_CHIPS, RANK_NAMES, SUIT_ID, SUITS


@dataclass
class Card:
    rank: int           # 2-14 (11=J, 12=Q, 13=K, 14=A)
    suit: str           # "Spades" | "Hearts" | "Clubs" | "Diamonds"
    enhancement: str = "None"   # Bonus | Mult | Wild | Glass | Steel | Stone | Gold | Lucky
    edition: str = "None"       # Foil | Holographic | Polychrome | Negative
    seal: str = "None"          # Gold | Red | Blue | Purple
    debuffed: bool = False      # Set by boss blinds (The Goad, The Plant, etc.)
    flipped: bool = False       # Face-down (The Mark): identity hidden from the observation
    id: int = field(default_factory=lambda: Card._next_id())

    _id_counter: int = field(default=0, init=False, repr=False, compare=False)

    # Class-level id counter
    _counter = 0

    @staticmethod
    def _next_id() -> int:
        Card._counter += 1
        return Card._counter

    @property
    def rank_name(self) -> str:
        return RANK_NAMES[self.rank]

    @property
    def suit_id(self) -> int:
        return SUIT_ID[self.suit]

    @property
    def base_chips(self) -> int:
        """Chip contribution of this card when it scores."""
        if self.enhancement == "Stone":
            return 50
        return RANK_CHIPS.get(self.rank, 0)

    @property
    def is_face_card(self) -> bool:
        return self.rank in (11, 12, 13)

    def __repr__(self) -> str:
        e = f"+{self.enhancement}" if self.enhancement != "None" else ""
        ed = f"[{self.edition}]" if self.edition != "None" else ""
        s = f"({self.seal})" if self.seal != "None" else ""
        d = " [DEBUFFED]" if self.debuffed else ""
        return f"{self.rank_name}{self.suit[0]}{e}{ed}{s}{d}"

    def copy(self) -> "Card":
        # __new__-based: identical fields + a fresh id, but avoids the
        # dataclass __init__ machinery (Card.copy is ~200k calls/run on the
        # eval-oracle path). Semantics are byte-identical to the old
        # constructor (flipped defaults to False, as before).
        c = Card.__new__(Card)
        c.rank = self.rank
        c.suit = self.suit
        c.enhancement = self.enhancement
        c.edition = self.edition
        c.seal = self.seal
        c.debuffed = self.debuffed
        c.flipped = False
        c.id = Card._next_id()
        return c


def make_standard_deck() -> list[Card]:
    """Return a fresh 52-card standard deck."""
    cards = []
    for suit in SUITS:
        for rank in range(2, 15):
            cards.append(Card(rank=rank, suit=suit))
    return cards
