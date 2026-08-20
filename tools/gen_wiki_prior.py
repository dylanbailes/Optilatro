"""tools/gen_wiki_prior.py — scrape the Balatro wiki's per-joker "Synergies"
sections into a PRIOR matrix for the synergy tree.

Every joker page on balatrowiki.org has a ``==Synergies==`` section listing
(under ``===Jokers===`` / ``===Vouchers===`` / etc.) the other Jokers,
Vouchers, Tarots, Planets and Spectrals it combines well with, using the
wiki's link templates: ``{{J|Baron}}``, ``{{V|Paint Brush}}``,
``{{Tarot|The Emperor}}``, ``{{Planet|Mercury}}``, ``{{Spectral|Cryptid}}``.

This script fetches the wikitext for all 150 canonical jokers (via the
MediaWiki API, batched), parses the Synergies section (STOPPING at
``==Anti-Synergies==`` so anti-synergies are excluded), maps each mention's
display name back to the sim's key (from tools/joker_spec.json +
tools/consumable_spec.json), and writes a prior matrix:

  {
    "meta": {... "prior_strength": 3.0 ...},
    "joker_joker":      {joker: {synergizing_joker: 1.0}},
    "joker_consumable": {joker: {tarot/planet/spectral: 1.0}},
    "joker_voucher":    {joker: {voucher: 1.0}},
    "joker_hand":       {joker: {poker_hand: 1.0}},
    "joker_card":       {joker: {enh_*/seal_*/edition_* feature: 1.0}},
  }

The uniform 1.0 edge weights are the wiki prior's strength (a wiki-listed
synergy). synergy_tree.py blends this prior with the MINED tree via a
pseudo-count, so gameplay data upgrades the prior as support accumulates.

Usage:
  python tools/gen_wiki_prior.py [--out tools/wiki_synergy_prior.json]
      [--prior-strength 3.0] [--limit N] [--spec-dir tools]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
from pathlib import Path

API_URL = "https://balatrowiki.org/api.php"
USER_AGENT = "balatro-sim-synergy-miner/0.1 (research; deterministic sim prior)"
_BATCH = 50          # MediaWiki anon batch limit
_DELAY_S = 0.5       # politeness between API requests


# ── name → key maps (from the spec files) ───────────────────────────────────

def _normalize(name: str) -> str:
    """Lowercase + alphanumerics only — a robust join key for wiki display
    names (drops '!', '.', apostrophes, spaces, hyphens, and folds accents so
    the wiki's "Séance" matches the spec's "Seance")."""
    folded = unicodedata.normalize("NFKD", name)
    folded = folded.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]", "", folded.lower())


def _name_maps(spec_dir: Path) -> dict[str, dict[str, str]]:
    """Per-family {exact_name: key} and {normalized_name: key} maps."""
    joker_spec = json.loads((spec_dir / "joker_spec.json").read_text(encoding="utf-8"))
    cons_spec = json.loads((spec_dir / "consumable_spec.json").read_text(encoding="utf-8"))

    families = {
        "joker": {v["name"]: k for k, v in joker_spec.items()},
        "tarot": {v["name"]: k for k, v in cons_spec["tarots"].items()},
        "planet": {v["name"]: k for k, v in cons_spec["planets"].items()},
        "spectral": {v["name"]: k for k, v in cons_spec["spectrals"].items()},
        "voucher": {v["name"]: k for k, v in cons_spec["vouchers"].items()},
    }
    out = {}
    for fam, exact in families.items():
        norm = {_normalize(n): k for n, k in exact.items()}
        out[fam] = {"exact": exact, "norm": norm}
    return out


def _resolve(maps: dict, family: str, name: str):
    """(key, matched_name) or (None, None) — exact first, then normalized."""
    m = maps[family]
    if name in m["exact"]:
        return m["exact"][name], name
    n = _normalize(name)
    if n in m["norm"]:
        return m["norm"][n], name
    return None, None


def _resolve_any(maps: dict, name: str):
    """(family, key) across every family — the wiki sometimes links a Voucher
    with the {{J|...}} template (e.g. "{{J|Nacho Tong}}"), so a name that
    misses in its declared family falls back to the others."""
    for fam in ("joker", "voucher", "tarot", "planet", "spectral"):
        key, _ = _resolve(maps, fam, name)
        if key is not None:
            return fam, key
    return None, None


# Canonical poker-hand + playing-card vocabularies (match the sim's hand
# types, enhancement names, and card seal/edition values).
HAND_NAMES = ["High Card", "Pair", "Two Pair", "Three of a Kind", "Straight",
              "Flush", "Full House", "Four of a Kind", "Straight Flush",
              "Five of a Kind", "Flush House", "Flush Five"]
ENHANCEMENT_NAMES = ["Bonus", "Mult", "Glass", "Steel", "Stone", "Gold",
                     "Lucky", "Wild"]
SEAL_NAMES = ["Red", "Blue", "Gold", "Purple"]
EDITION_NAMES = ["Foil", "Holographic", "Polychrome"]


def _resolve_hand(name: str):
    """Resolve a wiki poker-hand mention, tolerating plurals ("Pairs" →
    "Pair") and the wiki's "Royal Flush" (Balatro folds it into "Straight
    Flush")."""
    n = _normalize(name)
    variants = {n}
    for suf in ("es", "s"):
        if n.endswith(suf):
            variants.add(n[:-len(suf)])
    if "royalflush" in variants:
        return "Straight Flush"
    for h in HAND_NAMES:
        if _normalize(h) in variants:
            return h
    return None


