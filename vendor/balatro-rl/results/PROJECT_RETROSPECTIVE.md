# Balatro RL — Project Retrospective

**Status:** Concluded (April 2026). Capped at PPO-based approach after
V7 Run 7 confirmed that the ~2% win rate is a structural ceiling of
shaped-reward PPO, not a network capacity limit.

**Final result:** 2.35% solo win rate (V7 Run 4), reached ante 9 reliably,
used strategic discards ~30% of SELECTING_HAND steps, filled joker slots
96% of the time. Random play wins <0.01%; skilled humans win ~70%.

---

## The Journey, In One Paragraph

V1–V3 trained against the real game via Lua mod with file/socket IPC,
topping out at ~14 sps with RAM degradation. V4 pivoted to a pure Python
sim (~1000 sps) and produced inflated wins from fixed seeds + a broken
Burglar joker. V5 tried a dual-agent split (play / shop) and failed 12
times on shop starvation. V6 audited the sim (32 joker bugs fixed),
switched to random seeds, and got the first legitimate 1.9% win rate
from a single-agent PPO with pre-ranked combo actions. V7 replaced the
combo ranking with a hierarchical intent + learned card selection
architecture, reached **2.35% win rate** (Run 4), and plateaued there
across six reward-shaping experiments. V8 tried self-play multiplayer
to break the plateau and fell short (reward plateau at ~8 after 1000
iters). V7 Run 7 scaled the network 5.5x as a final test and confirmed
that capacity is not the bottleneck.

---

## The Three Ceilings

Each version hit a different wall. Understanding them is the most
valuable artifact of this project.

### Ceiling 1 — Simulation Fidelity (V4)

V4 reported huge win rates that turned out to be artifacts: fixed-seed
memorization + a Burglar joker that multiplied chips instead of modifying
the hand, letting the policy score fake 612M-chip pairs. Auditing every
joker in V6 revealed ~30% had wrong implementations. **Takeaway:** any
result before sim audit is untrusted.

### Ceiling 2 — Action Space Expressiveness (V6)

V6 with pre-ranked combos got 1.9% but 80% of games died at ante 1. The
agent always picked action 0 (best combo by score) and never learned to
discard bad cards strategically. The action space made the right
decision easy but the *interesting* decisions impossible. **Takeaway:**
pre-ranking trades short-term learning speed for a hard ceiling.

### Ceiling 3 — Strategy Discovery (V7, V8, V7 Run 7)

V7's hierarchical action space broke the V6 ceiling (2.35%) and the
agent did learn strategic discarding. But it also locked in on a single
dominant strategy — Green Joker + Space Joker — across six different
reward-shaping experiments. V8 tried self-play to force alternative
strategies through same-seed comparison and PvP pressure; it plateaued
worse than V7. V7 Run 7 scaled the network to 13.6M params (5.5x) and
still showed the same early-peak, plateau-then-drift pattern. **Takeaway:**
shaped-reward PPO at our scale cannot discover multi-step coordinated
strategies that require exploring a specific sequence of shop purchases
across multiple antes. The ceiling is the exploration mechanism, not
capacity.

---

## Cross-Version Summary

| Version | Method | Peak WR | Hit By |
|:-:|---|:-:|---|
| V1–V3 | Live game, IPC | <0.01% | IPC bottleneck, RAM leak |
| V4 | Python sim, fixed seeds | inflated | Memorization + sim bugs |
| V5 | Dual-agent (play/shop) | 0% | Shop starvation (12 failed runs) |
| V6 | Single-agent, combo ranker | 1.9% | Action space rigidity |
| **V7 Run 4** | **Hierarchical + shaped reward** | **2.35%** | **Green+Space strategy lock-in** |
| V7 Runs 5-6 | Reward-shape retunes | 2.07-2.23% | Same lock-in |
| V7 Run 7 | 5.5x network + 2x batch | 0.16%@184 | Same plateau, killed early |
| V8 Runs 1-2 | Self-play + V7 migration | 0% | Migration disrupted V7 competence |
| V8 Run 3 | Self-play + MP obs + HOUSE RULE | 0% | Lives buffer masked failure |
| V8 Run 4 | Self-play, no lives | 0% | Two weak policies, no teaching signal |

---

## What Worked

- **Python simulation** instead of live-game training: 12,500x throughput speedup, made everything downstream possible
- **Random seeds per episode**: the test that separates memorization from generalization
- **Joker audit**: one 30% implementation error rate will kill any RL experiment silently
- **Hierarchical action space (intent + subset)**: V7's win over V6 proves factored actions with factored log_prob work for combinatorial decisions
- **Per-card features in obs**: adding suit_match, rank_match, straight_connectivity, chip_value gave the card head something to condition on
- **Shaped reward for card quality**: `played_score / best_possible_score` was the single most impactful reward term
- **Same-seed self-play infrastructure**: even though V8 plateaued, the same-seed comparison mechanism was clean and the feature-importance analysis confirmed the MP obs features were used

