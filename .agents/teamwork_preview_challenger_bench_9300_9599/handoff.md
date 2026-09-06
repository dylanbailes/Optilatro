# Empirical Challenger Benchmark Report: Seeds 9300–9599 (`search_shop_v10`)

**Agent**: `teamwork_preview_challenger_bench_9300_9599`  
**Parent**: `orchestrator_4` (`ae7f41b5-88b7-4891-99ec-90a2e8f71801`)  
**Evaluated Policy**: `search_shop_v10`  
**Seed Bank**: Pristine, never-before-seen Seeds 9300–9599 (300 games, zero overlap with 0–299 or 9000–9299)  
**Report Artifact**: `vendor/balatro-rl/results/bench_9300_9599_search_shop_v10.json`  
**Benchmark Execution Time**: 285 seconds (~1.1 games/second across 16 parallel workers)  

---

## 1. Observation

### 1.1 Benchmark Execution Command and Console Output
The benchmark was executed with the authoritative command:
```bash
python bench/bench_agent_v10.py --seeds 9300-9599 --workers 16 --policies search_shop_v10 --report vendor/balatro-rl/results/bench_9300_9599_search_shop_v10.json
```
Verbatim console aggregate output:
```text
=== search_shop_v10 (285s, 1.1 games/s) ===
  wins 32/300 = 10.67% | ante-1 deaths 12 (4.00%) | mean ante 5.06 | mean steps 149
  econ-source $16.5/run | interest $17.6/run | tarots 7.1 planets 6.4 spectrals 0.4 | end $8.2
  ante 1:    12 ( 4.00%) ##
  ante 2:    21 ( 7.00%) ###
  ante 3:    44 (14.67%) #######
  ante 4:    54 (18.00%) #########
  ante 5:    60 (20.00%) ##########
  ante 6:    32 (10.67%) #####
  ante 7:    24 ( 8.00%) ####
  ante 8:    21 ( 7.00%) ###
  ante 9:    32 (10.67%) #####

report sidecar: vendor\balatro-rl\results\bench_9300_9599_search_shop_v10.json
```

### 1.2 Comparison Against Baseline `heuristic_v9` on Exact Same Seeds (9300–9599)
Inspecting `vendor/balatro-rl/results/bench_9300_9599_baseline_v9.json`:
- Baseline v9 Wins: **9 / 300** (3.00%)
- Baseline v9 Ante 1 Deaths: **27 / 300** (9.00%)
- `search_shop_v10` Wins: **32 / 300** (10.67%) [Net Gain: +23 wins, +7.67 percentage points, +255.6% relative gain]
- `search_shop_v10` Ante 1 Deaths: **12 / 300** (4.00%) [Net Reduction: -15 deaths, -5.00 percentage points, -55.6% relative reduction]
- Paired breakdown:
  - Gains (`v9` lost $\to$ `v10` won): 26 seeds
  - Regressions (`v9` won $\to$ `v10` lost): 3 seeds (seeds 9322, 9400, 9467)
  - Common wins: 6 seeds

### 1.3 Comparison Against Previous Verification Bank (Seeds 9000–9299)
- Seeds 9000–9299 (`bench_9000_9299_search_shop_v10.json`):
  - Wins: 24 / 300 (8.00%)
  - Ante 1 Deaths: 17 / 300 (5.67%)
  - Mean Ante: 4.88
- Seeds 9300–9599 (`bench_9300_9599_search_shop_v10.json`):
  - Wins: 32 / 300 (10.67%)
  - Ante 1 Deaths: 12 / 300 (4.00%)
  - Mean Ante: 5.06

### 1.4 Full Mortality Breakdown by Ante
| Ante | Deaths | Death % | Cumulative Mortality |
|:---:|:---:|:---:|:---:|
| Ante 1 | 12 | 4.00% | 4.00% |
| Ante 2 | 21 | 7.00% | 11.00% |
| Ante 3 | 44 | 14.67% | 25.67% |
| Ante 4 | 54 | 18.00% | 43.67% |
| Ante 5 | 60 | 20.00% | 63.67% |
| Ante 6 | 32 | 10.67% | 74.33% |
| Ante 7 | 24 | 8.00% | 82.33% |
| Ante 8 | 21 | 7.00% | 89.33% |
| **Ante 8 Cleared (Wins)** | **32** | **10.67%** | **100.00%** |

