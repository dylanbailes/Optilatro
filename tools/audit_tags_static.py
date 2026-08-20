"""Static skip-blind Tag audit — catalogue + roll + apply-path fidelity gate.

Verifies the sim's tag definitions and apply paths against
tools/tag_spec.json, which is generated from docs/reference/balatro-mechanics.md
§14 (the project's source of truth).

Gates, each of which must report 0:

  NAMES   — every t_* key's display name must EXACTLY match the doc §14 table.
  COUNTS  — 24 tags, bidirectional spec <-> sim coverage.
  ANTE    — the 9 ante-2-gated tags must be exactly the real game's list
            (wiki: Negative, Standard, Meteor, Buffoon, Handy, Garbage,
            Ethereal, Top-up, Orbital); the other 15 appear from Ante 1.
            roll_tag must offer no tag on Boss blinds and honor the gate.
  EFFECT  — per-tag semantic regexes: instant tags against apply_tag's
            branches in tags.py, shop tags against their consumption site in
            shop.py (the pending_* flag AND the shop-side effect), queue tags
            against their resolution in game.py. Code-specific patterns so a
            regression fails CI.
  WIRED   — roll_tag draws one weighted pick per non-Boss blind on the
            Tag{ante} RNG node through TAG_CATALOGUE, and game.py actually
            calls roll_tag / apply_tag on skip.

Known, documented divergences (deliberate sim choices, not bugs — covered by
behavioral tests):
  - Orbital Tag upgrades the HIGHEST-leveled hand deterministically. The real
    game shows a random poker hand type on the tag; the sim auto-applies at
    skip time with no tag UI, and the highest-level choice is the agent-optimal
    deterministic analogue (code comment in tags.py).
  - Tag weights are uniform (TAG_WEIGHTS all 1.0). The real game weights a few
    tags non-uniformly / discovery-gates edition tags; the sim treats the
    collection as complete and A5 (tag weights) is still pending balatro-seed
    alignment. The draw COUNT is correct (one pick per blind).

Usage:  python tools/audit_tags_static.py [--json]
Exit:   0 when all gates are clean, 1 otherwise.
"""
import json
import re
import sys

sys.path.insert(0, "vendor/balatro-rl")
from balatro_sim.tags import TAG_CATALOGUE, TAG_ORDER, TAG_WEIGHTS

SPEC = "tools/tag_spec.json"
TAGS = "vendor/balatro-rl/balatro_sim/tags.py"
SHOP = "vendor/balatro-rl/balatro_sim/shop.py"
GAME = "vendor/balatro-rl/balatro_sim/game.py"

#: The real game's 9 Ante-2-gated tags (wiki Tags page — the doc §14 table has
#: no ante column; this list is the wiki-verified real-game gate).
ANTE2_GATED = {
    "t_negative", "t_standard", "t_meteor", "t_buffoon", "t_handy",
    "t_garbage", "t_ethereal", "t_top_up", "t_orbital",
}

#: tag -> [(file, pattern), ...]. Every pattern must match in its named file.
#: instant tags live entirely in apply_tag (tags.py); shop tags set a pending
#: flag in tags.py and are consumed in shop.py; queue tags set a flag in
#: tags.py and resolve in game.py.
TAG_EFFECT = {
    # ── instant (apply_tag branches, tags.py) ───────────────────────────────
    "t_economy":  [("tags", r"game\.dollars < 40"), ("tags", r"game\.dollars \+= 40"),
                   ("tags", r"game\.dollars = 0")],
    "t_speed":    [("tags", r"5 \* game\.skipped_blinds")],
    "t_garbage":  [("tags", r"game\.run_unused_discards")],
    "t_handy":    [("tags", r"game\.run_hands_played")],
    "t_orbital":  [("tags", r"planet_levels\[best\] \+= 3")],
    "t_top_up":   [("tags", r"_add_topup_jokers"), ("tags", r"random_joker_key\("),
                    ("tags", r'rarity="Common"')],
    "t_charm":    [("tags", r"p_arcana_mega"), ("tags", r"_open_pack_tag")],
    "t_buffoon":  [("tags", r"p_buffoon_mega"), ("tags", r"_open_pack_tag")],
    "t_ethereal": [("tags", r"p_spectral"), ("tags", r"_open_pack_tag")],
    "t_meteor":   [("tags", r"p_celestial_mega"), ("tags", r"_open_pack_tag")],
    "t_standard": [("tags", r"p_standard_mega"), ("tags", r"_open_pack_tag")],
    # ── shop: flag set in tags.py, consumed in shop.py ──────────────────────
    "t_coupon":   [("shop", r"item\.kind != \"voucher\""), ("shop", r"item\.price = 0")],
    "t_d6":       [("shop", r"reroll_cost = 0")],
    "t_uncommon": [("tags", r'pending_free_rarity = "Uncommon"'),
                    ("shop", r"rarity=free_rarity")],
    "t_rare":     [("tags", r'pending_free_rarity = "Rare"'),
                    ("shop", r"rarity=free_rarity")],
    "t_foil":     [("tags", r'pending_free_edition = "Foil"'),
                    ("shop", r"free_edition = game\.pending_free_edition")],
    "t_holographic": [("tags", r'pending_free_edition = "Holographic"'),
                       ("shop", r"free_edition = game\.pending_free_edition")],
    "t_polychrome":  [("tags", r'pending_free_edition = "Polychrome"'),
                       ("shop", r"free_edition = game\.pending_free_edition")],
    "t_negative": [("tags", r'pending_free_edition = "Negative"'),
                    ("shop", r"free_edition = game\.pending_free_edition")],
    "t_voucher":  [("tags", r"pending_voucher = True"), ("shop", r"voucher_extra")],
    # ── queue: flag set in tags.py, resolved in game.py ─────────────────────
    "t_investment": [("tags", r"investment_pending = True"), ("game", r"dollars \+= 25")],
    "t_boss":     [("tags", r"boss_reroll_pending = True"),
                    ("game", r"boss_appearances"), ("game", r"exclude=boss_key")],
    "t_juggle":   [("tags", r"hand_size_bonus_next_round = 3")],
    "t_double":   [("tags", r"double_tag_active = True"),
                    ("game", r"apply_tag\(self, key\)\s+apply_tag\(self, key\)")],
}


