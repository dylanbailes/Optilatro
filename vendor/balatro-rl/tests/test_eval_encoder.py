import copy
import math
import pickle

import pytest

from balatro_sim.game import BalatroGame
from balatro_sim.jokers.base import JokerInstance


def make_game():
    game = BalatroGame(seed=70123, rng_mode="seed")
    game.step({"type": "play_blind"})
    return game


def test_encoder_is_pure_and_ignores_undrawn_order():
    from balatro_sim.eval_encoder import encode_state

    game = make_game()
    game.grant_joker("j_castle")
    before = pickle.dumps(game)
    encoded = encode_state(game)
    assert pickle.dumps(game) == before
    game.deck.reverse()
    assert encode_state(game) == encoded
    assert len(encoded["cards"]) == len(game.hand)
    assert len(encoded["context"]) > 52


def test_rng_ids_and_future_information_are_absent():
    from balatro_sim.eval_encoder import encode_state
    from balatro_sim.seed_rng import make_source

    game = make_game()
    encoded = encode_state(game)
    game.rng = make_source(99887, "seed")
    game.next_boss_key = "bl_violet"
    game.future_shop = ["j_blueprint"]
    for card in game.deck + game.hand + game.spent:
        card.id += 100000
    assert encode_state(game) == encoded


def test_flipped_cards_mask_every_attribute_in_every_block():
    from balatro_sim.eval_encoder import encode_state, schema

    game = make_game()
    game.hand[0].flipped = True
    game.deck[0].flipped = True
    encoded = encode_state(game)
    row = encoded["cards"][0]
    hidden = schema()["card_names"].index("flipped")
    assert row[hidden] == 1
    assert sum(abs(v) for i, v in enumerate(row) if i != hidden) == 0
    for card in (game.hand[0], game.deck[0]):
        card.rank = 3
        card.suit = "Diamonds"
        card.edition = "Negative"
        card.enhancement = "Steel"
        card.seal = "Purple"
        card.debuffed = True
        card.bonus_chips = float("nan")
    assert encode_state(game) == encoded


def test_hidden_allocation_permutations_preserve_encoding():
    from balatro_sim.eval_encoder import encode_state

    game = make_game()
    game.hand[0].flipped = game.deck[0].flipped = True
    before = encode_state(game)
    game.hand[0], game.deck[0] = game.deck[0], game.hand[0]
    assert encode_state(game) == before


def test_composition_counts_real_piles_without_hand_truncation():
    from balatro_sim.eval_encoder import encode_state, flatten_state, schema

    game = make_game()
    original_width = len(flatten_state(encode_state(game)))
    game.hand.extend(game.deck.pop() for _ in range(5))
    game.spent.extend(game.deck.pop() for _ in range(4))
    encoded = encode_state(game)
    context = dict(zip(schema()["context_names"], encoded["context"]))
    assert len(encoded["cards"]) == 13
    assert context["total_count"] == 52
    assert context["undrawn_count"] == 35
    assert context["spent_count"] == 4
    for pile, n in (("total", 52), ("undrawn", 35), ("spent", 4)):
        assert sum(context[f"{pile}_rank_{r}"] for r in range(2, 15)) == n
    assert len(flatten_state(encoded)) == original_width == schema()["flat_dim"]
    game.hand[-1].bonus_chips = 100
    assert encode_state(game)["cards"][-1] != encoded["cards"][-1]


def test_joker_slot_and_name_keyed_runtime_state():
    from balatro_sim.eval_encoder import encode_state, schema

    game = make_game()
    game.jokers = [JokerInstance("j_blueprint", game=game), JokerInstance("j_baron", game=game)]
    game.jokers[0].state = {"chips": 7, "mult": 11, "mystery": 2, "target": "Pair"}
    before = encode_state(game)
    names = schema()["joker_names"]
    row = dict(zip(names, before["jokers"][0]))
    assert row["slot"] == 0
    assert before["jokers"][1][names.index("slot")] == 1
    assert row["state_chips"] == 7
    assert row["state_mult"] == 11
    assert row["missing_state_chips"] == 0
    assert row["missing_state_xmult"] == 1
    assert row["target_hand_Pair"] == 1.0
    assert row["missing_target_hand"] == 0.0
    assert row["missing_target_suit"] == 1.0
    assert row["unknown_state_count"] == 1
    game.jokers[0].state = {"mult": 11, "target": "Pair", "mystery": 2, "chips": 7}
    assert encode_state(game) == before
    game.jokers[0].state["chips"], game.jokers[0].state["mult"] = 11, 7
    assert encode_state(game) != before
    game.jokers.reverse()
    assert encode_state(game)["jokers"][0] != before["jokers"][1]


