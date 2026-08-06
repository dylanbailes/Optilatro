"""
balatro_rl/nav.py
Python-side navigation for Balatro using pyautogui.
Finds the Balatro window and clicks the real game buttons.

Coordinates calibrated from 1456x816 gameplay screenshots.
All positions are relative (0.0-1.0) to the game window dimensions.
"""

import time
import pyautogui
import win32gui
import win32api
import win32con
from typing import Optional, Tuple

pyautogui.FAILSAFE = True
pyautogui.PAUSE    = 0.0   # we handle delays manually

# ── Calibrated relative positions (from 1456×816 screenshots) ─────────────────
#
# Blind Select — "Select" button on each blind card
BLIND_SELECT_BTN = {
    "Small": (0.364, 0.339),   # leftmost card
    "Big":   (0.545, 0.339),   # center card  — measured: (793, 277) / 1456x816
    "Boss":  (0.730, 0.339),   # rightmost    — measured: (1063, 277) / 1456x816
}

# Cash Out button — measured: (789, 335) / 1456x816
CASH_OUT_BTN = (0.542, 0.411)

# Shop — measured from 1456x816
NEXT_ROUND_BTN     = (0.366, 0.420)   # (533, 343)
SHOP_JOKER_SLOTS   = [
    (0.556, 0.490),   # slot 1 - (810, 400) / 1456x816
    (0.677, 0.490),   # slot 2 - (985, 400) / 1456x816 (shifted 5px left)
]
# BUY button appears at bottom of the card's ORIGINAL position when card pops up
# Measured: y≈490 in 816px image → 0.600
BUY_BTN_Y          = 0.600            # (490 / 816)

# Game Over — "Play Again" button (approximate center-right of game over modal)
GAME_OVER_BTN      = (0.542, 0.650)


# ── Window helpers ────────────────────────────────────────────────────────────

def get_balatro_rect() -> Optional[Tuple[int, int, int, int]]:
    """Return (left, top, right, bottom) of the Balatro window client area."""
    hwnd = win32gui.FindWindow(None, "Balatro")
    if not hwnd:
        return None
    return win32gui.GetWindowRect(hwnd)

def rel_to_screen(rect: Tuple[int,int,int,int], rx: float, ry: float) -> Tuple[int, int]:
    left, top, right, bottom = rect
    w = right  - left
    h = bottom - top
    return int(left + rx * w), int(top + ry * h)

def focus_balatro():
    """Bring Balatro window to the foreground before clicking."""
    hwnd = win32gui.FindWindow(None, "Balatro")
    if hwnd:
        try:
            win32gui.SetForegroundWindow(hwnd)
        except Exception:
            pass
        time.sleep(0.15)

def _win_click(x: int, y: int):
    """Reliable click: move → mousedown → pause → mouseup."""
    pyautogui.moveTo(x, y, duration=0.05)
    time.sleep(0.05)
    win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    time.sleep(0.08)
    win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)

def click_rel(rect, rx: float, ry: float, label: str = "", post_delay: float = 0.25):
    x, y = rel_to_screen(rect, rx, ry)
    print(f"  [nav] {label} → screen ({x}, {y})")
    _win_click(x, y)
    time.sleep(post_delay)


# ── Navigation actions ────────────────────────────────────────────────────────

class BalatroNav:
    def __init__(self):
        self._rect = None

    def _rect_or_warn(self) -> Optional[Tuple[int,int,int,int]]:
        rect = get_balatro_rect()
        if rect:
            self._rect = rect
        if not self._rect:
            print("  [nav] ERROR: Balatro window not found")
        return self._rect

    def _focus_and_rect(self):
        rect = self._rect_or_warn()
        if rect:
            focus_balatro()
        return rect

    def select_blind(self, blind_type: str = "Small"):
        """Click the Select button on the correct blind card."""
        rect = self._focus_and_rect()
        if not rect:
            return False
        pos = BLIND_SELECT_BTN.get(blind_type, BLIND_SELECT_BTN["Small"])
        click_rel(rect, *pos, label=f"select_blind({blind_type})", post_delay=0.3)
        return True

    def cash_out(self):
        """Click the Cash Out button."""
        rect = self._focus_and_rect()
        if not rect:
            return False
        click_rel(rect, *CASH_OUT_BTN, label="cash_out", post_delay=0.3)
        return True

    def _buy_at(self, rect, rx: float, label_suffix: str):
        """Select a card at rx and click BUY below it."""
        click_rel(rect, rx, SHOP_JOKER_SLOTS[0][1], label=f"shop_select_{label_suffix}", post_delay=0.7)
        click_rel(rect, rx, BUY_BTN_Y,              label=f"shop_buy_{label_suffix}",    post_delay=0.5)

    def leave_shop(self, joker_slots: list = None):
        """
        Buy jokers at the given slot indices, then click Next Round.
        joker_slots: list of slot indices (0=left, 1=right) to buy.

        Special case: if buying BOTH slots, after buying slot 0 the remaining
        joker recenters to a middle position (~rx=0.613), so we click there
        instead of the original slot 1 position.
        """
        rect = self._focus_and_rect()
        if not rect:
            return False

        if joker_slots:
            buy_both = (0 in joker_slots and 1 in joker_slots)

            if 0 in joker_slots:
                self._buy_at(rect, SHOP_JOKER_SLOTS[0][0], "slot1")

            if 1 in joker_slots:
                if buy_both:
                    # After buying slot 1, remaining joker recenters to ~rx=0.613
                    self._buy_at(rect, 0.613, "slot2_recentered")
                else:
                    self._buy_at(rect, SHOP_JOKER_SLOTS[1][0], "slot2")

            time.sleep(0.3)

        click_rel(rect, *NEXT_ROUND_BTN, label="leave_shop(Next Round)", post_delay=0.3)
        return True

    def new_run(self):
        """Click Play Again after game over."""
        rect = self._focus_and_rect()
        if not rect:
            return False
        click_rel(rect, *GAME_OVER_BTN, label="new_run", post_delay=0.3)
        return True
