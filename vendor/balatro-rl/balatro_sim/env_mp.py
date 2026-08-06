"""
env_mp.py — Multiplayer Balatro environment for V8 self-play training.

Wraps two V7-style agents playing against each other via MultiplayerBalatro.
Each player gets the standard V7 observation (434 dims) and hierarchical action
space (intent + card subset for SELECTING_HAND, phase actions for blind/shop).

The multiplayer coordinator handles:
  - Same-seed card draws for both players
  - Lives system (4 per player)
  - HOUSE RULE: regular blind failures cost a life
  - PvP blind resolution (higher score wins, loser loses life + comeback money)
  - Game termination on 0 lives

Reward structure per player:
  - All V7 rewards (card quality, synergy, blind clear, etc.)
  - NEW: PvP win: +3.0 | PvP loss: -2.0 | PvP tie: 0
  - NEW: Game win (opponent hit 0 lives): +20.0 | Game loss: -10.0

API:
  env = MultiplayerBalatroEnv(seed=42)
  p1_obs, p2_obs = env.reset()
  # Both players act simultaneously each step
  (p1_obs, p2_obs), (p1_reward, p2_reward), done, info = env.step(p1_action, p2_action)
"""
from __future__ import annotations
from typing import Optional

import numpy as np

from .mp_game import MultiplayerBalatro, MPPhase
from .game import State
from .env_v7 import (
    BalatroV7Env, OBS_DIM as V7_OBS_DIM, N_PHASE_ACTIONS, N_INTENTS, N_HAND_SLOTS,
    PHASE_SELECTING_HAND, PHASE_BLIND_SELECT, PHASE_SHOP, PHASE_GAME_OVER,
)
from .card_selection import INTENT_PLAY, INTENT_DISCARD, INTENT_USE_CONSUMABLE
from .shop import set_banned_jokers


# V8 Run 3: Extended observation with multiplayer state
# V7 obs (434) + 4 MP features = 438 total
#   [434] self_lives / 4.0                    — how much cushion do I have
#   [435] opponent_lives / 4.0                — how close am I to winning
#   [436] opponent_pvp_score_ratio            — opponent score / my target (capped 2.0), 0 if not PvP
#   [437] is_pvp_blind                        — 1.0 if current blind is boss/PvP, else 0.0
MP_OBS_FEATURES = 4
OBS_DIM = V7_OBS_DIM + MP_OBS_FEATURES


# Standard Ranked multiplayer ruleset disables these jokers because they
# interact with boss blinds (which are now PvP blinds in multiplayer):
#   - Chicot: disables boss blind effect (irrelevant in PvP)
#   - Matador: $8 when boss triggers (irrelevant in PvP)
#   - Mr. Bones: prevents loss at 25% (broken in lives system)
#   - Luchador: sell to disable boss blind (irrelevant in PvP)
MULTIPLAYER_BANNED_JOKERS = {
    "j_chicot",
    "j_matador",
    "j_mr_bones",
    "j_luchador",
}

# Apply ban list at module import time so any MP env construction inherits it.
# This is global state — if you also use single-player envs in the same process,
# call clear_banned_jokers() before doing so.
set_banned_jokers(MULTIPLAYER_BANNED_JOKERS)


# V8 Run 4 rewards — simplified, no lives system.
# Regular blind failure kills the game immediately for that player.
# PvP blind: both survive regardless, just reward adjustment.
R_PVP_WIN     = 10.0   # BIGGER (was 3.0) — PvP matters more now
R_PVP_LOSS    = -5.0   # BIGGER (was -2.0)
R_GAME_WIN    = 20.0   # opponent died (failed regular blind) — unchanged
R_GAME_LOSS   = -10.0  # you died first (failed regular blind) — unchanged
R_DRAW_BONUS  = 5.0    # both survived through ante 8 (extremely rare)


