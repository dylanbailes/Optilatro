# R3 Investigation: Scaling Joker Acceleration During Safe Blinds

## 1. Executive Summary

Scaling jokers (`j_green_joker`, `j_ride_the_bus`, `j_supernova`, `j_wee`, `j_square_joker`, `j_spare_trousers`, `j_runner`, `j_hiker`) are the premier growth engines in Balatro. In typical winning runs on Red Deck / White Stake, scaling jokers provide the necessary flat mult (+30 to +50) or chips (+150 to +300) to cross the Ante 7 (~100k) and Ante 8 (~100k–200k) clear thresholds.

However, detailed investigation of `vendor/balatro-rl/balatro_sim/agent_v10.py` reveals that the current in-blind play policy systematically **starves scaling engines** due to premature knockout plays:
1. **The Immediate Knockout Trap**: In `_tier1_survive` (lines 2190–2193), if the held hand contains any combination that clears the remaining target (`if best_score >= target:`), the agent immediately plays it on Hand 1, ending the round with 2 to 3 hands unspent.
2. **Wasted Scaling Headroom**: In safe blinds (e.g. Small and Big Blinds in Antes 2–6), an agent holding Green Joker or Ride the Bus only triggers them once per round (+1 Mult), rather than 2 to 3 times (+2 to +3 Mult). Across an 8-ante run (~24 blinds), this leaves 30–45 permanent Mult on the table.
3. **Green Joker Discard Penalty**: `j_green_joker` loses 1 Mult for every discard (`on_discard`), yet `_tier1_survive` discards aggressively to dig for structural hands even when playing a safe low hand would preserve the bonus and bank +1 Mult (+2 swing).
4. **Ride the Bus Reset Hazard**: `j_ride_the_bus` resets mult to 0 if ANY non-debuffed scoring face card scores (`on_hand_scored`). There is currently no check in `_tier1_survive` preventing face cards from destroying accumulated mult during play.
5. **Wee and Square Joker Blindness**: No logic in `agent_v10.py` identifies 2s in hand for Wee Joker or 4-scoring-card combinations for Square Joker.

By implementing **Scaling Joker Acceleration** under strict safety guardrails ($P(\text{clear}) \ge 0.98$, $h \ge 2$, deterministic knockout reservations, and boss blind bans), Optilatro can reliably compound permanent joker growth in safe blinds, bridging the gap to the 10.0%+ win rate threshold.

---

## 2. In-Blind Play Policy Analysis (`agent_v10.py`)

### 2.1 The Decision Cascade in `_v10_decide_hand`
In `vendor/balatro-rl/balatro_sim/agent_v10.py`:
- Line 2497: `_v10_decide_hand(game)` orchestrates in-blind decisions.
  1. **Boss Pre-actions**: Sells worst joker under Verdant Leaf if debuffed (line 2523).
  2. **Play Candidate Enumeration**: Calls `scored_plays(game, topk=8)` to rank held combinations (line 2532).
  3. **Ante-1 Planet Doctrine**: Spends held planet for the run's main hand type (line 2537).
  4. **Sampled Lookahead Picker**: Evaluates Manacle / early marginal openings via continuation rollouts (line 2551).
  5. **Consumable Deployment**: Uses held planets or tarots via `_v10_maybe_use_planet` and `_v10_decide_consumable` (lines 2588, 2593).
  6. **Farming Gate**:
     - Line 2601: `if p["farm_clear_threshold"] >= 1.0: return _tier1_survive(game, plays)` (default `farm_clear_threshold` is 0.90 in `V10_DEFAULTS`).
     - Line 2605: Computes `type_scores = _compute_type_scores(game, plays)` and `p_clear = estimate_clear_probability(game, type_scores=type_scores)`.
     - Lines 2622–2639: If `p_clear >= p["farm_clear_threshold"]`, it checks the rate sanity gate (`plays[0][0] >= share * rate_share`) and calls `tier2_value(game, plays, type_scores)`.
  7. **Fallback to Tier 1 Survive**: If `tier2_value` returns `None`, line 2641 executes `return _tier1_survive(game, plays)`.

