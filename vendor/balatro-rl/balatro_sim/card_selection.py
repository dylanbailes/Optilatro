"""
card_selection.py — Subset enumeration and intent-to-action translation for V7.

The V7 agent picks an intent (PLAY / DISCARD / USE_CONSUMABLE) and then selects
a card subset via learned card scores. This module handles:

1. Enumerating all valid 1-5 card subsets (cached by hand size)
2. Scoring subsets from per-card scores (play = sum of scores, discard = sum of 1-scores)
3. Validating subsets against boss blind restrictions
4. Converting (intent, subset) into game.step()-compatible action dicts
"""
from __future__ import annotations

import itertools
from functools import lru_cache
from typing import Optional

import numpy as np

from .card import Card
from .hand_eval import evaluate_hand

# ════════════════════════════════════════════════════════════════════════════
# Intent constants
# ════════════════════════════════════════════════════════════════════════════

INTENT_PLAY = 0
INTENT_DISCARD = 1
INTENT_USE_CONSUMABLE = 2
N_INTENTS = 3

INTENT_NAMES = {
    INTENT_PLAY: "PLAY",
    INTENT_DISCARD: "DISCARD",
    INTENT_USE_CONSUMABLE: "USE_CONSUMABLE",
}


# ════════════════════════════════════════════════════════════════════════════
# Subset enumeration (cached)
# ════════════════════════════════════════════════════════════════════════════

@lru_cache(maxsize=16)
def enumerate_subsets(n_cards: int) -> list[tuple[int, ...]]:
    """
    All 1-5 card subsets of n_cards, as tuples of indices.
    Cached by n_cards (only 1-8 possible values).

    Returns subsets sorted by size then lexicographic order.

    Examples:
        enumerate_subsets(3) -> [(0,), (1,), (2,), (0,1), (0,2), (1,2), (0,1,2)]
        len(enumerate_subsets(8)) -> 218
    """
    if n_cards <= 0:
        return []
    subsets = []
    for k in range(1, min(6, n_cards + 1)):
        for combo in itertools.combinations(range(n_cards), k):
            subsets.append(combo)
    return subsets


def subset_count(n_cards: int) -> int:
    """Number of valid 1-5 card subsets for n_cards cards."""
    return len(enumerate_subsets(n_cards))


# ════════════════════════════════════════════════════════════════════════════
# Subset scoring
# ════════════════════════════════════════════════════════════════════════════

def compute_subset_logits(card_scores: np.ndarray, subsets: list[tuple[int, ...]],
                          intent: int, temperature: float = 1.0) -> np.ndarray:
    """
    Compute logits for a Categorical distribution over subsets.

    For PLAY intent: logit = sum of card_scores for cards in subset
    For DISCARD intent: logit = sum of (1 - card_scores) for cards in subset
                        (high score = keep, so low score = discard)

    Args:
        card_scores: shape (n_cards,), values in [0, 1] from sigmoid
        subsets: list of index tuples from enumerate_subsets()
        intent: INTENT_PLAY or INTENT_DISCARD
        temperature: softmax temperature (lower = sharper distribution)

    Returns:
        logits: shape (n_subsets,), ready for softmax / Categorical
    """
    n_subsets = len(subsets)
    if n_subsets == 0:
        return np.zeros(0, dtype=np.float32)

    logits = np.zeros(n_subsets, dtype=np.float32)

    if intent == INTENT_PLAY:
        for i, subset in enumerate(subsets):
            logits[i] = sum(card_scores[j] for j in subset)
    elif intent == INTENT_DISCARD:
        for i, subset in enumerate(subsets):
            logits[i] = sum(1.0 - card_scores[j] for j in subset)
    else:
        # USE_CONSUMABLE — no subset needed, return uniform
        logits[:] = 0.0

    if temperature != 1.0 and temperature > 0:
        logits /= temperature

    return logits


# ════════════════════════════════════════════════════════════════════════════
# Boss blind validation
# ════════════════════════════════════════════════════════════════════════════

def validate_play_subset(subset: tuple[int, ...], hand: list[Card],
                         boss_key: str, played_types: set[str]) -> bool:
    """
    Check if a play subset is valid under boss blind restrictions.

    Args:
        subset: card indices to play
        hand: current hand cards
        boss_key: active boss blind key (e.g. "bl_psychic") or ""
        played_types: set of hand types already played this round

    Returns:
        True if the subset can be played, False if boss would reject it.
    """
    if not subset or not hand:
        return False

    cards = [hand[i] for i in subset if i < len(hand)]
    if not cards:
        return False

    # bl_psychic: must play exactly 5 cards
    if boss_key == "bl_psychic" and len(cards) != 5:
        return False

    try:
        hand_type, _ = evaluate_hand(cards)
    except Exception:
        return False

    # bl_eye: can't repeat a hand type
    if boss_key == "bl_eye" and hand_type in played_types:
        return False

    # bl_mouth: must play same type as first play (if any plays made)
    if boss_key == "bl_mouth" and played_types and hand_type not in played_types:
        return False

    return True


def get_valid_play_mask(subsets: list[tuple[int, ...]], hand: list[Card],
                        boss_key: str, played_types: set[str]) -> np.ndarray:
    """
    Return boolean mask over subsets indicating which are valid plays.
    For non-boss or non-restrictive bosses, all subsets are valid.
    """
    n = len(subsets)
    if n == 0:
        return np.zeros(0, dtype=bool)

    # Fast path: most bosses don't restrict subset choice
    if boss_key not in ("bl_psychic", "bl_eye", "bl_mouth"):
        return np.ones(n, dtype=bool)

    mask = np.zeros(n, dtype=bool)
    for i, subset in enumerate(subsets):
        mask[i] = validate_play_subset(subset, hand, boss_key, played_types)

    # Ensure at least one valid option (fallback: best single card)
    if not mask.any():
        mask[0] = True

    return mask


# ════════════════════════════════════════════════════════════════════════════
# Action application
# ════════════════════════════════════════════════════════════════════════════

def apply_action(intent: int, subset: tuple[int, ...],
                 hand: list[Card], game_state) -> dict:
    """
    Convert (intent, subset) into a game.step()-compatible action dict.

    Args:
        intent: INTENT_PLAY, INTENT_DISCARD, or INTENT_USE_CONSUMABLE
        subset: card indices selected by the agent
        hand: current hand cards
        game_state: BalatroGame instance (for validation)

    Returns:
        Action dict for game.step(), e.g.:
        {"type": "play", "cards": [0, 2, 4]}
        {"type": "discard", "cards": [1, 3]}
        {"type": "use_consumable", "consumable_idx": 0, "target_cards": []}
    """
    if intent == INTENT_PLAY:
        # Validate indices are in range
        valid_indices = [i for i in subset if i < len(hand)]
        if not valid_indices:
            valid_indices = [0]  # fallback
        return {"type": "play", "cards": valid_indices}

    elif intent == INTENT_DISCARD:
        valid_indices = [i for i in subset if i < len(hand)]
        if not valid_indices:
            valid_indices = [0]
        return {"type": "discard", "cards": valid_indices}

    elif intent == INTENT_USE_CONSUMABLE:
        return {"type": "use_consumable", "consumable_idx": 0, "target_cards": []}

    else:
        # Unknown intent — fallback to playing first card
        return {"type": "play", "cards": [0]}
