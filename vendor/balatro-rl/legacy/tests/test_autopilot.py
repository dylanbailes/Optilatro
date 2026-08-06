"""
test_autopilot.py
Verify Lua auto-pilot (blind select, cash out, shop, restart) without the PPO agent.
Python just plays random hands so the game progresses; all navigation is handled by the mod.

Run with:  python test_autopilot.py
Stop with: Ctrl+C
"""

import time
import random
from balatro_rl.state  import read_state
from balatro_rl.action import write_action

# How many hands to play before we stop (0 = run forever until Ctrl+C)
MAX_HANDS = 0
STEP_TIMEOUT = 20.0   # seconds to wait for state change

def play_random_hand(gs):
    """Play 5 random cards from the hand."""
    hand_size = len(gs.hand)
    n = min(5, hand_size)
    indices = random.sample(range(hand_size), n)
    write_action(indices, "play")
    return indices

def wait_for_change(old_ts, timeout=STEP_TIMEOUT):
    deadline = time.time() + timeout
    while time.time() < deadline:
        gs = read_state(timeout=1.0)
        if gs and gs.timestamp > old_ts:
            return gs
        time.sleep(0.05)
    return None

def main():
    print("Waiting for Balatro to have a hand ready... (start a run in-game)")
    print("Press Ctrl+C to stop.\n")

    # Wait for initial state
    gs = None
    while gs is None or not gs.hand:
        gs = read_state(timeout=2.0)
        time.sleep(0.2)

    print(f"Connected! Ante={gs.ante} Round={gs.round} Blind={gs.blind_name}")
    print(f"Score target: {gs.score_target}\n")

    hands_played = 0
    last_ante  = gs.ante
    last_round = gs.round
    last_event = gs.event

    while True:
        gs = read_state(timeout=2.0)
        if gs is None:
            time.sleep(0.1)
            continue

        # Print state transitions as they happen
        if gs.ante != last_ante:
            print(f"  ★ ANTE ADVANCED: {last_ante} → {gs.ante}")
            last_ante = gs.ante
        if gs.round != last_round:
            print(f"  ✓ BLIND CLEARED: round {last_round} → {gs.round} | Blind={gs.blind_name}")
            last_round = gs.round
        if gs.event != last_event:
            print(f"  [event] {last_event} → {gs.event} | state ante={gs.ante} round={gs.round}")
            last_event = gs.event

        # Only act when hand is ready
        if gs.event not in ("selecting_hand", "hand_drawn") or not gs.hand:
            time.sleep(0.05)
            continue

        # Play a random hand
        indices = play_random_hand(gs)
        hand_size = len(gs.hand)
        ranks = [gs.hand[i].rank for i in indices if i < hand_size]
        print(f"  Hand #{hands_played+1:>3} | ante={gs.ante} round={gs.round} "
              f"hands_left={gs.hands_left} disc_left={gs.discards_left} "
              f"score={int(gs.current_score)}/{int(gs.score_target)} "
              f"| playing {ranks}")

        old_ts = gs.timestamp
        new_gs = wait_for_change(old_ts)
        if new_gs is None:
            print("  [timeout] Game unresponsive — is Balatro running?")
            time.sleep(2.0)
            continue

        gs = new_gs
        hands_played += 1

        if gs.event == "game_over":
            print(f"\n  ✗ GAME OVER at ante={gs.ante} after {hands_played} hands")
            print("  Waiting for Lua auto-restart...\n")
            # Wait for a fresh run
            time.sleep(6.0)
            hands_played = 0
            last_ante  = 1
            last_round = 1
            last_event = ""

        if MAX_HANDS and hands_played >= MAX_HANDS:
            print(f"\nReached MAX_HANDS={MAX_HANDS}. Done.")
            break

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped.")
