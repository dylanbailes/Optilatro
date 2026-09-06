"""test_scaling_acceleration.py — Regression tests for R3 scaling joker acceleration.

Verifies:
- Ride the Bus plays non-face cards on safe blinds and never plays scoring face cards.
- Green Joker plays safe hands instead of discarding when safe (banking +1 Mult).
- Wee Joker banks 2s, prioritizing Hanging Chad index 0 positioning.
- Square Joker banks 4-scoring-card hands.
- Spare Trousers banks Two Pair / Full House hands.
- Scaling is completely suppressed when hands_left == 1 and under banned bosses.
- Strict Ante 1 safety isolation (requires P(clear) >= 0.99).
"""
from __future__ import annotations

import pytest

from balatro_sim.card import Card
from balatro_sim.game import BalatroGame, State
from balatro_sim.jokers.base import JokerInstance
from balatro_sim.agent_v9 import scored_plays
from balatro_sim import agent_v10 as v10


def _setup_game(hand_cards, jokers=(), hands_left=3, discards_left=3, target=300, ante=2, boss=""):
    g = BalatroGame(seed=42, rng_mode="seed")
    g.reset()
    g.ante = ante
    if g.state != State.SELECTING_HAND:
        g.state = State.BLIND_SELECT
        g.step({"type": "play_blind"})
    g.hand = [Card(rank=r, suit=s) for s, r in hand_cards]
    g.hands_left = hands_left
    g.discards_left = discards_left
    g.current_blind.chips_target = target
    g.chips_scored = 0
    g.current_blind.boss_key = boss
    g.jokers = [JokerInstance(k, game=g) for k in jokers]
    return g


