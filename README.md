# Optilatro

A **search-first Balatro agent** that maximizes ante-8 win rate on **Red Deck / White Stake**.

The engine is a Python simulator (vendored, heavily audited) plus heuristic and
shop-search policies. Training is **not** more PPO — prior art (balatro-rl V7)
plateaued at 2.35% win. This repo's path is exact in-blind play, human-fair
valuation, and limited-horizon shop search.

**Read this first, then [AGENTS.md](AGENTS.md) if you are an agent, then
[docs/STATUS.md](docs/STATUS.md) for what is done vs still open.**

---

## Current headline

| Policy | What it is | Last recorded headline |
|---|---|---|
| `heuristic_v10` | L0: exact-ish in-blind play + survive/value farming | ~5% @ 300 seeds; farm knobs confirmed at defaults |
| `search_shop_v9` / `search_shop_v10` | L1: comparative shop search over L0 | Historic oracle peaks are **not** the human-fair number |
| random | floor | **0.10%** (2/2000) after shop/economy fidelity fixes |

Scope lock: Red Deck, White Stake, antes 1–8, no Endless. Benchmarks must be
**human-fair** (deck *composition* is legal; draw *order* and future shops are
not). `--lookahead` is research-only.

Full scoreboard and open work: [docs/STATUS.md](docs/STATUS.md).

---

## Repository layout

```
Optilatro/
├── README.md                 ← you are here
├── AGENTS.md                 ← handoff for other agents
├── knowledge.md              ← short live context (not the old 90 KB dump)
├── requirements-ci.txt       ← pytest + numpy + gymnasium (torch installed separately)
├── docs/                     ← first-party documentation (start at docs/README.md)
├── bench/                    ← win-rate / throughput harnesses
├── tools/                    ← spec generators, static audits, A/B reporters
├── vendor/balatro-rl/        ← live simulator + agents (EDIT HERE)
│   └── balatro_sim/          ← game.py, shop.py, scoring, jokers, agent_v9/v10
└── vendor/balatro-rs/        ← Rust reference (RNG / scoring oracle; do not train on it)
```

First-party Python lives in `bench/` and `tools/`. Almost all game and agent
code lives under `vendor/balatro-rl/balatro_sim/` — that tree is **vendored then
forked**. Treat it as this project's source, not an untouched upstream.

A full file map is in [docs/REPO_MAP.md](docs/REPO_MAP.md).

---

## Quick start

Python 3.11. From the repo root:

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements-ci.txt
```

```bash
# Full sim suite (skips the slow seed-exactness gate)
python -m pytest vendor/balatro-rl/tests vendor/balatro-rl/balatro_sim/tests -q

# Seed-exactness gate (CI also runs this)
python -m pytest vendor/balatro-rl/tests/test_seed_exactness.py -m ci_gate -v

# Static audits vs the mechanics sheet (must stay CLEAN)
python tools/audit_jokers_static.py
python tools/audit_consumables_static.py
python tools/audit_bosses_static.py
python tools/audit_tags_static.py

# Random-agent throughput + win-rate floor
python bench/bench_sim.py --games 200

# Human-fair V9 / V10 A/B (small smoke)
python bench/bench_v9.py --games 20 --policies heuristic_v9
python bench/bench_agent_v10.py --games 20 --policies heuristic_v9,heuristic_v10
```

There is no `pip install -e .`. Scripts insert `vendor/balatro-rl` onto
`sys.path`. Always run them from the **repo root**.

---

## Where to look

| I want to… | Open |
|---|---|
| Understand the project bet | [docs/spec.md](docs/spec.md) |
| See what is finished / still open | [docs/STATUS.md](docs/STATUS.md) |
| Edit game rules / jokers / shop | `vendor/balatro-rl/balatro_sim/` |
| Edit the current agent | `vendor/balatro-rl/balatro_sim/agent_v10.py` (v9 is the frozen A/B baseline) |
| Check a mechanic against the sheet | [docs/reference/balatro-mechanics.md](docs/reference/balatro-mechanics.md) |
| Run or add a benchmark | [bench/README.md](bench/README.md) |
| Regenerate a spec JSON | [tools/README.md](tools/README.md) |
| Read an experiment archive | [vendor/balatro-rl/results/README.md](vendor/balatro-rl/results/README.md) |
| See prior-art RL history | `vendor/balatro-rl/README.md` and `results/PROJECT_RETROSPECTIVE.md` |

---

## Licensing

Neither vendored tree ships a LICENSE. Default is all rights reserved. This
repo is a local research fork — do not redistribute the vendored code without
permission from the original maintainers.

- Simulator origin: [taggarttufte/balatro-rl](https://github.com/taggarttufte/balatro-rl)
- RNG / scoring reference: [evanofslack/balatro-rs](https://github.com/evanofslack/balatro-rs)
- Balatro itself is © LocalThunk / Playstack. Unofficial research only.