def test_special_joker_targets_are_encoded():
    from balatro_sim.eval_encoder import encode_state, schema

    game = make_game()
    game.grant_joker("j_ancient")
    game.grant_joker("j_idol")
    game.grant_joker("j_card_sharp")
    game.jokers[0].state["suit"] = "Hearts"
    game.jokers[1].state["suit"] = "Spades"
    game.jokers[1].state["rank"] = 14
    game.jokers[2].state["played_hands"] = {"Flush", "Pair"}

    state = encode_state(game)
    names = schema()["joker_names"]
    ancient_row = dict(zip(names, state["jokers"][0]))
    idol_row = dict(zip(names, state["jokers"][1]))
    sharp_row = dict(zip(names, state["jokers"][2]))

    assert ancient_row["target_suit_Hearts"] == 1.0
    assert ancient_row["target_suit_Spades"] == 0.0
    assert ancient_row["missing_target_suit"] == 0.0
    assert ancient_row["unknown_state_count"] == 0

    assert idol_row["target_suit_Spades"] == 1.0
    assert idol_row["target_suit_Hearts"] == 0.0
    assert idol_row["missing_target_suit"] == 0.0
    assert idol_row["state_rank"] == 14.0
    assert idol_row["unknown_state_count"] == 0

    assert sharp_row["played_hands_count"] == 2.0
    assert sharp_row["unknown_state_count"] == 0


def test_flipped_jokers_hide_identity_edition_state_and_missingness():
    from balatro_sim.eval_encoder import encode_state, schema

    game = make_game()
    game.jokers = [JokerInstance("j_blueprint", game=game), JokerInstance("j_baron", game=game)]
    game.jokers_flipped = True
    before = encode_state(game)
    names = schema()["joker_names"]
    for row in before["jokers"]:
        assert row[names.index("flipped")] == 1
        assert all(value == 0 for name, value in zip(names, row) if name not in ("slot", "flipped"))
    game.jokers.reverse()
    game.jokers[0].edition = "Negative"
    game.jokers[0].state = {"mult": float("inf"), "foo": 22}
    assert encode_state(game) == before


def test_string_consumables_vouchers_levels_and_histories():
    from balatro_sim.eval_encoder import encode_state, schema

    game = make_game()
    before = encode_state(game)
    game.consumable_hand = ["c_chariot", "pl_pluto"]
    game.vouchers = {"v_paint_brush"}
    game.planet_levels["Pair"] = 3
    game.run_hand_counts["Pair"] = 9
    game.played_hand_types_this_round = {"Pair"}
    game.last_hand_played = "Pair"
    state = encode_state(game)
    values = dict(zip(schema()["context_names"], state["context"]))
    assert state["context"] != before["context"]
    assert values["consumable_c_chariot"] == 1
    assert values["consumable_pl_pluto"] == 1
    assert values["voucher_v_paint_brush"] == 1
    assert values["level_Pair"] == 3
    assert values["run_count_Pair"] == 9
    assert values["round_played_Pair"] == values["last_played_Pair"] == 1
    assert sum(values[f"consumable_spec_{name}"] for name in ("kind_tarot", "kind_planet")) == 2


@pytest.mark.parametrize("where", ["context", "card", "joker", "unknown_joker"])
@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite_observable_values_rejected(where, bad):
    from balatro_sim.eval_encoder import encode_state

    game = make_game()
    if where == "context":
        game.dollars = bad
    elif where == "card":
        game.deck[0].bonus_chips = bad
    else:
        game.jokers = [JokerInstance("j_baron", game=game)]
        game.jokers[0].state["chips" if where == "joker" else "unknown"] = bad
    with pytest.raises(ValueError, match="finite"):
        encode_state(game)


def test_schema_and_flatten_are_fixed_width_and_order_sensitive():
    from balatro_sim.eval_encoder import encode_state, flatten_state, schema

    game = make_game()
    dimensions = schema()
    assert dimensions["version"]
    assert dimensions["limitations"]
    for block in ("context", "card", "joker"):
        assert dimensions[f"{block}_dim"] == len(dimensions[f"{block}_names"])
        assert len(set(dimensions[f"{block}_names"])) == dimensions[f"{block}_dim"]
    for count in (0, 1, 5, 15):
        game.jokers = [JokerInstance("j_baron", game=game) for _ in range(count)]
        flat = flatten_state(encode_state(game))
        assert len(flat) == dimensions["flat_dim"]
        assert all(math.isfinite(x) for x in flat)
    game.jokers = [JokerInstance("j_blueprint", game=game), JokerInstance("j_baron", game=game)]
    flat = flatten_state(encode_state(game))
    game.jokers.reverse()
    assert flatten_state(encode_state(game)) != flat
    bad = copy.deepcopy(encode_state(game))
    bad["cards"][0].append(1)
    with pytest.raises(ValueError):
        flatten_state(bad)
