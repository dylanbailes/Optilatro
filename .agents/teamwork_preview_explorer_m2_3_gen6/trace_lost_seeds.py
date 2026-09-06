import sys
from pathlib import Path
sys.path.insert(0, str(Path('vendor/balatro-rl').resolve()))

from balatro_sim.game import BalatroGame, State
from balatro_sim.agent_v10 import SearchShopV10, portfolio_target_hand
from balatro_sim.rollout import rollout

lost_seeds = [21, 40, 43, 54, 60, 80, 95, 131, 139, 155, 188, 198, 211, 298]

class TracingSearchShop(SearchShopV10):
    def __init__(self, trace_log, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.trace_log = trace_log

    def decide(self, game):
        st = game.state
        ante = game.ante
        blind = getattr(game, 'blind_index', None)
        dollars = game.dollars
        th = portfolio_target_hand(game) if hasattr(game, 'jokers') else None
        
        act = super().decide(game)
        
        atype = act.get('type')
        if atype in ('buy', 'sell_joker', 'reroll'):
            j_keys = [j.key for j in game.jokers]
            if atype == 'buy':
                item_idx = act.get('item_idx')
                item = game.current_shop[item_idx] if 0 <= item_idx < len(game.current_shop) else None
                item_desc = f"{item.kind}:{item.key}" if item else str(item_idx)
                self.trace_log.append(f"A{ante}B{blind} (${dollars}) BUY {item_desc} | J:{j_keys} | TH:{th}")
            elif atype == 'sell_joker':
                j_idx = act.get('joker_idx')
                sold_j = game.jokers[j_idx].key if 0 <= j_idx < len(game.jokers) else str(j_idx)
                self.trace_log.append(f"A{ante}B{blind} (${dollars}) SELL {sold_j} | J:{j_keys} | TH:{th}")
            elif atype == 'reroll':
                self.trace_log.append(f"A{ante}B{blind} (${dollars}) REROLL (#{self._rerolls_this_shop}) | J:{j_keys} | TH:{th}")
        return act

results = {}

for s in lost_seeds:
    trace_log = []
    game = BalatroGame(seed=s, rng_mode='seed')
    policy = TracingSearchShop(trace_log=trace_log, search_shops=1, lookahead=False)
    
    res = rollout(game, policy)
    
    death_round_hands = []
    if 'stats' in res and 'co_owned' in res['stats']:
        death_round_hands = res['stats']['co_owned'][-8:]
        
    results[s] = {
        'won': res['won'],
        'ante': res['ante'],
        'death_blind': res.get('death_blind'),
        'death_kind': res.get('death_kind'),
        'dollars': res.get('dollars'),
        'jokers': [j.key if hasattr(j, 'key') else j for j in game.jokers],
        'rerolls': res['stats']['rerolls'],
        'money_spent': res['stats']['money_spent'],
        'tarots': res['stats']['tarots'],
        'planets': res['stats']['planets'],
        'target_hand': portfolio_target_hand(game),
        'trace_tail': trace_log[-12:],
        'death_round_hands': death_round_hands
    }

with open('.agents/teamwork_preview_explorer_m2_3_gen6/trace_results.json', 'w') as f:
    import json
    json.dump(results, f, indent=2)

print("Trace complete. Results saved.")
