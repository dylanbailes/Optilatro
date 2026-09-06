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
import random
import json
from itertools import combinations
from pathlib import Path

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
    _EvalGame,
    scored_plays,
    best_play_score,
    _boss_play_filter,
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
    _value_multiset,
    _sample_value_keys,
    _keys_to_cards,
    CHIPS_JOKERS,
    ECONOMY_JOKERS,
    XMULT_JOKERS,
    RETRIGGER_JOKERS,
)
from .agent_l1 import SearchShopV9
from .graph_v9 import deck_groups

try:
    from tools.portfolio import (
        classify_joker,
        extract_features_from_state,
        extract_game_features,
        CHIPS_JOKERS as PORTFOLIO_CHIPS,
        FLAT_MULT_JOKERS as PORTFOLIO_FLAT,
        XMULT_JOKERS as PORTFOLIO_XMULT,
        SCALING_JOKERS as PORTFOLIO_SCALING,
        ECON_JOKERS as PORTFOLIO_ECON,
        RETRIGGER_JOKERS as PORTFOLIO_RETRIGGER,
    )
except ImportError:
    import sys
    _root = Path(__file__).resolve().parent.parent.parent.parent
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))
    from tools.portfolio import (
        classify_joker,
        extract_features_from_state,
        extract_game_features,
        CHIPS_JOKERS as PORTFOLIO_CHIPS,
        FLAT_MULT_JOKERS as PORTFOLIO_FLAT,
        XMULT_JOKERS as PORTFOLIO_XMULT,
        SCALING_JOKERS as PORTFOLIO_SCALING,
        ECON_JOKERS as PORTFOLIO_ECON,
        RETRIGGER_JOKERS as PORTFOLIO_RETRIGGER,
    )

CHIPS_JOKERS = PORTFOLIO_CHIPS
FLAT_MULT_JOKERS = PORTFOLIO_FLAT
XMULT_JOKERS = PORTFOLIO_XMULT
SCALING_JOKERS = PORTFOLIO_SCALING
ECON_JOKERS = PORTFOLIO_ECON
RETRIGGER_JOKERS = PORTFOLIO_RETRIGGER

EARLY_FLAT_CHIPS_JOKERS = {
    "j_sly", "j_wily", "j_clever", "j_devious", "j_crafty", "j_half",
    "j_banner", "j_mystic_summit", "j_scary_face", "j_odd_todd",
    "j_scholar", "j_even_steven", "j_ice_cream", "j_blue_joker", "j_stuntman",
}
COMBAT_SCALING_JOKERS = PORTFOLIO_SCALING - {
    "j_egg", "j_gift", "j_gift_card", "j_rocket", "j_satellite",
    "j_burnt", "j_burnt_joker", "j_space", "j_space_joker",
}
RELIABLE_XMULT_JOKERS = {
    "j_cavendish", "j_trio", "j_tribe",
    "j_card_sharp", "j_ramen", "j_constellation", "j_hologram",
    "j_baseball", "j_acrobat", "j_stuntman", "j_photograph",
    "j_blueprint", "j_brainstorm", "j_baron", "j_ancient",
}
HIGH_LEVERAGE_SCORING_JOKERS = {
    "j_cavendish", "j_duo", "j_trio", "j_family", "j_order", "j_tribe",
    "j_card_sharp", "j_baseball", "j_acrobat", "j_constellation", "j_hologram",
    "j_blueprint", "j_brainstorm", "j_baron", "j_ancient", "j_ramen", "j_stuntman", "j_photograph",
}
PREMIER_XMULT_FINISHERS = {
    "j_cavendish", "j_baseball", "j_constellation", "j_acrobat",
}
DEAD_ECONOMY_JOKERS = {
    "j_egg", "j_ticket", "j_golden_ticket", "j_todo_list", "j_to_do_list", "j_faceless",
    "j_delayed_grat", "j_golden", "j_business", "j_business_card",
    "j_satellite", "j_cloud_9", "j_rocket", "j_to_the_moon", "j_trading", "j_trading_card",
    "j_gift", "j_gift_card", "j_mail", "j_mail_in_rebate", "j_reserved_parking",
    "j_rough_gem", "j_credit_card", "j_astronomer", "j_chaos",
}


def build_interactions(f: dict[str, float]) -> dict[str, float]:
    """Add explicit domain interaction terms representing Balatro mechanics."""
    res = dict(f)
    ante = f.get("ante", 1.0)
    n_chips = f.get("n_chips", 0.0)
    n_flat = f.get("n_flat_mult", 0.0)
    n_xmult = f.get("n_xmult", 0.0)
    n_scaling = f.get("n_scaling", 0.0)
    n_econ = f.get("n_econ", 0.0)

    # Multiplicative scoring synergy
    res["inter_chips_mult"] = n_chips * (n_flat + n_scaling)
    res["inter_mult_xmult"] = (n_flat + n_scaling) * n_xmult
    res["inter_chips_xmult"] = n_chips * n_xmult
    res["inter_ante_xmult"] = ante * n_xmult
    res["inter_late_econ_penalty"] = max(0.0, ante - 3.0) * n_econ
    res["early_econ"] = n_econ if ante <= 3.0 else 0.0
    res["late_econ"] = n_econ if ante >= 4.0 else 0.0
    res["inter_late_zero_xmult"] = (1.0 if (ante >= 4.0 and n_xmult == 0.0) else 0.0)
    return res


_SHOP_MODEL_DATA: dict[str, Any] | None = None
_SHOP_MODEL_PRECOMPUTED: tuple[float, list[tuple[str, float]]] | None = None


def _load_shop_value_model(path: Path | str | None = None) -> dict[str, Any] | None:
    """Load and cache shop value model weights with precomputed linear coefficients."""
    global _SHOP_MODEL_DATA, _SHOP_MODEL_PRECOMPUTED
    if path is None:
        path = Path(__file__).resolve().parent / "shop_model.json"
    else:
        path = Path(path)
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        feat_order = data["feat_order"]
        mean = data["mean"]
        std = data["std"]
        w = data["w"]
        bias = float(data.get("bias", w[-1]))

        # Precompute linear weights and bias for fast dot-product:
        # z = bias + sum(w_i * (f_i - mu_i) / sigma_i)
        #   = (bias - sum(w_i * mu_i / sigma_i)) + sum((w_i / sigma_i) * f_i)
        c0 = bias
        coeffs = []
        for i, name in enumerate(feat_order):
            sd = std[i] if std[i] > 1e-9 else 1.0
            wi = w[i]
            ci = wi / sd
            c0 -= ci * mean[i]
            coeffs.append((name, ci))

        _SHOP_MODEL_DATA = data
        _SHOP_MODEL_PRECOMPUTED = (c0, coeffs)
        return data
    except Exception:
        return None


# Load and precompute model coefficients upon module load
_load_shop_value_model()


def evaluate_shop_value(features: dict[str, float]) -> float:
    """Pure-Python evaluation of shop state value model V(s) -> P(Win Ante 8).

    Evaluates in <5µs with zero runtime dependencies.
    """
    if _SHOP_MODEL_PRECOMPUTED is None:
        _load_shop_value_model()
    if _SHOP_MODEL_PRECOMPUTED is None:
        return 0.5

    f_inter = build_interactions(features)
    c0, coeffs = _SHOP_MODEL_PRECOMPUTED
    z = c0
    for name, ci in coeffs:
        z += ci * f_inter.get(name, 0.0)

    z = max(-30.0, min(30.0, z))
    return 1.0 / (1.0 + math.exp(-z))


def evaluate_game_shop_value(game: Any) -> float:
    """Extract features from live game and evaluate shop state value V(s)."""
    feat = extract_game_features(game)
    return evaluate_shop_value(feat)


# ────────────────────────────────────────────────────────────────────────────
# V10 tunables (farm gate / value mode). Independent of V9's PARAMS; the A/B
# `--params '{...}'` override targets these knobs only.
# ────────────────────────────────────────────────────────────────────────────

