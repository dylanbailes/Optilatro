"""agent_v10.py — M12: in-blind goal hierarchy & value farming.

The V9 agent plays/discards purely to clear the blind ASAP ("just enough").
It has no concept of *value in the blind*: holding gold cards / blue seals at
round end, discarding purple seals, farming Faceless (3-face discards),
deliberately playing a weaker gold-seal hand for its $3.

This module adds a tiered goal hierarchy on top of V9's isolated scoring
oracle (which it reuses BY IMPORT — agent_v9 stays frozen as the A/B baseline):

  decide_hand(game):
    1. Verdant sell / no-hand / planet / consumable   (unchanged from v9)
    2. P_clear = estimate_clear_probability(game)      # NEW — human-fair,
                                                       #   hypergeometric over
                                                       #   deck COMPOSITION only
    3. if P_clear >= FARM_THRESHOLD:                    # value mode
           act = tier2_value(game)                      # hold/play/discard
           if act: return act
    4. return tier1_survive(game)                       # v9 play/discard core

Everything is human-fair (a pure function of the known deck composition; no
draw-order peek) and side-effect-free on the live game (throwaway seed-0 RNG,
isolated eval copies). See docs/agent-v10-inblind-spec.md.
"""
from __future__ import annotations

import math

from .card import Card
from .game import State
from .hand_eval import evaluate_hand

# Reuse the isolated scoring oracle + human-fair helpers from agent_v9
# (frozen baseline). No copy-paste of the oracle; agent_v9 is untouched.
from .agent_v9 import (
    HAND_TYPES,
    HAND_PRIORITY,
    ACTIVE_PARAMS,
    HeuristicV9,
    scored_plays,
    best_play_score,
    eval_hand_score,
    reference_hand,
    _value_multiset,
    _structure_pool,
    _card_quality,
    _type_candidates,
    main_hand_type,
    maybe_use_planet,
    worst_joker_idx,
    best_discard,
    tarot_value,
    ALL_TAROTS,
    ALL_SPECTRALS,
    BAD_BOSSES,
    PLANET_HAND,
    TAROT_ENHANCEMENT,
    TAROT_MAX_TARGETS,
    TAROT_SUIT,
    VOUCHER_PRIORITY,
    _KIND_RANK,
    _enhance_targets,
    _pack_card_value,
    _spectral_action,
    _target_lists,
    _tarot_action,
    forecast_beatable,
    joker_value,
    joker_value_of,
    pack_value,
    spectral_value,
    worth_spending,
)
from .agent_l1 import SearchShopV9
from .graph_v9 import deck_groups

# ────────────────────────────────────────────────────────────────────────────
# V10 tunables (farm gate / value mode). Independent of V9's PARAMS; the A/B
# `--params '{...}'` override targets these knobs only.
# ────────────────────────────────────────────────────────────────────────────

V10_DEFAULTS = {
    "farm_clear_threshold": 0.90,   # enter value mode when Farm P(clear) >= this
    "abandon_clear_floor": 0.75,    # hard-survive below this (abandon-farm)
    "farm_spare_hands": 1,          # hands reserved when measuring Farm P(clear)
    "tier2_opp_bonus": 0.02,        # value-point bonus for opportunistic actions
    "tier2_min_value": 0.0,         # min value points to bother farming
    "hook_hold_discount": True,     # discount held value under The Hook
    "tooth_money_net": True,        # subtract $1/card played under The Tooth
    "eval_topk_value_play": 8,      # top-K scored plays considered in value mode
    "target_enabled": True,         # joker-aware blind targeting (M14)
    "fallback_protect_plan": True,  # M14h: the fallback EV discard must
                                    #   never shed a committed plan's cards
    "chase_min_prob": 0.40,         # min P(assemble the plan) to commit a
                                    #   chase line (kills the doomed flush/
                                    #   straight chases that burned 4 discards
                                    #   on seeds 52/54/63)
    "chase_max_hands": 1,           # only chase KILL LINES: plans that clear
                                    #   the whole remaining target in <= this
                                    #   many hands (M14c). Every audited rule
                                    #   is an m=1 line (face-flush x Photo,
                                    #   trips->FH x chip jokers, Small flush);
                                    #   m>=2 'grind' chases were pure variance
                                    #   on top of the V9 grind.
    "early_chip_bias": 0.35,        # ante<=2 with <3 jokers: value bonus for
                                    #   flat-chip jokers (Sly/Wily/Clever/
                                    #   Banner) in SHOP ranking and PACK PICKS
                                    #   (M14d). The ante-1 deaths own flat-
                                    #   chips: packs kept dealing econ jokers
                                    #   (seed 0 got shoot_the_moon from two
                                    #   Buffoons and died Big with no chips).
    "chase_min_ev_gain": 1.00,      # chase EV (P·S_made) must beat the current
                                    #   best play by this factor (seed 228:
                                    #   never dump a working 240 straight for a
                                    #   coin-flip flush)
    "chase_max_ante": 2,            # M14g scope: committed chase lines only
                                    #   up to this ante. Bank evidence: the
                                    #   chase layer saves ~5 ante-1 deaths but
                                    #   costs ~5-6 WINS when allowed mid-game
                                    #   (nochase arm: 12/200 wins vs 6/200).
    "chase_max_consec": 2,          # M14e doom-loop guard: at most this many
                                    #   chase discards IN A ROW without an
                                    #   intervening play. Seed 59 re-fired an FH
                                    #   chase on every decision and burned all
                                    #   4 discards before the first hand; the
                                    #   counter resets on every play, so mid-
                                    #   game chase->play->chase kill lines
                                    #   (the pre-fix wins) stay available.
    "buffoon_open_value": 0.45,     # ante<=2 with <2 jokers: open-Buffoon
                                    #   ranking floor for paths without the
                                    #   pre-buy (L1 comparative search)
    "buffoon_first": True,          # ante<=2 with <2 jokers: open the
                                    #   Buffoon BEFORE any other buy (audit
                                    #   seed 0: $8 j_order starved the $4
                                    #   pack; two fresh picks compound for
                                    #   the whole run, one Rare does not)
    "reshape_enabled": True,        # deck-reshaping toward bought engines
    "reshape_pack_rank_bonus": 0.10,
    "reshape_pack_near_rank_bonus": 0.05,
    "reshape_pack_suit_bonus": 0.08,
    "reshape_pack_enh_bonus": 0.08,
    "reshape_pack_face_bonus": 0.06,
    "reshape_tarot_death_bonus": 0.06,
    "reshape_tarot_strength_bonus": 0.05,
    "reshape_tarot_suit_bonus": 0.06,
    "reshape_tarot_lovers_bonus": 0.04,
    "reshape_tarot_enh_bonus": 0.06,
    "reshape_tarot_anyenh_bonus": 0.03,
}
V10_PARAMS = dict(V10_DEFAULTS)

# Joker keys (canonical + legacy aliases) for the in-blind value levers.
# The shop sells under the real-game ids (j_mail, j_business, j_ticket,
# j_todo_list, j_trading); the legacy keys are the registered class names.
_RETRIGGER_PLAY_KEYS = {"j_hack", "j_sock_and_buskin",
                        "j_hanging_chad", "j_dusk"}


def _money_vp(dollars: float) -> float:
    """Dollar return -> dimensionless value point (the `econ_value` band)."""
    return min(0.25, max(0.0, dollars) / 10.0)


def _boss_key(game) -> str:
    return game.current_blind.boss_key if game._boss_effects_on() else ""


# ────────────────────────────────────────────────────────────────────────────
# Deck reshaping — build the deck TOWARD the bought engines
# ────────────────────────────────────────────────────────────────────────────
# Once an engine is owned (The Family, Baron, Cloud 9, a flush engine, Steel
# Joker, ...), the tarot/standard policy steers the deck toward the engine's
# trigger: Death/Strength stack a rank, suit-converts build a flush suit,
# enhancement tarots enrich the stack, Standard-pack picks prefer the target
# card values. Pure composition reads (deck_groups + owned jokers + run
# history) — human-fair, no RNG, no draw-order peek.
#
# Gated by `reshape_enabled` AND the farm gate (`farm_clear_threshold < 1.0`):
# the farm-off arm (threshold=1.0) must keep reproducing V9 byte-for-byte
# (the §10.3 attribution control), so "everything off" also disables
# reshaping; `reshape_enabled=False` isolates reshaping's own contribution.

# Fixed-rank engines: owning one commits the reshape to that rank (Baron
# needs Kings, not just "a rank").
_RANK_ENGINES = (
    ("j_baron", 13),           # x1.5 per King held
    ("j_cloud_9", 9),          # $1 per 9 in deck
    ("j_shoot_the_moon", 12),  # +13 Mult per Queen held
)

# Kind-stack hand types: Four of a Kind / Full House want a rank stack.
_KIND_STACK_HANDS = {"Four of a Kind", "Full House"}

# Suit engines: fixed suit (Golden/Rough Gem -> Diamonds, Bloodstone ->
# Hearts) vs dominant-suit (Ancient / Blackboard / a committed Flush build).
_SUIT_ENGINES_FIXED = (
    ("j_golden", "Diamonds"),
    ("j_rough_gem", "Diamonds"),
    ("j_bloodstone", "Hearts"),
)
_SUIT_ENGINES_DOMINANT = ("j_ancient", "j_blackboard", "j_tribe")

# Enhancement engines (joker key -> enhancement to add).
_ENH_ENGINES = {
    "j_steel_joker": "Steel",
    "j_glass": "Glass",
}

# Face engines: the deck should lean faces (Photo/Sock/Business/Parking).
_FACE_ENGINES = ("j_photograph", "j_sock_and_buskin", "j_business",
                 "j_reserved_parking")

_SUIT_ORDER = ("Spades", "Hearts", "Clubs", "Diamonds")

