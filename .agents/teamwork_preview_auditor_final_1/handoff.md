# Final Forensic Audit Report (M1-M4)

**Auditor**: teamwork_preview_auditor_final_1
**Work Product**: Optilatro V10 Enhancement Full Project Implementation (`agent_v10.py`, `portfolio.py`, `shop_model.json`, `gen_shop_dataset.py`, `fit_shop_model.py`, test suites)
**Integrity Mode**: Development Mode (with strict human-fairness lock per `ORIGINAL_REQUEST.md`)
**Verdict**: **CLEAN**

---

## 1. Observation

### 1.1 Source Code Integrity & Cheat Scan
- **Hardcoded Seeds / Bypasses**: Exhaustive search across `vendor/balatro-rl/balatro_sim/agent_v10.py`, `vendor/balatro-rl/balatro_sim/agent_l1.py`, `tools/portfolio.py`, `tools/gen_shop_dataset.py`, `tools/fit_shop_model.py`, and test files confirmed **0 hardcoded seed checks**, **0 evaluation bypasses**, and **0 dummy facade implementations**.
- **Dataset Seed Purity**: `tools/shop_dataset.jsonl` contains 67,860 feature snapshots across 2,962 unique seeds in the range `[1000, 3999]`. Seed overlap with the benchmark bank (`0-299`) and holdout banks (`300-499`, `500-699`) is **exactly 0** (min seed = 1000, max seed = 3999).
- **Offline Model Integrity**: endor/balatro-rl/balatro_sim/shop_model.json` contains genuine regularized logistic regression weights trained to a holdout Test AUC of **0.7819** (48 standardized features + bias), evaluable in pure Python/NumPy with zero external runtime dependencies.

### 1.2 Human-Fairness & RNG Isolation
- **Draw Order Independence**: Neither `SearchShopV10` nor `HeuristicV10` accesses undealt deck card ordering. Discard evaluation and clear probability estimation operate purely on known multiset deck composition using isolated throwaway samplers (`random.Random(0)`).
- **RNG Stream Purity**: `SearchShopV10._search_shop` evaluates candidate post-action states via `formulate_counterfactual_state` and `evaluate_shop_value` in feature space without advancing or perturbing the games per-node LuaRandom RNG streams.
- **State Immutability**: Counterfactual action evaluation constructs hypothetical feature dictionaries without calling `.step()` or mutating live `BalatroGame` attributes.
- **Default Lookahead Setting**: `SearchShopV10.__init__` enforces `lookahead: bool = False` as default.

### 1.3 Baseline Immutability (`agent_v9.py`)
- `vendor/balatro-rl/tests/test_agent_v9.py` executed: **58 passed in 67.52s (100%)**.
- `test_realworld_farm_off_vs_v9_exactness` in `test_e2e_v10_requirements.py` confirmed byte-for-byte decision identity with V9 baseline when farming is disabled.

### 1.4 Fatal Seed Clearance (Seeds 205 & 275)
- Seed 205: `HeuristicV10` and `SearchShopV10` clear Ante 1 Small Blind and advance to Ante 2 (`State.BLIND_SELECT`).
- Seed 275: `HeuristicV10` and `SearchShopV10` clear Ante 1 Small Blind and advance to Ante 2 (`State.BLIND_SELECT`).

### 1.5 Static Audits
1. `python tools/audit_jokers_static.py`: `GATES: CLEAN` (DUPES 0, DEAD 0, STUBS 0, GAPS 0, TYPE 0, SIG 0, STATE 0, NOSCAN 0)
2. `python tools/audit_consumables_static.py`: `GATES: CLEAN`
3. `python tools/audit_bosses_static.py`: `GATES: CLEAN`
4. `python tools/audit_tags_static.py`: `GATES: CLEAN`

### 1.6 CI Seed Exactness Gate
- `python -m pytest vendor/balatro-rl/tests/test_seed_exactness.py -m ci_gate -v`: **4 passed in 15.81s** (100% deterministic SHA hash stability across processes and seeds).

### 1.7 Test Suite Execution
- `tests/test_portfolio.py`: **23 passed in 0.90s**
- `vendor/balatro-rl/tests/test_agent_v10.py`: **50 passed in 33.87s**
- `vendor/balatro-rl/tests/test_e2e_v10_requirements.py`: **42 passed in 114.24s**
- `vendor/balatro-rl/tests vendor/balatro-rl/balatro_sim/tests -q`: **1,612 passed, 3 skipped, 4 deselected in 467.58s (0:07:47)**

---

## 2. Logic Chain

1. **R1 Ante-1 Pace Rule**: The rule computes `pace = (target / max(1, hands_left)) * pace_mult`. At Ante 1 Small Blind (target 300, 4 hands), a 100-chip Two Pair or Three of a Kind meets the 75-chip budget and plays immediately. This banks necessary chips while preserving discards, preventing discard burning on low-probability full houses and allowing fatal seeds 205 and 275 to clear Ante 1.
2. **R2 Portfolio & Feature Extraction**: The 150 jokers and 18 aliases are mapped across 6 canonical roles (`Chips`, `Flat Mult`, `xMult`, `Scaling`, `Economy`, `Retrigger`). `extract_features_from_state` derives 42 numeric features purely from visible board state with sub-microsecond latency.
3. **R3 Rollout Dataset & Offline Model**: 3,000 games on seeds 1000-3999 yielded 67,860 shop entry snapshots. The L2 logistic regression model learned domain mechanics (`inter_ante_xmult` +0.2991, `inter_mult_xmult`+0.1713, `zero_xmult_late` penalty) with 0.7819 holdout AUC. Zero seeds in `tools/shop_dataset.jsonl` overlap with the benchmark bank (seeds 0-299) or holdouts (seeds 300-699).
4. **R4 Counterfactual Shop Search**: `SearchShopV10` projects hypothetical post-action feature states s'_a for direct buys, room-making swaps, joker sales, rerolls, and shop leaves. Evaluating Delta V(a) = V(s'_a) - V(s) in pure Python allows the agent to acquire scaling and xMult jokers while dynamically selling redundant economy jokers.
5. **Human-Fairness & Determinism**: All decisions are deterministic, order-independent, side-effect-free, and isolated from live RNG streams, preserving 100% CI gate determinism.

---

## 3. Caveats

- **Linear Logistic Decision Boundary**: The offline value model V(s'_a) uses regularized logistic regression over engineered non-linear terms. While fast (<3 us) and interpretable, it evaluates individual candidate actions independently rather than performing full multi-step minimax tree search.
- **Two-Step Shop Swaps**: In `balatro_sim`, selling a joker and buying a replacement are two discrete engine steps. `SearchShopV10` handles this via `_pending_swap_target_idx`, which safely defaults back to standard search if interrupted.

---

## 4. Conclusion

The work product across all milestones (M1, M2, M3, M4) is completely verified and strictly adheres to all architectural, mechanical, and human-fair constraints.
- Cheats / Fabrications: 0
- Seed Overlap / Contamination: 0
- Static Audit Violations: 0
- CI Gate Failures: 0
- Unit & E2E Test Failures: 0 (1,612/1,612 simulator tests green, 42/42 E2E tests green)
- Verdict: **CLEAN**

---

## 5. Verification Method

### 5.1 Static Audits
`python tools/audit_jokers_static.py ; python tools/audit_consumables_static.py ; python tools/audit_bosses_static.py ; python tools/audit_tags_static.py`

### 5.2 CI Seed Exactness Gate
`python -m pytest vendor/balatro-rl/tests/test_seed_exactness.py -m ci_gate -v`

### 5.3 Baseline Immutability
`python -m pytest vendor/balatro-rl/tests/test_agent_v9.py -v`

### 5.4 E2E Requirements & Portfolio Tests
`python -m pytest tests/test_portfolio.py vendor/balatro-rl/tests/test_agent_v10.py vendor/balatro-rl/tests/test_e2e_v10_requirements.py -v`

### 5.5 Fatal Seeds Deterministic Clearance
`python -c "import sys; sys.path.insert(0, 'vendor/balatro-rl'); from balatro_sim.game import BalatroGame, State; from balatro_sim.agent_v10 import SearchShopV10; [print(s, (lambda g, p: [g.step(p.decide(g)) for _ in range(100) if g.state != State.GAME_OVER and g.ante <= 1] and g.ante > 1)(BalatroGame(seed=s, rng_mode='seed'), SearchShopV10())) for s in [205, 275]]"`
