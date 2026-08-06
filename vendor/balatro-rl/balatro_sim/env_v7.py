"""
env_v7.py — V7 Balatro environment with hierarchical intent + learned card selection.

The SELECTING_HAND phase uses a two-level action:
  1. Intent: PLAY / DISCARD / USE_CONSUMABLE  (Discrete(3), from intent head)
  2. Card subset: selected via card scoring head -> subset distribution -> sample

The env receives a composite action dict and translates it to game.step() calls.
Shop and blind_select phases use a flat Discrete(18) phase action.

Observation: 434 dims (402 from V6 + 32 new per-card features)
  New per-card features (4 per slot, 8 slots = 32):
    suit_match_count, rank_match_count, straight_connectivity, card_chip_value

Reward structure: identical to V6.
"""
from __future__ import annotations

import math
from collections import Counter
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
from .constants import SUITS, RANK_CHIPS, STARTING_HANDS, STARTING_DISCARDS, HAND_SIZE
from .shop import JOKER_CATALOGUE
from .card_selection import (
    INTENT_PLAY, INTENT_DISCARD, INTENT_USE_CONSUMABLE, N_INTENTS,
    enumerate_subsets, apply_action,
)

# ════════════════════════════════════════════════════════════════════════════
# Constants
# ════════════════════════════════════════════════════════════════════════════

# Phase actions (blind_select + shop)
N_PHASE_ACTIONS = 18
# Phase action mapping:
#   0  play_blind
#   1  skip_blind
#   2-8  buy shop item 0-6
#   9-13  sell joker 0-4
#   14  reroll
#   15  leave_shop
#   16  use planet in shop
#   17  reroll boss (Director's Cut / Retcon)

# Phase IDs
PHASE_SELECTING_HAND = 0
PHASE_BLIND_SELECT = 1
PHASE_SHOP = 2
PHASE_GAME_OVER = 3

ENHANCEMENTS = ["None", "Bonus", "Mult", "Wild", "Glass", "Steel", "Stone", "Gold", "Lucky"]
EDITIONS     = ["None", "Foil", "Holographic", "Polychrome", "Negative"]
SEALS        = ["None", "Gold", "Red", "Blue", "Purple"]
SUIT_ORDER   = ["Spades", "Hearts", "Clubs", "Diamonds"]

JOKER_KEYS   = sorted(JOKER_CATALOGUE.keys())
JOKER_IDX    = {k: i for i, k in enumerate(JOKER_KEYS)}
N_JOKERS     = len(JOKER_KEYS)

HAND_TYPES = [
    "High Card", "Pair", "Two Pair", "Three of a Kind", "Straight", "Flush",
    "Full House", "Four of a Kind", "Straight Flush", "Five of a Kind",
    "Flush House", "Flush Five",
]

HAND_PRIORITY = {ht: i for i, ht in enumerate(HAND_TYPES)}

# Feature dimensions
GAME_SCALARS   = 14
CARD_FEATURES  = 30    # 26 from V6 + 4 new
N_HAND_SLOTS   = 8
JOKER_FEATURES = 10
N_JOKER_SLOTS  = 5
SHOP_FEATURES  = 6
N_SHOP_SLOTS   = 7
PLANET_FEATURES = 12
CONS_FEATURES  = 8
N_CONS_SLOTS   = 2
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
# = 14 + 240 + 50 + 42 + 12 + 16 + 78 + 24 + 5 = 481

# Reward constants — V7 Run 5: auto-positioning, ante-aware synergy, sell rewards
R_BLIND_BASE     = 1.0
R_ANTE_COMPLETE  = 2.5
R_WIN            = 30.0
R_LOSE           = -1.0
R_SCORE_PROGRESS = 0.02
R_HEUR_USE_PLANET   = 0.2
R_HEUR_WASTE_MONEY  = -0.02

# V7 card selection quality
R_CARD_QUALITY     = 2.0

