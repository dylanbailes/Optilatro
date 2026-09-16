"""buy_model.py — Candidate-conditioned shop-buy value model (V11 open-slot).

WHY THIS EXISTS
===============
`evaluate_shop_value` (agent_v10, shop_model.json) is a *state* value model:
it scores the post-buy portfolio with coarse class counts (n_xmult, has_chips,
...). That is enough to rank full-slot SWAPS (removing a joker moves the class
counts), but provably inert for open-slot candidate ranking: adding one joker
to an open slot barely moves a 50-feature state vector, so every candidate
scores ΔV ≈ 0.000–0.005 and the search never fires.

This module defines a *candidate-conditioned* scorer:
    buy_value(game, shop_item) -> P(candidate contributes to a won run)
trained on **counterfactual rollout outcomes** (see
tools/collect_shop_rollouts.py): at each open-slot shop decision, fork the
seed-exact game, force-buy the candidate in one fork and skip it in the
other, roll both to GAME_OVER with the shipped (frozen-V10-parity) policy,
and label the row with the outcome difference. The model therefore learns
"what does buying THIS joker do to THIS run", not "how does the portfolio
vector shift".

SHARED CODE RULE
================
The feature builder below is the SINGLE SOURCE OF TRUTH: the collector
(tools/collect_shop_rollouts.py) and the runtime consumer (agent_v11) both
call `extract_buy_features`, so train/serve skew is structurally impossible.
The label schema is versioned via BUILD_VERSION; a trained weight file
records the version it was fitted on and the loader refuses mismatches.

Human-fairness: every feature is computed from observable state (shop items,
owned jokers, deck composition, hand levels, money, the pre-selected next
boss). No RNG calls, no draw-order peeking, no rollout lookahead at decision
time — the rollouts happen OFFLINE at training time only.

FEATURE FAMILIES (44 + shared build_interactions on the 40 base feats)
=====================================================================
A. Candidate identity  : role one-hots + slot-pressure interactions
B. Candidate power     : joker_value marginal (+variants)
C. Portfolio context   : owned counts/needs, duplicate flag
D. Run context         : ante, blind kind, money, slots
E. Threat context      : next-blind target vs current power, boss key hash
F. Scaling velocity    : needs-per-remaining-round for owned/candidate scaling
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Optional

BUILD_VERSION = 1
MODEL_PATH = Path(__file__).resolve().parent / "buy_model.json"

# ────────────────────────────────────────────────────────────────────────────
# Role sets (mirrors tools/portfolio.py families; keep in sync by importing
# the canonical sets where possible).
# ────────────────────────────────────────────────────────────────────────────
try:  # canonical role sets live in tools/portfolio.py
    import sys as _sys
    _root = Path(__file__).resolve().parents[3]
    if str(_root) not in _sys.path:
        _sys.path.insert(0, str(_root))
    from tools.portfolio import (  # type: ignore
        CHIPS_JOKERS, FLAT_MULT_JOKERS, XMULT_JOKERS,
        SCALING_JOKERS, ECON_JOKERS, RETRIGGER_JOKERS,
    )
except Exception:  # pragma: no cover — collector/runtime both run from repo root
    CHIPS_JOKERS = set()
    FLAT_MULT_JOKERS = set()
    XMULT_JOKERS = set()
    SCALING_JOKERS = set()
    ECON_JOKERS = set()
    RETRIGGER_JOKERS = set()

# No-fit fallback: candidate identity must still rank S-tier finishers
# sensibly if the weight file is missing (evaluate_buy returns None then, and
# consumers keep the frozen baseline behaviour — this set is documentation).
PREMIER_XMULT = {
    "j_baron", "j_the_duo", "j_the_family", "j_the_order", "j_the_tribe",
    "j_bloodstone", "j_idol", "j_photograph", "j_hologram", "j_stuntman",
    "j_gift_card", "j_vampire", "j_caino", "j_triboulet",
}

# Scaling velocity table: (cards/states needed per +step). Values chosen from
# the sim's jokers/scaling.py semantics; None → not a scaling joker.
_SCALING_NEEDS: dict[str, Optional[int]] = {
    "j_green_joker": 1, "j_ride_the_bus": 1, "j_runner": 1, "j_ice_cream": 0,
    "j_popcorn": 0, "j_square_joker": 1, "j_fortune_teller": 1,
    "j_bull": 2, "j_flash_card": 1, "j_supernova": 1, "j_constellation": 1,
    "j_green": 1, "j_ceremonial": 1, "j_midas_mask": 0, "j_arrowhead": 0,
    "j_hologram": 1, "j_madness": 0, "j_vampire": 1, "j_campfire": 1,
    "j_Throwback": 1, "j_throwback": 1, "j_castle": 1, "j_smiley_face": 0,
    "j_spare_trousers": 2, "j_obelisk": 20, "j_ride_bus": 1,
    "j_shoot_the_moon": 0, "j_perkeo": 0, "j_egg": 0, "j_to_do_list": 0,
    "j_todo_list": 0, "j_bulk": 0,
}

_TRAP_BUY_KEYS = {
    "j_madness", "j_obelisk", "j_idol", "j_the_idol", "j_campfire",
    "j_red_card", "j_gros_michel",
}


def _norm(key: str) -> str:
    return (key or "").strip()


def _blind_info(game: Any) -> tuple[int, str, int, str, bool]:
    """(blind_idx, kind, chips_target, boss_key, is_boss) for the UPCOMING blind.

    At shop time game.blind_idx indexes the next blind (0=Small,1=Big,2=Boss);
    the boss is pre-selected into game.next_boss_key before the shop.
    """
    idx = int(getattr(game, "blind_idx", 0) or 0)
    kind = ["Small", "Big", "Boss"][idx if 0 <= idx <= 2 else 0]
    ante = int(getattr(game, "ante", 1) or 1)
    boss_key = ""
    is_boss = kind == "Boss"
    if is_boss:
        boss_key = _norm(getattr(game, "next_boss_key", "") or "")
    target = 0
    try:
        from .constants import BLIND_CHIPS
        target = BLIND_CHIPS[ante][idx]
    except Exception:
        target = 0
    if is_boss:
        if boss_key == "bl_needle":
            target = BLIND_CHIPS[ante][0]
        elif boss_key == "bl_wall":
            target = BLIND_CHIPS[ante][0] * 4
        elif boss_key == "bl_violet":
            target = BLIND_CHIPS[ante][0] * 6
    return idx, kind, int(target), boss_key, is_boss


def _current_power(game: Any, ref) -> float:
    """Best drawable hand score (ceiling) — the run's current single-hand power."""
    try:
        _ceiling, _typical, _reach, base_c, _base_t = ref
        return float(base_c)
    except Exception:
        return 0.0


