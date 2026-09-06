# Handoff Report: Challenger Bench Gen5 (Seeds 0–299 Paired Benchmark)

**Verdict**: **REJECT**  
**Milestone**: M2 Paired Benchmark Verification (Seeds 0–299)  
**Agent**: `teamwork_preview_challenger_bench_gen5` (Empirical Challenger)  
**Target Policy**: `search_shop_v10`  
**Date**: 2026-09-05T00:31:00Z  

---

## 1. Observation

### Benchmark Execution & Artifact
Command executed:
```powershell
python bench/bench_agent_v10.py --seeds 0-299 --workers 16 --policies search_shop_v10 --report vendor/balatro-rl/results/bench_0_299_search_shop_v10_gen5.json
```
- Total duration: 239s (~4.0 minutes, 1.3 games/s).
- Artifact produced: `vendor/balatro-rl/results/bench_0_299_search_shop_v10_gen5.json` (300 games, 100% completed).

---

### Core Metric Evaluation vs Acceptance Criteria

| Metric | Gen5 Candidate (`search_shop_v10`) | Gen4 Candidate | Frozen Baseline (`bench_0_299_search_shop_v10.json`) | Acceptance Target | Delta vs Baseline | Status |
|---|---|---|---|---|---|---|
| **Total Games** | 300 | 300 | 300 | 300 | — | — |
| **Wins** | **27** | 26 | 26 | **>= 30** | **+1** (+0.33pp) | **FAIL** (Deficit of 3 wins) |
| **Win Rate** | **9.00%** | 8.67% | 8.67% | **>= 10.00%** | **+0.33%** | **FAIL** |
| **Ante 1 Deaths** | **11** | 13 | 11 | **< 12** | **0** | **PASS** |
| **Ante 1 Mortality** | **3.67%** | 4.33% | 3.67% | **< 4.00%** | **0.00%** | **PASS** |
| **Mean Ante** | 4.94 | 4.84 | 4.94 | — | 0.00 | Even |
| **Mean Steps** | 147 | 145 | 150 | — | -3 | - |
| **Mean Dollars** | $9.20 | $8.72 | $10.31 | — | -$1.11 | - |
| **Mean Econ Source** | $18.5/run | $18.2/run | $20.5/run | — | -$2.0/run | - |
| **Mean Interest** | $17.0/run | $16.9/run | $17.8/run | — | -$0.8/run | - |

---

### Mortality Breakdown by Ante (Gen5)

| Ante | Deaths | Percentage | Distribution Visual |
|---|---|---|---|
| **Ante 1** | 11 | 3.67% | `#` |
| **Ante 2** | 27 | 9.00% | `####` |
| **Ante 3** | 50 | 16.67% | `########` |
| **Ante 4** | 50 | 16.67% | `########` |
| **Ante 5** | 51 | 17.00% | `########` |
| **Ante 6** | 38 | 12.67% | `######` |
| **Ante 7** | 27 | 9.00% | `####` |
| **Ante 8** | 19 | 6.33% | `###` |
| **Ante 9 (Wins)** | **27** | **9.00%** | `####` |

Ante-1 deaths list (11 seeds): `[33, 82, 100, 145, 164, 199, 250, 269, 287, 291, 298]`  
Baseline Ante-1 deaths (11 seeds): `[33, 82, 100, 145, 164, 199, 250, 260, 269, 287, 291]`  
- **Net change**: Seed 260 was rescued (died in Ante 2 instead of Ante 1).  
- **Regression**: Seed 298 died on Ante 1 Big Blind (was an Ante 9 win in baseline!).

---

### Paired Flip Analysis vs Baseline

- **Wins Gained (15 seeds)**:  
  `[3, 17, 24, 64, 81, 94, 98, 134, 186, 190, 202, 216, 231, 245, 293]`
- **Wins Lost (14 seeds)**:  
  `[21, 40, 43, 54, 60, 80, 95, 131, 139, 155, 188, 198, 211, 298]`
- **Net Win Gain**: $+1$ win ($27 - 26 = +1$).

---

### Premier Finishers Acquired & Win Rates (Gen5)

| Joker Key | Name | Acquired Runs | Win Count | Win Rate % |
|---|---|---|---|---|
| `j_baseball` | Baseball Card | 9 / 300 (3.0%) | 6 | **66.7%** |
| `j_constellation` | Constellation | 16 / 300 (5.3%) | 5 | **31.2%** |
| `j_cavendish` | Cavendish | 58 / 300 (19.3%) | 17 | **29.3%** |
| `j_trio` | The Trio | 13 / 300 (4.3%) | 2 | **15.4%** |
| `j_brainstorm` | Brainstorm | 10 / 300 (3.3%) | 1 | **10.0%** |
| `j_blueprint` | Blueprint | 3 / 300 (1.0%) | 0 | **0.0%** |
| `j_duo` | The Duo | 8 / 300 (2.7%) | 0 | **0.0%** |
| `j_family` | The Family | 14 / 300 (4.7%) | 0 | **0.0%** |
| `j_order` | The Order | 8 / 300 (2.7%) | 0 | **0.0%** |
| `j_tribe` | The Tribe | 2 / 300 (0.7%) | 0 | **0.0%** |
| `j_acrobat` | Acrobat | 8 / 300 (2.7%) | 0 | **0.0%** |
| **Total (>= 1 Finisher)** | Any Premier Finisher | **120 / 300 (40.0%)** | **20** | **16.7%** |

---

