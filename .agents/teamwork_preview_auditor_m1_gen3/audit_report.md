# Forensic Audit Report: Milestone M1 (Core Policy Enhancement R1+R2+R3)

**Target Work Product**: `vendor/balatro-rl/balatro_sim/agent_v10.py` and `vendor/balatro-rl/tests/test_scaling_acceleration.py`
**Auditor**: Forensic Integrity Auditor (`teamwork_preview_auditor_m1_gen3`)
**Integrity Mode**: Development (with Balatro Human-Fair & Anti-Cheat Invariants from AGENTS.md)
**Final Verdict**: **CLEAN**

---

## 1. Executive Summary

A comprehensive forensic integrity audit was conducted on all modifications delivered by Worker M1 across `vendor/balatro-rl/balatro_sim/agent_v10.py` and `vendor/balatro-rl/tests/test_scaling_acceleration.py`.

The audit evaluated the codebase against four core integrity threats:
1. Hardcoded seed tables or special-cased benchmark seeds.
2. Peeking at deck draw order, future shop items, or RNG streams.
3. Mutation of live game state during search or evaluation.
4. Facade implementations or benchmark gaming.

Every claim made in Worker M1's handoff report was empirically verified through independent static analysis, AST/regex pattern scanning, and end-to-end execution of the full test suite and static audit gates.

All forensic checks passed without exception. The verdict is **CLEAN**.

---

## 2. Phase 1: Mode-Agnostic Forensic Investigation

### Check 1: Hardcoded Seed Values and Lookup Tables
- **Methodology**: Exhaustive AST and string scan across `agent_v10.py` and `test_scaling_acceleration.py` for seed numbers (`205`, `275`, `0`–`299`), seed dictionary maps, seed parameter overrides, or benchmark branching.
- **Findings**:
  - Exactly 3 occurrences of `seed` in `agent_v10.py`:
    1. Line 22: Architectural comment (`throwaway seed-0 RNG, isolated eval copies`).
    2. Line 2241: Docstring reference (`seeded from the already-`).
    3. Line 2991: Explanatory comment describing an architectural edge case (`P(clear) reads 1.000 on doomed boards (seed 87 bank)`).
  - No seed lookup tables, no seed conditionals, no seed-keyed branches.
  - Fatal seed numbers 205 and 275 do not appear anywhere in `agent_v10.py`.
- **Result**: **PASS (CLEAN)**

### Check 2: Information Leakage, Lookahead, and RNG Peeking
- **Methodology**: Audited all accesses to `.deck`, `.rng`, `.chance()`, and `current_shop`.
- **Findings**:
  - `game.deck` is accessed solely via compositional reads (`len(game.deck)`, `_value_multiset(game.deck)`, `deck_groups(game)`, `any(getattr(c, "enhancement", "") == ... for c in game.deck)`). There is zero positional indexing (`deck[0]`, `deck[-1]`, or slices) on the live deck.
  - `game.chance()` and `game.rng` are never invoked in `agent_v10.py`. All stochastic simulation uses an isolated, deterministic throwaway generator (`random.Random(0)`).
  - Shop evaluation inspects only `game.current_shop`; no future shops, hidden queues, or RNG rollouts are read in default mode.
- **Result**: **PASS (CLEAN)**

### Check 3: Live Game State Mutation During Evaluation
- **Methodology**: Audited all functions involved in R1 (forecasting and shop ranking), R2 (tarot/spectral actions and planet usage), and R3 (scaling play generation).
- **Findings**:
  - `_forecast_round_score` reads `ref = reference_hand(game)` and computes static scoring bounds without altering game attributes.
  - In `_find_scaling_action`, scoring evaluation relies strictly on `eval_hand_score(game, ht_c, sc_c, cards_c, held_cards=held_c)`, the non-mutating scoring oracle. Candidate cards are evaluated as subsets of indices without modifying `game.hand`.
  - In-shop tarot actions (`c_death`, `c_strength`, `c_hanged_man`) return action dictionaries with target indices (`{"type": "use_consumable", ...}`) rather than directly mutating cards in memory.
  - `TestEstimateClearProbability::test_no_live_mutation` passed cleanly.
- **Result**: **PASS (CLEAN)**

