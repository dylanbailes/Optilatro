"""
balatro_rl/state_v2.py
V2 state parsing with play/discard options and deck composition.

Observation space: Box(206,) float32, all values in [0,1]
  [0:56]    Hand cards (8 × 7 features)
  [56:86]   Jokers (5 × 6 features)
  [86:95]   Scalar state (9 features)
  [95:119]  Hand levels (12 × 2 features)
  [119:159] Play options (10 × 4 features)
  [159:189] Discard options (10 × 3 features)
  [189:206] Deck composition (13 ranks + 4 suits)
"""

import json
import time
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Optional
import numpy as np

# ── Joker ID mapping ──────────────────────────────────────────────────────────
JOKER_NAMES = [
    "none",
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
    "Seance","Riff-raff","Vampire","Shortcut","Hologram",
    "Vagabond","Baron","Cloud 9","Rocket","Obelisk",
    "Midas Mask","Luchador","Photograph","Gift Card","Turtle Bean",
    "Erosion","Reserved Parking","Mail-In Rebate","To the Moon","Hallucination",
    "Fortune Teller","Juggler","Drunkard","Stone Joker","Golden Joker",
    "Lucky Cat","Baseball Card","Bull","Diet Cola","Trading Card",
    "Flash Card","Popcorn","Spare Trousers","Ancient Joker","Ramen",
    "Walkie Talkie","Seltzer","Castle","Smiley Face","Campfire",
    "Golden Ticket","Mr. Bones","Acrobat","Sock and Buskin","Swashbuckler",
    "Troubadour","Certificate","Smeared Joker","Throwback","Hanging Chad",
    "Rough Gem","Bloodstone","Arrowhead","Onyx Agate","Glass Joker",
    "Showman","Flower Pot","Blueprint","Wee Joker","Merry Andy",
    "Oops! All 6s","The Idol","Seeing Double","Matador","Hit the Road",
    "The Duo","The Trio","The Family","The Order","The Tribe",
    "Stuntman","Invisible Joker","Brainstorm","Satellite","Shoot the Moon",
    "Driver's License","Cartomancer","Astronomer","Burnt Joker","Bootstraps",
    "Caino","Triboulet","Yorick","Chicot","Perkeo",
]
JOKER_TO_ID = {name: i for i, name in enumerate(JOKER_NAMES)}

# Hand type mapping
HAND_TYPE_NAMES = [
    "High Card", "Pair", "Two Pair", "Three of a Kind", "Straight",
    "Flush", "Full House", "Four of a Kind", "Straight Flush",
    "Five of a Kind", "Flush House", "Flush Five"
]
HAND_TYPE_TO_ID = {name: i for i, name in enumerate(HAND_TYPE_NAMES)}

# ── Dataclasses ───────────────────────────────────────────────────────────────

@dataclass
class CardState:
    rank: str = "none"
    suit: str = "none"
    rank_id: int = 0
    suit_id: int = 0
    highlighted: bool = False

@dataclass
class JokerState:
    name: str = "none"
    key: str = "none"
    joker_id: int = 0
    mult: float = 0.0
    chips: float = 0.0
    extra_val: float = 0.0
    is_present: bool = False

@dataclass
class PlayOption:
    indices: List[int] = field(default_factory=list)  # 1-indexed card positions
    hand_type: str = "High Card"
    hand_type_id: int = 0
    n_cards: int = 0
    score: float = 0.0
    is_valid: bool = True

@dataclass
class DiscardOption:
    indices: List[int] = field(default_factory=list)  # 1-indexed card positions
    n_cards: int = 0
    is_valid: bool = True

@dataclass
class GameState:
    event: str = "unknown"
    timestamp: float = 0.0
    file_mtime: float = 0.0
    game_state: int = 0
    seed: str = "unknown"
    ante: int = 0
    round: int = 0
    blind_name: str = "unknown"
    blind_chips: float = 0.0
    blind_boss: bool = False
    hands_left: int = 0
    discards_left: int = 0
    money: int = 0
    joker_slots: int = 5
    current_score: float = 0.0
    score_target: float = 0.0
    deck_remaining: int = 0
    last_hand_type: str = "unknown"
    
    # Cards and jokers
    hand: List[CardState] = field(default_factory=list)
    jokers: List[JokerState] = field(default_factory=list)
    
    # V2: play/discard options
    play_options: List[PlayOption] = field(default_factory=list)
    discard_options: List[DiscardOption] = field(default_factory=list)
    best_play_score: float = 0.0
    
    # V2: deck composition
    deck_ranks: List[int] = field(default_factory=list)  # 13 values
    deck_suits: List[int] = field(default_factory=list)  # 4 values

