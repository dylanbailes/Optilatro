import sys
from pathlib import Path
sys.path.insert(0, str(Path('vendor/balatro-rl').resolve()))

from balatro_sim.agent_v10 import PREMIER_XMULT_FINISHERS, RELIABLE_XMULT_JOKERS, HIGH_LEVERAGE_SCORING_JOKERS
try:
    from tools.portfolio import XMULT_JOKERS as PORTFOLIO_XMULT
except:
    PORTFOLIO_XMULT = set()

print("PREMIER_XMULT_FINISHERS:", PREMIER_XMULT_FINISHERS)
print("Is blueprint in PREMIER:", "j_blueprint" in PREMIER_XMULT_FINISHERS)
print("Is brainstorm in PREMIER:", "j_brainstorm" in PREMIER_XMULT_FINISHERS)
print("Is blueprint in PORTFOLIO_XMULT:", "j_blueprint" in PORTFOLIO_XMULT)
print("Is brainstorm in PORTFOLIO_XMULT:", "j_brainstorm" in PORTFOLIO_XMULT)
