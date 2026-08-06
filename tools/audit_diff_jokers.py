"""Audit: definitive joker triage — real Balatro jokers vs the sim.

For each real joker (authoritative balatro-rs joker_data! table), classify:
  OFFERED   — in sim JOKER_CATALOGUE (name-matched)
  UNOFFERED — effect exists in JOKER_REGISTRY but no catalogue entry (never sold)
  MISSING   — no effect at all in the sim
Also flags rarity mismatches between the sim catalogue and the real table
(wrong rarity corrupts shop rarity pools).
"""
import re
import sys

sys.path.insert(0, "vendor/balatro-rl")
from balatro_sim.shop import JOKER_CATALOGUE
from balatro_sim.jokers.base import JOKER_REGISTRY

# ── real side ───────────────────────────────────────────────────────────────
real = {}  # id -> (name, rarity)
text = open("vendor/balatro-rs/balatro-types/src/joker.rs", encoding="utf-8", errors="replace").read()
for m in re.finditer(r'(\w+),\s+"(j_[a-z0-9_]+)",\s+"([^"]+)",\s+(\w+),\s+(\d+)', text):
    real[m.group(2)] = (m.group(3), m.group(4).lower())

# ── sim side ────────────────────────────────────────────────────────────────
sim_names = {k: v.get("name", k) for k, v in JOKER_CATALOGUE.items()}
sim_rarity = {k: v.get("rarity", "?").lower() for k, v in JOKER_CATALOGUE.items()}


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


sim_by_name = {}
for key, name in sim_names.items():
    sim_by_name.setdefault(norm(name), key)

reg_by_name = {}
for key in JOKER_REGISTRY:
    n = norm(key)
    reg_by_name.setdefault(n, key)
    # also match by stripping common suffixes (greedy_joker / greedy_mult)
    for cand in (key.replace("j_", ""),):
        reg_by_name.setdefault(norm(cand), key)

offered, unoffered, missing, rarity_mismatch = [], [], [], []
for rid, (rname, rrar) in sorted(real.items()):
    n = norm(rname)
    skey = sim_by_name.get(n)
    if skey:
        offered.append((rid, rname, skey))
        srar = sim_rarity[skey]
        # normalize rarity labels (common/uncommon/rare/legendary)
        if srar != rrar:
            rarity_mismatch.append((rid, rname, skey, rrar, srar))
    else:
        # effect implemented under a differently-named key?
        if n in reg_by_name:
            unoffered.append((rid, rname, reg_by_name[n]))
        else:
            missing.append((rid, rname))

print(f"real jokers: {len(real)} | offered: {len(offered)} | unoffered: {len(unoffered)} | missing: {len(missing)}")

print(f"\n=== MISSING (no sim effect at all) — {len(missing)} ===")
for rid, rname in missing:
    print(f"  {rid:22s} {rname}")

print(f"\n=== IMPLEMENTED but NOT shop-offerable — {len(unoffered)} ===")
for rid, rname, key in unoffered:
    print(f"  {rid:22s} {rname:24s} registry_key={key}")

print(f"\n=== RARITY MISMATCH (real -> sim) — {len(rarity_mismatch)} ===")
for rid, rname, skey, rrar, srar in rarity_mismatch:
    print(f"  {rid:22s} {rname:24s} real={rrar:10s} sim({skey})={srar}")
