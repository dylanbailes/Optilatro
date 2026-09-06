# Technical Investigation & Architecture Analysis: Requirement R2 (Synergistic Deck Reshaping & Targeted Consumables)

## Executive Summary

This report delivers an exhaustive, evidence-backed codebase audit of **Requirement R2 (Synergistic Deck Reshaping & Targeted Consumable Flow)** within the Optilatro search-first Balatro agent. It focuses on the core interaction between:
1. `vendor/balatro-rl/balatro_sim/agent_v10.py` (L0 heuristic decisions, deck reshaping targets, consumable usage, shop item valuation, pack selection).
2. `tools/portfolio.py` (Joker role categorization, deck composition feature extraction, and offline state valuation).
3. `vendor/balatro-rl/balatro_sim/agent_v9.py` (Baseline frozen oracle and default valuations).
4. `vendor/balatro-rl/balatro_sim/consumables.py` & `game.py` (Engine mechanics and consumable resolution).

### Core Findings & Identified Gaps
1. **Portfolio Classification vs. Consumable Valuation Disconnect**:
   - `tools/portfolio.py` classifies jokers into 6 strategic roles (`CHIPS`, `FLAT_MULT`, `XMULT`, `SCALING`, `ECON`, `RETRIGGER`) and extracts 50 state features. However, its shop evaluation function `evaluate_shop_candidates` completely ignores Tarots and Booster Packs, while handling Planets via a partial hardcoded feature map (tracking only Flush, Pair, Two Pair, and High Card).
   - In `agent_v10.py`, `SearchShopV10` only uses `portfolio.py` for evaluating full-slot Joker swaps (`type == "swap_joker"`), falling back entirely to `_v10_decide_shop` for all consumable, planet, and booster pack transactions.
2. **Priority Inversion & Dictionary Order Flaw in `portfolio_target_hand`**:
   - In `agent_v10.py` (lines 686–694), `portfolio_target_hand(game)` iterates over `_JOKER_HAND_TYPES.items()` in raw dictionary insertion order (`j_runner` first!).
   - If an agent possesses both a tier-1 xMult finisher like `j_family` (x4 Mult for Four of a Kind) and a common early chip joker like `j_sly` (+50 Chips for Pair), `portfolio_target_hand` returns `"Pair"`, completely blinding the agent to its win-condition engine.
3. **The `save_mode` Interest Deadlock on High-Leverage Consumables**:
   - In `_v10_decide_shop` (lines 1400–1420), when `game.ante > 2` and `game.dollars < 25`, the agent enters `save_mode` whenever the upcoming blind is forecast as beatable. In `save_mode`, purchases require `value >= 0.30` or `is_high_ev_consumable`.
   - `is_high_ev_consumable` is strictly hardcoded to `("c_hermit", "c_death", "c_fool", "c_temperance")`.
   - As a consequence, **synergistic Planet cards (value 0.14), rank/suit-fixing Tarots (Strength value 0.13, Hanged Man value 0.12, Suit conversions value 0.12), and Celestial booster packs (value 0.15–0.19) are systematically rejected and skipped** in Antes 3–7 while hoarding cash for $5 interest. The agent enters Ante 7/8 with level-1 or level-2 hands and un-reshaped decks.
4. **Booster Pack Consumable-Inventory Trap**:
   - In `game.py` (line 1427), picking a planet/tarot from a booster pack appends the string to `game.consumable_hand` if `len(game.consumable_hand) < game.consumable_slots`. If full, the card is silently dropped.
   - `_v10_decide_booster` checks `room_for_consumable = len(game.consumable_hand) < game.consumable_slots`. When `room_for_consumable` is False, all planet/tarot choices receive a valuation of `0.0`, resulting in `{"type": "skip_booster"}`.
   - Crucially, `_v10_rank_shop_items` (lines 1315–1324) checks open consumable slots for individual Tarots, Planets, and Spectrals, **but NEVER checks consumable slots for Booster Packs** (`p_celestial*`, `p_arcana*`, `p_spectral*`). An agent with 2/2 full consumable slots will spend $4–$8 buying a Celestial or Arcana pack, enter `State.BOOSTER_OPEN`, find no room, and immediately skip the pack, throwing away capital.
