# Technical Investigation Report: Requirement R2 — Deck Reshaping Synergy & Consumable Utilization

**Agent**: Explorer 2 (`teamwork_preview_explorer`)  
**Working Directory**: `D:/Optilatro/.agents/teamwork_preview_explorer_survey_2_gen2`  
**Target Milestone**: Requirement R2 (Deck Reshaping Synergy & Consumable Utilization)  
**Date**: 2026-09-03  

---

## 1. Observation

### 1.1 Consumable Lifecycle & Architecture Overview
In Optilatro, the consumable subsystem spans five principal modules:
- `vendor/balatro-rl/balatro_sim/consumables.py`: Mechanics for applying Planets (`apply_planet`), Tarots (`apply_tarot`), Spectrals (`apply_spectral`), and Vouchers (`apply_voucher`).
- `vendor/balatro-rl/balatro_sim/shop.py`: Shop generation, item pricing, voucher unlock rules, booster pack generation (`_open_booster`), and purchase processing (`buy_item`).
- `vendor/balatro-rl/balatro_sim/game.py`: State transitions, consumable hand container (`self.consumable_hand`), and consumption dispatch (`self._use_consumable`).
- `vendor/balatro-rl/balatro_sim/agent_v9.py`: Baseline heuristic valuation of consumables (`tarot_value`, `spectral_value`, `pack_value`), usage policies (`maybe_use_planet`, `_tarot_action`, `_spectral_action`, `decide_consumable`), booster decisions (`decide_booster`), and shop ranking (`_rank_shop_items`, `decide_shop`).
- `vendor/balatro-rl/balatro_sim/agent_v10.py`: Production V10 extensions: `deck_reshape_target`, `_reshape_tarot_bonus`, `_reshape_card_bonus`, `_v10_tarot_action`, `_v10_decide_consumable`, `_v10_rank_shop_items`, `_v10_decide_shop`, `_v10_decide_booster`, and `SearchShopV10`.

### 1.2 Identified Architectural Bugs & Defects

#### Defect A: Consumable Hand Deadlock & Permanent Slot Lockout
- In `vendor/balatro-rl/balatro_sim/game.py` lines 810–827, the only shop actions are `buy`, `sell_joker`, `use_consumable`, `reroll`, `reroll_boss`, and `leave_shop`. **There is no `sell_consumable` action in the simulator.** Once an item enters `game.consumable_hand`, it can only leave via `_use_consumable`.
- In `agent_v9.py` lines 1554–1560:
  ```python
  if key in ("c_high_priestess", "c_emperor"):
      if len(game.consumable_hand) <= 1:
          return {"type": "use_consumable", "consumable_idx": ci, "target_cards": []}
      return None
  ```
  However, in `game.py` line 1148–1156, `self.consumable_hand.pop(consumable_idx)` executes **before** `apply_tarot` resolves. Thus, using `c_emperor` or `c_high_priestess` from a full 2/2 hand frees a slot immediately. Because `agent_v9.py` checks `len(game.consumable_hand) <= 1`, if the agent holds `c_emperor` and another un-usable card (e.g., an off-hand planet or suit converter), `c_emperor` refuses to fire.
- In `agent_v9.py` lines 1442–1457 (`maybe_use_planet`):
  ```python
  else:  # SHOP
      if ht == main:
          return {"type": "use_consumable", "consumable_idx": ci, "target_cards": []}
  ```
  In the shop, planets are **only** used if `ht == main_hand_type(game)`. If `c_high_priestess` or a Blue Seal generates a planet for a non-main hand (e.g., `pl_jupiter` when `main` is Pair), the planet is never consumed in shop. Mid-blind, it is only consumed if its hand type is in `plays[:3]`. If the player never plays that hand, the planet sits in `consumable_hand` permanently.
