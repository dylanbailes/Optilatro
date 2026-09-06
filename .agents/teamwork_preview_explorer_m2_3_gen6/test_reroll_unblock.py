import sys
from pathlib import Path
sys.path.insert(0, str(Path('vendor/balatro-rl').resolve()))

from balatro_sim.game import BalatroGame
from balatro_sim.agent_v10 import SearchShopV10
from balatro_sim.rollout import rollout
import balatro_sim.agent_v10 as ag10

# Test comprehensive tweaks:
# 1. Blueprint solo guard: no buy if len(jokers) == 0 or (ante == 1 and len(jokers) <= 1)
# 2. Blueprint worst_joker guard: protect blueprint/brainstorm from being sold
# 3. Trap jokers blacklist in general shop: obelisk, idol
# 4. Late-game capital unblock: in Ante >= 6, don't let save_mode block rerolls when in deficit or urgent

orig_rank = ag10._v10_rank_shop_items
orig_worst = ag10._v10_worst_joker_idx
orig_decide_shop = ag10._v10_decide_shop

TRAP_JOKERS = {"j_obelisk", "j_idol", "j_the_idol"}

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

def tweaked_decide_shop(game, rerolls_used):
    # In ante >= 6, ensure urgent rerolls can execute without save_mode suppression
    # Let's inspect what orig_decide_shop does
    # We can temporarily patch ACTIVE_PARAMS or force_no_save
    return orig_decide_shop(game, rerolls_used)

# Let's test on the late-game deaths: [139, 155, 198, 211, 40, 54]
ag10._v10_rank_shop_items = tweaked_rank
ag10._v10_worst_joker_idx = tweaked_worst

# Let's see what happens if we patch line 1625 in agent_v10 logic:
# Specifically in _v10_decide_shop: allow reroll if (not save_mode or is_urgent_late)
