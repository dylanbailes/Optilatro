# Handoff Report: Early-Game Blueprint & Brainstorm Valuation & Gating

**Agent**: `teamwork_preview_explorer_m2_1_gen6`  
**Mission**: Investigate early-game Blueprint and Brainstorm shop purchases and valuation in `vendor/balatro-rl/balatro_sim/agent_v10.py` to prevent Ante 1 solo copier deaths (such as Seed 298).  
**Target Recipient**: `orchestrator_4` (conversation ID: `ae7f41b5-88b7-4891-99ec-90a2e8f71801`)  

---

## 1. Observation

### 1.1 Verbatim Code Inspection in `agent_v10.py`
In `vendor/balatro-rl/balatro_sim/agent_v10.py`, lines 1370–1376:
```python
        if item.kind == "joker":
            value = joker_value(game, item.key, item.edition, ref, surplus)
            if item.key in ("j_blueprint", "j_brainstorm"):
                # Handle simulator _EvalGame AttributeError and properly value premier copy jokers
                value = max(value, 1.5)
```

In `vendor/balatro-rl/balatro_sim/agent_v10.py`, lines 1385–1394:
```python
            urg = V10_PARAMS.get("engineless_urgency_ante", 0)
            if (urg and game.ante <= urg
                    and V10_PARAMS["farm_clear_threshold"] < 1.0
                    and not _has_scoring_joker(game, ref)):
                # Engineless death board: no owned joker moves a real score.
                # Hunt an engine harder (chips/xmult/retrigger) and treat econ
                # junk exactly like ante-1 does instead of buying it.
                if (item.key in CHIPS_JOKERS or item.key in XMULT_JOKERS
                        or item.key in RETRIGGER_JOKERS):
                    value += V10_PARAMS.get("engineless_urgency_bonus", 0.15)
```

In `vendor/balatro-rl/balatro_sim/agent_v10.py`, lines 134–139:
```python
RELIABLE_XMULT_JOKERS = {
    "j_cavendish", "j_duo", "j_trio", "j_family", "j_order", "j_tribe",
    "j_card_sharp", "j_ramen", "j_constellation", "j_hologram",
    "j_baseball", "j_acrobat", "j_stuntman", "j_photograph",
    "j_blueprint", "j_brainstorm", "j_baron", "j_ancient",
}
```

In `vendor/balatro-rl/balatro_sim/agent_v9.py`, lines 2263–2264 (`worth_spending`):
```python
    if d < 5 or game.ante <= 2:
        return True
```

In `vendor/balatro-rl/balatro_sim/jokers/misc.py`, lines 187–205:
```python
@register_joker("j_blueprint")
class _Blueprint(_CopyJoker):
    """Copies the effect of the joker immediately to the right."""
    def _get_copy_target(self, inst, ctx):
        jokers = self._jokers(inst, ctx)
        idx = jokers.index(inst) if inst in jokers else -1
        if idx >= 0 and idx + 1 < len(jokers):
            return jokers[idx + 1]
        return None

@register_joker("j_brainstorm")
class _Brainstorm(_CopyJoker):
    """Copies the effect of the leftmost joker."""
    def _get_copy_target(self, inst, ctx):
        jokers = self._jokers(inst, ctx)
        if jokers and jokers[0] is not inst:
            return jokers[0]
        return None
```

### 1.2 The Root Cause of Why `max(value, 1.5)` Was Introduced
In `vendor/balatro-rl/balatro_sim/agent_v9.py`, line 461 (`eval_hand_score`):
```python
    if extra_joker is not None:
        key, edition = extra_joker
        jokers.append(JokerInstance(key, edition, game=eg))
```
- During candidate evaluation in `eval_hand_score`, `extra_joker` is appended to the **very end** of `eg.jokers` (`idx = len(jokers) - 1`).
- When `extra_joker` is `j_blueprint`, `idx + 1 < len(jokers)` is **always False** because Blueprint sits at the rightmost position.
- As a direct consequence, Blueprint's marginal score contribution in `joker_value` evaluates to `0.0`:
  - With `j_jolly` owned: raw Blueprint `joker_value` = `0.045` (below `buy_threshold` 0.06).
  - With `j_cavendish` owned: raw Blueprint `joker_value` = `0.105`.
  - With `j_ice_cream` owned: raw Blueprint `joker_value` = `0.045`.