def _resolve_enhancement(name: str):
    n = _normalize(name)
    for e in ENHANCEMENT_NAMES:
        if _normalize(e) == n:
            return e
    return None


def _resolve_seal(name: str):
    """The wiki param is the colour ({{Seal|Blue}}) or the full name
    ("Red Seals") — normalize both to the sim's seal value."""
    n = _normalize(name)
    for suf in ("seals", "seal"):
        if n.endswith(suf):
            n = n[:-len(suf)]
            break
    for s in SEAL_NAMES:
        if _normalize(s) == n:
            return s
    return None


def _resolve_edition(name: str):
    n = _normalize(name)
    for e in EDITION_NAMES:
        if _normalize(e) == n:
            return e
    return None


# ── wiki fetch ──────────────────────────────────────────────────────────────

def _fetch_wikitext(titles: list[str]) -> dict[str, str]:
    """Batch-fetch raw wikitext for `titles` (title -> wikitext)."""
    out: dict[str, str] = {}
    for i in range(0, len(titles), _BATCH):
        chunk = titles[i:i + _BATCH]
        params = urllib.parse.urlencode({
            "action": "query",
            "titles": "|".join(chunk),
            "prop": "revisions",
            "rvprop": "content",
            "rvslots": "main",
            "format": "json",
            "redirects": "1",
        })
        url = f"{API_URL}?{params}"
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        # map normalized title -> canonical title
        norm2title = {_normalize(t): t for t in chunk}
        for _, page in (data.get("query", {}).get("pages", {}) or {}).items():
            title = page.get("title", "")
            key = _normalize(title)
            if key in norm2title:
                title = norm2title[key]      # keep our requested casing
            rev = (page.get("revisions") or [{}])[0]
            content = rev.get("slots", {}).get("main", {}).get("*", "")
            out[title] = content
        time.sleep(_DELAY_S)
    return out


# ── section extraction ──────────────────────────────────────────────────────

_SYNERGY_RE = re.compile(r"==\s*Synergies\s*==\s*(.*)", re.DOTALL)
_LEVEL2_RE = re.compile(r"\n==[^=]")