5. **Tarot Targeting Deficiencies**:
   - **Death (`c_death`)**:
     - Fails to target Face cards (`t["face"] = True` for Photograph, Smiley, Sock and Buskin, Scary Face, Triboulet). Because `t["face"]` does not set `t["rank"]` or `t["suit"]`, line 1087 evaluates to False and Death falls back to generic V9 targeting (`best[0]` onto `weakest[0]`).
     - Fails rank concentration for `j_trio` (Three of a Kind) and `j_duo` (Pair) because `deck_reshape_target` only activates `t["rank"] = _majority_rank` for `j_family`.
     - When both `t["rank"]` and `t["suit"]` are active (e.g. Bloodstone + Scholar), line 1090 branches exclusively into `t["rank"]`, which may copy an off-suit rank card onto a target-suit card, destroying flush synergy.
   - **Strength (`c_strength`)**:
     - Completely ignores Face card engines (`t["face"]`), failing to promote 10s into Jacks (rank 10 -> 11), which would create new face cards to trigger Photograph (x2 Mult), Smiley (+5 Mult), and Scary Face (+30 Chips).
     - Does not backfill the second target card if only one `target_r - 1` card is present.
   - **Hanged Man (`c_hanged_man`)**:
     - Does not protect majority ranks when `j_trio` or `j_duo` is owned, allowing thinning of key duplicate cards.
     - Awards zero value bonus (`_reshape_tarot_bonus` returns 0.0) when only `t["suit"]` or `t["face"]` is active, despite deck thinning being the fastest route to high suit/face concentration.
   - **Justice (`c_justice`) & Magician (`c_magician`)**:
     - `c_justice` has static value `0.0` in `agent_v9.py` and receives `0.0` in `_reshape_tarot_bonus`, meaning it is never bought in the shop or picked from packs, even when `j_glass_joker` is owned.
     - `c_magician` receives no synergy bonus when `j_lucky_cat` is owned.
6. **Planet Valuation & Utilization Bottlenecks**:
   - `planet_value(game, ht)` (lines 1570–1590) calculates actual fractional hand-level EV, but is solely utilized for Blue Seal round-end calculation (`triggers · planet_value(ht)`). Shop planet ranking relies on flat static numbers (0.14 vs 0.10).
   - In the shop, `_v10_maybe_use_planet` only uses planets if `ht == target_ht or ht == main_ht or slots_full`. It holds onto non-target planets, clogging consumable inventory and preventing new shop/pack purchases.

---

## Detailed Component Analysis

### 1. Joker Classification & Deck Composition in `tools/portfolio.py`

#### 1.1 Classification Mechanism
`tools/portfolio.py` defines 6 mutually inclusive sets of jokers:
```python
CHIPS_JOKERS: set[str]       # 23 jokers
FLAT_MULT_JOKERS: set[str]   # 37 jokers
XMULT_JOKERS: set[str]       # 32 jokers
SCALING_JOKERS: set[str]     # 39 jokers (chips, mult, xmult, econ)
ECON_JOKERS: set[str]        # 34 jokers (cash, interest, consumables)
RETRIGGER_JOKERS: set[str]   # 12 jokers
UTILITY_JOKERS: set[str]     # 19 jokers
```
`classify_joker(key: str) -> dict[str, bool]` handles canonical keys and aliases through `normalize_joker_key(key)`.

