"""
shop.py — Shop generation, pricing, buy/sell logic.

The Balatro shop has:
  - 2 Joker slots      (main row)
  - 2 Card slots       (consumable row: planets, tarots)
  - 1 Voucher slot
  - 2 Booster pack slots

Prices:
  Common Joker:    $6    Uncommon: $7    Rare: $8    Legendary: $20
  Planet / Tarot:  $3
  Booster (std):   $4
  Voucher:         $10

Selling jokers: ~50% of buy price (rounded down), minimum $1.
"""
from __future__ import annotations
import random
from dataclasses import dataclass, field
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .game import BalatroGame

from .consumables import (
    ALL_PLANETS, ALL_TAROTS, ALL_SPECTRALS, ALL_VOUCHERS,
    PLANET_NAME, TAROT_NAME, SPECTRAL_NAME, VOUCHER_NAME, VOUCHER_BASE,
    PLANET_HAND,
)
from .seed_rng import (
    node_joker, node_rarity, node_edition, node_tarot, node_planet,
    node_spectral, node_voucher, node_shop_pack, node_stdset, node_cdt,
    MAGIC_CARD_NODE, OMEN_NODE, ILLUSION_NODE,
)
from .constants import ENHANCEMENTS, EDITIONS

# Hand-tier order for Telescope's "higher tier hand" tie-break.
_HAND_TIERS = {h: i for i, h in enumerate([
    "High Card", "Pair", "Two Pair", "Three of a Kind", "Straight", "Flush",
    "Full House", "Four of a Kind", "Straight Flush", "Five of a Kind",
    "Flush House", "Flush Five",
])}

# ════════════════════════════════════════════════════════════════════════════
# JOKER CATALOGUE — all joker keys with rarity and base price
# ════════════════════════════════════════════════════════════════════════════

JOKER_CATALOGUE: dict[str, dict] = {}

def _reg(key, name, rarity, price):
    JOKER_CATALOGUE[key] = {"key": key, "name": name, "rarity": rarity, "price": price}

