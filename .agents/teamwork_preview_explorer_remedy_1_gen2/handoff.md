# Handoff Report — Remedy Explorer 1 (`teamwork_preview_explorer_remedy_1_gen2`)

## Executive Summary
This report provides exact code solutions and verifiable patches for the four issues assigned to Remedy Explorer 1:
1. **Constrained Open-Slot Early Ante Spending**: Prevents `SearchShopV10._search_shop` from purchasing expensive pure xMult jokers (`j_tribe`, `j_order`, `j_baseball`) down to $0 in early antes (Antes 1–2). Enforces an early cash reserve (default $4) and strictly mandates that a flat scoring anchor (`CHIPS_JOKERS` or `FLAT_MULT_JOKERS`) must be held before considering pure xMult acquisitions.
2. **Restoration of `V10_DEFAULTS` & Test Resolution**: Restores `ante1_chip_bias: 0.8` and `ante2_chip_bias: 0.5` in `V10_DEFAULTS`, and resolves `test_m13_ante1.py:95` by scoping a dual-assertion that validates both legacy behavior (Buffoon Pack > Sly Joker under 0.03 bias) and Configuration D behavior (Sly Joker > Buffoon Pack under 0.8 bias).
3. **Infeasible Buy Dangling State Resolution**: Clears `self._pending_swap_target_idx = None` immediately when target evaluation begins, preventing target index dangling when price or room constraints fail.
4. **Accurate Sell Value Lookup**: Replaces non-existent `getattr(j, "sell_cost", ...)` with `getattr(j, "state", {}).get("sell_value", max(1, getattr(j, "cost", 4) // 2))` across all 3 counterfactual valuation sites in `agent_v10.py`.

---

## 1. Observation

### 1.1 Root Cause 1: Open-Slot Counterfactual Early Over-Spending
- **Location**: `vendor/balatro-rl/balatro_sim/agent_v10.py:2840-2861`
- **Observed Code**:
  ```python
  # 2. Open-Slot Counterfactual Evaluation (len(jokers) < joker_slots)
  if len(game.jokers) < game.joker_slots:
      best_buy_delta = swap_threshold
      best_buy_idx = None
      for i, item in enumerate(game.current_shop):
          if item.sold or item.kind != "joker":
              continue
          price = item.discounted_price(game.shop_discount)
          if price > game.dollars:
              continue
          f_buy = formulate_counterfactual_state(game, {"type": "buy", "item_idx": i})
          v_buy = evaluate_shop_value(f_buy)
          delta = v_buy - v_curr
          is_high_leverage = item.key in HIGH_LEVERAGE_SCORING_JOKERS
          thr = 0.000 if is_high_leverage else best_buy_delta
          if delta > thr:
              if delta > best_buy_delta or (is_high_leverage and best_buy_idx is None):
                  best_buy_delta = max(best_buy_delta, delta)
                  best_buy_idx = i

      if best_buy_idx is not None:
          return {"type": "buy", "item_idx": best_buy_idx}
  ```
- **Observed Defects**:
  1. The loop permitted buying any joker whenever `price <= game.dollars`, even if it spent 100% of player cash ($0 remaining).
  2. The offline model weights in `shop_model.json` reward `has_xmult` and `n_xmult` for endgame win probability.
  3. `HIGH_LEVERAGE_SCORING_JOKERS` (`j_cavendish`, `j_baseball`, `j_duo`, `j_trio`, `j_order`, `j_tribe`, `j_family`, `j_ramen`, `j_stuntman`, `j_constellation`) were given a relaxed threshold of `thr = 0.000`.
  4. In Ante 1 and 2, when `j_tribe` ($8), `j_order` ($8), or `j_baseball` ($8) appeared, the agent spent all early capital on pure xMult cards that provide 0 chips and 0 mult on standard opening hands (Pair / Two Pair / High Card).
  5. Challenger 2 recorded the empirical result on Seeds 0–299: Ante 1 deaths surged from 14 to 22 (+8 deaths), 19 baseline-surviving seeds died in Ante 1 (e.g. Seed 30 died on Big Blind holding `j_tribe` scoring only 412/450; Seed 249 died on Small Blind), and mean interest dropped from $15.11 to $8.66 (-42.7%).