#### 1.2 Deck Composition Features (`extract_features_from_state` lines 393–407)
```python
d_size = max(1, deck_size)
max_suit = max(suit_counts.values(), default=0) if suit_counts else 0
suit_conc = max_suit / d_size
face_ratio = face_count / d_size
enh_ratio = enhanced_count / d_size
seal_ratio = sealed_count / d_size
```
**Identified Gaps in Feature Extraction**:
- **No Rank Concentration**: `rank_conc = max(rank_counts) / d_size` is missing. Rank concentration is the primary physical metric for Pair, Three of a Kind, Four of a Kind, and Full House builds.
- **No Ace Ratio**: Aces (rank 14) are excluded from `face_count` (which only checks 11, 12, 13). Scholar and Fibonacci specifically demand Ace metrics.
- **Aggregate Hand Levels**: Features only track `flush_lvl`, `pair_lvl`, `two_pair_lvl`, `high_card_lvl`, ignoring `three_of_a_kind_lvl`, `straight_lvl`, `full_house_lvl`, and `four_of_a_kind_lvl`.

---

### 2. Consumable Shop Valuation & Selection Flow

#### 2.1 Code Path in `agent_v10.py`
In `_v10_rank_shop_items(game, ref, surplus, rerolls_used)`:
1. **Planets** (lines 1335–1352):
   ```python
   target_ht = portfolio_target_hand(game)
   main_ht = main_hand_type(game)
   item_ht = PLANET_HAND.get(item.key)
   val = 0.05
   if item_ht == target_ht:
       val = 0.14
   elif item_ht == main_ht:
       val = 0.10
   elif any(j.key == "j_constellation" for j in game.jokers):
       val = 0.12
   elif any(j.key == "j_satellite" for j in game.jokers) and item.key not in getattr(game, "planets_used", set()):
       val = 0.12
   if val >= p["buy_threshold"] and len(game.consumable_hand) < game.consumable_slots:
       buys.append((val, i))
   ```
2. **Tarots** (lines 1353–1357):
   ```python
   value = _v10_tarot_value(game, item.key)
   if (value >= p["buy_threshold"] and len(game.consumable_hand) < game.consumable_slots):
       buys.append((value, i))
   ```
3. **Booster Packs** (lines 1315–1324):
   ```python
   value = pack_value(game, item.key)
   if game.ante == 1 and item.key.startswith("p_buffoon") and V10_PARAMS["farm_clear_threshold"] < 1.0:
       value += V10_PARAMS.get("ante1_buffoon_boost", 0.20)
   if game.ante == 1 and item.key.startswith("p_celestial") and V10_PARAMS["farm_clear_threshold"] < 1.0:
       value += V10_PARAMS.get("ante1_celestial_bonus", 0.0)
   if value >= p["buy_threshold"]:
       buys.append((value, i))
   ```

#### 2.2 The `save_mode` Blocker
In `_v10_decide_shop` (lines 1400–1420):
```python
save_mode = (
    game.ante > 2
    and game.dollars < p["interest_target"]
    and max((v for v, _ in buys), default=0.0) < p["save_strong_value"]
    and forecast_beatable(game, p["save_margin"], ref)
)
# ...
if (price <= game.dollars
        and (not save_mode or value >= p["save_strong_value"] or is_high_ev_consumable)
        and worth_spending(game, price, value)):
    return {"type": "buy", "item_idx": idx}
```
Where:
- `p["interest_target"] = 25`
- `p["save_strong_value"] = 0.30`
- `is_high_ev_consumable = item.key in ("c_hermit", "c_death", "c_fool", "c_temperance")`

**Impact**:
Whenever bankroll is under $25 and the upcoming blind can be beaten by `ref.ceiling * 1.20`:
- Planet cards with `value = 0.14` are skipped.
- Tarot cards with `value = 0.12 - 0.16` (except Hermit, Death, Fool, Temperance) are skipped.
- Celestial packs with `value = 0.15 - 0.19` are skipped.
This starves the run of scaling stats in mid-game (Antes 3–6), guaranteeing failure in Antes 7–8.

---

### 3. Tarot Targeting Logic Analysis