# Common ($6)
for k, n in [
    ("j_joker","Joker"),("j_greedy_mult","Greedy Joker"),("j_lusty_mult","Lusty Joker"),
    ("j_wrathful_mult","Wrathful Joker"),("j_gluttonous_mult","Gluttonous Joker"),
    ("j_jolly","Jolly Joker"),("j_zany","Zany Joker"),("j_mad","Mad Joker"),
    ("j_crazy","Crazy Joker"),("j_droll","Droll Joker"),("j_sly","Sly Joker"),
    ("j_wily","Wily Joker"),("j_clever","Clever Joker"),("j_devious","Devious Joker"),
    ("j_crafty","Crafty Joker"),("j_half","Half Joker"),("j_stencil","Joker Stencil"),
    ("j_four_fingers","Four Fingers"),("j_mime","Mime"),("j_credit_card","Credit Card"),
    ("j_ceremonial","Ceremonial Dagger"),("j_banner","Banner"),
    ("j_mystic_summit","Mystic Summit"),("j_marble","Marble Joker"),
    ("j_loyalty_card","Loyalty Card"),("j_8_ball","8 Ball"),("j_misprint","Misprint"),
    ("j_dusk","Dusk"),("j_raised_fist","Raised Fist"),("j_chaos","Chaos the Clown"),
    ("j_fibonacci","Fibonacci"),("j_steel_joker","Steel Joker"),
    ("j_scary_face","Scary Face"),("j_abstract","Abstract Joker"),
    ("j_delayed_grat","Delayed Gratification"),("j_hack","Hack"),
    ("j_pareidolia","Pareidolia"),("j_gros_michel","Gros Michel"),
    ("j_even_steven","Even Steven"),("j_odd_todd","Odd Todd"),
    ("j_scholar","Scholar"),("j_business_card","Business Card"),
    ("j_supernova","Supernova"),("j_ride_the_bus","Ride the Bus"),
    ("j_space_joker","Space Joker"),("j_egg","Egg"),("j_burglar","Burglar"),
    ("j_blackboard","Blackboard"),("j_runner","Runner"),("j_ice_cream","Ice Cream"),
    ("j_dna","DNA"),("j_splash","Splash"),("j_blue_joker","Blue Joker"),
    ("j_sixth_sense","Sixth Sense"),("j_constellation","Constellation"),
    ("j_hiker","Hiker"),("j_faceless","Faceless Joker"),
    ("j_green_joker","Green Joker"),("j_superposition","Superposition"),
    ("j_to_do_list","To Do List"),("j_cavendish","Cavendish"),
    ("j_card_sharp","Card Sharp"),("j_red_card","Red Card"),
    ("j_madness","Madness"),("j_square_joker","Square Joker"),
    ("j_seance","Seance"),("j_riff_raff","Riff-Raff"),
    ("j_vampire","Vampire"),("j_shortcut","Shortcut"),
    ("j_hologram","Hologram"),("j_vagabond","Vagabond"),("j_baron","Baron"),
    ("j_cloud_9","Cloud 9"),("j_rocket","Rocket"),("j_obelisk","Obelisk"),
    ("j_midas_mask","Midas Mask"),("j_luchador","Luchador"),
    ("j_gift_card","Gift Card"),("j_turtle_bean","Turtle Bean"),
    ("j_erosion","Erosion"),("j_reserved_parking","Reserved Parking"),
    ("j_flash","Flash Card"),("j_popcorn","Popcorn"),
    ("j_ramen","Ramen"),("j_walkie_talkie","Walkie Talkie"),
    ("j_seltzer","Seltzer"),("j_castle","Castle"),
    ("j_mr_bones","Mr. Bones"),("j_acrobat","Acrobat"),
    ("j_sock_and_buskin","Sock and Buskin"),("j_swashbuckler","Swashbuckler"),
    ("j_troubadour","Troubadour"),("j_certificate","Certificate"),
    ("j_smeared_joker","Smeared Joker"),("j_throwback","Throwback"),
    ("j_hanging_chad","Hanging Chad"),("j_rough_gem","Rough Gem"),
    ("j_bloodstone","Bloodstone"),("j_arrowhead","Arrowhead"),
    ("j_onyx_agate","Onyx Agate"),("j_glass_joker","Glass Joker"),
    ("j_showman","Showman"),("j_flower_pot","Flower Pot"),
    ("j_wee_joker","Wee Joker"),("j_merry_andy","Merry Andy"),
    ("j_oops","Oops! All 6s"),("j_photograph","Photograph"),
    ("j_lucky_cat","Lucky Cat"),("j_baseball","Baseball Card"),
    ("j_bull","Bull"),("j_diet_cola","Diet Cola"),
    ("j_trading_card","Trading Card"),("j_stuntman","Stuntman"),
    ("j_invisible_joker","Invisible Joker"),("j_brainstorm","Brainstorm"),
    ("j_satellite","Satellite"),("j_shoot_the_moon","Shoot the Moon"),
    ("j_drivers_license","Driver's License"),("j_cartomancer","Cartomancer"),
    ("j_astronomer","Astronomer"),("j_burnt_joker","Burnt Joker"),
]:
    _reg(k, n, "Common", 6)

# Uncommon ($7)
for k, n in [
    ("j_abstract","Abstract Joker"),("j_half","Half Joker"),
    ("j_odd_todd","Odd Todd"),("j_ancient","Ancient Joker"),
    ("j_campfire","Campfire"),("j_seeing_double","Seeing Double"),
    ("j_spare_trousers","Spare Trousers"),("j_matador","Matador"),
    ("j_hit_the_road","Hit the Road"),("j_duo","The Duo"),
    ("j_trio","The Trio"),("j_family","The Family"),
    ("j_order","The Order"),("j_tribe","The Tribe"),
]:
    _reg(k, n, "Uncommon", 7)