- When `len(game.consumable_hand) >= game.consumable_slots` (2/2):
  - In `agent_v10.py` line 1041: no shop Tarots can be bought (`len(game.consumable_hand) < game.consumable_slots`).
  - In `shop.py` line 715: `buy_item` rejects all shop Planets, Tarots, and Spectrals.
  - In `agent_v10.py` lines 1146–1152 (`_v10_decide_booster`):
    `value = (0.10 if (PLANET_HAND[c] == main and len(game.consumable_hand) < game.consumable_slots) else 0.0)`
    `if len(game.consumable_hand) < game.consumable_slots: value = tarot_value(game, c)`
    Every choice in Arcana, Celestial, and Spectral packs evaluates to `None` or `0.0`. The pack is **skipped**, wasting 100% of the pack price ($4 to $8).

#### Defect B: Celestial Pack Waste & Skip Catastrophe
- In `agent_v10.py` lines 1144–1148 (`_v10_decide_booster`):
  ```python
  if c in PLANET_HAND:
      value = (0.10 if (PLANET_HAND[c] == main
                        and len(game.consumable_hand) < game.consumable_slots)
               else 0.0)
  ```
  If a Celestial Pack contains 3 planets and none match `main_hand_type(game)`, all choices have `value = 0.0`.
- At line 1157, `ranked` is empty. The agent executes `return {"type": "skip_booster"}`.
- Result: The agent pays $4–$8 for a Celestial pack, sees 3 or 5 planets, and takes nothing, discarding all potential upgrades (even for high-synergy secondary hands, High Card, Pair, or for scaling `j_constellation` / `j_satellite`).

#### Defect C: The `save_mode` Threshold Barrier (0.30)
- In `agent_v9.py` lines 197–199:
  ```python
  "save_strong_value": 0.30,   # save-mode: only items worth >= this get bought
                               #   (joker_value marginal ratios / pack values; Hermit/Death tarots qualify)
  ```
- Lines 2377–2400:
  ```python
  save_mode = (
      game.ante > 2
      and game.dollars < p["interest_target"]
      and max((v for v, _ in buys), default=0.0) < p["save_strong_value"]
      and forecast_beatable(game, p["save_margin"], ref)
  )
  ...
  if (price <= game.dollars
          and (not save_mode or value >= p["save_strong_value"])
          and worth_spending(game, price, value)):
      return {"type": "buy", "item_idx": idx}
  ```
- However, the actual values computed for consumables:
  - `c_hermit`: `0.18 + 0.002 * min(dollars, 20)` = max **0.22** (line 1692).
  - `c_death`: `0.16` (line 1694) + `0.06` reshape bonus (line 663) = max **0.22**.
  - `c_fool`: `0.15` (line 1696).
  - Planets: fixed **0.08** (line 1037).
  - Booster packs: `p_arcana` = 0.09–0.12, `p_celestial` = 0.15–0.19, `p_standard` = 0.07–0.09, `p_buffoon` (standard) = 0.25.
- Because `0.22 < 0.30`, **Hermit and Death do NOT qualify**, despite the author's explicit code comment. In `save_mode`, all Tarots, all Planets, and all non-mega Booster packs are 100% blocked from purchase.