#### 3.1 Death (`c_death`)
**Current Implementation** (`agent_v10.py` lines 1087–1104):
```python
if key == "c_death" and (t["rank"] is not None or t["suit"] is not None):
    if t["rank"] is not None:
        src = next((i for i in best if hand[i].rank == t["rank"]), None)
        dst = next((i for i in weakest if hand[i].rank != t["rank"]
                    and not (t.get("rank_set") and hand[i].rank in t["rank_set"])
                    and not (hand[i].rank == 2 and "j_wee" in keys)
                    and not (hand[i].rank in (2, 3, 4, 5) and "j_hack" in keys)
                    and not (hand[i].rank in (14, 2, 3, 5, 8) and "j_fibonacci" in keys)), None)
    else:
        src = next((i for i in best if hand[i].suit == t["suit"]), None)
        dst = next((i for i in weakest if hand[i].suit != t["suit"]), None)
    if src is not None and dst is not None and src != dst:
        return {"type": "use_consumable", "consumable_idx": ci,
                "target_cards": [dst, src]}
    return None
```
**Anomalies & Missing Synergies**:
1. **Face Card Neglect**: If `t["face"]` is True (e.g. Photograph / Smiley / Sock & Buskin owned), but neither `t["rank"]` nor `t["suit"]` is active, Death falls through to V9's naive `[weakest[0], best[0]]`. It fails to seek a face card as `src` and can overwrite face cards as `dst`.
2. **Rank vs Suit Collision**: When an agent holds both a rank engine (e.g. `j_scholar` for Aces) and a suit engine (e.g. `j_bloodstone` for Hearts), the `if t["rank"] is not None:` branch completely ignores `t["suit"]`. It will happily copy an Ace of Spades onto a 2 of Hearts, destroying heart concentration.
3. **Restricted Rank Stacking**: `t["rank"]` is only set if a fixed rank joker is owned or `j_family` is owned. It is NOT set for `j_trio` (Three of a Kind, x3 Mult) or `j_duo` (Pair, x2 Mult).

#### 3.2 Strength (`c_strength`)
**Current Implementation** (`agent_v10.py` lines 1105–1115):
```python
if key == "c_strength" and (t["rank"] is not None or t.get("rank_set")):
    target_r = t["rank"]
    near = []
    if target_r is not None:
        near = [i for i in weakest if hand[i].rank == target_r - 1][:2]
    if not near and t.get("rank_set"):
        near = [i for i in weakest if (hand[i].rank + 1) in t["rank_set"] and hand[i].rank not in t["rank_set"]][:2]
    if near:
        return {"type": "use_consumable", "consumable_idx": ci,
                "target_cards": near}
    return _tarot_action(game, ci, key, hand, best, weakest)
```
**Anomalies & Missing Synergies**:
1. **Face Card Genesis Ignored**: When `t["face"]` is True, any 10 (rank 10) in hand can be promoted to a Jack (rank 11), creating an instant face card. Strength completely ignores `t["face"]`.
2. **Greedy 1-Card Exit**: If `near` only finds one card matching `target_r - 1`, it immediately returns `target_cards: [near[0]]`, failing to look for a second card from `rank_set` or face creation.

#### 3.3 Hanged Man (`c_hanged_man`)
**Current Implementation** (`agent_v10.py` lines 1057–1082):
- Filters cards from `weakest` to exclude target rank, rank set, Wee (2), Hack (2,3,4,5), Fibonacci (14,2,3,5,8), Face cards (if `t["face"]`), target suit (if `t["suit"]`), and enhanced/sealed/editioned cards.
- Deletes up to 2 cards in the shop.
**Anomalies**:
- While card destruction logic is sound, its purchase valuation in `_reshape_tarot_bonus` (line 803) only awards `+0.03` when `t["rank"] is not None`. It awards `0.0` when `t["suit"]` or `t["face"]` is active! Thinning 2 off-suit cards from a 52-card deck raises suit concentration from 25.0% to 26.0%, and thinning 4 off-suit cards raises it to 27.1%, which is the single most reliable way to guarantee 5-card flushes.

