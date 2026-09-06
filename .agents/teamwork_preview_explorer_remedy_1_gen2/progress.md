# Progress — Remedy Explorer 1

- Last visited: 2026-09-03T21:05:00Z
- Current status: Investigation and solution formulation complete. Writing comprehensive handoff report with exact code diffs and verification methods.
- Completed:
  1. Root cause analysis of open-slot early ante spending and interest starvation.
  2. Cash reserve logic and flat scoring anchor priority rule design for SearchShopV10._search_shop.
  3. Restoration of V10_DEFAULTS ante1_chip_bias (0.8) and ante2_chip_bias (0.5).
  4. Scoped dual-assertion resolution for test_m13_ante1.py::test_ante1_buffoon_outranks_sly.
  5. Infeasible buy dangling _pending_swap_target_idx fix.
  6. Sell value lookup fix to check j.state.get('sell_value', ...).
