# V6 Training Run Log

V6 = single-agent PPO with enhanced shop obs (402 dims), heuristic shop rewards,
randomized seeds, 2000-step truncation. Returns to V4 single-agent architecture
after V5 dual-agent failed.

---

## V5 Runs (for reference — all failed)

| Run | Config | Result | Failure Mode |
|-----|--------|--------|--------------|
| 1 | Phase A, frozen play | 0% win, shop collapsed iter 31 | Shop starvation |
| 2 | Phase B, pretrained play | NaN crash | Embed shape mismatch |
| 3 | Phase B, NaN fixed | NaN crash iter 1484 | Advantage normalization |
| 4 | Phase B, all NaN fixed | Play entropy collapsed | Pretrained weights + low entropy |
| 5 | Phase B, entropy 0.05 | NaN crash iter 1106 | Extreme advantages with 4k truncation |
| 6 | Phase B, full NaN hardening | Play+shop entropy collapsed | Pretrained agent dominates |
| 7 | Phase B, entropy 0.05 | rew +0.35, no wins | Shop "leave immediately" |
| 8 | Phase B, both from scratch | rew +0.08, no wins | Shop starvation structural |
| 9 | Phase B, leave penalty | rew -0.23, no wins | Shop not buying jokers |
| 10 | Combo fix, from scratch | rew +0.55, 0 wins, **46% blind clears** | First working play agent |
| 11 | + heuristic rewards | rew +7.99, 0 wins, entropy collapsed to 0 | Play exploits, shop starved |
| 12 | + shop workers, entropy floors | rew +1.85, 0 wins | Shop workers killed play training |

**Key V5 discovery:** The combo scoring bug in `env_v5.py._update_play_combos()` was
responsible for all runs 1-9 failing to clear ante 1. Every combo scored 0 due to wrong
`score_hand()` arguments — the agent was playing random hands.

---

## Run 1 — V6 Single Agent, Fixed Seeds (baseline)

**Config:** 16 workers, 4096 steps/iter (256/worker), 1000 iters, fixed seeds per worker
**Result:** Reward 50-100+, reached ante 9, 0% formal win rate but 19,361 highlight wins
**Duration:** ~45 minutes

**Metrics at iter 500:**
- rew=+50-100 (highly variable), best ante=9
- 21,438 highlight episodes (ante >= 7), 19,361 wins
- Entropy 2.7 (very healthy)

**Strategy discovered:**
- Plays Pairs (48%) and Two Pairs (21%) almost exclusively
- One-shots every blind (1 hand per ante in winning games)
- Top jokers: Green Joker (33% of wins), Burglar (31%), Space Joker (26%)
- Found Green Joker + Burglar synergy (extra hands feed mult scaling)

**Problem:** Only 117 unique seeds across all wins — heavy seed memorization.
Agent did NOT adapt hand type to joker loadout (deltas < 3% across conditions).

---

## Run 2 — V6 Single Agent, Random Seeds (current) ← RUNNING

**Config:** 16 workers, 32k steps/iter (2048/worker), 1000 iters, random seed per episode,
2000-step truncation
**Status:** iter 25+, reward +68-82, best ante 9, healthy entropy 2.5-2.7

**Early metrics:**
| Iter | Reward | Best Ante | Entropy | Eps/iter |
|------|--------|-----------|---------|----------|
| 1 | +8.57 | 6 | 2.88 | 400 |
| 4 | +25.90 | 9 | 2.83 | 187 |
| 10 | +43.93 | 9 | 2.78 | 156 |
| 15 | +98.51 | 9 | 2.58 | 136 |
| 25 | +68.01 | 9 | 2.71 | 129 |

**Observations:**
- Reward volatile (some iters have early deaths, others have deep runs)
- Entropy staying healthy at 2.5-2.7 (no collapse)
- Reaching ante 9 regularly by iter 4
- Need to wait for full run to assess win rate and seed generalization

**ETA:** ~6.5 hours for 1000 iterations at ~24s/iter

---

---

## Run 3 — V6 Single Agent, Random Seeds + Boss Blind Loop Fix ← RUNNING

**Config:** 16 workers, 32k steps/iter (2048/worker), 1000 iters, random seed per episode,
2000-step truncation

**Bug fixed before this run:** Boss blinds bl_mouth and bl_eye could cause infinite loops.
When all combos were blocked by the boss restriction, `_play_hand()` silently returned
without decrementing `hands_left`. The combo ranker also didn't filter restricted combos,
so the action mask showed valid combos that the game would reject.

- Combo ranker now filters boss-restricted combos (bl_mouth, bl_eye, bl_psychic)
- When ALL combos blocked, includes 1 fallback combo (game.py consumes the hand on rejection)
- `_play_hand()` now decrements hands_left on boss rejection (prevents infinite loops)
- Previously 4% of seeds were stuck indefinitely; now 0/1000 tested seeds get stuck

---

## Run 4 — V6 + Excess Money Penalty + Sell Blunder Penalty ← RUNNING

**Config:** 16 workers, 32k steps/iter, 1000 iters, random seeds, 2000-step truncation

**Changes from Run 3:**

