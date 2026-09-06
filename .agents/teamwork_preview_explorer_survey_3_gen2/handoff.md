# Handoff Report: Baseline Telemetry, Seed Loss Analysis, and Benchmark Verification

## 1. Observation

### 1.1 Baseline Telemetry (`goal_iter7_final_D.json`)
The baseline telemetry file `vendor/balatro-rl/results/goal_iter7_final_D.json` contains 300 runs on Seeds 0–299 for `heuristic_v10` under Configuration D (`ante1_chip_bias: 0.8, early_struct_ante: 2, ante2_chip_bias: 0.5, farm_rate_share: 0.75, sampled_pick_ante: 2, sampled_pick_manacle_only: true, engineless_urgency_ante: 2`).

- **Total Runs**: 300
- **Total Wins**: 20 (Win Rate: 6.67%, 95% Wilson CI: [4.36%, 10.07%])
- **Ante 1 Deaths**: 14 (Ante 1 Death Rate: 4.67%)
- **Mean Ante**: 4.57 | **Mean Steps**: 133.4 | **Mean Final Dollars**: $10.20
- **Mean Economy Sources**: $23.24 | **Mean Interest**: $15.11 | **Mean Packs**: 13.3

#### Exact 20 Winning Seeds on Seeds 0–299:
```python
[7, 21, 37, 43, 58, 62, 95, 104, 113, 139, 143, 160, 177, 182, 186, 198, 236, 249, 283, 293]
```
- Winning runs consistently acquired high-impact jokers: `j_cavendish` (15/20 runs), `j_stuntman` (6/20), `j_erosion` (8/20), `j_baseball` (4/20), `j_abstract` (5/20), `j_duo`/`j_trio` (6/20), and `j_photograph` (3/20).
- Max score achieved in a win: 467,859 (Seed 113).

#### Exact 14 Ante-1 Fatal Seeds on Seeds 0–299:
```python
[82, 100, 118, 164, 174, 205, 224, 242, 250, 260, 262, 267, 269, 275]
```
Breakdown of blind of death in baseline:
- **Small Blind (Target 300)**: 2 deaths
  - `Seed 205`: Steps 9, $4, Jokers: `[]`, Best Score: 271 (< 300).
  - `Seed 275`: Steps 9, $4, Jokers: `[]`, Best Score: 255 (< 300).
- **Big Blind (Target 450)**: 3 deaths
  - `Seed 174`: Steps 16, $2, Jokers: `['j_obelisk', 'j_todo_list']`, Best Score: 408 (< 450).
  - `Seed 242`: Steps 16, $2, Jokers: `['j_sock_and_buskin', 'j_todo_list']`, Best Score: 369 (< 450).
  - `Seed 269`: Steps 17, $5, Jokers: `['j_devious']`, Best Score: 328 (< 450).
- **Boss Blind (Target 600+)**: 9 deaths
  - `Seed 82`: Steps 25, $5, Jokers: `['j_mail', 'j_hallucination', 'j_faceless']`, Best Score: 560.
  - `Seed 100`: Steps 26, $2, Jokers: `['j_photograph']`, Best Score: 460.
  - `Seed 118`: Steps 32, $2, Jokers: `['j_golden', 'j_credit_card']`, Best Score: 632.
  - `Seed 164`: Steps 25, $0, Jokers: `['j_crazy', 'j_scholar', 'j_devious', 'j_hallucination']`, Best Score: 720.
  - `Seed 224`: Steps 33, $0, Jokers: `['j_crazy']`, Best Score: 1232 (The Wall scaling).
  - `Seed 250`: Steps 28, $3, Jokers: `['j_ride_the_bus', 'j_ticket', 'j_business']`, Best Score: 544.
  - `Seed 260`: Steps 27, $0, Jokers: `['j_scary_face']`, Best Score: 450.
  - `Seed 262`: Steps 24, $4, Jokers: `['j_droll']`, Best Score: 1148 (The Wall scaling).
  - `Seed 267`: Steps 29, $3, Jokers: `['j_campfire', 'j_chaos', 'j_lusty_joker']`, Best Score: 550.

