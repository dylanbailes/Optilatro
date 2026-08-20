# M13 — Ante-1 Survival (minimize ante-1 deaths)

**Date:** 2026-08-20
**Status:** Design — awaiting approval
**Scope lock:** Red Deck / White Stake / antes 1–8, human-fair (composition only, no draw-order peek). Source of truth: `docs/reference/balatro-mechanics.md` (§1 Scoring, §2 Jokers, §6 Enhancements, §7 Editions, §8 Seals, §10 Boss Blinds, §16 Ante/Blind Rewards, §17 Shop Pricing/Weights).
**Baseline:** human-fair V9 `14/300=4.67%` wins, ante-1 deaths `32/300=10.7%` (best `268/300=89.3%` clear). Oracle ceiling `26/300=8.7%` deaths — remaining gap is shop offer + no-engine variance, not pure play. V10 farming `+31% econ_source` but win `+0.3pp @1000`.

## 1. Goal

Reduce ante-1 deaths to the oracle ceiling and below if possible. Success is **more runs reaching ante-4+**, measured on the same seed bank (`bench/bench_v9.py --games 300`, `rng_mode=seed`, seeds 0-299).

**Gates (per-seed paired vs `heuristic_v9` on same bank):**

* `ante1_deaths` strictly down (primary). Target `≤ 20/300` (≤6.7%) — beats best structure `32` and approaches oracle `26`. Stretch `≤ 15/300` if shop-value track delivers.
* `win_rate` non-regressing (secondary). Must be `≥ baseline` at both 300 and 1000 seeds within noise (±2pp at 300, ±1.5pp at 1000).
* Telemetry: `mean_econ_source`, `interest_collected` not sacrificed for survival (already +31% from V10 — hold).

Why ante-1 first: every ante-1 death removes a run from mid/late evaluation; ante-4/5 cliff (`15-17%` die each) cannot be measured until ante-1 is cleared.

## 2. Source-of-truth constraints

* **Blinds (§16, §0):** ante-1 targets `300 / 450 / 600` (Small 1x / Big 1.5x / Boss 2x). Exceptions `bl_needle 1x`, `bl_wall 4x`, `bl_violet 6x`, `bl_flint` halves scoring not target (`game.py:446`). Rewards flat `$3/$4/$5` (`$8` showdown) — ante-1 total cash `≈ $12` + interest.
* **Starting state (§0):** `$4`, `8` hand size, `4` hands / `3` discards (+1 Red Deck = `4` discards `game.py:270`), `5` Joker slots, `2` consumable slots.
* **Shop (§17):** Joker `20` / Tarot `4` / Planet `4` (Merchant `9.6` / Tycoon `32`), rarity `70/25/5`, edition `0.3/0.3/1.4/2%` (+Hone/Glow-Up quirk). Duplicate suppression without Showman (`shop.py:_draw_excluding`). Voucher persists until Boss (`shop.py:496` `offered_voucher`). Packs `4/2/0.5` etc. All pricing via `buy_cost = round_half_down(base+edition) * discount` (`§17`).
* **Jokers (§2):** Types Chips / +Mult / xMult / Economy. Activation timing `On Scored / On Held / Independent` matters for ante-1 chip jokers (e.g. `j_sly +50 Chips if contains Pair` — Independent, `j_greedy_joker +3 Mult per Diamond scored` — On Scored).
* **Seals (§8):** Gold `$3` scored, Blue planet of final hand held-at-end, Purple tarot on discard — already fixed (`scoring.py:86`, `game.py:_discard`). Wild/Stone gaps remain but not ante-1 drivers.

No new mechanics; only valuation/decision changes.

## 3. Root causes of ante-1 deaths (traced)

From `vendor/balatro-rl/results/` forensics (`highlights.jsonl`, `bench_human_fair`, `ante1_economy_2026-08-17`, `structure_discard`):