1. **Excess money penalty on leaving shop:** -0.02 per dollar above the nearest $5
   interest boundary (holding $25 = max interest, so $9 -> spend $4, $32 -> spend $7).
   Respects the interest mechanic while pushing the agent to invest excess in jokers/planets.

2. **Sell blunder penalty:** -0.5 for selling a joker when you have open slots AND there's
   no expensive upgrade in the shop you can't currently afford. The agent was doing
   buy-sell-buy cycles (buy joker for $6, sell for $3, buy something else, leave broke).
   This is almost always a mistake — you lose half the value and end up with fewer jokers.

**Run 3 final stats (at iter ~30, killed for Run 4):**
- Win rate: 2.5%, avg ante 1.4, 70% die on ante 1 boss blind
- Agent averaged $5 at game end (money penalty working vs Run 2's $21)
- But only 1.5 avg jokers in wins — still not filling slots
- Top strategy: Burglar + Green Joker + Space Joker, 79% Pairs

**Run 4 killed at iter ~117 due to Burglar bug discovery (see Run 5).**

---

## Run 5 — V6 + Burglar Bug Fix ← RUNNING

**Config:** 16 workers, 32k steps/iter, 1000 iters, random seeds, all previous fixes

**Bug fixed: j_burglar was a broken scaling mult joker instead of a hand modifier.**

How it was discovered: Reviewing highlight play-by-plays, game #4 showed a win with 0
jokers scoring 676,424 chips on a Straight at ante 1 boss blind. The math didn't add up —
a level 1 Straight scores ~316 chips. Investigating the top wins showed the Burglar +
Space Joker + Green Joker "synergy" was producing 612 million chip Pairs by ante 8.

Root cause: `scaling.py` implemented Burglar as `+3 mult per hand played, -3 per discard`
with permanent accumulation in `inst.state["mult"]`. After 100 hands this gives +300 mult.
Combined with Green Joker (+1 mult/hand) and Space Joker (leveling Pair to 30+), this
produced exponential score inflation.

Real Balatro Burglar: **+3 Hands, -3 Discards when Blind is selected.** It's a game-state
modifier that gives you 7 hands but 0 discards per blind — a high-risk tradeoff, not a
scaling mult engine.

Fix: Rewrote Burglar to use `on_blind_selected` hook setting `extra_hands=3` and
`zero_discards=True`. `game.py._start_blind()` reads these and modifies `hands_left`
and `discards_left` accordingly.

**Impact:** The agent's entire winning strategy (Burglar+Green+Space, 33%+32%+31% of wins)
was built on a broken joker. Scores will drop dramatically and the agent must discover
new strategies from scratch. This is a hard reset of learning.

---

## Run 6 — V6 + Full Sim Audit + Card Counting ← RUNNING

**Config:** 16 workers, 32k steps/iter, 1000 iters, random seeds, all fixes applied

**Changes from Run 5:**

1. **Full joker audit — 32 fixes:** 7 completely wrong effects, 8 additive→multiplicative,
   13 other corrections, 4 stubs implemented. ~30% of jokers had incorrect behavior.
   See V6_DESIGN_NOTES.md for full list.

2. **Non-joker sim fixes:** Lucky enhancement probability 1/5→1/4, Stone cards now included
   in scoring_cards (contribute +50 chips each).

3. **Card counting obs:** Deck composition features now show draw pile only (`gs.deck`)
   instead of full deck+hand. Hand cards are already encoded separately. Agent can now
   reason about what's left to draw after discards.

**Run 6 converged at 1.9% win rate by iter ~100. Killed at iter 287.**

Mid-run discovered and fixed passive joker accumulation bug (Troubadour/Juggler/Merry Andy/
Drunkard hand_size stacking every blind instead of being constant). Also fixed Cloud 9 and
To The Moon crashing on ctx=None in on_round_end, and Delayed Gratification ctx access.

Final results: 1.9% win rate, Green Joker (51%) + Space Joker (45%) still dominant.
Sim fixes gave modest boost (1.3% → 2.0%) but the architecture is the ceiling.

**Conclusion:** V6 single-agent with pre-ranked combos has hit its ceiling at ~2% win rate.
The agent cannot learn strategic discarding (the key to surviving ante 1) because the combo
ranker automates card selection. Next step: V7 with strategic discard actions.

---

## Planned: V7 — Strategic Discard Actions

See separate design doc when implementation begins. Key changes:
- Replace "discard card i" with strategic discard actions (Chase Flush/Straight/Trips)
- Add hand potential obs features (suit counts, draw probabilities)
- Combo comparison with "clears blind?" flag
- Card counting obs (draw pile composition)

---

## Planned Analysis

1. **Win rate on held-out seeds** — test on 1000 unseen seeds
2. **Seed generalization** — does random seed training reduce memorization?
3. **Joker adaptation** — does the agent change hand type based on joker loadout?
4. **Ante distribution** — how often does it clear each ante?
5. **Shop behavior** — is it buying jokers, using planets, or just leaving?

---

## Next Steps

1. **Card selection** — replace combo ranker with agent-driven card selection
2. **Attention architecture** — for joker synergy reasoning in shop
3. **Weight transfer to V5** — use V6 weights to bootstrap dual-agent training
4. **Red deck mode** — train with +1 discard (the target difficulty)