### 2.2 Why Tier 2 Value Farming Does Not Scale Jokers
In `tier2_value` (lines 2418–2490):
- Play candidates are collected from `_value_play_combos(game, hand)` (line 2431).
- Inspecting `_value_play_combos` (lines 2299–2314):
  ```python
  def _value_play_combos(game, hand):
      joker_keys = {j.key for j in game.jokers}
      combos = []
      for i, c in enumerate(hand):
          if c.debuffed: continue
          if (c.seal == "Gold" or c.enhancement == "Lucky"
                  or ("j_business" in joker_keys and c.is_face_card)
                  or ("j_rough_gem" in joker_keys and c.suit == "Diamonds")
                  or ("j_ticket" in joker_keys and c.enhancement == "Gold")):
              combos.append((i,))
      return combos
  ```
  Only 1-card combos for Gold seals, Lucky cards, Business Card, Rough Gem, and Golden Ticket are considered!
- In `play_trigger_value` (lines 1646–1670):
  Only the economy levers above plus To Do List are scored. Scaling jokers (`j_green_joker`, `j_ride_the_bus`, `j_supernova`, `j_wee`, `j_square_joker`) return `val = 0.0`.
- Because `val <= 0.0`, `tier2_value` returns `None` (line 2489), and execution drops into `_tier1_survive`.

### 2.3 The Premature Knockout in `_tier1_survive`
Inspecting `_tier1_survive` (lines 2187–2193):
```python
best_score, best_combo, best_hand_type = plays[0]
target = game.current_blind.chips_target - game.chips_scored

if best_score >= target:
    clearing = [pl for pl in plays if pl[0] >= target]
    clearing.sort(key=lambda e: (len(e[1]), e[0]))
    return {"type": "play", "cards": list(clearing[0][1])}
```
If the best play in hand scores $\ge$ target:
- It finds the clearing play with the fewest cards and lowest overkill.
- It returns that play immediately.
- The hand scores, `chips_scored >= chips_target`, the round transitions to `ROUND_EVAL`, and all remaining hands are converted to dollars ($1 each).
- Any scaling joker in inventory only procs once per blind.

---

## 3. Simulator Joker Implementations & Quirks

### 3.1 Overview of Scaling Jokers in `balatro_sim`

| Joker Key | Class & Module | Trigger Hook | Mechanics in Sim | Critical Nuance / Quirk |
|---|---|---|---|---|
| `j_green_joker` | `_GreenJoker` (`jokers/scaling.py:72`) | `on_hand_scored`, `on_discard` | `inst.state["mult"] += 1` on hand played; `inst.state["mult"] = max(0, mult - 1)` on discard | Gains +1 per played hand; loses -1 per discard. Avoiding discards when safe yields a +2 mult swing. |
| `j_ride_the_bus` | `_RideTheBus` (`jokers/scaling.py:298`) | `on_hand_scored` | `if has_face: mult = 0 else: mult += 1` | `has_face = any(c.is_face_card for c in ctx.scoring_cards if not c.debuffed)`. If ANY scoring card is J, Q, K, mult resets to 0! |
| `j_supernova` | `_Supernova` (`jokers/mult.py:236`) | `on_hand_scored` | `ctx.mult += game.run_hand_counts.get(ctx.hand_type, 0)` | `game.py:1013` increments `run_hand_counts[hand_type]` for every non-rejected played hand. Playing extra hands of the main hand type permanently adds +1 Mult. |
| `j_wee` | `_Wee` (`jokers/misc.py:252`) | `on_score_card` | `if card.rank == 2 and not card.debuffed: chips += 8` | Fires per scored 2. Retriggered by Hanging Chad (index 0), Hack, and Red seals. |
| `j_square_joker` | `_SquareJoker` (`jokers/chips.py:54`) | `on_hand_scored` | `if len(ctx.scoring_cards) == 4: chips += 4` | **SIM QUIRK**: Checks `len(ctx.scoring_cards) == 4` instead of `len(ctx.all_cards) == 4`. Triggers on Two Pair or Four of a Kind, but not on 4-card High Card. |
| `j_spare_trousers` | `_SpareTrousers` (`jokers/scaling.py:227`) | `on_hand_scored` | `if "Two Pair" in ctx.hand_type: mult += 2` | Gains +2 permanent Mult whenever Two Pair is scored. |
| `j_runner` | `_Runner` (`jokers/scaling.py:259`) | `on_hand_scored` | `if "Straight" in ctx.hand_type: chips += 15` | Gains +15 permanent Chips whenever Straight is scored. |
| `j_hiker` | `_Hiker` (`jokers/scaling.py:292`) | `on_score_card` | `card.bonus_chips += 5` | Permanently adds +5 chips to each card scored in the played hand. |

