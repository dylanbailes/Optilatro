"""
env_sim.py — Gymnasium-compatible Balatro environment using the Python sim.

Observation: flat numpy float32 vector of shape (OBS_DIM,)
Action:      discrete integer in [0, N_ACTIONS)

Action space (47 actions):
  Phase BLIND_SELECT:
    30  play_blind
    31  skip_blind
  Phase SELECTING_HAND:
    0-19  play card combo i  (top 20 combos ranked by hand strength, pre-computed each step)
    20-27 discard single card i  (card indices 0-7)
    28-29 use consumable 0/1 (no target; planets/non-targeting tarots only)
  Phase SHOP:
    32-38 buy shop item 0-6
    39-43 sell joker 0-4
    44    reroll
    45    leave_shop
  Fallback:
    anything not matching current phase → no-op (legal but wasted)

Observation layout (342 dims):
  [0:14]   game scalars
  [14:222] hand cards  (8 × 26)
  [222:272] joker slots (5 × 10)
  [272:296] shop items  (7 × ~3 + padding → 24)
  [296:308] planet levels (12)
  [308:324] consumables  (2 × 8)
  [324:342] shop item features (7 × 2 + reserved = 18)

Note: layout is contiguous; see _obs() for exact encoding.

Reward structure:
  +2.0  per blind beaten
  +5.0  per ante completed (boss blind beaten)
  +20.0 on win (ante 8 boss beaten)
  -2.0  on loss
  +0.05 per 1% chips progress toward blind target (dense, current - prev)
"""
from __future__ import annotations

import itertools
import math
import time
from typing import Optional

import numpy as np

try:
    import gymnasium as gym
    from gymnasium import spaces
except ImportError:
    import gym
    from gym import spaces

from .game import BalatroGame, State
from .hand_eval import evaluate_hand
from .scoring import score_hand
from .constants import (
    SUITS, RANK_CHIPS,
    STARTING_HANDS, STARTING_DISCARDS, HAND_SIZE,
)
from .shop import JOKER_CATALOGUE

# ════════════════════════════════════════════════════════════════════════════
# Constants
# ════════════════════════════════════════════════════════════════════════════

N_ACTIONS = 47

# Hand type priority lookup (higher = better)
HAND_PRIORITY = {
    "High Card": 0, "Pair": 1, "Two Pair": 2, "Three of a Kind": 3,
    "Straight": 4, "Flush": 5, "Full House": 6, "Four of a Kind": 7,
    "Straight Flush": 8, "Five of a Kind": 9, "Flush House": 10, "Flush Five": 11,
}

ENHANCEMENTS = ["None","Bonus","Mult","Wild","Glass","Steel","Stone","Gold","Lucky"]
EDITIONS     = ["None","Foil","Holographic","Polychrome","Negative"]
SEALS        = ["None","Gold","Red","Blue","Purple"]
SUIT_ORDER   = ["Spades","Hearts","Clubs","Diamonds"]

JOKER_KEYS   = sorted(JOKER_CATALOGUE.keys())
JOKER_IDX    = {k: i for i, k in enumerate(JOKER_KEYS)}
N_JOKERS     = len(JOKER_KEYS)

HAND_TYPES = [
    "High Card","Pair","Two Pair","Three of a Kind","Straight","Flush",
    "Full House","Four of a Kind","Straight Flush","Five of a Kind",
    "Flush House","Flush Five",
]

# Feature dimensions
GAME_SCALARS   = 14
CARD_FEATURES  = 26    # per card slot
N_HAND_SLOTS   = 8
JOKER_FEATURES = 10    # per joker slot
N_JOKER_SLOTS  = 5
SHOP_FEATURES  = 6     # per shop item
N_SHOP_SLOTS   = 7
PLANET_FEATURES= 12
CONS_FEATURES  = 8     # per consumable slot
N_CONS_SLOTS   = 2

