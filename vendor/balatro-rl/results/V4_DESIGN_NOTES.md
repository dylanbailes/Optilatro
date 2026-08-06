# V4 Design Notes — Python Balatro Simulator

*Revised 2026-03-28. Previous V4 (dual shop agent) shelved; sim is the right foundation first.*

## Overview

V4 replaces LÖVE2D/Balatro as the training environment with a **faithful Python simulation**
of the full Balatro ruleset. The existing socket IPC (v3 mod) becomes the deployment layer:
train on the sim, eval/play on real Balatro.

### Why

| Pain point (v3)              | Fix (v4)                            |
|------------------------------|-------------------------------------|
| ~100 sps ceiling (8 procs)   | 10,000+ sps (pure Python, no I/O)   |
| Instance freezes, RAM bloat  | No game engine, no OS overhead      |
| Nav sync bugs                | Deterministic state machine         |
| Can't inspect internal state | Perfect state access for obs/debug  |
| Hard to reproduce failures   | Seeded, reproducible runs           |

---

## Architecture

```
Training:
  balatro_sim/ (Python game engine)
       |
  env_sim.py (gym wrapper, same obs/action space as v3)
       |
  train_v4.py (vectorized PPO, 256+ envs, no sockets)

Deployment:
  Trained policy
       |
  env_socket.py (existing v3 socket env)
       |
  BalatroRL_v3.lua (real Balatro via socket IPC)
```

The obs/action space is kept **identical to v3** (206 features, 20 actions) so the trained
policy transfers to real Balatro without modification.

---

## Sim Directory Structure

```
balatro_sim/
  __init__.py
  card.py          # Card representation (rank, suit, enhancement, edition, seal)
  deck.py          # Deck/hand management, draw logic
  hand_eval.py     # 12 hand types + Balatro-specific (Flush Five, Flush House, etc.)
  scoring.py       # Chips x mult engine, retrigger logic, seal effects
  jokers.py        # Joker registry + effect dispatch
  blinds.py        # Small/big/boss blind definitions, all boss effects
  shop.py          # Shop state, economy, buy/sell/reroll, vouchers
  consumables.py   # Tarot cards, Planet cards, Spectral cards
  game.py          # Top-level state machine (the full game loop)
  rng.py           # Seeded RNG wrapper (mirrors Balatro's pseudorandom functions)
  constants.py     # Hand base values, ante scaling, interest table, etc.

  jokers/          # Individual joker implementations (grouped by type)
    __init__.py
    base.py        # Joker base class + registry decorator
    mult.py        # Pure mult jokers (Joker, Greedy Joker, etc.)
    chips.py       # Pure chip jokers
    scaling.py     # Scaling jokers (Ride the Bus, Runner, etc.)
    hand_type.py   # Hand-type-gated jokers (Sly Joker, Half Joker, etc.)
    economy.py     # Money jokers (Golden Joker, To the Moon, etc.)
    retrigger.py   # Retrigger jokers (Hack, Dusk, etc.)
    special.py     # Complex jokers (Blueprint, Brainstorm, DNA, etc.)

  tests/
    test_hand_eval.py     # Known hands → expected type
    test_scoring.py       # Known hand+jokers → expected score
    test_blinds.py        # Boss blind effects
    test_shop.py          # Economy, buy/sell, interest
    test_game_flow.py     # Full run smoke tests
    test_crossval.py      # Cross-validate sim vs real Balatro via socket
```

---

## Game State Machine

```
NEW_ROUND
  -> BLIND_SELECT (choose small/big/boss, or skip)
  -> SELECTING_HAND (draw 8 cards, play/discard up to score)
  -> HAND_PLAYED (score hand, check vs target)
     -> DRAW_TO_HAND (refill to 8)
     -> back to SELECTING_HAND
  -> ROUND_EVAL (won blind: collect $, ante up if boss)
  -> SHOP (buy jokers/consumables/vouchers, reroll, sell)
  -> GAME_OVER (failed to beat blind) or loop back to NEW_ROUND

Win condition: beat ante 8 boss blind.
Loss condition: run out of hands with chips < blind target.
```

---

## Implementation Priority

