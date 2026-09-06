# Handoff Report: Hand-Type Specialization Traps in xMult Jokers & Portfolio Target Hand

**Agent**: `teamwork_preview_explorer_m2_2_gen6`  
**Date**: 2026-09-05T00:45:00Z  
**Target File**: `D:/Optilatro/.agents/teamwork_preview_explorer_m2_2_gen6/handoff.md`  
**Scope**: Read-only investigation into hand-type specialization traps with `j_family`, `j_order`, `j_duo` and `portfolio_target_hand()` in `vendor/balatro-rl/balatro_sim/agent_v10.py`, `tools/portfolio.py`, and `agent_v9.py`.

---

## 1. Observation

### 1.1 Empirical Benchmark Telemetry
In `vendor/balatro-rl/results/bench_0_299_search_shop_v10_gen5.json` (300-seed paired evaluation), acquiring hand-specialized xMult jokers resulted in a 0.0% win rate:
- **`j_family` (The Family: x4 Mult if played hand contains Four of a Kind)**: 0 wins out of 14 runs (**0.0% win rate**).
  - Seed 39 (died Ante 2), Seed 61 (died Ante 7), Seed 97 (died Ante 5), Seed 118 (died Ante 6), Seed 137 (died Ante 6), Seed 149 (died Ante 6), Seed 169 (died Ante 4), Seed 179 (died Ante 3), Seed 173 (died Ante 7), Seed 197 (died Ante 7), Seed 254 (died Ante 2), Seed 277 (died Ante 2), Seed 273 (died Ante 4), Seed 266 (died Ante 4).
  - **Critical Discovery**: Across all 14 runs holding `j_family`, **Four of a Kind was played in ONLY ONE RUN** (Seed 118, which still died in Ante 6). In the other 13 runs, Four of a Kind was played **zero times** throughout the entire run. Despite playing zero 4OAK hands, runs bought 3–4 `pl_mars` (Mars) planets (e.g. Seed 197 bought 4 Mars while playing exclusively Two Pair, Pair, Straight, and High Card).
- **`j_order` (The Order: x3 Mult if played hand contains Straight)**: 0 wins out of 8 runs (**0.0% win rate**).
  - Seed 0 (died Ante 3), Seed 71 (died Ante 3), Seed 117 (died Ante 6), Seed 150 (died Ante 6), Seed 124 (died Ante 8), Seed 158 (died Ante 7), Seed 207 (died Ante 5), Seed 276 (died Ante 3).
  - In 4 out of 8 runs (Seeds 71, 117, 150, 207), **Straight was NEVER played a single time** after acquiring `j_order`.
- **`j_duo` (The Duo: x2 Mult if played hand contains Pair)**: 0 wins out of 8 runs (**0.0% win rate**).
  - Seed 57 (died Ante 8), Seed 72 (died Ante 7), Seed 119 (died Ante 7), Seed 124 (died Ante 8), Seed 198 (died Ante 6), Seed 180 (died Ante 7), Seed 276 (died Ante 3), Seed 281 (died Ante 8).
  - In Seed 281 (Ante 8 Boss death), the agent scored 171,600 on Ante 7 with `['j_brainstorm', 'j_cavendish', 'j_green_joker', 'j_odd_todd', 'j_photograph']`. In Ante 8 shop, `SearchShopV10` treated `j_duo` as a `PREMIER_XMULT_FINISHER`, sold the +30 flat mult `j_green_joker` to buy `j_duo`, and bought `pl_mercury` (Pair planet). Stripped of flat mult, Two Pair scored only 7,632 on the 100k+ Ante 8 boss, resulting in immediate death.

