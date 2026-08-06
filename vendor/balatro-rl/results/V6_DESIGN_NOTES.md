# V6 Design Notes — Single Agent with Enhanced Shop Awareness

*Written 2026-04-09. V5 dual-agent architecture failed due to structural shop starvation.
V6 returns to V4's single-agent approach but incorporates all V5 learnings: richer shop
observations, heuristic shop reward shaping, and bug fixes that dramatically improved play.*

---

## What Happened to V5

V5 split the single PPO agent into two cooperating networks (Play + Shop) with a 32-dim
communication vector. After 12 training runs and extensive debugging, the approach failed:

1. **Shop starvation:** The shop agent received 0.1% of total training steps. The play agent
   dominated all data collection. Every attempt to balance this (dedicated shop workers,
   asymmetric collection, min shop steps) either starved the play agent or didn't collect
   enough shop data to learn.

2. **Credit assignment gap:** Jokers bought at step 50 pay off at step 400+. PPO's GAE
   cannot trace this across agent boundaries. The shop agent never connected purchases to
   downstream scoring improvements.

3. **Entropy collapse:** The play agent converges to "always play best combo" within 10-20
   iterations. With correct combo ranking (see bug fix below), action 0 is overwhelmingly
   dominant. Entropy floors fought the natural gradient and degraded play performance.

4. **The fundamental tension:** Play needs massive data to learn (65k steps/iter works).
   Shop needs data it almost never gets organically. Every fix for one hurts the other.

**Conclusion:** Dual-agent is the wrong abstraction for this problem. The single agent sees
both play and shop phases in one trajectory, naturally solving credit assignment and data
balance.

---

## V6 vs V4 — What Changed

V6 uses V4's single-agent architecture (`env_sim.py` + `train_sim.py`) with these additions:

### 1. Critical Bug Fix: Combo Scoring (from V5 debugging)

V5's `env_v5.py._update_play_combos()` had a broken call:
```python
# BROKEN (V5) — passes indices as all_cards, game object as hand_type
score, _ = score_hand(cards, list(combo), gs)
# Every call threw an exception, fell into score = 0
# All 20 combos had identical score — agent played random combos
```

V4's `env_sim.py` already had the correct implementation:
```python
# CORRECT (V4/V6) — proper named arguments
hand_type, scoring_cards = evaluate_hand(cards)
actual_score, _ = score_hand(
    scoring_cards=scoring_cards, all_cards=cards, hand_type=hand_type,
    jokers=gs.jokers, planet_levels=gs.planet_levels, ...
)
```

This single bug was why V5 runs 1-9 (1480 iterations) never cleared ante 1. Once fixed,
the agent immediately achieved 46% blind clear rate.

### 2. Enhanced Observation Space (342 → 402 dims)

Added 60 new features for shop decision-making:

| Range | Features | Description |
|-------|----------|-------------|
| `[342:344]` | 2 | Reroll cost (normalized), free rerolls remaining |
| `[344:371]` | 27 | Voucher ownership flags (binary) |
| `[371:386]` | 15 | Boss blind one-hot (which boss is active/upcoming) |
| `[386:394]` | 8 | Deck composition: 4 suit ratios + face/ace/number/total |
| `[394:402]` | 8 | Enhancement/edition/seal counts in deck |

These give the single agent the same information V5's shop agent had, without the
multi-agent complexity.

### 3. Heuristic Shop Reward Shaping

Based on the V4 Lua shop heuristic (buy all affordable jokers, sell-upgrade weak for
strong, reroll when nothing useful):

```
R_HEUR_BUY_JOKER  = +0.3   # bought a joker into an empty slot
R_HEUR_USE_PLANET  = +0.2   # used a planet card (free hand upgrade)
R_HEUR_LEAVE_EMPTY = -0.2   # left shop with affordable jokers and empty slots
```

The agent gets a dense signal for smart shop behavior from the start, but can learn to
deviate as it discovers better strategies. This replaced V5's quality delta and spending
rewards which required shop agent exposure to function.

### 4. Seed Randomization

V4 used fixed seeds per worker: `seed_base + worker_id * 100`. With 16 workers, the agent
only ever saw ~16 unique games, leading to seed memorization (117 unique seeds across 19k
wins in one run).

V6 randomizes the seed every episode reset:
```python
env._seed = _rng.randint(0, 2**31 - 1)
```

This forces the agent to generalize across millions of unique game configurations instead
of memorizing specific seed outcomes.

### 5. Episode Truncation

Added 2000-step max episode length. A complete 8-ante game takes ~300 steps, so this is a
generous safety net. Prevents degenerate episodes where the agent loops on no-op actions
without advancing the game state.

### 6. Joker Registry Bug Fix

