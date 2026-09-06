import sys
from pathlib import Path
sys.path.insert(0, str(Path('vendor/balatro-rl').resolve()))
from balatro_sim.game import BalatroGame

lost = [21, 40, 43, 54, 60, 80, 95, 131, 139, 155, 188, 198, 211, 298]

for s in lost:
    g = BalatroGame(seed=s, rng_mode='seed')
    print(f"Seed {s:>3}: Boss Ante 1={g.next_boss_key}")
