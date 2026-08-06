"""
env_v5.py — Dual-agent Gymnasium environment for V5 Balatro RL.

Two separate agents share one game instance:
  - Play agent:  handles BLIND_SELECT + SELECTING_HAND phases
  - Shop agent:  handles SHOP phase (with hierarchical pack sub-states)

Communication:
  Shop agent produces a 32-dim communication vector at end of each shop phase.
  This vector is concatenated to the play agent's 342-dim obs (total 374 dims).
  Initialized to zeros; populated once the shop agent network is wired in.

Observation spaces:
  Play:  Box(374,)  — 342 game obs + 32 comm vector
  Shop:  Box(SHOP_OBS_DIM,)  — shop-specific features (~166 dims)

Action spaces:
  Play:  Discrete(46)        — same as v4
  Shop (normal):  Discrete(17)
    0     reroll
    1     leave_shop
    2-7   buy shop item 0-5
    8-9   buy booster pack 0-1
    10-14 sell joker 0-4
    15-16 use consumable slot 0-1 (planets / non-targeting tarots only)

  Shop (PACK_OPEN substate):  Discrete(N+1)
    0..N-1  pick card/tarot/planet at index i from revealed pack
    N       skip (take nothing)

  Shop (PACK_TARGET substate):  Discrete(53)
    0..51   apply tarot/effect to deck card at index i
    52      skip targeting

Usage in training loop:
  obs, info = env.reset()
  while True:
      agent = info['agent']      # 'play' or 'shop'
      action = policy[agent](obs)
      obs, reward, terminated, truncated, info = env.step(action)
      ...

step() always returns obs for whoever acts NEXT (info['agent']).
"""
from __future__ import annotations

import math
import random
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
from .shop import (
    buy_item, sell_joker, reroll_shop, BOOSTER_CATALOGUE,
    JOKER_CATALOGUE,
)
from .consumables import (
    apply_tarot, apply_planet, apply_spectral,
    TAROT_NAME, PLANET_NAME, SPECTRAL_NAME,
    ALL_TAROTS, ALL_PLANETS,
)
from .constants import SUITS, RANK_CHIPS, STARTING_HANDS, STARTING_DISCARDS, HAND_SIZE
from .quality import loadout_quality

# ════════════════════════════════════════════════════════════════════════════
# Constants
# ════════════════════════════════════════════════════════════════════════════

COMM_DIM   = 32          # communication vector size (shop -> play)
from .env_sim import OBS_DIM as _SIM_OBS_DIM
PLAY_OBS_BASE = _SIM_OBS_DIM   # from env_sim.py (402 with shop context features)
PLAY_OBS_DIM  = PLAY_OBS_BASE + COMM_DIM   # 434

# Shop obs dimensions
SHOP_SCALARS     = 10    # ante, round, dollars, interest, hands_left, reroll_cost,
                         # joker_slots_used, joker_slots_max, consumable_slots, deck_size
SHOP_JOKER_FEATS = 10    # per joker slot
N_SHOP_JOKER_SLOTS = 5
SHOP_ITEM_FEATS  = 5     # per shop item slot
N_SHOP_ITEM_SLOTS = 6
PACK_SLOT_FEATS  = 5     # per booster pack slot
N_PACK_SLOTS     = 2
HAND_LEVEL_FEATS = 12    # one per hand type
CONS_FEATS       = 4     # per consumable slot
N_CONS_SLOTS_SHOP = 2
N_VOUCHERS       = 27    # binary flags
BOSS_FEATS       = 15    # one-hot over boss blind types
DECK_COMP_FEATS  = 18    # 13 rank counts + 4 suit counts + total deck size (normalized)
ENHANCE_FEATS    = 8     # foil/holo/poly/gold/wild counts + seal type counts

SHOP_OBS_DIM = (
    SHOP_SCALARS
    + N_SHOP_JOKER_SLOTS * SHOP_JOKER_FEATS   # 50
    + N_SHOP_ITEM_SLOTS  * SHOP_ITEM_FEATS    # 30
    + N_PACK_SLOTS       * PACK_SLOT_FEATS    # 10
    + HAND_LEVEL_FEATS                        # 12
    + N_CONS_SLOTS_SHOP  * CONS_FEATS         # 8
    + N_VOUCHERS                              # 27
    + BOSS_FEATS                              # 15
    + DECK_COMP_FEATS                         # 18
    + ENHANCE_FEATS                           # 8
)  # = 10+50+30+10+12+8+27+15+18+8 = 188

# Normal shop action space
SHOP_N_ACTIONS = 17
# 0=reroll, 1=leave, 2-7=buy item 0-5, 8-9=buy pack 0-1,
# 10-14=sell joker 0-4, 15-16=use consumable 0-1

