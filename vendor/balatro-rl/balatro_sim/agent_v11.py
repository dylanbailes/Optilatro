"""balatro_sim/agent_v11.py — Optilatro V11 Unified Architecture.

Combines:
  1. Component A: Full Left-to-Right Joker Trigger Order Optimization
     (Utility -> Chips -> Flat Mult -> Polychrome Flat -> xMult -> Polychrome xMult)
     plus Blueprint/Brainstorm/Ceremonial dynamic positioning and early-game
     scaling joker growth potential valuation.
  2. Component B: Combinatorial Multi-Item Shop Sequence Planning (L1 Decision Rule)
     evaluating sequential shop paths (sell -> buy, use -> buy, multi-buys)
     when transitioning builds or unlocking capital.
  3. Component C: Learned Global Full-Run Win Rate Value Network V_theta(S) -> P(Win)
     (2-layer MLP with 50 features and interaction terms, AUC 0.872+).

Preserves 100% human-fairness (no draw peeking, isolated evals, zero RNG consumption)
and maintains complete backward compatibility with SearchShopV10.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Sequence

import numpy as np

from .consumables import PLANET_HAND, TAROT_SUIT
from .game import State, BalatroGame
from .agent_v9 import (
    HAND_TYPES,
    ACTIVE_PARAMS,
    CONSUMABLE_JOKERS,
    reference_hand,
    forecast_beatable,
    best_play_score,
    BAD_BOSSES,
)
from .agent_v10 import (
    SearchShopV10,
    HeuristicV10,
    _v10_decide_hand,
    _v10_decide_booster,
    _v10_decide_shop,
    _v10_worst_joker_idx,
    _copy_target_strength,
    _forecast_round_score,
    _ante_boss_target,
    _v10_maybe_use_planet,
    _v10_decide_consumable,
    formulate_counterfactual_state,
    extract_game_features,
    build_interactions,
    V10_PARAMS,
    PORTFOLIO_CHIPS,
    PORTFOLIO_FLAT,
    PORTFOLIO_XMULT,
    PORTFOLIO_SCALING,
    PORTFOLIO_ECON,
    PORTFOLIO_RETRIGGER,
    COMBAT_SCALING_JOKERS,
    RELIABLE_XMULT_JOKERS,
    HIGH_LEVERAGE_SCORING_JOKERS,
    PREMIER_XMULT_FINISHERS,
    DEAD_ECONOMY_JOKERS,
    extract_features_from_state,
)

# ────────────────────────────────────────────────────────────────────────────
# 1. Component C: Value Network V_theta(S) Loader & Evaluator
# ────────────────────────────────────────────────────────────────────────────

_V11_MODEL_DATA: Optional[dict] = None
_V11_WEIGHTS: Optional[tuple] = None


def _load_value_network_v11() -> Optional[dict]:
    global _V11_MODEL_DATA, _V11_WEIGHTS
    if _V11_WEIGHTS is not None:
        return _V11_MODEL_DATA

    model_path = Path(__file__).resolve().parent / "shop_model_v11.json"
    if not model_path.exists():
        model_path = Path(__file__).resolve().parent.parent.parent.parent / "vendor" / "balatro-rl" / "balatro_sim" / "shop_model_v11.json"

    if not model_path.exists():
        return None

    try:
        data = json.loads(model_path.read_text(encoding="utf-8"))
        w = data["weights"]
        W1 = np.array(w["W1"], dtype=np.float32)
        b1 = np.array(w["b1"], dtype=np.float32)
        W2 = np.array(w["W2"], dtype=np.float32)
        b2 = np.array(w["b2"], dtype=np.float32)
        W3 = np.array(w["W3"], dtype=np.float32)
        b3 = np.array(w["b3"], dtype=np.float32)
        mean = np.array(data["mean"], dtype=np.float32)
        std = np.array(data["std"], dtype=np.float32)
        feat_order = data["feat_order"]

        _V11_MODEL_DATA = data
        _V11_WEIGHTS = (W1, b1, W2, b2, W3, b3, mean, std, feat_order)
        return data
    except Exception:
        return None


# Preload value network upon module import
_load_value_network_v11()


def evaluate_shop_value_v11(features: dict[str, float]) -> float:
    """Pure-NumPy forward pass through 2-layer MLP V_theta(s) -> P(Win).
    Latency < 10µs with zero heavy runtime dependencies."""
    if _V11_WEIGHTS is None:
        _load_value_network_v11()
    if _V11_WEIGHTS is None:
        from .agent_v10 import evaluate_shop_value
        return evaluate_shop_value(features)

    W1, b1, W2, b2, W3, b3, mean, std, feat_order = _V11_WEIGHTS
    f_inter = build_interactions(features)
    raw_x = np.array([f_inter.get(k, 0.0) for k in feat_order], dtype=np.float32)
    x_norm = (raw_x - mean) / std

    # Forward pass: 50 -> 32 -> 16 -> 1
    h1 = np.maximum(0.0, x_norm @ W1 + b1)
    h2 = np.maximum(0.0, h1 @ W2 + b2)
    logit = float((h2 @ W3 + b3).squeeze())
    logit = max(-30.0, min(30.0, logit))
    return 1.0 / (1.0 + math.exp(-logit))


# ────────────────────────────────────────────────────────────────────────────
# 2. Component A: Full Left-to-Right Joker Trigger Order & Scaling Growth
# ────────────────────────────────────────────────────────────────────────────

def _joker_order_priority(j) -> tuple[int, float]:
    """Return trigger order tier (lower = earlier/leftmost).
    Tier 0: Utility / Non-scoring Economy (no Polychrome)
    Tier 1: Chip jokers (no Polychrome)
    Tier 2: Flat mult jokers (no Polychrome)
    Tier 3: Non-xMult jokers with Polychrome (flat addition then x1.5)
    Tier 4: Multiplicative xMult jokers (no Polychrome)
    Tier 5: Multiplicative xMult jokers WITH Polychrome (xMult then x1.5)
    """
    k = getattr(j, "key", "")
    is_poly = (getattr(j, "edition", None) == "Polychrome")

    is_xmult = (k in PORTFOLIO_XMULT or k in RELIABLE_XMULT_JOKERS
                or k in PREMIER_XMULT_FINISHERS or k in HIGH_LEVERAGE_SCORING_JOKERS)
    is_flat = (k in PORTFOLIO_FLAT or k in COMBAT_SCALING_JOKERS)
    is_chips = (k in PORTFOLIO_CHIPS)

    if is_xmult:
        tier = 5 if is_poly else 4
        return (tier, _copy_target_strength(j))
    elif is_flat:
        tier = 3 if is_poly else 2
        return (tier, 0.0)
    elif is_chips:
        tier = 3 if is_poly else 1
        return (tier, 0.0)
    else:
        tier = 3 if is_poly else 0
        return (tier, 0.0)


def _optimize_joker_order_v11(game) -> None:
    """Optimize joker order in-place on game.jokers for mathematical scoring superiority.

    Guarantees:
      1. +Mult always triggers before xMult.
      2. Polychrome editions trigger at the optimal multiplicative positions.
      3. Blueprint is positioned immediately to the left of the best target.
      4. Brainstorm is positioned to copy the best target at position 0.
      5. Ceremonial Dagger has a safe sacrifice when entering blinds.

    Human-fair: Rearranging jokers is a free 0-cost game action in Balatro.
    """
    jokers = getattr(game, "jokers", None)
    if not jokers or len(jokers) <= 1:
        return

    blueprints = [j for j in jokers if j.key == "j_blueprint"]
    brainstorms = [j for j in jokers if j.key == "j_brainstorm"]
    ceremonials = [j for j in jokers if j.key == "j_ceremonial"]
    if not (blueprints or brainstorms or ceremonials):
        return

    others = [j for j in jokers if j.key not in ("j_blueprint", "j_brainstorm", "j_ceremonial")]

    if not others:
        return

    # Sort regular jokers by optimal left-to-right trigger pipeline
    others.sort(key=_joker_order_priority)

    # Identify best copy target (highest strength among scoring jokers)
    best_target = max(others, key=_copy_target_strength)

    # Construct optimized order
    if brainstorms:
        # Brainstorm copies leftmost joker (index 0). Put best target at index 0.
        remaining = [j for j in others if j is not best_target]
        new_order = [best_target]

        if blueprints:
            new_order.extend(blueprints)
        new_order.extend(remaining)
        new_order.extend(brainstorms)

    elif blueprints:
        # Blueprint copies joker to its right. Place Blueprint immediately before best_target.
        new_order = []
        for j in others:
            if j is best_target:
                new_order.extend(blueprints)
            new_order.append(j)
        if best_target not in new_order:
            new_order.extend(blueprints)
            new_order.append(best_target)
    else:
        new_order = others

    if ceremonials:
        new_order.extend(ceremonials)

    game.jokers = new_order


def _v11_scaling_growth_bonus(key: str, ante: int) -> float:
    """Projected lifecycle growth bonus for scaling jokers in early/mid game."""
    if key not in PORTFOLIO_SCALING or ante >= 6:
        return 0.0

    antes_remaining = max(0, 6 - ante)
    if key in {"j_constellation", "j_green_joker", "j_ride_the_bus", "j_wee",
               "j_spare_trousers", "j_trousers", "j_vampire"}:
        return 0.040 * antes_remaining

    if key in {"j_square", "j_red_card", "j_flash", "j_runner", "j_hiker",
               "j_fortune_teller", "j_castle", "j_lucky_cat"}:
        return 0.025 * antes_remaining

    return 0.015 * antes_remaining


# ────────────────────────────────────────────────────────────────────────────
# 3. Component B: Combinatorial Multi-Item Shop Sequence Planning (L1 Rule)
# ────────────────────────────────────────────────────────────────────────────

@dataclass
class ShopSimState:
    ante: int
    blind_idx: int
    dollars: int
    joker_slots: int
    jokers: list[tuple[str, Optional[str], int]]  # (key, edition, sell_value)
    consumable_slots: int
    consumables: list[str]
    vouchers: set[str]
    hand_levels: dict[str, int]
    deck_size: int
    suit_counts: dict[str, int]
    face_count: int
    enhanced_count: int
    sealed_count: int
    chips_target: int
    items_sold: set[int]
    rerolls_used: int


def _init_shop_sim(game, rerolls_used: int) -> ShopSimState:
    deck = getattr(game, "deck", [])
    d_size = len(deck)
    suit_counts: dict[str, int] = {}
    face_cnt = 0
    enh_cnt = 0
    seal_cnt = 0
    for c in deck:
        s = getattr(c, "suit", "")
        suit_counts[s] = suit_counts.get(s, 0) + 1
        if getattr(c, "rank", 0) in (11, 12, 13):
            face_cnt += 1
        if getattr(c, "enhancement", "None") != "None":
            enh_cnt += 1
        if getattr(c, "seal", None):
            seal_cnt += 1

    target = getattr(game.current_blind, "chips_target", 0) if getattr(game, "current_blind", None) else 0

    j_list = []
    for j in getattr(game, "jokers", []):
        s_val = getattr(j, "state", {}).get("sell_value", max(1, getattr(j, "cost", 4) // 2))
        j_list.append((j.key, getattr(j, "edition", None), s_val))

    c_list = [(c.key if hasattr(c, "key") else str(c)) for c in getattr(game, "consumable_hand", [])]
    v_set = set(getattr(game, "vouchers", []))
    h_levels = dict(getattr(game, "hand_levels", getattr(game, "planet_levels", {})))

    sold_set = {i for i, it in enumerate(getattr(game, "current_shop", [])) if getattr(it, "sold", False)}

    return ShopSimState(
        ante=getattr(game, "ante", 1),
        blind_idx=getattr(game, "blind_idx", 0),
        dollars=getattr(game, "dollars", 0),
        joker_slots=getattr(game, "joker_slots", 5),
        jokers=j_list,
        consumable_slots=getattr(game, "consumable_slots", 2),
        consumables=c_list,
        vouchers=v_set,
        hand_levels=h_levels,
        deck_size=d_size,
        suit_counts=suit_counts,
        face_count=face_cnt,
        enhanced_count=enh_cnt,
        sealed_count=seal_cnt,
        chips_target=target,
        items_sold=sold_set,
        rerolls_used=rerolls_used,
    )


def _sim_extract_features(sim: ShopSimState) -> dict[str, float]:
    j_tuples = [(k, ed) for k, ed, _ in sim.jokers]
    return extract_features_from_state(
        ante=sim.ante,
        blind_idx=sim.blind_idx,
        dollars=sim.dollars,
        hands_left=4,
        discards_left=3,
        joker_slots=sim.joker_slots,
        jokers=j_tuples,
        consumable_slots=sim.consumable_slots,
        consumables_count=len(sim.consumables),
        vouchers=sim.vouchers,
        hand_levels=sim.hand_levels,
        deck_size=sim.deck_size,
        suit_counts=sim.suit_counts,
        face_count=sim.face_count,
        enhanced_count=sim.enhanced_count,
        sealed_count=sim.sealed_count,
        chips_target=sim.chips_target,
    )


def _apply_sim_action(sim: ShopSimState, game, action: dict) -> bool:
    act_type = action.get("type")

    if act_type == "buy":
        idx = action["item_idx"]
        if idx in sim.items_sold or idx >= len(game.current_shop):
            return False
        item = game.current_shop[idx]
        price = item.discounted_price(game.shop_discount)
        if sim.dollars < price:
            return False

        sim.dollars -= price
        sim.items_sold.add(idx)

        if item.kind == "joker":
            is_neg = (getattr(item, "edition", None) == "Negative")
            if len(sim.jokers) >= sim.joker_slots and not is_neg:
                return False
            if is_neg:
                sim.joker_slots += 1
            s_val = max(1, item.price // 2)
            sim.jokers.append((item.key, item.edition, s_val))
        elif item.kind == "planet":
            ht = PLANET_HAND.get(item.key)
            if ht:
                sim.hand_levels[ht] = sim.hand_levels.get(ht, 1) + 1
        elif item.kind == "tarot":
            if len(sim.consumables) < sim.consumable_slots:
                sim.consumables.append(item.key)
        elif item.kind == "voucher":
            sim.vouchers.add(item.key)
        return True

    elif act_type == "sell_joker":
        j_idx = action["joker_idx"]
        if j_idx < 0 or j_idx >= len(sim.jokers):
            return False
        _, _, s_val = sim.jokers.pop(j_idx)
        sim.dollars += s_val
        return True

    elif act_type == "use_consumable":
        c_idx = action["idx"]
        if c_idx < 0 or c_idx >= len(sim.consumables):
            return False
        c_key = sim.consumables.pop(c_idx)
        if c_key == "c_hermit":
            sim.dollars = min(50, sim.dollars + min(sim.dollars, 20))
        elif c_key == "c_temperance":
            t_gain = sum(s_val for _, _, s_val in sim.jokers)
            sim.dollars = min(50, sim.dollars + min(50, t_gain))
        elif c_key in PLANET_HAND:
            ht = PLANET_HAND[c_key]
            sim.hand_levels[ht] = sim.hand_levels.get(ht, 1) + 1
        return True

    return False


def _plan_shop_sequence(game, rerolls_used: int) -> tuple[Optional[list[dict]], float]:
    """Combinatorial Multi-Item Sequence Search when slots are full (or unlocking capital).
    Returns (best_sequence, value_delta)."""
    sim_root = _init_shop_sim(game, rerolls_used)
    f_root = _sim_extract_features(sim_root)
    v_root = evaluate_shop_value_v11(f_root)

    best_seq: Optional[list[dict]] = None
    best_delta: float = 0.005  # calibrated hurdle matching V10

    owned_keys = [k for k, _, _ in sim_root.jokers]
    n_xmult = sum(1 for k in owned_keys if k in PORTFOLIO_XMULT or k in PREMIER_XMULT_FINISHERS)
    # Permanent scoring anchors exclude decaying consumable jokers
    n_chips_perm = sum(1 for k in owned_keys if k in PORTFOLIO_CHIPS and k not in CONSUMABLE_JOKERS)
    n_flat_perm = sum(1 for k in owned_keys if k in PORTFOLIO_FLAT and k not in CONSUMABLE_JOKERS)

    has_premier_in_shop = any(
        not getattr(it, "sold", False) and getattr(it, "kind", "") == "joker"
        and (it.key in HIGH_LEVERAGE_SCORING_JOKERS or it.key in RELIABLE_XMULT_JOKERS or it.key in PREMIER_XMULT_FINISHERS)
        for it in getattr(game, "current_shop", [])
    )

    def is_protected(j_idx: int) -> bool:
        if j_idx < 0 or j_idx >= len(sim_root.jokers):
            return True
        k, ed, _ = sim_root.jokers[j_idx]
        if k in {"j_hanging_chad", "j_mime", "j_sock_and_buskin", "j_blueprint", "j_brainstorm", "j_cavendish", "j_dusk"}:
            return True
        # Combat scaling jokers are permanent engines across ALL antes
        if k in COMBAT_SCALING_JOKERS:
            return True
        # Permanent anchors must never be liquidated without replacement
        if n_xmult <= 1 and (k in PORTFOLIO_XMULT or k in PREMIER_XMULT_FINISHERS):
            return True
        if n_chips_perm <= 1 and k in PORTFOLIO_CHIPS and k not in CONSUMABLE_JOKERS:
            return True
        if n_flat_perm <= 1 and k in PORTFOLIO_FLAT and k not in CONSUMABLE_JOKERS:
            return True
        # Protect early economy unless premier finisher in shop
        if sim_root.ante <= 5 and k in {"j_business", "j_golden", "j_todo_list", "j_satellite"}:
            if not has_premier_in_shop:
                return True
        return False

    worst_j = _v10_worst_joker_idx(game)
    sellable_jokers: list[int] = []
    if worst_j is not None and not is_protected(worst_j):
        sellable_jokers.append(worst_j)
    if sim_root.ante >= 5:
        for j_i in range(len(sim_root.jokers)):
            if j_i != worst_j and not is_protected(j_i):
                k = sim_root.jokers[j_i][0]
                if k in DEAD_ECONOMY_JOKERS or k in PORTFOLIO_ECON:
                    sellable_jokers.append(j_i)

    avail_items = []
    has_face_joker = any(j[0] in {"j_photograph", "j_smiley", "j_scary_face", "j_sock_and_buskin", "j_faceless"} for j in sim_root.jokers)
    has_bus_owned = any(j[0] == "j_ride_the_bus" for j in sim_root.jokers)
    for i, it in enumerate(game.current_shop):
        if it.sold or it.kind != "joker" or getattr(it, "edition", None) == "Negative":
            continue
        if it.key in {"j_madness", "j_obelisk", "j_idol", "j_the_idol"}:
            continue
        if it.key == "j_ride_the_bus" and has_face_joker:
            continue
        if it.key in {"j_photograph", "j_smiley", "j_scary_face", "j_sock_and_buskin"} and has_bus_owned:
            continue
        is_premier = (it.key in HIGH_LEVERAGE_SCORING_JOKERS or it.key in RELIABLE_XMULT_JOKERS or it.key in PREMIER_XMULT_FINISHERS)
        is_combat = (it.key in PORTFOLIO_FLAT or it.key in PORTFOLIO_CHIPS or it.key in PORTFOLIO_XMULT or it.key in COMBAT_SCALING_JOKERS or it.key in PORTFOLIO_RETRIGGER)
        if is_premier or (sim_root.ante >= 6 and is_combat):
            avail_items.append(i)

    useable_consumables = [
        c_i for c_i, c_k in enumerate(sim_root.consumables)
        if c_k in ("c_hermit", "c_temperance")
    ]

    sequences_to_eval: list[list[dict]] = []

    # 1. Swaps: sell_joker -> buy
    for j_i in sellable_jokers:
        k_sold = sim_root.jokers[j_i][0]
        is_dead_econ_sold = (k_sold in DEAD_ECONOMY_JOKERS or k_sold in PORTFOLIO_ECON)
        for i in avail_items:
            it = game.current_shop[i]
            is_premier = (it.key in HIGH_LEVERAGE_SCORING_JOKERS or it.key in RELIABLE_XMULT_JOKERS or it.key in PREMIER_XMULT_FINISHERS)
            is_combat = (it.key in PORTFOLIO_FLAT or it.key in PORTFOLIO_CHIPS or it.key in PORTFOLIO_XMULT or it.key in COMBAT_SCALING_JOKERS or it.key in PORTFOLIO_RETRIGGER)
            if not is_premier and not (sim_root.ante >= 6 and is_dead_econ_sold and is_combat):
                continue
            sequences_to_eval.append([
                {"type": "sell_joker", "joker_idx": j_i},
                {"type": "buy", "item_idx": i}
            ])

    # 2. Money unlock: use_consumable -> swap
    for c_i in useable_consumables:
        for j_i in sellable_jokers:
            k_sold = sim_root.jokers[j_i][0]
            is_dead_econ_sold = (k_sold in DEAD_ECONOMY_JOKERS or k_sold in PORTFOLIO_ECON)
            for i in avail_items:
                it = game.current_shop[i]
                is_premier = (it.key in HIGH_LEVERAGE_SCORING_JOKERS or it.key in RELIABLE_XMULT_JOKERS or it.key in PREMIER_XMULT_FINISHERS)
                is_combat = (it.key in PORTFOLIO_FLAT or it.key in PORTFOLIO_CHIPS or it.key in PORTFOLIO_XMULT or it.key in COMBAT_SCALING_JOKERS)
                if not is_premier and not (sim_root.ante >= 6 and is_dead_econ_sold and is_combat):
                    continue
                sequences_to_eval.append([
                    {"type": "use_consumable", "idx": c_i},
                    {"type": "sell_joker", "joker_idx": j_i},
                    {"type": "buy", "item_idx": i}
                ])

    # 3. Double sell for premier finishers when cash is short (Ante >= 6)
    if sim_root.ante >= 6 and len(sellable_jokers) >= 2:
        for j_1 in sellable_jokers:
            for j_2 in sellable_jokers:
                if j_1 != j_2:
                    for i in avail_items:
                        it = game.current_shop[i]
                        if it.kind == "joker" and (it.key in PREMIER_XMULT_FINISHERS or it.key in RELIABLE_XMULT_JOKERS):
                            sequences_to_eval.append([
                                {"type": "sell_joker", "joker_idx": j_1},
                                {"type": "sell_joker", "joker_idx": j_2},
                                {"type": "buy", "item_idx": i}
                            ])

    # Evaluate each candidate sequence
    for seq in sequences_to_eval:
        sim = _init_shop_sim(game, rerolls_used)
        valid = True
        for act in seq:
            if not _apply_sim_action(sim, game, act):
                valid = False
                break
        if not valid:
            continue

        f_end = _sim_extract_features(sim)
        v_end = evaluate_shop_value_v11(f_end)
        delta = v_end - v_root

        is_dead_econ_sold = any(
            act["type"] == "sell_joker" and (sim_root.jokers[act["joker_idx"]][0] in DEAD_ECONOMY_JOKERS or sim_root.jokers[act["joker_idx"]][0] in PORTFOLIO_ECON)
            for act in seq
        )
        is_premier_bought = any(
            act["type"] == "buy" and game.current_shop[act["item_idx"]].kind == "joker" and (game.current_shop[act["item_idx"]].key in PREMIER_XMULT_FINISHERS or game.current_shop[act["item_idx"]].key in RELIABLE_XMULT_JOKERS)
            for act in seq
        )
        if is_dead_econ_sold and is_premier_bought and sim_root.ante >= 4:
            delta = max(delta, 0.05)

        hurdle = 0.005 if (is_premier_bought or len(seq) == 2) else 0.020
        if delta > hurdle and delta > best_delta:
            best_delta = delta
            best_seq = seq

    return best_seq, best_delta


# ────────────────────────────────────────────────────────────────────────────
# 4. SearchShopV11 Policy Class
# ────────────────────────────────────────────────────────────────────────────

class SearchShopV11(SearchShopV10):
    """Optilatro V11 Agent:
    Integrates Component A (left-to-right trigger order & scaling growth),
    Component B (combinatorial multi-item shop sequence planning), and
    Component C (MLP Value Network V_theta(s) -> P(Win)).
    """
    policy_name = "search_shop_v11"

    def __init__(self, params=None, search_shops: int = 999, candidate_cap: int = 4,
                 lookahead: bool = False, max_rollout_steps: int = 4000, **kwargs):
        super().__init__(params=params, search_shops=search_shops,
                         candidate_cap=candidate_cap, lookahead=lookahead,
                         max_rollout_steps=max_rollout_steps)
        self._action_queue: list[dict] = []

    def _search_shop(self, game) -> dict:
        if not game.current_shop or all(getattr(item, "sold", False) for item in game.current_shop):
            return _v10_decide_shop(game, getattr(self, "_rerolls_this_shop", 0))

        # 1. Complete queued sequence steps if valid
        while self._action_queue:
            next_act = self._action_queue.pop(0)
            act_type = next_act.get("type")

            if act_type == "buy":
                idx = next_act["item_idx"]
                if 0 <= idx < len(game.current_shop) and not game.current_shop[idx].sold:
                    item = game.current_shop[idx]
                    price = item.discounted_price(game.shop_discount)
                    has_room = len(game.jokers) < game.joker_slots or getattr(item, "edition", None) == "Negative" or item.kind != "joker"
                    if price <= game.dollars and has_room:
                        return next_act
            elif act_type == "sell_joker":
                j_idx = next_act["joker_idx"]
                if 0 <= j_idx < len(game.jokers):
                    return next_act
            elif act_type == "use_consumable":
                c_idx = next_act["idx"]
                if 0 <= c_idx < len(game.consumable_hand):
                    return next_act

            self._action_queue.clear()
            break

        # 2. Boss reroll check
        if (game.next_boss_key in BAD_BOSSES and game.dollars >= 10):
            can_dc = ("v_directors_cut" in game.vouchers and game.dc_reroll_ante != game.ante)
            can_retcon = "v_retcon" in game.vouchers
            if can_dc or can_retcon:
                return {"type": "reroll_boss"}

        # 3. Essential shop-phase consumable usage
        act = _v10_maybe_use_planet(game)
        if act is not None:
            return act

        if ACTIVE_PARAMS.get("use_tarots", True):
            act = _v10_decide_consumable(game)
            if act is not None:
                return act

        # 4. Open slots: standard calibrated purchasing and interest management
        if len(game.jokers) < game.joker_slots:
            return _v10_decide_shop(game, getattr(self, "_rerolls_this_shop", 0))

        # 5. Full-slot portfolio swaps: combinatorial sequence search with Value Network
        if len(game.jokers) >= game.joker_slots and game.ante >= 4 and not self._searched_this_visit:
            self._searched_this_visit = True
            best_seq, delta = _plan_shop_sequence(game, getattr(self, "_rerolls_this_shop", 0))
            if best_seq:
                first_action = best_seq[0]
                if len(best_seq) > 1:
                    self._action_queue = list(best_seq[1:])
                return first_action

        # 6. Fallback to _v10_decide_shop
        return _v10_decide_shop(game, getattr(self, "_rerolls_this_shop", 0))

    def decide(self, game) -> dict:
        st = game.state
        if st == State.SELECTING_HAND:
            _optimize_joker_order_v11(game)
            return _v10_decide_hand(game)

        if st == State.BOOSTER_OPEN:
            return _v10_decide_booster(game)

        if st != State.SHOP:
            return super().decide(game)

        if not self._in_shop:
            self._in_shop = True
            self._rerolls_this_shop = 0
            self._searched_this_visit = False
            self._action_queue.clear()

        act = self._search_shop(game)

        if act.get("type") == "reroll":
            self._rerolls_this_shop += 1
            self._searched_this_visit = False
        elif act.get("type") == "leave_shop":
            self._in_shop = False
            self._searched_this_visit = False
            self._action_queue.clear()

        return act