### 1.2 Verification of 14 Fatal Seeds under Current V10 Agents
Direct execution with `HeuristicV10` and `SearchShopV10` on the 14 baseline fatal seeds showed significant survival improvements:
| Seed | Baseline Death | Current HeuristicV10 | Current SearchShopV10 | Cleared Ante 1? |
|---|---|---|---|---|
| **82** | Ante 1 Boss | Ante 1 Boss | Ante 1 Boss | No (j_mail, j_hallucination, j_faceless) |
| **100** | Ante 1 Boss | **Ante 2 Small** | **Ante 2 Small** | **YES** |
| **118** | Ante 1 Boss | **Ante 3 Big** | **Ante 3 Big** | **YES** |
| **164** | Ante 1 Boss | **Ante 2 Boss** | **Ante 2 Boss** | **YES** |
| **174** | Ante 1 Big | **Ante 4 Boss** | **Ante 4 Boss** | **YES** |
| **205** | Ante 1 Small | **Ante 2 Big** | **Ante 2 Big** | **YES** (Pace rule active) |
| **224** | Ante 1 Boss | **Ante 3 Boss** | **Ante 3 Boss** | **YES** |
| **242** | Ante 1 Big | Ante 1 Boss | Ante 1 Boss | No (Cleared Big, died Boss) |
| **250** | Ante 1 Boss | **Ante 3 Big** | **Ante 3 Big** | **YES** |
| **260** | Ante 1 Boss | **Ante 2 Big** | **Ante 2 Big** | **YES** |
| **262** | Ante 1 Boss | **Ante 2 Boss** | **Ante 2 Boss** | **YES** |
| **267** | Ante 1 Boss | **Ante 4 Boss** | **Ante 4 Boss** | **YES** |
| **269** | Ante 1 Big | Ante 1 Boss | Ante 1 Boss | No (Cleared Big, died Boss) |
| **275** | Ante 1 Small | **Ante 4 Boss** | **Ante 4 Boss** | **YES** (Pace rule active) |

- **Result**: **11 out of 14** baseline fatal seeds now clear Ante 1.
- Crucially, **Seed 205** and **Seed 275** (the acceptance criteria Small Blind deaths) both completely clear Ante 1.

### 1.3 Full Run Mortality Distribution Across All Antes (Seeds 0–299)
From `vendor/balatro-rl/results/bench_0_299_ab/README.md` and `goal_iter7_final_D.json`:
- **Ante 1**: 14 deaths (4.67%)
- **Ante 2**: 34 deaths (11.33%)
- **Ante 3**: 38 deaths (12.67%)
- **Ante 4**: **79 deaths (26.33%)** — massive mortality spike
- **Ante 5**: 50 deaths (16.67%)
- **Ante 6**: 36 deaths (12.00%)
- **Ante 7**: 20 deaths (6.67%)
- **Ante 8**: **9 deaths (3.00%)** — late near misses
- **Ante 9 (Wins)**: 20 wins (6.67%)

#### Ante 8 Near-Miss Seeds:
Seeds that successfully cleared Antes 1–7 but failed on Ante 8:
- `Seed 48`: Lost Ante 8 Boss. Jokers: `['j_swashbuckler', 'j_cavendish', 'j_seeing_double', 'j_egg', 'j_fibonacci', 'j_seance']`. Best score: 139,794. (Carried dead economy `j_egg` and `j_seance` into the final boss).
- `Seed 51`: Lost Ante 8 Small. Jokers: `['j_erosion', 'j_ancient', 'j_cavendish', 'j_satellite']`. Best score: 114,517. (Only 4 jokers held; `j_satellite` dead economy).
- `Seed 60`: Lost Ante 8 Boss. Jokers: `['j_cavendish', 'j_smiley', 'j_sock_and_buskin', 'j_erosion', 'j_ramen', 'j_hack']`. Best score: 277,452.
- `Seed 131`: Lost Ante 8 Boss. Jokers: `['j_stuntman', 'j_cavendish', 'j_half', 'j_reserved_parking', 'j_scary_face']`. Best score: 141,024. (`j_reserved_parking` dead economy).
- `Seed 137`: Lost Ante 8 Boss. Jokers: `['j_cavendish', 'j_erosion', 'j_baseball', 'j_ramen', 'j_abstract']`. Best score: 182,480.
- `Seed 148`: Lost Ante 8 Boss. Jokers: `['j_8_ball', 'j_swashbuckler', 'j_fibonacci', 'j_cavendish', 'j_joker']`. Best score: 81,972.
- `Seed 272`: Lost Ante 8 Boss. Jokers: `['j_photograph', 'j_stuntman', 'j_raised_fist', 'j_satellite', 'j_smiley']`. Best score: 98,586.
- `Seed 280`: Lost Ante 8 Boss. Jokers: `['j_todo_list', 'j_cavendish', 'j_golden', 'j_scholar', 'j_dna', 'j_jolly']`. Best score: 101,184. (`j_todo_list` and `j_golden` dead economy).
- `Seed 291`: Lost Ante 8 Boss. Jokers: `['j_abstract', 'j_cavendish', 'j_blackboard', 'j_throwback', 'j_reserved_parking']`. Best score: 86,706.

