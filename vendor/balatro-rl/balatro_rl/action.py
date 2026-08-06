"""
balatro_rl/action.py
Writes action.json for the BalatroRL Lua mod to consume.

Action format:
  card_indices: list of 0-based indices into the current hand
  action:       "play" or "discard"
"""

import json
import time
import numpy as np
from pathlib import Path
from typing import List

ACTION_FILE = Path(r"C:\Users\Taggart\AppData\Roaming\Balatro\balatro_rl\action.json")
STATE_FILE  = Path(r"C:\Users\Taggart\AppData\Roaming\Balatro\balatro_rl\state.json")

MAX_PLAY_CARDS    = 5
MAX_DISCARD_CARDS = 5


NAV_ACTIONS = {"select_blind", "cash_out", "leave_shop", "new_run"}


def write_action(card_indices: List[int], action_type: str, wait_consumed: float = 2.0) -> None:
    """Write a card play/discard action. Waits for previous action to be consumed."""
    assert action_type in ("play", "discard"), f"Unknown card action: {action_type}"
    deadline = time.time() + wait_consumed
    while ACTION_FILE.exists() and time.time() < deadline:
        time.sleep(0.02)
    payload = {"card_indices": card_indices, "action": action_type}
    ACTION_FILE.write_text(json.dumps(payload), encoding="utf-8")


def write_nav(action_type: str, wait_consumed: float = 2.0) -> None:
    """Write a navigation action (select_blind, cash_out, leave_shop, new_run)."""
    assert action_type in NAV_ACTIONS, f"Unknown nav action: {action_type}"
    deadline = time.time() + wait_consumed
    while ACTION_FILE.exists() and time.time() < deadline:
        time.sleep(0.02)
    ACTION_FILE.write_text(json.dumps({"action": action_type}), encoding="utf-8")


def agent_output_to_action(
    logits: np.ndarray,
    hand_size: int,
    hands_left: int,
    discards_left: int,
) -> tuple[List[int], str]:
    """
    Convert raw agent output (9 values) to a concrete action.

    logits[0:8]  — per-card selection scores (higher = more likely to highlight)
    logits[8]    — play vs discard score (>0 = play, <=0 = discard)

    Rules enforced here:
    - Only highlight cards that actually exist (hand_size guard)
    - Cap highlighted cards at MAX_PLAY_CARDS (5)
    - Force play if no discards left
    - Force discard if no hands left (shouldn't happen, but guard anyway)
    """
    card_scores = logits[:8]

    # Only consider cards actually in hand
    card_scores = card_scores[:hand_size]

    # Decide play vs discard
    if discards_left == 0:
        action_type = "play"
    elif hands_left == 0:
        action_type = "discard"
    else:
        action_type = "play" if logits[8] > 0 else "discard"

    # Pick top-k cards by score, capped at MAX
    k = MAX_PLAY_CARDS if action_type == "play" else MAX_DISCARD_CARDS
    if len(card_scores) <= k:
        selected = list(range(len(card_scores)))
    else:
        # Top-k indices, sorted by descending score
        selected = sorted(
            np.argpartition(card_scores, -k)[-k:].tolist(),
            key=lambda i: -card_scores[i]
        )

    # Filter: only include cards with positive score
    # (avoids highlighting cards the agent is uncertain about)
    selected = [i for i in selected if card_scores[i] > 0]

    # Must play/discard at least 1 card
    if not selected:
        selected = [int(np.argmax(card_scores))]

    return selected, action_type


def random_action(hand_size: int, discards_left: int) -> tuple[List[int], str]:
    """Random baseline action — useful for sanity checking."""
    n = min(np.random.randint(1, MAX_PLAY_CARDS + 1), hand_size)
    cards = np.random.choice(hand_size, size=n, replace=False).tolist()
    action = "play" if (discards_left == 0 or np.random.random() > 0.3) else "discard"
    return sorted(cards), action
