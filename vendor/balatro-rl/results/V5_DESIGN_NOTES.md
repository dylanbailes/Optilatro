# V5 Design Notes — Dual-Agent: Shop Agent + Play Agent

*Written 2026-03-29. V4 established the Python sim foundation. V5 splits the single PPO
policy into two cooperating agents: a shop agent that manages economy and loadout, and a
play agent that handles card decisions during blinds.*

---

## Goal

**80% win rate on the red deck** (standard deck + 1 extra discard per round).

Human expert win rate is ~70% on white deck. 80% on red deck is above expert-level play.
This will require orders of magnitude more training than v4 runs (estimated 100M-500M steps
vs v4's 8M per run).

---

## Core Architecture

```
SHOP PHASE                           BLIND PHASE
+------------------+                +------------------+
|   Shop Agent     |                |   Play Agent     |
|   6-layer resnet |                |   6-layer resnet |
|   ~2.3M params   |                |   ~2.3M params   |
+--------+---------+                +--------+---------+
         |                                   |
         |  32-dim communication vector      |
         +---------> concat to obs ----------+
                     (stop-gradient)

Decoder Head (auxiliary, not in main loop):
  communication_vector -> MLP -> quality labels
  (interpretability only, no gradient to agents)
```

### Communication Vector
- **Direction:** Shop agent → Play agent only (start simple; bidirectional is an upgrade)
- **Size:** 32 dimensions (float32)
- **Timing:** Produced once at end of each shop phase, carried as fixed context through all
  hands of the next blind. Resets to zeros at start of game.
- **Gradient:** Hard stop-gradient — communication vector is detached before being passed
  to the play agent. Agents train independently, not jointly. This prevents co-adaptation
  instability while still allowing learned coordination.
- **Usage in play agent:** Concatenated to the 342-dim obs before the embed layer, giving
  the play agent obs_dim = 342 + 32 = 374.

---

## Agent Specs

### Play Agent
- Architecture: 6-layer residual network (same as v4 run 6)
- Input: 374-dim (342 game obs + 32 communication vector)
- Output: Discrete(46) — same action space as v4
- Initialization: load from run 6 checkpoint (`checkpoints_sim/iter_1000.pt`), fine-tune
- Phase: SELECTING_HAND and BLIND_SELECT only

### Shop Agent
- Architecture: 6-layer residual network (new, initialized fresh)
- Input: shop-specific obs (see below)
- Output: Hierarchical action space (see below)
- Phase: SHOP only (including pack sub-state)
- Communication output: 32-dim linear head on top of shared trunk

---

## Shop Agent Observation Space

Different from play agent — shop-relevant features only:

| Range | Description |
|-------|-------------|
| `[0:10]` | Game scalars: ante, round, dollars, interest, hands_left, reroll_cost, joker_slots_used, joker_slots_max, consumable_slots, deck_size |
| `[10:60]` | Current joker loadout — 5 slots × 10 features (type_id, sell_value, rarity, scaling_state, edition, is_foil, is_holo, is_poly, slot_idx, exists) |
| `[60:90]` | Shop items available — 6 slots × 5 features (type_id, kind, cost, rarity, exists) |
| `[90:100]` | Booster packs available — 2 slots × 5 features (pack_type, cost, cards_shown, picks_allowed, exists) |
| `[100:112]` | Planet/hand levels — 12 hand types (current level) |
| `[112:120]` | Consumable slots — 2 slots × 4 features (type_id, kind, has_target, exists) |
| `[120:124]` | Vouchers active — 27 binary flags (clearance sale, overstock, etc.) |
| `[124:136]` | Upcoming boss blind — one-hot over 15 boss types (The Ox, The Hook, etc.) |
| `[136:154]` | Deck composition — 13 rank counts (normalized) + 4 suit counts + total deck size |
| `[154:166]` | Card enhancement counts — foil, holo, poly, gold, wild counts; seal counts by type |

**Total shop obs: ~166 dims** (TBD, will finalize during implementation)

### Deck Composition and Variable Deck Size

Balatro supports non-standard deck sizes:
- DNA joker clones a card into the deck permanently each round
- Standard packs add new cards to the deck
- Death tarot destroys one card and copies another (neutral count)
- Some consumables destroy cards outright

Deck can range from ~40 cards (many destructions) to 60+ (DNA joker over many rounds).

**Obs encoding:** rank counts and suit counts are **normalized by total deck size**, not
hardcoded to 52. Deck size itself is included as a separate feature (normalized by 60 as
soft max). This handles all legal deck sizes without obs blowup.

---

## Hierarchical Action Space (Shop Agent)

The shop phase is a mini-MDP. The env tracks `shop_substate` to route actions:

### Top-level shop actions (normal shop)
```
0    reroll
1    leave_shop (end shop phase)
2-7  buy shop item 0-5
8-9  buy booster pack 0-1
10-14 sell joker 0-4
15-16 use consumable 0-1 (planet/no-target tarot)
```

### Pack sub-state (triggered by buy booster pack)
When a pack is opened, the env enters `PACK_OPEN` substate:
```
Pack contents are revealed (N cards/tarots/planets)
0 - (N-1)   select item i to keep (up to K picks allowed per pack type)
N           skip / take nothing
```

After selecting items, if any selected item requires a target (e.g. tarot that changes
card suit), env enters `PACK_TARGET` substate:
```
0-51+   select deck card index to apply effect to
52      skip targeting (for optional targets)
```

State machine:
```
SHOP -> buy pack -> PACK_OPEN -> pick item(s) ->
  if item needs target -> PACK_TARGET -> apply -> back to SHOP
  else -> back to SHOP
```

### Action masking
All actions are masked when not applicable:
- `buy item i`: masked if insufficient dollars or item slot empty
- `buy pack`: masked if insufficient dollars
- `sell joker i`: masked if slot empty
- `use consumable i`: masked if slot empty or consumable needs target (handled in substate)
- `reroll`: masked if dollars < reroll cost
- `leave_shop`: always valid

---

## Quality Estimator (Auxiliary Reward for Shop Agent)

At the end of each shop phase, compute a **loadout quality score** as a dense auxiliary
reward to shorten credit horizon:

```python
def loadout_quality(jokers, planet_levels, deck) -> float:
    score = 0.0

    # 1. Rarity bonus
    RARITY_WEIGHTS = {"common": 0.5, "uncommon": 1.0, "rare": 2.0, "legendary": 4.0}
    for j in jokers:
        score += RARITY_WEIGHTS.get(j.rarity, 0.5)

    # 2. Synergy bonus — detected combos get a multiplier
    SYNERGY_PAIRS = {
        ("j_green_joker", "j_burglar"):      2.5,  # extra hands feeds mult scaling
        ("j_green_joker", "j_space_joker"):  2.0,
        ("j_ride_the_bus", "j_red_card"):    1.5,
        ("j_blueprint", ANY_RARE):           2.0,
        # ... extensible registry
    }
    joker_keys = {j.key for j in jokers}
    for (k1, k2), bonus in SYNERGY_PAIRS.items():
        if k1 in joker_keys and k2 in joker_keys:
            score += bonus

    # 3. Planet level bonus — leveled hands are hard to acquire
    score += sum(max(0, lv - 1) * 0.3 for lv in planet_levels)

    # 4. Deck quality — enhanced cards bonus
    score += 0.1 * sum(1 for c in deck if c.enhancement or c.edition)

    return score

# Applied in env after shop phase:
quality_delta = new_quality - prev_quality
reward += R_QUALITY * quality_delta  # R_QUALITY = 0.2 (small vs blind rewards)
```

The synergy registry is extensible — add pairs as we discover what the agent learns to build.

---

## Decoder Head (Interpretability)

A small MLP trained as an auxiliary task to predict human-readable labels from the
communication vector:

```python
class CommDecoder(nn.Module):
    def __init__(self):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(32, 64), nn.ReLU(),
            nn.Linear(64, N_STRATEGY_LABELS)
        )
    # Labels: chip_focus, mult_focus, hand_type_leveling,
    #         economy_focus, survival_mode, late_game_push
    # Trained with BCELoss against rule-based heuristic labels
    # Gradient does NOT flow back to shop agent (detach comm_vec before decoder)
```

The decoder is trained on the side using heuristic labels computed from game state:
- "mult focus" = joker loadout has >2 mult-scaling jokers
- "economy focus" = >$15 dollars at end of shop
- "survival mode" = hands_left <= 2 and score_progress < 0.5
etc.

Useful for reward shaping analysis but not required for training.

---

## Training Strategy

### Phase 1 — Pretrain shop agent against frozen play agent
1. Load run 6 play agent checkpoint (freeze weights)
2. Train shop agent from scratch, 500 iters, 8k batch
3. Shop agent learns to build loadouts that work with the fixed play policy
4. Monitor: ante distribution shift (does shop agent learn to buy jokers that help?)

### Phase 2 — Joint fine-tuning
1. Unfreeze play agent (continue from run 6 weights)
2. Both agents train simultaneously, each updating on their own phase transitions
3. Communication vector now trained end-to-end (but still stop-gradient across boundary)
4. Monitor: communication vector variance (should be non-zero — agents are using it)

### Phase 3 — Extended joint training
1. Increase iterations, monitor win rate toward 80% target
2. Add synergy pairs to quality estimator as agent discovers new strategies
3. Analyze decoder head to understand emerging communication

---

## Batch Size

The shop phase is less frequent than the play phase. In a typical full run:
- ~288 play steps (8 antes × 3 blinds × 12 hands avg)
- ~24 shop steps (8 antes × 3 shop visits avg)
- Ratio: ~12:1 play:shop transitions

With 8k batch: only ~640 shop transitions per iter — insufficient for stable shop agent
gradient. 

**Recommendation: 16k batch for v5.**
- 16k total steps per iter
- ~1,280 shop transitions + ~14,720 play transitions
- Both agents get meaningful gradient per update

Alternative if 16k is too slow: asymmetric collection — collect until 8k play steps OR
2k shop steps, whichever comes second. Updates both agents when both have enough data.

The 16 workers × 1024 steps-per-worker = 16,384 total = ~16k. Clean number.

---

## Multi-Training Run Strategy

Three training configurations to compare:

| Config | Play agent | Shop agent | Purpose |
|--------|-----------|-----------|---------|
| A | Frozen (run 6) | Training | Establish shop agent baseline |
| B | Training (run 6 init) | Training | Full joint fine-tuning |
| C | Training (fresh) | Training | Does joint training from scratch work? |

Running A first is lowest risk and gives the clearest signal on shop agent quality.
B follows using A's shop agent checkpoint as initialization.
C is a longer shot — full end-to-end from scratch, more variance but potentially higher ceiling.

With enough instances running in parallel, variance across runs is manageable. Run
multiple seeds of config A simultaneously to get reliable ante distribution data.

---

## Reward Structure (V5)

Play agent rewards (same as v4):
```
Blind cleared:     2.0 * (9 - ante)  # inverse-ante scaling from run 6
Ante completed:   +5.0
Win:             +50.0
Loss:             -2.0
Score progress:  +0.05 * log1p(delta) * 100
```

Shop agent rewards:
```
Same blind/win/loss rewards as play agent (shared objective)
Loadout quality delta: +0.2 * quality_improvement (auxiliary, per shop phase)
```

---

## What Needs to Be Built

| Item | Priority | Notes |
|------|----------|-------|
| `open_pack()` env action + PACK_OPEN substate | High | Core new feature |
| PACK_TARGET substate for tarot targeting | High | Needed for deck manipulation |
| Shop agent obs encoder | High | ~166 dim, separate from play obs |
| Communication vector module (32-dim linear head) | High | On shop agent trunk |
| Play agent obs extension (342 + 32 = 374 input) | High | Concat comm vec |
| `env_v5.py` — unified env routing phases to agents | High | Replaces env_sim.py for v5 |
| `train_v5.py` — dual-agent PPO loop | High | Two optimizers, two update steps per iter |
| Quality estimator function + synergy registry | Medium | Auxiliary reward |
| CommDecoder auxiliary network | Low | Interpretability, not required for training |
| Red deck support in sim | Medium | +1 discard per round |
| Deck size normalization in obs | Medium | Handles DNA joker / added cards |
| Boss blind one-hot in shop obs | High | Shop agent needs to know upcoming boss |

---

## Key Decisions

- **Stop-gradient on communication**: independent training stability > joint optimization power
- **32-dim comm vector**: expressive enough for strategy tokens, small enough to not dominate obs
- **Hierarchical action space**: pack sub-state as mini-MDP inside shop MDP
- **Deck composition normalized by deck size**: handles variable deck sizes cleanly
- **Quality estimator = rarity + synergies + planet levels + enhanced card count**
- **16k batch for v5**: ensures enough shop transitions per update
- **Load run 6 play agent**: skip re-learning play basics, start from best known policy
- **Shop agent fresh**: no prior knowledge to anchor on; learns from scratch against run 6 policy
- **Target: 80% win rate, red deck**: above human expert performance