_INACTIVE_TARGET = {"rank": None, "suit": None, "enh": None,
                    "enhanced_any": False, "face": False, "active": False}


def _majority_rank(dg) -> int | None:
    """Rank with the most copies in the full deck; highest rank wins ties
    (sorted iteration — never deck-order dependent)."""
    best_r, best_n = None, -1
    for r, n in sorted(dg["ranks"].items()):
        if n > best_n:
            best_r, best_n = r, n
    return best_r


def _majority_suit(dg) -> str | None:
    """Suit with the most copies; fixed _SUIT_ORDER wins ties."""
    best_s, best_n = None, -1
    for s in _SUIT_ORDER:
        n = dg["suits"].get(s, 0)
        if n > best_n:
            best_s, best_n = s, n
    return best_s


def deck_reshape_target(game) -> dict:
    """The deck-reshaping target derived from owned engines + main hand type.

    Returns {"rank", "suit", "enh", "enhanced_any", "face", "active"}:
    `rank`/`suit` are the rank/suit to stack, `enh` the enhancement to add,
    `enhanced_any` means any enhancement helps (Driver's License), `face`
    means faces are the target. Inactive (all-None) when reshaping is gated
    off or no engine/commitment exists — the biased functions then delegate
    to V9 byte-for-byte."""
    p = V10_PARAMS
    if (not p["reshape_enabled"]
            or p["farm_clear_threshold"] >= 1.0):
        return dict(_INACTIVE_TARGET)
    keys = {j.key for j in game.jokers}
    dg = deck_groups(game)
    t = dict(_INACTIVE_TARGET)

    # Rank: a fixed-rank engine first, else a kind-stack majority rank.
    for key, r in _RANK_ENGINES:
        if key in keys:
            t["rank"] = r
            break
    else:
        kind_stack = ("j_family" in keys) or (
            main_hand_type(game) in _KIND_STACK_HANDS
            and game.run_hand_counts.get(main_hand_type(game), 0) >= 2)
        if kind_stack:
            t["rank"] = _majority_rank(dg)

    # Suit: a fixed-suit engine, else dominant-suit engine / committed Flush.
    for key, s in _SUIT_ENGINES_FIXED:
        if key in keys:
            t["suit"] = s
            break
    else:
        dominant = any(k in keys for k in _SUIT_ENGINES_DOMINANT) or (
            main_hand_type(game) == "Flush"
            and game.run_hand_counts.get("Flush", 0) >= 2)
        if dominant:
            t["suit"] = _majority_suit(dg)

    # Enhancement.
    for key, e in _ENH_ENGINES.items():
        if key in keys:
            t["enh"] = e
            break
    if "j_drivers_license" in keys:
        t["enhanced_any"] = True

    # Faces.
    if any(k in keys for k in _FACE_ENGINES):
        t["face"] = True

    t["active"] = any((t["rank"] is not None, t["suit"] is not None,
                       t["enh"] is not None, t["enhanced_any"], t["face"]))
    return t


def _reshape_tarot_bonus(game, key: str) -> float:
    """Additive tarot value from the reshape target (shop buys + pack picks).
    Zero when inactive, so `tarot_value + 0` reproduces V9's value exactly."""
    t = deck_reshape_target(game)
    if not t["active"]:
        return 0.0
    p = V10_PARAMS
    if key == "c_death" and (t["rank"] is not None or t["suit"] is not None):
        return p["reshape_tarot_death_bonus"]   # the stacker
    if key == "c_strength" and t["rank"] is not None:
        return p["reshape_tarot_strength_bonus"]# near-target -> target
    if key == "c_hanged_man" and t["rank"] is not None:
        return 0.03                              # thin junk toward the stack
    if key in TAROT_SUIT and TAROT_SUIT[key] == t["suit"]:
        return p["reshape_tarot_suit_bonus"]    # convert toward the suit
    if key == "c_lovers" and t["suit"] is not None:
        return p["reshape_tarot_lovers_bonus"]  # Wild feeds any flush
    if key == "c_chariot" and t["enh"] == "Steel":
        return p["reshape_tarot_enh_bonus"]
    if key == "c_devil" and (t["face"]
                             or any(j.key == "j_ticket" for j in game.jokers)):
        return 0.04                              # Gold cards + faces/Ticket
    if key in ("c_magician", "c_empress", "c_hierophant") \
            and t["enhanced_any"]:
        return p["reshape_tarot_anyenh_bonus"]  # any enh feeds the License
    return 0.0


def _reshape_card_bonus(game, card) -> float:
    """Additive Standard-pack card value from the reshape target. Zero when
    inactive (the flat `_pack_card_value` is reproduced exactly)."""
    t = deck_reshape_target(game)
    if not t["active"]:
        return 0.0
    p = V10_PARAMS
    b = 0.0
    if t["rank"] is not None:
        if card.rank == t["rank"]:
            b += p["reshape_pack_rank_bonus"]
        elif card.rank == t["rank"] - 1:
            b += p["reshape_pack_near_rank_bonus"]  # one Strength away
    if t["suit"] is not None and card.suit == t["suit"]:
        b += p["reshape_pack_suit_bonus"]
    if t["enh"] is not None and card.enhancement == t["enh"]:
        b += p["reshape_pack_enh_bonus"]
    if t["face"] and card.is_face_card:
        b += p["reshape_pack_face_bonus"]
    return b


def _v10_tarot_value(game, key: str) -> float:
    return tarot_value(game, key) + _reshape_tarot_bonus(game, key)


def _v10_pack_card_value(game, card) -> float:
    return _pack_card_value(card) + _reshape_card_bonus(game, card)


def _enhance_targets_biased(hand, best, n, t):
    """Top-`n` enhancable cards, preferring target-rank cards (the stack gets
    the enhancement), else the best cards (V9's rule)."""
    out = []
    if t["rank"] is not None:
        for i in best:
            if len(out) >= n:
                break
            c = hand[i]
            if c.rank == t["rank"] and c.enhancement == "None":
                out.append(i)
    if len(out) < n:
        for i in best:
            if len(out) >= n:
                break
            c = hand[i]
            if c.enhancement == "None" and i not in out:
                out.append(i)
    return out


def _v10_tarot_action(game, ci, key, hand, best, weakest):
    """Tarot usage biased toward the reshape target; delegates everything
    else to V9's `_tarot_action` (byte-identical when inactive)."""
    t = deck_reshape_target(game)
    if not t["active"]:
        return _tarot_action(game, ci, key, hand, best, weakest)

    if key == "c_death" and (t["rank"] is not None or t["suit"] is not None):
        # Copy the best TARGET card onto the weakest non-target card
        # (stacking), instead of V9's copy-best-onto-weakest.
        if t["rank"] is not None:
            src = next((i for i in best if hand[i].rank == t["rank"]), None)
            dst = next((i for i in weakest if hand[i].rank != t["rank"]),
                       None)
        else:
            src = next((i for i in best if hand[i].suit == t["suit"]), None)
            dst = next((i for i in weakest if hand[i].suit != t["suit"]),
                       None)
        if src is not None and dst is not None and src != dst:
            return {"type": "use_consumable", "consumable_idx": ci,
                    "target_cards": [dst, src]}
        return _tarot_action(game, ci, key, hand, best, weakest)

    if key == "c_strength" and t["rank"] is not None:
        # +1 rank: cards one below the target rank first (they become the
        # target), else V9's weakest non-Ace.
        near = [i for i in weakest if hand[i].rank == t["rank"] - 1][:2]
        if near:
            return {"type": "use_consumable", "consumable_idx": ci,
                    "target_cards": near}
        return _tarot_action(game, ci, key, hand, best, weakest)

    if key in TAROT_SUIT and TAROT_SUIT[key] == t["suit"]:
        # Convert toward the build's suit. In the SHOP the leftover hand
        # returns to the deck -> pure deck improvement; mid-blind keep V9's
        # hand-majority safety (don't fragment the live hand).
        if game.state == State.SHOP:
            tgt = [i for i in best if hand[i].suit != t["suit"]
                   and hand[i].enhancement != "Stone"][:3]
            if tgt:
                return {"type": "use_consumable", "consumable_idx": ci,
                        "target_cards": tgt}
        return _tarot_action(game, ci, key, hand, best, weakest)

    if key in TAROT_ENHANCEMENT and key not in ("c_justice", "c_tower"):
        n = TAROT_MAX_TARGETS.get(key, 2)
        tgt = _enhance_targets_biased(hand, best, n, t)
        if tgt:
            return {"type": "use_consumable", "consumable_idx": ci,
                    "target_cards": tgt}
        return _tarot_action(game, ci, key, hand, best, weakest)

    return _tarot_action(game, ci, key, hand, best, weakest)


def _v10_decide_consumable(game):
    """decide_consumable with the reshape-biased tarot action (byte-identical
    to V9's when the reshape target is inactive)."""
    cons = game.consumable_hand
    if not cons:
        return None
    hand = game.hand
    best, weakest = _target_lists(hand)
    for ci, key in enumerate(cons):
        act = _v10_tarot_action(game, ci, key, hand, best, weakest)
        if act is None and key in ALL_SPECTRALS:
            act = _spectral_action(game, ci, key, hand, best, weakest)
        if act is not None:
            return act
    return None


