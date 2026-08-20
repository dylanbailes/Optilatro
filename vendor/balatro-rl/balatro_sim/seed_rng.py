"""seed_rng.py — Two-mode RNG for the Balatro sim.

Ports balatro-seed's per-node LuaRandom scheme to Python behind a single
interface. balatro-seed (vendor/balatro-rs/balatro-seed) is itself a
byte-accurate port of Balatro's REAL seed/RNG algorithm, verified ante-by-ante
against a reference implementation. Porting it 1:1 (pseudohash, round13,
LuaRandom, the per-node cache) is what makes seed-exact replay feasible.

Two modes, same API:

  generic (default):  one shared Python random.Random stream — exactly the
                      original sim's behavior (same stream, same call order).
                      Statistically correct for training; NOT reproducible
                      across processes and NOT Balatro's real scheme.

  seed:               per-node LuaRandom. Balatro doesn't use one global RNG
                      stream: every decision reseeds a FRESH LuaRandom from a
                      hash of (node_id, run_seed), and the node's cached value
                      advances on every access (that advance IS the reroll
                      mechanism). Node IDs are hashed verbatim, so they must
                      match the real game's strings exactly — see the
                      node_*() builders, pinned by balatro-seed's node_id.rs.

Consumers balatro-seed does NOT model (deck shuffle, in-round boss effects,
seal/joker probability triggers) use sim-internal node keys documented on
their constants below; those are deterministic per seed but are NOT pinned to
real Balatro call sites yet (documented in docs/M0-vendor-audit.md).
"""
from __future__ import annotations

import math
import random as _random
import struct
from dataclasses import dataclass
from typing import Optional, Sequence

# ────────────────────────────────────────────────────────────────────────────
# Ported primitives (balatro-seed/src/rng.rs — pure math, no domain knowledge)
# ────────────────────────────────────────────────────────────────────────────

_PI = math.pi
_E = math.e
_INV_PREC = 1e13
_TWO_INV_PREC = 8192.0                 # 2^13
_FIVE_INV_PREC = 1_220_703_125.0       # 5^13
_MASK64 = 0xFFFFFFFFFFFFFFFF
_MANT_MASK = 0x000FFFFFFFFFFFFF        # 2^52 - 1
_EXP_BIAS = 0x3FF0000000000000         # IEEE-754 bits of 1.0


def _fract(x: float) -> float:
    """Rust f64::fract — fractional part with truncation toward zero."""
    return x - math.trunc(x)


def pseudohash(s: str) -> float:
    """Balatro's own string hash; seeds a fresh LuaRandom per decision.

    Ported from balatro-seed's rng.rs::pseudohash. iterates the UTF-8 bytes in
    reverse, mixing each byte against PI.
    """
    num = 1.0
    b = s.encode("utf-8")
    for i in range(len(b), 0, -1):
        c = float(b[i - 1])
        num = _fract(1.1239285023 / num * c * _PI + _PI * i)
    return num


def _next_toward_one(x: float) -> float:
    """Rust next_up()/next_down() toward 1.0 — one representable step."""
    return math.nextafter(x, 1.0)


def round13(x: float) -> float:
    """balatro-seed rng.rs::round13 — 13-significant-digit stabilization.

    Keeps the per-node cache from drifting across repeated float updates.
    """
    tentative = math.floor(x * _INV_PREC) / _INV_PREC
    truncated = ((x * _TWO_INV_PREC) % 1.0) * _FIVE_INV_PREC
    if tentative != x and tentative != _next_toward_one(x) and (truncated % 1.0) >= 0.5:
        return (math.floor(x * _INV_PREC) + 1.0) / _INV_PREC
    return tentative


# next_u64's per-lane shift parameters (mirrors balatro-seed's next_u64).
# Hoisted: rebuilding this tuple on every call was ~6us/call (~180k/run).
_NEXT_U64_SHIFTS = ((31, 45, 1, 18), (19, 30, 6, 28), (24, 48, 9, 7),
                    (21, 39, 17, 8))