# Rare ($8)
for k, n in [
    ("j_blueprint","Blueprint"),("j_wee","Wee Joker"),
    ("j_the_duo","The Duo"),("j_the_trio","The Trio"),
    ("j_the_family","The Family"),("j_the_order","The Order"),
    ("j_the_tribe","The Tribe"),("j_stencil","Joker Stencil"),
    ("j_drivers_license","Driver's License"),("j_caino","Caino"),
    ("j_triboulet","Triboulet"),("j_yorick","Yorick"),
    ("j_chicot","Chicot"),("j_perkeo","Perkeo"),
    ("j_flash","Flash Card"),
]:
    _reg(k, n, "Rare", 8)

# Legendary ($20)
for k, n in [
    ("j_caino","Caino"),("j_triboulet","Triboulet"),
    ("j_yorick","Yorick"),("j_chicot","Chicot"),("j_perkeo","Perkeo"),
]:
    _reg(k, n, "Legendary", 20)

RARITY_WEIGHTS = {"Common": 70, "Uncommon": 20, "Rare": 8, "Legendary": 2}

# Real Balatro rarity thresholds (functions.hpp next_joker rarity poll):
# >0.95 rare, >0.7 uncommon, else common. Legendaries never roll in shops —
# they only enter via The Soul spectral card.
_RARITY_BY_POLL = {"3": "Rare", "2": "Uncommon", "1": "Common"}
# Legendary maps to rarity "4" → the real "Joker4" node (which has no
# source/ante suffix — see node_id.rs).
_JOKER_NODE_RARITY = {"Rare": "3", "Uncommon": "2", "Common": "1", "Legendary": "4"}

# Module-level joker ban list. Set by environments (e.g. MP env) to exclude
# specific jokers from shop generation. Standard Ranked multiplayer ruleset
# bans Chicot, Matador, Mr. Bones, Luchador (boss-blind interaction jokers).
BANNED_JOKERS: set[str] = set()


def set_banned_jokers(banned: set[str]):
    """Set the global banned joker list used by shop generation."""
    global BANNED_JOKERS
    BANNED_JOKERS = set(banned)


def clear_banned_jokers():
    """Clear the banned joker list (revert to base game)."""
    global BANNED_JOKERS
    BANNED_JOKERS = set()


def random_joker_key(
    rarity: Optional[str] = None,
    rng=None,
    ante: int = 1,
    source: str = "sho",
) -> str:
    """Pick a random joker key, honoring BANNED_JOKERS.

    rng: an RngSource to draw through (per-node in seed mode), or None to use
    the module-level random (legacy direct-call behavior). When rng is given,
    the draw mirrors Balatro's node scheme: a rarity poll on
    "rarity{ante}{source}" then a pick from that rarity's pool on
    "Joker{1|2|3}{source}{ante}".
    """
    if rng is None:
        if rarity:
            pool = [k for k, v in JOKER_CATALOGUE.items()
                    if v["rarity"] == rarity and k not in BANNED_JOKERS]
            return random.choice(pool) if pool else "j_joker"
        keys = [k for k in JOKER_CATALOGUE.keys() if k not in BANNED_JOKERS]
        weights = [RARITY_WEIGHTS.get(JOKER_CATALOGUE[k]["rarity"], 10) for k in keys]
        if not keys:
            return "j_joker"
        return random.choices(keys, weights=weights, k=1)[0]

    if rarity is None:
        poll = rng.node(node_rarity(source, ante)).random()
        rarity = _RARITY_BY_POLL["3" if poll > 0.95 else ("2" if poll > 0.7 else "1")]
    pool = [k for k, v in JOKER_CATALOGUE.items()
            if v["rarity"] == rarity and k not in BANNED_JOKERS]
    if not pool:
        return "j_joker"
    draw = rng.node(node_joker(_JOKER_NODE_RARITY[rarity], source, ante))
    return draw.choice(pool)


# ════════════════════════════════════════════════════════════════════════════
# SHOP ITEM
# ════════════════════════════════════════════════════════════════════════════

