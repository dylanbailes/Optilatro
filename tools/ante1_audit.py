"""Ante-1 death audit: why do we die? Do they have jokers? Bad discards? Buffoon opened?"""
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parent.parent
VENDOR = ROOT / "vendor" / "balatro-rl"
sys.path.insert(0, str(VENDOR))

from collections import Counter
from balatro_sim.game import BalatroGame
from balatro_sim.rollout import rollout
from balatro_sim.agent_v9 import HeuristicV9
from balatro_sim.agent_v10 import HeuristicV10
from balatro_sim.shop import JOKER_CATALOGUE
import json

def audit_policy(policy_name, policy_cls, params=None, seeds=range(200)):
    deaths = []  # list of dict per ante-1 death
    total = 0
    for seed in seeds:
        game = BalatroGame(seed=seed, rng_mode="seed")
        policy = policy_cls(params=params) if params else policy_cls()
        result = rollout(game, policy)
        total += 1
        if not result["won"] and result["ante"] <= 1:
            # ante-1 death: unpack
            stats = result.get("stats", {})
            jokers_bought = stats.get("jokers_bought", [])
            jokers_at_end = result.get("jokers", [])
            # Need to reconstruct what happened in ante-1: we need to re-run with trace
            # For now, capture high-level
            deaths.append({
                "seed": seed,
                "ante": result["ante"],
                "death_blind": result.get("death_blind", "?"),
                "dollars": result.get("dollars"),
                "steps": result.get("steps"),
                "jokers_bought": jokers_bought,
                "jokers_at_end": jokers_at_end,
                "econ_source": stats.get("econ_source"),
                "interest": stats.get("interest_collected"),
                "best_score": stats.get("best_score"),
            })
    # Detailed re-roll for each death with verbose trace: capture first shop and discards
    detailed = []
    for d in deaths[:10]:  # detailed for first 10
        seed = d["seed"]
        game = BalatroGame(seed=seed, rng_mode="seed")
        policy = policy_cls(params=params) if params else policy_cls()
        # Monkey patch shop buy to log
        from balatro_sim import shop as shop_mod
        orig_generate_shop = shop_mod.generate_shop
        shop_logs = []
        def logged_generate_shop(g, restock_voucher=False):
            items = orig_generate_shop(g, restock_voucher)
            shop_logs.append([(it.kind, it.key, it.price) for it in items])
            return items
        shop_mod.generate_shop = logged_generate_shop
        # Also trace discard decisions: wrap best_discard and decide_hand
        from balatro_sim import agent_v9
        orig_best_discard = agent_v9.best_discard
        discard_logs = []
        def logged_best_discard(*a, **kw):
            res = orig_best_discard(*a, **kw)
            discard_logs.append(res)
            return res
        agent_v9.best_discard = logged_best_discard

        result = rollout(game, policy)
        shop_mod.generate_shop = orig_generate_shop
        agent_v9.best_discard = orig_best_discard
        d["shop_logs"] = shop_logs
        d["discard_logs"] = discard_logs[:5]
        detailed.append(d)

    return deaths, detailed, total

def verify_starting_and_buffoon():
    print("=== Verify starting cash & first shop buffoon ===")
    from balatro_sim.game import BalatroGame
    from balatro_sim.shop import generate_shop
    for seed in [0,1,2,11,42,100]:
        g = BalatroGame(seed=seed, rng_mode="seed")
        # Starting cash should be 4 (constants.STARTING_MONEY) per docs/reference §0
        assert g.dollars == 4, f"seed {seed} dollars {g.dollars} !=4"
        # Advance to first shop: skip small blind to get to shop after small?
        # Actually first shop is after Small blind (blind_idx 0 -> ante 1 Small)
        # We can directly generate shop at ante 1 before any blind
        g2 = BalatroGame(seed=seed, rng_mode="seed")
        items = generate_shop(g2)
        booster_keys = [it.key for it in items if it.kind=="booster"]
        has_buffoon = "p_buffoon" in booster_keys
        print(f"seed {seed}: first shop boosters {booster_keys} has_buffoon={has_buffoon} all_items={[(it.kind,it.key) for it in items]}")
        assert has_buffoon, f"seed {seed} first shop missing p_buffoon"
    print("All starting checks passed: $4 and p_buffoon guaranteed")

