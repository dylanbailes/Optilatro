# Handoff Report: Challenger 2 (Paired Benchmark Evaluator Seeds 0–299)

**Verdict**: **REJECT**  
**Milestone**: M1 (Core Policy Enhancement R1+R2+R3)  
**Evaluator**: Challenger 2 (`teamwork_preview_challenger_bench_gen3`)  

---

## 1. Observation

### Evaluated Artifacts & Raw Execution Outputs
1. **Benchmark Command Executed**:
   ```bash
   python bench/bench_agent_v10.py --policies search_shop_v10 --seeds 0-299 --workers 8 --report vendor/balatro-rl/results/bench_0_299_search_shop_v10_breakthrough.json
   ```
2. **Breakthrough Candidate Summary** (`vendor/balatro-rl/results/bench_0_299_search_shop_v10_breakthrough.json`):
   - Total Games: 300
   - Wins: **21 / 300 = 7.00%**
   - Ante 1 Deaths: **12 / 300 = 4.00%**
   - Mean Ante: **4.71** (vs baseline 4.94)
   - Death Distribution:
     `ante 1: 12 (4.00%), ante 2: 28 (9.33%), ante 3: 54 (18.00%), ante 4: 59 (19.67%), ante 5: 50 (16.67%), ante 6: 39 (13.00%), ante 7: 23 (7.67%), ante 8: 14 (4.67%), ante 9 (wins): 21 (7.00%)`
3. **Baseline Comparison** (`vendor/balatro-rl/results/bench_0_299_search_shop_v10.json`):
   - Baseline Wins: **26 / 300 = 8.67%**
   - Baseline Ante 1 Deaths: **11 / 300 = 3.67%**
   - Net Outcome: **-5 wins (REGRESSION)**, **+1 Ante 1 death (REGRESSION)**.
4. **Diagnostic Ablation** (`scaling_accel_enabled: False`, `vendor/balatro-rl/results/bench_0_299_no_scaling_accel.json`):
   - Total Games: 300
   - Wins: **29 / 300 = 9.67%**
   - Ante 1 Deaths: **11 / 300 = 3.67%**
   - Mean Ante: **4.96**
5. **Seed-Level Autopsy**:
   - **Lost Wins (13 seeds)**: `[21, 30, 40, 43, 60, 93, 95, 131, 139, 188, 198, 280, 298]`
   - **Gained Wins (8 seeds)**: `[7, 17, 64, 97, 105, 182, 190, 241]` (all 8 also won in ablation)
   - **New Ante 1 Death (1 seed)**: `Seed 245`
     - Played 3 consecutive 1-card High Cards (16, 21, 28 pts) on Big Blind Ante 1 with `j_green_joker`, then Two Pair (360 pts). Total 425 / 450 chips. Died on Ante 1 Big Blind.
   - **Premature Scaling Deaths (23 seeds)**: Runs where Tier S2 scaling acceleration burned multiple hands playing low-scoring cards (<400 chips) and subsequently died in that round (e.g. seeds `2, 41, 47, 52, 55, 81, 102, 112, 120, 134, 153, 172, 180, 203, 204, 209, 218, 223, 242, 245, 248, 250, 281`).

---

## 2. Logic Chain

1. **Observation**: Acceptance criteria require:
   - Win rate $\ge 10.0\%$ ($\ge 30$ wins / 300).
   - Ante 1 mortality $< 4.00\%$ ($< 12$ deaths / 300).
2. **Inference**:
   - Actual candidate performance is 21 wins (7.00%) and 12 Ante-1 deaths (4.00%).
   - The candidate fails the win rate criterion by 9 wins ($21 < 30$).
   - The candidate fails the Ante-1 mortality criterion ($12 \not< 12$).
   - Both criteria are violated.
