import sys
sys.path.insert(0, "D:/Optilatro/vendor/balatro-rl")
from balatro_sim.game import BalatroGame

seeds_to_check = [82, 100, 118, 164, 174, 205, 224, 242, 250, 260, 262, 267, 269, 275]

print("=== BOSS FOR ANTE-1 FATAL SEEDS ===")
for s in seeds_to_check:
    g = BalatroGame(seed=s, deck="Red Deck", stake="White Stake")
    boss_name = g.boss if hasattr(g, "boss") else "unknown"
    # also check blind target for ante 1 boss
    print(f"Seed {s:3d}: Boss = {boss_name}, Boss Blind Target = {g.boss_target if hasattr(g, 'boss_target') else 'N/A'}")
