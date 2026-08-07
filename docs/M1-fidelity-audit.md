# M1 — Fidelity Audit (pre-search gate)

**Date:** 2026-08-06
**Scope:** `vendor/balatro-rl/` sim, full ruleset wired (all 28 bosses, 32 vouchers, 24 tags, seed-exact RNG). Companion to `docs/M0-vendor-audit.md`.
**Method:** code read of `game.py` / `shop.py` / `consumables.py` / `scoring.py` / `jokers/*.py`, automated diff of `JOKER_CATALOGUE` against the authoritative balatro-rs joker table (`tools/audit_diff_jokers.py`), and cross-checks against balatrowiki.org.

## Executive summary

The sim is behaviorally complete and seed-deterministic, but a fidelity audit found **two P0 and four P1 gaps** that would corrupt win-rate numbers if search/RL was trained on top of them today. The single highest-leverage issue: **the shop's joker rarity table is wrong for 78 of 136 offered jokers**, which makes the sim's shop dramatically easier than the real game's. Second: **blind-reward money is not paid at all**. Third: a whole class of **consumable-generating jokers is broken** (they push unresolvable placeholder strings into the consumable hand) and **8+ joker hooks are never fired** (dead jokers).

**Fix status (2026-08-06, updated):** the **economy/shop layer is fully closed against the reference doc** (`docs/M2-reference-audit.md` — all M2 P0s, all nine P1s, and P2 #13/#15 FIXED): **A1** blind rewards ($3/4/5/8), **A2** rarity table (149 canonical keys rebuilt from balatro-rs `joker_data!`, 70/25/5/0 verified), **A3** real per-joker prices, **A4** edition odds (2/1.4/0.3/0.3 + Poly 3x/7x quirk), **A6** full offerable pool — plus the real shop structure (cdt 20/4/4 slots + Overstock, Merchant/Tycoon 9.6/32), Showman duplicate suppression, voucher restock-after-Boss, pack-joker editions, Standard-Pack card modifiers, weighted pack rates, Mega Buffoon $8/4, The Needle 1x. **The scoring / joker-wiring track is now CLOSED too** (§3–§5: B1–B5 FIXED via the **joker-fidelity program** — see the dedicated bullet below). Full suite **974 passed**, ci_gate 4/4; bench **2/2000 = 0.10%** random win rate (was 0/1000 = 0.00%).

**Joker-fidelity program (2026-08-06, complete):** rebuilt the entire joker layer against the reference doc as source of truth — `tools/gen_joker_spec.py` parses the doc's §2 joker table (150 rows) into `tools/joker_spec.json` (149 canonical keys + base row, all costs verified; caught **Delayed Gratification missing from the catalogue** — generator regex gap, fixed); `tools/audit_jokers_static.py` gates structure (DUPES/DEAD/STUBS/GAPS/TYPE, wired into CI). Program fixes: **35 duplicate registrations** removed (import-order lottery — e.g. Mystic Summit chips-vs-mult, throwback ×0.25-vs-×2, photograph ×2-face-vs-+2-every-face), **15 dead non-canonical keys** purged, **Duo-family xMult moved onto canonical keys** (`j_duo` ×2, `j_trio` ×3, `j_family` ×4, `j_order` ×3, `j_tribe` ×2 — previously the shop sold additive +2/+4/+8/+3/+2 under those keys with the real xMult classes dead), `j_satellite` pass-stub shadow removed, **Madness** ×(1+0.5×blinds) Small/Big-only, **Steel Joker** ×0.2 per Steel in full deck, **Hiker** +5 stored as `card.bonus_chips` and **read by scoring**, **Campfire** grows on any joker sold, **destroyed-flag honored** (Gros Michel/Cavendish/Seltzer self-destruct), **Castle** lazy-suit init works round 1 with permanent chips, **Stuntman/Turtle Bean** hand-size passives applied, **held-in-hand scoring pass** (Steel ×1.5 held not played, Mime doubles held procs, Baron/Blackboard/Shoot the Moon/Raised Fist), **full-deck counts** (Driver's License 16+ enhanced, Stone/Glass/Steel Joker), **Lucky card odds corrected to 1-in-5 → +20 Mult / 1-in-15 → +$20** (was 1/4; confirmed vs wiki + balatro-rs `prob_roll(1,5)`), Oops! All 6s doubles Lucky/Glass, **Lucky Cat** X0.25 per trigger, and the **B2 dead-hook dispatch** (§3).