3. **Observation**: In Seed 245 and 22 other seeds, `_find_scaling_action` triggered Tier S2 because `(p_clear is not None and p_clear >= 0.995)` was satisfied early in the round, despite the top play failing to guarantee clearing the remaining target.
4. **Inference**:
   - `_find_scaling_action` threw away hands by prioritizing minor joker scaling increments (+1 mult) over blind survival.
   - This directly caused the death in Seed 245 and caused 8 potential winning seeds (`[21, 62, 81, 98, 139, 158, 202, 281]`) to die prematurely.
5. **Observation**: In the diagnostic ablation (`scaling_accel_enabled: False`), win count rose to 29 (9.67%) and Ante 1 deaths fell to 11 (3.67%).
6. **Inference**:
   - While R1 (capital deployment) and R2 (synergistic tarots/planets) provided positive value lifting base performance from 26 to 29 wins, R3 was severely bugged and caused a net 8-win collapse.
   - Even without R3, 29 wins is 9.67%, falling 1 win short of the 30-win target.
   - Therefore, the candidate policy cannot be approved in its current state.

---

## 3. Caveats

- **Holdout Bank (Seeds 300–499)**: Not evaluated in this report because the candidate failed the primary Seeds 0–299 bank gate. Testing generalization on holdout is only meaningful after clearing the primary bank.
- **R1 Liquidation Tuning**: The relaxation of interest floors in Antes 6–7 contributed to several lost runs (e.g. seeds 30, 40, 60) due to over-rerolling. Tuning this floor will likely provide the final margin needed to surpass 30 wins.

---

## 4. Conclusion

**Verdict: REJECT**

The breakthrough policy submitted in `vendor/balatro-rl/balatro_sim/agent_v10.py` regresses from baseline (26W / 11D -> 21W / 12D) and fails both Acceptance Criteria:
- **Criterion 1 (Win rate >= 10.0%)**: FAILED (21 wins = 7.00% vs target >= 30 wins / 10.0%).
- **Criterion 2 (Ante 1 deaths < 12)**: FAILED (12 deaths = 4.00% vs target < 12 deaths / 4.00%).

The policy must be returned to Worker M1 to fix the scaling acceleration logic (specifically eliminating the unvalidated $P(\text{clear}) \ge 0.995$ bypass in Tier S2) and re-tuning capital deployment floors.

---

## 5. Verification Method

To reproduce these empirical findings independently:

```bash
# 1. Reproduce candidate benchmark (21 wins, 12 Ante-1 deaths)
python bench/bench_agent_v10.py --policies search_shop_v10 --seeds 0-299 --workers 8 --report vendor/balatro-rl/results/bench_0_299_search_shop_v10_breakthrough.json

# 2. Reproduce diagnostic ablation with scaling acceleration disabled (29 wins, 11 Ante-1 deaths)
python bench/bench_agent_v10.py --policies search_shop_v10 --seeds 0-299 --workers 8 --params "{\"scaling_accel_enabled\": false}" --report vendor/balatro-rl/results/bench_0_299_no_scaling_accel.json

# 3. Verify Seed 245 fatal throw on Ante 1 Big Blind
python -c "
import sys; sys.path.insert(0, 'vendor/balatro-rl')
from balatro_sim.game import BalatroGame
from balatro_sim.agent_v10 import SearchShopV10
from balatro_sim.rollout import rollout

g = BalatroGame(seed=245, rng_mode='seed')
r = rollout(g, SearchShopV10())
print('Seed 245 default:', r['ante'], r['won'], r['stats']['co_owned'][-4:])

g2 = BalatroGame(seed=245, rng_mode='seed')
r2 = rollout(g2, SearchShopV10(params={'scaling_accel_enabled': False}))
print('Seed 245 no-scaling:', r2['ante'], r2['won'])
"
```

Invalidation conditions:
- Candidate achieves $\ge 30$ wins and $< 12$ Ante 1 deaths on Seeds 0–299.
- Seed 245 survives Ante 1 under default settings.