def pack_value_check():
    print("\n=== Pack value: does HeuristicV10 always buy buffoon? ===")
    from balatro_sim.game import BalatroGame
    from balatro_sim.agent_v9 import reference_hand
    from balatro_sim.agent_v10 import _v10_rank_shop_items, V10_PARAMS
    from balatro_sim.shop import ShopItem
    # Simulate first shop with buffoon vs cheap joker
    for seed in [0,1,2,11]:
        g = BalatroGame(seed=seed, rng_mode="seed")
        g.ante = 1
        g.dollars = 4
        g.current_shop = [
            ShopItem("joker", "j_sly", "Sly Joker", 3),
            ShopItem("booster", "p_buffoon", "Buffoon Pack", 4),
        ]
        ref = reference_hand(g)
        buys, _ = _v10_rank_shop_items(g, ref, surplus=False)
        print(f"seed {seed} buys sorted {[ (g.current_shop[i].key, v) for v,i in buys ]}")
        # Check that buffoon is in buys when affordable
        buffoon_in = any(g.current_shop[i].key=="p_buffoon" for _,i in buys)
        print(f"  buffoon_in_buys={buffoon_in}")

if __name__ == "__main__":
    verify_starting_and_buffoon()
    pack_value_check()
    print("\n=== Ante-1 death audit for HeuristicV10 (M13) 200 seeds ===")
    deaths, detailed, total = audit_policy("heuristic_v10", HeuristicV10, seeds=range(200))
    print(f"Total {total}, ante-1 deaths {len(deaths)} ({100*len(deaths)/total:.1f}%)")
    jokers_counter = Counter()
    no_joker = 0
    one_joker = 0
    econ_only = 0
    for d in deaths:
        j = d["jokers_bought"]
        if not j:
            no_joker += 1
        elif len(j)==1:
            one_joker += 1
        # Check if all bought are economy
        from balatro_sim.agent_v9 import ECONOMY_JOKERS
        if j and all(k in ECONOMY_JOKERS for k in j):
            econ_only += 1
        for k in j:
            jokers_counter[k] += 1
    print(f"Deaths with 0 jokers bought: {no_joker}/{len(deaths)}")
    print(f"Deaths with 1 joker bought: {one_joker}/{len(deaths)}")
    print(f"Deaths with econ-only jokers: {econ_only}/{len(deaths)}")
    print(f"Top jokers bought in deaths: {jokers_counter.most_common(10)}")
    print("\n=== Detailed 10 deaths (first shop logs) ===")
    for d in detailed:
        print(f"Seed {d['seed']}: ante {d['ante']} death_blind {d['death_blind']} dollars {d['dollars']} jokers_bought {d['jokers_bought']} econ {d['econ_source']} best_score {d['best_score']}")
        print(f"  first shop: {d['shop_logs'][0] if d['shop_logs'] else 'none'}")
        if len(d['shop_logs'])>1:
            print(f"  second shop: {d['shop_logs'][1]}")
        print(f"  discards: {d['discard_logs']}")
    # Also audit heuristic_v9 for comparison
    print("\n=== HeuristicV9 same bank for comparison ===")
    deaths_v9, _, _ = audit_policy("heuristic_v9", HeuristicV9, seeds=range(200))
    print(f"V9 ante-1 deaths {len(deaths_v9)} ({100*len(deaths_v9)/200:.1f}%)")
    c9 = Counter()
    for d in deaths_v9:
        for k in d["jokers_bought"]:
            c9[k]+=1
    print(f"V9 top in deaths: {c9.most_common(10)}")