# Link templates inside the Synergies section. `[^|}]+` stops at an extra
# param (|) or the closing braces, and requires a non-empty name so generic
# {{Tarot|}} / {{Planet|}} / {{Spectral|}} placeholders are skipped.
_TEMPLATE_RE = {
    "joker": re.compile(r"\{\{\s*[Jj]\s*\|\s*([^|}]+)"),
    "voucher": re.compile(r"\{\{\s*[Vv]\s*\|\s*([^|}]+)"),
    "tarot": re.compile(r"\{\{\s*[Tt]arot\s*\|\s*([^|}]+)"),
    "planet": re.compile(r"\{\{\s*[Pp]lanet\s*\|\s*([^|}]+)"),
    "spectral": re.compile(r"\{\{\s*[Ss]pectral\s*\|\s*([^|}]+)"),
}

# Poker-hand + playing-card templates (the "Poker Hands" and "Playing cards"
# subsections): {{Ph|High Card}}/{{ph|...}}, {{enhancement|Gold}}/
# {{Enhancement|...}}, {{Seal|Blue}}/{{seal|...}}, {{Edition|...}}. Captured
# from the WHOLE Synergies section — they also appear inline in the Jokers
# subsection when explaining a card-feature synergy.
_CARD_TEMPLATE_RE = {
    "hand": re.compile(r"\{\{\s*[Pp]h\s*\|\s*([^|}]+)"),
    "enhancement": re.compile(r"\{\{\s*[Ee]nhancement\s*\|\s*([^|}]+)"),
    "seal": re.compile(r"\{\{\s*[Ss]eal\s*\|\s*([^|}]+)"),
    "edition": re.compile(r"\{\{\s*[Ee]dition\s*\|\s*([^|}]+)"),
}


def _synergy_section(wikitext: str) -> str:
    """The `==Synergies==` section, cut at the next level-2 header
    (Anti-Synergies / Trivia / ...). Empty string when absent."""
    m = _SYNERGY_RE.search(wikitext)
    if not m:
        return ""
    section = m.group(1)
    cut = _LEVEL2_RE.search(section)
    if cut:
        section = section[:cut.start()]
    return section


# ── build ───────────────────────────────────────────────────────────────────