### Check 4: Genuine, Generalizable Domain Logic Review
- **Methodology**: Inspected implementation of R1, R2, and R3 to verify they are authentic heuristic enhancements rather than superficial facades.
- **Findings**:
  - **R1 (Late-Game Capital Deployment & Urgent Rerolls)**: Dynamically relaxes the interest floor in Ante 8 ($0), Ante 7 ($0 under score deficit), and Ante 6 ($15 lacking xMult). Reroll limits expand to 10, 6, 4 with a purchase buffer check (`capital_after_reroll >= 6`). Full-slot joker evaluation accounts for `_joker_sell_value(game.jokers[worst_j])` in available capital. `SearchShopV10.decide` resets `_searched_this_visit = False` upon rerolling to evaluate newly revealed shop items.
  - **R2 (Deck Reshaping & Targeted Consumables)**: Establishes `_HAND_ENGINE_PRIORITY` for `portfolio_target_hand(game)`. `deck_reshape_target` integrates Duo, Trio, and face-dependent jokers. In-shop tarot actions intelligently direct Death (duplicating engine target cards onto junk while protecting key synergies), Strength (promoting rank 10s to Jacks or `target - 1` to `target`), and Hanged Man (culling unenhanced junk). Planets are consumed proactively in shop to free slots and upgrade levels immediately.
  - **R3 (Scaling Joker Acceleration During Safe Blinds)**: Implements two safety tiers: Tier S1 (reserves a minimal disjoint knockout hand K, guaranteeing 100% deterministic round survival on the next hand) and Tier S2 (probabilistic safety under P(clear) >= 0.98 / 0.995). Enforces strict guardrails (`j_ride_the_bus` non-face verification, banned boss exclusions, Green Joker discard suppression, Wee Joker index 0 Chad positioning).
  - **Baseline Protection**: All new search and decision logic is strictly gated by `if V10_PARAMS.get("farm_clear_threshold", 0.90) < 1.0:`. When `farm_clear_threshold == 1.0`, `agent_v10.py` matches `agent_v9.py` byte-for-byte (`TestFarmOffReproducesV9::test_farm_off_matches_v9 PASSED`).
- **Result**: **PASS (CLEAN)**

---

## 3. Phase 2: Mode-Specific Flagging (Development Mode)

In accordance with `ORIGINAL_REQUEST.md`, Development Mode strictly prohibits hardcoded test results, facade implementations, and fabricated verification outputs.

| Prohibited Pattern | Status | Observations |
|---|:---:|---|
| Hardcoded test results | CLEAN | No expected values or hardcoded output literals found. |
| Facade implementations | CLEAN | Genuine multi-tier decision engines, dynamic capital models, and combinatorial solvers. |
| Fabricated verification outputs | CLEAN | All test outputs reproduced and verified live by auditor. |
| Seed / draw-order cheating | CLEAN | Composition-only reads; no deck ordering or RNG consumption. |
| Baseline corruption | CLEAN | `agent_v9.py` untouched (0 lines modified); V9 parity test passes. |

---

## 4. Empirical Test Suite & Static Audit Results

All commands were executed independently from the repository root:

### 1. Scaling Acceleration Regression Suite
`python -m pytest vendor/balatro-rl/tests/test_scaling_acceleration.py -v`
- Result: `9 passed in 0.28s`

### 2. V10 Comprehensive Test Suite
`python -m pytest vendor/balatro-rl/tests/test_agent_v10.py -v`
- Result: `50 passed in 29.95s` (including `TestFarmOffReproducesV9::test_farm_off_matches_v9`)

### 3. CI Gate Seed Exactness
`python -m pytest vendor/balatro-rl/tests/test_seed_exactness.py -m ci_gate -v`
- Result: `4 passed in 7.58s`

### 4. Static Audit Gates
- `python tools/audit_jokers_static.py`: `GATES: CLEAN` (0 dupes, 0 dead, 0 stubs, 0 gaps, 0 type, 0 sig, 0 state, 0 noscan)
- `python tools/audit_consumables_static.py`: `GATES: CLEAN` (0 names, 0 counts, 0 planet, 0 targets, 0 effect, 0 dead, 0 wired, 0 vnames, 0 vpairs, 0 veffect)
- `python tools/audit_bosses_static.py`: `GATES: CLEAN` (0 count, 0 min_ante, 0 showdown, 0 scaling, 0 select, 0 matador, 0 effect, 0 wired)
- `python tools/audit_tags_static.py`: `GATES: CLEAN` (0 names, 0 counts, 0 ante, 0 effect, 0 wired)

### 5. Full Simulator Suite
`python -m pytest vendor/balatro-rl/tests vendor/balatro-rl/balatro_sim/tests -q`
- Result: `1621 passed, 3 skipped, 4 deselected in 249.52s (0:04:09)`

---

## 5. Audit Verdict

**VERDICT: CLEAN**

Worker M1's implementation in `vendor/balatro-rl/balatro_sim/agent_v10.py` and `vendor/balatro-rl/tests/test_scaling_acceleration.py` fully complies with all integrity standards, architectural contracts, and human-fair simulation principles. No violations exist.
