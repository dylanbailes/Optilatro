"""
balatro_rl/env_v2.py
V2 Gymnasium environment with Discrete(20) action space and MaskablePPO support.

Observation space: Box(206,) float32
Action space:      Discrete(20)
  [0-9]   Play option N (ranked by estimated score)
  [10-19] Discard option N (8 single + 2 multi-card)
"""

import os
import subprocess
import time
import numpy as np
import gymnasium as gym
from gymnasium import spaces

from balatro_rl.state_v2 import (
    read_state, state_to_obs, GameState, OBS_SIZE,
    HAND_TYPE_TO_ID
)
from balatro_rl.action_v2 import (
    write_action, generate_action_mask, action_to_cards_and_type, ACTION_FILE
)

# ── Speed configuration ───────────────────────────────────────────────────────
# Adjust based on Handy mod speed multiplier
# 1.0 = 32x, 0.5 = 64x, 0.32 = 100x, 0.25 = 128x
SPEED_FACTOR = 0.5  # For 64x Handy speed

# ── Balatro process management ────────────────────────────────────────────────

_BALATRO_EXE = os.environ.get(
    "BALATRO_EXE",
    r"C:\Program Files (x86)\Steam\steamapps\common\Balatro\Balatro.exe"
)

def _balatro_restart():
    """Kill and relaunch Balatro."""
    r = subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq Balatro.exe", "/FO", "CSV", "/NH"],
        capture_output=True, text=True
    )
    for line in r.stdout.splitlines():
        if "Balatro.exe" in line:
            try:
                pid = int(line.split(",")[1].strip('"'))
                subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True)
                time.sleep(2)
            except (IndexError, ValueError):
                pass
    time.sleep(1)
    if os.path.exists(_BALATRO_EXE):
        subprocess.Popen([_BALATRO_EXE])
        print("[BalatroEnvV2] Balatro relaunched — waiting for mod to initialize...")
        time.sleep(5)

# ── Reward constants ──────────────────────────────────────────────────────────

R_BLIND_COMPLETE   =  2.0
R_ANTE_COMPLETE    =  5.0
R_WIN              = 20.0
R_LOSE             = -2.0
R_SCORE_PROGRESS   =  0.05
DISCARD_DELTA_SCALE = 0.001  # reward for Δ best_play_score after discard

# Game state constants
GS_SELECTING_HAND = 1

# ── Environment ───────────────────────────────────────────────────────────────

