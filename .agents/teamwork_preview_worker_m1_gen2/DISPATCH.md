## 2026-09-03T20:22:35Z
You are Worker M1 (teamwork_preview_worker).
Your assigned working directory is: D:/Optilatro/.agents/teamwork_preview_worker_m1_gen2

MANDATORY FIRST STEP: Read the full, verbatim user request at:
D:/Optilatro/.agents/ORIGINAL_REQUEST.md (specifically under `## 2026-09-03T20:10:17Z`).
Also read:
- D:/Optilatro/.agents/orchestrator_2/SCOPE.md
- D:/Optilatro/AGENTS.md and docs/STATUS.md
- Technical findings from the Survey Explorers:
  - D:/Optilatro/.agents/teamwork_preview_explorer_survey_1_gen2/handoff.md (R1 SearchShopV10 tuning, swap delta, anchor protection, parameters)
  - D:/Optilatro/.agents/teamwork_preview_explorer_survey_2_gen2/handoff.md (R2 Consumable utilization, deck reshaping, pack handling, engine classification, spectral exploits)
  - D:/Optilatro/.agents/teamwork_preview_explorer_survey_3_gen2/handoff.md (Baseline telemetry, seeds 205/275, loss patterns, testing commands)

EXCLUSIVE FILE WRITE OWNERSHIP:
You own `vendor/balatro-rl/balatro_sim/agent_v10.py`.
Do NOT modify `agent_v9.py` (it is the frozen baseline!).
Do NOT modify files in `.agents/` except your own directory.

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A teamwork_preview_auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

Mission & Implementation Scope:
Implement Requirement R1 (Win-Rate Bridge & Search Tuning) and Requirement R2 (Deck Reshaping Synergy & Consumable Utilization) in `vendor/balatro-rl/balatro_sim/agent_v10.py`:

1. Part 1 — SearchShopV10 & Swap Tuning (R1):
   - Fix Two-Step Swap Execution Drop Bug in `SearchShopV10.decide()`: When a swap occurs, Step 1 sells the joker and sets `self._pending_swap_target_idx`. In Step 2, ensure the target item is immediately bought without search deactivation or dropping to heuristic exit. Keep the target pending until bought or invalidated.
   - Search Availability: Set default `search_shops = 999` in `SearchShopV10.__init__` so counterfactual search is active across all shops throughout the run.
   - Open-Slot Counterfactual Evaluation: In `SearchShopV10._search_shop`, evaluate candidate purchases via $\Delta V = V(s') - V(s)$ even when slots are open (`len(game.jokers) < game.joker_slots`), ensuring high-leverage scoring jokers (Cavendish, Baseball Card, Duo, Trio, Order, Tribe, Family, Ramen, Stuntman, Constellation) are properly recognized and purchased.
   - Portfolio Anchor Protection: In `_v10_worst_joker_idx`, protect essential portfolio anchors: do not designate as worst any sole Chips joker (`n_chips <= 1 and j.key in CHIPS_JOKERS`), sole Flat Mult joker (`n_flat <= 1 and j.key in FLAT_MULT_JOKERS`), sole xMult joker (`n_xmult <= 1 and j.key in XMULT_JOKERS`), or scaling joker (`j.key in SCALING_JOKERS`), unless in late-game liquidation.
   - Swap Sensitivity & Late Economy Liquidation: Tune swap delta threshold from 0.015 to 0.005. Evaluate candidate sells beyond just index 0. In Ante >= 7, liquidate dead economy jokers (e.g. `j_golden`, `j_todo_list`, `j_egg`, `j_satellite`) to free slots for combat scoring jokers.
   - Restore V10 Parameter Defaults in `V10_DEFAULTS`: Ensure Configuration D values are default: `ante1_chip_bias: 0.8`, `ante2_chip_bias: 0.5`, `early_struct_ante: 2`, `farm_rate_share: 0.75`, `engineless_urgency_ante: 2`.

2. Part 2 — Deck Reshaping & Consumable Utilization (R2):
   - Consumable Slot Deadlock Fix: In `agent_v10.py`, ensure held consumables are utilized proactively in shop or combat rather than permanently locking the 2 consumable slots (since simulator has no `sell_consumable` action). Allow using non-main planets if slots are full or when held into combat.
   - Zero-Waste Booster Handling: In `_v10_decide_booster`, never skip an opened Celestial pack. If no planet matches main hand, pick the highest base value / scaling planet (fuels Constellation/Satellite, levels secondary hands).
   - Save-Mode Barrier Fix: Ensure high-EV consumables (Hermit, Death, Fool, high-synergy Planets) can be bought in save_mode (either lower `save_strong_value` or add consumable exceptions).
   - Comprehensive Engine Registries in `deck_reshape_target`:
     - Fix `_SUIT_ENGINES_FIXED`: remove `j_golden` (not a Diamond joker!). Add genuine suit jokers: Diamonds (`j_greedy_joker`, `j_rough_gem`), Hearts (`j_lusty_joker`, `j_bloodstone`), Spades (`j_wrathful_joker`, `j_arrowhead`), Clubs (`j_gluttonous_joker`, `j_onyx_agate`, `j_seeing_double`).
     - Expand `_RANK_ENGINES`: add `j_scholar` (14/Ace), `j_walkie_talkie` (10, 4), `j_wee` (2), `j_hit_the_road` (11/Jack).
     - Add rank group engines: Even Steven (2,4,6,8,10), Odd Todd (3,5,7,9,11,13,14), Fibonacci (14,2,3,5,8), Hack (2,3,4,5).
     - Expand `_FACE_ENGINES`: add `j_smiley`, `j_scary_face`, `j_triboulet`, `j_caino`.
   - Safe Reshaping Card Targeting: In `c_hanged_man` and `c_death`, protect active engine ranks! Never destroy Rank 2 cards when owning Wee Joker or Hack; never destroy Fibonacci cards when owning Fibonacci.
   - Zero-Risk Spectral Exploits: Use Hex and Ankh when owning exactly 1 joker (100% free Polychrome or joker duplication with zero downside).
   - Dynamic Planet Synergy: Align planet purchasing and valuation with active joker hand affinities (Duo -> Pair, Tribe -> Flush, Runner -> Straight, etc.) and scaling jokers (Constellation, Satellite).

3. Verification Steps:
   - Run `pytest vendor/balatro-rl/tests/test_agent_v10.py -v`
   - Run `pytest vendor/balatro-rl/tests/test_e2e_v10_requirements.py -v`
   - Run `pytest vendor/balatro-rl/tests/test_seed_exactness.py -m ci_gate -v`
   - Run all 4 static audits:
     - `python tools/audit_jokers_static.py`
     - `python tools/audit_consumables_static.py`
     - `python tools/audit_bosses_static.py`
     - `python tools/audit_tags_static.py`
   - Run full unit tests: `pytest vendor/balatro-rl/tests vendor/balatro-rl/balatro_sim/tests -q`
   - Verify seeds 205 and 275 clear Ante 1.

Deliverables:
- Maintain `D:/Optilatro/.agents/teamwork_preview_worker_m1_gen2/progress.md`.
- Write detailed handoff report to `D:/Optilatro/.agents/teamwork_preview_worker_m1_gen2/handoff.md`.
- Send completion message to parent when done with test results and summary of changes.
