"""
mp_game.py — Multiplayer Balatro game coordinator.

Wraps two BalatroGame instances with shared seed for deterministic card draws
and independent shops. Implements Attrition mode with our house rule change:
**failing a regular blind ALSO costs a life** (vs the official mod which only
loses lives on PvP).

Game flow per ante:
  1. Both players play Small Blind on same seed (same cards drawn)
     - Player failing loses a life (HOUSE RULE, not official mod)
  2. Both players play Big Blind on same seed (same cards drawn)
     - Same life penalty on failure
  3. PvP Blind — both players play, higher score wins
     - Loser loses a life (official mod rule)
     - Winner gets no bonus life
     - Both players get comeback money ($4 per life lost this round)

Game ends when either player reaches 0 lives. Survivor wins.
If both hit 0 on same round, the one with more antes cleared wins.
If tied, it's a draw.

Notes:
- Both players get IDENTICAL decks (same seed) and see SAME cards each blind
- Shops are INDEPENDENT (different random offerings per player)
- Boss blind effect applies to BOTH players on PvP blind (same restrictions)
"""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional

from .game import BalatroGame, State


DEFAULT_LIVES = 4
COMEBACK_MONEY_PER_LIFE = 4


class MPPhase(Enum):
    """Tracks which blind/phase each player is in."""
    SMALL_BLIND    = auto()
    BIG_BLIND      = auto()
    PVP_BLIND      = auto()
    SHOP           = auto()
    GAME_OVER      = auto()


@dataclass
class PlayerResult:
    """Outcome of a single blind for a player."""
    score: int
    won_blind: bool      # True if score >= target (or won PvP)
    lost_life: bool      # True if this player lost a life this round


@dataclass
class MPGameState:
    """Snapshot of the multiplayer game state."""
    ante: int
    phase: MPPhase
    p1_lives: int
    p2_lives: int
    p1_ante: int         # how far each player has progressed
    p2_ante: int
    game_over: bool
    winner: Optional[int]   # 0=draw, 1=player 1, 2=player 2, None=ongoing


