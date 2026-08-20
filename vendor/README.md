# vendor/

Two upstream snapshots, tracked as **plain files** (no git submodules).

| Dir | Origin | Role here |
|---|---|---|
| `balatro-rl/` | [taggarttufte/balatro-rl](https://github.com/taggarttufte/balatro-rl) (originally commit `59588ba`, then heavily forked) | **Live simulator and agents** |
| `balatro-rs/` | [evanofslack/balatro-rs](https://github.com/evanofslack/balatro-rs) | Reference RNG + scoring. Not the training env. |

Neither upstream ships a LICENSE. Do not redistribute.

## balatro-rl — what to touch

Edit:

- `balatro-rl/balatro_sim/` — game, shop, scoring, jokers, agents
- `balatro-rl/tests/` — almost all first-party tests

Read, do not extend:

- `balatro-rl/README.md` / `PROJECT_MAP.md` — **stale** (upstream V1–V8 story)
- `balatro-rl/balatro_rl/`, `legacy/`, `mod/`, `mod_v2/`, `launch/`, `viz/`
- `balatro-rl/results/V1_*` … `V8_*` — prior-art RL notes

Experiment archives we added: `balatro-rl/results/` — see
[balatro-rl/results/README.md](balatro-rl/results/README.md).

## Re-vendor warning

If you `git clone` into `vendor/balatro-rl` or `vendor/balatro-rs`, git will
record a **gitlink** (mode 160000) and CI will check out an empty directory.

1. Copy files, or clone elsewhere and rsync.
2. Delete any nested `.git` before staging.
3. `test -f vendor/balatro-rl/balatro_sim/game.py` must succeed.

## balatro-rs — how we use it

- `balatro-seed` is the algorithm `balatro_sim/seed_rng.py` ports.
- `core` / `joker_data!` were used to rebuild `JOKER_CATALOGUE`.
- `calc` / `explore` CLIs are optional oracles if you have a Rust toolchain.
  They are **not** required to run tests.