# Play agent action space (same as v4)
PLAY_N_ACTIONS = 46

# Reward constants (same as v4 run 6)
R_BLIND_BASE    = 2.0   # * (9 - ante)
R_ANTE_COMPLETE = 5.0
R_WIN           = 50.0
R_LOSE          = -2.0
R_SCORE_PROGRESS= 0.05
R_QUALITY_SCALE = 0.5   # loadout quality delta per shop phase (bumped from 0.2)
R_LEAVE_SHOP    = -0.1  # small penalty for leaving shop — encourages exploration
R_SPEND         = 0.05  # reward per dollar spent — incentivizes buying over hoarding

# Heuristic reward shaping (mirrors V4 Lua shop heuristic)
# Small bonuses for taking "smart" actions — agent can still learn to deviate
R_HEUR_BUY_JOKER     = 0.3   # bought a joker (filling empty slots is always good)
R_HEUR_UPGRADE       = 0.5   # sold weak joker and bought a stronger one
R_HEUR_USE_PLANET    = 0.2   # used a planet card (free hand upgrade)
R_HEUR_REROLL_SMART  = 0.1   # rerolled when nothing useful and can afford it
R_HEUR_LEAVE_EMPTY   = -0.2  # left shop with unspent money and empty joker slots

# Pack sub-states
SUBSTATE_NORMAL      = "normal"
SUBSTATE_PACK_OPEN   = "pack_open"
SUBSTATE_PACK_TARGET = "pack_target"

ENHANCEMENTS = ["None","Bonus","Mult","Wild","Glass","Steel","Stone","Gold","Lucky"]
EDITIONS     = ["None","Foil","Holographic","Polychrome","Negative"]
SEALS        = ["None","Gold","Red","Blue","Purple"]
SUIT_ORDER   = ["Spades","Hearts","Clubs","Diamonds"]
HAND_TYPES   = [
    "High Card","Pair","Two Pair","Three of a Kind","Straight","Flush",
    "Full House","Four of a Kind","Straight Flush","Five of a Kind",
    "Flush House","Flush Five",
]
BOSS_TYPES = [
    "The Ox","The Hook","The Wall","The Wheel","The Arm","The Club",
    "The Fish","The Psychic","The Goad","The Water","The Window",
    "The Manacle","The Eye","The Mouth","The Plant",
]
BOSS_IDX = {b: i for i, b in enumerate(BOSS_TYPES)}

JOKER_KEYS = sorted(JOKER_CATALOGUE.keys())
JOKER_IDX  = {k: i for i, k in enumerate(JOKER_KEYS)}

from .shop import BOOSTER_CATALOGUE   # already imported above — repeated for clarity


# ════════════════════════════════════════════════════════════════════════════
# Environment
# ════════════════════════════════════════════════════════════════════════════

