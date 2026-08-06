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

4. **Illusion odds wrong.** `_shop_card_item` (`shop.py:454-468`) gives a 50%
   enhancement and 50% edition, and the edition pool is `EDITIONS` **including
   Negative** (`shop.py:467`). Reference (§17): Enhancement **40%**, Edition
   **20%**, no Negative on playing cards. (Seals off ✓ and unaffected by
   Hone/Glow Up ✓ — both correct.)

5. **Magic Trick cards priced $4; reference says $1.** `shop.py:468`
   (`ShopItem(..., 4, ...)`). Base-cost table (§17): Playing card **$1**.

6. **No first-shop Buffoon Pack guarantee.** `generate_shop` (`shop.py:391-395`)
   always draws 2 packs from `SHOP_PACK_POOL`. Reference (§17): the first Shop
   of a run guarantees one normal Buffoon Pack.

7. **No Showman duplicate suppression.** `random_joker_key` (`shop.py:180-200`)
   filters only `BANNED_JOKERS` (empty); owned jokers/tarots/planets/spectrals
   are never excluded from shops or packs, so Showman is a no-op. Reference
   (§17): without Showman, cards already in the player's possession are
   excluded from the pool for the rest of the run.

8. **Voucher offered after every blind (not just after the Boss).**
   `generate_shop` appends a voucher each shop (`shop.py:398-402`; the slot
   goes empty only once every voucher is purchased). Reference (§17): the
   Voucher slot restocks only after defeating the Boss Blind.

9. **Booster-pack jokers never roll editions.** `_roll_edition` is called only
   for shop jokers (`shop.py:371`); Buffoon-pack jokers (`shop.py:678`) always
   spawn base. Reference (§17) applies the edition odds to shop and pack Jokers
   alike.

10. **Standard-Pack cards never get modifiers.** `_open_booster`'s `card`
    branch (`shop.py:682-684`) takes plain cards from `make_standard_deck()`.
    Reference (§17): Booster-Pack playing cards roll Foil 4% / Holo 2.8% /
    Poly 1.2%, Enhancement 40%, Seal 20%.

11. **The Needle uses 2x base instead of 1x.** Boss score scaling
    (`game.py:349-354`) handles Wall 4x and Violet 6x only. Reference (§10/§16):
    The Needle's requirement is **1x** base.

12. **Mega Buffoon priced $10 instead of $8 and holds 5 jokers instead of 4**
    (`shop.py:238`). Reference (§15): all Mega packs cost $8 and Mega Buffoon
    contains 4 Jokers (choose 2). Tag-only in the sim (free via its Tag), so
    low impact, but wrong in the catalogue.

## P2 — v1-scope / lower priority

13. **Booster Pack type/size rates are uniform, not weighted.** `generate_shop`
    picks both packs with `choice(SHOP_PACK_POOL)` — every type/size equal.
    The wiki (Booster Packs page) weights Standard / Arcana / Celestial at
    4 / 2 / 0.5 (Normal / Jumbo / Mega), Buffoon 1.2 / 0.6 / 0.15, Spectral
    0.6 / 0.3 / 0.07. Net effect: the sim over-offers Spectral (~10% vs ~4.3%)
    and Buffoon packs and under-offers Standard/Arcana/Celestial. (Reference
    §17 now documents the real rates.)

14. **Stakes + stickers entirely unimplemented.** No stake or sticker logic
    exists (`__init__.py:8` — "Phase 5: Deck types, stakes"). Reference (§13)
    sticker rules — 30% spawn each, 11 no-Eternal / 18 no-Perishable
    exemptions, Perishable 5-round countdown (debuff before cash-out), Rental
    $1 buy / $3 per round — are N/A while the sim is locked to White Stake
    (correct per the spec), but will be needed before any higher-stake work.

15. **Merchant/Tycoon multiplier model.** Sim: `w_tarot *= 2` then `*= 2`
    (Tycoon = 4× base 50). Reference (§17): Merchant→9.6, Tycoon→32 from base 4
    (i.e. ~2.4× / 8×). Only meaningful once the weights are moved to the real
    20/4/4 scale (#3).

16. **Endless not implemented** (v1 = Antes 1–8). Reference (§16) Endless
    growth formula + Ante-39 `naneinf` ceiling are documented for later.

## Verified correct (matches the reference — do not touch)

- **Edition odds**: `_roll_edition` (`shop.py:491-513`) — base Negative 0.3% /
  Poly 0.3% / Holo 1.4% / Foil 2%; Hone 2× / Glow Up 4× with the Polychrome
  3×/7× quirk → exactly the doc's 4/2.8/0.9% and 8/5.6/2.1%. Markup 2/3/5/5 ✓.
- **Joker rarity 70/25/5**, no Legendaries in the shop ✓ (§17).
- **BLIND_CHIPS** (`constants.py:58-68`) — White targets 300/800/2,000/…/50,000
  with the 1 / 1.5 / 2 multipliers ✓ (§16). Wall 4x / Violet 6x with correct
  Luchador/Chicot disable behavior ✓.
- **Boss min-ante table + selection** — all 28 match the doc and the wiki
  (Ox 6, Plant 4, Serpent 5, Eye/Tooth 3, Needle 2, 8 at ante 1) ✓ (§10).
- **Reroll $5 +$1/reset, pack prices $4/$6/$8, voucher $10, consumable prices
  $3/$3/$4** ✓ (§15/§17). Joker base costs come from the rebuilt catalogue ✓.
- **Hone/Glow Up, Magic Trick/Illusion, Omen Globe, Telescope, Observatory,
  Tarot/Planet Merchant/Tycoon, Overstock** all wired (subject to #3–#5).

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
→ `#4 Illusion odds / #5 card price` → `#6–#12` →
`#14 stickers/stakes` (when stakes are in scope). Remaining items are
localized swaps; the seed-exactness gate
(`tests/test_seed_exactness.py -m ci_gate`) protects against draw-order drift
as they land, and `EXPECTED_SHOP`/golden pins in `tests/test_seed_rng.py`
will need re-derivation for #4/#6/#13.
