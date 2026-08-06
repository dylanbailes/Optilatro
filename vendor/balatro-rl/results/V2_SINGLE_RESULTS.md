# V2 Single Instance Training Results

**Training period:** March 2026  
**Architecture:** Discrete(20) action space, SB3 MaskablePPO, single instance, file IPC  
**Script:** `train_v2.py` | **Env:** `env_v2.py` | **Logs:** `logs_v2/`  
**Status:** Complete — superseded by v2 parallel (Ray)

---

## Final Statistics

| Metric | Value |
|--------|-------|
| Total episodes | 9,073 |
| Total timesteps | ~210,000 |
| Training sessions | ~25 restarts |
| Best ante reached | Ante 9 (episode 40) |
| Overall ante 2+ rate | 41% |

---

## Performance Snapshot (~8,700 episodes)

At episode 8,732 (snapshot from 3/21 ~6pm — a confirmed reference point):

- **Ante 2+ rate (last 500 eps): 60.4%**

| Ante | % of runs |
|------|-----------|
| 1 | 39.6% |
| 2 | 26.2% |
| 3 | 24.0% |
| 4 | 8.2% |
| 5 | 1.6% |
| 6 | 0.4% |

### Blind-Level Survival
- **Small Blind:** ~61% of runs end here (40% survival rate)
- **Big Blind:** ~0% die here once past Small (~100% survival)
- **Boss Blind:** ~39% of runs end here (~60% survival rate)

Key finding: Small Blind is the primary bottleneck. Agent learned Big Blind is nearly
free but Boss Blind still kills ~40% of runs that reach it.

---

## Throughput

- ~6 steps/sec (file IPC, 64x game speed, single instance)
- ~1,800 steps/hour
- Average episode length: ~14 steps

---

## What V2 Learned (vs V1)

V2 introduced Discrete(20) action space — Lua pre-ranks all valid plays and discards,
agent picks one of top 10 plays or top 10 discards. This was the key architectural change.

- **Dramatically better hand selection:** Agent now picks from pre-evaluated options
  rather than blindly setting 9 card-selection bits
- **60% ante 2+ rate** vs V1's ~1.9% overall — ~30x improvement
- **Boss Blind still the ceiling:** Ante 4+ requires joker luck, not pure skill
- **Best run: Ante 9** (ep 40, likely early lucky joker draw)

---

## Bugs Fixed During V2 Single Training

- **Shop skip bug:** Agent held $50+ by ante 3 while ignoring shop when slots full.
  Fix: sell-upgrade heuristic — sell weakest joker if shop has strictly higher rarity joker.
- **Edition scoring:** Added Poly+10, Holo+5, Foil+3 to joker effective_value calculation.
- **Negative joker protection:** Never sell Negative jokers regardless of upgrade opportunity.
- **Reroll logic:** One reroll per shop when cash > 2x reroll_cost and no jokers available.
- **WON watchdog removed:** Was causing ante double-increment on The Hook boss.
- **Ante guard self-recovery:** Lua fires start_run when rr_ante > win_ante (edge case fix).

---

## Checkpoints

Saved to `checkpoints_v2/` every 10k steps and on Ctrl+C.
- `ppo_v2_10000.zip` through `ppo_v2_210000.zip` — regular checkpoints
- `ppo_v2_final_*_steps.zip` — final saves
- `ppo_v2_interrupted_*.zip` — interrupt saves (~many, due to early instability)

Model weights are 165MB total. Compatible with v2 single config only (Discrete(20),
206-feature obs). Not compatible with v2 parallel (different training stack).

---

## Transition to V2 Parallel

After 9,073 episodes, v2 single plateaued around 60% ante2+ rate. Small Blind survival
was the clear bottleneck. Two options: train longer (diminishing returns) or scale up
throughput with parallel instances to explore more episodes faster.

Decision: move to 8-instance parallel setup with Ray RLlib PPO.
See `V2_PARALLEL_RESULTS.md` for that run.