### 1.2 Root Cause 2: `V10_DEFAULTS` Configuration D Regression & Unit Test Collision
- **Location**: `vendor/balatro-rl/balatro_sim/agent_v10.py:294-295` and `vendor/balatro-rl/tests/test_m13_ante1.py:79-105`
- **Observed Code in `agent_v10.py`**:
  ```python
  294:     "ante1_chip_bias": 0.03,
  295:     "ante2_chip_bias": 0.0,
  ```
- **Observed Code in `test_m13_ante1.py`**:
  ```python
  79: def test_ante1_buffoon_outranks_sly():
  ...
  94:     # Ante-1: buffoon boosted 0.25+0.20=0.45 > sly 0.41, so buffoon should be top
  95:     assert vals["p_buffoon"] > vals["j_sly"], f"ante1 buffoon should outrank sly: {vals}"
  ```
- **Verbatim Error when `ante1_chip_bias = 0.8`**:
  ```text
  AssertionError: ante1 buffoon should outrank sly: {'j_sly': 1.0099687996805538, 'p_buffoon': 0.45}
  assert 0.45 > 1.0099687996805538
  ```
- **Observed Scope**: All other 92 tests in `test_agent_v10.py` and `test_e2e_v10_requirements.py` pass cleanly under `ante1_chip_bias: 0.8` and `ante2_chip_bias: 0.5`. Only line 95 of `test_m13_ante1.py` asserted that Buffoon Pack must outrank Sly Joker, which was hardcoded under the legacy 0.03 bias.

### 1.3 Root Cause 3: Dangling `_pending_swap_target_idx` on Infeasible Swaps
- **Location**: `vendor/balatro-rl/balatro_sim/agent_v10.py:2941-2952` and `2823-2834`
- **Observed Code**:
  ```python
  if self._pending_swap_target_idx is not None:
      target_i = self._pending_swap_target_idx
      if 0 <= target_i < len(game.current_shop) and not game.current_shop[target_i].sold:
          item = game.current_shop[target_i]
          price = item.discounted_price(game.shop_discount)
          has_room = len(game.jokers) < game.joker_slots or getattr(item, "edition", None) == "Negative"
          if price <= game.dollars and has_room:
              self._pending_swap_target_idx = None
              return {"type": "buy", "item_idx": target_i}
      else:
          self._pending_swap_target_idx = None
  ```
- **Observed Defect**: If `0 <= target_i < len(game.current_shop)` and `not item.sold`, but `not (price <= game.dollars and has_room)`, there is no `else` clause. `self._pending_swap_target_idx` remains set to `target_i`, dangling across actions until shop exit.

### 1.4 Root Cause 4: Sell Value Lookup Bug
- **Location**: `vendor/balatro-rl/balatro_sim/agent_v10.py:2749, 2760, 2897`
- **Observed Code**:
  ```python
  sell_val = getattr(j_inst, "sell_cost", max(1, getattr(j_inst, "cost", 4) // 2))
  ```
- **Observed Defect**: `JokerInstance` objects do not have an attribute `sell_cost`. In `balatro_sim/shop.py:766` and `agent_v9.py:1580`, sell values are stored in `j.state["sell_value"]`. Falling back to `cost // 2` underestimates sell value for scaling economy jokers (e.g. `j_egg` with accumulated sell value).

---

## 2. Logic Chain

1. **Early Survival Hierarchy**:
   - In Balatro White Stake, Ante 1 blind targets are Small: 300, Big: 450, Boss: 600. Base unscored hands without chips/mult jokers yield: High Card (5), Pair (20), Two Pair (40), 3 of a Kind (90).
   - An early flat chips joker (`j_sly`, `j_ice_cream`, `j_banner`, `j_stuntman`) or flat mult joker (`j_half`, `j_popcorn`, `j_gros_michel`) instantly elevates Pair/Two Pair to 120?250+ points per hand, clearing Big and Boss blinds in 2?3 hands.
   - Pure xMult jokers (`j_tribe`, `j_order`, `j_baseball`) multiply base mult. Without flat chips/mult, Two Pair with x2 mult only scores 40 points. Buying an $8 pure xMult joker with no flat scoring anchor leaves the player with $0 cash, 0 flat chips, 0 flat mult, and 0 interest compounding, causing guaranteed mortality on early blinds.
