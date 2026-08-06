"""
balatro_rl/env.py
Gymnasium environment wrapping live Balatro via file-based IPC.

Observation space: Box(119,) float32, all values in [0,1]
Action space:      MultiBinary(9)
  action[0:8] — which hand slots to highlight (1=select)
  action[8]   — 1=play, 0=discard

Reset: waits for the user to start a new run in Balatro.
       Call env.reset() AFTER clicking "New Run" in the game.
"""

import os
import subprocess
import time
import numpy as np
import gymnasium as gym
from gymnasium import spaces

from balatro_rl.state  import read_state, state_to_obs, GameState, OBS_SIZE
from balatro_rl.action import write_action, write_nav, agent_output_to_action, ACTION_FILE

# ── Balatro process management (self-contained, no train.py dependency) ───────
_BALATRO_EXE = os.environ.get(
    "BALATRO_EXE",
    r"C:\Program Files (x86)\Steam\steamapps\common\Balatro\Balatro.exe"
)

def _balatro_restart():
    """Kill and relaunch Balatro. Called automatically on stale state.json."""
    # Kill existing process
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
        print("[BalatroEnv] Balatro relaunched — waiting for mod to initialize...")
        time.sleep(5)  # give it a moment; _wait_for_new_run will wait for state.json
    else:
        print(f"[BalatroEnv] Balatro exe not found: {_BALATRO_EXE}")

# ── Reward constants ─────────────────────────────────────────────────────────
R_BLIND_COMPLETE  =  1.0   # finished a single blind
R_ANTE_COMPLETE   =  3.0   # finished all 3 blinds in an ante
R_WIN             = 10.0   # completed ante 8 — full win
R_LOSE            = -2.0   # ran out of hands on a blind
R_SCORE_PROGRESS  =  0.05  # per 1% of score target gained this step

# Hand-quality bonus given immediately when agent plays (not discards)
# Teaches card selection before score-progress signal kicks in
HAND_BONUS = {
    "high_card":       0.00,
    "pair":            0.10,
    "two_pair":        0.20,
    "three_of_a_kind": 0.35,
    "straight":        0.45,
    "flush":           0.45,
    "full_house":      0.55,
    "four_of_a_kind":  0.70,
    "straight_flush":  0.90,
    "five_of_a_kind":  0.95,
    "flush_house":     1.00,
    "flush_five":      1.10,
}

def _eval_hand(cards) -> str:
    """Classify a list of CardState objects (1-5 cards) into a Balatro hand type."""
    if not cards:
        return "high_card"
    from collections import Counter
    ranks = [c.rank_id for c in cards]
    suits = [c.suit_id for c in cards]
    n = len(cards)

    counts = sorted(Counter(ranks).values(), reverse=True)
    c0 = counts[0] if len(counts) > 0 else 0
    c1 = counts[1] if len(counts) > 1 else 0
    is_flush    = (n == 5 and len(set(suits)) == 1)
    is_straight = (n == 5 and len(set(ranks)) == 5 and (max(ranks) - min(ranks) == 4))
    # Wheel straight: A-2-3-4-5 (rank_ids 12,0,1,2,3)
    if n == 5 and set(ranks) == {12, 0, 1, 2, 3}:
        is_straight = True

    # Balatro-specific hands (checked first — they beat straight flush)
    if c0 == 5:
        return "flush_five" if is_flush else "five_of_a_kind"
    if c0 == 3 and c1 == 2 and is_flush:
        return "flush_house"

    # Standard hands
    if is_straight and is_flush:   return "straight_flush"
    if c0 == 4:                    return "four_of_a_kind"
    if c0 == 3 and c1 == 2:        return "full_house"
    if is_flush:                   return "flush"
    if is_straight:                return "straight"
    if c0 == 3:                    return "three_of_a_kind"
    if c0 == 2 and c1 == 2:        return "two_pair"
    if c0 == 2:                    return "pair"
    return "high_card"

# ── G.STATE constants ────────────────────────────────────────────────────────
GS_SELECTING_HAND = 1
GS_GAME_OVER      = 4
GS_SHOP           = 5
GS_BLIND_SELECT   = 7
GS_ROUND_EVAL     = 8

# In lua_nav mode, Lua handles: blind_select, cash_out, new_run
# Python only handles SHOP: waits 1.5s then writes leave_shop → Lua calls toggle_shop
LUA_NAV_SHOP_DELAY = 2.0   # seconds before Python signals leave_shop (G.shop needs time to build)

