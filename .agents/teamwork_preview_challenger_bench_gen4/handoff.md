# Handoff Report: Challenger Bench Gen4 (Seeds 0–299 Paired Benchmark)

**Verdict**: **REJECT**  
**Milestone**: M2 Paired Benchmark Verification (Seeds 0–299)  
**Agent**: `teamwork_preview_challenger_bench_gen4` (Empirical Challenger)  
**Target Policy**: `search_shop_v10`  

---

## 1. Observation

### Benchmark Execution & Results
Command executed:
```powershell
python bench/bench_agent_v10.py --seeds 0-299 --workers 16 --policies search_shop_v10 --report vendor/balatro-rl/results/bench_0_299_search_shop_v10_gen4.json
```
Elapsed time: 335s (0.9 games/s). Generated artifact: `vendor/balatro-rl/results/bench_0_299_search_shop_v10_gen4.json`.

#### Aggregate Performance Comparison
| Metric | Gen4 Candidate (`search_shop_v10`) | Frozen Baseline V10/V9 (`bench_0_299_search_shop_v10.json`) | Acceptance Threshold | Delta vs Baseline | Status |
|---|---|---|---|---|---|
| **Total Games** | 300 | 300 | 300 | — | — |
| **Wins** | **26** | 26 | **>= 30** | +0 | **FAIL** |
| **Win Rate** | **8.67%** | 8.67% | **>= 10.0%** | +0.00% | **FAIL** |
| **Ante 1 Deaths** | **13** | 11 | **< 12** | **+2** | **FAIL** |
| **Ante 1 Mortality** | **4.33%** | 3.67% | **< 4.00%** | **+0.66%** | **FAIL** |
| **Mean Ante Cleared** | 4.84 | 4.94 | — | -0.10 | Regression |
| **Mean Dollars at End** | $8.72 | $10.31 | — | -$1.59 | - |

#### Mortality Breakdown by Ante
| Ante | Deaths | Percentage | Visual Bar |
|---|---|---|---|
| **Ante 1** | 13 | 4.33% | `##` |
| **Ante 2** | 28 | 9.33% | `####` |
| **Ante 3** | 53 | 17.67% | `########` |
| **Ante 4** | 51 | 17.00% | `########` |
| **Ante 5** | 49 | 16.33% | `########` |
| **Ante 6** | 35 | 11.67% | `#####` |
| **Ante 7** | 28 | 9.33% | `####` |
| **Ante 8** | 17 | 5.67% | `##` |
| **Ante 9 (Wins)** | 26 | 8.67% | `####` |

#### Premier Finishers Acquired Across 300 Seeds
- `j_cavendish`: 56 runs (18.67%)
- `j_duo`: 7 runs (2.33%)
- `j_trio`: 14 runs (4.67%)
- `j_family`: 14 runs (4.67%)
- `j_baseball`: 13 runs (4.33%)
- `j_acrobat`: 17 runs (5.67%)
- `j_constellation`: 17 runs (5.67%)
- **Total runs acquiring >= 1 premier finisher**: 106 / 300 (35.33%) vs 117 / 300 (39.00%) in baseline.

---

### Critical Defects Uncovered

#### 1. Ante-1 Mortality Regression & Fatal Flip on Seed 298
- Gen4 Ante 1 Deaths (13 seeds): `[33, 82, 100, 145, 164, 168, 199, 250, 260, 269, 287, 291, 298]`
- Baseline Ante 1 Deaths (11 seeds): `[33, 82, 100, 145, 164, 199, 250, 260, 269, 287, 291]`
- **New Ante 1 Deaths**: `Seed 168` and `Seed 298`.
- In baseline, **Seed 298 WON the game** (reached Ante 9, 273 steps, 5 jokers). In Gen4, Seed 298 died on **Ante 1 Big Blind**!

#### 2. Root Cause: Fatal Crash in `_EvalGame` on Blueprint / Brainstorm
Tracing Seed 298 and Seed 168 revealed identical failure modes:
1. In `vendor/balatro-rl/balatro_sim/agent_v10.py` line 1371, `remedy_gen3` forced purchase of Blueprint/Brainstorm:
   ```python
   if item.key in ("j_blueprint", "j_brainstorm"):
       value = max(value, 1.5)
   ```
2. When the agent buys `j_blueprint` or `j_brainstorm`, subsequent calls to evaluate hand scores (`eval_hand_score` in `vendor/balatro-rl/balatro_sim/agent_v9.py`) instantiate:
   ```python
   eg = _EvalGame()
   ```
   `_EvalGame` defines `__slots__ = ("rng", "vouchers", "consumable_hand")` and does NOT define `.jokers`.
3. In `vendor/balatro-rl/balatro_sim/jokers/misc.py` lines 159 & 191, Blueprint/Brainstorm delegator accesses:
   ```python
   def _jokers(inst, ctx):
       return inst.game.jokers
   ```
   This raises:
   ```
   AttributeError: '_EvalGame' object has no attribute 'jokers'
   ```
4. `scored_plays()` in `agent_v10.py` catches all exceptions during candidate scoring with `except Exception: continue`. Consequently, **every candidate hand score is dropped and `scored_plays` returns an empty list `[]`**.
5. Line 3004 of `agent_v10.py` falls back to:
   ```python
   if not plays:
       return {"type": "play", "cards": [0] if game.hand else []}
   ```
   The agent is forced into playing 1-card High Cards (`cards: [0]`) on every remaining hand until defeat!
