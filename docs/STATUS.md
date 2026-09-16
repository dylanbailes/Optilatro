# Status

Last reviewed: 2026-08-20 (docs/layout pass). Numbers below are **recorded**
results from the 2026-08 working log — re-measure before citing a new paper
or comparing a new policy.

## Scope lock

Red Deck, White Stake, antes 1–8, no Endless. Human-fair evaluation.

## Pipeline (from [spec.md](spec.md))

| Milestone | Intent | State |
|---|---|---|
| M0 | Vendor sim, tests, bench floor | **Done** |
| M1 | Fidelity + per-node RNG + replay | **Done** (A5 still open) |
| M2 | Economy/shop vs reference sheet | **Done** except P2 #14 stakes, #16 Endless |
| M3–M6 (spec) | Exact solver, Gumbel MCTS, learning, live mod | **Superseded** by the V9/V10 search-first track |
| V9 L0/L1 | Heuristic + shop search | **Done** (human-fair pivot later) |
| V10 | In-blind survive/value hierarchy | **Done**; knobs confirmed |
| V11 | Multi-item sequences + copy ordering + MLP value net | **Done**; paired A/B approved on seeds 10500–10799 |

## Headline numbers (do not mix banks)

| What | Result | Notes |
|---|---|---|
| Random floor | 2/2000 = **0.10%** | `bench/bench_sim.py`, post-M2 |
| V7 PPO (upstream) | **2.35%** | Prior-art ceiling; not reproduced here |
| V9 heuristic, pre-human-fair | ~11% @ 300 | Used exact draw order — **not** a current bench |
| V9 heuristic, human-fair | **6.00%** @ 300 then later **4.67%** after structure rules | Same bank 0–299; stream diverges when discards change |
| V9 search + lookahead (oracle) | up to **23.33%** @ 300 | Research-only; not human-fair |
| V10 heuristic vs V9 | **5.00%** vs 3.67% @ 300; **4.40%** vs farm-off @ 1000 | Farm-off == V9 byte-for-byte |
| `search_shop_v10` (new default baseline) | **10.67%** @ 300 (Seeds 10200–10499) vs V9 **3.67%** | Strict human-fair. +21 wins (+190.9%), -20 ante-1 deaths (-69.0%). Baseline file: `results/default_baseline_v10.json` |
| `search_shop_v11` (V11 Architecture) | **14.00%** (42/300) on Seeds 10500–10799 | Matches V10 (14.00%) with 41 concordant wins, 10 ante-1 deaths (3.33%), zero regression, verified APPROVE |


Ante-1 clear on the structure-discard bank: human-fair ~89%, lookahead oracle
~91%. Remaining ante-1 deaths are mostly shop-RNG / no-joker, not discard
policy.

## Closed (do not reopen without a failing test)

- Persistent deck + mid-round reshuffle
- Per-node LuaRandom + cross-process `ci_gate`
- All 28 bosses, 32 vouchers, 24 tags, 150 catalogue jokers
- Shop structure (cdt 20/4/4, Showman, first-shop Buffoon, pack weights)
- Joker-layer architecture (R1–R8) and consumable/boss/tag static audits
- Seal timing: Gold on score, Purple on discard, Blue × Mime, Red held retrigger
- Human-fair discard EV and comparative shop search
- V10 farm knobs at spec defaults (`0.90` / `0.75` / spare `1`)

## Open

| ID | Item | Why it is still open |
|---|---|---|
| A5 | Tag weights + edition-discovery gating | `TAG_WEIGHTS` is still uniform |
| M2 #14 | Stakes + stickers | Out of v1 scope (White Stake lock) |
| M2 #16 | Endless | Out of v1 scope |
| GAP-W | Wild × suit-jokers | `card.suit == X` misses Wild |
| GAP-S | Stone × rank/suit-jokers | Stone still exposes rank/suit |
| — | Deck-reshaping loop | Tarots/packs should build toward a bought engine |
| — | Human-fair L1 ≠ L0 | Comparative search currently matches L0 byte-for-byte |
| — | Live-game verification (spec M5) | Not started |
| — | Balatro version pin | Never recorded in the vendored tree |

## 2026-08-23 — goal loop iter 3: fresh-bank validation + <1% feasibility

Extending iter-2's tuning to fresh banks exposed **bank overfitting**: the
0-199-tuned config does not transfer (seeds 300-499 defaults 7W/18D vs
tuned 4W/18D). Combined 300-seed paired run (seeds 0-299):

| config | wins | ante-1 deaths |
|---|---|---|
| tuned (`chip_bias .8, early_struct 2, ante2_bias .5, farm_rate .75`) | **20 (6.67%)** | **18 (6.00%)** |
| defaults | 17 (5.67%) | 30 (10.00%) |

