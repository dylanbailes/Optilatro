# M2 — Reference-Doc Fidelity Audit (2026-08-06)

Audits `vendor/balatro-rl` against the verified source of truth,
`balatro-mechanics-reference(2).md` (which was itself cross-checked against
balatrowiki.org and balatro-rs game data). Scope: every mechanic the reference
doc now pinpoints — stickers, boss score multipliers + Matador compatibility,
shop generation weights, first-shop booster guarantee, Illusion, plus the
still-open M1 economy items. File:line refs are `balatro_sim/<file>.py`.

## Verdict

The scoring/mechanics core (hand eval, jokers, consumables, bosses, tags,
vouchers, seed-exact RNG) is close to the reference. The gaps are concentrated
in the **economy and shop-generation layer**, where several sim approximations
distort *what the agent is offered and what it earns* — exactly the numbers a
win-rate search optimizes. None are hard to fix; they are data/odds swaps, not
re-architectures.

## Status — P0 fixes landed (2026-08-06)

All three P0 items below are **FIXED and verified** (838 tests pass, ci_gate
4/4, bench ~2,500 steps/s). Shop seed pins re-derived; the shop's RNG wiring is
now closer to the real game (one `cdt{ante}` poll per slot, then
`rarity{ante}sho` / `Joker{n}sho{ante}` for jokers).

## Status — P1 fixes landed (2026-08-06)

