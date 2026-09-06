"""tools/portfolio.py — Balatro joker portfolio classification & state feature extraction.

Defines the 6 canonical strategic joker roles:
  1. CHIPS: flat and per-card chip scoring (e.g. Blue Joker, Bull, Stuntman)
  2. FLAT_MULT: additive mult scoring (e.g. Gros Michel, Half Joker, Fibonacci)
  3. XMULT: multiplicative mult scaling (e.g. Cavendish, Constellation, Baron)
  4. SCALING: permanent/cumulative growth across rounds (e.g. Green Joker, Wee Joker)
  5. ECON: money generation, interest compounding, and consumable generation (e.g. Golden Joker, Rocket)
  6. RETRIGGER: card/joker retriggers and copy abilities (e.g. Hanging Chad, Blueprint, Mime)

Provides fast feature extraction for both live game states and counterfactual
post-action states (buy / sell / swap / leave) without cloning or mutating the game.
"""
from __future__ import annotations

import math
from typing import Optional, Any, Sequence

# Canonical alias mapping between alternate/legacy keys and canonical spec keys
ALIAS_TO_CANONICAL: dict[str, str] = {
    "j_burnt_joker": "j_burnt",
    "j_business_card": "j_business",
    "j_gift_card": "j_gift",
    "j_glass_joker": "j_glass",
    "j_the_idol": "j_idol",
    "j_invisible_joker": "j_invisible",
    "j_gluttonous_joker": "j_gluttenous_joker",
    "j_mail_in_rebate": "j_mail",
    "j_showman": "j_ring_master",
    "j_seltzer": "j_selzer",
    "j_smeared_joker": "j_smeared",
    "j_space_joker": "j_space",
    "j_square_joker": "j_square",
    "j_stone_joker": "j_stone",
    "j_golden_ticket": "j_ticket",
    "j_to_do_list": "j_todo_list",
    "j_trading_card": "j_trading",
    "j_spare_trousers": "j_trousers",
    "j_flash_card": "j_flash",
}

CANONICAL_TO_ALIAS: dict[str, str] = {v: k for k, v in ALIAS_TO_CANONICAL.items()}


def normalize_joker_key(key: str) -> str:
    """Normalize alias or canonical joker key to canonical spec key."""
    return ALIAS_TO_CANONICAL.get(key, key)


# ────────────────────────────────────────────────────────────────────────────
# 1. Primary Role Joker Sets (including canonical keys and aliases)
# ────────────────────────────────────────────────────────────────────────────

CHIPS_JOKERS: set[str] = {
    "j_arrowhead",
    "j_banner",
    "j_blue_joker",
    "j_bull",
    "j_castle",
    "j_clever",
    "j_crafty",
    "j_devious",
    "j_hiker",
    "j_ice_cream",
    "j_odd_todd",
    "j_runner",
    "j_scary_face",
    "j_scholar",
    "j_sly",
    "j_square",
    "j_square_joker",
    "j_stone",
    "j_stone_joker",
    "j_stuntman",
    "j_walkie_talkie",
    "j_wee",
    "j_wily",
}

FLAT_MULT_JOKERS: set[str] = {
    "j_abstract",
    "j_bootstraps",
    "j_ceremonial",
    "j_crazy",
    "j_droll",
    "j_erosion",
    "j_even_steven",
    "j_fibonacci",
    "j_flash",
    "j_flash_card",
    "j_fortune_teller",
    "j_gluttenous_joker",
    "j_gluttonous_joker",
    "j_greedy_joker",
    "j_green_joker",
    "j_gros_michel",
    "j_half",
    "j_joker",
    "j_jolly",
    "j_lusty_joker",
    "j_mad",
    "j_misprint",
    "j_mystic_summit",
    "j_onyx_agate",
    "j_popcorn",
    "j_raised_fist",
    "j_red_card",
    "j_ride_the_bus",
    "j_scholar",
    "j_shoot_the_moon",
    "j_smiley",
    "j_supernova",
    "j_swashbuckler",
    "j_trousers",
    "j_spare_trousers",
    "j_walkie_talkie",
    "j_wrathful_joker",
    "j_zany",
}

