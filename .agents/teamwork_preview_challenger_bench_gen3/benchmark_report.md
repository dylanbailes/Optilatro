# Empirical Benchmark Evaluation Report: Seeds 0–299 (`search_shop_v10`)

**Evaluator**: Challenger 2 (Benchmark Evaluator Seeds 0–299)  
**Date**: 2026-09-04  
**Policy Under Test**: `SearchShopV10` (`vendor/balatro-rl/balatro_sim/agent_v10.py`)  
**Baseline Artifact**: `vendor/balatro-rl/results/bench_0_299_search_shop_v10.json` (26W / 11D)  
**Evaluated Artifact**: `vendor/balatro-rl/results/bench_0_299_search_shop_v10_breakthrough.json` (21W / 12D)  
**Diagnostic Ablation**: `vendor/balatro-rl/results/bench_0_299_no_scaling_accel.json` (29W / 11D)  
**Verdict**: **REJECT**

---

## 1. Executive Summary

Empirical execution of the full 300-seed benchmark (Seeds 0–299) on `search_shop_v10` demonstrates that the policy **regressed** across all primary performance indicators compared to baseline and **failed both mandatory Acceptance Criteria**:

1. **Win Rate Target (>= 10.0%, >= 30 wins)**:
   - Baseline: **26 wins (8.67%)**
   - Breakthrough Candidate: **21 wins (7.00%)** — **FAILED** (-5 net wins, 9 wins short of threshold)
2. **Ante 1 Mortality Target (< 4.00%, < 12 deaths)**:
   - Baseline: **11 deaths (3.67%)**
   - Breakthrough Candidate: **12 deaths (4.00%)** — **FAILED** (+1 death, strictly misses `< 12` requirement)

### Root Cause of Regression
The primary culprit for the severe win-rate drop (26 -> 21) and the new Ante 1 death is **R3 Scaling Joker Acceleration** (`_find_scaling_action` / Tier S2). Tier S2 allowed playing junk 1-card hands based on high estimated $P(\text{clear})$ ($\ge 0.995$), falsely believing the round was secured. In reality, $P(\text{clear})$ is known to read $\approx 1.0$ at the start of rounds; burning hands for $+1$ scaling mult exhausted hands_left, leaving the agent with insufficient hands/chips to clear remaining blind targets.
- Disabling scaling acceleration via diagnostic ablation (`scaling_accel_enabled: false`) immediately restored Ante 1 deaths to **11** and lifted wins to **29 (9.67%)**.
- However, even with scaling acceleration disabled, 29 wins falls 1 win short of the mandatory $\ge 30$ wins ($\ge 10.0\%$) threshold.

---

## 2. Benchmark Performance Matrix

| Metric | Target | Baseline (`bench_0_299_search_shop_v10.json`) | Breakthrough Candidate (`bench_..._breakthrough.json`) | Status vs Target | Ablation (`scaling_accel_enabled: False`) |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Total Games** | 300 | 300 | 300 | — | 300 |
| **Wins** | $\ge 30$ ($\ge 10.0\%$) | 26 (8.67%) | **21 (7.00%)** | **FAILED** (-9) | 29 (9.67%) |
| **Ante 1 Deaths** | $< 12$ ($< 4.00\%$) | 11 (3.67%) | **12 (4.00%)** | **FAILED** (+1) | 11 (3.67%) |
| **Mean Ante** | — | 4.943 | **4.707** | Regressed (-0.236) | 4.963 |
| **Mean Steps** | — | 149.8 | **140.0** | Regressed (-9.8) | 150.2 |
| **Mean End Dollars** | — | $10.31 | **$8.82** | Lower (-$1.49) | $8.82 |
| **Mean Econ Source** | — | $20.52 | **$18.59** | Lower (-$1.93) | $19.60 |
| **Mean Interest** | — | $17.83 | **$15.53** | Lower (-$2.30) | $17.43 |
| **Mean Tarots** | — | 7.53 | **6.81** | Lower (-0.72) | 7.64 |
| **Mean Planets** | — | 6.28 | **5.79** | Lower (-0.49) | 6.39 |
| **Mean Spectrals** | — | 0.38 | **0.34** | Lower (-0.04) | 0.38 |

### Death Distribution by Ante