class BalatroSimEnvV5(gym.Env):
    """
    Dual-agent Balatro environment for V5 training.

    The env routes control between the play agent and shop agent depending on
    the current game phase. The caller checks info['agent'] to know who acts next.
    """

    metadata = {"render_modes": []}

    def __init__(self, seed: Optional[int] = None):
        super().__init__()

        # Play agent spaces
        self.play_observation_space = spaces.Box(
            low=-1.0, high=10.0, shape=(PLAY_OBS_DIM,), dtype=np.float32
        )
        self.play_action_space = spaces.Discrete(PLAY_N_ACTIONS)

        # Shop agent spaces (normal phase; substates have dynamic size handled in step)
        self.shop_observation_space = spaces.Box(
            low=-1.0, high=10.0, shape=(SHOP_OBS_DIM,), dtype=np.float32
        )
        self.shop_action_space = spaces.Discrete(SHOP_N_ACTIONS)

        # Default gym spaces (play agent for compatibility)
        self.observation_space = self.play_observation_space
        self.action_space = self.play_action_space

        self._seed = seed
        self.game = BalatroGame(seed=seed)

        # State tracking
        self._prev_progress  = 0.0
        self._prev_ante      = 1
        self._prev_blind_idx = 0
        self._steps          = 0
        self._episode_reward = 0.0

        # Communication vector (shop -> play); updated each shop phase
        self._comm_vec = np.zeros(COMM_DIM, dtype=np.float32)

        # Quality tracking for auxiliary reward
        self._prev_quality = 0.0

        # Pack sub-state
        self._shop_substate   = SUBSTATE_NORMAL
        self._pack_choices: list = []       # items revealed in open pack
        self._pack_picks_left: int = 0      # picks remaining
        self._pending_tarot: Optional[str] = None  # tarot waiting for target

        # Play combo cache
        self._play_combos: list[list[int]] = []

    # ── gym API ──────────────────────────────────────────────────────────────

    def reset(self, seed=None, options=None):
        if seed is not None:
            self._seed = seed
        self.game = BalatroGame(seed=self._seed)
        self._prev_progress  = 0.0
        self._prev_ante      = 1
        self._prev_blind_idx = 0
        self._steps          = 0
        self._episode_reward = 0.0
        self._comm_vec       = np.zeros(COMM_DIM, dtype=np.float32)
        self._prev_quality   = 0.0
        self._shop_substate  = SUBSTATE_NORMAL
        self._pack_choices   = []
        self._pack_picks_left= 0
        self._pending_tarot  = None
        self._update_play_combos()

        obs, info = self._get_obs_and_info()
        return obs, info

    def step(self, action: int):
        """
        Take an action. Routes to play or shop logic based on current game state.
        Returns (obs, reward, terminated, truncated, info).
        obs is for whoever acts NEXT (check info['agent']).
        """
        gs = self.game
        reward = 0.0
        terminated = False
        self._steps += 1

        agent = self._current_agent()

        if agent == "shop":
            reward = self._step_shop(action)
        else:
            reward = self._step_play(action, gs)

        terminated = (self.game.state == State.GAME_OVER)
        self._episode_reward += reward

        if terminated:
            self._update_play_combos()

        obs, info = self._get_obs_and_info()
        info["step_reward"] = reward
        info["total_reward"] = self._episode_reward
        return obs, reward, terminated, False, info

    # ── Agent routing ─────────────────────────────────────────────────────────

    def _current_agent(self) -> str:
        gs = self.game
        state = gs.state
        if state == State.SHOP or self._shop_substate != SUBSTATE_NORMAL:
            return "shop"
        return "play"

    def _get_obs_and_info(self):
        agent = self._current_agent()
        if agent == "shop":
            obs = self.get_shop_obs()
        else:
            obs = self.get_play_obs()

        info = {
            "agent": agent,
            "shop_substate": self._shop_substate,
            "pack_choices": self._pack_choices,
            "pack_picks_left": self._pack_picks_left,
        }
        return obs, info

    # ── Play step ─────────────────────────────────────────────────────────────

    def _step_play(self, action: int, gs) -> float:
        reward = 0.0
        state  = gs.state
        game   = self.game

        if state == State.BLIND_SELECT:
            if action == 31 and gs.blind_idx != 2:
                game.step({"type": "skip_blind"})
                # Skip enters shop — initialize quality baseline
                if game.state == State.SHOP:
                    self._prev_quality = loadout_quality(
                        game.jokers,
                        [game.planet_levels.get(ht, 1) for ht in HAND_TYPES],
                        game.deck,
                    )
            else:
                game.step({"type": "play_blind"})

        elif state == State.SELECTING_HAND:
            if action <= 19 and self._play_combos:
                combo_idx     = min(action, len(self._play_combos) - 1)
                combo         = self._play_combos[combo_idx]
                prev_ante     = game.ante
                prev_blind    = game.blind_idx
                prev_progress = (game.chips_scored / max(game.current_blind.chips_target, 1) if game.current_blind else 0.0)

                game.step({"type": "play", "cards": combo})

                new_state    = game.state
                new_progress = (game.chips_scored / max(game.current_blind.chips_target, 1) if game.current_blind else 0.0)

                delta = new_progress - prev_progress
                if delta > 0:
                    reward += R_SCORE_PROGRESS * math.log1p(delta) * 100

                if new_state == State.SHOP:
                    # Initialize quality baseline for this shop visit
                    self._prev_quality = loadout_quality(
                        game.jokers,
                        [game.planet_levels.get(ht, 1) for ht in HAND_TYPES],
                        game.deck,
                    )
                    if (game.ante, game.blind_idx) != (prev_ante, prev_blind):
                        was_boss = (prev_blind == 2)
                        reward += R_BLIND_BASE * (9 - prev_ante)
                        if was_boss:
                            reward += R_ANTE_COMPLETE
                        self._prev_ante      = game.ante
                        self._prev_blind_idx = game.blind_idx
                        self._prev_progress  = 0.0
                elif new_state == State.GAME_OVER:
                    reward += R_WIN if getattr(game, "won", False) else R_LOSE

                self._prev_progress = new_progress
                self._update_play_combos()

            elif 20 <= action <= 27:
                card_idx = action - 20
                if card_idx < len(game.hand) and game.discards_left > 0:
                    game.step({"type": "discard", "cards": [card_idx]})
                    self._update_play_combos()

            elif action in (28, 29):
                cons_idx = action - 28
                if cons_idx < len(game.consumable_hand):
                    ckey = game.consumable_hand[cons_idx]
                    if ckey in ALL_PLANETS:
                        game.step({"type": "use_consumable",
                                   "cons_idx": cons_idx, "target_indices": []})

        return reward

    # ── Shop step ─────────────────────────────────────────────────────────────

    def _step_shop(self, action: int) -> float:
        reward = 0.0

        if self._shop_substate == SUBSTATE_PACK_OPEN:
            reward = self._step_pack_open(action)
        elif self._shop_substate == SUBSTATE_PACK_TARGET:
            reward = self._step_pack_target(action)
        else:
            reward = self._step_shop_normal(action)

        return reward

    def _step_shop_normal(self, action: int) -> float:
        reward = 0.0
        game = self.game

        if action == 0:      # reroll
            # Heuristic: reroll is smart if nothing useful in shop and can afford it
            cost = max(0, game.reroll_cost - game.reroll_discount)
            has_affordable_joker = any(
                i.kind == "joker" and not i.sold
                and game.dollars >= i.discounted_price(game.shop_discount)
                and len(game.jokers) < game.joker_slots
                for i in game.current_shop
            )
            if not has_affordable_joker and game.dollars > cost * 2:
                reward += R_HEUR_REROLL_SMART
            reroll_shop(game)

        elif action == 1:    # leave shop
            prev_quality = self._prev_quality
            curr_quality = loadout_quality(
                game.jokers,
                [game.planet_levels.get(ht, 1) for ht in HAND_TYPES],
                game.deck,
            )
            quality_delta = curr_quality - prev_quality
            reward += R_QUALITY_SCALE * quality_delta
            reward += R_LEAVE_SHOP   # small penalty to discourage always leaving
            # Heuristic: penalize leaving with money and empty joker slots
            if len(game.jokers) < game.joker_slots:
                affordable = any(
                    i.kind == "joker" and not i.sold
                    and game.dollars >= i.discounted_price(game.shop_discount)
                    for i in game.current_shop
                )
                if affordable:
                    reward += R_HEUR_LEAVE_EMPTY  # leaving when you could buy
            self._prev_quality = curr_quality
            game.step({"type": "leave_shop"})

        elif 2 <= action <= 7:   # buy shop item 0-5
            item_idx = action - 2
            items = [i for i in game.current_shop if not i.sold and i.kind != "booster"]
            if item_idx < len(items):
                item = items[item_idx]
                price = item.discounted_price(game.shop_discount)
                if item.kind == "booster":
                    bought = buy_item(game, item)
                    if bought:
                        reward += R_SPEND * price
                        self._enter_pack_open(game)
                else:
                    n_jokers_before = len(game.jokers)
                    before = game.dollars
                    buy_item(game, item)
                    spent = before - game.dollars
                    if spent > 0:
                        reward += R_SPEND * spent
                        # Heuristic: bonus for buying a joker into an empty slot
                        if item.kind == "joker" and len(game.jokers) > n_jokers_before:
                            reward += R_HEUR_BUY_JOKER

        elif action in (8, 9):  # buy booster pack 0-1
            pack_idx = action - 8
            packs = [i for i in game.current_shop if i.kind == "booster" and not i.sold]
            if pack_idx < len(packs):
                before = game.dollars
                bought = buy_item(game, packs[pack_idx])
                if bought:
                    spent = before - game.dollars
                    reward += R_SPEND * max(spent, 0)
                    self._enter_pack_open(game)

        elif 10 <= action <= 14:  # sell joker 0-4
            joker_idx = action - 10
            if joker_idx < len(game.jokers):
                sold_joker = game.jokers[joker_idx]
                sold_value = _joker_value(sold_joker)
                # Check if there's a better joker in the shop we could buy after selling
                sell_price = sold_joker.state.get("sell_value", 2)
                budget_after = game.dollars + sell_price
                best_shop_value = 0
                for item in game.current_shop:
                    if item.kind == "joker" and not item.sold:
                        if budget_after >= item.discounted_price(game.shop_discount):
                            best_shop_value = max(best_shop_value, _joker_value(
                                type('FakeJoker', (), {'key': item.key, 'edition': item.edition})()
                            ))
                # Heuristic: reward sell-upgrade (sell weak, buy strong)
                if best_shop_value > sold_value:
                    reward += R_HEUR_UPGRADE
                sell_joker(game, joker_idx)
            else:
                sell_joker(game, joker_idx)

        elif action in (15, 16):  # use consumable 0-1
            cons_idx = action - 15
            cons = game.consumable_hand
            if cons_idx < len(cons):
                ckey = cons[cons_idx]
                if ckey in ALL_PLANETS:
                    apply_planet(game, ckey)
                    game.consumable_hand.pop(cons_idx)
                    reward += R_HEUR_USE_PLANET  # Heuristic: planets are always good
                elif ckey in ALL_TAROTS:
                    # Tarots that don't need a card target can fire immediately
                    # Tarots that need targets → enter PACK_TARGET substate
                    if _tarot_needs_target(ckey):
                        self._pending_tarot = ckey
                        self._shop_substate = SUBSTATE_PACK_TARGET
                    else:
                        apply_tarot(game, ckey)
                        game.consumable_hand.pop(cons_idx)

        return reward

    def _enter_pack_open(self, game):
        """Enter PACK_OPEN substate with current booster_choices."""
        self._pack_choices = list(getattr(game, "booster_choices", []))
        self._pack_picks_left = getattr(game, "booster_picks_remaining", 1)
        if self._pack_choices:
            self._shop_substate = SUBSTATE_PACK_OPEN
        # Clear on game
        game.booster_choices = []
        game.booster_picks_remaining = 0

    def _step_pack_open(self, action: int) -> float:
        """Handle a pick from an open pack."""
        n = len(self._pack_choices)
        game = self.game

        if action == n or not self._pack_choices:
            # Skip / no more picks
            self._exit_pack_substate()
            return 0.0

        chosen = self._pack_choices[action]

        if isinstance(chosen, tuple) and chosen[0] == "card":
            # Standard pack — add card to deck
            card = chosen[1]
            game.deck.append(card)
        elif isinstance(chosen, str):
            key = chosen
            if key in ALL_TAROTS:
                if _tarot_needs_target(key):
                    self._pending_tarot = key
                    self._shop_substate = SUBSTATE_PACK_TARGET
                    self._pack_picks_left -= 1
                    if self._pack_picks_left <= 0:
                        self._pack_choices = []
                    return 0.0
                else:
                    # Fit into consumable slot if available, else use immediately
                    if len(game.consumable_hand) < game.consumable_slots:
                        game.consumable_hand.append(key)
                    else:
                        apply_tarot(game, key)
            elif key in ALL_PLANETS:
                if len(game.consumable_hand) < game.consumable_slots:
                    game.consumable_hand.append(key)
                else:
                    apply_planet(game, key)
            else:
                # Joker from Buffoon pack
                from .jokers.base import JokerInstance
                if len(game.jokers) < game.joker_slots:
                    game.jokers.append(JokerInstance(key, game=game))

        self._pack_picks_left -= 1
        if self._pack_picks_left <= 0 or not self._pack_choices:
            self._exit_pack_substate()

        return 0.0

    def _step_pack_target(self, action: int) -> float:
        """Handle card targeting for a tarot."""
        game = self.game
        key = self._pending_tarot

        if action <= 51 and key:
            deck_idx = action
            if deck_idx < len(game.deck):
                apply_tarot(game, key, target_indices=[deck_idx])
                if key in game.consumable_hand:
                    game.consumable_hand.remove(key)
            elif deck_idx < len(game.hand):
                # Fall back to hand targeting
                apply_tarot(game, key, target_indices=[deck_idx - len(game.deck)])
                if key in game.consumable_hand:
                    game.consumable_hand.remove(key)

        # Skip (action=52) or after targeting
        self._pending_tarot = None
        if self._pack_picks_left > 0 and self._pack_choices:
            self._shop_substate = SUBSTATE_PACK_OPEN
        else:
            self._exit_pack_substate()

        return 0.0

    def _exit_pack_substate(self):
        self._shop_substate = SUBSTATE_NORMAL
        self._pack_choices  = []
        self._pack_picks_left = 0

    # ── Observation builders ──────────────────────────────────────────────────

    def get_play_obs(self) -> np.ndarray:
        """374-dim: 342 game obs (from env_sim encoding) + 32 comm vector."""
        from .env_sim import BalatroSimEnv
        # Reuse v4 obs encoding by borrowing the internal method
        tmp = BalatroSimEnv.__new__(BalatroSimEnv)
        tmp.game = self.game
        tmp._play_combos = self._play_combos
        game_obs = tmp._encode_obs()
        return np.concatenate([game_obs, self._comm_vec], dtype=np.float32)

    def get_shop_obs(self) -> np.ndarray:
        """~188-dim shop-specific observation."""
        obs = np.zeros(SHOP_OBS_DIM, dtype=np.float32)
        idx = 0
        gs = self.game
        game = self.game

        # 1. Game scalars (10)
        deck_total = max(1, len(game.deck) + len(game.hand) + len(game.discard_pile
                         if hasattr(game, 'discard_pile') else []))
        scalars = [
            gs.ante / 8.0,
            gs.blind_idx / 2.0,
            min(game.dollars, 50) / 50.0,
            min(getattr(game, 'interest', 0), 25) / 25.0,
            gs.hands_left / 4.0,
            min(game.reroll_cost, 10) / 10.0,
            len(game.jokers) / 5.0,
            game.joker_slots / 5.0,
            game.consumable_slots / 4.0,
            len(game.deck) / 60.0,
        ]
        obs[idx:idx+SHOP_SCALARS] = scalars
        idx += SHOP_SCALARS

        # 2. Joker slots (5 × 10)
        for si in range(N_SHOP_JOKER_SLOTS):
            if si < len(game.jokers):
                j = game.jokers[si]
                jidx = JOKER_IDX.get(j.key, 0) / max(1, len(JOKER_KEYS))
                rarity_map = {"common": 0.25, "uncommon": 0.5, "rare": 0.75, "legendary": 1.0}
                from .shop import JOKER_CATALOGUE as JC
                meta = JC.get(j.key, {})
                rarity = rarity_map.get(meta.get("rarity", "common"), 0.25)
                sell_val = j.state.get("sell_value", 2) / 20.0
                edition = EDITIONS.index(getattr(j, "edition", "None")) / 4.0
                obs[idx]   = jidx
                obs[idx+1] = rarity
                obs[idx+2] = sell_val
                obs[idx+3] = edition
                obs[idx+4] = 1.0  # exists
            idx += SHOP_JOKER_FEATS

        # 3. Shop items (6 × 5)
        items = [i for i in game.current_shop if not i.sold and i.kind != "booster"]
        for si in range(N_SHOP_ITEM_SLOTS):
            if si < len(items):
                item = items[si]
                kind_map = {"joker": 0.2, "tarot": 0.4, "planet": 0.6, "spectral": 0.8, "voucher": 1.0}
                obs[idx]   = kind_map.get(item.kind, 0.0)
                obs[idx+1] = item.price / 20.0
                obs[idx+2] = 1.0  # exists
            idx += SHOP_ITEM_FEATS

        # 4. Booster packs (2 × 5)
        packs = [i for i in game.current_shop if i.kind == "booster" and not i.sold]
        for si in range(N_PACK_SLOTS):
            if si < len(packs):
                pack = packs[si]
                binfo = BOOSTER_CATALOGUE.get(pack.key, ("",0,"",0))
                kind_map = {"tarot":0.25,"planet":0.5,"spectral":0.75,"joker":1.0,"card":0.1}
                obs[idx]   = kind_map.get(binfo[2], 0.0)
                obs[idx+1] = pack.price / 10.0
                obs[idx+2] = binfo[3] / 5.0  # cards shown
                obs[idx+3] = (2 if "mega" in pack.key else 1) / 2.0  # picks
                obs[idx+4] = 1.0  # exists
            idx += PACK_SLOT_FEATS

        # 5. Hand type levels (12)
        for ht in HAND_TYPES:
            lv = game.planet_levels.get(ht, 1)
            obs[idx] = min(lv, 10) / 10.0
            idx += 1

        # 6. Consumables (2 × 4)
        for ci in range(N_CONS_SLOTS_SHOP):
            if ci < len(game.consumable_hand):
                ckey = game.consumable_hand[ci]
                is_tarot  = 1.0 if ckey in ALL_TAROTS else 0.0
                is_planet = 1.0 if ckey in ALL_PLANETS else 0.0
                needs_tgt = 1.0 if _tarot_needs_target(ckey) else 0.0
                obs[idx]   = is_tarot
                obs[idx+1] = is_planet
                obs[idx+2] = needs_tgt
                obs[idx+3] = 1.0  # exists
            idx += CONS_FEATS

        # 7. Vouchers active (27 binary flags)
        from .consumables import ALL_VOUCHERS
        for vi, vkey in enumerate(ALL_VOUCHERS[:N_VOUCHERS]):
            obs[idx + vi] = 1.0 if vkey in game.vouchers else 0.0
        idx += N_VOUCHERS

        # 8. Upcoming boss blind one-hot (15)
        boss_name = getattr(game, 'upcoming_boss', None)
        if boss_name and boss_name in BOSS_IDX:
            obs[idx + BOSS_IDX[boss_name]] = 1.0
        idx += BOSS_FEATS

        # 9. Deck composition (18): 13 rank + 4 suit + total size (normalized)
        deck_size = len(game.deck)
        norm = max(1, deck_size)
        rank_counts  = [0] * 13
        suit_counts  = [0] * 4
        for card in game.deck:
            r = getattr(card, 'rank', 1)
            s = getattr(card, 'suit', 'Spades')
            rank_counts[min(r-2, 12)] += 1
            si = SUIT_ORDER.index(s) if s in SUIT_ORDER else 0
            suit_counts[si] += 1
        for i, c in enumerate(rank_counts):
            obs[idx+i] = c / norm
        idx += 13
        for i, c in enumerate(suit_counts):
            obs[idx+i] = c / norm
        idx += 4
        obs[idx] = deck_size / 60.0
        idx += 1

        # 10. Enhancement / edition / seal counts (8)
        foil = holo = poly = gold = wild = seal_gold = seal_red = seal_blue = 0
        for card in game.deck:
            enh = getattr(card, 'enhancement', None)
            edn = getattr(card, 'edition', None)
            seal= getattr(card, 'seal', None)
            if edn == "Foil":        foil += 1
            elif edn == "Holographic": holo += 1
            elif edn == "Polychrome":  poly += 1
            if enh == "Gold":  gold += 1
            if enh == "Wild":  wild += 1
            if seal == "Gold": seal_gold += 1
            elif seal == "Red": seal_red += 1
            elif seal == "Blue": seal_blue += 1
        obs[idx:idx+8] = [foil/norm, holo/norm, poly/norm, gold/norm,
                          wild/norm, seal_gold/norm, seal_red/norm, seal_blue/norm]
        idx += 8

        assert idx == SHOP_OBS_DIM, f"shop obs mismatch: {idx} != {SHOP_OBS_DIM}"
        return obs

    def set_comm_vec(self, vec: np.ndarray):
        """Called by the shop agent network after each shop phase to set the comm vector."""
        self._comm_vec = np.array(vec, dtype=np.float32)

    # ── Action masks ──────────────────────────────────────────────────────────

    def get_play_action_mask(self) -> np.ndarray:
        """Boolean mask over PLAY_N_ACTIONS. True = valid."""
        mask = np.zeros(PLAY_N_ACTIONS, dtype=bool)
        gs = self.game
        state = gs.state

        if state == State.BLIND_SELECT:
            mask[30] = True   # play blind always valid
            if gs.blind_idx != 2:
                mask[31] = True  # skip (non-boss only)

        elif state == State.SELECTING_HAND:
            n_combos = len(self._play_combos)
            mask[:n_combos] = True
            if gs.discards_left > 0:
                for i, _ in enumerate(gs.hand):
                    mask[20 + i] = True
            # Consumable usage
            for ci, ckey in enumerate(gs.consumable_hand):
                if ci < 2 and ckey in ALL_PLANETS:
                    mask[28 + ci] = True

        return mask

    def get_shop_action_mask(self) -> np.ndarray:
        """Boolean mask over SHOP_N_ACTIONS for normal shop substate."""
        mask = np.zeros(SHOP_N_ACTIONS, dtype=bool)
        game = self.game

        mask[1] = True   # leave_shop always valid

        cost = max(0, game.reroll_cost - getattr(game, 'reroll_discount', 0))
        if game.dollars >= cost:
            mask[0] = True  # reroll

        items = [i for i in game.current_shop if not i.sold and i.kind != "booster"]
        for ii, item in enumerate(items[:6]):
            if game.dollars >= item.discounted_price(game.shop_discount):
                if item.kind == "joker" and len(game.jokers) < game.joker_slots:
                    mask[2 + ii] = True
                elif item.kind in ("planet","tarot","spectral") and \
                     len(game.consumable_hand) < game.consumable_slots:
                    mask[2 + ii] = True
                elif item.kind == "voucher":
                    mask[2 + ii] = True

        packs = [i for i in game.current_shop if i.kind == "booster" and not i.sold]
        for pi, pack in enumerate(packs[:2]):
            if game.dollars >= pack.discounted_price(game.shop_discount):
                mask[8 + pi] = True

        for ji in range(min(len(game.jokers), 5)):
            mask[10 + ji] = True

        for ci, ckey in enumerate(game.consumable_hand[:2]):
            if ckey in ALL_PLANETS:
                mask[15 + ci] = True
            elif ckey in ALL_TAROTS:
                mask[15 + ci] = True  # tarot always usable (target picked in substate)

        return mask

    def get_pack_open_mask(self) -> np.ndarray:
        """Mask for PACK_OPEN substate: Discrete(N+1)."""
        n = len(self._pack_choices)
        mask = np.ones(n + 1, dtype=bool)
        return mask

    def get_pack_target_mask(self) -> np.ndarray:
        """Mask for PACK_TARGET substate: Discrete(53)."""
        mask = np.zeros(53, dtype=bool)
        deck_len = len(self.game.deck)
        for i in range(min(deck_len, 52)):
            mask[i] = True
        mask[52] = True  # skip always valid
        return mask

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _update_play_combos(self):
        """Pre-compute top-20 play combos, sorted by score_hand() descending."""
        gs = self.game
        hand = gs.hand
        n = len(hand)
        if n == 0:
            self._play_combos = []
            return

        from .hand_eval import evaluate_hand as _eval_hand, HAND_PRIORITY as _HP
        scored = []
        for size in range(1, min(n, 5) + 1):
            for combo in _combinations(list(range(n)), size):
                cards = [hand[i] for i in combo]
                try:
                    hand_type, scoring_cards = _eval_hand(cards)
                    priority = _HP.index(hand_type) if hand_type in _HP else 99
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
                    )
                    scored.append((-priority, actual_score, list(combo)))
                except Exception:
                    pass

        scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
        self._play_combos = [s[2] for s in scored[:20]]