class _PlayerEnvProxy:
    """
    A thin proxy that looks like a V7 env but shares the underlying BalatroGame
    with the MP coordinator. Reuses V7's obs encoding and reward logic.

    We don't subclass BalatroV7Env directly because we need to point it at a
    game instance owned by the MP coordinator, not create its own.
    """
    def __init__(self, mp_coord: MultiplayerBalatro, player: int):
        self.mp = mp_coord
        self.player = player
        # Create a V7 env as a helper, then swap its game for the MP coord's game
        self._v7 = BalatroV7Env(seed=mp_coord._seed, rng_mode=mp_coord.rng_mode)
        self._v7.game = mp_coord.get_player_game(player)
        # Re-initialize tracking state
        self._v7._prev_progress = 0.0
        self._v7._prev_ante = 1
        self._v7._prev_blind_idx = 0
        self._v7._steps = 0
        self._v7._play_history = []
        self._v7._episode_reward = 0.0
        self._v7._joker_acquisition_ante = {}

    @property
    def game(self):
        return self._v7.game

    def encode_obs(self) -> np.ndarray:
        """V7 obs (445) + 4 multiplayer state features = 449 total."""
        base = self._v7._encode_obs()
        # Build MP extension
        self_lives = self.mp.get_lives(self.player)
        opp_lives = self.mp.get_lives(2 if self.player == 1 else 1)
        opp_game = self.mp.get_player_game(2 if self.player == 1 else 1)
        own_game = self.mp.get_player_game(self.player)

        # Opponent PvP score ratio — only meaningful during PvP blind
        is_pvp = (own_game.current_blind is not None
                  and own_game.current_blind.is_boss)
        if is_pvp and own_game.current_blind.chips_target > 0:
            opp_ratio = min(
                opp_game.chips_scored / max(own_game.current_blind.chips_target, 1),
                2.0,
            )
        else:
            opp_ratio = 0.0

        mp_extension = np.array([
            self_lives / 4.0,
            opp_lives / 4.0,
            opp_ratio,
            1.0 if is_pvp else 0.0,
        ], dtype=np.float32)

        return np.concatenate([base, mp_extension])

    def get_intent_mask(self) -> np.ndarray:
        return self._v7.get_intent_mask()

    def get_phase_mask(self) -> np.ndarray:
        return self._v7.get_phase_mask()

    def get_phase(self) -> int:
        return self._v7.get_phase()

    def step_hand(self, intent: int, subset: tuple):
        return self._v7.step_hand(intent, subset)

    def step_phase(self, action: int):
        return self._v7.step_phase(action)

    def auto_advance(self):
        self._v7._auto_advance()


