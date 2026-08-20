# V9 Design Notes — Search-First Optimal Play (Deterministic Oracle + Graph Connectivity)

*Written 2026-08-07. Pivot from V7/V8 RL (2.35% / ~0% solo win-rate ceilings) to a
search-first architecture that exploits the seed-exact deterministic sim as a
perfect forward model. Training stays minimal — search is the workhorse, and the
only learned component is a small GNN distilled from search rollouts.*

---

## Motivation

### Where we are

| Baseline | Win rate (White Stake) | Note |
|----------|:-:|------|
| Random agent (post-M2 fixes) | 0.10% (2/2000) | ~94.8% die at ante 1, ~4.7% ante 2 |
| V7 PPO (best, Run 4) | 2.35% | ~80% die at ante 1; Green+Space lock-in; 6 shaped-reward runs plateaued |
| V8 self-play MP | ~0% | Self-play between two weak policies gives weaker signal than solo; abandoned |
| Human expert (wiki/tournament estimate) | ~85% | Target to approach |

### The core insight: the seed changes everything

`rng_mode="seed"` (per-node LuaRandom, replay-verified bit-exact) makes the sim a
**deterministic forward model**:

1. **The game tree is a directed graph you can actually search.** Every transition
   from a state is a deterministic function of the action. Rollouts are *exact*,
   not sampled — no variance, no repeated-rollout averaging needed.
2. **Deck order is known.** Discard/play decisions become *exact EV* (you know
   precisely which cards you will draw next), not probability estimates.
3. **The sim is fast.** ~2,290 steps/s single-env, ~0.5–1 s per full run →
   thousands of rollouts/hour per core, parallelizable with existing worker infra.

V7/V8 failed because end-to-end PPO cannot do 200+ step credit assignment across
a sparse win signal. Search does that for free; the network only needs to *judge*.

### External research (2026-08-07)

- **Balatron** (jarmstrong158/Balatron): PPO + forward-simulating build planner +
  near-optimal heuristic tactical layer; property-fingerprint jokers +
  self-attention over the joker set; targeting ~85% White Stake. Closest existing
  match to this design.
- **jackdaw-balatro** (TylerFlar): 1:1 pure-Python engine, entity-based obs,
  factored actions — validates entity/graph encoding over flat vectors.
- **Slay the Spire literature**: MCTS + (learned or handcrafted) evaluation is the
  winning recipe for roguelike deckbuilders; deterministic seeded runs are
  explicitly exploited as an oracle. End-to-end RL plateaus (matches our V7/V8).
- **GNN work**: small 2–3 layer GNNs / set-transformers over card–joker–deck
  entity graphs capture synergy that flat MLPs miss. Distilling search results
  into a small net (behavior cloning + value regression) is the cheap path.

---

## Target & Constraints (agreed 2026-08-07)

- **Primary metric**: White Stake full-run win rate over 1,000–2,000 seeds
  (extend `bench/bench_sim.py`; ante-9 bucket = win). Also track death-by-ante
  histogram + mean ante reached.
- **Compute**: CPU-first. RX 570 GPU available but slow — any training run must
  fit ~1 hr or less (small nets only); overnight runs kept to a minimum and only
  for the final distillation/eval.
- **Graph emphasis**: handcrafted connectivity features first (zero training),
  then a small GNN distilled from search rollouts.

---

## Architecture — 4 Layers

### Layer 0 — Heuristic solver (zero training, ~days)

Brute-force at the *per-hand* level using engines that already exist:

1. **Per-hand "just enough" solver.** `env_sim._update_play_combos` already
   enumerates all 218 card subsets and ranks by real `score_hand`. Turn it into a
   policy: play the *cheapest* hand that clears the blind (preserving strong hands
   and joker triggers), not the greediest. Handles "just enough vs overkill"
   (V7 Planning §3) exactly.
