# V13: state-value learning with lookahead — design

Status: **proposal, not implemented.** Everything in §1 is measured on this repo's data today;
everything from §3 on is a plan.

The goal is a policy that wins >20% on the 10500–10799 bank (V10 = 14.0%, best measured arm ≈ 15%).
The claim of this document is that the current *framing* cannot get there, that four measurements say
so, and that a different framing is both better-founded and ~350× cheaper per unit of learning signal.

---

## 1. The four measurements that force a redesign

**1.1 Model capacity is not the bottleneck.** Fitting a gradient-boosted model (31 leaves) to the same
161 features the ridge head uses:

| model | holdout concordance | top1 pick | ctx_delta |
|---|---|---|---|
| ridge (incumbent) | 0.498 | 0.493 | +0.078 |
| GBM | 0.527 | 0.491 | +0.056 |
| GBM, within-decision centred labels | **0.534** | **0.509** | **+0.187** |
| legacy ΔV | 0.487 | — | — |
| *GBM **in-sample*** | *0.549* | | |

In-sample 0.549 vs out-of-sample 0.527: the gap is tiny, so a flexible model given these features
**cannot separate the pairs even when allowed to memorise the training set**. This is a
representation limit, not variance, not regularisation, and not data volume *in this shape*.

**1.2 The decision the model is asked to make is often unwinnable.** Of the 193 on-policy
(pick, alternative) pairs measured in iteration 5, **92 (48%) are exact label ties** — the two items
measure identical — and on the 101 that differ the head is right **53.5%** of the time. The prior fires
≈0.33×/seed *inside* that region. The whole family's ±3 net screen results follow arithmetically.

**1.3 Trajectory data is ~350× denser per unit of compute.** One run hands over **168 states** free
(68 SHOP, 55 SELECTING_HAND, 16 BLIND_SELECT, 15 ROUND_EVAL, 14 BOOSTER_OPEN), at 7.1 s/run
single-process → **~284 labelled states/s** at 12 workers, versus **1,468 rows per 30 min** from the
paired-fork collector. A fork buys one number for two rollouts; a trajectory buys 168 numbers for one.

**1.4 Shop transitions are free and RNG-free.** `buy(item)` on a deepcopy costs **1.67 ms** and leaves
the RNG object state identical. So "what if I buy item *i*" needs no rollout — which makes
decision-time lookahead over *all* affordable actions cost milliseconds instead of the ~4 s rollout per
candidate the current oracle pays.

Together: the agent is ~99% the V10 heuristic, the learned part only breaks ties, ties are
unbreakable, and it is paying the most expensive possible price to learn the least useful quantity.

**1.5 The failure structure says the same thing.** Deaths cluster at antes 2–3 and at the ante 5–8
wall — both are *scoring-power* problems. Scoring power comes from portfolio synergy, multiplicative
scaling, and deck fixing. None of these is expressible in a linear model over one item's features, and
none is a tie-break.

---

## 2. What is actually missing (the human-play gap)

Optimal human play at Red Deck / White Stake is built on three decisions this agent cannot represent:

1. **Commit to a plan early** (a hand type / a scaling axis) and let every later purchase serve it.
2. **Value items jointly**, not individually — the same joker is worth 4× next to its partner and ~0
   alone.
3. **Spend against a projected requirement** — the blind targets are known, so the question is "does
   this portfolio clear ante 6's boss", not "is this a good item".

Items 2 and 3 are *state* problems. Item 1 is a *conditioning* problem. The current model has no state
representation at all: it scores a candidate in a context vector but never values the portfolio.

---

## 3. Architecture

### 3.1 The learned object: `V(S)` over the whole state

`S` is encoded as entities, not as a flat context vector:

* **Owned jokers**: one vector per joker derived from the catalogue's parsed effect fields (already
  spec-derived, already used for features) — not a one-hot of the key.
* **Portfolio aggregation**: permutation-invariant pooling over jokers (sum + max + count, or a Deep
  Sets / attention encoder in torch, which is available at 2.13.0+cpu). This is what makes
  "Blueprint + Baron" learnable *without* a synergy table: the interaction lives in the pooling, and
  its weight is learned.
* **Consumables, hand levels, deck composition** (suit/rank histograms, enhancements, seals), slots,
  money, ante/blind/boss identity, and the spec-derived blind target.
* **Derived, RNG-free quantities the sim already computes**: projected best-hand score, best current
  hand type, whether the next boss is beatable (`forecast_beatable`) — these are free and highly
  informative, and they carry no tuned constants.

### 3.2 Target: dense return with bootstrapping

Terminal win/loss is far too sparse (86% of runs lose). Use a dense return built from quantities the
sim already exposes per blind (`chips_scored` vs the blind's own target) plus ante and the terminal
win — all spec-derived, no tuned weights. Then **bootstrap**: fit `V` on Monte-Carlo dense returns,
refit on `r + γV(S')` targets. Bootstrapping is what lets V be accurate near the ante 6–8 frontier,
where Monte-Carlo data is rarest.

### 3.3 Decision rule: lookahead, not a ranking of pre-filtered candidates

At a shop: enumerate **all** affordable actions (buy each item, reroll, leave), compute each `S'` by
transition (1.7 ms, no RNG), score `V(S')`, and take the argmax subject to an uncertainty gate (act
only when the advantage exceeds the model's own error bar — the discipline that has kept the baseline
safe). Reroll is the only stochastic transition; evaluate `E[V]` over a handful of sampled shop draws,
which is still milliseconds.

This removes two structural limits at once: the candidate set is no longer the heuristic's top-2, and
the objective is the value of the resulting *portfolio* rather than a per-item score.

### 3.4 Plan conditioning (the honest way to get "archetypes")

`V(S, h)` where `h` ranges over the game's own hand types (already enumerated by the sim and already
used for the `item|hand:<type>` scenario cells). The plan is then `argmax_h` of a shallow lookahead —
**learned, not typed**. This is exactly the generalisation of the scenario cells that already exist,
promoted from a residual term to a conditioning axis. A joker that is worthless for a Flush plan and
central to a Two-Pair plan becomes expressible.