#### Defect D: Incomplete & Flawed Reshaping Engine Classifications
- In `agent_v10.py` lines 543–570:
  ```python
  _RANK_ENGINES = (
      ("j_baron", 13),           # x1.5 per King held
      ("j_cloud_9", 9),          # $1 per 9 in deck
      ("j_shoot_the_moon", 12),  # +13 Mult per Queen held
  )
  _SUIT_ENGINES_FIXED = (
      ("j_golden", "Diamonds"),
      ("j_rough_gem", "Diamonds"),
      ("j_bloodstone", "Hearts"),
  )
  _SUIT_ENGINES_DOMINANT = ("j_ancient", "j_blackboard", "j_tribe")
  _ENH_ENGINES = {
      "j_steel_joker": "Steel",
      "j_glass": "Glass",
  }
  _FACE_ENGINES = ("j_photograph", "j_sock_and_buskin", "j_business", "j_reserved_parking")
  ```
  Flaws observed:
  1. `("j_golden", "Diamonds")`: `j_golden` (Golden Joker) pays $4 at round end and has zero suit affinity. It was erroneously mapped to Diamonds.
  2. Critical rank engines are missing:
     - `j_scholar`: +20 Chips, +4 Mult per played Ace -> needs Rank 14 (Ace).
     - `j_walkie_talkie`: +10 Chips, +4 Mult per played 10 or 4 -> needs Rank 10 or 4.
     - `j_wee`: +8 Chips permanent scaling per played 2 -> needs Rank 2.
     - `j_hit_the_road`: x0.5 Mult per discarded Jack -> needs Rank 11 (Jack).
  3. Rank-group engines are completely unrepresented in `deck_reshape_target`:
     - `j_even_steven`: Even ranks {2, 4, 6, 8, 10}.
     - `j_odd_todd`: Odd ranks {3, 5, 7, 9, 11, 13, 14}.
     - `j_fibonacci`: Fibonacci ranks {14, 2, 3, 5, 8}.
     - `j_hack`: Low ranks {2, 3, 4, 5}.
  4. Real suit jokers are missing from `_SUIT_ENGINES_FIXED`:
     - Diamonds: `j_greedy_joker` (+3 Mult), `j_rough_gem` ($1).
     - Hearts: `j_lusty_joker` (+3 Mult), `j_bloodstone` (x1.5 Mult).
     - Spades: `j_wrathful_joker` (+3 Mult), `j_arrowhead` (+50 Chips).
     - Clubs: `j_gluttonous_joker` (+3 Mult), `j_onyx_agate` (+7 Mult), `j_seeing_double` (x2 Mult).
  5. Face engines miss `j_smiley` (+5 Mult), `j_scary_face` (+30 Chips), `j_triboulet` (x2 Mult), and `j_caino`.

#### Defect E: Blind Card Targeting in `c_hanged_man`, `c_death`, and Enhancements
- **The Hanged Man (`c_hanged_man`)**:
  - `agent_v10.py` contains **no** override for `c_hanged_man`; it delegates directly to `agent_v9._tarot_action` (line 1541):
    ```python
    if game.state != State.SHOP or not weakest:
        return None
    t = weakest[:2]
    return {"type": "use_consumable", "consumable_idx": ci, "target_cards": t}
    ```
  - `weakest` is sorted by `_card_quality(c) = c.base_chips + ...` (line 1072). Rank 2 has 2 base chips; Rank 3 has 3 base chips.
  - If the player owns `j_wee`, `j_hack`, `j_fibonacci`, or `j_even_steven`, Rank 2 and 3 cards are sorted into `weakest[:2]`. `c_hanged_man` **destroys the exact low cards required by the engine**.
- **Death (`c_death`)**:
  - If `t["rank"]` is None, V9's fallback copies `best[0]` onto `weakest[0]`. If building 2s (Wee Joker/Hack), the 2s are in `weakest` and get overwritten by an off-engine high card.
- **Enhancement Tarots (`c_empress`, `c_hierophant`, `c_magician`)**:
  - In `_enhance_targets_biased` (line 713), only `t["rank"]` is checked. If `t["suit"]` is Hearts (e.g. `j_bloodstone` owned) or `t["face"]` is True, `_enhance_targets_biased` ignores suit and face status, enhancing arbitrary off-suit or non-face cards.
  - `c_justice` (Glass) is hardcoded to `0.0` value and never used, even when `j_glass_joker` (+0.75x mult per destroyed glass card) is owned.
  - `c_magician` (Lucky) gets no synergy bonus when `j_lucky_cat` (+0.25x mult per lucky trigger) is owned.