# Shop context features (new — richer shop state for informed buying decisions)
SHOP_CONTEXT   = 78    # reroll(2) + vouchers(32) + boss(28) + deck_comp(8) + enhance(8)

# Skip-blind Tag features: offered-tag one-hot (24) + pending-tag state (5)
TAG_FEATURES         = 24
PENDING_TAG_FEATURES = 5

OBS_DIM = (GAME_SCALARS
           + N_HAND_SLOTS  * CARD_FEATURES
           + N_JOKER_SLOTS * JOKER_FEATURES
           + N_SHOP_SLOTS  * SHOP_FEATURES
           + PLANET_FEATURES
           + N_CONS_SLOTS  * CONS_FEATURES
           + SHOP_CONTEXT
           + TAG_FEATURES
           + PENDING_TAG_FEATURES)
# = 14 + 208 + 50 + 42 + 12 + 16 + 78 + 24 + 5 = 449

# Reward constants
# Blind clear reward scales inversely with ante: ante 1 = 16.0, ante 8 = 2.0
# Formula: R_BLIND_BASE * (9 - ante) — early survival is highly rewarded
R_BLIND_BASE     = 2.0
R_ANTE_COMPLETE  = 5.0
R_WIN            = 50.0   # bumped from 20 — winning is still the dominant signal
R_LOSE           = -2.0
R_SCORE_PROGRESS = 0.05   # per 1% progress increment

# Heuristic shop reward shaping (mirrors V4 Lua shop heuristic)
R_HEUR_BUY_JOKER   = 0.3   # bought a joker into an empty slot
R_HEUR_USE_PLANET   = 0.2   # used a planet card (free hand upgrade)
R_HEUR_LEAVE_EMPTY  = -0.2  # left shop with affordable jokers and empty slots
R_HEUR_WASTE_MONEY  = -0.02 # per dollar over $25 (interest cap) when leaving shop
                             # holding $25 = max interest, anything above is wasted potential


# ════════════════════════════════════════════════════════════════════════════
# Environment
# ════════════════════════════════════════════════════════════════════════════

