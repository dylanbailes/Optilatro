"""state_value.py — portfolio-aware state encoding for the V13 state-value model.

WHY A SECOND ENCODER EXISTS
===========================
`value_tables.decision_features` scores a **candidate in a context**: item fields,
context fields, and their pre-generated products. That is the right shape for
"is this item good here", and it structurally cannot express "this joker is worth
four times as much next to the one I already own", because the owned portfolio
enters it only through aggregate counts (`n_jokers`, `joker_slots_free`).

That gap is measured, not assumed. On 10,534 training rows a gradient-boosted
model over the 161 decision features reached concordance **0.549 on its own
training data** (0.527 held out) — a flexible model cannot separate the pairs
even when allowed to memorise them, and 48% of the pairs the shipped oracle
weighs are exactly equivalent. Both facts say the unit of learning is wrong.

V13 scores **states**. The difference is the set encoder below: every owned joker
is encoded with the same spec-derived vector the catalogue already produces, and
those vectors are pooled — sum, max and mean — so a model can learn an
interaction the moment the pool contains it. No synergy table, no typed
threshold: the interaction weights are learned, and the vocabulary is parsed from
the spec.

RNG-FREE AND SHARED
===================
Exactly the discipline `decision_features` follows: pure reads of the game
object, one implementation used by collection and (later) by the runtime, no
mutation, no RNG. The feature *layout* is not hardcoded either — features are a
dict, and the ordered key list is frozen into the fitted artifact, so adding an
item to the catalogue extends the encoding instead of silently shifting a column.
"""
from __future__ import annotations

import math
from typing import Any, Optional

from . import catalogue as CAT
from . import value_tables as VT
from . import constants as CONST

# Pooling prefixes. `pf_` = owned jokers, `cn_` = consumables held, `vo_` =
# owned vouchers. Three pools rather than one because they differ in kind: a
# joker occupies a scoring slot, a consumable is a one-shot, and a voucher is a
# permanent rule change.
_JOKER_PREFIX = "pf_"
_CONSUMABLE_PREFIX = "cn_"
_VOUCHER_PREFIX = "vo_"

# THE single source of truth for which reductions each pool produces. Both the
# encoder and `layout_keys` read this table, which is what makes the layout
# complete by construction. The alternative -- a hardcoded name list beside a
# hardcoded emission -- is exactly how 46 `vo_max_*` columns (11% of the layout)
# were silently dropped for every state that owned a voucher: `layout_keys`
# declared the voucher pool with no reductions while `_pool` emitted `max`
# unconditionally. Measured at 463,450 dropped feature instances over one 500-seed
# collection, with no error, because dropping is a counter rather than a raise.
_POOL_OPS: dict[str, tuple[str, ...]] = {
    _JOKER_PREFIX: ("max", "mean"),
    _CONSUMABLE_PREFIX: ("max", "mean"),
    _VOUCHER_PREFIX: ("max",),
}


def _num(v: Any) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return 0.0
    return f if f == f and abs(f) != float("inf") else 0.0


def _entity_vector(game: Any, item: Any) -> Optional[dict]:
    """The catalogue's SPEC vector for one owned entity. Fixed width, by design.

    Deliberately does **not** merge `item_live_features` into the pooled vector.
    That function adds a key conditionally (`own_hand_level`, only for planets),
    so pooling it makes the key set depend on which items a run happened to own —
    and a layout that depends on the data cannot be frozen before collection.
    Measured: a one-run layout probe dropped 2,139 feature instances from a
    single 8-run smoke batch, i.e. silently lost real signal.

    The live observations that matter for scaling entities are added instead as
    explicit, item-independent aggregates in `state_features`. `CAT.item_features`
    without `present` returns exactly `CAT.FEATURE_NAMES`, so every pooled name is
    catalogue-derived and the layout is a function of the spec, not of the data.
    """
    try:
        return CAT.item_features(str(getattr(item, "key", "") or ""))
    except Exception:
        return None


def pooled_names(prefix: str) -> list[str]:
    """The pooled feature names this prefix can produce — derived, never listed.

    Reads `_POOL_OPS`, the same table `_pool` emits from, so the layout cannot
    disagree with the encoder about which columns exist.
    """
    ops = _POOL_OPS.get(prefix, ())
    names = [f"{prefix}sum_{k}" for k in CAT.FEATURE_NAMES]
    if "max" in ops:
        names += [f"{prefix}max_{k}" for k in CAT.FEATURE_NAMES]
    if "mean" in ops:
        names += [f"{prefix}mean_{k}" for k in CAT.FEATURE_NAMES]
    return names + [f"{prefix}n"]


def live_aggregate_names(prefix: str = _JOKER_PREFIX) -> list[str]:
    """Item-independent live aggregates over the pool (see `_pool_live`)."""
    return [f"{prefix}{k}" for k in _LIVE_AGGREGATES]


