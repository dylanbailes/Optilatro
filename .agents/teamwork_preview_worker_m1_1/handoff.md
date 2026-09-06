# M1 Handoff Report: Ante-1 In-Blind Multi-Hand Pace Rule (R1)

**Author**: teamwork_preview_worker_m1_1  
**Target Milestone**: Milestone 1 (R1: Ante-1 In-Blind Multi-Hand Pace Rule)  
**Date**: 2026-09-02T21:51:00Z  

---

## 1. Observation

### 1.1 Code Modifications in `V10_DEFAULTS`
In `vendor/balatro-rl/balatro_sim/agent_v10.py` (line 108), `V10_DEFAULTS` was configured to enable `"ante1_pace_rule": True`:

```python
# vendor/balatro-rl/balatro_sim/agent_v10.py
V10_DEFAULTS = {
    ...
    "ante1_pace_rule": True,        # multi-hand budget rule at ante 1: if best
                                   # play >= remaining_target / hands_left, play
                                   # immediately instead of gambling discards on
                                   # thin structural upgrades
    "ante1_pace_mult": 1.0,         # pace multiplier: 1.0 = exactly on pace
    ...
}
```

Implementation in `_tier1_survive` (lines 1725–1729):
```python
    if (V10_PARAMS.get("ante1_pace_rule", False) and game.ante == 1
            and V10_PARAMS["farm_clear_threshold"] < 1.0):
        pace = (target / max(1, game.hands_left)) * V10_PARAMS.get("ante1_pace_mult", 1.0)
        if best_score >= pace:
            return {"type": "play", "cards": list(best_combo)}
```

### 1.2 Fatal Seed 205 & 275 Clearance Verification
Execution of `HeuristicV10(params={'ante1_pace_rule': False})` vs `HeuristicV10(params={'ante1_pace_rule': True})` (and default `HeuristicV10()`) and `SearchShopV10()` across Ante 1:

```text
Seed 205 pace_rule=False Cleared Ante 1 = False Final Ante = 1 State = State.GAME_OVER
Seed 205 pace_rule=True  Cleared Ante 1 = True  Final Ante = 2 State = State.BLIND_SELECT
Seed 275 pace_rule=False Cleared Ante 1 = False Final Ante = 1 State = State.GAME_OVER
Seed 275 pace_rule=True  Cleared Ante 1 = True  Final Ante = 2 State = State.BLIND_SELECT
SearchShopV10 Seed 205 Cleared Ante 1 = True Final Ante = 2 State = State.BLIND_SELECT
SearchShopV10 Seed 275 Cleared Ante 1 = True Final Ante = 2 State = State.BLIND_SELECT
```

### 1.3 Unit Test Enhancements
4 new unit tests were added to `vendor/balatro-rl/tests/test_agent_v10.py` in class `TestAnte1PaceRule`:
- `test_default_config_enabled`: Verifies `V10_DEFAULTS["ante1_pace_rule"] is True`.
- `test_pace_triggers_immediate_play`: Verifies that at Ante 1 Small Blind (target 300, 4 hands, 75 pace), a 100-chip hand plays immediately without discarding.
- `test_below_pace_discards_normally`: Verifies that when best play is 40 on 75 pace, normal discard logic fires.
- `test_fatal_seeds_clear_ante1`: Ensures deterministic clearance of fatal seeds 205 and 275 under `HeuristicV10()` without external overrides.

### 1.4 Verification Commands & Results
1. **Static Audits**:
   - `python tools/audit_jokers_static.py`
   - `python tools/audit_consumables_static.py`
   - `python tools/audit_bosses_static.py`
   - `python tools/audit_tags_static.py`
   - **Result**: All 4 audit gates report `GATES: CLEAN` (Exit code 0).
2. **CI Seed Exactness Gate**:
   - `python -m pytest vendor/balatro-rl/tests/test_seed_exactness.py -m ci_gate -v`
   - **Result**: `4 passed in 5.17s` (Exit code 0).
