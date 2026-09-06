import sys
from pathlib import Path
sys.path.insert(0, str(Path('vendor/balatro-rl').resolve()))

from balatro_sim.game import BalatroGame
from balatro_sim.agent_v10 import SearchShopV10
from balatro_sim.rollout import rollout
import balatro_sim.agent_v10 as ag10

TRAP_JOKERS = {"j_obelisk", "j_idol", "j_the_idol"}

orig_rank = ag10._v10_rank_shop_items
orig_worst = ag10._v10_worst_joker_idx
orig_decide = ag10._v10_decide_shop

def tweaked_rank(game, ref, surplus, rerolls_used=0):
    buys, need_sell = orig_rank(game, ref, surplus, rerolls_used)
    new_buys = []
    for v, idx in buys:
        item = game.current_shop[idx]
        if item.key in ("j_blueprint", "j_brainstorm") and len(game.jokers) == 0:
            continue
        if item.key in TRAP_JOKERS:
            continue
        new_buys.append((v, idx))
    return new_buys, need_sell

def tweaked_worst(game, ref=None):
    if not game.jokers:
        return None
    orig_jokers = game.jokers
    idx = orig_worst(game, ref)
    if idx is not None and idx < len(orig_jokers):
        if orig_jokers[idx].key in ("j_blueprint", "j_brainstorm") and len(orig_jokers) > 1:
            candidates = [i for i, j in enumerate(orig_jokers) if j.key not in ("j_blueprint", "j_brainstorm")]
            if candidates:
                return candidates[0]
    return idx

