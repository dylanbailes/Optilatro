"""
test_boss_effects.py — Regression tests for the implemented boss blind effects:

  The Wall (4x base), Violet Vessel (6x base), The Mark (face cards face-down),
  Verdant Leaf (all debuffed until a joker is sold), The Pillar (cards played
  earlier this ante are debuffed), The Ox (most-played hand sets money to $0),
  Cerulean Bell (forced card),  Amber Acorn (jokers flipped + shuffled),  Crimson Heart (one joker disabled per hand), The Club (all Clubs debuffed),
  The Wheel (1-in-7 cards drawn face down), The House (opening hand face down),
  The Arm (permanently decrease played hand level by 1), plus the corrected
  The Flint (halve base chips+mult) and The Eye / The Mouth
  (a disallowed hand still plays and wastes a hand but scores 0).

Effects verified against the Balatro wiki (balatrowiki.org/w/Blinds_and_Antes).
"""
from __future__ import annotations

from balatro_sim.game import BalatroGame, State, BlindInfo
from balatro_sim.seed_rng import node_boss, DECK_SHUFFLE_NODE, WHEEL_NODE
from balatro_sim.card import Card
from balatro_sim.constants import BLIND_CHIPS, HAND_BASE
from balatro_sim.jokers.base import JokerInstance
from balatro_sim.scoring import score_hand
from balatro_sim.hand_eval import evaluate_hand


def _force_boss(game: BalatroGame, boss_key: str) -> BlindInfo:
    """Set the next boss blind to a specific key and prepare it."""
    game.rng.node(node_boss()).choice = lambda seq: boss_key
    game._prepare_next_blind()
    return game.current_blind


def _setup_boss(game: BalatroGame, boss_key: str, chips_target: int = 1000):
    """Enter SELECTING_HAND with a specific boss blind active."""
    game.blind_idx = 2
    game.current_blind = BlindInfo(
        name=f"Test {boss_key}", kind="Boss",
        chips_target=chips_target, is_boss=True, boss_key=boss_key,
    )
    game.state = State.BLIND_SELECT
    game.step({"type": "play_blind"})
    return game


def _craft_hand(game: BalatroGame):
    """Replace the hand with a fixed 8-card set (High Card + a Pair + junk).
    Empty the deck so plays don't refill the hand and shuffle index positions."""
    game.hand = [
        Card(rank=2, suit="Spades"),
        Card(rank=7, suit="Hearts"), Card(rank=7, suit="Clubs"),
        Card(rank=3, suit="Diamonds"), Card(rank=4, suit="Spades"),
        Card(rank=5, suit="Clubs"), Card(rank=6, suit="Hearts"),
        Card(rank=8, suit="Diamonds"),
    ]
    game.deck = []


def _planet_levels():
    return {h: 1 for h in HAND_BASE.keys()}


# ── Score scaling bosses ──────────────────────────────────────────────────────

class TestLargeBlindScaling:
    def test_wall_4x_base_target(self):
        g = BalatroGame(seed=1)
        g.ante = 2
        g.blind_idx = 2
        blind = _force_boss(g, "bl_wall")
        assert blind.chips_target == BLIND_CHIPS[2][0] * 4

    def test_violet_vessel_6x_base_target(self):
        g = BalatroGame(seed=1)
        g.ante = 8
        g.blind_idx = 2
        blind = _force_boss(g, "bl_violet")
        assert blind.chips_target == BLIND_CHIPS[8][0] * 6

    def test_normal_boss_still_2x_base(self):
        g = BalatroGame(seed=1)
        g.ante = 2
        g.blind_idx = 2
        blind = _force_boss(g, "bl_hook")
        assert blind.chips_target == BLIND_CHIPS[2][2]


# ── The Flint (halve base chips AND mult, not final score) ───────────────────

class TestFlint:
    def test_score_hand_half_base(self):
        cards = [Card(rank=14, suit="Spades")]      # High Card Ace: (5,1)+11
        ht, sc = evaluate_hand(cards)
        kwargs = dict(
            scoring_cards=sc, all_cards=cards, hand_type=ht, jokers=[],
            planet_levels=_planet_levels(), hands_left=3, discards_left=3,
            dollars=10, ante=1, deck_remaining=44,
        )
        full, _ = score_hand(**kwargs)
        half, _ = score_hand(**kwargs, half_base=True)
        # full: (5+11)*1 = 16; half: (5//2+11)*(1//2) = 13*0 = 0
        assert full == 16
        assert half == 0

    def test_flint_in_game_zeroes_bare_high_card(self):
        g = BalatroGame(seed=42)
        _setup_boss(g, "bl_flint")
        g.step({"type": "play", "cards": [0]})
        assert g.chips_scored == 0


