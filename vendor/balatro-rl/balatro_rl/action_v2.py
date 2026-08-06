"""
balatro_rl/action_v2.py
V2 action handling with Discrete(20) action space and masking.

Action space: Discrete(20)
  [0-9]   Play option N (from ranked play_options)
  [10-19] Discard option N (from discard_options)
"""

import json
import time
from pathlib import Path
from typing import List, Tuple
import numpy as np

from balatro_rl.state_v2 import GameState

ACTION_FILE = Path.home() / "AppData/Roaming/Balatro/balatro_rl/action.json"

# ── Action Mask Generation ────────────────────────────────────────────────────

def generate_action_mask(gs: GameState) -> np.ndarray:
    """
    Generate a boolean mask for valid actions.
    
    Returns np.ndarray of shape (20,) where True = valid action.
    
    Masking rules:
    - Play options 0-9: valid if option exists AND hands_left > 0
    - Discard options 10-19: valid if option exists AND discards_left > 0
    """
    mask = np.zeros(20, dtype=bool)
    
    # Play options (indices 0-9)
    if gs.hands_left > 0:
        for i in range(min(10, len(gs.play_options))):
            # If option exists, it's valid (is_valid field optional for socket IPC)
            if hasattr(gs.play_options[i], 'is_valid'):
                if gs.play_options[i].is_valid:
                    mask[i] = True
            else:
                mask[i] = True
    
    # Discard options (indices 10-19)
    if gs.discards_left > 0:
        for i in range(min(10, len(gs.discard_options))):
            # If option exists, it's valid (is_valid field optional for socket IPC)
            if hasattr(gs.discard_options[i], 'is_valid'):
                if gs.discard_options[i].is_valid:
                    mask[10 + i] = True
            else:
                mask[10 + i] = True
    
    # Ensure at least one action is valid (fallback to first play if nothing else)
    if not mask.any():
        if len(gs.play_options) > 0:
            mask[0] = True
        elif len(gs.discard_options) > 0:
            mask[10] = True
    
    return mask

# ── Action Conversion ─────────────────────────────────────────────────────────

def action_to_cards_and_type(action: int, gs: GameState) -> Tuple[List[int], str]:
    """
    Convert action index to card indices and action type.
    
    Args:
        action: int in [0, 19]
        gs: current GameState with play/discard options
    
    Returns:
        (card_indices, action_type) where:
        - card_indices: 0-indexed card positions in hand
        - action_type: "play" or "discard"
    """
    if action < 10:
        # Play option
        action_type = "play"
        opt_idx = action
        if opt_idx < len(gs.play_options):
            # Convert 1-indexed Lua indices to 0-indexed Python
            card_indices = [i - 1 for i in gs.play_options[opt_idx].indices]
        else:
            # Fallback: play first card
            card_indices = [0] if len(gs.hand) > 0 else []
    else:
        # Discard option
        action_type = "discard"
        opt_idx = action - 10
        if opt_idx < len(gs.discard_options):
            card_indices = [i - 1 for i in gs.discard_options[opt_idx].indices]
        else:
            # Fallback: discard first card
            card_indices = [0] if len(gs.hand) > 0 else []
    
    # Filter to valid indices
    card_indices = [i for i in card_indices if 0 <= i < len(gs.hand)]
    
    return card_indices, action_type

# ── File I/O ──────────────────────────────────────────────────────────────────

def write_action(card_indices: List[int], action_type: str, wait_consumed: float = 2.0) -> None:
    """
    Write action to action.json for Lua to consume.
    
    Args:
        card_indices: 0-indexed card positions
        action_type: "play" or "discard"
        wait_consumed: max seconds to wait for Lua to consume the file
    """
    payload = {"card_indices": card_indices, "action": action_type}
    ACTION_FILE.parent.mkdir(parents=True, exist_ok=True)
    ACTION_FILE.write_text(json.dumps(payload), encoding="utf-8")
    
    # Wait for Lua to consume (file deleted after read)
    deadline = time.time() + wait_consumed
    while time.time() < deadline:
        if not ACTION_FILE.exists():
            return
        time.sleep(0.05)

def write_nav(nav_action: str) -> None:
    """Write a navigation action for Lua (legacy, may not be needed in V2)."""
    payload = {"action": nav_action}
    ACTION_FILE.parent.mkdir(parents=True, exist_ok=True)
    ACTION_FILE.write_text(json.dumps(payload), encoding="utf-8")