All nine shop-fidelity P1s are **FIXED and verified** (881 tests pass,
ci_gate 4/4): Illusion odds (#4), Magic-Trick card price (#5), the first-shop
Buffoon Pack guarantee (#6), Showman duplicate suppression (#7), the Voucher
slot restock-after-Boss rule (#8), Buffoon-pack joker editions (#9),
Standard-Pack card modifiers (#10), The Needle's 1x base (#11, incl. the
`_reroll_boss` path — `test_reroll_to_needle_scales_chips`), and Mega Buffoon
$8/4 (#12).

## P0 — fix before investing in search/RL  ✅ FIXED

1. **Blind reward money — FIXED.** `_end_round` now pays the flat **$3 / $4 /
   $5 / $8** (Small / Big / Boss / Showdown) on top of hand payout + interest
   (`constants.BLIND_REWARDS` / `SHOWDOWN_REWARD`, verified against the real
   `game.lua` blind table: `bl_small dollars=3`, `bl_big dollars=4`, bosses
   `dollars=5`, Showdown finals `dollars=8`).

2. **Matador — FIXED.** No blind-start payout; `_play_hand` pays **$8 per
   qualifying hand** for exactly the wiki's 13 bosses: Flint (every hand),
   Goad/Club/Window/Head/Plant/Pillar (a debuffed card must actually *score*),
   Eye/Mouth (rejected hand), Psychic (<5-card non-scoring play — consumes a
   hand, closing the free-$8 farm), Arm (played level ≥ 2), Ox (hand zeroes
   money; Ox zeroes first, then Matador pays), Verdant Leaf (until a joker is
   sold). The other 15 bosses never pay (Wheel, House, Fish, Water, Wall,
   Manacle, Serpent, Needle, Tooth, Mark, Hook, Amber, Violet, Crimson,
   Cerulean — the real-game flag-timing oversight).

3. **Shop card-type poll — FIXED.** `generate_shop` now creates
   `shop_item_slots` (2 base, +1 per Overstock/Overstock Plus — the real
   `G.GAME.shop.joker_max` + `change_shop_size(1)`) cdt-polled slots via
   `_random_shop_item` using the real weights **Joker 20 / Tarot 4 / Planet 4**
   (+4 playing-card with Magic Trick/Illusion; spectrals never without Ghost
   Deck; Merchant → 9.6, Tycoon → 32 — all cross-checked against
   balatro-seed's `next_shop_item` and the decompiled `shop.lua`/
   `create_card_for_shop`). The old hard split (2 jokers + 2 consumables) is
   gone; a shop slot can now be a Tarot or Planet.

## P1 — shop-fidelity gaps

4. **Illusion odds — FIXED.** `_shop_card_item` (`shop.py:448`) now rolls
   Enhancement **40%** and Edition **20%** (`chance(0.4)` / `chance(0.2)` — the
   real `pseudorandom('illusion') > 0.6 / > 0.8` checks). The edition split
   matches the real poll — Foil 50% / Holographic 35% / Polychrome 15% — and is
   **never Negative**. Seals stay off ✓ and Illusion is unaffected by Hone/Glow
   Up ✓ (both real-game correct). Test: `test_illusion_odds_40_20_no_negative`
   (4000 samples) in `tests/test_vouchers.py`.

5. **Magic Trick card price — FIXED.** `_shop_card_item` prices shop playing
   cards at **$1** (`ShopItem(..., 1, ...)` — §17 base-cost table). Test:
   `test_magic_trick_cards_cost_1`.

6. **First-shop Buffoon Pack — FIXED.** `generate_shop` forces the first pack
   slot of the run's first shop to `p_buffoon` via `game.first_shop_buffoon`
   (the real `G.GAME.first_shop_buffoon` in `get_pack`). It consumes **no**
   seeded pack-generic draw (the real game uses unseeded `math.random` for the
   variant), so the second slot gets draw #1 — the golden-pin shift captured in
   `test_seed_rng.EXPECTED_SHOP` (seed 11: `p_buffoon` + `p_standard_jumbo`).
   Tests: `TestShopSlots::test_first_shop_*` in `tests/test_phase0.py`.

7. **Showman duplicate suppression — FIXED.** Shop and pack generation now
   implement the real lock-triggered resample (balatro-seed
   `instance.rs::randchoice`, a byte-accurate port of the game): without
   Showman, any Joker/Tarot/Planet/Spectral in the player's possession is
   excluded from the pool in the Shop and Booster Packs alike by re-drawing
   from `{node_id}_resample{n}` nodes (1000-resample fallback — a fully-owned
   pool re-allows duplicates, like the real game). Pack generation also
   temporarily locks each drawn card, so a pack never repeats one. Both are
   bypassed when Showman (`j_ring_master`) is owned, and selling a joker or
   using a consumable re-allows it (possession is the lock source). Wired
   through every joker/tarot/planet/spectral draw: shop slots, all pack
   contents, tag jokers, and consumable-created jokers (Judgement/Wraith/The
   Soul). Tests: `TestShowmanSuppression` in `tests/test_phase0.py` (11).

8. **Voucher offered after every blind (not just after the Boss) — FIXED.**
   `generate_shop(game, restock_voucher=)` now tracks the offered voucher on
   `game.offered_voucher`: the same voucher **persists across non-Boss blinds
   and rerolls** (the real game's single voucher card stays until bought), and
   a fresh roll happens only after the Boss Blind is defeated — or the run's
   first shop, when nothing has been offered yet (`restock_voucher` is passed
   as `current_blind.is_boss` from `_end_round`; `reroll_shop` and the skip
   path pass False). Buying the offered voucher empties the slot until the
   next Boss (bought vouchers are never re-offered). The Voucher Tag's extra
   slot is still a fresh draw (`_random_voucher(exclude=)` keeps it distinct
   from the persistent slot). Draw-order note: a non-Boss shop now consumes
   **no** `Voucher{ante}` node draw (verified via the seed-mode trace log),
   matching balatro-seed's once-per-ante voucher draw; the golden pins were
   unchanged because the run's first shop still draws first. Tests:
   `TestVoucherRestock` in `tests/test_vouchers.py` (10, incl. an
   all-vouchers-owned sentinel test proving the slot stays empty AND draw-free
   once the pool is exhausted).

9. **Booster-pack jokers never roll editions — FIXED.** `_open_booster`'s
   joker branch now rolls `_roll_edition` on the real `edibuf{ante}` node for
   every Buffoon-pack joker, with Hone/Glow Up boosting identically to shop
   jokers (`_edition_boost` — the real game's `next_joker` reads
   `G.GAME.edition_rate` for every joker regardless of source; mirrored by
   balatro-seed `draws.rs::next_joker`). Pack choices are now
   `("joker", key, edition)` tuples (parallel to `("card", card)`), consumed
   by `game._pick_booster` and `env_v5._step_pack_open` — which also fixed a
   latent bug where plain-string joker keys were misrouted into the consumable
   hand when a slot was free. Tests: `TestBuffoonPackEditions` (6) in
   `test_phase0.py` (base-odds stats over 4800 draws, Hone 3x-Poly quirk,
   pick-through-game, env_v5 pick, seed-mode determinism, within-pack
   no-repeat on keys).

10. **Standard-Pack cards never get modifiers — FIXED.** `_open_booster`'s
    `card` branch now rolls the real `nextStandardCard` sequence per card
    (balatro-seed `draws.rs::next_standard_card`, node names from
    `node_id.rs`): Enhancement **40%** (`stdset{ante}` > 0.6, type from the 8
    real enhancements on `Enhancedsta{ante}`), base card (`frontsta{ante}` —
    one draw from the 52-card pool in the real CARDS order, so within-pack
    duplicates are expected, matching the real game's no-lock rule), Edition
    **Foil 4% / Holographic 2.8% / Polychrome 1.2%** (`standard_edition{ante}`
    thresholds 0.92/0.96/0.988 — **never Negative, and NOT boosted by
    Hone/Glow Up**, since only `next_joker` reads `G.GAME.edition_rate`), and
    Seal **20%** (`stdseal{ante}` > 0.8) evenly split across the 4 variants
    (`stdsealtype{ante}`). Replaces the old `make_standard_deck()` shuffle
    (which misused `stdset{ante}`, the real enhancement-poll node, for the
    shuffle). Choices stay `("card", card)` tuples — `game._pick_booster` and
    `env_v5._step_pack_open` were already tuple-aware, and the sim's scoring
    already implements seal effects (Red retrigger / Blue planet / Gold $3 /
    Purple tarot). Tests: `TestStandardPackModifiers` (6) in `test_phase0.py`
    (base-odds stats over 6000 cards, 52-card coverage, pick-through-game
    carries modifiers, seed-mode node-structure trace, deterministic
    Hone-no-boost proof, within-pack duplicates).

11. **The Needle — FIXED.** Boss score scaling (`game.py:356-363`) now gives
    The Needle a **1x** base requirement (`bl_needle.mult = 1` in game.lua).
    Unlike Wall/Violet — whose scaling is a disableable ability that reverts to
    2x with Chicot/Luchador — the Needle's 1x is not part of the ability set,
    so it stays 1x even when boss abilities are disabled. Tests:
    `TestLargeBlindScaling::test_needle_*` in `tests/test_boss_effects.py` + the
    updated chip-table check in `tests/test_game_transitions.py`.

12. **Mega Buffoon priced $10 / 5 jokers — FIXED.** `BOOSTER_CATALOGUE` now
    lists `p_buffoon_mega` as $8 / 4 jokers (pick 2) — the real 2/4/4
    (Normal/Jumbo/Mega) Buffoon progression at $4/$6/$8 (§15); only the
    tag-only Mega Buffoon was wrong (Mega Standard was already $8/5 ✓).
    Test: `test_mega_buffoon_is_8_dollars_four_jokers` in `test_phase0.py`.

## P2 — v1-scope / lower priority

13. **Booster Pack type/size rates are uniform, not weighted — FIXED.**
    `generate_shop` now draws each pack slot via the weighted `.choices()` on
    the real `shop_pack{ante}` node using `PACK_WEIGHTS` (shop.py) — the full
    15-pack real table from balatro-seed `pools.rs::PACKS` (pool order and
    weights byte-aligned; the 15 entries sum to 22.42, the table's RETRY
    sentinel): Arcana/Celestial/Standard 4 / 2 / 0.5, Buffoon 1.2 / 0.6 /
    0.15, Spectral 0.6 / 0.3 / 0.07 (Normal/Jumbo/Mega). The old uniform
    `choice(SHOP_PACK_POOL)` over 13 packs over-offered Spectral (~10% vs
    real ~4.3%) and Buffoon and under-offered Standard/Arcana/Celestial. This
    also fixes a latent gap: the Mega Buffoon/Standard (weights 0.15 / 0.5)
    were excluded as "tag-only", but the real game's shop can offer every
    size — they are now shop-legal (still granted free by their Tags). The
    run's first-shop Buffoon guarantee is unchanged and still consumes no
    seeded draw; seed-11's second-slot pin (`p_standard_jumbo`) landed on the
    same pack under the weighted mapping, so `EXPECTED_SHOP` needed no
    re-derivation. Tests: `TestPackWeights` (4) in `test_phase0.py` (family
    rates over ~5000 draws, Normal>Jumbo>Mega ordering per family,
    shop-legal Mega Buffoon/Standard, seed-mode trace pin that the
    shop_pack{ante} draw is a weighted 15/22.42 choices call).

14. **Stakes + stickers entirely unimplemented.** No stake or sticker logic
    exists (`__init__.py:8` — "Phase 5: Deck types, stakes"). Reference (§13)
    sticker rules — 30% spawn each, 11 no-Eternal / 18 no-Perishable
    exemptions, Perishable 5-round countdown (debuff before cash-out), Rental
    $1 buy / $3 per round — are N/A while the sim is locked to White Stake
    (correct per the spec), but will be needed before any higher-stake work.

15. **Merchant/Tycoon multiplier model — FIXED (landed with P0 #3).** The
    audit's "2x/4x on a base-50 weight" description predates the #3 shop
    restructure: `_shop_item_weights` (shop.py:527) already uses the real
    rates — base Joker 20 / Tarot 4 / Planet 4, Merchant → 9.6 (~28.6% of
    cdt-polled slots), Tycoon → 32 (~57.1%), Tycoon checked first (real
    precedence), matching balatro-seed `next_shop_item` and the decompiled
    `create_card_for_shop`. Pinned deterministically by `test_consumable_weights`
    and statistically by `test_merchant_and_tycoon_shop_rates` (4000 draws per
    rate) in `test_vouchers.py`; a Tarot voucher leaves the Planet weight at 4.

16. **Endless not implemented** (v1 = Antes 1–8). Reference (§16) Endless
    growth formula + Ante-39 `naneinf` ceiling are documented for later.

## Verified correct (matches the reference — do not touch)

- **Edition odds**: `_roll_edition` (`shop.py:491-513`) — base Negative 0.3% /
  Poly 0.3% / Holo 1.4% / Foil 2%; Hone 2× / Glow Up 4× with the Polychrome
  3×/7× quirk → exactly the doc's 4/2.8/0.9% and 8/5.6/2.1%. Markup 2/3/5/5 ✓.
- **Joker rarity 70/25/5**, no Legendaries in the shop ✓ (§17).
- **BLIND_CHIPS** (`constants.py:58-68`) — White targets 300/800/2,000/…/50,000
  with the 1 / 1.5 / 2 multipliers ✓ (§16). Wall 4x / Violet 6x with correct
  Luchador/Chicot disable behavior ✓; Needle 1x (non-disableable) ✓.
- **Boss min-ante table + selection** — all 28 match the doc and the wiki
  (Ox 6, Plant 4, Serpent 5, Eye/Tooth 3, Needle 2, 8 at ante 1) ✓ (§10).
- **Reroll $5 +$1/reset, pack prices $4/$6/$8, voucher $10, consumable prices
  $3/$3/$4** ✓ (§15/§17). Joker base costs come from the rebuilt catalogue ✓.
- **Hone/Glow Up, Magic Trick/Illusion, Omen Globe, Telescope, Observatory,
  Tarot/Planet Merchant/Tycoon (9.6/32 — #15), Overstock** all wired ✓ (#3–#5
  and #15 all FIXED).

## Doc corrections surfaced by this audit (already applied to the reference)

- **Spectral Pack contents: the reference doc was wrong, the sim was right.**
  §15 listed Spectral as 3 / 5 / 5; the wiki says Normal 2 / Jumbo 4 / Mega 4,
  which is what `BOOSTER_CATALOGUE` uses. Fixed in the doc + audit-log row.
- Booster Pack type/size weights added to §17 (the sim's uniform selection is
  finding #13 above).

## Notes / caveats

- The old `_consumable_weights` 40/50/10 claim was **resolved**: balatro-seed's
  `next_shop_item` and the decompiled `shop.lua` `create_card_for_shop`
  (`cdt` poll, `joker_rate=20/tarot_rate=4/planet_rate=4`, Merchant→9.6,
  Tycoon→32, Magic Trick→4) confirm the wiki. The sim now uses those exact
  weights and slot counts (2 + Overstock).

## Recommended fix order

`#3 card-type poll` ✅ → `#1 blind rewards` ✅ → `#2 Matador list + timing` ✅
→ `#4 Illusion odds` ✅ → `#5 card price` ✅ → `#6 first-shop Buffoon` ✅ →
`#11 Needle 1x` ✅ → `#7 Showman dup suppression` ✅ → `#8 voucher restock` →
`#9 pack-joker editions` ✅ → `#10 Standard-Pack modifiers` ✅ → `#12 Mega
Buffoon $8/4` ✅ → `#13 pack type/size rates` ✅ → `#15 Merchant/Tycoon rates` ✅ (landed with
#3) → `#14 stickers/stakes` (when stakes are in scope). Remaining items are
localized swaps; the seed-exactness gate
(`tests/test_seed_exactness.py -m ci_gate`) protects against draw-order drift
as they land; `EXPECTED_SHOP`/golden pins in `tests/test_seed_rng.py` needed
no re-derivation for #8 or #13 (the run's first shop still draws first, and
seed-11's weighted second-slot draw lands on the same pack).
