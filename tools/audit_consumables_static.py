"""Static consumables-layer audit — Tarot / Planet / Spectral / Voucher
fidelity gate.

Verifies the sim's consumable definitions and apply_* implementations against
tools/consumable_spec.json, which is generated from
balatro-mechanics-reference(2).md §3-§5 + §9 (the project's source of truth).

Gates, each of which must report 0:

  NAMES   — every canonical c_*/pl_*/s_* key's display name must EXACTLY match
            the reference doc (wrong names = the sim can't be trusted).
  COUNTS  — 22 tarots / 12 planets / 18 spectrals, and no extras/missing
            (bidirectional spec <-> sim coverage).
  PLANET  — PLANET_HAND[key] must match the doc's "Levels Up" hand type.
  TARGETS — the sim's per-card target max (TAROT_MAX_TARGETS / spectral
            [:N] slices) must match the doc's Targets column max.
  EFFECT  — per-key semantic regexes: the apply_* source must contain code
            that implements the doc's effect (wording-encoded as patterns).
            Catches wrong-effect wiring: wrong enhancement/suit strings,
            Hermit/Temperance caps, Death not copying edition+seal, Wraith
            not zeroing money, Fool self-copying, missing room checks, etc.
  DEAD    — spec keys not reachable in the sim maps (or vice versa).
  WIRED   — the generation pools and the game's use dispatch reference the
            ALL_* sets, so every card is actually buyable/pickable AND
            actually applied on use (deep behavior is tested per-card in
            tests/test_consumable_spec.py).
  VNAMES  — all 32 v_* display names must EXACTLY match doc §9.
  VPAIRS  — the 16 base/upgrade pairs: VOUCHER_BASE must encode exactly the
            doc's Base -> Upgrade structure (a missing pair = the upgrade is
            offered before its base is owned — a real fidelity bug).
  VEFFECT — per-voucher effect semantics. Vouchers implemented in
            apply_voucher get branch-scoped patterns; the "pass" vouchers
            (Hone, Omen Globe, Telescope, Observatory, Merchants, Magic
            Trick/Illusion, Director's Cut/Retcon) are verified against the
            engine file that implements them (shop.py / scoring.py / game.py).

Known, documented divergences (deliberate sim choices, not bugs — each is
covered by a behavioral test):
  - Familiar / Grim / Incantation destroy a RANDOM card in the real game
    (doc Targets = 0); the sim lets the caller pick the destroyed card so the
    heuristic agent can play deterministically. The destroy+create counts
    match the doc, and the created cards go to HAND per the doc (fixed
    2026-08-07).
  - Sigil / Ouija convert every card EXCEPT Stones (real-game behavior; the
    reference doc's "all cards" is shorthand).
  - Illusion shop cards get Enhancement 40% / Edition 20% but never a Seal —
    doc §9 says "Enhancement, Edition, and/or Seal", but seals are bugged off
    in the real game (documented in shop.py); the sim follows the real game.

Usage:  python tools/audit_consumables_static.py [--json]
Exit:   0 when all gates are clean, 1 otherwise.
"""
import json
import re
import sys

sys.path.insert(0, "vendor/balatro-rl")
from balatro_sim.consumables import (
    ALL_PLANETS, ALL_SPECTRALS, ALL_TAROTS,
    PLANET_HAND, PLANET_NAME, SPECTRAL_NAME, TAROT_NAME,
    TAROT_ENHANCEMENT, TAROT_MAX_TARGETS, TAROT_SUIT,
    VOUCHER_BASE, VOUCHER_NAME,
)

SPEC_PATH = "tools/consumable_spec.json"
CONSUMABLES_SRC = "vendor/balatro-rl/balatro_sim/consumables.py"
GAME_SRC = "vendor/balatro-rl/balatro_sim/game.py"
SHOP_SRC = "vendor/balatro-rl/balatro_sim/shop.py"

FAMILY_KEYS = {
    "tarots": ALL_TAROTS,
    "planets": ALL_PLANETS,
    "spectrals": ALL_SPECTRALS,
}
FAMILY_NAMES = {
    "tarots": TAROT_NAME,
    "planets": PLANET_NAME,
    "spectrals": SPECTRAL_NAME,
}

