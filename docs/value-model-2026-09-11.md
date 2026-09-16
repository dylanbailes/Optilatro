# Learned value model (V12 oracle) — design, measurements, outcome

Date: 2026-09-11. Status: **built, measured, and NOT adopted** — the 100-seed
screen came out behind frozen V10, so per the agreed gate no 300-seed benchmark
was run and the oracle ships **off by default**.

## What was asked for

A low-compute learning model that keeps only the important systems, removes the
embedded magic numbers and the hand-maintained hardcoding, goes back to first
principles, updates its own weights iteratively, and learns the value of
jokers, tarots, spectrals, planets, packs, vouchers, tags, bosses and hand
types **in each scenario**.

## What the old stack looked like

| Thing | Count |
|---|---|
| Tunable knobs (`agent_v9.PARAMS` + `agent_v10.V10_DEFAULTS`) | **111** |
| Hand-written CAPS tables across the three agent files | **~24** |
| Role taxonomies maintained in parallel (v9 / v10 / portfolio / v11) | **4 copies, already drifted** |
| Hand-typed numeric dicts (`PACK_VALUE`, `VOUCHER_PRIORITY`, `DECK_CONDITIONS`, `edition_bonus`, four lifecycle curves, …) | **~20** |
| Learned models, all *state*-level (none takes an item as input) | 3 |

The drift was not hypothetical — the first run of the new completeness test
found it:

* `tools/portfolio.py` `CHIPS_JOKERS` lists `j_square_joker` / `j_stone_joker`,
  which are **aliases**; the canonical spec keys are `j_square` / `j_stone`.
  A policy matching the alias while the shop sells the canonical key silently
  mis-scores the card.
* `j_business` is in **both** `ECON_JOKERS` and `DEAD_ECONOMY_JOKERS` in
  `agent_v10`. The same joker is simultaneously "economy" and "dead economy".

And the item-level gap was measurable, not theoretical: on 80 held-out
within-decision candidate pairs, the state model's ΔV ranked them at the same
rate as a coin flip (below).

## First principles

An item's value is a **controlled contrast**, not a score:

```
V(item | scenario) = E[R | acquire item] - E[R | policy's own action]
```

Three consequences drive the whole design:

1. **The label is a difference**, so the link is the identity, not a sigmoid.
   `+0.01` means "buying this adds one percentage point of win probability
   here", directly comparable to a search ΔV.
2. **The return must be dense.** Wins are ~14%, so a win label carries little
   information per fork. The return is
   `R = ante_reached + TOTAL_ANTES * won`, which is why 30% of collected rows
   carry a non-zero contrast instead of 3%.
3. **Hand types and boss patterns are not separate systems.** They are context
   dimensions of the same value function, which is how ~111 knobs collapse into
   one estimator.

Arms are forked from the **same state** (`clone_game`), so both share the run's
prior random stream (common random numbers) and the contrast cancels the shop
and deck luck the arms have in common.

## What was built

| Unit | Role |
|---|---|
| `balatro_sim/catalogue.py` | **One** spec-derived source of truth: 302 entries across jokers/tarots/spectrals/planets/vouchers/packs/cards/bosses/tags, generated from the four spec JSONs plus the sim's own rarity/price catalogue. Roles and flags are *parsed from the spec's effect strings*, not typed. |
| `balatro_sim/value_tables.py` | The artifact + the single feature builder shared by collector and runtime + pure-Python evaluation (dict walk + dot product; no numpy/torch at inference). |
| `tools/collect_decisions.py` | Paired-fork collector: shop and booster modes, attempt-and-verify arms, per-ante sampling, importance targeting, time budget. |
| `tools/fit_value_model.py` | Ridge head (alpha by seed-grouped CV) over spec+scenario features **plus** a count-shrunk residual table over cells `item|ante|support` backing off to `item|ante` → `item` → role block. |
| `balatro_sim/agent_v12.py` | Frozen V10 search + additive learned oracle, flag-gated, with a byte-identical parity control. |
| `tools/audit_value_coverage.py` | Enumerates item × scenario cells, reports what is measured, emits the next collection work order. |
| `tools/audit_magic_numbers.py` | Fails the build on any unledgered numeric constant in the new stack, or on importing a legacy curated table. |

### Magic numbers: every free parameter is fitted or declared

Ridge `alpha`, shrinkage `tau`, and all 161 feature weights are **fitted** and
live in `value_tables.json`, never in code. What remains in code is 9 constants,
each with recorded provenance in `tools/value_model_constants.json`
(spec-derived, structural, or measured). The gate is `GATE: CLEAN`.

This also killed a concrete piece of hardcoding: `_ante_boss_target` types the
chip ladders `40000 / 80000 / 70000 / 140000 / 100000 / 300000` while the sim
already exposes `current_blind.chips_target`; the new stack reads the sim, and
the boss multipliers (Violet ×6, Wall ×4) come from `boss_spec.json`'s scaling
map via `catalogue.boss_scaling()`.

## Measurements

### Dataset (iteration 1)

160 seeds, shop+booster modes, 2 candidates/decision, ≤2 decisions per ante,
12 workers, 55-minute budget.

```
rows 1690 | dense contrasts +285/-259 (30% signal) | win flips 92 | rejected arms 662 | errors 0 | 40 min
```

The 662 rejected arms are the attempt-and-verify design working: an ineligible
purchase (no slot, unusable pack) is recorded as `arm_ok=0` rather than
silently mislabelled.

### Model fit (1,338 train / 352 holdout rows, 126 train seeds)

| Metric | Legacy `evaluate_shop_value` ΔV | New model |
|---|---|---|
| **Within-decision concordance** (80 pairs) | **0.588** | **0.500** |
| Win-flip AUC | 0.719 | **0.929** |
| Holdout RMSE (dense return) | — | linear 2.659 → +residuals 2.699 |

Read honestly: the new model is **at chance on the metric that matters for
choosing between candidates**, and its residual table made holdout error
slightly *worse* (2.659 → 2.699), which means the cell layer is adding variance
rather than signal at this data size. It is much better at predicting win flips,
but with ~10 holdout flips that is a wide interval and not the deciding metric.

### Behavioural screen (100 seeds, paired)

