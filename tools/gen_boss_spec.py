"""Generate tools/boss_spec.json — machine-readable Boss Blind contracts parsed
from docs/reference/balatro-mechanics.md §10 + §16 (the project's source of
truth), keyed by the sim's canonical keys (bl_*).

Each spec entry:
  bosses:   {name, min_ante, effect, finisher}
      finisher — True for the 5 Ante-8 Showdown blinds, False otherwise
  matador:  the 13 Matador-compatible boss keys (doc's Matador list)
  showdown: the 5 Showdown (Ante-8 finisher) keys
  scaling:  the §16 large-blind chip multipliers
            {bl_wall: 4, bl_violet: 6, bl_needle: 1} (2x is the normal Boss)

Consumed by tools/audit_bosses_static.py (structural gates) and
tests/test_boss_spec.py (behavioral, per-boss doc-effect assertions).
Regenerate after any reference-doc edit:  python tools/gen_boss_spec.py
The generator itself is a gate: it exits 1 on any doc row that cannot be
matched to a sim key, any sim key with no doc row, or a count mismatch
(28 bosses = 23 regular + 5 finishers).
"""
import json
import re
import sys

from _paths import REFERENCE_DOC, ROOT, VENDOR_RL

sys.path.insert(0, str(VENDOR_RL))
from balatro_sim.game import BOSS_MIN_ANTE, SHOWDOWN_BOSSES

DOC = str(REFERENCE_DOC)
OUT = str(ROOT / "tools" / "boss_spec.json")

#: Doc display name -> sim key. The slug rule ("The Arm" -> bl_arm) covers
#: everything except The Arm, whose sim key is the internal-name bl_grim.
NAME_TO_KEY = {
    "The Arm": "bl_grim",
}
#: Slug-rule exceptions handled explicitly (finishers have no "The " prefix).
SLUG_KEYS = {
    "Amber Acorn": "bl_amber", "Cerulean Bell": "bl_cerulean",
    "Crimson Heart": "bl_crimson", "Verdant Leaf": "bl_verdant",
    "Violet Vessel": "bl_violet",
}


def boss_key(name: str) -> str:
    """Map a doc §10 display name to the sim's bl_* key."""
    name = name.strip().strip("*")
    if name in NAME_TO_KEY:
        return NAME_TO_KEY[name]
    if name in SLUG_KEYS:
        return SLUG_KEYS[name]
    if name.startswith("The "):
        slug = re.sub(r"[^a-z0-9]", "_", name[4:].lower()).strip("_")
        return "bl_" + slug
    return "bl_" + re.sub(r"[^a-z0-9]", "_", name.lower()).strip("_")


def main() -> int:
    text = open(DOC, encoding="utf-8").read()
    start = text.index("## 10. Boss Blinds")
    end = text.index("**Selection algorithm.**", start)
    section = text[start:end]

    rows = []
    for line in section.splitlines():
        m = re.match(r"^\|\s*(.+?)\s*\|\s*(.+?)\s*\|\s*(.+?)\s*\|\s*$", line)
        if not m or m.group(1) in ("Boss Blind", "---"):
            continue
        name_cell, ante_cell, effect = m.groups()
        finisher = "*(Finisher)*" in name_cell
        name = name_cell.replace("*(Finisher)*", "").strip().strip("*")
        rows.append((name, int(ante_cell.strip()), effect.strip(), finisher))

    bosses = {}
    for name, ante, effect, finisher in rows:
        key = boss_key(name)
        bosses[key] = {
            "name": name, "min_ante": ante, "effect": effect,
            "finisher": finisher,
        }

    # ── Matador-compatible list ─────────────────────────────────────────────
    mm = re.search(r"\*\*Matador-compatible Bosses\*\*[^:]*:\s*(.+)$",
                   text, re.M)
    matador_names = [n.strip().rstrip(".").lstrip("and ").strip()
                     for n in mm.group(1).split(",")]
    matador = [boss_key(n) for n in matador_names]

    # ── §16 large-blind scaling exceptions ──────────────────────────────────
    s16 = text[text.index("## 16."):]
    sm = re.search(r"Exceptions:\s*(.+?);", s16)
    scaling = {}
    for name, mult in re.findall(r"([A-Za-z ]+?)\s*(\d+)x", sm.group(1)):
        scaling[boss_key(name.strip())] = int(mult)

    showdown = sorted(k for k, e in bosses.items() if e["finisher"])
    regular = sorted(k for k, e in bosses.items() if not e["finisher"])

    # ── Bidirectional validation against the sim ────────────────────────────
    errors = []
    if len(bosses) != 28:
        errors.append(f"doc parsed {len(bosses)} boss rows, expected 28")
    if len(regular) != 23:
        errors.append(f"doc parsed {len(regular)} regular bosses, expected 23")
    if len(showdown) != 5:
        errors.append(f"doc parsed {len(showdown)} finishers, expected 5")
    if len(matador) != 13:
        errors.append(f"doc parsed {len(matador)} Matador bosses, expected 13")
    sim_keys = set(BOSS_MIN_ANTE)
    doc_keys = set(bosses)
    if sim_keys != doc_keys:
        errors.append(
            f"sim keys missing from doc: {sorted(sim_keys - doc_keys)}; "
            f"doc-only keys: {sorted(doc_keys - sim_keys)}")
    if set(SHOWDOWN_BOSSES) != set(showdown):
        errors.append(
            f"SHOWDOWN_BOSSES {sorted(SHOWDOWN_BOSSES)} vs doc "
            f"{sorted(showdown)}")
    if errors:
        print("gen_boss_spec FAILED:")
        for e in errors:
            print("  -", e)
        return 1

    payload = {
        "bosses": bosses,
        "matador": matador,
        "showdown": showdown,
        "scaling": scaling,
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, sort_keys=True)
    print(f"gen_boss_spec OK: {len(bosses)} bosses "
          f"({len(regular)} regular + {len(showdown)} finishers), "
          f"{len(matador)} Matador, scaling {scaling}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
