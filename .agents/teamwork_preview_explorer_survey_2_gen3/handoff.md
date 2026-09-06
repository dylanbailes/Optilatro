# Handoff Report: Requirement R2 (Synergistic Deck Reshaping & Targeted Consumables)

## 1. Observation

Direct code inspections across `vendor/balatro-rl/balatro_sim/agent_v10.py`, `tools/portfolio.py`, `vendor/balatro-rl/balatro_sim/agent_v9.py`, `vendor/balatro-rl/balatro_sim/consumables.py`, and `vendor/balatro-rl/balatro_sim/game.py` reveal the following verbatim mechanics, line numbers, and behaviors:

1. **Portfolio Evaluation Scope**:
   - In `tools/portfolio.py` (lines 589–674), `evaluate_shop_candidates` only evaluates `item.kind == "joker"`, `item.kind == "planet"`, and `item.kind == "voucher"`. It contains **no branch** for `item.kind == "tarot"` or `item.kind == "booster"`.
   - In `portfolio.py` (lines 643–659), `item.kind == "planet"` only checks and modifies `flush_lvl`, `pair_lvl`, `two_pair_lvl`, and `high_card_lvl`. All other hand types (Three of a Kind, Straight, Full House, Four of a Kind) only touch `max_hand_lvl`.
   - In `agent_v10.py` (lines 2870–2946), `SearchShopV10._search_shop` only uses the offline value model for full-slot Joker swaps (`type == "swap_joker"`). For all other decisions (empty slots, packs, tarots, planets, vouchers), it delegates to `_v10_decide_shop`.

2. **Priority Inversion in `portfolio_target_hand`**:
   - In `agent_v10.py` (lines 686–694):
     ```python
     def portfolio_target_hand(game) -> str:
         if not game.jokers:
             return main_hand_type(game)
         keys = {j.key for j in game.jokers}
         for jk, ht in _JOKER_HAND_TYPES.items():
             if jk in keys:
                 return ht
         return main_hand_type(game)
     ```
     `_JOKER_HAND_TYPES` is an unweighted dictionary iterated in insertion order (lines 652–678). Keys like `j_runner` ("Straight"), `j_jolly` ("Pair"), and `j_sly` ("Pair") precede premier xMult engines like `j_trio` ("Three of a Kind", line 676) and `j_family` ("Four of a Kind", line 677).
     When both `j_family` and `j_sly` are owned, `portfolio_target_hand` returns `"Pair"`.

3. **`save_mode` Consumable Starvation**:
   - In `agent_v10.py` (lines 1400–1420):
     ```python
     save_mode = (
         game.ante > 2
         and game.dollars < p["interest_target"]
         and max((v for v, _ in buys), default=0.0) < p["save_strong_value"]
         and forecast_beatable(game, p["save_margin"], ref)
     )
     # ...
     is_high_ev_consumable = False
     if V10_PARAMS.get("farm_clear_threshold", 0.90) < 1.0:
         is_high_ev_consumable = item.key in ("c_hermit", "c_death", "c_fool", "c_temperance")
     if (price <= game.dollars
             and (not save_mode or value >= p["save_strong_value"] or is_high_ev_consumable)
             and worth_spending(game, price, value)):
         return {"type": "buy", "item_idx": idx}
     ```
     With `p["interest_target"] = 25` and `p["save_strong_value"] = 0.30`:
     - Planet cards (`value = 0.14`) are blocked.
     - Synergistic Tarots like Strength (`0.13`), Hanged Man (`0.12`), and Suit conversions (`0.12`) are blocked.
     - Celestial booster packs (`0.15 - 0.19`) are blocked.

4. **Booster Pack Slot-Overfill Skip**:
   - In `game.py` (line 1427):
     ```python
     elif isinstance(choice, str):
         if len(self.consumable_hand) < self.consumable_slots:
             self.consumable_hand.append(choice)
     ```
   - In `agent_v10.py` (lines 1456, 1474, 1509–1514):
     When `len(game.consumable_hand) >= game.consumable_slots`, `room_for_consumable` is False. In `_v10_decide_booster`, all planet/tarot/spectral values become `0.0`, resulting in `{"type": "skip_booster"}`.
   - In `_v10_rank_shop_items` (lines 1315–1324), `item.kind == "booster"` does NOT check `len(game.consumable_hand) < game.consumable_slots`. Celestial and Arcana packs are bought with full consumable inventory and immediately skipped.

5. **Tarot Card Targeting Defects**:
   - **Death (`c_death`)**: Line 1087 gates on `(t["rank"] is not None or t["suit"] is not None)`. If `t["face"]` is True (Photograph/Smiley/Sock & Buskin), line 1087 evaluates to False and falls through to V9 naive targeting. Furthermore, if both `t["rank"]` and `t["suit"]` are present, `t["rank"]` ignores `t["suit"]`, risking overwriting target suit cards with off-suit ranks.
   - **Strength (`c_strength`)**: Line 1105 gates on `(t["rank"] is not None or t.get("rank_set"))`. It completely ignores `t["face"]`, missing 10 -> Jack promotions.
   - **Hanged Man (`c_hanged_man`)**: `_reshape_tarot_bonus` (line 803) returns `0.0` when `t["suit"]` or `t["face"]` is active. It does not protect majority ranks for `j_trio` or `j_duo`.
   - **Justice (`c_justice`)**: Line 1686 in `agent_v9.py` hardcodes `c_justice` value to `0.0`. `_reshape_tarot_bonus` has no check for `t["enh"] == "Glass"`. Justice is never bought even when `j_glass_joker` is owned.

