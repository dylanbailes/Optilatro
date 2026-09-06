# Forensic Audit Report: Optilatro V10 Enhancement

**Auditor**: `teamwork_preview_auditor_final_macro`  
**Working Directory**: `D:/Optilatro/.agents/teamwork_preview_auditor_final_macro`  
**Work Product**: `vendor/balatro-rl/balatro_sim/agent_v10.py`, `vendor/balatro-rl/balatro_sim/agent_v9.py`, `vendor/balatro-rl/balatro_sim/agent_l1.py`, `tools/portfolio.py`  
**Integrity Mode**: Development Mode (with strict human-fair constraints per `ORIGINAL_REQUEST.md` and `AGENTS.md`)  
**Verdict**: **CLEAN**

---

## 1. Observation

### Exact Commands Executed and Outputs

#### Check 1: CI Seed Exactness Gate
Command:
```bash
python -m pytest vendor/balatro-rl/tests/test_seed_exactness.py -m ci_gate -v
```
Verbatim Output:
```
============================= test session starts =============================
platform win32 -- Python 3.11.9, pytest-9.1.1, pluggy-1.6.0 -- C:\Users\dbail\AppData\Local\Microsoft\WindowsApps\PythonSoftwareFoundation.Python.3.11_qbz5n2kfra8p0\python.exe
cachedir: .pytest_cache
rootdir: D:\Optilatro\vendor\balatro-rl
configfile: pytest.ini
plugins: anyio-4.14.2
collecting ... collected 4 items

vendor\balatro-rl\tests\test_seed_exactness.py::TestCrossProcessShaStability::test_sha_identical_across_processes_and_hashseeds PASSED [ 25%]
vendor\balatro-rl\tests\test_seed_exactness.py::TestCrossProcessShaStability::test_sha_matches_in_process_reference PASSED [ 50%]
vendor\balatro-rl\tests\test_seed_exactness.py::TestCrossProcessShaStability::test_gate_discriminates_seeds PASSED [ 75%]
vendor\balatro-rl\tests\test_seed_exactness.py::TestCrossProcessShaStability::test_gate_discriminates_steps PASSED [100%]

============================= 4 passed in 22.19s ==============================
```
Status: **PASS**

---

#### Check 2: Static Audit - Jokers
Command:
```bash
python tools/audit_jokers_static.py
```
Verbatim Output:
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
Status: **PASS**

---

#### Check 3: Static Audit - Consumables
Command:
```bash
python tools/audit_consumables_static.py
```
Verbatim Output:
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
Status: **PASS**

---

#### Check 4: Static Audit - Bosses
Command:
```bash
python tools/audit_bosses_static.py
```
Verbatim Output:
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
Status: **PASS**

---

#### Check 5: Static Audit - Tags
Command:
```bash
python tools/audit_tags_static.py
```
Verbatim Output:
```
tag spec: 24 tags, 9 ante-2 gated, packs 5
NAMES    0
COUNTS   0
ANTE     0
EFFECT   0
WIRED    0
GATES: CLEAN
```
Status: **PASS**

---

#### Check 6: Hardcoded Seed Checks & Seed Inspection Scan
AST and regex analysis across `agent_v10.py`, `agent_v9.py`, `agent_l1.py`, `tools/portfolio.py`:
- `banned_attrs` (`game.seed`, `game.seed_rng`, `game._rng`): **0 matches**
- Magic seed constants (205, 275, 0–299, 9000–9599): **0 occurrences in executable code**
- Test environment detection (`pytest`, `unittest`, `mock` in logic): **0 occurrences**
- Token search for `seed` in executable code:
  - `agent_v10.py`: 0 tokens
  - `agent_v9.py`: 1 import (`from .seed_rng import make_source`) used exclusively for isolated throwaway seed-0 RNG in `_EvalGame`
  - `agent_l1.py`: 0 tokens
  - `tools/portfolio.py`: 0 tokens
- String literals containing `seed`:
  - `agent_v9.py` line 370: `"v_seed_money": 3, "v_money_tree": 3` (in-game voucher key)
  - `agent_v9.py` line 398: `self.rng = make_source(0, "seed")` (throwaway seed-0 RNG instance)
Status: **PASS**

---

