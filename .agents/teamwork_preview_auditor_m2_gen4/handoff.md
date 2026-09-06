# Forensic Integrity Audit Report

**Work Product**: `vendor/balatro-rl/balatro_sim/agent_v10.py`, `tools/portfolio.py`
**Auditor**: `teamwork_preview_auditor_m2_gen4`
**Profile**: General Project (Integrity mode: development from `ORIGINAL_REQUEST.md`)
**Verdict**: **CLEAN**

---

## 1. Observation

### 1.1 Source Code Static Inspection
- **Target Files**:
  - `vendor/balatro-rl/balatro_sim/agent_v10.py` (3,433 lines)
  - `tools/portfolio.py` (678 lines)
- **Check 1: Hardcoded Seeds (`seed ==`, `seed in`, `.seed`, etc.)**:
  - Search command: `grep_search` regex `\bseed\b`, `\.(seed|run_seed|_seed)\b`, and `\b(205|275)\b`.
  - Observation:
    - `agent_v10.py:22`: comment `draw-order peek) and side-effect-free on the live game (throwaway seed-0 RNG,`
    - `agent_v10.py:544`: comment `# No pair to start — keep highest rank as seed for trips`
    - `agent_v10.py:3027`: comment `# Rate sanity gate: P(clear) reads 1.000 on doomed boards (seed 87`
    - No code conditional branches on seed value exist.
    - Fatal seeds 205 and 275 do NOT appear anywhere in the codebase.
- **Check 2: Test-Specific Branching or Cheating Logic**:
  - Search command: `grep_search` regex `\b(pytest|unittest|environ|getenv)\b`.
  - Observation: 0 matches found in `agent_v10.py` and `tools/portfolio.py`.
- **Check 3: Deck Draw Order Peeking**:
  - Search command: `grep_search` regex `(\bdeck\[|\.draw_deck|\bdeck\.pop)`.
  - Observation:
    - Line 2251: `g2.deck[-refill:] = _keys_to_cards(samp) # pop() = tail` inside `_v10_sampled_pick`.
    - This occurs on a deepcopied game `g2 = _copy.deepcopy(game)`. Future draws on `g2` are replaced with samples drawn from `multiset = _value_multiset(game.deck)` using a throwaway deterministic `rng = random.Random(0)`.
    - Deck access in `agent_v10.py` and `tools/portfolio.py` only reads multiset card frequencies and composition counts (e.g. `len(game.deck)`, counting face cards, suits, and enhancements).
    - Zero peeking at live game draw order.
- **Check 4: Run RNG Stream Consumption**:
  - Search command: `grep_search` regex `\b(random|rng|seed_rng|LuaRandom|game\.rng)\b`.
  - Observation:
    - `agent_v10.py:2055`: `rng = random.Random(0)` (isolated evaluation)
    - `agent_v10.py:2196`: `rng = random.Random(0)` (isolated evaluation)
    - Neither `game.rng` nor LuaRandom streams are touched or consumed.
- **Check 5: Live Game State Mutation During Evaluation**:
  - Observation:
    - `formulate_counterfactual_state(game, action)` (lines 3078–3223) constructs a purely synthetic feature dictionary using primitive values without altering `game` state.
    - `_find_scaling_action` (lines 2407–2580) uses `eval_hand_score` to score candidate combinations without modifying the live game.
    - Deepcopies (`_copy.deepcopy(game)`) are used for rollout continuations in `_v10_sampled_pick`.

### 1.2 Test Suite Execution Output
- **CI Seed Exactness Gate**:
  - Command: `python -m pytest vendor/balatro-rl/tests/test_seed_exactness.py -m ci_gate -v`
  - Output:
    ```
    vendor\balatro-rl\tests\test_seed_exactness.py::TestCrossProcessShaStability::test_sha_identical_across_processes_and_hashseeds PASSED [ 25%]
    vendor\balatro-rl\tests\test_seed_exactness.py::TestCrossProcessShaStability::test_sha_matches_in_process_reference PASSED [ 50%]
    vendor\balatro-rl\tests\test_seed_exactness.py::TestCrossProcessShaStability::test_gate_discriminates_seeds PASSED [ 75%]
    vendor\balatro-rl\tests\test_seed_exactness.py::TestCrossProcessShaStability::test_gate_discriminates_steps PASSED [100%]

    ============================== 4 passed in 8.64s ==============================
    ```
