# Empirical Benchmark Challenger Verification Report — Seeds 9000–9299

## Executive Summary & Verdict

- **Policy Evaluated**: `search_shop_v10`
- **Seed Bank**: Seeds 9000–9299 (N = 300 completely fresh seeds, zero overlap with any prior bank)
- **Evaluation Mode**: Deterministic seed mode, `lookahead=False`, strictly human-fair
- **Benchmark Command**: `python bench/bench_agent_v10.py --seeds 9000-9299 --workers 16 --policies search_shop_v10 --report vendor/balatro-rl/results/bench_9000_9299_search_shop_v10.json`
- **Primary Acceptance Targets**:
  1. Win Rate: $\ge 10.0\%$ ($\ge 30$ wins / 300) $\rightarrow$ **FAIL** (Actual: **24 wins / 300 = 8.00%**, deficit of 6 wins)
  2. Ante 1 Mortality: $< 4.0\%$ ($< 12$ deaths / 300) $\rightarrow$ **FAIL** (Actual: **17 deaths / 300 = 5.67%**, excess of 5 deaths)
- **EXPLICIT VERDICT**: **REJECT**

---

## 1. Observation

### 1.1 Verbatim Benchmark Execution & Output
Benchmark executed via `run_command` across 16 worker processes:
```
python bench/bench_agent_v10.py --seeds 9000-9299 --workers 16 --policies search_shop_v10 --report vendor/balatro-rl/results/bench_9000_9299_search_shop_v10.json
```

Verbatim terminal stdout output from `task-24`:
```
bench_agent_v10: 300 seeds (9000..9299), rng_mode=seed, workers=16, policies=['search_shop_v10'], search_shops=999, lookahead=False, params=None
  [search_shop_v10] 25/300 | 5 wins (20.00%) | ante-1 deaths 3 | econ $21.3 | 0.8 games/s | ETA 5:53
  [search_shop_v10] 50/300 | 6 wins (12.00%) | ante-1 deaths 4 | econ $18.4 | 1.0 games/s | ETA 4:20
  [search_shop_v10] 75/300 | 9 wins (12.00%) | ante-1 deaths 5 | econ $18.5 | 1.0 games/s | ETA 3:38
  [search_shop_v10] 100/300 | 12 wins (12.00%) | ante-1 deaths 6 | econ $19.1 | 1.1 games/s | ETA 3:07
  [search_shop_v10] 125/300 | 13 wins (10.40%) | ante-1 deaths 8 | econ $17.7 | 1.2 games/s | ETA 2:30
  [search_shop_v10] 150/300 | 13 wins (8.67%) | ante-1 deaths 11 | econ $16.2 | 1.2 games/s | ETA 2:05
  [search_shop_v10] 175/300 | 16 wins (9.14%) | ante-1 deaths 11 | econ $16.4 | 1.2 games/s | ETA 1:43
  [search_shop_v10] 200/300 | 18 wins (9.00%) | ante-1 deaths 13 | econ $16.5 | 1.2 games/s | ETA 1:21
  [search_shop_v10] 225/300 | 19 wins (8.44%) | ante-1 deaths 15 | econ $16.2 | 1.3 games/s | ETA 0:59
  [search_shop_v10] 250/300 | 19 wins (7.60%) | ante-1 deaths 16 | econ $16.4 | 1.2 games/s | ETA 0:40
  [search_shop_v10] 275/300 | 23 wins (8.36%) | ante-1 deaths 17 | econ $16.9 | 1.2 games/s | ETA 0:20
  [search_shop_v10] 300/300 | 24 wins (8.00%) | ante-1 deaths 17 | econ $17.7 | 1.1 games/s | ETA 0:00

=== search_shop_v10 (284s, 1.1 games/s) ===
  wins 24/300 = 8.00% | ante-1 deaths 17 (5.67%) | mean ante 4.88 | mean steps 147
  econ-source $17.7/run | interest $17.7/run | tarots 7.2 planets 6.2 spectrals 0.4 | end $8.1
  ante 1:    17 ( 5.67%) ##
  ante 2:    35 (11.67%) #####
  ante 3:    33 (11.00%) #####
  ante 4:    57 (19.00%) #########
  ante 5:    53 (17.67%) ########
  ante 6:    26 ( 8.67%) ####
  ante 7:    26 ( 8.67%) ####
  ante 8:    29 ( 9.67%) ####
  ante 9:    24 ( 8.00%) ####

report sidecar: vendor\balatro-rl\results\bench_9000_9299_search_shop_v10.json
```