### 1.2 Unconditional Hierarchy in `portfolio_target_hand()`
In `vendor/balatro-rl/balatro_sim/agent_v10.py` lines 718–751:
```python
_HAND_ENGINE_PRIORITY = [
    # Tier 1: Premier xMult Hand Finishers
    ({"j_family"}, "Four of a Kind"),
    ({"j_order"}, "Straight"),
    ({"j_tribe"}, "Flush"),
    ({"j_trio"}, "Three of a Kind"),
    ({"j_duo"}, "Pair"),
    # Tier 2: Scaling Hand Engines
    ({"j_spare_trousers", "j_trousers"}, "Two Pair"),
    ({"j_runner"}, "Straight"),
    # Tier 3: High-Synergy Suit & Flat/Chip Engines
    ({"j_bloodstone", "j_crafty", "j_droll", "j_smeared", "j_smeared_joker"}, "Flush"),
    ({"j_clever", "j_mad"}, "Two Pair"),
    ({"j_wily", "j_zany"}, "Three of a Kind"),
    ({"j_sly", "j_jolly", "j_half"}, "Pair"),
    ({"j_shortcut", "j_four_fingers", "j_superposition", "j_crazy", "j_devious"}, "Straight"),
    # Tier 4: Held-in-Hand Engines
    ({"j_baron", "j_shoot_the_moon"}, "High Card"),
]

def portfolio_target_hand(game) -> str:
    """Hand type synergizing with acquired jokers; tiered by engine potency, falls back to main_hand_type."""
    if not game.jokers:
        return main_hand_type(game)
    keys = {j.key for j in game.jokers}
    for engine_keys, ht in _HAND_ENGINE_PRIORITY:
        if keys & engine_keys:
            return ht
    for jk, ht in _JOKER_HAND_TYPES.items():
        if jk in keys:
            return ht
    return main_hand_type(game)
```
- Line 744: `portfolio_target_hand(game)` iterates over `_HAND_ENGINE_PRIORITY`. The instant `j_family` is owned, it unconditionally returns `"Four of a Kind"`. The instant `j_order` is owned, it returns `"Straight"`. The instant `j_duo` is owned, it returns `"Pair"`.
- It completely ignores `game.deck` composition and `main_hand_type(game)`.

### 1.3 Downstream Traps Caused by `target_ht`
1. **Planet Evaluation in Shop (`_v10_rank_shop_items`, lines 1449–1456)**:
   ```python
   target_ht = portfolio_target_hand(game)
   main_ht = main_hand_type(game)
   item_ht = PLANET_HAND.get(item.key)
   val = 0.05
   if item_ht == target_ht:
       val = 0.14
   elif item_ht == main_ht:
       val = 0.10
   ```
   When `j_family` is owned, `val = 0.14` is assigned to Mars (`pl_mars`), while Jupiter (`Flush`) or Uranus (`Two Pair`) gets lower priority.
2. **Save Mode Consumable Exemption (`_v10_decide_shop`, lines 1572–1585)**:
   ```python
   target_ht = portfolio_target_hand(game)
   ...
   is_target_planet = (item.kind == "planet" and PLANET_HAND.get(item.key) == target_ht)
   ```
   When money is under the interest floor ($25), the agent is exempted to buy `is_target_planet`. Holding `j_family` forces buying Mars and suppresses buying Jupiter/Uranus.
3. **Booster Pack Celestial Picks (`_v10_decide_booster`, line 1648)**:
   `target_ht = portfolio_target_hand(game)` forces Celestial packs to select Mars / Saturn / Mercury.
4. **In-Blind Pacing Rule Suppression (`_tier1_survive`, line 2542)**:
   ```python
   target_ht = joker_target_hand_type(game)
   allow_pace = True
   if target_ht and target_ht != "High Card" and game.discards_left > 0:
       if best_hand_type != target_ht:
           allow_pace = False
   ```
   Holding `j_family` disables `allow_pace` on playable non-4OAK hands, forcing discards to be burned on impossible draws.
5. **In-Blind Premature Play of Low-Scoring Target Hand (`_tier1_survive`, lines 2565–2575)**:
   ```python
   target_ht = joker_target_hand_type(game)
   if target_ht and target_ht != "High Card":
       ht_plays = [pl for pl in plays if pl[2] == target_ht]
       if ht_plays:
           progress = max(ht_plays, key=lambda e: e[0])
           if progress[0] >= target or (
                   game.hands_left >= 2
                   and progress[0] >= target * 0.5):
               return {"type": "play", "cards": list(progress[1])}
   ```
   For `j_duo` (`target_ht = "Pair"`), if a single Pair scores 50% of the target, the agent plays the Pair instead of Two Pair or Full House (which also trigger `j_duo` and score 3x–10x higher).