2. **Constrained Open-Slot Counterfactual Evaluation**:
   - By distinguishing `is_early_scoring = item.key in CHIPS_JOKERS or item.key in FLAT_MULT_JOKERS` and `is_pure_xmult = item.key in XMULT_JOKERS and not is_early_scoring`:
     - When `game.ante <= 2` and `not has_flat_scoring`, the policy skips pure xMult purchases. The player MUST establish a flat chips/mult foundation first.
     - When `game.ante <= 2`, any purchase when already holding a scoring anchor (or for non-scoring utility/economy jokers) must preserve an early cash reserve: `game.dollars - price >= early_reserve` (default $4).
     - When `not has_flat_scoring`, spending down to $0 is permitted ONLY for a first flat chips/mult joker (`is_early_scoring`), because having an early flat anchor is essential for surviving the immediate blind.
     - The relaxed threshold `thr = 0.000` is disabled for xMult in early antes unless a flat scoring anchor is already secured.
3. **Parameter Restoration and Test Reconciliation**:
   - Setting `ante1_chip_bias: 0.8` and `ante2_chip_bias: 0.5` in `V10_DEFAULTS` restores the proven Configuration D baseline from `goal_iter7_final_D.json`.
   - In `test_m13_ante1.py::test_ante1_buffoon_outranks_sly`, the test was originally constructed to demonstrate that Buffoon Pack (base 0.25 + 0.20 boost = 0.45) outranks Sly Joker (base 0.38 + 0.03 chip bias = 0.41) under low chip bias.
   - Under Configuration D (`ante1_chip_bias: 0.8`), Sly Joker reaches 1.01 and properly outranks Buffoon Pack (1.01 > 0.45).
   - Scoping the test with a temporary context override to verify that Buffoon Pack outranks Sly Joker under `chip_bias = 0.03`, while also verifying that Sly Joker outranks Buffoon Pack under default `chip_bias = 0.8`, preserves the original test invariant while validating Configuration D behavior.
4. **State Cleanup on Infeasible Swaps**:
   - Clearing `self._pending_swap_target_idx = None` immediately upon entering the block guarantees that whether the buy succeeds or is aborted (e.g. due to cash fluctuation or slot constraints), the pending swap target never dangles into future turns.
5. **Sell Value Engine Alignment**:
   - Checking `getattr(j, "state", {}).get("sell_value", max(1, getattr(j, "cost", 4) // 2))` accurately reflects in-game cash realized upon selling, preventing under- or over-estimation in counterfactual states.

---

## 3. Caveats

- **No Caveats on Simulator Mechanics**: All proposed changes operate strictly within pure-Python logic, without modifying RNG streams or game state.
- **Independence from Pace Rule**: This remedy addresses shop spending and parameters (`SearchShopV10` and `V10_DEFAULTS`). In-blind discard/hand pace rule adjustments (`ante1_pace_rule`) are managed in parallel by Remedy Explorer 2.
- **Human-Fair Compliance**: The counterfactual search strictly utilizes current game state and shop items without lookahead into future shops or draw decks. CI seed exactness is fully preserved.

---

## 4. Conclusion & Actionable Fix Plan

The four fixes are localized, complete, and mutually compatible.

### Detailed Code Modifications

#### Fix 1: Update `V10_DEFAULTS` in `vendor/balatro-rl/balatro_sim/agent_v10.py`
Around line 294:
```python
<<<<
    "ante1_chip_bias": 0.03,
    "ante2_chip_bias": 0.0,
====
    "ante1_chip_bias": 0.8,
    "ante2_chip_bias": 0.5,
    "early_shop_reserve": 4,
>>>>
```

#### Fix 2: Correct Sell Value Lookups in `vendor/balatro-rl/balatro_sim/agent_v10.py`
At line 2749:
```python
<<<<
            sell_val = getattr(j_inst, "sell_cost", max(1, getattr(j_inst, "cost", 4) // 2))
====
            sell_val = getattr(j_inst, "state", {}).get("sell_value", max(1, getattr(j_inst, "cost", 4) // 2))
>>>>
```
At line 2760:
```python
<<<<
            sell_val = getattr(j_inst, "sell_cost", max(1, getattr(j_inst, "cost", 4) // 2))
====
            sell_val = getattr(j_inst, "state", {}).get("sell_value", max(1, getattr(j_inst, "cost", 4) // 2))
>>>>
```
At line 2897:
```python
<<<<
                sell_val = getattr(owned_cand, "sell_cost", max(1, getattr(owned_cand, "cost", 4) // 2))
====
                sell_val = getattr(owned_cand, "state", {}).get("sell_value", max(1, getattr(owned_cand, "cost", 4) // 2))
>>>>
```

