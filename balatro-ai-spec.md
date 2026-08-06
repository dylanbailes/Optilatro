# Balatro AI Optimizer — Project Specification

**Status:** Draft v1 — interview-complete, pre-implementation
**Date:** 2026-08-06
**Root cause / goal:** Build a lightweight system that plays Balatro with the goal of **maximizing ante-8 win rate** (base game, no Endless).
**Route (decided):** Headless simulator-first. Train/experiment in a fast pure-Python sim, verify against the real game via a Steamodded mod in a final live phase.

---

## 0. Interview summary (decisions locked in)

| Topic | Decision |
|---|---|
| Architecture route | **Headless sim-first**; live game used only for final verification (modding is acceptable) |
| Stack | **Pure Python** (no Rust). Accuracy of the sim is stated as *vital*. |
| Sim starting point | **balatro-rl's `balatro_sim`** (audited, 496 passing tests, 164 jokers, boss blinds, vouchers, spectrals already implemented) as the base; **port balatro-seed's RNG to Python** from balatro-rs |
| Scope | Boss blinds (must-have), Vouchers, Spectral (Soul first, then rest), joker allow-list. **No Endless, no higher stakes** — Red Deck / White Stake, antes 1–8 |
| Success bar | **Staged targets** (beat baselines → meaningful win rate → approach human) |
| Evaluation | **All three, staged**: (1) seed-exact replay-diff, (2) statistical win rate over random seeds, (3) live-game verification |
| Search philosophy | **Hybrid: search locally, learn globally** — exact/exhaustive search for in-blind decisions, learned + searched strategy for shop/econ |
| Graph/theory interest | State canonicalization → **DAG search**; **bounds-based pruning / beam search**; **joker-synergy graph / action abstraction**; **Gumbel MuZero / sparse Gumbel MCTS** core with limited simulation budgets |
| Seed solver | **No** — a general policy that plays any random run; seed tooling is only a debugging/verification aid |
| Latency | No hard real-time constraint, but **throughput profiling per step is a design requirement** (it drives training time) |
| Game version | Pin to the version **balatro-rl's tested sim/mod were verified against** |
| Hardware | Ryzen 7 2700 (8c/16t), RX 570 (8GB), 16GB-class RAM; CPU-parallel search favored over heavy GPU RL |
| Deliverable | Research repo rooted at **D:\Optilatro** (this repo) |
| RL/search experience | Comfortable with RL/MCTS theory — spec can go deep |

---

## 1. Objective & success criteria

Maximize **ante-8 completion rate on Red Deck / White Stake** (antes 1–8, 24 blinds). Staged success bars:

- **Stage A — pipeline correct:** Random-play baseline reproduced; seed-exact replay harness green; sim audited against real-game captures.
- **Stage B — beats prior art:** Defeat the documented RL baseline (**2.35% win rate**, balatro-rl V7) by a clear margin (≥10%).
- **Stage C — strong:** ≥ 30–50% ante-8 win rate (approaching the ~70% skilled-human reference on White Stake).
- **Stage D — live-verified:** The same decision engine plays the real game via mod, and live win rate agrees with sim within tolerance.

Win rate is always measured on **random seeds** (never a fixed seed set — fixed seeds caused inflated fake results in balatro-rl V4).

---

## 2. Route decision: simulation-first, live-verify-last

**Recommendation (confirmed with user): full simulation to train, real game to verify.**

Evidence from prior art:

- **Training throughput:** live-game training (file/socket IPC via Lua mod) topped out at ~14 steps/s and **degraded over time due to Lua GC/RAM issues** (balatro-rl V1–V3). A pure-Python sim reaches ~1,000–1,500 steps/s single-process and parallelizes trivially (V4–V7). That is a **~70–100× training-data advantage**.
- **Determinism:** a sim gives reproducible states for debugging, replay-diff, and auditing. The live game cannot be replayed.
- **Sim fidelity is the compensating risk** — it must be treated as the #1 engineering priority (Section 4).

Live component (Phase M5, optional-but-planned): a **Steamodded + lovely-injector** mod streams full game state (BalatRobot pattern), the Python decision engine plays the real game, and outcomes are compared against sim predictions. This also generates ground-truth captures for the replay-diff harness.

---

## 3. Stack & environment