- **Static Audit 1: Jokers**:
  - Command: `python tools/audit_jokers_static.py`
  - Output:
    ```
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
- **Static Audit 2: Consumables**:
  - Command: `python tools/audit_consumables_static.py`
  - Output:
    ```
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
- **Static Audit 3: Bosses**:
  - Command: `python tools/audit_bosses_static.py`
  - Output:
    ```
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
- **Static Audit 4: Tags**:
  - Command: `python tools/audit_tags_static.py`
  - Output:
    ```
    tag spec: 24 tags, 9 ante-2 gated, packs 5
    NAMES    0
    COUNTS   0
    ANTE     0
    EFFECT   0
    WIRED    0
    GATES: CLEAN
    ```
- **V10 Unit & Integration Suite**:
  - Command: `python -m pytest vendor/balatro-rl/tests/test_agent_v10.py vendor/balatro-rl/tests/test_scaling_acceleration.py vendor/balatro-rl/tests/test_e2e_v10_requirements.py vendor/balatro-rl/tests/test_m13_ante1.py -q`
  - Output: `118 passed in 233.66s (0:03:53)`

---

## 2. Logic Chain

1. **Adherence to Ground-Truth Constraints (`ORIGINAL_REQUEST.md`)**:
   - `ORIGINAL_REQUEST.md` specifies `development` integrity mode and strict human-fair constraints (zero peeking at draw order, zero future RNG consumption, zero live game mutation).
2. **Verification of Absence of Cheating Logic**:
   - The regex searches confirm no hardcoded seed IDs or test environment checks exist in `agent_v10.py` or `tools/portfolio.py`. Decisions are computed purely from visible state features (cash, hands left, shop cards, visible boss, deck composition multiset).
3. **Verification of RNG Stream Isolation**:
   - Where hypothetical simulations occur (such as `_v10_sampled_pick`), a private `random.Random(0)` instance is used to draw cards from the deck's multiset, replacing the tail of a deepcopied game's deck. The live game's per-node LuaRandom stream is never queried or perturbed.
   - The passing of `test_seed_exactness.py` (4/4 passed) proves that the game RNG streams remain byte-exact and unaffected across processes and steps.
4. **Verification of Non-Mutating State Projection**:
   - `formulate_counterfactual_state` computes the resulting state representation entirely through integer/string dictionary transformations.
   - Live hand scoring utilizes `eval_hand_score`, preserving the state of jokers and cards.
5. **Robustness and Static Audit Compliance**:
   - All 4 static audit scripts executed and reported `GATES: CLEAN` (0 dupes, 0 dead code, 0 stubs, 0 gaps, 0 type/sig errors, 0 unregistered effects).
   - 118 unit and integration tests across the V10 test suite passed cleanly.

---

## 3. Caveats

- **Out-of-Blind Holdout Bank Performance**: This audit evaluates the codebase for forensic integrity, zero-cheat compliance, and unit/static gate exactness. Paired A/B win-rate benchmarks on Seeds 0–299 and out-of-sample Seeds 300–499 are tracked and verified by the designated benchmark challenger agents.

---

## 4. Conclusion

**Verdict: CLEAN**

The implementation in `vendor/balatro-rl/balatro_sim/agent_v10.py` and `tools/portfolio.py`:
- Contains NO hardcoded seeds or test-specific branches.
- Respects human-fair visibility constraints with zero deck draw order peeking.
- Operates with complete RNG isolation and zero live game mutation.
- Conforms fully to all four static audits and passes the CI seed exactness gate.

The work product is approved without integrity violations.

---

## 5. Verification Method

To independently verify this audit:
```bash
# 1. Verify CI seed exactness
python -m pytest vendor/balatro-rl/tests/test_seed_exactness.py -m ci_gate -v

# 2. Verify all 4 static audits
python tools/audit_jokers_static.py
python tools/audit_consumables_static.py
python tools/audit_bosses_static.py
python tools/audit_tags_static.py

# 3. Verify V10 test suite
python -m pytest vendor/balatro-rl/tests/test_agent_v10.py vendor/balatro-rl/tests/test_scaling_acceleration.py vendor/balatro-rl/tests/test_e2e_v10_requirements.py vendor/balatro-rl/tests/test_m13_ante1.py -q
```