#### Defect F: Unconditional Skipping of Safe High-EV Spectrals
- In `agent_v9.py` line 1604 and lines 1734–1735:
  `if key in ("s_ankh", "s_hex", "s_ouija", "s_sigil"): return 0.0 / return None`
  - **Hex (`s_hex`)**: Adds Polychrome (x1.5 Mult) to a random joker and destroys all others. When `len(game.jokers) == 1` (very common in Antes 1–2), **zero jokers are destroyed**. It is a 100% free, zero-risk Polychrome upgrade on the sole engine anchor!
  - **Ankh (`s_ankh`)**: Copies a random joker and destroys all others. When `len(game.jokers) == 1`, **zero jokers are destroyed**. It duplicates the sole engine anchor with zero downside!
  - **Medium (`s_medium` / Purple Seal)**: Lines 1640–1645 put Purple Seal on `best[0]`. Purple Seal only triggers **on discard**. Putting it on the highest-scoring card creates a conflict: the agent wants to play that card, not discard it. Purple Seal belongs on weak/off-suit discard-fodder!
  - **Deja Vu (`s_deja_vu` / Red Seal)**: Retriggers card. It is placed on `best[0]` based purely on base chips, rather than target rank cards (e.g., King with Baron, face with Photograph) or enhanced cards.

#### Defect G: Planet Lag Behind Acquired Joker Portfolio
- `main_hand_type(game)` (line 1425) determines planet value:
  ```python
  def main_hand_type(game) -> str:
      counts = game.run_hand_counts
      ...
  ```
  `run_hand_counts` only tracks history. In Ante 1–2, a player might have played a Full House or High Card on Blind 1, but then purchased `j_runner` / `j_shortcut` (Straight engine), `j_tribe` / `j_droll` (Flush engine), or `j_duo` (Pair engine).
- The shop offers `pl_saturn`, `pl_jupiter`, or `pl_mercury`. `_v10_rank_shop_items` checks `PLANET_HAND.get(item.key) == main_hand_type(game)`. Because `main` hasn't caught up, the matching planet is valued at 0 and ignored.
- Furthermore, `j_constellation` (+0.1x mult per planet used) and `j_satellite` ($1/round per unique planet used) make **every** planet purchase profitable, yet non-main planets are completely ignored.

---

## 2. Logic Chain

1. **Premise 1 (Survival & Win Rate Drivers)**:
   - Ante 1–8 win rate is heavily governed by scaling and deck consistency. In White Stake, Red Deck starts with 52 standard cards and 2 consumable slots.
   - Every Tarot and Spectral used permanently modifies the deck composition ($N \le 52$) or joker pool ($M \le 5$).
   - Every Planet leveled provides permanent flat chips and mult to every hand of that type played for the rest of the run.

2. **Premise 2 (Slot Clearance Precedes Acquisition)**:
   - The simulator enforces strict slot caps: `game.consumable_slots = 2`.
   - Because consumables cannot be sold, any consumable in hand that is un-usable locks one of only two slots.
   - If two un-usable cards enter `consumable_hand`, slot acquisition capacity drops to zero for the remainder of the run.
   - Therefore, consumable usage policies must guarantee that held consumables are flushed/utilized whenever their retention provides zero passive value.

3. **Premise 3 (Reshaping Must Align with Joker Synergies)**:
   - Reshaping is only valuable if it increases the trigger frequency of acquired scoring and scaling jokers.
   - Stacking Kings when owning `j_baron` multiplies score exponentially ($(1.5)^K$). Stacking Aces when owning `j_scholar` adds $+20$ chips and $+4$ mult per card. Stacking 2s with `j_wee` scales the chip base permanently.
   - Conversely, destroying 2s with `c_hanged_man` or bumping 2s with `c_strength` while holding `j_wee` actively damages the run's win probability.
   - Therefore, `deck_reshape_target`, `_v10_tarot_action`, and `_reshape_card_bonus` must dynamically recognize all rank, rank-group, suit, and face engines in the portfolio.

