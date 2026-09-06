# Code Review & Adversarial Analysis: `vendor/balatro-rl/balatro_sim/agent_v10.py`

**Verdict**: REQUEST_CHANGES

---

## 1. Observation

### Obs 1: `_find_scaling_action` Contains Active Tier S2 Fallback That Breaks Guaranteed Winning Hands
- **Location**: `vendor/balatro-rl/balatro_sim/agent_v10.py`, lines 2407–2554.
- **Docstring Contract** (lines 2414–2417):
  ```python
  - Strict Tier S1 disjoint in-hand knockout reservation ONLY:
    There MUST exist a valid clearing combination K in hand (score(K) >= target),
    and candidate scaling play C must be a disjoint subset of hand \ K so K remains
    100% intact in hand for the next turn.
  ```
- **Observed Implementation** (lines 2501–2520):
  ```python
  # Tier S2: Overwhelming margin across remaining hands (loose probabilistic p_clear removed)
  best_score = plays[0][0] if plays else 0
  if best_score * (game.hands_left - 1) >= target * 1.25:
      candidates = []
      for r in (1, 2, 4, 5):
          if r > len(hand):
              continue
          for combo in combinations(range(len(hand)), r):
              cards_c = [hand[i] for i in combo]
              ht_c, sc_c = evaluate_hand(cards_c)
              held_c = [c for i, c in enumerate(hand) if i not in set(combo)]
              score = eval_hand_score(game, ht_c, sc_c, cards_c, held_cards=held_c)
              if score >= target:
                  continue
              if has_bus and any(c.is_face_card for c in sc_c if not getattr(c, "debuffed", False)):
                  continue
  ```
- **Adversarial Reproduction**:
  Executed test scenario with a 5-card non-face Flush (`[2S, 4S, 6S, 8S, 10S]`) as the sole clearing play (Flush score = 325, target = 120, hands_left = 3, jokers = `[j_green_joker]`):
  ```python
  act = v10._find_scaling_action(g, g.hand, plays, 1.0)
  # Output: {'type': 'play', 'cards': [0]}
  ```
  Tier S1 found no disjoint candidates outside the 5-card Flush (`non_k_indices = []`). Execution fell through to Tier S2, which selected `cards: [0]` (2 of Spades). Playing this card permanently fractures the 5-card Flush, leaving only 4 Spades in hand and forfeiting the guaranteed victory.

### Obs 2: `min_reserve` in `_v10_decide_shop` Relaxes to $3 During Deficit
- **Location**: `vendor/balatro-rl/balatro_sim/agent_v10.py`, line 1619:
  ```python
  min_reserve = 3 if (is_urgent_late and in_deficit) else (6 if is_urgent_late else max(reroll_cost, p["reroll_min_money"]))
  ```
- **Specification Contract**: `PROJECT.md` Key Subsystems 1 & F3:
  `allow up to 10 rerolls in Ante 8, 6 in Ante 7, 4 in Ante 6 if remaining cash + worst joker sell >= $6.`
- **Discrepancy**: When in a scoring deficit (`in_deficit = True`), `min_reserve` is dropped to $3. Premier xMult finishers and high-leverage scoring jokers (Cavendish $4, Trio/Family $7–$8, Baseball Card $8, Blueprint/Brainstorm $10) cost between $4 and $10. Setting the reserve to $3 permits rerolling down to $3 total purchasing power, rendering the agent unable to afford newly revealed premier finishers.

### Obs 3: Missing `None` Guard on `worst_cache` in `_v10_rank_shop_items`
- **Location**: `vendor/balatro-rl/balatro_sim/agent_v10.py`, lines 1358–1360:
  ```python
  if slots_full and game.jokers:
      worst_cache = _v10_worst_joker_idx(game, ref)
      worst_sell = _joker_sell_value(game.jokers[worst_cache])
  ```
- **Comparison with guarded call sites**:
  - Line 1414: `if worst_cache is not None and worst_cache < len(game.jokers):`
  - Line 1613: `if w_idx is not None and w_idx < len(game.jokers):`