Tuned wins on both metrics paired (+3 wins, -12 deaths), artifacts
`results/goal_final_tuned.json` / `goal_final_defaults.json`. But the
<1%-deaths goal is **not reachable** with composition-legal heuristics:
~25 measured arms put the floor at ~4.5% (dev bank) / ~6% (300 seeds).
A beam-search solver (`tools/diag_solve.py`) clears 13/13 fatal ante-1
blinds, but only via multi-step search over the true draw order — illegal
for default policies; 1-ply composition-legal surrogates (P(clear) picker,
Monte-Carlo picker, endgame switches) all measured flat or worse.
New dormant knobs this round: `pclear_pick_ante`, `mc_pick_ante`,
`ante1_reroll_reserve`, `ante1_celestial_bonus`, `ante1_first_joker_thr`,
`farm_rate_share` (the last one is in the winning config). Manacle boards
(-1 hand size) now demote run/suit chases to pair-based discards at
ante <= 2. Next real lever: a learned, calibrated value model trained on
rollout outcomes — heuristic weights are exhausted.

## 2026-08-24 — goal loop iter 3 addendum: sampled-lookahead picker (failed)

Built the authorized new decision branch: `_v10_sampled_pick` — for each
candidate action on a marginal early blind, run policy continuations on
forks whose future draws are replaced with composition-sampled synthetic
shuffles (throwaway RNG, human-fair; fires once per blind when the linear
projection is behind). Mechanically sound, but measured **net-negative in
every configuration**: 9W/46D (greedy continuations), 11W/11D and 11W/10D
(policy continuations, margin 1.4/1.0). The smoothed futures mis-rank
openings: rerouting the opening costs more wins than it saves deaths.
Knob stays dormant (`sampled_pick_ante: 0`). Best verified config remains
iter-2 + `farm_rate_share: 0.75` (16W/9D @ 0-199; 20W/18D @ 0-299 paired
vs defaults 17W/30D). The remaining ante-1 deaths need either true-draw
lookahead (forbidden) or a learned policy trained on rollout outcomes.

## 2026-08-24 — goal loop iter 4: Manacle-scoped sampled picker (+EV)

Scoping the sampled-lookahead picker to **The Manacle boards only**
(`sampled_pick_manacle_only: true`) turned it net-positive: seeds 0-199
**16W (8.00%) / 6 ante-1 deaths (3.00%)** — best verified dev-bank result
(`results/goal_iter4_best.json`). 300-seed final (0-299): **20W (6.67%) /
15D (5.00%)** (`results/goal_iter4_300.json`) vs defaults 17W/30D — same
wins, half the default ante-1 deaths.

Fresh-bank check (300-399): 3W/10D ≈ defaults — the absolute gates
(<1% deaths, >7% wins) are still NOT met out-of-sample; bank variance
dominates at n<=200. Picker design notes: fires once per blind at the
opening when the linear projection is behind; candidates include planet/
tarot use; continuations ride the real cascade; reentrancy-guarded.
Extensions that measured WORSE and stay off: endgame refire, non-Boss
scope, greedy continuations, unscoped firing.

## 2026-08-24 — iter 4 addendum: boss-scope widening measured worse

Widening `sampled_pick_bosses` to Club/Hook/Window/Wall (keeping Manacle)
flipped 300-seed results to 18W/16D vs **20W/15D Manacle-only** — the
extra coverage churns winning openings on seeds 200-299. Manacle-only
scoping stays the shipped configuration; `goal_iter4_300.json` remains
the best 300-seed artifact.

## 2026-08-24 — iter 5: learned clear-model branch (built, integrated, measured)

The authorized predictor branch is now in the tree:
- `tools/gen_clear_dataset.py` — logs composition-only features + blind
  outcome at every ante<=2 decision across rollout banks.
- `tools/fit_clear_model.py` — numpy L2 logistic fit; holdout AUC **0.931**,
  acc 96.3% on ~1.8k decisions; weights ship as
  `balatro_sim/clear_model.json`.
- `_model_clear_prob()` + `model_gate` / `model_pick_below` /
  `model_farm_floor` / `model_scope_widen` knobs in agent_v10.

Measured integrations (0-199): model-gated farming floor → 9W/6D (worse —
blocks profitable farming); model-widened picker scope → 9W/6D (worse).
The calibrated model separates doomed states well (AUC .93) but its
decisions still lose to the tuned cascade's: knowing doom ≠ having the
chips to escape it. Best config remains iter-4's Manacle-scoped picker
(16W/8% @0-199; 20W/15D @300). All knobs default off; tree is
baseline-identical without params.

## 2026-08-24 — iter 5 addendum: Bellatro-101 dig doctrine (worse, dormant)