# ════════════════════════════════════════════════════════════════════════════
# Helpers
# ════════════════════════════════════════════════════════════════════════════

def _combinations(pool, r):
    """itertools.combinations equivalent."""
    import itertools
    return list(itertools.combinations(pool, r))


# Tarots that require a card target
_TARGETING_TAROTS = {
    "c_magician",       # enhance 1-2 cards Lucky
    "c_high_priestess", # add 2 random planets to consumables (no target needed) — exclude
    "c_empress",        # enhance 2 cards Mult
    "c_emperor",        # add 2 random tarots — no target
    "c_hierophant",     # enhance 2 cards Bonus
    "c_lovers",         # enhance 1 card Wild
    "c_chariot",        # enhance 1 card Steel
    "c_justice",        # enhance 1 card Glass
    "c_hermit",         # double money — no target
    "c_wheel",          # 1/4 chance joker becomes neg — no target
    "c_strength",       # increase rank of 2 cards
    "c_hanged_man",     # destroy up to 2 cards
    "c_death",          # convert card to copy of another — 2 targets
    "c_temperance",     # collect joker sell values — no target
    "c_devil",          # enhance 1 card Gold
    "c_tower",          # enhance 1 card Stone
    "c_star",           # convert 3 cards to Diamonds
    "c_moon",           # convert 3 cards to Clubs
    "c_sun",            # convert 3 cards to Hearts
    "c_judgement",      # create random joker — no target
    "c_world",          # convert 3 cards to Spades
}