V10_DEFAULTS = {
    "farm_clear_threshold": 0.90,   # enter value mode when Farm P(clear) >= this
    "abandon_clear_floor": 0.75,    # hard-survive below this (abandon-farm)
    "scaling_accel_enabled": True,   # accelerate active scaling jokers during safe blinds
    "scaling_clear_threshold": 0.98, # clear probability threshold for safe-blind scaling
    "scaling_min_hands": 2,          # minimum hands remaining to attempt scaling
    "pclear_pick_ante": 0,          # at ante <= this, pick hand actions by a
                                    # 1-ply compositional P(clear) search
                                    # instead of the fixed tier cascade
    "mc_pick_ante": 0,              # at ante <= this, pick hand actions by
                                    # Monte-Carlo mean-EV over composition-
                                    # sampled continuations (human-fair:
                                    # throwaway RNG, never the run stream)
    "farm_rate_share": 0.75,        # farming rate sanity: enter value mode
                                    # only when top play >= this fraction of
                                    # the per-hand share of remaining target
                                    # (0 = off; P(clear) alone over-trusts
                                    # doomed boards and farms hands away)
    "ante1_pace_rule": True,        # multi-hand budget rule at ante 1: if best
                                    # play >= remaining_target / hands_left, play
                                    # immediately instead of gambling discards on
                                    # thin structural upgrades
    "ante1_pace_mult": 1.0,         # pace multiplier: 1.0 = exactly on pace
    "ante1_dig_discards": False,    # Bellatro-101 round-1 doctrine: at ante 1,
                                    # spend EVERY discard digging before
                                    # playing any non-clearing hand, even
                                    # over a held flush (draw the better one)
    "ante1_planet_main": False,     # at ante 1, use a held Planet for the
                                    # run's main hand type even when that
                                    # type is not in the current hand's top-3
                                    # plays (a level is permanent chips/mult
                                    # - exactly the boss close-miss margin)
    "sampled_pick_ante": 2,         # at ante <= this AND the blind projects
                                    # marginal, pick actions by short greedy
                                    # continuations over composition-sampled
                                    # synthetic shuffles (human-fair: samples
                                    # come from the deck multiset via a
                                    # throwaway RNG, never the run stream)
    "sampled_pick_manacle_only": True,
    "model_gate": False,            # use the learned clear-model (fit on
                                    # rollout outcomes) as the calibrated
                                    # danger gauge: gates farming and
                                    # widens sampled-picker scope to any
                                    # blind it flags as at-risk
    "model_pick_below": 0.85,       # model P(clear) below this -> sampled
                                    # picker may fire on any boss blind
    "model_farm_floor": 0.5,        # model P(clear) below this -> no farming
    "ante1_reroll_reserve": 0,      # at ante 1 with no scoring joker owned,
                                    # hold this much cash for rerolls instead
                                    # of spending down (0 = off)
    "early_struct_ante": 2,         # at ante <= this, loosen the structure
                                    # chase triggers (below) so marginal
                                    # ante-1/2 blinds assemble straights and
                                    # flushes they currently miss (0 = off)
    "early_struct_min_run": 3,      # straight-chase trigger while gated
    "early_struct_min_suit": 3,     # flush-chase trigger while gated
    "farm_spare_hands": 1,          # hands reserved when measuring Farm P(clear)
    "tier2_opp_bonus": 0.02,        # value-point bonus for opportunistic actions
    "tier2_min_value": 0.0,         # min value points to bother farming
    "hook_hold_discount": True,     # discount held value under The Hook
    "tooth_money_net": True,        # subtract $1/card played under The Tooth
    "eval_topk_value_play": 8,      # top-K scored plays considered in value mode
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
    "ante1_chip_bias": 0.8,
    "ante2_chip_bias": 0.5,
    "early_struct_ante": 2,
    "early_shop_reserve": 4,
    "swap_delta_threshold": 0.005,
    "search_shops": 999,
    "ante1_econ_discount": 0.35,
    "ante1_voucher_gate": True,
    "ante1_kd_boost": True,
    "ante1_good_hand": 0.65,
    "sell_uses_full_value": True,
    "ante1_buffoon_boost": 0.20,
    "enhance_into_play_ante": 0,    # at ante <= this, mid-blind enhancement
                                    # tarots (Empress/Hierophant/Lovers)
                                    # target cards INSIDE the top plays,
                                    # chosen to maximize the engine-scored
                                    # result (0 = off; V9 rule = top-quality
                                    # cards anywhere in hand, which lands
                                    # Mult/Bonus on off-suit cards while the
                                    # flush is the scoring hand)
    "enhance_into_play_topk": 3,    # top-K plays considered as target hosts
    "hold_enh_for_blind": False,    # in the SHOP, hold Empress/Hierophant/
                                    # Lovers/Magician instead of spending them
                                    # on leftover-hand cards - deploy them mid-
                                    # blind via enhance_into_play where the
                                    # boost pays on the actual scoring hand
                                    # (measured NET-NEGATIVE paired on 0-99:
                                    #  6W/2D vs baseline 7W/2D - stays off)
    "engineless_urgency_ante": 2,   # at ante <= this, when NO owned joker
                                    # measurably adds chips/mult (engineless
                                    # death boards: mail/ticket/todo_list...),
                                    # boost scoring-joker shop values and
                                    # discount economy jokers like ante-1 does
    "engineless_urgency_bonus": 0.15,  # value bonus for chips/xmult/retrigger
    "engineless_reroll_extra": 0,   # extra rerolls per shop when engineless at
                                    # ante <= engineless_urgency_ante (hunt an
                                    # engine instead of leaving cash unspent)
    "singles_window": False,        # score single-card plays even when they
                                    # sit outside the priority-sorted window:
                                    # retrigger/enhancement engines (Hanging
                                    # Chad, Scholar, Photograph, Greedy...)
                                    # make ONE card outscore a flush
                                    # (diag_topplay_miss.py: median gap 760)
    "discard_two_hand_ante": 0,     # at ante <= this, when the blind cannot be
                                    # cleared in one hand, evaluate discards by
                                    # the SUM of the top-2 plays after refill
                                    # (Bellatro-101: "any two five-card hands
                                    # will work") instead of the single best
    "joker_type_chase_ante": 0,     # at ante <= this, when a hand-type joker's
                                    # target type is NOT assembled in the plays,
                                    # commit discards to the partial structure
                                    # (keep the trips for Family/FoK, the 4-suit
                                    # for Tribe/Flush...) instead of generic EV
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


def _copy_target_strength(j) -> float:
    k = getattr(j, "key", "")
    if k == "j_cavendish": return 3.0
    if k in ("j_triboulet", "j_caino", "j_yorick"): return 2.8
    if k == "j_constellation": return 2.7
    if k == "j_hologram": return 2.6
    if k == "j_ancient": return 2.5
    if k in ("j_baron", "j_photograph", "j_hanging_chad"): return 2.4
    if k in ("j_baseball", "j_duo", "j_trio", "j_family", "j_order", "j_tribe"): return 2.3
    if k in ("j_ramen", "j_card_sharp", "j_campfire", "j_stuntman"): return 2.2
    if k in PORTFOLIO_XMULT: return 2.0
    if k in COMBAT_SCALING_JOKERS: return 1.5
    if k in PORTFOLIO_FLAT: return 1.0
    if k in PORTFOLIO_CHIPS: return 0.8
    return 0.1


def _optimize_joker_order(game) -> None:
    """Optimize joker order in-place on game.jokers for copy jokers and trigger ordering.
    Human-fair: rearranging jokers is a free zero-cost action at any time in Balatro.
    Only active when farm_clear_threshold < 1.0 (V10 mode)."""
    if V10_PARAMS.get("farm_clear_threshold", 0.90) >= 1.0:
        return
    jokers = getattr(game, "jokers", None)
    if not jokers or len(jokers) <= 1:
        return

    has_brainstorm = any(j.key == "j_brainstorm" for j in jokers)
    has_blueprint = any(j.key == "j_blueprint" for j in jokers)
    has_ceremonial = any(j.key == "j_ceremonial" for j in jokers)

    if not (has_brainstorm or has_blueprint or has_ceremonial):
        return

    brainstorms = [j for j in jokers if j.key == "j_brainstorm"]
    blueprints = [j for j in jokers if j.key == "j_blueprint"]
    ceremonials = [j for j in jokers if j.key == "j_ceremonial"]
    others = [j for j in jokers if j.key not in ("j_brainstorm", "j_blueprint", "j_ceremonial")]

    if not others:
        return

    others.sort(key=_copy_target_strength, reverse=True)
    best_target = others[0]
    rest = others[1:]

    new_jokers = []
    if blueprints:
        new_jokers.extend(blueprints)
        new_jokers.append(best_target)
        new_jokers.extend(rest)
        new_jokers.extend(brainstorms)
    elif brainstorms:
        new_jokers.append(best_target)
        new_jokers.extend(rest)
        new_jokers.extend(brainstorms)
    else:
        new_jokers = others

    if ceremonials:
        new_jokers.extend(ceremonials)

    game.jokers = new_jokers


def _v10_worst_joker_idx(game, ref=None):
    """Worst-joker via full joker_value with portfolio anchor protection.
    Protects essential anchors (sole chips, sole flat mult, sole xMult, scaling)
    unless in late-game liquidation (Ante >= 7) or when premier finishers are available.
    Aggressively identifies dead/redundant economy jokers when a premier finisher
    or xMult is available in shop or in late game."""
    if V10_PARAMS.get("farm_clear_threshold", 0.90) >= 1.0 or not V10_PARAMS.get("sell_uses_full_value", True):
        from .agent_v9 import worst_joker_idx as _orig
        return _orig(game, ref)
    if not game.jokers:
        return None
    owned = [j.key for j in game.jokers]
    n_xmult = sum(1 for k in owned if k in PORTFOLIO_XMULT or k in PREMIER_XMULT_FINISHERS)
    n_chips = sum(1 for k in owned if k in PORTFOLIO_CHIPS)
    n_flat = sum(1 for k in owned if k in PORTFOLIO_FLAT)

    has_premier_in_shop = any(
        not getattr(item, "sold", False) and getattr(item, "kind", "") == "joker"
        and (item.key in PREMIER_XMULT_FINISHERS or item.key in RELIABLE_XMULT_JOKERS or item.key in HIGH_LEVERAGE_SCORING_JOKERS)
        for item in getattr(game, "current_shop", [])
    )

    vals = []
    for i, j in enumerate(game.jokers):
        is_dead_econ = j.key in DEAD_ECONOMY_JOKERS or j.key in PORTFOLIO_ECON
        # Protect Blueprint and Brainstorm from being sold immediately if scoring engine present
        if j.key in ("j_blueprint", "j_brainstorm") and _has_scoring_joker(game, ref):
            continue
        if game.ante < 7 and not has_premier_in_shop:
            # Protect essential anchors before Ante 7 when no premier finisher is in shop
            if n_xmult <= 1 and (j.key in PORTFOLIO_XMULT or j.key in PREMIER_XMULT_FINISHERS):
                continue
            if n_chips <= 1 and j.key in PORTFOLIO_CHIPS and not is_dead_econ:
                continue
            if n_flat <= 1 and j.key in PORTFOLIO_FLAT and not is_dead_econ:
                continue
            if j.key in COMBAT_SCALING_JOKERS and not is_dead_econ:
                continue
        else:
            # Late-game liquidation (Ante >= 7) or premier finisher available:
            # Protect sole true xMult finishers, aggressively liquidate economy
            if n_xmult <= 1 and (j.key in PORTFOLIO_XMULT or j.key in PREMIER_XMULT_FINISHERS):
                continue
            if n_flat <= 1 and j.key in PORTFOLIO_FLAT and not is_dead_econ:
                continue
            if n_chips <= 1 and j.key in PORTFOLIO_CHIPS and not is_dead_econ:
                continue

        v = joker_value(game, j.key, j.edition, ref)
        if j.key in ("j_blueprint", "j_brainstorm") and _has_scoring_joker(game, ref):
            v = max(v, 1.5)
        # Aggressively identify dead/redundant economy jokers
        if (has_premier_in_shop or game.ante >= 7) and is_dead_econ:
            v -= 10.0
        elif game.ante >= 6 and is_dead_econ:
            v -= 4.0
        vals.append((v, i))

    if not vals:
        for i, j in enumerate(game.jokers):
            if n_xmult <= 1 and (j.key in PORTFOLIO_XMULT or j.key in PREMIER_XMULT_FINISHERS):
                continue
            if j.key in ("j_blueprint", "j_brainstorm") and _has_scoring_joker(game, ref):
                continue
            v = joker_value(game, j.key, j.edition, ref)
            if j.key in ("j_blueprint", "j_brainstorm") and _has_scoring_joker(game, ref):
                v = max(v, 1.5)
            if (has_premier_in_shop or game.ante >= 7) and (j.key in DEAD_ECONOMY_JOKERS or j.key in PORTFOLIO_ECON):
                v -= 10.0
            elif game.ante >= 6 and (j.key in DEAD_ECONOMY_JOKERS or j.key in PORTFOLIO_ECON):
                v -= 4.0
            vals.append((v, i))
        if not vals:
            return None

    vals.sort()
    return vals[0][1]


# Joker-aware keep: which cards to never discard because a joker wants them.
# Hand-type affinities for chips/xMult jokers (canonical §2). Keep logic mirrors
# _structure_pool but is driven by owned jokers, not hand structure.
_CHIPS_HAND_MAP = {
    "j_sly": "Pair", "j_wily": "Three of a Kind", "j_clever": "Two Pair",
    "j_devious": "Straight", "j_crafty": "Flush",
}
_XMULT_HAND_MAP = {
    "j_duo": "Pair", "j_trio": "Three of a Kind", "j_family": "Four of a Kind",
    "j_order": "Straight", "j_tribe": "Flush",
}

def joker_target_hand_type(game):
    """Hand type to chase for owned jokers — the highest-value chip/xMult engine's hand.
    Returns None if no hand-specific joker. Gated farm<1.0.

    Boss-blind aware: under a Boss the target must still CLEAR (Boss 600 needs
    more than a bare Pair), so hand types that scale with jokers win:
    Photograph → Flush (face inside flush = x2 on top of flush base §2/§16),
    chips jokers keep their mapped type."""
    try:
        if V10_PARAMS.get("farm_clear_threshold", 0.9) >= 1.0:
            return None
    except Exception:
        return None
    if not getattr(game, "jokers", None):
        return None
    candidates = []
    for j in game.jokers:
        ht = _CHIPS_HAND_MAP.get(j.key) or _XMULT_HAND_MAP.get(j.key)
        if ht:
            # Value via joker_value on reference hand — higher value = more important to chase
            try:
                from .agent_v9 import reference_hand as _ref
                ref = _ref(game)
                v = joker_value(game, j.key, j.edition, ref)
            except Exception:
                v = 0.0
            candidates.append((v, ht))
    # Photograph — prefer Flush if flush draw exists, else Pair with face
    owned = {j.key for j in game.jokers}
    if "j_photograph" in owned:
        # Photograph wants face + hand, Flush with face is ideal per §2 (x2 first face)
        candidates.append((0.20, "Flush"))
    if not candidates:
        return None
    candidates.sort(reverse=True)
    return candidates[0][1]


# Chips-joker upgrade path: a trips joker (j_wily) wants a Full House when the
# hand already holds trips — the +100 Chips rides on any hand containing a
# Three of a Kind (§2 "contains"), and a full house scores far more chips.
_UPGRADE_MAP = {
    "Three of a Kind": "Full House",
    "Pair": "Two Pair",
}

def _upgrade_target(hand, hand_type: str):
    """When `hand` already contains the base structure of `hand_type`, return
    the upgraded type worth chasing (trips→full house, pair→two pair)."""
    from collections import Counter
    cnt = Counter(c.rank for c in hand)
    if hand_type == "Three of a Kind" and any(c >= 3 for c in cnt.values()):
        return _UPGRADE_MAP[hand_type]
    if hand_type == "Pair" and sum(1 for c in cnt.values() if c >= 2) >= 2:
        return _UPGRADE_MAP[hand_type]
    return None

def _hand_keep_indices(hand, hand_type: str):
    """Indices of cards in `hand` that support `hand_type` and should not be discarded."""
    n = len(hand)
    if hand_type == "High Card":
        return set()
    if hand_type in ("Pair", "Three of a Kind", "Four of a Kind", "Full House"):
        # Keep any rank that appears at least twice (pairs/trips that can become trips/quads/full house)
        from collections import Counter
        cnt = Counter(c.rank for c in hand)
        keep_ranks = {r for r,c in cnt.items() if c >= 2}
        if hand_type == "Three of a Kind" and not keep_ranks:
            # No pair to start — keep highest rank as seed for trips
            keep_ranks = {max(cnt, key=cnt.get)} if cnt else set()
        return {i for i,c in enumerate(hand) if c.rank in keep_ranks}
    if hand_type == "Two Pair":
        from collections import Counter
        cnt = Counter(c.rank for c in hand)
        keep_ranks = {r for r,c in cnt.items() if c >= 2}
        return {i for i,c in enumerate(hand) if c.rank in keep_ranks}
    if hand_type == "Straight":
        # Keep longest straight run
        ranks = sorted({c.rank for c in hand}, reverse=True)
        best_run = []
        run = [ranks[0]] if ranks else []
        for r in ranks[1:]:
            if run[-1] - r == 1:
                run.append(r)
            else:
                if len(run) > len(best_run):
                    best_run = run
                run = [r]
        if len(run) > len(best_run):
            best_run = run
        in_run = set(best_run)
        return {i for i,c in enumerate(hand) if c.rank in in_run}
    if hand_type == "Flush":
        from collections import Counter
        cnt = Counter(c.suit for c in hand)
        if not cnt:
            return set()
        top_suit = cnt.most_common(1)[0][0]
        return {i for i,c in enumerate(hand) if c.suit == top_suit}
    return set()

def joker_keep_indices(hand, game) -> set:
    """Set of hand indices that should not be discarded because an owned joker needs them.
    Gated on farming (so farm_off stays byte-identical) and ante-1 only for now."""
    # Only ante-1 and farming on — keep farm_off identical
    try:
        if V10_PARAMS.get("farm_clear_threshold", 0.9) >= 1.0:
            return set()
    except Exception:
        return set()
    if not getattr(game, "jokers", None):
        return set()
    keep = set()
    owned = {j.key for j in game.jokers}
    # Photograph — keep all face cards (§2 On Scored x2 first face)
    if "j_photograph" in owned:
        keep.update(i for i,c in enumerate(hand) if c.is_face_card)
    # Chip jokers — keep their hand-type support; upgrade trips→full house /
    # pair→two pair when the hand already holds the base structure
    for key, ht in _CHIPS_HAND_MAP.items():
        if key in owned:
            keep.update(_hand_keep_indices(hand, ht))
            up = _upgrade_target(hand, ht)
            if up:
                keep.update(_hand_keep_indices(hand, up))
    # xMult engines — keep their hand-type support (Duo/Trio/Family/Order/Tribe)
    for key, ht in _XMULT_HAND_MAP.items():
        if key in owned:
            keep.update(_hand_keep_indices(hand, ht))
            up = _upgrade_target(hand, ht)
            if up:
                keep.update(_hand_keep_indices(hand, up))
    # For chips jokers that want High Card (e.g., j_half) — no keep
    return keep


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
    ("j_shoot_the_moon", 12),  # +13 Mult per Queen held
    ("j_hit_the_road", 11),    # x0.5 Mult per discarded Jack
    ("j_cloud_9", 9),          # $1 per 9 in deck
    ("j_scholar", 14),         # +20 Chips, +4 Mult per played Ace
    ("j_walkie_talkie", 10),   # +10 Chips, +4 Mult per played 10 (or 4)
    ("j_wee", 2),              # +8 Chips per played 2
)

# Rank group engines: owning one targets valid rank subset
_RANK_GROUP_ENGINES = {
    "j_even_steven": {2, 4, 6, 8, 10},
    "j_odd_todd": {14, 9, 7, 5, 3},
    "j_fibonacci": {14, 2, 3, 5, 8},
    "j_hack": {2, 3, 4, 5},
}

# Kind-stack hand types: Four of a Kind / Full House want a rank stack.
_KIND_STACK_HANDS = {"Four of a Kind", "Full House"}

# Suit engines: fixed suit vs dominant-suit
_SUIT_ENGINES_FIXED = (
    ("j_rough_gem", "Diamonds"),
    ("j_greedy_joker", "Diamonds"),
    ("j_bloodstone", "Hearts"),
    ("j_lusty_joker", "Hearts"),
    ("j_arrowhead", "Spades"),
    ("j_wrathful_joker", "Spades"),
    ("j_onyx_agate", "Clubs"),
    ("j_gluttonous_joker", "Clubs"),
    ("j_seeing_double", "Clubs"),
)
_SUIT_ENGINES_DOMINANT = (
    "j_ancient", "j_blackboard", "j_tribe", "j_droll", "j_crafty",
    "j_smeared", "j_smeared_joker"
)

# Enhancement engines (joker key -> enhancement to add).
_ENH_ENGINES = {
    "j_steel_joker": "Steel",
    "j_glass": "Glass",
    "j_glass_joker": "Glass",
    "j_lucky_cat": "Lucky",
}

# Face engines: the deck should lean faces.
_FACE_ENGINES = (
    "j_photograph", "j_sock_and_buskin", "j_business", "j_business_card",
    "j_reserved_parking", "j_smiley", "j_scary_face", "j_triboulet",
    "j_caino", "j_pareidolia"
)

# Joker hand type affinities for planet and reshaping synergy
_JOKER_HAND_TYPES = {
    "j_runner": "Straight",
    "j_shortcut": "Straight",
    "j_four_fingers": "Straight",
    "j_superposition": "Straight",
    "j_crazy": "Straight",
    "j_devious": "Straight",
    "j_order": "Straight",
    "j_droll": "Flush",
    "j_crafty": "Flush",
    "j_tribe": "Flush",
    "j_bloodstone": "Flush",
    "j_smeared": "Flush",
    "j_smeared_joker": "Flush",
    "j_jolly": "Pair",
    "j_sly": "Pair",
    "j_duo": "Pair",
    "j_half": "Pair",
    "j_mad": "Two Pair",
    "j_clever": "Two Pair",
    "j_spare_trousers": "Two Pair",
    "j_trousers": "Two Pair",
    "j_zany": "Three of a Kind",
    "j_wily": "Three of a Kind",
    "j_trio": "Three of a Kind",
    "j_family": "Four of a Kind",
}

_SUIT_ORDER = ("Spades", "Hearts", "Clubs", "Diamonds")

_INACTIVE_TARGET = {"rank": None, "rank_set": None, "suit": None, "enh": None,
                    "enhanced_any": False, "face": False, "active": False}