- When `_v10_worst_joker_idx` returns `None` (possible when all owned jokers are protected, e.g. line 458), indexing `game.jokers[None]` raises `TypeError: list indices must be integers or slices, not NoneType`.

### Obs 4: Verified `tier2_value` Discard Guard
- **Location**: `vendor/balatro-rl/balatro_sim/agent_v10.py`, line 2860:
  ```python
  # ── Discard candidates ─────────────────────────────────────────────────
  if game.discards_left > 0:
      for dcombo, committed in _value_discard_candidates(game, hand):
  ```
- When `game.discards_left <= 0`, no discard candidates are populated in `candidates`. All discard branches in `_tier1_survive` (lines 2608, 2642, 2659) also verify `game.discards_left > 0`. This eliminates infinite discard loops / deadlocks when holding discard-trigger jokers (`j_faceless`, `j_castle`, `j_green_joker`, `j_mail`, `j_trading`).

### Obs 5: Verified Blueprint / Brainstorm Valuation
- **Location**: `vendor/balatro-rl/balatro_sim/agent_v10.py`, lines 1370–1373:
  ```python
  value = joker_value(game, item.key, item.edition, ref, surplus)
  if item.key in ("j_blueprint", "j_brainstorm"):
      # Handle simulator _EvalGame AttributeError and properly value premier copy jokers
      value = max(value, 1.5)
  ```
- Verified that `joker_value(game, 'j_blueprint', None)` and `joker_value(game, 'j_brainstorm', None)` execute cleanly without exceptions. The floor `max(value, 1.5)` successfully prevents copy jokers from falling below the purchase threshold due to lack of a rightward neighbor during evaluation.

### Obs 6: Verified Test Suites and Audits
- **Pytest Suite**:
  Command: `python -m pytest vendor/balatro-rl/tests vendor/balatro-rl/balatro_sim/tests -q`
  Result: `1624 passed, 3 skipped, 4 deselected in 463.99s (0:07:43)` — 100% green.
- **CI Seed Exactness Gate**:
  Command: `python -m pytest vendor/balatro-rl/tests/test_seed_exactness.py -m ci_gate -v`
  Result: `4 passed in 41.83s` — 100% green.
- **Static Audits**:
  - `python tools/audit_jokers_static.py`: GATES: CLEAN.
  - `python tools/audit_consumables_static.py`: GATES: CLEAN.
  - `python tools/audit_bosses_static.py`: GATES: CLEAN.
  - `python tools/audit_tags_static.py`: GATES: CLEAN.

---

## 2. Logic Chain

1. **Premise 1**: The user request and interface contract mandate that scaling plays in `_find_scaling_action` be strictly limited to Tier S1 deterministic in-hand knockout reservations (Obs 1).
2. **Premise 2**: In `agent_v10.py`, lines 2501–2554 implement Tier S2 fallback logic that generates non-disjoint plays from all cards in hand whenever Tier S1 produces no candidate (Obs 1).
3. **Inference 1**: When a player holds a guaranteed winning hand (such as a 5-card Flush or 5-card Straight) that utilizes all or most of the cards in hand, Tier S1 has no available disjoint cards and yields no candidates. Tier S2 then selects a card from within the winning hand to trigger a minor scaling increment (e.g. +1 Mult on Green Joker).
4. **Inference 2**: Executing this scaling play breaks the winning hand combination. The player is forced to redraw, converting a 100% deterministic victory into a stochastic gamble, introducing unnecessary round loss risks.
5. **Premise 3**: The user request and `PROJECT.md` require maintaining a $6 purchase reserve buffer during late-game urgent rerolls (Obs 2).
6. **Inference 3**: Dropping `min_reserve` to $3 allows the policy to spend down below the purchase price of premier scoring jokers ($4–$10), causing the agent to uncover unpurchasable jokers and waste capital.
7. **Premise 4**: Defensively guarded code must handle `None` returns from index lookups. Line 1360 lacks the check present in lines 1414 and 1613, leaving an unhandled `TypeError` risk if all owned jokers are protected (Obs 3).
8. **Conclusion**: While test suites and static audits are green, the presence of active Tier S2 in `_find_scaling_action` violates the deterministic survival invariant and can cause fatal throws in safe blinds. Therefore, the verdict must be REQUEST_CHANGES.