**Joker-layer architecture refactor (R1–R8, 2026-08-06, complete):** hardened the joker/scoring system so the above stays verifiable. **R1** `@register_joker("j_x")` decorator-only registration (duplicate keys raise at import — the import-order lottery is impossible); **R2** every hook is a typed no-op on the `JokerEffect` base, dispatch is one `JokerInstance.fire()` (no `hasattr`/registry scatter, no `__import__` hack in scoring.py); **R3** capability flags replace engine key-scans (`doubles_lucky`, `retriggers_held`, `disables_bosses`, `free_planets`, `debt`, `allow_dupes`) — the engine never checks `j.key == "j_oops"` anymore; **R4** per-effect `STATE_DEFAULTS` deep-copied into each instance (Seltzer 10 hands, Egg sell value 1, Popcorn 20 mult, …); **R5** single `game.grant_joker()` acquisition path for all seven grant sites; **R6 B6 fixes** (below); **R7** new audit gates **SIG** (hook arity vs base), **STATE** (bare `inst.state["k"]` reads must have defaults), **NOSCAN** (engine key-scans banned) — all **CLEAN**; **R8** +9 regression tests. Validation: `tools/audit_jokers_static.py` reports **all 8 gates CLEAN**, 150/150 spec rows covered by `tests/test_joker_spec.py` (**78 behavioral tests**), full suite **974 passed**, ci_gate 4/4.