# ── The Mark (face cards drawn face down) ────────────────────────────────────

class TestMark:
    def test_face_cards_flipped_on_draw(self):
        g = BalatroGame(seed=42)
        g.blind_idx = 2
        g.current_blind = BlindInfo("mark", "Boss", 1000, is_boss=True, boss_key="bl_mark")
        g.state = State.BLIND_SELECT
        # Deterministically draw a face card: append it (deck is popped from the
        # END in _draw_to_full, so appending puts it first in the draw order)
        face = Card(rank=13, suit="Hearts")
        g.deck.append(face)
        g.rng.node(DECK_SHUFFLE_NODE).shuffle = lambda seq: None
        g.step({"type": "play_blind"})
        assert face in g.hand
        assert face.flipped
        assert all(c.flipped for c in g.hand if c.is_face_card)
        assert all(not c.flipped for c in g.hand if not c.is_face_card)

    def test_mark_unflips_after_boss_ends(self):
        g = BalatroGame(seed=42)
        _setup_boss(g, "bl_mark")
        g.chips_scored = g.current_blind.chips_target
        g.state = State.ROUND_EVAL
        g.step({"type": "noop"})          # end round → cleanup runs
        assert not any(c.flipped for c in g.hand + g.deck + g.spent)

    def test_mark_masks_face_cards_in_obs(self):
        from balatro_sim.env_sim import BalatroSimEnv, CARD_FEATURES, N_HAND_SLOTS, GAME_SCALARS
        env = BalatroSimEnv(seed=42)
        env.reset()
        g = env.game
        g.ante = 1
        g.blind_idx = 2
        _force_boss(g, "bl_mark")
        face = Card(rank=12, suit="Spades")
        g.deck.append(face)
        g.rng.node(DECK_SHUFFLE_NODE).shuffle = lambda seq: None
        g.step({"type": "play_blind"})
        assert face in g.hand and face.flipped
        obs = env._encode_obs()
        base = GAME_SCALARS
        seen_flipped = False
        for slot in range(N_HAND_SLOTS):
            if slot < len(g.hand):
                c = g.hand[slot]
                start = base + slot * CARD_FEATURES
                if c.flipped:
                    seen_flipped = True
                    assert obs[start:start+25].sum() == 0.0   # identity hidden
                    assert obs[start+25] == 1.0               # but present
                else:
                    assert obs[start+25] == 1.0
        assert seen_flipped


# ── Verdant Leaf (all debuffed until a joker is sold) ────────────────────────

class TestVerdant:
    def test_all_cards_debuffed(self):
        g = BalatroGame(seed=42)
        _setup_boss(g, "bl_verdant")
        assert all(c.debuffed for c in g.hand + g.deck)

    def test_selling_joker_lifts_debuff(self):
        g = BalatroGame(seed=42)
        _setup_boss(g, "bl_verdant")
        g.jokers.append(JokerInstance("j_joker"))
        g.step({"type": "sell_joker", "joker_idx": 0})
        assert not g.verdant_debuff
        assert not any(c.debuffed for c in g.hand + g.deck)

    def test_sell_mid_blind_only_under_verdant(self):
        g = BalatroGame(seed=42)
        _setup_boss(g, "bl_needle")
        g.jokers.append(JokerInstance("j_joker"))
        n = len(g.jokers)
        g.step({"type": "sell_joker", "joker_idx": 0})
        assert len(g.jokers) == n   # sell rejected outside Verdant Leaf


# ── The Pillar (cards played earlier this ante are debuffed) ─────────────────