# V7 Run 4 (kept): Slot-scaled synergy reward
R_SYNERGY_BUY_BASE = 1.5
SLOT_SYNERGY_BONUS = [0.0, 0.0, 0.5, 1.0, 1.5]
R_ANTI_SYNERGY     = -0.5

# V7 Run 4 (kept): Empty slot penalty scales with ante
R_EMPTY_SLOT_PER_ANTE = 0.3
MAX_EMPTY_SLOT_PENALTY = -6.0

# V7 Run 4 (kept): Interest cap reduced
INTEREST_CAP = 15

# V7 Run 5: Sell rewards (positive signal for smart sells, not just penalty for dumb)
R_SELL_SACRIFICIAL_CORRECT = 2.0  # selling Luchador on boss blind, Diet Cola anytime, etc.
R_SELL_WEAK_JOKER          = 0.3  # selling Egg, Credit Card, Gift Card
R_SELL_LATE_SCALING_SWAP   = 1.0  # selling scaling joker late-game for immediate payoff
R_SELL_UPGRADE_CHAIN       = 0.5  # selling low-synergy joker then buying higher-synergy
R_SELL_ACCUMULATED_BLUNDER = -2.0 # selling scaling joker held 3+ antes (accumulated value lost)
R_SELL_BLUNDER_DEFAULT     = -0.5 # selling with empty slots and no upgrade target (unchanged)

# V7 Run 5: Episode-end coherence bonus (BUMPED IN RUN 6)
# Rewards maintaining a focused strategy throughout the run
R_COHERENCE_END_MULT = 6.0   # Run 6: bumped from 2.0 → 6.0 (max +48)

# V7 Run 6: Per-blind coherence bonus (NEW)
# Fires on every blind cleared — gives in-game signal that coherence matters
R_COHERENCE_PER_BLIND = 1.5  # max contribution: 24 × 1.5 × 1.0 = +36 per perfect run

# V7 Run 6: Stronger anti-synergy + reduced neutral reward
ANTI_SYNERGY_THRESHOLD = 0.5  # Run 6: raised from 0.4 → 0.5 (sub-neutral = penalty)
R_ANTI_SYNERGY_RUN6   = -1.0  # Run 6: doubled from -0.5 → -1.0
NEUTRAL_SYNERGY_CAP   = 0.55  # Run 6: cap synergy reward calc when synergy < 0.55
                              # Effective: neutral (0.5) gets reward × 0.55/1.0 instead of × 0.75


# ════════════════════════════════════════════════════════════════════════════
# Environment
# ════════════════════════════════════════════════════════════════════════════

