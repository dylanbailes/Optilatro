# Plan: Optilatro V11 Policy Optimization & Acceptance Benchmark

## Objective
Scale Optilatro's V11 search policy (agent_v11.py) from 14% toward a 20%-25% full-run win rate on Red Deck / White Stake by activating:
1. Universal Value Network shop scoring & early scaling growth (R1).
2. High-capital economy scaling & in-blind value squeezing (R2).
3. Mid-game deficit capital deployment (R3).
4. Strict human-fair invariants & preservation of baseline strengths (R4).

## Step-by-Step Execution Plan

### Step 1: Deep Design & Gap Analysis of agent_v11.py
- Analyze R1:
  - Universal Value Network shop scoring in _rank_shop_items_v11 for open slots AND full slots.
  - Calculate Delta V = V_theta(S u {i}) - V_theta(S) using evaluate_shop_value_v11 and counterfactual state formulation.
  - Augment candidate values with Delta V so agent actively acquires portfolio-completing jokers (chips, mult, xmult), Celestial packs, and engine tarots.
  - Apply scaling growth valuation (_v11_scaling_growth_bonus) with high weight in Antes 1-4 for scaling jokers (Green Joker, Ride the Bus, Supernova, Constellation).
- Analyze R2:
  - In-blind value squeezing when clear is guaranteed (P(clear) >= 0.98 or immediate clearing hand available with surplus hands):
    - multi-card face hands for j_business (/face card)
    - hold face cards for j_reserved_parking
    - play Lucky cards for + cash / +20 mult chances (amplified by retriggers and Red Seals)
    - harvest  discards for j_mail
    - Always prioritize beating blind before farming.
  - Econ joker valuation: Value economy generators (j_business, j_reserved_parking, j_mail, j_egg, j_gift, j_rocket) highly in early/mid antes when initial scoring anchor is present.
  - Tarot engine: heavily prioritize c_magician, c_chariot, c_empress, c_hierophant.
- Analyze R3:
  - Mid-game deficit capital deployment:
    - In Antes 2-5, if projected round score < 1.5x upcoming boss target (is_deficit), reduce interest floor to  (or <= ).
    - Allow up to 1 targeted reroll per shop visit when dollars >= reroll_cost + 4 to fish for scoring anchors when lacking combat jokers.
    - When in surplus, allow interest to compound normally up to the  cap.
- Analyze R4:
  - Human-fair: zero draw-order peeking, zero future-shop RNG peeking, throwaway RNGs.
  - Preserve Ante-1 conservative opening: if game.ante == 1: return _v10_decide_shop(...).
  - Restrict joker reordering strictly to copy jokers (j_blueprint, j_brainstorm) and j_ceremonial. Regular jokers must NOT be reshuffled if copy jokers aren't moving.
  - agent_v10.py and default_baseline_v10.json remain 100% frozen.

### Step 2: Implementation in agent_v11.py
- Implement _rank_shop_items_v11 and integrate into shop decision logic.
- Implement deficit capital deployment and reroll rules.
- Implement in-blind value squeezing in _v11_decide_hand.
- Cleanly refine _optimize_joker_order_v11 to strictly only reorder copy/ceremonial jokers around existing order.

### Step 3: Local Verification & Tests
- Run unit tests: pytest vendor/balatro-rl/tests/test_agent_v11.py -v.
- Run static audits: jokers, consumables, bosses, tags.
- Run seed exactness CI gate: pytest vendor/balatro-rl/tests/test_seed_exactness.py -m ci_gate -v.
- Run smoke tests on a small seed sample.

### Step 4: Full Paired Benchmark (Seeds 10500-10799, N=300)
- Run paired benchmark between search_shop_v10 and search_shop_v11.
- Verify win rate >= 20%, mean ante, capital spent, ante-1 deaths <= 4%.

### Step 5: Report Generation & Delivery
- Generate vendor/balatro-rl/results/bench_10500_10799_paired.html with full Section 8 telemetry bundle and McNemar test.
- Write handoff.md and report.md.
- Send final completion message.
