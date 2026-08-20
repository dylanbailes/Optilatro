# bench/

Win-rate and throughput harnesses. Run from the **repo root**.

Policies import `vendor/balatro-rl` via `sys.path` — nothing is installed.

## Scripts

| Script | Measures |
|---|---|
| `bench_sim.py` | Random-agent steps/s + win rate (the 0.10% floor) |
| `bench_ab_reshuffle.py` | Same, with mid-round reshuffle monkey-patched off |
| `bench_v9.py` | V9 policies, seed bank, telemetry, HTML report, `--resume` |
| `bench_agent_v10.py` | Paired V9 vs V10 + econ-source / interest telemetry |

## Typical invocations

```bash
python bench/bench_sim.py --games 200

python bench/bench_v9.py --games 50 --policies heuristic_v9 \
    --telemetry-dir vendor/balatro-rl/results/scratch_tel

python bench/bench_agent_v10.py --games 50 \
    --policies heuristic_v9,heuristic_v10
```

Human-fair is the default. `bench_v9.py --lookahead` turns on the
perfect-forward-model shop search and **prints a not-a-benchmark warning**.

`--params '{"farm_clear_threshold": 1.0}'` is the V10 farming-off control
(must stay byte-identical to V9).

## Conventions

- Fixed seed bank, `rng_mode=seed`, same seeds on every arm.
- Progress every `--batch-size` runs; `--resume` reloads `run_<seed>.json`.
- Archive a real experiment with `tools/report_bench_ab.py` under
  `vendor/balatro-rl/results/<name>/` rather than leaving raw `*_tel/` dirs
  unexplained.