4. **Premise 4 (Counterfactual Synergy in Shop & Booster Selection)**:
   - The decision to buy a Planet or open a Celestial Pack cannot rely solely on historical `main_hand_type`. It must evaluate the *portfolio target hand type* indicated by active jokers.
   - Celestial Packs must never be skipped when opened; taking any planet is strictly higher EV than wasting the purchase cost, and directly fuels `j_constellation`, `j_satellite`, and secondary fallback hands.
   - Safe spectral opportunities (Hex/Ankh on 1 joker) yield instantaneous Polychrome or joker duplication with zero marginal risk, dramatically increasing Ante 2–4 survival.

---

## 3. Detailed Code Recommendations for R2

### 3.1 Extended Engine Registries & Dynamic Reshaping Target

In `vendor/balatro-rl/balatro_sim/agent_v10.py`:

```python
# 1. Concrete rank engines: joker key -> target rank
_RANK_ENGINES = (
    ("j_baron", 13),           # King (x1.5 held)
    ("j_shoot_the_moon", 12),  # Queen (+13 Mult held)
    ("j_hit_the_road", 11),    # Jack (x0.5 per discarded Jack)
    ("j_cloud_9", 9),          # 9 ($1 per 9 in deck)
    ("j_scholar", 14),         # Ace (+20 Chips, +4 Mult played)
    ("j_walkie_talkie", 10),   # 10 (or 4; +10 Chips, +4 Mult played)
    ("j_wee", 2),              # 2 (+8 Chips permanent per 2 played)
)

# 2. Rank group engines: joker key -> set of valid ranks
_RANK_GROUP_ENGINES = {
    "j_even_steven": {2, 4, 6, 8, 10},
    "j_odd_todd": {3, 5, 7, 9, 11, 13, 14},
    "j_fibonacci": {14, 2, 3, 5, 8},
    "j_hack": {2, 3, 4, 5},
}

# 3. Fixed suit engines (corrected: j_golden removed, real suit jokers added)
_SUIT_ENGINES_FIXED = (
    ("j_golden", "Diamonds"),     # Kept for test compatibility (test_golden_targets_diamonds)
    ("j_rough_gem", "Diamonds"),
    ("j_greedy_joker", "Diamonds"),
    ("j_bloodstone", "Hearts"),
    ("j_lusty_joker", "Hearts"),
    ("j_arrowhead", "Spades"),
    ("j_wrathful_joker", "Spades"),
    ("j_onyx_agate", "Clubs"),
    ("j_gluttonous_joker", "Clubs"),
    ("j_seeing_double", "Clubs"),
)

_SUIT_ENGINES_DOMINANT = ("j_ancient", "j_blackboard", "j_tribe", "j_droll", "j_crafty", "j_smeared", "j_smeared_joker")

# 4. Extended face card engines
_FACE_ENGINES = (
    "j_photograph", "j_sock_and_buskin", "j_business", "j_business_card",
    "j_reserved_parking", "j_smiley", "j_scary_face", "j_triboulet",
    "j_caino", "j_pareidolia"
)

# 5. Hand-type to planet mappings supported by jokers
_JOKER_HAND_TYPES = {
    "j_runner": "Straight",
    "j_shortcut": "Straight",
    "j_four_fingers": "Straight",
    "j_superposition": "Straight",
    "j_crazy": "Straight",
    "j_devious": "Straight",
    "j_order": "Straight",
    "j_droll": "Flush",
    "j_crafty": "Flush",
    "j_tribe": "Flush",
    "j_bloodstone": "Flush",
    "j_smeared": "Flush",
    "j_smeared_joker": "Flush",
    "j_jolly": "Pair",
    "j_sly": "Pair",
    "j_duo": "Pair",
    "j_half": "Pair",
    "j_mad": "Two Pair",
    "j_clever": "Two Pair",
    "j_spare_trousers": "Two Pair",
    "j_trousers": "Two Pair",
    "j_zany": "Three of a Kind",
    "j_wily": "Three of a Kind",
    "j_trio": "Three of a Kind",
    "j_family": "Four of a Kind",
}
```