XMULT_JOKERS: set[str] = {
    "j_acrobat",
    "j_ancient",
    "j_baron",
    "j_baseball",
    "j_blackboard",
    "j_bloodstone",
    "j_caino",
    "j_campfire",
    "j_card_sharp",
    "j_cavendish",
    "j_constellation",
    "j_drivers_license",
    "j_duo",
    "j_family",
    "j_flower_pot",
    "j_glass",
    "j_glass_joker",
    "j_hit_the_road",
    "j_hologram",
    "j_idol",
    "j_the_idol",
    "j_loyalty_card",
    "j_lucky_cat",
    "j_madness",
    "j_obelisk",
    "j_order",
    "j_photograph",
    "j_ramen",
    "j_seeing_double",
    "j_steel_joker",
    "j_stencil",
    "j_throwback",
    "j_tribe",
    "j_triboulet",
    "j_trio",
    "j_vampire",
    "j_yorick",
}

SCALING_JOKERS: set[str] = {
    # Scaling Chips
    "j_castle",
    "j_hiker",
    "j_runner",
    "j_square",
    "j_square_joker",
    "j_stone",
    "j_stone_joker",
    "j_wee",
    # Scaling Flat Mult
    "j_ceremonial",
    "j_erosion",
    "j_flash",
    "j_flash_card",
    "j_fortune_teller",
    "j_green_joker",
    "j_red_card",
    "j_ride_the_bus",
    "j_supernova",
    "j_swashbuckler",
    "j_trousers",
    "j_spare_trousers",
    # Scaling xMult
    "j_caino",
    "j_campfire",
    "j_constellation",
    "j_glass",
    "j_glass_joker",
    "j_hit_the_road",
    "j_hologram",
    "j_lucky_cat",
    "j_madness",
    "j_obelisk",
    "j_steel_joker",
    "j_throwback",
    "j_vampire",
    "j_yorick",
    # Scaling Economy / Deck / Hand Level
    "j_burnt",
    "j_burnt_joker",
    "j_egg",
    "j_gift",
    "j_gift_card",
    "j_rocket",
    "j_satellite",
    "j_space",
    "j_space_joker",
}

ECON_JOKERS: set[str] = {
    # Cash / Interest / Debt / Sell Value
    "j_business",
    "j_business_card",
    "j_cloud_9",
    "j_credit_card",
    "j_delayed_grat",
    "j_egg",
    "j_faceless",
    "j_gift",
    "j_gift_card",
    "j_golden",
    "j_mail",
    "j_mail_in_rebate",
    "j_matador",
    "j_reserved_parking",
    "j_rocket",
    "j_rough_gem",
    "j_satellite",
    "j_ticket",
    "j_golden_ticket",
    "j_to_the_moon",
    "j_todo_list",
    "j_to_do_list",
    "j_trading",
    "j_trading_card",
    # Economy Buffs & Tags & Free Shop Items
    "j_astronomer",
    "j_chaos",
    "j_diet_cola",
    "j_midas_mask",
    "j_riff_raff",
    # Consumable Generation (Tarot / Spectral / Consumable copies)
    "j_8_ball",
    "j_cartomancer",
    "j_certificate",
    "j_hallucination",
    "j_perkeo",
    "j_seance",
    "j_sixth_sense",
    "j_superposition",
    "j_vagabond",
}

RETRIGGER_JOKERS: set[str] = {
    "j_dusk",
    "j_hack",
    "j_hanging_chad",
    "j_mime",
    "j_selzer",
    "j_seltzer",
    "j_sock_and_buskin",
    "j_blueprint",
    "j_brainstorm",
    "j_invisible",
    "j_invisible_joker",
    "j_dna",
}

# Utility / Hand Modification Jokers (non-scoring manipulation)
UTILITY_JOKERS: set[str] = {
    "j_burglar",
    "j_drunkard",
    "j_four_fingers",
    "j_juggler",
    "j_luchador",
    "j_marble",
    "j_merry_andy",
    "j_mr_bones",
    "j_oops",
    "j_pareidolia",
    "j_ring_master",
    "j_showman",
    "j_shortcut",
    "j_smeared",
    "j_smeared_joker",
    "j_splash",
    "j_troubadour",
    "j_turtle_bean",
    "j_chicot",
}


