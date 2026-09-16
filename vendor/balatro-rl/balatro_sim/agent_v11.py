"""balatro_sim/agent_v11.py — Optilatro V11 Unified Architecture.

Combines:
  1. Component A: Left-to-right copy joker & ceremonial positioning (R4 restricted)
     and early-game scaling joker growth potential valuation (R1).
  2. Component B: Combinatorial Multi-Item Shop Sequence Planning (L1 Decision Rule)
     evaluating sequential shop paths (sell -> buy, use -> buy, multi-buys)
     when transitioning builds or unlocking capital.
  3. Component C: Learned Global Full-Run Win Rate Value Network V_theta(S) -> P(Win)
     (2-layer MLP with 50 features and interaction terms, AUC 0.872+).
  4. Component D: Universal Value Network shop scoring (_rank_shop_items_v11) for all
     candidate items across open slots and full-slot swaps (R1).
  5. Component E: Mid-game deficit capital deployment eliminating the interest-hoarding
     death trap in Antes 2–5 with targeted anchor fishing (R3).
  6. Component F: High-capital economy scaling and in-blind value squeezing (R2)
     for Business Card, Reserved Parking, Lucky Card synergies, and Mail-In Rebate.

Preserves 100% human-fairness (no draw peeking, isolated evals, zero RNG consumption)
and maintains complete backward compatibility with SearchShopV10.
"""
from __future__ import annotations

import json
import math
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Sequence

import numpy as np

from .card import Card
from .consumables import PLANET_HAND, TAROT_SUIT
from .game import State, BalatroGame
from .hand_eval import evaluate_hand
from .agent_v9 import (
    HAND_TYPES,
    ACTIVE_PARAMS,
    CONSUMABLE_JOKERS,
    reference_hand,
    forecast_beatable,
    best_play_score,
    BAD_BOSSES,
    joker_value,
    pack_value,
    worth_spending,
    _KIND_RANK,
    _boss_play_filter,
    scored_plays,
    eval_hand_score,
    best_discard,
    _card_quality,
    VOUCHER_PRIORITY,
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
    EARLY_FLAT_CHIPS_JOKERS,
    extract_features_from_state,
    _boss_key,
    _compute_type_scores,
    estimate_clear_probability,
    play_trigger_value,
    expected_round_end_value,
    _mail_target_rank,
    _v10_tarot_value,
    _v10_pack_card_value,
    _v10_rank_shop_items,
    _v10_spectral_value,
    _has_scoring_joker,
    portfolio_target_hand,
    main_hand_type,
    _joker_sell_value,
    ALL_TAROTS,
    ALL_SPECTRALS,
)

# ────────────────────────────────────────────────────────────────────────────
# V11 experiment flags. Defaults reproduce the shipped V11 behaviour; the
# ablation harness (bench/bench_v11_ablation.py) flips them via
# SearchShopV11(params={...}) so each new component can be measured in
# isolation against the frozen V10 baseline.
# ────────────────────────────────────────────────────────────────────────────
# ────────────────────────────────────────────────────────────────────────────
# MEASURED DEFAULTS (seed bank 10500-10799, strict human-fair).
#
# The D-F component set below (universal value-net shop ranking, in-blind value
# squeezing, trap filters, booster rules, xMult conversion) was shipped ON and
# scored 33/300 (11.0%) where the committed V11 artifact scored 42/300 (14.0%).
# It replaced the proven V10 L1 counterfactual shop search. Those components are
# therefore DORMANT: kept in the tree behind flags, default OFF, so they stay
# measurable without costing win rate. The defaults below reproduce the frozen
# V10-equivalent behaviour, which is the verified floor this file must not drop
# below (l1_parity = 12/100 on seeds 10500-10599, exactly V10).
# ────────────────────────────────────────────────────────────────────────────
V11_PARAMS: dict[str, Any] = {
    # Value-network delta multiplier in shop ranking; 0.0 disables the VN term.
    "v11_vn_weight": 0.0,
    # Use the pure V10 shop ranking (bypasses every V11 ranking change).
    "v11_shop_v10_rank": False,
    # Bypass the V11 shop decision loop entirely (delegate to _v10_decide_shop).
    "v11_shop_v10_full": False,
    # Bypass the V11 shop loop in favour of the frozen V10 L1 counterfactual
    # search (`SearchShopV10._search_shop`), keeping only the V11 hooks on top.
    # ON: this is the proven +21-win search component (V9 3.67% -> 10.67% ->
    # 14.0%). The D-F rewrite that replaced it is the measured regression.
    "v11_shop_v10_l1": True,
    # Combinatorial multi-item sell/buy sequence planning when slots are full.
    "v11_seq_plan": False,
    # In-blind value squeezing (Business/Parking/Lucky/Mail harvesting).
    "v11_squeeze": False,
    # Scaling-joker lifecycle growth bonus multiplier (R1). Consumed only by
    # `_rank_shop_items_v11` (1117) and the active branch of `_v11_decide_booster`
    # (1347); both are dormant below, so this value cannot move the win rate of
    # the shipped configuration. Left at the helper's calibrated 1.0 so the
    # helper keeps its documented ante-declining shape
    # (tests/test_agent_v11.py::test_scaling_bonus_declines_with_ante).
    "v11_growth": 1.0,
    # Trap / hand-specific / anti-synergy purchase filters.
    "v11_filters": False,
    # NOTE: the flag values above are the MEASURED-VALIDATED shipped set. They
    # must stay equal to the `l1_parity` / `shipped` arms of
    # bench/bench_v11_ablation.py, which reproduce frozen V10 with zero flips
    # (12/100, gained 0 / lost 0) and 41/300 on the full bank.
    # V11 booster-pack decision rule (tarot priorities, zero-waste celestial).
    "v11_boosters": False,
    # Flat value added to Celestial/Arcana/Buffoon packs in shop ranking.
    "v11_pack_bonus": False,
    # Limit full-portfolio swaps to one per shop visit.
    "v11_swap_limit": False,
    # --- Component G: mid-game interest-floor reduction (DORMANT, rejected) --
    # A 100-seed screen made $15 look like +2 wins (12 -> 14, 6 gained / 4
    # lost). Decisive n=300 on the same bank REJECTED it: 35/300 (11.67%)
    # against frozen V10's 42/300, gained 11 / lost 18 = -7. The 100-seed
    # response was non-monotonic (int 20 -> 11, 15 -> 14, 12 -> 9), which is
    # what noise looks like at n=100 with ~12 wins. Keep dormant. The override
    # is applied to the shared ACTIVE_PARAMS only for the duration of V11's own
    # shop call, so agent_v10.py stays byte-identical for the frozen baseline.
    "v11_interest_target": None,
    "v11_save_strong_value": None,
    # --- Component I: open-slot counterfactual search (candidate) -----------
    # SearchShopV10._search_shop runs its human-fair delta-V search ONLY when
    # joker slots are full and ante >= 4. Open slots fall straight through to
    # the pure heuristic with no search at all, which is the last unexplored
    # human-fair search dimension (every historical gain came from search:
    # V9 3.67% -> search_shop_v10 10.67% -> V11 14.0%). Purely additive: the
    # search only overrides a `leave_shop`/`reroll` answer from the calibrated
    # loop, so it can add missed buys but never displace V10's own decisions.
    "v11_open_slot_search": False,
    "v11_open_slot_threshold": 0.02,
    # --- Component J: rollout-fitted buy model (candidate) ------------------
    # `evaluate_shop_value` is a STATE value model: adding one joker to an
    # open slot barely moves its 50-feature vector, so its delta-V cannot
    # rank open-slot candidates (measured in docs/v11_forensics: the
    # open-slot search was inert because the legacy delta never cleared
    # 0.10). `buy_model.py` instead scores the CANDIDATE conditioned on
    # context, fitted on counterfactual fork-and-rollout outcomes
    # (tools/collect_shop_rollouts.py: one fork buys the joker, one skips
    # it; the win-outcome difference is the label). When this flag is on,
    # `_v11_open_slot_search` ranks candidates with the fitted P(win)
    # instead of the inert legacy delta. Human-fair: features are
    # observable-state only; rollouts happen offline at training time.
    "v11_buy_model": False,
    # Calibrated P(win-flip) has a ~3-6% base rate, so the operating point is
    # set from the holdout threshold sweep in tools/fit_buy_model.py, NOT at
    # a naive 0.5. Placeholder until the fit lands.
    "v11_buy_model_threshold": 0.10,
    # Upper bound on owned xMult jokers before conversion stops firing.
    "v11_xmult_convert_max": 3,
    # Apply the xMult conversion as a pre-step on top of the active shop loop.
    "v11_xmult_convert_hook": False,
    # Ante from which the agent deliberately converts stale +mult/chips/scaling
    # jokers into xMult finishers (0 = off). Human-optimal play treats xMult as
    # mandatory for the Ante 7-8 boss; V10/V11 reach the final boss ~0.4 xMult
    # jokers short and die there.
    "v11_xmult_convert_ante": 0,
    # Allow more than one full-portfolio swap per shop visit from that ante on.
    "v11_convert_multi_swap": False,
    # Let a joker in an OPEN slot bypass save-mode / worth_spending gating
    # (V10 does this from Ante 3 on). Without it V11 buys far fewer jokers
    # than V10 (7.0 vs 11.2 per run) and enters late antes underpaced.
    "v11_open_joker_exempt": False,
    # --- Component G: blind-honest desperation deployment -------------------
    # Root cause (seed-trace 10510/10501/10511): the urgency model compares an
    # optimistic board forecast against BOSS x2 and only trims the interest
    # target to $15/$10 in Antes 2-5, so the agent banks ~$13 and rerolls at
    # most twice while its board cannot beat the *next* blind (3,000 chips at
    # Ante-3 Big vs ~1,300 forecast). It then dies holding the cash.
    # When the forecast cannot beat the upcoming blind (public information),
    # stop banking interest and convert cash into board power instead.
    "v11_desperate": False,
    # Fire when forecast_round_score < next_blind_target * margin.
    "v11_desperate_margin": 1.0,
    # Hard per-shop reroll cap while desperate (V10's cap is 2).
    "v11_desperate_rerolls": 8,
    # Minimum shop item value worth buying in desperation.
    "v11_desperate_buy_floor": 0.05,
    # --- Component H: in-blind salvage (never farm an unclearable blind) ----
    # V10/V11 spend discards on single-card value farming while the blind is
    # not clearable (10510 burned all 4 discards on 5D/AD/QH/QS, then played
    # Two Pair for 112 against 3,000). When the best hand x hands_left cannot
    # reach the target, play the best hand and spend discards only on digging.
    "v11_salvage": False,
}


