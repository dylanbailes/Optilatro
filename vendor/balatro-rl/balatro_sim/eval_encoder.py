from __future__ import annotations

import math
from collections import Counter
from numbers import Real

from . import catalogue as CAT
from .constants import SUITS
from .game import BOSS_BLINDS, State, _HAND_TYPE_ORDER


VERSION = 1
EDITIONS = ("None", "Foil", "Holographic", "Polychrome", "Negative")
ENHANCEMENTS = ("None", "Bonus", "Mult", "Wild", "Glass", "Steel", "Stone", "Gold", "Lucky")
SEALS = ("None", "Gold", "Red", "Blue", "Purple")
JOKER_STATE_FIELDS = (
    "active", "blinds", "bonus", "chips", "count", "deck_nines", "destroy_random",
    "destroy_right", "destroyed", "discarded", "discards_left", "dollars",
    "extra_hands", "fired", "free_reroll", "gold_played", "hands", "mult",
    "pending_money", "pending_shop_buff", "rank", "rebate_rank", "rounds",
    "sell_value", "sold", "streak", "used", "xmult", "zero_discards",
)
FLAT_JOKER_SLOTS = 5
JOKER_KEYS = CAT.keys("joker")
CONSUMABLE_KEYS = tuple(sorted(CAT.keys("tarot") + CAT.keys("planet") + CAT.keys("spectral")))
VOUCHER_KEYS = CAT.keys("voucher")
if not JOKER_KEYS or not CONSUMABLE_KEYS or not VOUCHER_KEYS:
    raise RuntimeError("V14 encoder requires the generated item catalogue")

CARD_NAMES = (
    ("flipped", "debuffed", "bonus_chips", "forced")
    + tuple(f"rank_{r}" for r in range(2, 15))
    + tuple(f"suit_{s}" for s in SUITS)
    + tuple(f"enhancement_{e}" for e in ENHANCEMENTS)
    + tuple(f"edition_{e}" for e in EDITIONS)
    + tuple(f"seal_{s}" for s in SEALS)
)
KNOWN_NONSCALAR_JOKER_STATE = ("suit", "target", "hand", "played_hands", "counts", "most_played", "planet_upgrade")
JOKER_NAMES = (
    ("slot", "flipped", "debuffed")
    + tuple(f"edition_{e}" for e in EDITIONS)
    + tuple(f"key_{k}" for k in JOKER_KEYS)
    + ("unknown_key",)
    + tuple(f"spec_{name}" for name in CAT.FEATURE_NAMES)
    + tuple(name for field in JOKER_STATE_FIELDS for name in (f"state_{field}", f"missing_state_{field}"))
    + tuple(f"target_suit_{s}" for s in SUITS)
    + ("missing_target_suit",)
    + tuple(f"target_hand_{h}" for h in _HAND_TYPE_ORDER)
    + ("missing_target_hand", "played_hands_count", "unknown_state_count")
)
CONTEXT_SCALARS = (
    "ante", "blind_idx", "chips_scored", "hands_left", "discards_left", "dollars",
    "hand_size", "hand_size_mod", "base_hands", "base_discards", "joker_slots",
    "consumable_slots", "interest_cap", "run_hands_played", "run_unused_discards",
    "skipped_blinds", "verdant_debuff", "boss_disabled_override", "jokers_flipped",
)
CONTEXT_NAMES = (
    CONTEXT_SCALARS
    + ("chips_target", "hand_count", "joker_count")
    + tuple(f"phase_{s.name}" for s in State)
    + tuple(f"blind_kind_{s}" for s in ("Small", "Big", "Boss"))
    + tuple(f"boss_{key}" for key in BOSS_BLINDS)
    + tuple(f"boss_flag_{name}" for name in CAT.BOSS_FLAGS)
    + tuple(f"{pile}_{name}" for pile in ("total", "undrawn", "spent") for name in ("count",) + CARD_NAMES)
    + tuple(f"{prefix}_{hand}" for prefix in ("level", "run_count", "round_played", "last_played") for hand in _HAND_TYPE_ORDER)
    + tuple(f"consumable_{key}" for key in CONSUMABLE_KEYS)
    + ("consumable_unknown_count",)
    + tuple(f"consumable_spec_{name}" for name in CAT.FEATURE_NAMES)
    + tuple(f"voucher_{key}" for key in VOUCHER_KEYS)
    + ("voucher_unknown_count",)
    + tuple(f"voucher_spec_{name}" for name in CAT.FEATURE_NAMES)
)
FLAT_NAMES = (
    CONTEXT_NAMES
    + ("cards_count",)
    + tuple(f"cards_{op}_{name}" for op in ("sum", "mean", "max") for name in CARD_NAMES)
    + ("jokers_count",)
    + tuple(f"joker_slot_{slot}_{name}" for slot in range(FLAT_JOKER_SLOTS) for name in JOKER_NAMES)
    + tuple(f"joker_overflow_{op}_{name}" for op in ("sum", "slot_weighted_sum") for name in JOKER_NAMES)
)


