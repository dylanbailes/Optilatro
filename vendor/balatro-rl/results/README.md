# results/ — experiment archive

~20k JSON run files plus upstream design notes. **Do not delete** a folder
because it looks noisy; several A/Bs are the reason we stopped retrying a
failed idea.

## Read these first (upstream RL, concluded)

| File | Why |
|---|---|
| `PROJECT_RETROSPECTIVE.md` | Why PPO stopped at 2.35% |
| `V7_RUN_LOG.md` / `V7_PLANNING.md` | Best RL result |
| `V8_DESIGN_NOTES.md` / `V8_RUN_LOG.md` | Failed self-play |
| `V9_DESIGN_NOTES.md` | Search-first pivot (this project's track) |

`V1`–`V6` notes are prior-art only.

## First-party experiment folders (have their own README)

| Folder | Question |
|---|---|
| `bench_human_fair_2026-08-17/` | Human-fair vs lookahead oracle |
| `discard_ev_experiments_2026-08-17/` | Discard-EV v2 — all variants worse |
| `structure_discard_2026-08-18/` | Structure-aware discard / play-good-hand |
| `ante1_economy_2026-08-18/` | Ante-1 interest floors — all worse |

## Sweeps

| File | What |
|---|---|
| `sweep_v10.md` | Farm knobs; defaults win |
| `sweep_v10_tier2.md` | `tier2_min_value` / `opp_bonus`; defaults kept |
| `sweep_v10/` | Per-config JSON sidecars |

## Raw telemetry dirs (`*_tel`, `tel_*`)

Working output from `bench/bench_v9.py --telemetry-dir`. Named by experiment
(`hf_ab_tel`, `tel_lifecycle_heur`, `econ_v1_tel`, …). Prefer the dated
folders above when a README exists; use raw dirs only to rebuild a report:

```bash
python tools/report_bench_ab.py --out vendor/balatro-rl/results/<name> \
    --arm "label" vendor/balatro-rl/results/<tel>/<policy> "repro command"
```

Large one-off dumps (`reshape_*.json`) are confirm-run sidecars, not source.