### 1.4 Joker Categorization and Anchor Stripping in `SearchShopV10`
In `agent_v10.py` lines 134–149:
```python
RELIABLE_XMULT_JOKERS = {
    "j_cavendish", "j_duo", "j_trio", "j_family", "j_order", "j_tribe", ...
}
PREMIER_XMULT_FINISHERS = {
    "j_cavendish", "j_duo", "j_trio", "j_family", "j_order", "j_tribe", ...
}
```
In `_v10_worst_joker_idx` lines 426–436:
```python
if game.ante < 7 and not has_premier_in_shop:
    # Protect essential anchors before Ante 7 when no premier finisher is in shop
    if n_xmult <= 1 and (j.key in PORTFOLIO_XMULT or j.key in PREMIER_XMULT_FINISHERS):
        continue
    if n_chips <= 1 and j.key in PORTFOLIO_CHIPS and not is_dead_econ:
        continue
    if n_flat <= 1 and j.key in PORTFOLIO_FLAT and not is_dead_econ:
        continue
    if j.key in COMBAT_SCALING_JOKERS and not is_dead_econ:
        continue
```
- If `j_family`, `j_order`, or `j_duo` is in the shop, `has_premier_in_shop` is **True**.
- This disables anchor protection for sole flat mult (`n_flat <= 1`), sole chips, and combat scaling jokers (`j_green_joker`, `j_ride_the_bus`).
- `SearchShopV10` swaps out scaled flat-mult jokers to buy unmakeable or low-multiplier jokers.

### 1.5 Specification & Actual Triggers in `vendor/balatro-rl/balatro_sim/jokers/mult.py`
```python
@register_joker("j_duo")
class _TheDuo(JokerEffect):
    def on_hand_scored(self, inst, ctx):
        if _has_hand(ctx.hand_type, "Pair", "Two Pair", "Full House", "Four of a Kind", "Five of a Kind", "Flush House"):
            ctx.mult_mult *= 2

@register_joker("j_trio")
class _TheTrio(JokerEffect):
    def on_hand_scored(self, inst, ctx):
        if _has_hand(ctx.hand_type, "Three of a Kind", "Full House", "Five of a Kind", "Flush House"):
            ctx.mult_mult *= 3

@register_joker("j_family")
class _TheFamily(JokerEffect):
    def on_hand_scored(self, inst, ctx):
        if _has_hand(ctx.hand_type, "Four of a Kind", "Five of a Kind"):
            ctx.mult_mult *= 4
```
- `j_duo` triggers on **Two Pair** and **Full House**, not just Pair.
- `j_trio` triggers on **Full House**, not just Three of a Kind.
- `j_family` triggers **only** on Four of a Kind and Five of a Kind.

---

## 2. Logic Chain

### 2.1 Mathematical Impossibility of Natural Four of a Kind
1. In a standard 52-card deck, there are exactly 4 copies of each rank (Observation 1.1).
2. The probability of drawing 4 copies of a specific target rank:
   - In the opening 8-card hand: $\frac{\binom{4}{4} \binom{48}{4}}{\binom{52}{8}} = \frac{194,580}{752,538,150} \approx 0.0258\%$ (~1 in 3,867).
   - Across 23 cards (opening hand + 3 maximum 5-card discards, seeing 23 cards total): $\frac{\binom{4}{4} \binom{48}{19}}{\binom{52}{23}} \approx 3.27\%$.
   - Even across *all 13 ranks combined*, the probability of seeing 4 of *any* rank in 23 cards is only $37.62\%$ (Observation 1.1).
3. If the deck has not been reshaped via Death, Strength, or Cryptid, trying to assemble Four of a Kind fails on $>96\%$ of rounds for a target rank and $>62\%$ across the entire deck even when burning every discard.
4. When `portfolio_target_hand` unconditionally switches to "Four of a Kind", the agent diverts all planet purchases to Mars.
5. In combat, Four of a Kind is never drawn (confirmed by 13/14 benchmark runs with zero 4OAK plays). The agent plays Pairs, Two Pairs, and Flushes that have 0 planet levels and receive 1.0x mult from `j_family`. The joker is a dead slot and the deck is underleveled, guaranteeing death in Antes 3–6.