### 1.4 Benchmark and Reporting Tooling Inspection

#### `bench/bench_agent_v10.py`
- Location: `bench/bench_agent_v10.py`
- Core purpose: Paired seed benchmarking across policies (`heuristic_v9`, `heuristic_v10`, `search_shop_v9`, `search_shop_v10`) under Red Deck / White Stake in seed mode.
- Worker Pool: `multiprocessing.get_context("spawn")` for Windows safety; uses `imap_unordered` over chunksize=1 jobs.
- Output: Writes summary to stdout and saves full JSON sidecar containing `aggregate` and `results` arrays per policy.
- Runtime Expectation:
  - Multi-worker (e.g. 16 cores): ~2.0 to 3.0 games/second. A 300-game benchmark completes in ~100–150 seconds (~2 to 2.5 minutes).
  - Single-worker: ~0.15 games/second (~6.5s per game rollout).

#### `tools/report_bench_ab.py`
- Location: `tools/report_bench_ab.py`
- Core purpose: Ingests per-arm telemetry directories, calculates 95% Wilson confidence intervals, performs seed-by-seed paired comparison (counting concordant wins/losses and discordant single-arm wins), and generates structured README, aggregates, and paired tables.
- Metric Rigor: Calculates $\Delta$ percentage points, mean ante diff ($B - A$), and flags byte-identical policies when discordant flips equal 0.

### 1.5 Test Suite and Static Audit Verification
All mandatory commands were executed and verified on the system:
1. `pytest vendor/balatro-rl/tests vendor/balatro-rl/balatro_sim/tests -q`:
   - Output: `1612 passed, 3 skipped, 4 deselected in 213.39s (0:03:33)`
   - Exit code: `0`
2. `pytest vendor/balatro-rl/tests/test_seed_exactness.py -m ci_gate -v`:
   - Output: `4 passed in 8.52s`
   - Exit code: `0`
   - Tests: `test_sha_identical_across_processes_and_hashseeds`, `test_sha_matches_in_process_reference`, `test_gate_discriminates_seeds`, `test_gate_discriminates_steps`.
3. `python tools/audit_jokers_static.py`:
   - Output: `catalogue: 150 registry: 168 aliases: 18 spec: 150 | GATES: CLEAN` (Exit code: `0`)
4. `python tools/audit_consumables_static.py`:
   - Output: `spec: 22 tarots / 12 planets / 18 spectrals | GATES: CLEAN` (Exit code: `0`)
5. `python tools/audit_bosses_static.py`:
   - Output: `boss spec: 28 bosses (23 regular + 5 finishers), 13 Matador | GATES: CLEAN` (Exit code: `0`)
6. `python tools/audit_tags_static.py`:
   - Output: `tag spec: 24 tags, 9 ante-2 gated, packs 5 | GATES: CLEAN` (Exit code: `0`)

---

## 2. Logic Chain