def schema() -> dict:
    return {
        "version": VERSION,
        "name": "v14_observable_inblind",
        "context_dim": len(CONTEXT_NAMES),
        "card_dim": len(CARD_NAMES),
        "joker_dim": len(JOKER_NAMES),
        "flat_dim": len(FLAT_NAMES),
        "context_names": list(CONTEXT_NAMES),
        "card_names": list(CARD_NAMES),
        "joker_names": list(JOKER_NAMES),
        "flat_names": list(FLAT_NAMES),
        "joker_state_fields": list(JOKER_STATE_FIELDS),
        "flat_joker_slots": FLAT_JOKER_SLOTS,
        "catalogue_fingerprint": CAT.fingerprint(),
        "limitations": [
            "Raw numeric features; no score forecast or future shop/boss identity.",
            "Composition uses marginal sums, not full cross-attribute card multisets.",
            "Flipped entities contribute only visibility/count; joker slot remains observable.",
            "Only name-allowlisted numeric joker state is represented; unknown_state_count includes nonnumeric fields such as suit, target, counts and played_hands.",
            "Per-card run history keyed by runtime IDs is omitted; run/round hand-type history is retained.",
            "Hand tokens are a set; held-card ordering is not represented.",
            "Flat controls pool cards and preserve five explicit joker slots; overflow uses sum and slot-weighted sum, which cannot preserve arbitrary joker interactions/order.",
            "Current shop, tag queues and consumable-use history are outside this in-blind encoder.",
        ],
    }


def _number(value, name: str) -> float:
    if not isinstance(value, Real):
        raise ValueError(f"{name} must be numeric and finite")
    try:
        number = float(value)
    except (ValueError, OverflowError) as exc:
        raise ValueError(f"{name} must be finite") from exc
    if not math.isfinite(number):
        raise ValueError(f"{name} must be finite")
    return number


def _check_nested(value, name: str) -> None:
    if isinstance(value, Real):
        _number(value, name)
    elif isinstance(value, str):
        pass
    elif isinstance(value, dict):
        for key, item in value.items():
            _check_nested(item, f"{name}.{key}")
    elif isinstance(value, (list, tuple, set, frozenset)):
        for item in value:
            _check_nested(item, name)


def _one_hot(value, choices, name: str) -> list[float]:
    if value not in choices:
        raise ValueError(f"unknown {name}: {value!r}")
    return [float(value == choice) for choice in choices]


def _card_row(card, forced=None) -> list[float]:
    flipped = _number(getattr(card, "flipped", False), "card.flipped")
    if flipped:
        return [1.0] + [0.0] * (len(CARD_NAMES) - 1)
    return (
        [0.0, _number(card.debuffed, "card.debuffed"),
         _number(getattr(card, "bonus_chips", 0), "card.bonus_chips"), float(card is forced)]
        + _one_hot(_number(card.rank, "card.rank"), range(2, 15), "card.rank")
        + _one_hot(card.suit, SUITS, "card.suit")
        + _one_hot(card.enhancement, ENHANCEMENTS, "card.enhancement")
        + _one_hot(card.edition, EDITIONS, "card.edition")
        + _one_hot(card.seal, SEALS, "card.seal")
    )


def _sum_rows(rows, width: int) -> list[float]:
    return [math.fsum(row[i] for row in rows) for i in range(width)]


def _joker_row(joker, slot: int, flipped: bool) -> list[float]:
    if flipped or _number(getattr(joker, "flipped", False), "joker.flipped"):
        return [float(slot), 1.0] + [0.0] * (len(JOKER_NAMES) - 2)
    state = joker.state
    _check_nested(state, "joker.state")
    row = (
        [float(slot), 0.0, _number(getattr(joker, "debuffed", False), "joker.debuffed")]
        + _one_hot(joker.edition, EDITIONS, "joker.edition")
        + [float(joker.key == key) for key in JOKER_KEYS]
        + [float(joker.key not in JOKER_KEYS)]
        + [CAT.item_features(joker.key)[name] for name in CAT.FEATURE_NAMES]
    )
    for name in JOKER_STATE_FIELDS:
        missing = name not in state or state[name] is None
        row.extend([0.0 if missing else _number(state[name], f"joker.state.{name}"), float(missing)])
    suit = state.get("suit")
    if suit in SUITS:
        row.extend([float(suit == s) for s in SUITS] + [0.0])
    else:
        row.extend([0.0] * len(SUITS) + [1.0])
    target_hand = state.get("target") or state.get("hand")
    if target_hand in _HAND_TYPE_ORDER:
        row.extend([float(target_hand == h) for h in _HAND_TYPE_ORDER] + [0.0])
    else:
        row.extend([0.0] * len(_HAND_TYPE_ORDER) + [1.0])
    played = state.get("played_hands")
    played_count = float(len(played)) if isinstance(played, (set, list, tuple)) else 0.0
    row.append(played_count)
    known = set(JOKER_STATE_FIELDS) | set(KNOWN_NONSCALAR_JOKER_STATE)
    row.append(float(sum(name not in known for name in state)))
    return row