### Phase 1 — Core engine (no jokers)
- Card representation (rank 2-A, 4 suits, debuff flag)
- Hand evaluation (all 12 types, Balatro-specific variants)
- Scoring: base chips/mult, card chip values, mult math
- Blind progression: ante scaling table, chips targets
- Basic hand management: draw, play, discard, refill
- Simple shop: buy slots (no effects yet), sell for $, leave
- Full game loop from start to game over

*Validation: run 1000 games with random agent, check score distributions are sane*

### Phase 2 — Common jokers (~30)
The 20-30 jokers that appear most often and matter most for early learning:
- Joker, Greedy/Lusty/Wrathful/Gluttonous Joker
- Jolly/Zany/Mad/Crazy/Droll Joker (hand-type mult)
- Sly/Wily/Clever/Devious/Crafty (hand-type chips)
- Half Joker, Abstract Joker, Blue Joker
- Runner, Ice Cream, Green Joker, Ride the Bus
- Misprint, Scary Face, Business Card, Supernova

*Validation: for each joker, compare 100-game score distribution to real Balatro*

### Phase 3 — Boss blinds + consumables
- All 22 boss blind effects (The Ox, The Hook, The Eye, etc.)
- Planet cards (hand level upgrades)
- Tarot cards (card enhancements, joker rerolls, etc.)

### Phase 4 — Full joker set
- Remaining ~120 jokers
- Spectral cards
- Vouchers

### Phase 5 — Deck types + stakes
- Starting deck variations
- Stake modifiers (eternal jokers, negative ante, etc.)

---

## Cross-Validation Strategy

The v3 socket IPC makes real-Balatro the oracle:

```python
# test_crossval.py
def test_hand_score(hand_cards, jokers, expected_score):
    # 1. Feed same hand to sim
    sim_score = sim.score_hand(hand_cards, jokers)
    # 2. Feed same hand to real Balatro via socket
    real_score = socket_env.force_hand(hand_cards, jokers)
    assert abs(sim_score - real_score) / real_score < 0.01  # within 1%
```

Run cross-val suite after each joker batch is implemented. Catches ordering bugs,
retrigger edge cases, and boss blind interactions before they corrupt training.

---

## Observation Space (same as v3, 206 features)

Keeping 206 features unchanged so policies transfer. The sim can provide all of these
directly from Python state with zero parsing overhead.

See `balatro_rl/state_v2.py` for full spec.

---

## Training (v4)

With the sim, standard vectorized gym becomes viable:

```python
# train_v4.py
from stable_baselines3 import PPO
from stable_baselines3.common.vec_env import SubprocVecEnv
from balatro_rl.env_sim import BalatroSimEnv

envs = SubprocVecEnv([lambda: BalatroSimEnv() for _ in range(256)])
model = PPO("MlpPolicy", envs, ...)
model.learn(total_timesteps=10_000_000)
```

Or reuse train_v3.py with env_sim.py swapped in — same PPO loop, just faster envs.

Target: **10M steps** (vs v3's ~512k). Equivalent of ~70 hours of v3 training in under 1 hour.

---

## Policy Transfer (sim -> real Balatro)

After training on sim:
1. Load checkpoint
2. Swap `env_sim.py` for `env_socket.py` (same interface)
3. Run against real Balatro instances via socket
4. Compare ante distribution: sim-trained policy should match or exceed v3 policy

Any significant gap between sim and real performance indicates a sim fidelity bug worth fixing.

---

## Roadmap

```
v3 (current): Socket IPC + custom threaded PPO, real Balatro, ~100 sps
    |
v4a: Core sim (no jokers) + cross-val harness
    |
v4b: Common jokers implemented + validated
    |
v4c: Full joker set + boss blinds + consumables
    |
v4 training: 10M steps on sim, policy deployed to real Balatro
    |
v5 (future): Shop agent (original V4 design), now with fast sim underneath
```

---

## Key Decisions

- **Keep 206-feature obs** — policy transfers to real Balatro without retraining
- **Phase joker implementation** — validate each batch before training on it
- **Real Balatro as oracle** — cross-val catches sim bugs before they corrupt training
- **Separate jokers into submodules** — easier to track what's implemented vs not
- **No half measures** — full faithful ruleset, not a simplified approximation
