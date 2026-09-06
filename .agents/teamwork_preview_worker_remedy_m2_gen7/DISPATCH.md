# DISPATCH

## 2026-09-04T22:40:00Z

Task from orchestrator_4:
Implement targeted, high-leverage policy enhancements in vendor/balatro-rl/balatro_sim/agent_v10.py and tools/portfolio.py to close the 3-win gap (27 -> >=30 wins) and eliminate known early/mid-game traps, based on Explorer synthesis:

1. Early Copier Gating & Quick-Sell Protection in agent_v10.py:
   - In `_v10_rank_shop_items` (around line 1372):
     Only apply `value = max(value, 1.5)` if `_has_scoring_joker(game, ref)`.
     If `not _has_scoring_joker(game, ref)` and (`len(game.jokers) == 0` or `game.ante <= 2`): do NOT buy Blueprint or Brainstorm (assign negative value or `continue`), preventing suicidal solo purchases in Ante 1/2 like Seed 298.
     In lines 1392–1394, exclude `("j_blueprint", "j_brainstorm")` from receiving `engineless_urgency_bonus`.
   - In `_v10_worst_joker_idx`: protect Blueprint and Brainstorm from being sold immediately after purchase if `_has_scoring_joker(game, ref)` (fixing Seed 80).

2. Deck-Aware Hand Specialization in tools/portfolio.py & agent_v10.py:
   - In `tools/portfolio.py` (`portfolio_target_hand`):
     - For `j_family`: only target "Four of a Kind" if the full deck has >= 6 cards of the same rank (e.g. `max(_value_multiset(game.deck).values()) >= 6`); otherwise retain high-frequency hand (`main_hand_type` or "Two Pair" / "Pair" / "Flush").
     - For `j_order`: only target "Straight" if player owns `j_shortcut` or `j_four_fingers` or already has Straight as primary hand.
     - For `j_duo`: do NOT lock target hand to "Pair". Retain high-frequency hand (Two Pair / Full House / Flush) since Duo triggers on Two Pair and Full House.
   - In `agent_v10.py`:
     - Update `PREMIER_XMULT_FINISHERS`: remove `j_family`, `j_order`, `j_duo` (reserve premier finisher status for universal xMult: `j_cavendish`, `j_baseball`, `j_constellation`, `j_acrobat`).

3. Trap Jokers & Late-Game Capital Unlocking:
   - In `_v10_rank_shop_items`:
     - Add `j_obelisk` to a banned/skip list (assign `value = -1.0` or `continue`; Obelisk resets on High Card and caused fatal losses in Seeds 21 and 198).
     - Disallow buying `j_idol` unless deck has heavy monoculture (e.g. >= 20 of one suit).
     - In Ante >= 5, disallow selling combat jokers (flat mult / chips) to buy economy jokers (`j_golden`, `j_egg`, `j_satellite`, `j_rocket`). Rescues Seed 43.
   - In `_v10_decide_shop` line 1625:
     - Change `if not save_mode and ...` to `if (not save_mode or is_urgent_late) and ...` so late-game deficit unblocks rerolls down to `min_reserve` ($6), unlocking the $20–$25 cash hoards in Seeds 139, 155, 198, 211.

4. Run Verification Suite & 300-Seed Benchmark:
   - `python -m pytest tests/test_challenger_m2_gen4.py tests/test_challenger_m2_gen5.py -v`
   - `python -m pytest vendor/balatro-rl/tests vendor/balatro-rl/balatro_sim/tests -q`
   - `python -m pytest vendor/balatro-rl/tests/test_seed_exactness.py -m ci_gate -v`
   - All 4 static audits: jokers, consumables, bosses, tags.
   - Run 300-seed benchmark:
     `python bench/bench_agent_v10.py --seeds 0-299 --workers 16 --policies search_shop_v10 --report vendor/balatro-rl/results/bench_0_299_search_shop_v10_gen7.json`
   - Report wins, win rate %, Ante 1 deaths, mortality % in your handoff report.
