"""
balatro_rl/state.py
Reads state.json written by the BalatroRL Lua mod and converts it
into a flat numpy observation vector for the RL agent.

Observation vector layout (119 features total):
  [0:56]   Hand cards      — 8 slots × 7 features
  [56:86]  Jokers          — 5 slots × 6 features
  [86:95]  Scalar state    — 9 features
  [95:119] Hand levels     — 12 hand types × 2 (mult, chips)
"""

import json
import time
import numpy as np
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Dict, Optional

# ── Constants ────────────────────────────────────────────────────────────────

STATE_FILE = Path(r"C:\Users\Taggart\AppData\Roaming\Balatro\balatro_rl\state.json")

RANKS = ["2","3","4","5","6","7","8","9","10","Jack","Queen","King","Ace"]
SUITS = ["Spades","Hearts","Clubs","Diamonds"]

ENHANCEMENTS = ["none","Bonus Card","Mult Card","Wild Card","Glass Card",
                "Steel Card","Stone Card","Gold Card","Lucky Card"]
SEALS        = ["none","Gold Seal","Red Seal","Blue Seal","Purple Seal"]
EDITIONS     = ["none","foil","holo","polychrome","negative"]

HAND_TYPES = [
    "High Card","Pair","Two Pair","Three of a Kind","Straight",
    "Flush","Full House","Four of a Kind","Straight Flush",
    "Five of a Kind","Flush House","Flush Five",
]

# Build all joker names from a static list so the ID is stable across runs
JOKER_NAMES = [
    "none",
    # Common jokers (extend as you discover more in game)
    "Joker","Greedy Joker","Lusty Joker","Wrathful Joker","Gluttonous Joker",
    "Jolly Joker","Zany Joker","Mad Joker","Crazy Joker","Droll Joker",
    "Sly Joker","Wily Joker","Clever Joker","Devious Joker","Crafty Joker",
    "Half Joker","Joker Stencil","Four Fingers","Mime","Credit Card",
    "Ceremonial Dagger","Banner","Mystic Summit","Marble Joker","Loyalty Card",
    "8 Ball","Misprint","Dusk","Raised Fist","Chaos the Clown",
    "Fibonacci","Steel Joker","Scary Face","Abstract Joker","Delayed Gratification",
    "Hack","Pareidolia","Gros Michel","Even Steven","Odd Todd",
    "Scholar","Business Card","Supernova","Ride the Bus","Space Joker",
    "Egg","Burglar","Blackboard","Runner","Ice Cream",
    "DNA","Splash","Blue Joker","Sixth Sense","Constellation",
    "Hiker","Faceless Joker","Green Joker","Superposition","To Do List",
    "Cavendish","Card Sharp","Red Card","Madness","Square Joker",
    "Seance","Riff-Raff","Vampire","Shortcut","Hologram",
    "Vagabond","Baron","Cloud 9","Rocket","Obelisk",
    "Midas Mask","Luchador","Photograph","Gift Card","Turtle Bean",
    "Erosion","Reserved Parking","Flash Card","Popcorn","Spare Trousers",
    "Ancient Joker","Ramen","Walkie Talkie","Selzer","Castle",
    "Smiley Face","Campfire","Golden Ticket","Mr. Bones","Acrobat",
    "Sock and Buskin","Swashbuckler","Troubadour","Certificate","Smeared Joker",
    "Throwback","Hanging Chad","Rough Gem","Bloodstone","Arrowhead",
    "Onyx Agate","Glass Joker","Showman","Flower Pot","Blueprint",
    "Wee Joker","Merry Andy","Oops! All 6s","The Idol","Seeing Double",
    "Matador","Hit the Road","The Duo","The Trio","The Family",
    "The Order","The Tribe","Stuntman","Invisible Joker","Brainstorm",
    "Satellite","Shoot the Moon","Driver's License","Cartomancer","Astronomer",
    "Burnt Joker","Bootstraps","Caino","Triboulet","Yorick",
    "Chicot","Perkeo",
]
JOKER_TO_ID = {name: i for i, name in enumerate(JOKER_NAMES)}

OBS_SIZE = 8*7 + 5*6 + 9 + 12*2  # = 119

# ── Dataclasses ───────────────────────────────────────────────────────────────

