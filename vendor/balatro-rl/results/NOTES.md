# Balatro RL — Project Notes

## Overview
Reinforcement learning agent (PPO via Stable-Baselines3) trained to play Balatro via live file-based IPC.
- Lua mod writes `state.json` after every game tick; Python reads it and writes `action.json`
- Agent controls card play/discard only (119-dim obs, MultiBinary(9) action)
- All navigation (blind select, cash out, shop, new run) handled headlessly by Lua mod

---

## Architecture

### IPC Protocol
- Lua writes: `AppData/Roaming/Balatro/balatro_rl/state.json` (every 100ms poll)
- Python writes: `AppData/Roaming/Balatro/balatro_rl/action.json` (consumed by Lua)
- Log: `AppData/Roaming/Balatro/balatro_rl/log.txt`

### Observation Space (119 features)
- `[0:56]`  Hand cards — 8 slots × 7 features (rank, suit, enhanced, edition, seal, highlighted, exists)
- `[56:86]` Jokers — 5 slots × 6 features
- `[86:95]` Scalar state — 9 features (ante, round, score_progress, hands_left, discards_left, money, joker_slots, deck_remaining, discard_count)
- `[95:119]` Hand levels — 12 types × 2 (level, chips)

### Action Space (MultiBinary(9))
- `action[0:8]` — which hand slots to highlight
- `action[8]`   — 1=play, 0=discard
- Cap at 5 cards; force play if discards=0

### PPO Hyperparameters
- `n_steps=512`, `batch_size=64`, `n_epochs=10`
- Net arch: [256, 256, 128], actor-critic MlpPolicy
- ~150k params

### Reward Structure
- `R_BLIND_COMPLETE = 1.0`  — cleared a blind
- `R_ANTE_COMPLETE  = 3.0`  — cleared all 3 blinds in an ante
- `R_WIN            = 10.0` — completed ante 8
- `R_LOSE           = -2.0` — ran out of hands
- `R_SCORE_PROGRESS = 0.05` — per 1% of score target gained
- Hand quality bonus on play: pair=0.10 → flush_five=1.10 (teaches hand selection early)

### Lua Nav (headless)
All nav is handled by `BalatroRL.lua` via `G.E_MANAGER` event queue:
- **Blind select**: 0.5s delay → queues `ease_round` + `new_round` events; uses `G.P_BLINDS[blind_choices[bod]]` for correct blind object
- **Cash out**: 1.0s delay → calls `G.FUNCS.cash_out({config={button="cash_out"}})`
- **Shop**: 0.8s delay → buy affordable jokers (tracks remaining $ and slots locally), then 0.5s → `G.FUNCS.toggle_shop`
- **New run**: 0.5s delay → calls `G.FUNCS.start_run(nil, {stake=1})`

### Shop Joker Buying
- Iterates `G.shop_jokers.cards`, filters to `card.ability.set == 'Joker'` only
- Tracks `remaining_dollars` and `slots_used` locally (game state updates are queued, not instant)
- Buys as many affordable jokers as fit in slots
- Controlled by `buy_jokers` config flag in `metadata.json`

---

## Training Progress (as of 2026-03-19)

### Current results (~700 episodes, ~110k timesteps)
| Metric | Value |
|--------|-------|
| Best reward | 5.72 (ep 444, ante 2) |
| Ante 2+ reached | 1 time |
| Avg reward trend | -1.48 → -0.75 (improving) |
| PPO updates | ~114 |
| Gradient steps | ~9,120 |

### What the agent has learned
- **Discarding heavily**: best run had 52 discards vs 11 plays — correctly learned that fishing for better hands before playing is worth it
- **Playing more cards per hand**: avg 4.6–6.0 cards per play in best runs (approaching 5-card hands)
- **Not yet**: flush/straight detection, joker synergies, deck building awareness

### Reward trend (current run)
```
ep   0- 99: avg=-1.477
ep 100-199: avg=-1.374
ep 200-299: avg=-1.020
ep 300-399: avg=-1.009
ep 400-499: avg=-0.788   ← ante 2 hit here
ep 500-599: avg=-0.799
ep 600-699: avg=-0.772
ep 700-799: avg=-0.752   ← current
```

---

## Known Limitations