### 1.5 Forensic Audit of All 12 Ante 1 Deaths
Direct inspection of the 12 seeds failing in Ante 1:
1. **Seed 9300** | Ante 1 Big Blind | Scored: 183 / 450 | Held: `['j_business', 'j_pareidolia']` | Bought: `['j_pareidolia']` | Dollars: $1. Zero chip/mult boost.
2. **Seed 9323** | Ante 1 Boss Blind (`bl_goad`, debuffs Spades) | Scored: 342 / 600 | Held: `['j_crazy', 'j_lusty_joker']` | Bought: `['j_lusty_joker']` | Dollars: $0.
3. **Seed 9378** | Ante 1 Boss Blind (`bl_manacle`, -1 hand size) | Scored: 158 / 600 | Held: `['j_scholar', 'j_business', 'j_fortune_teller']` | Bought: `['j_business', 'j_fortune_teller']` | Dollars: $3.
4. **Seed 9379** | Ante 1 Boss Blind (`bl_goad`) | Scored: 253 / 600 | Held: `['j_constellation']` | Bought: `[]` | Dollars: $1. Constellation at 1.0x provides no base mult.
5. **Seed 9397** | Ante 1 Big Blind | Scored: 364 / 450 | Held: `['j_bull', 'j_hologram']` | Bought: `['j_bull']` | Dollars: $0. Bull provides 0 chips because cash is $0; Hologram is unscaled 1.0x.
6. **Seed 9438** | Ante 1 Big Blind | Scored: 418 / 450 | Held: `['j_splash']` | Bought: `[]` | Dollars: $1. **Died with 3 discards remaining** (`HandsLeft=0, DiscardsLeft=3`).
7. **Seed 9460** | Ante 1 Small Blind | Scored: 264 / 300 | Held: `[]` | Bought: `[]` | Dollars: $4. Opening blind failed to draw playable pairs/straights/flushes.
8. **Seed 9470** | Ante 1 Boss Blind (`bl_manacle`) | Scored: 522 / 600 | Held: `['j_wily', 'j_cloud_9', 'j_lusty_joker']` | Bought: `['j_wily']` | Dollars: $4.
9. **Seed 9512** | Ante 1 Boss Blind (`bl_hook`, discards 2 random cards) | Scored: 479 / 600 | Held: `['j_splash', 'j_mail']` | Bought: `['j_mail']` | Dollars: $3.
10. **Seed 9549** | Ante 1 Boss Blind (`bl_goad`) | Scored: 416 / 600 | Held: `['j_pareidolia']` | Bought: `[]` | Dollars: $0.
11. **Seed 9575** | Ante 1 Big Blind | Scored: 164 / 450 | Held: `['j_throwback']` | Bought: `[]` | Dollars: $5. Throwback at 1.0x with 0 skips.
12. **Seed 9577** | Ante 1 Boss Blind (`bl_window`, debuffs Diamonds) | Scored: 584 / 600 | Held: `['j_gluttenous_joker', 'j_splash', 'j_dna']` | Bought: `['j_gluttenous_joker', 'j_splash']` | Dollars: $1. **Died with 2 discards remaining**; missed target by just 16 chips.

Summary of Ante 1 Deaths by Blind:
- Small Blind: **1 / 300** (0.33%)
- Big Blind: **4 / 300** (1.33%)
- Boss Blind: **7 / 300** (2.33%)

