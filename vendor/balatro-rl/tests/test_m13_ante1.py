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