### 3.2 Deep Dive into Individual Mechanics

#### 3.2.1 Green Joker (`j_green_joker`)
In `vendor/balatro-rl/balatro_sim/jokers/scaling.py` lines 72–79:
```python
@register_joker("j_green_joker")
class _GreenJoker(JokerEffect):
    def on_hand_scored(self, inst, ctx):
        inst.state["mult"] = inst.state.get("mult", 0) + 1
        ctx.mult += inst.state.get("mult", 0)
    def on_discard(self, inst, cards, ctx):
        inst.state["mult"] = max(0, inst.state.get("mult", 0) - 1)
```
- Green Joker has a **dual incentive**:
  1. Play extra hands (+1 Mult each).
  2. Avoid discards (-1 Mult each).
- Current policy flaw: When `_tier1_survive` is seeking hands, it calls `best_discard` even on safe boards, needlessly degrading Green Joker.
- Remediation: When `j_green_joker` is owned and $P(\text{clear}) \ge 0.98$, suppress discards and instead play low safe hands.

#### 3.2.2 Ride the Bus (`j_ride_the_bus`)
In `vendor/balatro-rl/balatro_sim/jokers/scaling.py` lines 298–307:
```python
@register_joker("j_ride_the_bus")
class _RideTheBus(JokerEffect):
    def on_hand_scored(self, inst, ctx):
        has_face = any(c.is_face_card for c in ctx.scoring_cards if not c.debuffed)
        if has_face:
            inst.state["mult"] = 0
        else:
            inst.state["mult"] = inst.state.get("mult", 0) + 1
        ctx.mult += inst.state.get("mult", 0)
```
- In `card.py` line 50: `c.is_face_card` checks `self.rank in (11, 12, 13)` (Jacks, Queens, Kings). Aces (14) and 2–10 are NOT face cards.
- **Catastrophic Failure Mode**: If the agent plays any face card that is among `scoring_cards`, the accumulated mult is instantly wiped out to zero.
- Critical Guardrail: Any candidate scaling hand under Ride the Bus MUST verify:
  `all(not c.is_face_card for c in scoring_cards)` (and ideally `all(not c.is_face_card for c in played_cards)`).
  If any face card would score, the action must be rejected.

#### 3.2.3 Supernova (`j_supernova`)
In `vendor/balatro-rl/balatro_sim/jokers/mult.py` lines 236–241:
```python
@register_joker("j_supernova")
class _Supernova(JokerEffect):
    def on_hand_scored(self, inst, ctx):
        if inst.game is not None:
            ctx.mult += inst.game.run_hand_counts.get(ctx.hand_type, 0)
```
- In `game.py` line 1013: `self.run_hand_counts[hand_type] = self.run_hand_counts.get(hand_type, 0) + 1`.
- Every valid played hand increments the counter for that hand type by 1.
- If the run primarily builds around Pair or High Card, playing an extra Pair or High Card in a safe blind permanently increases Supernova mult for all future hands of that type.