@contextmanager
def _v11_shop_overrides():
    """Temporarily apply V11's mid-game economic policy to the shared
    ACTIVE_PARAMS dict for the duration of V11's own shop path.

    agent_v10.py is frozen and reads ACTIVE_PARAMS directly, so an explicit
    local override is the only way to give V11 a different (measured-better)
    interest floor without editing the baseline. Always restored, including on
    exception; the process is single-threaded per run.
    """
    saved: dict[str, Any] = {}
    it = V11_PARAMS.get("v11_interest_target")
    if it is not None and ACTIVE_PARAMS.get("interest_target") != it:
        saved["interest_target"] = ACTIVE_PARAMS.get("interest_target")
        ACTIVE_PARAMS["interest_target"] = it
    sv = V11_PARAMS.get("v11_save_strong_value")
    if sv is not None and ACTIVE_PARAMS.get("save_strong_value") != sv:
        saved["save_strong_value"] = ACTIVE_PARAMS.get("save_strong_value")
        ACTIVE_PARAMS["save_strong_value"] = sv
    try:
        yield
    finally:
        for k, v in saved.items():
            ACTIVE_PARAMS[k] = v


def _v11_next_blind_target(game) -> float:
    """Chips required by the *upcoming* blind.

    At SHOP time ``game.blind_idx`` already points at the next blind (verified
    for Antes 1-3), so this is public information the human player also has on
    screen before spending a single dollar.
    """
    try:
        idx = int(game.blind_idx)
    except Exception:
        return 0.0
    if idx >= 2:
        return float(_ante_boss_target(game))
    from .agent_v9 import BLIND_CHIPS
    row = BLIND_CHIPS.get(game.ante)
    if not row or idx < 0 or idx >= len(row):
        return 0.0
    return float(row[idx])


def _v11_desperation_active(game) -> bool:
    """True when the board cannot beat the next blind and cash must be spent."""
    if not V11_PARAMS.get("v11_desperate", False):
        return False
    # Never disturb V10's conservative Ante-1 opening (R4 invariant).
    if game.ante < 2:
        return False
    target = _v11_next_blind_target(game)
    if target <= 0.0:
        return False
    margin = float(V11_PARAMS.get("v11_desperate_margin", 1.0) or 1.0)
    return _forecast_round_score(game) < target * margin


def _v11_desperate_shop_action(game, rerolls_used: int) -> Optional[dict]:
    """Convert idle cash into immediate board power when the next blind is at
    risk: buy the best affordable item ignoring save-mode/interest gating, then
    reroll hard. Returns None when not desperate or nothing can be done."""
    if not _v11_desperation_active(game):
        return None

    ref = reference_hand(game)
    surplus = forecast_beatable(game, ACTIVE_PARAMS["tilt_surplus_margin"], ref)
    buys, _need_sell = _v10_rank_shop_items(game, ref, surplus,
                                           rerolls_used=rerolls_used)

    floor = float(V11_PARAMS.get("v11_desperate_buy_floor", 0.05) or 0.0)
    open_slots = len(game.jokers) < game.joker_slots
    rooms = len(game.consumable_hand) < game.consumable_slots
    for value, idx in sorted(buys, key=lambda b: b[0], reverse=True):
        if value < floor:
            continue
        if not (0 <= idx < len(game.current_shop)):
            continue
        item = game.current_shop[idx]
        if getattr(item, "sold", False):
            continue
        if item.discounted_price(game.shop_discount) > game.dollars:
            continue
        if item.kind == "joker":
            if not open_slots and getattr(item, "edition", None) != "Negative":
                continue  # full slots; V10's sell path owns swaps
        elif not rooms:
            continue
        return {"type": "buy", "item_idx": idx}

    # Nothing worth buying: reroll hard while cash allows (bounded per shop).
    reroll_cost = max(0, game.reroll_cost - game.reroll_discount)
    hard_cap = int(V11_PARAMS.get("v11_desperate_rerolls", 8) or 0)
    if game.dollars >= reroll_cost and rerolls_used < hard_cap:
        return {"type": "reroll"}
    return None


def _v11_open_slot_search(game) -> Optional[dict]:
    """Human-fair counterfactual ΔV search over OPEN joker slots.

    `SearchShopV10._search_shop` searches only when joker slots are full and
    ante >= 4; with an open slot it delegates straight to the heuristic
    `_v10_decide_shop`. This evaluates V(s') for every affordable shop joker via
    the same `formulate_counterfactual_state` / `evaluate_shop_value` machinery
    the proven full-slot swap search uses, and buys when ΔV clears a decisive
    hurdle. Pure function evaluation over observable state: no RNG, no draw
    peeking, so it stays human-fair and seed-exact.
    """
    if not V11_PARAMS.get("v11_open_slot_search", False):
        return None
    if len(game.jokers) >= game.joker_slots:
        return None
    if not getattr(game, "current_shop", None):
        return None

    # Component J: the rollout-fitted candidate model, when available.
    # Ranks by fitted P(candidate contributes to a won run) instead of the
    # legacy state-value delta (which is inert on open slots).
    if V11_PARAMS.get("v11_buy_model", False):
        from . import buy_model as _bm
        meta, weighted = _bm.load_buy_model()
        if weighted[0] is not None:
            from .agent_v9 import reference_hand
            ref = reference_hand(game)
            thr = float(V11_PARAMS.get("v11_buy_model_threshold", 0.55) or 0.55)
            best_p: Optional[float] = None
            best_idx: Optional[int] = None
            for i, item in enumerate(game.current_shop):
                if getattr(item, "sold", False) or getattr(item, "kind", "") != "joker":
                    continue
                if item.key in {"j_madness", "j_obelisk", "j_idol", "j_the_idol"}:
                    continue
                price = item.discounted_price(game.shop_discount)
                if price > game.dollars:
                    continue
                p = _bm.buy_value(game, item, price, ref=ref, weighted=weighted)
                if p is not None and (best_p is None or p > best_p):
                    best_p, best_idx = p, i
            if best_idx is not None and best_p is not None and best_p > thr:
                return {"type": "buy", "item_idx": best_idx}
            return None

    # Legacy path (Component I): state-value delta via the same evaluator the
    # proven full-slot swap search uses (agent_v10).
    from .agent_v10 import evaluate_shop_value

    v_curr = evaluate_shop_value(extract_game_features(game))
    thr = float(V11_PARAMS.get("v11_open_slot_threshold", 0.02) or 0.02)
    best_delta: Optional[float] = None
    best_idx: Optional[int] = None
    for i, item in enumerate(game.current_shop):
        if getattr(item, "sold", False) or getattr(item, "kind", "") != "joker":
            continue
        # Same trap set the full-slot swap search refuses.
        if item.key in {"j_madness", "j_obelisk", "j_idol", "j_the_idol"}:
            continue
        price = item.discounted_price(game.shop_discount)
        if price > game.dollars:
            continue
        delta = (evaluate_shop_value(formulate_counterfactual_state(
            game, {"type": "buy", "item_idx": i})) - v_curr)
        if best_delta is None or delta > best_delta:
            best_delta, best_idx = delta, i
    if best_idx is not None and best_delta is not None and best_delta > thr:
        return {"type": "buy", "item_idx": best_idx}
    return None