@dataclass
class ShopItem:
    kind: str          # "joker" | "planet" | "tarot" | "spectral" | "voucher" | "booster" | "card"
    key: str
    name: str
    price: int
    edition: str = "None"    # for jokers
    sold: bool = False
    card: Optional["Card"] = None   # Magic Trick: the offered playing card

    def discounted_price(self, discount_frac: float) -> int:
        return max(1, int(self.price * (1 - discount_frac)))


# ════════════════════════════════════════════════════════════════════════════
# SHOP GENERATION
# ════════════════════════════════════════════════════════════════════════════

BOOSTER_CATALOGUE = {
    "p_arcana":        ("Arcana Pack",     4, "tarot",    3),   # 3 tarots, pick 1
    "p_arcana_jumbo":  ("Jumbo Arcana",    6, "tarot",    5),
    "p_arcana_mega":   ("Mega Arcana",     8, "tarot",    5),   # pick 2
    "p_celestial":     ("Celestial Pack",  4, "planet",   3),
    "p_celestial_jumbo":("Jumbo Celestial",6, "planet",   5),
    "p_celestial_mega":("Mega Celestial",  8, "planet",   5),
    "p_spectral":      ("Spectral Pack",   4, "spectral", 2),
    "p_spectral_jumbo":("Jumbo Spectral",  6, "spectral", 4),
    "p_spectral_mega": ("Mega Spectral",   8, "spectral", 4),
    "p_standard":      ("Standard Pack",   4, "card",     3),
    "p_standard_jumbo":("Jumbo Standard",  6, "card",     5),
    "p_buffoon":       ("Buffoon Pack",    4, "joker",    2),
    "p_buffoon_jumbo": ("Jumbo Buffoon",   6, "joker",    4),
    # Tag-only Mega packs (Buffoon/Standard Tags). Kept OUT of the shop pool
    # (SHOP_PACK_POOL below) so the shop booster distribution is unchanged.
    "p_buffoon_mega":  ("Mega Buffoon",   10, "joker",    5),
    "p_standard_mega": ("Mega Standard",   8, "card",     5),
}

# Booster packs that can appear in the shop (real-game pool minus the
# tag-only Mega Buffoon/Standard, which enter only via their Tags).
SHOP_PACK_POOL = [
    k for k in BOOSTER_CATALOGUE
    if k not in ("p_buffoon_mega", "p_standard_mega")
]

def generate_shop(game: "BalatroGame") -> list[ShopItem]:
    """Generate a full shop for the current ante/round.

    Consumes one-shot skip-blind Tag shop modifiers (Coupon / D6 / Uncommon /
    Rare / Foil-Holo-Poly-Negative / Voucher Tags) — they apply to the first
    shop generated after the skipped blind.
    """
    items: list[ShopItem] = []

    # Consume pending tag modifiers (one-shot, apply to THIS shop only)
    coupon = game.pending_coupon
    game.pending_coupon = False
    free_rarity = game.pending_free_rarity
    game.pending_free_rarity = None
    free_edition = game.pending_free_edition
    game.pending_free_edition = None
    voucher_extra = game.pending_voucher
    game.pending_voucher = False
    if game.pending_reroll_free:
        game.pending_reroll_free = False
        game.reroll_cost = 0   # D6 Tag: rerolls in the next shop start at $0

    # Hone / Glow Up: 2x / 4x shop edition odds (Polychrome 3x / 7x)
    edition_boost = (4 if "v_glow_up" in game.vouchers
                     else 2 if "v_hone" in game.vouchers else 1)

    # Joker slots (2 by default)
    for i in range(game.shop_joker_slots):
        if i == 0 and free_rarity:
            # Uncommon/Rare Tag: a free Joker of that rarity
            key = random_joker_key(rarity=free_rarity, rng=game.rng,
                                   ante=game.ante, source="sho")
            info = JOKER_CATALOGUE.get(key, {})
            edition = "None"
            price = 0
        elif i == 0 and free_edition:
            # Foil/Holographic/Polychrome/Negative Tag: free Joker with the edition
            key = random_joker_key(rng=game.rng, ante=game.ante, source="sho")
            info = JOKER_CATALOGUE.get(key, {})
            edition = free_edition
            price = 0
        else:
            key = random_joker_key(rng=game.rng, ante=game.ante, source="sho")
            info = JOKER_CATALOGUE.get(key, {})
            edition = _roll_edition(
                game.rng.node(node_edition("sho", game.ante)), edition_boost)
            price = info.get("price", 6)
            if edition != "None":
                price += _edition_markup(edition)
        items.append(ShopItem("joker", key, info.get("name", key), price, edition))

    # Card slots (2 by default: planets / tarots / spectrals)
    for _ in range(game.shop_card_slots):
        items.append(_random_consumable_item(game))

    # Voucher slot (1; +1 with the Voucher Tag)
    for _ in range(1 + (1 if voucher_extra else 0)):
        voucher_key = _random_voucher(game)
        if voucher_key:
            items.append(ShopItem(
                "voucher", voucher_key,
                VOUCHER_NAME.get(voucher_key, voucher_key), 10
            ))

    # Booster pack slots (2)
    for _ in range(2):
        bkey = game.rng.node(node_shop_pack(game.ante)).choice(SHOP_PACK_POOL)
        bname, bprice, _, _ = BOOSTER_CATALOGUE[bkey]
        items.append(ShopItem("booster", bkey, bname, bprice))

    # Coupon Tag: initial cards and booster packs in the next shop are free
    # (vouchers excluded, matching the real effect)
    if coupon:
        for item in items:
            if item.kind != "voucher":
                item.price = 0

    return items