| Ante | Baseline Count (%) | Candidate Count (%) | Delta | Notes |
| :--- | :--- | :--- | :--- | :--- |
| **Ante 1** | 11 (3.67%) | **12 (4.00%)** | **+1** | New death on Seed 245 (Ante 1 Big Blind) |
| **Ante 2** | 29 (9.67%) | 28 (9.33%) | -1 | |
| **Ante 3** | 43 (14.33%) | **54 (18.00%)** | **+11** | Massive spike in premature Ante 3 deaths |
| **Ante 4** | 59 (19.67%) | 59 (19.67%) | 0 | |
| **Ante 5** | 44 (14.67%) | **50 (16.67%)** | **+6** | Elevated mid-game mortality |
| **Ante 6** | 38 (12.67%) | 39 (13.00%) | +1 | |
| **Ante 7** | 33 (11.00%) | 23 (7.67%) | -10 | Fewer runs reached Ante 7 due to early mortality |
| **Ante 8** | 17 (5.67%) | 14 (4.67%) | -3 | |
| **Ante 9 (Wins)**| 26 (8.67%) | **21 (7.00%)** | **-5** | Net drop of 5 winning runs |

---

## 3. Seed-by-Seed Pairwise Analysis

### A. Lost Wins (13 seeds that won in baseline but lost in breakthrough)
`[21, 30, 40, 43, 60, 93, 95, 131, 139, 188, 198, 280, 298]`

Detailed autopsy of key lost seeds:
- **Seed 21**: Base reached Ante 9 win ($265k chips on Ante 8 boss). Current died on Ante 8 Boss with $2 dollars holding `['j_stuntman', 'j_baron', 'j_shoot_the_moon', 'j_cavendish', 'j_blackboard']`. (Ablation with scaling disabled won Ante 9).
- **Seed 139**: Base reached Ante 9 win. Current died in Ante 5 Boss holding `j_ride_the_bus` after burning hands for scaling. (Ablation with scaling disabled won Ante 9).
- **Seed 30**: Base reached Ante 9 win with `j_constellation`, `j_trio`, `j_cavendish`. Current died on Ante 7 Boss with $1 after excessive late rerolls.
- **Seed 40**: Base reached Ante 9 win with $26 end bank. Current died on Ante 7 Boss with $0 after exhausting interest bankroll.
- **Seed 131**: Base reached Ante 9 win. Current died in Ante 3 Boss holding $3.
- **Seed 280**: Base reached Ante 9 win. Current died in Ante 3 Big Blind.

### B. Gained Wins (8 seeds that lost in baseline but won in breakthrough)
`[7, 17, 64, 97, 105, 182, 190, 241]`

- **Seed 7**: Base died Ante 8 Boss. Current won Ante 9 with `j_erosion`, `j_ramen`, `j_cavendish`, `j_baseball`.
- **Seed 17**: Base died Ante 7 Boss. Current won Ante 9 with `j_erosion`, `j_hologram`, `j_stuntman`.
- **Seed 64**: Base died Ante 7 Boss. Current won Ante 9 with `j_mail`, `j_cavendish`, `j_swashbuckler`, `j_ice_cream`, `j_mystic_summit`.
- **Seed 97**: Base died Ante 5 Small. Current won Ante 9 with `j_vampire`, `j_campfire`, `j_erosion`, `j_madness`.
- **Seed 105**: Base died Ante 5 Boss. Current won Ante 9 with `j_blackboard`, `j_stuntman`, `j_constellation`.
- **Seed 182**: Base died Ante 6 Boss. Current won Ante 9 with `j_seeing_double`, `j_cavendish`, `j_baseball`.
- **Seed 190**: Base died Ante 4 Boss. Current won Ante 9 with `j_fibonacci`, `j_scholar`, `j_cavendish`.
- **Seed 241**: Base died Ante 3 Boss. Current won Ante 9 with `j_cavendish`, `j_green_joker`, `j_blackboard`.

*Crucial Discovery*: All 8 gained wins were ALSO won in the ablation run (`bench_0_299_no_scaling_accel.json`). The scaling acceleration code contributed **0** of these gains.

### C. Retained Wins (13 seeds)
`[37, 44, 54, 58, 78, 80, 132, 143, 155, 211, 217, 236, 263]`

