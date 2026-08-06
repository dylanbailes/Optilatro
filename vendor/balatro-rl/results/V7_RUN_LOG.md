# V7 Training Run Log

V7 = hierarchical intent + learned card selection (Fix A approach).
Replaces V6's pre-ranked combo action space with a 2-level decision:
intent head (PLAY/DISCARD/USE_CONSUMABLE) + card scoring head that
defines a distribution over 218 card subsets.

---

## Architecture Summary

- **Obs:** 434 dims (V6's 402 + 4 new per-card features: suit_match, rank_match, straight_connectivity, card_chip_value)
- **Intent head:** Discrete(3) — PLAY / DISCARD / USE_CONSUMABLE
- **Card scoring head:** 8-dim sigmoid, conditioned on intent via embedding
- **Subset sampling:** card scores → softmax over 218 subsets → Categorical
- **Phase head:** Discrete(17) for BLIND_SELECT + SHOP actions
- **Factored log_prob:** log_prob(intent) + log_prob(subset|intent) for PPO
- **Network:** 2.48M params (vs V6's 2.34M)

---

## Run 1 — Initial V7 Training (no card quality reward)

**Config:** 16 workers, 32k steps/iter, 1000 iters planned, V6 weight migration
**Duration:** ~400 iterations before crash (Blueprint/Brainstorm recursion bug)
**Steps:** ~13M

**Results:**
- 5 wins / 755k episodes = **0.0007% win rate**
- Peak reward: 27.6 at iter 25
- Reward plateau: ~22 from iter 30 onward
- Intent distribution: P=55-60% D=28-34% C=7-17%
- Best ante reached: 9 (rarely)

**Diagnosis:**
The card scoring head wasn't getting useful reward signal. PPO sees similar reward for good and bad card selections because the log-scaled progress reward can't distinguish between a Full House (+2.0 reward) and a High Card (+0.1 reward) relative to episode variance (±30-50).

**Infrastructure fixes during run:**
- Vectorized subset logit computation in PPO update (per-step Python loop -> batched matmul). Throughput improved from ~0 sps to ~900 sps.
- n_cards capping at N_HAND_SLOTS (jokers like Troubadour give +2 hand size beyond the 8-slot observation).
- Blueprint/Brainstorm mutual recursion bug fix (recursion depth guard at 3 levels).

---

## Run 2 — Card Quality Reward

**Config:** Same as Run 1 + R_CARD_QUALITY = 2.0 reward
**Duration:** Resumed from Run 1 iter 410, ran to iter 1000
**Steps:** 13.5M → 32.8M

**Reward changes from Run 1:**
- NEW: Card quality bonus = R_CARD_QUALITY × (played_score / best_possible_score)
  - Computed per hand played, rewards playing strong hands relative to what was possible
  - Best possible score computed by enumerating all 218 subsets with score_hand()

**Results:**
- **24,627 wins / 1,398,281 episodes = 1.76% win rate**
- **Last 50 iters: 1.98% win rate** (matches V6's 1.9% baseline)
- Reward climbed from ~22 → ~35 within 50 iterations of enabling quality reward
- Intent distribution shifted: P=54% D=28% C=18% (V6 used no discards)
- Best ante reached: 9 consistently

**Strategy discovered:** Green Joker (47%) + Space Joker (51%) in 73% of wins. Same as V6. Agent plays High Cards (63%) and Pairs (33%) almost exclusively to maximize hands played (feeds Green Joker scaling + Space Joker level-ups).

**Key insight:** Card quality reward solved the per-hand signal problem. Agent can now learn "pick good cards" from the reward. BUT: converged to the same dominant strategy as V6 because Green+Space worked in training and PPO reinforced it. Shop-side decisions (which jokers to buy) still opaque to PPO — the agent just buys Green/Space whenever available.

---

## Run 3 — Synergy-Based Shop Reward (failed to break lock-in)

**Config:** V6 migration, rebalanced rewards to focus on shop + play fundamentals
**Duration:** Started fresh from V6 weights, killed at iter 216 after confirming plateau
**Steps:** 7M

**Reward changes from Run 2:**
- Blind clear: 2.0 × (9-ante) → **1.0 × (9-ante)** (reduced survival pressure)
- Ante complete: 5.0 → **2.5**
- Win: 50.0 → **30.0** (less dominant, more balanced)
- Loss: -2.0 → **-1.0**
- Score progress: 0.05 → **0.02** (card_quality carries hand-level signal)
- Buy joker: +0.3 flat → **+1.5 × coherence_score** (new synergy reward)
- Anti-synergy penalty: new, -0.5 × (0.4 - synergy) when synergy < 0.4

**Synergy classification:** 164 jokers tagged by strategy direction (flush, straight, pairs, suits, face cards, etc.) and universal tags (scaling, economy, retrigger, generic, utility). Coherence score measures how well a candidate joker fits existing loadout.

**Results:**
- Reward stuck at ~18-20 from iter 50 through iter 216 (never climbed)
- Wins/iter: 22-31 (similar to Run 2)
- Intent distribution: P=55% D=30% C=15% (similar to Run 2)
- **Loadout coherence IMPROVED: 0.50 → 0.62** (synergy reward is shaping buys somewhat)
- **BUT Green+Space still dominant:** 44%/43% in wins (only slightly down from 47%/51%)
- Avg jokers in winning runs: 2.0 (down from 2.3 in Run 2)

**Diagnosis:**
Synergy signal was too weak relative to overall episode reward. Calculated post-hoc:
- Synergy contributes only 1-4.5 reward per episode (1-3 joker buys × 0.75-1.5 reward each)
- Card quality contributes 0-40 per episode
- Signal-to-noise ratio for synergy: ~5-15% of mean reward — borderline weak
- Agent has strong prior for Green+Space (universal tag jokers, always neutral 0.5 synergy), so synergy reward doesn't differentiate them from alternatives

**Key insight:** Per-event reward magnitude is less important than per-episode total contribution. A reward component needs to contribute ~15-25% of mean reward across an episode to reliably shape behavior. Synergy was ~5-15%, which produced drift (coherence up slightly) but not policy change.

**Lock-in mechanism identified:** Green Joker (scaling) and Space Joker (utility) have universal tags, not strategy tags. The coherence scorer treats them as always-neutral. This means:
- Green+Space → any new joker: synergy = 0.5 → +0.75 reward (no differentiation)
- Flush+Flush → third Flush joker: synergy = 1.0 → +1.5 reward (strong signal, but never explored)

The agent can't explore Flush builds because its current policy (Green+Space) gives "safe" neutral rewards for any buy, and deviating to a new strategy requires multiple steps of coordinated purchases with delayed payoff.

---

## Run 4 — Slot-Scaled Rewards (planned)

**Planned changes from Run 3:**

1. **Interest cap reduced $25 → $15.** Less incentive to hoard money, more pressure to spend on jokers.

2. **Empty slot penalty scales with ante.** Formula: `-0.3 × (ante - 1)` per empty slot when leaving shop.
   - Ante 1: 0 (cash-strapped, learning phase)
   - Ante 5: -1.2 per empty slot
   - Ante 8: -2.1 per empty slot
   - Late-game empty slots become actively costly (scales up to -6 to -15 per shop visit with 3 empty slots)

3. **Synergy reward scales with slot count.** Buying additional jokers gets increasing bonuses:
   - Slot 1: +1.5 × synergy
   - Slot 2: +1.5 × synergy
   - Slot 3: +2.0 × synergy
   - Slot 4: +2.5 × synergy
   - Slot 5: +3.0 × synergy
   
   Rewards filling slots beyond the "2 jokers is enough" pattern.

**Expected effect:**
- Late-game shops become urgent (empty slot penalty dominant)
- Filling slots 3-5 becomes increasingly valuable (+2.0-3.0 reward per buy)
- Agent should aim for 4-5 jokers by ante 4-5
- Per-episode synergy contribution should grow to 8-15 reward (up from 1-4.5)

**Success criteria:**
- Avg jokers in wins: 2.0 → 3.5+
- Loadout coherence: 0.62 → 0.75+
- Green+Space dominance: 44%/43% → <30%/<30%
- Win rate: 2% → 3-5%+

---

## Domain Insights (for Run 5)

### 1. Green/Space are legitimately S-tier, not agent bugs

Green Joker and Space Joker are strategy-agnostic multipliers. In real Balatro, expert
players also always buy them when seen. The issue isn't that the agent picks them up —
it's that the agent has ONLY this strategy. Its policy lacks branches for:
- Committing to a flush/straight/pair build when the right jokers appear
- Rerolling when no jokers match existing strategy
- Picking immediate-payoff jokers over scaling jokers in late game

### 2. Time value of scaling jokers

Scaling jokers (Green, Space, Ride the Bus, Ice Cream, Madness) have dramatically
different value depending on when purchased:

| Ante Bought | Green Joker Expected Value | Space Joker Expected Levels |
|:-:|:-:|:-:|
| 1 | +40-60 mult | 10+ levels |
| 3 | +25-40 mult | 5-7 levels |
| 5 | +15-25 mult | 2-4 levels |
| 7 | +5-10 mult | 0-1 levels |

A scaling joker bought at ante 7 is worth ~20% of one bought at ante 1. At ante 6+,
flat-payoff jokers (Stuntman, Cavendish, The Duo, x-mult jokers) give more value.

Run 4's synergy scorer doesn't account for this — the agent likely wastes money on
scaling jokers in late-game shops when it should be buying immediate payoff jokers.

### 3. Blueprint/Brainstorm are positional and the agent can't reorder

`game.jokers.append(j)` — jokers stay in purchase order forever. No move action exists.
- Blueprint copies joker to its RIGHT. Only useful if bought 2nd-to-last.
- Brainstorm copies LEFTMOST joker. Only useful if a strong joker was bought first.
- In practice, these are ~random noise for the agent.

Blueprint appears in only ~2% of winning V7 runs — because when present, it usually
copies a mediocre joker based on purchase order.

### 4. Sell-protection for accumulated scaling jokers

If the agent has had a scaling joker for 3+ antes, it has accumulated significant value
(e.g., Green Joker with +30 mult banked). Selling it for $3 is a huge blunder. The
current sell-blunder penalty (-0.5) doesn't account for accumulated value.

---

## Planned Run 5 Changes

1. **Scaling time decay in synergy score**
   - Add `SCALING_DECAY[ante]` factor to coherence_score for jokers tagged `scaling`
   - Green bought at ante 1: +0.75 reward (full)
   - Green bought at ante 6: +0.19 reward (decayed)

2. **Immediate vs scaling tag distinction**
   - New tags: `flat_payoff`, `x_mult_flat`
   - Late-game (ante 5+), these get synergy boost
   - Examples: Stuntman (flat_payoff), Cavendish (x_mult_flat), The Duo/Trio (x_mult_flat)

3. **Accumulated value sell-protection**
   - Track ante each joker was acquired
   - Selling scaling joker held >2 antes: -2.0 penalty (up from -0.5)
   - Teaches agent not to throw away accumulated mult

4. **Auto-optimize positional joker placement**
   Three positional jokers in sim: Blueprint, Brainstorm, Ceremonial Dagger.
   Agent has no move action — jokers stay in purchase order forever.

   - **Blueprint** (copies right): on purchase, place immediately left of strongest joker
   - **Brainstorm** (copies leftmost): on purchase, swap strongest joker into position 0, place Brainstorm elsewhere
   - **Ceremonial Dagger** (destroys right on blind select): IMPORTANT — don't let it destroy Green Joker!
     - If there's a weak joker, place Ceremonial just before it (destroys weak, scales mult)
     - If no weak joker, place Ceremonial at end (destroys nothing, still builds +2 mult on blind select)

   Joker strength measured by score_hand() with a canonical test hand, excluding positional jokers.
   Adds ~200ms per episode (10-20 purchases × 10-20ms each) — negligible.

   Expected impact: Blueprint/Brainstorm become meaningful wins (estimated 90%+ win rate when acquired
   in real Balatro). Currently these appear in only 2% of V7 wins because they're copying random jokers.

5. **Episode-end coherence bonus**
   - At game end, reward final loadout's coherence score × ante_reached
   - Formula: `+loadout_coherence × min(ante, 8) × 2.0`
   - Max: +16 for a perfect coherent build reaching ante 8
   - Teaches agent to maintain a coherent strategy throughout the run

6. **New joker tags (early-game / sacrificial / weak)**

   **Early-game only** (value decays with ante, similar to scaling):
   - `j_ceremonial` — needs disposable targets + time to scale mult
   - `j_gros_michel` — eventually gets destroyed, use early
   - `j_ice_cream` — decays -5 chips/hand
   - `j_popcorn` — decays -4 mult/round
   - `j_seltzer` — destroys itself after 10 hands
   - Scaling jokers already covered (green, space, ride_the_bus, square, lucky_cat)

   **Sacrificial** (should be SOLD at right moment, not held):
   - `j_luchador` — sell vs boss blind for disable
   - `j_diet_cola` — sell for free Double Tag
   - `j_invisible_joker` — sell (after 2 rounds) to duplicate a joker
   - Reward event on SELL at appropriate trigger (not on buy or hold)

   **Weak** (low synergy score, penalize as bad buys):
   - `j_egg` — just gains sell value, no effect
   - `j_credit_card` — only enables debt, not a payoff joker
   - `j_gift_card` — marginal value ($1 to shop items)

7. **Sell context awareness**

   Current sell-blunder penalty (-0.5) is too blunt. Make it context-aware:
   - Selling a scaling joker with high accumulated value (>20 mult banked): -2.0 penalty
   - Selling a sacrificial joker at right trigger moment: +1.0 reward
   - Selling a weak joker for upgrade to synergistic joker: -0.2 (acceptable)
   - Selling any joker with empty slots elsewhere: -0.5 (current default)

   Requires tracking joker acquisition ante + accumulated state.

## Key Data Finding: Sell Behavior Is Minimal (CORRECTED)

Earlier analysis incorrectly suggested Space Joker was being destroyed in 56% of wins.
Corrected analysis from 4556 recent winning runs:

**Sell/destruction patterns:**
- 75.5% of wins: agent never sold or lost any joker
- 19.0% of wins: one joker lost (sold or destroyed)
- 4.1% of wins: two jokers lost
- 1.4% of wins: three+ jokers lost

**Space Joker specifically:**
- In final loadout: 51.1% of wins
- Seen in plays at any point: 57.5% of wins
- Lost mid-run: **6.4%** of wins (not 56.5%)
  - 28% of those losses had a destroyer joker in the run (likely destroyed)
  - 72% had no destroyer (likely sold by the agent)

**Destroyer joker frequencies:**
- Ceremonial Dagger: 2.7% of wins
- Madness: 1.1% of wins
- Gros Michel: 2.2% of wins

**Implication:** Positional destruction is NOT the main problem. Since Green/Space are
typically bought first (position 0-1), Ceremonial Dagger (placed later) destroys the
joker to ITS right — a later purchase, not Green/Space. Auto-positioning is still useful
but not as impactful as first estimated.

**Real problem: The agent rarely sells.** 75% of wins involve zero joker turnover.
Expert Balatro play involves frequent sells (economy jokers after value extracted,
off-synergy jokers when better ones appear, sacrificial jokers at trigger moments).
Our agent treats every purchase as permanent.

## Sell-Reward System (Run 5 Addition)

Currently we have sell-blunder PENALTY (-0.5) but no sell-upgrade REWARD. The agent
avoids selling because it's always slightly discouraged.

**New sell rewards to add:**

1. **Sell-upgrade chain** — selling a joker to buy a better one in the same shop:
   `+0.5 × (new_synergy - old_synergy) × max_slot_bonus`
   Encourages replacing low-synergy jokers with high-synergy ones.

2. **Sacrificial joker used correctly** — selling at right trigger:
   - Luchador sold during boss blind phase: +2.0
   - Diet Cola sold anytime: +1.0 (free tag)
   - Invisible Joker sold after 2+ rounds of ownership: +2.0

3. **Economy joker sold after value extracted** — selling an economy joker past its peak:
   - Rocket sold at ante 4+: +0.5 (collected max money)
   - Business Card sold past ante 4: +0.3

4. **Late-game scaling-to-immediate swap** — selling scaling joker past ante 5 to buy
   an immediate-payoff joker: +1.0 (teaches time-value awareness)

5. **Weak joker sold for any reason**: +0.3 (Egg, Credit Card, Gift Card)

These rewards create positive signal for smart selling, not just penalty for bad selling.

---

## Run 5 — All 8 Changes Applied (FINAL)

**Config:** V6 migration, 1000 iterations, ~32.8M steps, all 8 Run 5 design changes implemented.

**Changes implemented:**
1. Ante-aware synergy score (scaling decay + immediate-payoff boost)
2. Auto-position positional jokers (Blueprint/Brainstorm/Ceremonial)
3. Accumulated value sell-protection (-2.0 for selling scaling joker held 3+ antes)
4. Sell-reward system (sacrificial +2.0, weak +0.3, late-scaling-swap +1.0)
5. Episode-end coherence bonus (max +16: coherence × ante × 2.0)
6. New joker tags: early_game, immediate_payoff, sacrificial, weak, positional
7. Sell context awareness (different rewards per scenario)
8. Carried forward Run 4: slot-scaled synergy + ante-scaled empty slot penalty + interest cap $15

**Results:**
- 36,599 wins / 1,764,540 episodes = **2.07% win rate**
- Last 50 iters: 2.20%
- Best ante: 9

**What worked:**
- **Slot-filling: massive success.** 96% of winning runs now have full 5 jokers (up from ~25% in Run 4).
  Avg jokers in wins: 4.90 (up from 4.0 in Run 4).
- **Supporting joker diversity doubled.** Top 15 jokers (after Green/Space) now appear at 4-6% each
  (vs 2-3% in Run 4). Strategy-specific jokers like Even Steven, Crazy, Wrathful Mult, Scholar
  visible at 4% each.
- **Brainstorm usage up.** 3.6% of wins (vs 1-2% in Run 4) — auto-positioning helping.

**What didn't work:**
- **Win rate barely moved.** 2.35% (Run 4 last 50) → 2.20% (Run 5 last 50) — slightly worse.
- **Coherence dropped slightly.** 0.65 → 0.63. Agent fills slots but with random jokers, not
  coherent strategy-aligned jokers.
- **Green+Space still dominant.** 51%/51% in winning loadouts — no change. Ante-aware scaling
  decay didn't meaningfully reduce their use.
- **Blueprint nearly absent.** 0.2% of wins — auto-positioning works but Blueprint doesn't appear
  often enough in shops to matter.

**Diagnosis:**
We successfully pushed the agent to BUY more jokers, but didn't push it to BUILD COHERENT
strategies. Filling slots with random scaling jokers is better than empty slots, but worse than
focused Flush/Pairs/Straight builds. Episode-end coherence bonus (max +16) is too weak — the
slot-filling reward incentives dominate.

**Key insight:** The agent has no in-game pressure to commit to a build direction. Coherence
reward fires once at episode end, while slot-filling rewards fire on every shop visit. The
in-game signal pushes "buy any joker" while the episode-end signal whispers "build coherently."
The in-game signal wins.

---

## Planned Run 6 Changes — Coherence Amplification

The Run 5 results show we need MUCH stronger coherence pressure throughout the game,
not just at episode end.

1. **Per-blind coherence bonus**
   - On every blind cleared, add `loadout_coherence × 1.5` reward
   - Max contribution: 24 blinds × 1.5 × 1.0 = +36 per perfect run
   - Provides ongoing in-game signal that coherence matters

2. **Boost episode-end coherence bonus 3x**
   - From `coherence × ante × 2.0` (max +16) to `coherence × ante × 6.0` (max +48)
   - Makes final coherence the single largest end-of-game signal

3. **Penalize incoherent buys harder**
   - Anti-synergy threshold raised from 0.4 to 0.5
   - Any synergy below 0.5 (i.e. sub-neutral) gets penalized
   - Penalty coefficient doubled: -1.0 instead of -0.5

4. **Reduce neutral synergy reward**
   - Currently neutral (0.5) gives +0.75 reward (50% of max)
   - Cap neutral reward at +0.4 (about 27% of max)
   - Creates bigger gap between "great fit" and "any fit"

5. **Track running coherence in obs (optional)**
   - Add 1 obs feature for current loadout coherence
   - Lets agent reason about its own build direction

The goal is to make the agent FEEL the coherence pressure on every shop visit, not just
at game end. If the agent has 3 Flush jokers and sees Green Joker, the coherence-aware
reward should make it think twice — Green is universally good but it dilutes the build.

---

## Run 6 — Amplified Coherence (FINAL)

**Config:** V6 migration, 1000 iters, 32.8M steps. All Run 5 changes + 5 coherence amplification changes.

**Changes from Run 5:**
1. Per-blind coherence bonus: `coherence × 1.5` on every blind cleared (new)
2. Episode-end coherence 3x stronger: `coherence × ante × 6.0` (max +48)
3. Anti-synergy threshold raised: 0.4 → 0.5
4. Anti-synergy penalty doubled: -0.5 → -1.0
5. Neutral synergy reward capped (sub-neutral buys × 0.75 multiplier)

**Results:**
- 37,343 wins / 1,804,827 eps = **2.07% win rate** (same as Run 5)
- Last 50 iters: 2.23% (slightly better than Run 5's 2.20%)
- Best ante: 9
- Avg reward: 25.4 (higher than Run 5's 22 — agent IS collecting coherence bonuses)

**What happened — the coherence paradox:**

The amplified coherence rewards caused the agent to **reduce diversity**, not increase it:

| Metric | Run 5 | **Run 6** | Change |
|:-:|:-:|:-:|:-:|
| Avg jokers in wins | 4.90 | **3.33** | -32% |
| 5-joker loadouts | 96% | ~35% | -60pp |
| Avg coherence | 0.63 | **0.58** | -8% |
| Green Joker % | 51% | 50.5% | same |
| Space Joker % | 51% | 50.2% | same |
| Win rate | 2.07% | 2.07% | same |

**The agent gamed the coherence reward:**
- Buying more jokers → more chances for sub-coherent buys (now penalized -1.0)
- Buying fewer jokers → fewer coherence penalties, get neutral rewards safely
- Green + Space only → neutral coherence, no penalties, still get Green+Space win rate

The strong anti-synergy penalty created a perverse incentive: **do less to get penalized less.**

**Key insight:** Making coherence a bigger reward didn't help because:
1. The agent can't discover coherent builds through random exploration (need specific joker combinations)
2. Penalties for failed coherence attempts outweigh the potential rewards
3. The "safe" strategy (Green+Space only, no diversity) avoids penalty AND gets the baseline 2% win rate
4. PPO chose the safe path every time

## Run 7 — Network Scaling Experiment (5x capacity + 64k batch) — **KILLED at iter 184**

**Hypothesis:** Is the V7 ~2% ceiling a *capacity* limit (network too small to represent
conditional strategies) or a *reward-shaping* limit (PPO can't discover multi-step
strategies regardless of size)?

**Config:**
- Network: 13.6M params (hidden=1024, 8 res blocks — 5.5x baseline V7's 2.48M)
- Batch: 64k steps/iter (20 workers × 3200 steps, vs baseline 32k)
- LR: 1.5e-4 (lowered from 3e-4 for the bigger model)
- Fresh from scratch, no migration
- Checkpoints every 10 iters

**Run stats (184 iters, ~11.6M steps, ~6 hours wall clock):**

| Iter | Reward | Wins/Eps | WR | Best Ante | Notes |
|:-:|:-:|:-:|:-:|:-:|---|
| 1-10 | 17.4 | 9 / 43,147 | 0.02% | 9 | Warm-up, reached ante 9 by iter 7 |
| 20-30 | **24.9 (peak)** | 74 / 39,295 | **0.19%** | 9 | Brief peak, then plateau |
| 130-184 | 21.5 | 286 / 184,037 | 0.16% | 9 | Drift down, no further learning |
| Overall | 21.85 | 995 / 679,680 | 0.15% | 9 | — |

**Observations:**
- Same "early peak then decay" shape as V7 Run 4 at comparable iter count, but lower WR
- Iter time ~112-120s (vs ~35s baseline) — 3.5x slower despite 2x batch
- Entropy collapsed similarly to baseline (intent_entropy 0.5-0.6 by iter 150)
- Bigger network did NOT reach higher ante or discover new strategies — same ante 9 ceiling
- Last-50 WR of 0.16% is *below* V7 Run 4's 2.35% at equivalent training progress

**Decision to kill at iter 184:**

The curve shape after 6 hours mirrored V7 Run 4's shape at the same training step count —
same plateau pattern, no evidence of breakthrough. Continuing to 1000 iters (~36 more
hours) would likely reproduce V7 Run 4's ~2% ceiling with a more expensive model.

**Verdict: The plateau is structural, not a capacity limit.**

5.5x more parameters + 2x larger batch did NOT break the ceiling. This is strong
evidence that the reward-shaping regime (V7's hand-crafted scores) can only push PPO
to a specific behavioral basin — one that happens to top out around 2% — regardless
of how much network capacity is available. To discover qualitatively new strategies
(conditional builds, multi-shop planning, joker positioning) we need a different
**search mechanism**, not a bigger function approximator.

**Project-concluding takeaway:** For long-horizon games like Balatro where winning
requires coordinated multi-step strategies, shaped-reward PPO appears capacity-
insensitive past a threshold. The next meaningful axis is *search* (MCTS, planning,
or explicit exploration over strategy-level decisions) rather than *scale*.

---

## Cross-Run Summary

| Run | Overall WR | Last 50 WR | Avg Jokers | Coherence | Signature Finding |
|-----|:-:|:-:|:-:|:-:|---|
| Run 1 | 0.0007% | — | — | — | Card selection without reward signal = random |
| Run 2 | 1.98% | 1.98% | 2.3 | 0.50 | Card quality reward brought wins back |
| Run 3 | 1.80% | 1.80% | 2.0 | 0.62 | Synergy reward too weak, plateaued |
| Run 4 | 2.00% | 2.35% | 4.0 | 0.65 | Slot-scaled rewards + ante penalty worked |
| Run 5 | 2.07% | 2.20% | 4.90 | 0.63 | Slot filling succeeded, win rate plateaued |
| Run 6 | 2.07% | 2.23% | 3.33 | 0.58 | Coherence amplification BACKFIRED |
| Run 7 | 0.15% (killed @184) | 0.16% | — | — | **5.5x network did not break ceiling** |

## The Plateau — Why V7 Ends at ~2%

After 6 runs of reward shaping, we consistently land at 2.0-2.35% win rate. The agent
learned to:
- Play good hands (card quality reward)
- Use discards strategically (28-32% of SELECTING_HAND actions)
- Fill joker slots when pressured (Run 4/5)
- Buy coherent jokers slightly more often (Run 3 onward)

But it never learned:
- Conditional strategy (Flush build vs Pair build vs Straight build)
- Long-horizon planning (multi-purchase strategies)
- When to deviate from Green+Space based on shop availability

**The fundamental issue:** PPO with reward shaping can't discover specific multi-step
strategies. Green+Space gives consistent ~2% win rate; specific builds need coordinated
purchases across multiple shops that the agent never explores because single-step
exploration can't find them.

## Recommended Next Steps (V8 / Future Work)

1. **Curriculum learning** — Disable Green+Space for first 500k steps, force discovery of
   alternative strategies. Then re-enable and let agent combine.
2. **Population-based training** — Multiple agents with different reward weights, periodic
   selection and crossover.
3. **Search-guided imitation** — Monte Carlo search to find winning strategies per game,
   supervise the policy on those decisions.
4. **Joker positioning action** — Add explicit move_joker actions so Blueprint/Brainstorm
   can be used strategically by the agent.
5. **Larger network** — 2.5M params might be too small for conditional strategy. Try 10M+.

---

## V8 Design Plan — Self-Play with Specialist Population

Based on the Balatro multiplayer mod mechanics (both players on same seed, PvP blind,
4 lives), self-play addresses the core V7 problem directly: the agent can't discover
multi-step coordinated strategies through single-agent exploration.

### Core Insight

Same-seed comparison gives much stronger gradient signal than averaged rewards.
If Agent A plays seed 42 with Green+Space and dies at ante 5, and Agent B plays
the same seed with a Flush build and dies at ante 7, PPO gets a clear differential:
**Flush build was strictly better on this specific game state.** Our current
averaged-reward signal buries this information in noise.

Additionally, the PvP blind mechanic favors burst scoring (single-hand max score)
rather than long-horizon scaling. This shifts optimal strategy away from Green+Space
(scaling) toward x-mult/Flush/specific synergy builds. Self-play might naturally
break the lock-in.

### Diversity Mechanism: Specialist Population + Hall of Fame

**The collapse problem:** Two copies of the same policy with same rewards and entropy
will move in lockstep and converge to identical strategies. Self-play without
explicit diversity gives single-agent training with extra steps.

**Solution:** Population of 5 policies with differentiated reward shaping:

```
Population composition:
  - "Generalist"       : V6 warm start, standard V7 rewards, entropy 0.05
  - "Flush specialist" : +2x reward for Flush hand types, entropy 0.08
  - "Pairs specialist" : +2x reward for Pair/Two Pair/Full House, entropy 0.08
  - "Face specialist"  : +2x reward for face_cards synergy jokers, entropy 0.08
  - "Economy special"  : +2x reward for economy jokers, entropy 0.10

Training procedure:
  - Each iteration: all 5 policies play the same 500 seeds
  - Per-seed advantage = policy's score - median(all policies on that seed)
  - Every 50 iterations: save snapshots to Hall of Fame
  - Every 100 iterations: mix in Hall of Fame opponents for comparison

Why each element matters:
  - Reward diversity: prevents collapse (specialists stay specialists)
  - Same seeds: enables direct strategy comparison (strong gradient signal)
  - Population median baseline: clean relative performance signal
  - Hall of Fame: prevents catastrophic forgetting of past strategies
  - Entropy differences: fine-grained exploration variation
```

### Distillation Step

After population training, distill specialists into one general policy:
1. Generate huge dataset of (state, action) pairs where each state records which
   policy won on that state
2. Train a fresh policy to imitate the winning policy's action for each state
3. Fine-tune with standard PPO

Result: a single agent that plays Flush strategy when flush jokers appear, Pair
strategy when pair jokers appear, etc. — the **conditional strategy tree we've
been unable to build with single-agent training**.

### Implementation Phases

**Phase 1: Shadow play (easier to prototype)**
- No multiplayer mod mechanics — train 5 policies in parallel with reward variations
- All policies see same seed set each iteration
- Compare scores across policies for same-seed gradient signal
- Validate that population diversity holds and specialists emerge
- Estimated effort: 500 lines of training script changes

**Phase 2: Full multiplayer sim (if Phase 1 shows promise)**
- Implement PvP blind mechanic (both agents play same seed, compare scores)
- Lives system (4 per player, spendable on regular or PvP blinds)
- Shared seed state for shops (both players see same shop items)
- Turn-taking or parallel play logic
- Estimated effort: 200-400 lines of sim code

**Phase 3: Burst specialization (if PvP breaks lock-in)**
- Analyze what strategies emerge in PvP vs solo
- Potentially separate policy heads for "building mode" and "PvP mode"
- Conditional strategy activation based on current blind type

### Expected Results

- If PvP burst pressure shifts optimal strategy away from Green+Space: **10-20% win rate** likely
- If PvP doesn't meaningfully shift strategy: **3-5% win rate** (modest gains from population diversity alone)
- Primary success criterion: emergence of distinct winning strategies across population
  (Flush builds, Pair builds, etc. each winning their share of games)

### Alternative Diversity Techniques Considered

| Technique | Pros | Cons |
|-----------|------|------|
| Hall of Fame alone | Simple, prevents forgetting | Mostly trains vs weak past selves |
| Reward diversity | Forces specialization | Specialists may not generalize |
| Entropy diversity | Explicit explore/exploit balance | Wastes compute on high-entropy policies |
| Diversity regularization | Mathematical guarantee | Can produce nonsensical differences |
| Asymmetric initialization | Free diversity | Diminishes with training time |

The combination recommended above (reward diversity + Hall of Fame + population median)
is chosen because it attacks the specific V7 failure mode: inability to explore
multi-step strategies. Each specialist is FORCED by its reward to explore a specific
strategy, and Hall of Fame preserves that diversity against drift.