def _consumable_weights(game: "BalatroGame") -> tuple[list[str], list[int]]:
    """Shop card-slot item pools and weights, shifted by vouchers.

    Base: planets 40 / tarots 50 / spectrals 10 (the real cdt{ante} item-type
    poll). Tarot Merchant 2x / Tarot Tycoon 4x, Planet Merchant 2x / Planet
    Tycoon 4x (multiplicative — a Tycoon requires its Merchant base first).
    Magic Trick / Illusion add a playing-card kind (weight 25)."""
    w_planet, w_tarot, w_spectral, w_card = 40, 50, 10, 0
    v = game.vouchers
    if "v_tarot_merchant" in v:
        w_tarot *= 2
    if "v_tarot_tycoon" in v:
        w_tarot *= 2
    if "v_planet_merchant" in v:
        w_planet *= 2
    if "v_planet_tycoon" in v:
        w_planet *= 2
    if "v_magic_trick" in v or "v_illusion" in v:
        w_card = 25
    pool = ["planet", "tarot", "spectral"]
    weights = [w_planet, w_tarot, w_spectral]
    if w_card:
        pool.append("card")
        weights.append(w_card)
    return pool, weights


def _random_consumable_item(game: "BalatroGame") -> ShopItem:
    """Pick a random planet, tarot, spectral, or (Magic Trick) playing card."""
    pool, weights = _consumable_weights(game)
    kind = game.rng.node(node_cdt(game.ante)).choices(pool, weights)[0]
    ante = game.ante
    if kind == "planet":
        key = game.rng.node(node_planet("sho", ante)).choice(ALL_PLANETS)
        return ShopItem("planet", key, PLANET_NAME.get(key, key), 3)
    elif kind == "tarot":
        key = game.rng.node(node_tarot("sho", ante)).choice(ALL_TAROTS)
        return ShopItem("tarot", key, TAROT_NAME.get(key, key), 3)
    elif kind == "spectral":
        key = game.rng.node(node_spectral("sho", ante)).choice(ALL_SPECTRALS)
        return ShopItem("spectral", key, SPECTRAL_NAME.get(key, key), 4)
    else:
        return _shop_card_item(game)


