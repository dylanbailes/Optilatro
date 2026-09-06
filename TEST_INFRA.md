# Optilatro V10 Enhancement: Test Architecture & Infrastructure (TEST_INFRA)

## 1. Overview & Architecture

The Optilatro V10 Enhancement test infrastructure is designed as an opaque-box, requirement-driven, multi-tiered test framework ensuring that all algorithmic components (R1: Multi-Hand Pace Rule, R2: Joker Portfolio & Feature Extraction, R3: Value Model Evaluation, R4: Counterfactual Shop Search & Swapping) function correctly under strict human-fair constraints (no deck draw-order peeking, no RNG stream lookahead, zero live state mutation).

### Test Layout & Discovery
```
Optilatro/
├── tests/
│   └── test_e2e_v10_requirements.py      # Root test runner entry point
├── vendor/balatro-rl/
│   └── tests/
│       ├── test_e2e_v10_requirements.py  # Production 4-Tier E2E test suite
│       ├── test_agent_v10.py             # Unit & heuristic regression tests
│       ├── test_seed_exactness.py        # CI gate for RNG determinism
│       └── ...                           # 1,562+ simulator unit tests
├── tools/
│   ├── portfolio.py                      # Joker portfolio classifier & feature extractor
│   ├── fit_shop_model.py                 # Offline value model training & interaction builder
│   └── gen_shop_dataset.py               # Rollout data generator
├── TEST_INFRA.md                         # Test architecture and methodology documentation
└── TEST_READY.md                         # Test readiness, tier mapping & coverage summary
```

---

## 2. 4-Tier Testing Strategy

The E2E test suite is partitioned into four hierarchical tiers:

### Tier 1: Requirement Feature Coverage (>=5 test cases per requirement)
- **R1 (Multi-Hand Pace Rule)**:
  - Exact formula calculation: $\text{pace} = \frac{\text{target} - \text{scored}}{\max(1, \text{hands\_left})} \times \text{pace\_mult}$.
  - Immediate play triggering upon meeting or exceeding per-hand pace.
  - Strategic discard execution when hand score is below per-hand pace.
  - Multiplier sensitivity ($\text{pace\_mult} = 0.5$ vs $1.0$).
  - Ante scope gating (active strictly on Ante 1; bypassed on Ante 2+).
  - Multi-hand stepwise progression clearing Ante 1 blinds.
- **R2 (Joker Portfolio Classification & Feature Extraction)**:
  - 6 canonical strategic roles: Chips, Flat Mult, xMult, Scaling, Economy, Retrigger.
  - Dual-role and hybrid jokers (e.g. `j_green_joker`, `j_constellation`, `j_wee`, `j_castle`, `j_vampire`).
  - Card & joker edition augmentations (Foil $\rightarrow$ +Chips, Holo $\rightarrow$ +Flat Mult, Poly $\rightarrow$ +xMult, Negative $\rightarrow$ +Slot).
  - 42-dimensional flat numeric feature vector completeness and sanity.
  - Invariants: determinism, deck order independence (reversed deck test), zero live state mutation.
  - Danger indicators (`zero_xmult_late`, `econ_heavy_late`, `no_scoring_early`, `is_balanced`).
- **R3 (Offline Value Model & Interaction Terms)**:
  - Non-linear domain interaction terms (`inter_chips_mult`, `inter_mult_xmult`, `inter_chips_xmult`, `inter_ante_xmult`, `inter_late_econ_penalty`, `inter_late_zero_xmult`).
  - Standardized JSON schema specification and weight validation.
  - Pure-Python / NumPy logistic inference $V(s') = \frac{1}{1 + e^{-z}}$.
  - Monotonicity property: adding xMult in late ante strictly raises $V(s')$.
  - Penalty validation: late-game zero xMult boards are penalized.
  - Sub-millisecond latency benchmark ($< 1\,\text{ms}$, typically $< 50\,\mu\text{s}$).
- **R4 (Counterfactual Shop Search & Swapping)**:
  - Human-fair default contract (`lookahead = False`).
  - Candidate item evaluation and top-ranked affordable purchase execution.
  - Dynamic slot management & room-making (selling lowest-value/redundant joker when full to acquire high-value jokers).
  - Interest target and savings discipline preservation.
  - Safe shop lifecycle state transitions (buy, sell, reroll, leave_shop).

### Tier 2: Boundary & Corner Cases
- Empty portfolios, \$0 dollars, 0 discards left, empty deck/hand handling.
- Negative money handling (Credit Card debt, clamped interest units).
- Zero hands remaining boundary (graceful termination, $P(\text{clear}) = 0.0$).
- Overfilled and maximal joker slots (Negative joker handling, clamped free slots).
- Extreme antes (Ante 8, Ante 16) and target chips ($100,000,000$).
- Custom and unrecognized joker keys fallback.
- Division-by-zero resilience on exhausted decks.

### Tier 3: Cross-Feature Interactions
- Pace rule decisions combined with portfolio danger features (`no_scoring_early`).
- Counterfactual shop search evaluating xMult swaps against redundant economy jokers ($\Delta V$).
- Deck reshaping synergies interacting with shop Tarot card valuation (Baron $\rightarrow$ Kings $\rightarrow$ Death boost).
- End-to-end shop purchase driving subsequent in-blind scoring & pace satisfaction.
- Value farming gated by clear probability ($P(\text{clear}) \ge 0.90$) preserving survival integrity.
- State feature extraction on live vs counterfactual copies without state leakage.

### Tier 4: Real-World Scenarios & Game Simulations
- Seed 205 clearance (historic Ante 1 Small Blind fatal seed cleared).
- Seed 275 clearance (historic Ante 1 Small Blind fatal seed cleared).
- Deterministic paired-seed rollout reproducibility.
- Farming-off V10 byte-for-byte exactness against baseline V9 (RULING-L0 / human-fair proof).
- Full multi-ante game rollouts across seeds 0 through 5.
- SearchShopV10 multi-round progression and economy management.

---

## 3. Expected Output Derivation & Verification Methodology

Every test in the suite derives its expected output from authoritative sources:
1. **Mathematical Invariants**: Explicit algebraic derivations for pace calculations, binomial/hypergeometric clear probabilities, logistic sigmoid mappings, and non-linear interactions.
2. **Game Engine Invariants**: Exact state transitions in `BalatroGame`, card evaluation outcomes in `hand_eval.py`, scoring calculations in `scoring.py`, and catalogue prices in `shop.py`.
3. **Reference Baseline Oracles**: Frozen `HeuristicV9` policy used as the exact comparative oracle for the `farm_clear_threshold = 1.0` control arm.

---

## 4. Test Execution Commands

```bash
# Run the complete V10 E2E requirement test suite (42 tests)
python -m pytest vendor/balatro-rl/tests/test_e2e_v10_requirements.py -v

# Run from root test entry point
python -m pytest tests/test_e2e_v10_requirements.py -v

# Run full project test suite (1,604+ tests)
python -m pytest vendor/balatro-rl/tests vendor/balatro-rl/balatro_sim/tests -q

# Run static audit gates
python tools/audit_jokers_static.py
python tools/audit_consumables_static.py
python tools/audit_bosses_static.py
python tools/audit_tags_static.py
```