| Policy | Wins | Ante-1 deaths | Mean ante | Econ |
|---|---|---|---|---|
| `search_shop_v10` (frozen) | **12 (12.0%)** | 6 | 4.73 | $16.6 |
| `search_shop_v12` (oracle `entry`) | 10 (10.0%) | 7 | 4.58 | $16.4 |

Behind on wins, deaths and depth. The repo's own noise floor at this bank is
±3 wins/100, so this is "no better than parity, slightly negative" — and there
is a coherent causal story for the sign: the oracle **replaces** the search's
open-slot choice, so a model at 0.500 concordance displacing a 0.588 heuristic
should lose a little. The gate therefore aborted the 300-seed benchmark, as
agreed, rather than run it and dress up a non-result.

### Coverage (`audit_value_coverage.py`)

```
required n per cell : 7.6  (derived: (residual_sd 2.764 / 1 ante) ** 2)
grid                : 6000 cells = 8 antes x 3 support buckets x 250 purchasable items
covered             : 951 (15.8%)
  joker   150 items / 3600 cells with evidence / 723 covered
  voucher  32 /  384 / 117
  pack     15 /  312 /  75
  planet   12 /  288 /  27
  card      1 /   24 /   9
  tarot    22 /  432 /   0     <-- sampled but never to depth
  spectral 18 /   48 /   0     <-- sampled but never to depth
```

Two honest findings here beyond the number itself:

* **Bosses and tags are not items.** An early version of the audit gridded them
  as item × scenario cells, which produced 156 permanently uncoverable cells and
  made the headline meaningless. They are *context*: they enter through parsed
  boss flags in the feature vector. A per-boss residual (`bl_*` cells) is the
  missing piece — designed for, not yet populated.
* The volume ceiling is measured, not assumed: `SearchShopV10` 4.15 s/run vs
  `HeuristicV10` 4.11 vs `search_shops=0` 4.08, i.e. the L1 shop search is *not*
  the rollout bottleneck, so cheaper continuations buy ~2% and cannot fix
  coverage. ~1,700 rows per 40 minutes is the real rate.

### A design correction the measurements forced

The plan's oracle was strictly additive: "add a purchase the frozen search
declined". Instrumenting it showed **`offered = 0` for an entire run** — at
`leave_shop` the candidate list is empty, because the frozen search fills every
open slot before it leaves. The additive hook is therefore structurally inert,
and the oracle only does anything at shop *entry*, where it must replace the
heuristic ranking rather than supplement it. That is a real behavioural change
with real risk, which is exactly what the screen then caught.

## What was cut, what was frozen

* **Cut (for the new stack):** the four role taxonomies, the ~20 curated numeric
  dicts, the 111 knobs, and the state-level value models.
* **Frozen and untouched:** `agent_v9.py`, `agent_v10.py`, `agent_v11.py`. They
  are the A/B arms, and the last wholesale rewrite of V11's internals silently
  cost 9 wins. "Cut" applies to the new model, not to the reference arms.
* **Parity control:** `v12_oracle=False` is byte-identical to frozen V10 on the
  seed bank (asserted in `tests/test_value_model.py`, and confirmed on 20 seeds:
  identical wins, deaths, mean ante and econ). This is why V12 can be left in
  the tree enabled-but-off without being a regression risk.

## Why it did not reach 20%, and the sharpest next step

The bottleneck is **data volume per cell**, and it is now quantified: 1,690 rows
spread over ~600 keys is ~3 samples per item, while item-level effects (~1-2
antes) require ≈8 samples per cell at the measured residual spread. Coverage is
15.8% and the ranking metric sits at chance.

Two levers follow directly from the measurements:

1. **Collect against the coverage work order, not uniformly.**
   `audit_value_coverage.py --focus-out` already emits per-cell weights and
   `collect_decisions.py --focus-file` consumes them, so compute concentrates on
   the 5,049 uncovered cells instead of re-sampling jokers already at depth.
   Iteration 1 collected nothing for tarots/spectrals to depth — pack picks are
   exactly where those values are decided, so `--mode booster` needs a larger
   share of the budget.
2. **Populate the per-boss residual.** Bosses are context today; a `bl_*` cell
   layer is cheap (28 keys) and directly answers "boss patterns learned in each
   scenario".

The decision *rule* also deserves revisiting before more data: buying whenever
`value > 1 SE` on a model whose ranking is at chance spends real money on noise.
A safer intermediate is to let the learned model **only veto** candidates the
search would buy, or to require it to beat the search's own choice in a paired
fork — which is a different, and much better-posed, collector than the one built
here.

## Reproduction

```bash
# 1. catalogue + provenance gates
python -m pytest vendor/balatro-rl/tests/test_catalogue.py vendor/balatro-rl/tests/test_value_model.py -q
python tools/audit_magic_numbers.py

# 2. collect counterfactual decision data (≈40 min at 12 workers)
python tools/collect_decisions.py --seed-start 40000 --n-seeds 160 --mode both \
  --per-ante 2 --cand-cap 2 --accept-rate 0.6 --workers 12 --time-budget-min 55 --out-tag v1

# 3. fit; writes balatro_sim/value_tables.json and a calibration report
python tools/fit_value_model.py --train results/decisions/train_v1.jsonl \
  --holdout results/decisions/holdout_v1.jsonl \
  --out vendor/balatro-rl/balatro_sim/value_tables.json \
  --report results/value_model_report_v1.json

# 4. what is still unmeasured, and what to collect next
python tools/audit_value_coverage.py --focus-out results/coverage_focus_v1.json

# 5. behavioural screen (≤200 seeds before any 300-seed claim)
python bench/bench_agent_v10.py --seeds 10500-10599 \
  --policies search_shop_v10,search_shop_v12 \
  --params '{"v12_oracle":true,"v12_mode":"entry"}' --workers 12 --no-report
```

---

# Iteration 2 (same day): coverage-directed collection, refit, re-screen

## 1. The loop changed before it ran again — every change came from a measurement

