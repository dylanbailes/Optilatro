"""
consumables.py — Planet, Tarot, and Spectral card definitions and apply logic.

Usage:
    from balatro_sim.consumables import apply_planet, apply_tarot, apply_spectral
    apply_planet(game, "pl_mercury")           # Pair +1 level
    apply_tarot(game, "c_hermit")              # Double money
    apply_tarot(game, "c_star", target_indices=[0, 1, 2])  # 3 cards → Diamonds
"""
from __future__ import annotations
from .seed_rng import CHANCE_NODE
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .game import BalatroGame

# ════════════════════════════════════════════════════════════════════════════
# PLANET CARDS — each upgrades one hand type by 1 level
# ════════════════════════════════════════════════════════════════════════════

PLANET_HAND = {
    "pl_pluto":    "High Card",
    "pl_mercury":  "Pair",
    "pl_uranus":   "Two Pair",
    "pl_venus":    "Three of a Kind",
    "pl_saturn":   "Straight",
    "pl_jupiter":  "Flush",
    "pl_earth":    "Full House",
    "pl_mars":     "Four of a Kind",
    "pl_neptune":  "Straight Flush",
    "pl_planet_x": "Five of a Kind",
    "pl_ceres":    "Flush House",
    "pl_eris":     "Flush Five",
}

PLANET_NAME = {
    "pl_pluto":    "Pluto",
    "pl_mercury":  "Mercury",
    "pl_uranus":   "Uranus",
    "pl_venus":    "Venus",
    "pl_saturn":   "Saturn",
    "pl_jupiter":  "Jupiter",
    "pl_earth":    "Earth",
    "pl_mars":     "Mars",
    "pl_neptune":  "Neptune",
    "pl_planet_x": "Planet X",
    "pl_ceres":    "Ceres",
    "pl_eris":     "Eris",
}

ALL_PLANETS = list(PLANET_HAND.keys())


def apply_planet(game: "BalatroGame", planet_key: str) -> bool:
    """Upgrade the associated hand type by 1 level. Returns True on success."""
    hand = PLANET_HAND.get(planet_key)
    if not hand:
        return False
    game.planet_levels[hand] = game.planet_levels.get(hand, 1) + 1
    # Fire satellite jokers (Satellite / Constellation)
    for j in game.jokers:
        j.fire("on_planet_used", planet_key)
    # Track for the Fool's copy source (tarots + planets, in order) and for
    # Fortune Teller / Constellation
    game.consumables_used.append(planet_key)
    game.planets_used.append(planet_key)
    return True


# ════════════════════════════════════════════════════════════════════════════
# TAROT CARDS — 22 cards + The Fool
# ════════════════════════════════════════════════════════════════════════════

TAROT_NAME = {
    "c_fool":             "The Fool",
    "c_magician":         "The Magician",
    "c_high_priestess":   "The High Priestess",
    "c_empress":          "The Empress",
    "c_emperor":          "The Emperor",
    "c_hierophant":       "The Hierophant",
    "c_lovers":           "The Lovers",
    "c_chariot":          "The Chariot",
    "c_justice":          "Justice",
    "c_hermit":           "The Hermit",
    "c_wheel_of_fortune": "The Wheel of Fortune",
    "c_strength":         "Strength",
    "c_hanged_man":       "The Hanged Man",
    "c_death":            "Death",
    "c_temperance":       "Temperance",
    "c_devil":            "The Devil",
    "c_tower":            "The Tower",
    "c_star":             "The Star",
    "c_moon":             "The Moon",
    "c_sun":              "The Sun",
    "c_judgement":        "Judgement",
    "c_world":            "The World",
}

ALL_TAROTS = list(TAROT_NAME.keys())

# Enhancement each tarot applies to cards (for Magician, Empress, etc.)
TAROT_ENHANCEMENT = {
    "c_magician":    "Lucky",
    "c_empress":     "Mult",
    "c_hierophant":  "Bonus",
    "c_lovers":      "Wild",
    "c_chariot":     "Steel",
    "c_justice":     "Glass",
    "c_devil":       "Gold",
    "c_tower":       "Stone",
}

# Suit each tarot converts cards to
TAROT_SUIT = {
    "c_star":  "Diamonds",
    "c_moon":  "Clubs",
    "c_sun":   "Hearts",
    "c_world": "Spades",
}

