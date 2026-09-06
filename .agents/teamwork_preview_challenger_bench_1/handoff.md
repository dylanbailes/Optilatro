# Full Benchmark Bank (Seeds 0–299) Evaluation Report

**Milestone**: Benchmark & Performance Target Verification (Seeds 0–299, Red Deck / White Stake, Human-Fair Seed Mode)  
**Agent**: `teamwork_preview_challenger_bench_1`  
**Verdict**: **`REQUEST_CHANGES`**

---

## 1. Observation

### Benchmark Execution
- **Command Run**:
  ```bash
  python bench/bench_agent_v10.py --games 300 --policies heuristic_v9,heuristic_v10,search_shop_v10 --workers 8 --report vendor/balatro-rl/results/bench_0_299_eval.html
  ```
- **Telemetry Processing**:
  ```bash
  python tools/report_bench_ab.py --out vendor/balatro-rl/results/bench_0_299_ab --seed-bank "Seeds 0-299" \
    --arm "Baseline (goal_iter7_D)" vendor/balatro-rl/results/bench_0_299_tel/goal_iter7_baseline "python bench/bench_agent_v10.py --games 300 --policies heuristic_v10" \
    --arm "Heuristic V9 (baseline)" vendor/balatro-rl/results/bench_0_299_tel/heuristic_v9 "python bench/bench_agent_v10.py --games 300 --policies heuristic_v9" \
    --arm "Heuristic V10" vendor/balatro-rl/results/bench_0_299_tel/heuristic_v10 "python bench/bench_agent_v10.py --games 300 --policies heuristic_v10" \
    --arm "SearchShop V10" vendor/balatro-rl/results/bench_0_299_tel/search_shop_v10 "python bench/bench_agent_v10.py --games 300 --policies search_shop_v10" \
    --note "Full benchmark bank evaluation comparing V10 against frozen V9 and goal_iter7_final_D.json baseline."
  ```

### Aggregate Performance Summary

| Policy / Arm | Wins / 300 | Win Rate (95% Wilson CI) | Ante 1 Deaths | Ante 1 Death Rate | Mean Ante | Mean Steps | Econ-Source $/run | Interest $/run |
|---|---|---|---|---|---|---|---|---|
| **Reference Baseline (`goal_iter7_final_D.json`)** | **20** | **6.67%** [4.36%, 10.07%] | **14** | **4.67%** | **4.57** | 133 | $23.2 | $15.1 |
| **`heuristic_v9` (Frozen Baseline)** | 11 | 3.67% [2.06%, 6.45%] | 33 | 11.00% | 4.49 | 126 | $9.8 | $14.5 |
| **`heuristic_v10`** | 10 | 3.33% [1.82%, 6.03%] | 27 | 9.00% | 4.27 | 123 | $20.4 | $13.9 |
| **`search_shop_v10`** | **18** | **6.00%** [3.83%, 9.28%] | **25** | **8.33%** | **4.35** | 126 | $21.4 | $14.3 |

### Acceptance Target Comparison

| Metric | Target Floor / Ceiling | `goal_iter7_final_D.json` Baseline | `search_shop_v10` Empirical | Status |
|---|---|---|---|---|
| **Ante 8 Win Rate** | **> 7.00% (> 21 wins)** | 6.67% (20 wins) | **6.00% (18 wins)** | ❌ **FAIL** (-4 wins vs target, -2 wins vs baseline) |
| **Ante 1 Deaths** | **< 4.67% (< 14 deaths)** | 4.67% (14 deaths) | **8.33% (25 deaths)** | ❌ **FAIL** (+11 deaths vs target / baseline) |

### Seed-Level Breakdown
- **Winning Seeds**:
  - `Baseline (goal_iter7_D)` (20): `[7, 21, 37, 43, 58, 62, 95, 104, 113, 139, 143, 160, 177, 182, 186, 198, 236, 249, 283, 293]`
  - `heuristic_v9` (11): `[7, 17, 51, 58, 107, 111, 139, 197, 211, 219, 272]`
  - `heuristic_v10` (10): `[7, 37, 111, 139, 155, 182, 215, 217, 236, 283]`
  - `search_shop_v10` (18): `[7, 37, 58, 60, 62, 95, 111, 121, 130, 139, 155, 215, 217, 226, 236, 282, 283, 298]`
- **Wins Analysis for `search_shop_v10`**:
  - **Shared Wins with Baseline** (8): `[7, 37, 58, 62, 95, 139, 236, 283]`
  - **New Wins Gained by SearchShop** (10): `[60, 111, 121, 130, 155, 215, 217, 226, 282, 298]`
  - **Baseline Wins Lost** (12): `[21, 43, 104, 113, 143, 160, 177, 182, 186, 198, 249, 293]`