# Legacy Python-nav delays (used only if lua_nav mode is disabled)
PYTHON_NAV_DELAY = {
    GS_BLIND_SELECT: 1.2,
    GS_ROUND_EVAL:   2.0,
    GS_SHOP:         1.5,
    GS_GAME_OVER:    5.0,
}

# ── Env ──────────────────────────────────────────────────────────────────────

class BalatroEnv(gym.Env):
    metadata = {"render_modes": []}

    def __init__(self, step_timeout: float = 15.0):
        super().__init__()
        self.step_timeout = step_timeout

        self.observation_space = spaces.Box(
            low=0.0, high=1.0, shape=(OBS_SIZE,), dtype=np.float32
        )
        # 8 card slots + 1 play/discard bit
        self.action_space = spaces.MultiBinary(9)

        self._gs: GameState | None = None
        # Navigation state tracking
        self._nav_state_at: dict[int, float] = {}   # g_state → wall time first seen
        self._nav_last_g   = -1
        # Metadata exposed for logging callbacks
        self._last_seed       = "unknown"
        self._last_ante       = 1
        self._last_score      = 0
        self._last_hand_type  = "unknown"
        self._last_joker_names = []
        self._consecutive_timeouts = 0
        self._last_live_tick = 0.0   # last tick we saw state.json actually update   # current game state
        self._prev_ante   = 0
        self._prev_round  = 0
        self._prev_score  = 0.0
        self._episode_reward = 0.0

    # ── Gymnasium interface ──────────────────────────────────────────────────

    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)

        print("[BalatroEnv] Waiting for new run... (start a run in Balatro)")
        gs = self._wait_for_new_run(timeout=180.0)
        if gs is None:
            raise RuntimeError("Timed out waiting for Balatro to start a new run.")

        self._gs = gs
        self._prev_ante  = gs.ante
        self._prev_round = gs.round
        self._prev_score = gs.score_progress
        self._episode_reward = 0.0

        obs  = state_to_obs(gs)
        info = self._make_info(gs)
        print(f"[BalatroEnv] Run started — Ante {gs.ante}, Blind: {gs.blind_name}")
        return obs, info

    def step(self, action: np.ndarray):
        assert self._gs is not None, "Call reset() before step()"

        # Wait until game is in hand selection phase with cards ready
        gs = self._wait_for_hand_ready(self._gs.timestamp, timeout=self.step_timeout)
        if gs is None:
            # Could be game_over — check the latest state
            latest = read_state(timeout=1.0) or self._gs
            if self._is_terminal(latest):
                obs = state_to_obs(latest)
                self._last_seed  = latest.seed
                self._last_ante  = latest.ante
                self._last_score = int(latest.current_score)
                return obs, R_LOSE, True, False, self._make_info(latest)
            # Genuine timeout (game paused, etc.) — small penalty, continue
            obs = state_to_obs(self._gs)
            return obs, -0.1, False, False, self._make_info(self._gs)
        self._gs = gs

        # Update logging metadata from pre-action state (before any early returns)
        # so _last_hand_type / _last_joker_names are always current regardless of exit path.
        self._last_seed        = gs.seed
        self._last_ante        = gs.ante
        self._last_score       = int(gs.current_score)
        self._last_hand_type   = gs.last_hand_type
        self._last_joker_names = [j.name for j in gs.jokers if j.is_present]

        # Guard: if already terminal, end episode (fast check only — heuristic has debounce in post-action path)
        if self._is_terminal_fast(gs):
            print(f"[term] FAST: event={gs.event} ante={gs.ante}")
            obs = state_to_obs(gs)
            return obs, R_LOSE, True, False, self._make_info(gs)

        card_indices, action_type = agent_output_to_action(
            logits    = action.astype(np.float32) * 2 - 1,
            hand_size = len(gs.hand),
            hands_left    = gs.hands_left,
            discards_left = gs.discards_left,
        )

        # Pre-compute hand quality bonus (only for plays, not discards)
        hand_bonus = 0.0
        if action_type == "play" and card_indices:
            selected_cards = [gs.hand[i] for i in card_indices if i < len(gs.hand)]
            hand_type = _eval_hand(selected_cards)
            hand_bonus = HAND_BONUS.get(hand_type, 0.0)

        # Write action and wait for the game to return to a hand-ready state.
        # Use _wait_for_hand_ready (not _wait_for_state_change) so we skip through
        # HAND_PLAYED (gs=2) and DRAW_TO_HAND (gs=3) intermediate states where
        # G.GAME.chips is not yet finalized — reading chips mid-animation causes
        # false LOST terminal (score looks < target before scoring completes).
        write_action(card_indices, action_type)
        new_gs = self._wait_for_next_hand(gs.timestamp, timeout=self.step_timeout)

        if new_gs is None:
            self._consecutive_timeouts += 1
            if self._consecutive_timeouts >= 5:
                print(f"\n[BalatroEnv] Game unresponsive ({self._consecutive_timeouts} timeouts). "
                      "Is Balatro crashed? Waiting 15s...")
                time.sleep(15.0)
            obs = state_to_obs(gs)
            return obs, -0.1, False, False, self._make_info(gs)
        self._consecutive_timeouts = 0
        self._last_live_tick = new_gs.timestamp

        reward = self._compute_reward(gs, new_gs, action_type) + hand_bonus

        # Fast terminal check (game_over event, ante > 8) — no race risk
        if self._is_terminal_fast(new_gs):
            print(f"[term] FAST: event={new_gs.event} ante={new_gs.ante}")
            terminated = True
        elif new_gs.hands_left <= 0 and new_gs.discards_left <= 0:
            # Re-read after 0.15s: at 32x speed G.GAME.chips may not be finalized
            # yet when SELECTING_HAND first fires after the last hand scored.
            time.sleep(0.15)
            fresh = read_state(timeout=1.0)
            if fresh:
                new_gs = fresh
            if new_gs.current_score < new_gs.score_target:
                # Genuinely lost — terminate immediately.
                print(f"[term] LOST: h={new_gs.hands_left} d={new_gs.discards_left}"
                      f" score={new_gs.current_score:.0f} target={new_gs.score_target:.0f}"
                      f" blind={new_gs.blind_name} ante={new_gs.ante} gs={new_gs.game_state}")
                terminated = True
            else:
                # Score met — WON the blind. Debounce 0.65s so the Lua WON watchdog
                # (0.5s delay) has time to advance game to ROUND_EVAL/SHOP before we check.
                time.sleep(0.65)
                fresh = read_state(timeout=1.0)
                if fresh:
                    new_gs = fresh
                if self._is_terminal(new_gs):
                    print(f"[term] WON-DEBOUNCE-TERMINAL: event={new_gs.event} ante={new_gs.ante}"
                          f" gs={new_gs.game_state} h={new_gs.hands_left} d={new_gs.discards_left}"
                          f" score={new_gs.current_score:.0f} target={new_gs.score_target:.0f}")
                    terminated = True
                else:
                    terminated = False
        else:
            terminated = False
        truncated = False

        self._gs          = new_gs
        self._prev_ante   = new_gs.ante
        self._prev_round  = new_gs.round
        self._prev_score  = new_gs.score_progress
        self._episode_reward += reward

        obs  = state_to_obs(new_gs)
        info = self._make_info(new_gs)

        # Update metadata for logging callbacks
        self._last_seed        = new_gs.seed
        self._last_ante        = new_gs.ante
        self._last_score       = int(new_gs.current_score)
        self._last_hand_type   = new_gs.last_hand_type
        self._last_joker_names = [j.name for j in new_gs.jokers]

        if terminated:
            won = new_gs.ante > 8 or (new_gs.ante == 8 and new_gs.current_score >= new_gs.score_target)
            print(f"[BalatroEnv] Episode {'WON' if won else 'LOST'} | "
                  f"Ante {new_gs.ante} | Total reward: {self._episode_reward:.2f}")

        return obs, reward, terminated, truncated, info

    def render(self):
        pass  # rendering is Balatro itself

    def close(self):
        # Clean up any pending action file
        if ACTION_FILE.exists():
            ACTION_FILE.unlink()

    # ── Navigation ───────────────────────────────────────────────────────────

    @property
    def _lua_nav(self) -> bool:
        """True if Lua is handling nav (read from last known game config)."""
        if self._gs is None:
            return True  # assume lua_nav by default
        return self._gs.config.get("lua_nav", True)

    def _handle_nav(self, gs: GameState) -> bool:
        """
        Handle nav screens.
        In lua_nav mode: Lua handles blind_select/cash_out/new_run automatically.
        Python only handles SHOP: waits LUA_NAV_SHOP_DELAY then writes leave_shop.
        Returns True if we're still in a nav transition (caller should keep waiting).
        """
        g = gs.game_state

        # Track when we first entered this state
        if g != self._nav_last_g:
            self._nav_state_at.clear()
            self._nav_state_at[g] = time.time()
            self._nav_last_g = g

        lua_nav = self._gs.config.get("lua_nav", True) if self._gs else True

        if lua_nav:
            # Lua handles all nav: blind_select, cash_out, shop, new_run
            # Python just waits for SELECTING_HAND to come back
            if g in (GS_BLIND_SELECT, GS_ROUND_EVAL, GS_SHOP, GS_GAME_OVER):
                return True
        else:
            # Legacy Python-nav mode: send all nav actions
            delay = PYTHON_NAV_DELAY.get(g)
            if delay is None:
                return False
            if time.time() - self._nav_state_at.get(g, time.time()) < delay:
                return True
            self._nav_state_at.pop(g, None)
            nav_map = {
                GS_BLIND_SELECT: "select_blind",
                GS_ROUND_EVAL:   "cash_out",
                GS_SHOP:         "leave_shop",
                GS_GAME_OVER:    "new_run",
            }
            action = nav_map.get(g)
            if action:
                write_nav(action)
            return True

        return False

    # ── Reward ───────────────────────────────────────────────────────────────

    def _compute_reward(self, old: GameState, new: GameState, action_type: str) -> float:
        reward = 0.0

        # Score progress within a blind
        delta_progress = new.score_progress - old.score_progress
        if delta_progress > 0:
            reward += R_SCORE_PROGRESS * delta_progress * 100  # per % gained

        # Completed a blind (round advanced)
        if new.round > old.round and new.ante == old.ante:
            reward += R_BLIND_COMPLETE

        # Completed an ante (ante advanced)
        if new.ante > old.ante:
            reward += R_ANTE_COMPLETE

        # Won the run
        if new.ante > 8 or (new.ante == 8 and new.current_score >= new.score_target
                             and old.current_score < old.score_target):
            reward += R_WIN

        # Lost (no hands left, score not met)
        if new.hands_left == 0 and new.current_score < new.score_target:
            reward += R_LOSE

        return reward

    def _is_terminal_fast(self, gs: GameState) -> bool:
        """Fast checks only — no race condition risk."""
        if gs.event == "game_over":
            return True
        if gs.ante > 8:
            return True
        return False

    def _is_terminal(self, gs: GameState) -> bool:
        """Full terminal check including heuristic (call after debounce)."""
        if self._is_terminal_fast(gs):
            return True
        # Heuristic: out of hands AND discards AND score not met.
        # current_score is now G.GAME.chips (accumulated blind total).
        # Requires score > 0 to avoid false positives when score resets at blind start.
        if (gs.hands_left <= 0
                and gs.discards_left <= 0
                and gs.current_score >= 0   # always true, kept for clarity
                and gs.current_score < gs.score_target
                and gs.game_state not in (GS_ROUND_EVAL, GS_SHOP, GS_BLIND_SELECT)):
            return True
        return False

    # ── Waiting helpers ──────────────────────────────────────────────────────

    def _wait_for_state_change(self, old_ts: float, timeout: float) -> GameState | None:
        """Poll until state.json has a newer tick than old_ts."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            gs = read_state(timeout=1.0)
            if gs and gs.timestamp > old_ts and gs.event not in ("mod_loaded",):
                return gs
            time.sleep(0.05)
        return None

    def _wait_for_hand_ready(self, old_ts: float, timeout: float) -> GameState | None:
        """
        Pre-action: return current SELECTING_HAND state immediately (or wait briefly).
        Returns the current state even if tick == old_ts — used to snapshot state before acting.
        """
        HAND_EVENTS = ("selecting_hand", "hand_drawn")
        deadline = time.time() + timeout
        while time.time() < deadline:
            gs = read_state(timeout=1.0)
            if gs is None:
                time.sleep(0.1)
                continue
            if gs.event == "game_over":
                return gs
            if gs.hand and gs.event in HAND_EVENTS:
                return gs   # return immediately — pre-action snapshot
            self._handle_nav(gs)
            time.sleep(0.05)
        return None

    def _wait_for_next_hand(self, old_ts: float, timeout: float) -> GameState | None:
        """
        Post-action: wait for the NEXT actionable state after a play/discard.
        Requires tick > old_ts (genuinely new state).
        Skips intermediate states: HAND_PLAYED (gs=2), DRAW_TO_HAND (gs=3),
        and nav states (SHOP, BLIND_SELECT, ROUND_EVAL) that Lua handles autonomously.
        Only returns SELECTING_HAND or game_over.
        """
        HAND_EVENTS = ("selecting_hand", "hand_drawn")
        deadline = time.time() + timeout
        while time.time() < deadline:
            gs = read_state(timeout=1.0)
            if gs is None:
                time.sleep(0.1)
                continue
            if gs.timestamp <= old_ts:
                time.sleep(0.05)
                continue
            # New state (tick advanced)
            if gs.event == "game_over":
                return gs
            if gs.hand and gs.event in HAND_EVENTS:
                return gs
            # Skip: HAND_PLAYED, DRAW_TO_HAND, SHOP, BLIND_SELECT, ROUND_EVAL
            time.sleep(0.05)
        return None

    def _wait_for_new_run(self, timeout: float) -> GameState | None:
        """
        Wait for a fresh run at ante 1 with a hand dealt.
        In lua_nav mode: Lua auto-restarts after game over — just wait.
        In python-nav mode: handle nav (sends new_run action on game_over).
        """
        # Capture baseline mtime from current state.json so we can detect
        # any NEW write (even if the new run already started before reset() was called).
        # Lua writes state.json every poll cycle in SELECTING_HAND, so a fresh
        # write will arrive within ~100ms and will have mtime > baseline.
        current = read_state(timeout=5.0)
        baseline_mtime = current.file_mtime if current else 0.0

        STALE_SECS = 45.0   # restart Balatro if state.json hasn't updated in this long
        last_seen_mtime  = baseline_mtime
        last_mtime_wall  = time.time()

        deadline = time.time() + timeout
        while time.time() < deadline:
            gs = read_state(timeout=1.0)
            if gs is None:
                time.sleep(0.3)
                continue

            # Track last time state.json was updated; restart Balatro if stale
            if gs.file_mtime != last_seen_mtime:
                last_seen_mtime = gs.file_mtime
                last_mtime_wall = time.time()
            elif time.time() - last_mtime_wall > STALE_SECS:
                print(f"\n[BalatroEnv] state.json stale for {STALE_SECS:.0f}s — Balatro crashed. Restarting...")
                try:
                    _balatro_restart()
                except Exception as e:
                    print(f"[BalatroEnv] Auto-restart failed: {e}. Restart Balatro manually.")
                last_mtime_wall = time.time()
                last_seen_mtime = 0.0   # force mtime check to reset

            # Accept any playable SELECTING_HAND state written after baseline.
            # Filter out stuck states (0h/0d/score unmet) which look like valid runs.
            is_stuck = (gs.hands_left <= 0 and gs.discards_left <= 0
                        and gs.current_score < gs.score_target)
            if (gs.hand
                    and gs.event in ("hand_drawn", "selecting_hand")
                    and gs.hands_left > 0
                    and gs.ante == 1                    # must be a true new run
                    and gs.blind_name == "Small Blind"  # must be first blind (not mid-run)
                    and not is_stuck
                    and gs.file_mtime > baseline_mtime):
                return gs
            # If game is stuck (0h/0d, score unmet, SELECTING_HAND) — kick a new run
            if (gs.hands_left <= 0 and gs.discards_left <= 0
                    and gs.current_score < gs.score_target
                    and gs.game_state == GS_SELECTING_HAND):
                write_nav("new_run")
            # If game is mid-run (hands > 0) but past Small Blind ante 1 — Python called
            # reset() while Lua kept playing. Restart Balatro to get back to a fresh state.
            if (gs.hands_left > 0
                    and gs.game_state == GS_SELECTING_HAND
                    and not (gs.ante == 1 and gs.blind_name == "Small Blind")
                    and time.time() - last_mtime_wall > 3.0):  # only after 3s (not on first read)
                print(f"[BalatroEnv] Mid-run deadlock (ante={gs.ante} blind={gs.blind_name}) — restarting Balatro")
                try:
                    _balatro_restart()
                except Exception as e:
                    print(f"[BalatroEnv] Restart failed: {e}")
                last_mtime_wall = time.time()
                last_seen_mtime = 0.0
            lua_nav = gs.config.get("lua_nav", True)
            if not lua_nav:
                self._handle_nav(gs)
            time.sleep(0.1)
        return None

    # ── Info dict ────────────────────────────────────────────────────────────

    def _make_info(self, gs: GameState) -> dict:
        return {
            "ante":          gs.ante,
            "round":         gs.round,
            "blind_name":    gs.blind_name,
            "score":         gs.current_score,
            "score_target":  gs.score_target,
            "hands_left":    gs.hands_left,
            "discards_left": gs.discards_left,
            "money":         gs.money,
            "jokers":        [j.name for j in gs.jokers],
        }
