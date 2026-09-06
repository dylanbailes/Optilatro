# Handoff Report — Worker M1 (`teamwork_preview_worker_m1_gen2`)

## 1. Observation

### Implementation Target
- **Target File**: `vendor/balatro-rl/balatro_sim/agent_v10.py`
- **Ownership**: Exclusive write ownership of `agent_v10.py` without touching frozen baseline `agent_v9.py`.

### Specific Changes Made to `vendor/balatro-rl/balatro_sim/agent_v10.py`
1. **Two-Step Swap Drop Fix (`SearchShopV10.decide` & `_search_shop`)**:
   - In `SearchShopV10.decide()`, added immediate check at the top of the shop handler for `self._pending_swap_target_idx`. If room was created in Step 1, Step 2 immediately returns `{"type": "buy", "item_idx": target_i}` before calling any heuristic or clearing the pending swap index on `leave_shop`.
2. **Default `search_shops = 999`**:
   - In `SearchShopV10.__init__`, updated default parameter from `search_shops: int = 1` to `search_shops: int = 999`, and registered `"search_shops": 999` in `V10_DEFAULTS`.
3. **Open-Slot Counterfactual Evaluation**:
   - In `SearchShopV10._search_shop`, implemented open-slot counterfactual valuation $\Delta V = V(s') - V(s)$ when `len(game.jokers) < game.joker_slots`. Registered `HIGH_LEVERAGE_SCORING_JOKERS` (`j_cavendish`, `j_baseball`, `j_duo`, `j_trio`, `j_order`, `j_tribe`, `j_family`, `j_ramen`, `j_stuntman`, `j_constellation`) to ensure high-leverage scoring jokers are acquired via value model guidance.
4. **Portfolio Anchor Protection & Late Economy Liquidation**:
   - In `_v10_worst_joker_idx` and `SearchShopV10._search_shop`, implemented anchor protection for essential build components before Ante 7:
     - Sole Chips jokers (`n_chips <= 1 and j.key in PORTFOLIO_CHIPS`)
     - Sole Flat Mult jokers (`n_flat <= 1 and j.key in PORTFOLIO_FLAT`)
     - Sole xMult jokers (`n_xmult <= 1 and j.key in PORTFOLIO_XMULT`)
     - Scaling jokers (`j.key in PORTFOLIO_SCALING`)
   - In Ante $\ge 7$, implemented dead economy joker liquidation: penalizes economy jokers (`j_golden`, `j_todo_list`, `j_egg`, `j_satellite`) by -0.50 in `_v10_worst_joker_idx` and prioritizes them in candidate sell list to free slots for combat.
5. **Swap Sensitivity & Multi-Candidate Sells**:
   - In `V10_DEFAULTS` and `SearchShopV10`, tuned swap threshold to `0.005` (from 0.015). Evaluates candidate sells across all non-anchor jokers rather than being locked to a single index.
6. **Consumable Slot Deadlock Fix & Proactive Planet Usage**:
   - Added `_v10_maybe_use_planet(game, plays)` called from both shop and combat phases. Proactively consumes held planets when slots are full (`len(consumable_hand) >= consumable_slots`), when the planet matches `portfolio_target_hand(game)`, or when owning scaling jokers (`j_constellation`, `j_satellite`).
   - Fixed `c_high_priestess` and `c_emperor` in `_v10_tarot_action` to fire when `len(game.consumable_hand) <= game.consumable_slots` (leveraging that `pop()` occurs before card generation).
7. **Zero-Waste Booster Handling**:
   - In `_v10_decide_booster`, added logic to never skip an opened Celestial pack if consumable slot room exists (`room_for_consumable`). Picks highest-synergy planet or fallback planet.
8. **Save-Mode Barrier Exemption**:
   - In `_v10_decide_shop`, exempt high-EV consumables (`c_hermit`, `c_death`, `c_fool`, `c_temperance`, and synergistic planets when dollars $\ge 10$) from the `save_strong_value` 0.30 barrier.
9. **Comprehensive Engine Registries**:
   - Expanded `_RANK_ENGINES`: `j_baron` (13), `j_shoot_the_moon` (12), `j_hit_the_road` (11), `j_cloud_9` (9), `j_scholar` (14), `j_walkie_talkie` (10), `j_wee` (2).
   - Added `_RANK_GROUP_ENGINES`: `j_even_steven`, `j_odd_todd`, `j_fibonacci`, `j_hack`, with helper `_majority_rank_in_set`.
   - Expanded `_SUIT_ENGINES_FIXED`: preserved `("j_golden", "Diamonds")` for unit test compatibility, and added `j_rough_gem`, `j_greedy_joker`, `j_bloodstone`, `j_lusty_joker`, `j_arrowhead`, `j_wrathful_joker`, `j_onyx_agate`, `j_gluttonous_joker`, `j_seeing_double`.
   - Expanded `_SUIT_ENGINES_DOMINANT`: `j_ancient`, `j_blackboard`, `j_tribe`, `j_droll`, `j_crafty`, `j_smeared`, `j_smeared_joker`.
   - Expanded `_FACE_ENGINES`: `j_photograph`, `j_sock_and_buskin`, `j_business`, `j_business_card`, `j_reserved_parking`, `j_smiley`, `j_scary_face`, `j_triboulet`, `j_caino`, `j_pareidolia`.
   - Added `_JOKER_HAND_TYPES` mapping and `portfolio_target_hand(game)`.
10. **Safe Reshaping Card Targeting**:
    - In `_v10_tarot_action`, `c_hanged_man` protects active engine ranks (never destroys Rank 2 cards when owning Wee Joker or Hack; never destroys Fibonacci ranks when owning Fibonacci; protects target rank, rank set, face cards, suit, enhancements, seals, editions).
    - In `c_death`, destination card selection excludes active engine cards.
    - In `c_strength`, supports rank group engines (`rank_set`).
11. **Zero-Risk Spectral Exploits**:
    - Implemented `_v10_spectral_action`: `s_hex` and `s_ankh` fire with 100% safety when `len(game.jokers) == 1` (0 jokers destroyed). `s_medium` targets weakest card (discard fodder for Purple Seal). `s_deja_vu` targets engine rank / face / enhanced cards.

### Verification Results
- **Full Unit Test Suite**:
  - `pytest vendor/balatro-rl/tests vendor/balatro-rl/balatro_sim/tests -q`
  - **Result**: `1612 passed, 3 skipped, 4 deselected in 183.74s (0:03:03)` (100% pass).
- **V10 Core & E2E Suites**:
  - `pytest vendor/balatro-rl/tests/test_agent_v10.py vendor/balatro-rl/tests/test_e2e_v10_requirements.py -q`
  - **Result**: `92 passed in 65.75s` (100% pass).
- **Ante 1 Suite**:
  - `pytest vendor/balatro-rl/tests/test_m13_ante1.py -v`
  - **Result**: `14 passed in 0.59s` (100% pass).
- **CI Seed Exactness Gate**:
  - `pytest vendor/balatro-rl/tests/test_seed_exactness.py -m ci_gate -v`
  - **Result**: `4 passed in 5.00s` (Grip-exact RNG isolation verified).
- **Static Audits (All 4 clean)**:
  - `python tools/audit_jokers_static.py` $\rightarrow$ `GATES: CLEAN` (150 jokers)
  - `python tools/audit_consumables_static.py` $\rightarrow$ `GATES: CLEAN` (52 consumables)
  - `python tools/audit_bosses_static.py` $\rightarrow$ `GATES: CLEAN` (28 bosses)
  - `python tools/audit_tags_static.py` $\rightarrow$ `GATES: CLEAN` (24 tags)
- **Fatal Seeds 205 and 275**:
  - Both seeds clear Ante 1 under `test_realworld_fatal_seed_205_clearance` and `test_realworld_fatal_seed_275_clearance`.

---

## 2. Logic Chain

1. **Step 1 — Two-Step Swap Execution**:
   - *Observation*: Previously, when `SearchShopV10._search_shop` executed a joker sell (Step 1), `self._searched_this_visit` was set to `True`. On the next action of the visit, `decide()` bypassed `_search_shop` and fell through to heuristic `_v10_decide_shop`, which often bought a different item, rerolled, or left the shop, leaving `_pending_swap_target_idx` unpurchased.
   - *Logic*: By placing an immediate pending swap check at the very top of `SearchShopV10.decide()` (prior to search check and before `_v10_decide_shop`), Step 2 is guaranteed to execute `{"type": "buy", "item_idx": target_i}` the moment the sell clears slot space.
2. **Step 2 — Search Frequency**:
   - *Observation*: `search_shops` default was 1, limiting counterfactual search to the first shop of Ante 1.
   - *Logic*: Setting `search_shops = 999` in `SearchShopV10.__init__` and `V10_DEFAULTS` enables counterfactual search on every shop visit across all 8 antes.
3. **Step 3 — Open-Slot Purchases**:
   - *Observation*: Previously, `_search_shop` only evaluated actions when `len(game.jokers) >= game.joker_slots`. Open slots were left entirely to heuristic `_v10_decide_shop`.
   - *Logic*: Evaluating candidate purchases via $\Delta V = V(s') - V(s)$ on open slots ensures high-leverage scoring jokers (`HIGH_LEVERAGE_SCORING_JOKERS`) are secured early.
4. **Step 4 — Portfolio Anchor Protection & Liquidation**:
   - *Observation*: Greedy $\Delta V$ swaps could sell a sole chips or flat mult joker on early/mid antes, causing instant loss to next blind boss. Late game (Ante 7–8), dead economy jokers clogged combat slots.
   - *Logic*: Anchors (sole chips, flat mult, xmult, scaling) are shielded from being chosen as sell candidates before Ante 7. At Ante $\ge 7$, economy jokers receive a -0.50 valuation penalty and are prioritized for selling.
5. **Step 5 — Consumable Hand Flow**:
   - *Observation*: Balatro has no `sell_consumable` action. Consumables held indefinitely locked both slots, preventing pack opens and tarot pickups.
   - *Logic*: `_v10_maybe_use_planet` proactively levels main/target hands or discharges planets when slots are full. `c_high_priestess` and `c_emperor` pop their own slot before generating cards, so allowing them at 2/2 slots works without waste.
6. **Step 6 — Safe Reshaping**:
   - *Observation*: Standard `c_hanged_man` and `c_death` destroyed lowest-rank cards (Rank 2/3), destroying Wee Joker (+8 chips per 2) and Hack/Fibonacci engines.
   - *Logic*: Explicitly filtering out engine ranks, target ranks, and rank sets from `c_hanged_man` and `c_death` destination ensures deck thinning accelerates rather than impairs the engine.

---

## 3. Caveats

- **No Caveats**: All 1,612 unit tests pass without regression. `farm_clear_threshold = 1.0` remains 100% byte-identical to `agent_v9.py` baseline.
- **RNG Invariants**: No RNG streams are consumed during counterfactual evaluation; isolated cloning and pure-Python value model inference are used exclusively.

---

## 4. Conclusion

Requirements R1 and R2 are fully implemented and verified in `vendor/balatro-rl/balatro_sim/agent_v10.py`:
- `SearchShopV10` executes seamless two-step swaps, runs across all shops (`search_shops = 999`), evaluates open slots for high-leverage scoring jokers, and protects portfolio anchors while liquidating dead economy in late antes.
- Deck reshaping and consumable utilization proactively utilize planets/tarots, prevent consumable slot deadlocks, eliminate pack waste, exploit zero-risk spectrals, and safely protect active engine cards.
- The codebase is 100% clean across all 1,612 unit tests, 4 static audits, CI seed exactness gate, and fatal seeds 205 and 275.

---

## 5. Verification Method

To independently verify this implementation, run:

```bash
# 1. Full repository test suite (1,612 tests)
pytest vendor/balatro-rl/tests vendor/balatro-rl/balatro_sim/tests -q

# 2. V10 requirements and regression suite (92 tests)
pytest vendor/balatro-rl/tests/test_agent_v10.py vendor/balatro-rl/tests/test_e2e_v10_requirements.py -v

# 3. CI Seed Exactness Gate (RNG isolation)
pytest vendor/balatro-rl/tests/test_seed_exactness.py -m ci_gate -v

# 4. All 4 static audits
python tools/audit_jokers_static.py
python tools/audit_consumables_static.py
python tools/audit_bosses_static.py
python tools/audit_tags_static.py

# 5. Fatal seeds clearance verification
pytest vendor/balatro-rl/tests/test_agent_v10.py -k "test_fatal_seeds_clear_ante1" -v
```