def _scaling_velocity(game: Any) -> float:
    """Avg scaling progress rate of owned scaling jokers (steps per round)."""
    ante = int(getattr(game, "ante", 1) or 1)
    idx = int(getattr(game, "blind_idx", 0) or 0)
    rounds_left = max(0.5, (8 - ante) * 3 - idx)  # remaining blinds incl. current
    rates = []
    for j in getattr(game, "jokers", []):
        need = _SCALING_NEEDS.get(_norm(getattr(j, "key", "")))
        if need is None:
            continue
        st = getattr(j, "state", {}) or {}
        prog = float(st.get("counter", st.get("mult", st.get("chips", 0))) or 0)
        rates.append(prog / rounds_left)
    return (sum(rates) / len(rates)) if rates else 0.0


def extract_buy_features(
    game: Any,
    item: Any,
    price: int,
    ref=None,
    jv: Optional[float] = None,
    dV: Optional[float] = None,
) -> dict[str, float]:
    """Build the candidate-conditioned feature vector for ONE shop item.

    game      : live BalatroGame at SHOP state (read-only inspection)
    item      : ShopItem with kind == "joker" (not sold)
    price     : item.discounted_price(game.shop_discount)
    ref       : optional precomputed reference_hand tuple (perf)
    jv        : optional precomputed joker_value(game, key, edition) (perf)
    dV        : optional precomputed evaluate_shop_value ΔV (perf; kept as a
                feature so the fit can *learn how much* to trust the old model)
    """
    from .agent_v9 import reference_hand  # local import avoids cycles
    if ref is None:
        ref = reference_hand(game)
    if jv is None:
        from .agent_v9 import joker_value
        jv = joker_value(game, item.key, getattr(item, "edition", "None"), ref=ref)

    key = _norm(item.key)
    edition = getattr(item, "edition", "None") or "None"
    owned = [j for j in getattr(game, "jokers", [])]
    owned_keys = [_norm(getattr(j, "key", "")) for j in owned]
    n_owned = len(owned_keys)
    slots = int(getattr(game, "joker_slots", 5) or 5)
    free = max(0, slots - n_owned)
    ante = int(getattr(game, "ante", 1) or 1)
    dollars = int(getattr(game, "dollars", 0) or 0)
    idx, kind, target, boss_key, is_boss = _blind_info(game)

    # ── A. identity one-hots ────────────────────────────────────────────
    is_xmult = 1.0 if (key in XMULT_JOKERS or edition == "Polychrome") else 0.0
    is_chips = 1.0 if key in CHIPS_JOKERS else 0.0
    is_flat = 1.0 if key in FLAT_MULT_JOKERS else 0.0
    is_scaling = 1.0 if key in SCALING_JOKERS else 0.0
    is_econ = 1.0 if key in ECON_JOKERS else 0.0
    is_retrig = 1.0 if key in RETRIGGER_JOKERS else 0.0
    is_premier = 1.0 if key in PREMIER_XMULT else 0.0
    is_trap = 1.0 if key in _TRAP_BUY_KEYS else 0.0

    # ── B. power ────────────────────────────────────────────────────────
    jv = float(jv or 0.0)
    power = _current_power(game, ref)

    # ── C. portfolio context ────────────────────────────────────────────
    n_xm = sum(1 for k in owned_keys if k in XMULT_JOKERS)
    n_ch = sum(1 for k in owned_keys if k in CHIPS_JOKERS)
    n_fl = sum(1 for k in owned_keys if k in FLAT_MULT_JOKERS)
    n_sc = sum(1 for k in owned_keys if k in SCALING_JOKERS)
    n_ec = sum(1 for k in owned_keys if k in ECON_JOKERS)
    n_rt = sum(1 for k in owned_keys if k in RETRIGGER_JOKERS)
    dup = 1.0 if key in owned_keys else 0.0

    # ── D/E. run + threat context ───────────────────────────────────────
    money_ratio = (dollars - price) / max(1.0, target / 25.0)
    power_ratio = power / float(target) if target else 0.0

    # ── F. scaling velocity ─────────────────────────────────────────────
    sv = _scaling_velocity(game)
    cneed = _SCALING_NEEDS.get(key)
    cand_vel = (float(cneed) / max(0.5, (8 - ante) * 3 - idx)) if cneed else 0.0

    feats: dict[str, float] = {
        # A — identity
        "is_xmult": is_xmult, "is_chips": is_chips, "is_flat": is_flat,
        "is_scaling": is_scaling, "is_econ": is_econ, "is_retrig": is_retrig,
        "is_premier": is_premier, "is_trap": is_trap,
        "ed_foil": 1.0 if edition == "Foil" else 0.0,
        "ed_holo": 1.0 if edition == "Holographic" else 0.0,
        "ed_poly": 1.0 if edition == "Polychrome" else 0.0,
        "ed_neg": 1.0 if edition == "Negative" else 0.0,
        # B — power
        "jv": jv,
        "jv_late": jv * max(0.0, ante - 3) / 5.0,
        "jv_xm_need": jv * (1.0 if n_xm == 0 else 0.3),
        # C — portfolio
        "n_xmult": float(n_xm), "n_chips": float(n_ch), "n_flat": float(n_fl),
        "n_scaling": float(n_sc), "n_econ": float(n_ec), "n_retrig": float(n_rt),
        "owned": float(n_owned), "free": float(free),
        "dup": dup,
        "xm_gap_x": is_xmult * (1.0 if n_xm < 2 else 0.0),
        "chips_gap_c": is_chips * (1.0 if n_ch < 1 else 0.0),
        "flat_gap_f": is_flat * (1.0 if n_fl < 2 else 0.0),
        "econ_surplus": is_econ * (1.0 if dollars >= 12 else 0.0),
        "late_econ_pen": is_econ * max(0.0, ante - 5) / 3.0,
        "dup_pen": dup * 2.0,
        # D — run context
        "ante": float(ante), "blind_big": 1.0 if kind == "Big" else 0.0,
        "blind_boss": 1.0 if is_boss else 0.0,
        "price": float(price),
        "price_frac": float(price) / max(1.0, float(dollars)),
        "after_money": float(max(0, dollars - price)),
        "money_ratio": money_ratio,
        # E — threat
        "power_ratio": power_ratio,
        "power_deficit": max(0.0, 1.0 - power_ratio),
        "urgency": power_deficit if (power_deficit := max(0.0, 1.0 - power_ratio)) else 0.0,
        "combat_x_urgency": jv * max(0.0, 1.0 - power_ratio) * (1.0 - is_econ),
        "boss_key_hash": float((sum(ord(c) for c in boss_key) % 97) / 97.0),
        # F — scaling velocity
        "own_scale_vel": sv,
        "cand_vel": cand_vel,
        "scale_gain": is_scaling * max(0.0, cand_vel - sv),
        "vel_x_ante": sv * ante / 8.0,
    }
    if dV is not None:
        feats["legacy_dv"] = float(dV)
        feats["legacy_dv_pos"] = max(0.0, float(dV))
    return feats


