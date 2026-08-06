# M0 — Vendor Audit Report (balatro-rl sim)

**Date:** 2026-08-06
**Commit:** `59588ba` (shallow clone, `--depth 1`)
**Location:** `vendor/balatro-rl/`
**Python env:** `.venv` (Python 3.11.9; torch 2.13.0+cpu, numpy 2.4.6, gymnasium 1.3.0, pytest 9.1.1)

---

## 1. What was done

1. Cloned `taggarttufte/balatro-rl` into `vendor/balatro-rl/` (shallow, 49 MB — skips the huge checkpoints/logs).
2. Created `.venv` and installed `torch numpy gymnasium pytest`.
3. Ran the test suite per the README — note the README's path `balatro_sim/jokers/tests/` is **stale**; the real tests live in `tests/` + `balatro_sim/tests/`.
4. Verified coverage claims against actual code (Section 3).
5. Added `bench/bench_sim.py` — a reusable baseline benchmark (throughput + random win rate).

## 2. Test suite status

```
615 passed, 3 skipped in ~21s
```

- **3 skipped** = legacy V5 reward tests (`test_rewards_v5.py:62: Could not reach shop`). Non-core, ignorable.
- The suite exercises: hand evaluation (12 hand types incl. Flush Five/House, ace-low straight, wild/stone cards), card enhancements/editions/seals, joker scoring (flat/scaling/retrigger/multi-joker), planet levels, game state transitions, action masking, economy edge cases, and boss blinds (start / in-play / cleanup / pool).
- **Test-quality caveat:** several boss-blind tests are smoke tests ("just verify it doesn't crash" / weak invariants), and `test_win_transitions_to_shop` touches attributes (`gs.chips`, `gs.score_target`, action `"cash_out"`) that no longer exist in `game.py` — it passes because `ROUND_EVAL` → `_end_round()` runs regardless. Green suite ≠ full fidelity (see Section 4).

## 3. Verified coverage (from code, not the README)

| Component | Count | Notes |
|---|---|---|
| Jokers registered | 168 | `JOKER_REGISTRY` (includes aliases, e.g. `j_greedy` == `j_greedy_joker`) |
| Jokers sellable in shop | **144** | `JOKER_CATALOGUE` — the real allow-list surface; some entries are stubs/TODO (e.g. `j_chicot`/`j_matador` boss hooks were TODO in `mult.py`, implemented in `misc.py` — audit needed) |
| Planets | 12 | ✓ full |
| Tarots | 22 | ✓ full |
| Spectrals | 18 | ✓ full |
| Vouchers | 27 | ✓ full (`apply_voucher` wired into shop/game) |
| Boss blinds | 25 keys, **20 in pool** | Selection: `rng.choice(BOSS_BLINDS[:20])` — simplified (see 4.3) |
| Blind chip targets | ✓ | `BLIND_CHIPS` matches the real table (300 … 100,000) |
| Econ constants | ✓ | $4 start, $1/5 interest capped at $5, $1/hand payout, 4 hands / 3 discards / 8-card hand |

**Throughput baseline (single env, random agent, Ryzen 7 2700):**
```
~2,135 steps/s
random-agent win rate: 0/1000 = 0.00% (max ante reached: 3)
```
Matches the repo's "<0.01%" random baseline. Earlier `~2,992 steps/s` / `0/200` was measured pre-tags/vouchers; the env is now ~2.1–2.5k sps with the full ruleset wired.

