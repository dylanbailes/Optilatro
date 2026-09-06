# Analysis Report: Requirement R1 (Late-Game Capital Deployment & Urgent Rerolls)

**Author:** Survey Explorer 1 (R1 Focus)  
**Date:** 2026-09-04  
**Working Directory:** `D:/Optilatro/.agents/teamwork_preview_explorer_survey_1_gen3`  
**Target Codebase:** `vendor/balatro-rl/balatro_sim/agent_v10.py`, `agent_l1.py`, `agent_v9.py`, `game.py`, `constants.py`

---

## 1. Executive Summary

Optilatro's `search_shop_v10` policy achieves an **8.67% win rate (26/300)** on White Stake / Red Deck (Seeds 0–299). However, benchmark telemetry reveals an acute late-game ceiling:
- **88 out of 300 runs (29.3%) die in Antes 6, 7, and 8** (Ante 6: 38 deaths, Ante 7: 33 deaths, Ante 8: 17 deaths).
- A substantial fraction of these late deaths occur while **holding $20 to $28 in cash** (e.g. Seed 229 died Ante 8 Boss holding $28; Seed 215 died Ante 7 Boss holding $27; Seed 61 died Ante 8 Boss holding $24; Seeds 137, 197, 173, 195, 283 all died holding $23).
- Multiple runs died in Ante 7 and 8 holding **dead economy jokers** (`j_golden`, `j_todo_list`, `j_faceless`, `j_ticket`, `j_egg`, `j_credit_card`, `j_delayed_grat`) because the shop policy neither prioritized rolling for premier xMult finishers nor allowed full-slot replacement when cash on hand was slightly below item sticker price.

This analysis identifies five concrete structural defects in `vendor/balatro-rl/balatro_sim/agent_v10.py` and outlines exact, human-fair mechanisms to break through the 10.0%+ win rate threshold (>= 30/300 wins).

---

## 2. Exact Blind Targets for Antes 6–8 (Red Deck / White Stake)

Source of truth: `vendor/balatro-rl/balatro_sim/constants.py` (`BLIND_CHIPS`, lines 58–67) and `game.py` (`_set_blind`, lines 440–455):

| Ante | Small Blind | Big Blind | Boss Blind (Standard) | Boss Exceptions |
| :--- | :--- | :--- | :--- | :--- |
| **Ante 6** | 20,000 | 30,000 | 40,000 | **The Wall** (`bl_wall`, 4x base): **80,000**<br>**The Needle** (`bl_needle`, 1x base): **20,000** |
| **Ante 7** | 35,000 | 52,500 | 70,000 | **The Wall** (`bl_wall`, 4x base): **140,000**<br>**The Needle** (`bl_needle`, 1x base): **35,000** |
| **Ante 8** | 50,000 | 75,000 | 100,000 | **Violet Vessel** (`bl_violet`, 6x base): **300,000**<br>Standard Showdowns (Cerulean Bell, Crimson Heart, Verdant Leaf, Amber Acorn): **100,000** |

### Benchmark Scoring Requirements:
- **Ante 6**: Safe builds must output at least **~40,000 chips** (or ~80,000 vs The Wall) across the round.
- **Ante 7**: Safe builds must output **~70,000 to 100,000 chips** (or ~140,000 vs The Wall). A flat chips/mult build without multiplicative xMult or high scaling will almost inevitably fail here.
- **Ante 8**: Winning builds must output **~100,000 to 200,000+ chips** (or 300,000 chips vs Violet Vessel). Without premier xMult or scaling, survival is near 0%.

---

## 3. Investigation of Current Codebase Deficiencies

### 3.1 Deficiency A: Absence of Round Scoring Forecast & Flawed Immediate-Blind Gate

#### Current Implementation:
There is **no** round-level scoring forecast function in `agent_v10.py` (`_forecast_round_score` does not exist). Instead, `agent_v10.py` reuses `forecast_beatable(game, margin, ref)` from `agent_v9.py` (lines 2216–2227):

```python
def forecast_beatable(game, margin: float, ref=None) -> bool:
    if ref is None:
        ref = reference_hand(game)
    ceiling, typical, reach, base_c, base_t = ref
    expected = reach * base_c + (1.0 - reach) * base_t
    return expected >= next_blind_target(game) * margin
```

