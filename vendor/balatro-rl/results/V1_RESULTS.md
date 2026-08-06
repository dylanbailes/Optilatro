# V1 Training Results

**Training period:** March 2026  
**Architecture:** MultiBinary(9) action space, 119-feature observation

## Final Statistics

| Metric | Value |
|--------|-------|
| Total episodes | 26,412 |
| Total timesteps | 376,409 |
| Training sessions | 54 |

### Reward
- **Overall average:** 1.61
- **Post-bugfix average:** 5.54
- **Maximum:** 62.69

### Ante Distribution
| Ante | Count | Percentage |
|------|-------|------------|
| 1 | 25,914 | 98.11% |
| 2 | 322 | 1.22% |
| 3 | 141 | 0.53% |
| 4 | 33 | 0.12% |
| 5 | 2 | 0.01% |

- **Ante 2+ rate:** 1.89%
- **Ante 3+ rate:** 0.67%

### Top 5 Runs
| Episode | Ante | Reward | Steps |
|---------|------|--------|-------|
| 1505 | 4 | 62.69 | 124 |
| 1203 | 4 | 57.14 | 124 |
| 1499 | 3 | 56.62 | 67 |
| 832 | 3 | 55.49 | 109 |
| 593 | 4 | 54.81 | 115 |

## Key Findings

### What V1 Learned
- Basic macro strategy: discard weak cards, then play
- Consistently clear Small Blind + Big Blind at ante 1
- Average episode length ~14 steps indicates full blind attempts

### V1 Limitations (Why We Built V2)
1. **Blind card selection:** Agent picks card *slots* without evaluating hand combinations
2. **No score estimation:** Can't compare "Pair of Kings" vs "Flush draw"
3. **Deep runs are joker lottery:** Ante 3+ requires lucky joker pulls, not skill
4. **Plateau at ~5.5 avg reward:** No improvement after ~20k episodes post-bugfix

### Bugs Fixed During V1
- False LOST terminal (chips not finalized at 32x speed)
- Post-action spin loop (same state returned repeatedly)
- Mid-run reset deadlock (Python reset while Lua kept playing)
- G.E_MANAGER.queue nil crash (The Hook boss edge case)
- Circular import crash (env.py importing from train.py)

## Transition to V2

V1's ceiling confirmed the hypothesis: **card evaluation is the bottleneck**.

V2 changes:
- `Discrete(20)` action space with pre-ranked plays/discards
- Lua-side hand evaluation with joker bonus estimation
- Deck composition in observation space
- Discard reward based on Δ best_play_score

See [V2 implementation](mod_v2/) for details.