`ante1_dig_discards` (spend every ante-1 discard digging before any
non-clearing play, per the round-1 expert doctrine) measured 13W/10D vs
16W/6D — blanket digging burns discards on boards where playing the held
hand was correct. Dormant by default. The expert rules that DID map to
wins are already encoded: cheapest-clearing plays, flush-priority
structure chase, farm-rate sanity, Manacle-scoped sampled search.

## 2026-08-24 — iter 6/7: scoring-aware tarot deployment, engineless-shop
## urgency, joker-type chase

Three expert-guided branches built and measured (all human-fair):

- **`enhance_into_play_ante`** — mid-blind Empress/Hierophant/Lovers target
  cards INSIDE the top plays, chosen by engine-scored argmax
  (`_v10_scoring_enhance_targets`). Required hoisting the branch above the
  reshape-active gate (early blinds have inactive reshape targets). Paired
  0-99: 6W/2D vs baseline 7W/2D — net negative, stays off.
  `hold_enh_for_blind` (hold these tarots through the shop, deploy mid-blind)
  measured worse still (5W/2D). Probe (`tools/probe_enh_targets.py`) showed
  19/20 of these tarots burn in-shop before any blind — but forcing blind-time
  deployment loses more than it saves.
- **`engineless_urgency_ante`** — when NO owned joker moves a real score
  (>2% of reference ceiling, `_has_scoring_joker`), ante<=2 shops boost
  chips/xmult/retrigger values and discount economy junk like ante-1 does.
  Never worse on any bank tested; **new best 300-seed artifact**:
  20W (6.67%) / **14D (4.67%)** paired vs 20W/15D baseline
  (`results/goal_iter7_final_D.json`; zero per-seed regressions).
- **`joker_type_chase_ante`** — when a hand-type joker's type (Family→FoK,
  Tribe→Flush...) is not assembled, commit discards to a STRONG partial
  (3+ trips / 4-suit / 4-run) instead of generic EV, never over a good hand.
  The loose version (2+ partials) won 0-99 (+2W) but regressed fresh banks;
  the tightened version is neutral-to-positive. Combined loose config cost
  1 death on 0-299, so the shipped config keeps it OFF by default.

Final 300-seed paired verification (0-299): baseline 20W/15D,
both-knobs 20W/16D, **D-only 20W/14D** — D-only is the verified-best
configuration. The absolute gates (>=7% wins, <1% ante-1 deaths) remain
unmet; the composition-legal heuristic plateau stands at ~6.7%/4.7%.
Fresh-bank checks (500-599, 600-699) again showed dev-bank win gains do not
transfer; only the death-side improvement did. Full suite green (1562
passed), ci_gate green.

## 2026-08-24 — iter 8 (goal loop 2): evaluation-correctness audit + picker
## widening

Steering-driven audit of the play oracle (`tools/diag_topplay_miss.py`):
brute-forcing all C(n,1..5) combos against `scored_plays` found the
priority-pruned window missing the TRUE best engine-scored play in 100
decision points over 12 seeds (median gap 760 chips, max 23k) — retrigger /
enhancement engines (Hanging Chad, Scholar, Photograph, Greedy) make
SINGLE-card High Card lines outscore whole flushes, and 1-card combos are
priority-0 so they never reach the window.

Fix: `singles_window` knob injects valid 1-card combos into the scoring
window (`agent_v9.scored_plays`, gated farm<1.0 so V9 baseline stays
byte-identical). Verified: seed-4 misses drop to 5 residual Psychic-boss
edge cases. Outcome on 300 seeds: **20W/14D — identical to D-only**
(1 win flip each way = noise). Kept default-off (adds ~15% runtime for no
gate movement); the correctness fix matters for future learned policies
that consume `scored_plays`.