@dataclass
class CardState:
    rank: str        = "none"
    suit: str        = "none"
    rank_id: int     = 0
    suit_id: int     = 0
    enhancement: str = "none"
    seal: str        = "none"
    edition: str     = "none"
    highlighted: bool = False
    is_present: bool  = False

@dataclass
class JokerState:
    name: str      = "none"
    joker_id: int  = 0
    mult: float    = 0.0
    chips: float   = 0.0
    extra: float   = 0.0
    edition: str   = "none"
    is_present: bool = False

@dataclass
class GameState:
    event: str            = "unknown"
    timestamp: float      = 0.0
    file_mtime: float     = 0.0   # actual OS file modification time (wall clock)
    seed:      str        = "unknown"
    phase: int            = 0
    game_state: int       = 0   # G.STATE numeric value from Lua
    ante: int             = 0
    round: int            = 0
    blind_name: str       = "unknown"
    blind_boss: bool      = False
    score_target: float   = 300.0
    current_score: float  = 0.0
    hands_left: int       = 4
    discards_left: int    = 4
    money: float          = 4.0
    joker_slots: int      = 5
    deck_remaining: int   = 52
    discard_count: int    = 0
    hand: List[CardState]  = field(default_factory=list)
    jokers: List[JokerState] = field(default_factory=list)
    hand_levels: Dict[str, Dict] = field(default_factory=dict)
    shop: List[Dict]             = field(default_factory=list)
    config: Dict                 = field(default_factory=dict)  # mod config flags from Lua
    last_hand_type: str          = "unknown"

    # Derived
    @property
    def score_progress(self) -> float:
        if self.score_target <= 0:
            return 0.0
        return min(self.current_score / self.score_target, 1.0)

    @property
    def is_terminal(self) -> bool:
        """True if the round is over (won or lost)."""
        return self.hands_left == 0 or self.current_score >= self.score_target

# ── Parser ────────────────────────────────────────────────────────────────────

def _idx(lst, val, default=0) -> int:
    try:
        return lst.index(val)
    except ValueError:
        return default

def parse_card(raw: dict) -> CardState:
    return CardState(
        rank        = raw.get("rank", "none"),
        suit        = raw.get("suit", "none"),
        rank_id     = raw.get("rank_id", 0),
        suit_id     = raw.get("suit_id", 0),
        enhancement = raw.get("enhancement", "none"),
        seal        = raw.get("seal", "none"),
        edition     = raw.get("edition", "none"),
        highlighted = bool(raw.get("highlighted", False)),
        is_present  = True,
    )

def parse_joker(raw: dict) -> JokerState:
    name = raw.get("name", "none")
    return JokerState(
        name       = name,
        joker_id   = JOKER_TO_ID.get(name, 0),
        mult       = float(raw.get("mult", 0)),
        chips      = float(raw.get("chips", 0)),
        extra      = float(raw.get("extra", 0)),
        edition    = raw.get("edition", "none"),
        is_present = True,
    )

def _safe_float(val, default: float = 0.0) -> float:
    """Convert val to float, returning default if val is non-numeric (e.g. '?' from The Mark)."""
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def _parse_hand_levels(raw_hl) -> dict:
    """Normalise hand_levels from either list or dict format into
    a dict keyed by snake_case hand name, e.g. 'high_card', 'flush_five'."""
    if isinstance(raw_hl, dict):
        return raw_hl
    # List format: [{"name": "High Card", "level": 1, "chips": 5, "mult": 1}, ...]
    result = {}
    for entry in raw_hl:
        name = entry.get("name", "")
        key  = name.lower().replace(" ", "_")
        result[key] = entry
    return result