def build(spec_dir: Path, prior_strength: float, limit: int | None = None) -> dict:
    """Fetch every joker page and build the prior matrix."""
    maps = _name_maps(spec_dir)
    joker_spec = json.loads((spec_dir / "joker_spec.json").read_text(encoding="utf-8"))
    jokers = sorted(joker_spec.items(), key=lambda kv: kv[0])   # key -> spec
    if limit:
        jokers = jokers[:limit]

    names = [spec["name"] for _, spec in jokers]
    print(f"fetching {len(names)} joker pages from {API_URL} ...", flush=True)
    wikitext = _fetch_wikitext(names)

    jj: dict[str, dict[str, float]] = {}
    jc: dict[str, dict[str, float]] = {}
    jv: dict[str, dict[str, float]] = {}
    jh: dict[str, dict[str, float]] = {}
    jcard: dict[str, dict[str, float]] = {}
    unmatched: dict[str, list[str]] = {}
    n_with_synergies = 0
    n_missing = 0

    for key, spec in jokers:
        name = spec["name"]
        wt = wikitext.get(name, "")
        if not wt:
            n_missing += 1
            print(f"  ! no wikitext for {name}", flush=True)
            continue
        section = _synergy_section(wt)
        if not section:
            continue
        mentions = []   # (declared_family, raw_name)
        for fam, rx in _TEMPLATE_RE.items():
            for raw in rx.findall(section):
                mentions.append((fam, raw.strip()))
        seen = set()    # (resolved_family, key) dedupe within the page
        for declared, raw in mentions:
            tkey, _ = _resolve(maps, declared, raw)
            fam = declared
            if tkey is None:
                # cross-entity wiki quirk: {{J|Nacho Tong}} / {{j|Plasma Deck}}
                fam, tkey = _resolve_any(maps, raw)
            if tkey is None:
                unmatched.setdefault(name, []).append(f"{declared}:{raw}")
                continue
            if fam == "joker" and tkey == key:
                continue   # a page never lists itself as a synergy
            if (fam, tkey) in seen:
                continue
            seen.add((fam, tkey))
            if fam in ("tarot", "planet", "spectral"):
                jc.setdefault(key, {})[tkey] = 1.0
            elif fam == "joker":
                jj.setdefault(key, {})[tkey] = 1.0
            elif fam == "voucher":
                jv.setdefault(key, {})[tkey] = 1.0

        # ── Poker hands + playing-card modifiers (enhancement/seal/edition) ──
        hands: set[str] = set()
        feats: set[str] = set()
        for raw in _CARD_TEMPLATE_RE["hand"].findall(section):
            h = _resolve_hand(raw.strip())
            (hands.add(h) if h
             else unmatched.setdefault(name, []).append(f"hand:{raw.strip()}"))
        for raw in _CARD_TEMPLATE_RE["enhancement"].findall(section):
            e = _resolve_enhancement(raw.strip())
            (feats.add(f"enh_{e}") if e
             else unmatched.setdefault(name, []).append(f"enhancement:{raw.strip()}"))
        for raw in _CARD_TEMPLATE_RE["seal"].findall(section):
            s = _resolve_seal(raw.strip())
            (feats.add(f"seal_{s}") if s
             else unmatched.setdefault(name, []).append(f"seal:{raw.strip()}"))
        for raw in _CARD_TEMPLATE_RE["edition"].findall(section):
            e = _resolve_edition(raw.strip())
            if e:
                feats.add(f"edition_{e}")
            elif _normalize(raw.strip()) == "negative":
                pass   # Negative is a JOKER edition, not a playing-card feature
            else:
                unmatched.setdefault(name, []).append(f"edition:{raw.strip()}")
        if hands:
            jh[key] = {h: 1.0 for h in sorted(hands)}
        if feats:
            jcard[key] = {f: 1.0 for f in sorted(feats)}

        if seen or hands or feats:
            n_with_synergies += 1

    return {
        "meta": {
            "source": "https://balatrowiki.org per-joker Synergies sections",
            "scraped": time.strftime("%Y-%m-%d"),
            "prior_strength": prior_strength,
            "n_jokers_scraped": len(jokers),
            "n_jokers_with_synergies": n_with_synergies,
            "n_missing_pages": n_missing,
            "unmatched": {k: v for k, v in sorted(unmatched.items())},
        },
        "joker_joker": jj,
        "joker_consumable": jc,
        "joker_voucher": jv,
        "joker_hand": jh,
        "joker_card": jcard,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(Path(__file__).resolve().parent / "wiki_synergy_prior.json"))
    ap.add_argument("--spec-dir", default=str(Path(__file__).resolve().parent))
    ap.add_argument("--prior-strength", type=float, default=3.0)
    ap.add_argument("--limit", type=int, default=None,
                    help="scrape only the first N jokers (development)")
    args = ap.parse_args()

    prior = build(Path(args.spec_dir), args.prior_strength, args.limit)
    out = Path(args.out)
    out.write_text(json.dumps(prior, indent=1, sort_keys=True), encoding="utf-8")

    meta = prior["meta"]
    n_jj = sum(len(v) for v in prior["joker_joker"].values())
    n_jc = sum(len(v) for v in prior["joker_consumable"].values())
    n_jv = sum(len(v) for v in prior["joker_voucher"].values())
    n_jh = sum(len(v) for v in prior["joker_hand"].values())
    n_jcard = sum(len(v) for v in prior["joker_card"].values())
    print(f"wrote {out}:")
    print(f"  scraped {meta['n_jokers_scraped']} jokers "
          f"({meta['n_jokers_with_synergies']} with a Synergies section, "
          f"{meta['n_missing_pages']} missing)")
    print(f"  joker_joker {n_jj} | joker_consumable {n_jc} | "
          f"joker_voucher {n_jv} | joker_hand {n_jh} | joker_card {n_jcard}")
    um = meta["unmatched"]
    if um:
        print(f"  UNMATCHED names ({sum(len(v) for v in um.values())}):")
        for page, items in um.items():
            print(f"    {page}: {items}")
    else:
        print("  all names matched to sim keys")


if __name__ == "__main__":
    sys.exit(main())