class MultiplayerBalatro:
    """
    Coordinates two BalatroGame instances for head-to-head multiplayer.

    Use the single-player games for most logic, but override the blind-fail
    behavior to charge a life instead of ending the game.
    """

    def __init__(self, seed: Optional[int] = None, lives: int = DEFAULT_LIVES,
                 rng_mode: str = "generic"):
        self._seed = seed
        self._starting_lives = lives
        self.rng_mode = rng_mode

        # Two independent game instances with same seed for deterministic cards.
        # In generic mode shops drift apart via post-init RNG state divergence;
        # in seed mode both games start with identical per-node RNG tables, so
        # identical actions produce identical shops (per-node LuaRandom).
        self.p1_game = BalatroGame(seed=seed, rng_mode=rng_mode)
        self.p2_game = BalatroGame(seed=seed, rng_mode=rng_mode)

        self.p1_lives = lives
        self.p2_lives = lives

        # Track PvP blind scores for each player this round
        self._p1_pvp_score: Optional[int] = None
        self._p2_pvp_score: Optional[int] = None

        self.phase = MPPhase.SMALL_BLIND
        self.current_ante = 1

        # Lives lost this PvP round (for comeback money calc next round)
        self._p1_lives_lost_this_round = 0
        self._p2_lives_lost_this_round = 0

    # ─────────────────────────────────────────────────────────────────────
    # Game state queries
    # ─────────────────────────────────────────────────────────────────────

    @property
    def game_over(self) -> bool:
        return self.p1_lives <= 0 or self.p2_lives <= 0

    @property
    def winner(self) -> Optional[int]:
        """0=draw, 1=player 1, 2=player 2, None=ongoing."""
        if not self.game_over:
            return None
        if self.p1_lives > self.p2_lives:
            return 1
        if self.p2_lives > self.p1_lives:
            return 2
        # Same lives (both hit 0 same round): compare ante progress
        if self.p1_game.ante > self.p2_game.ante:
            return 1
        if self.p2_game.ante > self.p1_game.ante:
            return 2
        return 0  # draw

    def get_state(self) -> MPGameState:
        return MPGameState(
            ante=self.current_ante,
            phase=self.phase,
            p1_lives=self.p1_lives,
            p2_lives=self.p2_lives,
            p1_ante=self.p1_game.ante,
            p2_ante=self.p2_game.ante,
            game_over=self.game_over,
            winner=self.winner,
        )

    def get_player_game(self, player: int) -> BalatroGame:
        """Return the underlying BalatroGame for player 1 or 2."""
        if player == 1:
            return self.p1_game
        elif player == 2:
            return self.p2_game
        raise ValueError(f"player must be 1 or 2, got {player}")

    def get_lives(self, player: int) -> int:
        return self.p1_lives if player == 1 else self.p2_lives

    # ─────────────────────────────────────────────────────────────────────
    # Core mechanics
    # ─────────────────────────────────────────────────────────────────────

    def apply_blind_failure(self, player: int, pvp_loss: bool = False):
        """
        Player failed their blind (regular or PvP). Charge them a life.

        HOUSE RULE: regular blind failures cost a life (official mod doesn't).
        PvP losses always cost a life in both rulesets.
        """
        if player == 1:
            self.p1_lives -= 1
            self._p1_lives_lost_this_round += 1
        elif player == 2:
            self.p2_lives -= 1
            self._p2_lives_lost_this_round += 1
        else:
            raise ValueError(f"player must be 1 or 2, got {player}")

    def resolve_pvp(self, p1_score: int, p2_score: int):
        """
        Compare PvP scores, apply life penalties and comeback money.

        Tie: no lives lost (both players keep playing).
        Else: loser loses one life, gets comeback money.
        """
        self._p1_pvp_score = p1_score
        self._p2_pvp_score = p2_score

        if p1_score > p2_score:
            # P2 loses PvP
            self.apply_blind_failure(2, pvp_loss=True)
            self._award_comeback_money(2)
        elif p2_score > p1_score:
            # P1 loses PvP
            self.apply_blind_failure(1, pvp_loss=True)
            self._award_comeback_money(1)
        # Tie: no lives lost

    def _award_comeback_money(self, player: int):
        """Comeback money awarded to the PvP loser."""
        lives_lost = (self._p1_lives_lost_this_round if player == 1
                      else self._p2_lives_lost_this_round)
        money = COMEBACK_MONEY_PER_LIFE * lives_lost
        game = self.get_player_game(player)
        game.dollars += money

    def should_check_blind_completion(self, player: int) -> bool:
        """
        Check if a player has just completed or failed their current blind.
        Returns True if a resolution check is needed (blind cleared or hands run out).
        """
        game = self.get_player_game(player)
        if game.state == State.SELECTING_HAND:
            if game.chips_scored >= game.current_blind.chips_target:
                return True  # cleared
            if game.hands_left <= 0:
                return True  # failed
        return False

    # ─────────────────────────────────────────────────────────────────────
    # Blind resolution (called after both players finish a blind)
    # ─────────────────────────────────────────────────────────────────────

    def resolve_small_blind(self, p1_cleared: bool, p2_cleared: bool):
        """
        Apply house rule: failing small blind costs a life.
        """
        if not p1_cleared:
            self.apply_blind_failure(1)
        if not p2_cleared:
            self.apply_blind_failure(2)
        if not self.game_over:
            self.phase = MPPhase.BIG_BLIND

    def resolve_big_blind(self, p1_cleared: bool, p2_cleared: bool):
        if not p1_cleared:
            self.apply_blind_failure(1)
        if not p2_cleared:
            self.apply_blind_failure(2)
        if not self.game_over:
            self.phase = MPPhase.PVP_BLIND

    def resolve_pvp_blind(self, p1_score: int, p2_score: int):
        """
        PvP blind resolution. Compare scores, charge loser.

        Note: in our simplified model, we don't require either player to
        clear a chip target — they just compete. In the real mod both must
        clear a target too; we can add that in Phase 2.
        """
        self.resolve_pvp(p1_score, p2_score)
        if not self.game_over:
            self.phase = MPPhase.SHOP
            # Reset counters for next round
            self._p1_lives_lost_this_round = 0
            self._p2_lives_lost_this_round = 0

    def advance_to_next_ante(self):
        """After both players leave shop, advance ante."""
        self.current_ante += 1
        self.phase = MPPhase.SMALL_BLIND