3. **V10 Unit Tests**:
   - `python -m pytest vendor/balatro-rl/tests/test_agent_v10.py -v`
   - **Result**: `46 passed in 22.79s` (Exit code 0).
4. **Full Test Suite**:
   - `python -m pytest vendor/balatro-rl/tests vendor/balatro-rl/balatro_sim/tests -q`
   - **Result**: `1566 passed, 3 skipped, 4 deselected in 129.34s (0:02:09)` (Exit code 0).

---

## 2. Logic Chain
1. **Ante-1 Small Blind Budget**: On Red Deck / White Stake Pre-Blind 1 (100% base deck, 0 jokers, target=300, 4 hands, 3 discards), clearing the blind requires an average of 75 chips per hand (`300 / 4 = 75`).
2. **Farsighted Discard Burning Bug**: Under v9 baseline and unconfigured v10, `discard_play_good_hand` requires `best_score >= 0.50 * target` (150 chips). Standard Two Pairs (scoring 75-120 chips) fail this threshold (`120 < 150`). The agent burns all 3 discards attempting low-probability 5-card upgrades (Full Houses/Flushes) and exhausts hands, resulting in game over on fatal seeds 205 and 275.
3. **Pace Rule Mechanism**: The pace rule evaluates `pace = (target / max(1, game.hands_left)) * pace_mult`. When a Two Pair or Three of a Kind meets or exceeds this requirement (e.g. `100 >= 75`), it plays immediately, banking chips while preserving all discards for subsequent hands.
4. **Default Enablement & Backwards Compatibility**: Enabling `ante1_pace_rule` in `V10_DEFAULTS` makes this behavior standard for all V10 agents (`HeuristicV10`, `SearchShopV10`). Under `farm_clear_threshold >= 1.0` (V9 parity mode), the rule is disabled via the `farm_clear_threshold < 1.0` guard, ensuring zero regression against the baseline.
5. **Integrity Compliance**: No cheating, no lookahead, no dependency changes, no mutation of `agent_v9.py`.

---

## 3. Caveats
No caveats. The change is isolated to `agent_v10.py` and covered by comprehensive unit tests.

---

## 4. Conclusion
Milestone 1 (Requirement R1) is successfully completed and verified:
1. `ante1_pace_rule` is enabled by default in `V10_DEFAULTS` in `agent_v10.py`.
2. Fatal seeds 205 and 275 clear Ante 1 Small Blind cleanly under human-fair constraints.
3. All 1,566 unit tests, 4 static audits, and the CI seed exactness gate pass with 100% clean status.

---

## 5. Verification Method

### 5.1 Seed 205 & 275 Deterministic Clearance
```powershell
python -c "import sys; sys.path.insert(0, 'vendor/balatro-rl'); from balatro_sim.game import BalatroGame, State; from balatro_sim.agent_v10 import HeuristicV10; [print('Seed', s, 'Cleared Ante 1 =', (lambda g, p: [g.step(p.decide(g)) for _ in range(100) if g.state != State.GAME_OVER and g.ante <= 1] and g.ante > 1)(BalatroGame(seed=s, rng_mode='seed'), HeuristicV10())) for s in [205, 275]]"
```
Expected output:
```text
Seed 205 Cleared Ante 1 = True
Seed 275 Cleared Ante 1 = True
```

### 5.2 CI Seed Exactness Gate
```powershell
python -m pytest vendor/balatro-rl/tests/test_seed_exactness.py -m ci_gate -v
```

### 5.3 Static Audits
```powershell
python tools/audit_jokers_static.py
python tools/audit_consumables_static.py
python tools/audit_bosses_static.py
python tools/audit_tags_static.py
```

### 5.4 Full Test Suite
```powershell
python -m pytest vendor/balatro-rl/tests vendor/balatro-rl/balatro_sim/tests -q
```