- **Ante 1 Fatal Seeds**:
  - `Baseline (goal_iter7_D)` (14): `[82, 100, 118, 164, 174, 205, 224, 242, 250, 260, 262, 267, 269, 275]`
  - `search_shop_v10` (25): `[0, 16, 52, 57, 67, 82, 116, 118, 120, 125, 149, 154, 162, 168, 199, 220, 230, 242, 245, 249, 262, 269, 281, 287, 299]`
  - **Baseline Ante 1 Deaths Successfully Cleared** (9): `[100, 164, 174, 205, 224, 250, 260, 267, 275]` (including targeted fatal seeds **205** and **275**).
  - **New Ante 1 Deaths Introduced** (20): `[0, 16, 52, 57, 67, 116, 120, 125, 149, 154, 162, 168, 199, 220, 230, 245, 249, 281, 287, 299]`.

---

## 2. Logic Chain

1. **Relative Gains of L1 Shop Search vs Fixed Heuristics**:
   - `search_shop_v10` outperforms `heuristic_v9` by +2.33 percentage points (18 wins vs 11 wins, a +63.6% relative gain) and cuts Ante 1 deaths from 33 to 25 (-24.2%).
   - `search_shop_v10` outperforms `heuristic_v10` by +2.67 percentage points (18 wins vs 10 wins, a +80.0% relative gain).
   - Counterfactual shop value modeling successfully unlocks 10 new winning seeds not won by the iter7 baseline, proving the utility of dynamic value search and room-making swaps.

2. **Root Cause Analysis of the Target Deficit**:
   - **Missing Early Scoring Urgency (`engineless_urgency_ante`)**:
     - In `goal_iter7_final_D.json`, Configuration D utilized `engineless_urgency_ante: 2`. This boosted scoring joker valuations and discounted economy cards when the agent owned no scoring engine in Ante $\le 2$.
     - In `vendor/balatro-rl/balatro_sim/agent_v10.py`, `V10_DEFAULTS["engineless_urgency_ante"]` is currently set to `0` (dormant).
     - Without early scoring urgency, the offline value model's positive weight on `interest_units` (+0.1094) and negative weight on standalone un-synergized jokers causes the agent to pass on marginal early scoring jokers to preserve interest, leading to fatal Ante 1 and Ante 2 blinds on low-roll deals (20 new Ante 1 deaths).
   - **Loss of 12 Baseline Wins**:
     - Due to early game attrition, 12 runs that successfully converted to Ante 8 wins in iter7 died prematurely in Antes 1–4 under `search_shop_v10`.

3. **Conclusion Supported by Evidence**:
   - While `SearchShopV10` is functionally sound and superior to the raw heuristic policies, the shipped default configuration in `agent_v10.py` does not meet the contract criteria (> 7.0% win rate / < 4.67% Ante 1 deaths).

---

## 3. Caveats

- **Seed Exactness & Human-Fairness**: All policies strictly adhered to human-fair seed mode; zero deck peeking or future RNG stream lookaheads occurred (`ci_gate` tests pass 100%).
- **Holdout Banks**: Banks 300–499 and 500–699 were preserved untouched for out-of-sample holdout verification and were not tested in this round to prevent data contamination.

---

## 4. Conclusion & Actionable Mitigations

**Verdict**: **`REQUEST_CHANGES`**

### Summary of Gates
- [x] Human-fair execution (zero RNG leakage, deterministic replay): **PASS**
- [x] Clear Ante 1 Small Blind on fatal seeds 205 and 275: **PASS** (both cleared)
- [ ] Win rate > 7.0% (> 21 wins on 300 games): **FAIL** (18 wins = 6.00%)
- [ ] Ante 1 deaths < 14 (< 4.67% on 300 games): **FAIL** (25 deaths = 8.33%)

### Recommended Mitigations for Implementation Agents:
1. **Enable Early Scoring Urgency**: Set `engineless_urgency_ante = 2` in `V10_DEFAULTS` or integrate early scoring survival floor directly into `SearchShopV10` when `n_chips == 0 and n_flat_mult == 0` in Ante $\le 2$.
2. **Calibrate Early Interest Gate**: Prevent the value model from prioritizing interest over survival when no scoring joker is owned in Ante 1.
3. **Re-evaluate on 300 Seeds**: Re-run the benchmark once early urgency is restored to confirm clearance of the 22+ win (> 7.0%) and < 14 Ante-1 death thresholds.

---

## 5. Verification Method

To independently inspect and reproduce these findings:

1. **Inspect Full Telemetry & Paired Report**:
   ```bash
   view_file vendor/balatro-rl/results/bench_0_299_ab/README.md
   view_file vendor/balatro-rl/results/bench_0_299_ab/stats/aggregates.json
   view_file vendor/balatro-rl/results/bench_0_299_ab/stats/paired.json
   ```

2. **Re-run the Benchmark Command**:
   ```bash
   python bench/bench_agent_v10.py --games 300 --policies heuristic_v9,heuristic_v10,search_shop_v10 --workers 8 --report vendor/balatro-rl/results/bench_0_299_eval.html
   ```
