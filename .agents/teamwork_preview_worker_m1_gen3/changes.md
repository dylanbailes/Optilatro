# Summary of Changes: Milestone M1 (Core Policy Enhancement R1 + R2 + R3)

## 1. Overview
Implemented the full synthesis of R1, R2, and R3 policy enhancements in `vendor/balatro-rl/balatro_sim/agent_v10.py` without mutating live game state, without lookahead or RNG leakage, keeping `agent_v9.py` frozen as the baseline, and maintaining exact V9 byte-reproduction when `farm_clear_threshold = 1.0`.

---

## 2. Detailed File Changes

### A. `vendor/balatro-rl/balatro_sim/agent_v10.py`

#### R1: Late-Game Capital Deployment & Urgent Rerolls
- **Joker Catalogs & Synergies**:
  - Expanded `RELIABLE_XMULT_JOKERS` and defined `HIGH_LEVERAGE_SCORING_JOKERS` (`j_cavendish`, `j_duo`, `j_trio`, `j_family`, `j_order`, `j_tribe`, `j_card_sharp`, `j_baseball`, `j_acrobat`, `j_constellation`, `j_hologram`, `j_blueprint`, `j_brainstorm`, `j_baron`, `j_ancient`, `j_ramen`, `j_stuntman`, `j_photograph`).
- **Forecasting & Target Tracking**:
  - Added `_forecast_round_score(game, ref)` estimating round scoring output (hands_left * reference hand score).
  - Added `_ante_boss_target(game)` dynamically looking up or estimating the current Ante boss blind requirement.
- **Interest Floor Relaxation**:
  - In `_v10_decide_shop`:
    - Ante 8: `interest_target = 0` (spend down to $0).
    - Ante 7: `interest_target = 0` if `forecast < boss_target * 1.25` (deficit threshold).
    - Ante 6: `interest_target = 15` if lacking xMult jokers or scoring below 1.5x boss target.
- **Urgent Reroll Expansion**:
  - Relaxed reroll limits in late antes: Ante 8 cap 10, Ante 7 cap 6, Ante 6 cap 4.
  - Added purchase reserve buffer: only reroll if `capital_after_reroll >= 6` or Ante 8 last-ditch.
  - Fixed `SearchShopV10.decide`: cleared `self._searched_this_visit = False` upon rerolling to allow evaluating newly populated shop slots.
- **Worst-Joker Liquidation in Full-Slot Evaluation**:
  - Added `_joker_sell_value(j)` to safely extract sell value from `j.state.get("sell_value", ...)`.
  - In `_v10_rank_shop_items`: when jokers are full (5/5), credit `worst_sell` to available capital so high-leverage scoring jokers and xMult finishers can be purchased via room-making swaps.

#### R2: Synergistic Deck Reshaping & Targeted Consumables
- **Tiered Portfolio Target Hand**:
  - Refactored `portfolio_target_hand(game)` to select target hand types using `_HAND_ENGINE_PRIORITY`:
    1. xMult jokers (e.g. Tribe -> Flush, Trio -> Three of a Kind, Duo -> Pair).
    2. Scaling jokers (e.g. Spare Trousers -> Two Pair).
    3. Flat chip / +mult jokers.
    4. Defaults to `main_hand_type(game)` / High Card.
- **Target Engine Extensions**:
  - Extended `deck_reshape_target` to recognize `j_trio` (rank_set: top 3 ranks, min_copies: 3), `j_duo` (min_copies: 2), and face-dependent jokers (`j_photograph`, `j_face_joker`, `j_pareidolia`, `j_scary_face`, `j_smiley`) targeting `rank_set = {11, 12, 13}`.
- **Dynamic Tarot Valuation & Synergy Bonuses**:
  - In `_reshape_tarot_bonus`:
    - `c_death`: +0.22 if rank target active.
    - `c_strength`: +0.10 if rank target active (bonus if promoting to target or face rank).
    - `c_hanged_man`: +0.05 if suit target, +0.04 if face target.
    - `c_justice`: +0.16 if glass-scaling jokers owned (`j_glass`, etc.).
    - `c_magician`: +0.12 if `j_lucky_cat` owned.