def _shop_card_item(game: "BalatroGame") -> ShopItem:
    """A playing-card shop item ($4, Magic Trick). Illusion adds an
    enhancement and/or edition (seals are bugged off in the real game)."""
    from .card import Card
    from .constants import RANK_NAMES, SUITS

    node = game.rng.node(MAGIC_CARD_NODE)
    rank = node.randint(2, 14)
    suit = node.choice(SUITS)
    enhancement = edition = "None"
    if "v_illusion" in game.vouchers:
        inode = game.rng.node(ILLUSION_NODE)
        if inode.chance(0.5):
            enhancement = inode.choice([e for e in ENHANCEMENTS if e != "None"])
        if inode.chance(0.5):
            edition = inode.choice([e for e in EDITIONS if e != "None"])
    card = Card(rank, suit, enhancement=enhancement, edition=edition)
    name = f"{RANK_NAMES[rank]} of {suit}"
    return ShopItem("card", f"card_{rank}_{suit}", name, 4, card=card)


def _random_voucher(game: "BalatroGame") -> Optional[str]:
    """Pick a voucher for the shop slot. Upgraded vouchers only appear once
    their base pair is owned (real-game pair-unlock rule)."""
    available = []
    for v in ALL_VOUCHERS:
        if v in game.vouchers:
            continue
        base = VOUCHER_BASE.get(v)
        if base is not None and base not in game.vouchers:
            continue
        available.append(v)
    if not available:
        # Real game falls back to offering Blank repeatedly once every voucher
        # is purchased; the sim just leaves the voucher slot empty.
        return None
    return game.rng.node(node_voucher(game.ante)).choice(available)


def _roll_edition(node=None, boost: float = 1.0) -> str:
    """Edition roll; thresholds match real Balatro (next_joker's edition poll).
    node: a NodeRng to draw through (per-node in seed mode); None → module
    random (legacy direct-call behavior).
    boost: Hone (2) / Glow Up (4) multiply Foil + Holographic appearance;
    Polychrome gets 3x for Hone / 7x for Glow Up (the real game's quirk)."""
    r = node.random() if node is not None else random.random()
    if boost <= 1.0:
        if r < 0.003:   return "Negative"
        if r < 0.006:   return "Polychrome"
        if r < 0.02:    return "Holographic"
        if r < 0.04:    return "Foil"
        return "None"
    poly_boost = 7.0 if boost >= 4.0 else 3.0
    t_poly = 0.003 + 0.003 * poly_boost
    t_holo = t_poly + 0.014 * boost
    t_foil = t_holo + 0.02 * boost
    if r < 0.003:   return "Negative"
    if r < t_poly:  return "Polychrome"
    if r < t_holo:  return "Holographic"
    if r < t_foil:  return "Foil"
    return "None"


def _edition_markup(edition: str) -> int:
    return {"Foil": 2, "Holographic": 3, "Polychrome": 5, "Negative": 5}.get(edition, 0)


# ════════════════════════════════════════════════════════════════════════════
# BUY / SELL LOGIC
# ════════════════════════════════════════════════════════════════════════════

