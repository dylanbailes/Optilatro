# V8 Training Run Log

V8 = self-play multiplayer Balatro. Two players (sharing one policy) face off
in head-to-head games on the same seed via `MultiplayerBalatroEnv`. See
[V8 Design Notes](V8_DESIGN_NOTES.md) for full architecture.

---

## Architecture Quick Reference

- **Network**: ActorCriticV7 (2.5M params, hierarchical intent + card scoring)
- **Env**: `MultiplayerBalatroEnv` with HOUSE RULE (regular blind failures cost lives)
- **4 lives** per player, **4 banned jokers** (Chicot, Matador, Mr. Bones, Luchador)
- **20 workers** × 1 MP env × 1024 steps × 2 agents = 40,960 agent-steps/iter
- **Self-play with shared policy** — stochastic sampling provides divergence
- **V7 weight migration** from Run 4 (best V7 model: 2.35% solo win rate)

---

## Run 1 — Phase 1 Baseline (V7 Migration) — **KILLED at iter 63**

**Config:** 20 workers, 1024 steps/worker, V7 Run 4 migration

**Observed problem: game termination bug + collapsing distributions**

At iter 63 (~55 min in, 2.6M steps):
- **84% of games ended at ante 2** (V7 regularly reached ante 9)
- **74% of games were draws** (both players identical strategies)
- **Avg game length: 16 MP steps** (normal Balatro is 150-300)
- Reward plateau: ~19-20 per player, flat
- Phase entropy collapsed to 0.22 (V7's was ~0.45)

**Root cause #1: Shop skip bug in revive logic**

`_revive_if_needed()` advanced failed players directly to the next BLIND_SELECT,
**skipping the shop visit entirely**. Without shop visits, failed players never
got to buy jokers. They'd fail → skip shop → fail next blind → skip shop → etc.
Both players burned 4 lives in ~4-5 blinds with 0 jokers, ending at ante 2.

**Root cause #2: Sharp policy distributions from V7 migration**

V7 had already sharpened intent/phase distributions to near-deterministic
(entropy 0.22 on phase actions). Both players sampling from same sharp
distributions produced near-identical actions → same outcomes → 74% draws.

Killed at iter 63 to fix both issues for Run 2.

---

## Run 3 — Extended Observation for Multiplayer State (planned)

**Motivation:** Identified during Run 2 that the agent's observation has NO
multiplayer state. It sees its own game (V7 encoding: ante, hand, jokers,
shop, etc.) but doesn't know:
- Its own lives remaining
- Opponent's lives remaining
- Opponent's PvP score
- Whether current blind is PvP or regular

This means life loss penalties (-1.5) and PvP outcomes feed only through
the reward signal, not through observable state. The agent can't:
- Play conservatively when at 1 life
- Play aggressively when opponent is at 1 life
- Know how much to score on PvP to win

**Planned observation additions (OBS_DIM: 434 → 438):**

| Feature | Encoding |
|---------|----------|
| self_lives | self_lives / 4.0 |
| opponent_lives | opponent_lives / 4.0 |
| opponent_pvp_score_ratio | opponent_score / own_target (capped at 2.0, 0 if not PvP) |
| is_pvp_blind | 1.0 if current blind is boss/PvP, else 0.0 |

**Consequences:**
- Cannot migrate V7 weights (obs shape differs) — fresh training required
- Training time: ~9-10 hours for 1000 iters from scratch
- First ~100 iters will be chaotic (random play), but same-seed self-play +
  high entropy should make learning faster than V7's original from-scratch run

**Decision criteria:** If Run 2 plateaus at solo-like 2% win rate, that's
strong evidence the agent needs multiplayer awareness to learn multiplayer
strategies. Run 3 will add the 4 observation features and start fresh.

---

## Run 2 — Shop Fix + Temperature Asymmetry + Look-Ahead

**Three changes from Run 1:**

1. **Shop fix**: `_revive_if_needed()` now sends failed players to SHOP (with
   fresh shop generation) instead of skipping to the next blind. Failed
   players can now buy jokers to recover.

2. **Temperature asymmetry**: P2 samples all actions (intent + subset + phase)
   with temperature `P2_TEMPERATURE = 1.4` — flatter distributions, more
   exploration. P1 samples at normal temp 1.0. Same policy weights, different
   sampling behavior → natural divergence without requiring separate networks.

3. **Look-ahead win evaluation**: When game ends with a winner, simulate the
   winner's next few blinds with greedy scripted policy:
   - If winner dies to small/big blind in next ante → `R_WIN_SHAKY = -10.0`
     applied to game-win reward (so effective win reward = +10.0)
   - If winner reaches next PvP blind intact → `R_WIN_STRONG = +5.0`
     (effective win reward = +25.0)
   - Separates "won because opponent collapsed" from "my strategy is solid"

**Also fixed in Run 2:**
- Double-resolution bug (`_is_blind_done` now tracks `_last_resolved` position
  to avoid re-counting SHOP state until player moves past it)

**Smoke test (2 workers, 128 steps, 2 iters):**
- Zero draws across 19 games (vs 74% in Run 1)
- Reached ante 4 in iter 2 (vs ante 2 ceiling in Run 1)
- Both players distinctly differentiated in rewards (P1=25.4, P2=21.1)
- 491 tests passing

**Config:** 20 workers, 1024 steps/worker, 1000 iters, V7 Run 4 migration

**Status:** KILLED at iter 71 — policy got WORSE at basic play

**What happened at iter 70:**

Evaluating V8 iter 70 checkpoint in solo V7 env showed dramatic regression:
- V7 Run 4 baseline: 2.35% win rate, ~20% ante 1 death rate
- **V8 iter 70: 0% win rate, 88% ante 1 death rate**

Key finding: **V7→V8 migration broke V7's competence.** Temperature asymmetry
+ new V8 rewards + gradient updates from bad MP games disrupted V7's sharp
distributions. The policy un-learned basic play without replacing it.

**The positive discovery:**
- **Green+Space lock-in GENUINELY broken.** Green at 3% (was 47%), Space not in
  top 15 jokers (was 51%)
- Joker distribution flat — Arrowhead, Cartomancer, Reserved Parking,
  Photograph, Faceless, etc. all 3-4% each
- Most diverse joker set ever seen

**Why we killed it:** The unstable transition phase wasn't recovering. In MP
training, 68% of games ended at ante 2, avg game length 27 MP steps, both
players burning through 4 lives in ~6-8 blind failures. No meaningful
strategic learning emerging.

**Lesson:** V7 migration is not viable for V8. The multiplayer reward signal
disrupts V7's learned distributions before it can teach alternative strategies.
Fresh start with multiplayer-aware observations is the right path.

---

## Run 3 — Extended Observation for Multiplayer State (active)

**Config:** 20 workers, 1024 steps/worker, 1000 iters, FRESH START (no migration)

**Key change: OBS_DIM 434 → 438**

Added 4 multiplayer state features to the observation:

| Index | Feature | Encoding |
|-------|---------|----------|
| [434] | self_lives | self_lives / 4.0 |
| [435] | opponent_lives | opponent_lives / 4.0 |
| [436] | opponent_pvp_score_ratio | opponent_score / own_target (capped 2.0, 0 if not PvP) |
| [437] | is_pvp_blind | 1.0 if current blind is boss, else 0.0 |

This lets the agent actually SEE the multiplayer context and make strategic
decisions based on it:
- Play conservatively when at 1 life
- Play aggressively when opponent is at 1 life
- Know exactly how much to score on PvP to win
- Distinguish PvP blinds from regular blinds

**Other changes preserved from Run 2:**
- Shop fix (revive sends to SHOP, not next blind)
- Temperature asymmetry (P2 samples at temp 1.4)
- Look-ahead win evaluation (shaky/strong adjustments)
- Double-resolution fix
- Banned jokers (Chicot, Matador, Mr. Bones, Luchador)
- HOUSE RULE (regular blind failures cost a life)

**Training starts from scratch:**
- Network: ActorCriticV7 with obs_dim=438, ~2.48M params
- No V7 migration (obs shape incompatible — 434 vs 438)
- Expected: ~100-200 iterations to match V7's basic competence, then the
  multiplayer signal drives further learning with full context visibility

**496 tests passing.**

**Status:** KILLED at iter 210 — HOUSE RULE broke the training signal

**What happened:**

At iter 210, solo evaluation showed 91% ante 1 death rate (vs V7's ~20%). The agent had failed to learn basic play. Feature importance analysis confirmed MP obs features WERE being used (7% of gradient magnitude, highest per-feature of any group), so the obs extension wasn't the issue.

**Root cause identified:** HOUSE RULE + 4 lives made the environment too forgiving. The agent learned "failing blinds is OK, I have 4 lives" and optimized for accumulating small rewards (card quality, synergy) while burning lives rapidly. Avg MP game length: 29 steps (one player dying after 4 failures). Without time pressure (unlike real MP with clock), "retry forever" dominated "clear blinds well."

Feature importance revealed:
- MP obs features had highest per-feature gradient (policy WAS using them)
- But the training signal rewarded failure + lives cycling
- Basic blind-clearing competence never developed

---

## Run 4 — No Lives, Regular Blind Failure = Game Over

**Major design change:** Remove lives system entirely. Match V7 solo training
pressure but keep self-play comparison via same-seed and PvP.

**Rules:**
- Small/big blind failure → game ends, opponent wins (survivor gets +20, dead gets -10)
- PvP blind: pure score comparison, NO death (winner +10, loser -5, both advance)
- If both die on same blind same time: tiebreak by chips_scored on failing blind
- Cap at ante 8; mutual survival through ante 8 PvP = draw with +5 bonus each
- No lives system, no HOUSE RULE, no lookahead eval

**Reward changes:**
| Event | Run 3 | **Run 4** |
|-------|:-:|:-:|
| Game win | +20 | +20 (unchanged) |
| Game loss | -10 | -10 (unchanged) |
| PvP win | +3 | **+10** (3.3x bigger) |
| PvP loss | -2 | **-5** (2.5x bigger) |
| Life lost | -1.5 | **removed** |
| Win look-ahead | ±5/-10 | **removed** |
| HOUSE RULE revive | ON | **OFF** |
| Mutual ante 8 survival | — | **+5 each (new)** |

**Why this should work:**

1. **Forces basic competence.** The agent MUST clear blinds or lose immediately. Same pressure as V7 solo (which reached ante 9 reliably).
2. **Keeps MP signal.** Same-seed means both players face identical game states. When one dies, PPO gets clean gradient on which policy was better.
3. **PvP rewards matter but don't kill.** Burst scoring ability gets reinforced (via +10 PvP win) but doesn't disrupt basic survival training.
4. **Simpler code.** No lives tracking, no revive logic except for boss blind fails (pure code cleanup).

**Smoke test results (2w × 128 steps × 2 iters):**
- Before tiebreak fix: 33/34 games were draws (both players died on same blind simultaneously)
- After tiebreak (higher chips on failed blind wins): 26 decisive, 3 draws
- Iter 1: P1=11 / P2=15 / Draws=7 → Iter 2: 13/13/3

**495 tests passing.**

**Config:** 20 workers, 1024 steps/worker, 1000 iters, fresh from scratch

**Status:** COMPLETE (1000 iterations, ~41M steps, ~13 hours)

**Final Results:**

| Iter | Reward (P1/P2) | Wins (P1/P2/Draw) | Eps |
|:-:|:-:|:-:|:-:|
| 1 | 5.9 / 5.2 | 948/885/672 | 2505 |
| 100 | 9.0 / 7.1 | 1027/903/512 | 2442 |
| 500 | 7.6 / 7.6 | 974/960/379 | 2313 |
| 1000 | 8.8 / 7.2 | 1116/968/225 | 2309 |

**Last 50 iterations average:**
- Reward: 8.64 / 7.19
- Win split: 47.5% / 42.1% / 10.3% (P1/P2/Draw)

**Outcome: Plateau.** Reward stayed flat at ~8 for 950 iterations after initial rise.
The agent learned to clear at most ante 1 small blind, then died to ante 1 big or
boss blind. Translation in reward terms: ~+8 from clearing one blind, then -10
game loss balanced against +20 game win when opponent dies first.

**Why this happened:**
- Self-play with two equally weak policies provides limited learning signal
- Each policy is calibrated against its own past performance, not against
  external "good play" reward
- Without HOUSE RULE buffer (V8 Run 3), failures hurt enough to define the game
  but neither policy ever became competent enough to teach the other

**Comparison to V7 Run 4 baseline (best result):**
- V7 Run 4: 2.35% solo win rate, reached ante 9 reliably
- V8 Run 4: ~0% solo win rate (would need eval to confirm), reached ante 1-2 only
- **Self-play training is WORSE than solo training for this problem**

**Key insight added to project takeaways:**
For sample-efficient RL on long-horizon games, self-play between two beginner
policies provides much weaker training signal than solo play against a fixed
environment with shaped rewards. AlphaZero-style self-play works at
massive compute scale because the network keeps challenging itself with new
strategies; at our scale (one machine, hundreds of iterations), there's not
enough exploration breadth to drive improvement past initial random discovery.

---

## Pivot to V7 Scaling Experiment

V8 hit its ceiling. Pivoting to V7 architecture (proven 2.35% solo win rate
baseline) for a clean scaling experiment. Hypothesis: does more network capacity
break the V7 ceiling, or is the ceiling structural (reward shaping limits)?

See [V7_RUN_LOG.md](V7_RUN_LOG.md) for V7 Run 7 (5x network + 64k batch).

---

## Metrics To Track

Standard from V7:
- Avg reward per player per iteration
- Intent distribution (Play/Discard/Consumable)
- Best ante reached
- Episode count per iteration
- Joker count in winning loadouts
- Loadout coherence

NEW for V8:
- P1 wins / P2 wins / Draws per iteration (should hover near 50/50/X for
  pure self-play)
- Avg game length (in MP steps and antes)
- Lives remaining at game end (per winner)
- PvP blind win rate (per player)
- Strategy divergence between P1 and P2 in same-seed games

---

## Decision Points

- **Iter 100**: Early signal check. If reward and win patterns look identical
  to V7, we may need explicit policy diversification.
- **Iter 500**: Mid-run evaluation. Compare joker diversity and coherence
  against V7 baselines.
- **Iter 1000**: Full evaluation. Decide on Phase 2 (specialist population,
  new multiplayer jokers, Hall of Fame).

---

## Comparison Baseline

For reference, V7 final results (last 50 iters):

| Run | Win Rate | Avg Jokers | Coherence |
|:-:|:-:|:-:|:-:|
| V7 Run 4 | 2.35% | 4.0 | 0.65 |
| V7 Run 5 | 2.20% | 4.90 | 0.63 |
| V7 Run 6 | 2.23% | 3.33 | 0.58 |

V8 success = significantly exceeding these on a comparable solo win rate
metric (we'll need to evaluate V8's policy on single-player V7 env to
compare apples-to-apples).