### D. Ante 1 Mortality Analysis
- Baseline Ante 1 deaths: 11 seeds `[33, 82, 100, 145, 164, 199, 250, 260, 269, 287, 291]`
- Current Ante 1 deaths: 12 seeds `[33, 82, 100, 145, 164, 199, 245, 250, 260, 269, 287, 291]`
- **New Ante 1 Death**: **Seed 245**
  - In baseline, Seed 245 cleared Ante 1 cleanly: Big Blind played Two Pair (180) + Flush (330) = 510 chips, clearing target 450 in 2 hands, and reached Ante 4.
  - In current breakthrough code, the agent owned `j_green_joker`. In Big Blind Ante 1, Tier S2 scaling acceleration triggered because $P(\text{clear})$ was perceived as $\ge 0.995$.
  - The agent deliberately played 3 consecutive 1-card High Cards:
    - Hand 1: High Card (16 pts)
    - Hand 2: High Card (21 pts)
    - Hand 3: High Card (28 pts)
  - On Hand 4 (last hand!), it played Two Pair (360 pts).
  - Total score: $16 + 21 + 28 + 360 = 425$ pts vs target 450 pts. **Died with 425/450 chips.**
  - Seed 245 was a 100% preventable blind throw caused by `_find_scaling_action`.

---

## 4. Empirical Breakdown of Failure Modes

### Failure Mode 1: Scaling Joker Acceleration Throwing Blinds (R3)
In `agent_v10.py`:
```python
# Tier S2: Probabilistically safe blind (is_prob_safe)
if is_prob_safe:
    best_score = plays[0][0] if plays else 0
    if best_score * (game.hands_left - 1) >= target * 1.25 or (p_clear is not None and p_clear >= 0.995):
        candidates = []
```
- **Flaw**: The clause `or (p_clear is not None and p_clear >= 0.995)` was evaluated as True on nearly all unplayed early boards because $P(\text{clear})$ calculation over 4 hands and 3 discards is close to 1.0.
- Because `best_score * (game.hands_left - 1) >= target * 1.25` was bypassed, the agent repeatedly played non-scoring 1-card hands, decrementing `hands_left` each turn while assuming subsequent hands would easily clear.
- Once `hands_left` reached 1, `_find_scaling_action` exited, leaving the agent facing the remaining target in a single hand without discards.
- **Empirical impact**:
  - 23 separate runs died directly following multi-hand scaling plays.
  - 8 wins were thrown away: seeds `[21, 62, 81, 98, 139, 158, 202, 281]` won in ablation but lost in the candidate.
  - Ante 3 deaths surged from 43 to 54 (+11 deaths).
  - Seed 245 died in Ante 1 Big Blind.

### Failure Mode 2: Premature Capital Depletion in Antes 6–7 (R1)
- The dynamic interest floor relaxation ($0 in Ante 8, $0 in Ante 7 under deficit, $15 in Ante 6 without xMult) coupled with aggressive reroll allowances (caps 10, 6, 4) was designed to hunt finishers.
- However, in several seeds (e.g. Seed 30, Seed 40, Seed 60), the agent burned all interest and reserve capital in Ante 6 or Ante 7 on rerolls without finding a viable multiplier, leaving $0–$1 at round end.
- Without interest compounding, the agent entered subsequent blinds starved of shop purchasing power, resulting in death on Ante 7/8 Bosses where baseline (which kept a $25 reserve) had sufficient capital to purchase high-leverage jokers.

---

## 5. Summary of Acceptance Criteria

| Requirement | Threshold | Baseline | Candidate | Verdict |
| :--- | :--- | :--- | :--- | :--- |
| **Ante 8 Win Rate** | $\ge 10.0\%$ ($\ge 30$ wins) | 26 wins (8.67%) | **21 wins (7.00%)** | **FAIL** |
| **Ante 1 Mortality** | $< 4.00\%$ ($< 12$ deaths) | 11 deaths (3.67%) | **12 deaths (4.00%)** | **FAIL** |
| **Overall Recommendation** | Must meet both | — | — | **REJECT** |

---

## 6. Concrete Recommendations for Worker M1

1. **Remove or Severely Guard Tier S2 in `_find_scaling_action`**:
   - Completely delete the `or (p_clear is not None and p_clear >= 0.995)` bypass.
   - Strictly require that Tier S1 (deterministic knockout in hand) holds, OR require that `best_play_score * (game.hands_left - 2) >= target * 1.50` so that at least two full clearing plays are guaranteed to remain after scaling.
   - Forbid scaling actions entirely in Ante 1 and Ante 2.
   - Limit scaling actions to at most 1 play per blind.
2. **Tune Capital Deployment in Antes 6–7**:
   - Maintain a minimum floor of at least $10 in Ante 6 and Ante 7 even when searching for finishers, rather than depleting to $0.
   - In Ante 8, preserve $6 minimum for buying a found joker when rerolling.
3. **Bridge from 29 to 30+ Wins**:
   - Disabling scaling acceleration immediately achieves 29 wins (9.67%).
   - Fixing the capital bleed on seeds 30, 40, 43, 60 will easily push the win count beyond 30 wins (>= 10.0%).
