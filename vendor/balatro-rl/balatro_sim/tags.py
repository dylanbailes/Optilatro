"""
tags.py — The 24 real skip-blind Tags (Balatro 1.0 tag set).

A Tag is the reward for skipping a non-Boss blind. In the real game the tag is
drawn when the blind is reached (shown on the skip button), then activated by
clicking it in the next shop. This sim auto-applies the tag at skip time — the
agent still owns the real strategic decision (which blinds to skip), and the
tag itself is observable in the RL observation space before the skip choice.

Effects split into three kinds:
  "instant"  — applied immediately at skip time (money, packs, upgrades, jokers)
  "shop"     — a one-shot modifier consumed by the next shop generation
               (Coupon, D6, free-rarity/free-edition jokers, Voucher Tag)
  "queue"    — pending state resolved later (Investment after Boss, Boss Tag
               reroll, Juggle next round, Double Tag copy)

Ante gating: 9 tags only enter the pool at Ante 2+ (weight 0 at Ante 1), matching
the real game's per-tag `weight = 0` unlock rules. The edition tags (Foil /
Holographic / Polychrome / Negative) are discovery-gated in the real game; the
sim treats the collection as complete, so they are available from Ante 1.
"""
from __future__ import annotations

from typing import Optional

from .seed_rng import node_tag

# Canonical poker-hand order (matches game.py's tie-break: High Card first).
_HAND_TYPES = [
    "High Card", "Pair", "Two Pair", "Three of a Kind", "Straight", "Flush",
    "Full House", "Four of a Kind", "Straight Flush", "Five of a Kind",
    "Flush House", "Flush Five",
]

# key -> (name, min_ante, kind)
TAG_CATALOGUE = {
    "t_uncommon":      ("Uncommon Tag", 1, "shop"),
    "t_rare":          ("Rare Tag", 1, "shop"),
    "t_investment":    ("Investment Tag", 1, "queue"),
    "t_voucher":       ("Voucher Tag", 1, "shop"),
    "t_boss":          ("Boss Tag", 1, "queue"),
    "t_speed":         ("Speed Tag", 1, "instant"),
    "t_economy":       ("Economy Tag", 1, "instant"),
    "t_coupon":        ("Coupon Tag", 1, "shop"),
    "t_d6":            ("D6 Tag", 1, "shop"),
    "t_double":        ("Double Tag", 1, "queue"),
    "t_juggle":        ("Juggle Tag", 1, "queue"),
    "t_foil":          ("Foil Tag", 1, "shop"),
    "t_holographic":   ("Holographic Tag", 1, "shop"),
    "t_polychrome":    ("Polychrome Tag", 1, "shop"),
    "t_charm":         ("Charm Tag", 1, "instant"),      # free Mega Arcana pack
    "t_buffoon":       ("Buffoon Tag", 2, "instant"),    # free Mega Buffoon pack
    "t_ethereal":      ("Ethereal Tag", 2, "instant"),   # free Spectral pack
    "t_meteor":        ("Meteor Tag", 2, "instant"),     # free Mega Celestial pack
    "t_standard":      ("Standard Tag", 2, "instant"),   # free Mega Standard pack
    "t_top_up":        ("Top-up Tag", 2, "instant"),     # up to 2 Common jokers
    "t_garbage":       ("Garbage Tag", 2, "instant"),    # $1 per unused discard this run
    "t_handy":         ("Handy Tag", 2, "instant"),      # $1 per played hand this run
    "t_orbital":       ("Orbital Tag", 2, "instant"),    # +3 levels to highest hand
    "t_negative":      ("Negative Tag", 2, "shop"),
}

TAG_ORDER = sorted(TAG_CATALOGUE)
TAG_NAMES = {k: v[0] for k, v in TAG_CATALOGUE.items()}

# All tags currently weight 1. The real game weights the discovery-gated
# edition tags at 0 until discovered (the sim treats the collection as
# complete), and a few tags carry non-uniform weights in game data. Once
# balatro-seed pins the real tag weights, replace this table to make the
# "Tag{ante}" weighted pick bit-exact for seed replay — the draw count is
# already correct (one pseudorandom_element call per blind).
TAG_WEIGHTS = {k: 1.0 for k in TAG_ORDER}

# Tag → free booster pack key (tag-only Mega packs live in shop.py's catalogue
# but are excluded from the normal shop booster pool).
_TAG_PACK = {
    "t_charm":    "p_arcana_mega",
    "t_buffoon":  "p_buffoon_mega",
    "t_ethereal": "p_spectral",
    "t_meteor":   "p_celestial_mega",
    "t_standard": "p_standard_mega",
}


