# Balatro RL

A reinforcement learning agent that learns to play [Balatro](https://www.playbalatro.com/) using PPO.

**Status: Concluded** (April 2026). Eight architecture versions over five months. Peak result: **2.35% win rate** (V7 Run 4) — a ~235x improvement over random play but well short of human-level (~70%). A final scaling experiment (V7 Run 7, 5.5x network) confirmed the plateau is a **search** limitation, not a capacity one. See [PROJECT_RETROSPECTIVE.md](results/PROJECT_RETROSPECTIVE.md) for the post-mortem and [MCTS notes for future work](results/PROJECT_RETROSPECTIVE.md#future-direction--mcts--neural-network).

> **Disclaimer:** Balatro is a product of LocalThunk/Playstack. This is an unofficial project for research and educational purposes only.

---

## Watch the agent clear ante 9

A full 91-step trajectory from a winning V7 Run 4 game (seed `1768285469`), rendered
from the logged policy decisions. Shows the agent's aggressive early-skip strategy
(collect tags on Small + Big blinds, engage only Bosses through ante 5), the switch
to full engagement from ante 6 on, and the probability bars revealing how confident
the policy was at each decision point.

[![V7 Run 4 agent clears ante 9](https://img.youtube.com/vi/sw_9Ue72eVk/maxresdefault.jpg)](https://youtu.be/sw_9Ue72eVk)

*Click to watch on YouTube. A local copy of the MP4 is also in [`docs/media/v7_run4_replay.mp4`](docs/media/v7_run4_replay.mp4).*

The visualizer that generated this is in [`viz/`](viz/) — any episode from
`scripts/eval_with_trajectory.py` can be dropped in as `viz/trajectory.json` and
replayed. Scoring panel math (base chips × mult + joker contributions) is computed
client-side from the logged game state.

---

## Version progression at a glance

![Peak win rate across 8 architecture iterations](results/v1_v8_progression.png)

The full arc in one chart — sub-random live-game baselines (V1-V3), the invalidated
V4 result (hatched: fixed seeds + broken Burglar joker inflated the number),
V6 as the first legitimate measurement (1.9%), the V7 hierarchical architecture
peak (Run 4 at 2.35%), the reward-shape plateau (Runs 5-6), the failed 5.5× scaling
test (Run 7), and the self-play dead end (V8).

---

## What is Balatro?

Balatro is a roguelike poker deckbuilder. You play poker hands to score chips against escalating point thresholds ("blinds"), buying joker modifiers between rounds to multiply your scoring. Clear 8 antes (24 blinds) to win.

<p align="center">
  <img src="docs/media/balatro_the_hook.png" width="49%" alt="Agent at 598/600 vs The Hook boss blind" />
  <img src="docs/media/balatro_shop.png" width="49%" alt="Shop phase with jokers, booster packs, and a voucher" />
</p>

*Left: a nail-biter — the agent sits at 598/600 against* The Hook *(discards 2 random cards per hand).
Right: a shop phase — 2 jokers, 2 booster packs, a voucher, and a reroll, all priced against limited cash.*

**Why it's a hard RL problem:**

| Challenge | Description |
|-----------|-------------|
| Combinatorial action space | 8 cards in hand -> 218 possible play/discard subsets per turn |
| Long-horizon credit assignment | A joker bought in ante 1 might only pay off in ante 6 |
| Partial observability | Deck order, future shop contents, upcoming blinds all unknown |
| Sparse rewards | Only hands that clear blinds produce meaningful reward |
| Stochastic elements | Card draws, joker spawns, boss blind effects randomized each game |
| Compounding strategy | Hand upgrades, deck thinning, joker combos interact multiplicatively |

A skilled human wins ~70% of runs. Random play wins <0.01%.

---

## Version History

| Version | Method | Peak Win Rate | Key Learning |
|---------|--------|:---:|-------------|
| V1 | File IPC, SB3 | <0.01% | Proof of concept |
| V2 | File IPC, Ray | <0.01% | Parallelism works but IPC is the bottleneck |
| V3 | Socket IPC, custom PPO | <0.01% | RAM degradation kills live-game training |
| V4 | Python sim, single agent | inflated* | Sim works, combo ranking helps enormously |
| V5 | Python sim, dual agent | 0% | Shop starvation is structural — failed after 12 runs |
| V6 | Python sim + full audit | 1.9% | Sim fidelity matters, combo ranker is the ceiling |
| **V7** | **Hierarchical intent + learned card selection (Runs 1-6)** | **2.35%** (peak) | Agent can learn card play from reward; plateaus at Green+Space lock-in |
| V8 | Self-play multiplayer + MP-aware obs | 0% | Self-play between two weak policies gave weaker signal than solo training |
| V7 Run 7 | 5.5x network (13.6M params) + 64k batch | 0.16% @ 184 iters | Scaling did not break the ceiling. Killed early — same plateau shape as baseline. |

*V4 produced 35k+ wins but on fixed seeds + broken Burglar joker. V6 Run 6 (1.9%) is the first legitimate measurement with random seeds + audited sim.

### Throughput Progression

| Version | Method | Single-env sps | Training sps (16-20 workers) | vs V1 |
|---------|--------|:---:|:---:|:---:|
| V1 | File IPC, SB3, 1 env | ~0.08 | — | 1x |
| V2 | File IPC, Ray, 8 envs | ~6 | — | 75x |
| V3 | Socket IPC, 8 envs | ~14** | — | 175x |
| V4-V6 | Python sim, 16 workers | ~1,000 | ~900-1000 | ~12,500x |
| V7 | +`_best_hand_score` vectorization | **~1,535** | ~985 | ~19,000x |
| V8 | MP env + extended obs (20 workers) | ~1,400 | ~780 | — |

**V3 degraded from ~39 sps to ~14 sps over training due to Lua GC / RAM issues.

**Throughput notes:**
- V8 is slower per step (MP coordination + PvP resolution), but each step produces trajectories for two agents on the same seed — effective data throughput comparable to V7.
- Sim-side speedups carried into V7/V8: `_best_hand_score` vectorization (218 subsets → top candidates via priority filtering), batched inference within workers, hyperthreading (16 → 20 workers on Ryzen 9 7950X), banned-joker shop filter.

---

## Best Result: V7 — Hierarchical Intent + Learned Card Selection

V7 is the best-performing version. Peak: **2.35% win rate** (Run 4). Six runs of reward shaping across ~80 hours of training all landed within 2.0-2.35%.

### Network Architecture (V7)

```
Input (434) → Embed(512, ReLU) → 4× ResidualBlock(512) → trunk (512)

SELECTING_HAND (hierarchical):
    trunk → intent_head(3)                              → PLAY/DISCARD/USE_CONSUMABLE
    trunk + intent_embed(32) → card_head(8, sigmoid)    → card scores
    card_scores → 218 subsets → softmax → Categorical  → sample subset

Other phases:
    trunk → phase_head(17)                              → blind/shop actions

Shared:
    trunk → critic(1)                                   → value

~2.48M params
```

### Observation Space (434 features)

| Range | Dims | Description |
|-------|:----:|-------------|
| `[0:14]` | 14 | Game scalars (ante, blind, progress, target, hands/discards left, dollars, phase) |
| `[14:254]` | 240 | Hand cards: 8 slots × 30 features (rank, suit, enhancement, edition, seal, debuff, present, suit_match, rank_match, straight_conn, chip_value) |
| `[254:304]` | 50 | Joker slots: 5 × 10 features |
| `[304:346]` | 42 | Shop items: 7 × 6 features |
| `[346:358]` | 12 | Planet levels |
| `[358:374]` | 16 | Consumable slots: 2 × 8 features |
| `[374:434]` | 60 | Shop context (reroll, vouchers, boss, deck composition, enhancements) |

### Action Space

**SELECTING_HAND phase (hierarchical):**
- Intent head: Discrete(3) → PLAY / DISCARD / USE_CONSUMABLE
- Card scoring head: 8-dim continuous (sigmoid) → defines distribution over 218 subsets
- Sample intent from Categorical, sample subset from softmax(card_scores), factored log_prob = log_prob(intent) + log_prob(subset|intent)

**BLIND_SELECT + SHOP phases:** Discrete(17)
```
0-1     play_blind / skip_blind
2-8     buy shop item 0-6
9-13    sell joker 0-4
14      reroll
15      leave_shop
16      use planet in shop
```

### Reward Structure (V7 — solo, shaped)

| Signal | Value |
|--------|:-:|
| Blind cleared | +1.0 × (9-ante) |
| Ante complete | +2.5 |
| Score progress | +0.02 × log1p(delta) × 100 |
| Card quality | +2.0 × (played_score / best_possible_score) |
| Synergy buy (slot 1-5) | +1.5 to +3.0 × synergy (coherence-aware) |
| Anti-synergy buy | -1.0 × (0.5 - synergy) when synergy < 0.5 |
| Empty slot penalty | -0.3 × (ante-1) × empty_slots |
| Per-blind coherence | +1.5 × coherence |
| Episode-end coherence | +6.0 × coherence × ante |
| Smart sell rewards | +0.3 to +2.0 (sacrificial, weak, late-scaling swap) |
| Use planet | +0.2 |

### Training Configuration (V7 Run 4 — best result)

```
PPO: LR=3e-4, gamma=0.99, lambda=0.95, clip=0.2
     intent entropy=0.05, subset entropy=0.005, phase entropy=0.01
     VF coeff=0.5, grad_clip=0.5, epochs=10, minibatch=128

Workers: 16, steps-per-worker 2048, 1000 iters (~32.8M steps)
Device: CUDA (RTX 3080 Ti for PPO updates)
```

### V7 Run Summary

| Run | Last 50 WR | Key Finding |
|:-:|:-:|---|
| Run 1 | — | Card selection without reward signal = random |
| Run 2 | 1.98% | Card quality reward brought wins back |
| Run 3 | 1.80% | Synergy reward too weak, plateaued |
| **Run 4** | **2.35%** | Slot-scaled rewards + ante penalty (**best result**) |
| Run 5 | 2.20% | Slot filling succeeded, win rate plateaued |
| Run 6 | 2.23% | Coherence amplification backfired |
| Run 7 | 0.16% @ 184 | 5.5x network (13.6M params) — same plateau shape, killed early |

See [V7_RUN_LOG.md](results/V7_RUN_LOG.md) for detailed per-run journal.

### What the V7 Agent Learned (and Didn't)

**Learned:** Strategic card play, discard timing (~30% of SELECTING_HAND actions), slot filling (96% full loadouts), coherent joker purchases.

**Didn't learn:** Conditional strategy (Flush-build vs Pair-build vs Straight-build), multi-step joker planning, deviation from the Green+Space strategy lock-in.

**Why it plateaued:** Green+Space are legitimately S-tier jokers. The agent's only decision branch was "buy them if seen." PPO's averaged rewards across episodes never pushed it to explore multi-step coordinated alternatives, and six reward-shaping experiments + a 5.5x network scale-up couldn't dislodge the basin.

---

## V8 — Self-Play Multiplayer Extension (failed)

V8 was an experiment to break V7's Green+Space plateau using same-seed self-play on the [multiplayer Balatro ruleset](results/MULTIPLAYER_RULESET.md). Hypothesis: when two policies face identical game states and one wins, PPO gets a direct differential gradient — cleaner signal than averaged rewards, and the PvP burst-scoring blind would reward alternative strategies.

**Outcome: plateaued worse than V7 solo.** Self-play between two weak policies produced a weaker training signal than solo play against a shaped reward. Run 4 (the only full run) reward plateaued at ~8 after 1000 iters; solo evaluation showed ~0% win rate.

### V8 Changes vs V7

- **Obs extended 434 → 438:** added `self_lives/4`, `opponent_lives/4`, `opponent_pvp_score_ratio`, `is_pvp_blind`
- **Env:** `MultiplayerBalatroEnv` wrapping two V7 envs on the same seed; independent shops
- **Banned jokers:** Chicot, Matador, Mr. Bones, Luchador (boss-blind-dependent, break the PvP format)
- **Training:** 20 workers × 1024 MP steps × 2 agents = 40,960 agent-steps/iter
- **Sampling:** temperature asymmetry (P2 at temp 1.4) to prevent symmetric-draw collapse

### V8 Reward Structure (Run 4 final)

| Event | Value |
|-------|:-:|
| PvP blind win | +10.0 |
| PvP blind loss | -5.0 |
| Game win (opponent dies to regular blind first) | +20.0 |
| Game loss (you die to regular blind first) | -10.0 |
| Mutual ante 8 PvP survival (draw) | +5.0 each |

Run 4 removed the HOUSE RULE, lives system, life-loss penalties, and look-ahead win evaluation from earlier runs — regular blind failure immediately ends the game. See [V8_RUN_LOG.md](results/V8_RUN_LOG.md) for the full design progression.

### V8 Run History

| Run | Status | Key Finding |
|:-:|---|---|
| Run 1 | Killed iter 63 | Shop-skip bug: failed players never bought jokers. 84% games ended at ante 2. |
| Run 2 | Killed iter 71 | V7 migration disrupted basic play (solo win rate 2.35% → 0%). Broke Green+Space lock-in but lost competence. |
| Run 3 | Killed iter 210 | HOUSE RULE + 4 lives made environment too forgiving; agent optimized for life-burning. |
| Run 4 | Complete (1000 iters) | No lives; regular blind failure = game over. Reward plateau at ~8, ~0% solo win rate. |

### V8 Key Files

- [`balatro_sim/mp_game.py`](balatro_sim/mp_game.py) — `MultiplayerBalatro` coordinator (PvP resolution, game-over detection, tiebreaks)
- [`balatro_sim/env_mp.py`](balatro_sim/env_mp.py) — RL environment, banned jokers, extended obs
- [`train_v8.py`](train_v8.py) — Self-play PPO training loop with temperature asymmetry
- [`results/V8_DESIGN_NOTES.md`](results/V8_DESIGN_NOTES.md) — architecture spec
- [`results/MULTIPLAYER_RULESET.md`](results/MULTIPLAYER_RULESET.md) — Standard Ranked spec

---

## Why the Project Concluded Here

Four consecutive experiments failed to move past V7 Run 4's 2.35% ceiling:

1. **V7 Runs 5-6** (reward retuning): 2.07-2.23% — same Green+Space lock-in
2. **V8 Runs 1-4** (self-play, 4 variants): all effectively 0% — self-play between weak policies provides weaker signal than solo play against a shaped reward
3. **V7 Run 7** (5.5x network, 13.6M params): same early-peak/plateau shape as baseline — capacity is not the bottleneck

The consistent pattern is strong evidence that **shaped-reward PPO cannot discover the multi-step coordinated strategies Balatro requires**, regardless of architecture tweaks, reward restructurings, or network size. The next meaningful axis is **search** (MCTS + neural network prior), not more of the same. See [PROJECT_RETROSPECTIVE.md](results/PROJECT_RETROSPECTIVE.md) for the full analysis.

Directions not tried that might help at lower compute cost:

1. **MCTS + learned policy/value prior** (AlphaZero-style) — explicit lookahead over shop purchase sequences
2. **Curriculum learning** — disable Green+Space for first 500k steps to force discovery of alternatives
3. **Supervised imitation** from a scripted strategic player, followed by PPO fine-tuning
4. **Population-based training** with reward diversity + Hall of Fame ([planned in V7_RUN_LOG.md](results/V7_RUN_LOG.md))

---

## Previous Versions — Brief

Each version below has detailed design notes + run logs in [`results/`](results/).

### V1–V4 — Live Game to Python Sim

- **V1-V3:** Trained against live Balatro via Lua mod (file IPC → socket IPC). RAM degradation at 8 parallel instances killed long runs. Peak ~14 sps.
- **V4:** Pivoted to pure Python simulation. ~1000 sps (50,000x vs V1). All subsequent versions build on this sim.
- **V4 win rates were inflated** by fixed seeds (memorization) and a broken Burglar joker implementation, discovered later in V6.

### V5 — Dual-Agent Failure ([design](results/V5_DESIGN_NOTES.md) · [runs](results/V5_RUN_LOG.md))

- **Architecture:** Split play + shop into separate networks with 32-dim communication vector
- **Result:** 0% win rate, 12 failed runs
- **Why it failed:** Shop starvation — the shop agent received <0.1% of training steps. Every fix for shop exposure degraded play. Dual-agent is the wrong abstraction when play/shop ratio is 20:1.

### V6 — Audited Python Sim + Single Agent ([design](results/V6_DESIGN_NOTES.md) · [runs](results/V6_RUN_LOG.md))

- **Architecture:** Single-agent PPO, 402-dim obs, Discrete(46) action (20 pre-ranked combos, 8 discards, shop/blind actions)
- **Key achievement:** 1.9% win rate (first legitimate measurement on random seeds with audited sim)
- **Major changes:**
  - **Full sim audit:** Fixed 32 jokers (~30% of implementations were wrong). Most critical: Burglar was a scaling mult joker instead of a hand modifier, producing fake 612M chip Pairs.
  - **Random seeds per episode:** V4 had fixed seeds → 35k wins on 16k unique seeds (memorization). V6 randomized for true generalization.
  - **Heuristic shop rewards:** +0.3 buy joker, +0.2 use planet, -0.2 leave with buyable jokers, -0.5 sell blunder
  - **Boss blind loop fixes:** bl_mouth/bl_eye no longer infinite-loop on blocked combos
- **The ceiling:** 80% of games died at ante 1 because the agent couldn't discard strategically. The pre-ranked combo action space meant it always picked action 0 (best combo) and never learned alternatives.

V7 (the best result) is described in its own section above. V7's key reward shaping changes from V6: action space redesign (learned card selection via intent + subset sampling), card quality reward (+2.0 × played_score / best_possible_score), synergy/coherence rewards across 164 tagged jokers, auto-positioning for Blueprint/Brainstorm, and context-aware smart-sell rewards.

---

## Major Takeaways (TL;DR)

One-line per lesson. Full version in [PROJECT_RETROSPECTIVE.md](results/PROJECT_RETROSPECTIVE.md).

- **Sim fidelity first.** 30% of V6's jokers had bugs — any RL result before audit is untrusted.
- **Seed diversity prevents memorization.** Fixed seeds in V4 gave huge fake win rates; random seeds in V6 got real 1.9%.
- **Pre-ranking actions is a speed-vs-ceiling tradeoff.** V4 reached ante 9 in 2 iters; V6 plateaued because the agent never picked action ≠ 0.
- **Hierarchical actions work** when factored log_prob is set up correctly (V7 intent + subset).
- **Don't split what doesn't need splitting.** V5's dual-agent starved the shop head for 12 runs.
- **PPO has sticky local optima.** V7's Green+Space lock-in survived 6 reward retunes + a 5.5x network scale-up.
- **Reward shaping has a capacity-insensitive ceiling.** Scaling the net did not help. The bottleneck is exploration/search, not function approximation.
- **Self-play between two weak policies teaches less than solo play against shaped rewards** at our compute scale.
- **Observation must contain actionable context.** V8 penalized life loss but the agent couldn't see lives until Run 3 added MP state to obs.

---

## Simulation

The Python sim (`balatro_sim/`) reimplements Balatro's full ruleset:

| Module | Contents |
|--------|----------|
| `game.py` (661 lines) | Full game loop — 5 states, 15 boss blind effects, ante progression, win/loss |
| `mp_game.py` (V8) | Multiplayer coordinator: PvP resolution, game-over detection, tiebreaks |
| `scoring.py` (142 lines) | Chip/mult computation, enhancements, editions, seals, retriggers |
| `hand_eval.py` (172 lines) | All 12 hand types including Flush Five / Flush House |
| `jokers/` (6 modules) | **164 jokers**, fully audited |
| `consumables.py` (549 lines) | 12 planets, 22 tarots, 18 spectrals, 27 vouchers |
| `shop.py` | Weighted rarity rolls, buy/sell/reroll, banned joker filter (V8), 150+ item catalogue |
| `card.py` | Card representation with enhancement/edition/seal |
| `card_selection.py` (V7) | Subset enumeration, intent-to-action translation |
| `synergy.py` (V7) | Joker synergy tags, coherence scoring, auto-positioning |

Test suite: **496 tests passing** across joker behavior, scoring, boss blinds, game transitions, consumables, environment integration, multiplayer mechanics, and banned-joker filtering.

---

## Repository Layout

```
balatro-rl/
├── train_v7.py               # V7 training — hierarchical intent + learned card selection (best result)
├── train_v8.py               # V8 training — self-play multiplayer PPO (failed experiment)
├── train_sim.py              # V6 training — single-agent PPO with pre-ranked combos
├── train_v5.py               # V5 training — dual-agent PPO (deprecated)
├── balatro_sim/              # Python Balatro simulation
│   ├── env_mp.py             # V8 multiplayer environment (438 obs, self-play)
│   ├── mp_game.py            # V8 multiplayer coordinator
│   ├── env_v7.py             # V7 environment (434 obs, hierarchical actions)
│   ├── env_sim.py            # V6 environment (402 obs, 46 actions)
│   ├── env_v5.py             # V5 dual-agent env (deprecated)
│   ├── card_selection.py     # V7 subset enumeration
│   ├── synergy.py            # V7 joker synergy + auto-positioning
│   ├── game.py               # Core game loop
│   ├── shop.py, scoring.py, hand_eval.py, consumables.py, card.py, constants.py
│   └── jokers/               # 164 jokers across 6 modules
├── tests/                    # Integration tests (496 passing)
│   ├── test_env_mp.py        # V8 MP environment tests
│   ├── test_mp_game.py       # V8 MP coordinator tests
│   ├── test_mp_integration.py # V8 full-game integration
│   ├── test_env_v7.py        # V7 environment tests
│   ├── test_card_selection.py
│   └── test_*.py             # Joker + game flow tests
├── scripts/                  # Plotting and analysis dashboards
├── results/                  # Design notes + run logs (detailed per-version)
│   ├── PROJECT_RETROSPECTIVE.md  # Cross-version post-mortem and future directions
│   ├── V7_PLANNING.md        # V7 design (5 approaches analyzed)
│   ├── V7_RUN_LOG.md         # V7 run journal (7 runs; Run 4 = 2.35% peak, Run 7 = scaling test)
│   ├── V8_DESIGN_NOTES.md    # V8 architecture spec
│   ├── V8_RUN_LOG.md         # V8 run journal (4 runs, plateaued)
│   ├── MULTIPLAYER_RULESET.md # Standard Ranked spec from balatromp.com
│   ├── V6_DESIGN_NOTES.md, V6_RUN_LOG.md
│   ├── V5_DESIGN_NOTES.md, V5_RUN_LOG.md
│   └── V4_DESIGN_NOTES.md, V3_DESIGN_NOTES.md, V1/V2 results
├── checkpoints_v7/, checkpoints_v7_run7/, checkpoints_v8/, checkpoints_sim/, ... # Model weights per version/run
├── logs_v7/, logs_v7_run7/, logs_v8/, logs_sim/    # Training logs per version/run
├── legacy/                   # V1-V3 training scripts
├── mod/, mod_v2/             # Lua mod files (V1-V3)
└── launch/                   # PowerShell scripts (V3 instance management)
```

---

## Setup

```bash
git clone https://github.com/taggarttufte/balatro-rl
cd balatro-rl
python -m venv env && source env/bin/activate  # or env\Scripts\activate on Windows
pip install torch numpy gymnasium
```

```bash
# Run tests (496 passing)
python -m pytest balatro_sim/jokers/tests/ tests/ -v

# Train V7 (best result — reproduces the 2.35% Run 4 config)
python train_v7.py --workers 16 --steps-per-worker 2048 --iterations 1000

# Train V7 Run 7 config (5.5x network, to reproduce the scaling-ceiling finding)
python train_v7.py --workers 20 --steps-per-worker 3200 --iterations 1000 \
    --hidden 1024 --res-blocks 8 --lr 1.5e-4

# Train V8 (self-play multiplayer — reproduces the failed experiment)
python train_v8.py --workers 20 --steps-per-worker 1024 --iterations 1000

# Smoke test
python train_v7.py --workers 4 --steps-per-worker 256 --iterations 10

# Benchmark sim throughput
python -m balatro_sim.env_sim
```

---

## Acknowledgments

Built on [Steamodded](https://github.com/Steamopollys/Steamodded) for Lua mod loading and [Handy](https://github.com/nicholassam6425/balatro-mods) for speed control (V1-V3). The V8 multiplayer ruleset is based on [balatromp.com](https://balatromp.com/)'s Standard Ranked specification.