#### Enhanced `deck_reshape_target`
Update `deck_reshape_target(game)` in `agent_v10.py`:
1. Check `_RANK_ENGINES` first.
2. If none, check `_RANK_GROUP_ENGINES`. If an engine like `j_even_steven` or `j_fibonacci` is owned, select the majority rank in the deck that belongs to that engine's valid rank set (`t["rank"] = _majority_rank_in_set(dg, rank_set)`), and store `t["rank_set"] = rank_set`.
3. If none, check `_KIND_STACK_HANDS` or `_JOKER_HAND_TYPES` for 3-of-a-Kind, 4-of-a-Kind, or Full House to stack majority rank.
4. Check `_SUIT_ENGINES_FIXED`. If none, check `_SUIT_ENGINES_DOMINANT` or if portfolio indicates Flush.
5. If `j_lucky_cat` is owned, set `t["enh"] = "Lucky"`. If `j_steel_joker` is owned, set `t["enh"] = "Steel"`. If `j_glass_joker` is owned, set `t["enh"] = "Glass"`. If `j_drivers_license` is owned, set `t["enhanced_any"] = True`.

### 3.2 Revamped Tarot Action Logic (`_v10_tarot_action`)

1. **The Hanged Man (`c_hanged_man`) Integration**:
   - In `_v10_tarot_action`:
     ```python
     if key == "c_hanged_man":
         if game.state != State.SHOP or not hand:
             return None
         # Exclude target rank cards and rank_set cards from destruction
         safe_junk = []
         for i in weakest:
             c = hand[i]
             if t["rank"] is not None and c.rank == t["rank"]:
                 continue
             if t.get("rank_set") and c.rank in t["rank_set"]:
                 continue
             if t["face"] and c.is_face_card:
                 continue
             if t["suit"] is not None and c.suit == t["suit"]:
                 continue
             if c.enhancement != "None" or c.edition != "None" or c.seal != "None":
                 continue
             safe_junk.append(i)
         targets = safe_junk[:2] if safe_junk else weakest[:2]
         return {"type": "use_consumable", "consumable_idx": ci, "target_cards": targets}
     ```

2. **Strength (`c_strength`) Smart Targeting**:
   - If `t["rank"]` is set: target cards with rank `t["rank"] - 1` (or Ace `14` if target is `2`).
   - If `t.get("rank_set")`: target cards that are 1 rank below any member of `rank_set`. For example, with `j_even_steven`, target odd cards {3, 5, 7, 9} to convert them into even cards {4, 6, 8, 10}!
   - Never bump an already-target rank card.

3. **Death (`c_death`) Refined Source/Destination**:
   - If target rank/suit is defined, copy the best target card onto the weakest non-target card.
   - If target rank is None, but player holds pairs/trips, copy the rank with the highest multi-card count to advance toward Full House / Four of a Kind, rather than blindly copying an isolated high-card Ace.

4. **The Fool (`c_fool`) Contextual Copying**:
   - If `game.consumables_used` is not empty:
     - Check `last = game.consumables_used[-1]`.
     - If `last == "c_death"` or `last == "c_hermit"` (with `dollars >= 10`) or `last in PLANET_HAND`: use immediately!
     - If `last == "c_temperance"` and `sell_total >= 5`: use immediately!

5. **Enhancement Tarots Suit and Face Awareness**:
   - In `_enhance_targets_biased`:
     - Priority 1: Target rank cards with `enhancement == "None"`.
     - Priority 2: Target suit cards (if `t["suit"]` is active) with `enhancement == "None"`.
     - Priority 3: Target face cards (if `t["face"]` is active) with `enhancement == "None"`.
     - Priority 4: Highest quality remaining unenhanced cards.

