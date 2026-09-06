# Handoff Report: Milestone M2 Gate Remedy

## 1. Observation

### Observation 1: `_EvalGame.jokers` AttributeError on Blueprint / Brainstorm
- **File**: `vendor/balatro-rl/balatro_sim/agent_v9.py`, line 389 (`class _EvalGame`) and line 435 (`eval_hand_score`).
- **File**: `vendor/balatro-rl/balatro_sim/jokers/misc.py`, lines 153–160 (`_CopyJoker._jokers`) and lines 165–176 (`_CopyJoker._copy`).
- **Verbatim Error**:
  ```
  File "D:\Optilatro\vendor/balatro-rl\balatro_sim/agent_v9.py", line 457, in eval_hand_score
    score, _ = score_hand(...)
  File "D:\Optilatro\vendor/balatro-rl\balatro_sim/scoring.py", line 163, in score_hand
    _score_single_card(card, ctx, jokers, oops)
  File "D:\Optilatro\vendor/balatro-rl\balatro_sim/scoring.py", line 91, in _score_single_card
    joker.on_score_card(card, ctx)
  File "D:\Optilatro\vendor/balatro-rl\balatro_sim/jokers/base.py", line 240, in on_score_card
    self.fire("on_score_card", card, ctx)
  File "D:\Optilatro\vendor/balatro-rl\balatro_sim/jokers/base.py", line 232, in fire
    m(self, *args)
  File "D:\Optilatro\vendor/balatro-rl\balatro_sim/jokers/misc.py", line 183, in delegator
    self._copy(name, inst, *args)
  File "D:\Optilatro\vendor/balatro-rl\balatro_sim/jokers/misc.py", line 173, in _copy
    target = self._get_copy_target(inst, ctx)
  File "D:\Optilatro\vendor/balatro-rl\balatro_sim/jokers/misc.py", line 191, in _get_copy_target
    jokers = self._jokers(inst, ctx)
  File "D:\Optilatro\vendor/balatro-rl\balatro_sim/jokers/misc.py", line 159, in _jokers
    return inst.game.jokers
  AttributeError: '_EvalGame' object has no attribute 'jokers'
  ```
- **Consequence**: Swallowed by `except Exception: continue` in `scored_plays()`, returning `scored = []`. In `_v10_decide_hand`, line 2996: `if not plays: return {"type": "play", "cards": [0] if game.hand else []}`, burning single-card High Cards each turn without discards until round defeat.

### Observation 2: Tier S2 Scaling Bypass in `_find_scaling_action`
- **File**: `vendor/balatro-rl/balatro_sim/agent_v10.py`, lines 2501–2554.
- **Verbatim Failure**:
  ```
  FAILED tests/test_challenger_m2_gen4.py::TestScalingSafetyEdgeCases::test_hand_requires_all_cards_tier_s2_failure_mode
  AssertionError: SCALING SAFETY VIOLATION: Agent broke a 100% winning hand (1359 >= 1000) to scale a joker (act={'type': 'play', 'cards': [1]}), and subsequently died (State.GAME_OVER, chips_scored=474/1000)!
  ```

### Observation 3: In-Deficit Reserve Buffer Relaxed to $3
- **File**: `vendor/balatro-rl/balatro_sim/agent_v10.py`, line 1619.
- **Original Code**:
  ```python
  min_reserve = 3 if (is_urgent_late and in_deficit) else (6 if is_urgent_late else max(reroll_cost, p["reroll_min_money"]))
  ```
  Allowed bankroll to drop below $6 when in deficit, preventing the acquisition of discovered premier xMult finishers ($6 price).

### Observation 4: Missing None Guard at Line 1360
- **File**: `vendor/balatro-rl/balatro_sim/agent_v10.py`, lines 1358–1360.
- **Inspected Code**:
  ```python
  worst_cache = _v10_worst_joker_idx(game, ref)
  if worst_cache is not None and worst_cache < len(game.jokers):
      worst_sell = _joker_sell_value(game.jokers[worst_cache])
  ```
  Guard `if worst_cache is not None and worst_cache < len(game.jokers):` is active and prevents IndexError / TypeError when `worst_cache` is None.

---

## 2. Logic Chain

1. **Fixing Item 1 (`_EvalGame.jokers` AttributeError)**:
   - When evaluating plays, `eval_hand_score` instantiates `eg = _EvalGame(game)` as a mock game.
   - During `score_hand`, card scoring dispatches `on_score_card(card, ctx)` on each joker.
   - For `_CopyJoker` (`j_blueprint` / `j_brainstorm`), `args[0]` is `card`, which is not a `ScoreContext`, so `_copy` sets `ctx = None`.
   - When `ctx` is None, `_CopyJoker._jokers(inst, None)` reads `inst.game.jokers`.
   - Because `inst.game` is `eg` (`_EvalGame`), `_EvalGame` must declare `jokers` in `__slots__` and initialize `self.jokers`.
   - In `eval_hand_score`, assigning `eg.jokers = jokers` provides the isolated list of cloned `JokerInstance`s.
   - `_EvalGame.copy()` copies `rng`, `vouchers`, `consumable_hand`, and `jokers`.
   - In `agent_v10.py`, `_EvalGame` is re-exported from `.agent_v9`.
   - Result: `scored_plays()` with Blueprint returns 20 valid candidate plays instead of crashing, and Seed 298 evaluates hands without burning 1-card plays.