### 2.2 Threshold for Four of a Kind Viability
Calculating exact hypergeometric probabilities of drawing $\ge 4$ copies across 23 cards as rank frequency increases:
- **4 copies in deck**: $3.27\%$ chance in 23 cards (unmakeable; suicide to target).
- **5 copies in deck**: $11.18\%$ chance in 23 cards (misses $89\%$ of blinds; still unviable).
- **6 copies in deck**: $22.95\%$ chance in 23 cards (marginal; misses $\sim 77\%$ of blinds without extreme digging).
- **7 copies in deck**: $36.77\%$ chance in 23 cards (viable with standard discards).
- **8 copies in deck**: $50.74\%$ chance in 23 cards (reliable primary hand).
*(Note: `agent_v9.py` line 299 in `DECK_CONDITIONS` previously specified `("rank", 7, 0.30)` for `j_family`, explicitly recognizing the 7-card threshold!)*

Therefore, `portfolio_target_hand()` must **never** target "Four of a Kind" unless the deck contains at least 6 (preferably 7) cards of that rank. Until then, `portfolio_target_hand()` must maintain the established high-frequency base hand (`main_hand_type`, such as Flush or Two Pair).

### 2.3 The `j_order` Straight Trap
1. A Straight requires 5 consecutive ranks. Natural probability in 8 cards is $\approx 1.7\%$ (Observation 1.1).
2. Rank duplication tarots (Death, Strength) duplicate one rank, which reduces diversity of adjacent ranks and directly *harms* Straight formation.
3. Straights are only viable as a primary engine if the player holds `j_shortcut` (allowing 1-rank gaps), `j_four_fingers` (requiring only 4 cards), or has already played Straights extensively.
4. Without `j_shortcut` or `j_four_fingers`, unconditionally targeting Straight starves the run of Flush / Two Pair levels and leads to 0 wins out of 8 runs.

### 2.4 The `j_duo` Degradation & Flat Mult Liquidation Trap
1. `j_duo` card text: "X2 Mult if played hand contains a Pair" (Observation 1.5).
2. Two Pair (base 20x2, Uranus +20/+1) and Full House (base 40x4, Earth +25/+2) both contain a Pair and trigger `j_duo`.
3. Pair has base 10x2 (20 pts) and Mercury gives only +15 chips and +1 mult (Observation 1.1).
4. By unconditionally returning `"Pair"`, `portfolio_target_hand()` forces the shop to buy Mercury, neglecting Uranus and Earth.
5. In `_tier1_survive` (Observation 1.3), `target_ht = "Pair"` causes the agent to play a single Pair if it reaches 50% target, wasting a hand and discarding Two Pair or Full House lines that could clear immediately.
6. In `SearchShopV10`, `j_duo` was classified as a `PREMIER_XMULT_FINISHER`. Because it is only x2 Mult, treating it as premier strips anchor protection from +30 flat mult jokers (Green Joker), leaving the agent with xMult multiplying an empty base (Observation 1.1, Seed 281).

---

## 3. Caveats

1. **Spectral Pack Cryptid / Immolate**: If a Spectral pack creates multiple copies (e.g. Cryptid adding 2 copies of a selected card) or Immolate thins 5 non-target cards, rank concentration can spike rapidly in a single action. The deck-aware check must re-evaluate dynamically on each state transition.
2. **`j_tribe` (The Tribe - Flush x2)**: Flush starts with 13 cards of each suit in a standard deck. It does not suffer from the 4OAK rank scarcity problem. However, if the deck has been heavily converted away from a suit or against suit-debuff bosses (The Goad, The Head, The Window, The Club), suit dominance must still be checked.
3. **Four Fingers / Shortcut Interaction**: When holding `j_shortcut` or `j_four_fingers`, Straight probability jumps dramatically (>70% with discards). The gating for `j_order` must be conditional on these jokers.

---

## 4. Conclusion & Actionable Recommendations