def _item_context(items, keys) -> list[float]:
    counts = Counter(item if isinstance(item, str) else item.key for item in items)
    vectors = [[CAT.item_features(key)[name] * count for name in CAT.FEATURE_NAMES] for key, count in sorted(counts.items())]
    return (
        [float(counts[key]) for key in keys]
        + [float(sum(count for key, count in counts.items() if key not in keys))]
        + _sum_rows(vectors, len(CAT.FEATURE_NAMES))
    )


def encode_state(game) -> dict:
    forced = getattr(game, "bell_card", None)
    cards = [_card_row(card, forced) for card in game.hand]
    undrawn = [_card_row(card, forced) for card in game.deck]
    spent = [_card_row(card, forced) for card in game.spent]
    flipped = bool(_number(game.jokers_flipped, "jokers_flipped"))
    jokers = [_joker_row(joker, slot, flipped) for slot, joker in enumerate(game.jokers)]
    blind = game.current_blind
    context = [_number(getattr(game, name, 0), name) for name in CONTEXT_SCALARS]
    context += [_number(blind.chips_target, "chips_target"), float(len(cards)), float(len(jokers))]
    context += _one_hot(game.state, tuple(State), "phase")
    context += _one_hot(blind.kind, ("Small", "Big", "Boss"), "blind.kind")
    boss = blind.boss_key if blind.is_boss else ""
    context += [float(boss == key) for key in BOSS_BLINDS]
    flags = CAT.boss_features(boss)
    context += [flags.get(name, 0.0) for name in CAT.BOSS_FLAGS]
    for rows in (undrawn + cards + spent, undrawn, spent):
        context += [float(len(rows))] + _sum_rows(rows, len(CARD_NAMES))
    context += [_number(game.planet_levels.get(hand, 1), f"level_{hand}") for hand in _HAND_TYPE_ORDER]
    context += [_number(game.run_hand_counts.get(hand, 0), f"run_count_{hand}") for hand in _HAND_TYPE_ORDER]
    context += [float(hand in game.played_hand_types_this_round) for hand in _HAND_TYPE_ORDER]
    context += [float(hand == game.last_hand_played) for hand in _HAND_TYPE_ORDER]
    context += _item_context(game.consumable_hand, CONSUMABLE_KEYS)
    context += _item_context(game.vouchers, VOUCHER_KEYS)
    encoded = {"context": context, "cards": cards, "jokers": jokers}
    validate_state(encoded)
    return encoded


def validate_state(state: dict) -> None:
    for key, width in (("context", len(CONTEXT_NAMES)), ("cards", len(CARD_NAMES)), ("jokers", len(JOKER_NAMES))):
        rows = [state[key]] if key == "context" else state[key]
        for row in rows:
            if len(row) != width:
                raise ValueError(f"{key} row width must be {width}, got {len(row)}")
            for value in row:
                _number(value, key)
    slots = [row[0] for row in state["jokers"]]
    if len(set(slots)) != len(slots) or any(slot < 0 or slot != int(slot) for slot in slots):
        raise ValueError("joker slots must be distinct nonnegative integers")


def flatten_state(state: dict) -> list[float]:
    validate_state(state)
    cards, jokers = state["cards"], state["jokers"]
    total = _sum_rows(cards, len(CARD_NAMES))
    flat = list(state["context"]) + [float(len(cards))] + total
    flat += [value / max(1, len(cards)) for value in total]
    flat += [max((row[i] for row in cards), default=0.0) for i in range(len(CARD_NAMES))]
    flat += [float(len(jokers))]
    slots = {int(row[0]): row for row in jokers}
    for slot in range(FLAT_JOKER_SLOTS):
        flat += slots.get(slot, [0.0] * len(JOKER_NAMES))
    overflow = [row for row in jokers if row[0] >= FLAT_JOKER_SLOTS]
    flat += _sum_rows(overflow, len(JOKER_NAMES))
    flat += _sum_rows([[value * (row[0] + 1) for value in row] for row in overflow], len(JOKER_NAMES))
    return [_number(value, "flat") for value in flat]
