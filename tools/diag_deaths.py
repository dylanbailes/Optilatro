"""tools/diag_deaths.py — dump per-run detail for deaths from a bench report sidecar.

Usage:
  python tools/diag_deaths.py vendor/balatro-rl/results/goal_base.json [policy] [--max-ante N]
"""
from __future__ import annotations

import json
import sys


def main() -> None:
    path = sys.argv[1]
    policy = sys.argv[2] if len(sys.argv) > 2 else None
    max_ante = int(sys.argv[3]) if len(sys.argv) > 3 else 1
    raw = json.load(open(path, encoding="utf-8"))
    if policy is None:
        policy = next(iter(raw))
    runs = raw[policy]["results"]
    dead = [r for r in runs if not r["won"] and r["ante"] <= max_ante]
    print(f"{path} :: {policy} :: {len(dead)} deaths at ante <= {max_ante}")
    for r in sorted(dead, key=lambda x: x["seed"]):
        st = r.get("stats") or {}
        print(
            f"seed {r['seed']:>3} | died ante {r['ante']} blind {r['death_blind']}"
            f" ({r['death_kind']}) | ${r['dollars']} | steps {r['steps']}"
            f" | jokers={r['jokers']} | bought={st.get('jokers_bought')}"
            f" | spent=${st.get('money_spent')} rerolls={st.get('rerolls')}"
            f" | packs={st.get('packs_bought')}/{st.get('packs_opened')}"
        )


if __name__ == "__main__":
    main()
