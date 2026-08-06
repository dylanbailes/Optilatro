"""
hand_eval.py — Poker hand evaluation for Balatro.

Supports all 12 hand types including Balatro-specific variants.
Wild cards (Wild enhancement) count as any suit.
Stone cards don't count toward hand type but add chips when scoring.

Hand type priority (highest to lowest):
  Flush Five > Flush House > Five of a Kind > Straight Flush >
  Four of a Kind > Full House > Flush > Straight >
  Three of a Kind > Two Pair > Pair > High Card
"""
from collections import Counter
from typing import Optional
from .card import Card


HAND_PRIORITY = [
    "Flush Five",
    "Flush House",
    "Five of a Kind",
    "Straight Flush",
    "Four of a Kind",
    "Full House",
    "Flush",
    "Straight",
    "Three of a Kind",
    "Two Pair",
    "Pair",
    "High Card",
]


def _effective_suits(cards: list[Card]) -> list[str]:
    """Return suits treating Wild cards as the most common suit."""
    wilds = [c for c in cards if c.enhancement == "Wild"]
    non_wilds = [c for c in cards if c.enhancement != "Wild"]

    if not wilds:
        return [c.suit for c in cards]

    if non_wilds:
        most_common = Counter(c.suit for c in non_wilds).most_common(1)[0][0]
    else:
        most_common = "Spades"

    suits = [c.suit for c in non_wilds] + [most_common] * len(wilds)
    return suits


def _is_flush(cards: list[Card]) -> bool:
    if len(cards) < 5:
        return False
    suits = _effective_suits(cards)
    return len(set(suits)) == 1


def _is_straight(ranks: list[int]) -> bool:
    """Check if sorted unique ranks form a straight (5+ consecutive)."""
    unique = sorted(set(ranks))
    if len(unique) < 5:
        return False
    # Normal straight
    for i in range(len(unique) - 4):
        if unique[i + 4] - unique[i] == 4 and len(unique[i:i+5]) == 5:
            return True
    # Wheel: A-2-3-4-5
    if 14 in unique and all(r in unique for r in [2, 3, 4, 5]):
        return True
    return False


def evaluate_hand(cards: list[Card]) -> tuple[str, list[Card]]:
    """
    Evaluate the best hand type from 1-5 cards.
    Returns (hand_type, scoring_cards) where scoring_cards are the cards
    that contribute to the hand type (for retrigger/seal purposes).

    Stone cards are excluded from hand type evaluation but included in scoring_cards.
    """
    # Separate stone cards (they score but don't contribute to hand type)
    stones = [c for c in cards if c.enhancement == "Stone" and not c.debuffed]
    active = [c for c in cards if c.enhancement != "Stone"]

    if not active:
        return "High Card", cards

    ranks = [c.rank for c in active]
    rank_counts = Counter(ranks)
    freq = Counter(rank_counts.values())

    n = len(active)
    flush = _is_flush(active)
    straight = _is_straight(ranks)

    # Flush Five: 5 cards, all same rank, all same suit
    if n >= 5 and freq.get(5, 0) >= 1 and flush:
        return "Flush Five", active + stones

    # Flush House: Full house where all 5 cards same suit
    if n >= 5 and freq.get(3, 0) >= 1 and freq.get(2, 0) >= 1 and flush:
        return "Flush House", active + stones

    # Five of a Kind: 5 same rank
    if freq.get(5, 0) >= 1:
        rank = [r for r, c in rank_counts.items() if c == 5][0]
        scoring = [c for c in active if c.rank == rank]
        return "Five of a Kind", scoring + stones

    # Straight Flush
    if straight and flush:
        return "Straight Flush", active + stones

    # Four of a Kind
    if freq.get(4, 0) >= 1:
        rank = [r for r, c in rank_counts.items() if c == 4][0]
        scoring = [c for c in active if c.rank == rank]
        return "Four of a Kind", scoring + stones

    # Full House
    if freq.get(3, 0) >= 1 and freq.get(2, 0) >= 1:
        return "Full House", active + stones

    # Flush
    if flush:
        return "Flush", active + stones

    # Straight
    if straight:
        return "Straight", active + stones

    # Three of a Kind
    if freq.get(3, 0) >= 1:
        rank = [r for r, c in rank_counts.items() if c == 3][0]
        scoring = [c for c in active if c.rank == rank]
        return "Three of a Kind", scoring + stones

    # Two Pair
    pairs = [r for r, c in rank_counts.items() if c == 2]
    if len(pairs) >= 2:
        scoring = [c for c in active if c.rank in pairs]
        return "Two Pair", scoring + stones

    # Pair
    if len(pairs) == 1:
        scoring = [c for c in active if c.rank == pairs[0]]
        return "Pair", scoring + stones

    # High Card
    best_rank = max(ranks)
    scoring = [c for c in active if c.rank == best_rank][:1]
    return "High Card", scoring + stones


def best_hand_from_subset(cards: list[Card], play_count: int = 5) -> tuple[str, list[Card]]:
    """
    Find the best hand type achievable by playing `play_count` cards
    from the given set. Tries all combinations.
    """
    from itertools import combinations
    n = min(play_count, len(cards))
    best_type = "High Card"
    best_cards = cards[:1]

    for r in range(1, n + 1):
        for combo in combinations(cards, r):
            hand_type, scoring = evaluate_hand(list(combo))
            if HAND_PRIORITY.index(hand_type) < HAND_PRIORITY.index(best_type):
                best_type = hand_type
                best_cards = list(combo)

    return best_type, best_cards
