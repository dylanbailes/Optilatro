# DISPATCH

## 2026-09-04T06:42:00Z

Advance the Optilatro search-first Balatro AI agent to break through the 10.0%+ win rate threshold (>= 30 wins / 300) while keeping Ante 1 mortality below 4.0% (< 12 deaths / 300) on Red Deck / White Stake under strict human-fair constraints.

Current Milestone & Context:
- Current state: `search_shop_v10` achieves 8.67% win rate (26/300) and 3.67% Ante-1 mortality (11/300) on Seeds 0–299 (see sidecar `vendor/balatro-rl/results/bench_0_299_search_shop_v10.json`).
- Verified Suite: All 1,600+ test suite tests pass, CI seed exactness gate passes 4/4 (`test_seed_exactness.py -m ci_gate`), and all 4 static audits are clean.

Requirements:
- R1. Late-Game Capital Deployment & Urgent Reroll Pacing (`vendor/balatro-rl/balatro_sim/agent_v10.py`):
  In Antes 6–8, when current scoring forecast falls below upcoming blind targets (Ante 7: ~100k, Ante 8: ~100k–200k), relax the $25 interest floor and increase reroll limits. Aggressively hunt reliable xMult and scaling finishers (Cavendish, Duo, Trio, Family, Order, Tribe, Card Sharp, Baseball, Acrobat, Constellation, Hologram) to bridge mid-game leads into Ante 8 wins.
- R2. Synergistic Deck Reshaping & Targeted Consumable Flow (`agent_v10.py`, `tools/portfolio.py`):
  Direct Tarot conversions (Death, Strength, Hanged Man) toward cards favored by owned jokers (e.g. Ace/Face duplication for Scholar/Photograph, rank matching for Duo/Trio/Family, suit conversion for Bloodstone/Onyx). Align Planet card acquisition and usage with the primary hand type determined by the active joker portfolio rather than generic baseline hand EV.
- R3. Scaling Joker Acceleration During Safe Blinds:
  Enhance in-blind play pacing for scaling jokers (`j_green_joker`, `j_ride_the_bus`, `j_supernova`, `j_wee`, `j_square`). When estimated round clear probability is near 1.0 ($P(\text{clear}) \ge 0.98$), allow playing non-scoring or scaling-triggering hands to bank permanent mult/chip growth rather than ending the blind prematurely with overkill hands.
- R4. Strict Human-Fair & Isolation Guarantees:
  Zero peeking at future draw order, zero future shop/boss RNG stream consumption, zero live game mutation during evaluation. `test_seed_exactness.py -m ci_gate` must remain 100% green.

Acceptance Criteria:
- All simulator unit and integration tests pass: `python -m pytest vendor/balatro-rl/tests vendor/balatro-rl/balatro_sim/tests -q`.
- CI seed exactness gate passes: `python -m pytest vendor/balatro-rl/tests/test_seed_exactness.py -m ci_gate -v`.
- All 4 static audits remain clean: `python tools/audit_jokers_static.py`, `python tools/audit_consumables_static.py`, `python tools/audit_bosses_static.py`, `python tools/audit_tags_static.py`.
- Benchmark Bank (Seeds 0–299 paired evaluation against `goal_iter7_final_D.json` baseline of 20W / 14D and current 26W / 11D):
  - Win rate >= 10.0% (>= 30 wins / 300)
  - Ante 1 deaths < 12 (< 4.00%)
- Holdout Bank (Seeds 300–499):
  - Maintained generalization with no regression in Ante-1 survival or win rate.