1. **No-engine shop offer:** `24/32` deaths hold `≤2` jokers at death blind. Shop offered Tarot/Planet when `j_sly/j_wily +50/100` was the win condition. `joker_value` blended `ceiling/typical` by `reach` but `buy_threshold 0.06` let `c_hermit 0.18` outrank flat chips in ante-1 where `$4→$8` is max gain.
2. **Over-chasing flush/straight:** `_structure_pool` fixed worst cases but still commits to `4-suit` flush when hand already contains a Pair that clears `300` with no chase. Gate `base < remaining` helps but `remaining` is post-score, not per-hand share — a `Pair 45` looks weak vs `Flush 35+15*2` promise.
3. **Cash hoarding failure is not the fix:** Ante-1 economy audit tried blanket `$5` floor `32→37` deaths, joker-exempt floor `→35`, reroll gate flat. Holding `$5` for interest costs a `+50 Chips` joker that is `16%` of Small. Issue is **which** cheap engine is bought, not saving.
4. **Boss scaling ignored in shop:** `bl_wall 4x` (`1200` at ante-1 Big) / `bl_violet 6x` at ante-1 never appears (min-ante 8) but `bl_club/goad/window` debuffs are not priced into flat-chip value.

## 4. Architecture — three bounded tracks, one milestone

All changes live in `vendor/balatro-rl/balatro_sim/agent_v9.py` + `agent_v10.py` (no `game.py`/`shop.py` churn, human-fair, `ci_gate` safe). `HeuristicV9` stays frozen as A/B baseline; work goes in `HeuristicV10` (+ `SearchShopV10` inherits).

### Track A — Ante-1 shop valuation bias (highest leverage)

**A1. Ante-aware `buy_threshold` + `lifecycle` override.** `PARAMS["buy_threshold"]` currently flat `0.06`. Replace with `buy_threshold_ante1` check in `_v10_rank_shop_items` (`agent_v10.py:402`): if `game.ante==1`, require `value ≥ 0.04` for flat Chips jokers (`j_sly/wily/clever/devious/crafty/odd_todd` etc.) but `≥0.08` for econ/tarot-gen (`ECONOMY_JOKERS`, `TAROTGEN_JOKERS`). Implements "chips first, economy later" without saving cash — still spends, just on the right archetype.

**A2. `econ_value` ante-1 discount.** In `agent_v9.py:1967 econ_value`, ante-1 `total = econ_per_ante * _remaining_antes` overvalues `j_golden $4/round` (`$28`/run) vs `j_sly +50` immediate clear. Add ante-1 factor `0.35` multiplier for `ECONOMY_JOKERS` when `game.ante==1` (still counted in `joker_value` but deprioritized vs chip snapshot). Reference: `§2` Economy type never scores ante-1.

**A3. Voucher discipline ante-1.** `VOUCHER_PRIORITY` already ranks `v_overstock 3 / v_seed_money 3` above paints. In `_v10_rank_shop_items`, gate vouchers ante-1 unless `game.jokers ≥1` and `ref.base_c ≥ 120` (can clear Small without engine). Prevents `v_seed_money $10` blocking a `$3 j_sly` when `$4` cash.

Files: `agent_v10.py:_v10_rank_shop_items`, `agent_v9.py:econ_value`, `lifecycle_bonus` (no change, just re-used).

### Track B — `P(clear)` + discard: stop burning hands, stop breaking pairs

**B1. Ante-1 `P(clear)` floor tuning.** `agent_v10.py:899 fresh=d*k_d + (h-1)*k_r` with `k_d=3` errs low for ante-1 where max discard `4` matters. For `ante==1`, use `k_d = min(5, pool_hand_size)` and `k_r = max(2, hs-4)` (conservative → realistic). Keeps `farm_spare_hands=1` so farming never triggers ante-1 (`P_clear(Hands-1) <0.90` on `300`), but `tier1_survive` no longer misclassifies `Pair 80` as `P_clear≈0.3`.

**B2. `_structure_pool` priority already `pairs > flush > straight` (`agent_v9.py:1177`) — add boss-debuff awareness.** When `_boss_effects_on` and `debuffed suit == chase suit`, demote flush chase: require `min_suit 5` not `4` for that suit (`game._boss_effects_on` + `current_blind.boss_key` `bl_goad` Spades etc. `§10`). Prevents `4 Hearts` chase vs `bl_head`.

**B3. `discard_hold_until_clear` keeps its `good_hand = best_score ≥ target*0.50` rule (`agent_v9.py:1760`) — add ante-1 `good_hand` tightening to `0.65` when `game.ante==1 && hands_left==2` (last-two-hands must play a near-clear). Stops `200/300 straight` hold that died `290/300`.

Files: `agent_v10.py:estimate_clear_probability_bounds`, `agent_v9.py:_structure_pool`, `agent_v9.py:decide_hand`.

