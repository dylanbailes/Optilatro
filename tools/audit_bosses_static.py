"""Static Boss-Blind layer audit — selection + effects + Matador table
fidelity gate.

Verifies the sim's boss tables and game.py boss-effect implementation against
tools/boss_spec.json, which is generated from balatro-mechanics-reference(2).md
§10 + §16 (the project's source of truth).

Gates, each of which must report 0:

  COUNT    — exactly 28 boss keys (23 regular + 5 finishers) in the sim's
             BOSS_MIN_ANTE, bidirectionally matching the doc spec.
  MIN_ANTE — BOSS_MIN_ANTE[key] must equal the doc §10 minimum-ante column
             (wrong min-ante = a boss appears on the wrong ante, or a
             no-repeat rotation leaks an ante-8 boss early).
  SHOWDOWN — SHOWDOWN_BOSSES must equal the doc's 5 Ante-8 finisher blinds.
  SCALING  — §16 large-blind multipliers: The Wall 4x / Violet Vessel 6x /
             The Needle 1x (and Needle must not carry a multiplier).
  SELECT   — _select_boss must implement the doc's algorithm: ante%8==0 draws
             exclusively from the Showdown pool; regular pools filter by
             min-ante; the fewest-appearances no-repeat rotation; the pick
             drawn from the run's seeded RNG; an exclude hook for rerolls.
  MATADOR  — the doc's 13 Matador-compatible bosses must be exactly the keys
             the game's matador-decision code can pay out on (positive), and
             none of the other 15 (negative). Psychic is checked separately
             (it pays on the <5-card rejection branch).
  EFFECT   — per-boss semantic regexes scoped to the implementing function
             (_apply_boss_start / _on_card_drawn / _draw_cards / _play_hand /
             _discard / _prepare_next_blind / _undo_boss_debuffs). Wording-
             encoded so a wrong-effect regression fails CI.
  WIRED    — selection dispatches through BOSS_MIN_ANTE / SHOWDOWN_BOSSES /
             UNIMPLEMENTED_BOSSES (currently empty), and effects dispatch
             through current_blind.boss_key.

Known, documented divergences (deliberate sim choices, not bugs — covered by
behavioral tests):
  - The Fish: the doc says "cards drawn face down after each played/discarded
    hand"; the real game (wiki) deals draws-after-PLAY face down and
    discard-draws face up. The sim follows the real game (hand size is
    unchanged — the old "draw 1 fewer card" model was a bug, fixed 2026-08-07).
  - The Serpent: doc + wiki agree — draw 3 after every play AND discard,
    ignoring hand size (overfills). Implemented 2026-08-07 (was "discard hand
    and redraw to full", a bug).

Usage:  python tools/audit_bosses_static.py [--json]
Exit:   0 when all gates are clean, 1 otherwise.
"""
import json
import re
import sys

sys.path.insert(0, "vendor/balatro-rl")
from balatro_sim.game import BOSS_MIN_ANTE, SHOWDOWN_BOSSES

SPEC = "tools/boss_spec.json"
GAME = "vendor/balatro-rl/balatro_sim/game.py"

COMMENT = re.compile(r"#.*$", re.M)


def def_chunk(src: str, def_name: str) -> str:
    """The body of `def <def_name>(` — sliced to the next top-level def."""
    m = re.search(r"^    def " + re.escape(def_name) + r"\(", src, re.M)
    if not m:
        return ""
    start = m.start()
    nxt = re.search(r"\n    def |\nclass ", src[start + 1:])
    end = start + 1 + nxt.start() if nxt else len(src)
    return src[start:end]


def strip_comments(s: str) -> str:
    return COMMENT.sub("", s)