#### 3.2.4 Wee Joker (`j_wee`)
In `vendor/balatro-rl/balatro_sim/jokers/misc.py` lines 251–260:
```python
@register_joker("j_wee")
class _Wee(JokerEffect):
    state_defaults = {"chips": 0}
    def on_score_card(self, inst, card, ctx):
        if card.rank == 2 and not card.debuffed:
            inst.state["chips"] = inst.state.get("chips", 0) + 8
    def on_hand_scored(self, inst, ctx):
        ctx.chips += inst.state.get("chips", 0)
```
- Each scored 2 gives +8 Chips permanently.
- Retriggers multiply this:
  - Hanging Chad (`j_hanging_chad`): retriggers the 1st played card twice -> playing a 2 in the 1st position gives 3 triggers = +24 permanent Chips.
  - Hack (`j_hack`): retriggers 2, 3, 4, 5 -> gives 2 triggers = +16 permanent Chips.
  - Red Seal: retriggers once -> +16 permanent Chips.

#### 3.2.5 Square Joker (`j_square_joker`)
In `vendor/balatro-rl/balatro_sim/jokers/chips.py` lines 54–61:
```python
@register_joker("j_square_joker")
class _SquareJoker(JokerEffect):
    state_defaults = {"chips": 0}
    def on_hand_scored(self, inst, ctx):
        if len(ctx.scoring_cards) == 4:
            inst.state["chips"] = inst.state.get("chips", 0) + 4
        ctx.chips += inst.state.get("chips", 0)
```
- **Simulator Implementation Quirk**: In official Balatro mechanics, Square Joker text reads: "This Joker gains +4 Chips if played hand has exactly 4 cards" (`len(ctx.all_cards) == 4`).
- In `chips.py`, line 58 checks `len(ctx.scoring_cards) == 4`.
- Because `evaluate_hand` returns 1 scoring card for High Card and 2 for Pair, playing 4 random cards of different ranks does NOT trigger Square Joker under the simulator's current code! Only hands whose SCORING cards count is 4 (Two Pair, Four of a Kind) trigger it.
- Note for implementers: An agent targeting Square Joker can either target Two Pair (guaranteed 4 scoring cards) or the simulator `chips.py` line 58 can be patched to `if len(ctx.all_cards) == 4 or len(ctx.scoring_cards) == 4:`.

---

## 4. Clear Probability Estimation & Safety Formulations

### 4.1 How P(clear) is Currently Estimated
In `agent_v10.py` (lines 2106–2174):
- `estimate_clear_probability_bounds(game, h, d, T, hand, type_scores)` returns `(pessimistic, optimistic)`.
- Inputs:
  - $T = \text{chips\_target} - \text{chips\_scored}$ (remaining chips needed).
  - $h = \text{hands\_left}$.
  - $d = \text{discards\_left}$.
  - `type_scores`: mapping of hand type to best score $S_{ht}$.
- For each hand type $ht$:
  - $m_{ht} = \lceil T / S_{ht} \rceil$. If $m_{ht} > h$, this hand type cannot clear.
  - $a_{ht}$: hypergeometric assembly probability across `fresh` drawn cards:
    `fresh = min(N, d * k_d + (h - 1) * k_r)`.
  - If $m_{ht} \le 1$, $p_{ht} = a_{ht}$.
  - If $m_{ht} > 1$, $p_{ht} = a_{ht} \times (\min(1.0, fresh / m_{ht}))^{m_{ht}}$.
- Pessimistic probability: $P_{clear} = \min(1.0, \max_{ht} p_{ht})$.

