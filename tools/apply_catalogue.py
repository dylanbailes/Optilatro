"""Apply the rebuilt JOKER_CATALOGUE to shop.py and the canonical aliases to
jokers/__init__.py. Idempotent-ish: replaces between marker anchors."""
import io

# ── 1. shop.py: replace the old catalogue construction with the generated dict
shop_path = "vendor/balatro-rl/balatro_sim/shop.py"
src = io.open(shop_path, encoding="utf-8").read()

start_marker = "JOKER_CATALOGUE: dict[str, dict] = {}"
end_marker = "RARITY_WEIGHTS = {"
i0 = src.index(start_marker)
i1 = src.index(end_marker)

generated = io.open("tools/out_joker_catalogue.py", encoding="utf-8").read()
new_cat = (
    "# ════════════════════════════════════════════════════════════════════════════\n"
    "# JOKER CATALOGUE — canonical real-game ids, rarities, and base costs\n"
    "# (rebuilt from balatro-rs joker_data!, the authoritative game table; costs\n"
    "# wiki-verified). Effects resolve via JOKER_REGISTRY, incl. the canonical-key\n"
    "# aliases registered in jokers/__init__.py.\n"
    "# ════════════════════════════════════════════════════════════════════════════\n\n"
    + generated
    + "\n"
)
src = src[:i0] + new_cat + src[i1:]
io.open(shop_path, "w", encoding="utf-8", newline="\n").write(src)

# ── 2. shop.py: fix the stale price docstring ─────────────────────────────────
src = io.open(shop_path, encoding="utf-8").read()
old_doc = """Prices:
  Common Joker:    $6    Uncommon: $7    Rare: $8    Legendary: $20
  Planet / Tarot:  $3
  Booster (std):   $4
  Voucher:         $10"""
new_doc = """Prices:
  Jokers: per-joker base cost (real game table — e.g. Joker $2, Blueprint $10,
          Legendary $20) + edition markup; see JOKER_CATALOGUE.
  Planet / Tarot:  $3
  Booster (std):   $4
  Voucher:         $10"""
assert old_doc in src, "price docstring not found"
src = src.replace(old_doc, new_doc)
io.open(shop_path, "w", encoding="utf-8", newline="\n").write(src)

# ── 3. jokers/__init__.py: append canonical alias block ──────────────────────
init_path = "vendor/balatro-rl/balatro_sim/jokers/__init__.py"
src = io.open(init_path, encoding="utf-8").read()
alias_src = io.open("tools/out_joker_aliases.py", encoding="utf-8").read()
block = (
    "\n\n# ── Canonical-key aliases: real-game joker ids → sim effect classes ────\n"
    "# The shop now sells under the real game's ids (balatro-rs joker_data!).\n"
    "# Legacy sim keys (j_greedy_mult, ...) are aliased so a canonical id resolves\n"
    "# to the same effect class. Applied LAST so overrides win (e.g. j_ring_master\n"
    "# replaces the no-op marker with the Showman effect; j_ticket gets the real\n"
    "# Golden Ticket effect instead of the stale _Ticket).\n"
    + alias_src
    + "\nfor _canon, _legacy in _CANONICAL_JOKER_ALIASES.items():\n"
    "    if _legacy in JOKER_REGISTRY:\n"
    "        JOKER_REGISTRY[_canon] = JOKER_REGISTRY[_legacy]\n"
)
if "CANONICAL_JOKER_ALIASES" not in src:
    src = src + block
    io.open(init_path, "w", encoding="utf-8", newline="\n").write(src)

print("applied: shop.py catalogue rebuilt, price docstring fixed, aliases appended")