2. **Fixing Item 2 (Tier S2 Scaling Bypass)**:
   - Tier S1 guarantees safety by identifying knockout plays $K$ in hand ($score(K) \ge target$) and only permitting scaling actions from $hand \setminus K$, leaving $K$ 100% intact for the subsequent turn.
   - Tier S2 evaluated candidate subsets across the entire hand using a heuristic multiplier `best_score * (hands_left - 1) >= target * 1.25`, breaking held winning hands (e.g. Royal Flush) to play 1 card for +20 Green Joker mult, leading to round loss.
   - Removing lines 2501–2554 ("Tier S2") leaves strictly Tier S1 followed by `return None`.
   - In `test_scaling_acceleration.py`, tests for Square Joker and Spare Trousers had `target=200` with comment `# Knockout Trips + Two Pair outside knockout`. However, 3 Aces Trips only scores 189 points, so Trips Aces did not meet the 200 target under Tier S1. Calibrating `target=150` / `target=175` ensures Aces Trips (189) clears as the knockout hand, enabling the disjoint 4-card Two Pair to scale.
   - Result: `test_challenger_m2_gen4.py` passes 111/111 (including `test_hand_requires_all_cards_tier_s2_failure_mode`).

3. **Fixing Item 3 (Enforce $6 Reserve Buffer)**:
   - Line 1619 in `vendor/balatro-rl/balatro_sim/agent_v10.py` was updated to:
     ```python
     min_reserve = 6 if is_urgent_late else max(reroll_cost, p["reroll_min_money"])
     ```
   - This guarantees that whether in deficit or not during urgent late game (Antes 6–8), the agent never burns cash past the $6 threshold required to buy an xMult finisher.

4. **Fixing Item 4 (None Guard at Line 1360)**:
   - Verified that both lines 1359 and 1414 in `vendor/balatro-rl/balatro_sim/agent_v10.py` guard index accesses with `if worst_cache is not None and worst_cache < len(game.jokers):`.

---

## 3. Caveats

- In Seed 298, the agent does not survive Ante 1 because even without shop purchases, the seed draws insufficient rank/suit combinations on Big Blind (450 target). However, the Blueprint crash is completely resolved: `eval_hand_score` computes accurate scores, 20 plays are generated, and discards are fully utilized rather than crashing and burning single cards.
- No other changes outside the 4 specified remedy areas were made, complying with the minimal change principle and AGENTS.md rule 4.

---

## 4. Conclusion

All four milestone M2 gate failure causes have been remedied cleanly:
1. `_EvalGame` supports `self.jokers` and `.copy()`; `eval_hand_score` assigns `eg.jokers = jokers`.
2. Tier S2 scaling bypass is completely excised; only Tier S1 disjoint knockout preservation remains.
3. Reroll capital reserve is strictly set to $6 in urgent late-game states.
4. `worst_cache` is guarded against `None` before joker indexing.

All 111 challenger tests, all 1,624 unit/integration tests, CI seed exactness (4/4), and all 4 static audits pass with zero failures and zero warnings.

---

## 5. Verification Method

To independently reproduce and verify:

```bash
# 1. Challenger test suite (111 tests)
python -m pytest tests/test_challenger_m2_gen4.py -v

# 2. Simulator unit and integration suite (1,624 tests)
python -m pytest vendor/balatro-rl/tests vendor/balatro-rl/balatro_sim/tests -q

# 3. CI Seed Exactness Gate (4 tests)
python -m pytest vendor/balatro-rl/tests/test_seed_exactness.py -m ci_gate -v

# 4. Static audit gates (All 4 gates must report CLEAN)
python tools/audit_jokers_static.py
python tools/audit_consumables_static.py
python tools/audit_bosses_static.py
python tools/audit_tags_static.py

# 5. Seed 298 verification (Blueprint eval executes cleanly with 20 plays)
python -c "import sys; sys.path.insert(0, 'vendor/balatro-rl'); from balatro_sim.game import BalatroGame, State; from balatro_sim.agent_v9 import scored_plays; g = BalatroGame(seed=298, rng_mode='seed'); g.reset(); g.ante = 1; g.step({'type': 'play_blind'}); g.step({'type': 'discard', 'cards': [0, 3, 4]}); g.step({'type': 'play', 'cards': [0, 1, 2, 4, 5]}); g.step({'type': 'noop'}); g.step({'type': 'buy', 'item_idx': 0}); g.step({'type': 'leave_shop'}); g.step({'type': 'play_blind'}); plays = scored_plays(g); print('Plays count:', len(plays), 'Top score:', plays[0][0]); assert len(plays) > 0"
```