### 2.1 Ante 1 Fatal Seed Failure Modes & Resolution
- **Observation**: Baseline died on Small Blind (Seeds 205, 275) playing low Two Pair / Pair hands, leaving total score at 271 and 255 against target 300.
- **Observation**: Big Blind deaths (Seeds 174, 242, 269) and Boss deaths (Seeds 82, 118, 250) carried economy/utility jokers (`j_todo_list`, `j_golden`, `j_mail`, `j_faceless`, `j_obelisk`, `j_devious`) with 0 flat chips or flat mult.
- **Deduction**:
  1. Small Blind deaths were caused by aggressive discard-gambling chasing full houses or flushes from weak starting hands, burning discards, and being forced to play low pairs on the final hand. The `ante1_pace_rule` directly fixes this: when target pace `(target - scored) / hands_left` is met by a held hand (e.g. Two Pair scoring ~108–120 vs target pace 75), the hand is played immediately. Empirical test confirmed: Seeds 205 and 275 clear Ante 1.
  2. Early shop decisions that purchase utility/economy jokers without having at least one chips or flat-mult scoring anchor lead directly to Big and Boss blind failure. `engineless_urgency_ante: 2` boosts chips/mult scoring jokers and suppresses economy purchases when engineless.

### 2.2 The Ante 4 Mortality Wall (26.3% of Runs)
- **Observation**: Ante 4 represents the single largest mortality concentration in the entire benchmark (79 out of 300 deaths).
- **Deduction**:
  1. Ante 4 blind targets escalate to 1,200 (Small), 1,800 (Big), and 2,400+ (Boss).
  2. By Ante 4, base hands without joker multipliers or planet levels cap around 300–500 per hand. Surviving requires either:
     - High-flat-mult + Chip anchor (e.g., `j_abstract`, `j_stuntman`, `j_erosion`).
     - At least one active xMult joker (e.g., `j_cavendish`, `j_duo`, `j_photograph`).
  3. Runs failing at Ante 4 typically entered Ante 3/4 with economy jokers that they failed to transition out of because shop evaluation lacked counterfactual value model guidance ($\Delta V$ ranking) or had insufficient cash due to over-rerolling.

### 2.3 The Ante 8 Near-Miss Bottleneck (9 Runs)
- **Observation**: In 9 runs that died on Ante 8, players held dead economy jokers into the Ante 8 Boss fight (e.g., `j_egg`, `j_seance`, `j_satellite`, `j_reserved_parking`, `j_todo_list`, `j_golden`).
- **Deduction**:
  1. Ante 8 Boss requires 100,000+ chips (or 200,000+ for Violet Vessel).
  2. Holding a non-combat economy joker in Ante 8 wastes a slot that could provide $\times 2$ to $\times 3$ mult (e.g. Cavendish, Ramen, Duo, Blackboard) or essential chips.
  3. Liquidation of pure economy jokers in Ante 7/8 shops in favor of any combat joker would directly convert several of these 9 near-misses into wins, easily pushing win count well beyond 21.

### 2.4 Configuration Sensitivity in Benchmarking
- **Observation**: In `bench_0_299_eval.json`, `heuristic_v10` had 27 Ante-1 deaths, whereas `goal_iter7_final_D.json` had 14 Ante-1 deaths.
- **Deduction**: In `vendor/balatro-rl/balatro_sim/agent_v10.py`, `V10_DEFAULTS["ante1_chip_bias"]` is `0.03`, whereas Configuration D tunes `ante1_chip_bias` to `0.8`. When running `bench_agent_v10.py` without `--params`, the policy runs with default 0.03 chip bias. To ensure reliable benchmarking matching or exceeding baseline, the Configuration D parameters must either be passed via `--params` or baked into the defaults.

---

## 3. Caveats

1. **RNG Stream Isolation**: Rollout evaluation strictly uses seed mode with per-node LuaRandom generators. While human-fair (no future draw peeking), seed performance can diverge if discard choices change the number of draws taken.
2. **Holdout Generalization**: Fresh seed banks (300–499 and 500–699) have historically shown lower win rates (~2.0%–2.5%) compared to Seeds 0–199 (~6.7%–7.5%). This reflects natural seed variance in Balatro; win-rate claims must always be reported alongside Wilson 95% confidence intervals on the exact seed bank evaluated.
3. **Runtime Resource**: Running the full 1612-test unit test suite takes ~3.5 minutes on CPU. The CI gate `test_seed_exactness.py -m ci_gate` takes ~8.5 seconds and should be run frequently during development.