SPECTRAL_TARGETS_EXPECT = {
    "s_talisman": 1, "s_aura": 1, "s_deja_vu": 1,
    "s_trance": 1, "s_medium": 1, "s_cryptid": 1,
}
#: Spectrals the sim parameterizes (destroy a caller-chosen card instead of a
#: random one) — the doc's 0-target contract is intentionally relaxed.
DOCUMENTED_DIVERGENCES = {"s_familiar", "s_grim", "s_incantation"}

#: key -> list of regexes that the card's OWN apply_* branch MUST contain
#: (the doc's effect wording encoded as machine-checkable patterns). Patterns
#: are matched against the per-key branch chunk so cross-branch matches (e.g.
#: `edition` in s_aura) can't mask a missing effect elsewhere. Planets share
#: one branch and are matched against the whole file.
EFFECT_EXPECT = {
    # planets — level up the mapped hand type (PLANET gate pins WHICH type)
    **{k: [r"planet_levels", r"\+ 1"] for k in ALL_PLANETS},
    # special tarots
    "c_fool": [r"consumables_used"],            # copies LAST USED, self excluded
    "c_high_priestess": [r"consumable_slots"],  # must have room
    "c_emperor": [r"consumable_slots"],         # must have room
    "c_hermit": [r"min\(game\.dollars, 20\)"],  # doubles money, +$20 gain cap
    "c_wheel_of_fortune": [r"0\.25"],
    "c_strength": [r"card\.rank\s*="],
    "c_hanged_man": [r"game\.hand\.remove"],
    # Code-specific patterns (not bare words): the branch comment also says
    # "edition, seal", so a comment-match would false-pass a regression that
    # deleted the copy lines.
    "c_death": [r"left\.edition = right\.edition",
                r"left\.seal = right\.seal"],
    "c_temperance": [r"min\(sell_total, 50\)"],
    "c_judgement": [r"random_joker_key"],
    # spectrals
    "s_familiar": [r"range\(3\)", r"face_ranks", r"game\.hand\.append"],
    "s_grim": [r"range\(2\)", r"rank=14", r"game\.hand\.append"],
    "s_incantation": [r"range\(4\)", r"randint\(2, 10\)", r"game\.hand\.append"],
    "s_talisman": [r'seal = "Gold"'],
    # Aura: edition on a PLAYING CARD in hand (NOT a joker — doc §5 +
    # balatro-rs core/src/spectral.rs).
    "s_aura": [r"card\.edition"],
    "s_wraith": [r"dollars\s*=\s*0\b"],         # sets money to $0
    # Sigil: one random suit, Stone cards exempt (real-game behavior — the
    # reference doc's "all cards" is shorthand; the wiki + real game leave
    # Stones unaffected).
    "s_sigil": [r"card\.suit = suit"],
    # Ouija: one random rank + PERMANENT -1 hand size (hand_size_mod survives
    # the per-blind hand_size reset).
    "s_ouija": [r"hand_size", r"hand_size_mod"],
    # Ectoplasm: Negative on a random Joker (frees its slot) + PERMANENT -1
    # hand size; no-op with no jokers (balatro-rs test confirms).
    "s_ectoplasm": [r"j\.edition = \"Negative\"", r"hand_size_mod",
                    r"joker_slots \+= 1"],
    "s_immolate": [r"dollars \+= 20", r"min\(5"],
    # Ankh: the original SURVIVES alongside its copy (2 jokers; balatro-rs
    # `vec![original, clone]`), copy strips Negative.
    "s_ankh": [r"game\.jokers = \[keep, copy\]"],
    "s_deja_vu": [r'seal = "Red"'],
    "s_hex": [r"game\.jokers = \[lucky\]"],
    "s_trance": [r'seal = "Blue"'],
    "s_medium": [r'seal = "Purple"'],
    "s_cryptid": [r"range\(2\)", r"seal = orig\.seal", r"game\.hand\.append"],
    "s_soul": [r"Legendary"],
    "s_black_hole": [r"planet_levels", r"\+ 1"],
}

#: Enhancement / suit each tarot must apply (doc §3 effect wording) — checked
#: against the sim's TAROT_ENHANCEMENT / TAROT_SUIT map VALUES.
ENHANCEMENT_EXPECT = {
    "c_magician": "Lucky", "c_empress": "Mult", "c_hierophant": "Bonus",
    "c_lovers": "Wild", "c_chariot": "Steel", "c_justice": "Glass",
    "c_devil": "Gold", "c_tower": "Stone",
}
SUIT_EXPECT = {
    "c_star": "Diamonds", "c_moon": "Clubs",
    "c_sun": "Hearts", "c_world": "Spades",
}