#### Why This Fails in Late Game:
1. **Single-Hand Evaluation**: `expected` computes the score of a single hand (`reach * base_c + (1.0 - reach) * base_t`). In Balatro, rounds afford `STARTING_HANDS = 4` hands (or `game.base_hands`).
2. **Immediate Blind Myopia**: `next_blind_target(game)` evaluates *only* the immediate next blind:
   - When entering the shop after Ante 6 Boss, `next_blind_target` is Ante 7 Small Blind (**35,000**).
   - If the player's single hand scores 32,000, `forecast_beatable(game, 1.20)` is false; but if it scores 42,000, `forecast_beatable` evaluates to **True**.
   - Because `forecast_beatable` returns True, `save_mode` engages (`save_mode = True`), locking the bankroll below $25 and forbidding any rerolling!
   - Yet 42,000 per hand (or 80,000 across 2 hands) cannot defeat the Ante 7 Boss (70,000 standard, 140,000 Wall) or Ante 8 Showdown (100,000 to 300,000). The agent enters a false sense of security and hoards money directly into its grave.

---

### 3.2 Deficiency B: $25 Interest Hoarding and Arbitrary 2-Reroll Cap

#### Current Implementation in `agent_v10.py` (`_v10_decide_shop`, lines 1400–1436):
```python
    save_mode = (
        game.ante > 2
        and game.dollars < p["interest_target"] # 25
        and max((v for v, _ in buys), default=0.0) < p["save_strong_value"] # 0.30
        and forecast_beatable(game, p["save_margin"], ref) # 1.20
    )
...
    reroll_cost = max(0, game.reroll_cost - game.reroll_discount)
    eff_max = p["reroll_max"] # HARDCODED TO 2
    if (not save_mode
            and game.dollars >= max(reroll_cost, p["reroll_min_money"])
            and rerolls_used < eff_max):
        return {"type": "reroll"}

    return {"type": "leave_shop"}
```

#### Why This Fails:
1. **`eff_max` is Capped at 2 in Antes 6–8**:
   - Regardless of whether the agent has $30, $50, or $80, after 2 rerolls ($5 + $6 = $11), `rerolls_used < eff_max` becomes `2 < 2` (False).
   - The agent immediately calls `leave_shop`!
   - This leaves $20 to $60 in unspent capital sitting idle in Antes 6, 7, and 8.
2. **Economic Absurdity in Ante 8**:
   - In White Stake, the game terminates upon clearing Ante 8 Boss.
   - Any interest earned at the end of Ante 8 Small or Big Blind has **zero** value after the run ends.
   - Holding $25 for interest in Ante 8 provides zero compound benefit; every single dollar should be liquidated into combat power.
3. **Mortal Risk in Ante 7**:
   - In Ante 7, dying while holding $25 results in a 100% loss. Interest earned in Ante 7 is worthless if the run cannot survive to Ante 8.
   - When the scoring forecast falls below the Ante 7 Boss threshold (~70k–100k), the $25 interest floor should be relaxed down to $0 (or a small purchase buffer).

---

### 3.3 Deficiency C: `SearchShopV10` Post-Reroll Blindness

#### Current Implementation in `agent_v10.py` (`SearchShopV10.decide`, lines 2989–3015):
```python
        # Counterfactual shop search on first action of the shop visit
        if (self._searches_done < self._search_shops
                and not self._searched_this_visit):
            self._searched_this_visit = True
            act = (self._search_shop_rollout(game) if self._lookahead
                   else self._search_shop(game))
            if act is not None:
                if act.get("type") == "leave_shop":
...
                    return act
                elif act.get("type") in ("buy", "sell_joker", "reroll"):
                    if act.get("type") == "reroll":
                        self._rerolls_this_shop += 1
                    return act

        act = _v10_decide_shop(game, self._rerolls_this_shop)
```

#### Why This Fails:
1. `_searched_this_visit` is flipped to `True` on the **first shop action**.
2. If `_search_shop` returns a reroll, or if `_v10_decide_shop` executes a reroll:
   - On the next decision cycle, `not self._searched_this_visit` is **False**.
   - `_search_shop` is **NEVER CALLED AGAIN** during that shop visit!
   - All post-reroll decisions fall through to `_v10_decide_shop`.
3. Consequently, the offline value model $V(s')$ and the counterfactual swap logic $\Delta V(\text{swap}) = V(s') - V(s)$ never evaluate newly rolled items!

---

### 3.4 Deficiency D: Full-Slot Allowance Bug in `_v10_rank_shop_items`

#### Current Implementation in `agent_v10.py` (lines 1264–1314):
```python
    allowance = game.dollars - reserve
    for i, item in enumerate(game.current_shop):
        if item.sold:
            continue
        price = item.discounted_price(game.shop_discount)
        if price > allowance:
            continue
...
        elif not has_room:
            if worst_cache is None:
                worst_cache = _v10_worst_joker_idx(game, ref)
            if (worst_cache is not None
                    and value - joker_value_of(game, worst_cache, ref)
                    >= p["sell_margin"]):
                need_sell = (value, worst_cache)
```