class LuaRandom:
    """Balatro's reimplementation of Lua 5.4's math.random (xoshiro256-family).

    Ported 1:1 from balatro-seed's rng.rs. The real game reseeds from scratch
    for EVERY decision — never share one instance across decisions.
    """

    __slots__ = ("_state",)

    def __init__(self, seed: float):
        d = seed
        r = 0x11090601
        state = [0] * 4
        for i in range(4):
            m = 1 << (r & 255)
            r >>= 8
            d = d * _PI + _E
            bits = struct.unpack("<Q", struct.pack("<d", d))[0]
            if bits < m:
                bits = (bits + m) & _MASK64
            state[i] = bits
        self._state = state
        for _ in range(10):
            self.next_u64()

    def next_u64(self) -> int:
        s = self._state
        r = 0
        # (shift_left, shift_right, low_bits_kept, shift_out) per state lane —
        # mirrors the four blocks of balatro-seed's next_u64.
        for i, (sl, sr, keep, so) in enumerate(_NEXT_U64_SHIFTS):
            z = s[i]
            z = (
                ((((z << sl) & _MASK64) ^ z) >> sr)
                ^ ((z & (_MASK64 ^ ((1 << keep) - 1))) << so)
            ) & _MASK64
            r ^= z
            s[i] = z
        return r

    def random(self) -> float:
        """A pseudorandom double in [0, 1)."""
        bits = (self.next_u64() & _MANT_MASK) | _EXP_BIAS
        return struct.unpack("<d", struct.pack("<Q", bits))[0] - 1.0

    def randint(self, lo: int, hi: int) -> int:
        """A pseudorandom integer in [lo, hi] inclusive (truncating)."""
        return int(self.random() * (hi - lo + 1)) + lo


# ────────────────────────────────────────────────────────────────────────────
# Replay draw-log records (see SeedSource tracing)
# ────────────────────────────────────────────────────────────────────────────

def _canon(obj) -> str:
    """Stable identity for draw-log diffing.

    Cards are canonicalized by (rank, suit) so a choice that returns the same
    logical card matches across runs regardless of mutable state (debuff,
    seal, enhancement); everything else uses repr().
    """
    if hasattr(obj, "rank") and hasattr(obj, "suit") and hasattr(obj, "is_face_card"):
        return f"card({obj.rank},{obj.suit})"
    return repr(obj)


@dataclass(frozen=True)
class DrawRecord:
    """One per-node draw: node key, per-node sequence number, the node value
    that seeded the fresh LuaRandom, and the draw method + result."""

    node: str
    seq: int
    value: float
    method: str
    args: object
    result: object

    def as_text(self) -> str:
        return (f"{self.node}#{self.seq} {self.method}({_canon(self.args)})"
                f" -> {_canon(self.result)} @{self.value!r}")


def _weighted_choice(v: float, population: Sequence, weights: Sequence[float],
                     total: float):
    """Weighted pick from a fresh LuaRandom seeded by node value v."""
    poll = LuaRandom(v).random() * total
    acc = 0.0
    for item, w in zip(population, weights):
        acc += w
        if poll < acc:
            return item
    return population[-1]


# ────────────────────────────────────────────────────────────────────────────
# Node IDs — MUST match Balatro's strings exactly (balatro-seed node_id.rs)
# ────────────────────────────────────────────────────────────────────────────

def node_boss() -> str:
    """Boss blind selection."""
    return "boss"


def node_cdt(ante: int) -> str:
    """Shop item-type roll (real: functions.hpp nextShopItem poll)."""
    return f"cdt{ante}"


def node_rarity(source: str, ante: int) -> str:
    """Joker rarity roll. Field order is ante-then-source (unusual)."""
    return f"rarity{ante}{source}"


def node_edition(source: str, ante: int) -> str:
    """Joker/standard-card edition roll."""
    return f"edi{source}{ante}"


