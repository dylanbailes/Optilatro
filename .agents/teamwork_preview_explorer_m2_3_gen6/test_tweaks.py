import sys
from pathlib import Path
sys.path.insert(0, str(Path('vendor/balatro-rl').resolve()))

from balatro_sim.game import BalatroGame
from balatro_sim.agent_v10 import SearchShopV10
from balatro_sim.rollout import rollout
import balatro_sim.agent_v10 as ag10

# Test tweaks:
# 1. Blueprint purchase guard (no buy if len(jokers) == 0)
# 2. Blueprint worst_joker guard (never sell blueprint as worst joker if len > 1)
# 3. Obelisk / Idol blacklist in rank_shop_items
# 4. Late game reroll unblock (is_urgent_late overrides save_mode)

orig_rank = ag10._v10_rank_shop_items
orig_worst = ag10._v10_worst_joker_idx
orig_decide_shop = ag10._v10_decide_shop

TRAP_JOKERS = {"j_obelisk", "j_idol", "j_the_idol"}

def tweaked_rank(game, ref, surplus, rerolls_used=0):
    buys, need_sell = orig_rank(game, ref, surplus, rerolls_used)
    new_buys = []
    for v, idx in buys:
        item = game.current_shop[idx]
        # Tweak 1: Don't buy solo blueprint/brainstorm
        if item.key in ("j_blueprint", "j_brainstorm") and len(game.jokers) == 0:
            continue
        # Tweak 2: Don't buy trap jokers (obelisk, idol)
        if item.key in TRAP_JOKERS:
            continue
        new_buys.append((v, idx))
    return new_buys, need_sell

def tweaked_worst(game, ref=None):
    if not game.jokers:
        return None
    # If blueprint/brainstorm is owned, protect it by giving it high value
    orig_jokers = game.jokers
    idx = orig_worst(game, ref)
    if idx is not None and idx < len(orig_jokers):
        if orig_jokers[idx].key in ("j_blueprint", "j_brainstorm") and len(orig_jokers) > 1:
            # Find next worst non-blueprint joker
            candidates = [i for i, j in enumerate(orig_jokers) if j.key not in ("j_blueprint", "j_brainstorm")]
            if candidates:
                return candidates[0]
    return idx

ag10._v10_rank_shop_items = tweaked_rank
ag10._v10_worst_joker_idx = tweaked_worst

lost_seeds = [21, 40, 43, 54, 60, 80, 95, 131, 139, 155, 188, 198, 211, 298]

print("Testing lost seeds with Tweaks 1 & 2 (Blueprint & Trap Jokers):")
results = {}
for s in lost_seeds:
    game = BalatroGame(seed=s, rng_mode='seed')
    policy = SearchShopV10(search_shops=1, lookahead=False)
    res = rollout(game, policy)
    results[s] = res
    status = f"WON Ante {res['ante']}" if res['won'] else f"Died Ante {res['ante']} B{res.get('death_blind')}"
    print(f"Seed {s:>3}: {status:<15} | $={res.get('dollars'):<3} | Jokers: {res.get('jokers')}")