### Blueprint / Brainstorm Forensic Assessment

1. **Bug Resolution**:
   - The Gen4 fatal bug (`AttributeError: '_EvalGame' object has no attribute 'jokers'`) is **100% resolved**.
   - `_EvalGame` now correctly declares `jokers` in `__slots__`, initializes from `game.jokers`, and provides `.copy()`.
   - Hand scoring evaluation completed without any exceptions or fallback to 1-card play spam.
2. **Empirical Conversion**:
   - In Gen4: 21 runs acquired Blueprint/Brainstorm, **0 won** (0.0% win rate due to crash).
   - In Gen5: 13 runs acquired Blueprint or Brainstorm, **1 won** (Seed 263 won at Ante 9), **12 lost** (7.7% win rate).
3. **Failure Mode in Ante 1 (Seed 298)**:
   - In `_v10_rank_shop_items`, `if item.key in ("j_blueprint", "j_brainstorm"): value = max(value, 1.5)` forces the purchase of Blueprint in Ante 1 Shop 1 when the player has 0 other jokers and spends all money ($0 remaining).
   - Blueprint copies the joker to its right. With 0 other jokers, Blueprint contributes $+0$ chips and $+0$ mult.
   - The player enters Ante 1 Big Blind (450 chip target) with $0 bankroll and 0 functional scoring jokers, failing and dying at step 15. In baseline, Seed 298 did not buy Blueprint in Ante 1 and went on to win at Ante 9.

---

## 2. Logic Chain

1. **Criterion 1 (Win Rate)**:
   - Threshold: Win rate $\ge 10.0\%$ ($\ge 30$ wins / 300).
   - Observation: Gen5 achieved 27 wins out of 300 (9.00%).
   - Inference: $27 < 30$. The win rate criterion is **VIOLATED** (deficit of 3 wins).
2. **Criterion 2 (Ante-1 Mortality)**:
   - Threshold: Ante 1 deaths $< 12$ ($< 4.00\%$).
   - Observation: Gen5 achieved 11 Ante-1 deaths (3.67%).
   - Inference: $11 < 12$. The Ante-1 mortality criterion is **SATISFIED**.
3. **Net Policy Progress**:
   - Baseline: 26 wins (8.67%), 11 Ante-1 deaths.
   - Gen5: 27 wins (9.00%), 11 Ante-1 deaths.
   - Net gain is only $+1$ win (+0.33 percentage points) over 300 seeds.
4. **Root Cause of Win Rate Shortfall**:
   - 15 seeds were converted from losses to wins by late-game rerolls and high-leverage finishers.
   - However, 14 previously winning seeds were lost ($15 - 14 = +1$ net).
   - Premier finishers with high hand-type specialization (`j_family` 0/14 wins, `j_order` 0/8 wins, `j_duo` 0/8 wins) suffer from severe conversion collapse because `portfolio_target_hand` shifts planet/tarot priorities toward hands that an unshaped deck cannot consistently produce.
   - Forcing Blueprint/Brainstorm purchases regardless of owned joker count harms early survival (e.g. Seed 298 dying on Ante 1 Big Blind with solo Blueprint).
5. **Verdict Inevitability**:
   - Acceptance requires BOTH $\ge 30$ wins AND $< 12$ Ante-1 deaths.
   - Because wins = 27, the verdict must be **REJECT**.

---

## 3. Caveats

- **No random seed peeking or cheating**: The benchmark ran under strict human-fair seed mode (`BalatroGame(seed=s, rng_mode='seed')`) with 0 future stream peeking.
- **Holdout Bank (Seeds 300–499)**: In accordance with the protocol, the holdout bank was not evaluated because the primary gate failed on Seeds 0–299.
- **Engine Stability**: Simulator integrity is fully restored (`_EvalGame` fix is solid, 0 crashes across 300 seeds, 1.3 games/s throughput).

---

## 4. Conclusion

**VERDICT: REJECT**

While the engineering remedies successfully fixed the `_EvalGame` Blueprint/Brainstorm crash and restored Ante-1 mortality to 11/300 (3.67%, meeting the $< 12$ target), the policy achieves only **27 wins / 300 (9.00%)**, falling **3 wins short** of the required $\ge 30$ wins ($\ge 10.0\%$) milestone threshold.

### Key Insights for Next Iteration:
1. **Unconditional Blueprint/Brainstorm Trap**: In Ante 1, Blueprint/Brainstorm must NOT be bought if `len(game.jokers) == 0` or if it leaves the player with insufficient scoring to beat Ante 1 Big/Boss. Seed 298 alone is a lost win.
2. **Hand-Type Lock Trap (`j_family`, `j_order`, `j_duo`)**: Buying `j_family` or `j_order` resulted in 0 wins across 22 runs (0/14 and 0/8). Switching `portfolio_target_hand` to Four-of-a-Kind without sufficient deck fixing (e.g. Strength/Death) causes premature death.

---

## 5. Verification Method

To independently reproduce the benchmark results:

```powershell
# 1. Run the full 300-seed benchmark
python bench/bench_agent_v10.py --seeds 0-299 --workers 16 --policies search_shop_v10 --report vendor/balatro-rl/results/bench_0_299_search_shop_v10_gen5.json

# 2. Run the automated telemetry analyzer
python tools/analyze_gen5_bench.py
```
Expected output:
- Wins: 27 / 300 (9.00%)
- Ante 1 deaths: 11 / 300 (3.67%)
- Gained wins: 15 seeds
- Lost wins: 14 seeds