### 1.6 Finisher & High-Leverage Joker Acquisition and Win Conversion
| Joker Key | Acquired Runs | Acquisition Rate % | Won Runs | Win Conversion % |
|---|:---:|:---:|:---:|:---:|
| `j_cavendish` | 71 | 23.67% | 24 | 33.80% |
| `j_duo` | 15 | 5.00% | 5 | 33.33% |
| `j_trio` | 15 | 5.00% | 4 | 26.67% |
| `j_family` | 17 | 5.67% | 3 | 17.65% |
| `j_order` | 9 | 3.00% | 1 | 11.11% |
| `j_tribe` | 5 | 1.67% | 2 | 40.00% |
| `j_card_sharp` | 13 | 4.33% | 1 | 7.69% |
| `j_baseball` | 12 | 4.00% | 3 | 25.00% |
| `j_acrobat` | 10 | 3.33% | 1 | 10.00% |
| `j_constellation` | 23 | 7.67% | 7 | 30.43% |
| `j_hologram` | 18 | 6.00% | 4 | 22.22% |
| `j_blueprint` | 10 | 3.33% | 2 | 20.00% |
| `j_brainstorm` | 6 | 2.00% | 2 | 33.33% |
| `j_baron` | 15 | 5.00% | 3 | 20.00% |
| `j_ancient` | 17 | 5.67% | 1 | 5.88% |
| `j_ramen` | 28 | 9.33% | 10 | 35.71% |
| `j_stuntman` | 13 | 4.33% | 3 | 23.08% |
| `j_photograph` | 60 | 20.00% | 12 | 20.00% |
| **Core 4 Premier** (`cavendish`, `baseball`, `constellation`, `acrobat`) | **97** | **32.33%** | **26** | **26.80%** |
| **Reliable xMult Pool** | **180** | **60.00%** | **32** | **17.78%** |
| **All High-Leverage** | **192** | **64.00%** | **32** | **16.67%** |

*Key finding*: 100% of all 32 winning runs acquired at least one joker from the Reliable xMult Pool. Zero runs without a reliable xMult joker won Ante 8 (0/120 = 0.0%). Furthermore, 26 out of 32 wins (81.25%) held a Core 4 Premier finisher (`j_cavendish` alone accounted for 24 of the 32 wins).

### 1.7 Verification of Human-Fair and Isolation Guarantees
1. **CI Exactness Gate**:
   Command: `python -m pytest vendor/balatro-rl/tests/test_seed_exactness.py -m ci_gate -v`
   Result: **4 passed in 7.41s** (100% clean).
2. **Static Audits**:
   - `audit_jokers_static.py`: 150 jokers, 0 dupes, 0 dead, 0 stubs, 0 gaps, 0 noscan $\to$ **GATES: CLEAN**
   - `audit_consumables_static.py`: 22 tarots, 12 planets, 18 spectrals $\to$ **GATES: CLEAN**
   - `audit_bosses_static.py`: 28 bosses $\to$ **GATES: CLEAN**
   - `audit_tags_static.py`: 24 tags $\to$ **GATES: CLEAN**
3. **Unit & Integration Suite**:
   Command: `python -m pytest vendor/balatro-rl/tests/test_e2e_v10_requirements.py vendor/balatro-rl/tests/test_scaling_acceleration.py -v`
   Result: **54 passed in 79.41s** (100% clean).
4. **Draw Order & RNG Isolation**:
   - Benchmark ran with `lookahead=False`.
   - Feature extractor `extract_game_features` accesses only visible state (held cards, deck counts, shop items, cash).
   - Scoring and valuation do not mutate the live game or advance `game.rng`.

---

## 2. Logic Chain

1. **Target Criteria Definition**:
   The user prompt and `ORIGINAL_REQUEST.md` establish two explicit acceptance criteria for the 300-seed benchmark:
   - Criteria 1: Win rate $\ge 10.0\%$ ($\ge 30$ wins / 300).
   - Criteria 2: Ante 1 mortality $< 4.0\%$ ($< 12$ deaths / 300).
   - Explicit verdict instruction: `"APPROVE (if >= 30 wins and < 12 Ante-1 deaths) or REJECT."`

2. **Evaluation of Criteria 1 (Win Rate)**:
   - Observed wins: **32 / 300** = **10.67%** (95% Wilson CI: 7.66% – 14.67%).
   - Since $32 \ge 30$, Criteria 1 is **SATISFIED (PASS)**.
   - Compared to baseline v9 on the exact same seed bank (9 wins, 3.00%), this represents a +255.6% relative improvement and validates the effectiveness of the late-game capital deployment and finisher transition logic.

