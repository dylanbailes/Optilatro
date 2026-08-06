# V8 Design Notes — Self-Play Multiplayer Balatro

*Written 2026-04-13. Builds on V7 (2.35% solo win rate ceiling). The hypothesis:
self-play with same-seed comparison breaks the Green+Space lock-in by giving
PPO direct gradient signal between competing strategies.*

---

## Motivation

V7 plateaued at ~2% win rate after 6 reward-shaping runs. The diagnosis from
the V7 run log:

> The agent has only ONE decision branch — "if I see Green/Space, buy them."
> It lacks backup branches for "commit to Flush build when flush jokers appear"
> or "reroll when shop has no strategy-coherent options."

The fundamental issue is exploration. PPO can't discover multi-step coordinated
strategies from averaged reward signal alone. Same-seed self-play addresses
this directly: when two policies face identical game states and one wins, PPO
gets a clean differential signal showing exactly which strategy was better.

---

## Architecture

### Multiplayer Sim (Standard Ranked + House Rule)

Two `BalatroGame` instances coordinated by `MultiplayerBalatro`:

- **Same seed**: identical starting decks and card draws per blind
- **Independent shops**: post-init RNG drift creates different shop offerings
- **4 lives per player** (configurable)
- **HOUSE RULE: failing regular blind costs a life** (vs official mod which
  only loses lives on PvP) — makes the game more decisive, prevents draws
- **PvP boss blind**: higher score wins, loser loses a life
- **Comeback money**: $4 per life lost this round, awarded to PvP loser
- **Game ends at 0 lives**, winner determined by survivor (ante-tiebroken)

### Banned Jokers (Standard Ranked compliance)

4 jokers excluded from shop generation in MP mode:
- **Chicot** (disables boss blind effect — irrelevant in PvP)
- **Matador** ($8 when boss triggers — irrelevant)
- **Mr. Bones** (prevents loss at 25% — broken in lives system)
- **Luchador** (sell to disable boss — irrelevant)

Implemented via `set_banned_jokers()` in `balatro_sim/shop.py`. Active
automatically when `env_mp` is imported.

### Network (unchanged from V7)

```
Input (434) → Embed(512, ReLU) → 4x ResBlock(512) → trunk (512)

SELECTING_HAND:
  trunk → intent_head(3)                    → intent logits
  trunk + intent_embed(32) → card_head(8)   → card scores (sigmoid)
  card_scores → 218 subsets → softmax → Categorical → sample subset

Other phases:
  trunk → phase_head(17)                    → blind/shop actions

Shared:
  trunk → critic(1)                         → value

~2.5M params
```

### Training Setup