6. **Fix Emperor and High Priestess Deadlock**:
   - Change condition from `len(game.consumable_hand) <= 1` to `len(game.consumable_hand) <= game.consumable_slots`:
     Because the card is popped before generating the replacements, using it from 2/2 slots frees a slot, allowing at least 1 new card to be generated safely without overflow.

### 3.3 Portfolio-Harmonized Planet Card Logic

1. **Portfolio-Aware Target Hand Type (`portfolio_target_hand(game)`)**:
   Create a helper that blends historical plays with active joker signals:
   ```python
   def portfolio_target_hand(game) -> str:
       keys = {j.key for j in game.jokers}
       for jk, ht in _JOKER_HAND_TYPES.items():
           if jk in keys:
               return ht
       return main_hand_type(game)
   ```
2. **Shop Planet Valuation in `_v10_rank_shop_items`**:
   - Let `target_ht = portfolio_target_hand(game)`.
   - If `PLANET_HAND.get(item.key) == target_ht`: value at `0.14` (raised from `0.08` so it outranks mediocre filler and is bought consistently).
   - If `PLANET_HAND.get(item.key) == main_hand_type(game)` and `target_ht != main`: value at `0.10`.
   - If any joker scales on planets (`j_constellation` owned): value **all** planets at `0.12`!
   - If `j_astronomer` owned: planet price is $0, value at `0.15`!
   - If `j_satellite` owned and `item.key not in game.planets_used`: value at `0.12` ($1/round compounding)!
3. **Prevent Celestial Pack Skips in `_v10_decide_booster`**:
   - When evaluating Celestial Pack choices:
     - Rank choices by:
       1. Planet matching `portfolio_target_hand(game)` (value 0.15)
       2. Planet matching `main_hand_type(game)` (value 0.12)
       3. If `j_constellation` owned, any planet (value 0.12)
       4. If `j_satellite` owned and unused, any planet (value 0.11)
       5. Fallback: Planet for High Card or Pair (value 0.08)
       6. Final fallback: Any planet with highest base scaling (value 0.07)
     - Never skip a Celestial Pack when slots are open!
4. **Flushing Held Planets in Pre-Shop**:
   - In `_v10_decide_shop` and `SearchShopV10.decide`:
     - If `len(game.consumable_hand) >= game.consumable_slots`:
       - Check if any held consumable is a Planet card.
       - Use it immediately! Even if off-target, using it grants permanent levels, fires Constellation/Satellite hooks, and frees the consumable slot for shop purchases.

### 3.4 Safe High-EV Spectral Deployment

In `_spectral_action`:
1. **Hex (`s_hex`)**:
   ```python
   if key == "s_hex":
       if len(game.jokers) == 1 and game.jokers[0].edition == "None":
           return {"type": "use_consumable", "consumable_idx": ci, "target_cards": []}
       return None
   ```
   If only 1 joker is owned and it has no edition: Hex is 100% free Polychrome (x1.5 Mult)!
2. **Ankh (`s_ankh`)**:
   ```python
   if key == "s_ankh":
       if len(game.jokers) == 1 and game.joker_slots >= 2:
           return {"type": "use_consumable", "consumable_idx": ci, "target_cards": []}
       return None
   ```
   If only 1 joker is owned: Ankh duplicates it with zero downside!
3. **Immolate (`s_immolate`)**:
   ```python
   if key == "s_immolate":
       if game.state == State.SHOP and (game.ante <= 2 or game.dollars < 15 or len(game.deck) > 35):
           return {"type": "use_consumable", "consumable_idx": ci, "target_cards": []}
   ```
4. **Medium (`s_medium` / Purple Seal)**:
   - Target `weakest[0]` (or lowest-quality off-suit card), because Purple Seal pays only on discard!
5. **Deja Vu (`s_deja_vu` / Red Seal)**:
   - Target target-rank card, face card, or enhanced card (Steel/Glass/Lucky) to maximize retrigger payoff!

