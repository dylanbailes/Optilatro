# Final Acceptance Review & Adversarial Quality Report: Milestone 3 & Milestone 4

## 1. Observation

- **Review Target**:
  - Milestone 3: Rollout Dataset Generation & Offline Value Model (R3)
  - Milestone 4: True L1 Counterfactual Shop Search (SearchShopV10) (R4)
  - Artifacts:
    - vendor/balatro-rl/balatro_sim/agent_v10.py (2,692 lines)
    - vendor/balatro-rl/balatro_sim/shop_model.json (205 lines, 4,155 bytes)
    - tools/portfolio.py (518 lines)
    - tools/gen_shop_dataset.py (153 lines)
    - tools/fit_shop_model.py (156 lines)
    - vendor/balatro-rl/balatro_sim/agent_v9.py (frozen baseline integrity verified)

- **Verification Test Executions**:
  1. **Full Simulator Unit Test Suite**:
     - Command: python -m pytest vendor/balatro-rl/tests vendor/balatro-rl/balatro_sim/tests -q
     - Result: **1,612 passed, 3 skipped, 4 deselected in 331.12s (100% green)**.
  2. **E2E Requirements & Portfolio Test Suite**:
     - Command: python -m pytest tests/test_portfolio.py vendor/balatro-rl/tests/test_e2e_v10_requirements.py -v
     - Result: **65 passed in 125.36s (100% green across all 4 tiers)**.
  3. **Agent V10 Unit Tests**:
     - Command: python -m pytest vendor/balatro-rl/tests/test_agent_v10.py -v
     - Result: **50 passed in 60.07s (100% green)**.
  4. **CI Seed Exactness Gate**:
     - Command: python -m pytest vendor/balatro-rl/tests/test_seed_exactness.py -m ci_gate -v
     - Result: **4 passed in 20.17s (SHA stability verified)**.
  5. **Static Audits (4/4 Clean)**:
     - python tools/audit_jokers_static.py: GATES: CLEAN (DUPES 0, DEAD 0, STUBS 0, GAPS 0, TYPE 0, SIG 0, STATE 0, NOSCAN 0).
     - python tools/audit_consumables_static.py: GATES: CLEAN.
     - python tools/audit_bosses_static.py: GATES: CLEAN.
     - python tools/audit_tags_static.py: GATES: CLEAN.
  6. **Inference Latency & Zero External Dependency Benchmark**:
     - evaluate_shop_value: **20.1 us per evaluation** (budget was < 30.0 us, achieving a ~33% latency safety margin).
     - Dependencies: Standard library only (math, json, typing, pathlib). Zero PyTorch, scikit-learn, or external C-extensions in evaluation path.

- **Integrity Inspection Results**:
  - No hardcoded test seed shortcuts or fake conditional branches detected.
  - No RNG stream consumption or draw order peeking (human-fair invariant fully preserved).
  - Pure non-mutating state extraction (formulate_counterfactual_state).
  - Baseline agent_v9.py was not modified during M3/M4 development.

---

## 2. Logic Chain

1. **Model Mathematical Correctness & Fast Evaluation**:
   - _load_shop_value_model() precomputes the standardized linear weights:
     c0 = bias - sum(w_i * mean_i / std_i), c_i = w_i / std_i
   - Evaluation computes z = c0 + sum(c_i * f_i), clips z in [-30.0, 30.0], and applies the sigmoid sigma(z) = 1 / (1 + exp(-z)).
   - This formulation is algebraically identical to standard logistic regression with z-score standardization, eliminating standard deviation division and vector allocations during runtime inference.
   - Holdout Test AUC is **0.7819** on 13,572 independent test snapshots from seeds 1000-3999, exceeding the > 0.70 target.

2. **L1 Counterfactual Search Logic (SearchShopV10._search_shop)**:
   - **Candidate Action Formulation**: Formulates candidate actions a in {buy, sell_joker, swap_joker, reroll, leave_shop} and projects feature states s_prime_a = formulate_counterfactual_state(game, a) without cloning BalatroGame.
   - **Value Gain Ranking**: Ranks candidate actions by Delta V(a) = V(s_prime_a) - V(s).
   - **Dynamic Room Making & Joker Swaps**:
     - When slots are full (len(jokers) >= joker_slots), evaluates swaps swap(j, i) simulating selling joker j and buying item i.
     - If dollars + sell_val >= price and Delta V > min_delta_v, returns step 1 {type: sell_joker, joker_idx: j} and tracks _pending_swap_target_idx = i.
     - On the next step, completes the purchase of item i with the newly freed slot and reclaimed cash.
   - **Standalone Joker Pruning**: At Ante >= 3, evaluates selling dead/redundant jokers if removing them yields a net positive delta (Delta V > 0.02) by lifting danger penalties.
   - **Financial Discipline**: Enforces interest preservation ( interest target) in save mode unless candidate improvement exceeds min_delta_v = 0.005.

3. **Adversarial Robustness & Failure Mode Defense**:
   - *Interrupted Swaps*: If shop state changes or item i becomes unavailable before step 2 completes, _pending_swap_target_idx safely verifies affordability, slot availability, and un-sold status before executing, falling back gracefully if invalid.
   - *Numerical Extremes*: z-clamping in [-30, 30] guarantees zero OverflowError in math.exp(-z).
   - *Missing Feature Keys*: Default fallbacks in .get(name, 0.0) ensure forward compatibility if new features are added.

---

## 3. Caveats

- **Linear Logistic Decision Boundary**: The offline value model is an L2-regularized linear model over 48 engineered features (including 6 quadratic/interaction terms). While fast (< 21 us) and highly interpretable, complex higher-order relationships outside the 6 interaction terms rely on linear weighting.
- **Rollout Exploration Sampling Scope**: Training data was generated using epsilon-greedy exploratory perturbations across seeds 1000-3999; holdout benchmarks (0-699) were kept strictly unseen.

---

## 4. Conclusion & Verdict

**Verdict**: **APPROVE**

Milestone 3 (R3 Offline Value Model) and Milestone 4 (R4 SearchShopV10 L1 Counterfactual Search) satisfy all acceptance criteria:
1. Pure Python value model evaluates in **20.1 us** with zero external runtime dependencies.
2. SearchShopV10._search_shop implements full counterfactual action ranking, dynamic room-making swaps, interest discipline, and standalone joker pruning.
3. 100% of test suites pass: 1,612 simulator unit tests, 65 E2E requirement tests, 50 agent_v10 unit tests, 4 CI seed exactness tests, and 4 static audit gates clean.
4. Human-fair invariants and frozen baseline integrity are completely maintained.

---

## 5. Verification Method

To independently verify all findings:

1. Full Simulator Unit Tests:
   python -m pytest vendor/balatro-rl/tests vendor/balatro-rl/balatro_sim/tests -q

2. E2E Requirement Tests:
   python -m pytest tests/test_portfolio.py vendor/balatro-rl/tests/test_e2e_v10_requirements.py -v

3. Agent V10 Unit Tests:
   python -m pytest vendor/balatro-rl/tests/test_agent_v10.py -v

4. CI Seed Exactness Gate:
   python -m pytest vendor/balatro-rl/tests/test_seed_exactness.py -m ci_gate -v

5. Static Audits:
   python tools/audit_jokers_static.py
   python tools/audit_consumables_static.py
   python tools/audit_bosses_static.py
   python tools/audit_tags_static.py
