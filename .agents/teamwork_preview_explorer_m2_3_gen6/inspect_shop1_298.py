import sys
from pathlib import Path
sys.path.insert(0, str(Path('vendor/balatro-rl').resolve()))

from balatro_sim.game import BalatroGame

g = BalatroGame(seed=298, rng_mode='seed')
# Clear small blind
g.step({'type': 'play', 'cards': [0, 1, 2, 3, 4]})
while g.state.name != 'SHOP':
    g.step({'type': 'play', 'cards': [0, 1, 2, 3, 4]})

print("Seed 298 Ante 1 Shop 1 items:")
for i, it in enumerate(g.current_shop):
    print(f"  [{i}] {it.kind}: {it.key}, price={it.cost}")