class BalatroEnvV2(gym.Env):
    """
    V2 Balatro environment with pre-ranked play/discard options.
    
    Uses MaskablePPO-compatible action_masks() method.
    """
    
    metadata = {"render_modes": []}
    
    def __init__(self, step_timeout: float = 15.0):
        super().__init__()
        self.step_timeout = step_timeout
        
        # V2: 206-feature observation, Discrete(20) action
        self.observation_space = spaces.Box(
            low=0.0, high=1.0, shape=(OBS_SIZE,), dtype=np.float32
        )
        self.action_space = spaces.Discrete(20)
        
        self._gs: GameState | None = None
        self._action_mask = np.ones(20, dtype=bool)
        
        # State tracking
        self._prev_ante = 0
        self._prev_round = 0
        self._prev_best_play_score = 0.0
        self._last_action_type = "play"
        
        # Logging metadata
        self._last_seed = "unknown"
        self._last_ante = 1
        self._last_round = 0
        self._last_blind = "Small Blind"
        self._last_score = 0
        self._last_hand_type = "unknown"
        self._last_joker_names = []
        self._episode_reward = 0.0
        self._terminal_reason = "unknown"
        
        self._consecutive_timeouts = 0
        self._last_live_tick = 0.0

    # ── Gymnasium interface ──────────────────────────────────────────────────

    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        
        print("[BalatroEnvV2] Waiting for new run...")
        gs = self._wait_for_new_run(timeout=180.0)
        if gs is None:
            raise RuntimeError("Timed out waiting for Balatro to start a new run.")
        
        self._gs = gs
        self._prev_ante = gs.ante
        self._prev_round = gs.round
        self._prev_best_play_score = gs.best_play_score
        self._episode_reward = 0.0
        
        self._action_mask = generate_action_mask(gs)
        
        obs = state_to_obs(gs)
        info = self._make_info(gs)
        print(f"[BalatroEnvV2] Run started — Ante {gs.ante}, Blind: {gs.blind_name}")
        return obs, info

    def step(self, action: int):
        assert self._gs is not None, "Call reset() before step()"
        
        # Pre-action: wait for hand-ready state
        gs = self._wait_for_hand_ready(self._gs.timestamp, timeout=self.step_timeout)
        if gs is None:
            latest = read_state(timeout=1.0) or self._gs
            if self._is_terminal(latest):
                obs = state_to_obs(latest)
                return obs, R_LOSE, True, False, self._make_info(latest)
            obs = state_to_obs(self._gs)
            return obs, -0.1, False, False, self._make_info(self._gs)
        self._gs = gs
        
        # Update logging metadata
        self._last_seed = gs.seed
        self._last_ante = gs.ante
        # Derive round from blind_name (G.GAME.round is cumulative, not 0/1/2)
        if gs.blind_name == "Small Blind":
            self._last_round = 0
        elif gs.blind_name == "Big Blind":
            self._last_round = 1
        else:
            self._last_round = 2  # Boss blind
        self._last_blind = gs.blind_name
        self._last_score = int(gs.current_score)
        self._last_hand_type = gs.last_hand_type
        self._last_joker_names = [j.name for j in gs.jokers if j.is_present]
        
        # Check terminal before action
        if self._is_terminal_fast(gs):
            print(f"[term] FAST: event={gs.event} ante={gs.ante}")
            obs = state_to_obs(gs)
            return obs, R_LOSE, True, False, self._make_info(gs)
        
        # Check if blind already cleared (score >= target) — wait for transition
        if gs.current_score >= gs.score_target and gs.score_target > 0:
            # Blind is cleared, wait for game to transition
            time.sleep(0.3 * SPEED_FACTOR)
            new_gs = self._wait_for_next_hand(gs.timestamp, timeout=5.0)
            if new_gs:
                self._gs = new_gs
                gs = new_gs
        
        # Store pre-action state for reward computation
        pre_best_score = gs.best_play_score
        
        # Convert action to card indices
        card_indices, action_type = action_to_cards_and_type(action, gs)
        self._last_action_type = action_type
        
        # Write action and wait for game response
        write_action(card_indices, action_type)
        new_gs = self._wait_for_next_hand(gs.timestamp, timeout=self.step_timeout)
        
        if new_gs is None:
            self._consecutive_timeouts += 1
            if self._consecutive_timeouts >= 5:
                print(f"\n[BalatroEnvV2] Game unresponsive. Waiting 15s...")
                time.sleep(15.0)
            obs = state_to_obs(gs)
            return obs, -0.1, False, False, self._make_info(gs)
        self._consecutive_timeouts = 0
        self._gs = new_gs
        
        # Compute reward
        reward = self._compute_reward(gs, new_gs, action_type, pre_best_score)
        self._episode_reward += reward
        
        # Terminal detection
        terminated = False
        self._terminal_reason = "ongoing"
        if self._is_terminal_fast(new_gs):
            print(f"[term] FAST: event={new_gs.event} ante={new_gs.ante}")
            terminated = True
            self._terminal_reason = "won" if new_gs.ante > 8 else "game_over"
        elif new_gs.hands_left <= 0 and new_gs.discards_left <= 0:
            # The Hook and other bosses can have delayed scoring — retry multiple times
            for retry in range(4):
                time.sleep(0.25 * SPEED_FACTOR)
                fresh = read_state(timeout=1.0)
                if fresh:
                    new_gs = fresh
                # If score meets target or we moved to next blind, not lost
                if new_gs.current_score >= new_gs.score_target:
                    break
                # If ante/round changed, blind was cleared
                if new_gs.ante > gs.ante or new_gs.round > gs.round:
                    break
            if new_gs.current_score < new_gs.score_target and new_gs.ante == gs.ante:
                print(f"[term] LOST: h={new_gs.hands_left} d={new_gs.discards_left}"
                      f" score={new_gs.current_score:.0f} target={new_gs.score_target:.0f}")
                terminated = True
                self._terminal_reason = "lost"
            else:
                time.sleep(0.5 * SPEED_FACTOR)
                fresh = read_state(timeout=1.0)
                if fresh:
                    new_gs = fresh
                terminated = self._is_terminal(new_gs)
                if terminated:
                    self._terminal_reason = "won" if new_gs.ante > 8 else "lost"
        
        # Update metadata
        self._last_seed = new_gs.seed
        self._last_ante = new_gs.ante
        # Derive round from blind_name
        if new_gs.blind_name == "Small Blind":
            self._last_round = 0
        elif new_gs.blind_name == "Big Blind":
            self._last_round = 1
        else:
            self._last_round = 2  # Boss blind
        self._last_blind = new_gs.blind_name
        self._last_score = int(new_gs.current_score)
        self._last_hand_type = new_gs.last_hand_type
        self._last_joker_names = [j.name for j in new_gs.jokers if j.is_present]
        
        # Update action mask for next step
        self._action_mask = generate_action_mask(new_gs)
        
        obs = state_to_obs(new_gs)
        info = self._make_info(new_gs)
        
        if terminated:
            won = new_gs.ante > 8
            print(f"[BalatroEnvV2] Episode {'WON' if won else 'LOST'} | "
                  f"Ante {new_gs.ante} | Total reward: {self._episode_reward:.2f}")
        
        return obs, reward, terminated, False, info

    def action_masks(self) -> np.ndarray:
        """Return boolean mask for valid actions (MaskablePPO interface)."""
        return self._action_mask

    def render(self):
        pass

    def close(self):
        pass

    # ── Reward computation ────────────────────────────────────────────────────

    def _compute_reward(self, old: GameState, new: GameState, 
                        action_type: str, pre_best_score: float) -> float:
        reward = 0.0
        
        # Score progress
        old_progress = old.current_score / max(old.score_target, 1)
        new_progress = new.current_score / max(new.score_target, 1)
        delta_progress = new_progress - old_progress
        if delta_progress > 0:
            reward += R_SCORE_PROGRESS * delta_progress * 100
        
        # Blind complete
        if new.round > old.round and new.ante == old.ante:
            reward += R_BLIND_COMPLETE
        
        # Ante complete
        if new.ante > old.ante:
            reward += R_ANTE_COMPLETE
        
        # Win
        if new.ante > 8:
            reward += R_WIN
        
        # Discard reward: Δ best_play_score
        if action_type == "discard":
            delta_best = new.best_play_score - pre_best_score
            reward += DISCARD_DELTA_SCALE * delta_best
        
        # Loss penalty (already handled by terminal detection)
        
        return reward

    # ── Terminal detection ────────────────────────────────────────────────────

    def _is_terminal_fast(self, gs: GameState) -> bool:
        if gs.event == "game_over":
            return True
        if gs.ante > 8:
            return True
        return False

    def _is_terminal(self, gs: GameState) -> bool:
        if self._is_terminal_fast(gs):
            return True
        # Exclude nav screens
        if gs.game_state in (5, 7, 8, 19):  # SHOP, BLIND_SELECT, ROUND_EVAL, NEW_ROUND
            return False
        if gs.hands_left <= 0 and gs.discards_left <= 0:
            if gs.current_score < gs.score_target:
                return True
        return False

    # ── Wait helpers ──────────────────────────────────────────────────────────

    def _wait_for_hand_ready(self, old_ts: float, timeout: float) -> GameState | None:
        HAND_EVENTS = ("selecting_hand", "hand_drawn")
        deadline = time.time() + timeout
        shop_stuck_time = None
        while time.time() < deadline:
            gs = read_state(timeout=1.0)
            if gs is None:
                time.sleep(0.1 * SPEED_FACTOR)
                continue
            if gs.event == "game_over":
                return gs
            if gs.hand and gs.event in HAND_EVENTS:
                return gs
            # Detect stuck in shop - force leave after 10 seconds
            if gs.event == "shop":
                if shop_stuck_time is None:
                    shop_stuck_time = time.time()
                elif time.time() - shop_stuck_time > 10:
                    print("[WARN] Stuck in shop, forcing leave...")
                    write_action([], "leave_shop")
                    shop_stuck_time = time.time()
            else:
                shop_stuck_time = None
            time.sleep(0.05 * SPEED_FACTOR)
        return None

    def _wait_for_next_hand(self, old_ts: float, timeout: float) -> GameState | None:
        """Post-action: wait for NEXT actionable state (tick > old_ts)."""
        HAND_EVENTS = ("selecting_hand", "hand_drawn")
        deadline = time.time() + timeout
        shop_stuck_time = None
        while time.time() < deadline:
            gs = read_state(timeout=1.0)
            if gs is None:
                time.sleep(0.1 * SPEED_FACTOR)
                continue
            if gs.timestamp <= old_ts:
                time.sleep(0.05 * SPEED_FACTOR)
                continue
            if gs.event == "game_over":
                return gs
            if gs.hand and gs.event in HAND_EVENTS:
                return gs
            # Detect stuck in shop - force leave after 10 seconds
            if gs.event == "shop":
                if shop_stuck_time is None:
                    shop_stuck_time = time.time()
                elif time.time() - shop_stuck_time > 10:
                    print("[WARN] Stuck in shop, forcing leave...")
                    write_action([], "leave_shop")
                    shop_stuck_time = time.time()
            else:
                shop_stuck_time = None
            time.sleep(0.05 * SPEED_FACTOR)
        return None

    def _wait_for_new_run(self, timeout: float) -> GameState | None:
        """Wait for a fresh run at ante 1, Small Blind."""
        current = read_state(timeout=5.0)
        baseline_mtime = current.file_mtime if current else 0.0
        
        STALE_SECS = 45.0
        last_mtime_wall = time.time()
        last_seen_mtime = baseline_mtime
        
        deadline = time.time() + timeout
        while time.time() < deadline:
            gs = read_state(timeout=1.0)
            if gs is None:
                time.sleep(0.3 * SPEED_FACTOR)
                continue
            
            # Track staleness
            if gs.file_mtime != last_seen_mtime:
                last_seen_mtime = gs.file_mtime
                last_mtime_wall = time.time()
            elif time.time() - last_mtime_wall > STALE_SECS:
                print(f"\n[BalatroEnvV2] state.json stale — restarting Balatro...")
                try:
                    _balatro_restart()
                except Exception as e:
                    print(f"[BalatroEnvV2] Restart failed: {e}")
                last_mtime_wall = time.time()
                last_seen_mtime = 0.0
            
            # Stuck detection: mid-run state
            if (gs.hands_left > 0
                    and gs.game_state == GS_SELECTING_HAND
                    and not (gs.ante == 1 and gs.blind_name == "Small Blind")
                    and time.time() - last_mtime_wall > 3.0):
                print(f"[BalatroEnvV2] Mid-run deadlock — restarting Balatro")
                try:
                    _balatro_restart()
                except Exception as e:
                    print(f"[BalatroEnvV2] Restart failed: {e}")
                last_mtime_wall = time.time()
                last_seen_mtime = 0.0
            
            # Stuck in shop during reset - restart after 15 seconds
            if gs.event == "shop" and time.time() - last_mtime_wall > 15.0:
                print(f"[BalatroEnvV2] Stuck in shop during reset — restarting Balatro")
                try:
                    _balatro_restart()
                except Exception as e:
                    print(f"[BalatroEnvV2] Restart failed: {e}")
                last_mtime_wall = time.time()
                last_seen_mtime = 0.0
            
            # Accept valid new run state
            is_stuck = (gs.hands_left <= 0 and gs.discards_left <= 0
                        and gs.current_score < gs.score_target)
            if (gs.hand
                    and gs.event in ("hand_drawn", "selecting_hand")
                    and gs.hands_left > 0
                    and gs.ante == 1
                    and gs.blind_name == "Small Blind"
                    and not is_stuck
                    and gs.file_mtime > baseline_mtime):
                return gs
            
            time.sleep(0.1 * SPEED_FACTOR)
        return None

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _make_info(self, gs: GameState) -> dict:
        return {
            "ante": gs.ante,
            "round": gs.round,
            "score": gs.current_score,
            "target": gs.score_target,
            "blind": gs.blind_name,
            "hands_left": gs.hands_left,
            "discards_left": gs.discards_left,
            "best_play_score": gs.best_play_score,
        }