# Aggregate names for live observations over a pool. Fixed vocabulary on purpose:
# these are the quantities that make two copies of the same key distinguishable
# (what a scaling entity has accumulated, what it would sell for, whether it is
# editioned), and they must not vary with which items are owned.
_LIVE_AGGREGATES = ("sell_total", "sell_max", "editioned", "negative",
                    "owned_total")


def _live_of(item: Any) -> tuple[float, int, int]:
    """(sell value, is editioned, is negative) for one owned entity."""
    try:
        sell = float(getattr(item, "sell", 0) or 0)
    except (TypeError, ValueError):
        sell = 0.0
    edition = str(getattr(item, "edition", "None") or "None")
    return sell, int(edition != "None"), int(edition == "Negative")


def _pool_live(items: list, prefix: str, out: dict) -> None:
    """Pool the item-independent live observations of owned entities."""
    if not items:
        return
    sells, editioned, negative = [], 0, 0
    for it in items:
        sell, ed, neg = _live_of(it)
        sells.append(sell)
        editioned += ed
        negative += neg
    out[f"{prefix}sell_total"] = float(sum(sells))
    out[f"{prefix}sell_max"] = float(max(sells)) if sells else 0.0
    out[f"{prefix}editioned"] = float(editioned)
    out[f"{prefix}negative"] = float(negative)
    out[f"{prefix}owned_total"] = float(len(items))


def _pool(vecs: list[dict], prefix: str, out: dict) -> None:
    """Permutation-invariant pooling of entity vectors into `out`.

    Sum carries "how much of this effect do I own in total" (and doubles as a
    count for indicator fields), max carries "do I own any of it at all", and
    mean carries "is this effect concentrated or diluted across my slots". A
    model over these can express both portfolio-level and per-slot effects; the
    order of the entities is irrelevant by construction.

    Emits exactly `pooled_names(prefix)`, read from the same `_POOL_OPS` table --
    see the note there for the bug that convention prevents.
    """
    if not vecs:
        return
    ops = _POOL_OPS.get(prefix, ())
    keys = sorted({k for v in vecs for k in v})
    n = float(len(vecs))
    for k in keys:
        vals = [_num(v.get(k, 0.0)) for v in vecs]
        out[f"{prefix}sum_{k}"] = sum(vals)
        if "max" in ops:
            out[f"{prefix}max_{k}"] = max(vals)
        if "mean" in ops:
            out[f"{prefix}mean_{k}"] = sum(vals) / n
    out[f"{prefix}n"] = n