| Change | Measurement that forced it |
|---|---|
| **Offer census** (`tools/offer_census.py`, new) | The work order was shortfall-only, so it spent identical budget on a voucher the agent was offered 0 times in 300 runs and on a pack offered 50 times per run. 200 census runs → 31,691 offers, 230 distinct keys, 1,619 `key\|ante` cells. The top of the work order moved from exotic vouchers (`v_antimatter`, `v_glow_up`) to cells the agent actually meets (`p_celestial\|a4`, `p_standard\|a4`, `pl_earth\|a1`). |
| **Coverage counts own rows separately** | The audit counted hierarchy-inherited evidence, so one item-level row "covered" all eight of its ante cells. Reported both now: **33.6% inherited vs 4.0% own rows**. The earlier 24.1% headline was the inherited figure. |
| **Supply-limited ≠ budget-limited** | A spectral is offered **0.91 times per run across 18 keys**, so its 144 `key\|ante` cells need ~1,570 runs (≈6 iterations) to each reach the required 8.8 rows. 1,891 cells across 192 keys fall below the one-iteration fill rate; **128 of those 192 keys are covered at key level** (pooled across antes), which is exactly what the shrinkage hierarchy uses them for. More collection cannot fix these cells. |
| **Pack arms are filtered by slot room** | ~24–30% of pack arms were rejected as `arm_ok=0` — roughly a sixth of all collection compute spent proving that a full joker slot is still full. Rejections now also carry a reason string instead of vanishing into a counter. |
| **Confidence no longer inherits role strength** | `cell_stderr` used `effective_n`, which walks up to `role:*` cells pooling ~445 rows across unrelated items: standard error collapsed to ~0.15 and the oracle accepted 17 of its first 51 offers with no evidence about the item itself. `own_n` (finest evidence about *this* item) now governs confidence; shrinkage still borrows from the role. |
| **Overrides use a paired contrast, on the relative head** | The old rule tested one candidate in isolation. Buying A *instead of* B is a contrast, so `beats()` requires `value(A) − value(B) > z·sqrt(se_A² + se_B²)`, and the report had already measured the within-decision *relative* head as the better discriminator (0.527 vs 0.499 on the smaller fit). |
| **`v12_mode` default → `override`** | `entry` measured −2/100; `override` is the least-bad mode, and it can only change *which* item a decision already spends money on, never whether money is spent. |

## 2. Collection (iteration 2)

`248 seeds · 2,588 rows · 151 win-flips · +320/−462 dense contrasts · 0 errors · 56 min at 12 workers`
Cumulative corpus: **5,891 train / 1,554 holdout rows over 462 seeds**.

Two decisions were made by measurement rather than taste:

- **K=1, not K=2 continuations.** Cell-mean split-half reproducibility is **r = +0.119** over 308 cells, and **66.6% of label variance is between-decision (context)**, only 33.4% within. Extra continuations attack only the minority variance term while halving the number of runs — and run count is what rare-item coverage scales with.
- **The interaction hypothesis was already implemented.** The feature set carries `x_role_*__{ante_frac,power_deficit,support_frac,is_boss}` and `x_flag_*__…` (88 features) plus 11 boss flags, so item×context is representable and the binding constraint is data per cell (median n = 3), not model capacity. Adding interaction terms is explicitly *not* the next step.

