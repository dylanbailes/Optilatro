# Handoff Report — Challenger 2 Benchmark Verification (`teamwork_preview_challenger_bench_gen2`)

**Explicit Verdict**: **REJECT**

The evaluated policy `search_shop_v10` fails both primary benchmark acceptance criteria by a wide margin on Seeds 0–299 and shows severe degradation compared to baseline `goal_iter7_final_D.json`:
- **Win Rate**: **3.33%** (10 wins / 300) vs Acceptance Target **> 7.0%** (> 21 wins / 300) — **FAILED**
- **Ante 1 Deaths**: **22 deaths** (7.33%) vs Acceptance Target **< 14 deaths** (< 4.67%) — **FAILED** (severe regression from baseline 14 deaths)
- **Holdout Bank (Seeds 300–499)**: **1.00% win rate** (2 wins / 200) and **11 Ante 1 deaths** (5.50%)

---

## 1. Observation

### 1.1 Primary Benchmark Bank (Seeds 0–299, Default Parameters)
Command executed:
```bash
python bench/bench_agent_v10.py --seeds 0-299 --workers 16 --policies search_shop_v10
```
Telemetry sidecar: `vendor/balatro-rl/results/bench_0_299_search_shop_v10.json`

| Metric | Baseline (`goal_iter7_final_D.json`) | Evaluated (`search_shop_v10`) | Acceptance Target | Status |
|---|---|---|---|---|
| **Total Runs** | 300 | 300 | 300 | — |
| **Wins** | 20 (6.67%) | **10 (3.33%)** | **> 21 (> 7.0%)** | **FAIL** |
| **95% Wilson CI (Wins)** | [4.36%, 10.07%] | [1.82%, 6.03%] | — | Non-overlapping upper vs target |
| **Ante 1 Deaths** | 14 (4.67%) | **22 (7.33%)** | **< 14 (< 4.67%)** | **FAIL (+8 deaths)** |
| **95% Wilson CI (A1 Deaths)** | [2.80%, 7.68%] | [4.89%, 10.85%] | — | Regressed |
| **Mean Ante** | 4.57 | 4.06 | — | -0.51 antes |
| **Median Ante** | 4 | 4 | — | — |
| **Mean Econ Source $** | $23.24 | $11.89 | — | -48.8% |
| **Mean Interest $** | $15.11 | $8.66 | — | -42.7% |
| **Mean Tarots / Planets** | 6.5 / 2.0 | 4.9 / 4.2 | — | — |

#### Ante Mortality Distribution (Seeds 0–299):
```
Ante    Baseline (goal_iter7_final_D)    Evaluated (search_shop_v10)
Ante 1:        14 ( 4.67%)                      22 ( 7.33%)  [+8 deaths]
Ante 2:        34 (11.33%)                      38 (12.67%)
Ante 3:        38 (12.67%)                      57 (19.00%)  [+19 deaths]
Ante 4:        79 (26.33%)                      77 (25.67%)
Ante 5:        50 (16.67%)                      45 (15.00%)
Ante 6:        36 (12.00%)                      36 (12.00%)
Ante 7:        20 ( 6.67%)                       9 ( 3.00%)
Ante 8:         9 ( 3.00%)                       6 ( 2.00%)
Ante 9 (Wins): 20 ( 6.67%)                      10 ( 3.33%)  [-10 wins]
```

### 1.2 Paired Seed-by-Seed Flip Analysis vs Baseline
Executed via `tools/verify_bench_acceptance.py`:
- **Concordant Wins (both won)**: 3 seeds: `[7, 143, 236]`
- **Baseline-only Wins (baseline won, eval lost)**: **17 seeds**:
  `[21, 37, 43, 58, 62, 95, 104, 113, 139, 160, 177, 182, 186, 198, 249, 283, 293]`
- **Eval-only Wins (new wins)**: 7 seeds:
  `[90, 96, 147, 155, 175, 226, 275]`
- **Net Win Gain**: **-10 wins** (McNemar $\chi^2 = 3.375$)
- **Ante 1 Saved (died in baseline -> cleared in eval)**: 11 seeds:
  `[100, 118, 164, 174, 205, 224, 250, 260, 262, 267, 275]`
- **Ante 1 Regressed (survived in baseline -> died in Ante 1)**: **19 seeds**:
  `[1, 13, 16, 30, 47, 50, 72, 125, 126, 149, 154, 162, 168, 199, 213, 245, 249, 287, 299]`

### 1.3 Holdout Bank Benchmark (Seeds 300–499)
Command executed:
```bash
python bench/bench_agent_v10.py --seeds 300-499 --workers 16 --policies search_shop_v10
```
Telemetry sidecar: `vendor/balatro-rl/results/bench_300_499_search_shop_v10.json`