### What's hard about Balatro for RL
1. **Non-Markovian deck** — deck composition matters enormously; agent doesn't see what cards remain
2. **Joker synergies** — 200+ jokers with combinatorial interactions; current 6-feature joker encoding barely captures what a joker does
3. **Long-horizon credit assignment** — joker bought in ante 1 shop pays off in ante 6; hundreds of steps of delay
4. **No memory across rounds** — agent has no recurrent state; can't track deck depletion or plan ahead
5. **Partial information** — doesn't see opponent blinds' chip targets ahead of time

### Realistic ceiling with current setup
- Reliable ante 3-4 play with enough training (~1M+ timesteps)
- Learning hand hierarchy (pairs → straights → flushes)
- Not expected to develop joker synergy strategies without architectural changes

---

## Future Development Ideas

### Near-term (tractable)
0. **Joker sell-upgrade in shop heuristic**
   - Current behavior: when slots are full, agent skips shop entirely and banks cash — observed holding $50+ by ante 3 while ignoring shop
   - Fix: if slots full AND a shop joker's rarity > min rarity of held jokers AND sell_value + current_cash >= shop_joker_cost → sell weakest joker, buy upgrade
   - Rarity field: `card.config.center.rarity` (1=Common, 2=Uncommon, 3=Rare, 4=Legendary)
   - "Weakest" = lowest sell value (proxy for rarity; don't sell Uncommon for Uncommon, strict upgrades only)
   - Also consider rerolling shop when slots full and nothing is an upgrade — `$5` reroll is often better than banking
   - Implementation: ~10-15 lines in Lua shop buy loop, after the existing joker buy logic

1. **Deck composition in obs — do this before next long training run (requires fresh start)**
   - Add remaining deck counts to obs: rank counts (13) + suit counts (4) = **17 new features**
   - OBS_SIZE: 119 → 136; PPO input layer auto-resizes, existing checkpoints incompatible (start fresh)
   - **Lua side**: iterate `G.deck.cards` each poll tick, count rank/suit, write as two arrays to state.json
   - **Python side**: parse in `state.py`, append 17 features after existing 119, update OBS_SIZE constant
   - Why useful: lets agent reason about flush/straight odds, avoid fishing for already-seen ranks
   - Option A (52 features, full bitmap) is lossless but larger; Option C (17 features) is sweet spot

1. **Score simulation in obs (Option 2)**: Have Lua calculate the predicted chip×mult score for each candidate hand subset and include it in state.json. Agent sees "playing these 5 cards scores 847 chips" directly — collapses most of card-selection into a lookup. Removes need to learn hand hierarchy from scratch.

2. **Joker categorization**: Tag each joker as one of:
   - Scoring jokers (multiply chips/mult directly)
   - Deck-fixing jokers (improve card quality, e.g. add enhancements)
   - Economy jokers (generate money per hand/discard)
   Add category + rarity (Common/Uncommon/Rare/Legendary) as obs features. Rarity weights already in game data.

3. **Temporal joker value**: Economy/deck-fix jokers have higher value early (ante 1-2); scoring jokers dominate late (ante 6+). This is almost impossible to learn from sparse rewards alone — **reward shaping** could bootstrap it: small bonus for buying economy joker in early antes.

4. **Richer deck obs**: Add remaining deck composition (13 ranks × 4 suits = 52 binary features) so agent can reason about flush/straight probability.

### Medium-term
5. **Recurrent policy (LSTM)**: Replace MlpPolicy with RecurrentPPO (SB3-contrib). Gives agent memory across rounds — can track deck state, plan joker purchases.

6. **Parallel training**: SB3 supports `SubprocVecEnv` for N parallel environments. Would need N Balatro instances. Real unlock is **headless simulation** — strip Balatro to pure Lua state machine (no LÖVE rendering) and run thousands of episodes/minute.

7. **Curriculum learning**: Start on easy blinds only (Small Blind ante 1), gradually unlock harder content as agent achieves milestones. Prevents agent from spending 90% of training on losing runs.

### Long-term / research-level
8. **Imitation learning (behavioral cloning)**: Pre-train policy on high-level gameplay. YouTube has good Balatro content, but video → game state extraction is a major sub-project. Would need either a replay system or a computer vision pipeline to extract card states from video frames. AlphaStar used this approach with StarCraft replays.

9. **World model / score predictor**: Train a separate small net to predict score given hand + jokers, use embeddings as policy input. Effectively learns the Balatro scoring engine from data.

10. **Self-play / MCTS**: Monte Carlo tree search over possible card plays with rollouts. More compute-intensive but principled.

---

## Technical Notes

### Key Balatro API facts
- `G.STATES`: SELECTING_HAND=1, HAND_PLAYED=2, DRAW_TO_HAND=3, GAME_OVER=4, SHOP=5, BLIND_SELECT=7, ROUND_EVAL=8, NEW_ROUND=19
- `G.blind_on_deck`: "Small"/"Big"/"Boss" — current blind position
- `G.GAME.round_resets.blind_choices`: maps "Small"→"bl_small" (string key into G.P_BLINDS)
- `G.shop_jokers.cards`: list of joker cards currently in shop
- `card.ability.set == 'Joker'`: correct filter for jokers (vs consumables, vouchers)
- `ease_dollars(-cost)` is called inside `buy_from_shop` — don't call it separately
- `G.CONTROLLER.locks.toggle_shop` must be cleared after toggle_shop or subsequent calls may be blocked

### SB3 / training gotchas
- Always `python train.py --resume` — never start fresh mid-training (discards weights)
- `hand_levels` in state.json is a list, not dict — `_parse_hand_levels()` converts to keyed dict
- `MultiBinary(9)` actions stored as `.tolist()` in best_runs.jsonl
- Monitor CSV only tracks current session; episode_log.jsonl accumulates across restarts

### Files
| File | Purpose |
|------|---------|
| `BalatroRL.lua` | Lua mod — state writer + headless nav + action executor |
| `balatro_rl/state.py` | State parsing, observation encoding |
| `balatro_rl/action.py` | Action writing, agent output → card indices |
| `balatro_rl/env.py` | Gymnasium environment |
| `train.py` | PPO training loop with BestRunCallback |
| `analyze.py` | Episode log analysis |
| `test_shop.py` | Watch shop nav in real-time |
| `plot_training.py` | Reward curve visualization |
| `versions/` | Archived mod versions (lua_nav, no_nav) |
| `logs/episode_log.jsonl` | Per-episode stats (all runs) |
| `logs/best_runs.jsonl` | Full action sequences of best episodes |
| `checkpoints/` | PPO model checkpoints |

## V2 Architecture Plan

### Core Idea
Replace MultiBinary(9) card selection with Discrete(20) pre-ranked action selection.
Lua pre-computes all valid plays and discards, ranks them, and includes them in state.json.
Agent picks one of 20 options instead of setting 9 bits blindly.

### Action Space: Discrete(20)
```
[0-9]   → play one of top 10 hands (ranked by chip×mult, highest first)
[10-19] → discard one of top 10 card subsets (ranked by draw potential)
```
Lua enumerates all ~218 card combinations (C(8,1) through C(8,5)), scores each,
returns top 10 plays and top 10 discards in state.json.

### Obs Space Additions (~206 total features)
- 10 play options × (chips, mult, hand_type_id, num_cards) = 40 features
- 10 discard options × (expected_gain, cards_kept_type, hand_type_targeted) = 30 features
- Deck composition: 13 rank counts + 4 suit counts = 17 features
- Existing: 119 features → total ~206

### Ranking Logic
**Plays:** sort all C(8,k) combinations by chip×mult (Lua calculates base score)
**Discards:** rank by expected hand improvement given remaining deck
  - Simple version (no deck obs): keep cards that maximize current best hand, discard rest
  - Full version (with deck obs): factor in probability of drawing into target hand type

### Decision Flow (mirrors human 3-step logic)
1. What is the best hand I can play right now? → play options [0-9]
2. Does playing sacrifice future value given what I have left to draw? → needs deck obs
3. If not worth playing, what to discard to maximize next draw? → discard options [10-19]

### Curriculum Learning via Action Masking
Keep Discrete(20) throughout training. Use SB3 action masking to control effective action space:
- Early training: all 20 options unmasked (full guidance)
- Fine-tuning: progressively mask lower-ranked options (top 3 plays + top 3 discards)
- Masking sets invalid actions to -inf logit — agent never picks them
- Same weights throughout, no architecture change needed
- Avoids the "shrink action space" problem (would require retraining output layer)

### Why This Enables New Strategies
- One-shot blind strategy: agent sees chip×mult for best hand → can learn to hold discards
  for a single high-value play rather than burning through hands
- Money joker discovery: with economic obs visible, agent can learn "play weak hands for gold
  now → buy better joker → shift to one-shot strategy"
- Flush/straight planning: deck composition + discard options let agent build toward target hand

### Performance Impact
- Lua enumeration of ~218 combinations: <1ms, negligible at 32x speed
- Obs size increase ~73%: minor, MLP handles this fine
- Requires fresh training start (obs + action space both change)

### Comparison to Current Model
| | V1 (current) | V2 |
|---|---|---|
| Action space | MultiBinary(9) = 512 combos | Discrete(20) |
| Obs features | 119 | ~206 |
| Hand scoring | agent guesses | Lua pre-computes |
| Deck awareness | none | rank+suit counts |
| Discard strategy | blind | ranked by draw potential |
| Expected win rate | ~0% | unknown, target >5% |

## V3 Architecture Plan

### Overview
V2 playing agent + new dedicated shop agent. Playing agent unchanged from V2 unless training reveals new additions. Shop agent replaces Lua heuristic with a learned policy.

### V3 Shop Agent Obs
```
money                    — current dollars
interest_threshold       — how close to next $1 interest bracket
jokers[3] × features    — rarity, edition, category (scoring/economy/deck-fixing)
ante                     — current ante (1-8)
blind_type              — Small/Big/Boss
upcoming_boss           — which boss blind is next (huge: some punish specific hand types)
                           e.g. The Arm degrades hand levels, Violet Vessel needs huge mult
skip_tags[3]            — available tag rewards for skipping (free joker tag = don't spend)
hand_levels[12]         — which hand types have been leveled up
hands_remaining         — hands left this blind
shop_jokers[2]          — what's currently in shop (rarity, edition, category, cost)
reroll_cost             — current reroll price
```

### Communication Between Agents (Simple Version — recommended first)
Bidirectional structured obs features — no learned encoding:
```
Playing agent → shop agent:  hand_level_distribution (12d) — what hands have been working
Shop agent → playing agent:  joker_category_counts (3d)    — scoring/economy/deck jokers held
```
- Human-designed signals, easy to interpret, trains fast
- Playing agent knows its loadout changed after shop without rediscovering by trial and error
- Gets ~80% of the benefit at 20% of the complexity

### Communication Between Agents (Complex Version — research-level)
Fully bidirectional learned latent vectors:
```
Playing agent hidden state → strategy_out (16d) → Shop agent obs
Shop agent hidden state    → loadout_out  (16d) → Playing agent obs
```
- `strategy_out`: "I've been landing flushes, I need flush support"
- `loadout_out`:  "I just bought Fibonacci + Scary Face, lean into high cards"
- Playing agent wakes up post-shop knowing its loadout changed, shifts hand selection immediately
- No hand-engineering — what to communicate emerges from joint training
- Gradients flow through both agents simultaneously with shared reward
- Classic chicken-and-egg convergence problem: neither vector is useful until the other agent
  learns to use it — why this needs parallel envs and millions of episodes to converge

### Compute Requirements
| Version | Networks | Episodes to plateau | Parallel envs needed |
|---|---|---|---|
| V2 | 1 | ~50-100k | 1 |
| V3 simple | 2 separate | ~200k | 1-2 |
| V3 learned comm | 2 + shared encoder | millions | 4-8 minimum |

V3 learned comm requires WSL2 + Xvfb running 4-8 headless Balatro instances simultaneously. Parallel training near-mandatory. Genuinely research-level — emergent communication between agents is an active RL research area and notoriously slow to converge.

### Intuition: The Callout Analogy
The two levels of the communication system map cleanly to competitive gaming:

**Encoder weights = the callout vocabulary**
What each callout implies — "short" means peek around the corner, hold an angle, expect a push.
This is learned across millions of games and stays fixed once trained.
It's the shared language, not the content.

**16 floats each game = the actual callouts in real time**
"Short, short, he's pushing" — specific information about *this* game, *this* moment.
Resets to zero each new run and fills in dynamically as the game progresses.

**Early training = two players who just met**
One says "short" and the other doesn't know if it means peek, rotate, or flash.
The vectors carry noise, agents largely ignore them, both act on local obs only.

**Late training = experienced duo**
Playing agent has been landing flushes all run → produces a vector the shop agent has learned
means "flush build, buy flush support" → shop agent buys Smeared Joker → playing agent
picks up post-shop, vector says "flush support acquired" → holds suited cards more aggressively.
The specific strategy varies every game but the language for communicating it is shared.

**Why parallel envs matter**
Two players getting one game a day together vs eight games a day — the shared language
develops orders of magnitude faster with more reps. Same reason v3 needs 4-8 parallel
Balatro instances: enough games per gradient update to force the vocabulary to converge.

The reward signal is what drives vocabulary development — coordinated plays produce wins,
ignored communication doesn't. The encoding that emerges is whatever happened to be most
useful for winning. You don't design the language, you create conditions for it to develop.

### Recommendation
Implement V3 simple first. Only pursue learned comm if simple version plateaus and a meaningful performance gap remains.

## Training Milestones

### Checkpoint: Shop Heuristic Upgrade (2026-03-19 ~19:00 MDT)
- **Log index**: 7806 (after bad-ep removal) + new episodes since = ~9389 per training plot
- **Actual log entry at restart**: ep=115, ts=155960, reward=0.917 (training had restarted, log index ~9389 on plot)
- **Changes introduced at this point**:
  - Sell-upgrade: swap weakest held joker for strictly higher effective_value shop joker
  - Edition scoring: Poly+10, Holo+5, Foil+3 added to rarity�10 base score
  - Negative protection: never sell Negative jokers under any circumstances
  - Reroll: one reroll per shop when cash > 2� reroll_cost and no jokers in shop
  - WON watchdog removed (was causing ante double-increment on The Hook)
  - Ante guard self-recovery: Lua fires start_run when rr_ante > win_ante
- **Goal**: compare ante 2+ rate and avg reward in next 5-10k episodes vs baseline

### Exploration Note
- Epsilon-greedy wrapper considered but probably not worth implementing
- PPO entropy bonus already handles exploration implicitly
- Adding a passive exploration slot to the action array does nothing useful � agent never picks it if policy thinks it's suboptimal
- If policy collapse becomes an issue, simplest fix is keeping entropy_coef higher for longer rather than adding explicit epsilon-greedy

---

## v3 Socket IPC + Ray Training Attempt � 2026-03-27

### Goal
Replace file-based IPC (polling) with TCP socket IPC for lower latency and higher throughput.
Target: ~94 steps/sec across 8 instances (vs v2 parallel's ~6 steps/sec � ~16x improvement).

---

### Phase 1: v2 Parallel Baseline (Confirmed Working)
- 8 instances, file IPC, 64x game speed, Ray PPO (old API stack)
- Throughput: ~6 steps/sec total (~2,500 steps/hour)
- Run `brisk-canyon`: reached Ante 5 by episode 279, ~41k steps by pause point
- Critical bug fixed: at 64x speed, Lua writes game_over then immediately starts new game,
  overwriting state.json before Python polls. Fix: track episode_seed; new seed = terminal.

---

### Phase 2: Socket IPC Development (Instance 9 Isolated)

**Bugs hit during setup:**
- Mod loader uses %APPDATA%\Balatro\Mods\ not local game folder
- v3 mod had same ID as v2 -> SMODS silently skipped it. Fix: unique ID BalatroRL_v3
- LOVE filesystem not ready at module load -> socket_init() deferred to game.update
- Lua bind("*") on Windows only binds IPv6. Python must connect via ::1
- Python sent key "cards" but Lua expected "card_indices" -> actions silently failed
- G.GAME.seed always nil in Balatro -> removed seed-based reset detection

**Result:** Validated end-to-end. 3 episodes (210, 154, 97 steps), all terminated correctly.

---

### Phase 3: Benchmark Results

Socket IPC vs File IPC at 64x game speed (10 episodes each):
- Socket: 6.1 steps/sec, 91 steps/episode
- File:   1.8 steps/sec, 20 steps/episode
- Socket is 3.31x faster

128x validation (single instance):
- 64x: 6.1 steps/sec -> 128x: 11.7 steps/sec (linear scaling confirmed)

---

### Phase 4: Deploy v3 to All 8 Instances
- Dynamic port: 5000 + INSTANCE_ID -> ports 5001-5008
- All 8 instances confirmed listening at 128x game speed
- v2 file mod disabled on instances 1-8

---

### Phase 5: Ray Training � Full Bug Log (FAILED)

Every bug below was found, fixed, and immediately revealed the next one.
The 1-env debug test (debug_ray.py) worked: 96 steps across 3 iterations (~135s/iter).
8-env training never produced usable throughput.

**Bug 1 � keep_fresh flooding TCP buffer**
Lua sent state every game.update tick while in SELECTING_HAND. Python busy during
training -> buffer filled -> send timeout -> Lua dropped connection.
Fix: Removed keep_fresh entirely.

**Bug 2 � Regex broke underscore action names**
Pattern (%a+) stops at underscores. "new_run" parsed as "new", "leave_shop" as "leave".
Actions silently fell through to wrong handler.
Fix: Changed to ([%a_]+).

**Bug 3 � No initial state on connect (after removing keep_fresh)**
Python's reset() waited 60 seconds then returned zero observation.
Fix: _send_on_connect flag. On the tick after Python connects, send current state.

**Bug 4 � _send_after_action fired before action executed**
G.E_MANAGER processes events next frame, not same tick. Python received stale state,
then received actual post-action state -> buffer overflow / confusion.
Fix: Removed _send_after_action entirely.
- Play actions: G.STATE transitions (SELECTING_HAND->HAND_PLAYED->...->SELECTING_HAND) trigger send
- Discard actions: track _prev_discards; send "selecting_hand" when discards_left decreases

**Bug 5 � Wrong Ray metric key**
Logged num_env_steps_sampled_lifetime but old Ray API returns timesteps_total.
Fix: Updated key in train_ray_socket.py.

**Bug 6 � Stale sock_client in Lua after Python killed**
When training was killed and restarted, Lua held a dead connection. New Python
connection refused (Lua thought it was still connected).
Fix: reset() always disconnects before reconnecting.

**Bug 7 � Fragile dead-connection check (reverted)**
Added receive(0) in socket_try_accept() to detect dead connection. Was consuming
buffered data, causing issues. Reverted to simple if sock_client then return end check.

**Bug 8 � Wrong discard detection field**
Checked G.GAME.round_resets.discards (never changes mid-round).
Should be G.GAME.current_round.discards_left.
Fix: Updated field name.

**Bug 9 � Invalid actions time out at 60 seconds**
Random policy takes "discard" when discards_left=0. execute_action guard returns
immediately, no state change -> Python waits 60 seconds for a response that never comes.
Fix: 4-tick fallback timer in Lua. If no state sent after 4 game.update ticks (~200ms),
send current state as fallback.

**Bug 10 � Always-reconnect causing connection churn**
reset() disconnected/reconnected every episode. 8 envs constantly cycling connections
-> Lua overwhelmed.
Fix: Persistent connection. Connect once in __init__, only reconnect on actual drop.

**After ALL fixes: still 0.06-0.07 steps/sec (vs target ~94 steps/sec)**

---

### Root Cause: Ray VectorEnv is Inherently Sequential

Ray's old API VectorEnv (required � new API hangs on init, known Ray bug) steps all
8 envs one at a time in a single thread. Even at 90ms/step:
  8 sequential envs = 11.7 steps/sec total (same as 1 env � no parallelism gained)

With rollout_fragment_length=128 and ~15s/step observed:
  128 x 15s = 1920s > sample_timeout=600 -> "no samples" warning -> training hangs

Tried: fragment_length=16, sample_timeout=3600. Still 0.06 steps/sec.

Ray adds nothing on a single machine (no multi-machine distribution needed here).
The infrastructure overhead dominates everything else.

---

### Decision: Custom Threaded Training Loop

Why it beats Ray even in the theoretical best case:
- Ray VectorEnv (old API): sequential -> 11.7 steps/sec total regardless of env count
- Custom loop, 8 threads: GIL releases on socket recv -> true concurrency
  -> 8 x 11.7 = ~90 steps/sec (the original design goal)

Implementation plan: ~200 lines of PyTorch PPO, one thread per env, shared experience buffer.

---

### What Is Confirmed Working
- Socket IPC protocol (TCP, IPv6, newline-delimited JSON)
- All 8 instances with dynamic ports 5001-5008 at 128x game speed
- G.STATE transition-based state sending (play actions)
- Fallback timer for invalid/stuck actions
- Persistent connections
- 1-env training end-to-end (debug_ray.py)

### What Never Worked
- Ray with 8 envs: always 0.06-0.07 steps/sec regardless of fixes applied
- Ray new API stack: hangs on init (upstream Ray bug #53727)
- Ray callbacks: incompatible with old API stack