def _v10_rank_shop_items(game, ref, surplus):
    """`_rank_shop_items` with the reshape-biased tarot/card values (used by
    BOTH the L0 shop and the L1 comparative search). Pure reads."""
    p = ACTIVE_PARAMS
    buys = []  # (value, item_idx)
    need_sell = None  # (candidate_value, worst_idx) when slots are full
    worst_cache = None
    for i, item in enumerate(game.current_shop):
        if item.sold:
            continue
        price = item.discounted_price(game.shop_discount)
        if price > game.dollars:
            continue
        if item.kind == "joker":
            value = _v10_joker_value(game, item.key, item.edition, ref,
                                     surplus)
            has_room = (len(game.jokers) < game.joker_slots
                        or item.edition == "Negative")
            thr = 0.0 if (game.ante <= 2 and not game.jokers) else p["buy_threshold"]
            if has_room and value >= thr:
                buys.append((value, i))
            elif not has_room:
                if worst_cache is None:
                    worst_cache = worst_joker_idx(game, ref)
                if (worst_cache is not None
                        and value - joker_value_of(game, worst_cache, ref)
                        >= p["sell_margin"]):
                    need_sell = (value, worst_cache)
        elif item.kind == "booster":
            value = _v10_pack_value(game, item.key)
            if value >= p["buy_threshold"]:
                buys.append((value, i))
        elif item.kind == "voucher":
            prio = VOUCHER_PRIORITY.get(item.key, 0)
            if (prio >= 2 and len(game.jokers) > 0 and game.ante > 2
                    and game.dollars - price >= 5):
                buys.append((0.10 + 0.05 * prio, i))
        elif item.kind == "planet" \
                and PLANET_HAND.get(item.key) == main_hand_type(game):
            buys.append((0.08, i))
        elif item.kind == "tarot":
            value = _v10_tarot_value(game, item.key)
            if (value >= p["buy_threshold"]
                    and len(game.consumable_hand) < game.consumable_slots):
                buys.append((value, i))
        elif item.kind == "spectral":
            value = spectral_value(game, item.key)
            if (value >= p["buy_threshold"]
                    and len(game.consumable_hand) < game.consumable_slots):
                buys.append((value, i))
        elif item.kind == "card" and item.card is not None:
            value = _v10_pack_card_value(game, item.card)
            if value >= p["buy_threshold"]:
                buys.append((value, i))
    return buys, need_sell


def _v10_decide_shop(game, rerolls_used: int) -> dict:
    """decide_shop with the reshape bias: shop-phase consumable usage and
    tarot/card buying use the v10 reshape-aware versions (byte-identical to
    V9's when the reshape target is inactive)."""
    p = ACTIVE_PARAMS

    if (game.next_boss_key in BAD_BOSSES and game.dollars >= 10):
        can_dc = ("v_directors_cut" in game.vouchers
                  and game.dc_reroll_ante != game.ante)
        can_retcon = "v_retcon" in game.vouchers
        if can_dc or can_retcon:
            return {"type": "reroll_boss"}

    act = maybe_use_planet(game)
    if act is not None:
        return act

    if p["use_tarots"]:
        act = _v10_decide_consumable(game)
        if act is not None:
            return act

    # Early-Buffoon priority (M14): open the pack before any ranked buy.
    act = _buffoon_open_action(game)
    if act is not None:
        return act

    ref = reference_hand(game)
    surplus = forecast_beatable(game, p["tilt_surplus_margin"], ref)
    buys, need_sell = _v10_rank_shop_items(game, ref, surplus)

    if need_sell is not None:
        return {"type": "sell_joker", "joker_idx": need_sell[1]}

    save_mode = (
        game.ante > 2
        and game.dollars < p["interest_target"]
        and max((v for v, _ in buys), default=0.0) < p["save_strong_value"]
        and forecast_beatable(game, p["save_margin"], ref)
    )

    if buys:
        buys.sort(key=lambda b: (b[0], _KIND_RANK.get(
            game.current_shop[b[1]].kind, 1)), reverse=True)
        for value, idx in buys:
            item = game.current_shop[idx]
            price = item.discounted_price(game.shop_discount)
            if (price <= game.dollars
                    and (not save_mode or value >= p["save_strong_value"])
                    and worth_spending(game, price, value)):
                return {"type": "buy", "item_idx": idx}

    reroll_cost = max(0, game.reroll_cost - game.reroll_discount)
    if (not save_mode
            and game.dollars >= max(reroll_cost, p["reroll_min_money"])
            and rerolls_used < p["reroll_max"]):
        return {"type": "reroll"}

    return {"type": "leave_shop"}


def _v10_decide_booster(game) -> dict:
    """decide_booster with the reshape-biased tarot/card values (byte-
    identical to V9's when the reshape target is inactive)."""
    p = ACTIVE_PARAMS
    choices = game.booster_choices
    picks = game.booster_picks_remaining
    if not choices or picks <= 0:
        return {"type": "skip_booster"}

    ref = None  # lazy: only joker choices need the valuation reference
    main = main_hand_type(game)
    ranked = []  # (value, index)
    for i, c in enumerate(choices):
        value = None
        is_joker = isinstance(c, tuple) and c and c[0] == "joker"
        if is_joker:
            key, edition = c[1], c[2]
            if len(game.jokers) >= game.joker_slots and edition != "Negative":
                continue
            if ref is None:
                ref = reference_hand(game)
            value = _v10_joker_value(game, key, edition, ref)
        elif isinstance(c, tuple) and c and c[0] == "card":
            value = _v10_pack_card_value(game, c[1])
        elif isinstance(c, str):
            if c in PLANET_HAND:
                value = (0.10 if (PLANET_HAND[c] == main
                                  and len(game.consumable_hand)
                                  < game.consumable_slots)
                         else 0.0)
            elif c in ALL_TAROTS:
                if len(game.consumable_hand) < game.consumable_slots:
                    value = _v10_tarot_value(game, c)
            elif c in ALL_SPECTRALS:
                if len(game.consumable_hand) < game.consumable_slots:
                    value = spectral_value(game, c)
        if value is None:
            continue
        threshold = (p["booster_joker_threshold"] if is_joker
                     else p["booster_pick_threshold"])
        if value >= threshold:
            ranked.append((value, i))
    if ranked:
        ranked.sort(key=lambda t: t[0], reverse=True)
        return {"type": "pick_booster",
                "indices": [i for _, i in ranked[:picks]]}
    return {"type": "skip_booster"}


# ────────────────────────────────────────────────────────────────────────────
# Trigger counts (RULING-R: Red seal retriggers held AND played abilities)
# ────────────────────────────────────────────────────────────────────────────

def triggers_held(game, card) -> int:
    """Held-in-hand trigger count: 1 + Mime + Red-seal-on-this-card (RULING-R)."""
    n = 1
    if any(j.has_flag("retriggers_held") for j in game.jokers):
        n += 1
    if card.seal == "Red":
        n += 1
    return n


def triggers_played(game, card, is_first: bool = False) -> int:
    """Played/scored trigger count: 1 + Red seal + retrigger jokers.

    Hack retriggers 2-5, Sock & Buskin retriggers faces, Hanging Chad
    retriggers the FIRST scored card 2 extra, Dusk retriggers all cards on
    the last hand of the round. These are value ESTIMATES (the spec's
    per-trigger expected returns); the engine computes the true counts."""
    n = 1
    if card.seal == "Red":
        n += 1
    keys = {j.key for j in game.jokers}
    if "j_hack" in keys and card.rank in (2, 3, 4, 5):
        n += 1
    if "j_sock_and_buskin" in keys and card.is_face_card:
        n += 1
    if "j_hanging_chad" in keys and is_first:
        n += 2
    if "j_dusk" in keys and game.hands_left == 1:
        n += 1
    return n


# ────────────────────────────────────────────────────────────────────────────
# Blue-seal planet value (RULING-BLUE): planet_value(ht) = share · Δ_level
# ────────────────────────────────────────────────────────────────────────────

def _blue_seal_target_ht(game) -> str:
    """The hand type a Blue-seal planet keys off (the FINAL hand played, which
    the agent steers): main hand type when committed, else the best-play type
    on the reference hand."""
    counts = game.run_hand_counts
    main = main_hand_type(game)
    if counts.get(main, 0) >= 2:
        return main
    ref = reference_hand(game)
    plays = scored_plays(game, hand=ref.ceiling) if ref.ceiling else []
    return plays[0][2] if plays else main


def planet_value(game, ht: str) -> float:
    """Fractional score gain of one +1 planet level for hand type `ht`,
    weighted by how often the run actually plays `ht` (RULING-BLUE)."""
    if len(game.consumable_hand) >= game.consumable_slots:
        return 0.0
    ref = reference_hand(game)
    if not ref.ceiling:
        return 0.0
    base = best_play_score(game, hand=ref.ceiling)
    if base <= 0:
        return 0.0
    bumped = best_play_score(game, hand=ref.ceiling, level_override={ht: +1})
    delta = (bumped - base) / base
    counts = game.run_hand_counts
    total = sum(counts.values()) or 1
    main = main_hand_type(game)
    if counts.get(main, 0) >= 2 and ht == main:
        share = 1.0
    else:
        share = counts.get(ht, 0) / total
    return share * delta


# ────────────────────────────────────────────────────────────────────────────
# Round-end hold value (§5.5)
# ────────────────────────────────────────────────────────────────────────────

def expected_round_end_value(game, held_cards) -> float:
    """Dimensionless value-point sum over the cards LEFT IN HAND at round end.

    gold_card_term = min(0.25, 3·triggers/10)   (Gold enhancement, $3 held)
    blue_seal_term = triggers · planet_value(ht) (0 when consumables full)
    Reserved Parking = 0.5·faces(held)/10        (joker effect, once — no
                                                 triggers_held multiplier)

    The Hook's forced discard makes held value unreliable: discount by
    (hs-2)/hs (chance a held card survives the 2-of-hand discard)."""
    held = [c for c in held_cards if not c.debuffed]
    if not held:
        return 0.0
    joker_keys = {j.key for j in game.jokers}
    mime = any(j.has_flag("retriggers_held") for j in game.jokers)
    val = 0.0
    blue_ht = None
    for c in held:
        if c.enhancement == "Gold":
            trig = 1 + (1 if mime else 0) + (1 if c.seal == "Red" else 0)
            val += _money_vp(3 * trig)
        if c.seal == "Blue":
            if blue_ht is None:
                blue_ht = _blue_seal_target_ht(game)
            trig = 1 + (1 if mime else 0) + (1 if c.seal == "Red" else 0)
            val += trig * planet_value(game, blue_ht)
    if "j_reserved_parking" in joker_keys:
        faces = sum(1 for c in held if c.is_face_card)
        val += _money_vp(0.5 * faces)
    if V10_PARAMS["hook_hold_discount"] and _boss_key(game) == "bl_hook":
        hs = len(held)
        if hs >= 3:
            val *= (hs - 2) / hs
        else:
            val = 0.0
    return val