def _v11_salvage_action(game) -> Optional[dict]:
    """In-blind survival: never farm values on a blind that is not clearable.

    Only fires when ``best_hand * hands_left < target`` (the blind cannot be
    beaten by playing the best available hand every hand). In that state the
    policy plays the best hand and spends discards purely on digging for a
    better one, instead of burning them on single-card value farming.
    """
    if not V11_PARAMS.get("v11_salvage", False):
        return None
    if game.ante < 2:
        return None  # R4: Ante 1 keeps V10's calibrated play exactly
    target = game.current_blind.chips_target - game.chips_scored
    if target <= 0:
        return None
    plays = scored_plays(game, topk=ACTIVE_PARAMS["eval_topk_play"])
    if not plays:
        return None
    best = plays[0]
    if best[0] * max(1, game.hands_left) >= target:
        return None  # clearable by playing best hands: let the policy decide
    if game.discards_left <= 0 or len(game.hand) <= 5:
        return {"type": "play", "cards": list(best[1])}
    keep = set(best[1])
    junk = [i for i in range(len(game.hand)) if i not in keep]
    if not junk:
        return {"type": "play", "cards": list(best[1])}
    return {"type": "discard",
            "cards": junk[:ACTIVE_PARAMS["discard_max_size"]]}

# Jokers a late-game conversion must never sell: xMult engines and retriggers
# multiply every other effect, so they are the destination, not the fuel.
LATE_CONVERT_KEEP = (
    PORTFOLIO_XMULT | RELIABLE_XMULT_JOKERS | PREMIER_XMULT_FINISHERS
    | HIGH_LEVERAGE_SCORING_JOKERS
    | {"j_hanging_chad", "j_mime", "j_dusk", "j_sock_and_buskin", "j_cavendish"}
)


def _v11_count_xmult(game) -> int:
    n = 0
    for j in getattr(game, "jokers", []):
        if (j.key in PORTFOLIO_XMULT or j.key in RELIABLE_XMULT_JOKERS
                or j.key in PREMIER_XMULT_FINISHERS
                or j.key in HIGH_LEVERAGE_SCORING_JOKERS):
            n += 1
    return n


def _v11_xmult_conversion_step(game) -> Optional[dict]:
    """Late-game xMult conversion, usable on top of ANY shop loop.

    Human-optimal play treats xMult as mandatory for the Ante 7-8 boss: every
    build is expected to trade its stale +chips/+mult/scaling jokers for one or
    more multiplicative finishers. Measured on seeds 10500-10799, runs that
    reach the Ante 8 boss hold 2.07 xMult jokers on this agent vs 2.46 for the
    V10 baseline, and the closing rate collapses from 78% to 58%.

    Returns a `sell_joker` action carrying `_v11_buy_after` (the shop index to
    buy next) when selling a stale joker unlocks an affordable relied-upon
    xMult finisher; otherwise None (the normal shop loop decides).
    """
    ca = int(V11_PARAMS.get("v11_xmult_convert_ante", 0) or 0)
    if ca <= 0 or game.ante < ca:
        return None
    if len(game.jokers) < game.joker_slots:
        return None  # an open slot: ordinary buying already covers it
    if _v11_count_xmult(game) >= int(V11_PARAMS.get("v11_xmult_convert_max", 3) or 3):
        return None

    wanted = (PREMIER_XMULT_FINISHERS | RELIABLE_XMULT_JOKERS
              | HIGH_LEVERAGE_SCORING_JOKERS)
    ref = reference_hand(game)
    sells = _v11_late_sell_order(game, ref)
    if not sells:
        return None

    best = None  # (candidate_value, sell_idx, buy_idx)
    for i, item in enumerate(game.current_shop):
        if getattr(item, "sold", False) or item.kind != "joker":
            continue
        if getattr(item, "edition", None) == "Negative":
            continue  # negative fits without a sale
        if item.key not in wanted:
            continue
        if any(j.key == item.key for j in game.jokers):
            continue
        price = item.discounted_price(game.shop_discount)
        try:
            cand_val = joker_value(game, item.key, item.edition, ref)
        except Exception:
            cand_val = 0.0
        for wc in sells:
            sv = _joker_sell_value(game.jokers[wc])
            if price > game.dollars + sv:
                continue
            if best is None or cand_val > best[0]:
                best = (cand_val, wc, i)
            break  # sells is worst-first: this is the cheapest way to afford it

    if best is None:
        return None
    _, sell_idx, buy_idx = best
    return {"type": "sell_joker", "joker_idx": sell_idx, "_v11_buy_after": buy_idx}


def _v11_late_sell_order(game, ref) -> list[int]:
    """Indices of jokers we would sell to upgrade, worst-first.

    Used for late-game xMult conversion: unlike `_v10_worst_joker_idx`, this
    considers every non-xMult joker, so a stale scaling or flat +mult joker
    can be moved even when it is not the single worst card in the portfolio.
    """
    scored = []
    for i, j in enumerate(getattr(game, "jokers", [])):
        if j.key in LATE_CONVERT_KEEP:
            continue
        try:
            v = joker_value(game, j.key, getattr(j, "edition", None), ref)
        except Exception:
            v = 0.0
        scored.append((v, i))
    scored.sort(key=lambda t: t[0])
    return [i for _, i in scored]