def classify_joker(key: str) -> dict[str, bool]:
    """Return boolean membership across all 6 canonical roles for a given joker key.

    Handles both canonical spec keys and simulator aliases.
    """
    k = normalize_joker_key(key)
    return {
        "is_chips": k in CHIPS_JOKERS or key in CHIPS_JOKERS,
        "is_flat_mult": k in FLAT_MULT_JOKERS or key in FLAT_MULT_JOKERS,
        "is_xmult": k in XMULT_JOKERS or key in XMULT_JOKERS,
        "is_scaling": k in SCALING_JOKERS or key in SCALING_JOKERS,
        "is_econ": k in ECON_JOKERS or key in ECON_JOKERS,
        "is_retrigger": k in RETRIGGER_JOKERS or key in RETRIGGER_JOKERS,
    }


# ────────────────────────────────────────────────────────────────────────────
# 2. State Feature Extraction
# ────────────────────────────────────────────────────────────────────────────

def extract_features_from_state(
    ante: int,
    blind_idx: int,
    dollars: int,
    hands_left: int,
    discards_left: int,
    joker_slots: int,
    jokers: Sequence[tuple[str, Optional[str]] | Any],  # (key, edition) or JokerInstance
    consumable_slots: int,
    consumables_count: int,
    vouchers: set[str] | list[str] | tuple[str, ...],
    hand_levels: dict[str, int],
    deck_size: int,
    suit_counts: dict[str, int],
    face_count: int,
    enhanced_count: int,
    sealed_count: int,
    chips_target: int = 0,
) -> dict[str, float]:
    """Extract a standard, flat numeric feature vector from state components.

    Supports both live game states and hypothetical/counterfactual post-action states.
    All returned dictionary values are pure numeric floats.
    """
    # Normalize vouchers to a set
    voucher_set = set(vouchers) if not isinstance(vouchers, set) else vouchers

    # Portfolio counts
    n_chips = 0
    n_flat_mult = 0
    n_xmult = 0
    n_scaling = 0
    n_econ = 0
    n_retrigger = 0
    n_foil = 0
    n_holo = 0
    n_poly = 0
    n_negative = 0

    for item in jokers:
        if isinstance(item, tuple):
            key = item[0]
            edition = item[1] if len(item) > 1 else None
        elif hasattr(item, "key"):
            key = item.key
            edition = getattr(item, "edition", None)
        else:
            continue

        k = normalize_joker_key(key)
        if k in CHIPS_JOKERS or key in CHIPS_JOKERS:
            n_chips += 1
        if k in FLAT_MULT_JOKERS or key in FLAT_MULT_JOKERS:
            n_flat_mult += 1
        if k in XMULT_JOKERS or key in XMULT_JOKERS:
            n_xmult += 1
        if k in SCALING_JOKERS or key in SCALING_JOKERS:
            n_scaling += 1
        if k in ECON_JOKERS or key in ECON_JOKERS:
            n_econ += 1
        if k in RETRIGGER_JOKERS or key in RETRIGGER_JOKERS:
            n_retrigger += 1

        # Editions provide additive/multiplicative base stats to any host joker
        if edition == "Foil":
            n_foil += 1
            n_chips += 1
        elif edition == "Holographic":
            n_holo += 1
            n_flat_mult += 1
        elif edition == "Polychrome":
            n_poly += 1
            n_xmult += 1
        elif edition == "Negative":
            n_negative += 1

    n_jokers = len(jokers)
    free_joker_slots = max(0, joker_slots - n_jokers)

    # Deck stats
    d_size = max(1, deck_size)
    max_suit = max(suit_counts.values(), default=0) if suit_counts else 0
    suit_conc = max_suit / d_size
    face_ratio = face_count / d_size
    enh_ratio = enhanced_count / d_size
    seal_ratio = sealed_count / d_size

    # Level stats
    max_lvl = max(hand_levels.values(), default=1) if hand_levels else 1
    flush_lvl = hand_levels.get("Flush", 1)
    pair_lvl = hand_levels.get("Pair", 1)
    two_pair_lvl = hand_levels.get("Two Pair", 1)
    high_card_lvl = hand_levels.get("High Card", 1)

    # Balance metrics
    has_chips = 1.0 if n_chips > 0 else 0.0
    has_flat = 1.0 if n_flat_mult > 0 else 0.0
    has_xmult = 1.0 if n_xmult > 0 else 0.0
    has_scaling = 1.0 if n_scaling > 0 else 0.0
    has_econ = 1.0 if n_econ > 0 else 0.0
    is_balanced = 1.0 if (has_chips and (has_flat or has_scaling) and has_xmult) else 0.0

    # Danger signals (the critical failure modes identified in Ante 4 deaths)
    econ_heavy_late = 1.0 if (n_econ >= 2 and ante >= 3) else 0.0
    zero_xmult_late = 1.0 if (n_xmult == 0 and ante >= 4) else 0.0
    no_scoring_early = 1.0 if (ante <= 2 and (n_chips + n_flat_mult == 0)) else 0.0

    # Financial health
    interest_units = min(5, max(0, dollars // 5))

    return {
        "ante": float(ante),
        "blind_idx": float(blind_idx),
        "dollars": float(dollars),
        "interest_units": float(interest_units),
        "hands_left": float(hands_left),
        "discards_left": float(discards_left),
        "joker_count": float(n_jokers),
        "free_joker_slots": float(free_joker_slots),
        "n_chips": float(n_chips),
        "n_flat_mult": float(n_flat_mult),
        "n_xmult": float(n_xmult),
        "n_scaling": float(n_scaling),
        "n_econ": float(n_econ),
        "n_retrigger": float(n_retrigger),
        "n_foil": float(n_foil),
        "n_holo": float(n_holo),
        "n_poly": float(n_poly),
        "n_negative": float(n_negative),
        "has_chips": has_chips,
        "has_flat": has_flat,
        "has_xmult": has_xmult,
        "has_scaling": has_scaling,
        "has_econ": has_econ,
        "is_balanced": is_balanced,
        "econ_heavy_late": econ_heavy_late,
        "zero_xmult_late": zero_xmult_late,
        "no_scoring_early": no_scoring_early,
        "deck_size": float(deck_size),
        "suit_conc": float(suit_conc),
        "face_ratio": float(face_ratio),
        "enh_ratio": float(enh_ratio),
        "seal_ratio": float(seal_ratio),
        "max_hand_lvl": float(max_lvl),
        "flush_lvl": float(flush_lvl),
        "pair_lvl": float(pair_lvl),
        "two_pair_lvl": float(two_pair_lvl),
        "high_card_lvl": float(high_card_lvl),
        "vouchers_count": float(len(voucher_set)),
        "has_telescope": 1.0 if "v_telescope" in voucher_set else 0.0,
        "has_directors_cut": 1.0 if "v_directors_cut" in voucher_set else 0.0,
        "has_grabber": 1.0 if "v_grabber" in voucher_set else 0.0,
        "has_wasteful": 1.0 if "v_wasteful" in voucher_set else 0.0,
    }


def extract_game_features(game: Any) -> dict[str, float]:
    """Extract portfolio feature vector directly from a live BalatroGame instance.

    Pure inspection only — does not mutate the game state or consume RNG.
    """
    jokers = [(j.key, getattr(j, "edition", None)) for j in getattr(game, "jokers", [])]
    vouchers = set(getattr(game, "vouchers", []))
    hand_levels = dict(getattr(game, "hand_levels", getattr(game, "planet_levels", {})))

    # Deck stats
    deck = getattr(game, "deck", [])
    suit_counts: dict[str, int] = {}
    face_count = 0
    enh_count = 0
    seal_count = 0
    for c in deck:
        s = getattr(c, "suit", "")
        suit_counts[s] = suit_counts.get(s, 0) + 1
        if getattr(c, "rank", 0) in (11, 12, 13):
            face_count += 1
        if getattr(c, "enhancement", None):
            enh_count += 1
        if getattr(c, "seal", None):
            seal_count += 1

    target = 0
    if getattr(game, "current_blind", None):
        target = getattr(game.current_blind, "chips_target", 0)

    return extract_features_from_state(
        ante=getattr(game, "ante", 1),
        blind_idx=getattr(game, "blind_idx", 0),
        dollars=getattr(game, "dollars", 0),
        hands_left=getattr(game, "hands_left", 4),
        discards_left=getattr(game, "discards_left", 3),
        joker_slots=getattr(game, "joker_slots", 5),
        jokers=jokers,
        consumable_slots=getattr(game, "consumable_slots", 2),
        consumables_count=len(getattr(game, "consumable_hand", [])),
        vouchers=vouchers,
        hand_levels=hand_levels,
        deck_size=len(deck),
        suit_counts=suit_counts,
        face_count=face_count,
        enhanced_count=enh_count,
        sealed_count=seal_count,
        chips_target=target,
    )


_LOADED_SHOP_MODEL = None


def load_shop_model(model_path: Optional[Path] = None) -> Optional[dict]:
    global _LOADED_SHOP_MODEL
    if _LOADED_SHOP_MODEL is not None:
        return _LOADED_SHOP_MODEL
    import json
    if model_path is None:
        model_path = Path(__file__).resolve().parent.parent / "vendor" / "balatro-rl" / "balatro_sim" / "shop_model.json"
        if not model_path.exists():
            model_path = Path(__file__).resolve().parent / "shop_model.json"
    if model_path and Path(model_path).exists():
        try:
            with open(model_path, encoding="utf-8") as f:
                _LOADED_SHOP_MODEL = json.load(f)
        except Exception:
            _LOADED_SHOP_MODEL = None
    return _LOADED_SHOP_MODEL


def score_portfolio_features(f: dict[str, float], model: Optional[dict] = None) -> float:
    if model is None:
        model = load_shop_model()
    if model is None:
        return 0.0

    ante = f.get("ante", 1.0)
    n_chips = f.get("n_chips", 0.0)
    n_flat = f.get("n_flat_mult", 0.0)
    n_xmult = f.get("n_xmult", 0.0)
    n_scaling = f.get("n_scaling", 0.0)
    n_econ = f.get("n_econ", 0.0)

    f_full = dict(f)
    f_full["inter_chips_mult"] = n_chips * (n_flat + n_scaling)
    f_full["inter_mult_xmult"] = (n_flat + n_scaling) * n_xmult
    f_full["inter_chips_xmult"] = n_chips * n_xmult
    f_full["inter_ante_xmult"] = ante * n_xmult
    f_full["inter_late_econ_penalty"] = max(0.0, ante - 3.0) * n_econ
    f_full["early_econ"] = n_econ if ante <= 3.0 else 0.0
    f_full["late_econ"] = n_econ if ante >= 4.0 else 0.0
    f_full["inter_late_zero_xmult"] = 1.0 if (ante >= 4.0 and n_xmult == 0.0) else 0.0

    z = model.get("bias", model["w"][-1])
    for name, mean, std, w in zip(model["feat_order"], model["mean"], model["std"], model["w"]):
        val = f_full.get(name, 0.0)
        z += ((val - mean) / std) * w
    z = max(-30.0, min(30.0, z))
    return 1.0 / (1.0 + math.exp(-z))


def evaluate_shop_candidates(game, model: Optional[dict] = None) -> list[tuple[float, dict]]:
    """Evaluate candidate shop actions by predicted post-action win probability delta."""
    if model is None:
        model = load_shop_model()
    if model is None:
        return []

    cur_f = extract_game_features(game)
    cur_v = score_portfolio_features(cur_f, model)

    candidates: list[tuple[float, dict]] = []

    current_jokers = [(j.key, getattr(j, "edition", None)) for j in game.jokers]
    dollars = game.dollars
    discount = getattr(game, "shop_discount", 0)
    joker_slots = game.joker_slots

    for idx, item in enumerate(game.current_shop):
        price = item.discounted_price(discount)
        if price > dollars:
            continue

        if item.kind == "joker":
            # Buy directly if space
            if len(current_jokers) < joker_slots or getattr(item, "edition", None) == "Negative":
                new_jokers = current_jokers + [(item.key, getattr(item, "edition", None))]
                new_f = dict(cur_f)
                new_f["dollars"] = dollars - price
                new_f["joker_count"] = len(new_jokers)
                new_f["free_joker_slots"] = max(0, joker_slots - len(new_jokers))
                if item.key in CHIPS_JOKERS:
                    new_f["n_chips"] = new_f.get("n_chips", 0.0) + 1
                if item.key in FLAT_MULT_JOKERS:
                    new_f["n_flat_mult"] = new_f.get("n_flat_mult", 0.0) + 1
                if item.key in XMULT_JOKERS:
                    new_f["n_xmult"] = new_f.get("n_xmult", 0.0) + 1
                if item.key in SCALING_JOKERS:
                    new_f["n_scaling"] = new_f.get("n_scaling", 0.0) + 1
                if item.key in ECON_JOKERS:
                    new_f["n_econ"] = new_f.get("n_econ", 0.0) + 1
                if item.key in RETRIGGER_JOKERS:
                    new_f["n_retrigger"] = new_f.get("n_retrigger", 0.0) + 1
                new_v = score_portfolio_features(new_f, model)
                candidates.append((new_v - cur_v, {"type": "buy", "item_idx": idx}))

            # Or Swap: sell a joker to buy this joker
            elif len(current_jokers) >= joker_slots and len(game.jokers) > 0:
                for j_idx, j in enumerate(game.jokers):
                    sell_val = j.state.get("sell_value", 2)
                    if dollars + sell_val < price:
                        continue
                    swapped_jokers = [other for k, other in enumerate(current_jokers) if k != j_idx] + [(item.key, getattr(item, "edition", None))]
                    swapped_f = dict(cur_f)
                    swapped_f["dollars"] = dollars + sell_val - price
                    n_ch = sum(1 for k, _ in swapped_jokers if k in CHIPS_JOKERS)
                    n_fl = sum(1 for k, _ in swapped_jokers if k in FLAT_MULT_JOKERS)
                    n_xm = sum(1 for k, _ in swapped_jokers if k in XMULT_JOKERS)
                    n_sc = sum(1 for k, _ in swapped_jokers if k in SCALING_JOKERS)
                    n_ec = sum(1 for k, _ in swapped_jokers if k in ECON_JOKERS)
                    n_rt = sum(1 for k, _ in swapped_jokers if k in RETRIGGER_JOKERS)
                    swapped_f["n_chips"] = n_ch
                    swapped_f["n_flat_mult"] = n_fl
                    swapped_f["n_xmult"] = n_xm
                    swapped_f["n_scaling"] = n_sc
                    swapped_f["n_econ"] = n_ec
                    swapped_f["n_retrigger"] = n_rt
                    swapped_v = score_portfolio_features(swapped_f, model)
                    delta = swapped_v - cur_v
                    if delta > 0:
                        candidates.append((delta, {"type": "sell_joker", "joker_idx": j_idx, "_target_buy": idx}))

        elif item.kind == "planet":
            from balatro_sim.consumables import PLANET_HAND
            ht = PLANET_HAND.get(item.key)
            new_f = dict(cur_f)
            new_f["dollars"] = dollars - price
            if ht == "Flush":
                new_f["flush_lvl"] = new_f.get("flush_lvl", 1.0) + 1.0
            elif ht == "Pair":
                new_f["pair_lvl"] = new_f.get("pair_lvl", 1.0) + 1.0
            elif ht == "Two Pair":
                new_f["two_pair_lvl"] = new_f.get("two_pair_lvl", 1.0) + 1.0
            elif ht == "High Card":
                new_f["high_card_lvl"] = new_f.get("high_card_lvl", 1.0) + 1.0
            new_f["max_hand_lvl"] = max(new_f.get("max_hand_lvl", 1.0), new_f.get(f"{ht.lower().replace(' ', '_')}_lvl", 1.0) if ht else 1.0)
            new_v = score_portfolio_features(new_f, model)
            candidates.append((new_v - cur_v, {"type": "buy", "item_idx": idx}))

        elif item.kind == "voucher":
            new_f = dict(cur_f)
            new_f["dollars"] = dollars - price
            new_f["vouchers_count"] = new_f.get("vouchers_count", 0.0) + 1.0
            if item.key == "v_telescope":
                new_f["has_telescope"] = 1.0
            elif item.key == "v_directors_cut":
                new_f["has_directors_cut"] = 1.0
            elif item.key == "v_grabber":
                new_f["has_grabber"] = 1.0
            elif item.key == "v_wasteful":
                new_f["has_wasteful"] = 1.0
            new_v = score_portfolio_features(new_f, model)
            candidates.append((new_v - cur_v, {"type": "buy", "item_idx": idx}))

    candidates.sort(key=lambda t: t[0], reverse=True)
    return candidates


def main_hand_type(game: Any) -> str:
    """The hand type the run is building: most played, tie-break by planet level."""
    counts = getattr(game, "run_hand_counts", {})
    levels = getattr(game, "hand_levels", getattr(game, "planet_levels", {}))
    best, best_key = "High Card", (-1, -1)
    for ht, c in counts.items():
        key = (c, levels.get(ht, 1))
        if key > best_key:
            best_key, best = key, ht
    return best


def portfolio_target_hand(game: Any) -> str:
    """Hand type synergizing with acquired jokers; deck-aware and preserves viable base hands."""
    if not getattr(game, "jokers", None):
        return main_hand_type(game)

    keys = {getattr(j, "key", "") for j in game.jokers}
    main = main_hand_type(game)

    # Inspect full deck composition (deck + hand + spent)
    cards = list(getattr(game, "deck", ())) + list(getattr(game, "hand", ())) + list(getattr(game, "spent", ()))
    from collections import Counter
    rank_counts = Counter(getattr(c, "rank", None) for c in cards if getattr(c, "rank", None) is not None)
    max_rank_cnt = max(rank_counts.values()) if rank_counts else 4
    suit_counts = Counter(getattr(c, "suit", None) for c in cards if getattr(c, "suit", None) is not None)
    max_suit_cnt = max(suit_counts.values()) if suit_counts else 13

    # 1. Four of a Kind (The Family): ONLY target if deck actually supports it (>= 6 of a rank)
    if "j_family" in keys:
        if max_rank_cnt >= 6:
            return "Four of a Kind"
        # Otherwise retain high-frequency hand
        return main if main in ("Flush", "Two Pair", "Full House", "Pair", "Three of a Kind") else "Two Pair"

    # 2. Straight (The Order / Runner): ONLY target if Shortcut/Four Fingers owned or already primary hand
    if "j_order" in keys or "j_runner" in keys:
        has_helper = bool({"j_shortcut", "j_four_fingers"} & keys)
        committed_straight = getattr(game, "run_hand_counts", {}).get("Straight", 0) >= 2 or main == "Straight"
        if has_helper or committed_straight:
            return "Straight"
        return main if main in ("Flush", "Two Pair", "Full House", "Pair") else "Two Pair"

    # 3. Flush (The Tribe / Bloodstone / Crafty / Smeared):
    if keys & {"j_tribe", "j_bloodstone", "j_crafty", "j_droll", "j_smeared", "j_smeared_joker"}:
        if "j_smeared" in keys or "j_smeared_joker" in keys or max_suit_cnt >= 13 or main == "Flush":
            return "Flush"

    # 4. Pair-containing xMult (The Duo / The Trio) & Scaling (Spare Trousers):
    # Duo triggers on Two Pair and Full House in addition to Pair. Retain high-frequency hand!
    if "j_duo" in keys:
        if main in ("Two Pair", "Full House", "Three of a Kind", "Flush"):
            return main
        return "Two Pair"

    if "j_trio" in keys:
        if main == "Full House" or max_rank_cnt >= 5:
            return "Full House"
        if main in ("Three of a Kind", "Two Pair", "Flush"):
            return main
        return "Three of a Kind"

    if keys & {"j_spare_trousers", "j_trousers", "j_clever", "j_mad"}:
        return "Two Pair"

    if keys & {"j_wily", "j_zany"}:
        return "Full House" if main == "Full House" else "Three of a Kind"

    if keys & {"j_baron", "j_shoot_the_moon"}:
        return "High Card"

    if keys & {"j_sly", "j_jolly", "j_half"}:
        return "Pair"

    return main