class BalatroSimEnv(gym.Env):
    """
    Gymnasium environment wrapping the Python Balatro simulation.

    Observation space: Box(shape=(OBS_DIM,), dtype=float32)
    Action space:      Discrete(N_ACTIONS)
    """

    metadata = {"render_modes": []}

    def __init__(self, seed: Optional[int] = None, rng_mode: str = "generic"):
        super().__init__()
        self.observation_space = spaces.Box(
            low=-1.0, high=10.0, shape=(OBS_DIM,), dtype=np.float32
        )
        self.action_space = spaces.Discrete(N_ACTIONS)

        self._seed = seed
        self._rng_mode = rng_mode
        self.game = BalatroGame(seed=seed, rng_mode=rng_mode)
        self._prev_progress = 0.0
        self._prev_ante = 1
        self._prev_blind_idx = 0
        self._play_combos: list[list[int]] = []   # pre-computed for current hand
        self._steps = 0
        self._play_history: list[dict] = []       # per-hand log for highlight reel
        self._episode_reward: float = 0.0         # cumulative reward this episode

    # ── gym API ──────────────────────────────────────────────────────────────

    def reset(self, seed=None, options=None):
        if seed is not None:
            self._seed = seed
        self.game = BalatroGame(seed=self._seed, rng_mode=self._rng_mode)
        self._prev_progress = 0.0
        self._prev_ante = 1
        self._prev_blind_idx = 0
        self._steps = 0
        self._play_history = []
        self._episode_reward = 0.0
        self._auto_advance()
        self._update_play_combos()
        obs = self._encode_obs()
        return obs, {}

    def step(self, action: int):
        self._steps += 1
        reward = 0.0
        gs = self.game

        state = gs.state

        # ── Blind select ──────────────────────────────────────────────────
        if state == State.BLIND_SELECT:
            if action == 30:
                gs.step({"type": "play_blind"})
                self._update_play_combos()
            elif action == 31:
                gs.step({"type": "skip_blind"})
                self._auto_advance()
                self._update_play_combos()
            # else no-op

        # ── Selecting hand ────────────────────────────────────────────────
        elif state == State.SELECTING_HAND:
            prev_chips = gs.chips_scored
            target = gs.current_blind.chips_target

            if 0 <= action <= 19:
                if action < len(self._play_combos):
                    combo = self._play_combos[action]
                    # Capture pre-play state for highlight log
                    pre_cards    = [gs.hand[i] for i in combo if i < len(gs.hand)]
                    jokers_held  = [j.key for j in gs.jokers]
                    ante_now     = gs.ante
                    blind_kind   = gs.current_blind.kind if gs.current_blind else "?"
                    chips_before = gs.chips_scored

                    gs.step({"type": "play", "cards": combo})

                    # Dense reward: log-scaled progress so overshooting the
                    # blind target is still incentivised but with diminishing
                    # returns (1.5x target ~ 1.3x reward vs exact clear;
                    # 5x target ~ 2x reward; 1000x target ~ 10x reward).
                    new_progress = gs.chips_scored / max(target, 1)
                    delta = new_progress - self._prev_progress
                    if delta > 0:
                        reward += R_SCORE_PROGRESS * math.log1p(delta) * 100
                    self._prev_progress = new_progress

                    # Record play for highlight reel using pre-captured cards
                    try:
                        ht, _ = evaluate_hand(pre_cards) if pre_cards else ("?", [])
                    except Exception:
                        ht = "?"
                    self._play_history.append({
                        "ante":        ante_now,
                        "blind":       blind_kind,
                        "cards":       [repr(c) for c in pre_cards],
                        "hand_type":   ht,
                        "chips":       gs.chips_scored - chips_before,
                        "total":       gs.chips_scored,
                        "target":      target,
                        "jokers":      jokers_held,
                    })
                    self._update_play_combos()

            elif 20 <= action <= 27:
                card_idx = action - 20
                if card_idx < len(gs.hand) and gs.discards_left > 0:
                    gs.step({"type": "discard", "cards": [card_idx]})
                    self._update_play_combos()

            elif action in (28, 29):
                c_idx = action - 28
                if c_idx < len(gs.consumable_hand):
                    gs.step({"type": "use_consumable",
                             "consumable_idx": c_idx,
                             "target_cards": []})

        # ── Shop ─────────────────────────────────────────────────────────
        elif state == State.SHOP:
            if 32 <= action <= 38:
                idx = action - 32
                n_jokers_before = len(gs.jokers)
                gs.step({"type": "buy", "item_idx": idx})
                # Heuristic: bonus for buying a joker
                if len(gs.jokers) > n_jokers_before:
                    reward += R_HEUR_BUY_JOKER

            elif 39 <= action <= 43:
                j_idx = action - 39
                # Penalize selling when you have open slots — almost always a blunder
                # Exception: selling to afford a much better joker (checked by
                # whether a shop joker costs more than current dollars)
                if j_idx < len(gs.jokers) and len(gs.jokers) <= gs.joker_slots:
                    has_expensive_upgrade = any(
                        i.kind == "joker" and not i.sold
                        and i.discounted_price(gs.shop_discount) > gs.dollars
                        for i in gs.current_shop
                    )
                    if not has_expensive_upgrade:
                        reward += -0.5  # clear blunder — selling with open slots for no reason
                gs.step({"type": "sell_joker", "joker_idx": j_idx})

            elif action == 44:
                gs.step({"type": "reroll"})

            elif action == 45:
                # Heuristic: penalize leaving with affordable jokers and empty slots
                if len(gs.jokers) < gs.joker_slots:
                    affordable = any(
                        i.kind == "joker" and not i.sold
                        and gs.dollars >= i.discounted_price(gs.shop_discount)
                        for i in gs.current_shop
                    )
                    if affordable:
                        reward += R_HEUR_LEAVE_EMPTY
                # Penalize wasted money above the nearest $5 interest boundary
                # Interest: $1 per $5, cap at $25. So optimal is to spend down
                # to the nearest $5 (e.g. $9 -> spend $4, keep $5 for interest)
                # Above $25, ALL excess is waste (interest capped)
                interest_floor = min(gs.dollars // 5 * 5, gs.interest_cap)
                wasted = gs.dollars - interest_floor
                if wasted > 0:
                    reward += R_HEUR_WASTE_MONEY * wasted
                gs.step({"type": "leave_shop"})
                self._auto_advance()
                self._update_play_combos()

            elif action == 46:
                # Director's Cut / Retcon: reroll the upcoming Boss Blind ($10)
                gs.step({"type": "reroll_boss"})

            elif action in (28, 29):
                # Use consumable in shop (planets)
                c_idx = action - 28
                if c_idx < len(gs.consumable_hand):
                    from .consumables import ALL_PLANETS as _AP
                    if gs.consumable_hand[c_idx] in _AP:
                        gs.step({"type": "use_consumable",
                                 "consumable_idx": c_idx, "target_cards": []})
                        reward += R_HEUR_USE_PLANET

        # ── Auto-advance non-decision states ─────────────────────────────
        self._auto_advance()

        # ── Compute milestone rewards ─────────────────────────────────────
        new_state = gs.state
        new_ante  = gs.ante
        new_blind = gs.blind_idx

        if new_state == State.GAME_OVER:
            if gs._obs().won:
                reward += R_WIN
            else:
                reward += R_LOSE
        elif new_state == State.SHOP:
            # Crossed into shop = blind was beaten
            if (new_ante, new_blind) != (self._prev_ante, self._prev_blind_idx):
                was_boss = (self._prev_blind_idx == 2)
                # Inverse ante scaling: ante 1 blind = 16.0, ante 8 blind = 2.0
                blind_reward = R_BLIND_BASE * (9 - self._prev_ante)
                reward += blind_reward
                if was_boss:
                    reward += R_ANTE_COMPLETE
                self._prev_ante = new_ante
                self._prev_blind_idx = new_blind
                self._prev_progress = 0.0

        terminated = (new_state == State.GAME_OVER)
        truncated  = False
        obs = self._encode_obs()
        info = {
            "ante": gs.ante,
            "blind_kind": gs.current_blind.kind,
            "chips_scored": gs.chips_scored,
            "chips_target": gs.current_blind.chips_target,
            "dollars": gs.dollars,
            "n_jokers": len(gs.jokers),
            "state": new_state.name,
        }

        self._episode_reward += reward

        # ── Highlight reel: write detailed log for good episodes ──────────
        if terminated and gs.ante >= 7 and self._play_history:
            self._write_highlight(gs, self._episode_reward)

        return obs, reward, terminated, truncated, info

    def _write_highlight(self, gs, total_reward: float):
        """Append a rich episode record to logs_sim/highlights.jsonl."""
        import json, os
        os.makedirs("logs_sim", exist_ok=True)
        record = {
            "seed":         self._seed,
            "ante_reached": gs.ante,
            "won":          gs.ante > 8,
            "total_reward": round(total_reward, 2),
            "dollars":      gs.dollars,
            "steps":        self._steps,
            "jokers_final": [j.key for j in gs.jokers],
            "plays": [
                {
                    "ante":      p["ante"],
                    "blind":     p["blind"],
                    "hand_type": p["hand_type"],
                    "cards":     p["cards"],
                    "chips":     p["chips"],
                    "total":     p["total"],
                    "target":    p["target"],
                    "jokers":    p["jokers"],
                }
                for p in self._play_history
            ],
        }
        with open("logs_sim/highlights.jsonl", "a") as f:
            f.write(json.dumps(record) + "\n")

    def _auto_advance(self):
        """Auto-step through non-decision states (ROUND_EVAL, BOOSTER_OPEN)."""
        for _ in range(20):   # safety cap
            s = self.game.state
            if s == State.ROUND_EVAL:
                self.game.step({"type": "noop"})
            elif s == State.BOOSTER_OPEN:
                # Auto-pick first item
                if self.game.booster_choices:
                    self.game.step({"type": "pick_booster", "indices": [0]})
                else:
                    self.game.step({"type": "skip_booster"})
            else:
                break

    # ── Observation encoding ─────────────────────────────────────────────────

    def _encode_obs(self) -> np.ndarray:
        obs = np.zeros(OBS_DIM, dtype=np.float32)
        gs  = self.game
        idx = 0

        # ── Game scalars (14) ─────────────────────────────────────────────
        obs[idx]   = gs.ante / 8.0
        obs[idx+1] = gs.blind_idx / 2.0
        obs[idx+2] = int(gs.current_blind.is_boss)
        progress   = gs.chips_scored / max(gs.current_blind.chips_target, 1)
        obs[idx+3] = min(progress, 2.0)
        obs[idx+4] = math.log1p(gs.current_blind.chips_target) / math.log1p(100000)
        obs[idx+5] = gs.hands_left  / max(gs.base_hands, 1)
        obs[idx+6] = gs.discards_left / max(gs.base_discards, 1)
        obs[idx+7] = min(gs.dollars / 50.0, 2.0)
        obs[idx+8] = len(gs.jokers) / gs.joker_slots
        # Phase one-hot (3)
        phase_map = {
            State.BLIND_SELECT:   idx+9,
            State.SELECTING_HAND: idx+10,
            State.SHOP:           idx+11,
            State.ROUND_EVAL:     idx+12,
            State.GAME_OVER:      idx+13,
        }
        obs[phase_map.get(gs.state, idx+13)] = 1.0
        idx += GAME_SCALARS

        # ── Hand cards (8 × 26 = 208) ─────────────────────────────────────
        for slot in range(N_HAND_SLOTS):
            if slot < len(gs.hand):
                c = gs.hand[slot]
                if not c.flipped:
                    obs[idx]   = (c.rank - 2) / 12.0
                    # Suit one-hot (4)
                    si = SUIT_ORDER.index(c.suit) if c.suit in SUIT_ORDER else 0
                    obs[idx+1+si] = 1.0
                    # Enhancement one-hot (9)
                    if c.enhancement in ENHANCEMENTS:
                        obs[idx+5+ENHANCEMENTS.index(c.enhancement)] = 1.0
                    # Edition one-hot (5)
                    if c.edition in EDITIONS:
                        obs[idx+14+EDITIONS.index(c.edition)] = 1.0
                    # Seal one-hot (5)
                    if c.seal in SEALS:
                        obs[idx+19+SEALS.index(c.seal)] = 1.0
                    obs[idx+24] = float(c.debuffed)
                # Face-down cards (The Mark): only "present" is visible
                obs[idx+25] = 1.0   # present
            idx += CARD_FEATURES

        # ── Joker slots (5 × 10 = 50) ─────────────────────────────────────
        for slot in range(N_JOKER_SLOTS):
            if slot < len(gs.jokers):
                j = gs.jokers[slot]
                obs[idx]   = 1.0    # present
                if not gs.jokers_flipped:  # Amber Acorn: joker identity/stats hidden
                    obs[idx+1] = JOKER_IDX.get(j.key, 0) / max(N_JOKERS, 1)
                    info = JOKER_CATALOGUE.get(j.key, {})
                    rarity_map = {"Common": 0, "Uncommon": 1, "Rare": 2, "Legendary": 3}
                    obs[idx+2] = rarity_map.get(info.get("rarity", "Common"), 0) / 3.0
                    edition_map = {k: i for i, k in enumerate(EDITIONS)}
                    obs[idx+3] = edition_map.get(j.edition, 0) / 4.0
                    obs[idx+4] = math.log1p(j.state.get("mult", 0)) / 10.0
                    obs[idx+5] = math.log1p(j.state.get("chips", 0)) / 10.0
                    obs[idx+6] = math.log1p(j.state.get("sell_value", 2)) / 5.0
                    obs[idx+7] = float(j.state.get("destroyed", False))
                    obs[idx+8] = min(j.state.get("mult_mult", 1.0), 5.0) / 5.0
                    obs[idx+9] = info.get("price", 6) / 20.0
            idx += JOKER_FEATURES

        # ── Shop items (7 × 6 = 42) ───────────────────────────────────────
        for slot in range(N_SHOP_SLOTS):
            if slot < len(gs.current_shop):
                item = gs.current_shop[slot]
                obs[idx]   = float(not item.sold)
                kind_map   = {"joker": 1, "planet": 2, "tarot": 3,
                              "spectral": 4, "voucher": 5, "booster": 6, "card": 7}
                obs[idx+1] = kind_map.get(item.kind, 0) / 7.0
                obs[idx+2] = item.price / 20.0
                can_afford  = float(gs.dollars >= item.price and not item.sold)
                obs[idx+3] = can_afford
                # Negative jokers bypass the slot cap (grant_joker) — mirror it
                obs[idx+4] = (float(len(gs.jokers) < gs.joker_slots
                                    or item.edition == "Negative")
                              if item.kind=="joker" else 0.0)
                obs[idx+5] = float(len(gs.consumable_hand) < gs.consumable_slots) if item.kind in ("planet","tarot","spectral") else 0.0
            idx += SHOP_FEATURES

        # ── Planet levels (12) ────────────────────────────────────────────
        for ht in HAND_TYPES:
            obs[idx] = min((gs.planet_levels.get(ht, 1) - 1) / 10.0, 1.0)
            idx += 1

        # ── Consumable hand (2 × 8 = 16) ──────────────────────────────────
        from .consumables import PLANET_HAND, ALL_TAROTS, ALL_SPECTRALS, ALL_VOUCHERS
        for slot in range(N_CONS_SLOTS):
            if slot < len(gs.consumable_hand):
                key = gs.consumable_hand[slot]
                obs[idx]   = 1.0   # present
                obs[idx+1] = float(key in PLANET_HAND)
                obs[idx+2] = float(key in ALL_TAROTS)
                obs[idx+3] = float(key in ALL_SPECTRALS)
                # Planet: encode which hand type it upgrades
                if key in PLANET_HAND:
                    ht = PLANET_HAND[key]
                    obs[idx+4] = HAND_TYPES.index(ht) / 11.0 if ht in HAND_TYPES else 0.0
                obs[idx+5] = gs.dollars / 50.0   # afford context
                obs[idx+6] = gs.hands_left / max(gs.base_hands, 1)
                obs[idx+7] = float(gs.state == State.SELECTING_HAND)
            idx += CONS_FEATURES

        # ── Shop context (60) — richer features for informed shop decisions ──

        # Reroll info (2)
        reroll_cost = max(0, gs.reroll_cost - gs.reroll_discount)
        obs[idx]   = min(reroll_cost, 10) / 10.0
        obs[idx+1] = gs.free_rerolls_remaining / max(gs.free_rerolls_per_round + 1, 1)
        idx += 2

        # Vouchers owned (32 binary flags — full real voucher set)
        for vi, vkey in enumerate(ALL_VOUCHERS):
            obs[idx + vi] = 1.0 if vkey in gs.vouchers else 0.0
        idx += len(ALL_VOUCHERS)

        # Boss blind one-hot (28 — full real boss set)
        BOSS_TYPES = [
            "bl_hook", "bl_goad", "bl_window", "bl_manacle", "bl_eye",
            "bl_mouth", "bl_fish", "bl_plant", "bl_needle", "bl_head",
            "bl_tooth", "bl_wall", "bl_house", "bl_mark", "bl_flint",
            "bl_psychic", "bl_grim", "bl_verdant", "bl_serpent", "bl_pillar",
            "bl_water", "bl_ox", "bl_cerulean", "bl_amber", "bl_violet",
            "bl_crimson", "bl_club", "bl_wheel",
        ]
        boss_key = gs.current_blind.boss_key if gs.current_blind.is_boss else ""
        if boss_key in BOSS_TYPES:
            obs[idx + BOSS_TYPES.index(boss_key)] = 1.0
        idx += len(BOSS_TYPES)

        # Deck composition summary (8): DRAW PILE only (hand already encoded above)
        # This gives the agent card counting — what's left to draw after discards
        draw_pile = gs.deck
        deck_n = max(1, len(draw_pile))
        suit_counts = [0, 0, 0, 0]
        face_count = ace_count = number_count = 0
        for card in draw_pile:
            si = SUIT_ORDER.index(card.suit) if card.suit in SUIT_ORDER else 0
            suit_counts[si] += 1
            if card.rank >= 11 and card.rank <= 13:
                face_count += 1
            elif card.rank == 14:
                ace_count += 1
            else:
                number_count += 1
        for i in range(4):
            obs[idx + i] = suit_counts[i] / deck_n
        obs[idx + 4] = face_count / deck_n
        obs[idx + 5] = ace_count / deck_n
        obs[idx + 6] = number_count / deck_n
        obs[idx + 7] = len(draw_pile) / 60.0
        idx += 8

        # Enhancement / edition / seal counts in draw pile (8)
        foil = holo = poly = gold_enh = wild = seal_gold = seal_red = seal_blue = 0
        for card in draw_pile:
            enh = getattr(card, 'enhancement', 'None')
            edn = getattr(card, 'edition', 'None')
            seal = getattr(card, 'seal', 'None')
            if edn == "Foil": foil += 1
            elif edn == "Holographic": holo += 1
            elif edn == "Polychrome": poly += 1
            if enh == "Gold": gold_enh += 1
            if enh == "Wild": wild += 1
            if seal == "Gold": seal_gold += 1
            elif seal == "Red": seal_red += 1
            elif seal == "Blue": seal_blue += 1
        obs[idx:idx+8] = [foil/deck_n, holo/deck_n, poly/deck_n, gold_enh/deck_n,
                          wild/deck_n, seal_gold/deck_n, seal_red/deck_n, seal_blue/deck_n]
        idx += 8

        # ── Skip-blind Tag features (29) ──────────────────────────────────
        # Offered/claimed-tag one-hot (24) + pending-tag state scalars (5).
        # The claimed tag persists through the following shop, so the agent can
        # see what it earned from the last skip.
        from .tags import TAG_ORDER
        for ti, tkey in enumerate(TAG_ORDER):
            obs[idx + ti] = 1.0 if gs.current_tag == tkey else 0.0
        idx += TAG_FEATURES
        obs[idx]   = gs.skipped_blinds / 8.0
        obs[idx+1] = float(gs.investment_pending)
        obs[idx+2] = float(gs.double_tag_active)
        obs[idx+3] = gs.hand_size_bonus_next_round / 3.0
        obs[idx+4] = float(gs.boss_reroll_pending)
        idx += PENDING_TAG_FEATURES

        assert idx == OBS_DIM, f"obs encoding mismatch: {idx} != {OBS_DIM}"
        return obs

    # ── Play combo enumeration ────────────────────────────────────────────────

    def _update_play_combos(self):
        """Pre-compute top-20 card combos for current hand, ranked by hand strength.
        Filters out combos rejected by boss blind restrictions (bl_mouth, bl_eye, bl_psychic).
        If boss restrictions eliminate ALL combos, includes best unfiltered combo as fallback
        (game.py will consume the hand on rejection, preventing infinite loops)."""
        hand = self.game.hand
        if not hand:
            self._play_combos = []
            return

        n = len(hand)
        scored: list[tuple] = []
        fallback: list[tuple] = []  # unfiltered combos for stuck situations

        # Boss blind restrictions
        gs = self.game
        boss = gs.current_blind.boss_key if gs.current_blind else ""
        played_types = gs.played_hand_types_this_round

        # Enumerate all k=1..5 card subsets
        for k in range(1, min(6, n+1)):
            # bl_psychic: must play exactly 5 cards
            if boss == "bl_psychic" and k != 5:
                continue

            for combo in itertools.combinations(range(n), k):
                cards = [hand[i] for i in combo]
                try:
                    hand_type, scoring_cards = evaluate_hand(cards)
                    priority = HAND_PRIORITY.get(hand_type, 0)
                    # Tiebreak by actual score (accounts for jokers, planet levels,
                    # card enhancements/editions). Changed from rank_sum tiebreak
                    # at run 2 start (~4.1M total steps, 2026-03-28 17:43 MDT).
                    actual_score, _ = score_hand(
                        scoring_cards=scoring_cards,
                        all_cards=cards,
                        hand_type=hand_type,
                        jokers=gs.jokers,
                        planet_levels=gs.planet_levels,
                        hands_left=gs.hands_left,
                        discards_left=gs.discards_left,
                        dollars=gs.dollars,
                        ante=gs.ante,
                        deck_remaining=len(gs.deck),
                        half_base=(boss == "bl_flint"),
                    )
                    entry = (priority, actual_score, list(combo))
                    fallback.append(entry)

                    # Boss blind filtering
                    if boss == "bl_eye" and hand_type in played_types:
                        continue
                    if boss == "bl_mouth" and played_types and hand_type not in played_types:
                        continue
                    if boss == "bl_cerulean" and gs.bell_card is not None and gs.bell_card not in cards:
                        continue

                    scored.append(entry)
                except Exception:
                    pass

        # Sort descending: best hand first
        scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
        if not scored and fallback:
            # All combos blocked by boss — include best fallback so the agent
            # can at least attempt something (game.py rejects invalid plays
            # without consuming a hand, so this is safe)
            fallback.sort(key=lambda x: (x[0], x[1]), reverse=True)
            scored = fallback[:1]
        self._play_combos = [s[2] for s in scored[:20]]


# ════════════════════════════════════════════════════════════════════════════
# Throughput benchmark
# ════════════════════════════════════════════════════════════════════════════

def benchmark(n_steps: int = 10_000, seed: int = 0) -> dict:
    """
    Run random-policy benchmark and return throughput stats.
    """
    import random as _random

    env = BalatroSimEnv(seed=seed)
    env.reset()
    rng = _random.Random(seed)

    t0 = time.perf_counter()
    steps = 0
    episodes = 0
    total_reward = 0.0

    obs, _ = env.reset()
    for _ in range(n_steps):
        action = rng.randint(0, N_ACTIONS - 1)
        obs, reward, terminated, truncated, info = env.step(action)
        total_reward += reward
        steps += 1
        if terminated or truncated:
            obs, _ = env.reset()
            episodes += 1

    elapsed = time.perf_counter() - t0
    return {
        "steps":        steps,
        "episodes":     episodes,
        "elapsed_s":    round(elapsed, 3),
        "sps":          round(steps / elapsed, 0),
        "mean_reward":  round(total_reward / max(episodes, 1), 3),
    }


if __name__ == "__main__":
    print(f"OBS_DIM    = {OBS_DIM}")
    print(f"N_ACTIONS  = {N_ACTIONS}")
    print()
    print("Smoke test...")
    env = BalatroSimEnv(seed=42)
    obs, _ = env.reset()
    print(f"  obs shape: {obs.shape}, dtype: {obs.dtype}")
    print(f"  obs range: [{obs.min():.3f}, {obs.max():.3f}]")
    print()
    print("Benchmarking 10,000 random steps...")
    stats = benchmark(10_000)
    print(f"  {stats['sps']:,.0f} steps/sec")
    print(f"  {stats['episodes']} episodes in {stats['elapsed_s']}s")
    print(f"  mean reward per episode: {stats['mean_reward']}")