---

## 2. Logic Chain

1. **Premise 1**: Late-game scoring scaling in Balatro requires compounded synergy across three distinct pillars: Joker xMult/scaling, base Hand Level chips/mult (Planets), and deck card concentration/enhancement (Tarots/Spectrals).
2. **Premise 2**: An AI agent cannot scale hand levels or reshape its deck if shop decision logic systematically suppresses purchasing synergistic consumables during the accumulation phase (Antes 3–6).
3. **Observation Link**: `save_mode` blocks all items with valuation below 0.30 unless listed in `is_high_ev_consumable`. Planets (0.14) and synergistic Tarots (0.12–0.16) are excluded from `is_high_ev_consumable`.
4. **Deduction 1**: Under the current policy, whenever the agent has between $5 and $24 and can clear the upcoming blind, it saves for interest rather than buying Jupiter for a Flush build or Death/Strength for an Ace/Face build. Consequently, the agent enters late antes under-leveled.
5. **Observation Link**: In `portfolio_target_hand`, iteration order determines the target hand type. `_JOKER_HAND_TYPES` iterates through common chip jokers before xMult jokers.
6. **Deduction 2**: A player holding `j_family` and `j_sly` targets Pair instead of Four of a Kind. Planet purchases and celestial packs buy Mercury instead of Mars, discarding the run's primary win condition.
7. **Observation Link**: Booster packs are purchased without verifying consumable slot vacancy. Upon opening with full slots, all choices yield value 0.0 and the pack is skipped.
8. **Deduction 3**: The agent suffers net-negative transactions where it spends $4–$8 of scarce capital for zero return.
9. **Conclusion**: Resolving these five discrete, localized failure modes in `agent_v10.py` and `portfolio.py` will directly unlock synergistic deck reshaping and enable the target >10% win rate.

---

## 3. Concrete Code Locations & Recommendations

### Recommendation 1: Tiered `portfolio_target_hand`
**Target File**: `vendor/balatro-rl/balatro_sim/agent_v10.py` (lines 686–694)
**Design**:
```python
_HAND_ENGINE_PRIORITY = [
    # Tier 1: Premier xMult Hand Finishers
    ({"j_family"}, "Four of a Kind"),
    ({"j_order"}, "Straight"),
    ({"j_tribe"}, "Flush"),
    ({"j_trio"}, "Three of a Kind"),
    ({"j_duo"}, "Pair"),
    # Tier 2: Scaling Hand Engines
    ({"j_spare_trousers", "j_trousers"}, "Two Pair"),
    ({"j_runner"}, "Straight"),
    # Tier 3: High-Synergy Suit & Flat/Chip Engines
    ({"j_bloodstone", "j_crafty", "j_droll", "j_smeared", "j_smeared_joker"}, "Flush"),
    ({"j_clever", "j_mad"}, "Two Pair"),
    ({"j_wily", "j_zany"}, "Three of a Kind"),
    ({"j_sly", "j_jolly", "j_half"}, "Pair"),
    ({"j_shortcut", "j_four_fingers", "j_superposition", "j_crazy", "j_devious"}, "Straight"),
    # Tier 4: Held-in-Hand Engines
    ({"j_baron", "j_shoot_the_moon"}, "High Card"),
]

def portfolio_target_hand(game) -> str:
    if not game.jokers:
        return main_hand_type(game)
    keys = {j.key for j in game.jokers}
    for engine_keys, ht in _HAND_ENGINE_PRIORITY:
        if keys & engine_keys:
            return ht
    return main_hand_type(game)
```

### Recommendation 2: Extend `deck_reshape_target`
**Target File**: `vendor/balatro-rl/balatro_sim/agent_v10.py` (lines 744–789)
**Modifications**:
- Activate `kind_stack` rank targeting for `j_trio` and `j_duo`, not just `j_family`:
  ```python
  kind_stack = any(k in keys for k in ("j_family", "j_trio", "j_duo")) or (
      main_hand_type(game) in _KIND_STACK_HANDS
      and game.run_hand_counts.get(main_hand_type(game), 0) >= 2)
  if kind_stack:
      t["rank"] = _majority_rank(dg)
  ```
- If `t["face"]` is True and `t["rank"]` is None, expose `t["rank_set"] = {11, 12, 13}`.

