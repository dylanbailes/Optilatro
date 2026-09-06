# Scope: Optilatro V10 Enhancement Phase 2 — Win-Rate Breakthrough (>7.0% Win Rate, <4.67% Ante 1 Deaths)

## Architecture
Optilatro is a search-first Balatro agent targeting maximum win rate on Red Deck / White Stake (Antes 1–8) under strict human-fair constraints (no deck order peeking, no future RNG stream lookahead, zero live game mutation).

### Component Architecture
1. **In-Blind Policy (`vendor/balatro-rl/balatro_sim/agent_v10.py`)**:
   - Multi-hand budget pace rule for Ante 1 (`(target - scored) / hands_left`).
   - Configuration D baseline parameters (`ante1_chip_bias: 0.8`, `ante2_chip_bias: 0.5`, `early_struct_ante: 2`, `farm_rate_share: 0.75`, `engineless_urgency_ante: 2`).
2. **L1 Counterfactual Search (`SearchShopV10`)**:
   - Two-step swap execution reliability (fix drop bug).
   - Full-game search capability (`search_shops = 999`).
   - Open-slot counterfactual $\Delta V$ candidate evaluation.
   - Dynamic anchor protection (protect sole Chips, sole Flat Mult, sole xMult).
   - Sensitive swap threshold ($\Delta V > 0.005$) and late-ante economy liquidation (Ante 7/8).
3. **Deck Reshaping & Consumable Synergy**:
   - Slot deadlock elimination and proactive consumable consumption.
   - Zero-waste Celestial and Arcana pack handling (never skip opened packs).
   - Removal of the 0.30 `save_mode` barrier for high-EV tarots and planets.
   - Extended rank and suit engines (Scholar, Walkie-Talkie, Wee Joker, Hit the Road, Hack, Fibonacci, suit jokers; fix `j_golden` Diamond bug).
   - Non-destructive Hanged Man and Death targeting (never destroy active engine ranks).
   - Zero-risk Spectral usage (Hex and Ankh on single-joker states).
   - Dynamic planet synergy matching active jokers and scaling jokers (Constellation, Satellite).

## Feature Inventory
| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| F1 | Two-Step Swap Execution Fix | Fix swap drop bug in `SearchShopV10.decide()` so pending buy is never lost | M1 | Survey Explorer 1 |
| F2 | Full-Game Search Availability | Default `search_shops = 999` to keep counterfactual search active across all antes | M1 | Survey Explorer 1 |
| F3 | Open-Slot Counterfactual Search | Evaluate $\Delta V$ on open slots so S-tier jokers (Cavendish, Duo, Baseball, Ramen) are bought | M1 | Survey Explorer 1 |
| F4 | Portfolio Anchor Protection | Protect sole Chips and sole Flat Mult in `_v10_worst_joker_idx` to prevent floor collapses | M1 | Survey Explorer 1 |
| F5 | Sensitive Swap & Econ Liquidation | Lower swap delta to 0.005; liquidate dead economy jokers in Ante 7/8 for combat jokers | M1 | Survey Explorer 1, 3 |
| F6 | V10 Defaults Restoration | Set `ante1_chip_bias: 0.8`, `ante2_chip_bias: 0.5`, `early_struct_ante: 2` in `V10_DEFAULTS` | M1 | Survey Explorer 1, 3 |
| F7 | Consumable Slot Deadlock Fix | Eliminate slot lockouts by ensuring held consumables are consumed before blocking purchases | M1 | Survey Explorer 2 |
| F8 | Zero-Waste Celestial Packs | Never skip opened Celestial packs; select fallback/scaling planets | M1 | Survey Explorer 2 |
| F9 | Consumable Save-Mode Fix | Ensure Hermit, Death, Fool, and synergistic Planets/Tarots bypass save_mode threshold | M1 | Survey Explorer 2 |
| F10 | Comprehensive Engine Registries | Expand `_RANK_ENGINES`, `_SUIT_ENGINES_FIXED`, `_FACE_ENGINES`, rank groups; fix `j_golden` bug | M1 | Survey Explorer 2 |
| F11 | Safe Reshaping Card Targeting | Protect active engine ranks in `c_hanged_man` and `c_death` (never delete 2s with Wee Joker) | M1 | Survey Explorer 2 |
| F12 | Zero-Risk Spectral Exploits | Utilize Hex and Ankh for free Polychrome / duplication when holding 1 joker | M1 | Survey Explorer 2 |
| F13 | Portfolio-Synergistic Planets | Align planet valuation with active jokers (Duo->Pair, Tribe->Flush, Runner->Straight, Constellation) | M1 | Survey Explorer 2 |
| F14 | Suite & Gate Verification | 1,600+ unit tests, CI seed exactness gate, 4 static audits | M1 Gate | Acceptance Criteria |
| F15 | Full Benchmark Bank (0–299) | Paired benchmark achieving >7.0% win rate (>21/300) and <4.67% Ante 1 deaths (<14/300) | M2 | Acceptance Criteria |
| F16 | Holdout Bank (300–499) | Verified generalization with consistent win rate and low Ante 1 mortality | M2 | Acceptance Criteria |
| F17 | Forensic Integrity Audit | Independent verification of zero hardcoding, zero RNG leakage, strict human-fairness | Final | Acceptance Criteria |

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| M1 | V10 Policy Optimization (R1 + R2) | F1–F13 in `agent_v10.py` + F14 unit tests, CI gate, audits | Survey | IN_PROGRESS |
| M2 | Paired Benchmark (0–299) & Holdout (300–499) | F15, F16 paired benchmarking and telemetry | M1 | PLANNED |
| Final | Forensic Integrity Audit & Victory Attestation | F17 independent forensic audit | M2 | PLANNED |

## Interface Contracts
### SearchShopV10 ↔ _v10_decide_shop
- When `self._pending_swap_target_idx` is set: Step 2 of `decide()` MUST execute `{"type": "buy", "item_idx": target}` if price <= dollars and room exists.
- In `_search_shop`: evaluate candidate buys when open slots exist using $\Delta V = V(s') - V(s)$.
- In `_v10_worst_joker_idx`: jokers qualifying for sole-role status (`n_chips <= 1 and key in CHIPS_JOKERS`, `n_flat <= 1 and key in FLAT_MULT_JOKERS`, `n_xmult <= 1 and key in XMULT_JOKERS`, or `key in SCALING_JOKERS`) MUST be excluded from candidate sells unless in Ante >= 7 liquidation.