# Max cards each card-targeting tarot can affect (reference doc §3 Targets
# column: 1 = single-card tarots like The Lovers, 2 = "1-2" tarots, Death = 2).
# Suit-conversion tarots are handled by the shared TAROT_SUIT branch (up to 3).
TAROT_MAX_TARGETS = {
    "c_magician":    2,
    "c_empress":     2,
    "c_hierophant":  2,
    "c_lovers":      1,
    "c_chariot":     1,
    "c_justice":     1,
    "c_devil":       1,
    "c_tower":       1,
    "c_strength":    2,
    "c_hanged_man":  2,
    "c_death":       2,
}


def apply_tarot(
    game: "BalatroGame",
    tarot_key: str,
    target_indices: list[int] | None = None,
) -> bool:
    """
    Apply a Tarot card effect.

    target_indices: indices into game.hand for card-targeting tarots.
    Returns True on success.
    """
    targets = [game.hand[i] for i in (target_indices or []) if i < len(game.hand)]

    # Enhancement tarots (doc Targets: 1 card or 1-2 cards)
    if tarot_key in TAROT_ENHANCEMENT:
        enh = TAROT_ENHANCEMENT[tarot_key]
        for card in targets[:TAROT_MAX_TARGETS.get(tarot_key, 2)]:
            card.enhancement = enh
        _note_use(game, tarot_key)
        return True

    # Suit conversion tarots (up to 3 cards)
    if tarot_key in TAROT_SUIT:
        suit = TAROT_SUIT[tarot_key]
        for card in targets[:3]:
            card.suit = suit
        _note_use(game, tarot_key)
        return True

    # Special tarots
    if tarot_key == "c_fool":
        # Copy the LAST used Tarot or Planet (The Fool itself excluded — it is
        # never recorded in game.consumables_used, so it can never copy
        # itself; reference doc §3).
        if game.consumables_used:
            game.consumable_hand.append(game.consumables_used[-1])
        _note_use(game, tarot_key)
        return True

    if tarot_key == "c_high_priestess":
        # Create up to 2 random Planet cards, room permitting (doc: "must have
        # room"). The used card is consumed before the effect resolves, so its
        # own slot frees up for the creation.
        for _ in range(2):
            if len(game.consumable_hand) < game.consumable_slots:
                game.consumable_hand.append(game.rng.node(CHANCE_NODE).choice(ALL_PLANETS))
        _note_use(game, tarot_key)
        return True

    if tarot_key == "c_emperor":
        # Create up to 2 random Tarot cards, room permitting (doc: "must have
        # room").
        for _ in range(2):
            if len(game.consumable_hand) < game.consumable_slots:
                game.consumable_hand.append(game.rng.node(CHANCE_NODE).choice(ALL_TAROTS))
        _note_use(game, tarot_key)
        return True

    if tarot_key == "c_hermit":
        # Double money, max $20 gain
        gain = min(game.dollars, 20)
        game.dollars += gain
        _note_use(game, tarot_key)
        return True

    if tarot_key == "c_wheel_of_fortune":
        # 1/4 chance to give random edition to random joker
        if game.jokers and game.rng.node(CHANCE_NODE).random() < 0.25:
            j = game.rng.node(CHANCE_NODE).choice(game.jokers)
            j.edition = game.rng.node(CHANCE_NODE).choice(["Foil", "Holographic", "Polychrome"])
        _note_use(game, tarot_key)
        return True

    if tarot_key == "c_strength":
        # Increase rank of up to 2 cards by 1 (wraps A back to 2)
        for card in targets[:2]:
            card.rank = (card.rank % 14) + 1 if card.rank < 14 else 2
        _note_use(game, tarot_key)
        return True

    if tarot_key == "c_hanged_man":
        # Destroy up to 2 selected cards
        for card in targets[:2]:
            if card in game.hand:
                game.hand.remove(card)
            if card in game.deck:
                game.deck.remove(card)
        _note_use(game, tarot_key)
        return True

    if tarot_key == "c_death":
        # Convert left card to copy of right card (both selected) — rank,
        # suit, enhancement, edition, AND seal (reference doc §3).
        if len(targets) >= 2:
            left, right = targets[0], targets[1]
            left.rank = right.rank
            left.suit = right.suit
            left.enhancement = right.enhancement
            left.edition = right.edition
            left.seal = right.seal
        _note_use(game, tarot_key)
        return True

    if tarot_key == "c_temperance":
        # Give $ equal to total joker sell value (max $50)
        sell_total = sum(j.state.get("sell_value", 2) for j in game.jokers)
        game.dollars += min(sell_total, 50)
        _note_use(game, tarot_key)
        return True

    if tarot_key == "c_judgement":
        # Create a random joker (if slot available)
        from .shop import random_joker_key
        _grant_joker(game, random_joker_key(
            rng=game.rng, ante=game.ante, source="sho", game=game))
        _note_use(game, tarot_key)
        return True

    return False