Also this round, both rejected:
- `sampled_pick_other_margin=1.0` (strict-margin doomed-board widening of
  the sampled picker to all bosses): 7W/**3D** on 0-99 vs D-only 7W/1D —
  the widened search re-ranks openings on boards where the held line was
  right. Off.
- `ante1_planet_main=true`: exactly neutral (7W/1D). Stays off.

Best verified configuration remains iter-7 D-only:
`{"ante1_chip_bias": 0.8, "early_struct_ante": 2, "ante2_chip_bias": 0.5,
"farm_rate_share": 0.75, "sampled_pick_ante": 2,
"sampled_pick_manacle_only": true, "engineless_urgency_ante": 2}`
→ 20W (6.67%) / 14D (4.67%) @ 0-299. Gates (>=7% / <1%) unmet.

## What not to try again

Recorded as flat or worse, with archives under `vendor/balatro-rl/results/`:

- Ante-1 interest floors / reroll gates (underpowered runs)
- Discard-EV v2 (top-K, flush bonus, target-aware gamble)
- Raising `tier2_min_value` above 0
- More PPO / self-play / dual play-shop networks (upstream V5–V8)
- Scoring-aware enhancement targeting + hold-into-blind (`enhance_into_play_ante`,
  `hold_enh_for_blind`) — paired negative on 0-99
- `search_shop_v10` on the goal banks — byte-equal to heuristic_v10 (L1==L0)

## 2026-08-23 — 200-seed goal benchmark (goal loop iter 2)

`heuristic_v10 --params '{"ante1_chip_bias": 0.8, "early_struct_ante": 2,
"ante2_chip_bias": 0.5}'` on seeds 0–199 (human-fair, seed mode):
**15 wins (7.50%) / 9 ante-1 deaths (4.50%)** — meets the >7% win and
<5% ante-1-death gates. Artifact:
`vendor/balatro-rl/results/goal_iter2.json`.

What moved the needle:

- `ante1_chip_bias` 0.35 → 0.8: +3 wins (ante-1 shops rank chip jokers
  harder; plateau at 0.8).
- `early_struct_ante: 2` (+ `early_struct_min_run/suit: 3`): loosens the
  straight/flush chase triggers on antes 1–2 only — 13 → 9 ante-1 deaths.
  Motivated by a beam-search solver (`tools/diag_solve.py`) clearing
  **13/13** fatal ante-1 blinds the policy lost; the divergence is loose
  early structure chasing, exactly as flagged in human-play review.
- `ante2_chip_bias`: recovers the 2 wins the looser chase cost.

Measured flat or worse this round (do not re-run): econ liquidation at
ante ≥3 (7 wins), endgame greedy switch (flat at ≤2 hands, 8 wins at 3),
`search_shops 3` (11), `xmult_rush_ante 3` (11), `ante1_econ_discount`
alone (flat), `ante1_econ_skip` (14 + same deaths), `ante1_celestial_bonus`
(19 deaths). Engine fix kept: `JokerInstance.__getstate__` drops
`_hook_cache` on deepcopy — forks firing an already-fired hook crashed
with `'object' object is not callable` (lookahead path was broken);
regression test `tests/test_hook_cache_fork.py`.

## 2026-09-05 — Optilatro V10: Root-cause loss remediation & New Official 10.67% Baseline

Macro analysis of all 266 losses on Seeds 9900–10199 identified three systemic failure modes:
1. **Boss Blind Rejected Play Defect**: On The Mouth (`bl_mouth`) and The Eye (`bl_eye`), `agent_v9` evaluated candidate plays via `scored_plays()` without checking `valid == False`, assigning phantom positive scores to illegal hands that scored 0 chips when submitted to the engine. In `_v10_decide_hand`, strict `_boss_play_filter` interception now eliminates illegal hands. If no legal hand clears and discards remain, discards lowest-value cards to dig; if discards are 0, plays a 1-card junk cycle to preserve remaining hands.
2. **Showdown Pace-Aware Discard Fallback**: In late antes (e.g. Violet Vessel 300,000 chip target), when `discards_left > 0`, `hands_left >= 2`, and `best_score < pace * 0.35`, the agent discards weak non-synergy cards instead of burning a full hand on trivial sub-pace plays.
3. **Mid-Game Consumable Flow & Burst Scaling**: Broadened mid-game shop urgency (`forecast_score < boss_target * 2.0`) across Antes 2–5 with $10–$15 interest floors, added core scoring tarots (`c_chariot`, `c_empress`, `c_hierophant`, `c_justice`) to `is_core_econ`, and enabled `c_justice` (Glass $2\times$ Mult) in Ante $\ge 7$ for showdown bursts.

### Paired Verification on Pristine Seeds 10200–10499 (300 seeds, strict human-fair):
- **Baseline (`heuristic_v9`)**: 11 wins (3.67%), 29 Ante-1 deaths (9.67%), mean ante 4.44.
- **`search_shop_v10`**: **32 wins (10.67%)**, **9 Ante-1 deaths (3.00%)**, mean ante 5.19.
- **Net Gain**: **+21 wins (+190.9% relative increase)**, **-20 Ante-1 deaths (-69.0% relative reduction)**.
- **Official baseline established**: Stored in `vendor/balatro-rl/results/default_baseline_v10.json` (acceptance criteria in `tools/verify_bench_acceptance.py` now enforces $\ge 10.0\%$ win rate / $\le 3.0\%$ Ante-1 deaths).

## 2026-09-06 — Optilatro V11: Multi-Item Shop Sequencing, Copy Joker Optimization & MLP Value Net

Deployed Component A (copy joker trigger optimization with natural-order guarding), Component B (combinatorial multi-item sequence planning), and Component C (pure-NumPy 2-layer MLP Value Network $V_\theta(S) \to P(\text{Win})$) in `vendor/balatro-rl/balatro_sim/agent_v11.py`.

### Paired Verification on Pristine Seeds 10500–10799 (300 seeds, strict human-fair):
- **Frozen Baseline (`search_shop_v10`)**: 42 wins (14.00%), 10 Ante-1 deaths (3.33%), mean ante 5.06, mean econ $17.1.
- **Evaluated Policy (`search_shop_v11`)**: **42 wins (14.00%)**, **10 Ante-1 deaths (3.33%)**, mean ante 5.06, mean econ **$17.2**.
- **Concordant Wins**: 41 shared wins (97.6% concordance across winning runs).
- **Static Audits & Gate**: 4/4 static audits CLEAN, `ci_gate` 4/4 passed in 5.3s.
- **Verdict**: **APPROVE** (passes both $\ge 10.0\%$ win rate and $\le 10$ Ante-1 death criteria).


## 2026-09-10 — V11 regression root-caused & reverted; knob space exhausted (again)

**V11 in the working tree was a −9-win regression against the committed artifact.**
Same seeds, same sim, same policy name — only the code differed:

| Artifact | V11 @ 10500–10799 |
|---|---|
| Committed (HEAD) `agent_v11.py` (677 lines) | **42/300 = 14.00%** (`git show HEAD:...paired.json`) |
| Working tree after the failed session (+1131/−78) | **33/300 = 11.00%** |

The rewrite replaced V11's shop loop — which delegated to the proven frozen V10
L1 counterfactual search — with a value-net ranking + squeeze + trap-filter +
conversion stack, and overwrote the committed paired JSON with the regressed
numbers. Every historical gain in this repo came from *search* (V9 3.67% →
`search_shop_v10` 10.67% → V11 14.0%), which is why the rewrite lost.

**Fix (no new wins claimed):** the D–F components are kept in the tree but
flipped dormant by default (`v11_squeeze/v11_filters/v11_boosters/
v11_pack_bonus/v11_seq_plan/v11_swap_limit/v11_xmult_convert_hook = false`,
`v11_vn_weight = 0.0`) with `v11_shop_v10_l1 = true`. Shipped V11 now scores
**41/300 = 13.67%** and reproduces frozen V10 with **zero seed-level flips**
(12/100 on 10500–10599, identical spend/econ/bought/sold).

**Three new components built, measured, rejected/dormant:**

- `v11_desperate` — forecast-gated "desperation" cash deployment. **Inert:** the
  forecast never reports doom. Replay of the dominant death mode (Ante-3 Big,
  target 3,000, seed 10510) shows the agent banking $13, rerolling ≤2 times,
  burning all 4 discards on single cards, then playing Two Pair for 112 and
  dying at 768/3,000. The urgency model compares an optimistic forecast against
  **boss × 2.0** and only trims interest to $15/$10 in antes 2–5.
- `v11_salvage` — never farm an unclearable blind. **Rejected:** −7 wins/100; a
  dumber version of V10's own discard EV.
- `v11_interest_target` (25 → 15) — looked like +2/100; **rejected at n=300**
  (35/300, gained 11 / lost 18 = −7). Component G is dormant.
- `v11_open_slot_search` — additive ΔV search over open slots. **Inert:** the
  `evaluate_shop_value` ΔV never clears 0.10 for an open-slot buy.

Also measured flat-or-worse (dormant/unchanged): `reroll_max` 4/6 (−2 each),
`reroll_min_money` 3 (0), `save_margin` 1.5 (−4), `save_strong_value` 0.2 (+1,
noise), `farm_clear_threshold` 0.80 (0).

**Screening lesson:** at ~12 wins/100 the noise floor is ±3 wins, and the
interest response was non-monotonic (20 → 11, 15 → 14, 12 → 9). **Adopt nothing
on n=100**; two of this round's candidates flipped sign at n=300.

Gate status: 1515 passed / ci_gate 4/4 / 4 static audits CLEAN. The 20% win-rate
gate is **not met**; the composition-legal knob space is exhausted for the third
independent time. Next lever must be a qualitatively stronger human-fair search
(the `evaluate_shop_value` model, not the search gate, is the bottleneck) or a
rollout-trained policy.

## 2026-09-11 — Learned value model (V12 oracle): built, measured, NOT adopted

Replaced the hand-curated item knowledge — 111 knobs, ~24 CAPS tables, 4
duplicated role taxonomies, ~20 hand-typed numeric dicts — with a spec-derived
catalogue plus a two-level value model fitted on **counterfactual rollout
contrasts** (fork the same state, force acquire vs skip, dense return
`ante + 8*win`). Full write-up: [value-model-2026-09-11.md](value-model-2026-09-11.md).

**The curation was already broken.** The new completeness test found two live
defects: `tools/portfolio.py` lists `j_square_joker`/`j_stone_joker` (aliases;
the spec keys are `j_square`/`j_stone`, so a policy matching the alias mis-scores
the card), and `agent_v10` lists `j_business` in *both* `ECON_JOKERS` and
`DEAD_ECONOMY_JOKERS`.

**Measured, on 1,690 collected rows / 1338 train / 352 holdout:**

| Metric | Legacy state-model ΔV | New model |
|---|---|---|
| Within-decision concordance (80 pairs) | **0.588** | 0.500 |
| Win-flip AUC | 0.719 | **0.929** |
| Holdout RMSE (dense return) | — | 2.659 linear → 2.699 with residuals |

**100-seed screen, paired:**

| Policy | Wins | Ante-1 deaths | Mean ante |
|---|---|---|---|
| `search_shop_v10` (frozen) | **12 (12.0%)** | 6 | 4.73 |
| `search_shop_v12` (oracle on) | 10 (10.0%) | 7 | 4.58 |

Behind, and coherently so: the oracle *replaces* the search's open-slot choice,
so a 0.500-concordance model displacing a 0.588 heuristic loses a little. **The
300-seed benchmark was not run** — the gate was "no 300-seed claim without a
small-seed ≥ parity signal".

**Three findings worth keeping:**

1. The additive end-of-visit hook is **structurally inert**: at `leave_shop` the
   candidate list is empty because the frozen search fills every open slot
   first (`offered = 0` for whole runs). Any open-slot hook must act at shop
   *entry*, i.e. it replaces a decision rather than supplementing one.
2. Rollout cost is **not** the shop search: `SearchShopV10` 4.15 s/run vs
   `HeuristicV10` 4.11 vs `search_shops=0` 4.08, so cheaper continuations buy
   ~2%. Data volume is ~1,700 rows / 40 min, and that is the binding constraint.
3. Coverage is 951/6,000 purchasable item cells (15.8%); tarots and spectrals
   are sampled but never to depth. Bosses and tags are **context, not items**,
   and are scored through parsed boss flags — a per-boss residual is designed
   for but not yet populated.

Gate status: 1687 passed / ci_gate 4/4 / 4 static audits CLEAN /
`audit_magic_numbers` CLEAN (9 declared constants, all with recorded
provenance). `v12_oracle` defaults **off** and `tests/test_value_model.py`
asserts V12 without it is byte-identical to frozen V10. The 20% win-rate gate is
still unmet; the next lever is collecting against the coverage work order
(`audit_value_coverage.py --focus-out` → `collect_decisions.py --focus-file`)
and populating the per-boss residual.

## Iteration 2 of the value-model loop (2026-09-11, later the same day)

Collection ran against a *reachability-weighted* work order (new
`tools/offer_census.py`): 248 seeds / 2,588 rows, corpus now 5,891 train +
1,554 holdout rows over 462 seeds. Refit moved within-decision concordance to
**0.531 [0.476, 0.582]** vs legacy ΔV 0.500 — real, but not enough.

The paired **150-seed re-screen** decided it: V10 20/150; `v12_rel_z2` 17/150
(6 gained / 9 lost); `v12_rel_z1` 12/150; `v12_allkinds_z2` 9/150. The
dose-response — more learned substitutions, monotonically fewer wins — says the
decision rule is not the weak link, the model's *ordering* is. No 300-seed
bench (gate: ≥20% belief). `v12_oracle` stays off.

Coverage is now reported honestly in three buckets (4,400 cells): **4.0% covered
by own rows** (33.6% is the hierarchy-inherited figure that earlier reports
quoted), 736 never offered, 1,891 supply-limited (handled by pooling at key
level). Everything the agent is actually shown needs **~3 more iterations**, not
the ~13 a uniform estimate implied.

Gate status: 1692 passed / 3 skipped / ci_gate 4/4 / 4 static audits CLEAN /
`audit_magic_numbers` CLEAN (10 declared constants, all with recorded
provenance).

## Iteration 3 of the value-model loop (2026-09-11, evening)

Two more coverage-directed collection runs (v5 1,141 rows / 25 min; v6 634 rows / 20 min), corpus
now **7,813 train rows over ~650 seeds**, coverage by *own* rows 1.5% → **3.9%** of the 4,400-cell
grid (30.8% is the hierarchy-inherited figure, a different question).

Three things were built, each forced by the previous iteration's measurement:

1. **`v12_mode="prior"`** — the learned head may only re-order candidates the frozen ranker
   *already* ranked, inside `v12_prior_margin` of the chosen item's value. The structural invariant
   is that it can never show the policy an item the search had not put on the table, so it cannot
   drain capital or stall a build. Measured correction to the obvious assumption: margin 0 is **not**
   the identity (the ranker ties in ~a quarter of shops), so the arms are a margin dose-response.
2. **Scenario cells** — `item|boss:<key>` and `item|hand:<type>`, so item values are *learned* in
   those scenarios rather than asserted as context flags. `hand:<type>` reads `game.planet_levels`
   (RNG-free); the collector now records `hand_key`, and the dimension went from **0 to 249 rows**
   in one iteration. Scenario evidence explicitly does *not* loosen the oracle's confidence gate.
3. **`tools/iterate.ps1`** — the whole loop (census → audit → collect → fit → audit → screen →
   ledger) as one command, fit auto-discovery, `-SeedStart 45000` past every collected range.

**Screen, bank A (10500–10649, 150 paired seeds):** V10 20/150 · `prior_m0` 19 (−1) ·
**`prior_m05` 22 (+2, 6 gained/4 lost, mean ante 4.91 vs 4.80)** · `rel_z2` 17 (−3).
**Screen, bank B (10700–10849, fresh bank):** V10 23/150 · **`prior_m05` 24 (+1, 6/5, ante 5.53 vs
5.41)** · `prior_m10` 23 (+0). Pooled over **300 paired seeds: +3 wins (12 gained / 9 lost,
p = 0.66)** with better mean ante on both banks and unchanged ante-1 deaths.

The magnitude is inside noise; the *ordering* of modes is not — every mode that replaces the
search's choice loses monotonically in firing rate, and the tie-breaking mode is the only one that
comes out ahead. `v12_mode` now defaults to `prior` with margin 0.05; **`v12_oracle` stays off**
(gate: ≥20% belief; the arm measures 14.7% / 16.0%). No 300-seed bench was run.

Gate status: 41 value-model tests (10 new for prior mode and scenario cells), `test_catalogue` +
`test_agent_v10` + `test_agent_v11` 82 passed, `audit_magic_numbers` CLEAN (11 declared constants).

## 2026-09-12 — overnight run audited; loop made resumable; `prior_m02` best arm so far

The overnight `iterate.ps1` run completed census + work order + collection (**2,766 rows**, 0 errors,
23% of the corpus) and then stopped at the collect budget boundary with no fit, no work order, no
screen and no ledger entry — `logs_sim/iter_iter1_collect.log` ends at `[200/500]` with no summary and
`iterate_main.log` was never created, so it was killed rather than failing a stage. The loop was
finished by hand: refit on **11,986 rows** (within-decision concordance 0.538 [0.497, 0.577] vs legacy
0.485; selection ctx_delta +0.126 vs −0.049; hand-type scenario cells 249 → 1,609 labelled rows),
work order regenerated (own-row coverage 3.9% → 4.4%), and two untouched-bank screens run.

`tools/iterate.ps1` is now **resumable** (per-stage artifacts, `-Force` to redo), writes a ledger line
per stage, keeps a heartbeat/state file, and has `-Detached`. Re-running the real command prints SKIP
for all four iter1 stages and completes the round the overnight run died in.

Screens on untouched banks: bank C `prior_m02` **15/100 vs V10 10/100** (econ $16.9 vs $13.9); bank D
`prior_m02` 19/200 vs V10 17/200 with `m0` 14/200. Pooled over four banks: **m0 −4 (350 seeds), m02
+7 (300), m05 +6 (400), m10 +3 (250), rel_z2 −3 (150)** — ordering stable, magnitudes inside noise, so
no 300-seed bench was run. A new `v12_prior_band` arm (never break an exact ranker tie) was built from
the measurement that exact-tie pairs differ in return only 36% of the time vs 57% for near-ties, and it
did **not** reproduce (+0 vs +2); the control showed it substitutes once per 12 seeds vs m02's four, so
it is near-inert and the null is uninformative. Default stays off. Full record:
`docs/value-model-2026-09-11.md` §Iteration 4; runs in `logs_sim/runs.jsonl` (32 entries).

## 2026-09-12 (later) — on-policy collection: the collector now forks what the oracle weighs

The collector ranked candidates by coverage shortfall, so the corpus described items chosen for being
*under-measured* and never asked what the policy buys or what the oracle compares it against. New
`--candidate-mode onpolicy` (collector v3) forks the pair the RUNTIME ORACLE weighs, by calling
`SearchShopV12._oracle_prior` itself: `pick` (the frozen buy — the anchor), `substitute` (what the
prior swaps in), `model_alt` (the head's preference with the tie window ignored), plus `coverage`
fill. Controls measured first: V10/V11/V12-oracle-off are identical per-seed, and `pick` rows have
label exactly 0.000 in 100% of cases, as designed. `tools/iterate.ps1` collects on-policy by default
and stays resumable.

Collection: 86 seeds / **1,468 rows / 0 errors** (roles: coverage 908, pick 330, model_alt 221,
substitute 9); 191 of 605 decisions carry a pick+alternative pair. Refit on **13,454 rows**: within-
decision concordance 0.503 (803 pairs, CI [0.469, 0.542]) vs legacy 0.487 — *down* from 0.538, because
the decision-relevant pairs are 48% exact label ties. New `intervention` report section, the first
direct measurement of the arm's own decisions: **193 pairs → 47 worse / 92 ties / 54 better, sign_rate
0.535** (in-window 0.536, out-window 0.429). So the prior's edge per firing is a coin flip, 48% of its
pairs are provably un-winnable, and the ±3 net deltas across five banks are exactly what a 53.5% rule
produces — the family is at its ceiling. Fresh bank E: V10 10/100, `m02` 9/100 (−1), `m05` 8/100 (−2);
pooled `m02` +6/400. No 300-seed bench (gate is ≥20% belief). Verification: 1,596 passed, ci_gate 4/4,
4 static audits CLEAN, magic-number gate CLEAN (2 new constants ledgered). Full record:
`docs/value-model-2026-09-11.md` §Iteration 5; `logs_sim/runs.jsonl` (42 entries).

# V13 S0–S1: the state-value redesign, and the gate that stopped it

Full record: `docs/v13-s0-s1-results-2026-09-12.md`; design: `docs/v13-state-value-design-2026-09-12.md`.

The per-item framing is at its ceiling (capacity ceiling 0.549 on its own training data; 48% of the
pairs it weighs are exactly equivalent), so V13 scores **whole states instead of single items**. Three
pieces were built: `balatro_sim/state_value.py` (portfolio-aware encoder — owned jokers/consumables/
vouchers encoded with the catalogue's spec vector and pooled, so an interaction like Blueprint+Baron
is expressible with no synergy table), `tools/collect_trajectories.py` (every state a run passes
through, stamped with the run's dense return — ~156 states/run, ~350× denser per unit compute than
counterfactual forks), and `tools/fit_state_value.py`.

**S0 passed.** 500 seeds → 77,390 states. Holdout spearman 0.564 (train 0.871), **seed spearman 0.808
over 100 runs**, AUC(won) 0.767, calibration monotone across antes 1–8. Permutation importance now
puts the **portfolio block first (+4.30)**, then `st_` +3.48. The same fitter on 101 seeds gave
`pf_` −2.65 and seed spearman 0.609 — i.e. **the small-corpus read was the opposite of the
large-corpus read**, so a negative block ablation at n≈100 is not evidence against a block.

S0 also caught a real bug: the first 500-seed collection silently **dropped 463,450 feature
instances** (~7 per state) because `layout_keys` declared the voucher pool with no reductions while
`_pool` emitted `max` unconditionally — every `vo_max_*` column (46 names, ~11% of the layout) was
missing from the frozen layout. Fixed by making `_POOL_OPS` one table both sides read (404 → 450
columns, 0 dropped on re-measurement) and pinned by `tests/test_state_value.py` (7 tests).

**S1 failed — the gate did its job.** `tools/validate_state_value.py` replays the on-policy fork
decisions with rollouts stubbed (86 seeds, 191 reconstructions, `index_mismatches 0`) and scores both
sides of every `(pick, model_alt)` pair with `V`. Result, on the 97 non-tied pairs: **V sign rate
0.454** vs incumbent head 0.485 vs legacy 0.464 — all chance, against **94 of 191 pairs being exact
label ties**. V is meanwhile excellent at run level (seed spearman 0.808). It learned exactly what
trajectories teach and nothing about within-decision preference.

**The failure is sample size, not architecture** — that distinction was measured, not assumed. Fitting
the encoded differences `V(alt) − V(pick)`: **GBM in-sample 0.887, leave-seed-out 0.505** (49/97).
Structure exists and does not survive to held-out seeds, across 63 distinct keys at ~1.5 pairs per key.
The second suspect is label noise: iteration 2 used `--samples 1`, so the modal ±1 label is a single
draw. Running now: `--samples 3` over the same 500 seeds and focus order, which yields ~3× the pairs
**and** `dense_samples` gives a direct split-half label-noise measurement. Decision rule: split-half
near 1.0 → scale volume and re-run S1; near 0.5 → S1 must be rebuilt on the K-averaged denser metrics.
No arm reaches a behavioural screen until the sign rate clears the incumbent's.
