# V14 Offline Evaluator Implementation Plan

> **For agentic workers:** Use subagent-driven-development or executing-plans task-by-task. No commits without user authorization.

**Goal:** Build a standalone simulator-supervised P(clear) evaluator and honest offline ranking report, without changing live policies.

**Architecture:** Observable post-state encoding, small multi-head torch evaluator, sampled exact transitions, raw continuation outcomes, seed-grouped training and cluster-bootstrap evaluation. P(clear) alone ranks actions; all other heads remain separate.

**Tech Stack:** Python, existing CPU torch/numpy, optional existing sklearn controls, pytest.

**Spec:** ../specs/2026-09-16-v14-inblind-evaluator-design.md

## Correctness amendments discovered during implementation planning

The earlier spec has unsafe assumptions; these amendments take precedence.
- Reseeding after step leaves hidden draw order in both post-state and labels. Sample a canonicalized undrawn pile and install a fresh seed-mode RNG BEFORE each candidate step. Retain one observable post-state and outcome per sample. Action estimate is mean P(clear) over sampled post-states, not one privileged successor. This is stochastic one-step offline evaluation, not live search.
- Initial implementation excludes decision roots with flipped cards/jokers; stop and mark continuation censored if H10 reaches hidden observations. Frozen H10 accesses full game state, so masking only the network is insufficient to claim human-fair continuation behavior. Report eligibility/censoring; never turn censored trials into failures. Coverage/generalization claims apply only to this supported domain.
- Runtime numeric fields need a name-indexed explicit allowlist, not truncated sorted values with changing meanings. Unknown fields are counted, not silently interpreted; nonnumeric mechanics remain a documented representation limitation.
- Mask every attribute of flipped entities. Composition invariance tests preserve known multiset while permuting hidden allocations.
- Sampled world index, actual seed, action indices, complete raw outcome, policy/config fingerprints must be retained. Same seeds are only a coupling proposal. Report empirical correlation and variance ratio with independent trials.
- K=10 is configurable, not justified by unmeasured latency; benchmark before large collection. K=5 is a smoke/ablation budget, not precise probabilities.
- Evaluation requires **K >= 2 with disjoint selection/evaluation halves**: even `sample_index` values are the selection half, odd indices the evaluation half (`split_world_parity_v1`, `SELECTION_RULE` in `eval_metrics.py`); a same-world fallback is forbidden, `validate_row` enforces unique non-None `(sample_index, seed)` per arm, and the collector declares `config.samples` in the JSONL header. Note that sub-K10 estimates remain noisy — report counts, CIs, and the `evaluation_protocol`/`selection_rule` protocol fields with every result; never present a small-K ranking as precise.
- Train on raw Bernoulli outcomes; each sample's post-state corresponds to its own outcome. Do not attach an arm-average label to a different sampled post-state.
- Do not clip score ratios at four. Use log1p ratios, monotone quantiles. Median exceedance is not a probability estimate.
- P(clear) is sole ranking objective. Ranking loss is optional/off initially, uses within-decision contrasts, and requires an ablation.
- Do not use empirical-zero SE to declare noisy small-K labels certain. Report unfiltered paired improvement and cluster CIs; ambiguous ties are not errors. Reference-pool maxima are optimistic finite-sample proxies, not legal-action oracles.
- Seed 60000/61000 ranges were previously used for smoke work. Use a versioned split by seed hash, no claim of freshness without provenance audit. Test remains separate from tuning.
- Attention parameter count must be computed, not asserted as 0.9M. No requirement to inflate a smaller adequate model.
- Scientific gate can be INCONCLUSIVE. Smoke success is never evaluator success; count independent test seeds and at least 200 informative decisions before positive ranking claims.

## File ownership and interfaces

- `balatro_sim/eval_encoder.py`: `encode_state(game) -> dict`, `schema() -> dict`, `flatten_state(encoded) -> list[float]`; fixed-width context, variable `cards` and ordered `jokers` numeric rows.
- `balatro_sim/evaluator.py`: `EvaluatorConfig`, `StructuredEvaluator(config)`, `collate_states(states) -> dict[str, Tensor]`, forward returns `clear_logit`, `quantiles`, `horizon_logits`, `dense`, `final_ante`, `win_logit`; `evaluator_loss(outputs, targets)`.
- `balatro_sim/blind_dataset.py`: candidate generation, sampled-world construction, collect decision trials, seed split, schema/provenance and resumable JSONL reading/writing helpers.
- `tools/collect_blind_decisions.py`: CLI collector, time/sample/step caps, raw JSONL plus collection/coverage/coupling report.
- `tools/fit_evaluator.py`: torch training plus flat MLP/HistGBM controls, train-only normalization, validated checkpoint and manifest.
- `tools/validate_evaluator.py`: predictions grouped by seed/decision/action; bootstrap advantage, tie-aware ranking/regret, probability/quantile metrics, gate verdict.
- `balatro_sim/eval_metrics.py`: pure numerical reporting helpers.
- Tests: `vendor/balatro-rl/tests/test_eval_encoder.py`, `test_evaluator.py`, `test_blind_dataset.py`, `test_eval_metrics.py`.