def node_joker(rarity: str, source: str, ante: int) -> str:
    """Specific joker draw. rarity is '1'|'2'|'3'|'4'.

    Real game quirk (node_id.rs): the legendary node is just "Joker4" — it has
    no source/ante suffix, unlike Joker1/2/3.
    """
    if rarity == "4":
        return "Joker4"
    return f"Joker{rarity}{source}{ante}"


def node_tarot(source: str, ante: int) -> str:
    return f"Tarot{source}{ante}"


def node_planet(source: str, ante: int) -> str:
    return f"Planet{source}{ante}"


def node_spectral(source: str, ante: int) -> str:
    return f"Spectral{source}{ante}"


def node_soul_tarot(ante: int) -> str:
    return f"soul_Tarot{ante}"


def node_voucher(ante: int) -> str:
    return f"Voucher{ante}"


def node_tag(ante: int) -> str:
    return f"Tag{ante}"


def node_shop_pack(ante: int) -> str:
    return f"shop_pack{ante}"


def node_stdset(ante: int) -> str:
    """Standard-Pack enhancement poll (real: functions.hpp nextStandardCard)."""
    return f"stdset{ante}"


def node_std_enhanced(ante: int) -> str:
    """Standard-Pack enhancement-type roll (real: EnhancedStandard node)."""
    return f"Enhancedsta{ante}"


def node_std_front(ante: int) -> str:
    """Standard-Pack base-card draw (real: FrontStandard node)."""
    return f"frontsta{ante}"


def node_std_edition(ante: int) -> str:
    """Standard-Pack edition poll (real: StandardEdition node)."""
    return f"standard_edition{ante}"


def node_std_seal(ante: int) -> str:
    """Standard-Pack seal poll (real: StdSeal node)."""
    return f"stdseal{ante}"


def node_std_seal_type(ante: int) -> str:
    """Standard-Pack seal-type poll (real: StdSealType node)."""
    return f"stdsealtype{ante}"


# Sim-internal node IDs — deterministic per seed, NOT pinned to real Balatro
# (balatro-seed models shop/pack/tag/voucher/boss only). Documented as the
# remaining seed-exactness gap: in-game pseudorandom call sites.
DECK_SHUFFLE_NODE = "shuffle"
RESHUFFLE_NODE = "reshuffle"    # mid-round spent-pile reshuffle (deck exhausted)
CHANCE_NODE = "chance"          # joker/consumable/scoring probability triggers
AMBER_NODE = "amber"            # Amber Acorn: joker order shuffle
WHEEL_NODE = "wheel"            # The Wheel: 1-in-7 face-down
BELL_NODE = "bell"              # Cerulean Bell: forced card pick
HOOK_NODE = "hook"              # The Hook: which 2 cards are discarded
CRIMSON_NODE = "crimson"        # Crimson Heart: which joker is disabled
MADNESS_NODE = "madness"        # Madness joker: which joker is destroyed
PURPLE_SEAL_NODE = "purple_seal"  # Purple seal: which tarot is added
MAGIC_CARD_NODE = "magic_card"    # Magic Trick: shop playing-card rank/suit
OMEN_NODE = "omen"                # Omen Globe: 20% tarot -> spectral in Arcana Packs
ILLUSION_NODE = "illusion"        # Illusion: shop-card enhancement/edition rolls
DEFAULT_NODE = "default"


# ────────────────────────────────────────────────────────────────────────────
# Node API + two sources
# ────────────────────────────────────────────────────────────────────────────

class NodeRng:
    """Random-draw API shared by generic and seed nodes."""

    def random(self) -> float:
        raise NotImplementedError

    def randint(self, lo: int, hi: int) -> int:
        raise NotImplementedError

    def randrange(self, lo: int, hi: Optional[int] = None) -> int:
        """Integer in [lo, hi), or in [0, lo) when hi is omitted (like
        random.Random.randrange(stop))."""
        raise NotImplementedError

    def choice(self, seq: Sequence):
        raise NotImplementedError

    def shuffle(self, seq: list) -> None:
        raise NotImplementedError

    def choices(self, population: Sequence, weights: Sequence[float], k: int = 1) -> list:
        """Weighted sample with replacement (single draw when k == 1)."""
        raise NotImplementedError

    def chance(self, p: float) -> bool:
        """True with probability p."""
        return self.random() < p