class MultiplayerBalatroEnv:
    """
    Self-play environment for V8. Two V7 agents play against each other.

    Both players step simultaneously. After each step, we check if the
    underlying MP coordinator should transition phases (e.g. both finished
    a blind -> resolve lives/PvP).
    """

    def __init__(self, seed: Optional[int] = None, lives: int = 4,
                 rng_mode: str = "generic"):
        self._seed = seed
        self._lives = lives
        self._rng_mode = rng_mode
        self.mp: Optional[MultiplayerBalatro] = None
        self.p1: Optional[_PlayerEnvProxy] = None
        self.p2: Optional[_PlayerEnvProxy] = None
        self._episode_reward = [0.0, 0.0]  # cumulative per player
        # V8 Run 4: track winner override since MP coordinator's life-based
        # winner logic is no longer the source of truth
        self._winner_override: Optional[int] = None

    def reset(self, seed: Optional[int] = None) -> tuple[np.ndarray, np.ndarray]:
        if seed is not None:
            self._seed = seed
        self.mp = MultiplayerBalatro(seed=self._seed, lives=self._lives,
                                     rng_mode=self._rng_mode)
        self.p1 = _PlayerEnvProxy(self.mp, 1)
        self.p2 = _PlayerEnvProxy(self.mp, 2)
        # Auto-advance both games to first decision point
        self.p1.auto_advance()
        self.p2.auto_advance()
        self._episode_reward = [0.0, 0.0]
        self._winner_override = None
        # Track last resolved (ante, blind_idx) per player to avoid double-resolving
        # the same blind when both players are lingering in SHOP post-resolution.
        self._last_resolved_p1 = (-1, -1)
        self._last_resolved_p2 = (-1, -1)
        return self.p1.encode_obs(), self.p2.encode_obs()

    # ─────────────────────────────────────────────────────────────────────
    # Actions
    # ─────────────────────────────────────────────────────────────────────

    def step(self, p1_action: dict, p2_action: dict):
        """
        Step both players simultaneously.

        Each action is a dict:
          SELECTING_HAND:  {"type": "hand", "intent": int, "subset": tuple}
          Other phases:    {"type": "phase", "action": int}

        Returns:
            (obs_tuple, reward_tuple, done, info)
        """
        p1_reward = self._apply_action(self.p1, p1_action)
        p2_reward = self._apply_action(self.p2, p2_action)

        # After actions, check if both players have finished a blind and
        # need MP-level resolution
        mp_rewards = self._check_blind_resolution()
        p1_reward += mp_rewards[0]
        p2_reward += mp_rewards[1]

        self._episode_reward[0] += p1_reward
        self._episode_reward[1] += p2_reward

        # Run 4: game-over is driven by _winner_override set in _check_blind_resolution
        done = self.mp.phase == MPPhase.GAME_OVER or self._winner_override is not None
        info = {
            "p1_lives": self.mp.p1_lives,      # kept for obs consistency, no longer meaningful
            "p2_lives": self.mp.p2_lives,
            "p1_ante": self.mp.p1_game.ante,
            "p2_ante": self.mp.p2_game.ante,
            "phase": self.mp.phase.name,
            "winner": self._winner_override if self._winner_override is not None else self.mp.winner,
            "p1_total_reward": self._episode_reward[0],
            "p2_total_reward": self._episode_reward[1],
        }
        return (
            (self.p1.encode_obs(), self.p2.encode_obs()),
            (p1_reward, p2_reward),
            done,
            info,
        )

    def _apply_action(self, player_env: _PlayerEnvProxy, action: dict) -> float:
        """Execute one player's action and return their reward delta."""
        game = player_env.game
        # Skip if game already over (e.g. one player is waiting for the other)
        if game.state == State.GAME_OVER:
            return 0.0

        action_type = action.get("type")
        if action_type == "hand":
            obs, reward, term, trunc, info = player_env.step_hand(
                action["intent"], action["subset"]
            )
        elif action_type == "phase":
            obs, reward, term, trunc, info = player_env.step_phase(action["action"])
        else:
            reward = 0.0
        return reward

    # ─────────────────────────────────────────────────────────────────────
    # Phase coordination
    # ─────────────────────────────────────────────────────────────────────

    def _check_blind_resolution(self) -> tuple[float, float]:
        """
        After both players step, check if we need to resolve a blind at the MP level.

        A blind is "resolved" when both players have either:
          - Cleared the current blind (score >= target)
          - Run out of hands without clearing (failure)
          - Reached GAME_OVER (individual game ended)

        When both are done with current blind, apply MP rules (life loss, PvP).
        Returns (p1_reward, p2_reward) for MP-level events.
        """
        p1, p2 = self.mp.p1_game, self.mp.p2_game

        # Only resolve if both players are "done" with the current blind
        p1_done = self._is_blind_done(p1, self._last_resolved_p1)
        p2_done = self._is_blind_done(p2, self._last_resolved_p2)
        if not (p1_done and p2_done):
            return (0.0, 0.0)

        # Record the resolution positions so we don't double-resolve the same
        # SHOP state while players decide their shop actions.
        self._last_resolved_p1 = (p1.ante, p1.blind_idx)
        self._last_resolved_p2 = (p2.ante, p2.blind_idx)

        p1_reward = 0.0
        p2_reward = 0.0

        # Determine which blind we're resolving based on blind_idx
        # blind_idx: 0=Small, 1=Big, 2=Boss (PvP)
        p1_cleared = p1.chips_scored >= p1.current_blind.chips_target
        p2_cleared = p2.chips_scored >= p2.current_blind.chips_target

        phase = self.mp.phase
        if phase in (MPPhase.SMALL_BLIND, MPPhase.BIG_BLIND):
            # Regular blind — failure = game over for that player, opponent wins
            p1_died = not p1_cleared
            p2_died = not p2_cleared

            if p1_died or p2_died:
                # Someone died — game ends
                self.mp.phase = MPPhase.GAME_OVER
                if p1_died and p2_died:
                    # Both died same blind — tiebreak by chips scored on this blind
                    # (higher chips = closer to clearing = moral winner)
                    if p1.chips_scored > p2.chips_scored:
                        self._winner_override = 1
                        p1_reward += R_GAME_WIN
                        p2_reward += R_GAME_LOSS
                    elif p2.chips_scored > p1.chips_scored:
                        self._winner_override = 2
                        p2_reward += R_GAME_WIN
                        p1_reward += R_GAME_LOSS
                    else:
                        # Exact tie on failing blind — rare, small reward for effort
                        self._winner_override = 0
                        p1_reward += R_GAME_LOSS * 0.5
                        p2_reward += R_GAME_LOSS * 0.5
                elif p1_died:
                    self._winner_override = 2
                    p2_reward += R_GAME_WIN
                    p1_reward += R_GAME_LOSS
                else:
                    self._winner_override = 1
                    p1_reward += R_GAME_WIN
                    p2_reward += R_GAME_LOSS
            else:
                # Both cleared — advance to next blind phase
                self.mp.phase = (MPPhase.BIG_BLIND if phase == MPPhase.SMALL_BLIND
                                 else MPPhase.PVP_BLIND)

        elif phase == MPPhase.PVP_BLIND:
            # PvP blind: no death, just score comparison + reward adjustment
            p1_score = p1.chips_scored
            p2_score = p2.chips_scored

            # Revive underlying games if they failed the boss blind target
            # (they failed the chip target, but in MP this doesn't kill them —
            # they just lose the PvP and advance)
            self._revive_boss_if_needed(p1)
            self._revive_boss_if_needed(p2)

            # PvP reward: larger signal than before
            if p1_score > p2_score:
                p1_reward += R_PVP_WIN
                p2_reward += R_PVP_LOSS
            elif p2_score > p1_score:
                p2_reward += R_PVP_WIN
                p1_reward += R_PVP_LOSS
            # Tie: no PvP reward

            # Advance to next ante. If we just cleared ante 8, both survived → draw/mutual win
            if self.mp.current_ante >= 8:
                self.mp.phase = MPPhase.GAME_OVER
                self._winner_override = 0  # mutual survival
                p1_reward += R_DRAW_BONUS + R_GAME_WIN
                p2_reward += R_DRAW_BONUS + R_GAME_WIN
            else:
                self.mp.advance_to_next_ante()

        return (p1_reward, p2_reward)

    # NOTE: _lookahead_winner_survival removed in Run 4.
    # With the new design (regular blind failure = immediate game over), the
    # winner is decisively the survivor — no need to simulate forward to
    # distinguish "shaky" from "strong" wins. The reward structure is simpler.


    def _revive_boss_if_needed(self, game):
        """
        Boss blind-specific revive: after a PvP blind is resolved, the underlying
        BalatroGame may be in GAME_OVER state if the player failed the chip target.
        In V8 Run 4, PvP blind failure doesn't end the overall game — it just loses
        the PvP reward. We revive the player to SHOP so they can proceed to next ante.

        Regular (small/big) blind failures are NOT revived — they end the game
        for that player.
        """
        if game.state != State.GAME_OVER:
            return  # cleared naturally

        from .shop import generate_shop

        # Reset to SHOP so they can recover between antes
        game.current_shop = generate_shop(game)
        game.reroll_discount = 0
        game.free_rerolls_remaining = game.free_rerolls_per_round
        game.state = State.SHOP

    def _is_blind_done(self, game, last_resolved: tuple[int, int]) -> bool:
        """A player's current blind is "done" when they've scored enough, run out
        of hands, or reached game over.

        last_resolved: the (ante, blind_idx) that was already resolved for this
        player. If they're still at that same position in SHOP state, we've
        already counted them as done — wait until they move past it.
        """
        if game.state == State.GAME_OVER:
            return True
        current_pos = (game.ante, game.blind_idx)
        if game.state == State.SHOP:
            # Don't re-count a SHOP state we've already resolved
            return current_pos != last_resolved
        if game.state == State.SELECTING_HAND and game.hands_left <= 0:
            return True
        return False

    # ─────────────────────────────────────────────────────────────────────
    # Player-specific helpers
    # ─────────────────────────────────────────────────────────────────────

    def get_phase(self, player: int) -> int:
        return (self.p1 if player == 1 else self.p2).get_phase()

    def get_intent_mask(self, player: int) -> np.ndarray:
        return (self.p1 if player == 1 else self.p2).get_intent_mask()

    def get_phase_mask(self, player: int) -> np.ndarray:
        return (self.p1 if player == 1 else self.p2).get_phase_mask()