def buy_item(game: "BalatroGame", item: ShopItem) -> bool:
    """
    Attempt to purchase a shop item. Returns True on success.
    Modifies game.dollars, game.jokers, game.consumable_hand as appropriate.
    """
    if item.sold:
        return False

    effective_price = item.discounted_price(game.shop_discount)
    if game.dollars < effective_price:
        return False

    if item.kind == "joker":
        if len(game.jokers) >= game.joker_slots:
            return False
        from .jokers.base import JokerInstance
        j = JokerInstance(item.key, item.edition, game=game)
        j.state["sell_value"] = max(1, effective_price // 2)
        game.jokers.append(j)
        game.dollars -= effective_price
        item.sold = True
        return True

    if item.kind in ("planet", "tarot", "spectral"):
        if len(game.consumable_hand) >= game.consumable_slots:
            return False
        game.consumable_hand.append(item.key)
        game.dollars -= effective_price
        item.sold = True
        return True

    if item.kind == "voucher":
        from .consumables import apply_voucher
        if apply_voucher(game, item.key):
            game.dollars -= effective_price
            item.sold = True
            return True
        return False

    if item.kind == "card":
        # Magic Trick: buying a playing card adds it to the run deck
        if item.card is None:
            return False
        game.deck.insert(0, item.card)
        game.dollars -= effective_price
        item.sold = True
        return True

    if item.kind == "booster":
        game.dollars -= effective_price
        item.sold = True
        _open_booster(game, item.key)
        from .game import State
        game.state = State.BOOSTER_OPEN   # agent picks from the pack next
        return True

    return False


def sell_joker(game: "BalatroGame", joker_idx: int) -> int:
    """Sell joker at index. Returns dollars gained (0 if invalid)."""
    if joker_idx < 0 or joker_idx >= len(game.jokers):
        return 0
    j = game.jokers.pop(joker_idx)
    sell_value = j.state.get("sell_value", 2)
    game.dollars += sell_value
    # Fire on_sell hooks
    effect = _get_effect(j.key)
    if effect and hasattr(effect, "on_sell"):
        effect.on_sell(j, None)
    return sell_value


def reroll_shop(game: "BalatroGame") -> bool:
    """Pay for a reroll. Returns True on success."""
    cost = max(0, game.reroll_cost - game.reroll_discount)
    if game.free_rerolls_remaining > 0:
        game.free_rerolls_remaining -= 1
        cost = 0
    if game.dollars < cost:
        return False
    game.dollars -= cost
    game.reroll_cost += 1
    game.current_shop = generate_shop(game)
    return True


# ════════════════════════════════════════════════════════════════════════════
# BOOSTER PACK OPENING
# ════════════════════════════════════════════════════════════════════════════

def _open_booster(game: "BalatroGame", booster_key: str):
    """Open a booster pack — add options to game.booster_choices for the agent to pick."""
    info = BOOSTER_CATALOGUE.get(booster_key)
    if not info:
        return
    _, _, content_kind, n_cards = info
    picks = 2 if "mega" in booster_key else 1

    choices = []
    if content_kind == "tarot":
        # Omen Globe: 20% chance each Arcana-Pack Tarot is replaced by a
        # Spectral card (real-game effect).
        omen = "v_omen_globe" in game.vouchers
        omen_node = game.rng.node(OMEN_NODE)
        for _ in range(n_cards):
            key = game.rng.node(node_tarot("ar1", game.ante)).choice(ALL_TAROTS)
            if omen and omen_node.chance(0.2):
                key = game.rng.node(node_spectral("spe", game.ante)).choice(ALL_SPECTRALS)
            choices.append(key)
    elif content_kind == "planet":
        # Telescope: Celestial Packs always contain the Planet card for the
        # most-played hand (tie-break: the higher-tier hand, real-game rule).
        forced = None
        if "v_telescope" in game.vouchers:
            counts = getattr(game, "run_hand_counts", None)
            if counts:
                most = max(counts, key=lambda h: (counts[h], _HAND_TIERS.get(h, 0)))
                forced = {v: k for k, v in PLANET_HAND.items()}.get(most)
        for i in range(n_cards):
            if forced is not None and i == 0:
                choices.append(forced)
                continue
            choices.append(game.rng.node(node_planet("pl1", game.ante)).choice(ALL_PLANETS))
    elif content_kind == "spectral":
        choices = [game.rng.node(node_spectral("spe", game.ante)).choice(ALL_SPECTRALS)
                   for _ in range(n_cards)]
    elif content_kind == "joker":
        choices = [random_joker_key(rng=game.rng, ante=game.ante, source="buf")
                   for _ in range(n_cards)]
    elif content_kind == "card":
        from .card import make_standard_deck
        deck = make_standard_deck()
        game.rng.node(node_stdset(game.ante)).shuffle(deck)
        choices = [("card", deck[i]) for i in range(min(n_cards, len(deck)))]

    game.booster_choices = choices
    game.booster_picks_remaining = picks


def _get_effect(key: str):
    from .jokers.base import JOKER_REGISTRY
    return JOKER_REGISTRY.get(key)
