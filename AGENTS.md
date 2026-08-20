# Agent handoff

You are working in **Optilatro**, a search-first Balatro agent. Read
[README.md](README.md) then [docs/STATUS.md](docs/STATUS.md) before editing.

This file is the contract for further agents. Follow it.

---

## What this repo is

- **Goal:** maximize ante-8 win rate on Red Deck / White Stake.
- **Live code:** `vendor/balatro-rl/balatro_sim/` (Python sim + agents).
- **First-party glue:** `bench/`, `tools/`, `docs/`, `.github/workflows/ci.yml`.
- **Reference only:** `vendor/balatro-rs/` (Rust). Do not train against it; use
  it as an RNG/scoring oracle.
- **Not the product:** `.agents/` (leftover Codebuff TypeScript types). Ignore
  unless the user asks about Codebuff agents.

The root used to be a dump: specs, a 90 KB `knowledge.md`, and
`balatro-mechanics-reference(2).md`. Those now live under `docs/`. The old log
is [docs/history/changelog.md](docs/history/changelog.md).

---

## Hard rules

1. **Do not peek at draw order** in default policies. Human-fair =
   composition of `deck + hand + spent`, current shop, revealed boss. Exact
   future shops / `--lookahead` rollouts are research-only and must be labeled.
2. **Never consume the run RNG** from evaluation. Isolated eval uses a
   throwaway seed-0 RNG. `ci_gate` (`tests/test_seed_exactness.py`) must stay
   green.
3. **Do not mutate the live game** from scoring / valuation. Use
   `eval_hand_score` / `clone_game`.
4. **Do not rewrite `agent_v9.py` as the new policy.** It is the frozen A/B
   baseline. New in-blind behavior goes in `agent_v10.py`.
5. **Do not silently change shop/RNG draw order.** If you must, re-derive
   golden pins in `tests/test_seed_rng.py` in the same change and say so.
6. **Do not re-vendor** `vendor/balatro-rl` or `vendor/balatro-rs` by cloning
   into place. A nested `.git` turns the directory into a gitlink and CI
   checks out **zero files**. Copy files; never commit a nested `.git`.
7. **Do not add Endless or higher stakes** unless the user explicitly expands
   scope. White Stake / antes 1–8 is the lock.
8. **Do not treat historic win rates as current.** Many peaks used exact
   draw-order or lookahead. Cite the bank, policy, and whether it was
   human-fair.

---

## Where to edit

| Change | Files |
|---|---|
| Joker effect / hook | `vendor/balatro-rl/balatro_sim/jokers/` + `tests/test_joker_spec.py` |
| Scoring, seals, enhancements | `scoring.py`, `hand_eval.py`, `game.py` |
| Shop / packs / editions | `shop.py` |
| Consumables / vouchers | `consumables.py` |
| Boss blinds / tags | `game.py`, `tags.py` |
| L0 / L1 policy | `agent_v9.py` (baseline), `agent_v10.py`, `agent_l1.py` |
| State fork / rollouts | `rollout.py` |
| Per-node RNG | `seed_rng.py`, `replay.py` |
| Mechanics sheet | `docs/reference/balatro-mechanics.md` then regenerate specs |
| CI | `.github/workflows/ci.yml`, `requirements-ci.txt` |

After editing the mechanics sheet, regenerate:

```text
python tools/gen_joker_spec.py
python tools/gen_consumable_spec.py
python tools/gen_boss_spec.py
python tools/gen_tag_spec.py
```

Paths are centralized in `tools/_paths.py`. Do not hardcode the old root
filename `balatro-mechanics-reference(2).md`.

---

## Commands (repo root)

```bash
# Suite used in CI (from vendor/balatro-rl in the workflow)
python -m pytest vendor/balatro-rl/tests vendor/balatro-rl/balatro_sim/tests -q

python -m pytest vendor/balatro-rl/tests/test_seed_exactness.py -m ci_gate -v

python tools/audit_jokers_static.py
python tools/audit_consumables_static.py
python tools/audit_bosses_static.py
python tools/audit_tags_static.py
```

Torch is required (pulled in via `train_sim.py`) but must be the **CPU** wheel
in CI. See `requirements-ci.txt`.

---

## Invariants the suite is protecting

- Decorator-only joker registration; no engine `j.key == "j_oops"` scans
  (capability flags). Audit gates: DUPES / DEAD / STUBS / GAPS / TYPE / SIG /
  STATE / NOSCAN.
- Seed mode is per-node LuaRandom. Generic mode is one `random.Random` stream.
- Mid-round empty deck reshuffles `spent` on the `reshuffle` node.
- Blind rewards are flat $3 / $4 / $5 / $8.
- Shop cdt weights: Joker 20 / Tarot 4 / Planet 4. Rarity 70/25/5/0.
- Gold seal pays **on score**; Purple seal grants on **discard**.

Gotchas (do not re-learn the hard way):

- Python `and`/`or` return operands. Wrap flags in `bool(...)`.
- `Card` equality is expensive; do not write `c not in hand` in hot loops.
- Created jokers must carry `game=` or `chance()` falls back to module random.
- Wild cards miss suit-jokers (`card.suit == X`) — known P2 gap.
- Stone cards still expose rank/suit to some jokers — known P2 gap.

---

## Open work (do not invent a new roadmap)

See [docs/STATUS.md](docs/STATUS.md). The live leftovers are:

- **A5** tag weights + edition-discovery gating
- **M2 P2 #14 / #16** stakes+stickers and Endless (out of v1 scope)
- Wild / Stone helper sweep (GAP-W / GAP-S)
- Deck-reshaping loop (tarots/packs build toward a bought engine)
- Human-fair L1 decision rule that is not byte-identical to L0

---

## Style

- Prefer a measured A/B on a fixed seed bank over a rewrite.
- Put new benches in `bench/` and new audits in `tools/`.
- Archive experiment telemetry under `vendor/balatro-rl/results/` with a
  README (see `tools/report_bench_ab.py`).
- Keep docs short and linked. Do not grow `knowledge.md` back into a changelog;
  append dated notes to `docs/history/changelog.md` or `docs/STATUS.md`.