_HAND_ENGINE_PRIORITY = [
    # Tier 1: Premier xMult Hand Finishers
    ({"j_family"}, "Four of a Kind"),
    ({"j_order"}, "Straight"),
    ({"j_tribe"}, "Flush"),
    ({"j_trio"}, "Three of a Kind"),
    ({"j_duo"}, "Pair"),
    # Tier 2: Scaling Hand Engines
    ({"j_spare_trousers", "j_trousers"}, "Two Pair"),
    ({"j_runner"}, "Straight"),
    # Tier 3: High-Synergy Suit & Flat/Chip Engines
    ({"j_bloodstone", "j_crafty", "j_droll", "j_smeared", "j_smeared_joker"}, "Flush"),
    ({"j_clever", "j_mad"}, "Two Pair"),
    ({"j_wily", "j_zany"}, "Three of a Kind"),
    ({"j_sly", "j_jolly", "j_half"}, "Pair"),
    ({"j_shortcut", "j_four_fingers", "j_superposition", "j_crazy", "j_devious"}, "Straight"),
    # Tier 4: Held-in-Hand Engines
    ({"j_baron", "j_shoot_the_moon"}, "High Card"),
]


def portfolio_target_hand(game) -> str:
    """Hand type synergizing with acquired jokers; deck-aware and preserves viable base hands."""
    if not getattr(game, "jokers", None):
        return main_hand_type(game)

    keys = {j.key for j in game.jokers}
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


def _majority_rank(dg) -> int | None:
    """Rank with the most copies in the full deck; highest rank wins ties
    (sorted iteration — never deck-order dependent)."""
    best_r, best_n = None, -1
    for r, n in sorted(dg["ranks"].items()):
        if n > best_n:
            best_r, best_n = r, n
    return best_r