class GenericNode(NodeRng):
    """Delegates to a shared random.Random — the legacy single-stream behavior."""

    __slots__ = ("_rng",)

    def __init__(self, rng: _random.Random):
        self._rng = rng

    def random(self) -> float:
        return self._rng.random()

    def randint(self, lo: int, hi: int) -> int:
        return self._rng.randint(lo, hi)

    def randrange(self, lo: int, hi: Optional[int] = None) -> int:
        if hi is None:
            return self._rng.randrange(lo)
        return self._rng.randrange(lo, hi)

    def choice(self, seq: Sequence):
        return self._rng.choice(seq)

    def shuffle(self, seq: list) -> None:
        self._rng.shuffle(seq)

    def choices(self, population: Sequence, weights: Sequence[float], k: int = 1) -> list:
        return self._rng.choices(population, weights=weights, k=k)


class SeedNode(NodeRng):
    """A per-node LuaRandom stream (balatro-seed instance.rs semantics).

    Every draw advances the node's cached value once and reseeds a FRESH
    LuaRandom from it — exactly how the real game draws one decision. Every
    draw funnels through _draw(), which is where the optional replay tracer
    hooks in (observation-only — it never perturbs the stream).
    """

    __slots__ = ("_source", "key")

    def __init__(self, source: "SeedSource", key: str):
        self._source = source
        self.key = key

    def _draw(self, method: str, args, compute):
        """One decision: advance the node, run the draw, and (when tracing is
        enabled) record (node, value, method, result) for replay diffing."""
        value = self._source.table.get_node(self.key)
        result = compute(value)
        self._source._record_draw(self.key, method, args, result, value)
        return result

    def random(self) -> float:
        return self._draw("random", None, lambda v: LuaRandom(v).random())

    def randint(self, lo: int, hi: int) -> int:
        return self._draw("randint", (lo, hi), lambda v: LuaRandom(v).randint(lo, hi))

    def randrange(self, lo: int, hi: Optional[int] = None) -> int:
        if hi is None:
            return self._draw("randrange", lo, lambda v: LuaRandom(v).randint(0, lo - 1))
        return self._draw("randrange", (lo, hi), lambda v: LuaRandom(v).randint(lo, hi - 1))

    def choice(self, seq: Sequence):
        return self._draw(
            "choice", len(seq),
            lambda v: seq[LuaRandom(v).randint(0, len(seq) - 1)],
        )

    def shuffle(self, seq: list) -> None:
        for i in range(len(seq) - 1, 0, -1):
            j = self._draw("shuffle", i, lambda v, i=i: LuaRandom(v).randint(0, i))
            seq[i], seq[j] = seq[j], seq[i]

    def choices(self, population: Sequence, weights: Sequence[float], k: int = 1) -> list:
        out = []
        for _ in range(k):
            total = float(sum(weights))
            item = self._draw(
                "choices", (len(population), total),
                lambda v, total=total: _weighted_choice(v, population, weights, total),
            )
            out.append(item)
        return out

    def chance(self, p: float) -> bool:
        return self._draw("chance", p, lambda v: LuaRandom(v).random() < p)


class RngSource:
    """Two-mode RNG source. node(key) returns a cached per-key NodeRng.

    Nodes are cached so callers can stub `source.node(key).choice` for tests
    (the boss-selection stub relies on this).
    """

    def node(self, key: str) -> NodeRng:
        raise NotImplementedError

    # Convenience passthroughs to the default node — kept for callers that
    # don't care about node separation.
    def random(self) -> float:
        return self.node(DEFAULT_NODE).random()

    def randint(self, lo: int, hi: int) -> int:
        return self.node(DEFAULT_NODE).randint(lo, hi)

    def randrange(self, lo: int, hi: int) -> int:
        return self.node(DEFAULT_NODE).randrange(lo, hi)

    def choice(self, seq: Sequence):
        return self.node(DEFAULT_NODE).choice(seq)

    def shuffle(self, seq: list) -> None:
        self.node(DEFAULT_NODE).shuffle(seq)


