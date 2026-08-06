# M1 — Fidelity Audit (pre-search gate)

**Date:** 2026-08-06
**Scope:** `vendor/balatro-rl/` sim, full ruleset wired (all 28 bosses, 32 vouchers, 24 tags, seed-exact RNG). Companion to `docs/M0-vendor-audit.md`.
**Method:** code read of `game.py` / `shop.py` / `consumables.py` / `scoring.py` / `jokers/*.py`, automated diff of `JOKER_CATALOGUE` against the authoritative balatro-rs joker table (`tools/audit_diff_jokers.py`), and cross-checks against balatrowiki.org.

## Executive summary

The sim is behaviorally complete and seed-deterministic, but a fidelity audit found **two P0 and four P1 gaps** that would corrupt win-rate numbers if search/RL was trained on top of them today. The single highest-leverage issue: **the shop's joker rarity table is wrong for 78 of 136 offered jokers**, which makes the sim's shop dramatically easier than the real game's. Second: **blind-reward money is not paid at all**. Third: a whole class of **consumable-generating jokers is broken** (they push unresolvable placeholder strings into the consumable hand) and **8+ joker hooks are never fired** (dead jokers).

**Fix status (2026-08-06):** **A2 (rarity table), A3 (prices), A6 (canonical keys + full pool) FIXED** — `JOKER_CATALOGUE` rebuilt from the balatro-rs `joker_data!` table: 149 canonical real-game ids, real rarities, real per-joker base costs (wiki-verified), the 6 duplicate entries dropped, and every key resolves via canonical aliases (`tools/gen_joker_catalogue.py`). Shop rarity distribution verified at 69.9/25.0/5.1/0% over 6,000 samples (real = 70/25/5/0). Obs dims unchanged (jokers encode as a normalized index, not a one-hot). Regression tests added in `tests/test_seed_rng.py` (catalogue matches real game, real rarities/prices, canonical aliases resolve). Full suite **821 passed**, gate green.

**Remaining before training any policy:** A1, B1, B2, B3, B4 (see §5).

---

## 1. What was verified correct (don't touch)

| Area | Status |
|---|---|
| Hand evaluation | 12 hand types incl. Flush Five/House, ace-low straights, Wild/Stone handling ✓ |
| Card model | 8 enhancements, 4 editions, 4 seals (Red retrigger, Blue/Purple/Gold wired) ✓ |
| Boss blinds | All 28 real bosses with effects; real selection (min-ante, no-repeat rotation, ante-8 Showdown pool) ✓ |
| Vouchers | All 32 with pair-unlock; **Seed Money = interest cap $10, Money Tree = $20 — CONFIRMED CORRECT vs wiki** (interest cap was thought mislabeled; it is not) ✓ |
| Tags | All 24 real tags implemented; weights uniform (A5) |
| Deck persistence | Run deck persists across blinds; destroyed cards stay gone ✓ |
| RNG | Every consumer routes through `game.rng`; cross-process seed-exactness gate green ✓ |
| Economy constants | $4 start, $1 per $5 interest (cap 5), $1/hand remaining, 4 hands / 3 discards / 8-card hand, reroll $5 uncapped + resets per shop, shop = 2 jokers + 2 cards + 1 voucher + 2 packs ✓ |
| Consumable sets | 22 tarots, 12 planets, all 18 spectrals (incl. Soul → legendary joker) ✓ |

---

## 2. [P0] Shop / joker economy

### A1. No blind-reward money is paid
`game._end_round()` pays only `hands_left * $1` + interest. The real game pays a **blind reward** on defeat: Small **$3**, Big **$4**, Boss **$5**, ante-8 Showdown **$8** (below Red Stake; $0 for Small on Red+). This is ~$3–5 × 24 blinds = **$80–120 of run economy missing** — every economy decision (reroll, interest timing, buy thresholds) is trained against a poorer-than-real game. (Note: the interest-cap vouchers are correctly wired — Seed Money = cap $10, Money Tree = cap $20, verified against the current wiki — so no voucher change is needed here.)