- **20 workers** (hyperthreading sweet spot from benchmarking: ~2-5% over 16)
- **1024 steps per worker** × 2 agents = 2048 agent-records per worker per iter
- **Total batch**: 40,960 agent-steps per iter (vs V7's 32,768)
- **Same shared policy** for both players — stochastic sampling provides
  divergence; no need for separate networks in Phase 1
- **V7 weight migration** from Run 4 (best V7 model: 2.35% win rate)

### Reward Structure

**Layer 1: V7 base rewards** (per player, every step):

| Event | Value |
|-------|:-:|
| Card quality | +2.0 × (played/best) |
| Score progress | +0.02 × log1p(delta) × 100 |
| Blind clear | +1.0 × (9-ante) |
| Ante complete | +2.5 |
| Synergy buy (slot 1-5) | +1.5 to +3.0 × synergy |
| Anti-synergy | -1.0 × (0.5 - synergy) when sub-coherent |
| Empty slot penalty | -0.3 × (ante-1) × empty slots |
| Per-blind coherence | +1.5 × coherence |
| Episode-end coherence | +6.0 × coherence × ante |
| Sell rewards (sacrificial/weak/late-scaling) | +0.3 to +2.0 |
| Sell blunders | -0.5 to -2.0 |

**Layer 2: V8 multiplayer rewards** (NEW, on top of V7):

| Event | Value |
|-------|:-:|
| **PvP win** | +3.0 |
| **PvP loss** | -2.0 |
| **Life lost** (any cause) | -1.5 |
| **Game win** (opponent at 0 lives) | +20.0 |
| **Game loss** (you at 0 lives) | -10.0 |

### Key Design Decisions

**Why one shared policy instead of two distinct policies?**

For Phase 1, simplicity. Stochastic action sampling provides natural
divergence — both players sample different intents and subsets from the same
distribution. This gives meaningful self-play data without doubling GPU
memory or training infrastructure.

If Phase 1 shows promise, Phase 2 will introduce a population of 5 specialist
policies (Generalist, Flush, Pairs, Face Cards, Economy) with differentiated
reward shaping per the V7_RUN_LOG.md V8 design plan.

**Why house rule (regular blinds cost lives)?**

The official mod only loses lives on PvP, meaning bad players who fail every
small/big blind still get to compete at PvP. This produces lots of low-skill
games and slow learning. Our house rule punishes survival failures, making
training signal cleaner and games more decisive.

**Why migrate from V7 instead of starting fresh?**

V7 already learned the basics: card play, discards, basic shop strategy.
Starting fresh would burn ~500 iterations relearning V7's ceiling before
adapting to multiplayer. Migration lets V8 begin adapting immediately.

The risk: V7's Green+Space lock-in might transfer. But the new multiplayer
reward signal (PvP burst pressure) should pull the policy in different
directions if better strategies exist for PvP.

---

## What's NOT in V8 Phase 1

Deliberate omissions to keep scope focused:

1. **10 multiplayer-specific jokers** (Defensive, Skip-Off, Pacifist, etc.)
   — require Nemesis-state access, significant sim refactor
2. **Joker balance nerfs** (Hanging Chad, Seltzer, Turtle Bean, Golden Ticket)
   — using base game values for now
3. **Ouija rework, Asteroid planet, Justice tarot, Glass card restrictions**
   — minor balance changes, not critical
4. **Multiple specialist policies** (planned for Phase 2)
5. **Hall of Fame opponents** (planned for Phase 2)
6. **Move joker action** (Blueprint/Brainstorm still positional, auto-placed
   from V7)

---

## Success Criteria

### Phase 1 (this run)

- **Primary**: Single-agent equivalent win rate breaks 3% (vs V7's 2.35%)
- **Secondary**: Loadout coherence climbs above 0.70
- **Tertiary**: Joker diversity in winning loadouts (Green+Space drop below 40% combined)

### Failure modes to watch

- Both policies converge to identical strategies → no meaningful self-play data
- Lives system creates degenerate "always die at ante 1" loop
- PvP rewards dominate to the point of ignoring solo play quality
- Reward explosion from stacked V7 + V8 rewards

### Decision points

- Iter 100: should see win rate or coherence trending different from V7
- Iter 500: clear evidence of strategy diversification or plateau
- Iter 1000: full evaluation, decide on Phase 2 implementation

---

## Implementation Files

- `balatro_sim/mp_game.py` — `MultiplayerBalatro` coordinator (mechanics)
- `balatro_sim/env_mp.py` — `MultiplayerBalatroEnv` (RL interface, banned jokers)
- `balatro_sim/shop.py` — `BANNED_JOKERS` set with `set_banned_jokers()` API
- `train_v8.py` — Self-play PPO training loop
- `tests/test_mp_game.py` — 34 tests for coordinator mechanics
- `tests/test_env_mp.py` — 19 tests for env (5 banned-joker tests)
- `tests/test_mp_integration.py` — 7 integration tests with scripted policies

---

## Reference

- [V7 Run Log](V7_RUN_LOG.md) — full V7 history with V8 design plan
- [Multiplayer Ruleset](MULTIPLAYER_RULESET.md) — Standard Ranked spec from
  balatromp.com
