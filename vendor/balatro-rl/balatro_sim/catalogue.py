"""catalogue.py — the single spec-derived source of truth for every item.

WHY
===
The policy stack currently re-types the same knowledge four times:

  * ``agent_v9.py``      — SCALING_JOKERS / ECONOMY_JOKERS / XMULT_JOKERS / ...
  * ``agent_v10.py``     — RELIABLE_XMULT_JOKERS / DEAD_ECONOMY_JOKERS / ...
  * ``tools/portfolio.py`` — CHIPS_JOKERS / FLAT_MULT_JOKERS / ...
  * ``agent_v11.py``     — LATE_CONVERT_KEEP / HAND_SPECIFIC_JOKERS

These copies have already drifted (``j_business`` is simultaneously an
"economy" and a "dead economy" joker). Every one of them is a hand-derivation
of data the repo already generates into JSON.

This module replaces all of them with ONE table whose fields come from files,
never from a human typing a set literal:

  * ``tools/joker_spec.json``       — 150 jokers: type, timing, effect, cost
  * ``tools/consumable_spec.json``  — 22 tarots, 18 spectrals, 12 planets, 32 vouchers
  * ``tools/boss_spec.json``        — 28 bosses: effect, finisher, min_ante, scaling
  * ``tools/tag_spec.json``         — 24 tags: kind, ante, pack grant
  * ``balatro_sim/shop.py``         — JOKER_CATALOGUE / BOOSTER_CATALOGUE
                                      (rarity + price, i.e. what the shop
                                      actually charges — the authority)

Those JSONs are themselves generated from
``docs/reference/balatro-mechanics.md`` by ``tools/gen_*_spec.py``, so the
chain of custody is: mechanics sheet -> generated spec -> catalogue -> model.

NO TUNING CONSTANTS
===================
Nothing here is tuned. A field is either (a) copied straight from a spec file,
or (b) derived from an effect string by a named, documented rule below. Role
classification is a *feature* handed to the learned model, not a verdict the
model must obey — a misclassified item costs nothing but a slightly worse
prior, because the model also carries a per-item residual term.

If the spec files are absent (standalone vendored use, minimal CI checkout),
``available()`` returns False and this module degrades to an empty catalogue.
Callers must fall back rather than crash.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional

# ────────────────────────────────────────────────────────────────────────────
# Spec location
# ────────────────────────────────────────────────────────────────────────────

SPEC_FILES = {
    "joker": "joker_spec.json",
    "consumable": "consumable_spec.json",
    "boss": "boss_spec.json",
    "tag": "tag_spec.json",
}

_ENV_SPEC_DIR = "OPTILATRO_SPEC_DIR"


def _find_spec_dir() -> Optional[Path]:
    """Locate the generated spec directory.

    Priority: ``$OPTILATRO_SPEC_DIR`` (explicit, reproducible) -> the repo's
    ``tools/`` directory relative to this file -> ``./tools`` from the CWD.
    Returns None when nothing is found (catalogue is then unavailable).
    """
    env = os.environ.get(_ENV_SPEC_DIR)
    if env:
        p = Path(env)
        return p if p.is_dir() else None
    # vendor/balatro-rl/balatro_sim/catalogue.py -> parents[3] == repo root
    try:
        root_tools = Path(__file__).resolve().parents[3] / "tools"
        if root_tools.is_dir():
            return root_tools
    except IndexError:  # pragma: no cover — pathological install layout
        pass
    cwd_tools = Path.cwd() / "tools"
    return cwd_tools if cwd_tools.is_dir() else None


# ────────────────────────────────────────────────────────────────────────────
# Derivation rules (documented; the ONLY source of interpretation)
# ────────────────────────────────────────────────────────────────────────────
#
# A joker's spec `type` uses 7 values. We map them to scoring roles 1:1 —
# no judgement involved:
_SPEC_TYPE_TO_ROLES: dict[str, tuple[str, ...]] = {
    "Chips": ("chips",),
    "+Mult": ("flat_mult",),
    "xMult": ("xmult",),
    "Economy": ("econ",),
    "Retrigger": ("retrigger",),
    "Chips+Mult": ("chips", "flat_mult"),
    "Effect": ("other",),
}

# Effect-string phrase rules. Each maps a *documented* phrasing to a boolean
# feature. These are grammatical detectors, not tuning: Balatro's own wording
# is the classifier.
_SCALING_PHRASES = (
    "gains", "per ", "for each", "for every", "every time", "loses",
    "each time", "permanently",
)
_CHANCE_PHRASES = ("chance", " in ")
_MONEY_PHRASES = ("$", "earn", "sell value", "interest")
_DESTROY_PHRASES = ("destroy",)
_RESET_PHRASES = ("reset",)
_HELD_PHRASES = ("held in hand", "in hand")
_FACE_PHRASES = ("face card", "jack", "queen", "king")
_SUIT_WORDS = ("heart", "club", "spade", "diamond")
_SLOT_PHRASES = ("joker slot", "hand size", "discard", "hand per round")
_GENERATOR_PHRASES = ("create", "adds", "copy", "duplicate", "converts")

_HAND_TYPE_NAMES = (
    "high card", "pair", "two pair", "three of a kind", "straight", "flush",
    "full house", "four of a kind", "straight flush", "five of a kind",
    "flush house", "flush five",
)

# Boss-modifier vocabulary, parsed from the boss spec's own effect strings.
# This is how "boss patterns" get learned rather than curated: the model sees
# what a boss *does* (debuff, discard, one-hand, ...) crossed with what an item
# does (face, suit, held, ...), and separately accumulates a fully-learned
# per-boss residual. No hand-written BAD_BOSSES list is involved.
BOSS_FLAGS = (
    "debuff", "face_down", "discard", "one_hand", "no_discard",
    "hand_size", "force_select", "money", "shuffle", "random",
    "no_repeat", "destroy", "suit", "face", "joker_target",
    "scaling", "finisher", "late_only",
)

_BOSS_PHRASE_RULES: dict[str, tuple[str, ...]] = {
    "debuff": ("debuff",),
    "face_down": ("face down",),
    "discard": ("discard",),
    "one_hand": ("1 hand",),
    "no_discard": ("no discard",),
    "hand_size": ("hand size",),
    "force_select": ("always be selected", "forces a random card"),
    "money": ("$", "money", "cash"),
    "shuffle": ("shuffle",),
    "random": ("random",),
    "no_repeat": ("cannot play the same",),
    "destroy": ("destroy",),
    "suit": _SUIT_WORDS,
    "face": ("face",),
    "joker_target": ("joker",),
}

# Bosses whose chip requirement is scaled up (spec `scaling`: Violet x6,
# Wall x4, Needle x1). Read from the spec so the multipliers are never typed.
_BOSS_SCALING: dict[str, int] = {}

# Effect detail captured as a small enumerated vocabulary. Ordered so the
# numeric encoding is stable across processes (dict/set order is not).
EFFECT_FLAGS = (
    "scaling", "chance", "money", "destroy", "reset", "held", "face",
    "suit", "slot", "generator", "xmult", "edition", "negative",
)

ROLES = ("chips", "flat_mult", "xmult", "econ", "retrigger", "other")
TIMINGS = (
    "Independent", "Passive", "On Scored", "On Held", "On Discard",
    "On Played", "On Blind Select", "Mixed", "On Other Jokers",
    "On Other Jokers*",
)
RARITIES = ("Common", "Uncommon", "Rare", "Legendary", "Unknown")
# "card" is a playing card offered by a Standard pack or a shop card slot.
# It has no per-key spec entry (quality is carried by live enhancement / seal /
# edition features), so the catalogue registers a single synthetic entry for
# it — which keeps `item_features` total: a known kind, never a sentinel.
KINDS = ("joker", "tarot", "spectral", "planet", "voucher", "pack", "card",
         "tag", "boss")


def _flagged(effect: str, phrases: Iterable[str]) -> bool:
    low = effect.lower()
    return any(p in low for p in phrases)


# ────────────────────────────────────────────────────────────────────────────
# Item model
# ────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ItemSpec:
    """One catalogue item. All fields are spec-derived or spec-parsed."""

    key: str
    kind: str
    name: str = ""
    cost: int = 0
    sell: int = 0
    rarity: str = "Unknown"
    jtype: str = ""
    timing: str = ""
    effect: str = ""
    targets: int = 0
    hand_type: str = ""
    min_ante: int = 0
    finisher: bool = False
    grants: str = ""
    roles: tuple[str, ...] = ()
    flags: dict[str, float] = field(default_factory=dict)

    @property
    def is_joker(self) -> bool:
        return self.kind == "joker"

    @property
    def scaling(self) -> bool:
        return bool(self.flags.get("scaling"))

    @property
    def hand_type_key(self) -> str:
        """Lower-cased poker hand this item upgrades (planets)."""
        return (self.hand_type or "").lower()

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["roles"] = list(self.roles)
        return d


# ────────────────────────────────────────────────────────────────────────────
# Loading
# ────────────────────────────────────────────────────────────────────────────

_CACHE: Optional[dict[str, ItemSpec]] = None
_FINGERPRINT: Optional[str] = None
_COST_MAX: int = 0
_SPEC_DIR_USED: Optional[Path] = None


def _load_json(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _sim_joker_meta() -> dict[str, dict[str, Any]]:
    """Rarity + price straight from the sim's shop catalogue.

    Imported lazily: this module is imported by the value model, which is
    imported by the policy, so a top-level sim import would risk a cycle.
    """
    try:
        from .shop import JOKER_CATALOGUE  # type: ignore
        return JOKER_CATALOGUE
    except Exception:  # pragma: no cover — sim not importable / unavailable
        return {}


def _sim_booster_meta() -> dict[str, dict[str, Any]]:
    try:
        from .shop import BOOSTER_CATALOGUE  # type: ignore
        return BOOSTER_CATALOGUE
    except Exception:  # pragma: no cover
        return {}


def _parse_flags(effect: str, jtype: str) -> dict[str, float]:
    low = effect.lower()
    roles = set(_SPEC_TYPE_TO_ROLES.get(jtype, ("other",)))
    return {
        "scaling": float(_flagged(low, _SCALING_PHRASES)),
        "chance": float(_flagged(low, _CHANCE_PHRASES)),
        "money": float(_flagged(low, _MONEY_PHRASES)),
        "destroy": float(_flagged(low, _DESTROY_PHRASES)),
        "reset": float(_flagged(low, _RESET_PHRASES)),
        "held": float(_flagged(low, _HELD_PHRASES)),
        "face": float(_flagged(low, _FACE_PHRASES)),
        "suit": float(any(w in low for w in _SUIT_WORDS)),
        "slot": float(_flagged(low, _SLOT_PHRASES)),
        "generator": float(_flagged(low, _GENERATOR_PHRASES)),
        "xmult": float("xmult" in roles or bool(re.search(r"x\d", low))),
        "edition": float("foil" in low or "holo" in low or "polychrome" in low),
        "negative": float("negative" in low),
    }


def _roles_for(effect: str, jtype: str, flags: dict[str, float]) -> tuple[str, ...]:
    roles = list(_SPEC_TYPE_TO_ROLES.get(jtype, ("other",)))
    # A "+Mult" joker that grows is still flat mult: `scaling` is carried as a
    # flag, never folded into the role, so the two remain independently
    # measurable by the model.
    return tuple(roles)


def load(force: bool = False) -> dict[str, ItemSpec]:
    """Build (and cache) the catalogue. Empty dict when specs are absent."""
    global _CACHE, _FINGERPRINT, _COST_MAX, _SPEC_DIR_USED
    if _CACHE is not None and not force:
        return _CACHE

    spec_dir = _find_spec_dir()
    out: dict[str, ItemSpec] = {}
    if spec_dir is not None:
        _SPEC_DIR_USED = spec_dir
        joker_meta = _sim_joker_meta()
        booster_meta = _sim_booster_meta()

        # ── jokers ──────────────────────────────────────────────────────
        jpath = spec_dir / SPEC_FILES["joker"]
        if jpath.is_file():
            for key, spec in _load_json(jpath).items():
                jtype = str(spec.get("type", "")) or "Effect"
                effect = str(spec.get("effect", ""))
                flags = _parse_flags(effect, jtype)
                meta = joker_meta.get(key, {})
                out[key] = ItemSpec(
                    key=key, kind="joker", name=str(spec.get("name", "")),
                    cost=int(meta.get("price", spec.get("cost", 0)) or 0),
                    rarity=str(meta.get("rarity", "Unknown")),
                    jtype=jtype, timing=str(spec.get("timing", "")),
                    effect=effect, roles=_roles_for(effect, jtype, flags),
                    flags=flags,
                )

        # ── consumables: tarots / spectrals / planets / vouchers ────────
        cpath = spec_dir / SPEC_FILES["consumable"]
        if cpath.is_file():
            consumables = _load_json(cpath)
            group_kind = {
                "tarots": "tarot", "spectrals": "spectral",
                "planets": "planet", "vouchers": "voucher",
            }
            for group, kind in group_kind.items():
                for key, spec in (consumables.get(group) or {}).items():
                    effect = str(spec.get("effect", ""))
                    out[key] = ItemSpec(
                        key=key, kind=kind, name=str(spec.get("name", "")),
                        cost=int(spec.get("cost", 0) or 0),
                        sell=int(spec.get("sell", 0) or 0),
                        effect=effect, targets=int(spec.get("targets", 0) or 0),
                        hand_type=str(spec.get("hand_type", "")),
                    )

        # ── booster packs (the sim owns price; spec has no pack table) ──
        # BOOSTER_CATALOGUE values are 4-tuples:
        #   (display_name, price, grants_kind, cards_offered)
        for key, meta in booster_meta.items():
            if isinstance(meta, (tuple, list)):
                name = str(meta[0]) if len(meta) > 0 else ""
                price = int(meta[1]) if len(meta) > 1 else 0
                grants = str(meta[2]) if len(meta) > 2 else ""
                offered = int(meta[3]) if len(meta) > 3 else 0
            else:  # tolerate a future dict-shaped catalogue
                name = str(meta.get("name", ""))
                price = int(meta.get("price", meta.get("cost", 0)) or 0)
                grants = str(meta.get("kind", ""))
                offered = int(meta.get("cards", 0) or 0)
            out[key] = ItemSpec(
                key=key, kind="pack", name=name, cost=price,
                effect=grants, targets=offered,
            )

        # ── bosses ─────────────────────────────────────────────────────
        bpath = spec_dir / SPEC_FILES["boss"]
        if bpath.is_file():
            boss_doc = _load_json(bpath)
            scaling = boss_doc.get("scaling") or {}
            for key, val in scaling.items():
                _BOSS_SCALING[key] = int(val)
            for key, spec in (boss_doc.get("bosses") or {}).items():
                effect = str(spec.get("effect", ""))
                min_ante = int(spec.get("min_ante", 0) or 0)
                flags = {
                    f: float(_flagged(effect, _BOSS_PHRASE_RULES[f]))
                    for f in BOSS_FLAGS if f in _BOSS_PHRASE_RULES
                }
                flags["scaling"] = float(_BOSS_SCALING.get(key, 1) > 1)
                flags["finisher"] = float(bool(spec.get("finisher")))
                flags["late_only"] = float(min_ante >= 8)
                out[key] = ItemSpec(
                    key=key, kind="boss", name=str(spec.get("name", "")),
                    effect=effect, min_ante=min_ante,
                    finisher=bool(spec.get("finisher")), flags=flags,
                )

        # ── tags ───────────────────────────────────────────────────────
        tpath = spec_dir / SPEC_FILES["tag"]
        if tpath.is_file():
            tags = (_load_json(tpath).get("tags") or {})
            for key, spec in tags.items():
                out[key] = ItemSpec(
                    key=key, kind="tag", name=str(spec.get("name", "")),
                    effect=str(spec.get("effect", "")),
                    min_ante=int(spec.get("ante", 0) or 0),
                )

    out["card"] = ItemSpec(key="card", kind="card", name="Playing Card")

    _COST_MAX = max((i.cost for i in out.values()), default=0)
    _CACHE = out
    _FINGERPRINT = _hash(out)
    return out


def _hash(items: dict[str, ItemSpec]) -> str:
    h = hashlib.sha256()
    for key in sorted(items):
        h.update(json.dumps(items[key].as_dict(), sort_keys=True).encode())
    return h.hexdigest()[:16]


# ────────────────────────────────────────────────────────────────────────────
# Public accessors
# ────────────────────────────────────────────────────────────────────────────


def available() -> bool:
    return bool(load())


def fingerprint() -> str:
    """Stable content hash of the catalogue — recorded with every artifact."""
    load()
    return _FINGERPRINT or ""


def spec_dir() -> Optional[Path]:
    load()
    return _SPEC_DIR_USED


def cost_max() -> int:
    """Largest catalogue cost — the scale used to normalise price features."""
    load()
    return _COST_MAX


def item(key: str) -> Optional[ItemSpec]:
    return load().get(key)


def keys(kind: Optional[str] = None) -> tuple[str, ...]:
    cat = load()
    return tuple(sorted(k for k, v in cat.items() if kind is None or v.kind == kind))


def by_kind() -> dict[str, tuple[str, ...]]:
    return {k: keys(k) for k in KINDS}


def items(kind: Optional[str] = None) -> list[ItemSpec]:
    return [load()[k] for k in keys(kind)]


def scaling_keys() -> tuple[str, ...]:
    return tuple(sorted(k for k, v in load().items() if v.scaling))


def boss_features(key: str) -> dict[str, float]:
    """Parsed semantic flags for a boss modifier (empty for unknown keys)."""
    it = item(key)
    if it is None or it.kind != "boss":
        return {}
    return {f: float(it.flags.get(f, 0.0)) for f in BOSS_FLAGS}


def boss_scaling(key: str) -> int:
    """Chip-requirement multiplier for a boss (from the spec's scaling map)."""
    load()
    return int(_BOSS_SCALING.get(key, 1))


def hand_types_leveled_by_planets() -> dict[str, str]:
    """planet key -> the poker hand it levels (the sim's own mapping)."""
    return {k: v.hand_type for k, v in load().items()
            if v.kind == "planet" and v.hand_type}


# ────────────────────────────────────────────────────────────────────────────
# Feature encoding (the model's item side)
# ────────────────────────────────────────────────────────────────────────────

# Ordered block layout; index arithmetic is derived from these tuples so the
# encoder cannot silently desync from the vocabulary.
_BLOCK_ORDER = ("kind", "role", "timing", "rarity")

FEATURE_NAMES: tuple[str, ...] = (
    ("cost_frac", "sell_frac", "targets")
    + tuple(f"flag_{f}" for f in EFFECT_FLAGS)
    + ("kind_joker",)
    + tuple(f"kind_{k}" for k in KINDS if k != "joker")
    + tuple(f"role_{r}" for r in ROLES)
    + tuple(f"timing_{t}" for t in TIMINGS)
    + tuple(f"rarity_{r}" for r in RARITIES)
)


def item_features(key: str, present: Optional[dict[str, float]] = None) -> dict[str, float]:
    """Spec-derived numeric encoding of one item.

    ``present`` may carry live-state observations the catalogue cannot know
    (e.g. the item's current stack/sell value in the shop). They are merged
    without overwriting spec fields.
    """
    it = item(key)
    feats: dict[str, float] = {name: 0.0 for name in FEATURE_NAMES}
    if it is None:
        feats["cost_frac"] = -1.0  # explicit "unknown item" sentinel
        if present:
            feats.update({k: float(v) for k, v in present.items()})
        return feats

    cmax = cost_max() or 1
    feats["cost_frac"] = it.cost / cmax
    feats["sell_frac"] = it.sell / cmax
    feats["targets"] = float(it.targets)
    for f in EFFECT_FLAGS:
        feats[f"flag_{f}"] = float(it.flags.get(f, 0.0))
    feats[f"kind_{it.kind}"] = 1.0
    for r in it.roles:
        if f"role_{r}" in feats:
            feats[f"role_{r}"] = 1.0
    if f"timing_{it.timing}" in feats:
        feats[f"timing_{it.timing}"] = 1.0
    if f"rarity_{it.rarity}" in feats:
        feats[f"rarity_{it.rarity}"] = 1.0
    if present:
        feats.update({k: float(v) for k, v in present.items()})
    return feats


def coverage_cells() -> list[tuple[str, str]]:
    """Every (item, kind) pair the coverage gate must account for."""
    return [(k, v.kind) for k, v in sorted(load().items())]


def summary() -> dict[str, Any]:
    cat = load()
    kinds: dict[str, int] = {}
    for v in cat.values():
        kinds[v.kind] = kinds.get(v.kind, 0) + 1
    return {
        "fingerprint": _FINGERPRINT or "",
        "spec_dir": str(_SPEC_DIR_USED) if _SPEC_DIR_USED else None,
        "total": len(cat),
        "by_kind": kinds,
        "by_role": {r: sum(1 for v in cat.values() if r in v.roles) for r in ROLES},
        "by_boss_flag": {f: sum(1 for v in cat.values()
                                if v.kind == "boss" and v.flags.get(f))
                         for f in BOSS_FLAGS},
        "scaling": sum(1 for v in cat.values() if v.scaling),
    }