**Random-agent baseline with the FULL ruleset (2026-08-06, `bench/bench_sim.py --games 1000`)** — all 32 vouchers, all 24 tags, all 28 bosses live:
```
throughput:           2,135 steps/s (single env, random agent)
random-agent win rate: 0/1000 = 0.00%  (losses: 1000, in 52.8s)
death by ante (9 = won past ante 8):
  ante 1:   960 (96.00%)
  ante 2:    38 ( 3.80%)
  ante 3:     2 ( 0.20%)
```
Sanity: across 60 random games the sim exercised SHOP state 3,117×, rolled a tag 5,995×, offered a voucher 5,736×, and hit a Boss blind 1,274× — the full ruleset is reachable and live in random play. Win detection verified (`g.ante > 8` on GAME_OVER; the ante-8 → ante-9 shop transition is the win path). A uniform-random policy over the 47-action space stalls at the ante-1 small blind (96%) — it cannot reliably score 300 chips with random plays. This 0.00% is the floor to beat; the search agent (Tier 1) is the first real target above it.

## 4. Fidelity gaps found (this is the real M0 value)

These are the concrete discrepancies to fix in **M1** before any win-rate number is trusted.

### 4.1 ~~[P0]~~ **[FIXED 2026-08-06]** The deck is rebuilt from scratch at the start of every blind
`_start_blind()` → `_init_deck()` → `make_standard_deck()` + shuffle. Nothing carried over between blinds:
- Tarot enhancements on cards that return to the deck → **lost**
- Standard-pack card additions → **lost**
- Deck thinning (Hanged Man, immolate targets, etc.) → **lost**

**Fix applied to `balatro_sim/game.py`:** the deck is now created once per run and persists across blinds. Cards played/discarded go to a new `game.spent` pile (not redrawn mid-round) and are returned to the deck — along with any cards still held — at the start of the next blind; destroyed cards (Hanged Man, Immolate, spectral destroys via `_remove_card`) are removed from hand/deck and stay gone permanently. `Cloud 9` (`deck_nines`) now counts the full alive pool. Also fixed a follow-on bug the review caught: boss-blind debuffs leaked through the `spent` pile — `_undo_boss_debuffs` now clears `deck + hand + spent` so debuffed played cards don't stay debuffed into later blinds. **Regression tests added** in `tests/test_deck_persistence.py` (7 tests: pool size constant across blinds, played/discarded cards return, enhanced cards persist, destroyed cards stay gone, no mid-round redraw, boss debuffs don't persist via spent). Full suite: **622 passed** (was 615).

### 4.2 [P0] RNG was a single stream — now a two-mode interface (2026-08-06)
`BalatroGame` previously used one global stream for everything. `balatro_sim/seed_rng.py` now ports balatro-seed's per-node LuaRandom scheme (verified byte-accurate against the real game) behind `rng_mode="generic"| "seed"`:
- **generic (default):** one shared `random.Random` stream — byte-identical to the legacy sim for the game-state backbone (deck shuffle, boss, in-round effects). **Shop changed though:** it now draws from the game stream (was unseeded module `random`) and rarity uses the real 70/25/5 thresholds (was weighted 70/20/8/2; real shops never roll legendaries — The Soul only).
- **seed:** per-node LuaRandom (`SeedSource`). Every decision reseeds a FRESH `LuaRandom` from a hash of `(node_id, run_seed)`, and the node's cached value advances on every access (that advance is the real reroll mechanism). Node IDs match Balatro's real strings where balatro-seed pins them: `boss`, `cdt{ante}`, `rarity{ante}{source}`, `edi{source}{ante}`, `Joker{1|2|3}{source}{ante}` (**`Joker4` has no suffix**), `Tarot/Planet/Spectral{source}{ante}`, `Voucher{ante}`, `Tag{ante}`, `shop_pack{ante}`, `stdset{ante}`, with real sources `sho` (shop), `buf` (buffoon pack), `ar1`/`pl1`/`spe` (arcana/celestial/spectral packs). Sources balatro-seed doesn't model use sim-internal keys (`shuffle`, `wheel`, `crimson`, `bell`, `hook`, `madness`, `amber`, `purple_seal`) — deterministic per seed but not byte-exact vs the real game.

**Wiring status (2026-08-06):**

