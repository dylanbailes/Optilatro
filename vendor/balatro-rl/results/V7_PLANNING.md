# V7 Planning — Strategic Card Selection and Long-Horizon Decision Making

*Written 2026-04-09. Captures everything learned from V1-V6 to inform the V7 architecture.*

---

## What We Know Works

1. **Python sim is fast and accurate** — 1,800 sps, 164 jokers implemented and audited,
   all boss blinds, full consumable/voucher systems. 504 tests passing.

2. **Single-agent PPO > dual-agent** — V5's play/shop split created irreconcilable data
   imbalance. The single agent naturally handles credit assignment across play and shop.

3. **Combo ranking for play** — evaluating all card subsets and ranking by score is correct
   for "what's the best play RIGHT NOW." The agent reaches ante 9 by always picking the
   best combo.

4. **Heuristic reward shaping helps bootstrap** — buy-joker bonus, sell-blunder penalty,
   excess-money penalty all gave the agent useful signal early in training.

5. **Random seeds prevent memorization** — essential for generalization.

6. **Boss blind restrictions need special handling** — bl_mouth/bl_eye infinite loops taught
   us that game mechanics edge cases can silently break training.

## What Doesn't Work

1. **Pre-ranked combos as the action space** — The agent converges to "always play action 0"
   within 50 iterations. This removes all card selection learning. The combo ranker IS the
   policy, and PPO just learns to trust it.

2. **Single-card discards** — Actions 20-27 (discard card i) are never used meaningfully
   because the agent can't plan multi-card discards or reason about draw probabilities.

3. **Greedy play** — The combo ranker optimizes for THIS hand, not the game trajectory.
   Playing a Full House when a Pair would clear the blind wastes a strong hand. Overkilling
   wastes resources that could matter later.

4. **Local reward shaping for shop** — Buy-joker bonuses help but can't replace actual
   understanding of joker synergies and long-term deck building strategy.

5. **Entropy management** — Play entropy collapses because action 0 is genuinely dominant.
   Entropy floors fight the gradient and degrade performance. The action space itself needs
   to present real choices, not one dominant option.

## The Ceiling: 2% Win Rate

V6's 2% win rate breaks down as:
- **80% die at ante 1** — mostly on boss blind (600 chips, 4 hands, no jokers)
- **18% reach ante 2-4** — cleared ante 1 with lucky draws but can't sustain
- **2% reach ante 9** — found Green Joker + Space Joker scaling combo

The 80% ante 1 death rate is the primary bottleneck. A human player survives ante 1 ~95%+
of the time by discarding intelligently. The agent can't discard, so it's at the mercy of
the initial hand draw.

---

## The Real Challenge (AlphaGo Parallel)

Balatro is NOT primarily a combinatorial search problem like Go. The per-hand card
selection is bounded (218 subsets of 8 cards). The real challenges are:

### 1. Multi-Round Planning
A joker bought in ante 1 pays off in ante 5. A planet card used in ante 2 compounds
through ante 8. The agent needs to reason about investment vs immediate reward across
24+ blinds. PPO with GAE(lambda=0.95) can handle ~50-step dependencies, but key decisions
are 200+ steps apart.

### 2. Conditional Strategy
Good play depends on your joker loadout, which changes every game:
- "I have Flush jokers → discard non-suited cards → play Flushes"
- "I have scaling mult jokers → play many hands → let mult accumulate"
- "I have no jokers → play highest raw score combos → hope to survive"

The agent needs to learn POLICIES CONDITIONED ON GAME STATE, not a single fixed policy.

### 3. "Just Enough" vs Greedy
The optimal play often ISN'T the highest-scoring combo. If the blind needs 300 chips:
- Playing a Pair (60) + Pair (60) + Pair (60) + Three of a Kind (180) = 360 (cleared, used all 4 hands)
- Playing a Full House (336) = cleared in 1 hand, 3 hands saved for payout ($3)
- But: playing the Full House wastes cards that could be used after discarding for a better position

The right play depends on: remaining blind targets this ante, hands remaining, discards
remaining, deck composition, joker effects per hand played. This is contextual optimization
that pure greedy scoring can't capture.

### 4. Deck Building (the meta-game)
Expert Balatro play involves intentionally modifying the deck:
- Thin the deck (remove low cards) so you draw your good cards more often
- Convert suits (Star tarot → all Diamonds for Flush builds)
- Add enhanced/sealed cards for bonus effects
- Planet cards to level up your primary hand type

This spans the entire run and requires a "plan" that persists across shop visits.

---

## Approaches Considered for V7

### A. Card Scoring Head (practical, medium ceiling)

