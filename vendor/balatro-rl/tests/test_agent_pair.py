from __future__ import annotations

import itertools
import math
import random
from copy import copy as shallowcopy, deepcopy
from enum import Enum

import pytest

import balatro_sim.agent_pair as pair_policy
from balatro_sim.agent_pair import (
    PairBot,
    _determine_anchor_rank,
    _eval_joker_utility,
    _get_representative_cards,
    _is_held_in_hand_value_card,
    _pair_eval_hand_score,
    _pair_joker_lifecycle_value,
    _pair_plan_discard,
    _pair_remaining_blinds,
    _rank_shop_items,
)
from balatro_sim.card import Card
from balatro_sim.card_selection import validate_play_subset
from balatro_sim.constants import BLIND_CHIPS, HAND_SIZE
from balatro_sim.game import BOSS_BLINDS, BalatroGame, BlindInfo, State
from balatro_sim.seed_rng import DECK_SHUFFLE_NODE, WHEEL_NODE
from balatro_sim.hand_eval import HAND_PRIORITY, evaluate_hand
from balatro_sim.jokers.base import JokerInstance
from balatro_sim.shop import ShopItem


def _randomize_hand(game: BalatroGame, rng: random.Random, size: int) -> None:
    drawn = rng.sample(game.deck, size)
    drawn_ids = {id(card) for card in drawn}
    game.deck = [card for card in game.deck if id(card) not in drawn_ids]
    for card in drawn:
        card.enhancement = rng.choice(("None", "None", "Bonus", "Mult", "Stone", "Wild", "Glass", "Steel", "Lucky"))
        card.seal = rng.choice(("None", "None", "None", "Red", "Blue", "Gold"))
        card.debuffed = rng.random() < 0.08
    game.hand = drawn


def _reference_legal_subsets(game: BalatroGame, boss: str) -> set[tuple[int, ...]]:
    """Brute-force game-rule legality oracle, independent of PairBot's search."""
    sizes = (5,) if boss == "bl_psychic" else range(1, min(5, len(game.hand)) + 1)
    legal = set()
    for size in sizes:
        for combo in itertools.combinations(range(len(game.hand)), size):
            selected = [game.hand[index] for index in combo]
            if boss == "bl_cerulean" and game.bell_card is not None and not any(
                card is game.bell_card for card in selected
            ):
                # The engine automatically adds the forced Bell card after
                # selection; it need not be a scoring card or an explicit index.
                selected.append(game.bell_card)
            hand_type, _scoring_cards = evaluate_hand(selected)
            if boss == "bl_eye" and hand_type in game.played_hand_types_this_round:
                continue
            if boss == "bl_mouth" and game.played_hand_types_this_round and hand_type not in game.played_hand_types_this_round:
                continue
            legal.add(combo)
    return legal


def _rng_snapshot(game: BalatroGame):
    source = game.rng
    node_keys = tuple(sorted(getattr(source, "_nodes", {})))
    if hasattr(source, "_rng"):
        return ("generic", source._rng.getstate(), node_keys)
    return (
        "seed",
        dict(source.table.nodes),
        dict(source._seq),
        tuple(source.records) if source.records is not None else None,
        node_keys,
    )


def _freeze_game_value(value, game):
    if isinstance(value, Enum):
        return (type(value).__name__, value.name)
    if isinstance(value, type):
        return ("type", value.__module__, value.__qualname__)
    if value is game:
        return ("game-ref", id(game))
    if value is game.rng:
        return ("rng", _rng_snapshot(game))
    if isinstance(value, Card):
        return ("card", id(value), _freeze_game_value(value.__dict__, game))
    if isinstance(value, JokerInstance):
        # Joker instances point back to the game and have transient hook-cache
        # entries; only persistent owned-joker identity/state belongs here.
        return ("joker", id(value), value.key, value.edition, _freeze_game_value(value.state, game))
    if isinstance(value, random.Random):
        return ("python-rng", value.getstate())
    if isinstance(value, dict):
        return tuple((_freeze_game_value(key, game), _freeze_game_value(item, game)) for key, item in value.items())
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_game_value(item, game) for item in value)
    if isinstance(value, (set, frozenset)):
        return tuple(sorted((_freeze_game_value(item, game) for item in value), key=repr))
    if value is None or isinstance(value, (bool, int, float, str, bytes)):
        return value
    attributes = getattr(value, "__dict__", None)
    if attributes is not None:
        return (type(value).__name__, id(value), _freeze_game_value(attributes, game))
    return (type(value).__name__, id(value), repr(value))


def _game_runtime_snapshot(game: BalatroGame):
    # Snapshot every persistent game field, not just those expected to be
    # touched by scoring. The canonicalizer handles card identity and joker
    # back-references while including both generic and per-node RNG internals.
    return _freeze_game_value(vars(game), game)


def _random_played_types(game: BalatroGame, boss: str, rng: random.Random) -> None:
    possible = {
        evaluate_hand([game.hand[index] for index in combo])[0]
        for size in range(1, min(5, len(game.hand)) + 1)
        for combo in itertools.combinations(range(len(game.hand)), size)
    }
    if boss == "bl_eye":
        # Leave High Card available, guaranteeing a legal baseline subset.
        blocked = sorted(possible - {"High Card"})
        game.played_hand_types_this_round = set(rng.sample(blocked, min(len(blocked), rng.randrange(4))))
    elif boss == "bl_mouth":
        game.played_hand_types_this_round = {rng.choice(sorted(possible))}
    else:
        game.played_hand_types_this_round = set()


def _pair_decision_oracle_score(game: BalatroGame, boss: str) -> int:
    """Exact best isolated score, grouped by PairBot's Pair/tactical policy."""
    pair_scores = []
    tactical_scores = []
    legal_subsets = _reference_legal_subsets(game, boss)
    for combo in sorted(legal_subsets):
        requested_cards = [game.hand[index] for index in combo]
        requested_type, _ = evaluate_hand(requested_cards)
        played_indices = list(combo)
        played_cards = list(requested_cards)
        if boss == "bl_cerulean" and game.bell_card is not None:
            for bell_index, card in enumerate(game.hand):
                if card is game.bell_card:
                    if bell_index not in combo:
                        played_indices.append(bell_index)
                        played_cards.append(card)
                    break
        hand_type, scoring_cards = evaluate_hand(played_cards)
        if boss == "bl_psychic":
            # PairBot starts Psychic candidates from an actually playable pair;
            # Stone cards do not count toward hand type even when their ranks
            # match another selected card.
            has_pair = any(
                evaluate_hand([game.hand[i] for i in pair])[0] == "Pair"
                for pair in itertools.combinations(combo, 2)
            )
        elif boss == "bl_cerulean":
            # Cerulean may auto-add the Bell and upgrade the resolved hand, but
            # PairBot categorizes the candidate by the player's explicit pick.
            has_pair = requested_type == "Pair"
        else:
            # PairBot only retains resolved Pair plays as Pair candidates;
            # Wild cards can turn a five-card Pair selection into a Flush.
            has_pair = hand_type == "Pair"
        held = [card for index, card in enumerate(game.hand) if index not in set(played_indices)]
        score = pair_policy.eval_hand_score(
            game, hand_type, scoring_cards, played_cards, held_cards=held,
        )
        (pair_scores if has_pair else tactical_scores).append(score)

    candidates = pair_scores or tactical_scores
    assert candidates, "exact oracle fixture must have a legal Pair or tactical play"
    return max(candidates)


class MockJoker:
    def __init__(self, key: str, edition: str = "None"):
        self.key = key
        self.edition = edition
        self.state = {}
        self.cost = 4

    def has_flag(self, flag: str) -> bool:
        return False


def make_card(rank: int, suit: str = "Spades", enhancement: str = "None", seal: str = "None") -> Card:
    return Card(rank=rank, suit=suit, enhancement=enhancement, seal=seal)


def make_shop_item(kind: str, key: str, price: int, edition: str = "None") -> ShopItem:
    return ShopItem(kind=kind, key=key, name=key, price=price, edition=edition)


def _boss_effect_deck() -> list[Card]:
    """Small deterministic deck with every suit, face cards, and draw slack."""
    return [
        make_card(2, "Spades"), make_card(3, "Hearts"),
        make_card(4, "Clubs"), make_card(5, "Diamonds"),
        make_card(9, "Spades"), make_card(10, "Hearts"),
        make_card(12, "Clubs"), make_card(8, "Diamonds"),
        make_card(9, "Spades"), make_card(10, "Hearts"),
        make_card(13, "Clubs"), make_card(14, "Diamonds"),
        make_card(2, "Clubs"), make_card(3, "Spades"),
        make_card(4, "Hearts"), make_card(5, "Clubs"),
    ]


def _pair_fairness_fixture(
    phase: str,
    rng_mode: str,
    seed: int,
    reverse_deck: bool = False,
) -> BalatroGame:
    """Build identical observable PairBot states while varying only hidden inputs."""
    game = BalatroGame(seed=seed, rng_mode=rng_mode)
    game.ante = 2
    game.blind_idx = 0
    game.state = State.BLIND_SELECT
    game.current_blind = BlindInfo("Fairness audit", "Small", 10**9)
    game.current_tag = None
    game.next_boss_key = None
    game.boss_appearances = {}
    game.dollars = 20
    game.chips_scored = 0
    game.hands_left = 3
    game.discards_left = 2
    game.jokers = []
    game.hand = []
    game.spent = []
    game.consumable_hand = []
    game.current_shop = []
    game.booster_choices = []
    game.booster_picks_remaining = 0

    if phase in ("hand_play", "hand_discard", "hand_consumable"):
        if phase == "hand_play":
            hand = [
                make_card(10, "Spades"), make_card(10, "Hearts"),
                make_card(2, "Clubs"), make_card(4, "Diamonds"),
                make_card(6, "Clubs"), make_card(8, "Hearts"),
            ]
            game.discards_left = 0
        elif phase == "hand_discard":
            hand = [
                make_card(2, "Spades"), make_card(4, "Hearts"),
                make_card(6, "Clubs"), make_card(8, "Diamonds"),
                make_card(10, "Spades"), make_card(12, "Hearts"),
            ]
        else:
            hand = [make_card(10, "Spades"), make_card(10, "Hearts"), make_card(3, "Clubs")]
            game.consumable_hand = ["c_mercury"]
        hand_signatures = {(card.rank, card.suit) for card in hand}
        game.deck = [
            card for card in game.deck
            if (card.rank, card.suit) not in hand_signatures
        ]
        game.hand = hand
        game.state = State.SELECTING_HAND
    elif phase == "shop":
        game.state = State.SHOP
        game.current_shop = [
            make_shop_item("joker", "j_jolly", 3),
            make_shop_item("joker", "j_half", 5),
            make_shop_item("booster", "p_buffoon", 4),
        ]
    elif phase == "booster":
        game.state = State.BOOSTER_OPEN
        game.booster_picks_remaining = 1
        game.booster_choices = [
            ("card", make_card(8, "Clubs")),
            ("card", make_card(5, "Diamonds", seal="Blue")),
            ("card", make_card(9, "Hearts", enhancement="Bonus")),
            ("joker", "j_jolly", "None"),
        ]
    elif phase == "round_eval":
        game.state = State.ROUND_EVAL
    elif phase == "game_over":
        game.state = State.GAME_OVER
    elif phase != "blind_select":
        raise ValueError(f"unknown PairBot fairness phase: {phase}")

    if reverse_deck:
        game.deck.reverse()
    if rng_mode == "seed":
        game.rng.enable_tracing()
    return game


