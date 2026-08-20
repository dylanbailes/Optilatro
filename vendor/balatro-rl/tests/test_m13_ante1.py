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
