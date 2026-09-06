# Original User Request

## Initial Request — 2026-09-02T21:37:46Z

Implement an end-to-end improvement for the Optilatro search-first Balatro AI to break the 7% win rate and 5% Ante 1 death ceiling on Red Deck / White Stake under strict human-fair constraints.

Working directory: D:/Optilatro
Integrity mode: development

## Requirements

### R1. Ante-1 In-Blind Multi-Hand Pace Rule
Implement a multi-hand budget rule in `vendor/balatro-rl/balatro_sim/agent_v10.py` that checks whether the best playable hand meets the per-hand target pace (`(target - scored) / hands_left`). If on pace, play the hand immediately rather than gambling discards on low-probability structural upgrades (e.g. chasing Full Houses from Two Pairs on Small Blind).

### R2. Joker Portfolio Classification & State Feature Extraction
Provide a structured feature extractor (`tools/portfolio.py`) that categorizes jokers into the core strategic roles (Chips, Flat Mult, xMult, Scaling, Economy, Retrigger) and extracts progression, financial, synergy, and deck composition features for both live and counterfactual shop states.

### R3. Rollout Dataset Generation & Offline Value Model
Generate a dataset of perturbed rollout games (`tools/gen_shop_dataset.py`) sampling shop transitions (buying xMult/scaling jokers and selling redundant economy jokers). Train an offline state value model $V(s') \rightarrow P(\text{Win Ante 8})$ (`tools/fit_shop_model.py`) incorporating key interaction terms, and export lightweight weights (`vendor/balatro-rl/balatro_sim/shop_model.json`) evaluable in pure Python/NumPy with zero external runtime dependencies.

### R4. True L1 Counterfactual Shop Search (`SearchShopV10`)
Upgrade `SearchShopV10._search_shop` in `agent_v10.py` / `agent_l1.py` to evaluate candidate shop actions (buy, sell, swap, reroll, leave) by predicting post-action state value $V(s')$, executing actions with positive $\Delta V = V(s') - V(s)$ and making room by selling the lowest-value/redundant jokers.

## Acceptance Criteria

### Baseline & Integrity Verification
- [ ] All 1,562+ existing simulator unit tests pass: `python -m pytest vendor/balatro-rl/tests vendor/balatro-rl/balatro_sim/tests -q`.
- [ ] CI seed exactness gate passes: `python -m pytest vendor/balatro-rl/tests/test_seed_exactness.py -m ci_gate -v`.
- [ ] All static audits remain clean: `python tools/audit_jokers_static.py`, `python tools/audit_consumables_static.py`, `python tools/audit_bosses_static.py`, `python tools/audit_tags_static.py`.
- [ ] Strictly human-fair: no peeking at deck draw order or future shop/boss RNG streams.

### Benchmark & Performance Targets
- [ ] Ante 1 Small Blind fatal seeds (seed 205 and seed 275) clear Ante 1 successfully.
- [ ] Dev bank (seeds 0–199 paired A/B): Win rate >= 8.0% and Ante 1 death rate < 5.0%.
- [ ] Full benchmark bank (seeds 0–299 paired against `goal_iter7_final_D.json` baseline of 20W / 14D): Win rate > 7.0% (> 21 wins) and Ante 1 deaths < 14 (< 4.67%).
- [ ] Out-of-sample holdout bank (seeds 300–499 and 500–699): Verified generalization to ensure improvements do not stem from bank overfitting.

## Follow-up — 2026-09-03T20:10:17Z

Optimize and advance the Optilatro Balatro AI agent to break through the 7.0% win rate ceiling (> 21 wins / 300) and maintain Ante 1 mortality below 4.67% (< 14 deaths / 300) on Red Deck / White Stake under strict human-fair constraints.

Working directory: D:/Optilatro
Integrity mode: development

## Context & Current State
- **Phase 1 (Ante-1 Pace Rule)**: Implemented in `vendor/balatro-rl/balatro_sim/agent_v10.py` (`ante1_pace_rule`). Seeds 205 and 275 clear Ante 1.
- **Phase 2 (Portfolio Classification)**: Implemented in `tools/portfolio.py` with 6 strategic joker roles and 50 state features.
- **Phase 3 (Offline Value Model)**: Trained on 67,860 samples (holdout AUC 0.7822) in `vendor/balatro-rl/balatro_sim/shop_model.json`. Pure Python/NumPy inference in <10 µs.
- **Phase 4 (L1 Counterfactual Search)**: Implemented in `SearchShopV10._search_shop` evaluating $\Delta V = V(s') - V(s)$ on `_v10_worst_joker_idx`.
- **Verified Suite**: All 1,600+ tests pass (`test_agent_v10.py`, `test_e2e_v10_requirements.py`, `test_m13_ante1.py`), CI exactness gate is clean, and all 4 static audits are clean.
- **Empirical Baseline**: On Seeds 0–99, Ante 1 death rate dropped to 4.00% and `search_shop_v10` won 5/100 (5.00%). Across Seeds 0–299, baseline `goal_iter7_final_D.json` achieved 20 wins (6.67%) with 14 Ante-1 deaths (4.67%).

## Requirements

### R1. Win-Rate Bridge & Search Tuning
Tune `SearchShopV10` swap delta threshold, candidate selection, and synergies with `_v10_decide_shop` to ensure high-leverage scoring jokers (e.g. Cavendish, Baseball Card, Duo/Trio/Family, Ramen, Stuntman) are consistently secured and transitioned into without selling essential portfolio anchors.

### R2. Deck Reshaping Synergy & Consumable Utilization
Ensure tarot deck-reshaping and spectral/planet usage harmonize with the acquired joker portfolio (e.g. prioritizing Death/Strength on target ranks and Planet cards on primary hand types).

### R3. Human-Fair & Isolation Guarantees
Maintain strict human-fairness: zero peeking at draw order, zero future RNG stream consumption, zero live game mutation during evaluation. `test_seed_exactness.py -m ci_gate` must stay green.

## Acceptance Criteria

### Baseline & Integrity Verification
- [ ] All 1,600+ simulator unit tests pass: `python -m pytest vendor/balatro-rl/tests vendor/balatro-rl/balatro_sim/tests -q`.
- [ ] CI seed exactness gate passes: `python -m pytest vendor/balatro-rl/tests/test_seed_exactness.py -m ci_gate -v`.
- [ ] All 4 static audits remain clean: `python tools/audit_jokers_static.py`, `python tools/audit_consumables_static.py`, `python tools/audit_bosses_static.py`, `python tools/audit_tags_static.py`.

### Benchmark & Performance Targets
- [ ] Full benchmark bank (Seeds 0–299 paired against `goal_iter7_final_D.json` baseline of 20W / 14D):
  - Win rate $> 7.0\%$ ($> 21$ wins out of 300).
  - Ante 1 deaths $< 14$ ($< 4.67\%$).
- [ ] Out-of-sample holdout bank (Seeds 300–499):
  - Verified generalization showing consistent win rate and low Ante 1 mortality without bank overfitting.

## 2026-09-04T06:41:04Z

Advance the Optilatro search-first Balatro AI agent to break through the 10.0%+ win rate threshold (>= 30 wins / 300) while keeping Ante 1 mortality below 4.0% (< 12 deaths / 300) on Red Deck / White Stake under strict human-fair constraints.

Working directory: D:/Optilatro
Integrity mode: development

## Context & Current State
- **Current Milestone**: `search_shop_v10` achieves **8.67% win rate (26/300)** and **3.67% Ante-1 mortality (11/300)** on Seeds 0–299 (sidecar: `vendor/balatro-rl/results/bench_0_299_search_shop_v10.json`).
- **Verified Suite**: All 1,600+ test suite tests pass, CI seed exactness gate passes 4/4 (`test_seed_exactness.py -m ci_gate`), and all 4 static audits are clean.
- **Identified Growth Levers**:
  1. *Late-Game Capital Deployment & Urgent Rerolls*: In Antes 6–8, the current policy often dies holding $25+ in bankroll. When forecasted score cannot clear upcoming Ante 7/8 targets, relax the interest reserve and aggressively reroll for premier xMult finishers (Cavendish, Baseball Card, Duo/Trio/Family, Blueprint/Brainstorm, Acrobat, Constellation).
  2. *Synergistic Deck Reshaping & Consumable Utilization*: Prioritize rank/suit-fixing Tarots (Death, Strength, Hanged Man) and Planet cards that harmonize directly with the active joker engine (e.g. duplicating target ranks/suits, boosting primary hand levels).
  3. *Scaling Joker Acceleration*: Maximize scaling joker increments (e.g. Green Joker, Ride the Bus, Supernova, Wee Joker, Square Joker) during safe/easy blinds when clear probability is high, compounding mult/chips reserves for late antes.

## Requirements

### R1. Late-Game Capital Deployment & Urgent Reroll Pacing
Implement adaptive bankroll liquidation in `vendor/balatro-rl/balatro_sim/agent_v10.py`:
- In Antes 6–8, when current scoring forecast falls below upcoming blind targets (Ante 7: ~100k, Ante 8: ~100k–200k), relax the $25 interest floor and increase reroll limits.
- Aggressively hunt reliable xMult and scaling finishers (e.g. Cavendish, Duo, Trio, Family, Order, Tribe, Card Sharp, Baseball, Acrobat, Constellation, Hologram) to bridge mid-game leads into Ante 8 wins.

### R2. Synergistic Deck Reshaping & Targeted Consumable Flow
Enhance consumable valuation and usage in `agent_v10.py` and `tools/portfolio.py`:
- Direct Tarot conversions (Death, Strength, Hanged Man) toward cards favored by owned jokers (e.g. Ace/Face duplication for Scholar/Photograph, rank matching for Duo/Trio/Family, suit conversion for Bloodstone/Onyx).
- Align Planet card acquisition and usage with the primary hand type determined by the active joker portfolio rather than generic baseline hand EV.

### R3. Scaling Joker Acceleration During Safe Blinds
Enhance in-blind play pacing for scaling jokers (`j_green_joker`, `j_ride_the_bus`, `j_supernova`, `j_wee`, `j_square`):
- When estimated round clear probability is near 1.0 ($P(\text{clear}) \ge 0.98$), allow playing non-scoring or scaling-triggering hands to bank permanent mult/chip growth rather than ending the blind prematurely with overkill hands.

### R4. Human-Fair & Isolation Guarantees
Maintain strict human-fairness: zero peeking at future draw order, zero future shop/boss RNG stream consumption, zero live game mutation during evaluation. `test_seed_exactness.py -m ci_gate` must remain 100% green.

## Acceptance Criteria

### Baseline & Integrity Verification
- [ ] All simulator unit and integration tests pass: `python -m pytest vendor/balatro-rl/tests vendor/balatro-rl/balatro_sim/tests -q`.
- [ ] CI seed exactness gate passes: `python -m pytest vendor/balatro-rl/tests/test_seed_exactness.py -m ci_gate -v`.
- [ ] All 4 static audits remain clean: `python tools/audit_jokers_static.py`, `python tools/audit_consumables_static.py`, `python tools/audit_bosses_static.py`, `python tools/audit_tags_static.py`.

### Benchmark & Performance Targets
- [ ] Full benchmark bank (Seeds 0–299 paired evaluation against `goal_iter7_final_D.json` baseline of 20W / 14D and current 26W / 11D):
  - Win rate $\ge 10.0\%$ ($\ge 30$ wins out of 300).
  - Ante 1 deaths $< 12$ ($< 4.00\%$).
- [ ] Out-of-sample holdout bank (Seeds 300–499):
  - Maintained generalization with no regression in Ante-1 survival or win rate.

## 2026-09-04T23:54:04Z

Advance the Optilatro search-first Balatro AI agent to break through the 10.0%+ win rate threshold (>= 30 wins / 300) while keeping Ante 1 mortality below 4.0% (< 12 deaths / 300) on Red Deck / White Stake under strict human-fair constraints.

Working directory: D:/Optilatro
Integrity mode: development

## Requirements

### R1. Late-Game Capital Deployment & Urgent Rerolls
Implement adaptive bankroll liquidation in vendor/balatro-rl/balatro_sim/agent_v10.py:
- In Antes 6–8, when current scoring forecast falls below upcoming blind targets, relax the $25 interest floor and aggressively hunt reliable xMult finishers (Cavendish, Duo, Trio, Family, Baseball Card, Acrobat, Constellation).

### R2. Synergistic Deck Reshaping & Targeted Consumables
Direct Tarot/Planet conversions and usages towards engine synergies.

### R3. Scaling Joker Acceleration
Safe in-blind scaling acceleration when knockout is reserved.

### R4. Human-Fair & Isolation Guarantees
Strict human-fairness; test_seed_exactness.py -m ci_gate must remain green.

## Acceptance Criteria
- 300-seed benchmark >= 30 wins (>= 10.0%) and < 12 Ante-1 deaths (< 4.0%).

## 2026-09-05T06:01:08Z

URGENT COURSE CORRECTION FROM USER:
1. Do not focus on converting specific close games or individual seed traces. Trace macro patterns across losses across all failed runs to determine systemic fixes that minimize widespread failure modes.
2. All verification and benchmark acceptance runs MUST be conducted on completely fresh, never-before-seen seed banks. Never reuse verification seeds across iterations.
3. Use seeds 9000–9299 for the current verification run. Ensure zero overlap with any previously examined seeds.
Please immediately pivot the verification panel and benchmark challenger to execute the acceptance evaluation on Seeds 9000–9299.

## 2026-09-05T06:16:45Z

In accordance with the user's strict instruction ("seeds should never be reused in verification runs, make sure we never reuse verification seeds"):
Seeds 9000–9299 have been used as the initial verification bank.
For the upcoming verification run after the macro remedies (Ante 1 economy gate & mid-game deficit capital deployment), the verification panel MUST use the next completely pristine, never-before-seen bank: Seeds 9300–9599.
Never reuse seeds 9000–9299 or 0–299 for verification.