### 1.2 Telemetry Summary & Confidence Intervals
Generated via `tools/analyze_bench_9000.py` on `vendor/balatro-rl/results/bench_9000_9299_search_shop_v10.json`:
- **Total Games**: 300
- **Wins**: 24 (8.00%) | 95% Wilson Score Interval: [5.43%, 11.63%]
- **Ante 1 Deaths**: 17 (5.67%) | 95% Wilson Score Interval: [3.57%, 8.89%]
- **Mean Ante**: 4.88 (Median: 5.0)
- **Mean Steps**: 146.9
- **Mean Ending Bankroll**: $8.08
- **Mean Econ $ Source**: $17.72
- **Mean Interest Collected**: $17.72
- **Mean Consumables**: 7.25 Tarots, 6.24 Planets, 0.35 Spectrals

### 1.3 Full Ante Mortality Distribution
| Ante Bucket | Deaths / Clears | Percentage | Cumulative Deaths |
|---|---|---|---|
| Ante 1 | 17 | 5.67% | 17 (5.67%) |
| Ante 2 | 35 | 11.67% | 52 (17.33%) |
| Ante 3 | 33 | 11.00% | 85 (28.33%) |
| Ante 4 | 57 | 19.00% | 142 (47.33%) |
| Ante 5 | 53 | 17.67% | 195 (65.00%) |
| Ante 6 | 26 | 8.67% | 221 (73.67%) |
| Ante 7 | 26 | 8.67% | 247 (82.33%) |
| Ante 8 (Final Boss Death) | 29 | 9.67% | 276 (92.00%) |
| Ante 8 Cleared (Wins) | 24 | 8.00% | 300 (100.00%) |

### 1.4 Ante 1 Death Breakdown
Deaths by Blind:
- Small Blind: **0 deaths (0.00%)**
- Big Blind: **6 deaths (35.29% of Ante 1 deaths)**
- Boss Blind: **11 deaths (64.71% of Ante 1 deaths)**

Audit of the 17 Ante 1 Deaths:
- Seed 9007: Boss Blind | Held: `['j_mystic_summit', 'j_vagabond', 'j_splash']` | Bought: `['j_mystic_summit', 'j_splash']` | End $: 2
- Seed 9008: Boss Blind | Held: `['j_wily', 'j_business']` | Bought: `['j_wily', 'j_business']` | End $: 5
- Seed 9023: Boss Blind | Held: `['j_scholar', 'j_splash']` | Bought: `['j_scholar', 'j_splash']` | End $: 3
- Seed 9059: Big Blind  | Held: `['j_seeing_double', 'j_business']` | Bought: `['j_business']` | End $: 4
- Seed 9067: Big Blind  | Held: `['j_credit_card']` | Bought: `[]` | End $: 1
- Seed 9091: Big Blind  | Held: `['j_todo_list', 'j_business']` | Bought: `['j_business']` | End $: 5
- Seed 9111: Boss Blind | Held: `['j_joker', 'j_rocket']` | Bought: `['j_rocket']` | End $: 1
- Seed 9132: Boss Blind | Held: `['j_shoot_the_moon', 'j_wily', 'j_business']` | Bought: `['j_wily', 'j_business']` | End $: 3
- Seed 9138: Boss Blind | Held: `['j_splash']` | Bought: `['j_splash']` | End $: 1
- Seed 9144: Boss Blind | Held: `['j_reserved_parking', 'j_rocket']` | Bought: `['j_rocket']` | End $: 4
- Seed 9157: Big Blind  | Held: `['j_loyalty_card']` | Bought: `[]` | End $: 1
- Seed 9185: Boss Blind | Held: `['j_hanging_chad', 'j_golden']` | Bought: `['j_golden']` | End $: 2
- Seed 9206: Boss Blind | Held: `['j_photograph', 'j_credit_card', 'j_dusk']` | Bought: `['j_credit_card', 'j_dusk']` | End $: 2
- Seed 9212: Boss Blind | Held: `['j_ride_the_bus']` | Bought: `[]` | End $: 0
- Seed 9226: Big Blind  | Held: `['j_todo_list', 'j_gift']` | Bought: `['j_gift']` | End $: 0
- Seed 9240: Big Blind  | Held: `['j_crazy', 'j_wily']` | Bought: `['j_crazy', 'j_wily']` | End $: 1
- Seed 9281: Boss Blind | Held: `['j_scholar', 'j_reserved_parking']` | Bought: `['j_scholar']` | End $: 1