def _pair_composition_fuzz_fixture(
    composition_seed: int,
    rng_mode: str,
    run_seed: int,
    boss_key: str,
    disable_boss: bool = False,
    reverse_deck: bool = False,
    force_discard: bool = False,
) -> BalatroGame:
    """Build a reproducible randomized hand with a separately seeded run RNG."""
    rng = random.Random(composition_seed)
    game = BalatroGame(seed=run_seed, rng_mode=rng_mode)
    game.ante = 2
    game.blind_idx = 2 if boss_key else 0
    game.state = State.SELECTING_HAND
    game.current_blind = BlindInfo(
        name=f"Composition fuzz {boss_key or 'no boss'}",
        kind="Boss" if boss_key else "Small",
        chips_target=10**9,
        is_boss=bool(boss_key),
        boss_key=boss_key,
    )
    game.current_tag = None
    game.next_boss_key = None
    game.boss_appearances = {}
    game.chips_scored = 0
    game.hands_left = 2 if force_discard else rng.randint(1, 4)
    game.discards_left = 1 if force_discard else rng.randint(0, 2)
    game.boss_disabled_override = disable_boss
    game.bell_card = None
    game.played_hand_types_this_round = set()
    game.consumable_hand = []
    game.jokers = []

    hand_size = 5 if boss_key == "bl_psychic" else rng.randint(5, 8)
    _randomize_hand(game, rng, hand_size)
    enhancements = (
        "None", "None", "None", "Bonus", "Mult", "Stone", "Wild",
        "Glass", "Steel", "Lucky", "Gold",
    )
    editions = ("None", "None", "None", "Foil", "Holographic", "Polychrome", "Negative")
    seals = ("None", "None", "None", "None", "Red", "Blue", "Gold", "Purple")
    all_cards = game.deck + game.hand
    rank_suits = [
        (rank, suit)
        for suit in ("Spades", "Hearts", "Clubs", "Diamonds")
        for rank in range(2, 15)
    ]
    rng.shuffle(rank_suits)
    for card, (rank, suit) in zip(all_cards, rank_suits):
        card.rank = rank
        card.suit = suit
        card.enhancement = rng.choice(enhancements)
        card.edition = rng.choice(editions)
        card.seal = rng.choice(seals)
        card.debuffed = rng.random() < 0.06
        card.flipped = False

    if force_discard:
        # Keep a guaranteed no-pair hand so this randomized audit also reaches
        # the composition-based discard planner (without hidden draw-order data).
        game.jokers = []
        forced_ranks = (2, 4, 6, 8, 10, 12, 14, 3)
        suit_options_by_rank = {
            rank: [suit for candidate_rank, suit in rank_suits if candidate_rank == rank]
            for rank in range(2, 15)
        }
        forced_rank_suits = [
            (rank, rng.choice(suit_options_by_rank[rank]))
            for rank in forced_ranks[:len(game.hand)]
        ]
        for card, (rank, suit) in zip(game.hand, forced_rank_suits):
            card.rank = rank
            card.suit = suit
            card.enhancement = "None"
            card.edition = "None"
            card.seal = "None"
            card.debuffed = False
        forced_keys = set(forced_rank_suits)
        remaining_rank_suits = [key for key in rank_suits if key not in forced_keys]
        rng.shuffle(remaining_rank_suits)
        for card, (rank, suit) in zip(game.deck, remaining_rank_suits):
            card.rank = rank
            card.suit = suit
        assert len(remaining_rank_suits) == len(game.deck)

    active_boss = boss_key if game._boss_effects_on() else ""
    if active_boss == "bl_cerulean":
        game.bell_card = rng.choice(game.hand)
    _random_played_types(game, active_boss, rng)

    if not force_discard:
        joker_pool = (
            "j_green_joker", "j_ice_cream", "j_ride_the_bus", "j_hiker",
            "j_popcorn", "j_ramen", "j_constellation", "j_jolly", "j_half",
            "j_square", "j_baron", "j_mime", "j_blueprint", "j_brainstorm",
        )
        joker_editions = ("None", "None", "Foil", "Holographic", "Polychrome", "Negative")
        for key in rng.sample(joker_pool, rng.randint(0, 3)):
            joker = JokerInstance(key, edition=rng.choice(joker_editions), game=game)
            state_fields = {
                "j_green_joker": ("mult", rng.randint(0, 5)),
                "j_ice_cream": ("chips", rng.randint(0, 100)),
                "j_ride_the_bus": ("mult", rng.randint(0, 8)),
                "j_popcorn": ("mult", rng.randint(0, 20)),
                "j_ramen": ("mult", rng.uniform(1.0, 2.0)),
                "j_constellation": ("mult", rng.uniform(1.0, 2.0)),
            }
            if key in state_fields:
                field, value = state_fields[key]
                joker.state[field] = value
            game.jokers.append(joker)

    if reverse_deck:
        game.deck.reverse()
    if rng_mode == "seed":
        game.rng.enable_tracing()
    return game


def _start_boss_effect_game(
    boss_key: str,
    disabled: bool = False,
    played_types: tuple[str, ...] = (),
) -> BalatroGame:
    game = BalatroGame(seed=0xB055)
    game.ante = 2
    game.blind_idx = 2
    game.current_blind = BlindInfo(
        name=f"Test {boss_key}", kind="Boss", chips_target=100_000,
        is_boss=True, boss_key=boss_key,
    )
    game.state = State.BLIND_SELECT
    game.played_hand_types_this_round = set(played_types)
    game.boss_disabled_override = disabled
    game.hand = []
    game.spent = []
    game.deck = _boss_effect_deck()
    game.rng.node(DECK_SHUFFLE_NODE).shuffle = lambda _cards: None
    if boss_key == "bl_wheel":
        game.rng.node(WHEEL_NODE).random = lambda: 0.0
    if boss_key == "bl_amber":
        game.jokers = [
            JokerInstance("j_joker", game=game),
            JokerInstance("j_half", game=game),
        ]
    if boss_key == "bl_pillar":
        # The last deterministic-deck card is drawn first by _start_blind.
        game.ante_played_ids.add(game.deck[-1].id)
    game._start_blind()
    return game