## Task 1: Encoder and evaluator
- [ ] Write tests before implementation: full-state/RNG pickle fingerprint unchanged; reversed deck identical encoding; replaced RNG identical encoding; card IDs absent; hidden slots fully masked; dynamic hand size; explicit joker position; consumable strings; state field identity; finite inputs; padding invariance; finite loss/backprop; quantiles monotone; parameter cap.
- [ ] Run `python -m pytest vendor/balatro-rl/tests/test_eval_encoder.py vendor/balatro-rl/tests/test_evaluator.py -q` and record expected missing-module failure.
- [ ] Implement the stated interfaces using catalogue mechanics, actual deck+hand+spent, fixed context and named numeric joker fields. Encode rank/suit/debuff/seal/enhancement/edition and bonus chips without runtime IDs. Include per-pile composition and played/run hand histories where observable.
- [ ] Rerun tests; verify torch forward/backprop and checkpoint round trip.

## Task 2: Fork data pipeline
- [ ] Write tests: repeated seed identical trials, parent unchanged, permuted undrawn pile same sampled worlds, different seeds change worlds, duplicate actions absent, unsupported anchors skipped not replaced, anchor decide once, terminal clear/failure and truncation distinguished, partial resume rejected/recovered correctly, disjoint seed split.
- [ ] Run `python -m pytest vendor/balatro-rl/tests/test_blind_dataset.py -q` before implementing.
- [ ] Implement `candidate_actions(game, anchor, extended=False)`, `sample_world(game, seed)`, `collect_decision(game, anchor, seeds, max_steps, terminal=False)` and raw schema below. H10 parameters are snapshotted/restored around offline calls. Refuse hidden roots; censor hidden continuation states.
- [ ] CLI calls H10 once on main trajectory and executes same action. Candidate enumeration uses isolated forks. Full action payload participates in dedupe, preserve played-card ordering. Extended pool includes candidate set, diverse plays, singles and expanded discards; label all with same K and separate heldout repetitions when budget permits.
- [ ] Add bounded real smoke and coupling experiment with independently sampled arm seeds. No variance reduction claim without evidence.

## Shared row contract

```json
{"version":1,"seed":70000,"decision_id":0,"split":"train","ante":1,"blind_idx":0,"anchor":0,"arms":[{"action":{"type":"play","cards":[0]},"source":"anchor","trials":[{"seed":"v14:70000:0:0","state":{"context":[],"cards":[],"jokers":[]},"clear":true,"score":350,"target":300,"steps":2,"censored":false,"terminal":null}]}]}
```

`terminal` when available: `{ "won": false, "final_ante": 3, "dense": 3, "horizons": [true,true,false], "censored": false }`. Store origin ante for horizons; beyond ante 8 is explicitly unattainable (not endless); ante 9 terminal means win, not playable ante 9. Censored clear is null, score can be partial diagnostic only. Header includes encoder schema, policy params/code fingerprints, world sampler version, RNG mode, collection settings and seed manifest.

## Task 3: Fitter and metrics
- [ ] Write numerical tests: bootstrap clusters seeds not rows; tie predictions/labels handled explicitly; all-tie data INCONCLUSIVE; chosen-action improvement computed paired per decision; unknown/missing/censored labels masked; no heldout-seed overlap; train normalization excludes validation/test.
- [ ] Run `python -m pytest vendor/balatro-rl/tests/test_eval_metrics.py -q` before implementing.
- [ ] Implement Bernoulli BCE, raw log1p pinball, masked terminal auxiliary objectives, optional pairwise loss default zero. Use grouped batches and per-decision weighting; checkpoint selection uses validation BCE only in first version.
- [ ] Implement flat MLP and optional HistGBM controls with identical usable samples; preserve missing terminal labels via masks, never fill as failures. Save model config, schema, training seed IDs, normalization and environment versions.
- [ ] Metrics: mean paired clear advantage over anchor with seed-bootstrap 95% CI; tie-aware top-set accuracy, pairwise preference, candidate-relative regret/normalized regret, Brier on raw outcomes, reliability bins, quantile coverage, masked terminal errors. Report counts and value-gap buckets. Coverage explicitly refers to extended reference pool; report top1/top3 inclusion and regret with tie handling.

## Task 4: Verification and offline experiment
- [ ] Run new tests plus full documented vendor pytest suites and ci_gate, then four static audits.
- [ ] Check available lint/typecheck configuration; run declared commands, otherwise ask user rather than inventing a successful gate.
- [ ] Run bounded collect -> fit -> validate smoke using explicit output paths under approved temporary directory or results directory. Record measured latencies and exact sample counts; do not launch hours of collection before Gate 1 passes.
- [ ] Independent review for information leakage, stochastic transition averaging, H10 state/global purity, target alignment and gate validity. Fix findings with regression tests.
- [ ] If evidence volume insufficient, report INCONCLUSIVE and exact next collection command. Do not claim scientific gate passed from plumbing checks or silently expand scope.

## Scope and completion

No agent_v14, no online policy changes, no shop evaluator, no MCTS/beam/full-game search, no strategy-conditioned head, no commits. Legacy artifacts are not overwritten. Existing staged .gitignore belongs to user. Work is complete only when delivered pieces and actually executed evidence are distinguished from remaining experiments.