#### Fix 3: Infeasible Swap Step 2 Dangling State Fix
In `SearchShopV10._search_shop` (lines 2822-2834):
```python
<<<<
        # 1. Complete pending second step of a swap
        if self._pending_swap_target_idx is not None:
            target_i = self._pending_swap_target_idx
            if 0 <= target_i < len(game.current_shop) and not game.current_shop[target_i].sold:
                item = game.current_shop[target_i]
                price = item.discounted_price(game.shop_discount)
                has_room = len(game.jokers) < game.joker_slots or getattr(item, "edition", None) == "Negative"
                if price <= game.dollars and has_room:
                    self._pending_swap_target_idx = None
                    return {"type": "buy", "item_idx": target_i}
            else:
                self._pending_swap_target_idx = None
====
        # 1. Complete pending second step of a swap
        if self._pending_swap_target_idx is not None:
            target_i = self._pending_swap_target_idx
            self._pending_swap_target_idx = None
            if 0 <= target_i < len(game.current_shop) and not game.current_shop[target_i].sold:
                item = game.current_shop[target_i]
                price = item.discounted_price(game.shop_discount)
                has_room = len(game.jokers) < game.joker_slots or getattr(item, "edition", None) == "Negative"
                if price <= game.dollars and has_room:
                    return {"type": "buy", "item_idx": target_i}
>>>>
```
In `SearchShopV10.decide()` (lines 2940-2952):
```python
<<<<
        # 1. Complete pending second step of a swap immediately
        if self._pending_swap_target_idx is not None:
            target_i = self._pending_swap_target_idx
            if 0 <= target_i < len(game.current_shop) and not game.current_shop[target_i].sold:
                item = game.current_shop[target_i]
                price = item.discounted_price(game.shop_discount)
                has_room = len(game.jokers) < game.joker_slots or getattr(item, "edition", None) == "Negative"
                if price <= game.dollars and has_room:
                    self._pending_swap_target_idx = None
                    return {"type": "buy", "item_idx": target_i}
            else:
                self._pending_swap_target_idx = None
====
        # 1. Complete pending second step of a swap immediately
        if self._pending_swap_target_idx is not None:
            target_i = self._pending_swap_target_idx
            self._pending_swap_target_idx = None
            if 0 <= target_i < len(game.current_shop) and not game.current_shop[target_i].sold:
                item = game.current_shop[target_i]
                price = item.discounted_price(game.shop_discount)
                has_room = len(game.jokers) < game.joker_slots or getattr(item, "edition", None) == "Negative"
                if price <= game.dollars and has_room:
                    return {"type": "buy", "item_idx": target_i}
>>>>
```