#### Why This Fails:
- If joker slots are full (`len(jokers) >= joker_slots`), the player can sell `worst_joker` to recoup `sell_value` (typically $2 to $5).
- However, at line 1269:
  `if price > allowance: continue`
  If `game.dollars` is $4, and a Cavendish is in the shop for $6:
  `price (6) > allowance (4)`!
  The item is skipped **before** line 1308 (`elif not has_room:`) is ever reached!
  `need_sell` is **NEVER triggered** for an item whose price exceeds current pocket cash, even if selling the worst joker yields enough money to afford it ($4 + $3 = $7 >= $6)!
- While `SearchShopV10._search_shop` handled this via `if game.dollars + sell_val < price: continue` (line 2925), `_search_shop` is bypassed on post-reroll shops, leaving `_v10_rank_shop_items` completely crippled when cash is low.

---

### 3.5 Deficiency E: Dead Economy Joker Clutter in Late Game

In benchmark runs dying in Antes 6–8:
- Seed 286: held `['j_egg', 'j_swashbuckler', 'j_banner', 'j_todo_list', 'j_ticket']` — three economy jokers in Ante 7!
- Seed 195: held `['j_faceless', 'j_erosion', 'j_fortune_teller', 'j_trio', 'j_delayed_grat']` — two economy jokers in Ante 7 Boss!
- Seed 173: held `['j_family', 'j_obelisk', 'j_hologram', 'j_selzer', 'j_credit_card']` — held credit card in Ante 7 Boss!
- Seed 202: held `['j_madness', 'j_green_joker', 'j_golden', 'j_ice_cream', 'j_flower_pot', 'j_half']` — held Golden Joker in Ante 7 Boss!
- Seed 237: held `['j_blue_joker', 'j_abstract', 'j_ramen', 'j_misprint', 'j_golden']` — held Golden Joker in Ante 8!

Currently, `_v10_worst_joker_idx` (lines 381–430) applies an economy penalty `v -= 0.50` only at `game.ante >= 7`, but:
1. In Ante 6, economy jokers receive no penalty.
2. In `SearchShopV10._search_shop` (line 2895):
   ```python
   if game.ante <= 6:
       if n_xmult <= 1 and owned_cand.key in PORTFOLIO_XMULT: ...
       if n_chips <= 1 and owned_cand.key in PORTFOLIO_CHIPS: ...
       if n_flat <= 1 and owned_cand.key in PORTFOLIO_FLAT: ...
       if owned_cand.key in COMBAT_SCALING_JOKERS: ...
   ```
   If an owned joker is economy, it is not protected, but because `_search_shop` doesn't run after rerolls and `_v10_rank_shop_items` skips unaffordable items, the swap rarely materializes.

---

## 4. Technical Architecture for R1 Implementation

### 4.1 Scoring Forecast Function (`_forecast_round_score`)

Define a human-fair scoring forecast in `agent_v10.py`:

```python
def _forecast_round_score(game, ref=None) -> float:
    """Human-fair round scoring forecast:
    Computes expected total chips achievable across all available hands in the round,
    weighting best drawable hand (ceiling) and typical stratified sample by reachability."""
    if ref is None:
        from .agent_v9 import reference_hand
        ref = reference_hand(game)
    ceiling, typical, reach, base_c, base_t = ref
    expected_hand_score = reach * base_c + (1.0 - reach) * base_t
    base_hands = getattr(game, "base_hands", 4)
    # Conservatively discount for imperfect discards / variance (e.g. 0.85x)
    return float(base_hands * expected_hand_score * 0.85)
```

And define Ante Boss Target lookup:
```python
def _ante_boss_target(game, ante: int | None = None) -> float:
    a = ante if ante is not None else game.ante
    if a > 8:
        return 0.0
    from .constants import BLIND_CHIPS
    base_boss = float(BLIND_CHIPS[a][2])
    if a == game.ante and getattr(game, "next_boss_key", None):
        bk = game.next_boss_key
        if bk == "bl_violet":
            return float(BLIND_CHIPS[a][0] * 6)
        elif bk == "bl_wall":
            return float(BLIND_CHIPS[a][0] * 4)
        elif bk == "bl_needle":
            return float(BLIND_CHIPS[a][0])
    return base_boss
```

### 4.2 Adaptive Interest Floor Relaxation

In `agent_v10.py`, replace static `p["interest_target"] = 25` with adaptive floor:

```python
def _get_interest_target(game, forecast_score: float | None = None) -> int:
    """Adaptive interest target:
    - Ante 8: 0 (final ante; no future interest benefit).
    - Ante 7: 0 to 10 if in scoring deficit (forecast < target), else 25.
    - Ante 6: 15 if lacking xMult and in deficit, else 25.
    - Antes 1-5: 25 (standard compound interest)."""
    if game.ante >= 8:
        return 0
    target = _ante_boss_target(game)
    if forecast_score is None:
        forecast_score = _forecast_round_score(game)
    
    if game.ante == 7:
        if forecast_score < target * 1.25:
            return 0  # Imminent mortality: spend to survive
        return 20
    elif game.ante == 6:
        n_xmult = sum(1 for j in game.jokers if j.key in PORTFOLIO_XMULT)
        if n_xmult == 0 or forecast_score < target:
            return 15
    return 25
```

### 4.3 Urgent Reroll Pacing with Purchase Reserve Buffer

In `_v10_decide_shop`:
```python
    forecast = _forecast_round_score(game, ref)
    boss_target = _ante_boss_target(game)
    is_urgent = (
        (game.ante == 8)
        or (game.ante == 7 and forecast < boss_target * 1.25)
        or (game.ante == 6 and forecast < boss_target)
    )

    # Dynamic reroll limits:
    if is_urgent:
        if game.ante == 8:
            eff_max = 10
        elif game.ante == 7:
            eff_max = 6
        else:
            eff_max = 4
    else:
        eff_max = p["reroll_max"] # 2

    # Purchase reserve buffer:
    # Do not reroll if remaining cash post-reroll cannot buy a target joker
    # (accounting for sell value if slots are full)
    worst_sell = 0
    if len(game.jokers) >= game.joker_slots:
        worst_idx = _v10_worst_joker_idx(game, ref)
        if worst_idx is not None:
            worst_j = game.jokers[worst_idx]
            worst_sell = getattr(worst_j, "state", {}).get(
                "sell_value", max(1, getattr(worst_j, "cost", 4) // 2)
            )

    reroll_cost = max(0, game.reroll_cost - game.reroll_discount)
    dollars_after_reroll = game.dollars - reroll_cost + (worst_sell if len(game.jokers) >= game.joker_slots else 0)
    min_purchase_buffer = 6  # Minimum price for Cavendish/xMult

    can_reroll = (
        rerolls_used < eff_max
        and game.dollars >= reroll_cost
        and (not is_urgent and not save_mode and game.dollars >= max(reroll_cost, p["reroll_min_money"]))
            or (is_urgent and dollars_after_reroll >= min_purchase_buffer)
    )
```

### 4.4 Premier xMult & Scaling Finisher Hunting Target List

Ensure the finisher candidate catalog includes all premier winning engines:
```python
PREMIER_FINISHERS = {
    # Reliable xMult:
    "j_cavendish", "j_duo", "j_trio", "j_family", "j_order", "j_tribe",
    "j_card_sharp", "j_baseball", "j_acrobat", "j_ramen", "j_photograph",
    "j_baron", "j_ancient", "j_blueprint", "j_brainstorm",
    # Premier Scaling:
    "j_constellation", "j_hologram", "j_campfire",
    # Massive Chips:
    "j_stuntman",
}
```

### 4.5 Fixing Post-Reroll Search & Allowance in Full Slots

1. In `_v10_rank_shop_items`:
   Account for `worst_sell` when determining if an item is affordable for a swap:
   ```python
   effective_allowance = allowance + (worst_sell if len(game.jokers) >= game.joker_slots else 0)
   if price > effective_allowance:
       continue
   ```
2. In `SearchShopV10.decide`:
   Do **not** disable search for the entire visit upon the first action. When a reroll occurs, reset `self._searched_this_visit = False` so that newly presented shop cards are evaluated by `_search_shop` counterfactual swap logic!

---

## 5. Human-Fairness & Isolation Verification

- **Draw Order Invariant**: Neither `_forecast_round_score` nor the reroll decision reads `deck[-1]` or accesses future draw order. Everything operates on the reachability-blended composition (`RefHand`).
- **RNG Consumption**: All scoring evaluations use `reference_hand` and `best_play_score` with isolated `_EvalGame` and throwaway seed-0 RNG. Live game state and LuaRandom streams are never consumed during shop evaluation.
- **Shop Future Peeking**: Rerolls advance the shop RNG via normal simulator action `{"type": "reroll"}`. The policy evaluates *only* currently visible shop items.
- **CI Gate**: Conforms to `test_seed_exactness.py -m ci_gate`.