6. Across the entire 300-seed benchmark:
   - **32 runs** acquired `j_blueprint` or `j_brainstorm`.
   - **29 of those 32 runs died** (90.6% mortality rate).
   - Trace confirmed Seed 298 played `[0]`, `[0]`, `[0]`, `[0]` on Ante 1 Big Blind and died with 0 chips.
   - Trace confirmed Seed 168 played `[0]`, `[0]`, `[0]`, `[0]` on Ante 1 Boss and died.

---

## 2. Logic Chain

1. **Premise 1 (Acceptance Criteria)**:
   - Win rate must be $\ge 10.0\%$ ($\ge 30$ wins / 300).
   - Ante 1 deaths must be $< 12$ ($< 4.00\%$).
2. **Observation 1**:
   - The empirical 300-seed benchmark under `search_shop_v10` yielded 26 wins (8.67%) and 13 Ante-1 deaths (4.33%).
3. **Inference 1**:
   - Win rate fails: $26 < 30$ (deficit of 4 wins).
   - Mortality fails: $13 \ge 12$ (excess of 2 deaths).
4. **Observation 2**:
   - Seed 298 was a win in baseline and became an Ante-1 death in Gen4.
   - Seed 168 became an Ante-1 death in Gen4.
5. **Inference 2**:
   - Net change in Ante-1 mortality is $+2$ deaths, representing an active regression against the frozen baseline.
6. **Observation 3**:
   - Blueprint and Brainstorm trigger `AttributeError: '_EvalGame' object has no attribute 'jokers'` during `eval_hand_score`.
   - `scored_plays` returns empty `[]`, resulting in deterministic failure via 1-card play spam.
   - 29 out of 32 Blueprint/Brainstorm runs died.
7. **Conclusion**:
   - The candidate policy violates both core acceptance criteria and suffers from an active critical defect in the scoring evaluation engine. The candidate must be rejected.

---

## 3. Caveats

- Holdout bank (Seeds 300–499) was not evaluated because the candidate failed the primary gate criteria on Seeds 0–299.
- Individual seed flips show that some seeds gained wins (+15 wins gained on other seeds), demonstrating that late-game liquidation and targeted swaps have positive potential once the underlying `_EvalGame` defect is corrected.
- No other simulator modifications were introduced or tested during this evaluation turn.

---

## 4. Conclusion

**VERDICT: REJECT**

The Gen4 candidate policy fails the milestone acceptance criteria on both dimensions:
1. **Win Rate**: 26 / 300 (8.67%) vs target $\ge 30 / 300$ ($\ge 10.00\%$).
2. **Ante 1 Mortality**: 13 / 300 (4.33%) vs target $< 12 / 300$ ($< 4.00\%$).
3. **Regression**: Ante-1 deaths increased from 11 to 13 (+2 regression), including baseline winning seed 298 turning into an Ante-1 death.
4. **Root Cause**: `_EvalGame` in `agent_v9.py` lacks a `jokers` attribute in its `__slots__` and initialization. When `j_blueprint` or `j_brainstorm` is owned, hand evaluation crashes, causing `scored_plays` to return empty lists and the agent to play 1-card High Cards until round loss.

---

## 5. Verification Method

To independently reproduce the findings:

1. **Run the 300-Seed Benchmark**:
   ```powershell
   python bench/bench_agent_v10.py --seeds 0-299 --workers 16 --policies search_shop_v10 --report vendor/balatro-rl/results/bench_0_299_search_shop_v10_gen4.json
   ```
   Inspect summary:
   - Wins: 26 (8.67%)
   - Ante 1 deaths: 13 (4.33%)

2. **Reproduce the `_EvalGame` AttributeError on Seed 298**:
   ```powershell
   python -c "import sys; sys.path.insert(0, 'vendor/balatro-rl'); from balatro_sim.game import BalatroGame; from balatro_sim.agent_v9 import eval_hand_score; from balatro_sim.hand_eval import evaluate_hand; game = BalatroGame(seed=298, rng_mode='seed'); game.step({'type': 'play_blind'}); game.step({'type': 'discard', 'cards': [0, 3, 4]}); game.step({'type': 'play', 'cards': [0, 1, 2, 4, 5]}); game.step({'type': 'noop'}); game.step({'type': 'buy', 'item_idx': 0}); game.step({'type': 'leave_shop'}); game.step({'type': 'play_blind'}); cards = game.hand[:5]; ht, sc = evaluate_hand(cards); eval_hand_score(game, ht, sc, cards)"
   ```
   Expected output:
   ```
   AttributeError: '_EvalGame' object has no attribute 'jokers'
   ```

3. **Verify Seed 298 1-Card Play Spam**:
   ```powershell
   python -c "import sys; sys.path.insert(0, 'vendor/balatro-rl'); from balatro_sim.game import BalatroGame, State; from balatro_sim.agent_v10 import SearchShopV10; game = BalatroGame(seed=298, rng_mode='seed'); policy = SearchShopV10(); [game.step(policy.decide(game)) for _ in range(11)]; print('Dead on Ante:', game.ante, 'State:', game.state, 'Jokers:', [j.key for j in game.jokers])"
   ```
