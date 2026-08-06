# Balatro Multiplayer Mod — Standard Ranked Ruleset

Reference document for V8 self-play design. Summary of mechanics from the official
Balatro Multiplayer mod (balatromp.com) and the Standard Ranked competitive ruleset.

Sources:
- [Standard Ranked Ruleset](https://balatromp.com/docs/rulesets/standard)
- [Ranked Rules](https://balatromp.com/docs/ranked-matchmaking/Ranked-rules)
- [Multiplayer FAQ](https://balatromp.com/docs/getting-started/faq)
- [Official mod site](https://balatromp.com/)
- [GitHub repo](https://github.com/Balatro-Multiplayer/BalatroMultiplayer)

---

## Core Multiplayer Mechanics

### Blind Structure (per ante)

| Blind | Mechanic |
|-------|---------|
| Small Blind | Each player plays normally on the SAME seed. No direct interaction. |
| Big Blind | Each player plays normally on the SAME seed. No direct interaction. |
| **PvP Boss Blind** | Head-to-head. Higher score wins. Loser loses a life. |

### Lives System

- Each player starts with a set number of lives (usually **4** in Ranked)
- **You DON'T lose the game for failing a small/big blind** — you still compete at PvP
- You lose a life on:
  - Losing the PvP blind (lower score than opponent)
  - Failing a regular blind AND losing the subsequent PvP
- Game ends when a player runs out of lives
- **Comeback money** (Standard Ranked): $4 per life lost (Blue stake+: $2), only during PvP blinds

### Shop Synchronization

- Both players see different shops (shops are not shared)
- Both players play the same seed for CARDS drawn (same blind progression)
- Shop randomness is independent per player

### Early Win Mechanic

When both players are in the PvP blind, **if you finish your hands and have a higher score than the opponent's current score, you immediately win the round**. The opponent doesn't get to play remaining hands.

Consequences:
- **Bad for you if winning early:** miss out on money-earning jokers, scaling jokers stop triggering, seals don't get chance to work
- **Good for you if winning early:** collect hands-remaining money, save fragile cards (Glass cards not broken, Gros Michel not destroyed)
- Creates interesting timing decisions — do you play fast for early win, or slow for maximum value?

### Stalled PvP Blind Rule

If a PvP blind is taking too long, the lower-scoring player must play first.

---

## Standard Ranked Balance Changes (vs Base Game)

### New Multiplayer Jokers (10 total)

These don't exist in singleplayer — they reference your "Nemesis" (opponent):

| Joker | Effect |
|-------|--------|
| Defensive Joker | +125 Chips for every life less than your Nemesis |
| Skip-Off | +1 Hands and +1 Discards per additional Blind skipped vs Nemesis |
| Let's Go Gambling | 1/4 chance for X4 Mult and $10; 1/4 chance to give Nemesis $10 |
| Speedrun | Create random Spectral card if reaching PvP Blind before Nemesis |
| Conjoined Joker | X0.5 Mult per remaining Hand your Nemesis has (Max X3) |
| Penny Pincher | Gain $1 for every $3 Nemesis spent in corresponding shop |
| Taxes | +4 Mult for every card Nemesis sold since last PvP Blind |
| Pizza | Grant +1 discard to you and +2 to Nemesis after PvP Blind |
| Pacifist | X10 Mult while not in PvP Blind |

### Disabled Jokers (4)

Removed due to boss blind interactions (which are now PvP blinds):
- **Chicot** (disables boss blind effect — no longer meaningful)
- **Matador** ($8 for triggered boss effect — irrelevant)
- **Mr. Bones** (prevents loss at 25% — broken in lives system)
- **Luchador** (sell to disable boss — irrelevant)

### Modified Jokers (4)

| Joker | Base Effect | Ranked Effect |
|-------|------------|---------------|
| Hanging Chad | Retriggers first scoring card twice | Retriggers first AND second scoring cards once more |
| Seltzer | Retriggers all cards for 10 hands | Reduced to 8 hands |
| Turtle Bean | +5 hand size | Reduced to +4 hand size |
| Golden Ticket | $4 per Gold card, Common rarity | $3 per Gold card, Uncommon rarity |

### Spectral Card Change

- **Ouija**: Reworked to "Destroys 3 random cards, sets remaining to same rank"

### Planet Card Addition

- **Asteroid** (new): Removes one level from Nemesis's highest-level poker hand

### Tarot Card Changes

- **Justice** unavailable in Standard Ranked

### Enhancement Changes

- **Glass Cards**: X1.5 Mult with 25% destruction chance; only found in Standard packs or spawning Spectral cards (restricted availability)

---

## Game Modes

### Attrition
- Face off at each boss blind (every ante)
- Lives lost on PvP loss
- Lives lost if you fail a non-PvP blind AND then lose PvP
- Play until one player has 0 lives

### Showdown
- Each player gets 3 normal antes to prepare (no PvP on antes 1-3)
- After ante 3: endless mode where every blind is PvP
- Play until one player has 0 lives

### Hivemind (experimental, team mode)
- Up to 8 players, 4 teams
- Team coordinated play

### Potluck (experimental)
- Face all players at once
- Must beat the AVERAGE score across all players

---

## Implications for V8 Self-Play Design

### What Maps Well to Our Setup

1. **Same-seed small/big blinds** → Perfect for comparing two policies' play on identical game states
2. **4 lives system** → Natural mid-episode resets, sample efficiency boost
3. **PvP blind = burst scoring** → Shifts optimal strategy away from long-term scaling (Green+Space)
4. **Attrition mode** is the simplest to implement and most directly measures strategy quality

### What We'd Need to Build

1. **PvP blind scoring comparison** — compare both policies' scores on the same boss blind
2. **Lives tracking** — 4 lives per policy, lose on PvP loss
3. **Early win detection** — if one policy is ahead when other finishes
4. **Comeback money** — $4 per life lost (for loser)
5. **Game termination** — on 0 lives for either player

### What We Can Skip for Initial Prototype

1. Multiplayer-specific jokers (Defensive, Skip-Off, etc.) — too complex, use standard joker pool
2. The 10 new jokers — can add later if population training works
3. Balance adjustments (Seltzer, Turtle Bean nerfs) — our sim already has these at base values
4. Shop synchronization differences — both policies already play on different random shops
5. Nemesis-referencing mechanics — simplify to "score comparison only"

### Simplified V8 Phase 1 Rules

```
Setup:
  - 2 policies from same or different population members
  - Both play Attrition mode
  - 4 lives each
  - Standard sim (no multiplayer jokers yet)

Flow:
  - Ante 1: both policies play small + big blind on same seed, then PvP blind
  - PvP blind: compare scores, loser loses a life, both get comeback money ($4)
  - Shop: each policy gets independent shop
  - Repeat for antes 2-8
  - First player to 0 lives loses

Reward:
  - Per PvP win: +3.0
  - Per PvP loss: -2.0
  - Per ante cleared by both: +1.0 each
  - Total game win (opponent hit 0 lives first): +20.0
  - All existing V7 rewards still apply (card quality, synergy, etc.)
```

This gives us the population diversity benefit of self-play without needing to
implement the full mod. If it shows promise, we can add the multiplayer jokers
and more nuanced mechanics in V8.2.

---

## Full Source Documentation

- Standard Ranked ruleset: https://balatromp.com/docs/rulesets/standard
- Ranked matchmaking rules: https://balatromp.com/docs/ranked-matchmaking/Ranked-rules
- FAQ: https://balatromp.com/docs/getting-started/faq
- Official site: https://balatromp.com/
- Source code: https://github.com/Balatro-Multiplayer/BalatroMultiplayer