def _grant_joker(game: "BalatroGame", key: str, edition: str = "None"):
    """Append a new joker and fire its on_init hook (To Do List target,
    Popcorn/Ramen/Ice Cream/Castle initial values). Used by Judgement /
    Wraith / The Soul — every acquisition path must init (M1 B2)."""
    game.grant_joker(key, edition)


def _note_use(game: "BalatroGame", tarot_key: str):
    """Record a tarot use and dispatch on_tarot_used hooks.

    game.consumables_used (the Fool's copy source) records every tarot AND
    planet used, in order — The Fool itself is excluded so it can never copy
    itself (reference doc §3)."""
    if tarot_key != "c_fool":
        game.consumables_used.append(tarot_key)
    game.tarots_used.append(tarot_key)
    _fire_tarot_hooks(game, tarot_key)


def _fire_tarot_hooks(game: "BalatroGame", tarot_key: str):
    """Notify jokers that a Tarot was used (e.g. Fortune Teller)."""
    for j in game.jokers:
        j.fire("on_tarot_used", tarot_key)


# ════════════════════════════════════════════════════════════════════════════
# SPECTRAL CARDS — 18 powerful deck-modifying cards
# ════════════════════════════════════════════════════════════════════════════

SPECTRAL_NAME = {
    "s_familiar":   "Familiar",
    "s_grim":       "Grim",
    "s_incantation":"Incantation",
    "s_talisman":   "Talisman",
    "s_aura":       "Aura",
    "s_wraith":     "Wraith",
    "s_sigil":      "Sigil",
    "s_ouija":      "Ouija",
    "s_ectoplasm":  "Ectoplasm",
    "s_immolate":   "Immolate",
    "s_ankh":       "Ankh",
    "s_deja_vu":    "Deja Vu",
    "s_hex":        "Hex",
    "s_trance":     "Trance",
    "s_medium":     "Medium",
    "s_cryptid":    "Cryptid",
    "s_soul":       "The Soul",
    "s_black_hole": "Black Hole",
}

ALL_SPECTRALS = list(SPECTRAL_NAME.keys())


