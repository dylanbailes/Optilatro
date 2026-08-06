"""
test_shop.py — Watch the shop nav and joker buying in action.
Run this while Balatro is open. It just prints state transitions and waits.
No actions sent — Lua drives everything.
"""
import time
from balatro_rl.state import read_state

GS_NAMES = {1: "SELECTING_HAND", 2: "HAND_PLAYED", 3: "DRAW_TO_HAND",
            4: "GAME_OVER", 5: "SHOP", 7: "BLIND_SELECT", 8: "ROUND_EVAL",
            19: "NEW_ROUND"}

def main():
    print("Watching Balatro state... (Ctrl+C to stop)")
    print("Play normally until you reach a shop, then watch here.\n")

    last_gs  = -1
    last_ts  = 0
    last_jokers = []

    while True:
        state = read_state(timeout=1.0)
        if state is None:
            time.sleep(0.2)
            continue

        g = state.game_state
        ts = state.timestamp

        # Print on state change
        if g != last_gs:
            name = GS_NAMES.get(g, f"STATE_{g}")
            print(f"  → {name} (state={g})  ante={state.ante}  $={state.money:.0f}")
            last_gs = g

        # Print joker changes
        joker_names = [j.name for j in state.jokers]
        if joker_names != last_jokers:
            if joker_names:
                print(f"  🃏 Jokers: {joker_names}")
            last_jokers = joker_names

        # Print shop items when entering shop
        if g == 5 and ts != last_ts:
            shop = getattr(state, "shop", [])
            if shop:
                joker_items = [s for s in shop if isinstance(s, dict) and s.get("key","").startswith("j_")]
                if joker_items:
                    for item in joker_items:
                        print(f"  🏪 Shop joker: {item.get('name','?')}  cost=${item.get('cost','?')}")
            last_ts = ts

        time.sleep(0.1)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nDone.")
