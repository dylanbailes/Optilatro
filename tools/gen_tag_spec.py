"""Generate tools/tag_spec.json — machine-readable skip-blind Tag contracts
parsed from balatro-mechanics-reference(2).md §14 (the project's source of
truth), keyed by the sim's canonical keys (t_*).

Each spec entry:
  tags:   {name, effect, ante, kind}
      ante  — the sim's min-ante gate (1 or 2; the doc's table has no ante
              column — the 9 ante-2 gates come from the real game, wiki-verified)
      kind  — "instant" (applied at skip time) / "shop" (one-shot modifier
              consumed by the next shop) / "queue" (pending state resolved
              later) — the sim's effect-dispatch taxonomy
  gated:  the 9 tags excluded from the Ante-1 pool
  packs:  tag -> free booster pack key (the 5 free-pack tags)

Consumed by tools/audit_tags_static.py (structural gates) and
tests/test_tag_spec.py (behavioral, per-tag doc-effect assertions).
Regenerate after any reference-doc edit:  python tools/gen_tag_spec.py
The generator itself is a gate: it exits 1 on any doc row that cannot be
matched to a sim key, any sim key with no doc row, or a count mismatch (24).
"""
import json
import re
import sys

sys.path.insert(0, "vendor/balatro-rl")
from balatro_sim.tags import TAG_CATALOGUE, TAG_ORDER, _TAG_PACK

DOC = "balatro-mechanics-reference(2).md"
OUT = "tools/tag_spec.json"


def tag_key(name: str) -> str:
    """Map a doc §14 display name ('Uncommon Tag') to the sim key (t_uncommon)."""
    slug = re.sub(r"[^a-z0-9]", "_", name.lower()).strip("_")
    slug = slug.replace("tag", "").strip("_")          # drop the trailing "Tag"
    return "t_" + re.sub(r"_+", "_", slug).strip("_")


def main() -> int:
    text = open(DOC, encoding="utf-8").read()
    start = text.index("## 14. Tags")
    end = text.index("## 15.", start)
    section = text[start:end]

    rows = []
    for line in section.splitlines():
        m = re.match(r"^\|\s*(.+?)\s*\|\s*(.+?)\s*\|\s*$", line)
        if not m or m.group(1) in ("Tag", "---"):
            continue
        name, effect = m.groups()
        rows.append((name.strip(), effect.strip()))

    tags = {}
    for name, effect in rows:
        key = tag_key(name)
        if key not in TAG_CATALOGUE:
            print(f"gen_tag_spec FAILED: doc name {name!r} -> unknown key {key}")
            return 1
        entry = TAG_CATALOGUE[key]
        tags[key] = {
            "name": entry[0], "ante": entry[1], "kind": entry[2],
            "effect": effect,
        }

    sim_keys = set(TAG_ORDER)
    doc_keys = set(tags)
    errors = []
    if len(tags) != 24:
        errors.append(f"doc parsed {len(tags)} tag rows, expected 24")
    if sim_keys != doc_keys:
        errors.append(f"sim-only keys {sorted(sim_keys - doc_keys)}; "
                      f"doc-only keys {sorted(doc_keys - sim_keys)}")
    for key in sim_keys:
        if TAG_CATALOGUE[key][0] != tags[key]["name"]:
            errors.append(f"{key}: sim name {TAG_CATALOGUE[key][0]} != "
                          f"doc name {tags[key]['name']}")
    if errors:
        print("gen_tag_spec FAILED:")
        for e in errors:
            print("  -", e)
        return 1

    gated = sorted(k for k in TAG_ORDER if TAG_CATALOGUE[k][1] > 1)
    payload = {"tags": tags, "gated": gated, "packs": dict(_TAG_PACK)}
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, sort_keys=True)
    kinds = {}
    for k in TAG_ORDER:
        kinds.setdefault(TAG_CATALOGUE[k][2], []).append(k)
    print(f"gen_tag_spec OK: {len(tags)} tags, {len(gated)} ante-2 gated "
          f"({gated}), kinds "
          + ", ".join(f"{kn}={len(v)}" for kn, v in sorted(kinds.items())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