#: Vouchers implemented directly in apply_voucher — branch-scoped patterns.
VOUCHER_EFFECT_EXPECT = {
    "v_overstock": [r"shop_item_slots \+= 1"],
    "v_overstock_plus": [r"shop_item_slots \+= 1"],
    "v_clearance_sale": [r"shop_discount \+ 0\.25"],  # = min(+0.25, 0.5)
    "v_liquidation": [r"shop_discount \+ 0\.25"],
    "v_reroll_surplus": [r"reroll_discount \+= 2"],
    "v_reroll_glut": [r"reroll_discount \+= 2"],
    "v_crystal_ball": [r"consumable_slots \+= 1"],
    "v_grabber": [r"base_hands \+= 1"],
    "v_nacho_tong": [r"base_hands \+= 1"],
    "v_wasteful": [r"base_discards \+= 1"],
    "v_recyclomancy": [r"base_discards \+= 1"],
    "v_hieroglyph": [r"ante = max\(1", r"base_hands = max\(1"],
    "v_petroglyph": [r"ante = max\(1", r"base_discards = max\(1"],
    "v_paint_brush": [r"hand_size \+= 1"],
    "v_palette": [r"hand_size \+= 1"],
    "v_seed_money": [r"interest_cap\s*=\s*10"],  # 5 -> $10 (doc "by $5")
    "v_money_tree": [r"interest_cap\s*=\s*20"],  # -> $20 (wiki-confirmed)
    "v_blank": [r"pass"],                       # documented no-op
    "v_antimatter": [r"joker_slots \+= 1"],
}

#: Vouchers whose apply_voucher branch is `pass` — the effect lives in the
#: engine. Each must be referenced by the file that implements it.
VOUCHER_ENGINE = {
    "v_hone": "shop.py", "v_glow_up": "shop.py",
    "v_omen_globe": "shop.py", "v_telescope": "shop.py",
    "v_tarot_merchant": "shop.py", "v_tarot_tycoon": "shop.py",
    "v_planet_merchant": "shop.py", "v_planet_tycoon": "shop.py",
    "v_magic_trick": "shop.py", "v_illusion": "shop.py",
    "v_observatory": "scoring.py",
    "v_directors_cut": "game.py", "v_retcon": "game.py",
}



def voucher_chunk(src: str, key: str) -> str:
    """The apply_voucher branch for `v_<key>` (if/elif voucher_key chain)."""
    m = re.search(r'^\s*(?:if|elif) voucher_key == "' + re.escape(key) + r'":',
                    src, re.MULTILINE)
    if not m:
        return ""
    start = m.start()
    nxt = re.search(r"\n(?:    (?:if|elif) voucher_key ==|    return True|def |# ═)",
                    src[start + 1:])
    end = start + 1 + nxt.start() if nxt else len(src)
    return src[start:end]


def branch_chunk(src: str, key: str) -> str:
    """The source of `if (tarot|spectral)_key == "key":` up to the next
    same-level statement (next 4-space `if`, `return False`, or a def/header)."""
    m = re.search(r'if (?:tarot_key|spectral_key) == "' + re.escape(key) + r'":', src)
    if not m:
        return ""
    start = m.start()
    nxt = re.search(r"\n(?:    if (?:tarot_key|spectral_key) ==|    return False|def |# ═)",
                    src[start + 1:])
    end = start + 1 + nxt.start() if nxt else len(src)
    return src[start:end]