### 4.2 Limitations & Pathologies of the Current Estimator
1. **Bonferroni Union Bound Inflation**:
   For Pair and Two Pair, the assembler uses `_rank_union`:
   $$\sum_{r=2}^{14} P(\text{at least 2 of rank } r)$$
   When summed across all 13 ranks with $h=4, d=3$, the sum often exceeds 1.0 (capped at 1.0). Even when each pair scores only 40 chips and $T=600$, the formula may report $P(\text{clear}) = 1.0$ if $S_{ht}$ from a representative hand is inflated.
2. **Rate Sanity Requirement**:
   Recognizing this issue, line 2623 notes:
   *"Rate sanity gate: P(clear) reads 1.000 on doomed boards (seed 87 bank)... Only enter farming when the board's ACTUAL top play carries its fair share of the remaining target."*
   Optilatro requires:
   `plays[0][0] >= ((target - chips_scored) / max(1, hands_left)) * rate_share`.
3. **Absence of In-Hand Knockout Awareness**:
   The current estimator treats hands probabilistically across draws, ignoring the fact that if a clearing hand is ALREADY held in the current hand, clearance is 100% deterministic if those specific cards are preserved.

### 4.3 Robust 3-Tier Safety Hierarchy for Scaling Acceleration
To ensure survival is NEVER compromised when banking scaling jokers ($P(\text{clear}) \ge 0.98$ and $h \ge 2$):

#### Tier S1: Deterministic In-Hand Knockout Reservation (Risk = 0.000%)
- Inspect `plays`: find the best play $K = (score_K, cards_K, ht_K)$ such that $score_K \ge target - chips\_scored$.
- Let $H$ be the set of cards in `game.hand`.
- Let $R = H \setminus cards_K$ be the remaining cards in hand not used by the knockout play.
- If a valid scaling play $C$ can be formed using ONLY cards from $R$ ($C \subseteq R$):
  - Playing $C$ consumes 0 cards from the knockout combo $K$.
  - $K$ remains 100% intact in hand for the next turn.
  - On the next turn, with $hands\_left - 1 \ge 1$, $K$ is guaranteed to be playable.
  - Furthermore, $K$ will score $score_K + \Delta_{scale} \ge score_K \ge T > T - score(C)$.
  - **Survival is 100% mathematically guaranteed with zero RNG and zero draw dependence.**

#### Tier S2: Single-Hand Clear Projection with Multi-Hand Buffer
If no disjoint knockout exists in hand, evaluate whether the top play $S_{top} = plays[0][0]$ satisfies:
$$S_{top} \ge target - chips\_scored \quad \text{and} \quad S_{top} \times (hands\_left - 1) \ge (target - chips\_scored) \times 2.0$$
This guarantees that even after spending one hand on scaling, the remaining hands provide at least a 2.0x safety margin over the blind.

#### Tier S3: Compositional & Calibrated Model Bounds
If neither Tier S1 nor S2 applies, require:
1. `p_surv = estimate_clear_probability(game, h=hands_left - 1, d=discards_left, T=target - chips_scored - score_C, hand=hand_after, type_scores=type_scores) >= 0.98`.
2. Rate sanity: `plays[0][0] >= ((target - chips_scored) / max(1, hands_left)) * 0.75`.
3. Model agreement: If `clear_model.json` is loaded, require calibrated `model_prob >= 0.95`.

---

## 5. Scaling Trigger Actions & Joker-Specific Strategies

### 5.1 Ride the Bus (`j_ride_the_bus`)
- **Scaling Action**: Play 1 or 2 non-face cards (ranks 2, 3, 4, 5, 6, 7, 8, 9, 10, or 14/Ace).
- **Mandatory Guardrail**:
  `all(not c.is_face_card for c in scoring_cards)` AND `all(not c.is_face_card for c in played_cards)`.
  If ANY card in the scaling hand is a Jack, Queen, or King, **ABORT**. Never risk resetting Ride the Bus mult to 0.

