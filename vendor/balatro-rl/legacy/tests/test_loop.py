"""
test_loop.py
Manual test of the full observe → act → observe loop.
Run this while Balatro is open on a hand selection screen.

Usage:  python test_loop.py
"""

import sys, time
sys.path.insert(0, ".")

from balatro_rl.state  import read_state, state_to_obs, STATE_FILE
from balatro_rl.action import write_action, random_action, ACTION_FILE

STEPS = 10  # how many actions to take

def wait_for_new_state(old_timestamp: int, timeout: float = 10.0):
    """Poll until state.json has a newer timestamp than old_timestamp."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        gs = read_state(timeout=1.0)
        if gs and gs.event != "mod_loaded":
            if gs.timestamp != old_timestamp:
                return gs
        time.sleep(0.05)
    return None

def main():
    print("Reading initial state...")
    gs = read_state()
    if gs is None:
        print("ERROR: Could not read state.json — is Balatro running with the mod enabled?")
        return

    print(f"Connected! Ante {gs.ante}, Round {gs.round}, Phase={gs.phase}")

    # Wait until we have an actual hand dealt
    if not gs.hand:
        print("Waiting for hand to be dealt (play a round in Balatro)...")
        deadline = time.time() + 30
        while time.time() < deadline:
            gs = read_state()
            if gs and gs.hand:
                break
            time.sleep(0.2)
        if not gs or not gs.hand:
            print("ERROR: No hand dealt within 30s. Make sure you're in a run.")
            return

    print(f"Hand: {[(c.rank, c.suit) for c in gs.hand]}")

    for step in range(STEPS):
        if gs.phase != 2 or not gs.hand:
            print(f"Step {step+1}: not in hand selection (phase={gs.phase}), waiting...")
            time.sleep(1.0)
            gs = read_state() or gs
            continue

        # Pick a random action
        cards, action_type = random_action(len(gs.hand), gs.discards_left)
        hand_preview = [(gs.hand[i].rank, gs.hand[i].suit) for i in cards if i < len(gs.hand)]

        print(f"\nStep {step+1}: {action_type.upper()} cards {cards} -> {hand_preview}")
        print(f"  Score: {gs.current_score}/{gs.score_target}  "
              f"Hands: {gs.hands_left}  Discards: {gs.discards_left}")

        old_ts = gs.timestamp
        write_action(cards, action_type)

        # Wait for Lua to consume and update state
        new_gs = wait_for_new_state(old_ts, timeout=8.0)
        if new_gs is None:
            print("  WARNING: no new state received — did the action fire?")
            gs = read_state() or gs
        else:
            gs = new_gs
            obs = state_to_obs(gs)
            print(f"  → event={gs.event}  score={gs.current_score}  obs_norm=[{obs.min():.2f}, {obs.max():.2f}]")

    print("\nDone.")

if __name__ == "__main__":
    main()
