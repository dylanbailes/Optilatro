"""value_tables.py — the learned value artifact and its feature contract.

WHAT THIS IS
============
A single value function over *items in scenarios*:

    V(item | scenario)  =  linear_head(features)  +  shrunk_residual(cell)

fit on counterfactual rollout contrasts (see tools/collect_decisions.py), and
evaluated in pure Python with no runtime dependency (no numpy, no torch).

It replaces, for the new agent, the curated numeric knowledge in the frozen
baselines: PACK_VALUE, VOUCHER_PRIORITY, DECK_CONDITIONS, edition_bonus, the
lifecycle curves, the tier bonuses, and ~111 tunable knobs.

FIRST PRINCIPLES
================
An item's value is a *controlled contrast*, not a score:

    V = E[R | acquire item] - E[R | policy's own action],    R = 1[win]

Three consequences drive the implementation:

1. **The label is a difference**, so the natural link is the identity, not a
   sigmoid. A value of +0.01 means "buying this adds 1 percentage point of win
   probability in this scenario". That is directly comparable to a search ΔV
   and needs no calibration trickery.
2. **Win is sparse (base rate ~14%)**, so `ante_delta` rides along as a
   CONTROL VARIATE. The per-sample score is

       y_i = (won_buy - won_skip) - beta * (ante_buy - ante_skip - mean_ante)

   with a single `beta` fitted on the pooled data. `beta` lives in the artifact
   ("fitted"), never in code. This cuts variance without changing the estimand,
   and — critically — the variate is an *outcome*, so it is used at fit time
   only and never becomes a runtime feature.
3. **Most (item, scenario) cells are thin.** The residual table backs off
   through a hierarchy

       item|ante|support  ->  item|ante  ->  item  ->  role-block  ->  0

   with count-based shrinkage `(n*mean + tau*parent) / (n + tau)`, where `tau`
   is fitted by cross-validation. No hand-chosen shrinkage weight.

Determinism: the artifact is a frozen, hashed snapshot. Evaluation is a pure
function of (snapshot, features). Nothing here mutates a game, consumes RNG, or
writes state, so an evaluated benchmark stays seed-exact.

TRAIN/SERVE SKEW IS STRUCTURALLY IMPOSSIBLE
===========================================
`scenario_features` / item features below are the ONLY feature builder. The
collector imports them to write training rows; the runtime imports them to
score candidates. There is no second implementation to drift.

HUMAN-FAIRNESS
==============
Every feature is observable at decision time to a player who knows the deck's
composition (deck + hand + spent), the current shop, and the revealed boss.
No RNG, no draw-order peeking, no future-shop knowledge.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional

from . import catalogue as CAT

MODEL_VERSION = 1
DEFAULT_PATH = Path(__file__).resolve().parent / "value_tables.json"

# Scope lock (PROJECT.md / AGENTS.md): Red Deck, White Stake, antes 1-8.
TOTAL_ANTES = 8
STANDARD_DECK = 52

# Run return. Dense by construction: depth carries the gradient that a sparse
# win label cannot, while the win bonus keeps the true objective dominant.
# The bonus is not a tuned number — it is the scope constant, which makes a
# win worth the whole run's depth again (ante 8 + win == 16 > dying at 8).
RETURN_WIN_BONUS = TOTAL_ANTES


# ────────────────────────────────────────────────────────────────────────────
# Scenario (context) features
# ────────────────────────────────────────────────────────────────────────────

BLIND_KINDS = ("Small", "Big", "Boss")


def _blind_kind(game: Any) -> str:
    idx = int(getattr(game, "blind_idx", 0) or 0)
    if 0 <= idx < len(BLIND_KINDS):
        return BLIND_KINDS[idx]
    try:
        return str(getattr(game.current_blind, "kind", "") or "")
    except Exception:
        return ""


def _target(game: Any) -> float:
    """Chips the upcoming blind demands (sim-provided, never a typed table).

    ``game.current_blind`` is the UPCOMING blind while in the shop (verified),
    so this needs no ante ladder of its own — which is precisely how the old
    `_ante_boss_target`'s hardcoded 40k/80k/300k literals disappear.
    """
    try:
        return float(game.current_blind.chips_target)
    except Exception:
        return 0.0


def _power(game: Any, ref=None) -> float:
    """Current single-hand power: the best play off the reference hand.

    ``reference_hand`` returns RefHand(ceiling, typical, reach, base_c,
    base_t) — index 3 is ``base_c``, the best-play score of the reference
    hand. Index 2 is ``reach``, a probability, and must never be used as a
    chip quantity.
    """
    try:
        from .agent_v9 import reference_hand
        if ref is None:
            ref = reference_hand(game)
        return float(ref[3])
    except Exception:
        return 0.0


def _owned_records(game: Any) -> list[tuple[str, ...]]:
    """Role tuples of owned jokers, in catalogue terms."""
    out: list[tuple[str, ...]] = []
    for j in getattr(game, "jokers", []) or []:
        it = CAT.item(str(getattr(j, "key", "")))
        out.append(it.roles if it is not None else ())
    return out


def _support(owned: list[tuple[str, ...]], cand_roles: Iterable[str]) -> tuple[int, int]:
    """(sharing, total): how many owned jokers share a role with the candidate.

    This is the diminishing-returns / anti-synergy context, derived from the
    catalogue's role vocabulary rather than a curated list of "conflicts".
    """
    cand = set(cand_roles)
    if not cand:
        return 0, len(owned)
    return sum(1 for r in owned if cand & set(r)), len(owned)


def support_bucket(game: Any, item_key: str) -> int:
    """Coarse support level used as a residual-cell dimension (0/1/2)."""
    it = CAT.item(item_key)
    roles = it.roles if it is not None else ()
    sharing, _total = _support(_owned_records(game), roles)
    return 2 if sharing >= 2 else sharing


def item_live_features(game: Any, item: Any) -> dict[str, float]:
    """Observable, *live* features of one candidate (kind-agnostic).

    Merged on top of the catalogue's spec-derived features. Everything here
    would be visible to a human looking at the shop.
    """
    key = str(getattr(item, "key", "") or "")
    kind = str(getattr(item, "kind", "") or "")
    discount = float(getattr(game, "shop_discount", 0.0) or 0.0)
    try:
        price = float(item.discounted_price(discount))
    except Exception:
        price = float(getattr(item, "price", 0) or 0)
    dollars = float(getattr(game, "dollars", 0) or 0)
    owned_keys = [str(getattr(j, "key", "")) for j in getattr(game, "jokers", []) or []]
    it = CAT.item(key)
    roles = it.roles if it is not None else ()
    sharing, total_owned = _support(_owned_records(game), roles)

    interest_cap = float(getattr(game, "interest_cap", 0) or 0)
    bank_target = max(1.0, interest_cap * 5.0)  # $1 per $5 held, capped

    feats = {
        "price": price,
        "price_frac": price / dollars if dollars > 0 else 1.0,
        "affordable": 1.0 if price <= dollars else 0.0,
        "after_money": max(0.0, dollars - price),
        "bank_frac": min(1.0, max(0.0, (dollars - price)) / bank_target),
        "editioned": 1.0 if str(getattr(item, "edition", "None") or "None") != "None" else 0.0,
        "dup_owned": 1.0 if key in owned_keys else 0.0,
        "support_sharing": float(sharing),
        "support_total": float(total_owned),
        "support_frac": (sharing / total_owned) if total_owned else 0.0,
        "is_consumable_kind": 1.0 if kind in ("tarot", "spectral", "planet") else 0.0,
        # Playing cards (Standard packs, shop card slots) carry no catalogue
        # key, so their quality lives here instead: an enhanced/sealed/editioned
        # card is the only kind worth taking.
        "card_enh": 1.0 if str(getattr(item, "enhancement", "None") or "None") not in ("None", "") else 0.0,
        "card_seal": 1.0 if str(getattr(item, "seal", "None") or "None") not in ("None", "") else 0.0,
    }
    # Planter: a planet's own hand type is already levelled how much?
    if kind == "planet" and it is not None and it.hand_type:
        levels = getattr(game, "hand_levels", None) or {}
        lvl = levels.get(it.hand_type, 1) if hasattr(levels, "get") else 1
        feats["own_hand_level"] = float(lvl)
    return feats


def scenario_features(game: Any, item_key: str, ref=None) -> dict[str, float]:
    """The scenario side of the value function (item-independent parts too).

    Returned keys are the raw feature names; `build_vector` expands them into
    the fixed model layout (including generated interactions).
    """
    ante = float(getattr(game, "ante", 1) or 1)
    kind = _blind_kind(game)
    target = _target(game)
    power = _power(game, ref)
    dollars = float(getattr(game, "dollars", 0) or 0)
    jokers = list(getattr(game, "jokers", []) or [])
    consum = list(getattr(game, "consumable_hand", []) or [])
    jslots = float(getattr(game, "joker_slots", 0) or 0)
    cslots = float(getattr(game, "consumable_slots", 0) or 0)
    deck_size = len(getattr(game, "full_deck", []) or []) or STANDARD_DECK

    boss_key = str(getattr(game, "next_boss_key", "") or "")
    boss_feats = CAT.boss_features(boss_key) if boss_key else {}

    ratio = (power / target) if target > 0 else 0.0
    feats: dict[str, float] = {
        "ante": ante,
        "ante_frac": ante / TOTAL_ANTES,
        "blind_idx": float(getattr(game, "blind_idx", 0) or 0),
        "is_boss": 1.0 if kind == "Boss" else 0.0,
        "is_big": 1.0 if kind == "Big" else 0.0,
        "log_target": math.log1p(target),
        "log_power": math.log1p(power),
        "power_ratio": ratio,
        "power_deficit": max(0.0, 1.0 - ratio),
        "dollars": dollars,
        "n_jokers": float(len(jokers)),
        "n_consumables": float(len(consum)),
        "joker_slots_free": max(0.0, jslots - len(jokers)),
        "consumable_slots_free": max(0.0, cslots - len(consum)),
        "deck_frac": deck_size / STANDARD_DECK,
        "boss_known": 1.0 if boss_key else 0.0,
    }
    for k, v in boss_feats.items():
        feats[f"boss_{k}"] = v
    return feats


# ────────────────────────────────────────────────────────────────────────────
# Feature layout (fixed, generated — never hand-listed)
# ────────────────────────────────────────────────────────────────────────────

# Context fields carried through to the model (interaction sources too).
_CTX_KEYS = (
    "ante_frac", "is_boss", "is_big", "log_target", "log_power",
    "power_ratio", "power_deficit", "dollars", "joker_slots_free",
    "consumable_slots_free", "deck_frac", "bank_frac", "price_frac",
    "after_money", "support_frac", "support_sharing", "dup_owned",
    "affordable", "editioned", "card_enh", "card_seal",
)

# Item fields that are meaningfully interacted with context. Generated from
# the catalogue vocabulary, so adding a role or flag extends the layout.
_ITEM_INTERACTION_FIELDS = (
    ("role", CAT.ROLES),
    ("flag", CAT.EFFECT_FLAGS),
)

# Which context fields get crossed with the item fields above.
_INTERACTION_CTX = ("ante_frac", "power_deficit", "support_frac", "is_boss")


def _interaction_names() -> list[str]:
    names: list[str] = []
    for kind, vocab in _ITEM_INTERACTION_FIELDS:
        for v in vocab:
            for c in _INTERACTION_CTX:
                names.append(f"x_{kind}_{v}__{c}")
    return names


FEATURE_ORDER: tuple[str, ...] = (
    tuple(f"item_{k}" for k in CAT.FEATURE_NAMES)
    + tuple(f"ctx_{k}" for k in _CTX_KEYS)
    + tuple(f"boss_{k}" for k in CAT.BOSS_FLAGS)
    + tuple(_interaction_names())
)


def build_vector(feats: dict[str, float]) -> list[float]:
    """Expand a flat feature dict into the fixed model layout.

    `feats` may contain item_*, ctx_*, boss_*, and raw catalogue keys; the
    function is total (unknown keys become 0.0) so a missing field can never
    crash a policy mid-run.
    """
    out = [0.0] * len(FEATURE_ORDER)
    for i, name in enumerate(FEATURE_ORDER):
        if name.startswith("x_"):
            continue
        out[i] = float(feats.get(name, 0.0))
    # Interactions: item field x context scalar.
    idx = {name: i for i, name in enumerate(FEATURE_ORDER)}
    for kind, vocab in _ITEM_INTERACTION_FIELDS:
        for v in vocab:
            fv = float(feats.get(f"item_{kind}_{v}", 0.0))
            if fv == 0.0:
                continue
            for c in _INTERACTION_CTX:
                name = f"x_{kind}_{v}__{c}"
                out[idx[name]] = fv * float(feats.get(f"ctx_{c}", 0.0))
    return out


def decision_features(game: Any, item: Any, ref=None) -> dict[str, float]:
    """Complete featurisation of one (game, candidate) pair.

    Single source of truth for both the collector and the runtime.
    """
    key = str(getattr(item, "key", "") or "")
    spec = CAT.item_features(key)
    live = item_live_features(game, item)
    scn = scenario_features(game, key, ref=ref)
    try:
        from .agent_v9 import joker_value, reference_hand
        if ref is None:
            ref = reference_hand(game)
        spec["item_live_jv"] = float(
            joker_value(game, key, getattr(item, "edition", "None"), ref=ref))
    except Exception:
        spec["item_live_jv"] = 0.0

    feats: dict[str, float] = {}
    for k, v in spec.items():
        feats[f"item_{k}"] = v
    for k, v in scn.items():
        feats.setdefault(f"ctx_{k}", v)
    for k, v in live.items():
        feats.setdefault(f"ctx_{k}", v)
    return feats


def run_return(outcome: dict) -> float:
    """Dense run return from a rollout outcome dict.

    R = ante_reached + RETURN_WIN_BONUS * won. Using a dense return is what
    makes ~3% base-rate win flips learnable from a few thousand forks: a run
    that reaches ante 6 instead of 3 carries signal even when neither arm won.
    """
    return float(outcome.get("ante", 0)) + (
        RETURN_WIN_BONUS if outcome.get("won") else 0.0)


def cell_key(game: Any, item_key: str) -> str:
    """Finest residual cell: item | ante | support bucket."""
    ante = int(getattr(game, "ante", 1) or 1)
    return f"{item_key}|a{ante}|s{support_bucket(game, item_key)}"


# ── Scenario cells: the item's value IN A SCENARIO, not just per ante ────────
#
# The requirement is that an item's value is learned "in each scenario". Ante
# is the coarse scenario the primary cell already covers. Two more are free
# (RNG-free reads) and a purchase decision genuinely depends on them:
#
#   item|boss:<key>  the UPCOMING boss (the sim pre-selects it at shop entry and
#                   reveals it with the shop, exactly as the real game does). A
#                   boss that debuffs Faces changes what a face-card joker is
#                   worth BEFORE it is bought, which no per-item average can
#                   express.
#   item|hand:<type> the hand type this run is investing in, read from
#                   `game.planet_levels`. "This joker is worth more now that
#                   Flush is levelled" becomes a measured cell instead of an
#                   assertion in a curated table.
#
# These cells are pooled ACROSS antes on purpose: the shortfall is data, not
# resolution, and a 3-way grid (item x boss x ante) would fragment every cell
# below the evidence threshold the coverage audit enforces.
SCENARIO_PREFIXES = ("boss:", "hand:")


def boss_scenario(game: Any) -> str:
    """Upcoming boss key, or "" when the sim has not pre-selected one yet."""
    return str(getattr(game, "next_boss_key", "") or "")


def hand_scenario(game: Any) -> str:
    """The hand type the run is investing in, from planet levels.

    Returns "" while every hand is still at level 1: the argmax of an all-tie
    dict is an arbitrary alphabetical choice, and labelling a decision with a
    scenario the run has not actually chosen would manufacture cells out of
    nothing. Only a raised level means the run has declared a hand.
    """
    levels = getattr(game, "planet_levels", None)
    if not levels:
        return ""
    best = max(sorted(levels), key=lambda h: int(levels.get(h, 0) or 0))
    return best if int(levels.get(best, 0) or 0) > 1 else ""


def scenario_cells(game: Any, item_key: str) -> list[str]:
    """Item x scenario interaction cells for the live game object."""
    out: list[str] = []
    boss = boss_scenario(game)
    if boss:
        out.append(f"{item_key}|boss:{boss}")
    hand = hand_scenario(game)
    if hand:
        out.append(f"{item_key}|hand:{hand}")
    return out


def row_scenario_cells(row: dict) -> list[str]:
    """The same cells, rebuilt from a collected row (fit-time).

    Both callers must agree on the cell strings or train/serve skew becomes
    invisible, so the row carries exactly the two fields this reads and the
    names are built in one place (`scenario_cells` for the game, this for the
    row).
    """
    key = str(row.get("key", "") or "")
    if not key:
        return []
    out: list[str] = []
    boss = str(row.get("boss_key", "") or "")
    if boss:
        out.append(f"{key}|boss:{boss}")
    hand = str(row.get("hand_key", "") or "")
    if hand:
        out.append(f"{key}|hand:{hand}")
    return out


def cell_parents(cell: str) -> list[str]:
    """Hierarchy from a cell up to (but excluding) the root.

    ``item|a3|s1`` -> ``[item|a3, item, role:...]``
    ``item|a3``    -> ``[item, role:...]``
    ``item``       -> ``[role:...]``
    ``role:...``   -> ``[]``  (the root: the linear head stands alone)

    The role block is the last parent, so an item that was never offered still
    borrows strength from its spec type. A cell must never list itself as a
    parent — that would recurse forever in the shrinkage walk.
    """
    if cell.startswith("role:") or not cell:
        return []
    parts = cell.split("|")
    out: list[str] = []
    if len(parts) >= 3:
        out.append("|".join(parts[:2]))
    if len(parts) >= 2:
        out.append(parts[0])
    it = CAT.item(parts[0])
    if it is not None and it.roles:
        out.append("role:" + "+".join(sorted(it.roles)))
    return out


# ────────────────────────────────────────────────────────────────────────────
# Artifact
# ────────────────────────────────────────────────────────────────────────────


@dataclass
class Residual:
    n: float = 0.0
    total: float = 0.0


class ValueTable:
    """Frozen learned value snapshot. Read-only, pure-Python evaluation."""

    __slots__ = ("feature_order", "w", "b", "mu", "sd", "residuals",
                 "tau", "beta", "meta", "catalogue_fingerprint",
                 "resid_sd", "_index",
                 "w_rel", "b_rel", "residuals_rel", "tau_rel", "resid_sd_rel")

    def __init__(self, data: dict):
        if int(data.get("version", -1)) != MODEL_VERSION:
            raise ValueError(f"unsupported value-table version {data.get('version')}")
        self.feature_order: list[str] = list(data["feature_order"])
        self.w: list[float] = [float(x) for x in data["w"]]
        self.b: float = float(data.get("b", 0.0))
        self.mu: list[float] = [float(x) for x in data.get("mu", [])]
        self.sd: list[float] = [float(x) for x in data.get("sd", [])]
        self.residuals: dict[str, dict[str, float]] = data.get("residuals", {})
        self.tau: float = float(data.get("tau", 0.0))
        self.beta: float = float(data.get("beta", 0.0))
        self.meta: dict = data.get("meta", {})
        self.catalogue_fingerprint: str = str(
            data.get("catalogue_fingerprint", ""))
        # Global SD of the head's out-of-fold residuals. Fitted at fit time;
        # supplies the uncertainty floor for cells with little evidence.
        self.resid_sd: float = float(data.get("resid_sd", 0.0))
        # Relative head: the same regression fitted on labels CENTRED within
        # the decision. Choosing among the items in one shop is a within-shop
        # comparison, and the absolute head spends most of its capacity on
        # between-decision variation (how rich the run is) that is constant
        # across candidates and therefore irrelevant to the choice. Absent
        # (older artifacts) means "no relative head": callers fall back.
        self.w_rel: list[float] = [float(x) for x in data.get("w_rel", [])]
        self.b_rel: float = float(data.get("b_rel", 0.0))
        self.residuals_rel: dict[str, dict[str, float]] = data.get("residuals_rel", {})
        self.tau_rel: float = float(data.get("tau_rel", self.tau))
        self.resid_sd_rel: float = float(data.get("resid_sd_rel", self.resid_sd))
        self._index = {n: i for i, n in enumerate(self.feature_order)}

    @property
    def has_relative(self) -> bool:
        return bool(self.w_rel)

    # -- construction ------------------------------------------------------
    @classmethod
    def load(cls, path: Path | str | None = None) -> Optional["ValueTable"]:
        p = Path(path) if path else DEFAULT_PATH
        if not p.is_file():
            return None
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return None
        try:
            return cls(data)
        except Exception:
            return None

    # -- evaluation -------------------------------------------------------
    def _apply(self, feats: dict[str, float], w: list[float], b: float,
               cell: str, residuals: dict, tau: float) -> float:
        vec = build_vector(feats)
        z = b
        for name, wi in zip(self.feature_order, w):
            i = self._index[name]
            m = self.mu[i] if i < len(self.mu) else 0.0
            s = self.sd[i] if i < len(self.sd) else 1.0
            v = vec[i]
            z += wi * ((v - m) / s if s else v)
        if cell:
            z += self._shrunk_from(residuals, cell, tau)
        return z

    def linear(self, feats: dict[str, float]) -> float:
        return self._apply(feats, self.w, self.b, "", {}, 0.0)

    def relative(self, feats: dict[str, float], cell: str = "") -> float:
        """Within-decision value: how this candidate compares to its rivals.

        Falls back to the absolute head when no relative head is in the
        artifact, so an older model still loads.
        """
        if not self.has_relative:
            return self.value(feats, cell=cell)
        return self._apply(feats, self.w_rel, self.b_rel, cell,
                           self.residuals_rel, self.tau_rel)

    def scenario_term(self, game: Any, item_key: str, residuals=None,
                      tau: Optional[float] = None) -> float:
        """Sum of the item's scenario-cell corrections (boss, hand type).

        Read-only and hierarchy-aware, so an unmeasured scenario contributes
        exactly its parent's value and an unseen one contributes nothing.
        """
        res = self.residuals if residuals is None else residuals
        t = self.tau if tau is None else tau
        if not res:
            return 0.0
        total = 0.0
        for c in scenario_cells(game, item_key):
            if c in res:
                total += self._shrunk_from(res, c, t)
        return total

    def relative_of(self, game: Any, item: Any, ref=None) -> float:
        key = str(getattr(item, "key", "") or "")
        feats = decision_features(game, item, ref=ref)
        return (self.relative(feats, cell=cell_key(game, key))
                + self.scenario_term(game, key, self.residuals_rel,
                                     self.tau_rel))

    def relative_stderr(self, cell: str) -> float:
        n = self.own_n(cell, self.residuals_rel)
        sd = self.resid_sd_rel or self.resid_sd
        if n <= 0.0:
            return sd
        return sd / math.sqrt(n)

    @staticmethod
    def _shrunk_from(residuals: dict, cell: str, tau: float) -> float:
        """Recursive count-based shrinkage up the cell hierarchy.

        The root value is 0.0 because the linear head already supplies the
        global level; residuals are corrections, so they must vanish when
        unseen. Static so the fitter can evaluate candidate `tau` values
        against the holdout without building a table object.
        """
        parent_val = 0.0
        for p in cell_parents(cell):
            if p in residuals:
                parent_val = ValueTable._shrunk_from(residuals, p, tau)
                break
        row = residuals.get(cell)
        if row is None:
            return parent_val
        n = float(row.get("n", 0.0))
        total = float(row.get("total", 0.0))
        if n <= 0.0:
            return parent_val
        denom = n + tau
        if denom <= 0.0:
            return total / n
        return (total + tau * parent_val) / denom

    def _shrunk(self, cell: str, _seen: Optional[set] = None) -> float:
        return ValueTable._shrunk_from(self.residuals, cell, self.tau)

    def residual(self, cell: str) -> float:
        return self._shrunk(cell)

    def effective_n(self, cell: str, residuals: Optional[dict] = None) -> float:
        """Sample count backing this cell, walking up until evidence exists.

        A brand-new item falls back to its role block and then to zero, which
        is what makes the confidence test below conservative for unseen items
        instead of quietly confident.
        """
        res = self.residuals if residuals is None else residuals
        for c in [cell, *cell_parents(cell)]:
            row = res.get(c)
            if row and float(row.get("n", 0.0)) > 0.0:
                return float(row["n"])
        return 0.0

    def own_n(self, cell: str, residuals: Optional[dict] = None) -> float:
        """Evidence about *this item* — role pooling deliberately excluded.

        `effective_n` walks the whole hierarchy including the role block, which
        is correct for *shrinkage* (borrowing strength to form an estimate) but
        wrong for *confidence*. A role like `role:economy` pools ~445 rows
        across dozens of unrelated jokers, so inheriting it collapses the
        standard error to ~0.15 and lets the oracle act with no evidence about
        the item in front of it at all. Measured: that is exactly how the first
        V12 oracle came to accept 17 of 51 offers and behave like an unfiltered
        override.

        So confidence is measured on the finest evidence that exists for the
        item itself: its own cell, else its item-level row, else none.
        """
        res = self.residuals if residuals is None else residuals
        item_cell = cell.split("|")[0] if cell else ""
        for c in (cell, item_cell):
            if not c:
                continue
            row = res.get(c)
            if row and float(row.get("n", 0.0)) > 0.0:
                return float(row["n"])
        return 0.0

    def cell_stderr(self, cell: str) -> float:
        """Standard error of the value estimate in this cell.

        se = sd_out_of_fold / sqrt(n) where n is `own_n` — the evidence about
        this item, not its category. With no evidence at all this is the whole
        residual spread, so an unsupported candidate must show a large effect
        before the oracle will act: the cheap, data-derived confidence gate.
        """
        n = self.own_n(cell)
        if n <= 0.0:
            return self.resid_sd
        return self.resid_sd / math.sqrt(n)

    def beats(self, game: Any, item_a: Any, item_b: Any, z: float,
              ref=None, head: str = "relative") -> tuple[bool, float, float]:
        """Paired comparison: does A beat B by more than the noise in both?

        Buying A instead of B is a *contrast*, so its uncertainty is the sum of
        the two estimates' variances rather than either alone:

            act if value(A) - value(B) > z * sqrt(se_A^2 + se_B^2)

        This is the rule an override needs. An absolute test ("is A worth
        buying?") cannot express "A is better than the thing the heuristic was
        about to buy", and on the same candidate set the two disagree sharply.
        """
        cell_a = cell_key(game, str(getattr(item_a, "key", "") or ""))
        cell_b = cell_key(game, str(getattr(item_b, "key", "") or ""))
        # Within one shop, the between-decision level is shared by both items,
        # so it cancels in the contrast. The relative head was fitted on
        # exactly that demeaned target and measures better for choosing between
        # candidates (top-1 0.527 with context-matched delta +0.198) than the
        # absolute head (0.499, +0.011). Default to it for comparisons.
        use_rel = (head == "relative" and self.has_relative)
        score = self.relative_of if use_rel else self.value_of
        se_fn = self.relative_stderr if use_rel else self.cell_stderr
        va = score(game, item_a, ref=ref)
        vb = score(game, item_b, ref=ref)
        se_a = se_fn(cell_a)
        se_b = se_fn(cell_b)
        margin = va - vb
        se_d = math.sqrt(se_a * se_a + se_b * se_b)
        return (margin > z * se_d), margin, se_d

    def significant(self, game: Any, item: Any, z: float, ref=None) -> tuple[bool, float, float]:
        """(act?, value, stderr) — act only when value clears z standard errors.

        `z` is the only free number here and it is declared, not tuned: z=1
        means "one standard error", i.e. act only when the learned effect is
        larger than the noise in its own estimate.
        """
        key = str(getattr(item, "key", "") or "")
        cell = cell_key(game, key)
        v = self.value_of(game, item, ref=ref)
        se = self.cell_stderr(cell)
        return (v > z * se), v, se

    def value(self, feats: dict[str, float], cell: str = "") -> float:
        v = self.linear(feats)
        if cell:
            v += self.residual(cell)
        return v

    def value_of(self, game: Any, item: Any, ref=None) -> float:
        key = str(getattr(item, "key", "") or "")
        feats = decision_features(game, item, ref=ref)
        return (self.value(feats, cell=cell_key(game, key))
                + self.scenario_term(game, key))

    def rank(self, game: Any, items: Iterable[Any], ref=None,
             head: str = "absolute") -> list[tuple[int, float]]:
        """Score candidate indices, best first (used by the agent hook).

        `head="relative"` ranks by the within-decision head, which is the one
        fitted for exactly this comparison.
        """
        score = self.relative_of if head == "relative" else self.value_of
        scored = [(int(getattr(it, "_idx", i)), score(game, it, ref=ref))
                  for i, it in enumerate(items)]
        return sorted(scored, key=lambda kv: kv[1], reverse=True)

    def fingerprint(self) -> str:
        import hashlib
        h = hashlib.sha256()
        h.update(json.dumps(self.residuals, sort_keys=True).encode())
        h.update(json.dumps(self.w).encode())
        h.update(f"{self.b}{self.tau}{self.beta}".encode())
        return h.hexdigest()[:16]


def load(path: Path | str | None = None) -> Optional[ValueTable]:
    return ValueTable.load(path)


# ────────────────────────────────────────────────────────────────────────────
# Writer (used by tools/fit_value_model.py)
# ────────────────────────────────────────────────────────────────────────────


def dump(path: Path | str, table_data: dict) -> Path:
    p = Path(path)
    p.write_text(json.dumps(table_data, indent=1, sort_keys=True) + "\n",
                 encoding="utf-8")
    return p