# ────────────────────────────────────────────────────────────────────────────
# Play-trigger value (§6 Play levers)
# ────────────────────────────────────────────────────────────────────────────

def _todo_target(game):
    for j in game.jokers:
        if j.key in ("j_todo_list", "j_to_do_list"):
            return j.state.get("target")
    return None


def play_trigger_value(game, scoring_cards, hand_type) -> float:
    """Value points from deliberately SCORING `scoring_cards` (§6 Play levers).
    Card abilities scale with triggers_played; To Do List fires once."""
    joker_keys = {j.key for j in game.jokers}
    val = 0.0
    for i, c in enumerate(scoring_cards):
        if c.debuffed:
            continue
        trig = triggers_played(game, c, is_first=(i == 0))
        if c.seal == "Gold":
            val += _money_vp(3 * trig)
        if c.enhancement == "Lucky":
            val += _money_vp((20 / 15) * trig)
        if "j_business" in joker_keys and c.is_face_card:
            val += _money_vp(1 * trig)
        if "j_rough_gem" in joker_keys and c.suit == "Diamonds":
            val += _money_vp(1 * trig)
        if "j_ticket" in joker_keys and c.enhancement == "Gold":
            val += _money_vp(4 * trig)
    target = _todo_target(game)
    if target is not None and hand_type == target:
        val += _money_vp(4)
    if V10_PARAMS["tooth_money_net"] and _boss_key(game) == "bl_tooth":
        val -= _money_vp(len(scoring_cards))
    return val


# ────────────────────────────────────────────────────────────────────────────
# P(clear) — the human-fair survive check (§5.1)
# ────────────────────────────────────────────────────────────────────────────

def _hg_tail(c: int, N: int, fresh: int, need: int) -> float:
    """Hypergeometric CDF tail: P(draw >= `need` successes in `fresh` draws
    from a pool of N with `c` successes). Exact (math.comb), closed form."""
    if need <= 0:
        return 1.0
    if fresh <= 0 or c < need or N <= 0:
        return 0.0
    lo = max(need, fresh - (N - c))
    hi = min(c, fresh)
    if lo > hi:
        return 0.0
    denom = math.comb(N, fresh)
    total = sum(math.comb(c, k) * math.comb(N - c, fresh - k)
                for k in range(lo, hi + 1))
    return min(1.0, total / denom)


def _draw_pile_support(M, pred) -> int:
    return sum(cnt for (r, s, e, ed, seal), cnt in M.items()
               if pred(r, s, e, ed, seal))


def _held_support(held, pred) -> int:
    return sum(1 for c in held if pred(c))


def _assemble_kind(M, held, rank, k, N, fresh) -> float:
    in_hand = _held_support(held, lambda c: c.rank == rank)
    if in_hand >= k:
        return 1.0
    c = _draw_pile_support(M, lambda r, s, e, ed, seal: r == rank)
    return _hg_tail(c, N, fresh, k - in_hand)


def _assemble_flush(M, held, suit, k, N, fresh) -> float:
    in_hand = _held_support(held, lambda c: c.suit == suit
                            or c.enhancement == "Wild")
    if in_hand >= k:
        return 1.0
    c = _draw_pile_support(M, lambda r, s, e, ed, seal: s == suit
                           or e == "Wild")
    return _hg_tail(c, N, fresh, k - in_hand)


def _assemble_straight(M, held, N, fresh) -> float:
    """P(∃ a 5-consecutive-rank window all present), incl. the A-2-3-4-5 wheel."""
    best = 0.0
    windows = [list(range(start, start + 5)) for start in range(2, 11)]
    windows.append([14, 2, 3, 4, 5])  # wheel
    for w in windows:
        p = 1.0
        for r in w:
            if _held_support(held, lambda c: c.rank == r) > 0:
                continue
            c = _draw_pile_support(M, lambda rr, s, e, ed, seal: rr == r)
            p *= _hg_tail(c, N, fresh, 1)
            if p == 0.0:
                break
        best = max(best, p)
    return min(1.0, best)


def _assemble_full_house(M, held, N, fresh) -> float:
    """P(∃ r1 with ≥3 AND ∃ r2≠r1 with ≥2) — max over rank pairs."""
    ranks = range(2, 15)
    p3 = {r: _assemble_kind(M, held, r, 3, N, fresh) for r in ranks}
    p2 = {r: _assemble_kind(M, held, r, 2, N, fresh) for r in ranks}
    best = 0.0
    for r1 in ranks:
        if p3[r1] <= 0.0:
            continue
        others = max((p2[r2] for r2 in ranks if r2 != r1), default=0.0)
        best = max(best, p3[r1] * others)
    return min(1.0, best)


def _assemble_two_pair(M, held, N, fresh) -> float:
    """P(≥2 distinct ranks each with ≥2 copies) — union bound over rank pairs."""
    ranks = list(range(2, 15))
    p2 = {r: _assemble_kind(M, held, r, 2, N, fresh) for r in ranks}
    best = 0.0
    for i, r1 in enumerate(ranks):
        for r2 in ranks[i + 1:]:
            best = max(best, p2[r1] * p2[r2])
    return min(1.0, best)


def _rank_union(M, held, k, N, fresh) -> float:
    """Bonferroni union bound: P(∃ rank with ≥k copies)."""
    return min(1.0, sum(_assemble_kind(M, held, r, k, N, fresh)
                        for r in range(2, 15)))


_ASSEMBLERS = {
    "Pair": lambda M, held, N, f: _rank_union(M, held, 2, N, f),
    "Three of a Kind": lambda M, held, N, f: _rank_union(M, held, 3, N, f),
    "Four of a Kind": lambda M, held, N, f: _rank_union(M, held, 4, N, f),
    "Five of a Kind": lambda M, held, N, f: _rank_union(M, held, 5, N, f),
    "Flush": lambda M, held, N, f: min(1.0, sum(
        _assemble_flush(M, held, s, 5, N, f)
        for s in ("Spades", "Hearts", "Clubs", "Diamonds"))),
    "Straight": lambda M, held, N, f: _assemble_straight(M, held, N, f),
    "Full House": lambda M, held, N, f: _assemble_full_house(M, held, N, f),
    "Two Pair": lambda M, held, N, f: _assemble_two_pair(M, held, N, f),
    "High Card": lambda M, held, N, f: 1.0,
    # Rare — not modeled for the gate (no clear contribution).
    "Straight Flush": lambda M, held, N, f: 0.0,
    "Flush House": lambda M, held, N, f: 0.0,
    "Flush Five": lambda M, held, N, f: 0.0,
}


def _card_sort_key(c):
    """Deterministic quality-desc sort key: quality, then the card value
    (rank/suit/enh/edition/seal) so ties never depend on deck order."""
    return (_card_quality(c),
            (c.rank, c.suit, c.enhancement, c.edition, c.seal))


def _plain_flush_candidates(ranked):
    """Per-suit best PLAIN-flush 5-card constructions (quality-desc order).

    M14f root cause (seed 59): `_type_candidates(ranked, "Flush")` builds ONE
    candidate from an arbitrarily tie-broken top suit, and with a near-full
    deck its best five are almost always A-K-Q-J-10 — which evaluates as a
    STRAIGHT Flush. The scan-until-requested-type loop then exhausts its only
    candidate, `S["Flush"]` never exists, and the planner is blind to the
    user's majority-suit flush line even while holding four of that suit.

    Fix: build a candidate per suit (>=5 pool cards, stones excluded), and
    when the top-5 window reads as a straight flush, slide the LOW card down
    the quality order until the five are not consecutive. Deterministic;
    empty when no suit can produce a plain flush."""
    suits = {}
    for c in ranked:
        if c.enhancement != "Stone":
            suits.setdefault(c.suit, []).append(c)
    out = []
    for cs in suits.values():
        if len(cs) < 5:
            continue
        for c5 in ([cs[:5]]
                   + [cs[1:5] + [cs[k]] for k in range(5, len(cs))]):
            try:
                ht5, _sc = evaluate_hand(c5)
            except Exception:
                continue
            if ht5 == "Flush":
                out.append(c5)
                break
    return out


def _compute_type_scores(game, plays) -> dict:
    """S(ht): the best ONE-hand score of each type, seeded from the already-
    scored held-hand `plays` (free) and filled for missing big types from a
    representative deck+hand construction (bounded evals). Deterministic
    (quality-desc with a value tie-break) — order-independent (§7)."""
    S = {}
    for score, combo, ht in plays:
        if score > S.get(ht, 0):
            S[ht] = score
    pool = list(game.deck) + list(game.hand)
    if not pool:
        return S
    ranked = sorted(pool, key=_card_sort_key, reverse=True)
    for ht in ("Flush", "Straight", "Full House", "Four of a Kind",
               "Straight Flush", "Five of a Kind"):
        if ht in S:
            continue
        if ht == "Flush":
            # Real per-suit plain-flush lines (M14f); the generic generator
            # yields a single arbitrary-suit candidate that usually reads as
            # a Straight Flush and leaves Flush absent entirely.
            cands = _plain_flush_candidates(ranked)
        else:
            cands = _type_candidates(ranked, ht)
        for c5 in cands:
            try:
                ht5, sc = evaluate_hand(c5)
                s = eval_hand_score(game, ht5, sc, c5)
            except Exception:
                continue
            S[ht5] = max(S.get(ht5, 0), s)
            if ht5 == ht:
                # The first candidate is often a NEAR type (asking Full
                # House yields the bare-quads construction, which scores as
                # Four/Five of a Kind). Keep scanning until the REQUESTED
                # type is represented, or the candidates run out — otherwise
                # Full House never lands in S and the planner can never
                # target the trips→full-house upgrade line.
                break
    return S


