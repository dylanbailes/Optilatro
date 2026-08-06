"""
test_deck_persistence.py — Regression tests for the persistent-deck fix.

The run deck is created once and carries over across blinds (real Balatro
behavior). Cards played or discarded in a round return to the deck at the
start of the next blind; permanently destroyed cards (Hanged Man, Immolate,
spectral destroy effects) leave the run for good.
"""
from __future__ import annotations

from balatro_sim.game import BalatroGame, State, BlindInfo
from balatro_sim.consumables import apply_tarot


def _play_and_clear_blind(game: BalatroGame) -> None:
    """Force-clear the current blind, run the shop, advance to the next blind."""
    game.chips_scored = game.current_blind.chips_target
    game.state = State.ROUND_EVAL
    game.step({"type": "cash_out"})   # any action is fine in ROUND_EVAL
    assert game.state == State.SHOP
    game.step({"type": "leave_shop"})
    assert game.state == State.BLIND_SELECT


class TestDeckPersistence:
    def test_deck_size_constant_across_blind(self):
        """Clearing a blind must not reset the deck: pool stays 52 cards."""
        g = BalatroGame(seed=42)
        g.step({"type": "play_blind"})
        assert len(g.hand) == 8
        g.step({"type": "play", "cards": [0, 1]})
        _play_and_clear_blind(g)
        g.step({"type": "play_blind"})
        assert len(g.hand) == 8
        assert len(g.deck) + len(g.hand) == 52  # nothing destroyed yet

    def test_played_cards_return_at_next_blind(self):
        """Cards played in blind 1 must be back in the pool for blind 2."""
        g = BalatroGame(seed=42)
        g.step({"type": "play_blind"})
        played = g.hand[0]
        g.step({"type": "play", "cards": [0]})
        _play_and_clear_blind(g)
        g.step({"type": "play_blind"})
        assert played in g.deck + g.hand

    def test_discarded_cards_return_at_next_blind(self):
        """Cards discarded in blind 1 must be back in the pool for blind 2."""
        g = BalatroGame(seed=42)
        g.step({"type": "play_blind"})
        g.step({"type": "play", "cards": [0]})   # keep the rest, then discard one
        discarded = g.hand[0]
        g.step({"type": "discard", "cards": [0]})
        _play_and_clear_blind(g)
        g.step({"type": "play_blind"})
        assert discarded in g.deck + g.hand

    def test_enhanced_card_persists_across_blinds(self):
        """A tarot-enhanced held card returns with its enhancement intact."""
        g = BalatroGame(seed=42)
        g.step({"type": "play_blind"})
        g.hand[0].enhancement = "Mult"   # simulate a tarot used on a held card
        g.step({"type": "play", "cards": [0, 1]})
        _play_and_clear_blind(g)
        g.step({"type": "play_blind"})
        pool = g.deck + g.hand
        assert sum(1 for c in pool if c.enhancement == "Mult") == 1

    def test_destroyed_cards_do_not_return(self):
        """Hanged Man destroys 2 held cards permanently (pool shrinks and stays shrunk)."""
        g = BalatroGame(seed=42)
        g.step({"type": "play_blind"})
        destroyed_0 = g.hand[0]
        destroyed_1 = g.hand[1]
        assert apply_tarot(g, "c_hanged_man", [0, 1]) is True
        assert len(g.deck) + len(g.hand) == 50  # 2 permanently gone
        _play_and_clear_blind(g)
        g.step({"type": "play_blind"})
        pool = g.deck + g.hand
        assert len(pool) == 50                  # still gone next blind
        assert destroyed_0 not in pool
        assert destroyed_1 not in pool

    def test_played_cards_not_redrawn_mid_round(self):
        """Within a round, played cards leave the draw pile (no instant redraw)."""
        g = BalatroGame(seed=42)
        g.step({"type": "play_blind"})
        played = g.hand[0]
        g.step({"type": "play", "cards": [0]})
        # The card is gone from hand and deck for the rest of this round
        assert played not in g.deck
        assert played not in g.hand

    def test_boss_debuffs_do_not_persist_via_spent(self):
        """A card debuffed and then played under a boss blind returns un-debuffed."""
        g = BalatroGame(seed=42)
        # Force The Goad as the boss (debuffs all Spades, including played ones)
        g.blind_idx = 2
        g.current_blind = BlindInfo("Test bl_goad", "Boss", 1000, is_boss=True, boss_key="bl_goad")
        g.state = State.BLIND_SELECT
        g.step({"type": "play_blind"})

        # Pull a debuffed spade into the hand (deck+hand are debuffed at blind start)
        spade = next(c for c in g.hand + g.deck if c.suit == "Spades")
        if spade not in g.hand:
            g.deck.remove(spade)
            g.hand.append(spade)
        assert spade.debuffed

        g.step({"type": "play", "cards": [g.hand.index(spade)]})
        assert spade not in g.hand          # played this round (sits in spent)

        # Beat the boss blind and advance to the next blind
        g.chips_scored = g.current_blind.chips_target
        g.state = State.ROUND_EVAL
        g.step({"type": "cash_out"})
        g.step({"type": "leave_shop"})
        g.step({"type": "play_blind"})

        # The spade is back in the pool and no longer debuffed
        assert spade in g.deck + g.hand
        assert not spade.debuffed