class TestAgentPair:
    def test_anchor_rank_selection(self):
        game = BalatroGame(seed=123)

        # 1. Walkie Talkie selects 10 or 4
        game.jokers = [MockJoker("j_walkie_talkie")]
        rank = _determine_anchor_rank(game)
        assert rank in (10, 4)

        # 2. Wee Joker selects 2
        game.jokers = [MockJoker("j_wee")]
        assert _determine_anchor_rank(game) == 2

        # 3. Fibonacci selects from Fibonacci set
        game.jokers = [MockJoker("j_fibonacci")]
        assert _determine_anchor_rank(game) in {14, 2, 3, 5, 8}

        # 4. Ride the Bus excludes face cards
        game.jokers = [MockJoker("j_ride_the_bus")]
        assert _determine_anchor_rank(game) not in {11, 12, 13}

    def test_anchor_ties_are_stable_and_high_rank_first(self):
        game = BalatroGame(seed=123)
        game.deck = [make_card(4), make_card(4), make_card(10), make_card(10)]
        assert _determine_anchor_rank(game) == 10
        game.jokers = [MockJoker("j_hack")]
        game.deck = [make_card(2), make_card(2), make_card(5), make_card(5)]
        assert _determine_anchor_rank(game) == 5

    def test_held_in_hand_protection(self):
        j_keys = {"j_baron"}
        gold_card = make_card(rank=5, enhancement="Gold")
        steel_card = make_card(rank=7, enhancement="Steel")
        blue_seal = make_card(rank=8, seal="Blue")
        king = make_card(rank=13)
        normal = make_card(rank=9)

        assert _is_held_in_hand_value_card(gold_card, j_keys) is True
        assert _is_held_in_hand_value_card(steel_card, j_keys) is True
        assert _is_held_in_hand_value_card(blue_seal, j_keys) is True
        assert _is_held_in_hand_value_card(king, j_keys) is True
        assert _is_held_in_hand_value_card(normal, j_keys) is False

    def test_hand_sizing_half_joker(self):
        bot = PairBot()
        game = BalatroGame(seed=456)
        game.state = State.SELECTING_HAND
        game.jokers = [MockJoker("j_half")]
        # Hand: Pair of 10s, three junk cards
        game.hand = [
            make_card(10, "Spades"),
            make_card(10, "Hearts"),
            make_card(2, "Clubs"),
            make_card(3, "Diamonds"),
            make_card(4, "Spades"),
        ]

        action = bot._pair_decide_hand(game)
        assert action["type"] == "play"
        # Half Joker requires <= 3 cards played, so PairBot must play strictly 2 cards
        assert len(action["cards"]) == 2
        assert set(action["cards"]) == {0, 1}

    def test_hand_sizing_square_joker(self):
        bot = PairBot()
        game = BalatroGame(seed=456)
        game.state = State.SELECTING_HAND
        game.current_blind.chips_target = 100
        game.jokers = [MockJoker("j_square")]
        game.hand = [
            make_card(10, "Spades"),
            make_card(10, "Hearts"),
            make_card(2, "Clubs"),
            make_card(3, "Diamonds"),
            make_card(4, "Spades"),
        ]

        action = bot._pair_decide_hand(game)
        assert action["type"] == "play"
        # Square Joker requires exactly 4 cards to scale
        assert len(action["cards"]) == 4
        # Pair (0, 1) must be included
        assert 0 in action["cards"] and 1 in action["cards"]

    def test_hand_sizing_psychic_boss(self):
        bot = PairBot()
        game = BalatroGame(seed=456)
        game.state = State.SELECTING_HAND
        game.current_blind.chips_target = 100
        game.current_blind.boss_key = "bl_psychic"
        game.current_blind.is_boss = True
        game.hand = [
            make_card(10, "Spades"),
            make_card(10, "Hearts"),
            make_card(2, "Clubs"),
            make_card(3, "Diamonds"),
            make_card(4, "Spades"),
        ]

        action = bot._pair_decide_hand(game)
        assert action["type"] == "play"
        # Psychic boss requires playing exactly 5 cards
        assert len(action["cards"]) == 5

    def test_held_value_not_attached_as_junk(self):
        bot = PairBot()
        game = BalatroGame(seed=456)
        game.state = State.SELECTING_HAND
        # No Half Joker, 2 hands left, 0 discards -> allows junk cycling
        game.hands_left = 2
        game.discards_left = 0
        game.hand = [
            make_card(10, "Spades"),
            make_card(10, "Hearts"),
            make_card(7, "Diamonds", enhancement="Steel"),  # Held value!
            make_card(8, "Spades", seal="Blue"),           # Held value!
            make_card(2, "Clubs"),                         # Pure junk
        ]

        action = bot._pair_decide_hand(game)
        assert action["type"] == "play"
        # Indices 2 (Steel) and 3 (Blue seal) must NOT be played as junk
        assert 2 not in action["cards"]
        assert 3 not in action["cards"]

    def test_mercury_instant_consumption(self):
        bot = PairBot()
        game = BalatroGame(seed=789)
        game.state = State.SELECTING_HAND
        game.consumable_hand = ["c_mercury", "c_fool"]
        game.hand = [make_card(10), make_card(10), make_card(3)]

        action = bot._pair_decide_hand(game)
        assert action["type"] == "use_consumable"
        assert action["consumable_idx"] == 0

    def test_death_tarot_pair_targeting(self):
        bot = PairBot()
        game = BalatroGame(seed=789)
        game.state = State.SELECTING_HAND
        game.jokers = [MockJoker("j_walkie_talkie")]  # Anchor rank is 10
        game.consumable_hand = ["c_death"]
        game.hand = [
            make_card(10, "Spades"),  # Index 0: Anchor rank
            make_card(2, "Hearts"),   # Index 1: Junk
            make_card(3, "Clubs"),    # Index 2: Junk
        ]

        action = bot._pair_decide_hand(game)
        assert action["type"] == "use_consumable"
        assert action["consumable_idx"] == 0
        # target_cards = [dst, src] -> 0 is source (10), destination is non-anchor junk
        dst, src = action["target_cards"]
        assert src == 0
        assert dst in (1, 2)

    def test_pair_lifecycle_values_decline_with_ante_and_use_live_counters(self):
        game = BalatroGame(seed=129)
        game.state = State.SHOP
        game.deck = [make_card(10), make_card(10, "Hearts")]
        game.ante = 1
        early = _pair_joker_lifecycle_value(game, "j_green_joker", {"mult": 0})
        game.ante = 7
        late = _pair_joker_lifecycle_value(game, "j_green_joker", {"mult": 0})
        assert early > late >= 0

        game.ante = 3
        game.jokers = [MockJoker("j_rocket")]
        current = _pair_joker_lifecycle_value(game, "j_rocket", {"bonus": 1})
        stacked = _pair_joker_lifecycle_value(game, "j_rocket", {"bonus": 5})
        assert stacked > current

    def test_finite_joker_exposure_uses_remaining_runtime_state(self):
        game = BalatroGame(seed=130)
        game.ante = 8
        game.state = State.SHOP
        game.blind_idx = 0
        almost_spent = _pair_joker_lifecycle_value(game, "j_popcorn", {"mult": 4})
        fresh = _pair_joker_lifecycle_value(game, "j_popcorn", {"mult": 20})
        assert almost_spent < fresh

    def test_copy_joker_counterfactuals_are_state_and_rng_isolated(self):
        game = BalatroGame(seed=70124)
        game.state = State.SHOP
        game.ante = 3
        game.deck = [make_card(10), make_card(10, "Hearts")]
        game.jokers = [MockJoker("j_jolly"), MockJoker("j_blueprint")]
        game.jokers[0].state = {"mult": 4, "nested": {"kept": True}}
        rng_before = game.rng._rng.getstate()
        joker_order = list(game.jokers)
        states_before = deepcopy([j.state for j in game.jokers])
        rep_pair, rep_held = _get_representative_cards(game)

        score_with_blueprint = _pair_eval_hand_score(
            game, "Pair", rep_pair, rep_pair, held_cards=rep_held,
        )
        score_without_jolly = _pair_eval_hand_score(
            game, "Pair", rep_pair, rep_pair, held_cards=rep_held,
            exclude_joker=0,
        )
        score_without_blueprint = _pair_eval_hand_score(
            game, "Pair", rep_pair, rep_pair, held_cards=rep_held,
            exclude_joker=1,
        )
        assert score_with_blueprint > score_without_jolly
        assert score_with_blueprint > score_without_blueprint
        assert math.isfinite(_eval_joker_utility(game, "j_blueprint"))
        assert game.rng._rng.getstate() == rng_before
        assert game.jokers == joker_order
        assert [j.state for j in game.jokers] == states_before

    def test_pair_lifecycle_ends_after_game_over(self):
        game = BalatroGame(seed=131)
        game.state = State.GAME_OVER
        assert _pair_remaining_blinds(game) == 0
        assert _pair_joker_lifecycle_value(game, "j_green_joker") == 0

    def test_tactical_non_pair_saves_non_psychic_boss_hand(self):
        bot = PairBot()
        game = BalatroGame(seed=132)
        game.ante = 2
        game.state = State.SELECTING_HAND
        game.hands_left = 1
        game.discards_left = 0
        game.current_blind.chips_target = 1000
        game.current_blind.boss_key = "bl_eye"
        game.current_blind.is_boss = True
        game.played_hand_types_this_round.add("Pair")
        game.hand = [
            make_card(2, "Clubs"), make_card(4, "Clubs"),
            make_card(6, "Clubs"), make_card(8, "Clubs"), make_card(10, "Clubs"),
        ]
        action = bot._pair_decide_hand(game)
        assert action["type"] == "play"
        assert len(action["cards"]) == 5
        assert len({game.hand[i].suit for i in action["cards"]}) == 1

    def test_cerulean_pair_can_omit_a_forced_non_scoring_card(self, monkeypatch):
        bot = PairBot()
        game = BalatroGame(seed=136)
        game.ante = 2
        game.state = State.SELECTING_HAND
        game.hands_left = 1
        game.discards_left = 0
        game.hand_size = 6
        game.current_blind = BlindInfo(
            "Test Cerulean", "Boss", 100_000, is_boss=True, boss_key="bl_cerulean",
        )
        game.hand = [
            make_card(10, "Spades"), make_card(10, "Hearts"),
            make_card(2, "Clubs", enhancement="Steel"),
            make_card(4, "Diamonds"), make_card(6, "Clubs"), make_card(8, "Hearts"),
        ]
        game.bell_card = game.hand[2]
        bell = game.bell_card
        evaluated_with_bell = []

        def deterministic_score(_game, hand_type, scoring_cards, all_cards, held_cards=None, **_kwargs):
            if hand_type == "Pair" and bell in all_cards:
                evaluated_with_bell.append((list(scoring_cards), list(all_cards), list(held_cards or [])))
            return 100 + sum(card.rank for card in scoring_cards)

        monkeypatch.setattr(pair_policy, "eval_hand_score", deterministic_score)
        action = bot._pair_decide_hand(game)

        assert action == {"type": "play", "cards": [0, 1]}
        assert evaluated_with_bell
        scoring_cards, played_cards, held_cards = evaluated_with_bell[0]
        assert bell not in scoring_cards  # forced inclusion need not score
        assert bell in played_cards
        assert bell not in held_cards

        # The real engine adds the omitted bell to the played hand and spends it.
        game.step(action)
        assert bell in game.spent
        assert game.run_hand_counts["Pair"] == 1
        assert game.chips_scored > 0

    def test_psychic_submits_unavoidable_short_hand_when_no_legal_play_exists(self):
        bot = PairBot()
        game = BalatroGame(seed=133)
        game.ante = 2
        game.state = State.SELECTING_HAND
        game.hands_left = 1
        game.discards_left = 0
        game.current_blind.chips_target = 1000
        game.current_blind.boss_key = "bl_psychic"
        game.current_blind.is_boss = True
        game.hand = [make_card(2), make_card(4, "Hearts"), make_card(6, "Clubs"), make_card(8, "Diamonds")]
        action = bot._pair_decide_hand(game)
        assert action["type"] == "play"
        assert len(action["cards"]) == 4

    def test_human_fair_isolated_rng(self):
        # Generic mode
        game = BalatroGame(seed=70123)
        bot = PairBot()
        rng_before = game.rng._rng.getstate()
        bot.decide(game)
        rng_after = game.rng._rng.getstate()
        assert rng_before == rng_after

        # Seed mode
        game_seed = BalatroGame(seed="70123", rng_mode="seed")
        game_seed.rng.enable_tracing()
        bot.decide(game_seed)
        assert len(game_seed.rng.records) == 0

    @pytest.mark.parametrize("rng_mode", ("generic", "seed"))
    @pytest.mark.parametrize(
        "phase",
        (
            "blind_select", "hand_play", "hand_discard", "hand_consumable",
            "shop", "booster", "round_eval", "game_over",
        ),
    )
    def test_cross_phase_fairness_audit_ignores_deck_order_and_run_rng(self, phase, rng_mode):
        primary = _pair_fairness_fixture(phase, rng_mode, seed=70123)
        reversed_deck = _pair_fairness_fixture(
            phase, rng_mode, seed=70123, reverse_deck=True,
        )
        alternate_rng = _pair_fairness_fixture(phase, rng_mode, seed=70124)

        deck_key = lambda card: (
            card.rank, card.suit, card.enhancement, card.edition,
            card.seal, card.debuffed, card.flipped,
        )
        assert sorted(map(deck_key, primary.deck)) == sorted(map(deck_key, reversed_deck.deck))
        assert [deck_key(card) for card in primary.deck] != [
            deck_key(card) for card in reversed_deck.deck
        ]
        assert _rng_snapshot(primary) == _rng_snapshot(reversed_deck), (
            "reversing the hidden deck must not alter the run-RNG state"
        )
        assert _rng_snapshot(primary) != _rng_snapshot(alternate_rng), (
            "the audit must compare distinct run-RNG states"
        )

        def audited_decision(game):
            game_before = _game_runtime_snapshot(game)
            rng_before = _rng_snapshot(game)
            python_rng_before = random.getstate()
            action = PairBot().decide(game)
            assert _game_runtime_snapshot(game) == game_before, (
                f"PairBot mutated live game state in {phase}/{rng_mode}"
            )
            assert _rng_snapshot(game) == rng_before, (
                f"PairBot consumed the run RNG in {phase}/{rng_mode}"
            )
            assert random.getstate() == python_rng_before, (
                f"PairBot consumed global Python RNG in {phase}/{rng_mode}"
            )
            if rng_mode == "seed":
                assert game.rng.records == [], (
                    f"PairBot emitted run-RNG draws in {phase}"
                )
            return action

        primary_action = audited_decision(primary)
        reversed_action = audited_decision(reversed_deck)
        alternate_rng_action = audited_decision(alternate_rng)
        assert primary_action == reversed_action, (
            f"PairBot action depends on hidden deck order in {phase}/{rng_mode}: "
            f"{primary_action} != {reversed_action}"
        )
        assert primary_action == alternate_rng_action, (
            f"PairBot action depends on run RNG in {phase}/{rng_mode}: "
            f"{primary_action} != {alternate_rng_action}"
        )

        expected_types = {
            "blind_select": "play_blind",
            "hand_play": "play",
            "hand_discard": "discard",
            "hand_consumable": "use_consumable",
            "shop": "buy",
            "booster": "pick_booster",
            "round_eval": "noop",
            "game_over": "noop",
        }
        assert primary_action["type"] == expected_types[phase], (
            f"fairness fixture did not exercise {phase}: {primary_action}"
        )

    def test_seeded_randomized_composition_fairness_audit(self):
        boss_keys = ("", "bl_psychic", "bl_eye", "bl_mouth", "bl_cerulean")
        seen_boss_states = set()
        seen_actions = set()
        seen_hand_compositions = set()
        case = 0

        for rng_mode in ("generic", "seed"):
            for boss_key in boss_keys:
                for variation in range(2):
                    disabled = bool(boss_key and variation == 1)
                    force_discard = not boss_key and variation == 1
                    composition_seed = 0xFA17_0000 + case * 97
                    run_seed = 74000 + case * 13
                    primary = _pair_composition_fuzz_fixture(
                        composition_seed, rng_mode, run_seed, boss_key,
                        disable_boss=disabled, force_discard=force_discard,
                    )
                    reversed_deck = _pair_composition_fuzz_fixture(
                        composition_seed, rng_mode, run_seed, boss_key,
                        disable_boss=disabled, reverse_deck=True,
                        force_discard=force_discard,
                    )
                    alternate_rng = _pair_composition_fuzz_fixture(
                        composition_seed, rng_mode, run_seed + 1, boss_key,
                        disable_boss=disabled, force_discard=force_discard,
                    )
                    case += 1

                    card_key = lambda card: (
                        card.rank, card.suit, card.enhancement, card.edition,
                        card.seal, card.debuffed, card.flipped,
                    )
                    hand_composition = tuple(card_key(card) for card in primary.hand)
                    assert hand_composition == tuple(
                        card_key(card) for card in reversed_deck.hand
                    ) == tuple(card_key(card) for card in alternate_rng.hand)
                    seen_hand_compositions.add(hand_composition)
                    assert sorted(map(card_key, primary.deck)) == sorted(
                        map(card_key, reversed_deck.deck)
                    ) == sorted(map(card_key, alternate_rng.deck))
                    assert [card_key(card) for card in primary.deck] != [
                        card_key(card) for card in reversed_deck.deck
                    ]
                    assert _rng_snapshot(primary) == _rng_snapshot(reversed_deck)
                    assert _rng_snapshot(primary) != _rng_snapshot(alternate_rng)

                    active_boss = boss_key if primary._boss_effects_on() else ""
                    seen_boss_states.add((rng_mode, boss_key, bool(active_boss)))

                    def audited_decision(game):
                        game_before = _game_runtime_snapshot(game)
                        rng_before = _rng_snapshot(game)
                        python_rng_before = random.getstate()
                        action = PairBot().decide(game)
                        assert _game_runtime_snapshot(game) == game_before, (
                            f"PairBot mutated randomized state case={case - 1}, "
                            f"boss={boss_key or 'none'}/{active_boss or 'disabled'}"
                        )
                        assert _rng_snapshot(game) == rng_before, (
                            f"PairBot consumed run RNG case={case - 1}, "
                            f"boss={boss_key or 'none'}"
                        )
                        assert random.getstate() == python_rng_before, (
                            f"PairBot consumed global Python RNG case={case - 1}"
                        )
                        if rng_mode == "seed":
                            assert game.rng.records == [], (
                                f"PairBot emitted seed-RNG draws case={case - 1}"
                            )
                        return action

                    primary_action = audited_decision(primary)
                    reversed_action = audited_decision(reversed_deck)
                    alternate_action = audited_decision(alternate_rng)
                    assert primary_action == reversed_action, (
                        f"randomized decision depends on deck order case={case - 1}, "
                        f"boss={boss_key or 'none'}: {primary_action} != {reversed_action}"
                    )
                    assert primary_action == alternate_action, (
                        f"randomized decision depends on run RNG case={case - 1}, "
                        f"boss={boss_key or 'none'}: {primary_action} != {alternate_action}"
                    )
                    assert primary_action["type"] in ("play", "discard"), primary_action
                    seen_actions.add(primary_action["type"])
                    if primary_action["type"] == "play":
                        selected = tuple(sorted(primary_action["cards"]))
                        assert selected in _reference_legal_subsets(primary, active_boss), (
                            f"PairBot returned an illegal randomized play case={case - 1}, "
                            f"boss={active_boss}: {selected}"
                        )
                    else:
                        selected = primary_action["cards"]
                        assert 0 < len(selected) <= 5
                        assert len(selected) == len(set(selected))
                        assert all(0 <= index < len(primary.hand) for index in selected)

        expected_boss_states = {
            (mode, boss, enabled)
            for mode in ("generic", "seed")
            for boss in boss_keys
            for enabled in ((False, True) if boss else (False,))
        }
        assert seen_boss_states == expected_boss_states
        assert seen_actions == {"play", "discard"}
        assert len(seen_hand_compositions) == case

    def test_discard_farming_trading_card(self):
        bot = PairBot()
        game = BalatroGame(seed=456)
        game.state = State.SELECTING_HAND
        game.jokers = [MockJoker("j_trading")]
        game.discards_left = 2
        game.hands_left = 3
        game.current_blind.chips_target = 30
        game.hand = [
            make_card(10, "Spades"),
            make_card(10, "Hearts"),
            make_card(2, "Clubs"),
        ]
        action = bot._pair_decide_hand(game)
        assert action["type"] == "discard"
        assert action["cards"] == [2]

    def test_discard_farming_purple_seal(self):
        bot = PairBot()
        game = BalatroGame(seed=456)
        game.state = State.SELECTING_HAND
        game.consumable_hand = []
        game.discards_left = 1
        game.hands_left = 2
        game.current_blind.chips_target = 30
        game.hand = [
            make_card(10, "Spades"),
            make_card(10, "Hearts"),
            make_card(4, "Diamonds", seal="Purple"),
        ]
        action = bot._pair_decide_hand(game)
        assert action["type"] == "discard"
        assert action["cards"] == [2]

    def test_discard_farming_mail_in_rebate(self):
        bot = PairBot()
        game = BalatroGame(seed=456)
        game.state = State.SELECTING_HAND
        j = MockJoker("j_mail")
        j.state = {"rebate_rank": 7}
        game.jokers = [j]
        game.discards_left = 1
        game.hands_left = 2
        game.current_blind.chips_target = 30
        game.hand = [
            make_card(10, "Spades"),
            make_card(10, "Hearts"),
            make_card(7, "Clubs"),
            make_card(3, "Diamonds"),
        ]
        action = bot._pair_decide_hand(game)
        assert action["type"] == "discard"
        assert action["cards"] == [2]

    def test_discard_farming_faceless(self):
        bot = PairBot()
        game = BalatroGame(seed=456)
        game.state = State.SELECTING_HAND
        game.jokers = [MockJoker("j_faceless")]
        game.discards_left = 1
        game.hands_left = 2
        game.current_blind.chips_target = 30
        game.hand = [
            make_card(10, "Spades"),
            make_card(10, "Hearts"),
            make_card(11, "Clubs"),
            make_card(12, "Diamonds"),
            make_card(13, "Spades"),
        ]
        action = bot._pair_decide_hand(game)
        assert action["type"] == "discard"
        assert set(action["cards"]) == {2, 3, 4}

    def test_death_tarot_prioritizes_blue_seal(self):
        bot = PairBot()
        game = BalatroGame(seed=789)
        game.state = State.SELECTING_HAND
        game.jokers = [MockJoker("j_walkie_talkie")]  # Anchor rank is 10
        game.consumable_hand = ["c_death"]
        game.hand = [
            make_card(10, "Spades"),               # Index 0: Anchor rank
            make_card(4, "Hearts", seal="Blue"),   # Index 1: Blue Seal
            make_card(2, "Clubs"),                 # Index 2: Junk
        ]
        action = bot._pair_decide_hand(game)
        assert action["type"] == "use_consumable"
        assert action["consumable_idx"] == 0
        dst, src = action["target_cards"]
        assert src == 1  # Blue Seal card is duplicated
        assert dst == 2  # Junk card is overwritten

    def test_death_tarot_prioritizes_steel(self):
        bot = PairBot()
        game = BalatroGame(seed=789)
        game.state = State.SELECTING_HAND
        game.jokers = [MockJoker("j_walkie_talkie")]  # Anchor rank is 10
        game.consumable_hand = ["c_death"]
        game.hand = [
            make_card(10, "Spades"),                     # Index 0: Anchor rank
            make_card(5, "Diamonds", enhancement="Steel"),# Index 1: Steel Card
            make_card(2, "Clubs"),                       # Index 2: Junk
        ]
        action = bot._pair_decide_hand(game)
        assert action["type"] == "use_consumable"
        assert action["consumable_idx"] == 0
        dst, src = action["target_cards"]
        assert src == 1  # Steel card is duplicated
        assert dst == 2  # Junk card is overwritten

    def test_booster_standard_pack_picks_blue_seal(self):
        bot = PairBot()
        game = BalatroGame(seed=789)
        game.state = State.BOOSTER_OPEN
        game.booster_picks_remaining = 1
        game.booster_choices = [
            ("card", make_card(8, "Clubs")),
            ("card", make_card(5, "Diamonds", seal="Blue")),
            ("card", make_card(9, "Hearts", enhancement="Bonus")),
        ]
        action = bot._decide_booster(game)
        assert action["type"] == "pick_booster"
        assert action["indices"] == [1]

    def test_booster_standard_pack_picks_steel(self):
        bot = PairBot()
        game = BalatroGame(seed=789)
        game.state = State.BOOSTER_OPEN
        game.booster_picks_remaining = 1
        game.booster_choices = [
            ("card", make_card(8, "Clubs")),
            ("card", make_card(5, "Diamonds", enhancement="Steel")),
            ("card", make_card(9, "Hearts")),
        ]
        action = bot._decide_booster(game)
        assert action["type"] == "pick_booster"
        assert action["indices"] == [1]

    def test_shop_ranking_is_deterministic_and_keeps_best_buy_first(self):
        game = BalatroGame(seed=134)
        game.state = State.SHOP
        game.ante = 3
        game.dollars = 20
        game.jokers = [MockJoker("j_jolly")]
        game.current_shop = [
            make_shop_item("joker", "j_blueprint", 10),
            make_shop_item("voucher", "v_overstock", 10),
            make_shop_item("tarot", "c_hermit", 3),
        ]
        ranked_a = _rank_shop_items(game)
        ranked_b = _rank_shop_items(game)
        assert ranked_a == ranked_b
        buys, _ = ranked_a
        assert buys
        values = [value for value, _ in buys]
        assert values == sorted(values, reverse=True)
        assert len({index for _, index in buys}) == len(buys)
        assert all(math.isfinite(value) for value in values)

    def test_open_slot_joker_price_penalty_is_applied_once(self, monkeypatch):
        game = BalatroGame(seed=135)
        game.state = State.SHOP
        game.ante = 3
        game.dollars = 20
        game.joker_slots = 2
        game.current_shop = [make_shop_item("joker", "j_cavendish", 4)]
        monkeypatch.setattr(pair_policy, "_pair_price_penalty", lambda _game, price: 0.25 if price else 0.0)
        monkeypatch.setattr(
            pair_policy,
            "_eval_joker_utility",
            lambda _game, _key, _edition, price=0, *_args, **_kwargs: 2.0 - (0.25 if price else 0.0),
        )

        buys, _ = _rank_shop_items(game)
        assert len(buys) == 1
        assert buys[0][1] == 0
        assert buys[0][0] == pytest.approx(1.75)

    def test_full_slot_swap_considers_each_owned_joker(self, monkeypatch):
        game = BalatroGame(seed=135)
        game.state = State.SHOP
        game.ante = 4
        game.dollars = 6
        game.joker_slots = 2
        game.jokers = [MockJoker("j_drunkard"), MockJoker("j_half")]
        game.current_shop = [make_shop_item("joker", "j_cavendish", 8)]
        monkeypatch.setattr(pair_policy, "_eval_candidate_swap_utility", lambda g, key, edition, sell_idx, *a: 3.0 if sell_idx == 0 else 2.0)
        monkeypatch.setattr(pair_policy, "_eval_owned_joker_value", lambda g, idx, *a: 0.0 if idx == 0 else 1.5)

        buys, swap = _rank_shop_items(game)
        assert buys == []
        assert swap is not None
        assert swap[1] == 0

    def test_swap_handshake_buys_target_after_sell(self):
        bot = PairBot()
        game = BalatroGame(seed=789)
        game.state = State.SHOP
        game.ante = 4
        game.dollars = 10
        game.joker_slots = 5
        game.jokers = [
            MockJoker("j_jolly"), MockJoker("j_bull"), MockJoker("j_sly"),
            MockJoker("j_half"), MockJoker("j_stone_joker"),
        ]
        game.current_shop = [make_shop_item("joker", "j_duo", 8)]
        first = bot._search_shop(game)
        assert first == {"type": "sell_joker", "joker_idx": 4}
        assert bot._pending_swap_target_idx == 0
        assert bot._action_queue == []

        game.jokers.pop(first["joker_idx"])
        game.dollars += 2
        second = bot._search_shop(game)
        assert second == {"type": "buy", "item_idx": 0}
        assert bot._pending_swap_target_idx is None

    def test_flat_to_xmult_swap_engine(self):
        bot = PairBot()
        game = BalatroGame(seed=789)
        game.state = State.SHOP
        game.ante = 4
        game.dollars = 10
        game.joker_slots = 5
        game.jokers = [
            MockJoker("j_jolly"),
            MockJoker("j_bull"),
            MockJoker("j_sly"),
            MockJoker("j_half"),
            MockJoker("j_stone_joker"),
        ]
        # Shop has The Duo (x2 Mult)
        item = type("MockItem", (), {
            "kind": "joker",
            "key": "j_duo",
            "cost": 8,
            "sold": False,
            "edition": "None",
            "discounted_price": lambda self, disc: 8,
        })()
        game.current_shop = [item]

        action = bot._search_shop(game)
        # Principled swap engine identifies Stone Joker (index 4) as providing 0 value (no stone cards)
        assert action["type"] == "sell_joker"
        assert action["joker_idx"] == 4
        assert bot._pending_swap_target_idx == 0
        assert bot._action_queue == []

    def test_seeded_randomized_boss_play_selection_matches_legality_oracle(self, monkeypatch):
        rng = random.Random(0xBA1A7)
        bot = PairBot()

        # Selection legality is the subject here; a deterministic cheap scorer
        # keeps this differential test focused and avoids benchmarking policy quality.
        monkeypatch.setattr(
            pair_policy,
            "eval_hand_score",
            lambda _game, _type, scoring, cards, **_kwargs: 100 + len(cards) + sum(c.rank for c in scoring),
        )

        # One randomized hand per implemented boss, plus no-boss and disabled
        # versions of every boss that imposes a play-selection restriction.
        boss_cases = [(boss_key, False) for boss_key in BOSS_BLINDS]
        boss_cases.append(("", False))
        boss_cases.extend(
            (boss_key, True)
            for boss_key in ("bl_psychic", "bl_eye", "bl_mouth", "bl_cerulean")
        )
        rng.shuffle(boss_cases)
        assert {boss_key for boss_key, disabled in boss_cases if boss_key and not disabled} == set(BOSS_BLINDS)

        for case, (boss_key, disabled) in enumerate(boss_cases):
            game = BalatroGame(seed=9100 + case)
            game.ante = 2  # avoid the Ante-1 opening override
            game.state = State.SELECTING_HAND
            game.hands_left = 1
            game.discards_left = 0
            game.current_blind.boss_key = boss_key
            game.current_blind.is_boss = bool(boss_key)
            game.current_blind.chips_target = 10**9
            game.boss_disabled_override = disabled
            # Six cards exercise Psychic's exact-five rule; other cases use
            # only five or six cards to keep exhaustive differential checks small.
            size = 6 if boss_key == "bl_psychic" else rng.randint(5, 6)
            _randomize_hand(game, rng, size)

            active_boss = boss_key if game._boss_effects_on() else ""
            if active_boss == "bl_cerulean":
                game.bell_card = rng.choice(game.hand)
            _random_played_types(game, active_boss, rng)

            oracle = _reference_legal_subsets(game, active_boss)
            assert oracle, f"fixture must include a legal subset (case={case}, boss={active_boss})"

            if active_boss != "bl_cerulean":
                # validate_play_subset covers explicit Psychic/Eye/Mouth
                # restrictions, but not Cerulean's engine-side auto-inclusion
                # of the Bell card; the independent oracle handles that case.
                candidate_subsets = (
                    combo
                    for size in ((5,) if active_boss == "bl_psychic" else range(1, min(5, len(game.hand)) + 1))
                    for combo in itertools.combinations(range(len(game.hand)), size)
                )
                assert oracle == {
                    combo for combo in candidate_subsets
                    if validate_play_subset(
                        combo, game.hand, active_boss, game.played_hand_types_this_round
                    )
                }, f"reference legality disagrees with subset validator (case={case}, boss={active_boss})"

            action = bot._pair_decide_hand(game)
            assert action["type"] == "play", f"legal play was available (case={case}, boss={active_boss}): {action}"
            selected = tuple(sorted(action["cards"]))
            assert len(selected) == len(set(selected))
            assert selected in oracle, (
                f"PairBot selected illegal subset {selected} in case={case}, "
                f"boss={active_boss}, prior={game.played_hand_types_this_round}"
            )

    @pytest.mark.parametrize(
        "boss_key",
        (
            "bl_goad", "bl_club", "bl_window", "bl_head", "bl_plant",
            "bl_mark", "bl_wheel", "bl_manacle", "bl_needle", "bl_water",
            "bl_cerulean", "bl_verdant", "bl_amber", "bl_house", "bl_pillar",
        ),
    )
    def test_boss_start_effects_and_disable_override(self, boss_key):
        active = _start_boss_effect_game(boss_key)
        disabled = _start_boss_effect_game(boss_key, disabled=True)

        if boss_key in {"bl_goad", "bl_club", "bl_window", "bl_head"}:
            suit = {
                "bl_goad": "Spades", "bl_club": "Clubs",
                "bl_window": "Diamonds", "bl_head": "Hearts",
            }[boss_key]
            assert any(card.suit == suit for card in active.hand)
            assert all(card.debuffed == (card.suit == suit) for card in active.hand)
            assert not any(card.debuffed for card in disabled.hand)
        elif boss_key == "bl_plant":
            assert any(card.is_face_card for card in active.hand)
            assert all(card.debuffed == card.is_face_card for card in active.hand)
            assert not any(card.debuffed for card in disabled.hand)
        elif boss_key == "bl_mark":
            assert any(card.is_face_card for card in active.hand)
            assert all(card.flipped == card.is_face_card for card in active.hand)
            assert not any(card.flipped for card in disabled.hand)
        elif boss_key == "bl_wheel":
            assert active.hand and all(card.flipped for card in active.hand)
            assert not any(card.flipped for card in disabled.hand)
        elif boss_key == "bl_house":
            assert active.hand and all(card.flipped for card in active.hand)
            assert not any(card.flipped for card in disabled.hand)
        elif boss_key == "bl_manacle":
            assert active.hand_size == disabled.hand_size - 1
            assert len(active.hand) == active.hand_size
            # Completing the blind restores permanent hand-size modifiers.
            active._end_round()
            assert active.hand_size == HAND_SIZE + active.hand_size_mod
        elif boss_key == "bl_needle":
            assert active.hands_left == 1
            assert disabled.hands_left == disabled.base_hands
        elif boss_key == "bl_water":
            assert active.discards_left == 0
            assert disabled.discards_left == disabled.base_discards
        elif boss_key == "bl_cerulean":
            assert active.bell_card in active.hand
            assert disabled.bell_card is None
        elif boss_key == "bl_verdant":
            assert active.verdant_debuff and all(card.debuffed for card in active.hand + active.deck)
            assert not disabled.verdant_debuff and not any(card.debuffed for card in disabled.hand + disabled.deck)
        elif boss_key == "bl_amber":
            assert active.jokers_flipped
            assert not disabled.jokers_flipped
        elif boss_key == "bl_pillar":
            active_card = next(
                card for card in active.hand + active.deck
                if card.id in active.ante_played_ids
            )
            disabled_card = next(
                card for card in disabled.hand + disabled.deck
                if (card.rank, card.suit) == (active_card.rank, active_card.suit)
            )
            assert active_card.debuffed
            assert not disabled_card.debuffed

    @pytest.mark.parametrize(
        ("boss_key", "ante", "multiplier"),
        (("bl_wall", 7, 4), ("bl_violet", 8, 6), ("bl_needle", 7, 1)),
    )
    @pytest.mark.parametrize("disabled", (False, True))
    def test_boss_blind_score_scaling_respects_disable_override(self, boss_key, ante, multiplier, disabled):
        game = BalatroGame(seed=138)
        game.ante = ante
        game.blind_idx = 2
        game.boss_disabled_override = disabled
        game.next_boss_key = boss_key
        game._prepare_next_blind()

        if boss_key == "bl_needle":
            expected = BLIND_CHIPS[ante][0]
        elif disabled:
            expected = BLIND_CHIPS[ante][2]
        else:
            expected = BLIND_CHIPS[ante][0] * multiplier
        assert game.current_blind.boss_key == boss_key
        assert game.current_blind.chips_target == expected

    @pytest.mark.parametrize("boss_key", ("bl_fish", "bl_hook", "bl_serpent"))
    @pytest.mark.parametrize("disabled", (False, True))
    def test_boss_play_draw_and_discard_effects_respect_disable_override(self, boss_key, disabled):
        game = _start_boss_effect_game(boss_key, disabled=disabled)
        before = list(game.hand)
        before_ids = {id(card) for card in before}

        game.step({"type": "play", "cards": [0]})
        new_cards = [card for card in game.hand if id(card) not in before_ids]
        expected_delta = 0 if disabled or boss_key == "bl_fish" else -2 if boss_key == "bl_hook" else 2
        assert len(game.hand) == len(before) + expected_delta

        if boss_key == "bl_fish":
            assert len(new_cards) == 1
            assert new_cards[0].flipped is (not disabled)
        elif boss_key == "bl_serpent":
            assert len(new_cards) == (1 if disabled else 3)

    @pytest.mark.parametrize("disabled", (False, True))
    def test_serpent_draws_three_after_discard_only_when_enabled(self, disabled):
        game = _start_boss_effect_game("bl_serpent", disabled=disabled)
        before_ids = {id(card) for card in game.hand}

        game.step({"type": "discard", "cards": [0]})
        new_cards = [card for card in game.hand if id(card) not in before_ids]
        assert len(new_cards) == (3 if not disabled else 1)
        assert len(game.hand) == (len(before_ids) + 2 if not disabled else len(before_ids))

    @pytest.mark.parametrize("boss_key", ("bl_eye", "bl_mouth"))
    @pytest.mark.parametrize("disabled", (False, True))
    def test_boss_hand_type_lock_and_disabled_play(self, boss_key, disabled):
        game = _start_boss_effect_game(boss_key, disabled=disabled)
        game.hand = [make_card(2, "Spades")]
        game.deck = []
        game.hand_size = 1
        game.hands_left = 2
        game.played_hand_types_this_round = {
            "High Card" if boss_key == "bl_eye" else "Pair"
        }

        game.step({"type": "play", "cards": [0]})
        if disabled:
            assert game.chips_scored > 0
        else:
            assert game.chips_scored == 0
        assert game.hands_left == 1

    @pytest.mark.parametrize("boss_key", ("bl_eye", "bl_mouth"))
    @pytest.mark.parametrize("disabled", (False, True))
    def test_start_of_blind_resets_hand_type_lock(self, boss_key, disabled):
        game = _start_boss_effect_game(
            boss_key, disabled=disabled, played_types=("Pair",),
        )
        # The same game instance must clear prior-round hand-type locks before
        # either boss-specific restriction can affect this blind.
        assert game._boss_effects_on() is (not disabled)
        assert game.played_hand_types_this_round == set()

    @pytest.mark.parametrize("disabled", (False, True))
    def test_crimson_heart_disables_joker_only_while_boss_is_active(self, disabled):
        game = _start_boss_effect_game("bl_crimson", disabled=disabled)
        game.jokers = [JokerInstance("j_jolly", game=game)]
        game.hand = [make_card(10, "Spades"), make_card(10, "Hearts")]
        game.deck = []
        game.hand_size = 2
        game.hands_left = 2

        game.step({"type": "play", "cards": [0, 1]})
        active_score = game.chips_scored
        baseline = _start_boss_effect_game("bl_crimson", disabled=True)
        baseline.jokers = [JokerInstance("j_jolly", game=baseline)]
        baseline.hand = [make_card(10, "Spades"), make_card(10, "Hearts")]
        baseline.deck = []
        baseline.hand_size = 2
        baseline.hands_left = 2
        baseline.step({"type": "play", "cards": [0, 1]})
        if disabled:
            assert active_score == baseline.chips_scored
        else:
            # With a single joker Crimson Heart must disable it for this hand.
            assert active_score < baseline.chips_scored

    @pytest.mark.parametrize("boss_key", ("bl_tooth", "bl_ox", "bl_grim", "bl_flint"))
    @pytest.mark.parametrize("disabled", (False, True))
    def test_boss_scoring_economy_and_level_effects_respect_disable_override(self, boss_key, disabled):
        game = _start_boss_effect_game(boss_key, disabled=disabled)
        game.hand = [make_card(10, "Spades")]
        game.deck = [make_card(7, "Hearts")]
        game.hand_size = 1
        game.hands_left = 2
        game.dollars = 20
        game.planet_levels["High Card"] = 3

        game.step({"type": "play", "cards": [0]})
        if boss_key == "bl_tooth":
            assert game.dollars == 20 - (0 if disabled else 1)
        elif boss_key == "bl_ox":
            assert game.dollars == (20 if disabled else 0)
        elif boss_key == "bl_grim":
            assert game.planet_levels["High Card"] == (3 if disabled else 2)
        else:
            # Flint halves the hand's base chips and multiplier only while active.
            assert game.chips_scored > 0
            active_score = game.chips_scored
            baseline = _start_boss_effect_game("bl_flint", disabled=True)
            baseline.hand = [make_card(10, "Spades")]
            baseline.deck = [make_card(7, "Hearts")]
            baseline.hand_size = 1
            baseline.hands_left = 2
            baseline.planet_levels["High Card"] = 3
            baseline.step({"type": "play", "cards": [0]})
            if disabled:
                assert active_score == baseline.chips_scored
            else:
                assert active_score < baseline.chips_scored

    def test_pair_hand_decision_does_not_reorder_owned_jokers(self):
        game = BalatroGame(seed=1500)
        game.ante = 2
        game.state = State.SELECTING_HAND
        game.hands_left = 2
        game.discards_left = 0
        game.current_blind.chips_target = 10**6
        game.hand = [
            make_card(10, "Spades"), make_card(10, "Hearts"),
            make_card(2, "Clubs"), make_card(4, "Diamonds"),
            make_card(6, "Clubs"), make_card(8, "Hearts"),
        ]
        game.jokers = [
            JokerInstance("j_blueprint", game=game),
            JokerInstance("j_jolly", game=game),
            JokerInstance("j_brainstorm", game=game),
        ]
        original_order = list(game.jokers)
        action = PairBot()._pair_decide_hand(game)
        assert action["type"] == "play"
        assert game.jokers == original_order

    def test_seeded_randomized_hand_decisions_isolate_game_and_rng_state(self):
        rng = random.Random(0x1501A7E)
        bot = PairBot()
        stateful_keys = (
            "j_green_joker", "j_ice_cream", "j_ride_the_bus", "j_hiker",
            "j_popcorn", "j_ramen", "j_lucky_cat", "j_constellation",
        )
        bosses = ("", "bl_eye", "bl_mouth", "bl_psychic", "bl_cerulean")

        for case in range(10):
            rng_mode = "seed" if case % 2 else "generic"
            game = BalatroGame(seed=f"state-{case}" if rng_mode == "seed" else 12000 + case, rng_mode=rng_mode)
            boss_key = bosses[case % len(bosses)]
            game.ante = 2
            game.state = State.SELECTING_HAND
            game.hands_left = 1
            game.discards_left = 0
            game.current_blind.boss_key = boss_key
            game.current_blind.is_boss = bool(boss_key)
            game.current_blind.chips_target = 10**9
            _randomize_hand(game, rng, 5 if boss_key == "bl_psychic" else rng.randint(5, 6))
            # Assign a freshly sampled rank for each card so the exact hand
            # oracle checks meaningful Pair-vs-tactical ranking outcomes.
            for card in game.hand:
                card.rank = rng.randrange(2, 15)
                card.enhancement = "None"
                card.seal = "None"
                card.debuffed = False

            active_boss = boss_key if game._boss_effects_on() else ""
            if active_boss == "bl_cerulean":
                game.bell_card = rng.choice(game.hand)
            _random_played_types(game, active_boss, rng)

            # Include a scoring hook that mutates its instance while scoring,
            # plus randomly chosen companions whose state/card effects are also
            # evaluated only on PairBot's isolated counterfactual copies.
            primary = rng.choice(("j_green_joker", "j_ice_cream", "j_ride_the_bus"))
            companions = rng.sample(
                [key for key in stateful_keys if key != primary],
                rng.randint(0, 2),
            )
            game.jokers = [JokerInstance(key, game=game) for key in (primary, *companions)]
            if primary == "j_green_joker":
                game.jokers[0].state["mult"] = rng.randint(0, 5)
            if rng_mode == "seed":
                game.rng.enable_tracing()

            before = _game_runtime_snapshot(game)
            python_rng_before = random.getstate()
            action = bot._pair_decide_hand(game)
            assert action["type"] == "play", f"fixture expected a play action in case={case}: {action}"
            assert _game_runtime_snapshot(game) == before, f"PairBot mutated live game state in case={case}"
            assert random.getstate() == python_rng_before, f"PairBot consumed global Python RNG in case={case}"

            original_deck = list(game.deck)
            game.deck.reverse()
            reversed_action = bot._pair_decide_hand(game)
            game.deck = original_deck
            assert reversed_action == action, (
                f"PairBot used hidden deck order in state-isolation case={case}, "
                f"boss={active_boss}, jokers={[joker.key for joker in game.jokers]}"
            )
            assert _game_runtime_snapshot(game) == before
            assert random.getstate() == python_rng_before

            selected = tuple(sorted(action["cards"]))
            if active_boss:
                assert selected in _reference_legal_subsets(game, active_boss), (
                    f"PairBot selected an illegal play in state-isolation case={case}, boss={active_boss}"
                )

    def test_seeded_randomized_play_choices_match_exact_pair_tactical_oracle(self):
        rng = random.Random(0xE7AC7)
        bot = PairBot()
        boss_cases = ("", "bl_psychic", "bl_eye", "bl_mouth", "bl_cerulean")

        for case in range(16):
            game = BalatroGame(seed=24000 + case)
            game.ante = 2
            game.state = State.SELECTING_HAND
            game.hands_left = 1
            game.discards_left = 0
            game.current_blind.boss_key = boss_cases[case % len(boss_cases)]
            game.current_blind.is_boss = bool(game.current_blind.boss_key)
            game.current_blind.chips_target = 10**9
            size = 5 if game.current_blind.boss_key == "bl_psychic" else 6
            _randomize_hand(game, rng, size)
            for card in game.hand:
                card.rank = rng.randrange(2, 15)
                card.enhancement = "None"
                card.seal = "None"
                card.debuffed = False

            boss = game.current_blind.boss_key if game._boss_effects_on() else ""
            if boss == "bl_cerulean":
                game.bell_card = game.hand[rng.randrange(len(game.hand))]
            if boss in ("bl_eye", "bl_mouth"):
                _random_played_types(game, boss, rng)

            oracle_best = _pair_decision_oracle_score(game, boss)
            action = bot._pair_decide_hand(game)
            assert action["type"] == "play", f"expected play from exact-oracle fixture {case}: {action}"
            original_deck = list(game.deck)
            game.deck.reverse()
            reversed_deck_action = bot._pair_decide_hand(game)
            game.deck = original_deck
            assert reversed_deck_action == action, (
                f"PairBot used hidden deck order in exact-oracle fixture {case}: "
                f"{action} != {reversed_deck_action}"
            )
            selected = tuple(sorted(action["cards"]))
            assert selected in _reference_legal_subsets(game, boss), (
                f"PairBot selected illegal subset {selected} in case={case}, boss={boss}"
            )
            selected_indices = list(selected)
            selected_cards = [game.hand[index] for index in selected]
            if boss == "bl_cerulean" and game.bell_card is not None:
                for bell_index, card in enumerate(game.hand):
                    if card is game.bell_card:
                        if bell_index not in selected:
                            selected_indices.append(bell_index)
                            selected_cards.append(card)
                        break
            selected_type, selected_scoring = evaluate_hand(selected_cards)
            selected_set = set(selected_indices)
            selected_held = [
                card for index, card in enumerate(game.hand) if index not in selected_set
            ]
            selected_score = pair_policy.eval_hand_score(
                game, selected_type, selected_scoring, selected_cards,
                held_cards=selected_held,
            )
            assert selected_score == oracle_best, (
                f"PairBot score {selected_score} below exact Pair/tactical maximum "
                f"{oracle_best} in case={case}, boss={boss}, hand={game.hand}, "
                f"selected={selected}"
            )

    def test_enhanced_cards_and_retrigger_jokers_match_exact_play_oracle(self):
        rng = random.Random(0xE7A7E)
        bot = PairBot()
        boss_cases = ("", "bl_psychic", "bl_eye", "bl_mouth", "bl_cerulean")
        retrigger_cases = (
            ("j_hack",),
            ("j_sock_and_buskin",),
            ("j_hanging_chad",),
            ("j_dusk",),
            ("j_mime",),
            ("j_seltzer",),
            ("j_blueprint", "j_hack"),
            ("j_hack", "j_brainstorm"),
            ("j_blueprint", "j_sock_and_buskin"),
            ("j_sock_and_buskin", "j_brainstorm"),
            ("j_blueprint", "j_hanging_chad"),
            ("j_hanging_chad", "j_brainstorm"),
            ("j_blueprint", "j_seltzer"),
            ("j_seltzer", "j_brainstorm"),
            ("j_hack", "j_hanging_chad", "j_seltzer", "j_dusk"),
        )
        copy_retrigger_cases = {
            ("j_blueprint", "j_hack"): (0, 1, False),
            ("j_hack", "j_brainstorm"): (1, 0, False),
            ("j_blueprint", "j_sock_and_buskin"): (0, 1, False),
            ("j_sock_and_buskin", "j_brainstorm"): (1, 0, False),
            ("j_blueprint", "j_hanging_chad"): (0, 1, True),
            ("j_hanging_chad", "j_brainstorm"): (1, 0, True),
            ("j_blueprint", "j_seltzer"): (0, 1, False),
            ("j_seltzer", "j_brainstorm"): (1, 0, False),
        }
        enhancement_cycle = (
            "None", "Bonus", "Mult", "Stone", "Wild", "Glass", "Lucky", "Gold",
        )
        seal_cycle = ("None", "Red", "Gold", "Purple")
        seen_enhancements = set()
        seen_retriggers = set()

        # Cross each retrigger family with all implemented boss-selection
        # paths. Five cards keep the exhaustive oracle tiny and ensure PairBot's
        # bounded Pair attachments include every possible filler.
        for family_idx, joker_keys in enumerate(retrigger_cases):
            for boss_idx, boss_key in enumerate(boss_cases):
                case = family_idx * len(boss_cases) + boss_idx
                game = BalatroGame(seed=26000 + case)
                game.ante = 2
                game.state = State.SELECTING_HAND
                game.hands_left = (
                    1 if "j_dusk" in joker_keys and boss_idx % 2 == 0
                    else rng.randint(2, 4) if "j_dusk" in joker_keys
                    else rng.randint(1, 4)
                )
                game.discards_left = 0
                game.current_blind.boss_key = boss_key
                game.current_blind.is_boss = bool(boss_key)
                game.current_blind.chips_target = 10**9
                _randomize_hand(game, rng, 5)

                pair_rank = rng.choice((2, 3, 4, 5) if "j_hack" in joker_keys else
                                       (11, 12, 13) if "j_sock_and_buskin" in joker_keys else
                                       tuple(range(2, 15)))
                game.hand[0].rank = pair_rank
                game.hand[1].rank = pair_rank
                other_ranks = [rank for rank in range(2, 15) if rank != pair_rank]
                rng.shuffle(other_ranks)
                for card, rank in zip(game.hand[2:], other_ranks):
                    card.rank = rank

                for index, card in enumerate(game.hand):
                    card.enhancement = enhancement_cycle[(case + 3 * index) % len(enhancement_cycle)]
                    if index < 2 and card.enhancement == "Stone":
                        # Keep a genuine two-card Pair; Stone rank is ignored
                        # by poker evaluation and is covered on filler cards.
                        card.enhancement = "Bonus"
                    elif index >= 2 and card.enhancement == "Gold":
                        # PairBot deliberately keeps held-value Gold cards;
                        # reserve Gold for a paired card so the exhaustive
                        # legal-play oracle and policy candidate space align.
                        card.enhancement = "Mult"
                    card.seal = seal_cycle[(case + 2 * index) % len(seal_cycle)]
                    card.debuffed = False
                    card.flipped = False
                # A Red-sealed scoring card exercises the seal retrigger path.
                game.hand[0].seal = "Red"
                if "j_mime" in joker_keys:
                    # Mime + Red Steel yields three held-in-hand Steel procs.
                    # Make every filler valuable to hold so the exhaustive
                    # legal-play maximum respects PairBot's held-card policy.
                    for card in game.hand[2:]:
                        card.enhancement = "Steel"
                        card.seal = "Red"
                else:
                    # Include a played Gold Card, but never make a filler a
                    # held-value Gold/Steel card the policy intentionally keeps.
                    game.hand[0].enhancement = "Gold"
                seen_enhancements.update(card.enhancement for card in game.hand)

                active_boss = boss_key if game._boss_effects_on() else ""
                if active_boss == "bl_cerulean":
                    game.bell_card = game.hand[rng.randrange(len(game.hand))]
                if active_boss in ("bl_eye", "bl_mouth"):
                    _random_played_types(game, active_boss, rng)

                game.jokers = [JokerInstance(key, game=game) for key in joker_keys]
                if "j_seltzer" in joker_keys:
                    # Exercise the last-use state transition in the isolated
                    # oracle without allowing it to mutate the owned joker.
                    next(joker for joker in game.jokers if joker.key == "j_seltzer").state["hands"] = 1
                seen_retriggers.update(joker_keys)

                before = _game_runtime_snapshot(game)
                joker_order_before = tuple(game.jokers)
                joker_states_before = deepcopy([joker.state for joker in game.jokers])
                game_rng_before = _rng_snapshot(game)
                python_rng_before = random.getstate()
                copy_case = copy_retrigger_cases.get(joker_keys)
                if copy_case is not None:
                    copy_index, source_index, shared_one_shot_state = copy_case
                    pair_cards = game.hand[:2]
                    pair_type, pair_scoring = evaluate_hand(pair_cards)
                    pair_held = game.hand[2:]
                    copied_score = pair_policy.eval_hand_score(
                        game, pair_type, pair_scoring, pair_cards, held_cards=pair_held,
                    )
                    source_only_score = pair_policy.eval_hand_score(
                        game, pair_type, pair_scoring, pair_cards,
                        held_cards=pair_held, exclude_joker=copy_index,
                    )
                    copy_only_score = pair_policy.eval_hand_score(
                        game, pair_type, pair_scoring, pair_cards,
                        held_cards=pair_held, exclude_joker=source_index,
                    )
                    no_retrigger_game = shallowcopy(game)
                    no_retrigger_game.jokers = [
                        joker for index, joker in enumerate(game.jokers)
                        if index not in (copy_index, source_index)
                    ]
                    no_retrigger_score = pair_policy.eval_hand_score(
                        no_retrigger_game, pair_type, pair_scoring, pair_cards,
                        held_cards=pair_held,
                    )
                    assert copied_score > no_retrigger_score, (
                        f"copy did not add its retrigger effect in case={case}, "
                        f"jokers={joker_keys}"
                    )
                    if shared_one_shot_state:
                        # Hanging Chad's copied hook and native hook share the
                        # target instance state, so the first invocation marks
                        # it fired and the second does not add another retrigger.
                        assert copied_score == source_only_score
                    else:
                        assert copied_score > source_only_score, (
                            f"copy did not duplicate its target's retrigger in case={case}, "
                            f"jokers={joker_keys}"
                        )
                    assert copied_score > copy_only_score, (
                        f"retrigger copy did not score when its source was removed in case={case}, "
                        f"jokers={joker_keys}"
                    )
                if "j_dusk" in joker_keys:
                    # In a hand-selection state the evaluator must model the
                    # post-play count: Dusk retriggers only when this is the
                    # final available hand. Compare the same cards in both
                    # contexts to ensure the retrigger is exercised.
                    pair_cards = game.hand[:2]
                    pair_type, pair_scoring = evaluate_hand(pair_cards)
                    original_hands_left = game.hands_left
                    try:
                        game.hands_left = 1
                        last_hand_score = pair_policy.eval_hand_score(
                            game, pair_type, pair_scoring, pair_cards,
                        )
                        game.hands_left = 2
                        other_hand_score = pair_policy.eval_hand_score(
                            game, pair_type, pair_scoring, pair_cards,
                        )
                    finally:
                        game.hands_left = original_hands_left
                    assert last_hand_score > other_hand_score, (
                        "Dusk must add a scoring-card retrigger on the last hand"
                    )
                oracle_best = _pair_decision_oracle_score(game, active_boss)
                assert _pair_decision_oracle_score(game, active_boss) == oracle_best, (
                    f"isolated score oracle was not repeatable in case={case}"
                )
                assert _game_runtime_snapshot(game) == before, (
                    f"scoring oracle mutated cards or joker state in case={case}"
                )
                assert tuple(game.jokers) == joker_order_before, (
                    f"scoring oracle reordered jokers in case={case}, jokers={joker_keys}"
                )
                assert [joker.state for joker in game.jokers] == joker_states_before, (
                    f"scoring oracle mutated owned joker state in case={case}, jokers={joker_keys}"
                )
                assert _rng_snapshot(game) == game_rng_before
                assert random.getstate() == python_rng_before

                action = bot._pair_decide_hand(game)
                assert action["type"] == "play", f"expected play in enhanced case={case}: {action}"
                selected = tuple(sorted(action["cards"]))
                assert selected in _reference_legal_subsets(game, active_boss), (
                    f"PairBot selected illegal subset {selected} in case={case}, boss={active_boss}"
                )
                played_indices = list(selected)
                played_cards = [game.hand[index] for index in selected]
                if active_boss == "bl_cerulean" and game.bell_card is not None:
                    for bell_index, card in enumerate(game.hand):
                        if card is game.bell_card:
                            if bell_index not in selected:
                                played_indices.append(bell_index)
                                played_cards.append(card)
                            break
                hand_type, scoring_cards = evaluate_hand(played_cards)
                played_set = set(played_indices)
                held = [card for index, card in enumerate(game.hand) if index not in played_set]
                selected_score = pair_policy.eval_hand_score(
                    game, hand_type, scoring_cards, played_cards, held_cards=held,
                )
                assert selected_score == oracle_best, (
                    f"PairBot score {selected_score} below exact maximum {oracle_best} "
                    f"in enhanced/retrigger case={case}, boss={active_boss}, "
                    f"jokers={joker_keys}, hand={game.hand}, selected={selected}"
                )

                original_deck = list(game.deck)
                game.deck.reverse()
                reversed_action = bot._pair_decide_hand(game)
                game.deck = original_deck
                assert reversed_action == action, (
                    f"PairBot used hidden deck order in enhanced/retrigger case={case}"
                )
                assert _game_runtime_snapshot(game) == before
                assert tuple(game.jokers) == joker_order_before
                assert [joker.state for joker in game.jokers] == joker_states_before
                assert _rng_snapshot(game) == game_rng_before
                assert random.getstate() == python_rng_before

        assert seen_enhancements >= {
            "Bonus", "Mult", "Stone", "Wild", "Glass", "Lucky", "Steel", "Gold",
        }
        assert seen_retriggers == {
            "j_hack", "j_sock_and_buskin", "j_hanging_chad", "j_dusk", "j_mime",
            "j_seltzer", "j_blueprint", "j_brainstorm",
        }

    @pytest.mark.parametrize(
        ("case_name", "pair_rank", "joker_keys", "hands_left"),
        (
            ("hack-red-seal", 3, ("j_hack",), 2),
            ("sock-and-buskin", 12, ("j_sock_and_buskin",), 2),
            ("hanging-chad", 8, ("j_hanging_chad",), 2),
            ("last-hand-dusk", 4, ("j_dusk",), 1),
            ("seltzer", 8, ("j_seltzer",), 2),
            ("mime-held-steel", 8, ("j_mime",), 2),
            ("stacked-last-hand", 5, ("j_hack", "j_hanging_chad", "j_seltzer", "j_dusk"), 1),
        ),
        ids=lambda value: value if isinstance(value, str) else None,
    )
    def test_engine_step_score_matches_pair_prediction_for_enhanced_retriggers(
        self, case_name, pair_rank, joker_keys, hands_left,
    ):
        filler_ranks = [
            rank for rank in (2, 6, 8, 10, 14, 5, 9, 7)
            if rank != pair_rank
        ][:4]
        game = BalatroGame(seed=27001, rng_mode="seed")
        game.ante = 2
        game.state = State.SELECTING_HAND
        game.hands_left = hands_left
        game.discards_left = 0
        game.current_blind = BlindInfo(
            "Pair score differential", "Small", 10**9,
        )
        game.chips_scored = 73
        game.hand = [
            make_card(pair_rank, "Spades", enhancement="Bonus", seal="Red"),
            make_card(pair_rank, "Hearts", enhancement="Mult"),
            make_card(filler_ranks[0], "Clubs", enhancement="Stone"),
            make_card(filler_ranks[1], "Diamonds", enhancement="Wild"),
            make_card(filler_ranks[2], "Spades", enhancement="Bonus"),
            make_card(filler_ranks[3], "Hearts", enhancement="Mult"),
        ]
        game.hand[0].edition = "Holographic"
        game.hand[1].edition = "Foil"
        if "j_mime" in joker_keys:
            # PairBot should keep this held; Mime plus its Red seal produces
            # three deterministic Steel triggers in the real scoring pass.
            game.hand[2].enhancement = "Steel"
            game.hand[2].seal = "Red"
        game.jokers = [JokerInstance(key, game=game) for key in joker_keys]

        before = _game_runtime_snapshot(game)
        rng_before = _rng_snapshot(game)
        action = PairBot()._pair_decide_hand(game)
        assert action["type"] == "play", f"{case_name}: expected a play, got {action}"
        selected_indices = action["cards"]
        assert len(selected_indices) == len(set(selected_indices))
        selected_cards = [game.hand[index] for index in selected_indices]
        hand_type, scoring_cards = evaluate_hand(selected_cards)
        assert hand_type == "Pair", f"{case_name}: selected hand resolved as {hand_type}"
        assert game.hand[0] in scoring_cards and game.hand[1] in scoring_cards
        held_cards = [
            card for index, card in enumerate(game.hand) if index not in set(selected_indices)
        ]
        if "j_mime" in joker_keys:
            assert game.hand[2] not in selected_cards
            assert game.hand[2] in held_cards
            assert game.hand[2].enhancement == "Steel" and game.hand[2].seal == "Red"

        # Glass and Lucky intentionally stay out of engine-step fixtures: their
        # probabilistic engine triggers use the live game RNG, unlike the
        # evaluator's throwaway RNG. Bonus/Mult/Stone/Wild, editions, and seals
        # exercise only deterministic scoring paths here.
        assert not any(card.enhancement in ("Glass", "Lucky") for card in game.hand)
        predicted = pair_policy.eval_hand_score(
            game, hand_type, scoring_cards, selected_cards, held_cards=held_cards,
        )
        red_scoring_cards = [card for card in scoring_cards if card.seal == "Red"]
        assert red_scoring_cards, f"{case_name}: PairBot's play must score its Red-sealed pair card"
        red_seals = [(card, card.seal) for card in red_scoring_cards]
        try:
            for card, _seal in red_seals:
                card.seal = "None"
            without_red_seal = pair_policy.eval_hand_score(
                game, hand_type, scoring_cards, selected_cards, held_cards=held_cards,
            )
        finally:
            for card, seal in red_seals:
                card.seal = seal
        assert predicted > without_red_seal, f"{case_name}: Red Seal retrigger was not scored"

        for joker_index, joker in enumerate(game.jokers):
            without_joker = pair_policy.eval_hand_score(
                game, hand_type, scoring_cards, selected_cards,
                held_cards=held_cards, exclude_joker=joker_index,
            )
            assert predicted > without_joker, (
                f"{case_name}: {joker.key} did not increase the predicted score"
            )

        assert _game_runtime_snapshot(game) == before, f"{case_name}: prediction mutated live state"
        assert _rng_snapshot(game) == rng_before, f"{case_name}: prediction consumed the live RNG"

        score_before = game.chips_scored
        game.step(action)
        actual_score = game.chips_scored - score_before
        assert actual_score == predicted, (
            f"{case_name}: PairBot predicted {predicted}, engine scored {actual_score}; "
            f"jokers={joker_keys}, hand={game.hand}, action={action}"
        )
        assert game.run_hand_counts["Pair"] == 1
        if "j_hanging_chad" in joker_keys:
            assert next(joker for joker in game.jokers if joker.key == "j_hanging_chad").state["fired"]
        if "j_seltzer" in joker_keys:
            assert next(joker for joker in game.jokers if joker.key == "j_seltzer").state["hands"] == 9
        if "j_dusk" in joker_keys:
            assert hands_left == 1
            assert game.hands_left == 0

    def test_pair_discard_planner_is_bounded_order_independent_and_rng_isolated(self):
        rng = random.Random(0xD15CA4D)
        reference_hand = [
            make_card(10, "Hearts"), make_card(10, "Spades"),
            make_card(2, "Clubs"), make_card(4, "Diamonds"),
            make_card(6, "Clubs"), make_card(8, "Hearts"),
        ]
        game = BalatroGame(seed=25001)
        game.ante = 2
        game.state = State.SELECTING_HAND
        game.discards_left = 2
        game.hands_left = 2
        game.current_blind.chips_target = 10**6
        game.hand = reference_hand
        game.deck = [
            make_card(rank, suit)
            for rank, suit in ((2, "Hearts"), (3, "Hearts"), (5, "Hearts"),
                               (7, "Hearts"), (9, "Hearts"), (11, "Hearts"),
                               (3, "Clubs"), (5, "Clubs"), (7, "Diamonds"),
                               (9, "Spades"), (12, "Clubs"), (14, "Diamonds"))
        ]
        rng_before = _rng_snapshot(game)
        game_before = _game_runtime_snapshot(game)
        python_rng_before = random.getstate()

        forward = _pair_plan_discard(
            game, range(2, len(game.hand)), protected_indices=(0, 1),
        )
        game.deck.reverse()
        reverse = _pair_plan_discard(
            game, range(2, len(game.hand)), protected_indices=(0, 1),
        )

        assert forward is not None
        assert reverse is not None
        assert forward == reverse
        assert 0 < forward["candidate_count"] <= pair_policy._PAIR_DISCARD_SEARCH_MAX_CANDIDATES
        assert forward["sample_count"] == pair_policy._PAIR_DISCARD_SEARCH_SAMPLES
        assert 0 < forward["score_evaluations"] <= pair_policy._PAIR_DISCARD_SEARCH_SCORE_BUDGET
        assert 0 < forward["subset_evaluations"] <= pair_policy._PAIR_DISCARD_SEARCH_SUBSET_BUDGET
        assert _rng_snapshot(game) == rng_before
        # Reverse the test-only deck edit back before comparing full live state.
        game.deck.reverse()
        assert _game_runtime_snapshot(game) == game_before

        # Exercise the production decision path too: deck order is hidden, so
        # reversing an otherwise identical draw pile must not change PairBot's
        # chosen hand action (including whether it discards or plays).
        bot = PairBot()
        forward_action = bot._pair_decide_hand(game)
        game.deck.reverse()
        reverse_action = bot._pair_decide_hand(game)
        game.deck.reverse()
        assert forward_action["type"] == "discard"
        assert not set(forward_action["cards"]) & {0, 1}
        assert forward_action == reverse_action
        assert _game_runtime_snapshot(game) == game_before
        assert random.getstate() == python_rng_before

    def test_pair_discard_planner_can_choose_composition_supported_discard(self):
        game = BalatroGame(seed=25002)
        game.ante = 2
        game.state = State.SELECTING_HAND
        game.discards_left = 2
        game.hands_left = 2
        game.current_blind.chips_target = 10**6
        game.hand = [
            make_card(10, "Hearts"), make_card(10, "Spades"),
            make_card(2, "Clubs"), make_card(4, "Diamonds"),
            make_card(6, "Clubs"), make_card(8, "Hearts"),
        ]
        game.deck = [
            make_card(rank, "Hearts")
            for rank in (2, 3, 5, 7, 9, 11, 12, 13, 14)
        ] + [make_card(rank, "Clubs") for rank in (3, 5, 7, 9, 12, 14)]
        plan = _pair_plan_discard(
            game, range(2, len(game.hand)), protected_indices=(0, 1),
        )
        assert plan is not None
        assert plan["expected_score"] > plan["baseline_score"]
        assert all(index >= 2 for index in plan["indices"])
        assert not set(plan["indices"]) & {0, 1}