Add an 8-dim output head to the network that scores each card. Actions become "play top N"
or "discard bottom N." The network learns card valuation contextually.

**Pros:** Small action space, single forward pass, differentiable
**Cons:** Can't express "keep cards 0 and 5 but discard 1,2,3,4,6,7" — only ranks cards
linearly. May converge to same greedy-best-combo behavior.

### B. Multi-Binary Selection (most flexible, hardest to train)

Agent outputs 8 independent keep/discard bits. Any combination possible.

**Pros:** Maximum expressiveness — any card combination
**Cons:** PPO handles multi-binary poorly (each bit is independent, hard to coordinate).
Exploration is random bit flipping. Very slow to learn card synergies.

### C. Autoregressive Selection (most human-like, slowest)

Agent selects cards one at a time across multiple env steps. Toggle card → toggle card →
play/discard.

**Pros:** Exactly matches human interaction. Each step is a simple choice.
**Cons:** 3-6 env steps per game decision. Credit assignment across selection steps is hard.
Very slow training — 3-6x more steps needed per game.

### D. Search-Guided Policy (AlphaGo-style, most powerful)

Use Monte Carlo sim to evaluate discard options at each decision point. Train network to
approximate the search results (policy distillation). Then RL to go beyond search.

**Pros:** Near-optimal card play from day 1. Network learns from strong signal.
**Cons:** Search is greedy per-hand (can't plan across rounds). Expensive to generate
training data at scale. The hard part (shop/deck building) isn't addressed by search.

### E. Hierarchical Decision (hybrid, potentially best balance)

Split the decision into two levels:
1. **Strategic intent** (discrete action): "play for score", "discard to improve",
   "play just enough", "discard to thin deck", "play to trigger joker effects"
2. **Card selection** (learned head): given the intent, score cards appropriately

The intent shapes what the card scorer optimizes for. "Play for score" ranks by raw chips.
"Discard to improve" ranks by replacement potential. "Play just enough" finds the minimum
hand that clears the blind.

**Pros:** Separates strategy from tactics. Intent is a small discrete space (trainable).
Card selection is continuous (expressive). The agent can learn "when to be greedy vs
conservative" as a high-level decision.
**Cons:** More complex architecture. Intent labels need careful design. Two heads to train.

---

## Approach Rankings

### By Ceiling (how high can it go?)

| Rank | Approach | Estimated Ceiling | Why |
|:---:|----------|:-:|---|
| 1 | E. Hierarchical | 30%+ | Separates strategy from tactics — can express "play just enough", "discard to improve", "thin deck." Intent layer learns WHEN, card scorer learns WHAT. |
| 2 | D. Search-Guided | 20-30% | Near-optimal per-hand play, but greedy. Can't plan across rounds without additional planning layer. Strong floor but needs RL to reach ceiling. |
| 3 | A. Card Scoring | 5-10% | Learns contextual card valuation but linear ranking can't express "keep these specific non-adjacent cards." Will converge to greedy-best again. |
| 4 | C. Autoregressive | 15-25% | Can express any selection in theory, but multi-step credit assignment limits what PPO can actually learn. Ceiling exists but reaching it is impractical. |
| 5 | B. Multi-Binary | 3-5% | 8 independent decisions can't coordinate. Exploration is random bit-flipping. Barely better than current combo ranker. |

### By Development Difficulty (build + train + debug)

| Rank | Approach | Difficulty | Why |
|:---:|----------|:-:|---|
| 1 (easiest) | A. Card Scoring | Low | One linear head, small action space change. 1-2 day build. |
| 2 | B. Multi-Binary | Low | 8 sigmoid outputs, simple. But debugging poor coordination is frustrating. |
| 3 | D. Search-Guided | Medium | Search is straightforward (sim is fast). Distillation + RL pipeline is real plumbing work. |
| 4 | E. Hierarchical | Medium-High | Two heads, intent label design, coordination. Most design thinking upfront. Implementation is moderate once design is solid. |
| 5 (hardest) | C. Autoregressive | High | Multi-step env changes, 3-6x training time, debugging which selection step caused a loss. |

### Combined Ranking (ceiling × feasibility)

| Rank | Approach | Rationale |
|:---:|----------|-----------|
| **1** | **E. Hierarchical** | Best ceiling-to-difficulty ratio. The extra design work is front-loaded — once the intent labels and architecture are right, training is standard PPO. The hard problems (conditional strategy, just-enough play) are directly addressed by the intent layer. |
| 2 | D. Search-Guided | Strong floor from search, good ceiling with RL. But search is greedy per-hand and can't solve the real problem (shop/deck building). Best as a complement to E, not a replacement. |
| 3 | A. Card Scoring | Easy to build but low ceiling. Would validate that learned card selection works at all, but the linear scoring head would be thrown away when building E — it needs conditional rankings that A can't provide. |
| 4 | C. Autoregressive | Theoretically expressive but practically painful. The 3-6x training slowdown and credit assignment across selection steps make it a poor fit for PPO. |
| 5 | B. Multi-Binary | Wrong paradigm. Independent binary decisions can't learn coordinated card selection. |

### Decision: Go Straight to E

Considered building A first as a stepping stone, but the gains don't transfer:
- A's card scorer learns one fixed valuation per card
- E needs conditional valuations that change based on intent ("when playing for score, card 3 is best; when discarding to improve, card 7 is the keeper")
- A's scorer would be thrown away and rebuilt for E
- The only real gain from A would be confirming gradient flow through a card scoring head, which we can validate within E directly
- Building A first delays confronting the real design problems (intent labels, head coordination) that E must solve regardless

**Go straight to E. The extra complexity is in the design, not the implementation.**

---

## What V7 Should Prioritize

Based on everything we've learned, the highest-impact changes are:

### Priority 1: Survive Ante 1 (the 80% bottleneck)

The agent dies at ante 1 because it can't discard. ANY discard mechanism that lets the
agent turn a bad hand into a decent hand will dramatically improve survival. Even a simple
"discard worst 3 cards, draw new ones" action would help.

This doesn't need a sophisticated architecture — just the ability to discard and the
observation features to make informed discard decisions (suit counts, rank pairs, deck
composition).

### Priority 2: Conditional Strategy (joker-aware play)

The agent needs to change its play style based on its joker loadout. This requires:
- Obs features that encode joker-hand synergies
- An action space that presents genuinely different options (not 20 variants of "best combo")
- Enough training diversity that the agent sees many joker configurations

### Priority 3: Shop Strategy (the meta-game)

This is the hardest problem and the one where 2% → 30% win rate actually lives. The agent
needs to learn deck building, joker synergies, and long-term planning. This might require:
- Larger networks with more capacity for strategic reasoning
- Attention mechanisms over joker slots and shop items
- Much longer training (millions of iterations)
- Potentially MCTS or planning-based approaches for shop decisions

---

## Open Questions

1. **Can PPO learn multi-round strategy at all?** The credit assignment gap (buy joker at
   step 50, payoff at step 400) may be fundamentally too long for GAE. Alternatives:
   hindsight experience replay, auxiliary value heads per-phase, or reward decomposition.

2. **Should the search oracle be used at all?** It's greedy but could provide a useful
   floor. Supervised pretraining on oracle decisions → RL fine-tuning is a proven recipe.
   But the user correctly notes that the oracle can't solve the real problem (shop strategy).

3. **Is the network big enough?** 2.3M params with 4 residual blocks may not have capacity
   for conditional strategy. AlphaGo used 13-layer networks with 192 filters. We might
   need more depth and width, especially if adding card scoring heads.

4. **How much of the problem is observation vs architecture?** The agent might already have
   enough information to play well — it just can't express the right actions. Or it might
   be missing critical obs features (joker synergy scores, expected hand improvements,
   blind-clear probability). Hard to know without testing.

5. **Is curriculum learning the key?** Start with easy blinds (ante 1 only, reduced
   targets), let the agent learn basic card play and shop strategy, then gradually
   increase difficulty. This avoids the 80% early-death problem that prevents shop learning.

---

## Recommended V7 Starting Point

Start with the **simplest change that breaks the 80% ante 1 death rate**:

1. Add a handful of discard actions (3-5) with hand-potential obs features
2. Keep the combo ranker for play actions
3. Train with curriculum (reduced ante 1 targets initially)
4. See if survival rate improves enough for the agent to learn shop strategy

If this works, iterate toward more sophisticated card selection. If it doesn't, the problem
is deeper than card selection and we need to rethink the approach (planning, search,
hierarchical RL, etc.).

---

## Version History Summary

| Version | Architecture | Peak Win Rate | Key Learning |
|---------|-------------|---------------|-------------|
| V1 | File IPC, SB3 | <0.01% | Proof of concept |
| V2 | File IPC, Ray | <0.01% | Parallelism works |
| V3 | Socket IPC, custom PPO | <0.01% | RAM kills live game training |
| V4 | Python sim, single agent | 0.47% | Sim works, combo ranking helps |
| V5 | Dual agent (play + shop) | 0% | Shop starvation is structural |
| V6 | Single agent, enhanced obs | 2.0% | Sim accuracy matters, combo ranking is ceiling |
| V7 | TBD | Target: 30% | Strategic card selection + long-horizon planning |