def apply_spectral(
    game: "BalatroGame",
    spectral_key: str,
    target_indices: list[int] | None = None,
) -> bool:
    """Apply a Spectral card effect. Returns True on success."""
    targets = [game.hand[i] for i in (target_indices or []) if i < len(game.hand)]
    # Observation-only usage tally (every recognized key succeeds — see
    # game._use_consumable's invariant). No RNG, so seed-exactness is safe.
    game.spectrals_used.append(spectral_key)

    if spectral_key == "s_familiar":
        # Destroy 1 held card, add 3 random Enhanced face cards TO HAND
        # (reference doc §5 — the sim previously inserted into the deck).
        if targets:
            _remove_card(game, targets[0])
        from .card import Card
        face_ranks = [11, 12, 13]
        suits = ["Spades", "Hearts", "Clubs", "Diamonds"]
        enhs = ["Bonus", "Mult", "Wild", "Glass", "Steel", "Gold", "Lucky"]
        for _ in range(3):
            c = Card(rank=game.rng.node(CHANCE_NODE).choice(face_ranks),
                     suit=game.rng.node(CHANCE_NODE).choice(suits))
            c.enhancement = game.rng.node(CHANCE_NODE).choice(enhs)
            game.hand.append(c)
        return True

    if spectral_key == "s_grim":
        # Destroy 1 held card, add 2 random Enhanced Aces TO HAND
        if targets:
            _remove_card(game, targets[0])
        from .card import Card
        suits = ["Spades", "Hearts", "Clubs", "Diamonds"]
        enhs = ["Bonus", "Mult", "Wild", "Glass", "Steel", "Gold", "Lucky"]
        for _ in range(2):
            c = Card(rank=14, suit=game.rng.node(CHANCE_NODE).choice(suits))
            c.enhancement = game.rng.node(CHANCE_NODE).choice(enhs)
            game.hand.append(c)
        return True

    if spectral_key == "s_incantation":
        # Destroy 1 held card, add 4 random Enhanced number cards (2-10) TO HAND
        if targets:
            _remove_card(game, targets[0])
        from .card import Card
        suits = ["Spades", "Hearts", "Clubs", "Diamonds"]
        enhs = ["Bonus", "Mult", "Wild", "Glass", "Steel", "Gold", "Lucky"]
        for _ in range(4):
            c = Card(rank=game.rng.node(CHANCE_NODE).randint(2, 10),
                     suit=game.rng.node(CHANCE_NODE).choice(suits))
            c.enhancement = game.rng.node(CHANCE_NODE).choice(enhs)
            game.hand.append(c)
        return True

    if spectral_key == "s_talisman":
        # Add Gold seal to 1 selected card
        for card in targets[:1]:
            card.seal = "Gold"
        return True

    if spectral_key == "s_aura":
        # Add Foil/Holographic/Polychrome to 1 selected PLAYING CARD in hand
        # (reference doc §5 + balatro-rs core/src/spectral.rs — Aura targets a
        # card, NOT a joker; the sim previously had this backwards).
        for card in targets[:1]:
            card.edition = game.rng.node(CHANCE_NODE).choice(
                ["Foil", "Holographic", "Polychrome"]
            )
        return True

    if spectral_key == "s_wraith":
        # Create a random Rare Joker, sets money to $0 (reference doc §5)
        from .shop import random_joker_key
        _grant_joker(game, random_joker_key(
            rarity="Rare", rng=game.rng, ante=game.ante, source="spe",
            game=game))
        game.dollars = 0
        return True

    if spectral_key == "s_sigil":
        # Convert all cards in hand to single random suit
        suit = game.rng.node(CHANCE_NODE).choice(["Spades", "Hearts", "Clubs", "Diamonds"])
        for card in game.hand:
            if card.enhancement != "Stone":
                card.suit = suit
        return True

    if spectral_key == "s_ouija":
        # Convert all cards in hand to single random rank, -1 hand size
        # (PERMANENT — reference doc §5; hand_size resets every blind, so the
        # -1 lives in game.hand_size_mod and is re-applied in _start_blind).
        rank = game.rng.node(CHANCE_NODE).randint(2, 14)
        for card in game.hand:
            if card.enhancement != "Stone":
                card.rank = rank
        game.hand_size_mod -= 1
        game.hand_size = max(1, game.hand_size - 1)
        return True

    if spectral_key == "s_ectoplasm":
        # Add Negative to a random Joker, -1 hand size (PERMANENT) — reference
        # doc §5 + balatro-rs core/src/spectral.rs. No-op with no jokers (the
        # real game has nothing to target; balatro-rs test confirms).
        if game.jokers:
            j = game.rng.node(CHANCE_NODE).choice(game.jokers)
            # A re-targeted already-Negative joker grants NO new slot (the
            # Negative is wasted) — only bump the slot for a fresh target.
            if j.edition != "Negative":
                j.edition = "Negative"
                # The negatived joker no longer occupies a slot (real game),
                # so a future buy has one more slot available.
                game.joker_slots += 1
            game.hand_size_mod -= 1
            game.hand_size = max(1, game.hand_size - 1)
        return True

    if spectral_key == "s_immolate":
        # Destroy 5 random cards in hand, +$20
        shuffled = list(game.hand)
        game.rng.node(CHANCE_NODE).shuffle(shuffled)
        destroy = shuffled[:min(5, len(shuffled))]
        for card in destroy:
            _remove_card(game, card)
        game.dollars += 20
        return True

    if spectral_key == "s_ankh":
        # Copy a random joker, destroy all OTHER jokers — the original SURVIVES
        # alongside its copy (reference doc §5 + balatro-rs: `vec![original,
        # clone]`). The copy strips Negative (real game — same rule as Invisible
        # Joker's copy); the original keeps its edition.
        if game.jokers:
            keep = game.rng.node(CHANCE_NODE).choice(game.jokers)
            from .jokers.base import JokerInstance
            copy_edition = "None" if keep.edition == "Negative" else keep.edition
            copy = JokerInstance(keep.key, copy_edition, game=game)
            copy.state = dict(keep.state)
            game.jokers = [keep, copy]
        return True

    if spectral_key == "s_deja_vu":
        # Add Red seal to 1 selected card
        for card in targets[:1]:
            card.seal = "Red"
        return True

    if spectral_key == "s_hex":
        # Add Polychrome to random joker, destroy all others
        if game.jokers:
            lucky = game.rng.node(CHANCE_NODE).choice(game.jokers)
            lucky.edition = "Polychrome"
            game.jokers = [lucky]
        return True

    if spectral_key == "s_trance":
        # Add Blue seal to 1 selected card
        for card in targets[:1]:
            card.seal = "Blue"
        return True

    if spectral_key == "s_medium":
        # Add Purple seal to 1 selected card
        for card in targets[:1]:
            card.seal = "Purple"
        return True

    if spectral_key == "s_cryptid":
        # Create 2 copies of 1 selected card INTO HAND (reference doc §5 — the
        # sim previously inserted into the deck).
        if targets:
            from .card import Card
            orig = targets[0]
            for _ in range(2):
                c = Card(rank=orig.rank, suit=orig.suit)
                c.enhancement = orig.enhancement
                c.edition = orig.edition
                c.seal = orig.seal
                game.hand.append(c)
        return True

    if spectral_key == "s_soul":
        # Create random Legendary joker (possession-aware: a second Soul can't
        # hand out an already-owned Legendary without Showman — real game).
        from .shop import random_joker_key
        _grant_joker(game, random_joker_key(
            rarity="Legendary", rng=game.rng, ante=game.ante, source="spe",
            game=game))
        return True

    if spectral_key == "s_black_hole":
        # Upgrade every hand type by 1 level
        for hand in list(game.planet_levels.keys()):
            game.planet_levels[hand] = game.planet_levels.get(hand, 1) + 1
        return True

    return False


