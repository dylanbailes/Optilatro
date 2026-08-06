# Balatro RL — Project Map
*Last updated: 2026-03-27*

---

## Core Python Package — `balatro_rl/`

| File | What it does |
|------|-------------|
| `env.py` | v1 env (single instance, old IPC) — obsolete |
| `env_v2.py` | v2 env (single instance, file-based IPC) — used by `train_v2.py` |
| `env_parallel.py` | v2 parallel env (8 instances, file-based IPC, seed-fix applied 2026-03-27) — **current active env** |
| `action.py` | v1 action space |
| `action_v2.py` | v2 action space — used by all current envs |
| `state.py` | v1 state parser |
| `state_v2.py` | v2 state parser (206-feature obs space) — used by all current envs |
| `nav.py` | Mouse navigation helpers (click-based UI control) |
| `ray/balatro_env.py` | Ray RLlib wrapper around `env_parallel.py` |
| `ray/callbacks.py` | Ray training callbacks (NEW BEST logging, stats checkpointing every 10 iters) |

---

## Training Scripts

| File | What it does |
|------|-------------|
| `train.py` | v1 SB3 single instance — obsolete |
| `train_v2.py` | v2 SB3 single instance — produced the 60%/ante-8 run in `logs_v2/` |
| `train_v2_parallel.py` | v2 SB3 parallel (multi-instance, SB3 VecEnv) — experimental, predates Ray |
| `train_parallel.py` | Earlier parallel attempt — obsolete |
| `train_ray.py` | **Current training script** — Ray RLlib PPO, 8 envs, run `brisk-canyon` |

---

## Test Scripts

| File | What it does |
|------|-------------|
| `test_v2.py` | Smoke test for v2 env |
| `test_parallel_2.py` | 2-instance parallel test |
| `test_parallel_train.py` | Parallel training smoke test |
| `test_loop.py` | Basic env loop test |
| `test_autopilot.py` | Autopilot/nav test |
| `test_nav.py` | Navigation test |
| `test_shop.py` | Shop interaction test |

---

## Analysis & Utility Scripts

| File | What it does |
|------|-------------|
| `analyze.py` | General episode log analysis |
| `analyze_recent.py` | Recent episode analysis (rolling windows) |
| `ante8_analysis.py` | Deep-dive on ante 8 runs |
| `ante8_breakdown.py` | Ante 8 run breakdown |
| `check_best.py` | Print best runs from logs |
| `check_blind_data.py` | Blind-level survival stats |
| `check_drop.py` | Detect performance drops |
| `check_hook.py` | Check Lua hook / IPC connection |
| `check_progress.py` | Training progress summary |
| `check_recent.py` | Recent episode summary |
| `check_scores.py` | Score distribution |
| `check_trend.py` | Rolling trend analysis |
| `find_unicode.py` | Debug: find unicode issues in state JSON |
| `highscore_analysis.py` | High score run analysis |
| `overnight_analysis.py` | Overnight run summary |
| `plot_training.py` | Plot training curves (v1/v2 logs) |
| `plot_v2.py` | Plot v2 training curves |
| `plot_with_blinds.py` | Plot blind survival over training |
| `top10.py` | Print top 10 runs |
| `v1_final_stats.py` | v1 final stats summary |

---

## Lua Mods

| Location | File | What it does |
|----------|------|-------------|
| `mod/` | `BalatroRL.lua` | v1 mod (old, file-based IPC, no instance guard) — obsolete |
| `mod/` | `metadata.json` | LÖVE mod metadata for v1 |
| `mod_v2/` | `BalatroRL_v2.lua` | v2 mod (file-based IPC) — used by current training |
| `mod_v2/` | `BalatroRL_parallel.lua` | v2 parallel mod (instance-numbered file paths) |
| `versions/` | `BalatroRL_lua_nav.lua` | Archived: version with mouse navigation |
| `versions/` | `BalatroRL_no_nav.lua` | Archived: version without nav |
| `versions/` | `nav_mouse.py` | Archived: Python mouse nav helper |
| `versions/` | `test_nav_mouse.py` | Archived: nav test |
| `versions/` | `README.md` | Notes on archived versions |