### 3.5 On-policy iteration (the RL loop)

1. Collect trajectories with the current policy (~5 min for 500 runs / 84k states at 12 workers).
2. Fit `V` (and refit with bootstrapped targets).
3. Improve the policy with lookahead.
4. Repeat. Evaluate on untouched banks.

Approximate policy iteration, one cycle ≈ 15–25 min of CPU. The existing paired-fork collector is
**repurposed as an active-learning instrument**: fork only where `|V(a₁) − V(a₂)| < ε`, i.e. where V is
uncertain. That is a far better use of the most expensive data generator in the repo than uniform
coverage.

### 3.6 Where an LLM legitimately helps

* **Hypothesis generation with a measured gate.** Ask for candidate feature interactions and failure
  narratives; each becomes a *hypothesis* that must beat the incumbent on held-out pairs before it is
  kept. Knowledge injection with an empirical filter, never encoded as parameters.
* **Plan templates.** Propose plan axes in the game's own spec vocabulary (suit concentration,
  retrigger stacking, xMult timing); each becomes a conditioning axis whose value is *learned*.
  Templates that do not measurably help are dropped — the same status the hand-type cells have.
* **Trace critique** as a triage tool: feed a lost run and ask what strategic error occurred, to
  prioritise what to model next.
* **Not** proposed: baking LLM claims in as weights or tables. That is the failure mode this repo's
  magic-number gate exists to prevent.

---

## 4. Why this can plausibly clear 20%

* The learned component currently influences ~0.33 decisions/seed. Lookahead over all shop actions
  with a portfolio-aware `V` makes it the *primary* decision maker — a much larger share of the
  variance in outcome.
* The two structure-level deficits (joint valuation, planning) are exactly what the ante 2–3 deaths
  and the ante 5–8 wall are made of.
* The economics invert: training signal ~350× denser, decision evaluation ~2400× cheaper, so the loop
  iterates in minutes and can afford the search depth that was previously unaffordable.
* The measured population-selection competence (+0.127 ctx_delta, where the legacy heuristic is
  *negative*) says the signal to learn *which portfolios are better* is real; it has simply never been
  pointed at that question.

## 5. Staged plan, with stop rules

| stage | what | stop rule |
|---|---|---|
| S0 | Entity encoder + trajectory collector; fit `V` on ~500 runs | held-out rank correlation with dense return must clear a floor before any further work |
| S1 | **Offline validation against known forks**: replay the 86 iter2 seeds, reconstruct the decision states, score each candidate with `V(S')`, and compare the induced ranking to the *already-collected* fork labels | must beat the incumbent's 0.535 sign rate on the same pairs; if not, stop and report |
| S2 | Lookahead policy behind a flag, parity control off-path | dense metrics (mean ante, blind margin) improve beyond noise |
| S3 | Plan conditioning `V(S,h)` | ablation: conditioning must earn its cost |
| S4 | On-policy iteration; screens on untouched banks | 300-seed paired bench only at ≥20% belief |

S1 is the decisive gate and it is **nearly free**, which was verified rather than assumed: with only
`rollout` stubbed out (the collector's decision logic — sampling coins, focus forcing, candidate
selection — left exactly as it ran), replaying seeds 47200–47205 reproduced **26 of 26** `pick` rows
by `dec_id` *and* key, with identical `dec_id` sets. So for every one of the 330 `pick` + 221
`model_alt` + 9 `substitute` rows already on disk we can reconstruct the exact decision state, score
`V(S')` for each candidate, and compare the induced ranking against the fork labels that were bought
for that very decision. The redesign's make-or-break question can therefore be answered offline, in
minutes, before a single new behavioural screen is run.

## 6. Risks

* **Off-policy drift** — `V` is fit on states the current policy generates; lookahead then visits
  different states. Mitigation: on-policy iteration, and keep the incumbent as a fallback control.
* **Frontier starvation** — weak builds rarely reach ante 8, so `V` is least accurate where it matters
  most. Mitigation: TD bootstrapping, and prioritised collection at the frontier (the existing focus
  machinery).
* **Dense-reward gaming** — mitigated by keeping the terminal win in the return and reporting win rate
  as the only promotion criterion.
* **Set encoder overfits with ~84k states** — mitigated by starting with pooled aggregates + GBM
  (known-good on tabular data of this size) and only moving to torch if it measurably wins.
* **Hand-play ceiling** — the base policy for playing hands stays V10; if the win-rate gain stalls
  while shop decisions stop being the bottleneck, the next axis is play/discard decisions, which the
  same `V` can rank by one-step lookahead.

## 7. Invariants this keeps

Human-fairness and seed-exactness (all instrumentation read-only; buy-transitions verified RNG-free);
no typed tables (all learned weights live in the artifact, enforced by the magic-number gate); the
frozen baselines stay frozen; no 300-seed claim below the belief gate.