### 1.5 Finisher Acquisition & Win Conversion
| Finisher / Scoring Joker | Acquired Runs | Acq Rate % | Wins | Win Conversion % |
|---|---|---|---|---|
| `j_cavendish` | 69 | 23.00% | 14 | 20.29% |
| `j_stuntman` | 16 | 5.33% | 8 | 50.00% |
| `j_constellation` | 17 | 5.67% | 5 | 29.41% |
| `j_acrobat` | 15 | 5.00% | 4 | 26.67% |
| `j_card_sharp` | 14 | 4.67% | 3 | 21.43% |
| `j_baron` | 12 | 4.00% | 3 | 25.00% |
| `j_baseball` | 7 | 2.33% | 2 | 28.57% |
| `j_trio` | 11 | 3.67% | 2 | 18.18% |
| `j_blueprint` | 10 | 3.33% | 2 | 20.00% |
| `j_ancient` | 21 | 7.00% | 2 | 9.52% |
| `j_ramen` | 20 | 6.67% | 2 | 10.00% |
| `j_duo` | 7 | 2.33% | 1 | 14.29% |
| `j_tribe` | 7 | 2.33% | 1 | 14.29% |
| `j_hologram` | 18 | 6.00% | 1 | 5.56% |
| `j_photograph` | 91 | 30.33% | 11 | 12.09% |
| `j_family` | 11 | 3.67% | 0 | 0.00% |
| `j_brainstorm` | 7 | 2.33% | 0 | 0.00% |
| `j_order` | 4 | 1.33% | 0 | 0.00% |
| **Core 4 Premier** (`cavendish`, `baseball`, `constellation`, `acrobat`) | **91** | **30.33%** | **19** | **20.88%** |
| **Reliable xMult Pool** | **182** | **60.67%** | **24** | **13.19%** |
| **All High-Leverage Jokers** | **185** | **61.67%** | **24** | **12.97%** |
| **No High-Leverage Joker** | **115** | **38.33%** | **0** | **0.00%** |

### 1.6 Environment & Integrity Gates
- CI seed exactness gate: `python -m pytest vendor/balatro-rl/tests/test_seed_exactness.py -m ci_gate -v` $\rightarrow$ **4 passed in 5.57s**.
- Static audits: Jokers, Consumables, Bosses, Tags $\rightarrow$ **All GATES CLEAN (0 errors)**.
- Human-fair parameters: verified `lookahead=False`, seeded LuaRandom per run, no draw-order peeking in `agent_v10.py`.

---

## 2. Logic Chain

1. **Failure on Win Rate Criterion**:
   - The user mandate and acceptance criteria require $\ge 30$ wins / 300 ($\ge 10.0\%$).
   - On the completely fresh seed bank of seeds 9000–9299, `search_shop_v10` achieved 24 wins (8.00%).
   - The 95% Wilson confidence interval is [5.43%, 11.63%], with the point estimate falling 2.0% (6 wins) short of the 10.0% acceptance floor.
   - Therefore, the win rate criterion is **NOT MET**.

2. **Failure on Ante 1 Mortality Criterion**:
   - The acceptance criteria require $< 12$ Ante 1 deaths ($< 4.0\%$).
   - On seeds 9000–9299, `search_shop_v10` suffered 17 Ante 1 deaths (5.67%).
   - This exceeds the threshold by 5 deaths (+1.67 percentage points).
   - Therefore, the Ante 1 mortality criterion is **NOT MET**.

