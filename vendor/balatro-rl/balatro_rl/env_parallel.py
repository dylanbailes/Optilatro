"""
balatro_rl/env_parallel.py
Parallel-capable environment with instance_id support.
"""

import os
import subprocess
import time
import numpy as np
import gymnasium as gym
from gymnasium import spaces
from pathlib import Path

from balatro_rl.state_v2 import (
    GameState, OBS_SIZE, HAND_TYPE_TO_ID
)
from balatro_rl.action_v2 import (
    generate_action_mask, action_to_cards_and_type
)

# Speed configuration - adjust based on game speed
SPEED_FACTOR = 0.5  # 0.5 for 64x

# Rewards
R_WIN = 20.0
R_LOSE = -1.0


def get_state_paths(instance_id: int):
    """Get paths for a specific instance."""
    base = Path.home() / "AppData/Roaming/Balatro"
    state_dir = base / f"balatro_rl_{instance_id}"
    return {
        "state_file": state_dir / "state.json",
        "action_file": state_dir / "action.json",
        "log_file": state_dir / "log.txt",
    }


def read_state(state_file: Path, timeout: float = 2.0) -> GameState | None:
    """Read and parse state.json for a specific instance."""
    import json
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if not state_file.exists():
                time.sleep(0.05)
                continue
            text = state_file.read_text(encoding='utf-8')
            if not text.strip():
                time.sleep(0.05)
                continue
            data = json.loads(text)
            return GameState(data, state_file.stat().st_mtime)
        except (json.JSONDecodeError, OSError):
            time.sleep(0.05)
    return None


def write_action(action_file: Path, card_indices: list, action_type: str):
    """Write action.json for a specific instance."""
    import json
    payload = {"type": action_type, "cards": card_indices}
    action_file.write_text(json.dumps(payload), encoding='utf-8')


def state_to_obs(gs: GameState) -> np.ndarray:
    """Convert GameState to observation vector."""
    obs = np.zeros(OBS_SIZE, dtype=np.float32)
    idx = 0
    
    # Hand cards: 8 slots × 7 features = 56
    for i in range(8):
        if i < len(gs.hand):
            card = gs.hand[i]
            obs[idx] = card.rank_id / 14.0
            obs[idx+1] = card.suit_id / 4.0
            obs[idx+2] = float(card.is_enhanced)
            obs[idx+3] = float(card.has_edition)
            obs[idx+4] = float(card.has_seal)
            obs[idx+5] = 1.0  # highlighted (not used)
            obs[idx+6] = 1.0  # exists
        idx += 7
    
    # Jokers: 5 slots × 6 features = 30
    for i in range(5):
        if i < len(gs.jokers):
            j = gs.jokers[i]
            if j.is_present:
                obs[idx] = hash(j.name) % 1000 / 1000.0
                obs[idx+1] = j.sell_value / 10.0
                obs[idx+2] = j.rarity / 4.0
                obs[idx+3] = 0.0  # buy price
                obs[idx+4] = 0.0  # effect encoding
                obs[idx+5] = 1.0  # exists
        idx += 6
    
    # Scalars: 9 features
    obs[idx] = gs.ante / 8.0
    obs[idx+1] = gs.round / 3.0
    obs[idx+2] = min(gs.current_score / max(gs.score_target, 1), 2.0)
    obs[idx+3] = gs.hands_left / 5.0
    obs[idx+4] = gs.discards_left / 5.0
    obs[idx+5] = min(gs.money / 100.0, 1.0)
    obs[idx+6] = gs.joker_slots / 5.0
    obs[idx+7] = min(gs.deck_remaining / 52.0, 1.0)
    obs[idx+8] = 0.0  # discard count
    idx += 9
    
    # Hand levels: 12 types × 2 features = 24
    hand_types = ["High Card", "Pair", "Two Pair", "Three of a Kind", 
                  "Straight", "Flush", "Full House", "Four of a Kind",
                  "Straight Flush", "Five of a Kind", "Flush House", "Flush Five"]
    for ht in hand_types:
        level_info = gs.hand_levels.get(ht, {})
        obs[idx] = level_info.get('level', 1) / 10.0
        obs[idx+1] = min(level_info.get('chips', 10) / 100.0, 1.0)
        idx += 2
    
    # Top plays: 10 × 8 features = 80
    for i in range(10):
        if i < len(gs.top_plays):
            play = gs.top_plays[i]
            obs[idx] = min(play.get('score', 0) / 10000.0, 1.0)
            obs[idx+1] = len(play.get('indices', [])) / 5.0
            ht = play.get('hand_name', 'High Card')
            obs[idx+2] = HAND_TYPE_TO_ID.get(ht, 0) / 12.0
            # Card indices (5 slots)
            indices = play.get('indices', [])
            for j in range(5):
                obs[idx+3+j] = (indices[j] / 8.0) if j < len(indices) else 0.0
        idx += 8
    
    return obs


