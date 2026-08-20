"""Generate tools/joker_spec.json — machine-readable joker contracts parsed
from docs/reference/balatro-mechanics.md §2 (the project's source of truth),
keyed by the sim's canonical JOKER_CATALOGUE keys.

Each spec entry: {name, cost, type, effect, timing}
  name    — exact doc name (also the catalogue name)
  cost    — doc base cost ($)
  type    — effect class: Chips | +Mult | xMult | Effect | ...
  effect  — the doc's effect wording (for humans / future behavioral tests)
  timing  — the doc's Activation column (On Scored / On Held / On Discard / ...)

Consumed by tools/audit_jokers_static.py (structural gates) and
tests/test_joker_spec.py (per-joker behavioral assertions). Regenerate after
any reference-doc edit:  python tools/gen_joker_spec.py
"""
import json
import re
import sys

from _paths import REFERENCE_DOC, ROOT, VENDOR_RL

sys.path.insert(0, str(VENDOR_RL))
from balatro_sim.shop import JOKER_CATALOGUE  # canonical key -> {name, rarity, price}

DOC = str(REFERENCE_DOC)
OUT = str(ROOT / "tools" / "joker_spec.json")


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def main() -> int:
    text = open(DOC, encoding="utf-8").read()
    start = text.index("## 2. Jokers")
    end = text.index("## 3. Tarot Cards")
    body = text[start:end]

    # ── parse §2 table rows ──────────────────────────────────────────────────
    rows = []  # (name, cost, type, effect, timing)
    for line in body.splitlines():
        line = line.strip()
        if not (line.startswith("|") and line.endswith("|")):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 5:
            continue
        name = cells[0]
        if not name.startswith("**"):
            continue  # subsection headers / separator rows
        m = re.match(r"\$?(\d+)", cells[1])
        if not m:
            print(f"ANOMALY (cost): {line}")
            continue
        # Effect cells may themselves contain '|' — join everything between
        # type and timing.
        timing = cells[-1]
        effect = " | ".join(cells[3:-1])
        rows.append((name.strip("*").strip(), int(m.group(1)),
                     cells[2], effect, timing))

    # ── match names to canonical keys ────────────────────────────────────────
    by_name: dict[str, str] = {}
    for key, info in JOKER_CATALOGUE.items():
        by_name.setdefault(norm(info["name"]), key)

    spec: dict[str, dict] = {}
    unmatched = []
    cost_mismatch = []
    for name, cost, jtype, effect, timing in rows:
        key = by_name.get(norm(name))
        if key is None:
            unmatched.append(name)
            continue
        entry = {"name": name, "cost": cost, "type": jtype,
                 "effect": effect, "timing": timing}
        if key in spec:
            print(f"WARNING: duplicate doc row for {key} ({name})")
            continue
        spec[key] = entry
        if JOKER_CATALOGUE[key].get("price") != cost:
            cost_mismatch.append((key, JOKER_CATALOGUE[key].get("price"), cost))

    # ── report ───────────────────────────────────────────────────────────────
    print(f"doc rows parsed: {len(rows)}")
    print(f"spec entries:    {len(spec)}  (catalogue has {len(JOKER_CATALOGUE)})")
    missing = sorted(set(JOKER_CATALOGUE) - set(spec))
    print(f"catalogue keys with no doc row: {missing if missing else 'none'}")
    print(f"doc rows unmatched to a catalogue key: {unmatched if unmatched else 'none'}")
    if cost_mismatch:
        print(f"cost mismatches (catalogue vs doc): "
              f"{[(k, a, b) for k, a, b in cost_mismatch]}")
    else:
        print("cost check: all catalogue prices match the doc")

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(spec, f, indent=2, sort_keys=True)
        f.write("\n")
    print(f"wrote {OUT}")
    return 1 if (unmatched or missing or cost_mismatch) else 0


if __name__ == "__main__":
    sys.exit(main())
