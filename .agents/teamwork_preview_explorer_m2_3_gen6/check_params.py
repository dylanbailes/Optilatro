import sys
from pathlib import Path
sys.path.insert(0, str(Path('vendor/balatro-rl').resolve()))
from balatro_sim.agent_v10 import V10_PARAMS

print("V10_PARAMS:")
for k, v in sorted(V10_PARAMS.items()):
    print(f"  {k}: {v}")