#### Fix 4: Constrained Open-Slot Early Ante Spending in `SearchShopV10._search_shop`
In `vendor/balatro-rl/balatro_sim/agent_v10.py` (lines 2839-2861):
```python
<<<<
        # 2. Open-Slot Counterfactual Evaluation (len(jokers) < joker_slots)
        if len(game.jokers) < game.joker_slots:
            best_buy_delta = swap_threshold
            best_buy_idx = None
            for i, item in enumerate(game.current_shop):
                if item.sold or item.kind != "joker":
                    continue
                price = item.discounted_price(game.shop_discount)
                if price > game.dollars:
                    continue
                f_buy = formulate_counterfactual_state(game, {"type": "buy", "item_idx": i})
                v_buy = evaluate_shop_value(f_buy)
                delta = v_buy - v_curr
                is_high_leverage = item.key in HIGH_LEVERAGE_SCORING_JOKERS
                thr = 0.000 if is_high_leverage else best_buy_delta
                if delta > thr:
                    if delta > best_buy_delta or (is_high_leverage and best_buy_idx is None):
                        best_buy_delta = max(best_buy_delta, delta)
                        best_buy_idx = i

            if best_buy_idx is not None:
                return {"type": "buy", "item_idx": best_buy_idx}
====
        # 2. Open-Slot Counterfactual Evaluation (len(jokers) < joker_slots)
        if len(game.jokers) < game.joker_slots:
            best_buy_delta = swap_threshold
            best_buy_idx = None

            # Check if player currently owns a flat scoring anchor (chips or flat mult)
            has_flat_scoring = any(
                j.key in CHIPS_JOKERS or j.key in FLAT_MULT_JOKERS
                for j in game.jokers
            )

            for i, item in enumerate(game.current_shop):
                if item.sold or item.kind != "joker":
                    continue
                price = item.discounted_price(game.shop_discount)
                if price > game.dollars:
                    continue

                is_early_scoring = item.key in CHIPS_JOKERS or item.key in FLAT_MULT_JOKERS
                is_pure_xmult = item.key in XMULT_JOKERS and not is_early_scoring

                # Early-ante constraints (Ante <= 2) to protect interest compounding and prevent premature death
                if game.ante <= 2:
                    # 1. Require flat scoring anchor before buying pure xMult / specific-hand endgame jokers
                    if is_pure_xmult and not has_flat_scoring:
                        continue

                    # 2. Enforce cash reserve in early antes:
                    # If already holding a flat scoring anchor or evaluating non-scoring jokers,
                    # ensure purchase leaves at least the reserve (e.g. $4).
                    early_reserve = V10_PARAMS.get("early_shop_reserve", 4)
                    if (has_flat_scoring or not is_early_scoring) and (game.dollars - price < early_reserve):
                        continue

                f_buy = formulate_counterfactual_state(game, {"type": "buy", "item_idx": i})
                v_buy = evaluate_shop_value(f_buy)
                delta = v_buy - v_curr

                is_high_leverage = item.key in HIGH_LEVERAGE_SCORING_JOKERS
                # Relaxed threshold (0.000) only for high-leverage scoring in mid/late game (Ante > 2)
                # or early ante when a flat scoring anchor is already secured
                allow_relaxed_thr = is_high_leverage and (game.ante > 2 or has_flat_scoring or is_early_scoring)
                thr = 0.000 if allow_relaxed_thr else best_buy_delta

                if delta > thr:
                    if delta > best_buy_delta or (allow_relaxed_thr and best_buy_idx is None):
                        best_buy_delta = max(best_buy_delta, delta)
                        best_buy_idx = i

            if best_buy_idx is not None:
                return {"type": "buy", "item_idx": best_buy_idx}
>>>>
```