**Still open before training any policy:** **A5** (tag weights + edition-discovery gating), the **B6 misc item** below (mid-round reshuffle of the spent pile when the deck empties), and the M2 P2 scope: **stakes + stickers (#14)** and **Endless (#16)** — see `docs/M2-reference-audit.md`.

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
| Economy constants | $4 start, $1 per $5 interest (cap 5; Seed Money 10 / Money Tree 20), $1/hand, 4 hands / 3 discards (Red Deck +1) / 8-card hand, reroll $5, **flat blind rewards $3/4/5/8** ✓ |
| Shop structure | Real cdt{ante} poll (Joker 20 / Tarot 4 / Planet 4; Merchant→9.6, Tycoon→32), 2 random slots (+1 per Overstock), voucher slot (restocks after Boss), 2 weighted pack slots, per-joker prices, edition odds, Showman suppression ✓ (M2) |
| Consumable sets | 22 tarots, 12 planets, all 18 spectrals (incl. Soul → legendary joker) ✓ |

---

## 2. [P0] Shop / joker economy

### ~~A1~~ **[FIXED 2026-08-06]** No blind-reward money is paid
*`_end_round` now pays the flat **$3 / $4 / $5 / $8** (Small / Big / Boss / Showdown) on top of hand payout + interest (`constants.BLIND_REWARDS` / `SHOWDOWN_REWARD`, verified against the real `game.lua` blind table — M2 P0 #1). Tests: `TestBlindRewards` in `tests/test_phase0.py`.*
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

### ~~A4~~ **[FIXED 2026-08-06]** [P2] Shop edition odds slightly off
*`_roll_edition` now matches the real poll exactly — Negative 0.3% / Poly 0.3% / Holo 1.4% / Foil 2%; Hone 2x / Glow Up 4x with the real Poly 3x/7x quirk — and the same poll now applies to Buffoon-pack jokers on `edibuf{ante}` (M2 P1 #9). Verified in the M2 audit.*
`_roll_edition` uses 0.4%/2%/4% for Foil/Holo; the real game is roughly 0.3% Negative / 0.6% Polychrome / ~1.4% Holographic / ~2.8% Foil (approximate — verify against the wiki before relying on it).

### A5. [P2] Tag weights uniform; no edition-discovery gating
`roll_tag` uses uniform weights (documented `TAG_WEIGHTS` placeholder). Real game has per-tag weights and gates Foil/Holo/Poly/Negative tags behind having ever owned that edition.

### ~~A6~~ **[FIXED 2026-08-06]** 12 real jokers never offered in the shop
*All 149 real jokers are now offerable under canonical ids (`j_bootstraps`, `j_drunkard`, `j_fortune_teller`, `j_golden`, `j_smiley`, `j_hallucination`, `j_idol`, `j_juggler`, `j_mail`, `j_stone`, `j_ticket`, `j_to_the_moon`, …). Note: `j_caino` IS the real Canio id (the earlier "typo" call was wrong), and the real game spells Gluttonous Joker as `j_gluttenous_joker` (a game-data typo the sim bridges via alias). Canonical ids also unblock future save-file/live-game interop. Caveat: the previously-unoffered jokers include the M1-documented broken ones (Hallucination's hook never fires, etc.) — they're now buyable, which raises the priority of the B1/B2 wiring fixes.*

---

## 3. [P0] Joker effect wiring — broken classes

### ~~B1~~ **[FIXED 2026-08-06]** Consumable-generating jokers are broken (12 jokers)
*Resolved. Jokers now park **real** rewards — random tarot/spectral keys, `("joker"|"card"|"hand_card", …)` object tuples, or direct game mutations — and `game.py`'s new `_grant_pending` materializes them; no placeholder string can ever enter `consumable_hand`. Rewrites: **8-Ball** / **Superposition** / **Cartomancer** / **Vagabond** / **Hallucination** → random real Tarot; **Seance** / **Sixth Sense** → random real Spectral; **Riff-Raff** → 2 real Common jokers into the joker slots (deferred until after the blind-select hook loop, so a created joker's own hook never refires for the same blind); **Marble** → a real Stone card into the run deck; **Certificate** → a real card with a **random seal** into the hand (wiki-verified: seal, not enhancement; it persists in the run deck); **DNA** → a real copy of the played card (modifiers preserved) into the hand, returning to the deck next blind; **Perkeo** → a Negative copy of a random held consumable, appended past the slot cap (Negative grants +1 slot); **Invisible Joker** → sells after 2 rounds to duplicate a random joker, Negative stripped from the copy; **Diet Cola** → selling queues a free Double Tag. Also removed the wrong chips-only "+20 chips" 8-Ball build in chips.py that shadowed the real tarot-creating 8-Ball (chips imports after misc). Caveats: Perkeo's `on_shop_leave` and Hallucination's `on_booster_opened` still never fire (B2), so those two resolvers stay dormant until B2 lands; Sixth Sense's fake-destroy remains (B6). Tests: `TestB1RewardResolution` (11 tests, incl. seed-mode game-loop integration) + updated placeholder assertions in `tests/test_jokers.py`. Full suite **896 passed**, ci_gate 4/4.*

### ~~B2~~ **[FIXED 2026-08-06]** Joker hooks never fired by the game loop (8+ dead jokers)
*Dispatch sites now exist for every listed hook (joker-fidelity program, Phase 3): **`on_shop_enter`** (Astronomer free planets — `generate_shop` honors `free_planets`; Credit Card $-20 debt — `buy_item` checks `debt_limit`; Chaos free first reroll), **`on_shop_leave`** (Perkeo), **`on_reroll`** (Flash Card +2 Mult per reroll), **`on_booster_opened`** (Hallucination parks a real Tarot), **`on_init`** (To Do List target, Popcorn/Ramen/Ice Cream/Castle init), **`on_planet_used`** (Satellite +$1/unique planet, Constellation +X0.1), **`on_tarot_used`** (Fortune Teller +1 Mult), **`on_lucky_trigger`** (Lucky Cat X0.25 per successful ROLL — the real `lucky_trigger` loop fires per roll, so a card hitting both the +20-Mult and $20 rolls grants X0.5), **`on_card_added`** (Hologram X0.25 — wired to Marble/Certificate/DNA grants + Magic Trick buys), **`on_card_destroyed`** (Canio), **`on_booster_skipped`** (Red Card +3 Mult — fired from the real `skip_booster` action); `Gift Card`'s `pending_shop_buff` is honored by `generate_shop`. **`on_init` fires on EVERY acquisition path** — `buy_item`, `game._pick_booster` + env_v5's `_step_pack_open`, `_grant_pending` (Riff-Raff), Judgement/Wraith/The Soul (new `consumables._grant_joker` helper), and the Top-Up tag's `_add_topup_jokers` — so To Do List/Popcorn/Ramen/Ice Cream/Castle init identically however they arrive. All hooks route through `game._fire_joker_hook` on the per-node RNG (seed-deterministic). Tests: `tests/test_joker_spec.py` (Satellite/Constellation, Fortune Teller, Hologram, Red Card/Hallucination, Astronomer/Chaos/Credit Card, Flash, To Do List, `test_on_init_fires_on_all_acquisition_paths`, Lucky Cat double-trigger probe) + `TestB1RewardResolution`.*

---

## 4. [P1/P2] Card-mechanic & scoring fidelity

### ~~B3~~ **[FIXED 2026-08-06]** Steel card + Mime use the wrong model
*Held-in-hand scoring pass (joker-fidelity program, Phase 4): `score_hand` now takes `held_cards`; **Steel gives X1.5 Mult only while HELD** (never for a played Steel card), **Mime doubles each held-Steel proc** (engine-detected in `scoring.py`, plus doubled held-Gold payouts in `_end_round`), and the same held context powers **Baron** (X1.5 per held King), **Blackboard** (X3 if no red in hand), **Shoot the Moon** (+13 Mult per held Queen), **Raised Fist** (2× lowest held card rank), **Reserved Parking** ($1 per held face card). Tests: `test_steel_held_in_hand_not_scored`, `test_mime_doubles_held_steel`, + SCORING_SPEC held rows in `tests/test_joker_spec.py`.*

### ~~B4~~ **[FIXED 2026-08-06]** Lucky card odds/effects wrong
*Corrected to the real game (verified against the wiki AND balatro-rs `core/src/game.rs` `prob_roll(1,5)`/`prob_roll(1,15)` and the reference doc §6): **1-in-5 → +20 Mult**, **1-in-15 → +$20** (two independent rolls; the old sim rolled 1-in-4 for the Mult). **Oops! All 6s doubles both** (2/5 and 2/15), and **Lucky Cat** gains **X0.25 Mult per successful trigger** via the newly dispatched `on_lucky_trigger`. Test: `test_lucky_card_odds_and_lucky_cat`.*

### ~~B5~~ **[FIXED 2026-08-06]** Driver's License & Stone Joker count the wrong population
*All deck-count jokers now count the **full deck** via `ScoreContext.full_deck()` (joker-fidelity program, Phase 4): **Driver's License** X3 with 16+ enhanced cards (Stone excluded, per the real game), **Stone Joker** +25 chips per Stone in deck, **Glass Joker** X0.75 per Glass in deck, **Steel Joker** X0.2 per Steel in deck. Tests: `test_steel_joker_counts_full_deck`, `test_glass_joker_counts_full_deck`, `test_stone_joker_counts_full_deck`, `test_drivers_license_16_enhanced_in_full_deck`.*

### ~~B6~~ **[FIXED 2026-08-06]** [P2] Miscellaneous
*Standard Packs now roll enhanced/editioned/sealed cards and Buffoon-pack jokers roll editions (M2 P1 #9/#10); the joker `destroyed` flag is pruned from `game.jokers` (Gros Michel/Cavendish/Seltzer self-destruct). The joker-layer refactor (R6) closed the rest: **Trading Card's destroy pick now uses `inst.chance()`** (per-node seeded RNG — the module-`random` leak is gone; verified by a test that patches `random.choice` and asserts it is never called); **real destroys** — Sixth Sense appends the played 6 to `ctx.destroyed` and Trading Card parks a `("destroy_card", card)` tuple, both resolved by the new `game._destroy_card()` which removes the card from deck/hand/spent for the rest of the run and fires Canio for face cards; **Blueprint/Brainstorm copy scope** now covers ALL hooks (discard/round-end/shop/booster/economy — the real game's copy is not scoring-only) via generated per-hook delegators with the recursion guard; **Negative edition grants a free joker slot** on both the `grant_joker` and shop-buy paths; **Blue Seal corrected to the reference doc §8** — it fires at ROUND END for a sealed card HELD in hand, granting the Planet of the FINAL hand played that round (not at play time, not the played hand's planet — wiki: "Creates the Planet card for final played poker hand of round if held in hand"). Tests: `test_trading_card_destroy_is_seeded_and_permanent`, `test_trading_card_uses_seeded_rng_not_module_random`, `test_sixth_sense_destroys_the_played_6`, `test_blueprint_copies_economy_hooks`, `test_blueprint_discard_hook_copy`, `test_negative_edition_does_not_consume_a_slot`, `test_blue_seal_grants_final_hand_planet_at_round_end`, `test_state_defaults_seed_initial_values`, `test_mutable_state_defaults_are_per_instance`.*
**Still open:**
- No mid-round reshuffle of the discard pile when the deck empties (real game recycles spent cards; the sim stops drawing). Rare at base config, matters after heavy deck thinning.

---

## 5. Recommended fix order before search/RL

**Economy/shop layer — DONE (2026-08-06).** A1–A6 all fixed (see `docs/M2-reference-audit.md`: M2 P0s, P1s #4–#12, P2 #13/#15).

**Scoring / joker-wiring track — DONE (2026-08-06, joker-fidelity program).** B1–B5 all fixed (§3–§4); remaining pre-training gaps are the B6 misc items + A5 below, plus the M2 P2 scope items.

1. **~~B1~~ [DONE 2026-08-06]** — Placeholder consumables resolved (real keys / object tuples via `game._grant_pending`); see §3.
2. **~~B2~~ [DONE 2026-08-06]** — All dead hooks dispatched from `game.py`/`shop.py` (`on_shop_enter/leave`, `on_reroll`, `on_booster_opened`, `on_init`, `on_planet_used`, `on_tarot_used`, `on_lucky_trigger`, `on_card_added`, `on_card_destroyed`, `on_booster_skipped`); `generate_shop` honors `free_planets`/`pending_shop_buff`; `buy_item` honors Credit Card debt.
3. **~~B3 + B4~~ [DONE 2026-08-06]** — Held-in-hand scoring pass (Steel, Mime, Baron, Blackboard, Shoot the Moon, Raised Fist) + Lucky odds corrected to 1/5 / 1/15 with Oops doubling and Lucky Cat wired.
4. **~~B5~~ [DONE 2026-08-06]** — Driver's License / Stone Joker / Glass Joker / Steel Joker full-deck counts.
5. **~~B6~~ [DONE 2026-08-06]** — Real destroys (Sixth Sense/Trading Card via `game._destroy_card`), Trading Card seeded RNG, Blueprint/Brainstorm full-hook copy, Negative slot, Blue Seal final-hand-at-round-end (reference doc §8). Remaining: mid-round reshuffle. **A5** — tag weights + edition-discovery gating (still open).
6. **M2 P2 scope** — stakes + stickers (#14, needs stake scope; sim locked to White Stake per spec) and Endless (#16).
7. Re-run the seed-exactness gate + golden pins after any change that touches draw order (the gate will catch drift).

Tracking: `tools/audit_diff_jokers.py` reproduces the A2/A6 diff (name-matched against balatro-rs); `tools/audit_jokers_static.py` (CI-wired) keeps the joker layer structurally clean; `tools/gen_joker_spec.py` regenerates the spec from the reference doc.