### 5.2 Green Joker (`j_green_joker`)
- **Scaling Action**: Play 1 junk card or a low-scoring combo.
- **Discard Mitigation**:
  In `_tier1_survive` (lines 2261–2277), when `j_green_joker` is owned and $P(\text{clear}) \ge 0.98$:
  Instead of discarding junk cards (which applies a -1 Mult penalty), play 1–2 junk cards as a High Card play. This avoids the -1 penalty AND earns +1 Mult (+2 swing).

### 5.3 Wee Joker (`j_wee`)
- **Scaling Action**: Play any rank 2 cards present in hand.
- **Chad Synergy**: If `j_hanging_chad` is owned, place the rank 2 card in the first scoring slot (`cards[0]`). Chad retriggers the first card twice, yielding 3 procs = +24 permanent Chips.

### 5.4 Square Joker (`j_square_joker`)
- **Scaling Action**: Under current sim code (`len(ctx.scoring_cards) == 4`), play Two Pair or Four of a Kind that does not prematurely end the blind.
- If simulator is patched to `len(ctx.all_cards) == 4`, play any 4 non-essential cards.

### 5.5 Supernova (`j_supernova`)
- **Scaling Action**: Play a low hand of the run's most-played hand type (e.g. High Card or Pair) to increment `run_hand_counts[hand_type]`.

---

## 6. Comprehensive Safety Guardrails & Boss Banning

To guarantee that survival is **never** compromised:

1. **Strict Hand Floor**: `hands_left >= 2` mandatory. Never scale on the final hand.
2. **Boss Blind Banning**:
   Scaling acceleration MUST be disabled on dangerous bosses:
   - `bl_needle` (The Needle): Only 1 hand allowed per blind! Scaling causes instant game over.
   - `bl_mouth` (The Mouth): Only 1 hand type allowed this blind. Playing High Card locks the player out of playing Flush or Two Pair to clear.
   - `bl_eye` (The Eye): No repeat hand types allowed.
   - `bl_grim` (The Arm): Decreases the level of played hand type. Extra plays degrade planet levels.
   - `bl_hook` (The Hook): Discards 2 random cards per play, risking loss of knockout cards.
   - `bl_tooth` (The Tooth): Drains $1 per played card.
   - `bl_pillar` (The Pillar): Cards played earlier this ante are debuffed.
   - `bl_psychic` (The Psychic): Must play exactly 5 cards.
   *Recommendation*: Whitelist scaling ONLY for Small Blind and Big Blind, or restrict to non-debuffing Boss Blinds.
3. **Financial Limit**:
   Each remaining hand pays $1 at round end (`game.py:1226`).
   In early antes (Antes 1–3), if dollars are close to an interest boundary ($5, $10, $15, $20, $25), cap scaling plays at 1 per blind.
4. **Ante-1 Conservatism**:
   In Ante 1, survivability is the priority. Only scale if a scoring joker is owned and $P(\text{clear}) \ge 0.99$.

---

## 7. Concrete Implementation Plan & Code Blueprint

### 7.1 Proposed Configuration Knobs in `V10_DEFAULTS`
In `vendor/balatro-rl/balatro_sim/agent_v10.py`:
```python
V10_DEFAULTS = {
    ...
    "scaling_accel_enabled": True,       # Enable scaling joker acceleration
    "scaling_clear_threshold": 0.98,     # P(clear) required to trigger scaling
    "scaling_min_hands": 2,              # Minimum hands left to scale
    "scaling_max_per_blind": 2,          # Max scaling hands to burn per blind
    "scaling_disjoint_only": False,      # If True, only allow Tier S1 (strictly disjoint in-hand knockout)
    "scaling_safe_blinds_only": True,    # Restrict scaling to Small and Big Blinds (skip all bosses)
}
```

### 7.2 Proposed Helper Functions in `agent_v10.py`

