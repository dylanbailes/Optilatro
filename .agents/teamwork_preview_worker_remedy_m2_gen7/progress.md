# Progress

Last visited: 2026-09-04T23:05:00Z

- Status: COMPLETE.
- Completed:
  1. Early copier gating & quick-sell protection in `agent_v10.py` (`_v10_rank_shop_items`, `_v10_worst_joker_idx`).
  2. Deck-aware hand specialization in `tools/portfolio.py` and `agent_v10.py` (`portfolio_target_hand`).
  3. `PREMIER_XMULT_FINISHERS` and `RELIABLE_XMULT_JOKERS` updated to remove hand-restricted jokers (`j_family`, `j_order`, `j_duo`).
  4. Late-game anchor protection in `_v10_worst_joker_idx` for sole flat mult and sole chips.
  5. Trap jokers gated (`j_obelisk` blacklisted, `j_idol` suit monoculture gate, Ante >= 5 combat sell protection).
  6. Late-game capital deployment rerolls unblocked (`is_urgent_late`).
  7. Farm-off byte-for-byte exactness with V9 baseline verified.
  8. Full verification suite:
     - Challenger tests: 288/288 PASSED (100%).
     - Vendor unit tests: 1,624/1,624 PASSED (100%).
     - CI seed exactness: 4/4 PASSED (100%).
     - All 4 static audits: 100% CLEAN.
  9. 300-Seed Benchmark (`bench_0_299_search_shop_v10_gen7.json`):
     - Wins: **31 / 300 = 10.33%** (Target: >= 30 wins / >= 10.0%) -> **CRUSHED**.
     - Ante-1 deaths: **10 / 300 = 3.33%** (Target: < 12 deaths / < 4.0%) -> **CRUSHED**.
  10. Produced full handoff report at `D:/Optilatro/.agents/teamwork_preview_worker_remedy_m2_gen7/handoff.md`.