# ── Parsing ───────────────────────────────────────────────────────────────────

def _safe_float(val, default: float = 0.0) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return default

def parse_card(raw: dict) -> CardState:
    return CardState(
        rank=raw.get("rank", "none"),
        suit=raw.get("suit", "none"),
        rank_id=int(raw.get("rank_id", 0)),
        suit_id=int(raw.get("suit_id", 0)),
        highlighted=bool(raw.get("highlighted", False)),
    )

def parse_joker(raw: dict) -> JokerState:
    name = raw.get("name", "none")
    return JokerState(
        name=name,
        key=raw.get("key", "none"),
        joker_id=JOKER_TO_ID.get(name, 0),
        mult=_safe_float(raw.get("mult", 0)),
        chips=_safe_float(raw.get("chips", 0)),
        extra_val=_safe_float(raw.get("extra_val", 0)),
        is_present=True,
    )

def parse_play_option(raw: dict) -> PlayOption:
    return PlayOption(
        indices=raw.get("indices", []),
        hand_type=raw.get("hand_type", "High Card"),
        hand_type_id=raw.get("hand_type_id", 0),
        n_cards=raw.get("n_cards", 0),
        score=_safe_float(raw.get("score", 0)),
        is_valid=True,
    )

def parse_discard_option(raw: dict) -> DiscardOption:
    return DiscardOption(
        indices=raw.get("indices", []),
        n_cards=raw.get("n_cards", 0),
        is_valid=True,
    )

def parse_state(raw: dict, file_mtime: float = 0.0) -> GameState:
    gs = GameState(
        event=raw.get("event", "unknown"),
        timestamp=raw.get("tick", raw.get("timestamp", 0)),
        file_mtime=file_mtime,
        game_state=int(raw.get("game_state", 0)),
        seed=str(raw.get("seed", "unknown")),
        ante=int(raw.get("ante", 0)),
        round=int(raw.get("round", 0)),
        blind_name=raw.get("blind_name", "unknown"),
        blind_chips=_safe_float(raw.get("blind_chips", 0)),
        blind_boss=bool(raw.get("blind_boss", False)),
        hands_left=int(raw.get("hands_left", 0)),
        discards_left=int(raw.get("discards_left", 0)),
        money=int(raw.get("money", 0)),
        joker_slots=int(raw.get("joker_slots", 5)),
        current_score=_safe_float(raw.get("current_score", 0)),
        score_target=_safe_float(raw.get("score_target", 0)),
        deck_remaining=int(raw.get("deck_remaining", 0)),
        last_hand_type=raw.get("last_hand_type", "unknown"),
        best_play_score=_safe_float(raw.get("best_play_score", 0)),
    )
    
    # Parse hand
    gs.hand = [parse_card(c) for c in raw.get("hand", [])]
    
    # Parse jokers
    gs.jokers = [parse_joker(j) for j in raw.get("jokers", [])]
    
    # Parse play options
    gs.play_options = [parse_play_option(p) for p in raw.get("play_options", [])]
    
    # Parse discard options
    gs.discard_options = [parse_discard_option(d) for d in raw.get("discard_options", [])]
    
    # Deck composition
    gs.deck_ranks = raw.get("deck_ranks", [0]*13)
    gs.deck_suits = raw.get("deck_suits", [0]*4)
    
    return gs

# ── File I/O ──────────────────────────────────────────────────────────────────

STATE_PATH = Path.home() / "AppData/Roaming/Balatro/balatro_rl/state.json"

def read_state(timeout: float = 5.0) -> Optional[GameState]:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if STATE_PATH.exists():
                mtime = STATE_PATH.stat().st_mtime
                text = STATE_PATH.read_text(encoding="utf-8")
                raw = json.loads(text)
                return parse_state(raw, file_mtime=mtime)
        except (json.JSONDecodeError, IOError):
            pass
        time.sleep(0.05)
    return None

# ── Observation Vector ────────────────────────────────────────────────────────

OBS_SIZE = 206