class GenericSource(RngSource):
    """One shared random.Random stream — byte-identical to the original sim."""

    __slots__ = ("_rng", "_nodes")

    def __init__(self, seed: Optional[int] = None):
        self._rng = _random.Random(seed)
        self._nodes: dict[str, NodeRng] = {}

    def node(self, key: str) -> NodeRng:
        n = self._nodes.get(key)
        if n is None:
            n = GenericNode(self._rng)
            self._nodes[key] = n
        return n


class SeedSource(RngSource):
    """Per-node LuaRandom. Node ids are hashed with the run seed verbatim."""

    __slots__ = ("table", "_nodes", "_records", "_seq")

    def __init__(self, seed: str):
        self.table = NodeTable(_normalize_seed(seed))
        self._nodes: dict[str, NodeRng] = {}
        self._records: Optional[list[DrawRecord]] = None   # None unless tracing
        self._seq: dict[str, int] = {}                    # per-node draw counter

    def node(self, key: str) -> NodeRng:
        n = self._nodes.get(key)
        if n is None:
            n = SeedNode(self, key)
            self._nodes[key] = n
        return n

    # ── Replay tracing (observation-only) ───────────────────────────────────
    @property
    def records(self) -> Optional[list[DrawRecord]]:
        """Draw log recorded since tracing was enabled (None when disabled)."""
        return self._records

    def enable_tracing(self) -> list[DrawRecord]:
        """Start recording every per-node draw. Returns the (empty) log list.
        Tracing never perturbs the RNG stream — it only appends records."""
        self._records = []
        self._seq = {}
        return self._records

    def disable_tracing(self) -> list[DrawRecord]:
        """Stop tracing and return the draws recorded so far."""
        records = self._records or []
        self._records = None
        self._seq = {}
        return records

    def _record_draw(self, node_id: str, method: str, args, result, value: float):
        if self._records is not None:
            seq = self._seq.get(node_id, 0) + 1
            self._seq[node_id] = seq
            self._records.append(DrawRecord(node_id, seq, value, method, args, result))


class NodeTable:
    """balatro-seed instance.rs's per-node cache (the reroll mechanism).

    get_node() advances the node's stored value on EVERY access — that
    mutation is what makes a reroll (or any repeated draw) produce a fresh
    number, exactly like the real game.
    """

    __slots__ = ("seed", "hashed_seed", "nodes")

    def __init__(self, seed: str):
        self.seed = seed
        self.hashed_seed = pseudohash(seed)
        self.nodes: dict[str, float] = {}

    def get_node(self, node_id: str) -> float:
        if node_id not in self.nodes:
            self.nodes[node_id] = pseudohash(f"{node_id}{self.seed}")
        v = self.nodes[node_id]
        v = round13((v * 1.72431234 + 2.134453429141) % 1.0)
        self.nodes[node_id] = v
        return (v + self.hashed_seed) / 2.0


# ────────────────────────────────────────────────────────────────────────────
# Factory
# ────────────────────────────────────────────────────────────────────────────

def _normalize_seed(seed: str) -> str:
    """Match balatro-seed's explore CLI: uppercase, and 0 is never a seed char."""
    return seed.upper().replace("0", "O")


def make_source(seed=None, mode: str = "generic") -> RngSource:
    """Build an RNG source. mode: 'generic' (default) or 'seed'.

    seed: int or str. In seed mode the string form is hashed with every node id
    (int seeds hash as their decimal string). seed=None in seed mode derives an
    effectively-unseeded value.
    """
    if mode == "seed":
        if seed is None:
            seed = f"{_random.random():.12f}"
        return SeedSource(str(seed))
    return GenericSource(seed)
