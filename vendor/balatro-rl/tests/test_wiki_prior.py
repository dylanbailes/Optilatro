"""test_wiki_prior.py — the wiki synergy-prior scraper's parsing helpers.

The scraper (tools/gen_wiki_prior.py) hits the live wiki in `build()`; these
tests cover the pure, offline pieces: section slicing (stop at
Anti-Synergies), accent-folded name normalization, template extraction, and
name→key resolution across the joker/tarot/planet/spectral/voucher families.
"""
from __future__ import annotations

import importlib.util
import pathlib

from balatro_sim.game import BalatroGame

_ROOT = pathlib.Path(__file__).resolve().parents[3]
_spec = importlib.util.spec_from_file_location(
    "gen_wiki_prior", _ROOT / "tools" / "gen_wiki_prior.py")
_gen = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_gen)

_FIXTURE = """
==Synergies==
===[[Jokers]]===
*Held in hand Jokers synergize best with Mime: {{J|Reserved Parking}},
 {{J|Raised Fist}}, {{J|Baron}}, {{j|Hanging Chad}} and {{J|Blueprint}}.
===[[Vouchers]]===
*{{V|Paint Brush}} and {{V|Palette}} each increase hand size.
===[[Consumables]]===
*{{Tarot|The Emperor}} creates more {{Tarot|}} cards; {{Planet|Mercury}} and
 {{Spectral|Cryptid}} round out the build.
==Anti-Synergies==
===[[Jokers]]===
*{{J|Stuntman}} reduces hand size.
==Trivia==
"""


def test_normalize_folds_accents():
    assert _gen._normalize("Séance") == _gen._normalize("Seance") == "seance"
    assert _gen._normalize("Oops! All 6s") == "oopsall6s"
    assert _gen._normalize("Mr. Bones") == "mrbones"
    assert _gen._normalize("8 Ball") == "8ball"


def test_synergy_section_stops_at_anti_synergies():
    sec = _gen._synergy_section(_FIXTURE)
    assert "Reserved Parking" in sec and "Stuntman" not in sec
    assert "Trivia" not in sec
    # no Synergies header -> empty
    assert _gen._synergy_section("==Trivia==\nfoo") == ""


def test_template_extraction():
    sec = _gen._synergy_section(_FIXTURE)
    found = {fam: {m.strip() for m in rx.findall(sec)}
             for fam, rx in _gen._TEMPLATE_RE.items()}
    assert "Baron" in found["joker"]
    assert "Hanging Chad" in found["joker"]       # lowercase {{j|...}}
    assert found["voucher"] == {"Paint Brush", "Palette"}
    assert "The Emperor" in found["tarot"]
    assert "Mercury" in found["planet"]
    assert "Cryptid" in found["spectral"]
    # generic empty-name {{Tarot|}} is NOT captured (requires a non-empty name)
    assert all(n for n in found["tarot"])


def test_name_resolution_across_families():
    maps = _gen._name_maps(_ROOT / "tools")
    assert _gen._resolve(maps, "joker", "Baron")[0] == "j_baron"
    assert _gen._resolve(maps, "joker", "Séance")[0] == "j_seance"  # accent
    assert _gen._resolve(maps, "voucher", "Paint Brush")[0] == "v_paint_brush"
    assert _gen._resolve(maps, "tarot", "The Emperor")[0] == "c_emperor"
    assert _gen._resolve(maps, "planet", "Mercury")[0] == "pl_mercury"
    assert _gen._resolve(maps, "spectral", "Cryptid")[0] == "s_cryptid"
    # cross-entity wiki quirk: a voucher linked with the {{J|...}} template
    assert _gen._resolve(maps, "joker", "Nacho Tong")[0] is None
    assert _gen._resolve_any(maps, "Nacho Tong") == ("voucher", "v_nacho_tong")
    # a deck is not any of the five families
    assert _gen._resolve_any(maps, "Plasma Deck") == (None, None)


def test_hand_and_card_resolution():
    # poker hands (plurals + Royal Flush folded into Straight Flush)
    assert _gen._resolve_hand("High Card") == "High Card"
    assert _gen._resolve_hand("Pairs") == "Pair"
    assert _gen._resolve_hand("Straights") == "Straight"
    assert _gen._resolve_hand("Straight Flushes") == "Straight Flush"
    assert _gen._resolve_hand("Royal Flush") == "Straight Flush"
    assert _gen._resolve_hand("Five of a Kinds") == "Five of a Kind"
    assert _gen._resolve_hand("X of a Kind") is None       # generic, dropped
    # card modifiers
    assert _gen._resolve_enhancement("Glass") == "Glass"
    assert _gen._resolve_enhancement("Steel") == "Steel"
    assert _gen._resolve_seal("Blue") == "Blue"
    assert _gen._resolve_seal("Red Seals") == "Red"
    assert _gen._resolve_edition("Polychrome") == "Polychrome"


def test_prior_file_families_and_covers_all_jokers():
    """The generated prior must contain the five families and a joker_joker
    entry for (almost) every canonical joker."""
    import json
    prior = json.loads((_ROOT / "tools" / "wiki_synergy_prior.json")
                       .read_text(encoding="utf-8"))
    assert set(prior) == {"meta", "joker_joker", "joker_consumable",
                          "joker_voucher", "joker_hand", "joker_card"}
    joker_spec = json.loads((_ROOT / "tools" / "joker_spec.json")
                            .read_text(encoding="utf-8"))
    missing = [k for k in joker_spec if k not in prior["joker_joker"]]
    assert len(missing) <= 2   # a couple pages legitimately list no jokers
    # the user's cited example: Mime synergizes with Baron/Reserved Parking/
    # Raised Fist, the Paint Brush/Palette vouchers, small poker hands, and
    # Gold/Steel/Blue-Seal cards.
    mime_jj = prior["joker_joker"].get("j_mime", {})
    for k in ("j_baron", "j_reserved_parking", "j_raised_fist"):
        assert k in mime_jj
    mime_jv = prior["joker_voucher"].get("j_mime", {})
    assert "v_paint_brush" in mime_jv and "v_palette" in mime_jv
    mime_hands = prior["joker_hand"].get("j_mime", {})
    assert "High Card" in mime_hands and "Pair" in mime_hands
    mime_cards = prior["joker_card"].get("j_mime", {})
    assert "enh_Steel" in mime_cards and "enh_Gold" in mime_cards \
        and "seal_Blue" in mime_cards


def test_prior_does_not_perturb_rng():
    """Loading + scoring the wiki prior is a pure read (no seed draws)."""
    import balatro_sim.synergy_tree as ST
    ST.clear_prior_cache()
    g = BalatroGame(seed=11, rng_mode="seed")
    g.rng.enable_tracing()
    ST.load_wiki_prior()
    assert g.rng.records == []