HAND_SPECIFIC_JOKERS = {
    # Xmult
    "j_duo": {"Pair"},
    "j_trio": {"Three of a Kind"},
    "j_family": {"Four of a Kind"},
    "j_order": {"Straight"},
    "j_tribe": {"Flush"},
    # Chips
    "j_sly": {"Pair"},
    "j_wily": {"Three of a Kind"},
    "j_clever": {"Two Pair"},
    "j_devious": {"Straight"},
    "j_crafty": {"Flush"},
    # Flat mult
    "j_jolly": {"Pair"},
    "j_zany": {"Three of a Kind"},
    "j_mad": {"Two Pair"},
    "j_crazy": {"Straight"},
    "j_droll": {"Flush"},
    "j_runner": {"Straight"},
}

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
# 2. Component A: Joker Trigger Order & Scaling Growth
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
    """Optimize joker positioning in-place on game.jokers.

    R4 Invariant: Restrict joker reordering strictly to copy jokers
    (j_blueprint, j_brainstorm) and j_ceremonial, preserving the natural
    order of all other jokers.
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

    # Identify best copy target (highest strength among scoring jokers)
    best_target = max(others, key=_copy_target_strength)

    if brainstorms:
        # Brainstorm copies leftmost joker (index 0). Place best target at index 0.
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
        new_order = list(others)

    if ceremonials:
        # Place ceremonial at the very end to prevent accidental engine destruction
        new_order.extend(ceremonials)

    game.jokers = new_order


def _v11_scaling_growth_bonus(key: str, ante: int) -> float:
    """Projected lifecycle growth bonus for scaling jokers in early/mid game (R1)."""
    mult = V11_PARAMS.get("v11_growth", 1.0)
    if not mult or key not in PORTFOLIO_SCALING or ante >= 6:
        return 0.0

    antes_remaining = max(0, 6 - ante)
    # R1: Universal scaling jokers with 20+ rounds to grow
    if key in {"j_constellation", "j_green_joker", "j_ride_the_bus", "j_supernova"}:
        return mult * 0.045 * antes_remaining

    if key in {"j_spare_trousers", "j_trousers", "j_fortune_teller", "j_wee", "j_vampire"}:
        return mult * 0.025 * antes_remaining

    return 0.0


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
    best_delta: float = 0.005

    target_ht = portfolio_target_hand(game)
    main_ht = main_hand_type(game)

    def is_active_hand_joker(j_key: str) -> bool:
        if j_key in HAND_SPECIFIC_JOKERS:
            req = HAND_SPECIFIC_JOKERS[j_key]
            return target_ht in req or main_ht in req
        return True

    owned_keys = [k for k, _, _ in sim_root.jokers]
    n_xmult = sum(1 for k in owned_keys if (k in PORTFOLIO_XMULT or k in PREMIER_XMULT_FINISHERS) and is_active_hand_joker(k))
    n_chips_perm = sum(1 for k in owned_keys if k in PORTFOLIO_CHIPS and k not in CONSUMABLE_JOKERS and is_active_hand_joker(k))
    n_flat_perm = sum(1 for k in owned_keys if k in PORTFOLIO_FLAT and k not in CONSUMABLE_JOKERS and is_active_hand_joker(k))

    has_premier_in_shop = any(
        not getattr(it, "sold", False) and getattr(it, "kind", "") == "joker"
        and (it.key in HIGH_LEVERAGE_SCORING_JOKERS or it.key in RELIABLE_XMULT_JOKERS or it.key in PREMIER_XMULT_FINISHERS)
        for it in getattr(game, "current_shop", [])
    )

    convert_ante = int(V11_PARAMS.get("v11_xmult_convert_ante", 0) or 0)
    in_convert_ante = convert_ante > 0 and sim_root.ante >= convert_ante

    def is_protected(j_idx: int) -> bool:
        if j_idx < 0 or j_idx >= len(sim_root.jokers):
            return True
        k, ed, _ = sim_root.jokers[j_idx]
        if in_convert_ante and k not in LATE_CONVERT_KEEP:
            # Late-game xMult conversion: any non-xMult joker is upgrade fuel.
            return False
        if k in {"j_hanging_chad", "j_mime", "j_sock_and_buskin", "j_blueprint", "j_brainstorm", "j_cavendish", "j_dusk"}:
            return True
        if k in COMBAT_SCALING_JOKERS:
            return True
        if is_active_hand_joker(k):
            if n_xmult <= 1 and (k in PORTFOLIO_XMULT or k in PREMIER_XMULT_FINISHERS):
                return True
            if n_chips_perm <= 1 and k in PORTFOLIO_CHIPS and k not in CONSUMABLE_JOKERS:
                return True
            if n_flat_perm <= 1 and k in PORTFOLIO_FLAT and k not in CONSUMABLE_JOKERS:
                return True
        if sim_root.ante <= 5 and k in {"j_business", "j_golden", "j_satellite"}:
            if not has_premier_in_shop:
                return True
        return False

    worst_j = _v10_worst_joker_idx(game)
    sellable_jokers: list[int] = []
    if in_convert_ante:
        sellable_jokers = [i for i in _v11_late_sell_order(game, reference_hand(game))
                           if not is_protected(i)]
    else:
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
    target_ht = portfolio_target_hand(game)
    main_ht = main_hand_type(game)
    for j_i in sellable_jokers:
        k_sold = sim_root.jokers[j_i][0]
        is_dead_econ_sold = (k_sold in DEAD_ECONOMY_JOKERS or k_sold in PORTFOLIO_ECON)
        for i in avail_items:
            it = game.current_shop[i]
            if it.kind == "joker" and it.key in HAND_SPECIFIC_JOKERS:
                if target_ht not in HAND_SPECIFIC_JOKERS[it.key] and main_ht not in HAND_SPECIFIC_JOKERS[it.key]:
                    continue
            is_premier = (it.key in PREMIER_XMULT_FINISHERS or it.key in RELIABLE_XMULT_JOKERS)
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
                if it.kind == "joker" and it.key in HAND_SPECIFIC_JOKERS:
                    if target_ht not in HAND_SPECIFIC_JOKERS[it.key] and main_ht not in HAND_SPECIFIC_JOKERS[it.key]:
                        continue
                is_premier = (it.key in PREMIER_XMULT_FINISHERS or it.key in RELIABLE_XMULT_JOKERS)
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
                        if it.kind == "joker" and it.key in HAND_SPECIFIC_JOKERS:
                            if target_ht not in HAND_SPECIFIC_JOKERS[it.key] and main_ht not in HAND_SPECIFIC_JOKERS[it.key]:
                                continue
                        if it.kind == "joker" and (it.key in PREMIER_XMULT_FINISHERS or it.key in RELIABLE_XMULT_JOKERS):
                            sequences_to_eval.append([
                                {"type": "sell_joker", "joker_idx": j_1},
                                {"type": "sell_joker", "joker_idx": j_2},
                                {"type": "buy", "item_idx": i}
                            ])

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
# 4. Component D: Universal Value Network Shop Ranking (_rank_shop_items_v11)
# ────────────────────────────────────────────────────────────────────────────

def _v11_tarot_value(game, key: str) -> float:
    """Tarot valuation heavily prioritizing compounding deck enhancements (R2)."""
    base = _v10_tarot_value(game, key)
    # R2: Prioritize The Magician, The Chariot, The Empress, The Hierophant
    if key == "c_magician":
        base += 0.08  # Lucky cards (1/5 +20 mult, 1/15 +$20)
    elif key == "c_chariot":
        base += 0.06  # Steel cards (x1.5 held in hand)
    elif key == "c_empress":
        base += 0.06  # Mult cards (+4 mult)
    elif key == "c_hierophant":
        base += 0.05  # Bonus cards (+30 chips)
    return base


def _rank_shop_items_v11(game, ref, surplus, rerolls_used: int = 0, is_deficit: bool = False):
    """Universal Value Network Shop Ranking incorporating V_theta(S) deltas (R1).
    Evaluates both open slots and full-slot swaps, boosting portfolio completeness,
    early scaling growth, econ generators, and deck enhancements.
    """
    if V11_PARAMS.get("v11_shop_v10_rank", False):
        return _v10_rank_shop_items(game, ref, surplus, rerolls_used=rerolls_used)

    p = ACTIVE_PARAMS
    vn_weight = float(V11_PARAMS.get("v11_vn_weight", 4.5) or 0.0)
    use_filters = bool(V11_PARAMS.get("v11_filters", True))
    pack_bonus = bool(V11_PARAMS.get("v11_pack_bonus", True))
    buys = []
    need_sell = None
    worst_cache = None

    slots_full = len(game.jokers) >= game.joker_slots
    worst_sell = 0
    if slots_full and game.jokers:
        worst_cache = _v10_worst_joker_idx(game, ref)
        if worst_cache is not None and worst_cache < len(game.jokers):
            worst_sell = _joker_sell_value(game.jokers[worst_cache])

    allowance = game.dollars
    f_curr = extract_game_features(game)
    v_curr = evaluate_shop_value_v11(f_curr)
    has_scoring = _has_scoring_joker(game, ref)

    target_ht = portfolio_target_hand(game)
    main_ht = main_hand_type(game)

    vn_scale = (vn_weight / 4.5) if vn_weight else 0.0

    def _vn_delta(item_idx: int) -> float:
        """V_theta(S u {i}) - V_theta(S); 0.0 when the VN term is disabled."""
        if vn_weight <= 0.0:
            return 0.0
        f_cand = formulate_counterfactual_state(game, {"type": "buy", "item_idx": item_idx})
        return evaluate_shop_value_v11(f_cand) - v_curr

    def _vn_term(item_idx: int, coef: float) -> float:
        return max(0.0, _vn_delta(item_idx) * coef * vn_scale)

    def is_active_hand_joker(j_key: str) -> bool:
        if j_key in HAND_SPECIFIC_JOKERS:
            req = HAND_SPECIFIC_JOKERS[j_key]
            return target_ht in req or main_ht in req
        return True

    n_xmult = sum(1 for j in game.jokers if (j.key in PORTFOLIO_XMULT or j.key in RELIABLE_XMULT_JOKERS or j.key in PREMIER_XMULT_FINISHERS) and is_active_hand_joker(j.key))
    n_chips = sum(1 for j in game.jokers if j.key in PORTFOLIO_CHIPS and j.key not in CONSUMABLE_JOKERS and is_active_hand_joker(j.key))
    n_flat = sum(1 for j in game.jokers if j.key in PORTFOLIO_FLAT and j.key not in CONSUMABLE_JOKERS and is_active_hand_joker(j.key))
    n_combat = n_xmult + n_chips + n_flat + sum(1 for j in game.jokers if j.key in COMBAT_SCALING_JOKERS)
    n_econ = sum(1 for j in game.jokers if j.key in PORTFOLIO_ECON or j.key in {"j_business", "j_business_card", "j_reserved_parking", "j_mail", "j_mail_in_rebate", "j_egg", "j_gift", "j_gift_card", "j_rocket", "j_golden", "j_todo_list", "j_to_do_list"})

    for i, item in enumerate(game.current_shop):
        if item.sold:
            continue
        price = item.discounted_price(game.shop_discount)
        eff_allowance = allowance + (worst_sell if (slots_full and item.kind == "joker") else 0)
        if price > eff_allowance:
            continue

        if item.kind == "joker":
            if use_filters:
                # Trap jokers filter
                if item.key in ("j_obelisk", "j_madness", "j_red_card", "j_campfire"):
                    continue
                has_face_joker = any(j.key in {"j_photograph", "j_smiley", "j_scary_face", "j_sock_and_buskin", "j_faceless", "j_triboulet"} for j in game.jokers)
                has_bus_owned = any(j.key == "j_ride_the_bus" for j in game.jokers)
                if item.key == "j_ride_the_bus" and has_face_joker:
                    continue
                if item.key in {"j_photograph", "j_smiley", "j_scary_face", "j_sock_and_buskin", "j_faceless", "j_triboulet"} and has_bus_owned:
                    continue
                if item.key in HAND_SPECIFIC_JOKERS:
                    req_hands = HAND_SPECIFIC_JOKERS[item.key]
                    if target_ht not in req_hands and main_ht not in req_hands:
                        continue
            if item.key in ("j_idol", "j_the_idol"):
                cards = list(getattr(game, "deck", ())) + list(getattr(game, "hand", ())) + list(getattr(game, "spent", ()))
                from collections import Counter
                suit_counts = Counter(getattr(c, "suit", None) for c in cards if getattr(c, "suit", None) is not None)
                if max(suit_counts.values(), default=0) < 20:
                    continue

            # Base joker value from heuristic
            value = joker_value(game, item.key, item.edition, ref, surplus)

            # R1: Scaling growth bonus in early/mid game (Antes 1-4)
            growth = _v11_scaling_growth_bonus(item.key, game.ante)
            if growth > 0.0:
                value += growth * 1.0

            # R2: Econ Joker Valuation in early/mid antes when scoring anchor present and no econ owned yet
            if game.ante <= 4 and has_scoring and n_econ == 0 and n_combat >= 2:
                if item.key in {"j_business", "j_business_card", "j_reserved_parking",
                               "j_mail", "j_mail_in_rebate", "j_rocket"}:
                    value += 0.15

            # Copy jokers
            if item.key in ("j_blueprint", "j_brainstorm"):
                if not has_scoring and (len(game.jokers) == 0 or game.ante <= 2):
                    continue
                if has_scoring:
                    value = max(value, 1.6)

            # xMult urgency in mid/late game when lacking xMult
            if game.ante >= 5 and n_xmult == 0:
                if item.key in PREMIER_XMULT_FINISHERS or item.key in RELIABLE_XMULT_JOKERS:
                    value += 0.50
            elif (item.key in PREMIER_XMULT_FINISHERS or item.key in RELIABLE_XMULT_JOKERS) and game.ante >= 6:
                value += 0.40

            # Early chips bias
            if game.ante <= 2:
                if item.key in EARLY_FLAT_CHIPS_JOKERS:
                    value += 0.30

            # Deficit survival urgency: if lacking combat jokers in deficit, boost combat jokers
            if is_deficit:
                is_combat = (item.key in PORTFOLIO_FLAT or item.key in PORTFOLIO_CHIPS
                             or item.key in PORTFOLIO_XMULT or item.key in COMBAT_SCALING_JOKERS)
                if is_combat:
                    value += 0.30

            has_room = (len(game.jokers) < game.joker_slots or item.edition == "Negative")
            if has_room:
                augmented_value = value
                if vn_weight > 0.0:
                    # R1: Augment with Value Network delta
                    f_cand = formulate_counterfactual_state(game, {"type": "buy", "item_idx": i})
                    v_cand = evaluate_shop_value_v11(f_cand)
                    delta_v = v_cand - v_curr
                    augmented_value = value + max(-0.06, delta_v * vn_weight)
                is_combat = (item.key in PORTFOLIO_FLAT or item.key in PORTFOLIO_CHIPS
                             or item.key in PORTFOLIO_XMULT or item.key in COMBAT_SCALING_JOKERS)
                if len(game.jokers) < game.joker_slots and (is_combat or game.ante >= 6):
                    augmented_value += 0.20
                if augmented_value >= p["buy_threshold"]:
                    buys.append((augmented_value, i))
            elif slots_full:
                # Full slots: evaluate a swap. From `v11_xmult_convert_ante` on,
                # a premier xMult candidate may be bought by selling ANY stale
                # non-xMult joker (worst-value first), not just the single worst
                # card -- this is the late-game +mult/chips -> xMult conversion
                # that human play treats as mandatory for the Ante 7-8 boss.
                convert_ante = int(V11_PARAMS.get("v11_xmult_convert_ante", 0) or 0)
                is_premier_cand = (item.key in PREMIER_XMULT_FINISHERS
                                   or item.key in RELIABLE_XMULT_JOKERS
                                   or item.key in HIGH_LEVERAGE_SCORING_JOKERS)
                convert_mode = (convert_ante > 0 and game.ante >= convert_ante
                                and is_premier_cand and n_xmult <= 2)

                if convert_mode:
                    cand_idxs = _v11_late_sell_order(game, ref)
                elif worst_cache is not None and worst_cache < len(game.jokers):
                    cand_idxs = [worst_cache]
                else:
                    cand_idxs = []

                for wc in cand_idxs:
                    if wc < 0 or wc >= len(game.jokers):
                        continue
                    worst_j = game.jokers[wc]
                    is_dead_econ_worst = worst_j.key in DEAD_ECONOMY_JOKERS or worst_j.key in PORTFOLIO_ECON
                    is_combat_worst = (worst_j.key in PORTFOLIO_FLAT or worst_j.key in PORTFOLIO_CHIPS
                                       or worst_j.key in PORTFOLIO_XMULT or worst_j.key in RELIABLE_XMULT_JOKERS
                                       or worst_j.key in PREMIER_XMULT_FINISHERS or worst_j.key in COMBAT_SCALING_JOKERS)
                    is_econ_cand = (item.key in ("j_golden", "j_egg", "j_satellite", "j_rocket")
                                    or item.key in PORTFOLIO_ECON)
                    if game.ante >= 5 and is_combat_worst and is_econ_cand and not convert_mode:
                        continue

                    if not convert_mode:
                        # Never sell key retriggers, premier anchors, or scaling engines
                        if worst_j.key in {"j_hanging_chad", "j_dusk", "j_mime", "j_sock_and_buskin", "j_cavendish", "j_ramen", "j_stuntman"}:
                            continue
                        if worst_j.key in COMBAT_SCALING_JOKERS:
                            continue

                        # Protect anchors before Ante 7
                        if game.ante <= 6 and is_active_hand_joker(worst_j.key):
                            if n_xmult <= 1 and (worst_j.key in PORTFOLIO_XMULT or worst_j.key in RELIABLE_XMULT_JOKERS or worst_j.key in PREMIER_XMULT_FINISHERS):
                                continue
                            if n_chips <= 1 and worst_j.key in PORTFOLIO_CHIPS:
                                continue
                            if n_flat <= 1 and worst_j.key in PORTFOLIO_FLAT:
                                continue

                    swap_delta_v = 0.0
                    if vn_weight > 0.0:
                        f_swap = formulate_counterfactual_state(game, {"type": "swap_joker", "sell_idx": wc, "buy_idx": i})
                        v_swap = evaluate_shop_value_v11(f_swap)
                        swap_delta_v = v_swap - v_curr

                    is_combat_cand = (item.key in PORTFOLIO_FLAT or item.key in PORTFOLIO_CHIPS
                                      or item.key in PORTFOLIO_XMULT or item.key in COMBAT_SCALING_JOKERS)
                    worst_val = joker_value(game, worst_j.key, getattr(worst_j, "edition", None), ref)
                    margin_ok = (value - worst_val >= p["sell_margin"])
                    if convert_mode:
                        # Deliberate conversion: the candidate is a proven xMult
                        # finisher and the joker sold is not, so the swap clears
                        # on role upgrade rather than a value margin.
                        swap_ok = True
                    else:
                        swap_ok = (margin_ok or (is_premier_cand and is_dead_econ_worst)
                                   or (game.ante >= 6 and is_dead_econ_worst and is_combat_cand)
                                   or (swap_delta_v >= 0.040 and is_premier_cand and not is_combat_worst))
                    if swap_ok:
                        cand = (value + max(0.0, swap_delta_v * vn_weight), wc, i)
                        if need_sell is None or cand[0] > need_sell[0]:
                            need_sell = cand

        elif item.kind == "booster":
            if item.key.startswith("p_buffoon") and len(game.jokers) >= game.joker_slots:
                continue
            if item.key.startswith(("p_celestial", "p_arcana", "p_spectral")) and len(game.consumable_hand) >= game.consumable_slots:
                continue
            base_pack_val = pack_value(game, item.key)
            if base_pack_val <= 0.0:
                continue
            if pack_bonus:
                # R1: Value Network Delta for Celestial / Arcana / Buffoon packs
                delta_v = 0.0
                if vn_weight > 0.0:
                    f_cand = formulate_counterfactual_state(game, {"type": "buy", "item_idx": i})
                    v_cand = evaluate_shop_value_v11(f_cand)
                    delta_v = v_cand - v_curr
                if item.key.startswith("p_celestial"):
                    base_pack_val += 0.12 + max(0.0, delta_v * 3.0)
                elif item.key.startswith("p_arcana"):
                    base_pack_val += 0.05 + max(0.0, delta_v * 2.0)
                elif item.key.startswith("p_buffoon"):
                    base_pack_val += 0.15 + max(0.0, delta_v * 3.0)
                else:
                    base_pack_val += max(0.0, delta_v * 2.0)

            if base_pack_val >= p["buy_threshold"]:
                buys.append((base_pack_val, i))

        elif item.kind == "tarot":
            if len(game.consumable_hand) < game.consumable_slots:
                base_t_val = _v11_tarot_value(game, item.key)
                val = base_t_val + _vn_term(i, 4.0)
                if val >= p["buy_threshold"]:
                    buys.append((val, i))

        elif item.kind == "planet":
            if len(game.consumable_hand) < game.consumable_slots:
                target_ht = portfolio_target_hand(game)
                main_ht = main_hand_type(game)
                item_ht = PLANET_HAND.get(item.key)
                val = 0.08
                if item_ht == target_ht:
                    val = 0.18
                elif item_ht == main_ht:
                    val = 0.14
                elif any(j.key == "j_constellation" for j in game.jokers):
                    val = 0.15
                elif any(j.key == "j_satellite" for j in game.jokers) and item.key not in getattr(game, "planets_used", set()):
                    val = 0.14

                val += _vn_term(i, 4.0)
                if val >= p["buy_threshold"]:
                    buys.append((val, i))

        elif item.kind == "voucher":
            prio = VOUCHER_PRIORITY.get(item.key, 0)
            if prio >= 2 and len(game.jokers) > 0 and game.ante > 2 and (game.dollars - price >= 10 and not is_deficit):
                val = 0.12 + 0.06 * prio + _vn_term(i, 4.0)
                buys.append((val, i))

        elif item.kind == "spectral":
            if len(game.consumable_hand) < game.consumable_slots:
                val = _v10_spectral_value(game, item.key)
                val += _vn_term(i, 4.0)
                if val >= p["buy_threshold"]:
                    buys.append((val, i))

        elif item.kind == "card" and item.card is not None:
            val = _v10_pack_card_value(game, item.card)
            val += _vn_term(i, 3.0)
            if val >= p["buy_threshold"]:
                buys.append((val, i))

    return buys, need_sell


def _v11_decide_booster(game) -> dict:
    """decide_booster incorporating V11 tarot priorities (R2) and portfolio completion (R1)."""
    # R4: Preserve V10's Ante-1 opening exactly
    if game.ante == 1 or not V11_PARAMS.get("v11_boosters", True):
        return _v10_decide_booster(game)

    choices = game.booster_choices
    picks = game.booster_picks_remaining
    if not choices or picks <= 0:
        return {"type": "skip_booster"}

    p = ACTIVE_PARAMS
    ref = None
    main = main_hand_type(game)
    target_ht = portfolio_target_hand(game)
    has_constellation = any(j.key == "j_constellation" for j in game.jokers)
    has_satellite = any(j.key == "j_satellite" for j in game.jokers)
    room_for_consumable = len(game.consumable_hand) < game.consumable_slots
    is_celestial_pack = any(isinstance(c, str) and c in PLANET_HAND for c in choices)

    ranked = []
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
            growth = _v11_scaling_growth_bonus(key, game.ante)
            if growth > 0.0:
                value += growth * 1.0
            if game.ante <= 5 and _has_scoring_joker(game, ref):
                if key in {"j_business", "j_business_card", "j_reserved_parking",
                           "j_mail", "j_mail_in_rebate", "j_egg", "j_gift", "j_gift_card", "j_rocket"}:
                    value += 0.35
        elif isinstance(c, tuple) and c and c[0] == "card":
            value = _v10_pack_card_value(game, c[1])
        elif isinstance(c, str):
            if c in PLANET_HAND:
                if room_for_consumable:
                    c_ht = PLANET_HAND[c]
                    if c_ht == target_ht:
                        value = 0.20
                    elif c_ht == main:
                        value = 0.16
                    elif has_constellation:
                        value = 0.16
                    elif has_satellite:
                        value = 0.15
                    elif c_ht in ("High Card", "Pair"):
                        value = 0.10
                    else:
                        value = 0.08
                else:
                    value = 0.0
            elif c in ALL_TAROTS:
                if room_for_consumable:
                    value = _v11_tarot_value(game, c)
            elif c in ALL_SPECTRALS:
                if room_for_consumable:
                    value = _v10_spectral_value(game, c)

        if value is not None:
            threshold = (p["booster_joker_threshold"] if is_joker else p["booster_pick_threshold"])
            if value >= threshold:
                ranked.append((value, i))

    if ranked:
        ranked.sort(key=lambda x: x[0], reverse=True)
        return {"type": "pick_booster", "indices": [i for _, i in ranked[:picks]]}

    # Zero-waste celestial pack: never skip if room for consumable exists
    if is_celestial_pack and room_for_consumable:
        planet_cands = [i for i, c in enumerate(choices) if isinstance(c, str) and c in PLANET_HAND]
        if planet_cands:
            return {"type": "pick_booster", "indices": [planet_cands[0]]}

    return {"type": "skip_booster"}


# ────────────────────────────────────────────────────────────────────────────
# 5. Component F: In-Blind Value Squeezing (_v11_decide_hand)
# ────────────────────────────────────────────────────────────────────────────

def _finish_hand_action(game, act: dict) -> dict:
    if act.get("type") == "discard":
        has_green = any(j.key == "j_green_joker" for j in game.jokers)
        has_banner = any(j.key == "j_banner" for j in game.jokers)
        has_ramen = any(j.key == "j_ramen" for j in game.jokers)
        if (has_green or has_banner or has_ramen) and game.hand:
            plays = scored_plays(game, topk=ACTIVE_PARAMS["eval_topk_play"])
            if plays:
                if has_green and game.hands_left > 1:
                    return {"type": "play", "cards": list(plays[0][1])}
                if (has_banner or has_ramen):
                    target = game.current_blind.chips_target - game.chips_scored
                    pace = target / max(1, game.hands_left)
                    if plays[0][0] >= pace:
                        return {"type": "play", "cards": list(plays[0][1])}
    return act


def _v11_decide_hand(game) -> dict:
    """In-Blind Value Squeezing & Decision Rule (§R2).

    When round clear is guaranteed (P(clear) >= 0.98 or immediate clearing hand available with surplus hands):
      - Squeeze multi-card face hands for j_business ($2/face card)
      - Hold face cards for j_reserved_parking
      - Play Lucky cards for +$20 cash / +20 mult chances
      - Harvest $5 discards for j_mail
      - Always prioritize beating the blind before farming.
    Otherwise, delegates to _v10_decide_hand.
    """
    # R4 Invariant: Ante 1 preserves V10's rock-solid conservative play exactly
    if game.ante == 1 or not V11_PARAMS.get("v11_squeeze", True):
        salvage = _v11_salvage_action(game)
        if salvage is not None:
            return salvage
        return _v10_decide_hand(game)

    salvage = _v11_salvage_action(game)
    if salvage is not None:
        return salvage

    # 1. Copy jokers & ceremonial positioning
    _optimize_joker_order_v11(game)

    joker_keys = {j.key for j in game.jokers}
    has_mail = ("j_mail" in joker_keys or "j_mail_in_rebate" in joker_keys) and game.discards_left > 0
    has_business = ("j_business" in joker_keys or "j_business_card" in joker_keys) and any(getattr(c, "is_face_card", False) and not c.debuffed for c in game.hand)
    has_parking = ("j_reserved_parking" in joker_keys) and any(getattr(c, "is_face_card", False) and not c.debuffed for c in game.hand)
    has_lucky = any(getattr(c, "enhancement", "None") == "Lucky" and not c.debuffed for c in game.hand)

    # If no value-squeezing opportunity is present, use V10's calibrated survival solver
    if not (has_mail or has_business or has_parking or has_lucky):
        return _finish_hand_action(game, _v10_decide_hand(game))

    # Scored plays
    plays = scored_plays(game, topk=ACTIVE_PARAMS["eval_topk_play"])
    if not plays:
        return _v10_decide_hand(game)

    T = game.current_blind.chips_target - game.chips_scored
    if T <= 0:
        return _v10_decide_hand(game)

    type_scores = _compute_type_scores(game, plays)
    p_clear = estimate_clear_probability(game, type_scores=type_scores)

    clearing_plays = [p for p in plays if p[0] >= T]

    # R2 Priority 1: When a clearing play is immediately available, prioritize beating the blind
    # while squeezing maximum value from face cards (Business), Lucky cards, and held faces (Parking).
    if clearing_plays:
        def value_score(p):
            cards_played = [game.hand[i] for i in p[1]]
            cards_held = [game.hand[i] for i in range(len(game.hand)) if i not in set(p[1])]
            score_val = 0.0
            if has_business:
                score_val += sum(2.0 for c in cards_played if getattr(c, "is_face_card", False) and not c.debuffed)
            if has_lucky:
                score_val += sum(3.0 for c in cards_played if getattr(c, "enhancement", "") == "Lucky" and not c.debuffed)
            if has_parking:
                score_val += sum(2.0 for c in cards_held if getattr(c, "is_face_card", False) and not c.debuffed)
            return score_val

        best_clearing = max(clearing_plays, key=lambda p: (value_score(p), p[0]))
        if value_score(best_clearing) > 0.0 or has_parking:
            return {"type": "play", "cards": list(best_clearing[1])}

    # R2 Priority 2: Mail-in Rebate harvest ($5/discard) when clear is guaranteed
    if has_mail:
        target_rank = _mail_target_rank(game)
        if target_rank is not None:
            mail_cands = [i for i, c in enumerate(game.hand) if c.rank == target_rank and not c.debuffed]
            if mail_cands:
                hand_after = [c for i, c in enumerate(game.hand) if i not in set(mail_cands)]
                surv_after = estimate_clear_probability(
                    game, h=game.hands_left, d=game.discards_left - 1, T=T, hand=hand_after, type_scores=type_scores
                )
                if surv_after >= 0.98 or (clearing_plays and all(i not in clearing_plays[0][1] for i in mail_cands) and surv_after >= 0.95):
                    return {"type": "discard", "cards": mail_cands[:ACTIVE_PARAMS["discard_max_size"]]}

    # R2 Priority 3: Non-clearing farming plays ONLY when surplus hands available and P(clear) >= 0.98
    if p_clear >= 0.98 and game.hands_left >= 3:
        if has_business:
            face_indices = [i for i, c in enumerate(game.hand) if c.is_face_card and not c.debuffed]
            if len(face_indices) >= 2:
                combo = face_indices[:min(5, len(face_indices))]
                cards = [game.hand[i] for i in combo]
                held = [game.hand[i] for i in range(len(game.hand)) if i not in set(combo)]
                try:
                    ht, sc = evaluate_hand(cards)
                    score = eval_hand_score(game, ht, sc, cards, held_cards=held)
                    hand_rem = [c for i, c in enumerate(game.hand) if i not in set(combo)]
                    surv_rem = estimate_clear_probability(
                        game, h=game.hands_left - 1, d=game.discards_left, T=T - score, hand=hand_rem, type_scores=type_scores
                    )
                    if surv_rem >= 0.98:
                        return {"type": "play", "cards": combo}
                except Exception:
                    pass

        if has_lucky:
            lucky_indices = [i for i, c in enumerate(game.hand) if c.enhancement == "Lucky" and not c.debuffed]
            if lucky_indices:
                combo = lucky_indices[:min(5, len(lucky_indices))]
                cards = [game.hand[i] for i in combo]
                held = [game.hand[i] for i in range(len(game.hand)) if i not in set(combo)]
                try:
                    ht, sc = evaluate_hand(cards)
                    score = eval_hand_score(game, ht, sc, cards, held_cards=held)
                    hand_rem = [c for i, c in enumerate(game.hand) if i not in set(combo)]
                    surv_rem = estimate_clear_probability(
                        game, h=game.hands_left - 1, d=game.discards_left, T=T - score, hand=hand_rem, type_scores=type_scores
                    )
                    if surv_rem >= 0.98:
                        return {"type": "play", "cards": combo}
                except Exception:
                    pass

    return _finish_hand_action(game, _v10_decide_hand(game))


# ────────────────────────────────────────────────────────────────────────────
# 6. SearchShopV11 Policy Class
# ────────────────────────────────────────────────────────────────────────────

class SearchShopV11(SearchShopV10):
    """Optilatro V11 Agent:
    Integrates Component A (left-to-right copy trigger order & scaling growth),
    Component B (combinatorial multi-item shop sequence planning),
    Component C (MLP Value Network V_theta(s) -> P(Win) shop ranking), and
    Component D (mid-game deficit capital deployment & in-blind value squeezing).
    """
    policy_name = "search_shop_v11"

    def __init__(self, params=None, search_shops: int = 999, candidate_cap: int = 4,
                 lookahead: bool = False, max_rollout_steps: int = 4000, **kwargs):
        super().__init__(params=params, search_shops=search_shops,
                         candidate_cap=candidate_cap, lookahead=lookahead,
                         max_rollout_steps=max_rollout_steps)
        if params:
            V11_PARAMS.update({k: v for k, v in params.items() if k in V11_PARAMS})
        self._action_queue: list[dict] = []
        self._pending_swap_target_idx: Optional[int] = None
        self._swapped_this_visit: bool = False

    def _search_shop(self, game) -> dict:
        if not game.current_shop or all(getattr(item, "sold", False) for item in game.current_shop):
            return {"type": "leave_shop"}

        # 1. V11 hook: deliberate late-game xMult conversion. Runs on top of
        #    whichever shop loop is active so the proven V10 loop keeps its
        #    churn while the agent still upgrades into multiplicative finishers.
        if (V11_PARAMS.get("v11_xmult_convert_hook", True)
                and (not self._swapped_this_visit
                     or V11_PARAMS.get("v11_convert_multi_swap", False))):
            act = _v11_xmult_conversion_step(game)
            if act is not None:
                self._pending_swap_target_idx = act["_v11_buy_after"]
                self._swapped_this_visit = True
                return {"type": "sell_joker", "joker_idx": act["joker_idx"]}

        # 1b. Blind-honest desperation deployment: when the board cannot beat
        #     the upcoming blind, spend cash on power instead of banking it.
        #     Runs before every shop loop so L1 delegation keeps the benefit.
        act = _v11_desperate_shop_action(game, getattr(self, "_rerolls_this_shop", 0))
        if act is not None:
            return act

        # 2. Frozen V10 L1 shop search (handles its own pending-swap buy).
        #    V11's own mid-game interest floor is applied locally for this call.
        if game.ante == 1 or V11_PARAMS.get("v11_shop_v10_l1", False):
            with _v11_shop_overrides():
                act = SearchShopV10._search_shop(self, game)
            # Additive open-slot search: only fills in purchases the calibrated
            # loop declined (leave_shop / reroll), never displaces its buys.
            if (V11_PARAMS.get("v11_open_slot_search", False)
                    and act.get("type") in ("leave_shop", "reroll")):
                extra = _v11_open_slot_search(game)
                if extra is not None:
                    return extra
            return act

        # 3. Complete a pending swap target first. This runs before the V11
        #    loop so a hook can sell and then buy within one visit.
        if self._pending_swap_target_idx is not None:
            target_i = self._pending_swap_target_idx
            self._pending_swap_target_idx = None
            if 0 <= target_i < len(game.current_shop) and not game.current_shop[target_i].sold:
                item = game.current_shop[target_i]
                price = item.discounted_price(game.shop_discount)
                has_room = len(game.jokers) < game.joker_slots or getattr(item, "edition", None) == "Negative" or item.kind != "joker"
                if price <= game.dollars and has_room:
                    return {"type": "buy", "item_idx": target_i}

        # R4: Preserve V10's rock-solid Ante-1 conservative opening
        if game.ante == 1 or V11_PARAMS.get("v11_shop_v10_full", False):
            return _v10_decide_shop(game, getattr(self, "_rerolls_this_shop", 0))

        # 2. Complete queued sequence steps if valid
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

        # 3. Boss reroll check
        if game.next_boss_key in BAD_BOSSES and game.dollars >= 10:
            can_dc = ("v_directors_cut" in game.vouchers and game.dc_reroll_ante != game.ante)
            can_retcon = "v_retcon" in game.vouchers
            if can_dc or can_retcon:
                return {"type": "reroll_boss"}

        # 4. Essential shop-phase consumable usage
        act = _v10_maybe_use_planet(game)
        if act is not None:
            return act

        if ACTIVE_PARAMS.get("use_tarots", True):
            act = _v10_decide_consumable(game)
            if act is not None:
                return act

        # 5. Deficit and Target Analysis (R3)
        ref = reference_hand(game)
        surplus = forecast_beatable(game, ACTIVE_PARAMS["tilt_surplus_margin"], ref)
        forecast_score = _forecast_round_score(game, ref)
        boss_target = _ante_boss_target(game)
        is_deficit = (forecast_score < boss_target * 2.0)
        is_mid_game = (2 <= game.ante <= 5)

        if game.ante <= 2:
            interest_floor = 0
            save_mode = False
        elif is_mid_game and is_deficit:
            interest_floor = 0
            save_mode = False
        elif game.ante >= 7:
            interest_floor = 0
            save_mode = False
        elif game.ante == 6 and is_deficit:
            interest_floor = 5
            save_mode = (game.dollars < 5)
        else:
            interest_floor = 25
            save_mode = (
                game.ante > 2
                and game.dollars < interest_floor
                and forecast_beatable(game, ACTIVE_PARAMS["save_margin"], ref)
            )

        convert_ante = int(V11_PARAMS.get("v11_xmult_convert_ante", 0) or 0)
        convert_active = (convert_ante > 0 and game.ante >= convert_ante
                          and bool(V11_PARAMS.get("v11_convert_multi_swap", False)))
        swap_limit = bool(V11_PARAMS.get("v11_swap_limit", True)) and not convert_active

        # 6. Full-slot portfolio swaps: combinatorial sequence search with Value Network (Ante >= 4)
        if (V11_PARAMS.get("v11_seq_plan", True)
                and not (swap_limit and self._swapped_this_visit)
                and len(game.jokers) >= game.joker_slots and game.ante >= 4
                and not self._searched_this_visit):
            self._searched_this_visit = True
            best_seq, delta = _plan_shop_sequence(game, getattr(self, "_rerolls_this_shop", 0))
            if best_seq:
                self._swapped_this_visit = True
                first_action = best_seq[0]
                if len(best_seq) > 1:
                    self._action_queue = list(best_seq[1:])
                return first_action

        # 7. Universal Value Network Shop Ranking (_rank_shop_items_v11)
        buys, need_sell = _rank_shop_items_v11(
            game, ref, surplus, rerolls_used=getattr(self, "_rerolls_this_shop", 0), is_deficit=is_deficit
        )
        if swap_limit and self._swapped_this_visit:
            need_sell = None

        # Prioritize between buys and swaps
        swap_val = need_sell[0] if need_sell is not None else 0.0
        best_buy_val = buys[0][0] if buys else 0.0

        if need_sell is not None and swap_val >= best_buy_val:
            if swap_limit:
                self._swapped_this_visit = True
            self._pending_swap_target_idx = need_sell[2]
            return {"type": "sell_joker", "joker_idx": need_sell[1]}

        target_ht = portfolio_target_hand(game)
        if buys:
            buys.sort(key=lambda b: (b[0], _KIND_RANK.get(game.current_shop[b[1]].kind, 1)), reverse=True)
            for value, idx in buys:
                item = game.current_shop[idx]
                price = item.discounted_price(game.shop_discount)
                if price <= game.dollars:
                    # In deficit or urgent: prioritize combat jokers, open-slot jokers, core economy, or target celestial
                    is_core_econ = item.key in ("c_hermit", "c_death", "c_fool", "c_temperance", "c_chariot", "c_empress", "c_hierophant", "c_justice")
                    is_target_planet = (item.kind == "planet" and PLANET_HAND.get(item.key) == target_ht)
                    is_combat = (item.kind == "joker" and (item.key in PORTFOLIO_FLAT or item.key in PORTFOLIO_CHIPS or item.key in PORTFOLIO_XMULT or item.key in COMBAT_SCALING_JOKERS))
                    is_open_joker = (item.kind == "joker" and len(game.jokers) < game.joker_slots)
                    is_early_pack = (item.kind == "booster" and game.ante <= 3)
                    is_urgent_item = is_combat or is_open_joker or is_core_econ or is_target_planet or is_early_pack

                    open_exempt = (V11_PARAMS.get("v11_open_joker_exempt", False)
                                   and is_open_joker and game.ante >= 3)
                    spend_ok = (open_exempt or is_deficit and is_mid_game and is_urgent_item) or (game.ante >= 6 and is_urgent_item) or (game.ante <= 2) or worth_spending(game, price, value)
                    save_ok = (open_exempt or not save_mode
                               or value >= ACTIVE_PARAMS["save_strong_value"]
                               or (is_deficit and is_mid_game and is_urgent_item))
                    if save_ok and spend_ok:
                        return {"type": "buy", "item_idx": idx}

        if need_sell is not None:
            if swap_limit:
                self._swapped_this_visit = True
            self._pending_swap_target_idx = need_sell[2]
            return {"type": "sell_joker", "joker_idx": need_sell[1]}

        # 8. Reroll logic (R3)
        reroll_cost = max(0, game.reroll_cost - game.reroll_discount)
        n_combat = sum(1 for j in game.jokers if j.key in PORTFOLIO_FLAT or j.key in PORTFOLIO_CHIPS
                       or j.key in PORTFOLIO_XMULT or j.key in COMBAT_SCALING_JOKERS)

        # Deficit targeted reroll:
        if is_mid_game and is_deficit and n_combat < 2:
            if getattr(self, "_rerolls_this_shop", 0) < 1 and game.dollars >= reroll_cost + 4:
                return {"type": "reroll"}

        # Late-game urgency rerolls
        eff_max = ACTIVE_PARAMS["reroll_max"]
        if game.ante >= 8:
            eff_max = max(eff_max, 10)
            min_reserve = 0
        elif game.ante == 7:
            eff_max = max(eff_max, 6)
            min_reserve = 2
        elif game.ante == 6 and is_deficit:
            eff_max = max(eff_max, 4)
            min_reserve = 4
        else:
            min_reserve = max(reroll_cost, ACTIVE_PARAMS["reroll_min_money"])

        if ((not save_mode or game.ante >= 6)
                and game.dollars >= reroll_cost
                and (game.dollars - reroll_cost >= min_reserve)
                and getattr(self, "_rerolls_this_shop", 0) < eff_max):
            return {"type": "reroll"}

        return {"type": "leave_shop"}

    def decide(self, game) -> dict:
        st = game.state
        if st == State.SELECTING_HAND:
            return _v11_decide_hand(game)

        if st == State.BOOSTER_OPEN:
            return _v11_decide_booster(game)

        if st != State.SHOP:
            return super().decide(game)

        if not self._in_shop or getattr(self, "_last_ante", None) != game.ante:
            self._in_shop = True
            self._last_ante = game.ante
            self._rerolls_this_shop = 0
            self._searched_this_visit = False
            self._swapped_this_visit = False
            self._action_queue.clear()
            self._pending_swap_target_idx = None

        act = self._search_shop(game)

        if act.get("type") == "reroll":
            self._rerolls_this_shop += 1
            self._searched_this_visit = False
        elif act.get("type") == "leave_shop":
            self._in_shop = False
            self._searched_this_visit = False
            self._swapped_this_visit = False
            self._action_queue.clear()
            self._pending_swap_target_idx = None

        return act