#### Fix 5: Dual Assertion in `vendor/balatro-rl/tests/test_m13_ante1.py`
At lines 79?105:
```python
<<<<
def test_ante1_buffoon_outranks_sly():
    from balatro_sim.game import BalatroGame
    from balatro_sim.agent_v9 import reference_hand, pack_value
    from balatro_sim.agent_v10 import _v10_rank_shop_items, V10_PARAMS
    from balatro_sim.shop import ShopItem
    g = BalatroGame(seed=0, rng_mode="seed")
    g.ante = 1
    g.dollars = 4
    g.current_shop = [
        ShopItem("joker", "j_sly", "Sly Joker", 3),
        ShopItem("booster", "p_buffoon", "Buffoon Pack", 4),
    ]
    ref = reference_hand(g)
    buys, _ = _v10_rank_shop_items(g, ref, surplus=False)
    vals = {g.current_shop[i].key: v for v,i in buys}
    # Ante-1: buffoon boosted 0.25+0.20=0.45 > sly 0.41, so buffoon should be top
    assert vals["p_buffoon"] > vals["j_sly"], f"ante1 buffoon should outrank sly: {vals}"
    # Verify boost is gated: ante-1 buffoon value should be 0.20 higher than base pack_value
    base = pack_value(g, "p_buffoon")
    assert abs(vals["p_buffoon"] - (base + V10_PARAMS["ante1_buffoon_boost"]) ) < 1e-6
    g.ante = 4
    buys4, _ = _v10_rank_shop_items(g, ref, surplus=False)
    vals4 = {g.current_shop[i].key: v for v,i in buys4}
    # Ante-4 no boost: buffoon should be base value (0.25)
    if "p_buffoon" in vals4:
        assert abs(vals4["p_buffoon"] - base) < 1e-6, f"ante4 buffoon should be base {base}, got {vals4['p_buffoon']}"
====
def test_ante1_buffoon_outranks_sly():
    from balatro_sim.game import BalatroGame
    from balatro_sim.agent_v9 import reference_hand, pack_value
    from balatro_sim.agent_v10 import _v10_rank_shop_items, V10_PARAMS
    from balatro_sim.shop import ShopItem
    g = BalatroGame(seed=0, rng_mode="seed")
    g.ante = 1
    g.dollars = 4
    g.current_shop = [
        ShopItem("joker", "j_sly", "Sly Joker", 3),
        ShopItem("booster", "p_buffoon", "Buffoon Pack", 4),
    ]
    ref = reference_hand(g)
    buys, _ = _v10_rank_shop_items(g, ref, surplus=False)
    vals = {g.current_shop[i].key: v for v,i in buys}

    # Under Config D defaults (ante1_chip_bias=0.8), high-priority flat chips jokers
    # take precedence over gambling on a buffoon pack (1.01 > 0.45) to ensure early survival.
    # Under legacy low chip bias (0.03), buffoon boost (0.25+0.20=0.45) outranks sly (0.41).
    old_bias = V10_PARAMS.get("ante1_chip_bias", 0.8)
    try:
        V10_PARAMS["ante1_chip_bias"] = 0.03
        buys_legacy, _ = _v10_rank_shop_items(g, ref, surplus=False)
        vals_legacy = {g.current_shop[i].key: v for v,i in buys_legacy}
        assert vals_legacy["p_buffoon"] > vals_legacy["j_sly"], f"ante1 buffoon should outrank sly under low bias: {vals_legacy}"
    finally:
        V10_PARAMS["ante1_chip_bias"] = old_bias

    # Under Config D, chip joker correctly outranks buffoon pack:
    assert vals["j_sly"] > vals["p_buffoon"], f"Config D chip joker should outrank buffoon pack: {vals}"

    # Verify boost is gated: ante-1 buffoon value should be 0.20 higher than base pack_value
    base = pack_value(g, "p_buffoon")
    assert abs(vals["p_buffoon"] - (base + V10_PARAMS["ante1_buffoon_boost"])) < 1e-6
    g.ante = 4
    buys4, _ = _v10_rank_shop_items(g, ref, surplus=False)
    vals4 = {g.current_shop[i].key: v for v,i in buys4}
    # Ante-4 no boost: buffoon should be base value (0.25)
    if "p_buffoon" in vals4:
        assert abs(vals4["p_buffoon"] - base) < 1e-6, f"ante4 buffoon should be base {base}, got {vals4['p_buffoon']}"
>>>>
```

---

## 5. Verification Method

### 5.1 Verification Commands
Once the implementer applies the changes, verify using the following commands:

```bash
# 1. Verify V10 unit tests pass cleanly:
pytest vendor/balatro-rl/tests/test_agent_v10.py -v

# 2. Verify V10 E2E requirements pass cleanly:
pytest vendor/balatro-rl/tests/test_e2e_v10_requirements.py -v

# 3. Verify M13 Ante 1 survival suite passes 100% (all 14 tests):
pytest vendor/balatro-rl/tests/test_m13_ante1.py -v

# 4. Verify CI seed exactness gate passes:
pytest vendor/balatro-rl/tests/test_seed_exactness.py -m ci_gate -v

# 5. Verify all 4 static audits remain clean:
python tools/audit_jokers_static.py
python tools/audit_consumables_static.py
python tools/audit_bosses_static.py
python tools/audit_tags_static.py

# 6. Verify V10_DEFAULTS values programmatically:
python -c "import sys; sys.path.insert(0, 'vendor/balatro-rl'); import balatro_sim.agent_v10 as v; assert v.V10_DEFAULTS['ante1_chip_bias'] == 0.8; assert v.V10_DEFAULTS['ante2_chip_bias'] == 0.5; assert v.V10_DEFAULTS['early_shop_reserve'] == 4; print('V10_DEFAULTS verification: SUCCESS')"
```

### 5.2 Invalidation Conditions
- Any failure in `pytest vendor/balatro-rl/tests/test_m13_ante1.py`.
- Any regression where an Ante 1 shop with 0 owned jokers and <= $8 cash buys pure xMult (`j_tribe`, `j_order`, `j_baseball`) instead of flat chips/mult or saving cash.
- Any dangling state where `self._pending_swap_target_idx` remains non-None after an unaffordable shop buy.