class BalatroEnvParallel(gym.Env):
    """Balatro environment for parallel training."""
    
    metadata = {"render_modes": []}
    
    def __init__(self, instance_id: int = 1, step_timeout: float = 30.0):
        super().__init__()
        self.instance_id = instance_id
        self.step_timeout = step_timeout
        
        paths = get_state_paths(instance_id)
        self.state_file = paths["state_file"]
        self.action_file = paths["action_file"]
        
        self.observation_space = spaces.Box(
            low=-1.0, high=2.0, shape=(OBS_SIZE,), dtype=np.float32
        )
        self.action_space = spaces.Discrete(20)
        
        self._gs = None
        self._action_mask = np.ones(20, dtype=np.int8)
        self._episode_reward = 0.0
        self._terminal_reason = "ongoing"
        
        # Logging metadata
        self._last_ante = 1
        self._last_round = 0
        self._last_blind = "Small Blind"
        self._last_score = 0
    
    def action_masks(self) -> np.ndarray:
        return self._action_mask
    
    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        
        gs = self._wait_for_new_run(timeout=180.0)
        if gs is None:
            raise RuntimeError(f"Instance {self.instance_id}: Timed out waiting for new run")
        
        self._gs = gs
        self._episode_reward = 0.0
        self._terminal_reason = "ongoing"
        self._action_mask = generate_action_mask(gs)
        
        return state_to_obs(gs), self._make_info(gs)
    
    def step(self, action: int):
        gs = self._gs
        
        # Check if blind already cleared
        if gs.current_score >= gs.score_target and gs.score_target > 0:
            time.sleep(0.3 * SPEED_FACTOR)
            new_gs = self._wait_for_next_hand(gs.timestamp, timeout=5.0)
            if new_gs:
                self._gs = new_gs
                gs = new_gs
        
        # Convert action
        card_indices, action_type = action_to_cards_and_type(action, gs)
        
        # Store pre-action state
        pre_score = gs.current_score
        pre_ante = gs.ante
        
        # Execute action
        write_action(self.action_file, card_indices, action_type)
        
        # Wait for result
        new_gs = self._wait_for_next_hand(gs.timestamp, timeout=self.step_timeout)
        if new_gs is None:
            self._terminal_reason = "timeout"
            return state_to_obs(gs), R_LOSE, True, False, self._make_info(gs)
        
        self._gs = new_gs
        
        # Compute reward
        reward = self._compute_reward(gs, new_gs, pre_score)
        self._episode_reward += reward
        
        # Check terminal
        terminated = False
        if new_gs.event == "game_over":
            terminated = True
            self._terminal_reason = "game_over"
        elif new_gs.ante > 8:
            terminated = True
            self._terminal_reason = "won"
            reward += R_WIN
        elif new_gs.hands_left <= 0 and new_gs.current_score < new_gs.score_target:
            terminated = True
            self._terminal_reason = "lost"
        
        # Update metadata
        self._last_ante = new_gs.ante
        self._last_blind = new_gs.blind_name
        self._last_score = int(new_gs.current_score)
        
        self._action_mask = generate_action_mask(new_gs)
        
        return state_to_obs(new_gs), reward, terminated, False, self._make_info(new_gs)
    
    def _compute_reward(self, old_gs, new_gs, pre_score):
        """Progress-based reward."""
        if new_gs.score_target <= 0:
            return 0.0
        
        old_progress = pre_score / old_gs.score_target if old_gs.score_target > 0 else 0
        new_progress = new_gs.current_score / new_gs.score_target
        
        # Blind completion bonus
        if new_gs.ante > old_gs.ante or (new_gs.ante == old_gs.ante and new_gs.round > old_gs.round):
            return 2.0 + new_gs.ante * 0.5
        
        return max(0, new_progress - old_progress) * 2.0
    
    def _wait_for_new_run(self, timeout: float):
        """Wait for fresh run at ante 1."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            gs = read_state(self.state_file, timeout=1.0)
            if gs is None:
                time.sleep(0.3 * SPEED_FACTOR)
                continue
            if (gs.event in ("selecting_hand", "hand_drawn") 
                and gs.hand 
                and gs.ante == 1 
                and gs.blind_name == "Small Blind"):
                return gs
            time.sleep(0.1 * SPEED_FACTOR)
        return None
    
    def _wait_for_next_hand(self, old_ts: float, timeout: float):
        """Wait for next actionable state."""
        HAND_EVENTS = ("selecting_hand", "hand_drawn")
        deadline = time.time() + timeout
        shop_stuck_time = None
        
        while time.time() < deadline:
            gs = read_state(self.state_file, timeout=1.0)
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
            
            # Shop stuck detection
            if gs.event == "shop":
                if shop_stuck_time is None:
                    shop_stuck_time = time.time()
                elif time.time() - shop_stuck_time > 10:
                    write_action(self.action_file, [], "leave_shop")
                    shop_stuck_time = time.time()
            else:
                shop_stuck_time = None
            
            time.sleep(0.05 * SPEED_FACTOR)
        return None
    
    def _make_info(self, gs):
        return {
            "instance_id": self.instance_id,
            "ante": gs.ante,
            "blind": gs.blind_name,
            "score": gs.current_score,
            "terminal_reason": self._terminal_reason,
        }