# ────────────────────────────────────────────────────────────────────────────
# Weight file I/O + evaluation (pure-python, no numpy at runtime)
# ────────────────────────────────────────────────────────────────────────────
_WEIGHTS_CACHE: tuple[Optional[dict], tuple] | None = None


def load_buy_model(path: Path | str | None = None):
    """Load trained weights. Returns (meta, (names, w, b)) or (None, (None, None, 0.0))."""
    global _WEIGHTS_CACHE
    p = Path(path) if path else MODEL_PATH
    if not p.exists():
        return None, (None, None, 0.0)
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return None, (None, None, 0.0)
    if int(data.get("build_version", -1)) != BUILD_VERSION:
        return None, (None, None, 0.0)
    names = data["feat_order"]
    w = data["w"]
    b = float(data.get("bias", 0.0))
    meta = {k: v for k, v in data.items()
            if k not in ("feat_order", "w", "bias")}
    _WEIGHTS_CACHE = (meta, (names, w, b))
    return meta, (names, w, b)


def evaluate_buy(feats: dict[str, float], weighted=None) -> Optional[float]:
    """P(candidate contributes to a won run). None if no weights available."""
    if weighted is None:
        _meta, weighted = load_buy_model()
    names, w, b = weighted
    if names is None:
        return None
    from .agent_v10 import build_interactions
    fi = build_interactions(feats)
    z = b
    for nm, wi in zip(names, w):
        z += wi * fi.get(nm, 0.0)
    z = max(-30.0, min(30.0, z))
    return 1.0 / (1.0 + math.exp(-z))


def buy_value(game: Any, item: Any, price: int, ref=None,
              jv: Optional[float] = None, dV: Optional[float] = None,
              weighted=None) -> Optional[float]:
    """Convenience: features + score in one call (used by agent_v11 runtime)."""
    feats = extract_buy_features(game, item, price, ref=ref, jv=jv, dV=dV)
    return evaluate_buy(feats, weighted=weighted)