class BalatroV7Env(gym.Env):
    """
    V7 Balatro environment with hierarchical action space.

    SELECTING_HAND actions are (intent, subset_indices) dicts.
    Other phase actions are flat integers from the phase head.
    """

    metadata = {"render_modes": []}

    def __init__(self, seed: Optional[int] = None, rng_mode: str = "generic"):
        super().__init__()
        self.observation_space = spaces.Box(
            low=-1.0, high=10.0, shape=(OBS_DIM,), dtype=np.float32
        )
        # Action space is handled externally by the training script
        # (hierarchical for SELECTING_HAND, discrete for other phases)
        self.action_space = spaces.Discrete(N_PHASE_ACTIONS)  # nominal

        self._seed = seed
        self._rng_mode = rng_mode
        self.game = BalatroGame(seed=seed, rng_mode=rng_mode)
        self._prev_progress = 0.0
        self._prev_ante = 1
        self._prev_blind_idx = 0
        self._steps = 0
        self._play_history: list[dict] = []
        self._episode_reward: float = 0.0
        # Run 5: track acquisition ante per joker for sell-protection
        self._joker_acquisition_ante: dict[int, int] = {}  # id(JokerInstance) -> ante

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
        self._joker_acquisition_ante = {}
        self._auto_advance()
        obs = self._encode_obs()
        return obs, {}

    def get_phase(self) -> int:
        """Return current phase ID."""
        s = self.game.state
        if s == State.SELECTING_HAND:
            return PHASE_SELECTING_HAND
        elif s == State.BLIND_SELECT:
            return PHASE_BLIND_SELECT
        elif s == State.SHOP:
            return PHASE_SHOP
        else:
            return PHASE_GAME_OVER

    def step_hand(self, intent: int, subset: tuple[int, ...]):
        """
        Execute a SELECTING_HAND action: intent + card subset.

        Args:
            intent: INTENT_PLAY, INTENT_DISCARD, or INTENT_USE_CONSUMABLE
            subset: tuple of card indices from the sampled subset

        Returns:
            (obs, reward, terminated, truncated, info)
        """
        self._steps += 1
        reward = 0.0
        gs = self.game

        if gs.state != State.SELECTING_HAND:
            # Wrong phase — no-op
            return self._finish_step(reward)

        target = gs.current_blind.chips_target

        if intent == INTENT_PLAY:
            valid_indices = [i for i in subset if i < len(gs.hand)]
            if not valid_indices:
                valid_indices = [0] if gs.hand else []
            if valid_indices:
                pre_cards = [gs.hand[i] for i in valid_indices]
                jokers_held = [j.key for j in gs.jokers]
                ante_now = gs.ante
                blind_kind = gs.current_blind.kind if gs.current_blind else "?"
                chips_before = gs.chips_scored

                # Compute best possible score BEFORE playing (for card quality reward)
                best_score = self._best_hand_score(gs)

                gs.step({"type": "play", "cards": valid_indices})

                played_score = gs.chips_scored - chips_before

                # Dense reward: log-scaled progress
                new_progress = gs.chips_scored / max(target, 1)
                delta = new_progress - self._prev_progress
                if delta > 0:
                    reward += R_SCORE_PROGRESS * math.log1p(delta) * 100
                self._prev_progress = new_progress

                # Card quality bonus: how good was this selection vs best possible?
                if best_score > 0:
                    quality_ratio = min(played_score / best_score, 1.0)
                    reward += R_CARD_QUALITY * quality_ratio

                # Highlight log
                try:
                    ht, _ = evaluate_hand(pre_cards) if pre_cards else ("?", [])
                except Exception:
                    ht = "?"
                self._play_history.append({
                    "ante": ante_now, "blind": blind_kind,
                    "cards": [repr(c) for c in pre_cards], "hand_type": ht,
                    "chips": gs.chips_scored - chips_before,
                    "total": gs.chips_scored, "target": target,
                    "jokers": jokers_held,
                })

        elif intent == INTENT_DISCARD:
            if gs.discards_left > 0:
                valid_indices = [i for i in subset if i < len(gs.hand)]
                if valid_indices:
                    gs.step({"type": "discard", "cards": valid_indices})

        elif intent == INTENT_USE_CONSUMABLE:
            if gs.consumable_hand:
                gs.step({"type": "use_consumable",
                         "consumable_idx": 0, "target_cards": []})

        return self._finish_step(reward)

    def step_phase(self, action: int):
        """
        Execute a BLIND_SELECT or SHOP action.

        Args:
            action: integer in [0, N_PHASE_ACTIONS)

        Returns:
            (obs, reward, terminated, truncated, info)
        """
        self._steps += 1
        reward = 0.0
        gs = self.game

        if gs.state == State.BLIND_SELECT:
            if action == 0:
                gs.step({"type": "play_blind"})
            elif action == 1:
                gs.step({"type": "skip_blind"})
                self._auto_advance()

        elif gs.state == State.SHOP:
            if 2 <= action <= 8:
                idx = action - 2
                n_jokers_before = len(gs.jokers)
                jokers_before = [j.key for j in gs.jokers]
                shop_item = gs.current_shop[idx] if idx < len(gs.current_shop) else None
                candidate_key = shop_item.key if shop_item and shop_item.kind == "joker" else None

                gs.step({"type": "buy", "item_idx": idx})

                # V7 Run 5: Auto-position positional jokers + track acquisition ante
                if len(gs.jokers) > n_jokers_before:
                    # The newly added joker was appended by game.step — re-position if needed
                    from .synergy import (coherence_score, auto_position_on_buy,
                                          POSITIONAL_JOKERS)
                    new_joker = gs.jokers[-1]  # just-appended joker
                    if new_joker.key in POSITIONAL_JOKERS:
                        # Remove it and re-insert via auto-positioning
                        gs.jokers.pop()
                        auto_position_on_buy(gs.jokers, new_joker)
                    # Track acquisition ante
                    self._joker_acquisition_ante[id(new_joker)] = gs.ante

                    # V7 Run 6: ante-aware synergy reward with stronger coherence pressure
                    if candidate_key:
                        synergy = coherence_score(candidate_key, jokers_before, ante=gs.ante)
                        slot_idx = min(n_jokers_before, len(SLOT_SYNERGY_BONUS) - 1)
                        max_reward = R_SYNERGY_BUY_BASE + SLOT_SYNERGY_BONUS[slot_idx]
                        # Run 6: cap the effective synergy multiplier for sub-coherent buys
                        # This reduces neutral (0.5) reward from 0.75 to ~0.41 (× 0.55)
                        effective_synergy = synergy if synergy >= NEUTRAL_SYNERGY_CAP else synergy * 0.75
                        reward += max_reward * effective_synergy
                        # Run 6: stronger anti-synergy penalty with higher threshold
                        if synergy < ANTI_SYNERGY_THRESHOLD:
                            reward += R_ANTI_SYNERGY_RUN6 * (ANTI_SYNERGY_THRESHOLD - synergy)

            elif 9 <= action <= 13:
                j_idx = action - 9
                if j_idx < len(gs.jokers):
                    from .synergy import (SACRIFICIAL_JOKERS, WEAK_JOKERS,
                                          EARLY_GAME_JOKERS, IMMEDIATE_PAYOFF_JOKERS)
                    sold_joker = gs.jokers[j_idx]
                    sold_key = sold_joker.key
                    acq_ante = self._joker_acquisition_ante.get(id(sold_joker), gs.ante)
                    ante_held = gs.ante - acq_ante

                    # V7 Run 5: Context-aware sell rewards
                    if sold_key in SACRIFICIAL_JOKERS:
                        # Sacrificial jokers should be sold — reward the action
                        # Luchador: reward if boss blind phase imminent
                        # Diet Cola: always rewarding to sell (free tag)
                        # Invisible Joker: reward if held 2+ rounds
                        if sold_key == "j_invisible_joker":
                            if ante_held >= 2:
                                reward += R_SELL_SACRIFICIAL_CORRECT
                            else:
                                reward += 0.5  # partial reward for selling too early
                        else:
                            reward += R_SELL_SACRIFICIAL_CORRECT
                    elif sold_key in WEAK_JOKERS:
                        # Selling a weak joker is fine — small reward
                        reward += R_SELL_WEAK_JOKER
                    elif sold_key in EARLY_GAME_JOKERS and ante_held >= 3:
                        # Selling a scaling joker you've accumulated value on = blunder
                        reward += R_SELL_ACCUMULATED_BLUNDER
                    elif sold_key in EARLY_GAME_JOKERS and gs.ante >= 5:
                        # Late-game selling a scaling joker (for immediate-payoff swap) = good
                        reward += R_SELL_LATE_SCALING_SWAP
                    elif len(gs.jokers) <= gs.joker_slots:
                        # Has open slots — check if there's an expensive upgrade
                        has_expensive_upgrade = any(
                            i.kind == "joker" and not i.sold
                            and i.discounted_price(gs.shop_discount) > gs.dollars
                            for i in gs.current_shop
                        )
                        if not has_expensive_upgrade:
                            reward += R_SELL_BLUNDER_DEFAULT
                        else:
                            reward += R_SELL_UPGRADE_CHAIN  # selling to afford upgrade = good
                    # Clean up acquisition tracking
                    if id(sold_joker) in self._joker_acquisition_ante:
                        del self._joker_acquisition_ante[id(sold_joker)]
                gs.step({"type": "sell_joker", "joker_idx": j_idx})

            elif action == 14:
                gs.step({"type": "reroll"})

            elif action == 15:
                # V7 Run 4: Empty slot penalty scales with ante
                # Formula: -0.3 × (ante - 1) × empty_slots, capped at -6.0 total
                # No penalty at ante 1 (cash-strapped learning phase)
                empty_slots = gs.joker_slots - len(gs.jokers)
                if empty_slots > 0 and gs.ante > 1:
                    slot_penalty = -R_EMPTY_SLOT_PER_ANTE * (gs.ante - 1) * empty_slots
                    slot_penalty = max(slot_penalty, MAX_EMPTY_SLOT_PENALTY)
                    reward += slot_penalty
                # V7 Run 4: Interest cap reduced $25 -> $15
                interest_floor = min(gs.dollars // 5 * 5, INTEREST_CAP)
                wasted = gs.dollars - interest_floor
                if wasted > 0:
                    reward += R_HEUR_WASTE_MONEY * wasted
                gs.step({"type": "leave_shop"})
                self._auto_advance()

            elif action == 16:
                # Use planet in shop
                from .consumables import ALL_PLANETS as _AP
                if gs.consumable_hand:
                    if gs.consumable_hand[0] in _AP:
                        gs.step({"type": "use_consumable",
                                 "consumable_idx": 0, "target_cards": []})
                        reward += R_HEUR_USE_PLANET

            elif action == 17:
                # Director's Cut / Retcon: reroll the upcoming Boss Blind
                gs.step({"type": "reroll_boss"})

        return self._finish_step(reward)

    def _finish_step(self, reward: float):
        """Common post-action logic: auto-advance, milestone rewards, obs."""
        gs = self.game
        self._auto_advance()

        new_state = gs.state
        new_ante = gs.ante
        new_blind = gs.blind_idx

        if new_state == State.GAME_OVER:
            if gs._obs().won:
                reward += R_WIN
            else:
                reward += R_LOSE
            # V7 Run 6: Episode-end coherence bonus (3x amplified)
            # Max: 1.0 coherence × 8 ante × 6.0 = +48 (vs +16 in Run 5)
            if gs.jokers:
                from .synergy import loadout_coherence
                final_coh = loadout_coherence([j.key for j in gs.jokers])
                ante_reached = min(gs.ante, 8)
                reward += final_coh * ante_reached * R_COHERENCE_END_MULT
        elif new_state == State.SHOP:
            if (new_ante, new_blind) != (self._prev_ante, self._prev_blind_idx):
                was_boss = (self._prev_blind_idx == 2)
                blind_reward = R_BLIND_BASE * (9 - self._prev_ante)
                reward += blind_reward
                if was_boss:
                    reward += R_ANTE_COMPLETE
                # V7 Run 6: per-blind coherence bonus (in-game pressure to maintain build)
                if gs.jokers:
                    from .synergy import loadout_coherence
                    coh = loadout_coherence([j.key for j in gs.jokers])
                    reward += R_COHERENCE_PER_BLIND * coh
                self._prev_ante = new_ante
                self._prev_blind_idx = new_blind
                self._prev_progress = 0.0

        terminated = (new_state == State.GAME_OVER)
        truncated = False
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

        if terminated and gs.ante >= 7 and self._play_history:
            self._write_highlight(gs, self._episode_reward)

        return obs, reward, terminated, truncated, info

    # ── Legacy step() for compatibility with gym interface ───────────────────

    def _best_hand_score(self, gs) -> float:
        """
        Compute the best possible score from the current hand.

        Two-phase optimization:
          1. Cheap phase: evaluate_hand() on all 218 subsets (~50us each)
          2. Expensive phase: score_hand() only on top candidates by hand type priority

        The top hand-type candidate(s) nearly always produce the highest score because
        base chips/mult scales steeply with hand type. We score the top 3 candidates
        to handle edge cases where joker synergies prefer a "lower" type (e.g. a Pair
        with matching suits for suit jokers beats a Straight with no synergy).
        """
        import itertools
        hand = gs.hand
        if not hand:
            return 0.0
        n = min(len(hand), N_HAND_SLOTS)

        # Phase 1: evaluate all subsets, track by hand type priority
        # candidates_by_priority[priority_idx] = list of (combo, scoring_cards, hand_type)
        candidates_by_priority: dict[int, list] = {}
        for k in range(1, min(6, n + 1)):
            for combo in itertools.combinations(range(n), k):
                cards = [hand[i] for i in combo]
                try:
                    ht, sc = evaluate_hand(cards)
                except Exception:
                    continue
                priority = HAND_PRIORITY.get(ht, 0)
                candidates_by_priority.setdefault(priority, []).append((combo, sc, ht, cards))

        if not candidates_by_priority:
            return 0.0

        # Phase 2: score only the top candidates
        # Take up to 3 priority tiers from the top, and cap total at 8 combos
        sorted_priorities = sorted(candidates_by_priority.keys(), reverse=True)
        candidates_to_score = []
        for priority in sorted_priorities[:3]:
            candidates_to_score.extend(candidates_by_priority[priority])
            if len(candidates_to_score) >= 8:
                break

        best = 0.0
        for combo, sc, ht, cards in candidates_to_score[:8]:
            try:
                s, _ = score_hand(
                    scoring_cards=sc, all_cards=cards, hand_type=ht,
                    jokers=gs.jokers, planet_levels=gs.planet_levels,
                    hands_left=gs.hands_left, discards_left=gs.discards_left,
                    dollars=gs.dollars, ante=gs.ante, deck_remaining=len(gs.deck),
                    half_base=(gs.current_blind.boss_key == "bl_flint"),
                )
                if s > best:
                    best = s
            except Exception:
                pass
        return best

    def step(self, action: int):
        """Fallback step for random rollouts — maps flat int to phase action."""
        phase = self.get_phase()
        if phase == PHASE_SELECTING_HAND:
            # Random fallback: play first card
            return self.step_hand(INTENT_PLAY, (0,))
        else:
            return self.step_phase(action % N_PHASE_ACTIONS)

    # ── Action masking ──────────────────────────────────────────────────────

    def get_intent_mask(self) -> np.ndarray:
        """Return bool mask of shape (N_INTENTS,) for SELECTING_HAND phase."""
        mask = np.zeros(N_INTENTS, dtype=bool)
        gs = self.game

        if gs.state != State.SELECTING_HAND:
            return mask

        # PLAY: always valid if hand has cards
        if gs.hand:
            mask[INTENT_PLAY] = True

        # DISCARD: valid if discards remain and hand > 1
        if gs.discards_left > 0 and len(gs.hand) > 1:
            mask[INTENT_DISCARD] = True

        # USE_CONSUMABLE: valid if consumables in hand
        if gs.consumable_hand:
            mask[INTENT_USE_CONSUMABLE] = True

        # Safety
        if not mask.any():
            mask[INTENT_PLAY] = True

        return mask

    def get_phase_mask(self) -> np.ndarray:
        """Return bool mask of shape (N_PHASE_ACTIONS,) for blind/shop phases."""
        mask = np.zeros(N_PHASE_ACTIONS, dtype=bool)
        gs = self.game

        if gs.state == State.BLIND_SELECT:
            mask[0] = True  # play_blind
            if gs.current_blind.kind != "Boss":
                mask[1] = True  # skip_blind

        elif gs.state == State.SHOP:
            shop = gs.current_shop
            for i, item in enumerate(shop[:7]):
                if not item.sold and gs.dollars >= item.discounted_price(gs.shop_discount):
                    if item.kind == "joker" and len(gs.jokers) >= gs.joker_slots:
                        pass
                    elif item.kind in ("planet", "tarot", "spectral") and \
                         len(gs.consumable_hand) >= gs.consumable_slots:
                        pass
                    else:
                        mask[2 + i] = True  # buy item i
            for i in range(min(len(gs.jokers), 5)):
                mask[9 + i] = True  # sell joker i
            reroll_cost = max(0, gs.reroll_cost - gs.reroll_discount)
            if gs.free_rerolls_remaining > 0 or gs.dollars >= reroll_cost:
                mask[14] = True  # reroll
            mask[15] = True  # leave shop
            # Planet in shop
            from .consumables import ALL_PLANETS as _AP
            if gs.consumable_hand and gs.consumable_hand[0] in _AP:
                mask[16] = True
            # Reroll Boss (Director's Cut / Retcon): $10, next blind is a Boss
            if gs.current_blind.kind == "Boss" and gs.dollars >= 10:
                can_retcon = "v_retcon" in gs.vouchers
                can_dc = ("v_directors_cut" in gs.vouchers
                          and gs.dc_reroll_ante != gs.ante)
                if can_retcon or can_dc:
                    mask[17] = True

        elif gs.state == State.GAME_OVER:
            mask[15] = True  # dummy

        if not mask.any():
            mask[15] = True

        return mask

    # ── Observation encoding ─────────────────────────────────────────────────

    def _encode_obs(self) -> np.ndarray:
        obs = np.zeros(OBS_DIM, dtype=np.float32)
        gs = self.game
        idx = 0

        # ── Game scalars (14) ─────────────────────────────────────────────
        obs[idx]   = gs.ante / 8.0
        obs[idx+1] = gs.blind_idx / 2.0
        obs[idx+2] = int(gs.current_blind.is_boss)
        progress   = gs.chips_scored / max(gs.current_blind.chips_target, 1)
        obs[idx+3] = min(progress, 2.0)
        obs[idx+4] = math.log1p(gs.current_blind.chips_target) / math.log1p(100000)
        obs[idx+5] = gs.hands_left / max(gs.base_hands, 1)
        obs[idx+6] = gs.discards_left / max(gs.base_discards, 1)
        obs[idx+7] = min(gs.dollars / 50.0, 2.0)
        obs[idx+8] = len(gs.jokers) / gs.joker_slots
        phase_map = {
            State.BLIND_SELECT:   idx+9,
            State.SELECTING_HAND: idx+10,
            State.SHOP:           idx+11,
            State.ROUND_EVAL:     idx+12,
            State.GAME_OVER:      idx+13,
        }
        obs[phase_map.get(gs.state, idx+13)] = 1.0
        idx += GAME_SCALARS

        # ── Hand cards (8 × 30 = 240) ─────────────────────────────────────
        # Precompute hand-level stats for new features
        hand = gs.hand
        suit_counts = Counter(c.suit for c in hand)
        rank_counts = Counter(c.rank for c in hand)
        hand_ranks = [c.rank for c in hand]

        for slot in range(N_HAND_SLOTS):
            if slot < len(hand):
                c = hand[slot]
                if not c.flipped:
                    # Original 26 V6 features
                    obs[idx] = (c.rank - 2) / 12.0
                    si = SUIT_ORDER.index(c.suit) if c.suit in SUIT_ORDER else 0
                    obs[idx+1+si] = 1.0
                    if c.enhancement in ENHANCEMENTS:
                        obs[idx+5+ENHANCEMENTS.index(c.enhancement)] = 1.0
                    if c.edition in EDITIONS:
                        obs[idx+14+EDITIONS.index(c.edition)] = 1.0
                    if c.seal in SEALS:
                        obs[idx+19+SEALS.index(c.seal)] = 1.0
                    obs[idx+24] = float(c.debuffed)

                    # ── New V7 features (4) ──────────────────────────────
                    obs[idx+26] = (suit_counts[c.suit] - 1) / 7.0
                    obs[idx+27] = (rank_counts[c.rank] - 1) / 7.0
                    connectivity = sum(1 for r in hand_ranks
                                       if r != c.rank and abs(r - c.rank) <= 4)
                    obs[idx+28] = connectivity / 7.0
                    obs[idx+29] = c.base_chips / 11.0

                # Face-down cards (The Mark): only "present" is visible
                obs[idx+25] = 1.0  # present

            idx += CARD_FEATURES

        # ── Joker slots (5 × 10 = 50) ─────────────────────────────────────
        for slot in range(N_JOKER_SLOTS):
            if slot < len(gs.jokers):
                j = gs.jokers[slot]
                obs[idx]   = 1.0
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
                obs[idx+4] = float(len(gs.jokers) < gs.joker_slots) if item.kind == "joker" else 0.0
                obs[idx+5] = float(len(gs.consumable_hand) < gs.consumable_slots) if item.kind in ("planet", "tarot", "spectral") else 0.0
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
                obs[idx]   = 1.0
                obs[idx+1] = float(key in PLANET_HAND)
                obs[idx+2] = float(key in ALL_TAROTS)
                obs[idx+3] = float(key in ALL_SPECTRALS)
                if key in PLANET_HAND:
                    ht = PLANET_HAND[key]
                    obs[idx+4] = HAND_TYPES.index(ht) / 11.0 if ht in HAND_TYPES else 0.0
                obs[idx+5] = gs.dollars / 50.0
                obs[idx+6] = gs.hands_left / max(gs.base_hands, 1)
                obs[idx+7] = float(gs.state == State.SELECTING_HAND)
            idx += CONS_FEATURES

        # ── Shop context (60) ────────────────────────────────────────────
        reroll_cost = max(0, gs.reroll_cost - gs.reroll_discount)
        obs[idx]   = min(reroll_cost, 10) / 10.0
        obs[idx+1] = gs.free_rerolls_remaining / max(gs.free_rerolls_per_round + 1, 1)
        idx += 2

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

        draw_pile = gs.deck
        deck_n = max(1, len(draw_pile))
        suit_counts_deck = [0, 0, 0, 0]
        face_count = ace_count = number_count = 0
        for card in draw_pile:
            si = SUIT_ORDER.index(card.suit) if card.suit in SUIT_ORDER else 0
            suit_counts_deck[si] += 1
            if card.rank >= 11 and card.rank <= 13:
                face_count += 1
            elif card.rank == 14:
                ace_count += 1
            else:
                number_count += 1
        for i in range(4):
            obs[idx + i] = suit_counts_deck[i] / deck_n
        obs[idx + 4] = face_count / deck_n
        obs[idx + 5] = ace_count / deck_n
        obs[idx + 6] = number_count / deck_n
        obs[idx + 7] = len(draw_pile) / 60.0
        idx += 8

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

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _auto_advance(self):
        """Auto-step through non-decision states."""
        for _ in range(20):
            s = self.game.state
            if s == State.ROUND_EVAL:
                self.game.step({"type": "noop"})
            elif s == State.BOOSTER_OPEN:
                if self.game.booster_choices:
                    self.game.step({"type": "pick_booster", "indices": [0]})
                else:
                    self.game.step({"type": "skip_booster"})
            else:
                break

    def _write_highlight(self, gs, total_reward: float):
        """Append a rich episode record to logs_sim/highlights_v7.jsonl."""
        import json, os
        os.makedirs("logs_sim", exist_ok=True)
        record = {
            "seed": self._seed,
            "ante_reached": gs.ante,
            "won": gs.ante > 8,
            "total_reward": round(total_reward, 2),
            "dollars": gs.dollars,
            "steps": self._steps,
            "jokers_final": [j.key for j in gs.jokers],
            "plays": [
                {
                    "ante": p["ante"], "blind": p["blind"],
                    "hand_type": p["hand_type"], "cards": p["cards"],
                    "chips": p["chips"], "total": p["total"],
                    "target": p["target"], "jokers": p["jokers"],
                }
                for p in self._play_history
            ],
        }
        with open("logs_sim/highlights_v7.jsonl", "a") as f:
            f.write(json.dumps(record) + "\n")