## What Didn't Work

- **Dual-agent architectures** (V5): starvation is structural, not tunable
- **V7 → V8 weight migration**: V7's sharp distributions couldn't survive new reward gradients + self-play symmetry; lost competence before gaining new strategies
- **HOUSE RULE buffer in V8 Run 3**: 4 lives made failure cheap; agent optimized for small rewards while burning lives
- **Symmetric self-play from fresh weights**: two weak policies teach each other nothing; 74% draws until temperature asymmetry added
- **Scaling the network (V7 Run 7)**: 5.5x params did not break the 2% plateau; early peak then drift, same shape as baseline V7

## What I Never Tried

- **Search (MCTS or planning)**: the most promising remaining direction
- **Curriculum learning** where Green+Space is disabled for first N steps
- **Population-based training** with reward diversity + Hall of Fame (planned in V7 log, never implemented)
- **Joker positioning as an explicit action** (Blueprint/Brainstorm are auto-placed)
- **Supervised imitation** from a scripted strategic player

---

## The Key Insight

**For long-horizon games where winning requires coordinated multi-step
strategies, shaped-reward PPO appears capacity-insensitive past a
threshold.** Six runs of reward retuning at ~2.5M params and one run at
13.6M params all produced the same ceiling. The policy converges to the
single strategy its exploration mechanism can reach, and reward shaping
alone cannot drag it to a better basin — the alternative strategies
require committing to a specific sequence of shop purchases across
multiple antes that the one-step PPO gradient never sees as a coherent
"action."

The right next axis is **search**, not scale.

---

## Future Direction — MCTS + Neural Network

If I return to this project (probably only if compute becomes much
cheaper — a weekend's MCTS training, not a multi-week run), the
approach would be:

1. **MCTS at decision points** — at each shop/card selection, run a
   Monte Carlo search using the current policy network as a prior and
   the value network as the rollout estimator.
2. **Policy improvement via MCTS targets** — train the network on the
   MCTS-improved action distribution (AlphaZero-style), not just raw
   rewards.
3. **Expected benefit**: MCTS provides explicit lookahead over
   multi-step joker purchase sequences. The policy learns "if I buy
   Green now, then Space next shop, I clear ante 8" as a single
   coordinated target, rather than having to stumble into it through
   single-step gradient noise.
4. **Risk**: MCTS on Balatro is expensive — the branching factor at
   shops is ~50 (buy/skip/reroll combinations) and the horizon is long.
   Will need heavy use of the neural network prior to keep the search
   tractable.

See `results/V7_RUN_LOG.md` Section "V8 Design Plan" for an earlier
population-based approach that was partially implemented as V8.

---

## Compute Cost Accounting

Approximate total compute spent:

| Phase | Wall Time | Notes |
|:-:|:-:|---|
| V1-V3 (live game) | ~150 hrs | Many killed runs from RAM degradation |
| V4-V6 (sim iteration) | ~100 hrs | Mostly V6 runs + audit work |
| V7 Runs 1-6 | ~80 hrs | 6 complete 1000-iter runs |
| V8 Runs 1-4 | ~30 hrs | Mostly killed early, Run 4 ran full 1000 iters |
| V7 Run 7 | ~6 hrs | 184 iters, killed at plateau |
| **Total** | **~366 hrs** | RTX 3080 Ti, Ryzen 9 7950X |

Per-win cost analysis: V7 Run 4's 2.35% win rate = ~24 wins per 1000
games = ~150 hrs / 24 = ~6 hrs of compute per 1% win rate point. For
MCTS to be worth pursuing, compute per improvement point needs to drop
significantly, or the ceiling needs to rise enough that a weekend of
work produces >5% win rate.

---

## Files of Lasting Value

- [`balatro_sim/`](../balatro_sim/) — audited Python simulation, 164 jokers, 99 consumables, boss blinds, deck mechanics
- [`results/V6_DESIGN_NOTES.md`](V6_DESIGN_NOTES.md) — joker audit notes, sim fidelity checklist
- [`results/V7_PLANNING.md`](V7_PLANNING.md) — hierarchical action space design (the architecture that broke V6's ceiling)
- [`results/V7_RUN_LOG.md`](V7_RUN_LOG.md) — six reward-shaping experiments, Green+Space plateau analysis, Run 7 scaling finding
- [`results/V8_DESIGN_NOTES.md`](V8_DESIGN_NOTES.md) + [`results/V8_RUN_LOG.md`](V8_RUN_LOG.md) — self-play experiment documentation
- [`scripts/analyze_feature_importance.py`](../scripts/analyze_feature_importance.py) — gradient-attribution diagnostic, confirmed MP obs features were used

---

*Project concluded April 2026. Five months, eight architecture versions,
~366 hours of compute, one 2.35% win rate, and a clear answer to "is
the ceiling capacity or search?" — it's search.*