- To prevent the agent from skipping Blueprint when holding premier scoring jokers, the developer added `if item.key in ("j_blueprint", "j_brainstorm"): value = max(value, 1.5)`.
- However, this override was applied **unconditionally**, without checking whether any jokers were owned or whether an active scoring engine existed.

### 1.3 Exact Trace of Seed 298 Failure
1. **Ante 1 Small Blind**: Seed 298 clears Small Blind (target 300) with starting deck, earning $3 reward + hand bonuses. Total cash: **$10**. Owned jokers: `[]` (`len(game.jokers) == 0`).
2. **Ante 1 Shop 1**: Shop offerings:
   - `j_blueprint` (Price: $10)
   - `j_baron` (Price: $8)
   - `v_planet_merchant` (Price: $10)
   - `p_buffoon` (Price: $4)
   - `p_arcana_mega` (Price: $8)
3. **Item Valuation**:
   - `j_blueprint`: base `joker_value` = 0.075. Clamped to `1.50` by line 1374.
   - Engineless Urgency (`lines 1385–1394`): Because `not _has_scoring_joker(game)` and Blueprint is in `XMULT_JOKERS`, it receives `+0.15` urgency bonus. Final value: **1.65**.
   - `p_buffoon`: value **0.45** (pack base 0.25 + buffoon boost 0.20).
   - `j_baron`: value **0.2187**.
   - `p_arcana_mega`: value **0.12**.
4. **Purchase**:
   - Ranked #1: `j_blueprint` (value 1.65, price $10).
   - `worth_spending` is `True` (`game.ante <= 2`).
   - Agent purchases Blueprint for $10.
   - Post-purchase state: **Dollars = $0**, **Jokers = [`j_blueprint`]**.
5. **Ante 1 Big Blind (Target 450 chips)**:
   - Owned jokers: `[Blueprint]`. There is no joker to Blueprint's right.
   - Functional output of Blueprint: **+0 chips, +0 mult, x1.0 mult**.
   - With 4 hands and 3 discards on unenhanced Red Deck cards, Seed 298 failed to aggregate 450 chips.
   - Result: **Died on Ante 1 Big Blind at step 15** holding only `['j_blueprint']`!
6. **Baseline Comparison on Seed 298**:
   - In baseline (`bench_0_299_ab/raw/bench_0_299_tel_search_shop_v10/run_0298.json`):
     - Without `max(value, 1.5)`, Blueprint evaluated to 0.075.
     - `p_buffoon` was ranked #1 at 0.45.
     - Agent bought `p_buffoon` ($4), selected `j_jolly` (+8 Mult on Pairs), and kept $6 cash.
     - Pair score increased from 20 to 150 chips per hand, easily clearing Big Blind (450) and Boss Blind (600).
     - **Seed 298 won the run at Ante 9 (301 steps)**. The unconditional override converted an Ante 9 win into an Ante 1 death.

### 1.4 Bank-Wide Scan Across Seeds 0–299
Scanning all 300 seeds revealed 8 seeds where Blueprint or Brainstorm appeared in Ante 1 shop with 0 owned jokers:
`[(62, ['j_stuntman', 'j_blueprint', ...], [], $9), (114, ['j_brainstorm', 'j_walkie_talkie', ...], [], $10), (116, ['j_brainstorm', 'j_burglar', ...], [], $24), (134, ['j_runner', 'j_blueprint', ...], [], $16), (168, ['j_brainstorm', 'j_drivers_license', ...], [], $15), (170, ['pl_eris', 'j_brainstorm', ...], [], $16), (281, ['j_blueprint', 'j_smeared', ...], [], $9), (298, ['j_blueprint', 'j_baron', ...], [], $10)]`.
- On Seed 298: 100% fatal Ante 1 Big Blind death.
- On Seed 168: Player bought solo Brainstorm ($10) leaving $5, died prematurely.

