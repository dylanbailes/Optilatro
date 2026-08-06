"""
quality.py — Loadout quality estimator for V5 shop agent auxiliary reward.

loadout_quality(jokers, planet_levels, deck) -> float

Higher = better joker loadout. Used to give the shop agent a dense reward signal
at the end of each shop phase, shortening credit horizon vs waiting for blind clears.
"""
from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .card import Card
    from .jokers.base import JokerInstance

# Rarity weights
RARITY_WEIGHTS: dict[str, float] = {
    "common":    0.5,
    "uncommon":  1.0,
    "rare":      2.0,
    "legendary": 4.0,
}

# Synergy pairs: (key1, key2) -> bonus score
# key2 can be a string key or the sentinel ANY_RARE
ANY_RARE = "__any_rare__"

SYNERGY_REGISTRY: dict[tuple[str, str], float] = {
    ("j_green_joker",   "j_burglar"):      2.5,  # extra hands -> mult scaling
    ("j_green_joker",   "j_space_joker"):  2.0,  # extra hands -> level up
    ("j_burglar",       "j_space_joker"):  1.5,  # extra hands + leveling
    ("j_blueprint",     ANY_RARE):         2.0,  # blueprint copies any rare
    ("j_brainstorm",    ANY_RARE):         2.0,  # brainstorm copies any rare
    ("j_ride_the_bus",  "j_red_card"):     1.5,  # scaling + bonus mult
    ("j_runner",        "j_shortcut"):     1.5,  # straight scaling
    ("j_fibonacci",     "j_hack"):         2.0,  # retrigger on odd ranks
    ("j_dusk",          "j_hack"):         1.5,  # retrigger synergy
    ("j_supernova",     "j_space_joker"):  1.5,  # play count -> hand leveling
    ("j_ice_cream",     "j_popcorn"):      1.0,  # both decay, stack while fresh
}


def loadout_quality(
    jokers: list,
    planet_levels: list[int],
    deck: list,
) -> float:
    """
    Estimate the quality of the current joker loadout.

    Args:
        jokers: list of JokerInstance objects (have .key and .rarity attributes)
        planet_levels: list of 12 ints, one per hand type (current level)
        deck: list of Card objects (have .enhancement and .edition attributes)

    Returns:
        float quality score (higher is better, no upper bound)
    """
    score = 0.0
    joker_keys = set()

    # 1. Rarity bonus
    for j in jokers:
        rarity = getattr(j, "rarity", "common") or "common"
        score += RARITY_WEIGHTS.get(rarity, 0.5)
        joker_keys.add(getattr(j, "key", ""))

    has_rare = any(
        (getattr(j, "rarity", "") in ("rare", "legendary"))
        for j in jokers
    )

    # 2. Synergy bonuses
    for (k1, k2), bonus in SYNERGY_REGISTRY.items():
        if k1 not in joker_keys:
            continue
        if k2 == ANY_RARE:
            if has_rare:
                score += bonus
        elif k2 in joker_keys:
            score += bonus

    # 3. Planet level bonus — each level above 1 is hard to achieve
    for lv in planet_levels:
        score += max(0, lv - 1) * 0.3

    # 4. Deck quality — enhanced or edited cards improve scoring
    for card in deck:
        enhancement = getattr(card, "enhancement", None)
        edition = getattr(card, "edition", None)
        if enhancement or edition:
            score += 0.1

    return score