3. **Evaluation of Criteria 2 (Ante 1 Mortality)**:
   - Observed Ante 1 deaths: **12 / 300** = **4.00%** (95% Wilson CI: 2.30% – 6.86%).
   - The acceptance rule is strictly formulated as `< 12` deaths (`< 4.00%`).
   - Mathematically, $12 < 12$ is **False**, and $4.00\% < 4.00\%$ is **False**.
   - Exactly 12 runs terminated in Ante 1. To satisfy $< 12$, deaths must be $\le 11$ ($\le 3.67\%$).
   - Therefore, Criteria 2 is **NOT SATISFIED (FAIL)** by a margin of exactly 1 fatal run.

4. **Conjunctive Acceptance Rule**:
   - The conditional rule is `(>= 30 wins AND < 12 Ante-1 deaths)`.
   - Since the second clause is False, the conjunction evaluates to `False`.
   - In accordance with the role of an Empirical Challenger, we do not round down or relax strict inequality thresholds.
   - Consequently, the formal verdict must be **REJECT**.

---

## 3. Caveats

1. **Near-Miss Boundary**:
   The policy missed the Ante-1 threshold by exactly one death (12 actual vs $\le 11$ required). In two of the failed seeds (Seed 9438 and Seed 9577), the agent died holding unspent discards (3 discards on 9438, 2 discards on 9577; 9577 missed by only 16 chips). Had discard pacing fully utilized available hands/discards, Ante 1 deaths could have been $\le 10$.
2. **Substantial Progress from Prior Verification Run**:
   Compared to Seeds 9000–9299 (24 wins, 17 Ante-1 deaths), Seeds 9300–9599 demonstrated notable systemic progress (32 wins, 12 Ante-1 deaths). The win rate increased from 8.00% to 10.67%, and Ante 1 mortality dropped from 5.67% to 4.00%.
3. **Sample Variability**:
   On a 300-seed sample, a difference of 1 game represents 0.33%. The 95% Wilson CI for Ante-1 mortality is [2.30%, 6.86%], which encompasses the 4.00% target. Nonetheless, on the empirical point estimate, 12 deaths does not meet $< 12$.

---

## 4. Conclusion

- **Verdict**: **REJECT**
- **Rationale**:
  While `search_shop_v10` achieved **32 wins / 300 (10.67%)**, decisively clearing the $\ge 30$ win requirement, it recorded exactly **12 Ante-1 deaths / 300 (4.00%)**, which fails the strict acceptance condition of **$< 12$ Ante-1 deaths ($< 4.00\%$)**.
- **Actionable Takeaways**:
  To achieve formal approval on a future fresh bank (e.g. Seeds 9600–9899), the team should address the two Ante 1 leakages observed in Seeds 9438 and 9577:
  1. Ensure Ante 1 in-blind discard pacing exhausts all available discards when projected hand score is insufficient to clear the blind (prevent dying with $DiscardsLeft \ge 2$).
  2. Further restrain shop purchases in Ante 1 for pure utility jokers (`j_pareidolia`, `j_splash`, `j_business`) when cash is depleted to $\le \$1$ and no scoring mult/chip base has been established.

---

## 5. Verification Method

To independently verify all observations, telemetry, and criteria:

1. **Re-run the 300-Seed Benchmark**:
   ```bash
   python bench/bench_agent_v10.py --seeds 9300-9599 --workers 16 --policies search_shop_v10 --report vendor/balatro-rl/results/bench_9300_9599_search_shop_v10.json
   ```
2. **Execute the Telemetry & Acceptance Analysis**:
   ```bash
   python tools/analyze_bench_9300.py
   ```
   Inspect stdout for:
   - `Wins: 32 / 300 (10.67%)`
   - `Ante 1 Deaths: 12 / 300 (4.00%)`
   - `Criteria 1: PASS`
   - `Criteria 2: FAIL`
   - `FINAL VERDICT: REJECT`
3. **Verify CI Exactness Gate & Audits**:
   ```bash
   python -m pytest vendor/balatro-rl/tests/test_seed_exactness.py -m ci_gate -v
   python tools/audit_jokers_static.py
   python tools/audit_consumables_static.py
   python tools/audit_bosses_static.py
   python tools/audit_tags_static.py
   ```
