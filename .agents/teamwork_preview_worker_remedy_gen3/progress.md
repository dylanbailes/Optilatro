# Progress Log

Last visited: 2026-09-04T07:46:50Z

- Resolved Challenger 1: Fixed critical discard deadlock bug by wrapping discard candidate generation in `tier2_value` with `if game.discards_left > 0:`
- Resolved Challenger 2: Enforced strict Ante 1 suppression (`game.ante <= 1`), `game.hands_left >= 3`, at most 1 scaling play per blind (`chips_scored == 0` and `hands_played == 0`), and removed loose probabilistic p_clear scaling
- Implemented Win-Rate Bridge optimizations:
  - Added `PREMIER_XMULT_FINISHERS` and `DEAD_ECONOMY_JOKERS`
  - Upgraded `_v10_worst_joker_idx` to aggressively penalize and liquidate dead economy jokers when premier finishers/xMult are in shop or in late game
  - Fixed Blueprint / Brainstorm valuation in `_v10_rank_shop_items` to overcome simulator `_EvalGame` crash
  - Permitted SearchShopV10 to execute counterfactual swaps of dead economy jokers into premier finishers
  - Tuned reroll pacing in Ante 7/8 when in deficit to aggressively hunt xMult finishers while strictly respecting reroll caps
- Verified stress tests 1-4: ALL PASSED (0 failures)
- Currently verifying 25 end-to-end rollouts in background task-236