### ~~A2~~ **[FIXED 2026-08-06]** Joker rarity table wrong for 78/136 offered jokers (+ 6 duplicate entries)
*Rebuilt: `JOKER_CATALOGUE` now has the 149 real jokers under canonical ids with real rarities + base costs (from balatro-rs `joker_data!`); the 6 duplicate-name entries are gone. Shop draws now track the real 70/25/5/0 rarity split (verified over 6,000 samples).*
`JOKER_CATALOGUE` assigns rarities that disagree with the real game for **78 of 136 name-matched jokers** (diff vs balatro-rs `joker_data!`, the definitive table). The shop's rarity **poll** is correct (real >0.7 / >0.95 thresholds), but **pool membership is wrong**, so the 70% Common pool contains many real Uncommon/Rare jokers and vice-versa. Examples:
- Baron (real **Rare**) → sim Common → offered 14× too often
- DNA, Brainstorm, Invisible Joker, Obelisk, Baseball Card (real **Rare**) → sim Common
- Abstract, Half Joker, Odd Todd (real **Common**) → sim Uncommon/Rare
- Acrobat, Fibonacci, Hack, Mime, Madness, Hologram, Bull (real **Uncommon**) → sim Common

Additionally **6 jokers are registered twice** under two keys with conflicting rarities, doubling their shop presence:
```
The Duo → j_duo(Uncommon) + j_the_duo(Rare)     The Family → j_family + j_the_family
The Trio → j_trio + j_the_trio                   The Order → j_order + j_the_order
The Tribe → j_tribe + j_the_tribe                Wee Joker → j_wee_joker(Common) + j_wee(Rare)
```
Same-key overwrites also left wrong final rarities: stencil (Common→Rare, correct), **drivers_license (real Uncommon → Rare)**, **abstract (Common → Uncommon)**, **half (Common → Uncommon)**, **odd_todd (Common → Uncommon)**, **flash (Uncommon → Rare)**.
Net effect: the sim's shop over-delivers strong jokers — win-rate numbers trained here will overstate the real game.

### ~~A3~~ **[FIXED 2026-08-06]** Flat joker prices
*Real per-joker base costs now used (Joker $2 … Blueprint $10, Legendary $20); sell value (half price) inherits the fix.*
Sim prices every Common $6 / Uncommon $7 / Rare $8. Real prices vary per joker (Common $1–6, Uncommon $4–8, Rare $7–10, Legendary $20). Sell value (half price) inherits the error. Moderate economy distortion.

### A4. [P2] Shop edition odds slightly off
`_roll_edition` uses 0.4%/2%/4% for Foil/Holo; the real game is roughly 0.3% Negative / 0.6% Polychrome / ~1.4% Holographic / ~2.8% Foil (approximate — verify against the wiki before relying on it).

### A5. [P2] Tag weights uniform; no edition-discovery gating
`roll_tag` uses uniform weights (documented `TAG_WEIGHTS` placeholder). Real game has per-tag weights and gates Foil/Holo/Poly/Negative tags behind having ever owned that edition.