- **Python 3.11** (installed). Deps: `numpy`, `torch` (CPU-capable), `gymnasium`, `pytest`, `numba` (optional JIT for hot loops), `maturin`/`rust` **only if** we later want to call balatro-rs directly (not required for v1).
- **balatro-rl `balatro_sim`** vendored into `vendor/balatro-rl/` — base simulator.
- **balatro-rs** used as a **reference source of truth** (read its `core/src` and `balatro-seed` for scoring formulas and the exact per-node RNG algorithm to port). Installing `rustup` is optional; reading the source in the repo is sufficient for the port.
- **Hardware strategy:** MCTS rollouts and sims parallelize across the 16 CPU threads; model inference on small MLPs is CPU-friendly; the RX 570 can train small networks if GPU training is ever desired. **Design for CPU-first.**

---

## 4. Simulator strategy (accuracy is vital)

### 4.1 Starting point

Use **balatro-rl's `balatro_sim`** as the base rather than balatro-rs's core:

- It already implements the mechanics that balatro-rs is still missing: **15 boss blind effects, 18 spectral cards, 27 vouchers, 164 fully audited jokers, 12 planets, 22 tarots** — with a **496-test suite**.
- It was audited in the V6 audit (which fixed ~32 incorrect joker implementations and caught the infamous broken Burglar joker that produced fake 612M-chip Pairs).
- Caveat to verify in M1: confirm exactly what the tested version covers, and re-run the full test suite in our repo immediately after vendoring.

### 4.2 The two accuracy axes (both required)

**Axis 1 — Deterministic scoring/mechanics correctness.** Poker-hand identification, chip/mult computation, joker/tarot/planet effects, boss blind effects, shop economy. Mitigations:

- Keep and extend the balatro-rl test suite (496 tests) as the regression base.
- **Cross-validate scoring against balatro-rs's `calc` CLI** on a corpus of hand+board states (balatro-rs core implements scoring/play/discard and is a good oracle for the overlap).
- **Replay-diff harness:** capture real-game state sequences (via the live mod or balatro-rs's recorded outputs), replay them through the Python sim, and diff scores/outcomes. Add captures for every mechanic added.

**Axis 2 — RNG/seed exactness.** Balatro does **not** use one global RNG stream. It uses a **per-node LuaRandom** system: each RNG-consuming event type draws from its own hash-derived stream keyed by an identifier, with a per-node call counter (pseudohash). Every new effect that consumes randomness must call the **same node key with the same call sequence, in the same relative order** as the real game, or it produces plausible-looking but seed-inaccurate results — a bug casual checks won't catch.

Plan:

1. **Port `balatro-seed`'s per-node LuaRandom algorithm to Python** (user decision). Do **not** invent the node-key/call-sequence pattern per effect — mirror what balatro-rs's verified implementation does, effect by effect.
2. **Two RNG modes behind one interface:**
   - `FastRng` (generic PRNG) for bulk self-play — statistically correct distributions, no exactness needed.
   - `SeedRng` (ported per-node LuaRandom) for the seed-exact replay harness and any debugging.
   Every random effect is written once and takes the RNG source as a parameter, so training is never blocked on bit-exactness — only the benchmark path is.
3. **Bit-exact tests:** for a battery of seeds, diff specific random outcomes (e.g., *which cards Immolate destroys*, which boss is drawn per ante, shop/pack contents, Wheel-of-Fortune hits) against real-game or balatro-rs outputs. Also verify **boss blind selection** comes out of the RNG port (balatro-rs's "verified ante-by-ante" description suggests seed→boss prediction already works — confirm and reuse rather than reverse-engineering).

### 4.3 Coverage policy

- **Joker allow-list config:** the shop/pack generator only produces jokers the sim implements. Coverage grows incrementally; the list is a single config point (mirrors balatro-rl's banned-joker filter pattern).
- **Order of coverage work (v1):** boss blinds (already in base — audit) → vouchers (already in base — audit) → Soul/spectral edge cases → grow joker allow-list toward 164.
- **Version pin:** record the exact Balatro version the base sim targets; do not silently update.

---

## 5. Decision-engine architecture (hybrid: search locally, learn globally)

### 5.1 Problem structure (why the hybrid split)

- **In-blind decisions** (which cards to play/discard, card order, joker order): combinatorial but *exactly solvable at small cost* — the hand is ≤8 cards, the deck is a **known multiset** (we track every addition/removal; only its order is hidden), and scoring is deterministic given a determinized draw.
- **Shop/econ/strategy decisions** (buy/sell/reroll/skip/pack choice): the *long-horizon* problem (a joker bought in ante 1 pays off in ante 6). This is where search + learned value earn their keep.

### 5.2 Layer 1 — Exact local solver (in-blind)

- Enumerate play subsets (≤ C(8,5) = 56) and discard subsets; score each deterministically with the current jokers.
- **Joker ordering:** find the optimal ordering by a bounded local permutation search (≤ 5! = 120 orderings per score; cache aggressively). Canonicalize the ordering for state keys.
- **Branch-and-bound:** score candidates in order of an admissible upper bound (best-case scoring); prune dominated subsets.
- Expected cost: well under a millisecond per decision — this layer is never the bottleneck, and it makes the "learned card selection" of balatro-rl V7 unnecessary (a strong simplification: V7's hierarchical intent+subset head exists precisely because they lacked an exact solver).

### 5.3 Layer 2 — Determinization (hidden deck order)

Because the deck multiset is known, the hidden state is only the shuffle:

- **PIMC-style determinization:** sample a shuffle; under that determinization the game is fully observable and searchable.
- The RNG port (Section 4.2) makes each determinization consistent with the seed when exactness is required; the generic PRNG suffices for training.
- Distributional reasoning is also available: the probability of drawing a given 5-card subset next hand is multivariate-hypergeometric over the known multiset → usable as an admissible future-score bound.

### 5.4 Layer 3 — Gumbel MCTS (the search core)

The core tree search is **Gumbel MuZero / Gumbel AlphaZero-style**, chosen for exactly the constraint the user flagged: it guarantees policy improvement even at **very limited simulation budgets** (m = min(n, 16) candidate actions per node — single-digit-to-teens simulations, not hundreds), and its sampled variant keeps a **~50-way shop branching factor** tractable.

- **Gumbel-top-k action sampling:** at each node, sample m candidate actions according to the current policy prior instead of expanding all children.
- **Sparse expansion:** shop decisions are evaluated over k sampled candidates (buy item i / reroll / buy voucher / buy pack / leave), not all ~50.
- **Value + policy priors:** initially a scripted heuristic (Section 5.6); progressively replaced by a learned small network (Section 6).
- **Progressive simulation budget:** cheap simulations early in training, growing only once the policy is worth the compute (per the user's research note).
- **Implementation strategy:** prefer adopting a vetted lightweight open sparse-Gumbel-MCTS implementation over reimplementing PUCT+Gumbel from scratch (the user identified one with a reported 2–20× speedup on large action spaces — **vet its license and quality in M0 before adopting**; if none are acceptable, fall back to implementing Gumbel MuZero from the published pseudocode). Alternatives if Gumbel proves heavier than needed: plain UCT + determinization, or OpenSpiel-style sparse sampling.

### 5.5 Layer 4 — Graph/node-theory optimizations (the "connected tree")

Four techniques, all in scope per the interview:

1. **State canonicalization → DAG search.** A Balatro state is mostly *symmetric*: card multisets, joker multisets, scalar economy. Define a canonical key — sorted hand-card tuple, deck-multiset hash, joker multiset with canonical (optimal) order, cash/hands/discards, blind/ante state, shop contents, consumables, RNG node counters — and merge equivalent nodes via a **transposition table** shared across rollouts. This collapses the search tree toward a DAG and is the single biggest win against "same branch searched a thousand times." *Caveat:* a canonical key must include the RNG state (or be fully determinized) — two states with different remaining RNG call sequences are not equivalent.
2. **Bounds-based pruning / beam search.**
   - Admissible upper bound on blind-clear probability/score given best-case draws + best-case play (Layer 2 distributional math + Layer 1 exact scoring) → prune actions that cannot reach the blind target with remaining hands, even in the best case.
   - **Beam search over shop purchase sequences** (top-k sequences by value prior) as the planning primitive for econ decisions.
3. **Joker-synergy graph / action abstraction.**
   - Nodes = jokers; edge weights = empirical synergy (Δ in rollout win-probability from holding both vs neither, measured in-sim; bootstrap with the handcrafted tags/coherence logic already in balatro-rl's `synergy.py`).
   - Uses: shop-scoring prior, coherence shaping, and **action abstraction** (cluster jokers/builds into archetypes to shrink the abstract action set the search considers).
4. **ISMCTS/determinization discipline.** Use determinization (Layer 2) for the hidden order rather than full information-set machinery; MCTS over determinizations is the established, cheap approach here.

### 5.6 Layer 5 — Scripted heuristic baseline (bootstrap prior)

Build a **scripted strategy agent** first — BalatRobot-style additive joker valuation across board reads, threshold-gated buy/commit decisions, plus the exact local solver — and benchmark it (Stage A/B). This is (a) a strong baseline to beat, (b) the initial policy/value prior for MCTS, and (c) a supervised-imitation source for the learned network.

---

## 6. Learning design (modest hardware)

- **AlphaZero-style self-improvement, not raw PPO.** Search (Layer 3) generates improved targets; a small **policy+value MLP** (few hundred-K params — CPU-trainable, RX 570-capable) is trained on `(state → search-policy, search-value)` and feeds back as the prior. This is precisely the "search layered on a learned prior" axis the balatro-rl retrospective says is untried and most promising.
- **Warm start:** initialize the network by supervised imitation of the scripted baseline (Section 5.6), then iterate search→train→search.
- **Curriculum (per retrospective):** during the first training phase, **ban the S-tier lock-in jokers (Green Joker, Space Joker)** so the policy is forced to discover alternative strategies instead of gluing onto "buy Green+Space if seen" (the exact basin that froze V7 for 6 reward retunes + a 5.5× scale-up).
- **Anti-dead-end rules (learned from balatro-rl):**
  - **Random seeds** per episode (fixed seeds = memorization, V4 lesson).
  - **Do NOT do self-play multiplayer** (V8: two weak policies give weaker signal than solo against shaped rewards).
  - **Do NOT split play/shop into separate networks** (V5: shop agent starved on <0.1% of steps).
  - **Keep the action space search-derived** (use the exact solver + abstraction), not a fixed pre-ranked combo list (V6: agent always took action 0).
  - **Light reward shaping** (sparse win/blind-clear signals + small econ signals only). Over-shaping created the V7 plateau; search provides the credit assignment instead.

---

## 7. Evaluation & benchmarking

| Stage | What | When |
|---|---|---|
| **1. Seed-exact replay** | Ported `SeedRng`; for a battery of seeds, replay real-game (or balatro-rs) recorded outcomes and diff specific RNG results (Immolate targets, boss per ante, shop/pack contents) and all scores. Gates trust in every number afterward. | M1 |
| **2. Statistical** | Win rate over ≥10k random seeds; baselines: random play, scripted heuristic, reference point 2.35% (balatro-rl). Track per-ante survival, loss causes, seed-stratification. | M2→M6 continuous |
| **3. Live verification** | Steamodded + lovely-injector mod streams state; the Python engine plays the real game; verify win rate agreement + capture new edge cases into the replay corpus. | M5 |

Loss-cause tracking (which boss killed the run, economy failure vs. scoring failure) is a first-class metric — it drives where search vs. learning effort goes.

---

## 8. Throughput & profiling (design requirement)

Per the interview, no hard latency target, but **know what slows down every step** — it sets training time:

- Instrument each stage: scoring, subset enumeration (Layer 1), canonicalization/hashing (Layer 4), MCTS node ops, model inference, rollout stepping. Report steps/s per stage.
- Known levers: numpy-vectorized hand scoring (balatro-rl's `_best_hand_score` priority-filtering dropped 218 subsets to top candidates), cached canonical keys, numba-JITed scoring, 16-thread rollout parallelism, progressive simulation budgets.
- A `bench/` suite runs on every major change; regressions gate merges.

---

## 9. Milestones

- **M0 — Repo & env:** venv + deps; vendor `balatro-rl/balatro_sim` under `vendor/`; 496 tests pass; verify coverage claims against actual code; vet sparse-Gumbel-MCTS base implementation + licenses; record pinned game version.
- **M1 — Sim accuracy + RNG port:** audit boss blinds / vouchers / spectrals in base sim; port per-node LuaRandom (`SeedRng`) with bit-exact tests; replay-diff harness v1 (score + RNG axes); cross-validate scoring vs balatro-rs `calc`.
- **M2 — Baselines:** exact local solver (Layer 1); scripted heuristic agent (Layer 5); benchmark harness with random baseline + loss-cause metrics.
- **M3 — Search core:** canonicalization/transposition table; Gumbel MCTS with sampled actions + progressive budget; bounds pruning + shop beam search; joker-synergy graph.
- **M4 — Learning:** imitation warm-start → AlphaZero-style iteration; curriculum (banned S-tiers phase 1); staged win-rate gates (Section 1).
- **M5 — Live verification:** Steamodded + lovely-injector state streaming; live play; replay-corpus expansion.
- **M6 — Hardening & docs:** full benchmark suite, profiling report, final write-up.

---

## 10. Risks & mitigations

| # | Risk | Mitigation |
|---|---|---|
| 1 | **Sim fidelity** (silently-wrong mechanics) | Test-suite base + audit + replay-diff + cross-validation vs balatro-rs `calc`; joker allow-list; trust no number before Stage 1 gates |
| 2 | **RNG port correctness** | Port balatro-rs's *verified* algorithm (don't reinvent); per-node call-sequence discipline; bit-exact tests; two-RNG-mode abstraction |
| 3 | **Search tractability** (~50-way shop, long horizon) | Sampled Gumbel MCTS (m ≤ 16), action abstraction, beam search, DAG canonicalization |
| 4 | **Hardware limits** (Ryzen 2700 / RX 570) | Small MLPs, CPU-parallel MCTS, progressive budgets, numba/vectorization; RX 570 only for small-batch training |
| 5 | **Long-horizon credit assignment** (PPO plateau) | Search-based value; light shaping; curriculum; supervised warm start |
| 6 | **Licensing — NO LICENSE FILES** | **Neither balatro-rl nor balatro-rs ships a LICENSE (verified 404 on both).** Default = all rights reserved. Before vendoring: contact maintainers for permission, or reimplement patterns from scratch using their code only as a reference. Do not ship vendored code without resolving this. |
| 7 | **Version drift** | Pin the Balatro version the sim/mod target; document the pin |
| 8 | **Mod platform churn** (Steamodded/lovely-injector updates) | Isolate mod code; only needed for M5 |

---

## 11. Open questions (resolve in M0/M1)

1. **Which sparse-Gumbel-MCTS base implementation to adopt** — vet quality, license, and maintenance. Fallback: implement Gumbel MuZero from published pseudocode (full control, more work).
2. **Exact Balatro version string** balatro-rl's sim was verified against (record it in M0).
3. **Maintainer contact / license permission** for both prior-art repos (Section 10.6).
4. Whether to install `rustup` to run balatro-rs's `calc`/`explore` CLIs directly vs. only reading its source (recommend: install — it's the cheapest way to get a trusted oracle; but not blocking).
5. Confirm the boss-blind selection RNG is already produced by the ported seed algorithm (per balatro-rs "verified ante-by-ante") vs. needs separate implementation.

---

## 12. Prior-art lessons (do / don't)

**Adopt:** balatro-rl's audited sim + test suite; its combo-ranking/synergy ideas (as priors, not action spaces); its banned-joker filter pattern; its "search over more PPO" conclusion; BalatRobot's board-read/joker-valuation as a scripted-baseline template; balatro-rs's verified per-node RNG port as the exactness backbone; the voucher-PR's existence as evidence vouchers are well-trodden.

**Avoid:** live-game training at scale (V1–V3), fixed-seed training (V4), pre-ranked action spaces (V6), dual play/shop networks (V5), self-play between weak policies (V8), heavy reward shaping + big networks (V7 Runs 5–7).

---

## 13. References

- balatro-rs: github.com/evanofslack/balatro-rs (core, balatro-types, balatro-jkr, balatro-profile, balatro-seed, pylatro)
- balatro-rl: github.com/taggarttufte/balatro-rl — `PROJECT_RETROSPECTIVE.md`, `results/` (V1–V8 notes + run logs)
- BalatRobot: balatrobot.com — live state streaming + heuristic joker valuation
- Balatro-AI: github.com/CzJLee/Balatro-AI — SB3 + lovely-injector live control
- Gumbel MuZero / Gumbel AlphaZero — sparse action sampling for limited budgets; sampled variant for large action spaces
- Cowling et al., "Information Set Monte Carlo Tree Search" — ISMCTS/determinization background
- Balatro wiki — blind thresholds, boss blind min-ante table + Showdown pool, 150 joker catalogue, econ rules (interest cap $25, rarity odds)
