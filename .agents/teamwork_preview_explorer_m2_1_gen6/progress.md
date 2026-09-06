# Progress

Last visited: 2026-09-04T17:56:15-07:00

## Status
- [x] Initial dispatch received and logged in DISPATCH.md
- [x] BRIEFING.md initialized
- [x] Read ORIGINAL_REQUEST.md and PROJECT.md
- [x] Inspect agent_v10.py (_v10_rank_shop_items, SearchShopV10, joker evaluation)
- [x] Analyze Seed 298 failure and Ante 1 dynamics with Blueprint/Brainstorm
  - Verified exact crash history: Gen4 AttributeError on _EvalGame -> Gen4 remedy added unconditional `value = max(value, 1.5)`.
  - Discovered root cause of why `max(value, 1.5)` was added: in `eval_hand_score`, `extra_joker` is appended to the right of existing jokers. Blueprint copies the joker to its RIGHT, so at the far right of `eg.jokers`, Blueprint copies nothing and scores 0 marginal delta.
  - Traced Seed 298: With 0 jokers and $10 cash in Ante 1 Shop 1, Blueprint was boosted to 1.65 (1.5 + 0.15 engineless urgency). Player bought Blueprint, left with $0 and 0 scoring jokers, and died on Ante 1 Big Blind (450 target).
  - Validated that without solo Blueprint, Seed 298 buys Buffoon Pack ($4), picks Jolly Joker (+8 Mult), and survives Ante 1 through Ante 5.
- [x] Scan seeds 0–299 for copy joker appearances in Ante 1/2:
  - Found 8 seeds with Blueprint/Brainstorm in Ante 1 shop with 0 jokers owned: [62, 114, 116, 134, 168, 170, 281, 298]
  - Both Seed 168 and Seed 298 are confirmed Ante 1 deaths from buying solo Brainstorm/Blueprint.
- [x] Evaluate candidate seeds with current policy vs gated policy:
  - Seed 298 with gating survives Ante 1 cleanly, advancing from step 15 Ante 1 Big Blind death to step 151 Ante 5.
- [x] Formulate concrete, mathematically sound gating/pricing recommendation
- [x] Produce handoff.md report following 5-component handoff protocol
- [x] Ready to notify parent agent via send_message