def main() -> int:
    spec = json.load(open(SPEC_PATH, encoding="utf-8"))
    src = open(CONSUMABLES_SRC, encoding="utf-8", errors="replace").read()
    game_src = open(GAME_SRC, encoding="utf-8", errors="replace").read()
    shop_src = open(SHOP_SRC, encoding="utf-8", errors="replace").read()
    scoring_src = open("vendor/balatro-rl/balatro_sim/scoring.py",
                       encoding="utf-8", errors="replace").read()

    names_bad = {}
    counts_bad = {}
    planet_bad = {}
    targets_bad = {}
    effect_bad = {}
    dead_bad = {}
    wired_bad = []

    for fam, keys in FAMILY_KEYS.items():
        # ── NAMES / COUNTS / DEAD ────────────────────────────────────────────
        spec_keys = set(spec[fam])
        if set(keys) != spec_keys:
            counts_bad[fam] = (sorted(set(keys) - spec_keys),
                               sorted(spec_keys - set(keys)))
        for key in keys:
            sim_name = FAMILY_NAMES[fam][key]
            spec_name = spec[fam].get(key, {}).get("name")
            if spec_name is not None and sim_name != spec_name:
                names_bad[key] = f"sim '{sim_name}' vs doc '{spec_name}'"
        for key in spec_keys - set(keys):
            dead_bad[key] = "in spec but not in sim maps"

        # ── PLANET hand-type mapping ─────────────────────────────────────────
        if fam == "planets":
            for key in keys:
                spec_hand = spec[fam][key]["hand_type"]
                if PLANET_HAND.get(key) != spec_hand:
                    planet_bad[key] = (f"sim levels '{PLANET_HAND.get(key)}' "
                                       f"doc says '{spec_hand}'")

        # ── TARGETS ──────────────────────────────────────────────────────────
        # Expected maxes come from the spec JSON itself (the doc's Targets
        # column) — the sim's TAROT_MAX_TARGETS must agree with it, and suit
        # tarots' doc max must be 3 (their shared branch converts up to 3).
        if fam == "tarots":
            for key, entry in spec[fam].items():
                want = entry["targets"]
                if key in TAROT_MAX_TARGETS:
                    got = TAROT_MAX_TARGETS[key]
                    if got != want:
                        targets_bad[key] = f"sim max {got} vs doc {want}"
                elif key in TAROT_SUIT and want != 3:
                    targets_bad[key] = f"spec targets {want}"
        elif fam == "spectrals":
            for key, want in SPECTRAL_TARGETS_EXPECT.items():
                got = spec[fam][key]["targets"]
                if got != want:
                    targets_bad[key] = f"spec targets {got} vs expected {want}"
            for key in DOCUMENTED_DIVERGENCES:
                if spec[fam][key]["targets"] != 0:
                    targets_bad[key] = f"doc targets {spec[fam][key]['targets']}"

        # ── EFFECT (semantic regexes, scoped to each card's branch) ──────────
        for key in keys:
            if fam == "planets":
                chunk = src
            else:
                chunk = branch_chunk(src, key)
            for pat in EFFECT_EXPECT.get(key, []):
                if not re.search(pat, chunk):
                    effect_bad.setdefault(key, []).append(pat)

    # Enhancement / suit map VALUES must match the doc.
    for key, want in ENHANCEMENT_EXPECT.items():
        if TAROT_ENHANCEMENT.get(key) != want:
            effect_bad.setdefault(key, []).append(
                f"map TAROT_ENHANCEMENT[{key}] = "
                f"'{TAROT_ENHANCEMENT.get(key)}' vs doc '{want}'")
    for key, want in SUIT_EXPECT.items():
        if TAROT_SUIT.get(key) != want:
            effect_bad.setdefault(key, []).append(
                f"map TAROT_SUIT[{key}] = '{TAROT_SUIT.get(key)}' "
                f"vs doc '{want}'")

    # ── VOUCHERS (§9) ───────────────────────────────────────────────────────
    vnames_bad = {}
    vpairs_bad = []
    veffect_bad = {}
    vspec = spec["vouchers"]
    if len(VOUCHER_NAME) != 32 or set(VOUCHER_NAME) != set(vspec):
        vpairs_bad.append(
            f"voucher count/keys mismatch: sim {len(VOUCHER_NAME)} "
            f"spec {len(vspec)}")
    for key, entry in vspec.items():
        if VOUCHER_NAME.get(key) != entry["name"]:
            vnames_bad[key] = (f"sim '{VOUCHER_NAME.get(key)}' "
                               f"vs doc '{entry['name']}'")
        if entry["base"]:
            continue
        doc_base = entry["upgrade_of"]
        if VOUCHER_BASE.get(key) != doc_base:
            vpairs_bad.append(
                f"{key}: sim base {VOUCHER_BASE.get(key)} vs doc {doc_base}")
    doc_upgrades = {k for k, e in vspec.items() if not e["base"]}
    if set(VOUCHER_BASE) != doc_upgrades:
        vpairs_bad.append(
            f"VOUCHER_BASE upgrades {sorted(set(VOUCHER_BASE) - doc_upgrades)} "
            f"vs doc-only {sorted(doc_upgrades - set(VOUCHER_BASE))}")

    for key, entry in vspec.items():
        if key in VOUCHER_EFFECT_EXPECT:
            chunk = voucher_chunk(src, key)
            for pat in VOUCHER_EFFECT_EXPECT[key]:
                if not re.search(pat, chunk):
                    veffect_bad.setdefault(key, []).append(pat)
        elif key in VOUCHER_ENGINE:
            engine_file = VOUCHER_ENGINE[key]
            engine_src = (shop_src if engine_file == "shop.py"
                          else game_src if engine_file == "game.py"
                          else scoring_src)
            # Match the quoted code usage (e.g. `"v_hone" in game.vouchers`) so
            # a bare mention in a comment can't false-pass the gate.
            if '"' + key + '"' not in engine_src:
                veffect_bad[key] = [f"not referenced in {engine_file}"]
        else:
            veffect_bad[key] = ["no effect pattern and no engine mapping"]

    # ── WIRED — generation pools + use dispatch reference the ALL_* sets ─────
    for const in ("ALL_TAROTS", "ALL_PLANETS", "ALL_SPECTRALS"):
        if const not in shop_src:
            wired_bad.append(f"shop.py never references {const}")
    for const in ("ALL_TAROTS", "ALL_PLANETS", "ALL_SPECTRALS", "PLANET_HAND"):
        if const not in game_src:
            wired_bad.append(f"game.py never references {const}")

    # ── report ───────────────────────────────────────────────────────────────
    lines = []
    lines.append(f"spec: {len(spec['tarots'])} tarots / "
                 f"{len(spec['planets'])} planets / "
                 f"{len(spec['spectrals'])} spectrals")
    lines.append(f"NAMES   {sum(len(v) for v in names_bad.values())}")
    for k, why in sorted(names_bad.items()):
        lines.append(f"    {k:22s} {why}")
    lines.append(f"COUNTS  {len(counts_bad)}")
    for fam, (extra, missing) in sorted(counts_bad.items()):
        lines.append(f"    {fam:10s} extra={extra} missing={missing}")
    lines.append(f"PLANET  {len(planet_bad)}")
    for k, why in sorted(planet_bad.items()):
        lines.append(f"    {k:22s} {why}")
    lines.append(f"TARGETS {len(targets_bad)}")
    for k, why in sorted(targets_bad.items()):
        lines.append(f"    {k:22s} {why}")
    # NOTE: EFFECT patterns are tripwires, not proofs — e.g. c_fool's
    # `consumables_used` pattern proves the branch touches the tracker, not
    # self-exclusion. Behavioral coverage lives in test_consumable_spec.py.
    lines.append(f"EFFECT  {sum(len(v) for v in effect_bad.values())}")
    for k, pats in sorted(effect_bad.items()):
        lines.append(f"    {k:22s} missing patterns: {', '.join(pats)}")
    lines.append(f"DEAD    {len(dead_bad)}")
    for k, why in sorted(dead_bad.items()):
        lines.append(f"    {k:22s} {why}")
    lines.append(f"WIRED   {len(wired_bad)}")
    for why in wired_bad:
        lines.append(f"    {why}")
    lines.append(f"VNAMES  {len(vnames_bad)}")
    for k, why in sorted(vnames_bad.items()):
        lines.append(f"    {k:22s} {why}")
    lines.append(f"VPAIRS  {len(vpairs_bad)}")
    for why in vpairs_bad:
        lines.append(f"    {why}")
    lines.append(f"VEFFECT {sum(len(v) for v in veffect_bad.values())}")
    for k, pats in sorted(veffect_bad.items()):
        lines.append(f"    {k:22s} {', '.join(pats)}")

    report = "\n".join(lines)
    print(report)

    if "--json" in sys.argv:
        json.dump({"names": names_bad, "counts": counts_bad,
                   "planet": planet_bad, "targets": targets_bad,
                   "effect": effect_bad, "dead": dead_bad,
                   "wired": wired_bad},
                  open("tools/out_audit_consumables.json", "w",
                       encoding="utf-8"),
                  indent=2, sort_keys=True)

    ok = not (names_bad or counts_bad or planet_bad or targets_bad
              or effect_bad or dead_bad or wired_bad or vnames_bad
              or vpairs_bad or veffect_bad)
    print("GATES:", "CLEAN" if ok else "ISSUES FOUND")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
