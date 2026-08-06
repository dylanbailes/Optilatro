# V2 Parallel Training Results

**Training period:** March 2026  
**Architecture:** Discrete(20) action space, Ray PPO (old API stack), 8 parallel instances, file IPC  
**Run name:** brisk-canyon  
**Status:** Permanently paused at iter ~20 (~41k steps) to pursue socket IPC (v3)

---

## Configuration

- 8 Balatro instances, 64x game speed
- Ray PPO, old API stack (new API hangs — upstream Ray bug #53727)
- `rollout_fragment_length=128`, `train_batch_size=2048`, `num_epochs=10`
- `lr=3e-4`, `gamma=0.99`, `entropy_coeff=0.01`
- File IPC: Lua writes state.json, Python reads + writes action.json
- Throughput: ~6 steps/sec total across 8 envs (~2,500 steps/hour)

---

## Results at Pause Point

| Metric | Value |
|--------|-------|
| Iterations completed | ~20 |
| Total timesteps | ~41,000 |
| Best ante reached | Ante 5 (episode 279) |
| PPO updates/hour | ~10-11 |
| Estimated time to 500 iters | ~45-50 hours |

### Milestone Progression
| Episode | Ante Reached |
|---------|-------------|
| 1 | Ante 1 (baseline) |
| 32 | Ante 2 |
| 112 | Ante 4 |
| 279 | Ante 5 |

---

## Ante Distribution Context (from v2 single run)

From the v2 single-instance run that preceded parallel training
(9,073 total episodes, ~210k timesteps — see V2_SINGLE_RESULTS.md):

At ~8,732 episodes (snapshot from 3/21 ~6pm):
- Ante 2+ rate (last 500 eps): **60.4%**
- Ante 1: 39.6% | Ante 2: 26.2% | Ante 3: 24.0% | Ante 4: 8.2% | Ante 5: 1.6% | Ante 6: 0.4%

### Key Finding: Small Blind is the Bottleneck
- ~61% of runs end at Small Blind (40% survival rate past Small)
- ~0% die at Big Blind once past Small (~100% survival if Small cleared)
- ~39% of runs end at Boss Blind (~60% survival rate)
- Implication: agent learned Big Blind is nearly free but Boss still kills ~40% of runs that reach it

### Episode Length
- v2 single: ~14 steps/episode average
- v2 parallel: ~67 steps/episode average
  (longer because Discrete(20) executes cleaner actions; file IPC drops fewer steps)

---

## Throughput Comparison

| Setup | Steps/sec | Steps/hour |
|-------|-----------|------------|
| v1 single (file IPC, 64x) | ~0.06-0.11 | ~200-400 |
| v2 single (file IPC, 64x) | ~0.5 | ~1,800 |
| v2 parallel 8x (file IPC, 64x) | ~6 | ~21,600 |
| v3 socket single (64x) | ~6.1 | ~22,000 |
| v3 socket single (128x) | ~11.7 | ~42,000 |
| v3 socket 8x target (128x) | ~94 | ~338,000 |

---

## Why We Paused

Socket IPC benchmark showed 3.31x throughput improvement over file IPC at identical
game speed. Extrapolated to 8 instances at 128x: ~94 steps/sec vs v2 parallel's ~6
steps/sec — a ~16x improvement. The performance gap was large enough to justify
pausing brisk-canyon and building v3 before accumulating more v2 data.

v2 parallel training was NOT producing bad results — the ante progression (Ante 5 by
episode 279) was on track. The decision was purely about throughput: spending 45-50
hours on a v2 run that could be done in ~3 hours with a working v3 wasn't worth it.

---

## Bugs Fixed During v2 Parallel Bring-Up

- **Episode terminal race condition:** At 64x speed, Lua writes game_over then
  immediately starts new game, overwriting state.json before Python polls. Python
  missed the terminal signal entirely — 0 completed episodes despite 80k+ steps.
  Fix: track episode_seed at reset(); if new state has different seed, treat as terminal.

- **Episode counter always 0:** Ray callbacks (on_episode_end) run in the worker
  subprocess, not main process. Counter in on_train_result always showed 0. Cosmetic
  only — [NEW BEST] log messages confirmed episodes were completing correctly.

---

## Checkpoints

Saved to `checkpoints_ray/` at each iteration. Last checkpoint: iter ~20, ~41k steps.
Compatible with v2 parallel config only (Discrete(20), 119-feature obs).
Not compatible with any future v3 obs space changes.