def roll_tag(game) -> Optional[str]:
    """Roll the skip-blind Tag offered for the current blind.

    Boss blinds offer no tag (they cannot be skipped). The draw mirrors the
    real game's weighted `pseudorandom_element` over the eligible tag pool on
    the per-node "Tag{ante}" stream — a single draw. All base tag weights are 1.
    """
    if getattr(game.current_blind, "is_boss", False):
        return None
    eligible = [k for k in TAG_ORDER if TAG_CATALOGUE[k][1] <= game.ante]
    if not eligible:
        return None
    node = game.rng.node(node_tag(game.ante))
    return node.choices(eligible, weights=[TAG_WEIGHTS[k] for k in eligible], k=1)[0]


def apply_tag(game, key: str) -> None:
    """Apply a Tag's effect immediately (auto-apply on blind skip)."""
    if key == "t_economy":
        # Economy Tag: doubles your money if it is below $40, otherwise adds
        # $40 (gain capped at +$40 — real game: "Doubles your money (Max of
        # $40)"; wiki: below $40 doubled, else +$40). A negative balance is
        # zeroed (the tag wastes on debt — wiki note), never left negative.
        if game.dollars < 0:
            game.dollars = 0
        elif game.dollars < 40:
            game.dollars *= 2
        else:
            game.dollars += 40
    elif key == "t_speed":
        # Speed Tag: $5 per skipped Blind this run (counts this skip)
        game.dollars += 5 * game.skipped_blinds
    elif key == "t_garbage":
        # Garbage Tag: $1 per unused discard this run
        game.dollars += game.run_unused_discards
    elif key == "t_handy":
        # Handy Tag: $1 per played hand this run
        game.dollars += game.run_hands_played
    elif key == "t_orbital":
        # Orbital Tag: +3 levels to the highest-leveled hand (deterministic —
        # the real game shows the hand on the tag; the highest level is the
        # choice that best matches its visible behavior)
        best = max(
            game.planet_levels,
            key=lambda h: (game.planet_levels[h], _HAND_TYPES.index(h)),
        )
        game.planet_levels[best] += 3
    elif key == "t_top_up":
        # Top-up Tag: create up to 2 Common Jokers (must have room)
        _add_topup_jokers(game)
    elif key in _TAG_PACK:
        # Free-pack tags: open the pack immediately; the agent picks from it
        # before entering the shop.
        _open_pack_tag(game, _TAG_PACK[key])
    elif key == "t_coupon":
        game.pending_coupon = True          # next shop: cards + packs free
    elif key == "t_d6":
        game.pending_reroll_free = True     # next shop: rerolls start at $0
    elif key == "t_uncommon":
        game.pending_free_rarity = "Uncommon"
    elif key == "t_rare":
        game.pending_free_rarity = "Rare"
    elif key == "t_foil":
        game.pending_free_edition = "Foil"
    elif key == "t_holographic":
        game.pending_free_edition = "Holographic"
    elif key == "t_polychrome":
        game.pending_free_edition = "Polychrome"
    elif key == "t_negative":
        game.pending_free_edition = "Negative"
    elif key == "t_voucher":
        game.pending_voucher = True         # next shop: extra voucher slot
    elif key == "t_investment":
        game.investment_pending = True      # +$25 after defeating the next Boss
    elif key == "t_boss":
        game.boss_reroll_pending = True     # reroll the next Boss Blind
    elif key == "t_juggle":
        game.hand_size_bonus_next_round = 3
    elif key == "t_double":
        game.double_tag_active = True       # copy of the next selected tag


def _add_topup_jokers(game) -> None:
    from .shop import random_joker_key

    for _ in range(2):
        key = random_joker_key(rarity="Common", rng=game.rng,
                               ante=game.ante, source="top", game=game)
        j = game.grant_joker(key, "None")   # single acquisition path (R5)
        if j is None:
            break
        j.state["sell_value"] = 3


def _open_pack_tag(game, booster_key: str) -> None:
    """Queue a free-pack Tag booster.

    Packs are queued in game.pending_packs so a doubled pack tag (Double Tag
    copying a pack tag) grants BOTH packs. The skip flow opens the first pack
    (game._skip_blind); each subsequent pack opens after the previous one is
    resolved (game._pick_booster)."""
    game.pending_packs.append(booster_key)
    game._shop_after_pack = True


def _open_next_pack(game) -> None:
    """Open the next queued free-pack booster, if any."""
    from .shop import _open_booster
    from .game import State

    if game.pending_packs:
        _open_booster(game, game.pending_packs.pop(0))
        game.state = State.BOOSTER_OPEN