def _chase_consec(game) -> int:
    """Consecutive chase discards since the last PLAYED hand this blind
    (M14e doom-loop guard).

    Keyed by blind identity so a stale counter can never leak into the next
    blind, and RESET whenever a hand is played (`_reset_chase`, called from
    `_v10_survive`'s play returns). Seed 59 lesson: an m=1 plan whose
    probability stayed above the gate re-fired on every decision and burned
    ALL four discards before the first hand was played. A blunt per-blind
    cap also blocked legitimate mid-game chase->play->chase kill lines, so
    the guard counts only CONSECUTIVE chases."""
    st = getattr(game, "_m14_chase_state", None)
    if st and st[0] == _plan_blind_id(game):
        return st[1]
    return 0


def _spend_chase(game) -> None:
    """Record that a chase discard fired this blind."""
    game._m14_chase_state = (_plan_blind_id(game), _chase_consec(game) + 1)


def _reset_chase(game) -> None:
    """A hand was played: the doom-loop counter starts over."""
    game._m14_chase_state = (_plan_blind_id(game), 0)


def estimate_clear_probability_bounds(game, h=None, d=None, T=None, hand=None,
                                      type_scores=None):
    """(pessimistic P_clear, optimistic P_clear⁺) — §5.1 Step 5.

    Purely a function of deck composition (no draw-order peek, no RNG).
    `type_scores` is cached across the cascade + guards (the one-hand scores
    barely change when one hand/discard is spent)."""
    if h is None:
        h = game.hands_left
    if d is None:
        d = game.discards_left
    if T is None:
        T = game.current_blind.chips_target - game.chips_scored
    if hand is None:
        hand = game.hand
    if type_scores is None:
        type_scores = _compute_type_scores(
            game, scored_plays(game, topk=ACTIVE_PARAMS["eval_topk_play"]))

    if T <= 0:
        return 1.0, 1.0
    if h <= 0:
        return 0.0, 0.0

    M = _value_multiset(game.deck)
    N = sum(M.values())
    hs = max(1, len(hand))
    k_d = min(3, hs)            # typical cards per discard (conservative)
    k_r = max(1, hs - 5)        # typical refill per play after the first
    fresh = max(0, min(N, d * k_d + (h - 1) * k_r))

    p_hts = {}
    for ht, S in type_scores.items():
        if S is None or S <= 0:
            continue
        m_ht = math.ceil(T / float(S))
        if m_ht > h:
            continue  # not finishing within the hand budget
        a_ht = _ASSEMBLERS.get(ht, lambda M, held, N, f: 0.0)(M, hand, N, fresh)
        if m_ht <= 1:
            p_hts[ht] = a_ht
        else:
            # m_ht independent assemblies across the fresh budget (spec §5.1).
            share = min(1.0, fresh / m_ht)
            p_hts[ht] = a_ht * (share ** m_ht)

    if not p_hts:
        return 0.0, 0.0

    pessimistic = min(1.0, max(p_hts.values()))
    prod = 1.0
    for p in p_hts.values():
        prod *= (1.0 - min(1.0, p))
    optimistic = min(1.0, 1.0 - prod)
    return pessimistic, optimistic


def estimate_clear_probability(game, h=None, d=None, T=None, hand=None,
                               type_scores=None) -> float:
    """Pessimistic P(clear) — the value the farm gate / abandon floor compare
    against (§5.1). See `estimate_clear_probability_bounds` for the ceiling."""
    return estimate_clear_probability_bounds(
        game, h, d, T, hand, type_scores)[0]


# ────────────────────────────────────────────────────────────────────────────
# Joker-aware blind targeting (M14): pick the hand TYPE the owned jokers
# want, then steer discards toward it
# ────────────────────────────────────────────────────────────────────────────
#
# The ante-1 audit's two traced losses are targeting failures, not luck:
#
#   - Photograph (x2 Mult first face) + a face-flush clears the Boss 600 in
#     ONE hand — but the agent ground pairs because nothing told it a flush
#     WITH A FACE is the kill line.
#   - Any flat-chips joker turns a Three-of-a-Kind board into a Full-House
#     kill (40×4 vs 30×3 base + the chip bonus) — the agent kept playing
#     trips and died at 413/600.
#
# The machinery already exists: `_compute_type_scores` scores a MADE hand of
# each type THROUGH THE REAL ENGINE (owned jokers active), and the §5.1
# assemblers give P(drawing into it) from deck composition alone. Combine
# them: target = fewest hands to clear, tie-broken by assembly probability,
# gated by a minimum probability and an EV-vs-current-best check. Then the
# committed chase discard keeps exactly the plan's cards and pools the rest.
#
# Human-fair: composition-only reads (multiset + hypergeometric), isolated
# scoring, deterministic tie-breaks. Gated off entirely at
# `farm_clear_threshold >= 1.0` so the farming-off arm stays byte-V9.


def _plan_context(game):
    """(M, held, N, fresh) — the §5.1 belief state: deck-value multiset,
    live hand, and the fresh-draw budget (≈min(3,hs) per discard +(hs-5)
    per later hand). Same formula as `estimate_clear_probability_bounds`."""
    hand = game.hand
    M = _value_multiset(game.deck)
    N = sum(M.values())
    hs = max(1, len(hand))
    h, d = game.hands_left, game.discards_left
    fresh = max(0, min(N, d * min(3, hs) + (h - 1) * max(1, hs - 5)))
    return M, hand, N, fresh


def _plan_flush_prob(M, held, N, fresh, suit) -> float:
    return _assemble_flush(M, held, suit, 5, N, fresh)


def _plan_kind_prob(M, held, N, fresh, ht) -> float:
    fn = _ASSEMBLERS.get(ht)
    return fn(M, held, N, fresh) if fn else 0.0


# Chasable plan types. Excluded on purpose (seed-52 lesson):
#   - Four/Five of a Kind, Straight/Flush House/Five: `type_scores` prices
#     them from a representative best-card construction (phantom S — a
#     "728-chip Four of a Kind" nobody holds), and `_rank_union`'s union
#     bound reads ~1.0 when the hand holds two trips. Those phantom plans
#     occupied the argmax all blind and burned discards on lottery tickets.
#   - Pair: never worth a committed chase — the V9 grind already plays pairs.
#   - Two Pair: NEVER a chase line (M14b). `_assemble_two_pair` reads ≈1.0
#     from any live deck, so it wins the argmax on probability alone and
#     produces no-progress loops (seed 7 Boss: plan Two Pair == best play,
#     burned every discard keeping the same [11,11,9,9]). The V9 grind
#     already plays two pairs; committing discards to it adds nothing.
_PLAN_TYPES = ("Flush", "Straight", "Full House", "Three of a Kind")


def _plan_eff_prob(raw: float, m: int) -> float:
    """P(the line actually clears), not P(one assembly). A plan needing m
    scored hands must re-assemble the shape every hand, so the honest
    pessimistic estimate compounds the per-attempt probability (seed 52:
    an m=3 flush passed every gate on its raw 0.90 and then lost the blind
    when attempts 2 and 3 missed)."""
    return raw if m <= 1 else raw ** m


def _blind_plan(game, type_scores) -> dict | None:
    """The joker-aware in-blind target: the hand type whose MADE score
    (real-engine eval with the owned jokers) clears the remaining target in
    the fewest hands, tie-broken by assembly probability. None when no line
    is reliable enough (the caller grinds V9-style).

    Ante-1 Small Blind resolves to the majority-suit flush almost always:
    S_flush ≈ 330-350 ≥ 300 in m=1 with P ≈ 0.8+ — exactly the user rule
    'impossible to lose if you chase the suit you hold most of', derived
    rather than hardcoded (a made pair/trips line with m=1 still wins)."""
    p = V10_PARAMS
    if not p["target_enabled"]:
        return None
    T = game.current_blind.chips_target - game.chips_scored
    if T <= 0 or not game.hand:
        return None
    M, held, N, fresh = _plan_context(game)
    best_key, best = None, None
    for ht in sorted(type_scores):
        S = type_scores.get(ht)
        if not S or S <= 0 or ht not in _PLAN_TYPES:
            continue
        m = math.ceil(T / float(S))
        if m > p["chase_max_hands"]:
            continue          # not a kill line (M14c), or impossible
        if m > game.hands_left:
            continue
        if ht == "Flush":
            # Commit to ONE suit: the most-assemblable one (ties resolve in
            # _SUIT_ORDER, i.e. deterministically, never by deck order).
            raw, suit = 0.0, None
            for s in _SUIT_ORDER:
                pr = _plan_flush_prob(M, held, N, fresh, s)
                if pr > raw:
                    raw, suit = pr, s
            detail = suit
        else:
            raw = _plan_kind_prob(M, held, N, fresh, ht)
            detail = None
        prob = _plan_eff_prob(raw, m)
        if prob < p["chase_min_prob"]:
            continue
        key = (m, -round(prob, 6), -S, ht)
        if best_key is None or key < best_key:
            best_key = key
            best = {"ht": ht, "suit": detail, "S": S, "prob": prob, "m": m}
    return best