---

### 4. Planet Valuation & Celestial Pack Logic

#### 4.1 Hand Priority Resolution
In `agent_v10.py`:
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
Where `_JOKER_HAND_TYPES` is an unordered dictionary:
```python
_JOKER_HAND_TYPES = {
    "j_runner": "Straight",
    "j_shortcut": "Straight",
    "j_four_fingers": "Straight",
    "j_superposition": "Straight",
    "j_crazy": "Straight",
    "j_devious": "Straight",
    "j_order": "Straight",
    "j_droll": "Flush",
    # ...
    "j_family": "Four of a Kind",
}
```
**Flaw**:
Because Python dictionaries iterate in insertion order, `j_runner` or `j_sly` precedes `j_family`!
If an agent owns:
- `j_family` (x4 Mult on Four of a Kind)
- `j_sly` (+50 Chips on Pair)
`portfolio_target_hand` sees `j_sly` at position 15 and returns `"Pair"`.
The Celestial packs and Planet purchases then prioritize Mercury (Pair) over Mars (Four of a Kind), crippling the build.

#### 4.2 Proactive Planet Utilization
In `_v10_maybe_use_planet` (lines 1213–1216):
```python
if game.state == State.SHOP:
    if ht == target_ht or ht == main_ht or has_constellation or has_satellite or slots_full:
        return {"type": "use_consumable", "consumable_idx": ci, "target_cards": []}
```
If an agent holds a planet that does not match `target_ht` or `main_ht`, and slots are not full (e.g. 1/2), it hoards the planet in inventory. This blocks subsequent Tarot purchases and clogs booster pack opening. In Balatro, hand level upgrades are permanent and carry no negative side-effects; any held planet should be used proactively in the shop.

---

## Strategic Recommendations for R2 Implementation

### 1. Robust Joker Hand Hierarchy (`portfolio_target_hand`)
Replace unweighted dictionary iteration with a tiered priority classification:
- **Tier 1 (xMult Hand Engines)**:
  - `j_family` -> `"Four of a Kind"`
  - `j_order` -> `"Straight"`
  - `j_tribe` -> `"Flush"`
  - `j_trio` -> `"Three of a Kind"`
  - `j_duo` -> `"Pair"`
- **Tier 2 (Scaling Hand Engines)**:
  - `j_spare_trousers`, `j_trousers` -> `"Two Pair"`
  - `j_runner` -> `"Straight"`
- **Tier 3 (Flat Mult & Chip Hand Synergies)**:
  - `j_crafty`, `j_droll`, `j_bloodstone` -> `"Flush"`
  - `j_clever`, `j_mad` -> `"Two Pair"`
  - `j_wily`, `j_zany` -> `"Three of a Kind"`
  - `j_sly`, `j_jolly` -> `"Pair"`
  - `j_devious`, `j_crazy` -> `"Straight"`
- **Tier 4 (High Card Enablers)**:
  - `j_baron`, `j_mime` -> `"High Card"`
- **Tier 5 (Run History Fallback)**:
  - `main_hand_type(game)` if played $\ge 2$ times, else `"Pair"` / `"High Card"`.

### 2. Comprehensive Deck Reshaping Target (`deck_reshape_target`)
Extend `deck_reshape_target`:
1. **Rank Stacking**:
   - Activate `t["rank"] = _majority_rank(dg)` not only for `j_family`, but also for `j_trio`, `j_duo`, or whenever Tier 1/2 target hand is Four of a Kind, Three of a Kind, or Pair.
2. **Face Engines Commitment**:
   - When `t["face"]` is True (Photograph, Smiley, Sock & Buskin, Scary Face, Triboulet), explicitly expose `t["rank_set"] = {11, 12, 13}` if no fixed rank engine is active.