def card_features(c: CardState) -> np.ndarray:
    """7 features per card slot."""
    return np.array([
        c.rank_id / 14.0,
        c.suit_id / 4.0,
        float(c.highlighted),
        1.0,  # is_present
        0.0, 0.0, 0.0  # reserved
    ], dtype=np.float32)

_EMPTY_CARD = np.zeros(7, dtype=np.float32)

def joker_features(j: JokerState) -> np.ndarray:
    """6 features per joker slot."""
    return np.array([
        j.joker_id / max(len(JOKER_NAMES)-1, 1),
        min(j.mult / 50.0, 1.0),
        min(j.chips / 200.0, 1.0),
        min(j.extra_val / 100.0, 1.0),
        float(j.is_present),
        0.0  # reserved
    ], dtype=np.float32)

_EMPTY_JOKER = np.zeros(6, dtype=np.float32)

def play_option_features(opt: PlayOption) -> np.ndarray:
    """4 features per play option."""
    return np.array([
        min(opt.score / 10000.0, 1.0),  # estimated score (normalized)
        opt.hand_type_id / 11.0,         # hand type
        opt.n_cards / 5.0,               # number of cards
        float(opt.is_valid),             # valid flag
    ], dtype=np.float32)

_EMPTY_PLAY = np.zeros(4, dtype=np.float32)

def discard_option_features(opt: DiscardOption) -> np.ndarray:
    """3 features per discard option."""
    return np.array([
        opt.n_cards / 5.0,        # number of cards to discard
        float(opt.is_valid),      # valid flag
        0.0,                      # reserved
    ], dtype=np.float32)

_EMPTY_DISCARD = np.zeros(3, dtype=np.float32)

def state_to_obs(gs: GameState) -> np.ndarray:
    """Convert GameState to 206-feature observation vector."""
    obs = np.zeros(OBS_SIZE, dtype=np.float32)
    ptr = 0
    
    # Hand cards (8 slots × 7 features = 56)
    for i in range(8):
        if i < len(gs.hand):
            obs[ptr:ptr+7] = card_features(gs.hand[i])
        else:
            obs[ptr:ptr+7] = _EMPTY_CARD
        ptr += 7
    
    # Jokers (5 slots × 6 features = 30)
    for i in range(5):
        if i < len(gs.jokers):
            obs[ptr:ptr+6] = joker_features(gs.jokers[i])
        else:
            obs[ptr:ptr+6] = _EMPTY_JOKER
        ptr += 6
    
    # Scalar state (9 features)
    score_progress = gs.current_score / max(gs.score_target, 1.0) if gs.score_target > 0 else 0.0
    obs[ptr:ptr+9] = np.array([
        gs.ante / 8.0,
        gs.round / 3.0,
        gs.hands_left / 4.0,
        gs.discards_left / 4.0,
        min(gs.money / 100.0, 1.0),
        gs.joker_slots / 5.0,
        min(score_progress, 2.0) / 2.0,
        gs.deck_remaining / 52.0,
        float(gs.blind_boss),
    ], dtype=np.float32)
    ptr += 9
    
    # Hand levels (12 types × 2 features = 24)
    # Placeholder: use flat values (actual levels would need game state)
    for _ in range(12):
        obs[ptr:ptr+2] = np.array([0.1, 0.1], dtype=np.float32)
        ptr += 2
    
    # Play options (10 slots × 4 features = 40)
    for i in range(10):
        if i < len(gs.play_options):
            obs[ptr:ptr+4] = play_option_features(gs.play_options[i])
        else:
            obs[ptr:ptr+4] = _EMPTY_PLAY
        ptr += 4
    
    # Discard options (10 slots × 3 features = 30)
    for i in range(10):
        if i < len(gs.discard_options):
            obs[ptr:ptr+3] = discard_option_features(gs.discard_options[i])
        else:
            obs[ptr:ptr+3] = _EMPTY_DISCARD
        ptr += 3
    
    # Deck composition (13 ranks + 4 suits = 17)
    for i in range(13):
        r = gs.deck_ranks[i] if i < len(gs.deck_ranks) else 0
        obs[ptr] = min(r / 4.0, 1.0)  # max 4 of each rank
        ptr += 1
    for i in range(4):
        s = gs.deck_suits[i] if i < len(gs.deck_suits) else 0
        obs[ptr] = min(s / 13.0, 1.0)  # max 13 of each suit
        ptr += 1
    
    return obs