def _longest_run_indices(hand) -> list[int]:
    """Hand indices of the longest consecutive-rank run (straight chase
    keep-set). Deterministic (rank-based, never deck order)."""
    by_rank = {}
    for i, c in enumerate(hand):
        if c.enhancement != "Stone":
            by_rank.setdefault(c.rank, []).append(i)
    ranks = sorted(by_rank, reverse=True)
    best_run: list[int] = []
    run: list[int] = []
    prev = None
    for r in ranks:
        if prev is not None and prev - r == 1:
            run.extend(by_rank[r])
        else:
            if len(run) > len(best_run):
                best_run = run
            run = list(by_rank[r])
        prev = r
    if len(run) > len(best_run):
        best_run = run
    return best_run


def _hand_rank_groups(hand):
    """Non-debuffed rank groups in deterministic rank order (never deck
    order): {rank: [indices]} plus the sorted rank list."""
    groups = {}
    for i, c in enumerate(hand):
        if not c.debuffed:
            groups.setdefault(c.rank, []).append(i)
    return [groups[r] for r in sorted(groups)]


def _kind_keep(groups, hand) -> list[int]:
    """Keep-set for a kind-plan (Trips / Full House): the best PAIR plus the
    second-best pair (callers already handled any ≥3 group as 'assembled',
    so every live group here is size ≤ 2). No pairs ⇒ nothing to build on.
    Quality-sorted, capped at 5, deterministic."""
    pairs = [g for g in groups if len(g) >= 2]
    if not pairs:
        return []
    ranked = sorted(pairs,
                    key=lambda g: (len(g), _card_sort_key(hand[g[0]])),
                    reverse=True)
    keep = list(ranked[0])
    if len(ranked) > 1:
        keep.extend(ranked[1][:2])
    keep.sort(key=lambda i: _card_sort_key(hand[i]), reverse=True)
    return keep[:5]


def _plan_keep_indices(hand, plan) -> list[int]:
    """The plan's cards in THIS hand (≤5, quality-best): the keep-set of the
    committed chase. Empty ⇒ nothing to chase toward this decision — either
    the line needs pure draws, or it is ALREADY ASSEMBLED and playing it
    beats fishing (M14b: seed 7 kept the same made pair for four straight
    discards because 'already holding it' read as 'keep chasing it')."""
    ht = plan["ht"]
    if ht == "Flush":
        s = plan["suit"]
        idx = [i for i, c in enumerate(hand)
               if not c.debuffed
               and (c.suit == s or c.enhancement == "Wild")]
        if not idx or len(idx) >= 5:
            return []          # assembled (or impossible) — play instead
        idx.sort(key=lambda i: _card_sort_key(hand[i]), reverse=True)
        return idx[:5]
    if ht == "Three of a Kind":
        groups = _hand_rank_groups(hand)
        trips = next((g for g in groups if len(g) >= 3), None)
        if trips is not None:
            return []          # trips already made — no chase
        # Biggest group (whole — a quad candidate is also the trips) + the
        # best second pair (fallback two pair, FH path). M14c: the earlier
        # single-pair keep threw away the second pair's equity.
        return _kind_keep(groups, hand)
    if ht == "Full House":
        groups = _hand_rank_groups(hand)
        trips = next((g for g in groups if len(g) >= 3), None)
        pair = next((g for g in groups if len(g) >= 2 and g is not trips),
                    None)
        if trips is not None and pair is not None:
            return []          # FH already assembled — play it
        return _kind_keep(groups, hand)
    if ht in ("Two Pair", "Pair"):
        # Not a chasable type any more; kept for stale-plan safety.
        groups = _hand_rank_groups(hand)
        pairs = sorted((g for g in groups if len(g) >= 2),
                       key=lambda g: _card_sort_key(hand[g[0]]),
                       reverse=True)
        if len(pairs) >= (2 if ht == "Two Pair" else 1):
            return []
        return list(pairs[0]) if pairs else []
    if ht in ("Straight", "Straight Flush"):
        idx = [i for i in _longest_run_indices(hand)]
        if not idx or len(idx) >= 5:
            return []
        idx.sort(key=lambda i: _card_sort_key(hand[i]), reverse=True)
        return idx[:5]
    return []


def _chase_discard(game, plan, base_score) -> dict | None:
    """Committed chase discard toward `plan`: keep the plan's cards, pool
    the rest (worst quality first, capped at the real-game 5-card limit).

    Two gates kill the audited doom-chases:
      EV   plan.prob * plan.S >= base_score * chase_min_ev_gain
           (never dump a working hand for a coin flip), and
      PROB P(plan assembles | keep-set + fresh draws) >= chase_min_prob
           (re-measured AFTER shedding the junk — the keep-set is what the
           draws have to land on)."""
    p = V10_PARAMS
    if game.discards_left <= 0 or not game.deck or len(game.hand) < 2:
        return None
    keep = _plan_keep_indices(game.hand, plan)
    if not keep:
        return None
    if plan["prob"] * plan["S"] < base_score * p["chase_min_ev_gain"]:
        return None
    M = _value_multiset(game.deck)
    N = sum(M.values())
    hs = max(1, len(game.hand))
    h, d = game.hands_left, game.discards_left
    fresh = max(0, min(N, d * min(3, hs) + (h - 1) * max(1, hs - 5)))
    keep_cards = [game.hand[i] for i in keep]
    if plan["ht"] == "Flush":
        raw = _plan_flush_prob(M, keep_cards, N, fresh, plan["suit"])
    else:
        raw = _plan_kind_prob(M, keep_cards, N, fresh, plan["ht"])
    prob = _plan_eff_prob(raw, plan["m"])
    if prob < p["chase_min_prob"]:
        return None
    kset = set(keep)
    off = sorted((i for i in range(len(game.hand)) if i not in kset),
                 key=lambda i: _card_sort_key(game.hand[i]))
    dset = off[:5]
    if not dset:
        return None
    return {"type": "discard", "cards": sorted(dset)}


# ────────────────────────────────────────────────────────────────────────────
# Tier 1 — survive (V9's play/discard core, re-armed with P(clear))
# ────────────────────────────────────────────────────────────────────────────

# Flat-chip jokers (§2): the ante-1 audit's missing piece. The grind line
# at antes 1-2 is pairs/two-pairs/trips, so these ride EVERY scoring hand:
#   j_sly +50 chips (Pair+) · j_clever +80 (Two Pair) · j_wily +100 (Trips)
#   j_banner +30 per remaining discard (≈ +120 on hand 1 at 4 discards)
_EARLY_CHIP_JOKERS = ("j_sly", "j_clever", "j_wily", "j_banner")


def _v10_joker_value(game, key: str, edition, ref, surplus=None) -> float:
    """joker_value with the early flat-chip bias (M14d): at ante ≤ 2 with
    fewer than 3 jokers, a flat-chip joker is worth more than its lifecycle/
    econ valuation suggests — it converts every grind hand into a blind
    clearer, which is exactly what the audited ante-1 deaths lacked (seed 0:
    two Buffoon packs, zero chips, died Big 198 short). Applied to BOTH the
    shop ranking and the booster-pack picks so the packs stop dealing econ
    jokers into a chips-starved run. Zero delta when gated off (byte-V9)."""
    v = joker_value(game, key, edition, ref, surplus)
    p = V10_PARAMS
    if (p["target_enabled"] and p["farm_clear_threshold"] < 1.0
            and p["early_chip_bias"] > 0
            and key in _EARLY_CHIP_JOKERS
            and game.ante <= 2 and len(game.jokers) < 3):
        v += p["early_chip_bias"]
    return v


def _v10_pack_value(game, key: str) -> float:
    """pack_value with the early Buffoon-open floor (M14): at ante ≤ 2 with
    fewer than 2 jokers, opening a Buffoon Pack beats almost any single shop
    item — two fresh joker picks compound for the whole run, while a weak
    Rare (j_order X3-straight with no straight deck) does not. Zero when
    gated off so the farming-off arm reproduces V9 exactly."""
    p = V10_PARAMS
    v = pack_value(game, key)
    if (p["target_enabled"] and p["farm_clear_threshold"] < 1.0
            and key.startswith("p_buffoon")
            and game.ante <= 2 and len(game.jokers) < 2):
        v = max(v, p["buffoon_open_value"])
    return v


def _buffoon_open_action(game) -> dict | None:
    """M14 shop rule: at ante ≤ 2 with fewer than 2 jokers, open an offered
    Buffoon Pack FIRST — before every other buy.

    A plain value comparison cannot express this: joker_value rates a weak
    ante-1 Rare ~1.6 (lifecycle/econ terms), far above any pack weight, yet
    the traced deaths bought exactly those Rares and skipped the $4 pack
    (seed 0: j_order for $8, left $1, died Big 252/450). Two random jokers
    compound across the run; the audit's rule is 'always open it unless far
    better' — and nothing offered in the first two shops is far better.
    None when gated off (the farming-off arm stays byte-V9)."""
    p = V10_PARAMS
    if (not p["target_enabled"] or not p["buffoon_first"]
            or p["farm_clear_threshold"] >= 1.0):
        return None
    if game.ante > 2 or len(game.jokers) >= 2:
        return None
    for i, item in enumerate(game.current_shop):
        if (item.kind == "booster" and not item.sold
                and item.key.startswith("p_buffoon")
                and item.discounted_price(game.shop_discount) <= game.dollars):
            return {"type": "buy", "item_idx": i}
    return None


def _plan_blind_id(game):
    """Identity of the current blind for plan-stickiness caching."""
    b = game.current_blind
    return (game.ante, getattr(b, "kind", ""), getattr(b, "boss_key", ""))


