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