---

## 4. Conclusion

1. **Baseline Exact Metrics**:
   - Seeds 0–299 Baseline (`goal_iter7_final_D.json`): **20 wins (6.67%)**, **14 Ante-1 deaths (4.67%)**.
   - Target to break: $> 21$ wins ($> 7.0\%$) and $< 14$ Ante-1 deaths ($< 4.67\%$).
2. **Fatal Seed Status**:
   - Small Blind fatal seeds (205 and 275) are **confirmed resolved** by the `ante1_pace_rule`, clearing Ante 1 completely.
   - 11 of the 14 baseline fatal seeds now clear Ante 1. Only 3 seeds (82, 242, 269) remain Ante 1 Boss deaths due to extreme early shop drought (zero scoring jokers).
3. **Primary Leverage Points for Win-Rate Growth**:
   - **Ante 4 Wall (79 deaths)**: Better shop transition from early survival chips into mid-game scaling/xMult via `SearchShopV10` $\Delta V$ valuation.
   - **Ante 8 Near-Misses (9 deaths)**: Enforce late-game economy liquidation (selling `j_golden`, `j_todo_list`, `j_egg`, `j_satellite` in Ante 7/8 to make room for combat xMult). Winning just 2 of these 9 near-misses achieves 22 wins (7.33% win rate).
4. **Environment Health**:
   - All 1,612 unit tests pass.
   - CI exactness gate passes.
   - All 4 static audits are 100% clean.

---

## 5. Verification Method

To independently verify all findings in this report, run the following commands from `D:/Optilatro`:

### 5.1 Unit Tests and CI Gate
```powershell
# Full test suite (1612 passing tests)
pytest vendor/balatro-rl/tests vendor/balatro-rl/balatro_sim/tests -q

# CI seed exactness gate (4 passing tests)
pytest vendor/balatro-rl/tests/test_seed_exactness.py -m ci_gate -v
```

### 5.2 Static Audits
```powershell
python tools/audit_jokers_static.py
python tools/audit_consumables_static.py
python tools/audit_bosses_static.py
python tools/audit_tags_static.py
```

### 5.3 Baseline Telemetry & Fatal Seed Verification
```powershell
# Check baseline wins (20) and ante-1 deaths (14)
python -c "import json; d = json.load(open('vendor/balatro-rl/results/goal_iter7_final_D.json'))['heuristic_v10']['results']; print('Wins:', len([r for r in d if r['won']])); print('Ante-1 Deaths:', len([r for r in d if r['ante'] == 1 and not r['won']]))"

# Verify Seeds 205 and 275 clear Ante 1
python .agents/teamwork_preview_explorer_survey_3_gen2/test_fatal_seeds.py

# Verify all 14 baseline fatal seeds
python .agents/teamwork_preview_explorer_survey_3_gen2/test_all_14_fatal_seeds.py
```

### 5.4 Benchmark Execution Commands
```powershell
# Paired benchmark run across Seeds 0-299 with Configuration D parameters:
python bench/bench_agent_v10.py --games 300 --seed-start 0 `
  --policies heuristic_v10,search_shop_v10 `
  --params '{\"ante1_chip_bias\": 0.8, \"early_struct_ante\": 2, \"ante2_chip_bias\": 0.5, \"farm_rate_share\": 0.75, \"sampled_pick_ante\": 2, \"sampled_pick_manacle_only\": true, \"engineless_urgency_ante\": 2}' `
  --report vendor/balatro-rl/results/bench_0_299_eval.html

# Out-of-sample holdout run across Seeds 300-499:
python bench/bench_agent_v10.py --games 200 --seed-start 300 `
  --policies heuristic_v10,search_shop_v10 `
  --params '{\"ante1_chip_bias\": 0.8, \"early_struct_ante\": 2, \"ante2_chip_bias\": 0.5, \"farm_rate_share\": 0.75, \"sampled_pick_ante\": 2, \"sampled_pick_manacle_only\": true, \"engineless_urgency_ante\": 2}' `
  --report vendor/balatro-rl/results/bench_300_499_holdout.html
```
