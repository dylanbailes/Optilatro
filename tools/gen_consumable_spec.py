"""Generate tools/consumable_spec.json — machine-readable Tarot / Planet /
Spectral / Voucher contracts parsed from balatro-mechanics-reference(2).md
§3-§5 + §9 (the project's source of truth), keyed by the sim's canonical
keys (c_*/pl_*/s_*/v_*).

Each spec entry:
  tarots/spectrals: {name, effect, targets, cost, sell}
      targets — the doc's Targets column collapsed to a MAX integer
                (0 = no targets, 2 = "1-2", 3 = "1-3").
  planets:        {name, hand_type, cost, sell}
  vouchers:       {name, effect, base, upgrade_of}
      base       — True for the 16 base vouchers, False for the 16 upgrades
      upgrade_of — the base key for upgrades, "" for base vouchers

Consumed by tools/audit_consumables_static.py (structural gates) and
tests/test_consumable_spec.py (behavioral, per-card doc-effect assertions).
Regenerate after any reference-doc edit:  python tools/gen_consumable_spec.py
The generator itself is a gate: it exits 1 on any doc row that cannot be
matched to a sim key, any sim key with no doc row, or a count mismatch
(22 tarots / 12 planets / 18 spectrals / 32 vouchers in 16 pairs).
"""
import json
import re
import sys

sys.path.insert(0, "vendor/balatro-rl")
from balatro_sim.consumables import (
    ALL_PLANETS, ALL_SPECTRALS, ALL_TAROTS,
    PLANET_HAND, PLANET_NAME, SPECTRAL_NAME, TAROT_NAME,
    VOUCHER_NAME,
)

DOC = "balatro-mechanics-reference(2).md"
OUT = "tools/consumable_spec.json"

#: family -> (section header, doc cost $, doc sell $)
FAMILIES = {
    "tarots":    ("## 3. Tarot Cards (22 total)", 3, 1),
    "planets":   ("## 4. Planet Cards (12 total)", 3, 1),
    "spectrals": ("## 5. Spectral Cards (18 total)", 4, 2),
}


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def parse_targets(cell: str) -> int:
    cell = cell.strip()
    if cell == "0":
        return 0
    parts = re.split(r"[–\-]", cell)
    return int(parts[-1])  # max target count


def main() -> int:
    text = open(DOC, encoding="utf-8").read()
    sections = {
        "tarots":    (text.index(FAMILIES["tarots"][0]),
                      text.index(FAMILIES["planets"][0])),
        "planets":   (text.index(FAMILIES["planets"][0]),
                      text.index(FAMILIES["spectrals"][0])),
        "spectrals": (text.index(FAMILIES["spectrals"][0]),
                      text.index("## 6. Card Enhancements")),
    }

    sim = {
        "tarots":    TAROT_NAME,
        "planets":   PLANET_NAME,
        "spectrals": SPECTRAL_NAME,
    }
    expect = {"tarots": 22, "planets": 12, "spectrals": 18}

    out = {"tarots": {}, "planets": {}, "spectrals": {}, "vouchers": {}}
    problems = []

    for fam, (start, end) in sections.items():
        body = text[start:end]
        _, cost, sell = FAMILIES[fam]
        name_to_key = {}
        for key, nm in sim[fam].items():
            name_to_key.setdefault(norm(nm), key)

        rows = []
        for line in body.splitlines():
            line = line.strip()
            if not (line.startswith("|") and line.endswith("|")):
                continue
            cells = [c.strip() for c in line.strip("|").split("|")]
            if fam == "planets":
                if len(cells) < 2 or not cells[0] or cells[0].startswith("-"):
                    continue
                if cells[1] == "Levels Up":  # header row (not bold)
                    continue
                rows.append((cells[0], cells[1]))
            else:
                if len(cells) < 3 or not cells[0].startswith("**"):
                    continue
                rows.append((cells[0].strip("*").strip(),
                             " | ".join(cells[1:-1]), cells[-1]))

        matched = 0
        for row in rows:
            if fam == "planets":
                name, hand = row
                key = name_to_key.get(norm(name))
                if key is None:
                    problems.append(f"{fam}: doc row '{name}' unmatched in sim")
                    continue
                out[fam][key] = {"name": name, "hand_type": hand,
                                 "cost": cost, "sell": sell}
                if hand != PLANET_HAND.get(key):
                    problems.append(
                        f"planets: {key} sim levels '{PLANET_HAND.get(key)}' "
                        f"but doc says '{hand}'")
                matched += 1
            else:
                name, effect, targets = row
                key = name_to_key.get(norm(name))
                if key is None:
                    problems.append(f"{fam}: doc row '{name}' unmatched in sim")
                    continue
                out[fam][key] = {"name": name, "effect": effect,
                                 "targets": parse_targets(targets),
                                 "cost": cost, "sell": sell}
                matched += 1

        missing = sorted(k for k in sim[fam] if k not in out[fam])
        if missing:
            problems.append(f"{fam}: sim keys with no doc row: {missing}")
        if len(sim[fam]) != expect[fam]:
            problems.append(f"{fam}: count {len(sim[fam])} != doc {expect[fam]}")
        print(f"{fam}: {matched} doc rows matched, {len(out[fam])} spec entries"
              + (f", PROBLEMS: {missing}" if missing else ""))

    # ── vouchers (§9: 4-column base/upgrade table) ──────────────────────────
    v_start = text.index("## 9. Vouchers (32 total")
    v_end = text.index("## 10. Boss Blinds")
    vrows = []
    for line in text[v_start:v_end].splitlines():
        line = line.strip()
        if not (line.startswith("|") and line.endswith("|")):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 4 or not cells[0].startswith("**"):
            continue
        vrows.append((cells[0].strip("*").strip(), cells[1],
                      cells[2].strip("*").strip(), cells[3]))
    vkey = {}
    for key, nm in VOUCHER_NAME.items():
        vkey.setdefault(norm(nm), key)
    vmatched = 0
    for base_name, base_eff, up_name, up_eff in vrows:
        b = vkey.get(norm(base_name))
        u = vkey.get(norm(up_name))
        if b is None or u is None:
            problems.append(f"vouchers: doc pair '{base_name}' -> "
                            f"'{up_name}' unmatched in sim")
            continue
        out["vouchers"][b] = {"name": base_name, "effect": base_eff,
                               "base": True, "upgrade_of": ""}
        out["vouchers"][u] = {"name": up_name, "effect": up_eff,
                               "base": False, "upgrade_of": b}
        vmatched += 1
    vmissing = sorted(k for k in VOUCHER_NAME if k not in out["vouchers"])
    if vmissing:
        problems.append(f"vouchers: sim keys with no doc row: {vmissing}")
    if len(VOUCHER_NAME) != 32:
        problems.append(f"vouchers: count {len(VOUCHER_NAME)} != doc 32")
    if vmatched != 16:
        problems.append(f"vouchers: {vmatched} doc pairs parsed != 16")
    print(f"vouchers: {vmatched} doc pairs matched, "
          f"{len(out['vouchers'])} spec entries")

    if problems:
        print("SPEC PROBLEMS:")
        for p in problems:
            print(f"  - {p}")
    else:
        print("spec: all doc rows matched, all keys covered, counts OK, "
              "planet hand-type mapping OK")

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, sort_keys=True)
        f.write("\n")
    print(f"wrote {OUT}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