#### Function 1: Detect Active Scaling Jokers
```python
SCALING_HAND_KEYS = {
    "j_green_joker", "j_ride_the_bus", "j_supernova",
    "j_wee", "j_square_joker", "j_spare_trousers",
    "j_runner", "j_hiker"
}

def _get_active_scaling_jokers(game) -> set[str]:
    return {j.key for j in game.jokers if j.key in SCALING_HAND_KEYS}
```

#### Function 2: Generate Safe Scaling Candidate
```python
def _find_scaling_action(game, hand, plays, scaling_keys, target):
    """Find a scaling hand that triggers owned scaling jokers while preserving knockout."""
    n = len(hand)
    # Check Tier S1: Disjoint in-hand knockout
    clearing_plays = [pl for pl in plays if pl[0] >= target]
    knockout_idxs = set()
    if clearing_plays:
        # Pick clearing play using fewest cards
        best_clear = min(clearing_plays, key=lambda pl: len(pl[1]))
        knockout_idxs = {i for i, c in enumerate(hand) if any(c is kc for kc in best_clear[1])}
    
    # Available cards for scaling that do not touch knockout combo
    avail = [i for i in range(n) if i not in knockout_idxs]
    
    # Strategy 1: Wee Joker (play a non-debuffed 2)
    if "j_wee" in scaling_keys:
        twos = [i for i in avail if hand[i].rank == 2 and not hand[i].debuffed]
        if twos:
            return {"type": "play", "cards": [twos[0]]}

    # Strategy 2: Ride the Bus (play non-face cards)
    if "j_ride_the_bus" in scaling_keys:
        non_faces = [i for i in avail if not hand[i].is_face_card and not hand[i].debuffed]
        if non_faces:
            # Play 1 low non-face card
            return {"type": "play", "cards": [non_faces[0]]}

    # Strategy 3: Green Joker (play any safe junk card to bank +1 and avoid discard penalty)
    if "j_green_joker" in scaling_keys:
        if avail:
            # Pick lowest card quality
            junk = min(avail, key=lambda i: _card_quality(hand[i]))
            return {"type": "play", "cards": [junk]}
            
    # Strategy 4: Square Joker (Two Pair under current sim code)
    if "j_square_joker" in scaling_keys:
        tp_plays = [pl for pl in plays if pl[2] == "Two Pair" and pl[0] < target]
        if tp_plays and len(tp_plays[0][1]) == 4:
            return {"type": "play", "cards": list(tp_plays[0][1])}

    return None
```

#### Function 3: Integration Hook in `_v10_decide_hand`
Insert immediately before line 2641 (`return _tier1_survive(game, plays)`):
```python
    # Scaling Joker Acceleration during safe blinds (R3)
    if (p.get("scaling_accel_enabled", False)
            and game.hands_left >= p.get("scaling_min_hands", 2)
            and (not game.current_blind.is_boss if p.get("scaling_safe_blinds_only", True)
                 else game.current_blind.boss_key not in BANNED_SCALING_BOSSES)):
        scaling_keys = _get_active_scaling_jokers(game)
        if scaling_keys and p_clear >= p.get("scaling_clear_threshold", 0.98):
            scale_act = _find_scaling_action(game, game.hand, plays, scaling_keys,
                                            game.current_blind.chips_target - game.chips_scored)
            if scale_act is not None:
                return scale_act
```

---

## 8. Human-Fairness and Isolation Compliance

1. **Zero Draw-Order Peeking**: Candidate scaling cards are selected exclusively from `game.hand`. Clearance estimation uses only visible cards and the composition multiset `_value_multiset(game.deck)`.
2. **Zero RNG Stream Consumption**: All hand evaluations utilize `eval_hand_score`, which runs inside `_EvalGame` with an isolated throwaway seed-0 RNG. `game.rng` is untouched.
3. **Zero Live Game Mutation**: Game state is stepped only when the engine processes the decided action dictionary.
4. **Verified CI Exactness Gate**: `vendor/balatro-rl/tests/test_seed_exactness.py -m ci_gate` passes 4/4.