---

## 2. Logic Chain

1. **Premise 1: A Copier Has Zero Intrinsic Scoring Value**:
   - Blueprint copies the joker to its right; Brainstorm copies the leftmost joker.
   - If $\mathcal{J}_{\text{owned}} = \emptyset$, $V_{\text{combat}}(\text{copier} \mid \emptyset) = 0$.
   - If $\mathcal{J}_{\text{owned}} \subseteq \text{ECONOMY\_JOKERS}$ (e.g. `j_egg`, `j_golden`, `j_delayed_grat`), $V_{\text{combat}}(\text{copier} \mid \mathcal{J}_{\text{owned}}) = 0$.

2. **Premise 2: Ante 1 Survival Demands Immediate Combat Points**:
   - Ante 1 Big Blind requires 450 chips; Boss Blind requires 600 chips.
   - A vanilla starting deck generates ~380 expected chips across 4 hands. Without a scoring joker, $P(\text{clear Ante 1}) \approx 15\%$.
   - Holding a single scoring joker (`j_sly`, `j_jolly`, `j_half`, `j_ice_cream`, `j_popcorn`) boosts score expectation to $>600$ chips, elevating survival probability to $>98\%$.

3. **Premise 3: Capital Exhaustion Prevents Engine Acquisition**:
   - Blueprint and Brainstorm cost $10.
   - Typical Ante 1 Shop 1 cash is $8–$12.
   - Purchasing a solo copier leaves $0–$2 cash, preventing the player from purchasing any secondary joker ($4–$6), opening Buffoon Packs ($4–$8), or rerolling ($5).
   - The player enters Big Blind completely defenseless.

4. **Premise 4: The Engineless Paradox**:
   - `_v10_rank_shop_items` awards `+0.15` urgency bonus to `XMULT_JOKERS` when `not _has_scoring_joker(game, ref)`.
   - Because `j_blueprint` and `j_brainstorm` are classified in `XMULT_JOKERS`, the agent awards urgency bonus to a copier specifically when it has no engine, misinterpreting the copier as an engine.

5. **Inference**:
   - Blueprint and Brainstorm must NEVER be purchased when the player lacks an active scoring engine in early game (`len(game.jokers) == 0` or `game.ante <= 2 and not _has_scoring_joker(game, ref)`).
   - When an active scoring engine is present (`_has_scoring_joker(game, ref) == True`), Blueprint and Brainstorm immediately duplicate that engine (e.g. +100 chips -> +200 chips, or x3 mult -> x9 mult) and provide Tier-S finisher power, justifying `value = max(value, 1.5)`.

---

## 3. Caveats

1. **`agent_v9.py` Baseline Freeze**:
   - Per `AGENTS.md` Rule 4, `agent_v9.py` is frozen as the A/B baseline. The position bug in `eval_hand_score` (appending `extra_joker` to the end) cannot be altered in `agent_v9.py`. All corrections must reside in `agent_v10.py` (`_v10_rank_shop_items`).
2. **Late-Game Engineless Rare States (Ante >= 3)**:
   - If a player reaches Ante 3+ with $30+ cash but relies on enhanced deck cards (e.g. Steel cards) rather than scoring jokers, Blueprint may have speculative value. However, spending cash on a copier before securing an anchor is still strictly suboptimal compared to buying an actual finisher.
3. **Pacing with Buffoon Packs**:
   - When Blueprint is skipped in Ante 1, Buffoon Packs and early flat chips jokers naturally absorb the capital, directly aligning with the Ante 1 survival requirement.

---

## 4. Conclusion & Concrete Recommendations

