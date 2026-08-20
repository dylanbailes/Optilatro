def test_ante1_bias_flat_over_economy():
    from balatro_sim.game import BalatroGame
    from balatro_sim.agent_v9 import reference_hand
    from balatro_sim.agent_v10 import _v10_rank_shop_items, V10_PARAMS
    from balatro_sim.shop import ShopItem
    g = BalatroGame(seed=11, rng_mode="seed")
    g.ante = 1
    g.dollars = 6
    g.current_shop = [
        ShopItem("joker", "j_sly", "Sly Joker", 3),
        ShopItem("joker", "j_golden", "Golden Joker", 6),
    ]
    ref = reference_hand(g)
    buys, _ = _v10_rank_shop_items(g, ref, surplus=False)
    vals = {g.current_shop[i].key: v for v,i in buys}
    assert vals["j_sly"] > vals["j_golden"], f"ante1 vals {vals}"
    g.ante = 4
    buys4, _ = _v10_rank_shop_items(g, ref, surplus=False)
    vals4 = {g.current_shop[i].key: v for v,i in buys4}
    assert vals4["j_golden"] > vals["j_golden"] or vals4["j_sly"] < vals["j_sly"]


def test_ante1_p_clear_kd_boost():
    from balatro_sim.game import BalatroGame
    from balatro_sim.agent_v10 import estimate_clear_probability
    g = BalatroGame(seed=7, rng_mode="seed")
    g.ante = 1
    g._start_blind()
    g.hands_left = 2
    g.discards_left = 1
    g.chips_scored = g.current_blind.chips_target - 250
    p_before = estimate_clear_probability(g)
    assert p_before >= 0.0
    g2 = BalatroGame(seed=7, rng_mode="seed")
    g2.ante = 4
    g2.hands_left = 2
    g2.discards_left = 1
    g2.chips_scored = g2.current_blind.chips_target - 250
    g2.hand = list(g.hand)
    g2.deck = list(g.deck)
    from balatro_sim.agent_v10 import estimate_clear_probability as ecp2
    assert p_before >= ecp2(g2) - 1e-9


def test_structure_pool_boss_debuff_demotes_flush():
    from balatro_sim.card import Card
    from balatro_sim.agent_v9 import _structure_pool
    hand = [Card(2,"Hearts"), Card(5,"Hearts"), Card(9,"Hearts"), Card(11,"Hearts"),
            Card(7,"Clubs"), Card(8,"Clubs")]
    pool4, target4 = _structure_pool(hand, min_suit=4, min_run=4, min_pairs=2)
    assert target4 is not None and target4[0] == "flush"
    pool5, target5 = _structure_pool(hand, min_suit=5, min_run=4, min_pairs=2)
    assert target5 is None or target5[0] != "flush"


def test_ante1_good_hand_65_with_two_hands():
    from balatro_sim.agent_v9 import ACTIVE_PARAMS
    from balatro_sim.agent_v10 import V10_PARAMS
    assert V10_PARAMS["ante1_good_hand"] == 0.65
    assert ACTIVE_PARAMS["discard_play_good_hand"] == 0.50


def test_sell_uses_full_value_late():
    from balatro_sim.game import BalatroGame
    from balatro_sim.jokers.base import JokerInstance
    from balatro_sim.agent_v9 import reference_hand
    from balatro_sim.agent_v10 import _v10_worst_joker_idx
    g = BalatroGame(seed=5, rng_mode="seed")
    g.ante = 6
    g.jokers = [JokerInstance("j_sly"), JokerInstance("j_family")]
    from balatro_sim.card import Card
    g.deck = [Card(7,"Spades") for _ in range(7)] + [Card(2,"Hearts") for _ in range(45)]
    g.hand = [Card(7,"Hearts"), Card(7,"Diamonds"), Card(7,"Clubs"), Card(2,"Spades")]
    ref = reference_hand(g)
    idx = _v10_worst_joker_idx(g, ref)
    assert g.jokers[idx].key == "j_sly", f"worst {g.jokers[idx].key} not j_sly"


