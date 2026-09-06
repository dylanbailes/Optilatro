# Handoff Report — Challenger 1 (Adversarial Verification & Stress Testing)

## 1. Observation
- **Inspected Code**:
  - `vendor/balatro-rl/balatro_sim/agent_v10.py`, lines 2824–2840 in `tier2_value`:
    ```python
    # ── Discard candidates ─────────────────────────────────────────────────
    for dcombo, committed in _value_discard_candidates(game, hand):
        if not dcombo:
            continue
        val = _discard_value(game, dcombo)
        if val <= 0.0:
            continue
        if not _guard(game, "discard", dcombo, 0, False, committed,
                      type_scores):
            continue
    ```
    There is no check for `if game.discards_left > 0:` prior to candidate generation.
  - `vendor/balatro-rl/balatro_sim/game.py`, line 1069:
    ```python
    def _discard(self, card_indices: list[int]):
        if self.discards_left <= 0:
            return
    ```
    The engine silently rejects discard actions when `discards_left <= 0`.
- **Empirical Execution & Failures**:
  - Tool command: `python tools/stress_m1_challenger.py`
  - Verbatim failure output:
    ```text
    FOUND 4 FAILURES/ANOMALIES:
      - 2.E [CRITICAL BUG]: tier2_value returned discard action when discards_left == 0! Triggers infinite deadlock loop.
      - Game seed 10001 exceeded max steps (deadlock)! Current state: State.SELECTING_HAND ante: 3 discards_left: 0
      - Game seed 10004 exceeded max steps (deadlock)! Current state: State.SELECTING_HAND ante: 6 discards_left: 0
      - Game seed 10024 exceeded max steps (deadlock)! Current state: State.SELECTING_HAND ante: 4 discards_left: 0
    ```
  - Direct trace on Seed 10001 at step 105:
    - Ante: 3, Target: 4,000, Scored: 2,520, Hands left: 3, Discards left: 0
    - Jokers: `['j_egg', 'j_faceless', 'j_scholar', 'j_popcorn', 'j_raised_fist']`
    - Action returned by `agent_v10`: `{'type': 'discard', 'cards': [1, 2, 4]}`
    - Result: `game.step()` did nothing; state remained frozen; loop repeated until step limit.

## 2. Logic Chain
1. **Observation**: `_value_discard_candidates` identifies 3 face cards for `j_faceless` and assigns +$5 value (0.50 VP).
2. **Observation**: Lines 2824–2840 in `tier2_value` do not verify `game.discards_left > 0`.
3. **Observation**: `_guard` evaluates survival clear probability at `d = game.discards_left - 1 = -1`. In `estimate_clear_probability`, with `h = 3` hands remaining, survival probability evaluates to `1.0 >= abandon_clear_floor`.
4. **Observation**: Because the discard action offers higher value points than available play actions, `tier2_value` returns `{'type': 'discard', 'cards': [1, 2, 4]}` despite having zero discards left.
5. **Observation**: In `game.py:1069`, `BalatroGame._discard` rejects the action with an early return `if self.discards_left <= 0: return`.
6. **Inference**: Hand, deck, score, and state do not change. On the next decision cycle, `agent_v10` emits the identical discard action, entering an unrecoverable infinite loop.
7. **Conclusion**: This is a critical blocker that causes random game freezes during rollouts whenever discard-incentive jokers are owned and discards are exhausted.

## 3. Caveats
- Non-discard scaling acceleration and capital deployment passed all adversarial challenges:
  - Ride the Bus strictly avoids scoring face cards and prefers safe non-face clearing plays.
  - Green Joker discard suppression only activates when `p_clear >= 0.98` (and when discards remain).
  - All 8 banned bosses (`SCALING_BANNED_BOSSES`) strictly suppress scaling.
  - Ante 8 shop terminates cleanly without index errors, and rerolls respect caps.
- The defect is isolated to `tier2_value` lacking a `game.discards_left > 0` check.

## 4. Conclusion
**EXPLICIT VERDICT**: `REJECT`.
Milestone M1 cannot be approved until the `tier2_value` zero-discard deadlock bug is fixed in `vendor/balatro-rl/balatro_sim/agent_v10.py`.

## 5. Verification Method
To independently reproduce:
```bash
# 1. Run adversarial stress testing harness (fails on 2.E and seeds 10001, 10004)
python tools/stress_m1_challenger.py
```
Minimal reproduction script:
```python
from balatro_sim.game import BalatroGame, State
from balatro_sim.agent_v10 import SearchShopV10

g = BalatroGame(seed=10001, rng_mode="seed")
g.reset()
agent = SearchShopV10()
for _ in range(105):
    g.step(agent.decide(g))

assert g.discards_left == 0
act = agent.decide(g)
assert act["type"] != "discard", f"Deadlock: returned discard when discards_left={g.discards_left}"
```
Invalidation conditions:
- `tools/stress_m1_challenger.py` passes with 0 failures and 0 deadlocks across all 25 rollout games.