# Now let's implement the full decide_shop with reroll unblock
def unblocked_decide_shop(game, rerolls_used: int) -> dict:
    # We copy the body of _v10_decide_shop with the line 1625 fix:
    # (not save_mode or is_urgent_late)
    p = ag10.ACTIVE_PARAMS
    if (game.next_boss_key in ag10.BAD_BOSSES and game.dollars >= 10):
        can_dc = ("v_directors_cut" in game.vouchers and game.dc_reroll_ante != game.ante)
        can_retcon = "v_retcon" in game.vouchers
        if can_dc or can_retcon:
            return {"type": "reroll_boss"}

    act = ag10._v10_maybe_use_planet(game)
    if act is not None:
        return act

    if p["use_tarots"]:
        act = ag10._v10_decide_consumable(game)
        if act is not None:
            return act

    ref = ag10.reference_hand(game)
    surplus = ag10.forecast_beatable(game, p["tilt_surplus_margin"], ref)
    buys, need_sell = ag10._v10_rank_shop_items(game, ref, surplus, rerolls_used=rerolls_used)

    if need_sell is not None:
        return {"type": "sell_joker", "joker_idx": need_sell[1]}

    forecast_score = ag10._forecast_round_score(game, ref)
    boss_target = ag10._ante_boss_target(game)
    interest_target = p["interest_target"]
    force_no_save = False

    if ag10.V10_PARAMS.get("farm_clear_threshold", 0.90) < 1.0:
        n_xmult = sum(1 for j in game.jokers if j.key in ag10.XMULT_JOKERS or j.key in ag10.RELIABLE_XMULT_JOKERS)

        if game.ante >= 8:
            interest_target = 0
            force_no_save = True
        elif game.ante == 7:
            if forecast_score < boss_target * 1.25:
                interest_target = 0
                force_no_save = True
        elif game.ante == 6:
            if n_xmult == 0 or forecast_score < boss_target:
                interest_target = min(interest_target, 15)

    save_mode = (
        not force_no_save
        and game.ante > 2
        and game.dollars < interest_target
        and max((v for v, _ in buys), default=0.0) < p["save_strong_value"]
        and ag10.forecast_beatable(game, p["save_margin"], ref)
    )

    if buys:
        buys.sort(key=lambda b: (b[0], ag10._KIND_RANK.get(game.current_shop[b[1]].kind, 1)), reverse=True)
        target_ht = ag10.portfolio_target_hand(game)
        main_ht = ag10.main_hand_type(game)
        for value, idx in buys:
            item = game.current_shop[idx]
            price = item.discounted_price(game.shop_discount)
            is_high_ev_consumable = False
            if ag10.V10_PARAMS.get("farm_clear_threshold", 0.90) < 1.0:
                is_core_econ = item.key in ("c_hermit", "c_death", "c_fool", "c_temperance")
                is_target_planet = (item.kind == "planet" and ag10.PLANET_HAND.get(item.key) == target_ht)
                is_target_tarot = (item.kind == "tarot" and ag10._reshape_tarot_bonus(game, item.key) > 0)
                is_high_ev_consumable = is_core_econ or is_target_planet or is_target_tarot
            if (price <= game.dollars
                    and (not save_mode or value >= p["save_strong_value"] or is_high_ev_consumable)
                    and ag10.worth_spending(game, price, value)):
                return {"type": "buy", "item_idx": idx}

    reroll_cost = max(0, game.reroll_cost - game.reroll_discount)
    eff_max = p["reroll_max"]
    if ag10.V10_PARAMS.get("engineless_reroll_extra", 0):
        urg = ag10.V10_PARAMS.get("engineless_urgency_ante", 0)
        if (game.ante <= urg and ag10.V10_PARAMS["farm_clear_threshold"] < 1.0 and not ag10._has_scoring_joker(game)):
            eff_max += ag10.V10_PARAMS["engineless_reroll_extra"]

    if ag10.V10_PARAMS.get("farm_clear_threshold", 0.90) < 1.0:
        is_urgent_ante6 = (game.ante == 6 and (n_xmult == 0 or forecast_score < boss_target))
        is_urgent_ante7 = (game.ante == 7 and force_no_save)
        is_urgent_ante8 = (game.ante >= 8)

        if is_urgent_ante8:
            eff_max = max(eff_max, 10)
        elif is_urgent_ante7:
            eff_max = max(eff_max, 6)
        elif is_urgent_ante6:
            eff_max = max(eff_max, 4)

        slots_full = len(game.jokers) >= game.joker_slots
        worst_sell_val = 0
        if slots_full and game.jokers:
            w_idx = ag10._v10_worst_joker_idx(game, ref)
            if w_idx is not None and w_idx < len(game.jokers):
                worst_sell_val = ag10._joker_sell_value(game.jokers[w_idx])

        capital_after_reroll = game.dollars - reroll_cost + (worst_sell_val if slots_full else 0)
        is_urgent_late = is_urgent_ante8 or is_urgent_ante7 or is_urgent_ante6
        min_reserve = 6 if is_urgent_late else max(reroll_cost, p["reroll_min_money"])
        reserve_ok = (capital_after_reroll >= min_reserve) if is_urgent_late else (game.dollars >= max(reroll_cost, p["reroll_min_money"]))
    else:
        is_urgent_late = False
        reserve_ok = (game.dollars >= max(reroll_cost, p["reroll_min_money"]))

    # HERE IS THE FIX: allow reroll when is_urgent_late even if save_mode is true!
    if ((not save_mode or is_urgent_late)
            and game.dollars >= reroll_cost
            and reserve_ok
            and rerolls_used < eff_max):
        return {"type": "reroll"}

    return {"type": "leave_shop"}

ag10._v10_rank_shop_items = tweaked_rank
ag10._v10_worst_joker_idx = tweaked_worst
ag10._v10_decide_shop = unblocked_decide_shop

test_seeds = [139, 155, 198, 211, 40, 54]
print("Running test on late-game seeds with unblocked rerolls:")
for s in test_seeds:
    g = BalatroGame(seed=s, rng_mode='seed')
    pol = SearchShopV10(search_shops=1, lookahead=False)
    r = rollout(g, pol)
    status = f"WON Ante {r['ante']}" if r['won'] else f"Died Ante {r['ante']} B{r.get('death_blind')}"
    print(f"Seed {s:>3}: {status:<15} | $={r.get('dollars'):<3} | Rerolls: {r['stats']['rerolls']:<2} | Jokers: {r.get('jokers')}")