_NO_TARGET_TAROTS = {
    "c_high_priestess", "c_emperor", "c_hermit", "c_wheel",
    "c_temperance", "c_judgement", "c_fool",
}


def _tarot_needs_target(key: str) -> bool:
    """Return True if this tarot requires selecting deck cards as targets."""
    return key in _TARGETING_TAROTS and key not in _NO_TARGET_TAROTS


def _joker_value(joker) -> float:
    """Score a joker instance by rarity + edition (mirrors V4 Lua heuristic).
    Higher = better. Used for sell-upgrade decisions."""
    rarity_score = {"Common": 10, "Uncommon": 20, "Rare": 30, "Legendary": 40}
    meta = JOKER_CATALOGUE.get(joker.key, {})
    base = rarity_score.get(meta.get("rarity", "Common"), 10)
    edition_bonus = {"Polychrome": 10, "Holographic": 5, "Foil": 3, "Negative": 50}
    base += edition_bonus.get(getattr(joker, "edition", "None"), 0)
    return base


# ════════════════════════════════════════════════════════════════════════════
# Quick smoke test
# ════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    env = BalatroSimEnvV5(seed=42)
    obs, info = env.reset()
    print(f"Reset OK  | agent={info['agent']}  | obs shape={obs.shape}")
    print(f"PLAY_OBS_DIM={PLAY_OBS_DIM}  SHOP_OBS_DIM={SHOP_OBS_DIM}")

    for step in range(200):
        agent = info["agent"]
        if agent == "play":
            mask = env.get_play_action_mask()
            valid = np.where(mask)[0]
            action = int(np.random.choice(valid)) if len(valid) else 30
        else:
            if info["shop_substate"] == SUBSTATE_PACK_OPEN:
                mask = env.get_pack_open_mask()
            elif info["shop_substate"] == SUBSTATE_PACK_TARGET:
                mask = env.get_pack_target_mask()
            else:
                mask = env.get_shop_action_mask()
            valid = np.where(mask)[0]
            action = int(np.random.choice(valid)) if len(valid) else 1
        obs, reward, terminated, _, info = env.step(action)
        if terminated:
            print(f"  Episode ended at step {step+1}  reward so far={info['total_reward']:.1f}")
            obs, info = env.reset()
    print("Smoke test passed.")