def parse_state(raw: dict) -> GameState:
    gs = GameState(
        event         = raw.get("event", "unknown"),
        timestamp     = raw.get("tick", raw.get("timestamp", 0)),
        seed          = raw.get("seed", "unknown"),
        phase         = int(raw.get("phase", 0)),
        game_state    = int(raw.get("game_state", 0)),
        ante          = int(raw.get("ante", 0)),
        round         = int(raw.get("round", 0)),
        blind_name    = raw.get("blind_name", "unknown"),
        blind_boss    = bool(raw.get("blind_boss", False)),
        score_target  = _safe_float(raw.get("score_target", 300)),
        current_score = _safe_float(raw.get("current_score", 0)),
        hands_left    = int(raw.get("hands_left", 4)),
        discards_left = int(raw.get("discards_left", 4)),
        money         = float(raw.get("money", 0)),
        joker_slots   = int(raw.get("joker_slots", 5)),
        deck_remaining= int(raw.get("deck_remaining", 52)),
        discard_count = int(raw.get("discard_count", 0)),
        hand_levels   = _parse_hand_levels(raw.get("hand_levels", {})),
    )
    gs.shop          = raw.get("shop", [])
    gs.config        = raw.get("config", {})
    gs.hand          = [parse_card(c)  for c in raw.get("hand", [])]
    gs.jokers        = [parse_joker(j) for j in raw.get("jokers", [])]
    gs.last_hand_type = raw.get("last_hand_type", "unknown")
    return gs


def read_state(path: Path = STATE_FILE, timeout: float = 5.0) -> Optional[GameState]:
    """Read and parse state.json. Returns None on timeout or error."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            mtime = path.stat().st_mtime
            text  = path.read_text(encoding="utf-8")
            raw   = json.loads(text)
            gs    = parse_state(raw)
            gs.file_mtime = mtime
            return gs
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            time.sleep(0.05)
    return None

# ── Observation vector ────────────────────────────────────────────────────────

def card_features(c: CardState) -> np.ndarray:
    """7 features per card slot."""
    return np.array([
        c.rank_id / 14.0,                          # rank normalized
        c.suit_id / 3.0,                           # suit normalized
        _idx(ENHANCEMENTS, c.enhancement) / max(len(ENHANCEMENTS)-1, 1),
        _idx(SEALS, c.seal)               / max(len(SEALS)-1, 1),
        _idx(EDITIONS, c.edition)         / max(len(EDITIONS)-1, 1),
        float(c.highlighted),
        float(c.is_present),
    ], dtype=np.float32)

def joker_features(j: JokerState) -> np.ndarray:
    """6 features per joker slot."""
    return np.array([
        j.joker_id / max(len(JOKER_NAMES)-1, 1),
        min(j.mult  / 50.0, 1.0),
        min(j.chips / 200.0, 1.0),
        min(j.extra / 20.0, 1.0),
        _idx(EDITIONS, j.edition) / max(len(EDITIONS)-1, 1),
        float(j.is_present),
    ], dtype=np.float32)

_EMPTY_CARD  = card_features(CardState())
_EMPTY_JOKER = joker_features(JokerState())

def state_to_obs(gs: GameState) -> np.ndarray:
    """Convert GameState to a flat float32 numpy array of shape (119,)."""
    obs = np.zeros(OBS_SIZE, dtype=np.float32)
    ptr = 0

    # Hand cards (8 slots, pad with zeros)
    for i in range(8):
        if i < len(gs.hand):
            obs[ptr:ptr+7] = card_features(gs.hand[i])
        else:
            obs[ptr:ptr+7] = _EMPTY_CARD
        ptr += 7

    # Jokers (5 slots)
    for i in range(5):
        if i < len(gs.jokers):
            obs[ptr:ptr+6] = joker_features(gs.jokers[i])
        else:
            obs[ptr:ptr+6] = _EMPTY_JOKER
        ptr += 6

    # Scalar game state (9 features)
    obs[ptr:ptr+9] = [
        gs.ante            / 8.0,
        gs.hands_left      / 4.0,
        gs.discards_left   / 4.0,
        min(gs.money       / 20.0, 1.0),
        gs.score_progress,
        gs.deck_remaining  / 52.0,
        gs.discard_count   / 52.0,
        float(gs.blind_boss),
        gs.joker_slots     / 5.0,
    ]
    ptr += 9

    # Hand levels (12 types × 2: mult, chips — normalized)
    for hand_name in HAND_TYPES:
        level_data = gs.hand_levels.get(hand_name, {})
        obs[ptr]   = min(float(level_data.get("mult",  1)) / 20.0, 1.0)
        obs[ptr+1] = min(float(level_data.get("chips", 5)) / 500.0, 1.0)
        ptr += 2

    assert ptr == OBS_SIZE, f"obs size mismatch: {ptr} != {OBS_SIZE}"
    return obs