---

## 3. Caveats

- The entire 1,624-test suite, 4/4 CI seed exactness tests, and all 4 static audits are currently passing. This indicates that current unit tests only assert that Tier S1 works when disjoint cards exist, without exercising the adversarial failure mode where Tier S2 breaks a tight 5-card clearing hand.
- No integrity violations (hardcoded test answers, fake mock stubs, or unauthorized RNG peeking) were detected. The issues found are logic bugs and incomplete refactorings.

---

## 4. Conclusion

**Verdict: REQUEST_CHANGES**

### Actionable Required Changes:
1. **[Critical] Remove or Disable Tier S2 in `_find_scaling_action`**:
   - In `vendor/balatro-rl/balatro_sim/agent_v10.py`, remove lines 2501–2554 (the entire `Tier S2: Overwhelming margin` block).
   - If Tier S1 cannot find a disjoint combination from `non_k_indices`, `_find_scaling_action` must immediately return `None`.
2. **[Major] Restore Strict $6 Purchase Reserve Buffer in `_v10_decide_shop`**:
   - In `vendor/balatro-rl/balatro_sim/agent_v10.py`, line 1619, change:
     ```python
     min_reserve = 6 if is_urgent_late else max(reroll_cost, p["reroll_min_money"])
     ```
     Do not drop `min_reserve` to $3 during deficit.
3. **[Minor] Add Defensive `worst_cache is not None` Check in `_v10_rank_shop_items`**:
   - In `vendor/balatro-rl/balatro_sim/agent_v10.py`, lines 1358–1360, guard `worst_cache` before indexing:
     ```python
     if slots_full and game.jokers:
         worst_cache = _v10_worst_joker_idx(game, ref)
         if worst_cache is not None and worst_cache < len(game.jokers):
             worst_sell = _joker_sell_value(game.jokers[worst_cache])
     ```

---

## 5. Verification Method

To independently verify these findings and any subsequent fixes:

1. **Adversarial Tier S2 Break Reproduction**:
   Run:
   ```bash
   python -c "import sys; sys.path.insert(0, 'vendor/balatro-rl'); from balatro_sim.card import Card; from balatro_sim.game import BalatroGame, State; from balatro_sim.jokers.base import JokerInstance; from balatro_sim.agent_v9 import scored_plays; from balatro_sim import agent_v10 as v10; g = BalatroGame(seed=42, rng_mode='seed'); g.reset(); g.ante = 2; g.state = State.BLIND_SELECT; g.step({'type': 'play_blind'}); g.hand = [Card(rank=2, suit='Spades'), Card(rank=4, suit='Spades'), Card(rank=6, suit='Spades'), Card(rank=8, suit='Spades'), Card(rank=10, suit='Spades')]; g.hands_left = 3; g.discards_left = 0; g.current_blind.chips_target = 120; g.chips_scored = 0; g.jokers = [JokerInstance('j_green_joker', game=g)]; plays = scored_plays(g); act = v10._find_scaling_action(g, g.hand, plays, 1.0); print('Result:', act)"
   ```
   - Current buggy behavior: returns `{'type': 'play', 'cards': [0]}` (breaks winning flush).
   - Expected fixed behavior: returns `None` (refuses to sacrifice winning flush).

2. **Run Full Test Suite**:
   ```bash
   python -m pytest vendor/balatro-rl/tests vendor/balatro-rl/balatro_sim/tests -q
   ```
   Must yield 1624+ passed.

3. **Run CI Seed Exactness Gate**:
   ```bash
   python -m pytest vendor/balatro-rl/tests/test_seed_exactness.py -m ci_gate -v
   ```
   Must yield 4 passed.

4. **Run 4 Static Audits**:
   ```bash
   python tools/audit_jokers_static.py
   python tools/audit_consumables_static.py
   python tools/audit_bosses_static.py
   python tools/audit_tags_static.py
   ```
   All 4 must report `GATES: CLEAN`.