def test_ante1_buffoon_outranks_sly():
    from balatro_sim.game import BalatroGame
    from balatro_sim.agent_v9 import reference_hand, pack_value
    from balatro_sim.agent_v10 import _v10_rank_shop_items, V10_PARAMS
    from balatro_sim.shop import ShopItem
    g = BalatroGame(seed=0, rng_mode="seed")
    g.ante = 1
    g.dollars = 4
    g.current_shop = [
        ShopItem("joker", "j_sly", "Sly Joker", 3),
        ShopItem("booster", "p_buffoon", "Buffoon Pack", 4),
    ]
    ref = reference_hand(g)
    buys, _ = _v10_rank_shop_items(g, ref, surplus=False)
    vals = {g.current_shop[i].key: v for v,i in buys}
    # Ante-1: buffoon boosted 0.25+0.20=0.45 > sly 0.41, so buffoon should be top
    assert vals["p_buffoon"] > vals["j_sly"], f"ante1 buffoon should outrank sly: {vals}"
    # Verify boost is gated: ante-1 buffoon value should be 0.20 higher than base pack_value
    base = pack_value(g, "p_buffoon")
    assert abs(vals["p_buffoon"] - (base + V10_PARAMS["ante1_buffoon_boost"]) ) < 1e-6
    g.ante = 4
    buys4, _ = _v10_rank_shop_items(g, ref, surplus=False)
    vals4 = {g.current_shop[i].key: v for v,i in buys4}
    # Ante-4 no boost: buffoon should be base value (0.25)
    if "p_buffoon" in vals4:
        assert abs(vals4["p_buffoon"] - base) < 1e-6, f"ante4 buffoon should be base {base}, got {vals4['p_buffoon']}"


def test_small_flush_chase_with_3_suited():
    from balatro_sim.game import BalatroGame
    from balatro_sim.card import Card
    from balatro_sim.agent_v9 import best_discard
    g = BalatroGame(seed=1, rng_mode="seed")
    g.ante = 1
    g.current_blind.kind = "Small"
    g.current_blind.chips_target = 300
    g.chips_scored = 0
    g.hands_left = 4
    g.discards_left = 4
    g.deck = [Card(2,"Hearts") for _ in range(20)] + [Card(3,"Clubs") for _ in range(20)]
    # Hand with 3 Hearts, 5 off-suit — should chase flush for Hearts with min_suit=3
    g.hand = [Card(2,"Hearts"), Card(5,"Hearts"), Card(9,"Hearts"),
              Card(7,"Clubs"), Card(8,"Clubs"), Card(9,"Clubs"), Card(11,"Diamonds"), Card(12,"Diamonds")]
    dset, _ = best_discard(g)
    # Should discard off-suit clubs/diamonds, not Hearts
    assert all(g.hand[i].suit != "Hearts" for i in dset), f"should discard off-Hearts, got {dset} {[g.hand[i].suit for i in dset]}"


def test_joker_keep_photograph():
    from balatro_sim.game import BalatroGame
    from balatro_sim.card import Card
    from balatro_sim.jokers.base import JokerInstance
    from balatro_sim.agent_v10 import joker_keep_indices
    g = BalatroGame(seed=1, rng_mode="seed")
    g.ante = 1
    g.jokers = [JokerInstance("j_photograph")]
    hand = [Card(11,"Hearts"), Card(13,"Spades"), Card(5,"Clubs"), Card(7,"Diamonds"), Card(9,"Hearts")]
    keep = joker_keep_indices(hand, g)
    # Photograph keeps faces (J, K)
    assert 0 in keep and 1 in keep, f"photograph should keep faces, got {keep}"
    assert 2 not in keep, "5 Clubs not face should not be kept for photograph alone"


def test_joker_keep_sly_pair():
    from balatro_sim.game import BalatroGame
    from balatro_sim.card import Card
    from balatro_sim.jokers.base import JokerInstance
    from balatro_sim.agent_v10 import joker_keep_indices
    g = BalatroGame(seed=1, rng_mode="seed")
    g.ante = 1
    g.jokers = [JokerInstance("j_sly")]
    hand = [Card(13,"Hearts"), Card(13,"Spades"), Card(5,"Clubs"), Card(7,"Diamonds"), Card(9,"Hearts")]
    keep = joker_keep_indices(hand, g)
    # Sly wants Pair — keep the Kings
    assert 0 in keep and 1 in keep
    assert 2 not in keep

def test_joker_keep_respects_farm_off():
    from balatro_sim.game import BalatroGame
    from balatro_sim.card import Card
    from balatro_sim.jokers.base import JokerInstance
    from balatro_sim.agent_v10 import joker_keep_indices, V10_PARAMS
    g = BalatroGame(seed=1, rng_mode="seed")
    g.ante = 1
    g.jokers = [JokerInstance("j_photograph")]
    hand = [Card(11,"Hearts"), Card(13,"Spades"), Card(5,"Clubs")]
    # Farm off should keep nothing
    old = V10_PARAMS["farm_clear_threshold"]
    V10_PARAMS["farm_clear_threshold"] = 1.0
    keep = joker_keep_indices(hand, g)
    assert keep == set(), f"farm off should keep nothing, got {keep}"
    V10_PARAMS["farm_clear_threshold"] = old