# ════════════════════════════════════════════════════════════════════════════
# VOUCHERS — passive upgrades purchased in shop
# ════════════════════════════════════════════════════════════════════════════

VOUCHER_NAME = {
    "v_overstock":      "Overstock",       # +1 card slot in shop
    "v_overstock_plus": "Overstock Plus",  # +1 more card slot
    "v_clearance_sale": "Clearance Sale",  # -25% shop prices
    "v_liquidation":    "Liquidation",     # -50% shop prices
    "v_hone":           "Hone",            # 2x foil/holo/poly chance
    "v_glow_up":        "Glow Up",         # 4x foil/holo/poly chance
    "v_reroll_surplus": "Reroll Surplus",  # reroll costs $2 less
    "v_reroll_glut":    "Reroll Glut",     # reroll costs $2 less again
    "v_crystal_ball":   "Crystal Ball",    # +1 consumable slot
    "v_omen_globe":     "Omen Globe",      # any spectral can appear in booster
    "v_telescope":      "Telescope",       # most played hand always has Planet
    "v_observatory":    "Observatory",     # Planet cards give x1.5 mult
    "v_grabber":        "Grabber",         # +1 permanent hand
    "v_nacho_tong":     "Nacho Tong",      # +1 permanent hand again
    "v_wasteful":       "Wasteful",        # +1 permanent discard
    "v_recyclomancy":   "Recyclomancy",    # +1 permanent discard again
    "v_tarot_merchant": "Tarot Merchant",  # shop Tarot weight 4 -> 9.6 (~28.6%)
    "v_tarot_tycoon":   "Tarot Tycoon",    # shop Tarot weight 4 -> 32 (~57.1%)
    "v_planet_merchant":"Planet Merchant", # shop Planet weight 4 -> 9.6
    "v_planet_tycoon":  "Planet Tycoon",   # shop Planet weight 4 -> 32
    "v_magic_trick":    "Magic Trick",     # Playing cards can appear in shop
    "v_illusion":       "Illusion",        # Playing cards can have editions
    "v_hieroglyph":     "Hieroglyph",      # -1 ante, -1 hand per round
    "v_petroglyph":     "Petroglyph",      # -1 ante (stacks with Hieroglyph)
    "v_directors_cut":  "Director's Cut",  # Reroll Boss Blind 1 time per Ante, $10
    "v_paint_brush":    "Paint Brush",     # +1 hand size
    "v_palette":        "Palette",         # +1 hand size again
    "v_seed_money":     "Seed Money",      # interest cap 5 -> $10
    "v_money_tree":     "Money Tree",      # interest cap -> $20
    "v_blank":          "Blank",           # does nothing (unlocks Antimatter)
    "v_antimatter":     "Antimatter",      # +1 joker slot
    "v_retcon":         "Retcon",          # reroll Boss Blind unlimited times
}