class TestPillar:
    def test_played_cards_tracked_and_debuffed(self):
        g = BalatroGame(seed=42)
        g.step({"type": "play_blind"})
        played = g.hand[0]
        g.step({"type": "play", "cards": [0]})
        assert played.id in g.ante_played_ids

        # Start the Pillar blind — the previously played card is debuffed
        g.blind_idx = 2
        g.current_blind = BlindInfo("pillar", "Boss", 1000, is_boss=True, boss_key="bl_pillar")
        g.state = State.BLIND_SELECT
        g.step({"type": "play_blind"})
        assert played.debuffed
        assert played in g.hand or played in g.deck

    def test_pillar_cleanup_after_boss(self):
        g = BalatroGame(seed=42)
        _setup_boss(g, "bl_pillar")
        # put a "previously played" card into the hand via the set
        g.ante_played_ids.add(g.hand[0].id)
        g._apply_boss_start("bl_pillar")   # re-run start effect
        assert g.hand[0].debuffed
        g._undo_boss_debuffs("bl_pillar")
        assert not any(c.debuffed for c in g.hand + g.deck + g.spent)

    def test_ante_tracking_resets_each_ante(self):
        g = BalatroGame(seed=42)
        g.step({"type": "play_blind"})
        g.step({"type": "play", "cards": [0]})
        assert g.ante_played_ids
        # advance blind_idx past the boss (simulate clearing 3 blinds)
        g.blind_idx = 2
        g._end_shop()   # wraps to new ante
        assert not g.ante_played_ids


# ── The Ox (most-played hand this run sets money to $0) ──────────────────────

class TestOx:
    def test_most_played_hand_zeroes_money(self):
        g = BalatroGame(seed=42)
        _setup_boss(g, "bl_ox")
        g.dollars = 20
        # all counts zero → High Card is the most-played (game default tie-break)
        g.step({"type": "play", "cards": [0]})   # 1 card = High Card
        assert g.dollars == 0

    def test_non_most_played_hand_spares_money(self):
        g = BalatroGame(seed=42)
        _setup_boss(g, "bl_ox")
        g.dollars = 20
        g.run_hand_counts["Flush"] = 10   # Flush is most-played
        g.step({"type": "play", "cards": [0]})   # High Card ≠ most-played
        assert g.dollars == 20


# ── Cerulean Bell (forced card must be in every hand) ────────────────────────

class TestCeruleanBell:
    def test_forced_card_auto_added_to_played_hand(self):
        g = BalatroGame(seed=42)
        _setup_boss(g, "bl_cerulean")
        bell = g.bell_card
        assert bell is not None and bell in g.hand
        other = next(i for i, c in enumerate(g.hand) if c is not bell)
        hands_before = g.hands_left
        g.step({"type": "play", "cards": [other]})
        assert g.hands_left == hands_before - 1   # hand consumed normally
        assert g.chips_scored > 0                 # forced card auto-added and scored
        assert bell in g.spent                    # ...so the forced card was played

    def test_play_with_bell_works_and_rechooses(self):
        g = BalatroGame(seed=42)
        _setup_boss(g, "bl_cerulean")
        bell = g.bell_card
        hands_before = g.hands_left
        g.step({"type": "play", "cards": [g.hand.index(bell)]})
        assert g.hands_left == hands_before - 1
        # a new forced card was chosen (or none if the hand is empty)
        assert g.bell_card is None or g.bell_card in g.hand

    def test_discarding_forced_card_rechooses(self):
        g = BalatroGame(seed=42)
        _setup_boss(g, "bl_cerulean")
        bell = g.bell_card
        g.step({"type": "discard", "cards": [g.hand.index(bell)]})
        assert g.bell_card is None or (g.bell_card in g.hand and g.bell_card is not bell)


# ── Amber Acorn (jokers flipped + shuffled) ──────────────────────────────────

class TestAmberAcorn:
    def test_jokers_flipped_and_flag(self):
        g = BalatroGame(seed=42)
        g.jokers = [JokerInstance("j_joker"), JokerInstance("j_half"), JokerInstance("j_bull")]
        _setup_boss(g, "bl_amber")
        assert g.jokers_flipped is True
        assert len(g.jokers) == 3
        g._undo_boss_debuffs("bl_amber")
        assert g.jokers_flipped is False

    def test_amber_masks_joker_obs(self):
        from balatro_sim.env_sim import BalatroSimEnv, JOKER_FEATURES, N_JOKER_SLOTS, GAME_SCALARS, N_HAND_SLOTS, CARD_FEATURES
        env = BalatroSimEnv(seed=42)
        env.reset()
        g = env.game
        g.jokers = [JokerInstance("j_joker"), JokerInstance("j_half")]
        g.ante = 1
        g.blind_idx = 2
        _force_boss(g, "bl_amber")
        g.step({"type": "play_blind"})
        obs = env._encode_obs()
        base = GAME_SCALARS + N_HAND_SLOTS * CARD_FEATURES
        for slot in range(N_JOKER_SLOTS):
            start = base + slot * JOKER_FEATURES
            if slot < len(g.jokers):
                assert obs[start] == 1.0                       # present
                assert obs[start+1:start+10].sum() == 0.0      # identity hidden
            else:
                assert obs[start:start+10].sum() == 0.0