def main() -> int:
    spec = json.load(open(SPEC, encoding="utf-8"))
    tags_spec, gated_spec, packs_spec = (spec["tags"], set(spec["gated"]),
                                         spec["packs"])
    tags_src = open(TAGS, encoding="utf-8").read()
    shop_src = open(SHOP, encoding="utf-8").read()
    game_src = open(GAME, encoding="utf-8").read()
    srcs = {"tags": tags_src, "shop": shop_src, "game": game_src}

    names_bad, counts_bad, ante_bad, effect_bad, wired_bad = [], [], [], {}, []

    # ── NAMES + COUNTS — 24 tags, bidirectional ─────────────────────────────
    sim_keys = set(TAG_ORDER)
    doc_keys = set(tags_spec)
    if len(sim_keys) != 24:
        counts_bad.append(f"sim has {len(sim_keys)} tags, expected 24")
    if sim_keys != doc_keys:
        counts_bad.append(f"sim-only {sorted(sim_keys - doc_keys)}; "
                          f"doc-only {sorted(doc_keys - sim_keys)}")
    for key in sorted(sim_keys):
        sim_name = TAG_CATALOGUE[key][0]
        doc_name = tags_spec[key]["name"]
        if sim_name != doc_name:
            names_bad.append(f"{key}: sim {sim_name!r} vs doc {doc_name!r}")

    # ── ANTE — the exact 9 gated tags ───────────────────────────────────────
    if gated_spec != ANTE2_GATED:
        ante_bad.append(f"gated {sorted(gated_spec)} vs wiki "
                        f"{sorted(ANTE2_GATED)}")
    for key in sim_keys:
        is_gated = key in ANTE2_GATED
        sim_ante = TAG_CATALOGUE[key][1]
        if is_gated and sim_ante != 2:
            ante_bad.append(f"{key}: gated but sim min-ante {sim_ante}")
        if not is_gated and sim_ante != 1:
            ante_bad.append(f"{key}: not gated but sim min-ante {sim_ante}")

    # ── EFFECT — per-tag semantics at the implementing site ─────────────────
    for key, pairs in TAG_EFFECT.items():
        missing = [p for f, p in pairs if not re.search(p, srcs[f])]
        if missing:
            effect_bad[key] = missing
    # The economy formula must NOT contain the old total-cap model.
    if re.search(r"min\(game\.dollars \* 2, 40\)", tags_src):
        effect_bad["t_economy"] = effect_bad.get("t_economy", []) + \
            ["old total-cap model present (min(dollars*2, 40))"]

    # ── WIRED — roll_tag + skip dispatch ────────────────────────────────────
    wired_checks = {
        "roll_tag gates on is_boss": (tags_src, r"is_boss"),
        "roll_tag uses node_tag(ante)": (tags_src, r"node_tag\(game\.ante\)"),
        "roll_tag reads TAG_CATALOGUE": (tags_src, r"TAG_CATALOGUE"),
        "game imports roll_tag/apply_tag": (game_src,
                                            r"from \.tags import roll_tag, apply_tag"),
        "skip calls apply_tag": (game_src, r"apply_tag\(self, key\)"),
        "roll offers no boss tag": (tags_src,
                                    r'if getattr\(game\.current_blind, "is_boss", False\):'),
        "weights uniform (A5 pending)": (tags_src,
                                         r"TAG_WEIGHTS = \{k: 1\.0 for k in TAG_ORDER\}"),
    }
    for label, (src, pat) in wired_checks.items():
        if not re.search(pat, src):
            wired_bad.append(label)

    # ── Report ──────────────────────────────────────────────────────────────
    lines = ["tag spec: 24 tags, "
             f"{len(gated_spec)} ante-2 gated, packs {len(packs_spec)}"]
    lines.append(f"NAMES    {len(names_bad)}")
    for why in names_bad:
        lines.append(f"    {why}")
    lines.append(f"COUNTS   {len(counts_bad)}")
    for why in counts_bad:
        lines.append(f"    {why}")
    lines.append(f"ANTE     {len(ante_bad)}")
    for why in ante_bad:
        lines.append(f"    {why}")
    lines.append(f"EFFECT   {sum(len(v) for v in effect_bad.values())}")
    for k, pats in sorted(effect_bad.items()):
        lines.append(f"    {k:18s} missing patterns: {', '.join(pats)}")
    lines.append(f"WIRED    {len(wired_bad)}")
    for why in wired_bad:
        lines.append(f"    {why}")
    print("\n".join(lines))

    if "--json" in sys.argv:
        json.dump({"names": names_bad, "counts": counts_bad, "ante": ante_bad,
                   "effect": effect_bad, "wired": wired_bad},
                  open("tools/out_audit_tags.json", "w", encoding="utf-8"),
                  indent=2, sort_keys=True)

    ok = not (names_bad or counts_bad or ante_bad or effect_bad or wired_bad)
    print("GATES:", "CLEAN" if ok else "ISSUES FOUND")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