def state_features(game: Any, ref: Any = None) -> dict[str, float]:
    """Encode a game state for the value model. Pure reads, never raises.

    Blocks, in the order they are added:

    * ``st_*``  the item-independent context — the same block `decision_features`
      already uses (ante, blind kind, target, projected power and its ratio to
      the target, dollars, slots, deck size, boss flags). Reused rather than
      re-derived, so the two encoders can never disagree about the same quantity.
    * ``pf_*``  the owned joker portfolio, pooled (the set encoder).
    * ``cn_*``  consumables held, pooled, plus a count per kind.
    * ``vo_*``  owned vouchers, pooled — permanent rule changes.
    * ``deck_*`` deck composition: suit and rank histograms, and the derived
      concentration/fixability quantities that decide whether a straight or
      flush plan is even reachable.
    * ``hlvl_*`` hand levels from the game's own `planet_levels` dict, plus
      summary statistics. This is the "what am I investing in" signal.
    * ``phase_*`` which of the sim's own states we are in, so the model can tell
      a shop apart from a blind.
    """
    feats: dict[str, float] = {}

    # ── context (item-independent) ──────────────────────────────────────────
    # `scenario_features` takes an item key for the item-conditional parts; the
    # block it returns here is the item-independent one, and passing "" is the
    # explicit way to ask for exactly that.
    try:
        for k, v in VT.scenario_features(game, "", ref=ref).items():
            feats[f"st_{k}"] = _num(v)
    except Exception:
        pass

    # ── owned jokers ────────────────────────────────────────────────────────
    jokers = list(getattr(game, "jokers", []) or [])
    _pool([v for v in (_entity_vector(game, j) for j in jokers) if v],
          _JOKER_PREFIX, feats)
    _pool_live(jokers, _JOKER_PREFIX, feats)

    # ── consumables held ────────────────────────────────────────────────────
    consum = list(getattr(game, "consumable_hand", []) or [])
    _pool([v for v in (_entity_vector(game, c) for c in consum) if v],
          _CONSUMABLE_PREFIX, feats)
    _pool_live(consum, _CONSUMABLE_PREFIX, feats)
    for c in consum:
        kind = str(getattr(c, "kind", "") or "")
        if kind:
            feats[f"cn_kind_{kind}"] = feats.get(f"cn_kind_{kind}", 0.0) + 1.0

    # ── vouchers ────────────────────────────────────────────────────────────
    vouchers = list(getattr(game, "vouchers", []) or [])
    if vouchers and not isinstance(vouchers[0], str):
        vecs = [v for v in (_entity_vector(game, x) for x in vouchers) if v]
    else:
        vecs = [CAT.item_features(str(k)) for k in vouchers]
    _pool(vecs, _VOUCHER_PREFIX, feats)

    # ── deck composition ────────────────────────────────────────────────────
    deck = list(getattr(game, "full_deck", []) or [])
    if deck:
        n = float(len(deck))
        suit_counts = {s: 0.0 for s in CONST.SUITS}
        rank_counts = {r: 0.0 for r in CONST.RANKS}
        enh = seal = face = editioned = 0.0
        for c in deck:
            suit = str(getattr(c, "suit", "") or "")
            if suit in suit_counts:
                suit_counts[suit] += 1.0
            rank = int(getattr(c, "rank", 0) or 0)
            if rank in rank_counts:
                rank_counts[rank] += 1.0
            if str(getattr(c, "enhancement", "None") or "None") != "None":
                enh += 1.0
            if str(getattr(c, "seal", "None") or "None") != "None":
                seal += 1.0
            if str(getattr(c, "edition", "None") or "None") != "None":
                editioned += 1.0
            try:
                face += 1.0 if c.is_face_card() else 0.0
            except Exception:
                pass
        for s, v in suit_counts.items():
            feats[f"deck_suit_{s}"] = v / n
        for r, v in rank_counts.items():
            feats[f"deck_rank_{r}"] = v / n
        # How concentrated the deck is, i.e. how close a suit/rank plan is to
        # being playable. Derived from the histogram above, not from a threshold.
        feats["deck_suit_top_frac"] = (max(suit_counts.values()) / n
                                       if suit_counts else 0.0)
        feats["deck_rank_top_frac"] = (max(rank_counts.values()) / n
                                       if rank_counts else 0.0)
        entropy = 0.0
        for v in suit_counts.values():
            p = v / n
            if p > 0:
                entropy -= p * math.log(p)
        feats["deck_suit_entropy"] = entropy
        feats["deck_enh_frac"] = enh / n
        feats["deck_seal_frac"] = seal / n
        feats["deck_edition_frac"] = editioned / n
        feats["deck_face_frac"] = face / n

    # ── hand levels: the run's declared investment ───────────────────────────
    levels = getattr(game, "planet_levels", None) or {}
    for hand in sorted(levels):
        feats[f"hlvl_{hand}"] = _num(levels.get(hand, 1))
    if levels:
        vals = [_num(v) for v in levels.values()]
        feats["hlvl_sum"] = sum(vals)
        feats["hlvl_max"] = max(vals)
        feats["hlvl_mean"] = sum(vals) / float(len(vals))

    # ── phase and immediate resources ───────────────────────────────────────
    try:
        feats[f"phase_{game.state.name}"] = 1.0
    except Exception:
        pass
    for attr in ("hands_left", "discards_left", "chips_scored", "blind_idx",
                 "reroll_cost", "shop_discount"):
        if hasattr(game, attr):
            feats[f"live_{attr}"] = _num(getattr(game, attr, 0))
    return feats


def layout_keys(probe_feats: dict, hand_types: list[str] | None = None) -> list[str]:
    """The complete layout, for a probe state, PLUS everything the spec can add.

    A layout taken from observed features alone is incomplete: pooled names depend
    on the pool being non-empty, `st_boss_*` depends on which boss is coming, and a
    probe run simply may not contain every item. This function closes that gap by
    adding the catalogue-derived pool vocabulary (`pooled_names`), the live
    aggregates, and every boss flag the catalogue knows, so a state can never
    contain a name outside the layout. Missing names read as 0, which is the
    correct encoding for "this entity/flag is not present".
    """
    keys: set[str] = set(probe_feats or {})
    for prefix in (_JOKER_PREFIX, _CONSUMABLE_PREFIX, _VOUCHER_PREFIX):
        keys.update(pooled_names(prefix))
    keys.update(live_aggregate_names(_JOKER_PREFIX))
    keys.update(live_aggregate_names(_CONSUMABLE_PREFIX))
    for flag in CAT.BOSS_FLAGS:
        keys.add(f"st_boss_{flag}")
    for kind in CAT.KINDS:
        keys.add(f"cn_kind_{kind}")
    for hand in (hand_types or []):
        keys.add(f"hlvl_{hand}")
    return sorted(keys)


def encode(feats: dict, layout: list[str]) -> list[float]:
    """Project a feature dict onto a frozen layout (missing keys read as 0)."""
    return [_num(feats.get(k, 0.0)) for k in layout]
