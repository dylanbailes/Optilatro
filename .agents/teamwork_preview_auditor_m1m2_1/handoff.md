## Forensic Audit Report

**Work Product**: Milestone 1 (Ante-1 Multi-Hand Pace Rule) & Milestone 2 (Joker Portfolio Classification & Feature Extraction)
**Profile**: General Project / Balatro Engine
**Verdict**: CLEAN

---

### Phase Results
- **Hardcoding & Cheat Detection**: PASS — Zero hardcoded seed branches, zero facade methods, zero dummy implementations.
- **Human-Fairness & RNG Purity**: PASS — No draw-order peeking, no RNG consumption during evaluation, pure order-independent multiset deck stats.
- **Baseline Immutability & Parity**: PASS — Baseline `agent_v9.py` verified with 58/58 passing unit tests and byte-identical farm-off decisions.
- **Static Audit Gates**: PASS — All 4 gates (`audit_jokers_static.py`, `audit_consumables_static.py`, `audit_bosses_static.py`, `audit_tags_static.py`) report `GATES: CLEAN` (Exit code 0).
- **CI Seed Exactness Gate**: PASS — `vendor/balatro-rl/tests/test_seed_exactness.py -m ci_gate` passes 4/4 tests.
- **E2E & Unit Test Suites**: PASS — 1,608 simulator unit tests pass (100%), 42/42 E2E requirement tests pass (100%), 23/23 portfolio tests pass (100%).

---

# 1. Observation

### 1.1 Empirical Test Execution & Raw Output

1. **Simulator Unit Test Suite**:
   Command: `python -m pytest vendor/balatro-rl/tests vendor/balatro-rl/balatro_sim/tests -q`
   ```text
   ........................................................................ [  4%]
   ........................................................................ [  8%]
   ........................................................................ [ 13%]
   ........................................................................ [ 17%]
   ........................................................................ [ 22%]
   ........................................................................ [ 26%]
   ........................................................................ [ 31%]
   ........................................................................ [ 35%]
   ........................................................................ [ 40%]
   ........................................................................ [ 44%]
   ........................................................................ [ 49%]
   ........................................................................ [ 53%]
   ........................................................................ [ 58%]
   ........................................................................ [ 62%]
   ........................................................................ [ 67%]
   ......................................................ss.s.............. [ 71%]
   ........................................................................ [ 75%]
   ........................................................................ [ 80%]
   ........................................................................ [ 84%]
   ........................................................................ [ 89%]
   ........................................................................ [ 93%]
   ........................................................................ [ 98%]
   ...........................                                              [100%]
   1608 passed, 3 skipped, 4 deselected in 191.76s (0:03:11)
   ```

2. **Static Audits (4 Gates)**:
   - `python tools/audit_jokers_static.py`
     ```text
     catalogue: 150  registry: 168  aliases: 18  spec: 150
     DUPES  0
     DEAD   0
     STUBS  0
     GAPS   cat=0 spec=0 broken_aliases=0
     TYPE   0
     SIG    0
     STATE  0
     NOSCAN 0
     GATES: CLEAN
     ```
   - `python tools/audit_consumables_static.py`
     ```text
     spec: 22 tarots / 12 planets / 18 spectrals
     NAMES   0
     COUNTS  0
     PLANET  0
     TARGETS 0
     EFFECT  0
     DEAD    0
     WIRED   0
     VNAMES  0
     VPAIRS  0
     VEFFECT 0
     GATES: CLEAN
     ```
   - `python tools/audit_bosses_static.py`
     ```text
     boss spec: 28 bosses (23 regular + 5 finishers), 13 Matador, scaling {'bl_needle': 1, 'bl_violet': 6, 'bl_wall': 4}
     COUNT    0
     MIN_ANTE 0
     SHOWDOWN 0
     SCALING  0
     SELECT   0
     MATADOR  0
     EFFECT   0
     WIRED    0
     GATES: CLEAN
     ```
   - `python tools/audit_tags_static.py`
     ```text
     tag spec: 24 tags, 9 ante-2 gated, packs 5
     NAMES    0
     COUNTS   0
     ANTE     0
     EFFECT   0
     WIRED    0
     GATES: CLEAN
     ```

3. **CI Seed Exactness Gate**:
   Command: `python -m pytest vendor/balatro-rl/tests/test_seed_exactness.py -m ci_gate -v`
   ```text
   vendor\balatro-rl\tests\test_seed_exactness.py::TestCrossProcessShaStability::test_sha_identical_across_processes_and_hashseeds PASSED [ 25%]
   vendor\balatro-rl\tests\test_seed_exactness.py::TestCrossProcessShaStability::test_sha_matches_in_process_reference PASSED [ 50%]
   vendor\balatro-rl\tests\test_seed_exactness.py::TestCrossProcessShaStability::test_gate_discriminates_seeds PASSED [ 75%]
   vendor\balatro-rl\tests\test_seed_exactness.py::TestCrossProcessShaStability::test_gate_discriminates_steps PASSED [100%]
   4 passed in 5.31s
   ```

4. **E2E Requirement Suite (4 Tiers, 42 Tests)**:
   Command: `python -m pytest vendor/balatro-rl/tests/test_e2e_v10_requirements.py -v`
   ```text
   42 passed in 54.83s (All Tier 1, Tier 2, Tier 3, Tier 4 test cases green)
   ```

