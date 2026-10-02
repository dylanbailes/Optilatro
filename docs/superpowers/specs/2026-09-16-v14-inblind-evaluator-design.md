# V14 Design: In-blind structured evaluator (first offline gate)

Status: **approved design, 2026-09-16.** Scope: offline evaluator + evidence; no
agent integration. Companion to [docs/STATUS.md](../../STATUS.md) (V13 S0/S1
record) and [v13-state-value-design-2026-09-12.md](v13-state-value-design-2026-09-12.md).

---

## 1. Revised objective

Learn a calibrated, multi-head evaluator of **post-action in-blind states under a
frozen continuation policy**:

    V̂_θ(S') ≈ V_H10(S') = E[ · | S', continue with frozen HeuristicV10, average future randomness ]

Action evaluation is induced, not learned end-to-end: Q̂(S,a) := V̂_θ(T(S,a)),
where T is the **exact simulator transition** (fork → step). Division of labor:

- Simulator: *what state results from action a?* (exact, incl. RNG consequences)
- Evaluator: *how good is that state under H10?* (learned, probabilistic, interpretable heads)
- Search (future work): *what to do about it.*

**Primary prediction/ranking target: `P(clear)`** — probability the current
blind is cleared from S' under H10. Secondary: score/target quantiles,
P(reach ante+1/2/3). Diagnostic: dense return, final ante, win. Heads are never
collapsed into one scalar in V14; per-head diagnostics determine what the model
actually learns.

The policy-conditioned framing is a *feature* for V14 (it measures the marginal
effect of an action given how we actually continue); its limitation — it cannot
value states whose strategy H10 cannot execute — is recorded in §18 and
addressed by on-policy iteration in future work.

## 2. Architecture

| Component | Choice |
|---|---|
| Encoder | Entity-token transformer: held cards + ordered jokers + blind context token → 2 self-attention layers, d_model=128, 4 heads, FFN 256, pre-LN |
| Parameter budget | ~0.9M (soft cap 5M hard) |
| Heads | See §8 |
| Controls (same data, same split) | (a) HistGBM on flattened features, (b) MLP on flattened features, (c) mean-pooled token encoder (no attention) |

Self-attention is not sacred: the ablation matrix (§17) tests whether structured
attention beats pooling. V13's S0 showed pooled features + GBM already achieve
seed-spearman 0.808 at run level, so "structure adds nothing over pooling" is a
live null hypothesis. Torch CPU is already in CI; runtime inference follows the
existing numpy-export pattern (V11) when integration comes.

## 3. State representation

All inputs are **observable-at-decision-time only**. Schema is an explicit
allowlist, pinned by test.

**Held cards** (up to hand_size tokens): rank, suit, enhancement, edition, seal
embeddings + scalars (debuffed, flipped-mask, Hiker bonus chips). **Flipped
cards are masked** (face-down token, no rank/suit) — human-fair. Card `id` is
**excluded** (process-global counter; leaks history order).

**Jokers** (ordered tokens): catalogue spec vector (46-d) + edition embedding +
**slot-position embedding** + runtime numerics from `j.state` (up to N numeric
fields, sorted by name, padded — carries scaling counters).

**Blind/run context**: log blind target, chips scored, chips/target,
hands_left, discards_left, ante, money, boss embedding (~28+none),
played-hand-types-this-round (multihot), planet_levels (12-d), vouchers
(multihot), consumables held (kind + key-spec), slot counts, hand size.

**Deck composition** (corrected source `deck + hand + spent`): 52-dim rank×suit
counts, enhancement/seal/edition aggregates, face fraction (computed correctly —
V13's `is_face_card()` call bug avoided), deck size.

**Leakage allowlist:** no deck *order*, no RNG state, no `next_boss_key`, no
future shop, no card ids, no continuation outcomes. Deck *composition* is
human-fair-legal.

## 4. Candidate generation

Per decision point (SELECTING_HAND), arms:

1. **Anchor**: the frozen policy's chosen action, computed **exactly once**
   (fixes the recorded double-`decide()` defect; the main game executes this
   same action).
2. **Plays**: top-5 valid plays from `scored_plays` (boss-filtered),
   **diversity-capped: ≤2 per hand type**, then next-best distinct types. Drops
   exact duplicate index-tuples.
3. **Discards** (when discards_left > 0): V10's best-EV discard + one "dig"
   discard (lowest structure value) — 2 arms.
4. Hard cap ≤8 arms; dedupe identical (type, indices) — including
   anchor-vs-play collapse.

Enumeration is composition-legal (scored_plays / discard-EV are human-fair) so
the future search integration can reproduce the same candidate set online.

## 5. Simulator fork protocol

For each arm: `fork = clone_game(game)` (deepcopy, 1–4 ms, RNG fully
independent), then `fork.step(arm_action)`, then encode S'. Transitions are
engine-exact regardless of which RNG nodes the action consumes. Fork
independence is an executable Gate-1 check. The main game is untouched by arm
enumeration (RNG-fingerprint check; `eval_hand_score` already uses a throwaway
RNG).

## 6. Continuation / label methodology

- **K=10 continuations per arm** (default), rolling each fork **to blind
  resolution only** → P̂(clear), score/target. Cost ≈ 30–150 ms each →
  ~2.5–12 s per decision point; 12 workers; time-budgeted, resumable.
- **Per-continuation raw outcomes retained** (`clear_k`, `score_k`, `target_k`,
  `ratio_k`, seed string, steps). Aggregates derived at fit time, never stored
  as the source of truth. K, estimators, pairing analysis re-decidable.
- **Terminal subset** (auxiliary heads only): every 8th decision, anchor arm
  only, K=2 continuations to GAME_OVER → win, final_ante, dense return
  (`ante_final + 8·won`).
- **K justification**: ranking is paired-comparison based; blind-resolution
  rollouts are cheap enough that K=10 (0.1 granularity) costs little more than
  K=5. Gates filter on **minimum label gap = 2× paired SE** (from retained raw
  outcomes). Fallback: K=5 + gap filter.
- **Decision-point sampling**: all decisions at antes 1–2; first 2 per blind at
  antes 3–5; first per blind at antes 6–8. Target ≈ 2,500–10k decisions from
  500 seeds.

## 7. RNG / CRN methodology — measured, not assumed

- Continuation seed strings derived per decision+k (`"{seed}:{dec_id}:k{k}"`),
  installed into all arms **after** fork+step, so node streams start
  synchronized. **The actual seed string is stored per continuation.**
- Executable verification (Gate 1 → `crn_report.json`):
  1. **Reproducibility**: identical state + seed → identical outcome.
  2. **Cross-arm coupling**: same seed, different post-action states → outcome
     correlation ρ across arms.
  3. **Variance test**: Var(Δ̂ shared) vs Var(Δ̂ independent) via split-half
     over k; report the variance-reduction factor.
- Decision rule: if ρ is materially positive, paired contrasts use pairing; if
  not, the design **says so** and treats continuations as independent samples.
  No CRN claim survives without the measurement.

## 8. Model and heads

| Head | Output | Training | Evaluation |
|---|---|---|---|
| **P(clear)** (primary) | Bernoulli p | Soft-target BCE on arm frequencies (binomial likelihood) | **Primary ranking signal**; Brier + calibration |
| Score/target quantiles Q10/25/50/75/90 | pinball on raw per-continuation ratios (log, clipped at 4) | Secondary; teaches spread | Quantile coverage; Q50 as secondary signal |
| P(reach ante+1/2/3) | Bernoulli | Auxiliary, anchor-terminal subset | Consistency + horizon calibration; **not** ranking input |
| Dense V / final ante / win | MSE / CE | Diagnostic, anchor-terminal subset | Run-quality diagnostics |

Head-consistency diagnostics: P(clear) vs P(Q50 ratio ≥ 1); monotonicity
P(ante+1) ≥ P(ante+2) ≥ P(ante+3); per-ante calibration curves.

## 9. Loss

    L = w_c L_clear + w_q L_quantile + w_h L_horizon + w_v L_value + w_r L_rank

Defaults w = (1.0, 0.3, 0.1, 0.1, 0.3), selected on val seeds.

**Pairwise ranking loss included, modularly**: within-decision pairs (i,j),
logistic loss on P(clear)-head logits, label = sign of ΔP̂, weighted by
`min(1, |Δ̂| / paired_SE)` (noise gate from raw outcomes; ties excluded).
Auxiliary only — an ablation (rank off) must show the ranking gate survives
without it.

## 10. Dataset schema

JSONL, one row per decision; arms as sub-records. Per arm: action (type +
indices), arm source (`anchor|play|discard`), hand type, S' tokens
(held-card tuples, joker tuples incl. state numerics + slot index, context
scalars, deck histograms), raw continuations
`[{k, seed_str, cleared, score, ratio, steps}]`. Per decision: seed, dec_id,
ante, blind_idx, boss, incumbent action, candidate metadata, terminal subset
outcomes if collected. Metadata: sim + collector versions, catalogue
fingerprint, **verbatim H10 param dict**, seed bank, K. No pickled states.

## 11. Train / validation / test split

Seed-grouped: 500 fresh seeds ≥ 60000 → 350 train / 75 val / 75 test. All
model selection on val; test touched once per gate report. Smoke collection
(5 seeds) is part of train.

## 12. Candidate coverage metrics (Gate 2 — reported, not gated)

On a 10% decision subsample, an **extended reference pool** (full scored_plays
window ~14 combos + all valid singles + 4 discards, K=3 continuations each)
approximates "best legal action." Exhaustive enumeration is infeasible
(~218 combos × K × rollout); the pool is still priority-pruned — documented
approximation. Metrics: **oracle top-1 coverage**, **oracle top-k** (k=3),
**candidate regret** R = V̂(best in pool) − V̂(best candidate), distribution +
per-ante breakdown. Separates candidate-generation quality from evaluator
ranking quality.

## 13. Evaluator ranking metrics (Gate 3 — decisive)

Primary question: **does the evaluator rank candidate actions better than the
incumbent on unseen seeds?**

- **Top-1 accuracy** (non-tied only; tie rate reported; ties never failures).
- **Pairwise preference accuracy** on non-tied within-decision pairs.
- **Paired regret**: label-best − label-of-model-choice (P(clear) points);
  **normalized regret** = regret / (label-best − label-worst).
- **Baselines**: incumbent anchor choice; scored_plays order; random arm.
- **Breakdowns**: value-gap buckets, ante, boss, arm type.
- **Uncertainty**: cluster bootstrap over **seeds** → 95% CIs.

Minimum evidence bar: ≥200 non-tied held-out decisions; model CI excluding the
incumbent baseline. Controls (HistGBM/MLP/pooled) on the **same pairs**.

## 14. Calibration / value metrics (secondary diagnostics)

Brier for P(clear) vs empirical arm frequencies; reliability curves per ante;
quantile coverage per Q; value-head error vs dense anchor labels; breakdowns
(boss class, hands_left, money band).

## 15. Offline gates

**Gate 1 — Pipeline validity** (all executable, blocking): zero dropped layout
columns; encoder deterministic + RNG-free + non-mutating; **leakage audit**
(schema allowlist; flipped-mask; no ids); label completeness; **arm pairing
integrity** (anchor recorded == action executed, computed once); no duplicate
arms; fork independence; continuation reproducibility; CRN report.

**Gate 2 — Candidate coverage**: reported (top-1/top-k, regret). *Investigate*
thresholds (e.g., top-1 < 70%) trigger arm-set revision before trusting
Gate 3 — a soft stop.

**Gate 3 — Evaluator ranking** (decisive): §13 on test seeds vs baselines with
seed-clustered CIs.

Order is causal: Gate 1 → data trustworthy; Gate 2 → arms contain the answer;
Gate 3 → model finds it.

## 16. Statistical confidence

Seed-level cluster bootstrap everywhere; no metric without a CI; selection
logged with val evidence; no architecture conclusion from <300 non-tied
held-out decisions (V13 small-corpus lesson).

## 17. Ablations

(A1) attention vs mean-pool encoder; (A2) vs HistGBM; (A3) vs MLP;
(A4) rank loss on/off; (A5) K sensitivity from raw outcomes (also completes
the V13 split-half label-noise measurement); (A6) multi-task vs P(clear)-only.

## 18. Failure diagnosis (pre-registered)

- **Gate 2 low, Gate 3 high** → widen arms before any agent work.
- **Gate 3 at chance, calibration good** → representation or volume; check
  A1–A3; if all tie at chance with >300 pairs, stop and report (doctrine).
- **Gate 3 passes offline only** → off-policy mismatch; on-policy iteration is
  the future fix.
- **Ranking good, quantiles miscalibrated** → suppress quantiles from decision
  rules; keep as diagnostics.
- **Known bias**: V_H10 conditions on the frozen policy; improved continuation
  policy shifts the target (on-policy iteration, future work).
- **Known ceiling**: labels value the blind; cross-blind effects visible only
  via anchor-terminal subset → horizon heads stay diagnostic until terminal
  labels scale up.

## 19. Implementation plan

| # | Deliverable | Stop rule |
|---|---|---|
| 1 | `balatro_sim/eval_encoder.py` + `tests/test_eval_encoder.py` | tests green; suite + ci_gate green |
| 2 | `tools/collect_blind_decisions.py` + 5-seed smoke + `collection_report.json` (Gate 1 + CRN) | Gate 1 clean |
| 3 | Coverage diagnostic mode → `coverage_report.json` | Gate 2 reported (soft) |
| 4 | `tools/fit_evaluator.py` (torch + HistGBM/MLP/pooled controls) | converges; artifacts + metrics |
| 5 | `tools/validate_evaluator.py` → Gate 3 report | verdict in `docs/` + STATUS entry |

Compute: smoke ≈ 10 min; main collection ≈ 1–2 h budgeted/resumable on 12
workers; training minutes; gates minutes. Seed banks: 60000–60499 only;
behavioral screens (future) ≥ 61000. Artifacts under `results/evaluator/`;
no `agent_v14`, no policy changes, live sim untouched (forks only).