`chips.py` contained a no-op stub for `j_card_sharp` that overwrote `misc.py`'s working
implementation due to import order. Fixed by removing the stub. The `j_card_sharp` joker
now correctly grants x3 mult when replaying a hand type within the same round.

### 7. Quality Baseline Fix

`_prev_quality` in `env_v5.py` was initialized to 0.0 at reset but not updated when
skipping a blind (which enters the shop). This caused incorrect quality delta rewards for
the first shop visit. Fixed by setting the baseline on skip_blind → shop transition.
(V6 uses heuristic rewards instead of quality delta, but the fix is preserved in env_v5.py.)

---

## Architecture

Same as V4 — single `ActorCritic` network:

```
Input (402 dims) → Embed (512, ReLU) → 4 ResidualBlocks (512) → Actor (46) / Critic (1)

ResidualBlock: x + ReLU(FC(ReLU(FC(x)))) with LayerNorm
Total params: ~2.34M
```

Action space (46 actions, same as V4):
```
BLIND_SELECT:    30=play, 31=skip
SELECTING_HAND:  0-19=play combo i, 20-27=discard card i, 28-29=use consumable
SHOP:            32-38=buy item i, 39-43=sell joker i, 44=reroll, 45=leave
```

---

## Training Configuration

```
PPO hyperparameters (same as V4):
  LR=3e-4, GAMMA=0.99, LAMBDA=0.95, CLIP=0.2
  ENTROPY_COEFF=0.01, VF_COEFF=0.5, GRAD_CLIP=0.5
  N_EPOCHS=10, MINIBATCH_SIZE=128

Workers: 16 (multiprocessing, CPU inference)
Steps/worker: 2048 (total 32,768/iter)
Episode truncation: 2000 steps
Seed: randomized per episode
Device: CUDA (RTX 3080 Ti for PPO updates)
```

---

## Reward Structure

```
Play rewards (same as V4):
  Blind cleared:     +2.0 * (9 - ante)   [ante 1 = +16, ante 8 = +2]
  Ante completed:    +5.0
  Win (ante 8 boss): +50.0
  Loss:              -2.0
  Score progress:    +0.05 * log1p(delta) * 100

Shop rewards (new in V6):
  Buy joker:         +0.3  (into empty slot)
  Use planet:        +0.2  (hand level upgrade)
  Leave with buyable jokers + empty slots: -0.2
```

---

## Key Lessons from V5

1. **Don't split what doesn't need splitting.** The dual-agent architecture created more
   problems than it solved. Shop starvation, credit assignment, entropy management — all
   were consequences of the split, not the underlying game.

2. **Fix the fundamentals first.** The combo scoring bug caused 10 failed training runs
   before being discovered. One line of broken code masked all other improvements.

3. **Heuristic reward shaping > learned reward.** V5's quality delta reward required the
   shop agent to have data to compute. The V4 Lua heuristic encodes domain knowledge
   directly — the agent benefits from it immediately.

4. **Seed diversity is critical.** 16 fixed seeds = memorization. Random seeds per episode
   = generalization. This is especially important for shop strategy, which depends on what
   jokers appear in each game.

5. **Entropy management is architecture-dependent.** Entropy floors work for exploration
   problems but fight the gradient when the optimal policy is genuinely low-entropy (as
   with combo selection). Let the agent exploit what works.

---

## Future: Transfer to Multi-Agent

V6's trained weights provide a foundation for future multi-agent work:

**Path A — Weight Transfer:**
- Play weights (embed, res blocks) → initialize V5 play agent
- Run V6 through shop episodes → supervised pretrain V5 shop agent on those decisions
- Joint finetune both

**Path B — Reward Distillation:**
- Use V6 as a teacher — reward V5 shop agent for matching V6's action distribution
- V5 shop agent starts with V6's knowledge but can discover improvements

**Path C — Card Selection (next major feature):**
- Current: agent picks combo index 0-19 from pre-ranked list
- Future: agent selects/deselects individual cards, learns card synergies
- Enables strategic play beyond "always pick the mathematically best combo"

---

## File Changes (V6)

| File | Change |
|------|--------|
| `balatro_sim/env_sim.py` | +60 shop context obs features (402 total), heuristic shop rewards |
| `balatro_sim/env_v5.py` | Combo scoring bug fix, quality baseline fix, import OBS_DIM dynamically |
| `balatro_sim/jokers/chips.py` | Removed j_card_sharp stub (was overriding misc.py impl) |
| `train_sim.py` | Seed randomization per episode, 2000-step truncation, planet usage in shop mask |
| `tests/test_shop_v5.py` | Updated _advance_to_shop helper, comm vector test |
| `tests/` | 6 new test files: play env, consumables, boss blinds, game transitions, rewards, jokers |

Test suite: **504 tests passing** (up from 217 pre-V6).