### Track C — Sell/hold discipline (supports ante-1 but also fixes late `chips→xMult`)

Not primary for ante-1 gate but landed in same milestone to avoid re-A/B.

**C1. Ante-aware `worst_joker_idx` sell curve.** Current `agent_v9.py:2083` protects last `xMult`. Add `game.ante` slope: `flat chips` (`j_sly/crafty/odd_todd`) `sell_value *= (1 - 0.12* _run_progress)` after ante-4, while `XMULT_JOKERS` `* (0.7 + 0.3*_run_progress)`. Implemented in `deck_condition_bonus` + `lifecycle_bonus` already, but sell reads only `marginal` — fix by making `worst_joker_idx` use `joker_value` (full) not `best_play_score` marginal.

Files: `agent_v9.py:worst_joker_idx` → call `joker_value(game, key, edition, ref)` instead of `best_play_score(... exclude_joker=i)`.

## 5. Data flow

```
BLIND_SELECT → _preselect_next_boss → SHOP (Track A ranks with ante-1 bias)
  → SELECTING_HAND: scored_plays → P(clear) (B1) → structure_pool (B2) → tier1_survive
  → good_hand check (B3) → play else best_discard
  → SHOP again: _v10_rank_shop_items respects ante-1 econ discount (A2) + voucher gate (A3)
  → BOOSTER_OPEN: _v10_decide_booster unchanged (Standard pack card bias already via _reshape_card_bonus,
     but ante-1 it delegates to V9 when reshape inactive — no change)
```

All new params are `V10_PARAMS` overrides, default-off for `farm_clear_threshold=1.0` farm-off arm (byte-identical V9 for attribution, `agent_v10.py:213`).

## 6. New tunable params

| Param | Default | Track |
|---|---|---|
| `ante1_chip_bias` | `0.02` additive for Chips archetype ante-1 | A1 |
| `ante1_econ_discount` | `0.35` multiplier on `econ_value` ante-1 | A2 |
| `ante1_voucher_gate` | `True` | A3 |
| `ante1_kd_boost` | `True` (`k_d 3→5` ante-1) | B1 |
| `ante1_good_hand` | `0.65` (vs `0.50` baseline) | B3 |
| `sell_uses_full_value` | `True` | C1 |

All are `V10_PARAMS` so `--params '{"ante1_econ_discount": 1.0}'` isolates.

## 7. Testing & benchmarks

* **Unit:** `test_structure_pool` ante-1 pair-vs-flush, `test_ante1_buy_bias` (Sly outranks Hermit ante-1), `test_p_clear_ante1_kd`, `test_good_hand_65`. All order-independent (sorted keys).
* **Bench:** `python bench/bench_agent_v10.py --games 300 --policies heuristic_v9,heuristic_v10` on bank `0-299` (primary), plus `1000` (`0-999`) confirm. Report `ante1_deaths`, `win_rate`, `mean_ante`, `econ_source`, `interest` via `aggregate()` in `bench_agent_v10.py`. Success = gates in §1.
* **CI:** `python -m pytest vendor/balatro-rl/tests vendor/balatro-rl/balatro_sim/tests -q` + `test_seed_exactness.py -m ci_gate -v` + 4 audits `CLEAN`. No `game.py`/`shop.py` change → golden pins (`tests/test_seed_rng.py:TestSeedModeGolden`) unchanged.

## 8. Risks & non-goals

* Not fixing Wild/Stone gaps (`GAP-W/S`) — P2, separate helper sweep.
* Not touching tags `A5` — uniform weights stay.
* Not making L1 search differ — remains comparative mean-measure; human-fair L1 is next milestone.
* No Endless/Stakes — scope lock holds.

## 9. Rollout order

1. Track A (A1-A3) → A/B 300 → if ante-1 `≤25`, ship.
2. Track B (B1-B3) → A/B 300 → if `≤20`, ship; else revert.
3. Track C (C1) → A/B 1000 for `mean_ante` shift (ante-4/5 cliff).

Each track is independently revertible via its `V10_PARAMS` flag.

## 10. Open questions for reviewer

* Is ante-1 voucher gating (`A3`) too aggressive vs `v_overstock` (+1 shop slot) which does help ante-1 engine odds?
* Should `ante1_chip_bias` be additive or multiplicative on `joker_value` (current: additive `0.02` so it clears `buy_threshold` without distorting late-game ranking)?