### Recommendation 3: Portfolio-Driven Dynamic Tarot Targeting
**Target File**: `vendor/balatro-rl/balatro_sim/agent_v10.py` (lines 1057–1145)
**Modifications**:
1. **Death (`c_death`)**:
   - Handle `t["face"]`:
     ```python
     if t.get("face") and t["rank"] is None and t["suit"] is None:
         src = next((i for i in best if hand[i].is_face_card), None)
         dst = next((i for i in weakest if not hand[i].is_face_card
                     and not (t.get("rank_set") and hand[i].rank in t["rank_set"])
                     and not (hand[i].rank == 2 and "j_wee" in keys)
                     and not (hand[i].rank in (2, 3, 4, 5) and "j_hack" in keys)), None)
     ```
   - Protect target suit when copying target rank:
     In `dst` selection, add `and not (t.get("suit") and hand[i].suit == t["suit"])`.
2. **Strength (`c_strength`)**:
   - Handle `t["face"]`: Target any rank 10 cards (`hand[i].rank == 10`) to promote to Jack (rank 11).
   - Backfill available targets up to 2 cards across both `target_r - 1` and `rank == 10`.
3. **Hanged Man (`c_hanged_man`)**:
   - Award purchase bonus in `_reshape_tarot_bonus` when `t["suit"]` (+0.05) or `t["face"]` (+0.04) is active.
4. **Justice (`c_justice`) & Magician (`c_magician`)**:
   - In `_reshape_tarot_bonus`:
     ```python
     if key == "c_justice" and any(j.key in ("j_glass", "j_glass_joker") for j in game.jokers):
         return 0.16
     if key == "c_magician" and any(j.key == "j_lucky_cat" for j in game.jokers):
         return 0.12
     ```

### Recommendation 4: Unlocking Consumable & Planet Purchases in `save_mode`
**Target File**: `vendor/balatro-rl/balatro_sim/agent_v10.py` (line 1417)
**Modifications**:
```python
is_high_ev_consumable = False
if V10_PARAMS.get("farm_clear_threshold", 0.90) < 1.0:
    target_ht = portfolio_target_hand(game)
    t = deck_reshape_target(game)
    is_target_planet = (item.kind == "planet" and PLANET_HAND.get(item.key) == target_ht)
    is_target_tarot = (item.kind == "tarot" and _reshape_tarot_bonus(game, item.key) > 0)
    is_core_econ = item.key in ("c_hermit", "c_death", "c_fool", "c_temperance")
    is_high_ev_consumable = is_core_econ or is_target_planet or is_target_tarot
```

### Recommendation 5: Consumable Inventory Guards & Proactive Planet Consumption
**Target File**: `vendor/balatro-rl/balatro_sim/agent_v10.py` (lines 1213–1216, 1315–1324)
**Modifications**:
1. In `_v10_rank_shop_items`:
   For booster packs that grant consumables (`p_celestial*`, `p_arcana*`, `p_spectral*`), gate purchase on:
   `len(game.consumable_hand) < game.consumable_slots`.
2. In `_v10_maybe_use_planet`:
   In `State.SHOP`, use ANY held planet immediately:
   ```python
   if game.state == State.SHOP:
       return {"type": "use_consumable", "consumable_idx": ci, "target_cards": []}
   ```

---

## 4. Caveats

1. **Stone / Wild Card Mechanics**: Known P2 mechanics gaps exist in the engine (Wild cards miss suit jokers, Stone cards expose rank). Tarot targeting should avoid creating Wild cards for suit-specific jokers until engine GAP-W is resolved.
2. **`c_fool` Preconditions**: If `c_fool` is acquired before any consumable has been used in the run, it cannot resolve targets. `c_fool` valuation should be discounted to 0 when `len(game.consumables_used) == 0`.
3. **Ante-1 Budget Interaction**: In Ante 1, cash is ultra-constrained ($4–$10). Gating rules must ensure the agent does not buy expensive planets in Ante 1 Small Blind at the expense of scoring jokers needed to survive Big Blind and Boss Blind.

---

## 5. Conclusion

Requirement R2 contains high-leverage optimization targets. The simulator already possesses rich capabilities for deck reshaping, but the flow is currently throttled by:
1. Unranked dictionary iteration in `portfolio_target_hand`.
2. Severe purchase suppression caused by `save_mode` interest locking.
3. Booster pack inventory oversights.
4. Blind spots in Tarot card targeting (missing Face promotions in Strength, Face copying in Death, and Glass joker synergy in Justice).

Implementing the localized improvements specified above will directly bridge mid-game leads into consistent Ante 8 victories, enabling the team to break past the 10.0% win-rate threshold.

---

## 6. Verification Method

To independently verify all findings and test subsequent implementations:

```bash
# 1. Verify exactness gate
python -m pytest vendor/balatro-rl/tests/test_seed_exactness.py -m ci_gate -v

# 2. Run agent v10 unit tests
python -m pytest vendor/balatro-rl/tests/test_agent_v10.py -v

# 3. Run all static audits
python tools/audit_jokers_static.py
python tools/audit_consumables_static.py
python tools/audit_bosses_static.py
python tools/audit_tags_static.py

# 4. Run full test suite
python -m pytest vendor/balatro-rl/tests vendor/balatro-rl/balatro_sim/tests -q
```