2. **Exact-discard EV solver.** With the deterministic draw order, simulate
   "discard set X → draw exactly what follows" for candidate discard sets and pick
   the max-EV one (blind-clear probability / best-hand score next). Directly
   attacks the 80%-die-at-ante-1 bottleneck (V7 diagnosis: "the agent can't
   discard").
3. **Marginal-value shop policy.** For each shop joker, compute
   Δ(best-play score with vs without) via direct `score_hand` calls; combine with
   rarity, edition, cost, slot status, and money management (interest floors,
   sell-to-upgrade). Rule policy with a few tunable weights.
4. **Consumable / tag / boss heuristics.** Planet on highest-value hand type,
   tarot targeting, boss reroll (Director's Cut/Retcon) when the boss counters the
   build, skip-vs-play by tag value.

**Expected: 0.1% → 25–50%.** Humans survive ante 1 ~95%; this layer captures most
of that gap. Likely 10×+ V7's ceiling with zero learning.

### Layer 1 — Macro search over the run graph (no training, search at decision time)

> **REVISION (2026-08-17) — HUMAN-FAIR constraint.** Benchmarks must use only
> information a human has access to: which cards remain in the deck
> (composition) is legal; the draw order, future shop contents, and future
> bosses are not. `SearchShopV9` therefore defaults to a **comparative
> mean-measure search** — rank every affordable shop item by expected score
> delta on the best/typical drawable hands + econ $/ante + tarot/spectral
> gen/ante (plus lifecycle/deck/graph/synergy terms) and play the argmax —
> with NO rollouts and NO exact-future prediction. This path is real-run
> usable. The rollout-based search below survives only as `lookahead=True`
> (bench `--lookahead`), an explicit RESEARCH-ONLY mode for prior-refinement
> and search-method runs, never benchmark results.
>
> **REVISION (2026-08-18) — structure-aware discard.** The user's ante-1
> principle ("discard toward the most likely best hand, play good hands
> that score near the blind target") exposed that the discard-EV's
> quality-weakest candidate pool broke structure (seed 65 discarded its
> 8s+As pairs chasing a 1-card flush; seed 228 held a 240 straight while
> its flush line discarded 4H 5H 6S 8H and died 298/300). `best_discard`
> now uses `_structure_pool` — the discard pool is committed to the best
> line in priority order (pairs > flush > straight; a pair is never
> discarded), fires only when the best hand can't clear the remaining
> target, and allows up to 4-card discards (a 4-card flush draw needs all
> 4 off-suit cards gone). `decide_hand` gained hold-until-clear (weak
> hands keep discarding while hands+discards remain) and play-good-hand
> (a hand scoring >= 50% of the REMAINING target is played, not held).
> Result: ante-1 clear 80.3% -> 89.3% (59 -> 32 deaths; the lookahead
> oracle's own ante-1 clear is 91.3% — the human-fair ceiling for this
> bank is ~91%, and 24 of the 32 remaining deaths have <= 2 jokers at the
> death blind, i.e. they are ante-1 ECONOMY failures, not discard ones).
> Archive: `results/structure_discard_2026-08-18/`.
>
> **REVISION (2026-08-18) — ante-1 economy audit, no fix found.** The
> remaining ante-1 deaths (32/300; 24 with <= 2 jokers at the death blind)
> were audited: interest is paid on dollars held at round end, but 287/300
> seeds enter the Big blind and 282/300 the Boss with $0-4, so ante-1
> interest collected is ~$0.43/seed. FOUR fixes were A/B'd on the same
> bank — blanket interest floor (14->10 wins), joker-exempt floor
> (14->12), reroll gating (flat), floor+reroll (11 wins) — every one flat
> or worse and all reverted: ante-1 income (~$9-11/blind) is too tight to
> both buy power AND hold the floor, and the Boss-death seeds hold 1-3
> weak commons the exact-draw oracle also cannot clear (its own ante-1
> clear is 91.3% — the bank's ceiling). Archive:
> `results/ante1_economy_2026-08-18/`. The lever for >91% ante-1 clear is
> joker VALUE (buying better commons), not money discipline.

- **Beam search / best-first search at shop entries.** Node = state at shop entry;
  actions = buy/sell/reroll/leave sequences; transition = deterministic rollout of
  the round (played by the Layer-0 solver) to the next shop; score = rollout
  outcome (money, chips headroom, survival). *(research-only mode now)*
- **Boss/tag lookahead.** Skip-vs-play and tag choice evaluated by 1-blind
  rollouts.
- **MCTS variant.** Because transitions are deterministic, this collapses to
  best-first tree search with rollout eval — no variance, few rollouts per node.
  The tree *is* the state-connectivity structure we exploit.
- **Parallel rollouts** across processes (existing `env_parallel`/worker pattern);
  per-decision budget tunable (e.g. 50–500 rollouts ≈ seconds per shop).

**Prerequisite (M0 infra):** state forking for search — no snapshot/restore exists
today. Add `BalatroGame` deepcopy (verify RNG source objects deepcopy cleanly) or
replay-to-state using the existing `replay.py` fast-forward infra.

**Expected: +10–30pp** over Layer 0. Seed determinism pays off hardest here.

### Layer 2 — Graph / node-connectiveness layer

**2a. Heterogeneous graph builder (no learning, reuses `synergy.py`).**
Per decision point, build a graph from live game state:

- **Nodes**: owned jokers, shop jokers, hand-type nodes (planet levels), deck
  aggregate groups (suit/rank/enhancement counts), consumables, boss, scalar
  context node.
- **Edges**: joker↔hand-type activation; joker↔deck-group affinity (auto-derived
  from `tools/joker_spec.json` effect strings — rank/suit/hand-type keywords);
  joker↔joker synergy (exists: `coherence_score`/`loadout_coherence` in
  `synergy.py`); consumable↔target.
- **Connectivity features (handcrafted, zero training)**: per-joker degree/affinity
  to the current build, loadout coherence (already computed), and — the big one —
  **per-joker marginal score value** (Δbest-play-score with/without, a few ms of
  `score_hand`). These capture most of what a GNN would learn, for free.

**2b. Small GNN (optional, ~1 hr training — the only training).**
2–3 GAT/GraphSAGE layers, <1M params, over the 2a graph → value head + shop/play
policy head. Trained by **behavior cloning + value regression on Layer-1 rollout
data** (few thousand seeds × saved decision snapshots). Fast inference at play
time; generalizes the search. CPU-trainable; RX 570 optional accelerator.

### Layer 3 (optional, research-y) — MCTS + NN iteration

Use the GNN as the tree policy/value to deepen Layer-1 search; re-distill on new
rollouts. AlphaZero-lite loop. Only if 2b shows promise.

### Fallback that is pure brute force

Black-box **parameter search (CMA-ES / random search)** over the Layer-0/1 policy
weights, fitness = win rate over N seeds. Zero NN training, just many sim games.
Strong cheap baseline to compare 2b against (and its "policy parameters" double as
the BC/regression label source if we later want the GNN).

---

## Milestones & Acceptance Criteria

| # | Milestone | Training | Est. wall time | Acceptance |
|---|-----------|----------|----------------|------------|
| M0 | State-fork primitive + rollout API + eval harness | — | 1–2 days | `rollout(state, policy) -> outcome` exact under `rng_mode="seed"`; replay-diff clean; bench harness extended (win rate + death-by-ante) |
| M1 | Layer 0 heuristic solver (4 components, each gated) | — | 2–4 days | Win rate > 2.35% (V7 ceiling), then > 10%; ante-1 death < 60% |
| M2 | Layer 1 macro search (shop/round beam + boss/tag lookahead) | — | 1–2 weeks | +10pp over M1; per-decision latency within budget |
| M3 | Layer 2a graph builder + connectivity features | — | 3–5 days | +5–15pp over M2; features saved to disk for 2b |
| M4 | Layer 2b small GNN distilled from M2/M3 rollouts | ~1 hr | 1 week | ≥ parity with M3 search at 10–100× lower decision latency; held-out-seed eval |
| M5 | Layer 3 iteration (optional) | incremental | ongoing | win rate toward 85% expert target |

Every milestone is independently measurable with the existing bench harness —
each layer's contribution is proven before committing to the next.

---

## Key Implementation Details

- **State forking**: `deepcopy` of `BalatroGame` — verify `seed_rng` source
  objects (per-node LuaRandom counters) deepcopy cleanly; fallback is
  replay-to-state (fast-forward from seed to a saved action prefix — `replay.py`
  already has the diffing harness; extend to return the state).
- **Rollout API**: `rollout(game_state, policy, max_steps) -> outcome` used by
  Layer 1 and by the 2b data collector. Logs `(graph_snapshot, action, value)`
  records for distillation.
- **Marginal-value calc**: `score_hand(...)` is directly callable (already used by
  env combo ranking); per-joker marginal Δ over a reference hand is the core shop
  feature.
- **Evaluation**: extend `bench/bench_sim.py`-style harness; fixed held-out seed
  bank (e.g. 1,000 seeds) for all A/B comparisons; multiprocessing worker pool
  over seeds (CPU) for rollout generation.
- **Env choice**: work at the `game.py` + `score_hand` level for search; `env_sim`
  for evaluation loops. `env_v7`/`env_mp` remain for any future learned-policy
  training.

---

## Risks & Mitigations

- **deepcopy too slow for search nodes** → replay-to-state; or fork-on-write
  snapshots of only the mutated slices (hand, deck, shop, RNG counters).
- **Search latency at decision time** → cap rollouts per decision, cache rollout
  results by (seed, action-prefix hash), restrict search to shop-entry + boss/tag
  decisions, keep per-hand decisions on the Layer-0 solver.
- **GNN overfit / weak signal** → tiny parameter count, held-out-seed eval,
  compare against the no-learning fallback (CMA-ES) before adopting.
- **Determinism drift in new features** → every M1+ change re-runs the
  seed-exactness gate (`tests/test_seed_exactness.py -m ci_gate`) + replay-diff.

---

## M0/M1 Status — Layer 0 DONE (2026-08-07)

Implemented and benchmarked: `balatro_sim/rollout.py` (clone_game + rollout),
`balatro_sim/agent_v9.py` (HeuristicV9: just-enough play, exact-discard EV,
marginal-value shop, booster picks, boss reroll), `bench/bench_v9.py` (A/B
harness), `tests/test_agent_v9.py` (14 tests). Full suite **992 passed** +
ci_gate 4/4.

**Benchmark (seed mode, same 1000-seed bank):**

| Metric | Random | V7 PPO (best) | **Heuristic V9** |
|--------|:-:|:-:|:-:|
| Win rate | 0.0% (0/1000) | 2.35% | ~2–3.5% (20/1000; 7/300, 8/300) |
| Mean ante reached | 1.00 | — | ~4.0 |
| Ante-1 death | 99.9% | ~80% | ~15–23% |

Key wins: ante-1 death cut from ~95% (random) / ~80% (V7) to ~15%; mean ante
3.6→4.0 after the rollout stall-guard fix (a state-only stall counter fired
"play card 0" every 3rd in-blind action — replaced with a progress-signature
check). Main remaining cliffs: ante-1 boss deaths (The Hook counter built:
hook-safe rank-multiset plays ≥4 cards) and the ante-5+ scaling cliff.

Notable implementation details:
- **Eval oracle runs on isolated copies** (fresh JokerInstance + deepcopied
  state, Card copies, throwaway seed-0 RNG) — the scoring engine is SIDEFUL
  (`on_hand_scored` mutates scaling jokers; Hiker writes card bonus_chips),
  and env_sim's combo ranking has this latent eval-mutation bug that we
  deliberately avoid.
- `deepcopy(BalatroGame)` verified ~1 ms and fully independent (RNG node
  tables included) — the Layer-1 search fork primitive.
- Discard EV is exact for the draw (deck.pop() order is deterministic);
  pruned to the 6 weakest cards × sizes 1–2 (documented approximation).
- v1 scope: planets only (tarot/spectral targeting is the next Layer-0 item),
  always play blinds (no skip-tag logic yet), booster packs = Buffoon +
  Celestial only.

## M2 Status — tarot/spectral policy DONE (2026-08-07)

Implemented the remaining Layer-0 consumable heuristic in `agent_v9.py`:
`_tarot_action` / `_spectral_action` / `decide_consumable` — wired into
`decide_hand` (mid-blind: upgrades the live hand) and `decide_shop` (upgrades
leftover hand cards, which return to the deck next blind — the optimal time to
use most target-tarots). `tests/test_agent_v9.py` 14→24 tests; full suite
**1002 passed** + ci_gate 4/4.

**Policy coverage:**
- *Enhance* (Magician/Empress/Hierophant/Lovers/Chariot/Devil) on the best
  cards; Justice/Tower deliberately skipped (Glass shatter risk / niche
  Stone-Joker builds).
- *Suit convert* (Star/Moon/Sun/World) toward the majority suit once it can
  form a flush (≥3 same-suit non-Stone); never converts Stones.
- *Strength* on the 2 weakest non-Aces (A wraps to 2); *Death* copies best
  onto weakest; *Hanged Man* deck-thinning — **shop-only** (destroying
  in-hand cards mid-blind shortens the live hand).
- *Seals* (Talisman/Deja Vu/Trance/Medium) on the best card; *Aura* edition
  on the first un-editioned joker (`target_indices[0]` = joker index);
  *Familiar/Grim/Incantation* destroy the weakest junk card;
  *Cryptid* copies the best enhanced/face card.
- *Self-tarots:* Hermit/Temperance (money, no upper bound — gain is monotonic
  in dollars), Fool, Emperor/High Priestess (conservative slot gate),
  Wheel of Fortune (only with a joker to upgrade), Judgement (slot gate).
- *Spectrals:* Black Hole always; Soul/Wraith (slot + $ gates); Ectoplasm
  (≥3 jokers); Immolate (shop-only, poor/bloated-deck gate). Risky
  build-destroyers (Ankh/Hex/Ouija/Sigil) intentionally skipped in v1.
- **Acquisition teeth:** shop now buys target-tarots (consumable-slot-gated,
  `worth_spending` interest-band gate) and Arcana/Spectral pack values were
  bumped in `PACK_VALUE` (jokers/celestial still outrank them).

**A/B results (same seeds, seed mode):**

| Run | Win rate | Mean ante | Ante-1 death |
|-----|:-:|:-:|:-:|
| 300 seeds, tarots OFF (control) | 7/300 = 2.33% | 4.02 | 21.7% |
| 300 seeds, tarots ON | 9/300 = 3.00% | 4.17 | ~18% |
| **1000 seeds, tarots ON** | **36/1000 = 3.60%** | **4.19** | **13.9%** |
| 1000 seeds, pre-tarot V9 (M0/M1) | 20/1000 = 2.00% | 3.59 | 22.8% |

Headline: 2.00% → **3.60%** on the same 1000-seed bank (95% CI [2.4%,
4.8%]); ante-5+ survival up (27.9% of runs reach ante 6+, vs ~8.8% before).
The 300-seed tarots-off control reproduced the earlier baseline exactly
(2.33%) — clean A/B. Remaining cliffs: ante-1 boss deaths (14%) and the
ante-5→6 scaling cliff (18.8% die at ante 5).

Notes:
- **Review-driven fixes landed after the 1000-seed run** (both strictly
  money-positive, so 3.60% is a slight underestimate): Hermit/Temperance
  gates had a `dollars < 20` upper bound that skipped them at exactly the
  max-gain point (gain = min(dollars, 20) is monotonic — no upper bound);
  plus a decide-level RNG-purity regression test (`test_decide_never_-
  perturbs_run_rng`: a full `decide()` consumes zero live-stream draws).
- **Sim gaps found while auditing the policy (NOT changed):** `s_wraith`
  costs -$3 (reference doc says money → $0); reference doc itself differs
  from the real game on Wraith (real: destroys a joker first). Flagged for
  the M2 P2 fidelity pass.
- Benchmark throughput: ~1.6 games/s at 8 workers (627s / 1000 games);
  the 1000-game A/B ≈ 11 min wall.

## M3 Status — L1 macro search + stats reporting (2026-08-07)

**L1 rollout-verified shop search (agent_l1.py) — benchmarked:**

| Policy | Wins / 300 | Win rate | Mean ante | Median ante | Mean steps |
|--------|:-:|:-:|:-:|:-:|:-:|
| Random (bench_sim floor) | ~0/1000 | ~0.10% | ~1.1 | — | — |
| V7 PPO ceiling (historical) | — | 2.35% | — | — | — |
| **HeuristicV9 (L0)** | 8/300 | 2.67% | 4.14 | 4 | 101 |
| **SearchShopV9 (L1, search_shops=1)** | 22/300 | **7.33%** | 4.95 | 5 | 123 |

Death-by-ante histogram (L1 vs L0): ante-1 deaths 10.3% vs 14.0%, ante-8
survival+ 8.0% vs 4.3% wins bucket 7.3% vs 2.7% — the search converts early
shop mistakes into ~2.75× more wins at 0.3 games/s (vs L0's 1.5). Every
policy runs the same 300 seeds (0..299, seed mode).

**Run-statistics instrumentation + report (observation-only):**

- `game.run_stats`: jokers_bought, consumables/cards/packs/vouchers_bought,
  money_spent, rerolls, packs_opened, best_score — all plain data, ZERO RNG
  consumption (ci_gate 4/4 re-verified). `game.spectrals_used` joins the
  existing tarots_used/planets_used.
- `rollout.outcome()` exposes `stats` (tarots/planets/spectrals/
  jokers_bought/money_spent/best_score/rerolls/packs_bought/packs_opened).
- `bench/bench_v9.py`: per-policy usage block (mean $, spent, max score,
  top-5 tarots/planets/spectrals, top-8 jokers) + self-contained HTML report
  (summary table, death-by-ante + usage bar charts per policy, raw JSON) and
  a JSON sidecar for tooling. `--report PATH` / `--no-report`.
- Tests: `tests/test_run_stats.py` (outcome-stats consistency vs game
  counters + direct increment checks + real-play best_score). L1 tests
  slimmed 129s → 47s with the same coverage.
- Suite **1402 passed** + ci_gate 4/4 + all 4 audits CLEAN.

Next: A5 tag weights, L2 graph-connectivity features, M2 P2
stakes/stickers + Endless.

## M4 Status — L2 graph-connectivity features (2026-08-07)

**The run graph (`balatro_sim/graph_v9.py`)** — heterogeneous nodes
(joker / hand-type / deck-group / boss) with affinity edges auto-derived from
the doc-pinned `tools/joker_spec.json` effect strings:

- **Affinity extraction** — word-boundary keyword matching over effect text
  (hand types, suits, ranks, enhancements, behaviour flags). Stat/odds tokens
  ("+10 Mult", "X2", "$4", "1 in 4 chance") are stripped first so they never
  become rank affinities; "Ace," punctuation handled via \b boundaries.
- **Edges** — joker→hand affinity, joker→deck-group support (normalized
  count), joker→joker shared-affinity, hand→deck feasibility (most-common
  rank/suit), joker→boss counter.
- **Features** — coherence (mean shared-affinity vs owned jokers), deck
  support (best normalized deck count for the joker's suit/rank/enh affinities),
  hand alignment (1.0 on the main hand type) — blended by FEATURE_WEIGHTS
  (0.40/0.30/0.30); `boss_counter_value` is SEPARATE.

**Why the boss term is separate** — Chicot/Luchador/Matador add ~0 chips/mult,
so marginal score eval values them at ~0 and they were never bought. The
blend-only L0 A/B was flat (8/300 both); adding the dedicated
`boss_buy_bonus` term moved L0 to:

| Policy (300 seeds) | Wins | Win rate | Mean ante |
|--------------------|:-:|:-:|:-:|
| L0, graph + boss OFF | 8/300 | 2.67% | 4.14 |
| L0, graph blend only | 8/300 | 2.67% | 4.14 |
| **L0, graph + boss ON** | **11/300** | **3.67%** | 4.17 |

**L1 full A/B (300 seeds, graph on)**: search_shop_v9 **24/300 = 8.00%**
(mean ante 5.01) vs the 22/300 = 7.33% no-graph L1 baseline — the same
+1.0pp-class lift the graph gave L0 (2.67% → 3.67%), reproduced across both
layers. The L0 rerun inside this A/B (11/300) exactly matched the earlier
graph-on run — decision changes are stable per seed.

| Policy (300 seeds) | Graph OFF | Graph ON | Δ |
|--------------------|:-:|:-:|:-:|
| L0 heuristic | 8/300 (2.67%) | **11/300 (3.67%)** | +3 wins |
| L1 search_shop | 22/300 (7.33%) | **24/300 (8.00%)** | +2 wins |

**The "known approximation" is FIXED by the boss-layer pass (next section)**
— the upcoming boss's KEY is now pre-selected at shop entry, so
`boss_counter_value` is key-specific (Matador only vs its 13 real trigger
blinds) and Director's Cut rerolls fire in the shop BEFORE the boss.

Pure reads throughout — zero RNG, zero mutation (ci_gate 4/4 re-verified).
13 tests: affinity pins (Fibonacci {14,2,3,5,8}, Triboulet {12,13}, 8-Ball,
Smeared all-suits, Chicot/Luchador boss flag, mr_bones NOT boss-flagged),
graph structure, feature behaviours, joker_value purity + boss-bonus term.
Suite **1415 passed** + ci_gate 4/4 + all 4 audits CLEAN.

## M5 Status — boss-layer pass: boss known at shop time (2026-08-07)

**The problem (pre-fix):** the sim selected the upcoming Boss Blind's key only
at shop END (`_prepare_next_blind`), so during the shop-before-the-boss the
key was unknown. Two consequences: (1) `boss_counter_value` fired for ANY
upcoming boss — Matador got bought even vs the ~15 bosses that never trigger
him; (2) Director's Cut rerolls in `decide_shop` only matched
`current_blind.kind == "Boss"` — i.e. AFTER the boss was beaten, silently
wasting $10/Ante rerolling the beaten boss.

**The fix (real-game semantics):**

- `game._preselect_next_boss()` — selects the upcoming Boss Blind at SHOP
  ENTRY (`blind_idx == 1`), storing it in `game.next_boss_key`. Called from
  `_end_round`, `_end_blind_and_enter_shop`, and `_skip_blind` (before any
  free-pack BOOSTER_OPEN window); consumes the Boss-Tag reroll; idempotent
  (no extra boss-node draw on re-entry).
- `_prepare_next_blind` REUSES `next_boss_key` for the Boss blind (no
  reselect; clears it) — the legacy select path remains as a safety net for
  hand-constructed states.
- `_reroll_boss` operates on `next_boss_key` — real Director's Cut/Retcon
  semantics (reroll IN the shop before the boss). The rerolled boss's score
  scaling (Wall 4x / Violet 6x / Needle 1x) is applied at blind setup
  (`_prepare_next_blind`).
- `agent_v9.decide_shop` fires the reroll when `next_boss_key in BAD_BOSSES`
  — no more post-boss $10 waste.
- `graph_v9.boss_context` returns the REAL key during shops;
  `boss_counter_value` is key-specific: `j_matador` only valued against
  `MATADOR_BOSSES` (the 13 real trigger blinds — now a single authoritative
  frozenset in `game.py` that also gates `_play_hand`'s trigger block;
  bl_psychic triggers via its <5-card rejected-hand early-return, not the
  block). Chicot/Luchador (disable ANY boss) unchanged. Unknown key
  (hand-built states) falls back to the old any-boss 1.0.

**RNG safety:** the boss-node draw moves one shop earlier in the trace, but
per-node streams are independently seeded — same draws, shop contents
byte-identical (ci_gate 4/4, EXPECTED_SHOP pins, full suite all green).

**Tests (+7):** `TestPreselectTiming` (5 — key known during the shop, blind
reuse without reselect, idempotent no-extra-draw, boss-before-voucher trace
order, rotation/min-ante parity vs the legacy path), rewritten
`TestBossReroll` (new semantics + post-boss reroll is a no-op), decide_shop
Matador-buy integration (bought before bl_ox, NOT before bl_wall), boss-tag
spy on the preselect path. Suite **1421 passed** + ci_gate 4/4 + audits
CLEAN.

**Re-bench (300 seeds, graph on):**

| Policy (300 seeds) | Pre-fix | Post-fix | Δ |
|--------------------|:-:|:-:|:-:|
| L0 heuristic | 11/300 (3.67%) | **11/300 (3.67%)** | 0 |
| L1 search_shop | 24/300 (8.00%) | **22/300 (7.33%)** | −2 wins |

L0 is flat (same 11 wins, slightly different histogram — decisions did
change, the win count didn't). L1 is −2 wins — a 0.67pp drop that is well
within sampling noise on 300 seeds (SE ≈ 1.5pp at this rate), but
DETERMINISTIC for this bank. Two known mechanisms, both consequences of the
fix's correctness: (1) Matador is no longer bought before non-trigger bosses
— but its value is long-run (the no-repeat rotation brings trigger bosses
later), so the next-boss-only term is myopic by design; (2) Director's Cut
no longer burns a boss-node draw (and $10) after every beaten boss, so the
boss sequence on DC-owning seeds shifted back to the natural stream. The
fidelity fix is correct (real game: boss known at shop, Matador pays only on
its 13 trigger blinds, DC rerolls pre-boss); a 1000-seed A/B would separate
the −2 from noise. A better long-run Matador valuation (value by the
upcoming-boss distribution, not just the next boss) is a candidate follow-up
if the drop persists.

## M6 Status — empirical synergy tree (2026-08-07)

Closed the "underutilised synergies" gap with a LEARNED counterpart to the
static affinity graph (M4): the agent now consumes an empirical synergy tree
mined from actual run telemetry, closing the loop — bench dumps telemetry,
`tools/gen_synergy_tree.py` mines weighted edges, `joker_value` adds a
differential prior term, re-bench validates.

**Telemetry (observation-only, zero RNG — ci_gate 4/4 proves purity)**:
`game.run_stats` now records `co_owned` (per scored hand: ante, hand type,
sorted joker keys, score), `consumable_uses` (ante, key, held-joker keys,
targeted-card features rank/suit/enh/edition/seal), `jokers_sold`; shop.py
tracks sells; the rollout outcome exposes it; `bench_v9 --telemetry-dir` dumps
per-run JSON.

**Tree** (`tools/synergy_tree.json`; loader `balatro_sim/synergy_tree.py`):

- joker↔joker — co-ownership at scored hands; lift vs the EXCLUSIVE single
  baseline (runs owning one joker but not the other)
- joker↔consumable — used-while-owned; lift vs the exclusive baseline (owned
  the joker WITHOUT using the consumable) — policy-balanced, no global-base
  confounding
- joker↔hand — empirical activation (n, mean score, share of the joker's hands)
- joker↔card — tarot-targeted card features (rank/suit/enhancement)
- deterministic (sorted iteration), min-support floor (3)

**Agent term**: `synergy_weight` (default 0.15) × (empirical_synergy_score −
0.5) in `joker_value` — a blended [0,1] score (joker 0.45 / consumable 0.30 /
hand 0.15 / card 0.10, each 0.5-neutral, support-smoothed sigmoid). Missing
tree → exactly 0 contribution. A/B-able via `--params '{"synergy_weight":0}'`.

**Bench (300 seeds, A/B off→on; the ON tree was mined from the OFF corpus)**:

| Policy | synergy OFF | synergy ON (600-run tree) | Δ |
|---|---|---|---|
| L0 heuristic | 11/300 (3.67%) | 10/300 (3.33%) | −1 |
| L1 search_shop | 22/300 (7.33%) | 21/300 (7.00%) | −1 |

The first iteration is flat-to-slightly-negative — within sampling noise
(SE ≈ 1.5pp), deterministic for this bank. Honest mechanisms: (1) a 600-run
tree at min-support 3 is noisy — top "synergies" (Seltzer/Credit-Card
survival correlations) are artifacts the support smoothing can't fully damp;
(2) the ±0.075 term is deliberately small, so it nudges rather than flips
decisions; (3) the hand/card components are tiny weights.

**Final bench — 1000 seeds, ON tree mined from the 1200-run merged corpus**
(2026-08-07):

| Policy | prior best | 1000-seed final (syn ON) |
|---|---|---|
| L0 heuristic | 36/1000 = 3.60% (M2, same bank, no synergy) | **44/1000 = 4.40%** (mean ante 4.21) |
| L1 search_shop | 22/300 = 7.33% (syn OFF, 300 bank) | **84/1000 = 8.40%** (mean ante 5.03) |

Read: at scale the empirical prior is neutral-to-positive. The heuristic leg
is a same-bank comparison (seeds 0-999, tarot-era policy, only the synergy
term differs) — 36 → 44 wins (+0.8pp), consistently positive but inside the
~1.5pp SE. search_shop 8.40% is the best L1 number ever recorded (vs 7.33%
syn-OFF 300-bank and 7.00% syn-ON 600-tree 300-bank; different banks, so not
a clean A/B). No regression anywhere. Both policies cleared every prior
milestone high-water mark on the same run.

Iteration 3 (ready, not yet benched): the merged 3200-run corpus (OFF 300 +
ON 300 + ON 1000) regenerated `tools/synergy_tree.json` — 4210 joker↔joker /
2119 joker↔consumable edges (2.7× the 1200-run tree). Levers if still flat:
higher support floors, per-policy trees, a min-lift gate (only edges with
|lift| above a threshold enter the term), or a same-bank 1000-seed syn-OFF
search_shop run for a clean A/B.

**Validation**: 13 new tests (telemetry capture/purity/serializability,
determinism across replays, miner pair-lift math + support floor + all four
edge families, scorer neutrality + edge-driven scores + hand mismatch, agent
term is exactly 0 at neutral) — full suite **1435 passed**, ci_gate 4/4,
audits CLEAN. The report now surfaces ALL FOUR mined families (joker↔joker /
joker↔consumable / joker↔hand / joker↔card) plus top mined edges.

## M7 Status — batched live-progress benches (2026-08-07)

Long benches no longer output only at the end. `bench/bench_v9.py` now runs
via `pool.imap_unordered` (chunksize 1) and flushes a progress line + a
pollable JSON checkpoint every `--batch-size` completed runs (default 25,
`0` = end-only):

```
  [search_shop_v9] 75/1000 runs | 9 wins (12.00%) | mean ante 5.57 |
                  0.2 games/s | ETA 1:07:10 | v9_report.progress.json
```

- **Progress checkpoint**: `<report>.progress.json` (or `--progress PATH`) —
  wins/win_rate/death-by-ante/mean_ante/median_ante/mean_steps/mean_$
  /mean_spent/max+mean score/top tarots+planets+spectrals+jokers, games/s,
  ETA (computed from NEW runs only). JSON keys are strings (death included).
- **Per-run telemetry**: written as runs COMPLETE (was: at policy end) — a
  killed bench leaves a usable corpus for `tools/gen_synergy_tree.py`.
- **`--resume`**: reloads existing `run_<seed>.json` files into the aggregate
  instead of re-running them (they carry the full outcome dict); warns if
  used without `--telemetry-dir`. Pairs with the A/B flow: relaunch after a
  crash/kill picks up exactly where the telemetry corpus left off.
- **Config fingerprint**: each policy dir gets a `meta.json` and every telemetry
  file a `_cfg` (policy/rng_mode/params/search_shops/seed bank). `--resume`
  refuses to reload runs produced under a different config — it warns with
  the exact diff and re-runs those seeds, so an A/B can never silently mix
  two parameterizations into one aggregate.
- All progress prints use `flush=True` (ASCII `|` separators — Windows
  cp1252 console mangles non-ASCII), so `tail -f` on a redirected log works.
- `bench/bench_ab_reshuffle.py` got the same batch-progress treatment
  (serial loop, `--batch-size`, default 100).

Smoke-verified (12 seeds, batch 5, incl. a full resume round-trip: 12/12
reloaded, identical aggregate, 0s). Suite **1435 passed** + ci_gate 4/4
unchanged (bench files only).

## M8 Status — synergy-prior tuning: min-support / min-lift / per-policy
(2026-08-07)

The three levers requested to make the prior high-confidence-only:

- **miner**: `--min-lift` drops joker↔joker AND joker↔consumable edges with
  |ante lift| < the gate (jc edges now store a derived `lift_ante` vs the
  exclusive owned-without-used baseline); `--policy` mines only one policy's
  runs (per-policy trees); default behavior unchanged at min_lift 0.
- **scorer/agent**: `load_tree(path)` caches per path; `empirical_synergy(_score)`
  take an explicit `tree` kwarg; agent param `synergy_tree` (path) selects it;
  `clear_tree_cache()` for long-lived processes/tests.
- **bench**: `--synergy-tree PATH` (all policies) / `--per-policy-trees`
  (auto tools/synergy_tree_<policy>.json); the injected tree is logged per
  policy and part of the cfg fingerprint (resume can't mix configs).
- **Hyperparameter scan** on the 3200-run corpus: lift distributions are
  survival-skewed (median +0.37 ante) — a 0.1-0.3 gate filters almost
  nothing. Chose **min-support 8 + min-lift 0.5** → 1436 jj / 881 jc edges
  (vs 4210/2119 at ms3/ml0, a 2.9× noise reduction); top edges are real
  game-theoretic pairs (Runner+Space Joker, Space Joker+Mercury,
  Cartomancer+tarots, Crafty Joker+Earth) — no more Seltzer/Credit-Card
  artifacts. Per-policy trees diverge sensibly (heuristic: econ pairs
  Egg+Golden/Matador+Popcorn; search_shop: Cartomancer+Magician/
  Certificate+Mercury).

**300-seed A/B (same bank 0-299; control = syn-OFF)**

| Policy | OFF | ON 600-run | ON tuned combined (ms8/ml0.5) | ON per-policy (ms8/ml0.5) |
|---|---|---|---|---|
| L0 heuristic | 11/300 (3.67%) | 10/300 (3.33%) | 11/300 (3.67%) | 10/300 (3.33%) |
| L1 search_shop | 22/300 (7.33%) | 21/300 (7.00%) | 21/300 (7.00%) | 21/300 (7.00%) |

Read: at 300-seed resolution EVERY synergy configuration lands within ±1
win of control (SE ≈ 1.5pp) — tuning the tree (higher support, min-lift,
per-policy) does not move win rate; the per-policy trees are not better than
the combined tree, and the tuned tree is not better than the untuned one.
The only above-noise readings remain the 1000-seed runs with the 1200-run
UNTUNED tree (heuristic 44 vs 36 same-bank +0.8pp inside SE; search_shop
84). Conclusion: at L1's decision margin the empirical prior is a weak-to-
neutral prior — its levers are implemented + A/B-able, and a same-bank
1000-seed OFF-vs-tuned run (~80 min) is the definitive remaining test.

The tuned tree stays the default `tools/synergy_tree.json` (cleaner for the
report's top-edge display); per-policy trees live alongside it.

**Validation**: 6 new tests (min-lift gate incl. negative-lift survival, jc
lift_ante math, --policy filter, per-path cache, explicit-tree scorer arg,
per-policy agent wiring) — full suite **1441 passed**, ci_gate 4/4, audits
CLEAN.

## Reference

- [V7 Planning](V7_PLANNING.md) — ceilings, "what doesn't work", approach rankings
- [V8 Run Log](V8_RUN_LOG.md) — self-play failure analysis
- `bench/bench_sim.py` — win-rate + throughput harness (M0 extends this)
- `balatro_sim/synergy.py` — existing joker-synergy graph (`coherence_score`,
  `loadout_coherence`)
- `tools/joker_spec.json` — canonical joker effects (source for affinity edges)
- `balatro_sim/seed_rng.py` + `tests/test_seed_exactness.py` — deterministic RNG