| Consumer | Status |
|---|---|
| Boss selection (`boss` node) | ✅ real node |
| Deck shuffle / opening draw | ✅ sim-internal `shuffle` |
| Shop (joker rarity+pick, edition, consumable type+pick, voucher, pack type+contents) | ✅ real node strings |
| In-round boss effects (wheel/mark/house flips, crimson, bell, hook, madness, purple seal) | ✅ sim-internal keys |
| Joker probability triggers (`jokers/*.py`, ~21 sites) | ✅ per-node `chance` node via `JokerInstance.chance()` |
| Consumable/spectral effects (`consumables.py`, ~15 sites) | ✅ per-node `chance` node |
| `scoring.py` Lucky card (2 sites) | ✅ per-node `chance` node via `ctx.game` |

**All consumers wired (2026-08-06)** — a seed-mode run now replays deterministically end-to-end (regression: `tests/test_seed_rng.py::TestReplayDeterminism`: full-run 2,000-step replay, joker trigger, consumable). Created jokers must carry `game=` (`JokerInstance(key, game=g)`) or their triggers fall back to module random. The remaining fidelity gap is not determinism but byte-exactness vs the real game: probability triggers use the sim-internal `chance` node (balatro-seed doesn't pin those call sites), and the shop/pack loop still differs structurally from real Balatro's. Seed normalization matches balatro-seed's explore CLI (uppercase, `0`→`O`); an int seed containing 0 (e.g. 10 → "1O") is silently rewritten.

### 4.3 [P1] Boss blind coverage was partial and selection is wrong — effects now implemented (2026-08-06)
- **Selection — now real (2026-08-06):** `_select_boss()` in `game.py` implements the real rules, verified against balatrowiki.org/w/Blinds_and_Antes: minimum-ante eligibility (`BOSS_MIN_ANTE` covers all 28 real bosses), the ante-8 Showdown pool (`SHOWDOWN_BOSSES` = amber/verdant/violet/crimson/cerulean, only at ante 8/16/24), the "fewest appearances" no-repeat rotation (`boss_appearances` — a boss can't reappear until every eligible boss has appeared once), and stable per-seed drawing (sorted candidates + `self.rng.node("boss")`, the real `boss` RNG node). **All 28 real bosses are now selectable (2026-08-06)** — `UNIMPLEMENTED_BOSSES` is empty after The Club, The Wheel, The House, and The Arm gained real effects. `bl_violet`/`bl_crimson` are reachable at ante 8. Also fixed a pre-existing effect bug: **The Goad debuffs Spades, not Clubs**. Tests: `tests/test_boss_selection.py` (18: eligibility, showdown pool, exclusions, rotation, determinism, full-run integration).
- **Implemented start effects:** manacle, needle, water, goad, window, head, plant, fish, psychic, **verdant, pillar, cerulean, amber, crimson, club** (all Clubs debuffed).
- **Implemented in-play (added 2026-08-06):** **wall** (4x base), **violet vessel** (6x base), **mark** (face cards drawn face-down; obs-masked in env_sim/env_v7), **ox** (most-played hand this run sets $0 — High Card default tie-break), **cerulean bell** (forced card auto-added to every played hand, re-picked on play/discard), **crimson heart** (one random joker disabled per hand, no immediate repeat), **wheel** (1-in-7 cards drawn face-down incl. opening hand; obs-masked), hook, eye, mouth, tooth, serpent, flint.
- **Fixed approximations:** `bl_flint` now halves **base chips and mult** in `score_hand` (`half_base`) before jokers (was "halve final score" — very different in real builds). `bl_eye`/`bl_mouth` corrected to the real-game rule: a disallowed hand is **still played and wastes a hand but scores 0** ("Not allowed!") and does **not** count as that hand type for the round's restriction — verified against balatrowiki. (The original M0 note claiming the real game "refuses the play without consuming a hand" was wrong; the wiki is explicit that rejections waste the hand.) This also removed a random-agent stall: previously, rejection cost nothing, so a policy could exhaust all hand types under The Eye and loop forever.
- **Edge-case bug found & fixed during this work:** the `rejected` flag was built with bare `and`/`or`, which return *operands* — the empty `played_hand_types_this_round` set (a falsy operand) leaked into the flag, then flipped truthy after the `.add()` mutation, silently zeroing the score of a legal first hand. Wrapped in `bool(...)`. **Regression tests** in `tests/test_boss_effects.py` (25 tests) + obs-dim updates: env_sim 413, env_v7 445 (was 434), env_mp 449 (was 438) for the 15→26 boss one-hot. Full suite: **647 passed** (was 622).
- **Boss coverage complete (2026-08-06)** — all 28 real bosses have real effects and are selectable; `UNIMPLEMENTED_BOSSES` is empty. Final two: **The House** (`bl_house`, ante 2 — the opening hand is dealt face-down, revealed on play, unflipped at round end) and **The Arm** (`bl_grim`, ante 2 — permanently decrements the played hand type's planet level by 1, floored at 1, applied *before* scoring). **The Club** (all Clubs debuffed) and **The Wheel** (1-in-7 face-down) landed earlier in this pass — the ante-1 pool is the full real 8/8. The obs boss one-hot is 28: env_sim **415**, env_v7 **447**, env_mp **451**. Full suite: **681 passed** (was 670). Tests: `tests/test_boss_effects.py` (41).
- **Missing boss mechanics referenced by jokers:** `j_chicot`/`j_matador`/`j_luchador`/`j_ring_master` need boss hooks (`on_boss_ability_triggered`, boss reroll) — partial wiring in `misc.py`.

### 4.4 ~~[P1]~~ **[FIXED 2026-08-06]** Deck/stake configuration — Red Deck wired
`BalatroGame(deck="red"|"white")` (default **red**, the spec lock): Red Deck gives +1 discard per round (`base_discards = STARTING_DISCARDS + 1`); `deck="white"` = base 3. Obs normalization already used `base_discards`, so it adapts automatically. White Stake is the only stake modeled (no stake scaling needed for v1). Phase 0 regression: `tests/test_phase0.py::TestRedDeck`.

### 4.5 ~~[P2]~~ **[FIXED 2026-08-06]** Skip blind — all 24 real tags implemented
`balatro_sim/tags.py` implements the full real tag set. `roll_tag` draws the offered tag per non-Boss blind on the real `Tag{ante}` RNG node (one weighted `pseudorandom_element` draw; uniform weights for now — the real game discovery-gates the edition tags and has a few non-uniform weights, tracked in `TAG_WEIGHTS` for later balatro-seed alignment). 9 tags are ante-gated (weight 0 at ante 1). Tags auto-apply at skip (`_skip_blind`): **economy** (double money, cap $40), **speed** ($5 × skipped blinds this run), **garbage/handy** (run counters for unused discards / played hands), **investment** (+$25 after defeating the next Boss), **coupon** (next shop's cards/packs free, vouchers excluded), **D6** (next shop rerolls start at $0), **uncommon/rare** (free joker of that rarity), **foil/holo/poly/negative** (free edition joker), **voucher** (+1 voucher slot next shop), **boss** (rerolls the next Boss via `_select_boss(exclude=)`, no-repeat rotation preserved), **juggle** (+3 hand size next round only), **orbital** (+3 levels to the highest-leveled hand), **top-up** (up to 2 Common jokers), **double** (copies the next tag — a doubled *pack* tag grants BOTH packs via a `pending_packs` queue resolved between booster picks), and the 5 **free-pack tags** (charm/buffoon/ethereal/meteor/standard → open a booster, then enter the skipped blind's shop; tag-only Mega Buffoon/Standard packs kept out of the shop pool so the shop RNG distribution is unchanged). Also fixed a latent bug: buying a booster now transitions to `BOOSTER_OPEN` (pack picks were previously unreachable — `booster_choices` filled but state never changed). Obs +29 features (24 offered/claimed-tag one-hot + 5 pending-tag scalars): env_sim **444**, env_v7 **476**, env_mp **480**. Tests: `tests/test_tags.py` (38; incl. doubled-pack regression + seed-determinism). Full suite: **785 passed**.

### 4.6 [P2] Test-suite gaps
- **Cross-process seed-exactness gate (2026-08-06)** — `tests/test_seed_exactness.py` (4 tests, marker `ci_gate`) proves the seed-mode draw-log sha256 is byte-identical across separate interpreter instances under different `PYTHONHASHSEED` values (incl. `random`); verified stable, and the gate discriminates seeds/steps. Opt-in so local dev stays fast: `python -m pytest tests/test_seed_exactness.py -m ci_gate` (deselected by default via `pytest.ini` `addopts = -m "not ci_gate"`). Full suite: **726 passed, 3 skipped, 4 deselected**.
- Boss effect tests now exist for every boss incl. wall/violet/mark/verdant/pillar/ox/cerulean/amber/crimson/flint/eye/mouth/club/wheel/house/arm (`tests/test_boss_effects.py`, 41 tests; obs masking included). Some pre-existing vendored boss tests remain weak smoke tests ("doesn't crash").
- Real boss-blind *selection* tests exist (`tests/test_boss_selection.py`, 18 tests: min-ante eligibility, ante-8 Showdown pool, empty allow-list, fewest-appearances rotation + restart, seed determinism, full-run integration).

### 4.7 ~~[P2]~~ **[FIXED 2026-08-06]** Vouchers — full 32-voucher set implemented
All 11 buyable no-ops now have real effects and the 5 missing vouchers are in the catalogue (**32 total**, 15 base→upgrade pairs via `VOUCHER_BASE`). Verified against balatrowiki.org/w/Vouchers:
- **Hone / Glow Up**: 2x / 4x Foil+Holo odds in the shop (`_roll_edition` boost; Polychrome gets the real 3x/7x quirk).
- **Tarot/Planet Merchant** (2x) and **Tycoon** (4x) shift the shop card-slot weights (`_consumable_weights`, multiplicative).
- **Magic Trick** adds playing-card items to shop card slots ($4, buy → added to the run deck); **Illusion** adds enhancement/edition to those cards (seals bugged off, matching the real game).
- **Omen Globe**: 20% chance each Arcana-Pack Tarot is replaced by a Spectral.
- **Telescope**: Celestial Packs always contain the most-played hand's Planet (higher-tier tie-break).
- **Observatory**: Planet cards in the consumable area give X1.5 Mult for their hand (`score_hand`).
- **Seed Money / Money Tree**: interest cap $10 / $20 (`game.interest_cap`).
- **Blank**: does nothing (unlocks Antimatter via the pair rule); **Antimatter**: +1 joker slot.
- **Director's Cut / Retcon**: `reroll_boss` shop action — $10, Director's Cut 1x/Ante, Retcon unlimited; no-repeat rotation preserved, Wall/Violet rescale the blind target. env_sim action 46, env_v7 phase action 17.
- **Pair-unlock rule**: upgraded vouchers only appear after the base is owned (initial pool = 17 bases/standalones, was 27) — this re-mapped the golden shop pin's voucher draw (v_paint_brush → v_seed_money; all non-voucher draws verified unchanged).
- **Drive-by fixes**: Director's Cut no longer grants +1 free shop reroll (it never did in the real game); Petroglyph now also −1 discard per round (was missing).
Obs vouchers 27→32 (+5 dims): env_sim **449**, env_v7 **481**, env_mp **485**. Tests: `tests/test_vouchers.py` (28). Full suite: **818 passed**. Known approximations: shop packs stay uniformly weighted (Tycoon/Telescope pack-odds half not modeled — only pack *contents*); Hone/Glow Up apply to shop jokers only; `dc_reroll_ante` (Director's Cut spent-this-ante) is not in the obs (hidden state the agent infers).

## 5. What this means for M1 (updated plan items)

1. **Persistent deck state** — the single most important fidelity fix. Cards return to deck at round end (played cards are spent, held cards return), deck composition carries across blinds. This enables the deck-strategy dimension the whole project depends on.
2. **Port balatro-seed's per-node LuaRandom — DONE (2026-08-06), plus replay-diff harness:** `seed_rng.py` ports the full scheme (pseudohash/round13/LuaRandom/per-node cache) behind `rng_mode="generic"|"seed"`; every consumer (boss, deck, shop, in-round effects, joker triggers, consumables, scoring) routes through the source (see 4.2 wiring table) — full-run seed-mode replay is deterministic (`TestReplayDeterminism`). `balatro_sim/replay.py` is the **replay-diff harness**: `SeedSource.enable_tracing()` records every per-node draw `(node, value, method, result)`, and `capture_game`/`ReplayDiff`/`log_sha` diff two runs bit-for-bit (`python -m balatro_sim.replay --seed N --steps M`; tests `tests/test_replay.py`). This gates byte-exactness: any consumer that stops routing through the source shows up as the first divergent draw in the report. **Cross-process gate (2026-08-06):** `tests/test_seed_exactness.py` (`-m ci_gate`) spawns fresh interpreter instances via `python -m balatro_sim.replay --sha` (the CLI's new single-run fingerprint mode) under varying `PYTHONHASHSEED` and asserts the draw-log sha256 + run summary are byte-identical — pinning the fingerprint stable across CI runs and machines. Run: `python -m pytest tests/test_seed_exactness.py -m ci_gate`.
3. **Boss blind selection — DONE (2026-08-06):** real selection (`_select_boss()`: min-ante eligibility, no-repeat rotation, ante-8 Showdown pool) driven from `self.rng`, and all 28 bosses have real effects (last: The House, The Arm). Remaining boss-adjacent work: the boss-hook jokers (chicot/matador/luchador/ring_master) — see item 5.
4. **Deck/stake config — DONE (2026-08-06):** Red Deck (+1 discard) wired as `BalatroGame(deck=...)`, default red (see 4.4).
5. **Joker audit — Phase 0 done (2026-08-06):** all 144 catalogue entries now resolve to registered effects (**zero dead shop jokers** — was j_supernova + j_oops). Fixed: **Supernova** registered with its real effect (+Mult per run-play-count of the played hand); **Oops! All 6s** registered under its catalogue key (`j_oops`, was buyable-but-dead); **Ring Master** corrected to real "Showman" semantics (duplicates already the sim default — the old "reroll boss" implementation was not a real Balatro joker). **Boss-hook jokers wired in game.py:** Chicot disables ALL boss abilities by presence (`_boss_effects_on()`); Luchador's sell sets a game-level `boss_disabled_override` (survives the sale, consumed when the boss blind resolves); Matador earns +$8 per ability trigger (`_fire_boss_trigger()` — at blind start for static bosses, per hand for Crimson Heart/Cerulean Bell/The Hook). **Glass shatter implemented** (1-in-4 per scored Glass card, doubled by Oops; shattered cards destroyed permanently). Regression: `tests/test_phase0.py` (21 tests).
6. **Strengthen tests:** replace smoke boss tests with exact-value tests; add a deck-persistence test; keep `bench/bench_sim.py` as the regression gate. Baseline moved to **~2,450 steps/s** after Phase 1 (2026-08-06) — the drop from ~3,000 is the now-functional booster flow + tag draws doing real work per step (obs encode is only 71µs; the tag block is negligible). Heavy training throughput targets the Rust core, not this env.

## 6. Open items (unchanged from spec)

- No Balatro version string is recorded anywhere in the repo (mod `metadata.json` says 0.1.0 — that's the mod, not the game). The pin target remains "whatever balatro-rl was tested against" — to be recorded when the live-mod phase (M5) starts.
- Licensing: balatro-rl has **no LICENSE file** (verified). Vendoring locally for research is fine; distributing the vendored code requires contacting the maintainer.