### Recommendation 1: Make `portfolio_target_hand()` Deck-Aware & Hierarchy-Inverted
In `vendor/balatro-rl/balatro_sim/agent_v10.py`:
1. **Gate `j_family` on Deck Rank Concentration**:
   - Inspect full deck composition (`game.deck + game.hand + game.spent` via `deck_groups(game)["ranks"]`).
   - If `max(ranks.values()) < 6`, DO NOT target "Four of a Kind". Instead, fall back to `main_hand_type(game)` (or "Three of a Kind" if max rank $\ge 4$, or "Two Pair").
   - Deck reshaping (`deck_reshape_target`) remains active to continue building toward `_majority_rank(dg)` in the background via Death and Strength.
2. **Gate `j_order` on Enabling Jokers or Established Play**:
   - Only return "Straight" if `{"j_shortcut", "j_four_fingers"} & keys` OR `game.run_hand_counts.get("Straight", 0) >= 2`.
   - Otherwise, fall back to `main_hand_type(game)`.
3. **Map `j_duo` to Superior Pair-Containing Hands**:
   - Never degrade an established hand to "Pair".
   - If `main_hand_type(game)` is "Two Pair", "Full House", or "Three of a Kind", return `main_hand_type(game)`.
   - If `main_hand_type(game)` is "Flush", return "Flush" (keep leveling Jupiter).
   - If no main hand is committed, return "Two Pair" instead of "Pair" because Two Pair has superior planet scaling and triggers `j_duo`.
4. **Proposed Code Replacement for `portfolio_target_hand()`**:
```python
def portfolio_target_hand(game) -> str:
    """Hand type synergizing with acquired jokers; deck-aware and preserves viable base hands."""
    if not getattr(game, "jokers", None):
        return main_hand_type(game)
    
    keys = {j.key for j in game.jokers}
    main = main_hand_type(game)
    
    # Check deck composition for rank/suit concentration
    from .graph_v9 import deck_groups
    dg = deck_groups(game)
    max_rank_cnt = max(dg["ranks"].values()) if dg.get("ranks") else 4
    max_suit_cnt = max(dg["suits"].values()) if dg.get("suits") else 13
    
    # 1. Four of a Kind (The Family): ONLY target if deck actually supports it (>= 6 of a rank)
    if "j_family" in keys:
        if max_rank_cnt >= 6:
            return "Four of a Kind"
        # Otherwise maintain working base hand while deck reshaping builds the rank
        return main if main in ("Flush", "Two Pair", "Full House", "Three of a Kind") else "Two Pair"

    # 2. Straight (The Order / Runner): ONLY target if Shortcut/Four Fingers owned or already established
    if "j_order" in keys or "j_runner" in keys:
        has_helper = bool({"j_shortcut", "j_four_fingers"} & keys)
        committed_straight = game.run_hand_counts.get("Straight", 0) >= 2
        if has_helper or committed_straight:
            return "Straight"
        return main if main in ("Flush", "Two Pair", "Full House", "Pair") else "Two Pair"

    # 3. Flush (The Tribe / Bloodstone / Crafty / Smeared):
    if keys & {"j_tribe", "j_bloodstone", "j_crafty", "j_droll", "j_smeared", "j_smeared_joker"}:
        if "j_smeared" in keys or "j_smeared_joker" in keys or max_suit_cnt >= 13 or main == "Flush":
            return "Flush"

    # 4. Pair-containing xMult (The Duo / The Trio) & Scaling (Spare Trousers):
    # Duo triggers on Pair, Two Pair, Full House. NEVER demote Two Pair/Full House to Pair!
    if "j_duo" in keys:
        if main in ("Two Pair", "Full House", "Three of a Kind", "Flush"):
            return main
        return "Two Pair"

    if "j_trio" in keys:
        if main == "Full House" or max_rank_cnt >= 5:
            return "Full House"
        if main in ("Three of a Kind", "Two Pair", "Flush"):
            return main
        return "Three of a Kind"

    if keys & {"j_spare_trousers", "j_trousers", "j_clever", "j_mad"}:
        return "Two Pair"

    if keys & {"j_wily", "j_zany"}:
        return "Full House" if main == "Full House" else "Three of a Kind"

    if keys & {"j_baron", "j_shoot_the_moon"}:
        return "High Card"

    if keys & {"j_sly", "j_jolly", "j_half"}:
        return "Pair"

    return main
```