### ~~A6~~ **[FIXED 2026-08-06]** 12 real jokers never offered in the shop
*All 149 real jokers are now offerable under canonical ids (`j_bootstraps`, `j_drunkard`, `j_fortune_teller`, `j_golden`, `j_smiley`, `j_hallucination`, `j_idol`, `j_juggler`, `j_mail`, `j_stone`, `j_ticket`, `j_to_the_moon`, …). Note: `j_caino` IS the real Canio id (the earlier "typo" call was wrong), and the real game spells Gluttonous Joker as `j_gluttenous_joker` (a game-data typo the sim bridges via alias). Canonical ids also unblock future save-file/live-game interop. Caveat: the previously-unoffered jokers include the M1-documented broken ones (Hallucination's hook never fires, etc.) — they're now buyable, which raises the priority of the B1/B2 wiring fixes.*

---

## 3. [P0] Joker effect wiring — broken classes

### B1. Consumable-generating jokers are broken (12 jokers)
Jokers signal "create a consumable" by pushing **placeholder strings** into `pending_consumables`/`pending_consumables`, which `game.py` appends verbatim to `consumable_hand`. These strings (`"tarot"`, `"spectral"`, `"common_joker"`, `"stone_card"`, `"duplicate_joker"`, `"negative_tarot"`, `"copy_card:14:Spades"`, `"double_tag"`, `"random_enhanced_card"`) are **never resolved** — they are not valid planet/tarot/spectral keys, so `_use_consumable` can never use them, and they **permanently occupy one of the 2 consumable slots** (can't be used or sold). Affected jokers (all effectively dead / harmful):
- Scoring-time: **8-Ball**, **Seance**, **Superposition**, **Sixth Sense** (also only fake-destroys the 6)
- Blind/round-time: **Cartomancer**, **Riff-Raff** ("common_joker" ×2), **Marble** ("stone_card"), **Certificate** ("random_enhanced_card"), **Perkeo** ("negative_tarot"), **Invisible Joker** ("duplicate_joker"), **Diet Cola** ("double_tag"), **DNA** ("copy_card:…")

### B2. Joker hooks never fired by the game loop (8+ dead jokers)
`game.py` fires only `on_blind_selected`, `on_boss_ability_triggered`, `on_discard`, `on_round_end`, `on_blind_skipped`, `on_sell`, `on_boss_beaten`. These hooks are **never called**, so their jokers do nothing when bought:
- `on_shop_enter` — **Astronomer** (free planets), **Credit Card** ($-20 debt), **Chaos** (free first reroll), **Showman** (no-op anyway)
- `on_shop_leave` — **Perkeo**
- `on_reroll` — **Flash** (Flash Card never gains +2 Mult)
- `on_booster_opened` — **Hallucination**
- `on_init` — **To Do List** (target never set; stuck at High Card)
- `on_planet_used` — **Satellite** (`planets_used` never populated → pays $0)
Also `Gift Card` sets `pending_shop_buff` which `shop.generate_shop` never reads (dead). Phase 0's "zero dead shop jokers" only verified registry resolution, not hook wiring.

---

## 4. [P1/P2] Card-mechanic & scoring fidelity

### B3. [P1] Steel card + Mime use the wrong model
Real Steel: **held in hand** → x1.5 Mult when the hand scores (the Steel card is *not* played). Sim (`scoring.py`): applies x1.5 when the Steel card is **scored**. This removes the core "hold Steel, score something else" strategy and turns played Steel into a mult bomb it isn't. **Mime** ("retrigger held-in-hand effects") is built on the same wrong model — it retriggers *scored* Steel/Gold cards instead of held ones. Both need a held-in-hand scoring pass.

### B4. [P1] Lucky card odds/effects wrong
Real Lucky: **1 in 5** chance to **win $20 (money)** when scored; **1 in 15** chance to **retrigger all played cards**. Sim: 1/4 chance to **+20 Mult**, and 1/15 to +$20 money. Both the odds and the effects differ.

### B5. [P1] Driver's License & Stone Joker count the wrong population
Both count `ctx.all_cards` (the current hand) instead of the **full deck**: Driver's License needs 16+ enhanced cards in the *deck* (essentially never triggers), Stone Joker should count Stones in the whole deck.

### B6. [P2] Miscellaneous
- **Trading Card** uses module `import random` for its destroy pick — the one remaining seed-exactness leak (masked because the gate's action sequences never discard with Trading Card owned).
- Sixth Sense / Trading Card fake "destroy" via `debuffed=True` instead of removing the card.
- Blueprint/Brainstorm copy only scoring hooks (`pre_score`/`on_score_card`/`on_hand_scored`); real Blueprint copies all effect types (economy, round-end, etc.).
- Negative edition's "-1 joker slot" (negatives don't consume a slot) not modeled — slot cap is hard at 5.
- Standard Packs never contain enhanced/editioned/sealed cards (real packs roll those); Buffoon-pack jokers never roll an edition.
- Blue Seal grants the planet of the hand *played*; real grants the most-played hand's planet when held at round end.
- No mid-round reshuffle of the discard pile when the deck empties (real game recycles spent cards; the sim stops drawing). Rare at base config, matters after heavy deck thinning.

---

## 5. Recommended fix order before search/RL

1. **A2/A3/A6 — DONE (2026-08-06)**: catalogue rebuilt from balatro-rs (149 canonical keys, real rarities/prices, duplicates dropped, aliases wired, regression tests).
2. **A1** — Pay the blind reward ($3/$4/$5/$8) in `_end_round`. (~15 min)
3. **B1** — Resolve placeholder consumables to real keys (random tarot/spectral/legendary etc.) or model the jokers' real outputs; never park junk in `consumable_hand`. (~2h)
4. **B2** — Fire `on_shop_enter/leave`, `on_reroll`, `on_booster_opened`, `on_init`, `on_planet_used` from `game.py`/`shop.py`; make `generate_shop` honor `free_planets`/`pending_shop_buff`. (~1h)
5. **B3 + B4** — Held-in-hand scoring pass (Steel, Mime, Blue Seal) + correct Lucky odds/effects. (~2h)
6. **B5, B6, A4, A5, C-* ** — sweep after the above; each is small and mostly independent.
7. Re-run the seed-exactness gate + golden pins after any change that touches draw order (B1–B4 all consume RNG — the gate will catch drift).

Tracking: `tools/audit_diff_jokers.py` reproduces the A2/A6 diff (name-matched against balatro-rs); keep it as a regression tool once rarities are fixed.
