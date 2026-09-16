# Original User Request

## Initial Request — 2026-09-10T14:00:54-07:00

You are the SWE Light Orchestrator for Optilatro.
Your assigned working directory is: D:\Optilatro\.agents\teamwork_preview_swe_1
The workspace directory is: D:\Optilatro
The authoritative request is recorded in: D:\Optilatro\.agents\ORIGINAL_REQUEST.md

## Objective
Scale Optilatro's V11 search policy (`agent_v11.py`) from 14% toward a 20%–25% full-run win rate on Red Deck / White Stake by activating universal Value Network shop scoring, early-game deficit capital deployment, and in-blind value squeezing.

## Requirements
### R1. Universal Value Network Shop Scoring & Early Scaling Growth
Incorporate the 50-feature MLP Value Network $V_\theta(S)$ into all shop candidate valuations (both open slots and full-slot swaps) in `vendor/balatro-rl/balatro_sim/agent_v11.py`. In `_rank_shop_items_v11`, augment candidate values with Value Network deltas $\Delta V_\theta(S \cup \{i\}) = V_\theta(S \cup \{i\}) - V_\theta(S)$ so the agent actively acquires portfolio-completing jokers (chips, mult, xmult), Celestial packs, and engine tarots. Apply scaling growth valuation (`_v11_scaling_growth_bonus`) with high weight in Antes 1–4 so scaling jokers (Green Joker, Ride the Bus, Supernova, Constellation) are purchased early with 20+ rounds to grow.

### R2. High-Capital Economy Scaling & In-Blind Value Squeezing
Enable human-like high-capital run scaling ($200+ spent per winning run):
- **In-Blind Value Squeezing**: When round clear is guaranteed ($P(\text{clear}) \ge 0.98$ or immediate clearing hand available with surplus hands), squeeze value: play multi-card face hands for `j_business` ($2/face card), hold face cards for `j_reserved_parking`, play Lucky cards for +$20 cash / +20 mult chances (amplified by retriggers and Red Seals), and harvest $5 discards for `j_mail`. Always prioritize beating the blind before farming.
- **Econ Joker Valuation**: Value economy generators (`j_business`, `j_reserved_parking`, `j_mail`, `j_egg`, `j_gift`, `j_rocket`) highly in early/mid antes when an initial scoring anchor is present.
- **The Magician & Tarot Engine**: Heavily prioritize `c_magician` (Lucky cards), `c_chariot` (Steel), `c_empress` (Mult), and `c_hierophant` (Bonus) to create compounding deck enhancements.

### R3. Mid-Game Deficit Capital Deployment
Eliminate the interest-hoarding death trap in Antes 2–5. When projected round score is below $1.5\times$ upcoming boss target (`is_deficit`):
- Reduce interest floor to $0 (or $\le \$5$) so the agent spends its capital to survive rather than dying holding cash.
- Permit up to 1 targeted reroll per shop visit when `dollars >= reroll_cost + 4` to fish for scoring anchors when lacking combat jokers.
- When in surplus, allow interest to compound normally up to the $25 cap.

### R4. Human-Fair Invariants & Preservation of Baseline Strengths
- Maintain strict 100% human-fairness: zero draw-order peeking, zero future-shop RNG peeking, isolated evaluation runs with throwaway RNGs.
- Preserve V10's rock-solid Ante-1 conservative opening (`if game.ante == 1: return _v10_decide_shop(...)`) to prevent Ante-1 regressions ($\le 3.3\%$ death rate).
- Restrict joker reordering strictly to copy jokers (`j_blueprint`, `j_brainstorm`) and `j_ceremonial`.
- `agent_v10.py` and `default_baseline_v10.json` remain 100% frozen.

## Acceptance Criteria
- Paired benchmark against frozen `search_shop_v10` on pristine seed bank 10500–10799 ($N=300$) achieves $\ge 20.0\%$ win rate (targeting $\ge 25.0\%$).
- Mean ante improves significantly over V10 baseline (baseline: 4.78).
- Total capital generated and spent per run increases substantially over V10 baseline ($>\$150+$ on deep runs).
- Ante-1 death rate remains $\le 4.0\%$ (matching or beating baseline 3.33%).
- All 4 static audits pass cleanly:
  `python tools/audit_jokers_static.py`
  `python tools/audit_consumables_static.py`
  `python tools/audit_bosses_static.py`
  `python tools/audit_tags_static.py`
- Seed exactness CI gate passes:
  `pytest vendor/balatro-rl/tests/test_seed_exactness.py -m ci_gate -v`
- HTML report generated: `vendor/balatro-rl/results/bench_10500_10799_paired.html` with full §8 telemetry bundle and McNemar statistical significance test.

Maintain your `progress.md` and `plan.md` in your working directory. Report completion back with full evidence when finished.