3. **Suit Engines Synergy**:
   - Ensure `_SUIT_ENGINES_FIXED` covers `j_bloodstone` (Hearts), `j_onyx_agate` (Clubs), `j_arrowhead` (Spades), `j_rough_gem` (Diamonds).

### 3. Dynamic Tarot Targeting Enhancements
1. **Death (`c_death`)**:
   - If `t["face"]` is True and `t["rank"]` is None:
     - `src`: highest quality face card in hand (`is_face_card` or rank in 11..13), prioritizing enhanced/editioned copies.
     - `dst`: lowest quality non-face card in hand (excluding engine ranks).
   - If both `t["rank"]` and `t["suit"]` are active:
     - `src` prioritizes matching BOTH `rank == t["rank"]` and `suit == t["suit"]`.
     - `dst` must NOT match `t["suit"]` if avoidable.
   - If `t.get("rank_set")`:
     - If `t["rank"]` is absent from hand, fall back to any card in hand matching `t["rank_set"]`.
2. **Strength (`c_strength`)**:
   - If `t.get("face")` is True:
     - Target any 10 (rank 10) in hand to promote to Jack (rank 11).
   - If `t["rank"]` is active (e.g. 14 for Scholar):
     - Target rank 13 (King) to promote to Ace (14).
   - Fill both available targets (up to 2 cards) across near-rank and face promotions.
3. **Hanged Man (`c_hanged_man`)**:
   - Protect majority rank when `j_trio` / `j_duo` is active.
   - Boost shop purchase valuation in `_reshape_tarot_bonus` when `t["suit"]` (+0.05) or `t["face"]` (+0.04) is active.
4. **Justice & Special Enhancements**:
   - In `_reshape_tarot_bonus`: If `j_glass_joker` is owned, grant `c_justice` a strong bonus (+0.16) so it is acquired and utilized.
   - If `j_steel_joker` or `j_baron` is owned, boost `c_chariot` (+0.10).
   - If `j_lucky_cat` is owned, boost `c_magician` (+0.10).

### 4. Unlocking Consumable & Planet Purchases in `save_mode`
In `_v10_decide_shop`:
- Expand `is_high_ev_consumable` to include:
  1. Any Planet card matching `target_ht` (the portfolio's primary hand type).
  2. Any Tarot card matching active deck reshape targets:
     - Suit conversion tarots when matching `t["suit"]`.
     - `c_strength` when near-target cards are in deck.
     - `c_hanged_man` when junk cards exist.
     - `c_justice` when `j_glass_joker` is owned.
     - `c_chariot` when `j_steel_joker` or `j_baron` is owned.
- In Antes 6–8, relax `p["save_strong_value"]` and the $25 interest floor so that active engines aggressively buy target planets and reroll for finishing xMult.

### 5. Consumable-Slot Guard for Booster Pack Purchases
In `_v10_rank_shop_items`:
- For `item.kind == "booster"`:
  - If `item.key.startswith(("p_celestial", "p_arcana", "p_spectral"))`:
    - Only consider buying if `len(game.consumable_hand) < game.consumable_slots`.
    - This eliminates the bug where $4–$8 is spent to buy a booster pack that is immediately skipped due to zero open consumable slots.
- In `_v10_maybe_use_planet`:
  - In shop state, immediately consume ALL held planets to free consumable slots for incoming shop items and packs.

---

## Verification & Isolation Guarantees

All proposed enhancements strictly uphold the system's core invariants:
1. **Zero Peeking at Draw Order**: All deck-reshaping and consumable targeting metrics read strictly from `deck_groups(game)`, `game.hand`, or multiset aggregations. No positional deck indexing is ever used.
2. **Zero RNG Mutation**: Consumable valuation and target selection perform zero RNG calls and do not touch `game.rng`.
3. **Zero Live Game Mutation During Valuation**: Evaluated actions operate on pure copied structures or pass index lists to `use_consumable`.
4. **CI Exactness Gate**: Unaffected; `tests/test_seed_exactness.py -m ci_gate` remains 100% compliant.
