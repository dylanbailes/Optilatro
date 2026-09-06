# Project: Optilatro V10 Enhancement (10%+ Win Rate Milestone Breakthrough)

## Architecture
Optilatro is a search-first Balatro agent targeting maximum win rate on Red Deck / White Stake (Antes 1–8) under strict human-fair constraints (no deck order peeking, no future RNG stream lookahead).
Baseline performance: 8.67% win rate (26/300) and 3.67% Ante-1 mortality (11/300) on Seeds 0–299.
Goal: Break through 10.0%+ win rate (>= 30/300) while keeping Ante 1 mortality < 4.0% (< 12/300).

### Key Subsystems
1. **Late-Game Capital Deployment & Urgent Rerolls (`vendor/balatro-rl/balatro_sim/agent_v10.py`)**:
   - Multi-hand scoring forecast `_forecast_round_score` vs upcoming boss target (Ante 6: 40k/80k, Ante 7: 70k/140k, Ante 8: 100k/300k).
   - Adaptive interest floor: relax $25 floor to $15 in Ante 6 (if lacking xMult/deficit) and $0 in Ante 7 (deficit) & Ante 8 (always).
   - Paced rerolls with purchase reserve: allow up to 10 rerolls in Ante 8, 6 in Ante 7, 4 in Ante 6 if remaining cash + worst joker sell >= $6.
   - Post-reroll search enabling in `SearchShopV10.decide`: reset `_searched_this_visit = False` after rerolling.
   - Candidate item allowance fix in `_v10_rank_shop_items` accounting for worst joker sell value.
2. **Synergistic Deck Reshaping & Consumable Flow (`agent_v10.py`, `tools/portfolio.py`)**:
   - Tiered `portfolio_target_hand` prioritizing premier xMult finishers (Family -> Four of a Kind, Order -> Straight, Tribe -> Flush, Trio -> Three of a Kind, Duo -> Pair).
   - Consumable purchase unlocking in `save_mode`: exempt target planets and synergistic Tarots from save mode suppression.
   - Booster pack inventory check: only buy Celestial/Arcana/Spectral packs when consumable slots have room.
   - Dynamic Tarot targeting: Death Face card copying, Strength 10->Jack Face promotions, Hanged Man rank protection, Justice Glass synergy.
   - Proactive Planet consumption in shop to prevent slot clogging.
3. **Scaling Joker Acceleration During Safe Blinds (`agent_v10.py`)**:
   - In-blind pacing during safe blinds ($P(\text{clear}) \ge 0.98$ or Tier S1 in-hand knockout reservation).
   - Banking permanent scaling for Green Joker (+1 per hand, discard suppression), Ride the Bus (strict non-face verification), Supernova, Wee Joker (rank 2 prioritization), and Square Joker.
   - Strict safety guardrails: `hands_left >= 2`, banned on dangerous bosses (`bl_needle`, `bl_mouth`, `bl_eye`, `bl_grim`, `bl_hook`, `bl_tooth`, `bl_pillar`, `bl_psychic`), and Ante 1 survival priority.
4. **Verification & Benchmark Infrastructure (`tests/`, `bench/`)**:
   - 1,600+ test suite pass, CI seed exactness (4/4 pass), 4 static audits clean.
   - Paired seed benchmark on Seeds 0–299 against baseline (26W / 11D).
   - Holdout validation on Seeds 300–499.

## Feature Inventory
| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| F1 | Multi-Hand Round Scoring Forecast | `_forecast_round_score` evaluating multi-hand potential vs upcoming boss targets | M1 | Survey R1 |
| F2 | Adaptive Interest Relaxation & Liquidation | Relax $25 interest floor in Antes 6–8 during scoring deficit; $0 floor in Ante 8 | M1 | Survey R1 |
| F3 | Urgent Rerolls with Purchase Reserve Buffer | Increase reroll limits in late game with $6 purchase reserve for premier finishers | M1 | Survey R1 |
| F4 | Post-Reroll SearchShop Refresh | Reset `_searched_this_visit = False` after rerolls so counterfactual swaps inspect new items | M1 | Survey R1 |
| F5 | Full-Slot Allowance Fix | Include worst joker sell value in `allowance` during `_v10_rank_shop_items` | M1 | Survey R1 |
| F6 | Tiered Portfolio Target Hand | Strict hierarchy in `portfolio_target_hand` prioritizing xMult finishers | M1 | Survey R2 |
| F7 | Save Mode Consumable Exemption | Allow buying target planets and synergistic Tarots in `save_mode` | M1 | Survey R2 |
| F8 | Booster Pack Inventory Guard | Check open consumable slots before buying Celestial/Arcana packs | M1 | Survey R2 |
| F9 | Portfolio-Driven Tarot Targeting | Death Face copying, Strength 10->Jack, Hanged Man rank protection, Justice Glass synergy | M1 | Survey R2 |
| F10 | Proactive Shop Planet Consumption | Consume held planets immediately in shop to free consumable inventory | M1 | Survey R2 |
| F11 | Safe Blind Scaling Pacing | Bank scaling joker triggers during safe blinds when $P(\text{clear}) \ge 0.98$ and $hands \ge 2$ | M1 | Survey R3 |
| F12 | In-Hand Knockout Reservation (Tier S1) | Reserve clearing hand combination in hand while playing scaling triggers | M1 | Survey R3 |
| F13 | Discard Suppression for Green Joker | Suppress discards during safe blinds when holding Green Joker | M1 | Survey R3 |
| F14 | Ride the Bus Face Reset Guardrail | Strictly forbid playing scoring face cards when holding Ride the Bus | M1 | Survey R3 |
| F15 | Suite & Exactness Verification | 1,600+ tests pass, CI seed exactness 4/4 clean, 4 static audits clean | M2 | Acceptance |
| F16 | Paired Benchmark Breakthrough | Seeds 0–299 win rate >= 10.0% (>= 30 wins) and Ante 1 deaths < 12 (< 4.0%) | M2 | Acceptance |
| F17 | Out-of-Sample Holdout Generalization | Seeds 300–499 validation demonstrating generalization without regression | M3 | Acceptance |
| F18 | Final Forensic Integrity Audit | Independent audit verifying authentic implementation and zero cheating | Final | Acceptance |

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| M0 | Survey & Technical Analysis | Survey code state, failure modes, and exact mechanics | none | DONE |
| M1 | Core Policy Implementation | Implement R1 + R2 + R3 in `agent_v10.py` | M0 | IN_PROGRESS |
| M2 | Verification Panel & Paired Benchmark | Reviewers, Challengers, Auditor, Seeds 0–299 Benchmark | M1 | PLANNED |
| M3 | Out-of-Sample Holdout Generalization | Seeds 300–499 Holdout Benchmark | M2 | PLANNED |
| Final | Forensic Integrity Audit & Victory Attestation | Final audit report & completion presentation | M3 | PLANNED |

## Code Layout
- `vendor/balatro-rl/balatro_sim/agent_v10.py`: In-blind policy, shop ranking, consumable decision logic, scaling pacing, and `SearchShopV10`.
- `tools/portfolio.py`: Feature extractor and joker role classifier.
- `bench/bench_agent_v10.py`: Benchmark execution script.
- `tools/report_bench_ab.py`: A/B comparison and telemetry analysis.
- `tests/`: Regression and unit test suites.