# ── Crimson Heart (one random joker disabled every hand) ─────────────────────

class TestCrimsonHeart:
    def test_single_joker_never_fires(self):
        g = BalatroGame(seed=42)
        g.jokers = [JokerInstance("j_joker")]   # +4 mult
        _setup_boss(g, "bl_crimson")
        g.step({"type": "play", "cards": [0]})
        # j_joker disabled → score is base only; max High Card = (5+11)*1 = 16
        assert g.chips_scored <= 16

    def test_disabled_joker_changes_each_hand(self):
        g = BalatroGame(seed=42)
        g.jokers = [JokerInstance("j_joker"), JokerInstance("j_half")]
        _setup_boss(g, "bl_crimson")
        g.step({"type": "play", "cards": [0]})
        idx_a = g._last_crimson_idx
        g.step({"type": "play", "cards": [0]})
        idx_b = g._last_crimson_idx
        assert idx_a != idx_b   # with 2 jokers it must alternate


# ── The Club (all Clubs debuffed) ───────────────────────────────────────────

class TestClub:
    def test_all_clubs_debuffed(self):
        g = BalatroGame(seed=42)
        _setup_boss(g, "bl_club")
        clubs = [c for c in g.hand + g.deck if c.suit == "Clubs"]
        if clubs:
            assert all(c.debuffed for c in clubs)
        non_clubs = [c for c in g.hand + g.deck if c.suit != "Clubs"]
        assert all(not c.debuffed for c in non_clubs)

    def test_club_debuffs_cleared_after_round(self):
        g = BalatroGame(seed=42)
        _setup_boss(g, "bl_club")
        assert any(c.debuffed for c in g.hand + g.deck if c.suit == "Clubs")
        g._undo_boss_debuffs("bl_club")
        assert not any(c.debuffed for c in g.hand + g.deck + g.spent)


# ── The Wheel (1-in-7 cards drawn face down) ─────────────────────────────────

class TestWheel:
    def test_every_draw_flips_when_rng_forced_low(self):
        g = BalatroGame(seed=42)
        g.rng.node(WHEEL_NODE).random = lambda: 0.0   # always below 1/7
        _setup_boss(g, "bl_wheel")
        assert g.hand and all(c.flipped for c in g.hand)

    def test_no_draw_flips_when_rng_forced_high(self):
        g = BalatroGame(seed=42)
        g.rng.node(WHEEL_NODE).random = lambda: 0.99  # always above 1/7
        _setup_boss(g, "bl_wheel")
        assert g.hand and all(not c.flipped for c in g.hand)

    def test_about_one_in_seven_flipped_statistically(self):
        g = BalatroGame(seed=7)
        _setup_boss(g, "bl_wheel")
        cards = [Card(rank=r, suit="Spades") for r in range(2, 14) for _ in range(8)]
        n_flipped = 0
        for c in cards:
            c.flipped = False
            g._on_card_drawn(c)
            n_flipped += int(c.flipped)
        frac = n_flipped / len(cards)
        assert 0.05 < frac < 0.30, f"flipped fraction {frac:.3f}"

    def test_revealed_when_played(self):
        g = BalatroGame(seed=42)
        g.rng.node(WHEEL_NODE).random = lambda: 0.0
        _setup_boss(g, "bl_wheel")
        flipped_card = next(c for c in g.hand if c.flipped)
        idx = g.hand.index(flipped_card)
        g.step({"type": "play", "cards": [idx]})
        assert not flipped_card.flipped

    def test_unflipped_after_round(self):
        g = BalatroGame(seed=42)
        g.rng.node(WHEEL_NODE).random = lambda: 0.0
        _setup_boss(g, "bl_wheel")
        assert any(c.flipped for c in g.hand)
        g._undo_boss_debuffs("bl_wheel")
        assert not any(c.flipped for c in g.hand + g.deck + g.spent)


# ── The House (opening hand drawn face down) ─────────────────────────────────