# Upgraded vouchers only appear in the shop once their base pair is owned
# (wiki: "only by claiming a Base Voucher can the player then claim the
# corresponding Upgraded Voucher in future shops in the run").
VOUCHER_BASE = {
    "v_overstock_plus":  "v_overstock",
    "v_liquidation":     "v_clearance_sale",
    "v_glow_up":         "v_hone",
    "v_reroll_glut":     "v_reroll_surplus",
    "v_observatory":     "v_telescope",
    "v_nacho_tong":      "v_grabber",
    "v_recyclomancy":    "v_wasteful",
    "v_tarot_tycoon":    "v_tarot_merchant",    "v_planet_tycoon":  "v_planet_merchant",
    "v_illusion":        "v_magic_trick",
    "v_omen_globe":      "v_crystal_ball",
    "v_petroglyph":      "v_hieroglyph",
    "v_retcon":          "v_directors_cut",
    "v_palette":         "v_paint_brush",
    "v_money_tree":      "v_seed_money",
    "v_antimatter":      "v_blank",
}

ALL_VOUCHERS = list(VOUCHER_NAME.keys())


def apply_voucher(game: "BalatroGame", voucher_key: str) -> bool:
    """Apply a voucher's permanent effect. Returns True on success."""
    if voucher_key in game.vouchers:
        return False  # already owned

    game.vouchers.add(voucher_key)

    if voucher_key == "v_overstock":
        game.shop_item_slots += 1
    elif voucher_key == "v_overstock_plus":
        game.shop_item_slots += 1
    elif voucher_key == "v_clearance_sale":
        game.shop_discount = min(game.shop_discount + 0.25, 0.5)
    elif voucher_key == "v_liquidation":
        game.shop_discount = min(game.shop_discount + 0.25, 0.5)
    elif voucher_key == "v_reroll_surplus":
        game.reroll_discount += 2
    elif voucher_key == "v_reroll_glut":
        game.reroll_discount += 2
    elif voucher_key == "v_crystal_ball":
        game.consumable_slots += 1
    elif voucher_key == "v_grabber":
        game.base_hands += 1
        game.hands_left = min(game.hands_left + 1, game.base_hands)
    elif voucher_key == "v_nacho_tong":
        game.base_hands += 1
        game.hands_left = min(game.hands_left + 1, game.base_hands)
    elif voucher_key == "v_wasteful":
        game.base_discards += 1
    elif voucher_key == "v_recyclomancy":
        game.base_discards += 1
    elif voucher_key == "v_hieroglyph":
        game.ante = max(1, game.ante - 1)
        game.base_hands = max(1, game.base_hands - 1)
    elif voucher_key == "v_petroglyph":
        game.ante = max(1, game.ante - 1)
        game.base_discards = max(1, game.base_discards - 1)  # -1 discard each round
    elif voucher_key == "v_paint_brush":
        game.hand_size += 1
    elif voucher_key == "v_palette":
        game.hand_size += 1
    elif voucher_key == "v_directors_cut":
        pass  # reroll the Boss Blind 1x per Ante for $10 — see game._reroll_boss
    elif voucher_key == "v_retcon":
        pass  # reroll the Boss Blind unlimited times for $10 — see game._reroll_boss
    elif voucher_key == "v_hone" or voucher_key == "v_glow_up":
        pass  # shop edition odds boost — applied in shop._roll_edition
    elif voucher_key == "v_omen_globe":
        pass  # 20% Spectral replaces Tarot in Arcana Packs — shop._open_booster
    elif voucher_key == "v_telescope":
        pass  # Celestial Packs always contain the most-played hand's Planet
    elif voucher_key == "v_observatory":
        pass  # Planet cards in the consumable area give X1.5 Mult — scoring
    elif voucher_key in ("v_tarot_merchant", "v_tarot_tycoon",
                         "v_planet_merchant", "v_planet_tycoon"):
        pass  # shop item-type weights — applied in shop._shop_item_weights
    elif voucher_key == "v_magic_trick" or voucher_key == "v_illusion":
        pass  # playing cards in the shop — applied in shop._random_shop_item
    elif voucher_key == "v_seed_money":
        # Reference doc §9 "raises interest cap by $5" = 5 -> 10 (absolute
        # caps, wiki-confirmed: Seed Money $10 / Money Tree $20).
        game.interest_cap = 10
    elif voucher_key == "v_money_tree":
        game.interest_cap = 20
    elif voucher_key == "v_blank":
        pass  # Blank does nothing — unlocks Antimatter via the pair rule
    elif voucher_key == "v_antimatter":
        game.joker_slots += 1

    return True


# ════════════════════════════════════════════════════════════════════════════
# Helpers
# ════════════════════════════════════════════════════════════════════════════

def _remove_card(game: "BalatroGame", card):
    if card in game.hand:
        game.hand.remove(card)
    elif card in game.deck:
        game.deck.remove(card)



