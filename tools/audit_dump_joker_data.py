"""Dump balatro-rs's authoritative joker_data! table and match each real joker
to the sim's effect key (by display name). Prints, for every real joker:
  canonical_id | name | rarity | cost | sim_catalogue_key | sim_registry_resolves(canonical)?
"""
import re
import sys

sys.path.insert(0, "vendor/balatro-rl")
from balatro_sim.shop import JOKER_CATALOGUE
from balatro_sim.jokers.base import JOKER_REGISTRY

# ── parse joker_data! rows: Variant, "id", "name", Rarity, cost, ... ─────────
rows = []
text = open("vendor/balatro-rs/balatro-types/src/joker.rs", encoding="utf-8", errors="replace").read()
for m in re.finditer(
    r'(\w+),\s+"(j_[a-z0-9_]+)",\s+"([^"]+)",\s+(\w+),\s+(\d+)',
    text,
):
    rows.append((m.group(1), m.group(2), m.group(3), m.group(4), int(m.group(5))))

def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())

sim_by_name = {}
for key, info in JOKER_CATALOGUE.items():
    sim_by_name.setdefault(norm(info["name"]), key)

print(f"rows parsed from balatro-rs: {len(rows)}")
print(f"{'canonical_id':22s} {'name':24s} {'rarity':10s} {'cost':>4s}  sim_cat_key")
print("-" * 90)
for variant, cid, name, rarity, cost in rows:
    n = norm(name)
    skey = sim_by_name.get(n, "-")
    print(f"{cid:22s} {name:24s} {rarity.lower():10s} {cost:4d}  {skey}")