class TestHouse:
    def test_opening_hand_face_down(self):
        g = BalatroGame(seed=42)
        _setup_boss(g, "bl_house")
        assert g.hand and all(c.flipped for c in g.hand)

    def test_refills_come_face_up(self):
        g = BalatroGame(seed=42)
        _setup_boss(g, "bl_house")
        n_before = len(g.hand)
        g.step({"type": "play", "cards": [0]})
        # Opening hand was 8 flipped; after playing 1, the 7 remaining stay
        # flipped and exactly 1 new face-up card is drawn to refill.
        assert len(g.hand) == n_before
        assert sum(c.flipped for c in g.hand) == len(g.hand) - 1

    def test_revealed_when_played(self):
        g = BalatroGame(seed=42)
        _setup_boss(g, "bl_house")
        card = g.hand[0]
        g.step({"type": "play", "cards": [0]})
        assert not card.flipped

    def test_unflipped_after_round(self):
        g = BalatroGame(seed=42)
        _setup_boss(g, "bl_house")
        g._undo_boss_debuffs("bl_house")
        assert not any(c.flipped for c in g.hand + g.deck + g.spent)


# ── The Arm (permanently decrease played hand level by 1) ────────────────────

class TestArm:
    def test_level_decreases_when_played(self):
        g = BalatroGame(seed=42)
        _setup_boss(g, "bl_grim")
        g.planet_levels["High Card"] = 3
        g.step({"type": "play", "cards": [0]})   # High Card
        assert g.planet_levels["High Card"] == 2

    def test_floors_at_level_1(self):
        g = BalatroGame(seed=42)
        _setup_boss(g, "bl_grim")
        g.planet_levels["High Card"] = 1
        g.step({"type": "play", "cards": [0]})
        assert g.planet_levels["High Card"] == 1

    def test_other_hand_types_unaffected(self):
        g = BalatroGame(seed=42)
        _setup_boss(g, "bl_grim")
        g.planet_levels["Pair"] = 4
        g.step({"type": "play", "cards": [0]})   # High Card
        assert g.planet_levels["Pair"] == 4

    def test_level_loss_is_permanent(self):
        """planet_levels is run-wide, so the loss persists after the blind."""
        g = BalatroGame(seed=42)
        _setup_boss(g, "bl_grim")
        g.planet_levels["High Card"] = 3
        g.step({"type": "play", "cards": [0]})
        assert g.planet_levels["High Card"] == 2
        # nothing restores it: end the round, shop, next blind
        g.chips_scored = g.current_blind.chips_target
        g.state = State.ROUND_EVAL
        g.step({"type": "cash_out"})
        assert g.planet_levels["High Card"] == 2

    def test_played_hand_scores_at_reduced_level(self):
        """The reduction happens BEFORE scoring: a level-2 High Card of 2S is
        scored at level 1 -> (5+2)*1 = 7, not (15+2)*2 = 34."""
        g = BalatroGame(seed=42)
        _setup_boss(g, "bl_grim")
        _craft_hand(g)
        g.planet_levels["High Card"] = 2
        g.step({"type": "play", "cards": [0]})   # 2S High Card
        assert g.planet_levels["High Card"] == 1
        assert g.chips_scored == 7


# ── The Eye / The Mouth (rejections cost no hand) ────────────────────────────

class TestEyeMouth:
    def test_eye_rejected_hand_wastes_hand_scores_zero(self):
        g = BalatroGame(seed=42)
        _setup_boss(g, "bl_eye")
        _craft_hand(g)
        g.step({"type": "play", "cards": [1, 2]})       # Pair — allowed
        assert g.played_hand_types_this_round == {"Pair"}
        g.step({"type": "play", "cards": [0]})          # High Card — new type, allowed
        hands_before = g.hands_left
        chips_before = g.chips_scored
        g.step({"type": "play", "cards": [0]})          # High Card again → rejected
        assert g.hands_left == hands_before - 1           # rejected play still wastes a hand
        assert g.chips_scored == chips_before             # but scores nothing

    def test_mouth_rejected_hand_wastes_hand_scores_zero(self):
        g = BalatroGame(seed=42)
        _setup_boss(g, "bl_mouth")
        _craft_hand(g)
        g.step({"type": "play", "cards": [1, 2]})       # Pair locks in
        hands_before = g.hands_left
        chips_before = g.chips_scored
        assert chips_before > 0
        g.step({"type": "play", "cards": [0]})          # High Card ≠ Pair → rejected
        assert g.hands_left == hands_before - 1           # rejected play still wastes a hand
        assert g.chips_scored == chips_before             # and scores nothing
        assert g.played_hand_types_this_round == {"Pair"}   # rejected type does not relock