class TestScalingAcceleration:
    def test_scaling_suppressed_when_hands_left_one(self):
        """Scaling must NEVER trigger when hands_left < 2."""
        # 4 Kings (clears easily) + 2 of Hearts, holding Wee Joker
        g = _setup_game(
            [("Spades", 13), ("Hearts", 13), ("Clubs", 13), ("Diamonds", 13), ("Hearts", 2)],
            jokers=["j_wee"],
            hands_left=1,
            target=100,
        )
        plays = scored_plays(g)
        p_clear = 1.0
        act = v10._find_scaling_action(g, g.hand, plays, p_clear)
        assert act is None, "Should not attempt scaling on last hand"

    def test_scaling_banned_on_dangerous_bosses(self):
        """Scaling must be suppressed on all banned bosses."""
        for boss in ("bl_needle", "bl_mouth", "bl_eye", "bl_grim", "bl_hook", "bl_tooth", "bl_pillar", "bl_psychic"):
            g = _setup_game(
                [("Spades", 14), ("Hearts", 14), ("Clubs", 14), ("Diamonds", 14), ("Hearts", 2)],
                jokers=["j_green_joker", "j_wee"],
                hands_left=3,
                target=100,
                boss=boss,
            )
            plays = scored_plays(g)
            act = v10._find_scaling_action(g, g.hand, plays, 1.0)
            assert act is None, f"Scaling should be suppressed under banned boss {boss}"

    def test_ride_the_bus_never_plays_scoring_face(self):
        """Ride the Bus must NEVER play scoring face cards during scaling."""
        # Hand with 4 Jacks (clears knockout) and non-face cards: 2H, 3C, 4D
        g = _setup_game(
            [
                ("Spades", 11), ("Hearts", 11), ("Clubs", 11), ("Diamonds", 11),  # Jacks (knockout)
                ("Hearts", 2), ("Clubs", 3), ("Diamonds", 4), ("Spades", 5)       # Non-face safe
            ],
            jokers=["j_ride_the_bus"],
            hands_left=3,
            target=200,
        )
        plays = scored_plays(g)
        act = v10._find_scaling_action(g, g.hand, plays, 1.0)
        assert act is not None
        played_cards = [g.hand[i] for i in act["cards"]]
        assert not any(c.is_face_card for c in played_cards), "Ride the bus scaling played a face card!"

    def test_green_joker_suppresses_discard_when_safe(self):
        """Green Joker suppresses discard during safe blinds to avoid -1 Mult penalty."""
        # Weak hand that would normally discard, but safe clear prob
        g = _setup_game(
            [("Spades", 2), ("Hearts", 4), ("Clubs", 6), ("Diamonds", 8), ("Spades", 10)],
            jokers=["j_green_joker"],
            hands_left=3,
            discards_left=2,
            target=50,
        )
        plays = scored_plays(g)
        # Call _tier1_survive with p_clear=0.99
        act = v10._tier1_survive(g, plays, p_clear=0.99)
        assert act["type"] == "play", f"Green joker should play instead of discarding, got {act}"

    def test_wee_joker_prioritizes_twos_with_chad_at_index_zero(self):
        """Wee Joker prioritizes rank 2 and puts rank 2 at index 0 when Hanging Chad is owned."""
        # Clearing 4 Aces + non-clearing 2 of Hearts, 8 of Clubs
        g = _setup_game(
            [
                ("Spades", 14), ("Hearts", 14), ("Clubs", 14), ("Diamonds", 14),
                ("Hearts", 2), ("Clubs", 8)
            ],
            jokers=["j_wee", "j_hanging_chad"],
            hands_left=3,
            target=300,
        )
        plays = scored_plays(g)
        act = v10._find_scaling_action(g, g.hand, plays, 1.0)
        assert act is not None
        first_card_idx = act["cards"][0]
        assert g.hand[first_card_idx].rank == 2, "Rank 2 card should be placed at index 0 for Hanging Chad"

    def test_square_joker_banks_four_scoring_cards(self):
        """Square Joker banks 4-scoring-card hands (e.g. Two Pair)."""
        # Knockout Trips + Two Pair (3s and 4s) outside knockout
        g = _setup_game(
            [
                ("Spades", 14), ("Hearts", 14), ("Clubs", 14),
                ("Hearts", 3), ("Diamonds", 3), ("Clubs", 4), ("Spades", 4)
            ],
            jokers=["j_square_joker"],
            hands_left=3,
            target=150,
        )
        plays = scored_plays(g)
        act = v10._find_scaling_action(g, g.hand, plays, 1.0)
        assert act is not None
        played_cards = [g.hand[i] for i in act["cards"]]
        assert len(played_cards) == 4, f"Square joker should play 4 cards, got {len(played_cards)}"

    def test_spare_trousers_banks_two_pair(self):
        """Spare Trousers banks Two Pair when safe."""
        g = _setup_game(
            [
                ("Spades", 14), ("Hearts", 14), ("Clubs", 14),
                ("Hearts", 5), ("Diamonds", 5), ("Clubs", 6), ("Spades", 6)
            ],
            jokers=["j_spare_trousers"],
            hands_left=3,
            target=175,
        )
        plays = scored_plays(g)
        act = v10._find_scaling_action(g, g.hand, plays, 1.0)
        assert act is not None
        played_cards = [g.hand[i] for i in act["cards"]]
        from balatro_sim.hand_eval import evaluate_hand
        ht, _ = evaluate_hand(played_cards)
        assert ht in ("Two Pair", "Full House"), f"Spare trousers should play Two Pair, got {ht}"

    def test_tier_s1_disjoint_knockout_preservation(self):
        """Tier S1 preserves knockout combo K completely in hand."""
        # Cards 0, 1, 2, 3 clear the blind. Cards 4, 5 are non-clearing.
        g = _setup_game(
            [
                ("Spades", 14), ("Hearts", 14), ("Clubs", 14), ("Diamonds", 14),
                ("Hearts", 2), ("Clubs", 3)
            ],
            jokers=["j_green_joker"],
            hands_left=3,
            target=300,
        )
        plays = scored_plays(g)
        clearing_combo = set(plays[0][1])
        act = v10._find_scaling_action(g, g.hand, plays, 1.0)
        assert act is not None
        played_indices = set(act["cards"])
        assert played_indices.isdisjoint(clearing_combo), "Scaling play overlapped with knockout combo K!"

    def test_ante_1_isolation(self):
        """Ante 1 scaling is strictly disallowed regardless of p_clear or hand strength."""
        g = _setup_game(
            [
                ("Spades", 14), ("Hearts", 14), ("Clubs", 14), ("Diamonds", 14),
                ("Hearts", 2), ("Clubs", 3)
            ],
            jokers=["j_green_joker"],
            hands_left=3,
            target=300,
            ante=1,
        )
        plays = scored_plays(g)
        act = v10._find_scaling_action(g, g.hand, plays, 1.0)
        assert act is None, "Ante 1 must strictly suppress scaling acceleration"

    def test_scaling_suppressed_when_hands_left_two(self):
        """Scaling must be suppressed when hands_left < 3 (enforce >= 2 hands remain after play)."""
        g = _setup_game(
            [
                ("Spades", 14), ("Hearts", 14), ("Clubs", 14), ("Diamonds", 14),
                ("Hearts", 2), ("Clubs", 3)
            ],
            jokers=["j_green_joker"],
            hands_left=2,
            target=300,
            ante=2,
        )
        plays = scored_plays(g)
        act = v10._find_scaling_action(g, g.hand, plays, 1.0)
        assert act is None, "Scaling must be suppressed when hands_left < 3"

    def test_scaling_capped_to_one_play_per_blind(self):
        """Scaling acceleration is capped to at most 1 play per blind (chips_scored == 0)."""
        g = _setup_game(
            [
                ("Spades", 14), ("Hearts", 14), ("Clubs", 14), ("Diamonds", 14),
                ("Hearts", 2), ("Clubs", 3)
            ],
            jokers=["j_green_joker"],
            hands_left=3,
            target=300,
            ante=2,
        )
        g.chips_scored = 15
        plays = scored_plays(g)
        act = v10._find_scaling_action(g, g.hand, plays, 1.0)
        assert act is None, "Scaling must be suppressed when chips have already been scored this blind"

    def test_tier2_value_rejects_discard_when_zero_discards_left(self):
        """tier2_value must NEVER return a discard action when discards_left == 0 (deadlock prevention)."""
        g = _setup_game(
            [
                ("Spades", 13), ("Hearts", 12), ("Clubs", 11),
                ("Diamonds", 10), ("Hearts", 9), ("Clubs", 8), ("Spades", 7), ("Hearts", 6)
            ],
            jokers=["j_faceless"],
            hands_left=3,
            discards_left=0,
            target=50,
            ante=2,
        )
        plays = scored_plays(g)
        ts = v10._compute_type_scores(g, plays)
        act = v10.tier2_value(g, plays, ts)
        if act is not None:
            assert act.get("type") != "discard", "tier2_value returned discard when discards_left == 0!"