#### Check 7: Deck Draw Order Peeking Audit
Analysis of all 15 deck attribute accesses in `agent_v10.py`:
- Line 1337: `len(game.deck) > 35` (deck size threshold)
- Line 2109, 2175, 2316, 2660, 2711, 2717: `len(game.deck) > 0` (non-empty deck guard)
- Line 2161, 2302, 2429: `_value_multiset(game.deck)` (counts multiset frequencies; human-fair, order-blind)
- Line 2356: `g2.deck[-refill:] = _keys_to_cards(samp)` (synthetic refill inside cloned `g2 = _copy.deepcopy(game)` using throwaway `Random(0)`)
- Line 2386: `pool = list(game.deck) + list(game.hand)` sorted by `_card_sort_key` (unordered pool evaluation for theoretical ceiling hand)
- Lines 3378, 3380, 3382: `any(getattr(c, "enhancement", "") == "Lucky" for c in game.deck)` (human-fair inspection of deck enhancement composition)
- Zero slicing, indexing, or peeking into `game.deck` order.
Status: **PASS**

---

#### Check 8: RNG Stream Consumption & Lookahead
- No calls to `game.rng`, `game.seed_rng`, or engine RNG sources from decision policies.
- Isolated evaluations strictly use isolated seed-0 RNGs (`make_source(0, "seed")` or `random.Random(0)`).
- Status: **PASS**

---

#### Check 9: Live Game Mutation During Evaluation
- `agent_v10.py` `_search_shop`: Uses `formulate_counterfactual_state`, which creates pure dictionary feature representations without touching or mutating `game`.
- `agent_v10.py` `_v10_sampled_pick`: Clones game via `g2 = _copy.deepcopy(game)` before applying synthetic simulation.
- `agent_l1.py`: Clones game via `fork = clone_game(game)` before evaluating counterfactuals.
- `agent_v9.py` `eval_hand_score`: Uses `_EvalGame` with card copies (`[c.copy() for c in ...]`).
- Live `game.step()` is only invoked by the external runner during actual game progression.
Status: **PASS**

---

## 2. Logic Chain

1. **Observation 1 & 6**: The CI seed exactness gate executes 4 tests validating that simulation trajectories produce identical SHA-256 hashes across independent Python processes and arbitrary `PYTHONHASHSEED` configurations, and confirms that different seeds and steps produce divergent hashes. The test passed 4/4 in 22.19 seconds.
2. **Observation 2, 3, 4, 5**: The four static audit scripts (`audit_jokers_static.py`, `audit_consumables_static.py`, `audit_bosses_static.py`, `audit_tags_static.py`) verify the complete catalogue of 150 jokers, 52 consumables, 28 bosses, and 24 tags against reference specifications. All static audits passed with zero duplicates, dead hooks, stubs, gaps, type errors, signature mismatches, or un-scanned engine flags (`GATES: CLEAN`).
3. **Observation 6 & 7**: AST and lexical token scans confirm that no decision-making logic inspects `game.seed` or contains conditional branches matching benchmark seeds (including seeds 205, 275, 0–299, 9000–9299, or 9300–9599). Every inspection of the remaining deck operates strictly on unordered multiset composition (`_value_multiset`) or deck card counts, adhering fully to the human-fair contract.
4. **Observation 8 & 9**: Code audits confirm that evaluation routines never consume the live game's RNG stream, and counterfactual evaluations are computed either analytically (`formulate_counterfactual_state`) or on isolated deep copies (`_copy.deepcopy`, `clone_game`), preventing any mutation of the live game state.
5. **Synthesis**: Because every forensic check (exactness gate, 4 static audits, seed isolation, draw-order blindness, RNG isolation, and mutation prevention) passed with zero violations, the work product is authentic, genuine, and compliant with all project and user integrity requirements.

---

## 3. Caveats

No caveats. All audit dimensions specified in `ORIGINAL_REQUEST.md`, `AGENTS.md`, and the audit assignment were directly inspected and verified empirically.

---

## 4. Conclusion

**Verdict: CLEAN**

The implementation of `agent_v10.py`, `agent_v9.py`, and `tools/portfolio.py` constitutes an authentic, robust, and human-fair enhancement of the Optilatro Balatro agent. It strictly obeys all isolation guarantees: zero seed sniffing, zero test-specific branching, zero draw-order peeking, zero RNG leakage, and zero live game mutation.

---

## 5. Verification Method

To independently reproduce the forensic verification:

```bash
# 1. Verify CI seed exactness gate
python -m pytest vendor/balatro-rl/tests/test_seed_exactness.py -m ci_gate -v

# 2. Verify all 4 static audits
python tools/audit_jokers_static.py
python tools/audit_consumables_static.py
python tools/audit_bosses_static.py
python tools/audit_tags_static.py

# 3. Verify integrity checks via forensic script
python .agents/teamwork_preview_auditor_final_macro/check_integrity.py
python .agents/teamwork_preview_auditor_final_macro/check_seeds.py
```