- **Total Runs**: 200
- **Total Wins**: 2 (1.00%, 95% Wilson CI: [0.27%, 3.57%])
- **Ante 1 Deaths**: 11 (5.50%, 95% Wilson CI: [3.10%, 9.58%])
- **Mean Ante**: 3.92 | **Mean Steps**: 110
- **Mean Econ Source**: $13.01 | **Mean Interest**: $8.37
- **Ante Distribution**: A1:11 (5.50%), A2:24 (12.00%), A3:45 (22.50%), A4:52 (26.00%), A5:43 (21.50%), A6:15 (7.50%), A7:5 (2.50%), A8:3 (1.50%), A9 (Wins): 2 (1.00%)

### 1.4 Diagnostic Configuration D Verification Run (Seeds 0–299)
To isolate whether missing `V10_DEFAULTS` chip bias parameters caused the degradation, a full run with Configuration D parameters was evaluated:
```bash
python bench/bench_agent_v10.py --seeds 0-299 --workers 16 --policies search_shop_v10 \
  --params '{"ante1_chip_bias": 0.8, "early_struct_ante": 2, "ante2_chip_bias": 0.5, "farm_rate_share": 0.75, "sampled_pick_ante": 2, "sampled_pick_manacle_only": true, "engineless_urgency_ante": 2}'
```
Telemetry sidecar: `vendor/balatro-rl/results/bench_0_299_search_shop_v10_configD.json`
- **Wins**: **10 / 300 (3.33%)** — identical failure
- **Ante 1 Deaths**: **20 / 300 (6.67%)** — still regressed (+6 deaths over baseline)
- **Net Gain**: **-10 wins** (16 baseline wins lost, 6 new wins)

---

## 2. Logic Chain

### 2.1 Bug 1: Premature Pace Rule Hand-Burning in Ante 1
- **Observation (`agent_v10.py:2178–2183`)**:
  ```python
  if (V10_PARAMS.get("ante1_pace_rule", False) and game.ante == 1
          and V10_PARAMS["farm_clear_threshold"] < 1.0):
      pace = (target / max(1, game.hands_left)) * V10_PARAMS.get("ante1_pace_mult", 1.0)
      if best_score >= pace:
          return {"type": "play", "cards": list(best_combo)}
  ```
- **Empirical Trace (Seed 249, Small Blind)**:
  - Required score: 300.
  - Hand 1: Best play scored 116. Pace = $300 / 4 = 75$. Played immediately. Remaining target: 184, hands: 3, discards: 4.
  - Hand 2: Discarded once, played hand scoring 92. Total: 208. Remaining target: 92, hands: 2, discards: 3.
  - Hand 3: Pace = $92 / 2 = 46$. Held hand scored 52. Since $52 \ge 46$, played immediately without discarding! Remaining target: 40, hands: 1, discards: 3.
  - Hand 4: Drew no pairs, scored 24. Total score: 284 (< 300).
  - **Result**: Died on Ante 1 Small Blind with **3 unused discards left**! In baseline `goal_iter7_final_D.json`, Seed 249 used its discards, cleared Ante 1, and won the run (Ante 9).
- **Empirical Trace (Seed 30, Big Blind)**:
  - Owned `j_tribe` (+X3 for Flush). Required score: 450.
  - Hand 1: Pace = $450 / 4 = 112.5$. Held Two Pair scored 108. (Discarded once, then played).
  - Hand 2: Pace = $342 / 3 = 114$. Held Two Pair scored 244.
  - Hand 3 & 4: Starved for discards, played low pairs, finished at 412 / 450 and died on Big Blind while holding `j_tribe`. In baseline, it discarded for flushes, scored 2,000, and reached Ante 5.
- **Logic**: The pace rule fires before joker-target alignment (`joker_target_hand_type`) and before discard digging. By accepting barely on-pace low-tier hands (Two Pair / Pair), it burns limited hands, deprives the player of the chance to discard for high-scoring hands, and frequently falls just short of the blind target with discards remaining.

### 2.2 Bug 2: Open-Slot Counterfactual Search Over-Spending in Ante 1
- **Observation (`agent_v10.py:2840–2860`)**:
  ```python
  if len(game.jokers) < game.joker_slots:
      ...
      is_high_leverage = item.key in HIGH_LEVERAGE_SCORING_JOKERS
      thr = 0.000 if is_high_leverage else best_buy_delta
      if delta > thr:
          ...
          return {"type": "buy", "item_idx": best_buy_idx}
  ```