def _committed_plan(game, type_scores) -> dict | None:
    """The blind's chase plan, STICKY across decisions (M14b).

    Once a chase commits, re-selecting from scratch every discard lets a
    hair-thin probability difference flip the line mid-chase — seed 19
    switched Full-House→Straight on a 0.704-vs-0.731 nudge and threw away
    the MADE pairs to fish an unmade run. So: while the committed type stays
    feasible (still in _PLAN_TYPES, still fits the remaining hands, its
    re-measured effective probability still clears `chase_min_prob`), it IS
    the plan regardless of what the fresh argmax would say. Only a dead
    commitment falls through to a fresh `_blind_plan`.

    The cache lives ON the game object, keyed by blind identity, and every
    touch is behind `target_enabled` — the byte-V9 arm never sees it."""
    p = V10_PARAMS
    if not p["target_enabled"]:
        return None
    cache = getattr(game, "_m14_plan_cache", None)
    if cache is not None:
        if cache.get("blind") != _plan_blind_id(game):
            game._m14_plan_cache = None          # new blind
        else:
            plan = dict(cache["plan"])
            ht, suit = plan["ht"], plan.get("suit")
            S = type_scores.get(ht, 0)
            T = game.current_blind.chips_target - game.chips_scored
            if S and S > 0 and ht in _PLAN_TYPES and T > 0:
                m = math.ceil(T / float(S))
                if m <= min(p["chase_max_hands"], game.hands_left):
                    M, held, N, fresh = _plan_context(game)
                    if ht == "Flush":
                        raw = _plan_flush_prob(M, held, N, fresh, suit)
                    else:
                        raw = _plan_kind_prob(M, held, N, fresh, ht)
                    prob = _plan_eff_prob(raw, m)
                    if prob >= p["chase_min_prob"]:
                        plan.update(S=S, m=m, prob=prob)
                        return plan
            game._m14_plan_cache = None          # commitment died
    return _blind_plan(game, type_scores)


def _commit_plan(game, plan) -> None:
    """Pin `plan` as this blind's chase line (called when a chase FIRES)."""
    if V10_PARAMS["target_enabled"]:
        game._m14_plan_cache = {"blind": _plan_blind_id(game),
                                "plan": dict(plan)}


def _v10_survive(game, plays, type_scores):
    """Tier 1 with joker-aware targeting: identical to `_tier1_survive`
    (clearing play → good-hand rule → hold/slack discards) plus ONE inserted
    step — when the best play is NOT worth playing yet, try the committed
    chase discard toward the joker-aware plan. Every original branch and
    threshold is preserved; the chase only replaces SOME weak-hand discards
    with a better line."""
    p = ACTIVE_PARAMS
    if not plays:
        return {"type": "play", "cards": [0] if game.hand else []}

    best_score, best_combo, _ = plays[0]
    target = game.current_blind.chips_target - game.chips_scored

    if best_score >= target:
        clearing = [pl for pl in plays if pl[0] >= target]
        clearing.sort(key=lambda e: (len(e[1]), e[0]))
        _reset_chase(game)               # played a hand: doom counter resets
        return {"type": "play", "cards": list(clearing[0][1])}

    good_hand = best_score >= target * p["discard_play_good_hand"]
    # M14e chase discipline: never chase into the last hand (V9 hold-gate
    # parity) and never stack more than chase_max_consec chases without
    # playing — seed 59 burned all four discards pre-play on a re-firing FH
    # plan.
    chase_ok = (game.hands_left >= 2
                and game.ante <= V10_PARAMS["chase_max_ante"]
                and _chase_consec(game)
                < V10_PARAMS["chase_max_consec"])
    # Resolve the committed plan ONCE per decision (M14h): the chase branch
    # consumes it directly, and the fallback branches need its keep-set for
    # protection even when the consec guard blocks another chase commit.
    plan = None
    if (not good_hand and game.discards_left > 0 and len(game.deck) > 0
            and V10_PARAMS["target_enabled"]):
        plan = _committed_plan(game, type_scores)
    protect = None
    if plan is not None and V10_PARAMS["fallback_protect_plan"]:
        protect = set(_plan_keep_indices(game.hand, plan)) or None
    if (not good_hand and chase_ok and game.discards_left > 0
            and len(game.deck) > 0):
        if plan is not None:
            act = _chase_discard(game, plan, best_score)
            if act is not None:
                _commit_plan(game, plan)
                _spend_chase(game)
                return act

    if (not good_hand and game.discards_left > 0 and len(game.deck) > 0
            and p["discard_hold_until_clear"] and game.hands_left >= 2):
        dset, dscore = best_discard(game, base_score=best_score,
                                    protect=protect)
        if dset:
            return {"type": "discard", "cards": list(dset)}

    if not good_hand and game.discards_left > 0 and len(game.deck) > 0:
        dset, dscore = best_discard(game, base_score=best_score,
                                    protect=protect)
        if dscore > best_score * p["discard_slack"]:
            return {"type": "discard", "cards": list(dset)}

    _reset_chase(game)                   # played a hand: doom counter resets
    return {"type": "play", "cards": list(best_combo)}


def _tier1_survive(game, plays):
    """The V9 'just enough / discard EV' core, minus the pre-actions (Verdant
    sell, planet, consumable) which the cascade runs first. Byte-equivalent to
    V9's play/discard decision so the farming-off arm reproduces V9."""
    p = ACTIVE_PARAMS
    if not plays:
        return {"type": "play", "cards": [0] if game.hand else []}

    best_score, best_combo, _ = plays[0]
    target = game.current_blind.chips_target - game.chips_scored

    if best_score >= target:
        clearing = [pl for pl in plays if pl[0] >= target]
        clearing.sort(key=lambda e: (len(e[1]), e[0]))
        return {"type": "play", "cards": list(clearing[0][1])}

    good_hand = best_score >= target * p["discard_play_good_hand"]
    if (not good_hand and game.discards_left > 0 and len(game.deck) > 0
            and p["discard_hold_until_clear"] and game.hands_left >= 2):
        dset, dscore = best_discard(game, base_score=best_score)
        if dset:
            return {"type": "discard", "cards": list(dset)}

    if not good_hand and game.discards_left > 0 and len(game.deck) > 0:
        dset, dscore = best_discard(game, base_score=best_score)
        if dscore > best_score * p["discard_slack"]:
            return {"type": "discard", "cards": list(dset)}

    return {"type": "play", "cards": list(best_combo)}


# ────────────────────────────────────────────────────────────────────────────
# Tier 2 — value farming (§5.3, §6)
# ────────────────────────────────────────────────────────────────────────────

def _mail_target_rank(game):
    for j in game.jokers:
        if j.key in ("j_mail", "j_mail_in_rebate"):
            return j.state.get("rebate_rank")
    return None


def _trading_used(game) -> bool:
    for j in game.jokers:
        if j.key in ("j_trading", "j_trading_card"):
            return bool(j.state.get("used"))
    return False


def _value_play_combos(game, hand):
    """Cheap combos that deliberately score a valuable card (a 1-card 'play
    the gold seal' high card). The Psychic forces 5-card plays (handled by the
    boss filter via scored_plays)."""
    joker_keys = {j.key for j in game.jokers}
    combos = []
    for i, c in enumerate(hand):
        if c.debuffed:
            continue
        if (c.seal == "Gold" or c.enhancement == "Lucky"
                or ("j_business" in joker_keys and c.is_face_card)
                or ("j_rough_gem" in joker_keys and c.suit == "Diamonds")
                or ("j_ticket" in joker_keys and c.enhancement == "Gold")):
            combos.append((i,))
    return combos


def _value_discard_candidates(game, hand):
    """Discard sets that trigger a §6 discard lever (committed) plus the
    structure-aware survive pool (opportunistic)."""
    joker_keys = {j.key for j in game.jokers}
    n = len(hand)
    cands = []   # (indices_tuple, committed)

    if "j_faceless" in joker_keys:
        faces = [i for i, c in enumerate(hand)
                 if c.is_face_card and not c.debuffed]
        if len(faces) >= 3:
            cands.append((tuple(sorted(faces[:3])), True))

    if "j_mail" in joker_keys or "j_mail_in_rebate" in joker_keys:
        target = _mail_target_rank(game)
        if target is not None:
            idx = [i for i, c in enumerate(hand)
                   if c.rank == target and not c.debuffed]
            if idx:
                cands.append((tuple(sorted(idx)), True))

    purple = [i for i, c in enumerate(hand)
              if c.seal == "Purple" and not c.debuffed]
    if purple:
        cands.append((tuple(sorted(purple)), True))

    if ("j_trading" in joker_keys or "j_trading_card" in joker_keys) \
            and not _trading_used(game) and hand:
        junk = min(range(n), key=lambda i: _card_quality(hand[i]))
        cands.append(((junk,), True))

    pool, _target = _structure_pool(hand)
    if pool:
        keep = sorted(pool)[:ACTIVE_PARAMS["discard_max_size"]]
        if keep:
            cands.append((tuple(keep), False))  # opportunistic

    return cands


def _discard_value(game, discard_indices) -> float:
    """§6 Discard levers for a discard set."""
    joker_keys = {j.key for j in game.jokers}
    cards = [game.hand[i] for i in discard_indices]
    val = 0.0
    if "j_faceless" in joker_keys:
        faces = sum(1 for c in cards if c.is_face_card and not c.debuffed)
        if faces >= 3:
            val += _money_vp(5)
    if "j_mail" in joker_keys or "j_mail_in_rebate" in joker_keys:
        target = _mail_target_rank(game)
        if target is not None:
            n = sum(1 for c in cards if c.rank == target and not c.debuffed)
            val += _money_vp(5 * n)
    purple = sum(1 for c in cards if c.seal == "Purple" and not c.debuffed)
    if purple and len(game.consumable_hand) < game.consumable_slots:
        # The tarot a Purple seal grants will be USED by the (reshape-biased)
        # consumable policy, so its expected value carries the reshape bonus.
        etarot = (sum(_v10_tarot_value(game, k) for k in ALL_TAROTS)
                  / max(1, len(ALL_TAROTS)))
        val += etarot * purple
    if ("j_trading" in joker_keys or "j_trading_card" in joker_keys) \
            and not _trading_used(game):
        val += _money_vp(3)
    return val