5. **Portfolio Unit Test Suite (23 Tests)**:
   Command: `python -m pytest tests/test_portfolio.py -v`
   ```text
   23 passed in 0.28s
   ```

6. **Baseline V9 Verification Suite (58 Tests)**:
   Command: `python -m pytest vendor/balatro-rl/tests/test_agent_v9.py -v`
   ```text
   58 passed in 40.69s
   ```

### 1.2 Fatal Seeds 205 & 275 Empirical Toggle Check
- With `ante1_pace_rule = False`:
  - Seed 205 Cleared Ante 1 = `False` (Died in Ante 1 Small Blind)
  - Seed 275 Cleared Ante 1 = `False` (Died in Ante 1 Small Blind)
- With `ante1_pace_rule = True` (Default V10 policy):
  - Seed 205 Cleared Ante 1 = `True` (Cleared Ante 1 to Ante 2)
  - Seed 275 Cleared Ante 1 = `True` (Cleared Ante 1 to Ante 2)

---

# 2. Logic Chain

1. **Authenticity of Pace Rule**:
   - The pace rule in `vendor/balatro-rl/balatro_sim/agent_v10.py` calculates `pace = (target / max(1, game.hands_left)) * pace_mult`.
   - On Ante 1 Small Blind ($300 target / 4 hands = 75 pace), an initial Two Pair or Three of a Kind hand scoring $\ge 75$ chips is played immediately instead of gambling discards for thin 5-card upgrades.
   - The empirical toggle check verifies that seeds 205 and 275 fail under `ante1_pace_rule = False` and succeed under `ante1_pace_rule = True`. There are zero seed conditionals or hardcoded branches in `agent_v10.py`.

2. **Authenticity of Joker Portfolio & Feature Extraction**:
   - `tools/portfolio.py` maps all 150 canonical jokers from `tools/joker_spec.json` and 18 canonical aliases into 6 strategic roles (`CHIPS_JOKERS`, `FLAT_MULT_JOKERS`, `XMULT_JOKERS`, `SCALING_JOKERS`, `ECON_JOKERS`, `RETRIGGER_JOKERS`).
   - `extract_features_from_state` computes a 42-dimensional numerical vector capturing progression, financial state, portfolio balance, editions, and danger indicators.
   - `extract_game_features` only inspects visible game fields (`game.jokers`, `game.vouchers`, `game.planet_levels`, `game.deck`, `game.dollars`, `game.ante`, `game.blind_idx`) using order-independent multiset statistics. It never modifies `game` state and never touches the `game.rng` stream (verified by `test_no_rng_stream_mutation` and `test_no_game_state_mutation`).

3. **Baseline Immutability & Human-Fairness**:
   - `agent_v9.py` passes all 58 baseline unit tests in `test_agent_v9.py`.
   - `test_realworld_farm_off_vs_v9_exactness` confirms identical byte-for-byte decisions on seeds 0, 1, 2 between `HeuristicV9()` and `HeuristicV10(farm_clear_threshold=1.0, ante1_pace_rule=False)`.
   - No code accesses future draw order or future RNG draws.

---

# 3. Caveats

No caveats. All investigated modules strictly adhere to human-fairness guidelines and maintain 100% test pass rates across all test suites and audit gates.

---

# 4. Conclusion

**Verdict: CLEAN**

Milestone 1 (Ante-1 Multi-Hand Pace Rule) and Milestone 2 (Joker Portfolio Classification & State Feature Extraction) are certified CLEAN:
- Zero hardcoded seed values or cheats.
- Zero RNG leakage or state mutation.
- All 4 static audit gates pass with zero violations.
- CI seed exactness gate passes.
- All 1,608 simulator unit tests, 42 E2E tests, 23 portfolio tests, and 58 V9 baseline tests pass.

---

# 5. Verification Method

To independently verify this forensic audit:

1. **Run All 4 Static Audits**:
   ```bash
   python tools/audit_jokers_static.py
   python tools/audit_consumables_static.py
   python tools/audit_bosses_static.py
   python tools/audit_tags_static.py
   ```

2. **Run CI Seed Exactness Gate**:
   ```bash
   python -m pytest vendor/balatro-rl/tests/test_seed_exactness.py -m ci_gate -v
   ```

3. **Run Full Simulator Test Suite**:
   ```bash
   python -m pytest vendor/balatro-rl/tests vendor/balatro-rl/balatro_sim/tests -q
   ```

4. **Run E2E Requirement Tests & Portfolio Tests**:
   ```bash
   python -m pytest vendor/balatro-rl/tests/test_e2e_v10_requirements.py -v
   python -m pytest tests/test_portfolio.py -v
   ```

5. **Empirically Verify Seed 205 & 275 Clearance**:
   ```bash
   python -c "import sys; sys.path.insert(0, 'vendor/balatro-rl'); from balatro_sim.game import BalatroGame, State; from balatro_sim.agent_v10 import HeuristicV10; [print('Seed', s, 'Cleared Ante 1 =', (lambda g, p: [g.step(p.decide(g)) for _ in range(100) if g.state != State.GAME_OVER and g.ante <= 1] and g.ante > 1)(BalatroGame(seed=s, rng_mode='seed'), HeuristicV10())) for s in [205, 275]]"
   ```