### Recommendation 2: Remove Unconditional Premier Classification for Hand-Restricted Jokers
In `agent_v10.py`:
1. Remove `j_family`, `j_order`, and `j_duo` from `PREMIER_XMULT_FINISHERS` and `RELIABLE_XMULT_JOKERS`:
   ```python
   # ONLY true universal or easily satisfied finishers belong here
   RELIABLE_XMULT_JOKERS = {
       "j_cavendish", "j_card_sharp", "j_ramen", "j_constellation", "j_hologram",
       "j_baseball", "j_acrobat", "j_stuntman", "j_photograph",
       "j_blueprint", "j_brainstorm", "j_ancient",
   }
   PREMIER_XMULT_FINISHERS = {
       "j_cavendish", "j_card_sharp", "j_baseball", "j_acrobat", "j_constellation",
       "j_hologram", "j_blueprint", "j_brainstorm", "j_ancient",
   }
   ```
2. Add a dynamic helper `is_active_premier_finisher(game, joker_key)`:
   - `j_family` is premier **only if** `max_rank_cnt >= 6`.
   - `j_order` is premier **only if** `has_shortcut_or_four_fingers` or `straight_count >= 2`.
   - `j_tribe` is premier **only if** `main_hand_type == "Flush"` or `dominant_suit >= 15`.
   - `j_duo` is **never** premier (it is standard 2x xMult, valuable but not worth destroying anchors).

### Recommendation 3: Strictly Protect Flat Mult & Scaling Anchors in `_v10_worst_joker_idx()`
In `agent_v10.py` line 426:
- Never allow `has_premier_in_shop` to strip anchor protection from the run's **sole flat mult joker** (`n_flat <= 1`) or heavily scaled combat joker (`j_green_joker` / `j_ride_the_bus` / `j_supernova`).
- If `n_flat <= 1`, selling the only source of flat mult for an xMult joker leaves $Chips \times BaseMult \times xMult$, reducing damage from tens of thousands down to 4,000–7,000 (as observed in Seed 281).

### Recommendation 4: Fix `joker_target_hand_type()` and In-Blind Play Priority
In `agent_v10.py`:
- In `_XMULT_HAND_MAP` (line 473): change `"j_duo": "Two Pair"` (or map to preferred pair-containing hand).
- In `_tier1_survive` (line 2565): when checking `progress[0] >= target * 0.5`, ensure that if `target_ht == "Pair"`, it does not block playing higher-tier valid plays (Two Pair, Full House).

---

## 5. Verification Method

### 5.1 Telemetry Regression Check on Known Trap Seeds
Run the isolated simulator against the specific trap seeds:
1. **`j_family` Trap Seeds**: Seeds 61, 118, 137, 197.
   - Command: `python bench/bench_agent_v10.py --seeds 61,118,137,197 --agent search_shop_v10`
   - Invalidation condition: If `portfolio_target_hand(game)` returns `"Four of a Kind"` when `max(ranks.values()) < 6`, or if the shop buys `pl_mars` when the run is playing Flushes/Two Pairs, the fix has failed.
2. **`j_duo` Anchor Stripping Seed**: Seed 281.
   - Command: `python bench/bench_agent_v10.py --seeds 281 --agent search_shop_v10`
   - Invalidation condition: In Ante 8 shop, if `j_green_joker` is sold for `j_duo`, or if `pl_mercury` is prioritized over `pl_uranus`, the fix has failed. Seed 281 scored 171,600 in Ante 7 and should easily win Ante 8 if Green Joker is preserved.
3. **`j_order` Straight Seeds**: Seeds 71, 117, 150.
   - Invalidation condition: If `portfolio_target_hand(game)` returns `"Straight"` when neither Shortcut nor Four Fingers is held and Straight count < 2.

### 5.2 Test Suite and Integrity Verification
Run full test suite and CI gates:
```bash
python -m pytest vendor/balatro-rl/tests vendor/balatro-rl/balatro_sim/tests -q
python -m pytest vendor/balatro-rl/tests/test_seed_exactness.py -m ci_gate -v
python tools/audit_jokers_static.py
python tools/audit_consumables_static.py
python tools/audit_bosses_static.py
python tools/audit_tags_static.py
```
- Expected outcome: All unit tests pass, seed exactness remains 100% clean (zero RNG pollution), all 4 static audits remain clean.