**Live mods (installed in Balatro):**
- `C:\Users\Taggart\AppData\Roaming\Balatro\Mods\BalatroRL\` — current active mod (v2, instances 1-8)

---

## Data & Logs

### `logs_v2/` — v2 Single Instance Run (THE GOOD RUN)
The run that achieved 60% ante2+ at ~8.7k episodes, best ante 8.

| File | What it is |
|------|-----------|
| `episode_log.jsonl` | 9,073 episodes, 41% overall ante2+, best ante 9, 25 resets |
| `episode_log_parallel.jsonl` | 4,429 eps from SB3 parallel attempt (pre-seed-fix, ~10% ante2+) |
| `best_runs.jsonl` | Top runs by ante (best: ante 8, ep 40) |
| `top_runs_recent.jsonl` | Top 10 most recent best runs |
| `run_detail_log.jsonl` | Detailed per-run logs (895 entries) |
| `training_output.txt` | Terminal output from v2 single training |
| `training_output_8inst.txt` | Terminal output from 8-instance SB3 attempt |
| `training_final.txt` | Final training session output |
| `training_fixed.txt` | Training output after bug fixes |
| `training_stable.txt` | Training output from stable period |
| `training_metrics.png` | Training metrics plot |
| `training_progress.png` | Training progress plot |
| `training_with_blinds.png` | Plot with blind-level breakdown |
| `v2_full_analysis.png` | Full analysis plot |
| `v2_training_analysis.png` | Training analysis plot |
| `tensorboard/` | TensorBoard event files (MaskablePPO runs 1-7) |

### `logs_ray/` — Current Ray PPO Run (brisk-canyon, started 2026-03-27 13:08 MDT)

| File | What it is |
|------|-----------|
| `training_8env.log` | Main training stdout log |
| `training_8env_err.log` | stderr log |
| `training.log` | Earlier Ray test run log |
| `stderr.txt` | Earlier stderr |
| `episodes.jsonl` | Episode log (currently empty — callback writes to wrong path) |
| `training_plot.png` | Early training plot |
| `training_plot_v2parallel.png` | v2 parallel training plot |
| `comparison_plot.png` | v2 single vs v2 parallel comparison (generated 2026-03-27) |

---

## Checkpoints

### `checkpoints_v2/` — v2 SB3 Model Weights (165 MB)
Model weights from the 60%/ante-8 run. Saved every 10k steps.
- `ppo_v2_10000.zip` through `ppo_v2_210000.zip` — regular checkpoints
- `ppo_v2_final_*_steps.zip` — final saves at end of training
- `ppo_v2_interrupted_*.zip` — saves on Ctrl+C (many due to instability early on)
- `ppo_v2_parallel_*_steps.zip` — saves from the SB3 parallel attempt

### `checkpoints_ray/` — Current Ray PPO Run (active, do not delete)
- `stats_iter_10.json` through `stats_iter_220.json` — PPO iteration stats snapshots
- `rllib_checkpoint.json` + subdirs — Ray checkpoint (most recent, auto-overwritten each iter)

---

## Documentation

| File | What it is |
|------|-----------|
| `README.md` | Project overview |
| `NOTES.md` | Dev notes (various) |
| `PARALLEL_SETUP.md` | How to set up and launch parallel instances |
| `V1_RESULTS.md` | v1 training results summary |
| `V3_DESIGN_NOTES.md` | Socket-based IPC rewrite design doc |
| `TRAINING_SAVEPOINT_2026-03-27.md` | Savepoint doc: all timing constants, Ray config, run state as of 2026-03-27 |
| `docs/v2_training_progress.png` | v2 progress plot (copy in docs/) |
| `results/training_progress.png` | Another copy of a progress plot |

---

## PowerShell Scripts

| File | What it does |
|------|-------------|
| `launch_2_instances.ps1` | Launch 2 Balatro instances for parallel training |
| `launch_parallel.ps1` | Launch full parallel setup (8 instances) |
| `setup_parallel.ps1` | One-time setup for parallel instance directories |
| `swap_version.ps1` | Swap active Lua mod version |

---

## What's Running Right Now

- **Nothing** — all training paused as of 2026-03-27
  - V2 parallel (`brisk-canyon`) permanently paused at iter ~20, ~41k steps
  - V3 Ray attempts abandoned (see NOTES.md for full bug log)

## Next Step

- **V3 custom training loop**: Write `train_v3.py` — threaded PPO, 8 envs, no Ray
  - Design in `V3_DESIGN_NOTES.md`
  - All 8 instances ready, socket IPC validated, env_socket.py working