Related negative result: per-head ridge alpha (chosen on the relative target's own CV) selects the **same** alpha as the absolute head (757.8), so the relative head was not over-shrunk. The change is kept because it is correct by construction, not because it helped.

## 3. Refit on v1…v4 (all four iterations)

```
within-decision : model 0.531 (416 pairs, ci95 [0.476, 0.582]) | legacy dV 0.500
top1 pick       : relative head 0.495 | absolute head 0.518 | legacy dV 0.467
selection (pop) : model +0.884 (78% of decisions positive, n=590) | legacy dV -0.129
win-flip AUC    : model 0.483 | legacy dV 0.619
```

The model now edges past the legacy ΔV on within-decision concordance (0.531 vs 0.500) — the first version measured 0.507 vs 0.510. But 0.531 is not enough to displace a strong search, as the screen below shows.

## 4. Re-screen: 150 paired seeds (10500–10649)

| arm | wins | rate | gained | lost | net | mean ante |
|---|---|---|---|---|---|---|
| `search_shop_v10` (frozen control) | 20/150 | 13.33% | — | — | — | 4.80 |
| `v12_rel_z2` (least intervening) | 17/150 | 11.33% | 6 | 9 | **−3** | 4.87 |
| `v12_rel_z1` (twice as many overrides) | 12/150 | 8.00% | 4 | 12 | **−8** | 4.75 |
| `v12_allkinds_z2` (jokers + tarot/spectral/planet) | 9/150 | 6.00% | 2 | 13 | **−11** | 4.55 |

**The dose–response is the finding.** The three arms differ only in how often the oracle intervenes; every additional learned substitution costs wins, monotonically. So the *decision rule* is not the weak link — a paired contrast, evidence-gated, over an already-strong search is about as conservative as an override can be — the **rank quality of the model** is, at 0.53 concordance. Widening the oracle to consumables (the kinds whose values were typed tables rather than measurements) makes it worse, not better: those cells are the least measured of all (planets 2/96, spectrals 0/144 own-covered).

A 60-seed screen of the same arm had read "7/60 vs 7/60, win-neutral". The 150-seed run shows −3 with 6 gained / 9 lost. Nothing was adopted on the small-n reading.

## 5. Not run, deliberately

**No 300-seed benchmark.** The standing gate is a 300-seed run only at ≥20% belief; this arm is below parity. `v12_oracle` ships **off**, and the V12 parity control (byte-identical to frozen V10 with the oracle disabled — `TestV12Parity`) is unchanged and green.

## 6. Where the evidence says the next iteration's compute goes

Coverage is now measurable in three buckets, and only one of them is worth collecting:

- **reachable and fillable** — joker own-cells 44/1200·3, packs **63/120**, vouchers 40/144, tarots 22/176, planets 2/96. Packs and tarots are the cheapest wins: a pack is offered 49.9 times per run across 15 keys, a tarot 18.6 across 22. Budget estimate for every cell the agent is actually shown: **~7,900 rows ≈ 3 iterations** (1,221 cells at 8.8 rows each) — not the ~13 iterations a uniform, unreachability-blind estimate implied.
- **never offered** — 736 cells. Reportable, not collectable.
- **supply-limited** — 1,891 cells across 192 keys; handle at key level, where 128 of those keys already are.

For the *model* rather than the corpus, the honest next step is not another knob and not more interaction features: it is enough per-scenario rows for the kinds that can be resolved, after which either the concordance moves or the conclusion is that a per-item additive-plus-cell model cannot beat the search's own rollout counterfactual at this scale.

## 7. Reproduction (iteration 2)

```bash
# offer census + coverage work order (the census is what makes the order honest)
python tools/offer_census.py --seed-start 50000 --n-seeds 200 --workers 12
python tools/audit_value_coverage.py --census results/offer_census.json \
  --budget-runs 250 --focus-out results/coverage_focus_v4.json

# collection against that order
python tools/collect_decisions.py --seed-start 42000 --n-seeds 500 --workers 12 \
  --focus-file results/coverage_focus_v3.json --booster-cand-cap 6 --accept-rate 0.4 \
  --time-budget-min 55 --out-tag v4

# refit on every iteration collected so far
python tools/fit_value_model.py \
  --train results/decisions/train_v1.jsonl,results/decisions/train_v2.jsonl,results/decisions/train_v3.jsonl,results/decisions/train_v4.jsonl \
  --holdout results/decisions/holdout_v1.jsonl,results/decisions/holdout_v2.jsonl,results/decisions/holdout_v3.jsonl,results/decisions/holdout_v4.jsonl \
  --report results/value_model_report_v4.json

# paired re-screen (never a 300-seed headline below parity)
python bench/bench_v11_ablation.py --seeds 10500-10649 \
  --variants v12_rel_z2,v12_rel_z1,v12_allkinds_z2 --workers 12 \
  --out results/screen_v12_n150.json

# the decisive measurement of the iteration, in one line per arm
#   V10 20/150 | rel_z2 17/150 (6 gained / 9 lost) | rel_z1 12/150 (4/12) | allkinds_z2 9/150 (2/13)
```

## 8. What this iteration established

1. **The corpus grew 2.3x and the model's ranking moved from parity to slightly-ahead of the
   legacy ΔV** (0.507 vs 0.510 → 0.531 vs 0.500 on within-decision concordance). That is real
   but not yet sufficient: the search it must beat is a rollout counterfactual.
2. **More data alone will not close the gap by accumulation.** The dose-response on intervention
   frequency says the model's *ordering* is the binding constraint, and the ordering is carried
   mostly by the linear head because 96% of scenario cells have no evidence of their own.
3. **The coverage question is now answered with numbers rather than ambition.** Reachable and
   fillable cells: ~3 iterations of collection. Never-offered: 736 cells, out of scope forever.
   Supply-limited: 1,891 cells, handled by pooling, which the model already does.
4. **Two measurement defects were fixed**, and both had been inflating results in the flattering
   direction: coverage counted a parent's rows as a child's evidence, and the oracle's confidence
   gate counted a role's 445 pooled rows as evidence about a specific item.


---

# Iteration 3 (same day): the prior architecture, scenario cells, and one long-run command

Iteration 2 ended with a decision, not a number: the override arm lost wins *monotonically in how
often it fired*, so the decision rule was innocent and the model's **ordering** was guilty. The
ledger's own `next` field said what follows from that — use the learned value as a **prior inside
the search**, not as a verdict on the search's output. This iteration implements that, plus the two
"learned in each scenario" dimensions the model was still only asserting, plus the loop itself as a
single command.

## 1. A third mode: `prior` (the search decides; the learned head breaks its ties)

```
entry     pick instead of the search    -2 wins / 100 seeds   (iteration 1)
override  substitute the search's pick  win-neutral, monotone  (iteration 2)
prior     break only the search's ties  this iteration
```

`prior` calls the frozen ranker (`_v10_rank_shop_items`, a pure-read routine the search itself
calls every shop step) to get the search's own candidate list, then lets the learned relative head
re-order only those candidates whose ranker value is within `v12_prior_margin` of the chosen item's.

The invariant this buys is structural, not statistical: **the prior can never show the policy an
item the frozen ranker had not already ranked affordable and worth buying**, so it cannot drain
capital or stall a build. Spending happens exactly when the search wanted to spend, on the same
slot budget.

A measurement immediately corrected the obvious assumption. `margin = 0` is **not** the identity:
within-shop ranker spread is q25 = 0.00 / q50 = 0.03, so the ranker ties in a large share of shops
and the learned head does substitute. On an 8-seed probe m0 took 5 substitutions and moved 2/8
seeds. So the arms are a *dose-response in margin* (m0 = exact ties only, m02, m05, m10), and the
honest parity control remains the flag-level one (`v12_oracle=False`, byte-identical, tested).

## 2. Scenario cells: item x boss and item x hand type, learned rather than asserted

The requirement is that an item's value is learned *in each scenario*. The primary cell covered
ante; two dimensions were still only context flags:

| dimension | source (RNG-free) | what it can express |
|---|---|---|
| `item\|boss:<key>` | the sim's pre-selected upcoming boss (revealed with the shop, as in the real game) | a boss that debuffs Faces changes what a face-card joker is worth **before** it is bought |
| `item\|hand:<type>` | `game.planet_levels` — the hand type the run has actually raised past level 1 | "worth more now that Flush is levelled" as a measured cell |

Both are pooled across antes on purpose: the shortfall is data, not resolution, and a 3-way grid
would fragment every cell below the evidence threshold the coverage audit enforces.

Three honesty guards came out of building them:

1. **No fabricated scenarios.** An all-level-1 planet dict is not a "leaning" (its argmax is an
   arbitrary alphabetical choice), so `hand_scenario` returns `""` until a level is actually raised.
2. **One naming convention.** The game-side builder and the row-side builder are asserted equal in
   a test, because a mismatch between them would be invisible train/serve skew.
3. **Scenario evidence never loosens the confidence gate.** Scenario terms add variance (they pool
   across antes), so counting their rows as confidence would overstate support; `cell_stderr` stays
   a lower bound on the estimate's uncertainty, and that is now a test.

The coverage audit reports them separately and targets them through the **item**
(`key|scenario`), because a scenario is a property of the *run*, not of the shop offer. That bias is
capped below the force threshold and only applied to items whose key-level row is already
measurable — otherwise forcing items for unfillable boss cells would spend the whole iteration on
cells no budget can resolve, which is the failure the supply-limited filter exists to prevent.

## 3. One command for the loop

`tools/iterate.ps1` runs the cycle that was previously five hand-typed commands, in the order that
keeps the work order in sync with the freshly fitted model:

```
census (every N) -> audit -> collect -> fit -> audit -> screen -> ledger
```

Each round appends a `logs_sim/runs.jsonl` entry carrying its metrics and an explicit `next` field;
the fit auto-discovers every non-empty `results/decisions/{train,holdout}_*.jsonl` except `*smoke*`
(dev rows live in `results/decisions/_dev/`), so a new collection round needs no edits.

## 4. Collection (iteration 3)

| run | seeds | rows | win-flips | rejected arms | wall clock |
|---|---|---|---|---|---|
| v5 | 43000–43099 (budget-stopped at 100 of 500) | 1,141 | 85 | 371 | 25 min @ 12 workers |
| v6 | 44000–44xxx (budget-stopped) | 634 | 22 | 59 | 20 min @ 8 workers |

Both ran against the supply-limited-aware work order, and v6 is the first iteration whose rows carry
`hand_key`, so the item x hand-type cells get their first evidence. Rejections are
`no_state_change` throughout — an attempted forced buy the sim declined (full slots, per-zone rules),
which is the collector's attempt-and-verify design working rather than an error.

Corpus after both: **7,813 rows over ~650 seeds**, coverage by own rows **3.9%** of the 4,400-cell
grid (up from 1.5% before this iteration; 30.8% is the hierarchy-inherited figure, which is a
different and more flattering question).

## 5. Refit on v1…v6

```
rows 7,813 train + ~1,950 holdout, 161 features, 3,553 cells (median n = 2)
within-decision concordance : model 0.536 [0.493, 0.581]  vs  legacy ΔV 0.491   (515 pairs)
context-matched selection   : model +0.779 (76.7% of decisions positive)  vs  legacy −0.121
scenario cells              : boss 743 rows / 743 item cells (125 with n>=3, max 6)
                              hand  249 rows / 249 item cells ( 96 with n>=3, max 13)
```

The hand-type dimension went from **0 rows to 249** the moment the collector recorded it, which is
the whole argument for making scenario evidence a *collected* quantity rather than an asserted one.

## 6. The re-screen, and the first positive paired result in this line of work

**Bank A — 10500–10649 (150 paired seeds), artifact fitted on v1…v5:**

| arm | wins | ante-1 deaths | mean ante | gained | lost | net |
|---|---|---|---|---|---|---|
| `search_shop_v10` | 20/150 | 7 | 4.80 | — | — | — |
| `v12_prior_m0` (exact ties only) | 19/150 | 7 | 4.83 | 2 | 3 | −1 |
| **`v12_prior_m05`** | **22/150** | 7 | **4.91** | **6** | **4** | **+2** |
| `v12_rel_z2` (override, iteration 2's arm) | 17/150 | 7 | 4.84 | 6 | 9 | −3 |

**Bank B — 10700–10849 (150 paired seeds), a fresh bank, artifact fitted on v1…v6:**

| arm | wins | ante-1 deaths | mean ante | gained | lost | net |
|---|---|---|---|---|---|---|
| `search_shop_v10` | 23/150 | 2 | 5.41 | — | — | — |
| **`v12_prior_m05`** | **24/150** | 2 | **5.53** | **6** | **5** | **+1** |
| `v12_prior_m10` | 23/150 | 2 | 5.58 | 6 | 6 | +0 |

Pooled over **300 paired seeds**, `v12_prior_m05` is **+3 wins (12 gained / 9 lost, binomial
p = 0.66)** with a better mean ante on *both* banks and identical ante-1 deaths.

**What is and is not claimed.** The magnitude is inside noise — three wins on 300 seeds is not a
result. What is not inside noise is the *ordering* of the three modes, which now has a mechanism:
every mode that lets the learned model **replace** the search's choice loses wins in proportion to
how often it fires (entry −2/100, override −3/−8/−11 by firing rate), and the mode that lets it only
break the search's ties is the only one that comes out ahead, on two independent banks. `v12_prior_m05`
is therefore the default now that the oracle is switched on — with the oracle still **off** by
default, because that ordering is a ~0.54-concordance model's contribution and 3/300 is not a
shipping claim.

**No 300-seed benchmark was run.** The standing gate is "≥20% belief", the arm measures 14.7% and
16.0% on the two banks, and dressing up +3/300 as a headline would be the wrong call.

## 7. Reproduction (iteration 3)

```powershell
# everything, in order, forever: census -> audit -> collect -> fit -> audit -> screen -> ledger
powershell -NoProfile -ExecutionPolicy Bypass -File tools/iterate.ps1 -Iterations 3

# one long unattended run (8 rounds, collection only, 12 workers, 55 min each)
powershell -NoProfile -ExecutionPolicy Bypass -File tools/iterate.ps1 -Iterations 8 -SkipScreen

# detached, so it survives the terminal closing
Start-Process powershell -ArgumentList '-NoProfile','-ExecutionPolicy','Bypass',
    '-File','tools/iterate.ps1','-Iterations','8' -WindowStyle Hidden `
    -RedirectStandardOutput logs_sim/iterate_main.log `
    -RedirectStandardError  logs_sim/iterate_main.err
```

The individual stages, if a single one needs re-running:

```powershell
python tools/offer_census.py --seed-start 52000 --n-seeds 200 --workers 12 --out results/offer_census.json
python tools/audit_value_coverage.py --census results/offer_census.json --focus-out results/coverage_focus_v8.json
python tools/collect_decisions.py --seed-start 45000 --n-seeds 500 --time-budget-min 55 `
    --workers 12 --focus-file results/coverage_focus_v8.json --focus-extra 3 --out-tag v7
python tools/fit_value_model.py --train results/decisions/train_v1.jsonl,results/decisions/train_v2.jsonl,`
    results/decisions/train_v3.jsonl,results/decisions/train_v4.jsonl,results/decisions/train_v5.jsonl,`
    results/decisions/train_v6.jsonl,results/decisions/train_v7.jsonl `
    --holdout results/decisions/holdout_v1.jsonl,results/decisions/holdout_v2.jsonl,`
    results/decisions/holdout_v3.jsonl,results/decisions/holdout_v4.jsonl,`
    results/decisions/holdout_v5.jsonl,results/decisions/holdout_v6.jsonl,`
    results/decisions/holdout_v7.jsonl `
    --out vendor/balatro-rl/balatro_sim/value_tables.json --report results/value_model_report_v7.json
python bench/bench_v11_ablation.py --seeds 10900-11049 --workers 10 `
    --variants v12_prior_m05,v12_prior_m10 --out results/screen_v12_prior_n150_v7.json
```

`tools/iterate.ps1` defaults to `-SeedStart 45000` (past every range already collected) and 12
workers (leaving 4 cores free so development work continues during a run). The fit auto-discovers
`results/decisions/{train,holdout}_*.jsonl`, so a new round needs no command edits.

The one-line read of any screen:

```powershell
python -c "import json,sys; d=json.load(open(sys.argv[1])); [print(k, len(v)) for k,v in d.items()]" results/screen_v12_prior_n150.json
```

## 8. What this iteration established

1. **The prior architecture is the right shape.** Replacement modes lose monotonically in firing
   rate; the tie-breaking mode is the only arm with a non-negative paired net, on two banks.
2. **Scenario learning is now real rather than designed.** Item x boss and item x hand-type cells
   exist, are fitted, are evaluated by both the runtime and the offline report through one shared
   naming function, and are reported by the coverage audit with their own evidence thresholds.
   Boss cells remain supply-limited by construction (a boss is known in ~40% of shop states and
   there are 28 of them); hand cells moved from 0 to 249 rows in a single iteration.
3. **The loop is one command with a ledger.** `tools/iterate.ps1` plus `logs_sim/runs.jsonl`, so the
   next iteration starts with a work order derived from the current artifact rather than from a
   stale one, and every run carries its own `next` action.
4. **What the next long run should buy.** ~3 further collection iterations on the fillable cells
   (packs 75/120 inherited, tarots 38/176, vouchers 55/144, planets 15/96 own-covered) and the
   scenario gaps, then the same prior arm re-tested — so the experiment separates *data* from
   *rule*, which is exactly what the last two iterations could not do.

---

# Iteration 4 (2026-09-12): the overnight run, what it actually did, and where the number came from

## 1. The overnight run: verified partial, not a failure of the tooling

Launched 01:17, stopped 02:13. What completed:

| stage | result |
|---|---|
| `offer_census` | 200 runs, 34,859 offers, 230 distinct keys → `results/offer_census.json` |
| `audit_pre` | work order `results/coverage_focus_iter1.json` (990 cells, 0 zero-evidence keys) |
| `collect` | **2,766 rows** (2,121 train / 645 holdout), 227 win-flips, +454/−501 dense contrasts, **233 rejected arms, 0 errors**, 200 of 500 seeds in 53 min |

What did **not** happen: the fit, the post-refit work order, the screen, and — the part that stings —
the ledger entry. `logs_sim/iter_iter1_collect.log` ends at `[200/500]` with no closing summary, so
the process was killed at the budget boundary rather than failing a stage. `iterate_main.log` was
never created, i.e. the detached form of the command from iteration 3's §7 was not what ran.

The corpus is now **11,986 rows / ~853 seeds**, of which the overnight run is 23%.

## 2. The loop now cannot lose a round like that

`tools/iterate.ps1` was one-shot: it wrote its ledger line only after the screen, so an interrupted
run was indistinguishable from a run that never started. Rewritten:

* **Resumable** — every stage declares an artifact; an existing artifact skips the stage unless
  `-Force`. Verified by re-running the real command: all four iter1 stages printed `SKIP` and the
  round completed. In other words the loop now finishes the round the overnight run died in.
* **Per-stage ledger lines** — a partial run is legible stage by stage instead of silent.
* **Heartbeat + state file** — the last stage that *started*, so "what was it doing" is answerable,
  and the next run prints a warning if the previous one was mid-stage.
* **`-Detached`** — the script relaunches itself hidden, so the launcher's lifetime is irrelevant.

## 3. Refit on the completed corpus (`results/value_model_report_iter1.json`)

```
train rows      9,348 (753 seeds)      holdout rows 2,638
within-decision model 0.538 [0.497, 0.577] (682 pairs) | legacy dV 0.485
selection (pop) model(rel) ctx_delta +0.126, abs +0.064, legacy dV -0.049 (n=1,054, 77.4% positive)
win-flip AUC    model 0.491 | legacy dV 0.587   <- the win-flip head got WORSE with more data
scenario cells  hand type 1,609 rows labelled (1,278 with n>=3, was 249) | boss 875 rows
```

Coverage by the cell's **own** rows: 3.9% → **4.4%**. The scenario layer the last iteration built is
now actually populated — that is the 1,609/1,278 hand-type figure, and it is the part of the grid
that replaces the typed tables.

## 4. Where the prior's firings land, measured (11,986 rows / 6,429 decisions)

| label | nonzero |
|---|---|
| dense return (what the head is fitted on) | 33.4% (sd 3.05) |
| win-flip | 6.9% |

**47.4% of all decisions are entirely silent** — every candidate in them measured equivalent — which
is a hard upper bound on what any ranking model can contribute. Then, pairing candidates inside a
decision by `|legacy_dV gap|`:

| ranker gap | pairs | differ in return | mean \|Δlabel\| |
|---|---|---|---|
| exact tie | 2,818 | **36.3%** | 1.30 |
| < 0.01 | 2,543 | **57.0%** | 1.88 |
| 0.01–0.05 | 1,081 | 52.0% | 2.09 |

`margin` gates on the ranker's gap, so the tie end of the window is the *least* informative place to
spend an intervention — and `margin 0` lives entirely there.

## 5. The screens: two fresh banks, and the band arm that did not reproduce

**Bank C (11500–11599, untouched):**

| arm | wins | g/l | net | p | mean ante | econ $/run |
|---|---|---|---|---|---|---|
| `__v10__` | 10/100 | — | — | — | 4.82 | 13.9 |
| `prior_m02` | **15/100** | +6/−1 | **+5** | 0.12 | 5.02 | **16.9** |
| `prior_m05` | 13/100 | +5/−2 | +3 | 0.45 | 4.89 | 16.7 |
| `prior_m10` | 13/100 | +6/−3 | +3 | 0.51 | 4.90 | 16.6 |

**Bank D (11600–11799, untouched):** V10 17/200 | `m0` 14/200 (+5/−8, **−3**) |
`prior_m02` 19/200 (+8/−6, **+2**, mean ante 5.08 vs 4.94, econ 18.8 vs 18.1) |
`prior_band_m02` 17/200 (+3/−3, **+0**).

Pooled over all four banks (paired against V10 on the same seeds):

| arm | paired seeds | gains/losses | net | p |
|---|---|---|---|---|
| `prior_m0` (exact ties only) | 350 | +7/−11 | **−4** | 0.48 |
| `prior_m02` | 300 | +14/−7 | **+7** | 0.19 |
| `prior_m05` | 400 | +17/−11 | +6 | 0.35 |
| `prior_m10` | 250 | +12/−9 | +3 | 0.66 |
| `rel_z2` (override) | 150 | +6/−9 | −3 | 0.61 |

The *ordering* replicates on every bank — the arm that fires only on exact ties is the only negative
one, and the peak sits at the narrowest nonzero margin — while every individual magnitude is inside
noise. **Not run: the 300-seed benchmark.** The standing gate is a ≥20% belief and the best arm is
34/300 on these (harder) banks.

**The band arm** (`v12_prior_band`: never break an exact ranker tie, margin fixed) was implemented
from §4's measurement and then **did not reproduce** a gain: +0 net on bank D vs +2 for plain m02 on
the same seeds. Before interpreting that, the control: over 12 seeds the band offers 8 pool members
and substitutes **once**, while m02 offers 31 and substitutes **4×**. So the band is nearly inert and
that null means "prior switched off", not "ties are useless". Default stays `False`; the hypothesis is
untested rather than refuted.

Per-intervention arithmetic, which is the useful number: m02 substitutes ~0.33×/seed, and nets ≈+7
over 300 seeds → **≈7% of its substitutions convert a lost run into a won one**. The lever is
therefore the *number* of informed interventions, not the width of the window.

## 6. Reproduction (iteration 4)

```bash
# the loop, resumable: re-running the identical command resumes from the last completed stage
powershell -NoProfile -ExecutionPolicy Bypass -File tools/iterate.ps1 -Iterations 1 -SkipScreen -CensusEvery 0
powershell -NoProfile -ExecutionPolicy Bypass -File tools/iterate.ps1 -Iterations 8 -SkipScreen -Detached

# refit on everything collected so far (the loop does this itself; this is the manual form)
python tools/fit_value_model.py --train <all train_*.jsonl> --holdout <all holdout_*.jsonl> \
    --out vendor/balatro-rl/balatro_sim/value_tables.json --report results/value_model_report_iter1.json

# paired screens on untouched banks (never a 300-seed headline below parity)
python bench/bench_v11_ablation.py --seeds 11500-11599 --variants v12_prior_m02,v12_prior_m05,v12_prior_m10 --workers 8 --out results/screen_v12_iter1_n100.json
python bench/bench_v11_ablation.py --seeds 11600-11799 --variants v12_prior_m0,v12_prior_m02 --workers 8 --out results/screen_v12_iter1_replication_n200.json
python bench/bench_v11_ablation.py --seeds 11600-11799 --variants v12_prior_band_m02 --workers 8 --out results/screen_v12_band_n200.json

# the measurement that motivates the next iteration, in one script-free pass
#   python - <<'PY' ... bucket candidate pairs by |legacy_dV gap| and report label disagreement
```

## 7. What this iteration established

1. **The loop's failure mode was the missing resume, not the science.** One night bought 23% of the
   corpus and the stage that turns rows into a model never ran. That is now fixed and verified.
2. **`prior_m02` is the best arm measured so far** (+7 net / 300 paired seeds) and it moves all three
   of the tracked targets the same direction on the banks where it was measured: wins 10→15,
   econ +$3.0/run (+22%), mean ante +0.20, ante-1 deaths flat.
3. **The firing domain is the lever, and the margin sweep is a proxy for it.** The prior acts ~0.33×
   per seed at a ≈57%-correct-per-firing edge. Width was the wrong dial to turn: the band cut firings
   4× and the gain vanished.
4. **A third of the decision space is closed to ranking** (47.4% of decisions are label-silent), so
   coverage of *items* is the wrong unit. The work order should target decisions the arm can act on.

---

# Iteration 5 (2026-09-12): on-policy collection, and the first direct measurement of the arm's own decisions

## 1. What was wrong with the corpus (not with the model, and not with the gate)

Every collection run to date ranked candidates by **coverage-work-order shortfall**. That is the
right rule for learning what an item is worth, and the wrong rule for learning which item to buy: it
forks the items that are *under-measured*, and never once asks what the policy buys or what the oracle
compares it against. The prior's pool is "offers within `margin` of the pick's own ranker value", so
in (pick, alternative) terms the corpus was mostly describing pairs the oracle never weighs. Three
arms were then judged by 100–200 seed screens that could not resolve the question, because the data
to answer it did not exist.

## 2. `--candidate-mode onpolicy` (collector v3)

Per sampled **shop** decision the candidate set is now:

| role | what it is |
|---|---|
| `pick` | the item the frozen search buys — the anchor a substitution has to beat |
| `substitute` | what the learned prior swaps in, taken from `SearchShopV12._oracle_prior` **itself**, not re-derived |
| `model_alt` | the head's own preference with the tie window ignored |
| `coverage` | work-order fill, as before (pack decisions stay coverage-driven; the prior only acts on shops) |

Design points worth keeping:

* **The oracle is called, not re-implemented.** The collector imports the shipped prior and asks it.
  There is no second copy of the pool logic to drift from the arm being screened.
* **The control came first.** `SearchShopV10()`, `SearchShopV11()` and `SearchShopV12(oracle off)` are
  identical per-seed on 12 seeds, so the collector's live policy *is* the arms' frozen search.
* **The anchor behaves as predicted:** `pick` rows have `label` exactly `0.000` in 100% of cases —
  forcing the action the policy would have taken reproduces the control arm. That is what makes the
  pair's delta interpretable.
* **`model_alt` exists for a reason.** It answers, offline, the question every screen in this line of
  work was buying and never resolving: does the head's preference carry information *outside* the
  near-tie window? If it does, the window is too narrow; if it does not, the fix is a better gate.

## 3. Collection (iteration 5)

86 of 500 seeds in 30 min at 12 workers — **finished cleanly**, unlike iteration 4's overnight run:
1,468 rows (1,186 train / 282 holdout), 104 win-flips, +260/−254 dense contrasts, 269 rejected arms,
**0 errors**. Roles: `coverage=908 pick=330 model_alt=221 substitute=9`. **605 sampled decisions, 191
carrying a pick+alternative pair.** Throughput ~49 rows/min, of which ~29% are decision-relevant and
~62% are pack coverage — pair yield per unit compute is now the metric to watch, since packs produce
most of the rows and none of the pairs.

## 4. Refit on 13,454 rows

```
train 10,534 (822 seeds) / holdout 2,920
within-decision model 0.503 (803 pairs, ci95 [0.469, 0.542]) | legacy dV 0.487
selection (pop) relative +0.127 | absolute +0.071 | legacy dV -0.042   (n = 1,160)
win-flip AUC    model 0.501 | legacy dV 0.583
scenario cells  hand type 2,327 labelled (1,818 with n>=3) | boss 933
```

Concordance went **down** from 0.538 — and that is the useful part. The decision-relevant pairs the
on-policy mode now samples are 48% exact label ties, which pulls a pairwise metric to chance; the
previous 0.538 was partly an artefact of which pairs coverage mode happened to sample.

## 5. The intervention test: 53.5%, and 48% of pairs cannot be won by anyone

`tools/fit_value_model.py` now reports this section directly from the rows (pooled over train+holdout
deliberately: the test uses no fitted quantity, so holding rows out would only cut `n` on the scarcest
rows in the corpus):

| bucket | n | worse / ties / better | sign_rate | mean Δ |
|---|---|---|---|---|
| `model_alt` in-window | 149 | 39 / 65 / 45 | **0.536** | +0.174 |
| `model_alt` out-window | 37 | 8 / 23 / 6 | 0.429 | +0.216 |
| `substitute` in-window | 5 | 0 / 3 / 2 | 1.0 | +3.200 |
| **all** | **193** | **47 / 92 / 54** | **0.535** | +0.306 [−0.23, 0.841] |

Two readings, both important:

1. **92 of 193 pairs (48%) are exact label ties** — the two candidate items measure *identical*. No
   ranker, however good, can gain there, and that is the region `margin` deliberately targets.
2. **Of the 101 pairs that differ, the head's preference is right 53.5% of the time**, with a CI that
   includes 0.5. That is the arm's edge per firing, measured directly instead of inferred.

This is the number that retro-explains five banks of screens: a rule that fires at 53.5% and converts
runs only when it fires produces net deltas of ±3 that drift around zero — which is exactly what was
observed (`m0` −4/350, `m02` +6/400 across banks C/D/E, `m05` +4/500, `m10` +3/250). No further screen
in this family will resolve anything; **the arm is at its ceiling because the model's ordering is a
coin flip on the only question the prior asks.** Meanwhile the model's population selection delta
(+0.127 vs legacy −0.042) is a real competence — applied to a question nobody is asking.

## 6. The screen (fresh bank E) and why it was still worth running

`11800–11899`, untouched, *with* the on-policy rows in the refit: V10 10/100 (ante-1 deaths 5, mean
ante 5.34, econ $14.9) | `m02` 9/100 (+2/−3, **−1**) | `m05` 8/100 (+2/−4, **−2**). It confirms the
prediction rather than contradicting it. As before: **no 300-seed bench** — the standing gate is a
≥20% belief, and the intervention test now says why the belief will not arrive from this family.

## 7. Reproduction (iteration 5)

```bash
# on-policy collection (the loop now does this by default; see tools/iterate.ps1)
python tools/collect_decisions.py --seed-start 47200 --n-seeds 500 --mode both \
    --time-budget-min 30 --workers 12 --candidate-mode onpolicy \
    --focus-file results/coverage_focus_iter2.json --focus-extra 3 --out-tag iter2

# refit: the `intervention` section is printed straight from the rows
python tools/fit_value_model.py --train <all train_*.jsonl> --holdout <all holdout_*.jsonl> \
    --out vendor/balatro-rl/balatro_sim/value_tables.json --report results/value_model_report_iter2.json

# fresh-bank screen
python bench/bench_v11_ablation.py --seeds 11800-11899 \
    --variants v12_prior_m02,v12_prior_m05 --workers 8 --out results/screen_v12_iter2_n100.json

# the whole loop, resumable, on-policy by default
powershell -NoProfile -ExecutionPolicy Bypass -File tools/iterate.ps1 -Iterations 8 -SkipScreen -Detached
```

## 8. What this iteration established

1. **The corpus now contains the decisions the arm acts on**, and the row schema says why each row
   exists (`role`), which is what makes the arm's own questions answerable offline.
2. **The arm's edge is 53.5% per firing, with 48% of its decision pairs provably un-winnable.** That
   single measurement explains the entire ±3 screen history and ends the value of screening in this
   family.
3. **The margin sweep was never the lever, and neither is data volume in the same shape.** The gate
   decides *how often* a coin flip is tossed; the constraint is that the head cannot separate near-tied
   candidates. Widening it multiplies chance-level decisions; narrowing it just does nothing.
4. **The clearest unexploited asset is the model's population selection delta** (+0.127). It knows
   which items are better *in general*, and that competence is currently spent on the one question it
   cannot answer. Redirecting it — toward shop-level quantity decisions (how much to spend, when to
   reroll, when to leave) rather than near-tie reordering — is where the next real gain has to come
   from, and it is a different instrument than any arm screened here.