- **Intelligent Tarot In-Shop Targeting**:
  - `c_death`: duplicates majority rank or highest-ranking target card onto non-target/lowest card.
  - `c_strength`: promotes rank 10 cards to rank 11 (Jacks) when face-synergies are owned; promotes adjacent ranks to target rank.
  - `c_hanged_man`: culls off-target low ranks while strictly protecting majority rank cards.
- **Consumable Flow & Shop Optimization**:
  - Save mode consumable exemption: exempts target planet cards and synergistic tarots from being hoarded when money is needed for high-leverage purchases.
  - Immediate Planet consumption: consumes planet cards directly in shop rather than holding in consumable inventory.
  - Booster pack slot checks: ensures celestial/arcana/spectral packs are purchased when space and capital permit.

#### R3: Scaling Joker Acceleration During Safe Blinds
- **Catalogs & Guardrails**:
  - Defined `SCALING_ACCEL_KEYS`: `{"j_ride_the_bus", "j_green_joker", "j_wee", "j_square_joker", "j_spare_trousers", "j_supernova"}`.
  - Defined `SCALING_BANNED_BOSSES`: `{"bl_needle", "bl_mouth", "bl_eye", "bl_grim", "bl_hook", "bl_tooth", "bl_pillar", "bl_psychic"}`.
  - Added non-face scoring verification `_has_scoring_face` and active scaling filter `_get_active_scaling_jokers`.
- **Hierarchical Safe Scaling Play Formulation**:
  - Implemented `_find_scaling_action(game, hand, plays, p_clear)`:
    - **Preconditions**: `hands_left >= 2`, target chips > 0, boss not in banned list, Ante 1 strict safety (`p_clear >= 0.99`).
    - **Tier S1 (Deterministic Knockout Reservation)**:
      - Discovers minimal-card clearing combos `k_combo` from `clearing_plays`.
      - Searches non-knockout indices (`i not in set(k_combo)`) for disjoint non-clearing plays that trigger owned scaling jokers.
      - 100% deterministic survival: `k_combo` remains untouched in hand for the following hand.
    - **Tier S2 (Probabilistic Safety)**:
      - Triggers when `p_clear >= 0.98` (or 0.995) and remaining hand output safely clears the blind.
    - **Joker Accelerations**:
      - `j_ride_the_bus`: +30 scaling value, strict non-face scoring guardrail (rejects any combo where scoring cards contain face cards).
      - `j_wee`: +100 per rank 2 card; automatically orders 2s to index 0 for Hanging Chad double retriggers.
      - `j_square_joker`: +40 scaling value for 4-scoring-card hands.
      - `j_spare_trousers`: +50 scaling value for Two Pair / Full House.
      - `j_green_joker`: +20 scaling value; also suppresses discards in `_tier1_survive` when blind is safe to preserve +1 Mult.
      - `j_supernova`: +10 scaling value for incremental hand increments.

---

### B. `vendor/balatro-rl/tests/test_scaling_acceleration.py`
New test suite verifying R3 scaling behavior with 9 targeted regression tests:
1. `test_scaling_suppressed_when_hands_left_one`: Confirms scaling is disabled when `hands_left < 2`.
2. `test_scaling_banned_on_dangerous_bosses`: Verifies scaling is suppressed on all 8 banned boss blinds.
3. `test_ride_the_bus_never_plays_scoring_face`: Asserts Ride the Bus plays safe non-face cards and never scores face cards.
4. `test_green_joker_suppresses_discard_when_safe`: Verifies Green Joker plays safe hands instead of discarding to avoid the -1 Mult penalty.
5. `test_wee_joker_prioritizes_twos_with_chad_at_index_zero`: Confirms Wee Joker prioritizes 2s and positions them at index 0 for Hanging Chad.
6. `test_square_joker_banks_four_scoring_cards`: Confirms Square Joker plays 4-card hands when safe.
7. `test_spare_trousers_banks_two_pair`: Confirms Spare Trousers plays Two Pair/Full House when safe.
8. `test_tier_s1_disjoint_knockout_preservation`: Confirms Tier S1 disjoint play completely preserves knockout combo K in hand.
9. `test_ante_1_isolation`: Confirms Ante 1 requires strict `p_clear >= 0.99` for scaling actions.
