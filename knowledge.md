# Project knowledge

Short live context for humans and agents. The long working log is
[docs/history/changelog.md](docs/history/changelog.md).

## What this is

Optilatro plays Balatro in a headless Python sim to maximize **ante-8 win rate**
on Red Deck / White Stake. Architecture: exact-ish local play, human-fair
valuation, shop search. Not more PPO.

## Layout

| Path | Role |
|---|---|
| [README.md](README.md) | Entry point |
| [AGENTS.md](AGENTS.md) | Handoff rules |
| [docs/](docs/README.md) | Specs, status, audits, mechanics sheet |
| `bench/` | Win-rate / throughput harnesses |
| `tools/` | Spec JSON + static audits + reporters |
| `vendor/balatro-rl/balatro_sim/` | **Live sim + agents** |
| `vendor/balatro-rs/` | Rust reference (read-only oracle) |
| `.agents/` | Leftover Codebuff types — ignore |

## Commands

From repo root, Python 3.11, CPU torch + `requirements-ci.txt`:

```bash
python -m pytest vendor/balatro-rl/tests vendor/balatro-rl/balatro_sim/tests -q
python -m pytest vendor/balatro-rl/tests/test_seed_exactness.py -m ci_gate -v
python tools/audit_jokers_static.py
python tools/audit_consumables_static.py
python tools/audit_bosses_static.py
python tools/audit_tags_static.py
python bench/bench_sim.py --games 200
```

## Conventions

- Human-fair by default: composition yes, draw order no.
- `agent_v9` is the frozen baseline; new in-blind work is `agent_v10`.
- Mechanics source of truth: `docs/reference/balatro-mechanics.md`.
- Spec generators read that file via `tools/_paths.py`.
- Never re-clone a vendor dir with a nested `.git`.

## Current leftovers

A5 tag weights. Wild/Stone suit helpers. Deck-reshaping toward bought engines.
Human-fair L1 that actually differs from L0. Stakes/Endless are out of v1 scope.

Details: [docs/STATUS.md](docs/STATUS.md).
