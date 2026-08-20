"""Inspect a mined synergy tree: top joker-joker and joker-consumable edges.

Usage: python results/inspect_tree.py <tree.json> [top_n]
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from balatro_sim.shop import JOKER_CATALOGUE
from balatro_sim.consumables import PLANET_NAME, SPECTRAL_NAME, TAROT_NAME


def main() -> None:
    tree_path = Path(sys.argv[1])
    top_n = int(sys.argv[2]) if len(sys.argv) > 2 else 12
    t = json.loads(tree_path.read_text(encoding="utf-8"))

    def nm(k):
        return JOKER_CATALOGUE.get(k, {}).get("name", k)

    jj = [(e["lift_ante"], e["n"], a, b)
          for a, o in t.get("joker_joker", {}).items()
          for b, e in o.items()]
    jj.sort(reverse=True)
    print(f"TOP {top_n} PAIRS ({tree_path.name}):")
    for lift, n, a, b in jj[:top_n]:
        print(f"  {nm(a)} + {nm(b)}: lift {lift:+.2f} n={n}")

    jc = [(e["lift_ante"], e["n"], j, c)
          for j, o in t.get("joker_consumable", {}).items()
          for c, e in o.items()]
    jc.sort(reverse=True)
    print(f"TOP {top_n} JOKER-CONSUMABLE:")
    for lift, n, j, c in jc[:top_n]:
        cname = TAROT_NAME.get(c, PLANET_NAME.get(c, SPECTRAL_NAME.get(c, c)))
        print(f"  {nm(j)} + {cname}: lift {lift:+.2f} n={n}")

    jh = t.get("joker_hand", {})
    rows = [(e["n"], j, ht, e["share"])
            for j, hands in jh.items() for ht, e in hands.items()]
    rows.sort(reverse=True)
    print(f"TOP {top_n} JOKER-HAND:")
    for n, j, ht, share in rows[:top_n]:
        print(f"  {nm(j)} x {ht}: share {share:.0%} n={n}")


if __name__ == "__main__":
    main()