def _guard(game, kind, combo, score, clearing, committed, type_scores) -> bool:
    """The standing trade-off: a value action must keep Survival P(clear)
    >= abandon_clear_floor; committed actions additionally keep Farm P(clear)
    >= farm_clear_threshold (§5.3)."""
    p = V10_PARAMS
    h = game.hands_left
    d = game.discards_left
    T = game.current_blind.chips_target - game.chips_scored
    if kind == "play":
        surv = estimate_clear_probability(game, h=h - 1, d=d, T=T - score,
                                          type_scores=type_scores)
        if surv < p["abandon_clear_floor"]:
            return False
        if committed:
            farm = estimate_clear_probability(
                game, h=h - 1 - p["farm_spare_hands"], d=d, T=T - score,
                type_scores=type_scores)
            if farm < p["farm_clear_threshold"]:
                return False
        return True
    # discard
    hand2 = [c for i, c in enumerate(game.hand) if i not in set(combo)]
    surv = estimate_clear_probability(game, h=h, d=d - 1, T=T, hand=hand2,
                                      type_scores=type_scores)
    if surv < p["abandon_clear_floor"]:
        return False
    if committed:
        farm = estimate_clear_probability(
            game, h=h - p["farm_spare_hands"], d=d - 1, T=T, hand=hand2,
            type_scores=type_scores)
        if farm < p["farm_clear_threshold"]:
            return False
    return True


def tier2_value(game, plays, type_scores):
    """Return a value action (play/discard) or None when nothing is worth
    farming (§5.3)."""
    p = V10_PARAMS
    hand = game.hand
    n = len(hand)
    T = game.current_blind.chips_target - game.chips_scored
    candidates = []  # (value_points, action, opportunistic, p_clear, chip_score)

    # ── Play candidates: top-K scored plays + value-targeted combos ────────
    combos = set()
    for score, combo, ht in plays[:p["eval_topk_value_play"]]:
        combos.add(tuple(combo))
    for combo in _value_play_combos(game, hand):
        combos.add(tuple(combo))

    boss = _boss_key(game)
    for combo in sorted(combos):
        if boss == "bl_psychic" and len(combo) != 5:
            continue
        cards = [hand[i] for i in combo]
        if not any(not c.debuffed for c in cards):
            continue
        held = [hand[i] for i in range(n) if i not in set(combo)]
        try:
            ht, sc = evaluate_hand(cards)
            score = eval_hand_score(game, ht, sc, cards, held_cards=held)
        except Exception:
            continue
        clearing = score >= T
        val = play_trigger_value(game, sc, ht)
        if clearing:
            val += expected_round_end_value(game, held)
        committed = not clearing
        if not _guard(game, "play", combo, score, clearing, committed,
                      type_scores):
            continue
        surv = estimate_clear_probability(game, h=game.hands_left - 1,
                                          d=game.discards_left, T=T - score,
                                          type_scores=type_scores)
        candidates.append((val, {"type": "play", "cards": list(combo)},
                           not committed, surv, score))

    # ── Discard candidates ─────────────────────────────────────────────────
    for dcombo, committed in _value_discard_candidates(game, hand):
        if not dcombo:
            continue
        val = _discard_value(game, dcombo)
        if val <= 0.0:
            continue
        if not _guard(game, "discard", dcombo, 0, False, committed,
                      type_scores):
            continue
        hand2 = [c for i, c in enumerate(hand) if i not in set(dcombo)]
        surv = estimate_clear_probability(game, h=game.hands_left,
                                          d=game.discards_left - 1, T=T,
                                          hand=hand2, type_scores=type_scores)
        candidates.append((val, {"type": "discard", "cards": list(dcombo)},
                           not committed, surv, 0))

    if not candidates:
        return None

    def rank(e):
        val, act, opp, surv, score = e
        # Final `str(act)` tie-break makes the argmax fully deterministic (§7).
        return (val + (p["tier2_opp_bonus"] if opp else 0.0), surv, score,
                str(act))

    val, act, opp, surv, score = max(candidates, key=rank)
    if val <= p["tier2_min_value"]:
        return None
    return act


# ────────────────────────────────────────────────────────────────────────────
# Cascade + policies
# ────────────────────────────────────────────────────────────────────────────

def _v10_decide_hand(game) -> dict:
    """The tier cascade (§5)."""
    p = V10_PARAMS

    # Pre-actions (unchanged from v9).
    if (game.current_blind.boss_key == "bl_verdant"
            and game.verdant_debuff and game.jokers):
        worst = worst_joker_idx(game)
        if worst is not None:
            return {"type": "sell_joker", "joker_idx": worst}

    if not game.hand:
        return {"type": "play", "cards": []}

    plays = scored_plays(game, topk=ACTIVE_PARAMS["eval_topk_play"])
    act = maybe_use_planet(game, plays)
    if act is not None:
        return act

    if ACTIVE_PARAMS["use_tarots"]:
        act = _v10_decide_consumable(game)
        if act is not None:
            return act

    if not plays:
        return {"type": "play", "cards": [0] if game.hand else []}

    # Farming-off fast path: reproduce V9's decision exactly (and at V9 speed).
    if p["farm_clear_threshold"] >= 1.0:
        return _tier1_survive(game, plays)

    # P(clear) gate (human-fair, composition-only).
    type_scores = _compute_type_scores(game, plays)
    p_clear = estimate_clear_probability(game, type_scores=type_scores)

    if p_clear >= p["farm_clear_threshold"]:
        act = tier2_value(game, plays, type_scores)
        if act is not None:
            return act

    return _v10_survive(game, plays, type_scores)


class HeuristicV10(HeuristicV9):
    """Layer-0 heuristic + the in-blind tiered goal hierarchy + deck
    reshaping. The hand decision is the §5 tier cascade; the shop/booster
    decisions are V9's with the reshape-biased tarot/standard values."""
    policy_name = "heuristic_v10"

    def __init__(self, params=None):
        super().__init__(params)         # ACTIVE_PARAMS + shop bookkeeping
        if params:
            V10_PARAMS.update(params)     # farm + reshape knobs

    def decide(self, game) -> dict:
        st = game.state
        if st == State.SELECTING_HAND:
            return _v10_decide_hand(game)
        if st == State.SHOP:
            if not self._in_shop:
                self._in_shop = True
                self._rerolls_this_shop = 0
            act = _v10_decide_shop(game, self._rerolls_this_shop)
            if act.get("type") == "reroll":
                self._rerolls_this_shop += 1
            elif act.get("type") == "leave_shop":
                self._in_shop = False
            return act
        if st == State.BOOSTER_OPEN:
            return _v10_decide_booster(game)
        return super().decide(game)


class SearchShopV10(SearchShopV9):
    """Layer-1: the tiered in-blind decisions + the comparative mean-measure
    shop search (RULING-L1). The in-blind tiers and the deck-reshaping apply
    on EVERY hand; the shop search ranks by the reshape-biased values."""
    policy_name = "search_shop_v10"

    def __init__(self, params=None, **kwargs):
        super().__init__(params, **kwargs)
        if params:
            V10_PARAMS.update(params)

    def _search_shop(self, game) -> dict:
        """SearchShopV9's comparative search, ranked by the v10 reshape-
        biased values (deck-reshaping reaches the L1 search too)."""
        p = ACTIVE_PARAMS
        ref = reference_hand(game)
        surplus = forecast_beatable(game, p["tilt_surplus_margin"], ref)
        buys, need_sell = _v10_rank_shop_items(game, ref, surplus)
        if need_sell is not None:
            return {"type": "sell_joker", "joker_idx": need_sell[1]}
        save_mode = (
            game.ante > 2
            and game.dollars < p["interest_target"]
            and max((v for v, _ in buys), default=0.0) < p["save_strong_value"]
            and forecast_beatable(game, p["save_margin"], ref)
        )
        if buys:
            buys.sort(key=lambda b: (b[0], _KIND_RANK.get(
                game.current_shop[b[1]].kind, 1)), reverse=True)
            for value, idx in buys[:self._candidate_cap]:
                item = game.current_shop[idx]
                price = item.discounted_price(game.shop_discount)
                if (price <= game.dollars
                        and (not save_mode or value >= p["save_strong_value"])
                        and worth_spending(game, price, value)):
                    return {"type": "buy", "item_idx": idx}
        return {"type": "leave_shop"}

    def decide(self, game) -> dict:
        st = game.state
        if st == State.SELECTING_HAND:
            return _v10_decide_hand(game)
        if st == State.BOOSTER_OPEN:
            return _v10_decide_booster(game)
        if st != State.SHOP:
            return super().decide(game)
        # Shop flow mirrors SearchShopV9.decide but the post-search path uses
        # the v10 shop decision (reshape-biased consumable usage + buys).
        if not self._in_shop:
            self._in_shop = True
            self._rerolls_this_shop = 0
            self._searched_this_visit = False
        if (self._searches_done < self._search_shops
                and not self._searched_this_visit):
            self._searched_this_visit = True
            act = (self._search_shop_rollout(game) if self._lookahead
                   else self._search_shop(game))
            if act.get("type") == "leave_shop":
                self._searches_done += 1
                self._in_shop = False
            return act
        act = _v10_decide_shop(game, self._rerolls_this_shop)
        if act.get("type") == "reroll":
            self._rerolls_this_shop += 1
        elif act.get("type") == "leave_shop":
            self._in_shop = False
            if self._searched_this_visit:
                self._searches_done += 1
                self._searched_this_visit = False
        return act
