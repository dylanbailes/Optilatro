import pathlib, sys, json
ROOT = pathlib.Path(__file__).resolve().parent.parent
VENDOR = ROOT / "vendor" / "balatro-rl"
sys.path.insert(0, str(VENDOR))

from balatro_sim.game import BalatroGame
from balatro_sim.rollout import rollout
from balatro_sim.agent_v10 import HeuristicV10
from balatro_sim import shop as shop_mod
from balatro_sim import agent_v9 as a9
from collections import Counter

# Death seeds from last 200 run for v10
death_seeds = [r['seed'] for r in json.loads(pathlib.Path("vendor/balatro-rl/results/v10_report.json").read_text())['heuristic_v10']['results'] if not r['won'] and r['ante']<=1]
print(f"Death seeds ({len(death_seeds)}): {death_seeds[:20]}")

for seed in death_seeds[:10]:
    game = BalatroGame(seed=seed, rng_mode="seed")
    pol = HeuristicV10()
    # Hook shop generation
    orig_gen = shop_mod.generate_shop
    shops = []
    def logged_gen(g, restock_voucher=False):
        items = orig_gen(g, restock_voucher)
        shops.append([(it.kind, it.key, it.price, it.edition) for it in items])
        return items
    shop_mod.generate_shop = logged_gen

    # Hook discard and play decisions: wrap decide_hand and best_discard
    orig_best_discard = a9.best_discard
    discards = []
    def logged_best_discard(*args, **kwargs):
        dset, val = orig_best_discard(*args, **kwargs)
        # Capture hand before discard
        hand = args[0].hand if args else None
        if hand is not None:
            discards.append((list(dset), val, [(c.rank, c.suit, c.enhancement) for c in hand]))
        else:
            discards.append((list(dset), val))
        return dset, val
    a9.best_discard = logged_best_discard

    # Also hook shop decision to see buys
    # Use game's jokers_bought after rollout
    result = rollout(game, pol)
    shop_mod.generate_shop = orig_gen
    a9.best_discard = orig_best_discard

    print(f"\n=== Seed {seed} ===")
    print(f"Result ante {result['ante']} won {result['won']} death_blind {result.get('death_blind')} dollars {result['dollars']} steps {result['steps']}")
    print(f"Jokers bought: {result['stats']['jokers_bought']}")
    print(f"Packs bought: {result['stats']['packs_bought']} Rerolls: {result['stats']['rerolls']} Money spent {result['stats']['money_spent']}")
    print(f"Best score {result['stats']['best_score']} tarots {len(result['stats'].get('tarots',[]))}")
    for i, s in enumerate(shops[:3]):
        print(f" Shop {i}: {s}")
    print(f" Discards (first 5): {discards[:5]}")
    # Check hand at death: game is at terminal, but we can print last hand? Not available. Use result's hand? Not stored.
    # Instead print co_owned for ante1?
    print(f" co_owned ante1: {[c for c in result['stats'].get('co_owned',[]) if c[0]==1][:3]}")
