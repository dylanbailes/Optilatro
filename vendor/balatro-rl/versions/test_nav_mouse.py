"""
test_nav.py  —  Navigation troubleshooter
Python watches game state and clicks the real Balatro UI buttons.
YOU play the hands; this handles blind select, cash out, shop, and new run.

Run: python test_nav.py
Stop: Ctrl+C  or move mouse to top-left corner (pyautogui failsafe)
"""

import time
from balatro_rl.state import read_state
from balatro_rl.nav   import BalatroNav

# G.STATE constants
S_SELECTING_HAND = 1
S_GAME_OVER      = 4
S_SHOP           = 5
S_BLIND_SELECT   = 7
S_ROUND_EVAL     = 8

# Delay before each nav action (let animations settle)
DELAY = {
    S_BLIND_SELECT: 1.2,
    S_ROUND_EVAL:   2.0,
    S_SHOP:         1.8,   # extra time for shop to load jokers
    S_GAME_OVER:    5.0,
}

# Blind sequence: cycles Small → Big → Boss → Small → ...
# Tracks which blind to select next regardless of game state
BLIND_SEQUENCE = ["Small", "Big", "Boss"]


def main():
    nav = BalatroNav()

    print("Waiting for Balatro...")
    gs = None
    while gs is None:
        gs = read_state(timeout=2.0)
        time.sleep(0.2)

    print(f"Connected! Ante={gs.ante} Blind={gs.blind_name}\n")
    print("YOU play the hands. Script handles everything else.")
    print("Move mouse to top-left corner to emergency stop.\n")

    nav_entered_at: dict[int, float] = {}
    last_g      = -1
    blind_idx   = 0   # 0=Small, 1=Big, 2=Boss; increments after each shop

    while True:
        gs = read_state(timeout=1.0)
        if gs is None:
            time.sleep(0.1)
            continue

        g = getattr(gs, "game_state", -1)

        # Track entry time for each nav screen
        if g != last_g:
            nav_entered_at.clear()
            nav_entered_at[g] = time.time()
            last_g = g
            if g not in (S_SELECTING_HAND, 3, 2):
                print(f"  → state={g}  ante={gs.ante} round={gs.round} "
                      f"blind={gs.blind_name}  next_blind={BLIND_SEQUENCE[blind_idx]}")

        delay = DELAY.get(g)
        if not delay:
            time.sleep(0.05)
            continue

        elapsed = time.time() - nav_entered_at.get(g, time.time())
        if elapsed < delay:
            time.sleep(0.05)
            continue

        # Fire — clear timer so we don't fire again for this screen
        nav_entered_at.pop(g, None)

        if g == S_BLIND_SELECT:
            blind_type = BLIND_SEQUENCE[blind_idx]
            nav.select_blind(blind_type)

        elif g == S_ROUND_EVAL:
            nav.cash_out()

        elif g == S_SHOP:
            # Debug: show raw shop data
            print(f"  → shop raw data: {gs.shop}")
            print(f"  → money: {gs.money}")
            # Only buy joker cards (key starts with "j_"), skip tarots/planets/packs
            joker_slots = []
            money = gs.money
            for i, item in enumerate(gs.shop[:2]):   # only first 2 slots are joker positions
                key  = item.get("key", "")
                cost = item.get("cost", 999)
                if key.startswith("j_") and cost <= money:
                    joker_slots.append(i)
                    money -= cost   # track running balance so we don't overspend
                    print(f"  → will buy joker slot {i+1}: {item.get('name')} (${cost})")
                else:
                    print(f"  → skip slot {i+1}: {item.get('name','?')} key={key} cost={cost}")

            nav.leave_shop(joker_slots=joker_slots)
            # Advance blind index after leaving shop
            blind_idx = (blind_idx + 1) % 3
            print(f"  → next blind will be: {BLIND_SEQUENCE[blind_idx]}")

        elif g == S_GAME_OVER:
            nav.new_run()
            blind_idx = 0   # reset for new run
            print("  → new run started, blind_idx reset to Small")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped.")