- **Logic**:
  1. The offline value model $V(s')$ was trained on endgame win probability $P(\text{Win Ante 8})$. To this model, endgame jokers (`j_tribe`, `j_order`, `j_throwback`, `j_baseball`) appear overwhelmingly positive ($\Delta V > 0$).
  2. Because the open-slot evaluation has a threshold of `0.000` for these jokers and bypasses `worth_spending` and reserve checks, `search_shop_v10` spends 100% of its cash in early shops to buy expensive $8 utility/xMult jokers.
  3. These jokers provide 0 flat chips and 0 flat mult unless specific conditions are met. The agent enters Big and Boss blinds with $0 cash, no flat scoring anchors, and dies immediately (causing 19 Ante 1 regressed deaths).

### 2.3 Bug 3: Severe Collapse of Mid/Late-Game Progression
- **Observation**:
  - In baseline, 65 runs reached Ante 6 or beyond (20 wins, 9 Ante 8 deaths, 20 Ante 7 deaths, 36 Ante 6 deaths).
  - In `search_shop_v10`, mortality shifts earlier: Ante 3 deaths surged from 38 to 57 (+50%), and Ante 4 deaths remained a massive wall (77 deaths). Only 30 runs reached Ante 6 or beyond.
  - Net economic generation was cut in half: mean econ source dropped from $23.24 to $11.89, and interest dropped from $15.11 to $8.66.
- **Logic**: Over-aggressive early spending and counterfactual swap logic destroyed early interest compounding. Entering Antes 3–5 with lower cash reserves prevented sufficient rerolls and pack purchases to assemble winning builds.

---

## 3. Caveats

- **Test Suite Pass vs Policy Performance**: All 1,612 unit tests and the CI seed exactness gate pass 100% cleanly. The failure is strictly empirical policy regression: the agent's decision logic makes suboptimal gameplay choices that drastically degrade win rate.
- **Fatal Seeds vs Regressed Seeds**: The `ante1_pace_rule` did successfully clear the 11 baseline fatal seeds identified in earlier phases (including Seeds 205 and 275). However, its indiscriminate firing caused 19 previously viable seeds to fail Ante 1, resulting in a net negative impact on Ante 1 survival.
- **Holdout Bank Variance**: Holdout bank win rates in Balatro are inherently lower (~1–3%), but a 1.0% win rate on Seeds 300–499 confirms that `search_shop_v10` exhibits no positive generalization.

---

## 4. Conclusion

The implementation of `search_shop_v10` fails the user requirements and acceptance criteria:
1. **Target 1**: Win rate $> 7.0\%$ ($> 21$ wins / 300).
   - **Observed**: **10 wins (3.33%)** — **FAILED** (half of baseline).
2. **Target 2**: Ante 1 deaths $< 14$ ($< 4.67\%$).
   - **Observed**: **22 deaths (7.33%)** — **FAILED** (+57% more deaths than baseline).
3. **Target 3**: Generalization on Holdout Bank (Seeds 300–499).
   - **Observed**: **2 wins (1.00%)**, **11 Ante 1 deaths (5.50%)** — **FAILED**.

**Explicit Verdict: REJECT**.

### Required Remediations for Next Worker:
1. **Gate the Ante 1 Pace Rule**:
   - Only activate on Small Blind (when score target is 300 and no jokers are held).
   - Require remaining discards $\le 1$ before accepting non-clearing on-pace plays, or disable when holding hand-type jokers (`joker_target_hand_type`). Never burn hands with $\ge 2$ discards left.
2. **Constrain Early-Ante Open-Slot Search**:
   - In Antes 1–2, enforce minimum cash reserve ($game.dollars - price \ge 4$) before buying non-chips jokers.
   - Do not allow $\Delta V$ open-slot search to buy expensive xMult jokers (`j_tribe`, `j_order`) when the player has 0 flat chips.
3. **Preserve Interest Compounding**:
   - Respect `worth_spending` and interest thresholds so the agent accumulates $25 for max interest by Ante 2/3.

---

## 5. Verification Method

To independently reproduce and verify all benchmark numbers:

```powershell
# 1. Primary Benchmark Bank (Seeds 0-299)
python bench/bench_agent_v10.py --seeds 0-299 --workers 16 --policies search_shop_v10

# 2. Compare against baseline with acceptance verification tool
python tools/verify_bench_acceptance.py vendor/balatro-rl/results/bench_0_299_search_shop_v10.json vendor/balatro-rl/results/goal_iter7_final_D.json

# 3. Holdout Bank (Seeds 300-499)
python bench/bench_agent_v10.py --seeds 300-499 --workers 16 --policies search_shop_v10

# 4. Verify seed 249 premature death with discards remaining
python -c "
import sys; sys.path.insert(0, 'vendor/balatro-rl')
from balatro_sim.game import BalatroGame, State
from balatro_sim.agent_v10 import HeuristicV10
g = BalatroGame(seed=249, rng_mode='seed')
p = HeuristicV10()
while g.state != State.GAME_OVER and g.ante <= 1:
    act = p.decide(g)
    print(f'H={g.hands_left} D={g.discards_left} Sc={g.chips_scored}/300 act={act.get(\"type\")}')
    g.step(act)
"
```