def main() -> int:
    spec = json.load(open(SPEC, encoding="utf-8"))
    bosses, matador = spec["bosses"], spec["matador"]
    showdown_doc, scaling = spec["showdown"], spec["scaling"]
    src = open(GAME, encoding="utf-8").read()

    count_bad, minante_bad, showdown_bad = [], [], []
    scaling_bad, select_bad, matador_bad = [], [], []
    effect_bad, wired_bad = {}, []

    # ── COUNT — 28 keys, bidirectional ──────────────────────────────────────
    sim_keys = set(BOSS_MIN_ANTE)
    doc_keys = set(bosses)
    if len(sim_keys) != 28:
        count_bad.append(f"sim has {len(sim_keys)} boss keys, expected 28")
    if sim_keys != doc_keys:
        count_bad.append(
            f"sim-only keys {sorted(sim_keys - doc_keys)}; "
            f"doc-only keys {sorted(doc_keys - sim_keys)}")

    # ── MIN_ANTE — per-key eligibility ──────────────────────────────────────
    for key in sorted(doc_keys):
        doc_ante = bosses[key]["min_ante"]
        sim_ante = BOSS_MIN_ANTE.get(key)
        if sim_ante != doc_ante:
            minante_bad.append(f"{key}: sim {sim_ante} vs doc {doc_ante}")

    # ── SHOWDOWN — the 5 Ante-8 finishers ───────────────────────────────────
    if set(SHOWDOWN_BOSSES) != set(showdown_doc):
        showdown_bad.append(
            f"SHOWDOWN_BOSSES {sorted(SHOWDOWN_BOSSES)} vs doc "
            f"{sorted(showdown_doc)}")

    # ── SCALING — §16 large-blind multipliers ───────────────────────────────
    prep = def_chunk(src, "_prepare_next_blind")
    for key, mult in scaling.items():
        if key == "bl_needle":
            # 1x base: the needle branch must set chips WITHOUT a multiplier.
            m = re.search(r'if boss_key == "bl_needle":(.*?)(?=\n            elif|\n            if)', prep, re.S)
            branch = m.group(1) if m else ""
            if "BLIND_CHIPS[self.ante][0]" not in branch or "* 4" in branch or "* 6" in branch:
                scaling_bad.append(
                    f"{key}: needle branch not 1x base "
                    f"(mult={int(mult)} expected; branch={branch.strip()!r})")
        else:
            if f"* {mult}" not in prep or f'"{key}"' not in prep:
                scaling_bad.append(
                    f"{key}: doc §16 says {mult}x base — missing "
                    f"`* {mult}` in _prepare_next_blind")

    # ── SELECT — selection algorithm ────────────────────────────────────────
    sel = def_chunk(src, "_select_boss")
    select_checks = {
        "showdown pool on ante%8": r"ante % 8 == 0",
        "showdown pool constant": r"SHOWDOWN_BOSSES",
        "min-ante eligibility": r"min_ante <= ante",
        "fewest-appearances rotation": r"== min_count",
        "seeded RNG pick": r'node\(node_boss\(\)\)',
        "exclude hook (rerolls)": r"exclude",
    }
    for label, pat in select_checks.items():
        if not re.search(pat, sel):
            select_bad.append(f"_select_boss missing: {label}")

    # ── MATADOR — exact 13-boss trigger table ───────────────────────────────
    # Strip comments on the WHOLE chunk first: the anchor text could otherwise
    # be found inside a comment (the 15 non-matador keys are listed in the
    # matador block's comment — that must not leak into the decision region).
    play = strip_comments(def_chunk(src, "_play_hand"))
    m = re.search(r"matador = False(.*?)if matador:", play, re.S)
    decision = m.group(1) if m else ""
    paid = sorted(set(re.findall(r"bl_[a-z_]+", decision)))
    non_matador = sorted(set(BOSS_MIN_ANTE) - set(matador))
    # Psychic pays on the <5-card rejection branch (checked separately below),
    # so it is not expected inside the matador decision block itself.
    for key in matador:
        if key == "bl_psychic":
            continue
        if key not in paid:
            matador_bad.append(f"{key}: missing from the matador decision block")
    for key in non_matador:
        if key in paid:
            matador_bad.append(f"{key}: wrongly in the matador decision block")
    # Psychic pays on the <5-card rejection branch (separate call site).
    if not re.search(r'bl_psychic.{0,120}?_fire_boss_trigger', play, re.S):
        matador_bad.append("bl_psychic: no _fire_boss_trigger on the <5-card branch")
    # The doc list itself must have 13 entries.
    if len(matador) != 13:
        matador_bad.append(f"doc matador list has {len(matador)} entries, expected 13")

    # ── EFFECT — per-boss semantics, scoped to the implementing function ────
    # (chunk, [patterns]) — each pattern must match inside the chunk.
    abs = def_chunk(src, "_apply_boss_start")
    ond = def_chunk(src, "_on_card_drawn")
    drw = def_chunk(src, "_draw_cards") + def_chunk(src, "_draw_to_full")
    und = def_chunk(src, "_undo_boss_debuffs")
    disc = def_chunk(src, "_discard")
    BOSS_EFFECT = {
        "bl_manacle":  (abs, [r"hand_size = max\(1, self\.hand_size - 1\)"]),
        "bl_needle":   (abs, [r"hands_left = 1"]),
        "bl_water":    (abs, [r"discards_left = 0"]),
        "bl_goad":     (abs, [r'c\.suit == "Spades"']),
        "bl_club":     (abs, [r'c\.suit == "Clubs"']),
        "bl_window":   (abs, [r'c\.suit == "Diamonds"']),
        "bl_head":     (abs, [r'c\.suit == "Hearts"']),
        "bl_plant":    (abs, [r"c\.is_face_card", r"c\.debuffed = True"]),
        "bl_verdant":  (abs, [r"verdant_debuff = True"]),
        "bl_pillar":   (abs, [r"ante_played_ids"]),
        "bl_cerulean": (abs, [r"_pick_bell_card"]),
        "bl_amber":    (abs, [r"AMBER_NODE", r"jokers_flipped = True"]),
        "bl_house":    (abs, [r"c\.flipped = True"]),
        "bl_mark":     (ond, [r"is_face_card", r"flipped = True"]),
        "bl_wheel":    (ond, [r"1 / 7", r"WHEEL_NODE"]),
        "bl_fish":     (drw, [r"flip_for_fish", r"flipped = True"]),
        "bl_hook":     (play, [r"HOOK_NODE", r"unplayed"]),
        "bl_psychic":  (play, [r"len\(selected\) != 5"]),
        "bl_ox":       (play, [r"_most_played_hand", r"self\.dollars = 0"]),
        "bl_eye":      (play, [r'boss == "bl_eye"', r"played_hand_types_this_round"]),
        "bl_mouth":    (play, [r'boss == "bl_mouth"', r"played_hand_types_this_round"]),
        "bl_crimson":  (play, [r"CRIMSON_NODE"]),
        "bl_flint":    (play, [r'half_base=\(boss == "bl_flint"\)']),
        "bl_grim":     (play, [r"planet_levels\[hand_type\] = max\(", r"- 1"]),
        "bl_tooth":    (play, [r"self\.dollars = max\(0, self\.dollars - len\(selected\)\)"]),
        "bl_serpent":  (play + disc, [r"_draw_cards\(3\)"]),
    }
    for key, (chunk, pats) in BOSS_EFFECT.items():
        if key not in bosses:
            continue  # COUNT gate reports the key mismatch
        missing = [p for p in pats if not re.search(p, chunk)]
        if missing:
            effect_bad[key] = missing
    # The Hook must discard UNPLAYED cards (doc §10 / balatro-rs: "Discards 2
    # random unplayed cards after every played hand"). The old model removed
    # cards from the PLAYED selection before scoring (a pair could be wiped).
    if re.search(r"shuffle = list\(selected\)", play) or \
            re.search(r"selected\.remove\(c\)", play):
        effect_bad["bl_hook"] = effect_bad.get("bl_hook", []) + \
            ["old hook model present (removes PLAYED cards before scoring)"]
    # The Serpent must fire on plays AND discards (draw-3 in both functions).
    if src.count("_draw_cards(3)") < 2:
        effect_bad["bl_fish"] = effect_bad.get("bl_fish", []) + \
            ["old hand-shrink model present (hand_size - played)"]
    # The Serpent must fire on plays AND discards (draw-3 in both functions).
    if src.count("_draw_cards(3)") < 2:
        effect_bad["bl_serpent"] = effect_bad.get("bl_serpent", []) + \
            ["_draw_cards(3) appears once — must fire on play AND discard"]
    # Fish's face-down draws must be cleared at blind end (flip-clear tuple).
    if "bl_fish" not in und:
        effect_bad["bl_fish"] = effect_bad.get("bl_fish", []) + \
            ["bl_fish missing from _undo_boss_debuffs flip-clear"]

    # ── WIRED — dispatch paths ──────────────────────────────────────────────
    if "BOSS_MIN_ANTE" not in sel:
        wired_bad.append("_select_boss does not reference BOSS_MIN_ANTE")
    if "SHOWDOWN_BOSSES" not in sel:
        wired_bad.append("_select_boss does not reference SHOWDOWN_BOSSES")
    if not re.search(r"UNIMPLEMENTED_BOSSES: set\[str\] = set\(\)", src):
        wired_bad.append("UNIMPLEMENTED_BOSSES is not the empty allow-list")
    if src.count("current_blind.boss_key") < 3:
        wired_bad.append("effects do not dispatch through current_blind.boss_key")

    # ── Report ──────────────────────────────────────────────────────────────
    lines = ["boss spec: 28 bosses (23 regular + 5 finishers), "
             f"{len(matador)} Matador, scaling {scaling}"]
    lines.append(f"COUNT    {len(count_bad)}")
    for why in count_bad:
        lines.append(f"    {why}")
    lines.append(f"MIN_ANTE {len(minante_bad)}")
    for why in minante_bad:
        lines.append(f"    {why}")
    lines.append(f"SHOWDOWN {len(showdown_bad)}")
    for why in showdown_bad:
        lines.append(f"    {why}")
    lines.append(f"SCALING  {len(scaling_bad)}")
    for why in scaling_bad:
        lines.append(f"    {why}")
    lines.append(f"SELECT   {len(select_bad)}")
    for why in select_bad:
        lines.append(f"    {why}")
    lines.append(f"MATADOR  {len(matador_bad)}")
    for why in matador_bad:
        lines.append(f"    {why}")
    lines.append(f"EFFECT   {sum(len(v) for v in effect_bad.values())}")
    for k, pats in sorted(effect_bad.items()):
        lines.append(f"    {k:22s} missing patterns: {', '.join(pats)}")
    lines.append(f"WIRED    {len(wired_bad)}")
    for why in wired_bad:
        lines.append(f"    {why}")
    print("\n".join(lines))

    if "--json" in sys.argv:
        json.dump({"count": count_bad, "min_ante": minante_bad,
                   "showdown": showdown_bad, "scaling": scaling_bad,
                   "select": select_bad, "matador": matador_bad,
                   "effect": effect_bad, "wired": wired_bad},
                  open("tools/out_audit_bosses.json", "w", encoding="utf-8"),
                  indent=2, sort_keys=True)

    ok = not (count_bad or minante_bad or showdown_bad or scaling_bad
              or select_bad or matador_bad or effect_bad or wired_bad)
    print("GATES:", "CLEAN" if ok else "ISSUES FOUND")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
