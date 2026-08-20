# Status

Last reviewed: 2026-08-20 (docs/layout pass). Numbers below are **recorded**
results from the 2026-08 working log — re-measure before citing a new paper
or comparing a new policy.

## Scope lock

Red Deck, White Stake, antes 1–8, no Endless. Human-fair evaluation.

## Pipeline (from [spec.md](spec.md))

| Milestone | Intent | State |
|---|---|---|
| M0 | Vendor sim, tests, bench floor | **Done** |
| M1 | Fidelity + per-node RNG + replay | **Done** (A5 still open) |
| M2 | Economy/shop vs reference sheet | **Done** except P2 #14 stakes, #16 Endless |
| M3–M6 (spec) | Exact solver, Gumbel MCTS, learning, live mod | **Superseded** by the V9/V10 search-first track |
| V9 L0/L1 | Heuristic + shop search | **Done** (human-fair pivot later) |
| V10 | In-blind survive/value hierarchy | **Done**; knobs confirmed |

## Headline numbers (do not mix banks)

| What | Result | Notes |
|---|---|---|
| Random floor | 2/2000 = **0.10%** | `bench/bench_sim.py`, post-M2 |
| V7 PPO (upstream) | **2.35%** | Prior-art ceiling; not reproduced here |
| V9 heuristic, pre-human-fair | ~11% @ 300 | Used exact draw order — **not** a current bench |
| V9 heuristic, human-fair | **6.00%** @ 300 then later **4.67%** after structure rules | Same bank 0–299; stream diverges when discards change |
| V9 search + lookahead (oracle) | up to **23.33%** @ 300 | Research-only; not human-fair |
| V10 heuristic vs V9 | **5.00%** vs 3.67% @ 300; **4.40%** vs farm-off @ 1000 | Farm-off == V9 byte-for-byte |

Ante-1 clear on the structure-discard bank: human-fair ~89%, lookahead oracle
~91%. Remaining ante-1 deaths are mostly shop-RNG / no-joker, not discard
policy.

## Closed (do not reopen without a failing test)

- Persistent deck + mid-round reshuffle
- Per-node LuaRandom + cross-process `ci_gate`
- All 28 bosses, 32 vouchers, 24 tags, 150 catalogue jokers
- Shop structure (cdt 20/4/4, Showman, first-shop Buffoon, pack weights)
- Joker-layer architecture (R1–R8) and consumable/boss/tag static audits
- Seal timing: Gold on score, Purple on discard, Blue × Mime, Red held retrigger
- Human-fair discard EV and comparative shop search
- V10 farm knobs at spec defaults (`0.90` / `0.75` / spare `1`)

## Open

| ID | Item | Why it is still open |
|---|---|---|
| A5 | Tag weights + edition-discovery gating | `TAG_WEIGHTS` is still uniform |
| M2 #14 | Stakes + stickers | Out of v1 scope (White Stake lock) |
| M2 #16 | Endless | Out of v1 scope |
| GAP-W | Wild × suit-jokers | `card.suit == X` misses Wild |
| GAP-S | Stone × rank/suit-jokers | Stone still exposes rank/suit |
| — | Deck-reshaping loop | Tarots/packs should build toward a bought engine |
| — | Human-fair L1 ≠ L0 | Comparative search currently matches L0 byte-for-byte |
| — | Live-game verification (spec M5) | Not started |
| — | Balatro version pin | Never recorded in the vendored tree |

## What not to try again

Recorded as flat or worse, with archives under `vendor/balatro-rl/results/`:

- Ante-1 interest floors / reroll gates (underpowered runs)
- Discard-EV v2 (top-K, flush bonus, target-aware gamble)
- Raising `tier2_min_value` above 0
- More PPO / self-play / dual play-shop networks (upstream V5–V8)