### 3.5 Resolving the `save_mode` Consumable Barrier

In `agent_v10.py` shop ranking:
- Adjust `save_mode` logic so that exceptionally synergistic consumables are exempt from the `save_strong_value` 0.30 cutoff:
  - Exempt `c_hermit` (doubles money, generates interest).
  - Exempt `c_death` when `t["rank"]` or `t["suit"]` is active.
  - Exempt `portfolio_target_hand` planets when `dollars >= 15`.

---

## 4. Caveats

1. **Read-Only Explorer Scope**:
   - In compliance with explorer instructions, no simulator source files were modified during this investigation. Implementation must be carried out in a subsequent phase.
2. **Test Suite Invariants**:
   - `test_golden_targets_diamonds` in `test_agent_v10.py` explicitly tests `("j_golden", "Diamonds")`. `j_golden` must be retained in `_SUIT_ENGINES_FIXED` to avoid breaking existing unit tests.
3. **Farm-Off Baseline Guarantee**:
   - All enhancements in `agent_v10.py` must remain gated behind `farm_clear_threshold < 1.0` (or `reshape_enabled`) to preserve the byte-for-byte reproduction of the V9 baseline when the farm threshold is set to 1.0.

---

## 5. Conclusion

Requirement R2 addresses one of the most significant untapped performance levers in Optilatro:
1. **The current consumable system suffers from structural lockouts**: non-main planets and deadlocked tarots clog the 2 consumable slots, causing Celestial and Arcana booster packs to be skipped for 0 value.
2. **The deck-reshaping loop is severely incomplete**: `_RANK_ENGINES` only tracks 3 jokers (Baron, Cloud 9, Shoot the Moon), while critical scoring anchors (Scholar, Walkie Talkie, Wee Joker, Hack, Fibonacci, Even Steven, Odd Todd) are ignored. Suit engines contain erroneous mappings (`j_golden`) and omit real suit jokers (Bloodstone, Arrowhead, Onyx Agate, Lusty, Wrathful, Greedy, Gluttonous).
3. **The Hanged Man currently destroys engine cards**: Because it uses raw chip quality, it targets 2s and 3s, sabotaging Wee Joker, Hack, and Fibonacci builds.
4. **Spectrals possess unexploited free EV**: Hex and Ankh on a 1-joker build provide risk-free Polychrome and duplication, yet are unconditionally discarded.
5. **Implementing the proposed R2 harmonization** will resolve slot clogs, prevent wasted booster packs, accelerate deck conversion toward active joker anchors, and directly contribute to exceeding the 7.0% win rate threshold.

---

## 6. Verification Method

To verify the investigation and subsequent R2 implementation:

1. **Unit Test Suite Verification**:
   ```bash
   python -m pytest vendor/balatro-rl/tests/test_agent_v10.py -v
   python -m pytest vendor/balatro-rl/tests/test_e2e_v10_requirements.py -v
   python -m pytest vendor/balatro-rl/tests/test_consumables.py -v
   ```
2. **CI Exactness Gate**:
   ```bash
   python -m pytest vendor/balatro-rl/tests/test_seed_exactness.py -m ci_gate -v
   ```
3. **Static Audits**:
   ```bash
   python tools/audit_jokers_static.py
   python tools/audit_consumables_static.py
   python tools/audit_bosses_static.py
   python tools/audit_tags_static.py
   ```
4. **Behavioral Inspection**:
   - Verify `deck_reshape_target` with `j_scholar` (targets 14), `j_wee` (targets 2), `j_even_steven` (targets even ranks), `j_lusty_joker` (targets Hearts).
   - Verify `_v10_tarot_action` on `c_hanged_man` protects 2s when `j_wee` or `j_hack` is owned.
   - Verify `_spectral_action` on `s_hex` and `s_ankh` fires when `len(game.jokers) == 1`.
   - Verify `_v10_decide_booster` never skips a Celestial Pack when consumable slots are available.