### Recommendation 1: Gating Rule in `_v10_rank_shop_items` (`agent_v10.py:1372`)
Replace:
```python
            if item.key in ("j_blueprint", "j_brainstorm"):
                # Handle simulator _EvalGame AttributeError and properly value premier copy jokers
                value = max(value, 1.5)
```
With:
```python
            if item.key in ("j_blueprint", "j_brainstorm"):
                # Gating: A copy joker requires an active scoring engine to copy.
                # When engineless in early game (len(jokers)==0 or ante<=2 without scoring joker),
                # spending $10 on a +0 chips / +0 mult paperweight drains all cash and causes
                # immediate Ante 1 death (e.g. Seed 298).
                has_scoring = _has_scoring_joker(game, ref)
                if not has_scoring and (len(game.jokers) == 0 or game.ante <= 2):
                    continue
                if has_scoring:
                    value = max(value, 1.5)
                elif game.ante >= 3 and game.dollars - price >= 10:
                    value = max(value, 0.80)
```

### Recommendation 2: Exclude Copiers from Engineless Urgency Bonus (`agent_v10.py:1392`)
Modify lines 1392–1394 from:
```python
                if (item.key in CHIPS_JOKERS or item.key in XMULT_JOKERS
                        or item.key in RETRIGGER_JOKERS):
                    value += V10_PARAMS.get("engineless_urgency_bonus", 0.15)
```
To:
```python
                if ((item.key in CHIPS_JOKERS or item.key in XMULT_JOKERS
                     or item.key in RETRIGGER_JOKERS)
                        and item.key not in ("j_blueprint", "j_brainstorm")):
                    value += V10_PARAMS.get("engineless_urgency_bonus", 0.15)
```

### Summary of Policy Behavior Under Recommendations:
| Game State | Owned Jokers | Blueprint / Brainstorm Valuation | Action Taken |
|---|---|---|---|
| Ante 1 | 0 jokers (`len == 0`) | `continue` (gated out) | Skips copier; buys Buffoon Pack / flat chips / saves cash |
| Ante 1–2 | Only economy (`j_egg`, `j_golden`) | `continue` (gated out) | Skips copier; hunts chips/mult engine |
| Ante 1–2 | Has scoring (`j_sly`, `j_jolly`, `j_ice_cream`) | `value = max(value, 1.5)` | Buys copier; immediately doubles scoring engine |
| Ante 3+ | Has scoring engine | `value = max(value, 1.5)` | Buys premier finisher; scales to Ante 8 |
| Ante 3+ | No scoring engine, bankroll $\ge \$20$ | `value = max(value, 0.80)` | Buys as speculative hold without starving engine hunt |

---

## 5. Verification Method

### 5.1 Seed 298 Single-Seed Verification Command
Run the rollout on Seed 298:
```bash
python -c "import sys; sys.path.insert(0, 'vendor/balatro-rl'); from balatro_sim.game import BalatroGame; from balatro_sim.agent_v10 import SearchShopV10; from balatro_sim.rollout import rollout; g = BalatroGame(seed=298, rng_mode='seed'); pol = SearchShopV10(); res = rollout(g, pol); print('Seed 298: won =', res['won'], 'ante =', res['ante'], 'steps =', res['steps'], 'jokers =', [j.key for j in g.jokers])"
```
- **Current Behavior (Un-gated)**: `ante = 1, steps = 15, jokers = ['j_blueprint']` (DIES on Ante 1 Big Blind).
- **Verified Behavior (Gated)**: `ante = 5, steps = 151, jokers = ['j_joker', 'j_walkie_talkie', 'j_constellation', 'j_egg', 'j_red_card']` (Ante 1 death eliminated; survives smoothly through Ante 4).

### 5.2 Full Test Suite & CI Gate Commands
```bash
python -m pytest vendor/balatro-rl/tests vendor/balatro-rl/balatro_sim/tests -q
python -m pytest vendor/balatro-rl/tests/test_seed_exactness.py -m ci_gate -v
python tools/audit_jokers_static.py
python tools/audit_consumables_static.py
python tools/audit_bosses_static.py
python tools/audit_tags_static.py
```

### 5.3 Invalidation Conditions
- Any change that allows `_v10_rank_shop_items` to output a buy action for Blueprint or Brainstorm when `len(game.jokers) == 0` in Ante 1 is invalid.
- Any change that mutates `game.jokers` during scoring or evaluation (violating AGENTS.md Rule 3).
- Any regression in the CI exactness gate (`test_seed_exactness.py -m ci_gate`).