3. **Identification of Systemic Failure Modes**:
   - **Mid-Game Scaling Cliff (Antes 4 & 5)**:
     - The mortality breakdown shows a steep mortality spike in Ante 4 (57 deaths, 19.0%) and Ante 5 (53 deaths, 17.67%).
     - Combined, 110 runs (36.67%) perish in Antes 4–5.
     - While the policy incorporates late-game capital deployment and interest floor relaxation in Antes 6–8, more than one-third of the runs never reach Ante 6 because early scoring engines (flat mult + chips) fall behind exponential blind scaling (e.g. 5,000 to 10,000 chips).
   - **Ante 1 Economy Trap**:
     - 0 deaths occurred on Ante 1 Small Blind, confirming the efficacy of the multi-hand pace rule.
     - However, 6 deaths occurred on Big Blind and 11 deaths occurred on Boss Blind.
     - Telemetry reveals that runs dying on the Ante 1 Boss Blind frequently purchased economy jokers in Shop 1 (e.g. `j_rocket`, `j_golden`, `j_business`, `j_credit_card`) rather than reserving bankroll or seeking flat mult/chips. At Ante 1 with base deck and no flat mult, an economy joker provides zero scoring, resulting in inability to reach the 600-chip Boss threshold.
   - **Ante 8 Showdown Conversion**:
     - 53 runs reached Ante 8. Of these, 29 died on Ante 8 blinds/bosses and 24 won (conversion rate: 45.28%).
     - Over half the runs reaching Ante 8 were unable to overcome the 100k–300k scaling requirements despite late-game liquidation.
   - **High-Leverage Joker Dependency**:
     - 100% of all winning runs (24/24) acquired at least one high-leverage scoring joker.
     - Runs failing to acquire a high-leverage scoring joker had a 0.00% win rate (0/115).
     - Furthermore, jokers like `j_family`, `j_order`, and `j_brainstorm` had 0% win conversion across 22 collective appearances, indicating misaligned hand-type steering or timing deficiencies.

4. **Verdict Synthesis**:
   - Because both primary numerical acceptance criteria (Win Rate $\ge 10.0\%$ and Ante 1 Deaths $< 4.0\%$) failed to pass on fresh seeds 9000–9299, the policy cannot be approved.

---

## 3. Caveats

1. **Single Bank Variance**: While seeds 9000–9299 represent 300 completely fresh seeds, Balatro run outcomes exhibit inherent RNG dispersion. The 95% Wilson confidence interval [5.43%, 11.63%] spans the 10% mark at its upper bound, but the sample point estimate (8.00%) confirms performance remains statistically consistent with the pre-enhancement ~8.67% baseline rather than a sustained breakthrough.
2. **Deterministic Seed Mode Only**: All testing was performed under `rng_mode=seed` on Red Deck / White Stake. Performance on generic random streams or alternate decks/stakes was not evaluated.
3. **No In-Blind Lookahead**: As mandated by human-fair rules, `lookahead=False` was strictly enforced. Policies utilizing lookahead or draw-order knowledge would achieve higher win rates but violate project constraints.

---

## 4. Conclusion

- `search_shop_v10` achieved **24 wins (8.00%)** and **17 Ante-1 deaths (5.67%)** across Seeds 9000–9299.
- Both acceptance targets ($\ge 30$ wins and $< 12$ Ante-1 deaths) were **FAILED**.
- Macro failure analysis indicates that the policy suffers from:
  1. Excessive early-ante economy valuation leading to 17 Ante-1 deaths (11 on Ante-1 Boss).
  2. A massive mid-game bottleneck in Antes 4 and 5 (110 deaths, 36.67% of all runs) where blind targets outpace un-synergized engines before late-game liquidation activates.
  3. Insufficient Ante-8 conversion (29 deaths vs 24 wins among runs reaching Ante 8).
- **Formal Verdict**: **REJECT**.

---

## 5. Verification Method

To independently reproduce the benchmark results, run:

```bash
# 1. Verify CI Seed Exactness Gate (must pass 4/4)
python -m pytest vendor/balatro-rl/tests/test_seed_exactness.py -m ci_gate -v

# 2. Verify static audits (must be CLEAN)
python tools/audit_jokers_static.py
python tools/audit_consumables_static.py
python tools/audit_bosses_static.py
python tools/audit_tags_static.py

# 3. Reproduce benchmark run on Seeds 9000–9299
python bench/bench_agent_v10.py --seeds 9000-9299 --workers 16 --policies search_shop_v10 --report vendor/balatro-rl/results/bench_9000_9299_search_shop_v10.json

# 4. Run deep telemetry analysis script
python tools/analyze_bench_9000.py
```

### Invalidation Conditions
This rejection report is invalidated if:
1. Re-running the deterministic benchmark on Seeds 9000–9299 yields $\ge 30$ wins and $< 12$ Ante-1 deaths under identical parameters.
2. The benchmark sidecar file `vendor/balatro-rl/results/bench_9000_9299_search_shop_v10.json` is shown to have been corrupted or run with altered parameters (`lookahead=True`).