def _majority_rank_in_set(dg, rank_set) -> int | None:
    """Rank with the most copies in the full deck among rank_set; highest rank wins ties."""
    best_r, best_n = None, -1
    for r in sorted(rank_set):
        n = dg["ranks"].get(r, 0)
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

    Returns {"rank", "rank_set", "suit", "enh", "enhanced_any", "face", "active"}:
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

    # Rank: fixed-rank engine first, else rank group engine, else kind-stack majority rank.
    for key, r in _RANK_ENGINES:
        if key in keys:
            t["rank"] = r
            break
    else:
        for key, rset in _RANK_GROUP_ENGINES.items():
            if key in keys:
                t["rank"] = _majority_rank_in_set(dg, rset)
                t["rank_set"] = rset
                break
        else:
            kind_stack = any(k in keys for k in ("j_family", "j_trio", "j_duo")) or (
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
        if t["rank"] is None and t.get("rank_set") is None:
            t["rank_set"] = {11, 12, 13}

    t["active"] = any((t["rank"] is not None, t.get("rank_set") is not None,
                       t["suit"] is not None, t["enh"] is not None,
                       t["enhanced_any"], t["face"]))
    return t


def _reshape_tarot_bonus(game, key: str) -> float:
    """Additive tarot value from the reshape target (shop buys + pack picks).
    Zero when inactive, so `tarot_value + 0` reproduces V9's value exactly."""
    t = deck_reshape_target(game)
    if not t["active"]:
        return 0.0
    p = V10_PARAMS
    if key == "c_death" and (t["rank"] is not None or t["suit"] is not None or t.get("face")):
        return p["reshape_tarot_death_bonus"]   # the stacker
    if key == "c_strength" and (t["rank"] is not None or t.get("face") or t.get("rank_set")):
        return p["reshape_tarot_strength_bonus"]# near-target -> target
    if key == "c_hanged_man":
        if t["rank"] is not None:
            return 0.03                          # thin junk toward the stack
        if t["suit"] is not None:
            return 0.05                          # thin off-suit cards
        if t.get("face"):
            return 0.04                          # thin non-face cards
    if key == "c_justice" and (any(j.key in ("j_glass", "j_glass_joker") for j in game.jokers) or game.ante >= 7):
        return 0.16                              # Glass synergy / late-game burst
    if key == "c_magician" and any(j.key == "j_lucky_cat" for j in game.jokers):
        return 0.12                              # Lucky synergy
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
    elif t.get("rank_set") and card.rank in t["rank_set"]:
        b += p["reshape_pack_rank_bonus"]
    if t["suit"] is not None and card.suit == t["suit"]:
        b += p["reshape_pack_suit_bonus"]
    if t["enh"] is not None and card.enhancement == t["enh"]:
        b += p["reshape_pack_enh_bonus"]
    if t["face"] and card.is_face_card:
        b += p["reshape_pack_face_bonus"]
    return b


def _v10_tarot_value(game, key: str) -> float:
    return tarot_value(game, key) + _reshape_tarot_bonus(game, key)


def _v10_spectral_value(game, key: str) -> float:
    if key in ("s_hex", "s_ankh") and len(game.jokers) == 1:
        return 0.20
    return spectral_value(game, key)


def _v10_pack_card_value(game, card) -> float:
    return _pack_card_value(card) + _reshape_card_bonus(game, card)


def _enhance_targets_biased(hand, best, n, t):
    """Top-`n` enhancable cards, preferring target-rank, suit, face cards,
    else the best unenhanced cards."""
    out = []
    # Priority 1: Target rank / rank_set cards
    if t.get("rank") is not None:
        for i in best:
            if len(out) >= n:
                break
            c = hand[i]
            if c.rank == t["rank"] and c.enhancement == "None":
                out.append(i)
    elif t.get("rank_set"):
        for i in best:
            if len(out) >= n:
                break
            c = hand[i]
            if c.rank in t["rank_set"] and c.enhancement == "None":
                out.append(i)

    # Priority 2: Target suit cards
    if t.get("suit") is not None and len(out) < n:
        for i in best:
            if len(out) >= n:
                break
            c = hand[i]
            if c.suit == t["suit"] and c.enhancement == "None" and i not in out:
                out.append(i)

    # Priority 3: Target face cards
    if t.get("face") and len(out) < n:
        for i in best:
            if len(out) >= n:
                break
            c = hand[i]
            if c.is_face_card and c.enhancement == "None" and i not in out:
                out.append(i)

    # Priority 4: Fallback to best remaining unenhanced cards
    if len(out) < n:
        for i in best:
            if len(out) >= n:
                break
            c = hand[i]
            if c.enhancement == "None" and i not in out:
                out.append(i)
    return out


# Enhancement tarots whose payoff lands on PLAYED cards (Steel/Gold pay when
# HELD, so targeting them into the play wastes the enhancement's timing).
_IN_PLAY_ENHANCEMENTS = ("c_empress", "c_hierophant", "c_lovers")


def _has_scoring_joker(game, ref=None) -> bool:
    """True when some owned joker measurably adds chips/mult to a real play
    (>2% of the reference ceiling). Engineless boards are the ante-1/2 death
    class that buys econ junk and dies: mail / ticket / todo_list / golden."""
    if not game.jokers:
        return False
    if ref is None:
        ref = reference_hand(game)
    ceiling, _typical, _reach, base_c, _base_t = ref
    base = base_c if base_c > 0 else 1.0
    for i in range(len(game.jokers)):
        without = best_play_score(game, hand=ceiling, exclude_joker=i,
                                  filter_boss=False)
        if (base - without) / base > 0.02:
            return True
    return False


def _joker_type_chase_discard(game, hand, target_ht):
    """Discard set committed to assembling `target_ht` when a hand-type joker
    (Duo/Trio/Family/Order/Tribe/Sly/... ) wants it and the type is NOT in the
    current plays: keep the partial structure (the trips for FoK, the 4-suit
    for a flush), throw away up to 4 off-structure cards. None when there is
    no viable partial (nothing to build on)."""
    n = len(hand)
    if n < 2:
        return None
    keep = set()
    if target_ht in ("Four of a Kind", "Three of a Kind", "Full House"):
        cnt = {}
        for i, c in enumerate(hand):
            if not c.debuffed:
                cnt.setdefault(c.rank, []).append(i)
        best_rank_idxs = max(cnt.values(), key=len) if cnt else []
        if len(best_rank_idxs) < 3:
            return None
        keep.update(sorted(best_rank_idxs))
    elif target_ht == "Flush":
        suits = {}
        for i, c in enumerate(hand):
            if not c.debuffed:
                suits.setdefault(c.suit, []).append(i)
        best_suit_idxs = max(suits.values(), key=len) if suits else []
        if len(best_suit_idxs) < 4:
            return None
        keep.update(sorted(best_suit_idxs))
    elif target_ht == "Straight":
        ranks = sorted({c.rank for c in hand if not c.debuffed}, reverse=True)
        best_run, run = [], []
        for r in ranks + [None]:
            if r is not None and run and run[-1] - r == 1:
                run.append(r)
            else:
                if len(run) > len(best_run):
                    best_run = list(run)
                run = [r] if r is not None else []
        if len(best_run) < 4:
            return None
        run_set = set(best_run)
        keep.update(i for i, c in enumerate(hand) if c.rank in run_set)
    else:
        return None
    off = [i for i in range(n) if i not in keep]
    off.sort(key=lambda i: _card_quality(hand[i]))
    dset = off[:min(4, game.discards_left,
                    ACTIVE_PARAMS["discard_structure_max"])]
    # never leave fewer than 5 cards to play
    while len(hand) - len(dset) < 5 and dset:
        dset.pop()
    return tuple(sorted(dset)) if dset else None


def _v10_scoring_enhance_targets(game, hand, key):
    """Mid-blind enhancement targeting that pays on the ACTUAL scoring hand.

    V9's rule enhances the top-quality cards anywhere in the hand — which can
    land Mult/Bonus on off-suit cards while a flush is the play that has to
    clear the blind. Enumerate target sets inside the top plays and keep the
    one with the best engine-scored result (isolated copies; no live
    mutation). Deterministic enhancements only (Mult/Bonus/Wild — Lucky's
    chance payouts make comparisons noisy). Returns hand indices or None."""
    if game.state != State.SELECTING_HAND or not hand:
        return None
    plays = scored_plays(
        game, topk=V10_PARAMS.get("enhance_into_play_topk", 3))
    if not plays:
        return None
    n = TAROT_MAX_TARGETS.get(key, 2)
    enh = TAROT_ENHANCEMENT[key]
    best_targets, best_score = None, -1
    for _s0, combo, _ht in plays:
        cand = sorted(i for i in combo
                      if hand[i].enhancement == "None"
                      and not hand[i].debuffed)
        if len(cand) < n:
            continue
        for pick in combinations(cand, n):
            cards = [hand[i].copy() for i in combo]
            for i in pick:
                cards[combo.index(i)].enhancement = enh
            try:
                ht2, sc2 = evaluate_hand(cards)
                s = eval_hand_score(game, ht2, sc2, cards)
            except Exception:
                continue
            if s > best_score:
                best_score, best_targets = s, list(pick)
    if best_targets is None or best_score <= plays[0][0]:
        return None
    return sorted(best_targets)


def _v10_tarot_action(game, ci, key, hand, best, weakest):
    """Tarot usage biased toward the reshape target and safe engine protection;
    delegates everything else to V9's `_tarot_action` (byte-identical when farm-off)."""
    if V10_PARAMS.get("farm_clear_threshold", 0.90) >= 1.0:
        return _tarot_action(game, ci, key, hand, best, weakest)

    # Scoring-aware enhancement deployment runs BEFORE the reshape gate
    if (key in _IN_PLAY_ENHANCEMENTS
            and V10_PARAMS.get("enhance_into_play_ante", 0)
            and game.ante <= V10_PARAMS["enhance_into_play_ante"]):
        tgt = _v10_scoring_enhance_targets(game, hand, key)
        if tgt:
            return {"type": "use_consumable", "consumable_idx": ci,
                    "target_cards": tgt}

    # Deadlock prevention: Emperor / High Priestess pop BEFORE generating, so using from 2/2 works
    if key in ("c_high_priestess", "c_emperor"):
        if len(game.consumable_hand) <= game.consumable_slots:
            return {"type": "use_consumable", "consumable_idx": ci, "target_cards": []}
        return None

    # The Fool: reuse high-EV last consumable
    if key == "c_fool":
        used = getattr(game, "consumables_used", [])
        if used:
            last = used[-1]
            if last in ("c_death", "c_hermit", "c_temperance") or last in PLANET_HAND:
                return {"type": "use_consumable", "consumable_idx": ci, "target_cards": []}

    t = deck_reshape_target(game)
    keys = {j.key for j in game.jokers}

    # The Hanged Man: protect engine ranks (Wee, Hack, Fibonacci, target rank)
    if key == "c_hanged_man":
        if game.state != State.SHOP or not hand:
            return None
        safe_junk = []
        maj_r = _majority_rank(deck_groups(game)) if t.get("rank") is None else None
        for i in weakest:
            c = hand[i]
            if t.get("rank") is not None and c.rank == t["rank"]:
                continue
            if maj_r is not None and c.rank == maj_r:
                continue
            if t.get("rank_set") and c.rank in t["rank_set"]:
                continue
            if c.rank == 2 and "j_wee" in keys:
                continue
            if c.rank in (2, 3, 4, 5) and "j_hack" in keys:
                continue
            if c.rank in (14, 2, 3, 5, 8) and "j_fibonacci" in keys:
                continue
            if t.get("face") and c.is_face_card:
                continue
            if t.get("suit") is not None and c.suit == t["suit"]:
                continue
            if c.enhancement != "None" or c.edition != "None" or c.seal != "None":
                continue
            safe_junk.append(i)
        if safe_junk:
            return {"type": "use_consumable", "consumable_idx": ci, "target_cards": safe_junk[:2]}
        return None

    if not t["active"]:
        return _tarot_action(game, ci, key, hand, best, weakest)

    if key == "c_death" and (t["rank"] is not None or t["suit"] is not None or t.get("face")):
        # Copy the best TARGET card onto the weakest non-target card
        # Protect active engine ranks from being destination
        if t["rank"] is not None:
            src = next((i for i in best if hand[i].rank == t["rank"]), None)
            dst = next((i for i in weakest if hand[i].rank != t["rank"]
                        and not (t.get("rank_set") and hand[i].rank in t["rank_set"])
                        and not (hand[i].rank == 2 and "j_wee" in keys)
                        and not (hand[i].rank in (2, 3, 4, 5) and "j_hack" in keys)
                        and not (hand[i].rank in (14, 2, 3, 5, 8) and "j_fibonacci" in keys)
                        and not (t.get("suit") and hand[i].suit == t["suit"])), None)
        elif t.get("face") and t["suit"] is None:
            src = next((i for i in best if hand[i].is_face_card), None)
            dst = next((i for i in weakest if not hand[i].is_face_card
                        and not (t.get("rank_set") and hand[i].rank in t["rank_set"])
                        and not (hand[i].rank == 2 and "j_wee" in keys)
                        and not (hand[i].rank in (2, 3, 4, 5) and "j_hack" in keys)
                        and not (hand[i].rank in (14, 2, 3, 5, 8) and "j_fibonacci" in keys)
                        and not (t.get("suit") and hand[i].suit == t["suit"])), None)
        else:
            src = next((i for i in best if hand[i].suit == t["suit"]), None)
            dst = next((i for i in weakest if hand[i].suit != t["suit"]), None)
        if src is not None and dst is not None and src != dst:
            return {"type": "use_consumable", "consumable_idx": ci,
                    "target_cards": [dst, src]}
        return None

    if key == "c_strength" and (t["rank"] is not None or t.get("rank_set") or t.get("face")):
        target_r = t["rank"]
        near = []
        for i in weakest:
            if len(near) >= 2:
                break
            r = hand[i].rank
            is_target_near = (target_r is not None and r == target_r - 1)
            is_face_near = (bool(t.get("face")) and r == 10)
            is_set_near = (bool(t.get("rank_set")) and (r + 1) in t["rank_set"] and r not in t["rank_set"])
            if is_target_near or is_face_near or is_set_near:
                if i not in near:
                    near.append(i)
        if near:
            return {"type": "use_consumable", "consumable_idx": ci,
                    "target_cards": near}
        return _tarot_action(game, ci, key, hand, best, weakest)

    if key in TAROT_SUIT and TAROT_SUIT[key] == t["suit"]:
        if game.state == State.SHOP:
            tgt = [i for i in best if hand[i].suit != t["suit"]
                   and hand[i].enhancement != "Stone"][:3]
            if tgt:
                return {"type": "use_consumable", "consumable_idx": ci,
                        "target_cards": tgt}
        return _tarot_action(game, ci, key, hand, best, weakest)

    if key in TAROT_ENHANCEMENT and key not in ("c_justice", "c_tower"):
        n = TAROT_MAX_TARGETS.get(key, 2)
        if (key in _IN_PLAY_ENHANCEMENTS
                and V10_PARAMS.get("enhance_into_play_ante", 0)
                and game.ante <= V10_PARAMS["enhance_into_play_ante"]):
            tgt = _v10_scoring_enhance_targets(game, hand, key)
            if tgt:
                return {"type": "use_consumable", "consumable_idx": ci,
                        "target_cards": tgt}
        tgt = _enhance_targets_biased(hand, best, n, t)
        if tgt:
            return {"type": "use_consumable", "consumable_idx": ci,
                    "target_cards": tgt}
        return _tarot_action(game, ci, key, hand, best, weakest)

    if key == "c_justice" and (any(j.key in ("j_glass", "j_glass_joker") for j in game.jokers) or game.ante >= 7):
        tgt = _enhance_targets_biased(hand, best, 1, t)
        if tgt:
            return {"type": "use_consumable", "consumable_idx": ci, "target_cards": tgt}

    return _tarot_action(game, ci, key, hand, best, weakest)


def _v10_spectral_action(game, ci, key, hand, best, weakest):
    """Zero-risk spectral exploits and safe deployment."""
    if V10_PARAMS.get("farm_clear_threshold", 0.90) >= 1.0:
        return _spectral_action(game, ci, key, hand, best, weakest)

    if key == "s_hex":
        # Free Polychrome (x1.5 Mult) on single-joker states with 0 jokers destroyed
        if len(game.jokers) == 1 and getattr(game.jokers[0], "edition", "None") in ("None", None, ""):
            return {"type": "use_consumable", "consumable_idx": ci, "target_cards": []}
        return None

    if key == "s_ankh":
        # Free joker duplication on single-joker states with 0 jokers destroyed
        if len(game.jokers) == 1 and game.joker_slots >= 2:
            return {"type": "use_consumable", "consumable_idx": ci, "target_cards": []}
        return None

    if key == "s_medium":
        # Purple Seal pays on discard -> put on weakest card (discard fodder)
        if weakest:
            return {"type": "use_consumable", "consumable_idx": ci, "target_cards": [weakest[0]]}
        return None

    if key == "s_deja_vu":
        # Red Seal retriggers -> put on target rank, face card, or best card
        t = deck_reshape_target(game)
        target_idx = None
        if t["rank"] is not None:
            target_idx = next((i for i in best if hand[i].rank == t["rank"]), None)
        if target_idx is None and t.get("face"):
            target_idx = next((i for i in best if hand[i].is_face_card), None)
        if target_idx is None:
            target_idx = next((i for i in best if hand[i].enhancement in ("Steel", "Glass", "Gold", "Lucky")), None)
        if target_idx is None and best:
            target_idx = best[0]
        if target_idx is not None:
            return {"type": "use_consumable", "consumable_idx": ci, "target_cards": [target_idx]}
        return None

    if key == "s_immolate":
        # Thin 5 cards for $20 if early or money is needed
        if game.state == State.SHOP and (game.ante <= 2 or game.dollars < 15 or len(game.deck) > 35):
            return {"type": "use_consumable", "consumable_idx": ci, "target_cards": []}

    return _spectral_action(game, ci, key, hand, best, weakest)


def _v10_maybe_use_planet(game, plays=None) -> dict | None:
    """Use held planets proactively to avoid slot deadlocks and level hand types."""
    if V10_PARAMS.get("farm_clear_threshold", 0.90) >= 1.0:
        return maybe_use_planet(game, plays)

    if not game.consumable_hand:
        return None

    target_ht = portfolio_target_hand(game)
    main_ht = main_hand_type(game)
    slots_full = len(game.consumable_hand) >= game.consumable_slots
    has_constellation = any(j.key == "j_constellation" for j in game.jokers)
    has_satellite = any(j.key == "j_satellite" for j in game.jokers)

    for ci, key in enumerate(game.consumable_hand):
        if key in PLANET_HAND:
            ht = PLANET_HAND[key]
            if game.state == State.SHOP:
                # In shop: proactively consume any held planet immediately to free slots and upgrade levels
                return {"type": "use_consumable", "consumable_idx": ci, "target_cards": []}
            elif game.state == State.SELECTING_HAND:
                # In combat: use if slots full, matching target, or matching top plays
                if plays is None:
                    plays = scored_plays(game, topk=3)
                top_hts = {p[2] for p in plays} if plays else set()
                if slots_full or ht in top_hts or ht == target_ht or has_constellation:
                    return {"type": "use_consumable", "consumable_idx": ci, "target_cards": []}
    return maybe_use_planet(game, plays)


def _v10_decide_consumable(game):
    """decide_consumable with the reshape-biased tarot and spectral action."""
    cons = game.consumable_hand
    if not cons:
        return None
    hand = game.hand
    best, weakest = _target_lists(hand)
    hold_enh = (V10_PARAMS.get("hold_enh_for_blind", False)
                and game.state == State.SHOP)
    for ci, key in enumerate(cons):
        if (hold_enh and key in _IN_PLAY_ENHANCEMENTS
                and len(cons) < game.consumable_slots):
            continue
        act = _v10_tarot_action(game, ci, key, hand, best, weakest)
        if act is None and key in ALL_SPECTRALS:
            act = _v10_spectral_action(game, ci, key, hand, best, weakest)
        if act is not None:
            return act
    return None


def _joker_sell_value(j) -> int:
    """Return the sell value of a JokerInstance."""
    if j is None:
        return 0
    return getattr(j, "state", {}).get("sell_value", max(1, getattr(j, "cost", 4) // 2))


def _v10_rank_shop_items(game, ref, surplus, rerolls_used: int = 0):
    """`_rank_shop_items` with the reshape-biased tarot/card values (used by
    BOTH the L0 shop and the L1 comparative search). Pure reads."""
    p = ACTIVE_PARAMS
    buys = []  # (value, item_idx)
    need_sell = None  # (candidate_value, worst_idx) when slots are full
    worst_cache = None
    # Ante-1 reroll reserve: with no scoring joker yet, keep cash back for
    # reroll hunts instead of spending down to $0 on packs/econ filler.
    reserve = 0
    if (game.ante == 1
            and rerolls_used < ACTIVE_PARAMS["reroll_max"]
            and V10_PARAMS.get("ante1_reroll_reserve", 0) > 0
            and not any(j.key in CHIPS_JOKERS or j.key in XMULT_JOKERS
                        for j in game.jokers)):
        reserve = V10_PARAMS["ante1_reroll_reserve"]
    allowance = game.dollars - reserve
    slots_full = len(game.jokers) >= game.joker_slots
    worst_sell = 0
    if slots_full and game.jokers and V10_PARAMS.get("farm_clear_threshold", 0.90) < 1.0:
        worst_cache = _v10_worst_joker_idx(game, ref)
        if worst_cache is not None and worst_cache < len(game.jokers):
            worst_sell = _joker_sell_value(game.jokers[worst_cache])

    for i, item in enumerate(game.current_shop):
        if item.sold:
            continue
        price = item.discounted_price(game.shop_discount)
        eff_allowance = allowance + (worst_sell if (slots_full and item.kind == "joker" and V10_PARAMS.get("farm_clear_threshold", 0.90) < 1.0) else 0)
        if price > eff_allowance:
            continue
        if item.kind == "joker":
            # Ban trap jokers that cause catastrophic scoring collapse
            if item.key in ("j_obelisk",):
                continue
            if item.key in ("j_idol", "j_the_idol"):
                cards = list(getattr(game, "deck", ())) + list(getattr(game, "hand", ())) + list(getattr(game, "spent", ()))
                from collections import Counter
                suit_counts = Counter(getattr(c, "suit", None) for c in cards if getattr(c, "suit", None) is not None)
                if max(suit_counts.values(), default=0) < 20:
                    continue

            if item.key == "j_family" and V10_PARAMS.get("farm_clear_threshold", 0.90) < 1.0:
                cards = list(getattr(game, "deck", ())) + list(getattr(game, "hand", ())) + list(getattr(game, "spent", ()))
                from collections import Counter
                rank_counts = Counter(getattr(c, "rank", None) for c in cards if getattr(c, "rank", None) is not None)
                if max(rank_counts.values(), default=0) < 5:
                    continue

            pure_econ_keys = ("j_rocket", "j_golden", "j_business", "j_credit_card", "j_cloud_9", "j_satellite", "j_egg", "j_pareidolia")
            if (V10_PARAMS.get("farm_clear_threshold", 0.90) < 1.0
                    and game.ante == 1 and not _has_scoring_joker(game, ref)
                    and item.key in pure_econ_keys):
                value = -1.0
                continue

            value = joker_value(game, item.key, item.edition, ref, surplus)
            if item.key in ("j_blueprint", "j_brainstorm"):
                has_scoring = _has_scoring_joker(game, ref)
                if not has_scoring and (len(game.jokers) == 0 or game.ante <= 2):
                    continue
                if has_scoring:
                    value = max(value, 1.5)
            if (item.key in PREMIER_XMULT_FINISHERS or item.key in RELIABLE_XMULT_JOKERS) and game.ante >= 6:
                value += 0.35
            if game.ante <= 2 and V10_PARAMS["farm_clear_threshold"] < 1.0:
                bias = (V10_PARAMS["ante1_chip_bias"] if game.ante == 1
                        else V10_PARAMS.get("ante2_chip_bias", 0.0))
                if item.key in EARLY_FLAT_CHIPS_JOKERS:
                    value += bias
                if game.ante == 1 and item.key in ECONOMY_JOKERS:
                    from .agent_v9 import econ_value as _ev
                    value -= (1.0 - V10_PARAMS["ante1_econ_discount"]) * _ev(game, item.key)
            urg = V10_PARAMS.get("engineless_urgency_ante", 0)
            if (urg and game.ante <= urg
                    and V10_PARAMS["farm_clear_threshold"] < 1.0
                    and not _has_scoring_joker(game, ref)):
                # Engineless death board: no owned joker moves a real score.
                # Hunt an engine harder (chips/xmult/retrigger) and treat econ
                # junk exactly like ante-1 does instead of buying it.
                if ((item.key in CHIPS_JOKERS or item.key in XMULT_JOKERS
                        or item.key in RETRIGGER_JOKERS)
                        and item.key not in ("j_blueprint", "j_brainstorm")
                        and item.key not in pure_econ_keys):
                    value += V10_PARAMS.get("engineless_urgency_bonus", 0.15)
                elif item.key in ECONOMY_JOKERS:
                    from .agent_v9 import econ_value as _ev2
                    value -= ((1.0 - V10_PARAMS["ante1_econ_discount"])
                              * _ev2(game, item.key))
            if (game.ante <= 2
                    and V10_PARAMS.get("ante1_econ_skip", False)
                    and item.key in ECONOMY_JOKERS
                    and rerolls_used < ACTIVE_PARAMS["reroll_max"]):
                # Early-shop econ junk clogs the death boards: skip it while
                # rerolls remain, so the cash hunts a chips/mult joker instead.
                continue
            has_room = (len(game.jokers) < game.joker_slots
                        or item.edition == "Negative")
            thr = (V10_PARAMS.get("ante1_first_joker_thr", 0.0)
                   if (game.ante <= 2 and not game.jokers) else p["buy_threshold"])
            if has_room and value >= thr:
                buys.append((value, i))
            elif not has_room:
                if worst_cache is None:
                    worst_cache = _v10_worst_joker_idx(game, ref)
                if worst_cache is not None and worst_cache < len(game.jokers):
                    worst_j = game.jokers[worst_cache]
                    is_dead_econ_worst = worst_j.key in DEAD_ECONOMY_JOKERS or worst_j.key in PORTFOLIO_ECON
                    is_premier_cand = item.key in PREMIER_XMULT_FINISHERS or item.key in RELIABLE_XMULT_JOKERS or item.key in HIGH_LEVERAGE_SCORING_JOKERS
                    # In Ante >= 5, disallow selling combat jokers for economy
                    is_combat_worst = (worst_j.key in PORTFOLIO_FLAT or worst_j.key in PORTFOLIO_CHIPS or worst_j.key in COMBAT_SCALING_JOKERS)
                    is_econ_cand = item.key in ("j_golden", "j_egg", "j_satellite", "j_rocket") or item.key in ECONOMY_JOKERS
                    if game.ante >= 5 and is_combat_worst and is_econ_cand:
                        continue

                    margin_ok = (value - joker_value_of(game, worst_cache, ref) >= p["sell_margin"])
                    is_combat_cand = (item.key in PORTFOLIO_FLAT or item.key in PORTFOLIO_CHIPS or item.key in PORTFOLIO_XMULT or item.key in COMBAT_SCALING_JOKERS)
                    if margin_ok or (is_premier_cand and is_dead_econ_worst) or (game.ante >= 6 and is_dead_econ_worst and is_combat_cand):
                        if V10_PARAMS.get("farm_clear_threshold", 0.90) < 1.0:
                            need_sell = (value, worst_cache, i)
                        else:
                            need_sell = (value, worst_cache)
        elif item.kind == "booster":
            if V10_PARAMS.get("farm_clear_threshold", 0.90) < 1.0 and item.key.startswith(("p_celestial", "p_arcana", "p_spectral")):
                if len(game.consumable_hand) >= game.consumable_slots:
                    continue
            value = pack_value(game, item.key)
            if game.ante == 1 and item.key.startswith("p_buffoon") and V10_PARAMS["farm_clear_threshold"] < 1.0:
                value += V10_PARAMS.get("ante1_buffoon_boost", 0.20)
            if game.ante == 1 and item.key.startswith("p_celestial") and V10_PARAMS["farm_clear_threshold"] < 1.0:
                # Planet levels on the main hand type are permanent chips/mult —
                # exactly the missing margin on ante-1 boss close misses.
                value += V10_PARAMS.get("ante1_celestial_bonus", 0.0)
            if value >= p["buy_threshold"]:
                buys.append((value, i))
        elif item.kind == "voucher":
            if game.ante == 1 and V10_PARAMS.get("ante1_voucher_gate", True) and V10_PARAMS["farm_clear_threshold"] < 1.0:
                # skip only when both: no jokers AND weak ceiling (De Morgan: allow if j!=0 or base>=120)
                if len(game.jokers) == 0 and ref.base_c < 120:
                    continue
            prio = VOUCHER_PRIORITY.get(item.key, 0)
            if (prio >= 2 and len(game.jokers) > 0 and game.ante > 2
                    and game.dollars - price >= 5):
                buys.append((0.10 + 0.05 * prio, i))
        elif item.kind == "planet":
            if V10_PARAMS.get("farm_clear_threshold", 0.90) >= 1.0:
                if PLANET_HAND.get(item.key) == main_hand_type(game):
                    buys.append((0.08, i))
            else:
                target_ht = portfolio_target_hand(game)
                main_ht = main_hand_type(game)
                item_ht = PLANET_HAND.get(item.key)
                val = 0.05
                if item_ht == target_ht:
                    val = 0.14
                elif item_ht == main_ht:
                    val = 0.10
                elif any(j.key == "j_constellation" for j in game.jokers):
                    val = 0.12
                elif any(j.key == "j_satellite" for j in game.jokers) and item.key not in getattr(game, "planets_used", set()):
                    val = 0.12
                if val >= p["buy_threshold"] and len(game.consumable_hand) < game.consumable_slots:
                    buys.append((val, i))
        elif item.kind == "tarot":
            value = _v10_tarot_value(game, item.key)
            if (value >= p["buy_threshold"]
                    and len(game.consumable_hand) < game.consumable_slots):
                buys.append((value, i))
        elif item.kind == "spectral":
            value = _v10_spectral_value(game, item.key)
            if (value >= p["buy_threshold"]
                    and len(game.consumable_hand) < game.consumable_slots):
                buys.append((value, i))
        elif item.kind == "card" and item.card is not None:
            value = _v10_pack_card_value(game, item.card)
            if value >= p["buy_threshold"]:
                buys.append((value, i))
    return buys, need_sell


def _forecast_round_score(game, ref=None) -> float:
    """Forecast expected multi-hand score for the round, discounted for variance."""
    if ref is None:
        ref = reference_hand(game)
    ceiling, typical, reach, base_c, base_t = ref
    expected_single = reach * base_c + (1.0 - reach) * base_t
    base_hands = getattr(game, "base_hands", 4)
    return expected_single * base_hands * 0.85


def _ante_boss_target(game) -> float:
    """Upcoming boss target chips for current ante."""
    ante = game.ante
    boss = getattr(game, "next_boss_key", "")
    if ante == 6:
        return 80000.0 if boss == "bl_wall" else 40000.0
    elif ante == 7:
        return 140000.0 if boss == "bl_wall" else 70000.0
    elif ante >= 8:
        return 300000.0 if boss == "bl_violet" else 100000.0
    from .agent_v9 import BLIND_CHIPS
    if ante in BLIND_CHIPS:
        base = float(BLIND_CHIPS[ante][2])
        if boss == "bl_wall":
            base = float(BLIND_CHIPS[ante][0] * 4)
        elif boss == "bl_violet":
            base = float(BLIND_CHIPS[ante][0] * 6)
        return base
    return 100000.0


def _v10_decide_shop(game, rerolls_used: int) -> dict:
    """decide_shop with the reshape bias: shop-phase consumable usage and
    tarot/card buying use the v10 reshape-aware versions (byte-identical to
    V9's when the reshape target is inactive)."""
    if V10_PARAMS.get("farm_clear_threshold", 0.90) >= 1.0:
        from .agent_v9 import decide_shop as _orig_decide_shop
        return _orig_decide_shop(game, rerolls_used)

    p = ACTIVE_PARAMS
    _optimize_joker_order(game)

    if (game.next_boss_key in BAD_BOSSES and game.dollars >= 10):
        can_dc = ("v_directors_cut" in game.vouchers
                  and game.dc_reroll_ante != game.ante)
        can_retcon = "v_retcon" in game.vouchers
        if can_dc or can_retcon:
            return {"type": "reroll_boss"}

    act = _v10_maybe_use_planet(game)
    if act is not None:
        return act

    if p["use_tarots"]:
        act = _v10_decide_consumable(game)
        if act is not None:
            return act

    if getattr(game, "_v10_pending_buy", None) is not None:
        p_idx = game._v10_pending_buy
        game._v10_pending_buy = None
        if 0 <= p_idx < len(game.current_shop) and not game.current_shop[p_idx].sold:
            p_item = game.current_shop[p_idx]
            p_price = p_item.discounted_price(game.shop_discount)
            if p_price <= game.dollars and len(game.jokers) < game.joker_slots:
                return {"type": "buy", "item_idx": p_idx}

    ref = reference_hand(game)
    surplus = forecast_beatable(game, p["tilt_surplus_margin"], ref)
    buys, need_sell = _v10_rank_shop_items(game, ref, surplus,
                                           rerolls_used=rerolls_used)

    if need_sell is not None:
        if V10_PARAMS.get("farm_clear_threshold", 0.90) < 1.0 and len(need_sell) > 2:
            game._v10_pending_buy = need_sell[2]
        return {"type": "sell_joker", "joker_idx": need_sell[1]}

    # R1 & Macro Remedy 2: Multi-hand scoring forecast vs upcoming boss targets & adaptive interest floor
    forecast_score = _forecast_round_score(game, ref)
    boss_target = _ante_boss_target(game)
    interest_target = p["interest_target"]
    force_no_save = False

    is_urgent_mid = False
    is_urgent_late = False
    is_urgent_ante6 = False
    is_urgent_ante7 = False
    is_urgent_ante8 = False

    if V10_PARAMS.get("farm_clear_threshold", 0.90) < 1.0:
        n_xmult = sum(1 for j in game.jokers if j.key in XMULT_JOKERS or j.key in RELIABLE_XMULT_JOKERS)

        # Macro Remedy 2: Mid-Game Deficit Capital Deployment
        is_urgent_mid = (game.ante in (2, 3, 4, 5)) and (forecast_score < boss_target * 2.0)
        is_urgent_ante6 = (game.ante == 6 and (n_xmult == 0 or forecast_score < boss_target * 1.5))
        is_urgent_ante7 = (game.ante == 7 and (n_xmult == 0 or forecast_score < boss_target * 1.75))
        is_urgent_ante8 = (game.ante >= 8)
        is_urgent_late = is_urgent_ante8 or is_urgent_ante7 or is_urgent_ante6

        if is_urgent_ante8:
            interest_target = 0
            force_no_save = True
        elif is_urgent_ante7:
            interest_target = 0
            force_no_save = True
        elif is_urgent_ante6:
            interest_target = min(interest_target, 5)
        elif game.ante in (4, 5) and is_urgent_mid:
            interest_target = min(interest_target, 10)
        elif game.ante in (2, 3) and is_urgent_mid:
            interest_target = min(interest_target, 15)

    save_mode = (
        not force_no_save
        and game.ante > 2
        and game.dollars < interest_target
        and max((v for v, _ in buys), default=0.0) < p["save_strong_value"]
        and forecast_beatable(game, p["save_margin"], ref)
    )

    if buys:
        buys.sort(key=lambda b: (b[0], _KIND_RANK.get(
            game.current_shop[b[1]].kind, 1)), reverse=True)
        target_ht = portfolio_target_hand(game)
        main_ht = main_hand_type(game)
        for value, idx in buys:
            item = game.current_shop[idx]
            price = item.discounted_price(game.shop_discount)
            is_high_ev_consumable = False
            is_open_slot_joker = False
            if V10_PARAMS.get("farm_clear_threshold", 0.90) < 1.0:
                is_core_econ = item.key in ("c_hermit", "c_death", "c_fool", "c_temperance", "c_chariot", "c_empress", "c_hierophant", "c_justice")
                is_target_planet = (item.kind == "planet" and PLANET_HAND.get(item.key) == target_ht)
                is_target_tarot = (item.kind == "tarot" and _reshape_tarot_bonus(game, item.key) > 0)
                is_high_ev_consumable = is_core_econ or is_target_planet or is_target_tarot
                is_open_slot_joker = (item.kind == "joker" and len(game.jokers) < game.joker_slots and game.ante >= 3)
            if (price <= game.dollars
                    and (not save_mode or is_urgent_late or is_urgent_mid or value >= p["save_strong_value"] or is_high_ev_consumable or is_open_slot_joker)
                    and (worth_spending(game, price, value) or is_urgent_late or is_urgent_mid or is_open_slot_joker)):
                return {"type": "buy", "item_idx": idx}

    reroll_cost = max(0, game.reroll_cost - game.reroll_discount)
    eff_max = p["reroll_max"]
    if V10_PARAMS.get("engineless_reroll_extra", 0):
        urg = V10_PARAMS.get("engineless_urgency_ante", 0)
        if (game.ante <= urg
                and V10_PARAMS["farm_clear_threshold"] < 1.0
                and not _has_scoring_joker(game)):
            eff_max += V10_PARAMS["engineless_reroll_extra"]

    if V10_PARAMS.get("farm_clear_threshold", 0.90) < 1.0:
        if is_urgent_ante8:
            eff_max = max(eff_max, 10)
        elif is_urgent_ante7:
            eff_max = max(eff_max, 6)
        elif is_urgent_ante6:
            eff_max = max(eff_max, 4)
        elif game.ante in (4, 5) and is_urgent_mid:
            eff_max = max(eff_max, 3)
        elif game.ante in (2, 3) and is_urgent_mid:
            eff_max = max(eff_max, 2)

        slots_full = len(game.jokers) >= game.joker_slots
        worst_sell_val = 0
        if slots_full and game.jokers:
            w_idx = _v10_worst_joker_idx(game, ref)
            if w_idx is not None and w_idx < len(game.jokers):
                worst_sell_val = _joker_sell_value(game.jokers[w_idx])

        capital_after_reroll = game.dollars - reroll_cost + (worst_sell_val if slots_full else 0)
        if is_urgent_ante8:
            min_reserve = 0
        elif is_urgent_ante7:
            min_reserve = 2
        elif (is_urgent_late or is_urgent_mid):
            min_reserve = 4
        else:
            min_reserve = max(reroll_cost, p["reroll_min_money"])
        reserve_ok = (capital_after_reroll >= min_reserve) if (is_urgent_late or is_urgent_mid) else (game.dollars >= max(reroll_cost, p["reroll_min_money"]))
    else:
        reserve_ok = (game.dollars >= max(reroll_cost, p["reroll_min_money"]))

    if ((not save_mode or is_urgent_late or is_urgent_mid)
            and game.dollars >= reroll_cost
            and reserve_ok
            and rerolls_used < eff_max):
        return {"type": "reroll"}

    return {"type": "leave_shop"}


def _v10_decide_booster(game) -> dict:
    """decide_booster with zero-waste celestial packs and portfolio synergy."""
    if V10_PARAMS.get("farm_clear_threshold", 0.90) >= 1.0:
        from .agent_v9 import decide_booster as _orig_booster
        return _orig_booster(game)

    p = ACTIVE_PARAMS
    choices = game.booster_choices
    picks = game.booster_picks_remaining
    if not choices or picks <= 0:
        return {"type": "skip_booster"}

    ref = None  # lazy: only joker choices need the valuation reference
    main = main_hand_type(game)
    target_ht = portfolio_target_hand(game)
    has_constellation = any(j.key == "j_constellation" for j in game.jokers)
    has_satellite = any(j.key == "j_satellite" for j in game.jokers)
    room_for_consumable = len(game.consumable_hand) < game.consumable_slots
    is_celestial_pack = any(isinstance(c, str) and c in PLANET_HAND for c in choices)

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
            value = joker_value(game, key, edition, ref)
        elif isinstance(c, tuple) and c and c[0] == "card":
            value = _v10_pack_card_value(game, c[1])
        elif isinstance(c, str):
            if c in PLANET_HAND:
                if room_for_consumable:
                    c_ht = PLANET_HAND[c]
                    if c_ht == target_ht:
                        value = 0.15
                    elif c_ht == main:
                        value = 0.12
                    elif has_constellation:
                        value = 0.12
                    elif has_satellite:
                        value = 0.11
                    elif c_ht in ("High Card", "Pair"):
                        value = 0.08
                    else:
                        value = 0.07
                else:
                    value = 0.0
            elif c in ALL_TAROTS:
                if room_for_consumable:
                    value = _v10_tarot_value(game, c)
            elif c in ALL_SPECTRALS:
                if room_for_consumable:
                    value = _v10_spectral_value(game, c)
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

    # Zero-waste celestial pack: never skip if room for consumable exists
    if is_celestial_pack and room_for_consumable:
        planet_cands = [i for i, c in enumerate(choices) if isinstance(c, str) and c in PLANET_HAND]
        if planet_cands:
            return {"type": "pick_booster", "indices": [planet_cands[0]]}

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


def _v10_pclear_pick(game, plays):
    """Composition-legal 1-ply outcome search for marginal early blinds.

    For each candidate action (top plays, EV/quality discards) build the
    hypothetical post-action state WITHOUT stepping the RNG: move cards by
    hand, adjust hands/discards/chips, then score the state with
    estimate_clear_probability_bounds (pure deck-composition math — the same
    signal the farm gate uses). Pick max (P(clear), projected finish).
    Captures the beam solver's edge — cycling junk hands into structures,
    keeping chase options alive — without peeking at draw order."""
    import copy as _copy

    target = game.current_blind.chips_target
    cands = []
    seen: set = set()
    for score, cards, ht in plays[:8]:
        ids = frozenset(id(c) for c in cards)
        if ids in seen:
            continue
        seen.add(ids)
        cands.append(("play", score, cards))
    if game.discards_left > 0 and len(game.deck) > 0:
        dset, _dscore = best_discard(game)
        if dset:
            cands.append(("discard", 0, dset))
        n = len(game.hand)
        if n > 5:
            cands.append(("discard", 0, [n - 1]))
            cands.append(("discard", 0, [n - 2, n - 1]))

    best = None
    for kind, score, cards in cands:
        if kind == "play":
            # plays carry Card objects; discards carry hand indices
            idxs = {i for i, hc in enumerate(game.hand)
                    if any(hc is pc for pc in cards)}
        else:
            idxs = set(cards)
        g2 = _copy.deepcopy(game)
        g2.hand = [c for i, c in enumerate(g2.hand) if i not in idxs]
        if kind == "play":
            g2.chips_scored += score
            g2.hands_left -= 1
        else:
            g2.discards_left -= 1
        if g2.state != State.SELECTING_HAND or g2.hands_left <= 0:
            cleared = (g2.chips_scored >= target
                       or g2.state == State.ROUND_EVAL)
            rank = (1 if cleared else 0, g2.chips_scored, 0.0)
        else:
            pc_lo, _pc_hi = estimate_clear_probability_bounds(g2)
            plays2 = scored_plays(g2, topk=1)
            proj = g2.chips_scored + ((plays2[0][0] if plays2 else 0)
                                      * g2.hands_left)
            rank = (pc_lo, proj, g2.hands_left)
        if best is None or rank > best[0]:
            best = (rank, {"type": kind, "cards": list(cards)})
    if best is None:
        return None
    return best[1]


def _v10_mc_pick(game, plays):
    """Monte-Carlo action picker for marginal early blinds (human-fair).

    Extends best_discard's mean-EV methodology to PLAY decisions: every
    candidate action (top plays + EV/quality discards) is valued by
      chips_now + E[best next-hand score] * hands-after,
    where continuation hands are sampled from the deck's composition
    multiset with a throwaway deterministic RNG — never the run's stream
    (same pattern as best_discard phase 2). No draw-order information is
    used; the belief is pure composition."""
    rng = random.Random(0)
    multiset = _value_multiset(game.deck)
    h = game.hands_left
    rem = game.current_blind.chips_target - game.chips_scored
    cap = max(1, sum(multiset.values()))
    samples = 6

    cands = []
    seen: set = set()
    for score, cards, ht in plays[:8]:
        ids = frozenset(id(c) for c in cards)
        if ids in seen:
            continue
        seen.add(ids)
        cands.append(("play", score, list(cards)))
    if game.discards_left > 0 and len(game.deck) > 0:
        dset, _dscore = best_discard(game)
        if dset:
            cands.append(("discard", 0, list(dset)))
        n = len(game.hand)
        if n > 5:
            cands.append(("discard", 0, [n - 1]))
            cands.append(("discard", 0, [n - 2, n - 1]))

    def cont_ev(keep_idx, refill):
        keep = [c for i, c in enumerate(game.hand) if i not in keep_idx]
        refill = min(refill, cap)
        tot = 0.0
        for _ in range(samples):
            drawn = _keys_to_cards(_sample_value_keys(rng, multiset, refill))
            tot += best_play_score(game, hand=keep + drawn)
        return tot / samples

    best = None
    for kind, score, cards in cands:
        if kind == "play":
            drop = {i for i, hc in enumerate(game.hand)
                    if any(hc is pc for pc in cards)}
            val = score + cont_ev(drop, len(cards)) * (h - 1)
            if score >= rem:
                val += 1e9  # clears the blind now — always take it
        else:
            drop = set(cards)
            val = cont_ev(drop, len(cards)) * h
        if best is None or val > best[0] + 1e-9:
            best = (val, {"type": kind, "cards": list(cards)})
    return best[1]


_CONT_POLICY = None
_IN_SAMPLED_PICK = False
_CLEAR_MODEL = None
_CLEAR_MODEL_LOADED = False

_CLEAR_MODEL_BOSS_FLAGS = ["bl_manacle", "bl_hook", "bl_club", "bl_window",
                           "bl_wall", "bl_needle", "bl_mouth", "bl_arm",
                           "bl_plant", "bl_goad", "bl_head", "bl_serpent",
                           "bl_pillar", "bl_flute"]


def _clear_features(game, plays):
    """Composition-only features for the learned clear-model. MUST mirror
    tools/gen_clear_dataset.py features() exactly (model is fit on that
    order)."""
    target = game.current_blind.chips_target
    rem = target - game.chips_scored
    top = plays[0][0] if plays else 0
    main = main_hand_type(game)
    keys = [j.key for j in game.jokers]
    f = {
        "rem_ratio": round(rem / max(1, target), 4),
        "top_share": round(top / max(1, rem), 4),
        "proj_ratio": round(top * max(1, game.hands_left)
                            / max(1, rem), 4),
        "hands": game.hands_left,
        "discards": game.discards_left,
        "n_jokers": len(keys),
        "chips_j": sum(1 for k in keys if k in (
            "j_sly", "j_wily", "j_clever", "j_devious", "j_crafty",
            "j_half", "j_banner", "j_mystic_summit", "j_scary_face",
            "j_odd_todd", "j_scholar", "j_even_steven")),
        "econ_j": sum(1 for k in keys if k in (
            "j_business", "j_cloud_9", "j_credit_card", "j_delayed_grat",
            "j_egg", "j_faceless", "j_gift", "j_golden", "j_mail",
            "j_reserved_parking", "j_rocket", "j_rough_gem", "j_satellite",
            "j_ticket", "j_to_the_moon", "j_todo_list", "j_trading")),
        "money": game.dollars,
        "planet_main": game.planet_levels.get(main, 1),
        "ante": game.ante,
        "is_boss": int(game.current_blind.is_boss),
    }
    for b in _CLEAR_MODEL_BOSS_FLAGS:
        f["b_" + b] = int(game.current_blind.boss_key == b)
    return f


def _model_clear_prob(game, plays):
    """Calibrated P(blind clears) from the learned logistic clear-model
    (fit offline on policy rollouts - composition-only features, no draw
    information). Returns None when no model file ships next to this
    module."""
    global _CLEAR_MODEL, _CLEAR_MODEL_LOADED
    if not _CLEAR_MODEL_LOADED:
        _CLEAR_MODEL_LOADED = True
        try:
            path = Path(__file__).with_name("clear_model.json")
            _CLEAR_MODEL = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            _CLEAR_MODEL = None
    model = _CLEAR_MODEL
    if model is None:
        return None
    f = _clear_features(game, plays)
    z = model["b"]
    for name, mean, std, w in zip(model["features"], model["mean"],
                                  model["std"], model["w"]):
        z += ((f[name] - mean) / std) * w
    z = max(-30.0, min(30.0, z))
    return 1.0 / (1.0 + math.exp(-z))


def _continuation_policy():
    """Lazy shared HeuristicV10 for continuation rollouts (mirrors the
    current V10_PARAMS globals)."""
    global _CONT_POLICY
    if _CONT_POLICY is None:
        _CONT_POLICY = HeuristicV10()
    return _CONT_POLICY


def _v10_sampled_pick(game, plays):
    """Sampled-lookahead action picker for marginal early blinds.

    The human-fair multi-step analogue of the beam solver: for each candidate
    action, run short policy continuations on game forks whose future draws
    are REPLACED with cards sampled from the deck's composition multiset
    (throwaway RNG - never the run stream). The decision is a pure function
    of deck composition: identical compositions produce identical choices
    regardless of the actual draw order."""
    import copy as _copy

    rng = random.Random(0)
    multiset = _value_multiset(game.deck)
    cap = max(1, sum(multiset.values()))
    S = 2

    cands = []
    seen: set = set()
    for _score, cards, _ht in plays[:6]:
        ids = frozenset(id(c) for c in cards)
        if ids in seen:
            continue
        seen.add(ids)
        idxs = [i for i, hc in enumerate(game.hand)
                if any(hc is pc for pc in cards)]
        cands.append(("play", idxs))
    if game.discards_left > 0 and len(game.deck) > 0:
        dset, _dscore = best_discard(game)
        if dset:
            cands.append(("discard", list(dset)))
        n = len(game.hand)
        if n > 5:
            cands.append(("discard", [n - 1]))
            cands.append(("discard", [n - 2, n - 1]))
    pact = maybe_use_planet(game)
    if pact is not None:
        cands.append(("use", pact))
    if ACTIVE_PARAMS["use_tarots"]:
        tact = _v10_decide_consumable(game)
        if tact is not None:
            cands.append(("use", tact))

    def policy_finish(g, pol):
        """Continue the blind with the real cascade policy (no nested
        sampling - the reentrancy guard keeps hooks inert inside here)."""
        steps = 0
        while g.state == State.SELECTING_HAND and steps < 14:
            steps += 1
            g.step(pol.decide(g))
        cleared = (g.state == State.ROUND_EVAL
                   or g.chips_scored >= g.current_blind.chips_target)
        return (1 if cleared else 0), g.chips_scored

    best = None
    pol = _continuation_policy()
    _v10_sampled_pick._running = True
    try:
        for kind, cards in cands:
            tot = 0.0
            for _s in range(S):
                g2 = _copy.deepcopy(game)
                if kind == "use":
                    g2.step(dict(cards))
                else:
                    refill = min(len(cards), cap)
                    samp = _sample_value_keys(rng, multiset, refill)
                    g2.deck[-refill:] = _keys_to_cards(samp)  # pop() = tail
                    g2.step({"type": kind, "cards": list(cards)})
                cleared, chips = policy_finish(g2, pol)
                tot += cleared * 1e6 + chips
            val = tot / S
            act_out = (dict(cards) if kind == "use"
                       else {"type": kind, "cards": list(cards)})
            if best is None or val > best[0] + 1e-9:
                best = (val, act_out)
    finally:
        _v10_sampled_pick._running = False
    return best[1]


def _card_sort_key(c):
    """Deterministic quality-desc sort key: quality, then the card value
    (rank/suit/enh/edition/seal) so ties never depend on deck order."""
    return (_card_quality(c),
            (c.rank, c.suit, c.enhancement, c.edition, c.seal))


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
        for c5 in _type_candidates(ranked, ht):
            try:
                ht5, sc = evaluate_hand(c5)
                s = eval_hand_score(game, ht5, sc, c5)
            except Exception:
                continue
            S[ht5] = max(S.get(ht5, 0), s)
            break
    return S


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
    if game.ante == 1 and V10_PARAMS.get("ante1_kd_boost", True) and V10_PARAMS["farm_clear_threshold"] < 1.0:
        k_d = min(5, hs)
        k_r = max(2, hs - 4)
    else:
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
# R3: Scaling joker acceleration during safe blinds (§5.3, §6)
# ────────────────────────────────────────────────────────────────────────────

SCALING_ACCEL_KEYS = {
    "j_green_joker",
    "j_ride_the_bus",
    "j_supernova",
    "j_wee",
    "j_square_joker",
    "j_spare_trousers",
}

SCALING_BANNED_BOSSES = {
    "bl_needle",
    "bl_mouth",
    "bl_eye",
    "bl_grim",
    "bl_hook",
    "bl_tooth",
    "bl_pillar",
    "bl_psychic",
}


def _has_scoring_face(hand: list[Card], combo: tuple[int, ...] | list[int]) -> bool:
    """Return True if any scoring card in combo is a face card (Jack, Queen, King)."""
    cards = [hand[i] for i in combo]
    res = evaluate_hand(cards)
    scoring_cards = res[1]
    return any(c.is_face_card for c in scoring_cards)


def _get_active_scaling_jokers(game) -> set[str]:
    keys = {j.key for j in game.jokers}
    return keys & SCALING_ACCEL_KEYS


def _find_scaling_action(game, hand: list[Card], plays, p_clear: float) -> dict | None:
    r"""Find a safe scaling action during easy blinds to bank permanent scaling triggers.
    Strictly enforces:
    - Ante > 1 (strictly disallowed in Ante 1)
    - hands_left >= 3 (so at least 2 hands remain after scaling play)
    - At most 1 scaling play per blind (chips_scored == 0 and hands_played == 0)
    - Non-banned boss blind
    - Strict Tier S1 disjoint in-hand knockout reservation ONLY:
      There MUST exist a valid clearing combination K in hand (score(K) >= target),
      and candidate scaling play C must be a disjoint subset of hand \ K so K remains
      100% intact in hand for the next turn.
    """
    if game.ante <= 1:
        return None
    scaling_keys = _get_active_scaling_jokers(game)
    if not scaling_keys:
        return None
    if game.hands_left < 3:
        return None
    if getattr(game, "chips_scored", 0) > 0 or getattr(game, "hands_played", 0) > 0:
        return None
    boss = _boss_key(game)
    if boss in SCALING_BANNED_BOSSES:
        return None

    target = game.current_blind.chips_target - game.chips_scored
    if target <= 0:
        return None

    clearing_plays = [pl for pl in plays if pl[0] >= target]
    if not clearing_plays:
        return None

    has_chad = any(j.key == "j_hanging_chad" for j in game.jokers)
    has_bus = "j_ride_the_bus" in scaling_keys
    has_wee = "j_wee" in scaling_keys
    has_square = "j_square_joker" in scaling_keys
    has_trousers = "j_spare_trousers" in scaling_keys
    has_green = "j_green_joker" in scaling_keys
    has_supernova = "j_supernova" in scaling_keys

    # Tier S1: Check for disjoint play outside knockout_k (100% deterministic survival next hand)
    # Prefer minimal-card clearing plays to leave maximal non-clearing cards in hand
    sorted_clearing = sorted(clearing_plays, key=lambda pl: (len(pl[1]), -pl[0]))
    for _, k_combo, _ in sorted_clearing[:5]:
        k_set = set(k_combo)
        non_k_indices = [i for i in range(len(hand)) if i not in k_set]
        if not non_k_indices:
            continue
        candidates = []
        for r in range(1, min(5, len(non_k_indices)) + 1):
            for combo in combinations(non_k_indices, r):
                cards_c = [hand[i] for i in combo]
                ht_c, sc_c = evaluate_hand(cards_c)
                held_c = [c for i, c in enumerate(hand) if i not in set(combo)]
                score = eval_hand_score(game, ht_c, sc_c, cards_c, held_cards=held_c)
                if score >= target:
                    continue
                # Strict non-face guardrail for Ride the Bus
                if has_bus and any(c.is_face_card for c in sc_c if not getattr(c, "debuffed", False)):
                    continue

                scale_val = 0
                ordered_combo = list(combo)

                if has_wee:
                    twos = [i for i in combo if hand[i].rank == 2 and not getattr(hand[i], "debuffed", False)]
                    if twos:
                        scale_val += 100 * len(twos)
                        others = [i for i in combo if i not in twos]
                        ordered_combo = twos + others

                if has_bus:
                    scale_val += 30

                if has_trousers and ht_c in ("Two Pair", "Full House"):
                    scale_val += 50

                if has_square and len(sc_c) == 4:
                    scale_val += 40

                if has_green:
                    scale_val += 20

                if has_supernova:
                    scale_val += 10

                if scale_val > 0:
                    candidates.append((scale_val, -score, ordered_combo))

        if candidates:
            candidates.sort(key=lambda x: (x[0], x[1]), reverse=True)
            return {"type": "play", "cards": candidates[0][2]}

    return None


# ────────────────────────────────────────────────────────────────────────────
# Tier 1 — survive (V9's play/discard core, re-armed with P(clear))
# ────────────────────────────────────────────────────────────────────────────

def _tier1_survive(game, plays, p_clear=None):
    """The V9 'just enough / discard EV' core, minus the pre-actions (Verdant
    sell, planet, consumable) which the cascade runs first. Byte-equivalent to
    V9's play/discard decision so the farming-off arm reproduces V9."""
    p = ACTIVE_PARAMS
    if not plays:
        return {"type": "play", "cards": [0] if game.hand else []}

    best_score, best_combo, best_hand_type = plays[0]
    target = game.current_blind.chips_target - game.chips_scored

    has_bus = any(j.key == "j_ride_the_bus" for j in game.jokers) if V10_PARAMS.get("farm_clear_threshold", 0.90) < 1.0 else False
    if best_score >= target:
        clearing = [pl for pl in plays if pl[0] >= target]
        if has_bus:
            safe_clearing = [pl for pl in clearing if not _has_scoring_face(game.hand, pl[1])]
            if safe_clearing:
                clearing = safe_clearing
        clearing.sort(key=lambda e: (len(e[1]), e[0]))
        return {"type": "play", "cards": list(clearing[0][1])}

    # Ante-1 pace rule: multi-hand budget discipline.
    # If the held play satisfies the per-hand pace to clear the blind, play it
    # rather than gambling discards on thin structural upgrades.
    # - If an active joker target hand is set (e.g. Flush for Tribe), don't pace-play
    #   off-target hands while discards remain.
    # - When hands_left <= 2 and hand doesn't clear, only pace-play if discards are
    #   exhausted (discards_left <= 1); otherwise use remaining discards to dig.
    if (V10_PARAMS.get("ante1_pace_rule", False) and game.ante == 1
            and V10_PARAMS["farm_clear_threshold"] < 1.0):
        target_ht = joker_target_hand_type(game)
        allow_pace = True
        if target_ht and target_ht != "High Card" and game.discards_left > 0:
            if best_hand_type != target_ht:
                allow_pace = False
        if allow_pace:
            is_dig_start = (game.hands_left >= 4 and game.discards_left >= 4 and game.chips_scored == 0)
            if not is_dig_start:
                if game.hands_left >= 3 or game.discards_left <= 1 or best_score >= target * 0.65:
                    pace = (target / max(1, game.hands_left)) * V10_PARAMS.get("ante1_pace_mult", 1.0)
                    if best_score >= pace:
                        return {"type": "play", "cards": list(best_combo)}

    # Ante-1 dig doctrine (Bellatro 101): spend every discard digging before
    # playing any non-clearing hand - even over a held flush, draw the
    # better one. Round-1 income makes hands cheap relative to information.
    if (V10_PARAMS.get("ante1_dig_discards") and game.ante == 1
            and game.discards_left > 0 and len(game.deck) > 0):
        dset, _dscore = best_discard(game, base_score=best_score)
        if dset:
            return {"type": "discard", "cards": list(dset)}

    # Joker-aware hand-type chase (M13+): when a hand-type joker is owned and
    # the target hand type can CLEAR within remaining hands, prefer playing
    # that type over the greedy best — e.g. Photograph + flush-with-face beats
    # Boss 600 in one; Sly + trips→full house clears Big 450. Gated farm<1.0.
    target_ht = joker_target_hand_type(game)
    if target_ht and target_ht != "High Card":
        ht_plays = [pl for pl in plays if pl[2] == target_ht]
        if ht_plays:
            # Prefer a play of the target type that makes real progress
            # (>50% of remaining target) or clears outright.
            progress = max(ht_plays, key=lambda e: e[0])
            if progress[0] >= target or (
                    game.hands_left >= 2
                    and progress[0] >= target * 0.5):
                return {"type": "play", "cards": list(progress[1])}

    good_thresh = V10_PARAMS.get("ante1_good_hand", p["discard_play_good_hand"]) if game.ante == 1 and game.hands_left == 2 and V10_PARAMS["farm_clear_threshold"] < 1.0 else p["discard_play_good_hand"]
    if V10_PARAMS.get("farm_clear_threshold", 0.90) < 1.0:
        good_hand = (best_score >= target) if game.hands_left == 1 else (best_score >= target * good_thresh)
    else:
        good_hand = best_score >= target * p["discard_play_good_hand"]

    # The joker's type is NOT assembled: chase its partial structure with the
    # discards instead of generic EV (Family boards died playing two pair
    # filler while the x4 Four-of-a-Kind engine starved). Never over a good
    # hand - playing progress beats gambling on structure.
    if (target_ht and target_ht != "High Card"
            and not good_hand
            and V10_PARAMS.get("joker_type_chase_ante", 0)
            and game.ante <= V10_PARAMS["joker_type_chase_ante"]
            and V10_PARAMS["farm_clear_threshold"] < 1.0
            and best_score < target
            and game.discards_left > 0
            and game.hands_left >= 2):
        chase = _joker_type_chase_discard(game, game.hand, target_ht)
        if chase:
            return {"type": "discard", "cards": list(chase)}

    has_green = any(j.key == "j_green_joker" for j in game.jokers) if V10_PARAMS.get("farm_clear_threshold", 0.90) < 1.0 else False
    safe_for_green = (p_clear is not None and (p_clear >= 0.99 if game.ante == 1 else p_clear >= 0.98))
    if has_green and safe_for_green and game.hands_left >= 2:
        # Suppress discard to avoid -1 Mult penalty; play a safe hand instead
        if plays:
            if has_bus:
                non_face = [pl for pl in plays if not _has_scoring_face(game.hand, pl[1])]
                if non_face:
                    return {"type": "play", "cards": list(non_face[0][1])}
            return {"type": "play", "cards": list(best_combo)}

    if (not good_hand and game.discards_left > 0 and len(game.deck) > 0
            and p["discard_hold_until_clear"] and game.hands_left >= 2):
        dset, dscore = best_discard(game, base_score=best_score)
        if dset:
            return {"type": "discard", "cards": list(dset)}

    if not good_hand and game.discards_left > 0 and len(game.deck) > 0:
        if game.hands_left == 1 and best_score < target and V10_PARAMS.get("farm_clear_threshold", 0.90) < 1.0:
            dset, _ = best_discard(game, base_score=best_score)
            if dset:
                return {"type": "discard", "cards": list(dset)}

        two_hand = (V10_PARAMS.get("discard_two_hand_ante", 0) > 0
                    and game.ante <= V10_PARAMS["discard_two_hand_ante"]
                    and V10_PARAMS["farm_clear_threshold"] < 1.0
                    and game.hands_left >= 2
                    and best_score < target)
        dset, dscore = best_discard(game, base_score=best_score,
                                    two_hand=two_hand)
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
    if game.discards_left > 0:
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
    if p.get("farm_clear_threshold", 0.90) < 1.0:
        _optimize_joker_order(game)

    # Early-ante structure gate: loosen the straight/flush chase triggers on
    # antes where the blinds are marginal close misses, restore the tuned v9
    # thresholds elsewhere so mid-game engine hands keep their discipline.
    if (p.get("early_struct_ante", 0) and game.ante <= p["early_struct_ante"]
            and p.get("farm_clear_threshold", 0.90) < 1.0):
        ACTIVE_PARAMS["discard_struct_min_run"] = p.get(
            "early_struct_min_run", 3)
        ACTIVE_PARAMS["discard_struct_min_suit"] = p.get(
            "early_struct_min_suit", 3)
    else:
        ACTIVE_PARAMS["discard_struct_min_run"] = 4
        ACTIVE_PARAMS["discard_struct_min_suit"] = 4

    # The Manacle (-1 hand size): 5-card structures are too thin to chase on
    # 7-card hands — the beam solver wins these boards via two pair / full
    # house lines. Demote run/suit chases so the pair-based EV pool drives.
    if (game.ante <= 2
            and game.current_blind.boss_key == "bl_manacle"):
        ACTIVE_PARAMS["discard_struct_min_run"] = 5
        ACTIVE_PARAMS["discard_struct_min_suit"] = 5

    # Pre-actions (unchanged from v9).
    if (game.current_blind.boss_key == "bl_verdant"
            and game.verdant_debuff and game.jokers):
        worst = _v10_worst_joker_idx(game)
        if worst is not None:
            return {"type": "sell_joker", "joker_idx": worst}

    if not game.hand:
        return {"type": "play", "cards": []}

    plays = scored_plays(game, topk=ACTIVE_PARAMS["eval_topk_play"])

    # Boss-restriction filter (Mouth, Eye, Cerulean Bell): scored_plays includes boss-blocked
    # hands with high scores which causes zero-score rejections if played. Gated on farm < 1.0.
    if V10_PARAMS.get("farm_clear_threshold", 0.90) < 1.0:
        boss = _boss_key(game)
        if boss in ("bl_mouth", "bl_eye", "bl_cerulean"):
            valid = []
            for s, combo, ht in plays:
                cards = [game.hand[i] for i in combo]
                if _boss_play_filter(game, combo, ht, cards, boss):
                    valid.append((s, combo, ht))
            if valid:
                if boss == "bl_mouth" and not game.played_hand_types_this_round:
                    rem = game.current_blind.chips_target - game.chips_scored
                    if valid[0][0] < rem and len(valid) > 1:
                        repeatable = [pl for pl in valid if pl[2] in ("Pair", "Two Pair", "High Card")]
                        if repeatable and repeatable[0][0] * max(1, game.hands_left) >= rem:
                            valid = repeatable + [pl for pl in valid if pl not in repeatable]
                plays = valid
            elif game.discards_left > 0 and len(game.deck) > 0:
                dset, _ = best_discard(game)
                return {"type": "discard", "cards": list(dset) if dset else [0]}
            else:
                trash = min(range(len(game.hand)), key=lambda i: (
                    game.hand[i].enhancement != "None",
                    game.hand[i].seal is not None,
                    game.hand[i].rank
                ))
                return {"type": "play", "cards": [trash]}

    # Ante-1 planet doctrine: a held Planet for the run's main hand type is
    # permanent chips/mult - spend it now even when that type is not in the
    # current hand's top-3 plays (the v9 top-3 gate strands it otherwise).
    if (V10_PARAMS.get("ante1_planet_main") and game.ante == 1
            and game.consumable_hand):
        main = main_hand_type(game)
        for ci, key in enumerate(game.consumable_hand):
            if key in PLANET_HAND and PLANET_HAND[key] == main:
                return {"type": "use_consumable",
                        "consumable_idx": ci, "target_cards": []}

    # Learned clear-model gauge (calibrated on rollout outcomes; see
    # tools/gen_clear_dataset.py + tools/fit_clear_model.py).
    model_prob = None
    if p.get("model_gate"):
        model_prob = _model_clear_prob(game, plays)

    # Sampled-lookahead picker: on marginal early blinds, evaluate candidate
    # actions (plays, discards, planet/tarot use) by policy continuations
    # over composition-sampled shuffles. Scoped (default) to Manacle blinds
    # where it measured +EV (+7 wins, -3 deaths); fires once per blind at
    # the opening - the opening decision carries most of the solver's edge.
    # `sampled_pick_bosses` widens coverage to more killer bosses.
    bosses = p.get("sampled_pick_bosses", ["bl_manacle"])
    other_margin = p.get("sampled_pick_other_margin", 0.0)
    in_scope = (not p.get("sampled_pick_manacle_only", False)
                or game.current_blind.boss_key in bosses
                or (p.get("model_scope_widen", False)
                    and model_prob is not None
                    and model_prob < p.get("model_pick_below", 0.85)))
    margin = p.get("sampled_pick_margin", 1.4)
    if not in_scope and other_margin > 0:
        # Strict-margin widening: ANY boss, but only when the linear
        # projection itself falls short of the target (top*hands < target).
        # The old widening churned healthy openings at margin 1.4; doomed-
        # looking boards have no healthy opening to churn.
        in_scope = True
        margin = other_margin
    if (p.get("sampled_pick_ante", 0)
            and game.ante <= p["sampled_pick_ante"]
            and in_scope
            and V10_PARAMS["farm_clear_threshold"] < 1.0
            and game.chips_scored == 0
            and not getattr(_v10_sampled_pick, "_running", False)
            and getattr(game, "_sp_fired_key", None) != (game.ante,
                                                         game.blind_idx)):
        top = plays[0][0] if plays else 0
        remaining = game.current_blind.chips_target
        if top * max(1, game.hands_left) < remaining * margin:
            act = _v10_sampled_pick(game, plays)
            game._sp_fired_key = (game.ante, game.blind_idx)
            if act is not None:
                return act

    act = _v10_maybe_use_planet(game, plays)
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

    # 1-ply compositional outcome search on early antes: choose the action
    # that maximizes post-action P(clear) instead of following the fixed
    # cascade (closes the gap the beam solver exposed).
    if p.get("pclear_pick_ante", 0) and game.ante <= p["pclear_pick_ante"]:
        act = _v10_pclear_pick(game, plays)
        if act is not None:
            return act

    # Monte-Carlo mean-EV picker (human-fair composition sampling).
    if p.get("mc_pick_ante", 0) and game.ante <= p["mc_pick_ante"]:
        act = _v10_mc_pick(game, plays)
        if act is not None:
            return act

    if V10_PARAMS.get("scaling_accel_enabled", True) and V10_PARAMS["farm_clear_threshold"] < 1.0:
        scale_act = _find_scaling_action(game, game.hand, plays, p_clear)
        if scale_act is not None:
            return scale_act

    if p_clear >= p["farm_clear_threshold"]:
        # Rate sanity gate: P(clear) reads 1.000 on doomed boards (seed 87
        # bank), so value-farming burns early hands for pennies exactly when
        # the blind is marginal. Only enter farming when the board's ACTUAL
        # top play carries its fair share of the remaining target - and,
        # when the learned model is on, when the CALIBRATED probability
        # agrees the blind is safe.
        share = ((game.current_blind.chips_target - game.chips_scored)
                 / max(1, game.hands_left))
        rate_share = p.get("farm_rate_share", 0.0)
        model_ok = (model_prob is None
                    or model_prob >= p.get("model_farm_floor", 0.5))
        if (model_ok
                and (rate_share <= 0
                     or (plays and plays[0][0] >= share * rate_share))):
            act = tier2_value(game, plays, type_scores)
            if act is not None:
                return act

    if V10_PARAMS.get("farm_clear_threshold", 0.90) < 1.0:
        target = game.current_blind.chips_target - game.chips_scored
        if target > 0 and game.discards_left > 0 and game.hands_left >= 2 and len(game.deck) > 0:
            pace = target / max(1, game.hands_left)
            best_score = plays[0][0] if plays else 0
            if best_score < pace * 0.35:
                dset, _ = best_discard(game, base_score=best_score)
                if dset:
                    return {"type": "discard", "cards": list(dset)}
                else:
                    pool = sorted(range(len(game.hand)), key=lambda i: _card_quality(game.hand[i]))
                    _keep = joker_keep_indices(game.hand, game)
                    pool = [i for i in pool if i not in _keep]
                    if pool:
                        to_discard = pool[:min(3, len(pool))]
                        return {"type": "discard", "cards": to_discard}

    return _tier1_survive(game, plays, p_clear=p_clear)


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


def formulate_counterfactual_state(game: Any, action: dict[str, Any]) -> dict[str, float]:
    """Formulate counterfactual post-action feature dict s'_a without mutating game state."""
    ante = getattr(game, "ante", 1)
    blind_idx = getattr(game, "blind_idx", 0)
    dollars = getattr(game, "dollars", 0)
    hands_left = getattr(game, "hands_left", 4)
    discards_left = getattr(game, "discards_left", 3)
    joker_slots = getattr(game, "joker_slots", 5)
    jokers = [(j.key, getattr(j, "edition", None)) for j in getattr(game, "jokers", [])]
    consumable_slots = getattr(game, "consumable_slots", 2)
    consumables_count = len(getattr(game, "consumable_hand", []))
    vouchers = set(getattr(game, "vouchers", []))
    hand_levels = dict(getattr(game, "hand_levels", getattr(game, "planet_levels", {})))

    deck = getattr(game, "deck", [])
    deck_size = len(deck)
    suit_counts: dict[str, int] = {}
    face_count = 0
    enh_count = 0
    seal_count = 0
    for c in deck:
        s = getattr(c, "suit", "")
        suit_counts[s] = suit_counts.get(s, 0) + 1
        if getattr(c, "rank", 0) in (11, 12, 13):
            face_count += 1
        if getattr(c, "enhancement", "None") != "None":
            enh_count += 1
        if getattr(c, "seal", None):
            seal_count += 1

    target = 0
    if getattr(game, "current_blind", None):
        target = getattr(game.current_blind, "chips_target", 0)

    act_type = action.get("type")

    if act_type == "leave_shop":
        pass

    elif act_type == "buy":
        idx = action["item_idx"]
        item = game.current_shop[idx]
        price = item.discounted_price(game.shop_discount)
        dollars = max(0, dollars - price)

        if item.kind == "joker":
            jokers = list(jokers) + [(item.key, item.edition)]
            if item.edition == "Negative":
                joker_slots += 1
        elif item.kind == "planet":
            ht = PLANET_HAND.get(item.key)
            if ht:
                hand_levels[ht] = hand_levels.get(ht, 1) + 1
        elif item.kind == "tarot":
            consumables_count = min(consumable_slots, consumables_count + 1)
            if item.key in ("c_empress", "c_hierophant", "c_lovers", "c_chariot",
                            "c_justice", "c_tower", "c_magician", "c_devil"):
                enh_count = min(deck_size, enh_count + (2 if item.key in ("c_empress", "c_hierophant") else 1))
            elif item.key in TAROT_SUIT:
                ts = TAROT_SUIT[item.key]
                suit_counts[ts] = suit_counts.get(ts, 0) + 3
            elif item.key == "c_hanged_man":
                deck_size = max(1, deck_size - 2)
            elif item.key == "c_strength":
                face_count = min(deck_size, face_count + 1)
            elif item.key == "c_death":
                enh_count = min(deck_size, enh_count + 1)
            elif item.key == "c_hermit":
                dollars = min(50, dollars + min(dollars, 20))
        elif item.kind == "spectral":
            consumables_count = min(consumable_slots, consumables_count + 1)
            seal_count = min(deck_size, seal_count + 1)
        elif item.kind == "voucher":
            vouchers = set(vouchers) | {item.key}
            if item.key in ("v_grabber", "v_nacho_tong"):
                hands_left += 1
            elif item.key in ("v_wasteful", "v_recyclomancy"):
                discards_left += 1
        elif item.kind == "booster":
            if item.key.startswith("p_buffoon"):
                if ante <= 2:
                    jokers = list(jokers) + [("j_banner", None)]
                else:
                    jokers = list(jokers) + [("j_cavendish", None)]
            elif item.key.startswith("p_celestial"):
                m_ht = main_hand_type(game)
                hand_levels[m_ht] = hand_levels.get(m_ht, 1) + 1
            elif item.key.startswith("p_standard"):
                enh_count = min(deck_size + 1, enh_count + 1)
                deck_size += 1
            elif item.key.startswith("p_arcana"):
                enh_count = min(deck_size, enh_count + 1)
            elif item.key.startswith("p_spectral"):
                seal_count = min(deck_size, seal_count + 1)
        elif item.kind == "card" and item.card is not None:
            deck_size += 1
            c = item.card
            if c.is_face_card:
                face_count += 1
            if getattr(c, "enhancement", "None") != "None":
                enh_count += 1
            if getattr(c, "seal", None):
                seal_count += 1

    elif act_type == "sell_joker":
        j_idx = action["joker_idx"]
        if 0 <= j_idx < len(game.jokers):
            j_inst = game.jokers[j_idx]
            sell_val = getattr(j_inst, "state", {}).get("sell_value", max(1, getattr(j_inst, "cost", 4) // 2))
            dollars += sell_val
            jokers = [jk for k, jk in enumerate(jokers) if k != j_idx]

    elif act_type == "swap_joker":
        s_idx = action["sell_idx"]
        b_idx = action["buy_idx"]
        item = game.current_shop[b_idx]
        price = item.discounted_price(game.shop_discount)
        if 0 <= s_idx < len(game.jokers):
            j_inst = game.jokers[s_idx]
            sell_val = getattr(j_inst, "state", {}).get("sell_value", max(1, getattr(j_inst, "cost", 4) // 2))
            dollars = max(0, dollars + sell_val - price)
            jokers = [jk for k, jk in enumerate(jokers) if k != s_idx] + [(item.key, item.edition)]

    elif act_type == "reroll":
        reroll_cost = max(0, game.reroll_cost - game.reroll_discount)
        dollars = max(0, dollars - reroll_cost)

    return extract_features_from_state(
        ante=ante,
        blind_idx=blind_idx,
        dollars=dollars,
        hands_left=hands_left,
        discards_left=discards_left,
        joker_slots=joker_slots,
        jokers=jokers,
        consumable_slots=consumable_slots,
        consumables_count=consumables_count,
        vouchers=vouchers,
        hand_levels=hand_levels,
        deck_size=deck_size,
        suit_counts=suit_counts,
        face_count=face_count,
        enhanced_count=enh_count,
        sealed_count=seal_count,
        chips_target=target,
    )


HIGH_LEVERAGE_SCORING_JOKERS = {
    "j_cavendish", "j_baseball", "j_duo", "j_trio", "j_order",
    "j_tribe", "j_family", "j_ramen", "j_stuntman", "j_constellation",
}


class SearchShopV10(SearchShopV9):
    """Layer-1: True L1 Counterfactual Shop Search with offline value model V(s').

    Evaluates candidate shop actions (buy, sell, swap, reroll, leave) by predicting
    post-action state value V(s') and computing value gain Delta V = V(s') - V(s).
    Performs dynamic room making when selling redundant/economy jokers to acquire
    higher-value scoring jokers yields positive Delta V(swap).
    """
    policy_name = "search_shop_v10"

    def __init__(self, params=None, search_shops: int = 999, candidate_cap: int = 4,
                 lookahead: bool = False, max_rollout_steps: int = 4000, **kwargs):
        super().__init__(params=params, search_shops=search_shops,
                         candidate_cap=candidate_cap, lookahead=lookahead,
                         max_rollout_steps=max_rollout_steps)
        if params:
            V10_PARAMS.update(params)
        self._pending_swap_target_idx: int | None = None

    def _search_shop(self, game) -> dict:
        """True L1 Counterfactual Shop Search:
        Evaluates candidate purchases via Delta V = V(s') - V(s) when slots are open.
        When slots are full, evaluates candidate joker swaps V(s') - V(s) across
        candidate sells to facilitate transitions to xMult / scaling / combat jokers."""
        if not game.current_shop or all(getattr(item, "sold", False) for item in game.current_shop):
            return {"type": "leave_shop"}

        # 1. Complete pending second step of a swap
        if self._pending_swap_target_idx is not None:
            target_i = self._pending_swap_target_idx
            self._pending_swap_target_idx = None
            if 0 <= target_i < len(game.current_shop) and not game.current_shop[target_i].sold:
                item = game.current_shop[target_i]
                price = item.discounted_price(game.shop_discount)
                has_room = len(game.jokers) < game.joker_slots or getattr(item, "edition", None) == "Negative"
                if price <= game.dollars and has_room:
                    return {"type": "buy", "item_idx": target_i}

        f_curr = extract_game_features(game)
        v_curr = evaluate_shop_value(f_curr)
        swap_threshold = V10_PARAMS.get("swap_delta_threshold", 0.005)

        # 2. Open slots: handled by _v10_decide_shop for calibrated scoring and interest management
        if len(game.jokers) < game.joker_slots:
            return _v10_decide_shop(game, getattr(self, "_rerolls_this_shop", 0))

        # 3. Full-Slot Portfolio Swaps (len(jokers) >= joker_slots and game.ante >= 4)
        if len(game.jokers) >= game.joker_slots and game.ante >= 4:
            owned = [j.key for j in game.jokers]
            n_xmult = sum(1 for k in owned if k in PORTFOLIO_XMULT)
            n_chips = sum(1 for k in owned if k in PORTFOLIO_CHIPS)
            n_flat = sum(1 for k in owned if k in PORTFOLIO_FLAT)

            worst_j = _v10_worst_joker_idx(game)
            if worst_j is None:
                return _v10_decide_shop(game, getattr(self, "_rerolls_this_shop", 0))

            owned_cand = game.jokers[worst_j]
            has_premier_in_shop = any(
                not getattr(it, "sold", False) and getattr(it, "kind", "") == "joker"
                and (it.key in HIGH_LEVERAGE_SCORING_JOKERS or it.key in RELIABLE_XMULT_JOKERS or it.key in PREMIER_XMULT_FINISHERS)
                for it in getattr(game, "current_shop", [])
            )
            # Protect economy jokers in early/mid game (Antes 1-5) EXCEPT pure piggy banks like egg
            # or when a premier finisher / xMult is available in shop
            if game.ante <= 5 and (owned_cand.key in {"j_business", "j_golden", "j_todo_list", "j_satellite"}):
                if not has_premier_in_shop:
                    return _v10_decide_shop(game, getattr(self, "_rerolls_this_shop", 0))

            # Never sell key retriggers or premier anchors before Ante 7
            if owned_cand.key in {"j_hanging_chad", "j_dusk", "j_mime", "j_sock_and_buskin", "j_cavendish", "j_ramen"}:
                return _v10_decide_shop(game, getattr(self, "_rerolls_this_shop", 0))

            # Protect anchors before Ante 7
            if game.ante <= 6:
                if n_xmult <= 1 and owned_cand.key in PORTFOLIO_XMULT:
                    return _v10_decide_shop(game, getattr(self, "_rerolls_this_shop", 0))
                if n_chips <= 1 and owned_cand.key in PORTFOLIO_CHIPS:
                    return _v10_decide_shop(game, getattr(self, "_rerolls_this_shop", 0))
                if n_flat <= 1 and owned_cand.key in PORTFOLIO_FLAT:
                    return _v10_decide_shop(game, getattr(self, "_rerolls_this_shop", 0))
                if owned_cand.key in COMBAT_SCALING_JOKERS:
                    return _v10_decide_shop(game, getattr(self, "_rerolls_this_shop", 0))

            sell_val = getattr(owned_cand, "state", {}).get("sell_value", max(1, getattr(owned_cand, "cost", 4) // 2))
            best_swap_delta = max(swap_threshold, 0.020)
            best_swap_item_idx = None

            for i, item in enumerate(game.current_shop):
                if item.sold or item.kind != "joker" or getattr(item, "edition", None) == "Negative":
                    continue
                # Skip trap or conditional xMult jokers unless prerequisite met
                if item.key in {"j_madness", "j_obelisk", "j_idol", "j_the_idol"}:
                    continue
                if item.key == "j_lucky_cat" and not any(getattr(c, "enhancement", "") == "Lucky" for c in game.deck):
                    continue
                if item.key == "j_glass_joker" and not any(getattr(c, "enhancement", "") == "Glass" for c in game.deck):
                    continue
                if item.key == "j_steel_joker" and not any(getattr(c, "enhancement", "") == "Steel" for c in game.deck):
                    continue
                if item.key == "j_family":
                    from collections import Counter
                    cards = list(getattr(game, "deck", ())) + list(getattr(game, "hand", ())) + list(getattr(game, "spent", ()))
                    rank_counts = Counter(getattr(c, "rank", None) for c in cards if getattr(c, "rank", None) is not None)
                    if max(rank_counts.values(), default=0) < 5:
                        continue
                # Target high-leverage scoring or reliable xMult transitions (or any combat joker to replace dead econ in late game)
                is_dead_econ = owned_cand.key in DEAD_ECONOMY_JOKERS or owned_cand.key in PORTFOLIO_ECON
                is_combat_cand = (item.key in PORTFOLIO_FLAT or item.key in PORTFOLIO_CHIPS or item.key in PORTFOLIO_XMULT or item.key in COMBAT_SCALING_JOKERS)
                if not (item.key in HIGH_LEVERAGE_SCORING_JOKERS or item.key in RELIABLE_XMULT_JOKERS or (game.ante >= 6 and is_dead_econ and is_combat_cand)):
                    continue
                price = item.discounted_price(game.shop_discount)
                if game.dollars + sell_val < price:
                    continue
                # Don't swap away sole xMult joker unless replacing with another xMult
                if owned_cand.key in PORTFOLIO_XMULT and n_xmult <= 1 and item.key not in PORTFOLIO_XMULT:
                    continue

                f_swap = formulate_counterfactual_state(game, {
                    "type": "swap_joker", "sell_idx": worst_j, "buy_idx": i
                })
                v_swap = evaluate_shop_value(f_swap)
                delta = v_swap - v_curr
                is_premier = item.key in PREMIER_XMULT_FINISHERS or item.key in RELIABLE_XMULT_JOKERS
                if is_dead_econ and is_premier and game.ante >= 4:
                    delta = max(delta, 0.05)
                elif is_dead_econ and is_combat_cand and game.ante >= 6:
                    delta = max(delta, 0.05)
                if delta > best_swap_delta:
                    best_swap_delta = delta
                    best_swap_item_idx = i

            if best_swap_item_idx is not None:
                self._pending_swap_target_idx = best_swap_item_idx
                return {"type": "sell_joker", "joker_idx": worst_j}

        # 4. Fallback to _v10_decide_shop for economy, packs, tarots, planets
        return _v10_decide_shop(game, getattr(self, "_rerolls_this_shop", 0))

    def decide(self, game) -> dict:
        st = game.state
        if st == State.SELECTING_HAND:
            return _v10_decide_hand(game)
        if st == State.BOOSTER_OPEN:
            return _v10_decide_booster(game)
        if st != State.SHOP:
            return super().decide(game)

        if not self._in_shop:
            self._in_shop = True
            self._rerolls_this_shop = 0
            self._searched_this_visit = False
            self._pending_swap_target_idx = None

        if V10_PARAMS.get("farm_clear_threshold", 0.90) < 1.0:
            _optimize_joker_order(game)

        # 1. Complete pending second step of a swap immediately
        if self._pending_swap_target_idx is not None:
            target_i = self._pending_swap_target_idx
            self._pending_swap_target_idx = None
            if 0 <= target_i < len(game.current_shop) and not game.current_shop[target_i].sold:
                item = game.current_shop[target_i]
                price = item.discounted_price(game.shop_discount)
                has_room = len(game.jokers) < game.joker_slots or getattr(item, "edition", None) == "Negative"
                if price <= game.dollars and has_room:
                    return {"type": "buy", "item_idx": target_i}

        # Pre-shop consumable usage (use planet/tarot to free slots or apply buffs)
        act = _v10_maybe_use_planet(game)
        if act is not None:
            return act
        if ACTIVE_PARAMS.get("use_tarots", True):
            act = _v10_decide_consumable(game)
            if act is not None:
                return act

        # Boss reroll check if dangerous boss and Director's Cut owned
        if game.next_boss_key in BAD_BOSSES and game.dollars >= 10:
            can_dc = ("v_directors_cut" in game.vouchers and game.dc_reroll_ante != game.ante)
            can_retcon = "v_retcon" in game.vouchers
            if can_dc or can_retcon:
                return {"type": "reroll_boss"}

        # Counterfactual shop search on first action of the shop visit
        if (self._searches_done < self._search_shops
                and not self._searched_this_visit):
            self._searched_this_visit = True
            act = (self._search_shop_rollout(game) if self._lookahead
                   else self._search_shop(game))
            if act is not None:
                if act.get("type") == "leave_shop":
                    self._searches_done += 1
                    self._in_shop = False
                    self._pending_swap_target_idx = None
                    return act
                elif act.get("type") in ("buy", "sell_joker", "reroll"):
                    if act.get("type") == "reroll":
                        self._rerolls_this_shop += 1
                        self._searched_this_visit = False
                    return act

        act = _v10_decide_shop(game, self._rerolls_this_shop)
        if act.get("type") == "reroll":
            self._rerolls_this_shop += 1
            self._searched_this_visit = False
        elif act.get("type") == "leave_shop":
            self._in_shop = False
            if self._searched_this_visit:
                self._searches_done += 1
                self._searched_this_visit = False
            self._pending_swap_target_idx = None
        return act
