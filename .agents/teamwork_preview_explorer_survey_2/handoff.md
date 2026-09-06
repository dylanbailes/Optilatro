# Step 0 Survey Report: Jokers, Portfolio & Shop Search Architecture

## 1. Observation

### 1.1 Joker Subsystem & Registration Architecture
- **Location**: `vendor/balatro-rl/balatro_sim/jokers/` (`__init__.py`, `base.py`, `chips.py`, `economy.py`, `hand_type.py`, `misc.py`, `mult.py`, `scaling.py`).
- **Registration**: Colocated decorator registration `@register_joker("j_x")` in `vendor/balatro-rl/balatro_sim/jokers/base.py` lines 50–65:
  ```python
  def register_joker(key: str):
      def decorator(cls):
          if key in JOKER_REGISTRY:
              raise ValueError(f"duplicate joker registration: {key!r} already registered")
          JOKER_REGISTRY[key] = cls()
          cls.key = key
          return cls
      return decorator
  ```
- **Capability Flags vs NOSCAN**: `JokerEffect.flags` (lines 79, 234–237 in `base.py`) replaces engine key-scans:
  - `flags = frozenset({"retriggers_held"})` (`j_mime`, `misc.py:72`)
  - `flags = frozenset({"free_planets"})` (`j_astronomer`, `misc.py:362`)
  - `flags = frozenset({"disables_bosses"})` (`j_chicot`, `misc.py:434`)
  - `flags = frozenset({"doubles_lucky"})` (`j_oops`, `misc.py:481`)
  - `flags = frozenset({"debt"})` (`j_credit_card`, `misc.py:523`)
  - `flags = frozenset({"allow_dupes"})` (`j_showman`, `misc.py:608`)
- **Static Audit Result**: `python tools/audit_jokers_static.py` reports:
  `catalogue: 150  registry: 168  aliases: 18  spec: 150 | DUPES 0, DEAD 0, STUBS 0, GAPS 0, TYPE 0, SIG 0, STATE 0, NOSCAN 0 -> GATES: CLEAN`.

### 1.2 Joker Categorization & Existing Portfolio Tooling
- **Specification**: `tools/joker_spec.json` categorizes all 150 jokers with schema `{"cost": int, "effect": str, "name": str, "timing": str, "type": str}` where `type` values are `"Chips"`, `"+Mult"`, `"xMult"`, `"Economy"`, `"Retrigger"`, and `"Effect"`.
- **Classification Sets**: `tools/portfolio.py` defines 6 canonical role sets:
  - `CHIPS_JOKERS` (21 keys, lines 20–25)
  - `FLAT_MULT_JOKERS` (29 keys, lines 27–34)
  - `XMULT_JOKERS` (36 keys, lines 36–45)
  - `SCALING_JOKERS` (21 keys, lines 47–53)
  - `ECON_JOKERS` (18 keys, lines 55–60)
  - `RETRIGGER_JOKERS` (8 keys, lines 62–65)
- **Classification Helpers**: `classify_joker(key: str)` (lines 68–77).
- **State Feature Extractor**: `extract_features_from_state(...)` (lines 80–216) and `extract_game_features(game)` (lines 218–260) produce a 42-dimensional numeric dictionary capturing:
  - Progression (`ante`, `blind_idx`, `chips_target`)
  - Economy (`dollars`, `interest_units`)
  - Inventory & Portfolio (`joker_count`, `free_joker_slots`, role counts `n_chips`, `n_flat_mult`, `n_xmult`, `n_scaling`, `n_econ`, `n_retrigger`, edition counts `n_foil`, `n_holo`, `n_poly`, `n_negative`)
  - Synergies & Danger Signals (`has_chips`, `has_flat`, `has_xmult`, `is_balanced`, `econ_heavy_late`, `zero_xmult_late`, `no_scoring_early`)
  - Deck Composition (`deck_size`, `suit_conc`, `face_ratio`, `enh_ratio`, `seal_ratio`, `hand_levels`, `vouchers`).

### 1.3 Shop Decision Functions & L1 Search (`agent_v9.py`, `agent_l1.py`, `agent_v10.py`)
- **Baseline Shop Flow in `agent_v9.py`**:
  - `decide_shop(game, rerolls_used)` (lines 2011–2078) uses `_rank_shop_items` to evaluate jokers, packs, planets, tarots, vouchers.
  - Implements money gating (`save_mode` targeting $25 interest when `forecast_beatable` is safe) and `worth_spending` checks.
  - If joker slots are full, evaluates `_v10_worst_joker_idx` and sells if $\Delta \ge \text{sell\_margin}$.
- **Comparative Search in `agent_l1.py`**:
  - `SearchShopV9._search_shop` (lines 104–140): Human-fair mode (`lookahead=False`) ranks affordable shop items with `_rank_shop_items` and plays the top item within `candidate_cap` that passes `worth_spending` and `save_mode`.
  - In research mode (`lookahead=True`, lines 144–209), uses `rollout.clone_game` to fork the game and simulate full runs; this violates human-fairness and is strictly forbidden for benchmarks.
  - **Prior finding** (`docs/STATUS.md` line 58 & 233): In human-fair mode, `SearchShopV9` and `SearchShopV10` currently produce **byte-identical** decisions to L0 because both execute greedy first-accept selection over `_rank_shop_items`.
- **Current `SearchShopV10` in `agent_v10.py`**:
  - `SearchShopV10(SearchShopV9)` (lines 2187–2257) overrides `_search_shop` to call `_v10_rank_shop_items` (incorporating `ante1_chip_bias`, `ante2_chip_bias`, and `engineless_urgency_ante`), but still uses the identical greedy loop over `buys[:self._candidate_cap]`.

### 1.4 Rollout Mechanics & Candidate Shop Actions
- **Rollout Primitives (`vendor/balatro-rl/balatro_sim/rollout.py`)**:
  - `clone_game(game)` (line 23): Performs `deepcopy(game)` ensuring independent `LuaRandom` per-node RNG state (~1 ms cost).
  - `rollout(game, policy, max_steps, stall_guard)` (lines 70–100): Steps game until `State.GAME_OVER` or step cap.
  - `outcome(game, steps, truncated)` (lines 102–141): Extracts run statistics and win condition (`ante > 8 and state == GAME_OVER`).
- **Actions Requiring Counterfactual Valuation**:
  1. `leave_shop`: Preserve cash for interest ($5 per $25) and upcoming blind security.
  2. `buy(item_idx)`:
     - Jokers: Deduct price, add $(key, edition)$, increment role counts ($N_{\text{xmult}}, N_{\text{chips}}$, etc.).
     - Planets: Deduct price, level up corresponding hand type.
     - Tarots / Packs: Deduct price, enhance deck composition / generate assets.
     - Vouchers: Deduct price, gain permanent passive modifiers (hands, discards, discounts).
  3. `sell_joker(joker_idx)`: Reclaim sell value and free a slot.
  4. `swap(joker_idx, item_idx)`: Sell lowest-value/redundant joker (e.g., redundant economy joker in late antes) to make room for scaling/xMult engine.
  5. `reroll`: Spend reroll cost ($5 base - discounts) to sample a refreshed shop pool.

### 1.5 Offline Value Model & Counterfactual State Feature Extraction
- **Dataset Generation (`tools/gen_shop_dataset.py`)**:
  - Generates rollout games with exploratory perturbations (`explore_shop_action`, lines 31–59) sampling xMult/scaling purchases and economy sales across Antes 2–5.
  - Logs snapshot features at shop entry and labels with terminal outcome ($y = 1.0$ if won, $0.0$ otherwise).
- **Offline Model Training (`tools/fit_shop_model.py`)**:
  - Computes domain interaction terms (`build_interactions`, lines 34–52):
    - Multiplicative synergies: `inter_chips_mult`, `inter_mult_xmult`, `inter_chips_xmult`, `inter_ante_xmult`
    - Late-game penalties: `inter_late_econ_penalty = max(0, ante - 3) * n_econ`, `inter_late_zero_xmult = 1.0 if (ante >= 4 and n_xmult == 0) else 0.0`
  - Fits L2-regularized logistic regression $V(s) = \sigma(w^T Z(f(s)) + b)$ with AUC optimization.
  - Exports lightweight weights to `vendor/balatro-rl/balatro_sim/shop_model.json`.
- **Pure-Python Runtime Evaluation Pattern**:
  - Matches `clear_model.json` in `agent_v10.py:1483–1506`: zero dependencies beyond standard library `math`, sub-microsecond vector dot product:
    $$z = b + \sum_i \frac{f_i - \mu_i}{\sigma_i} \cdot w_i, \quad V(s) = \frac{1}{1 + e^{-z}}$$

---

## 2. Logic Chain

1. **Failure Mode of Prior L1 Shop Search**:
   - `docs/STATUS.md` and `docs/history/changelog.md` record that `SearchShopV9` and `SearchShopV10` were byte-identical to L0 because both evaluated individual items in isolation via `joker_value` and greedily took the first item passing `worth_spending`.
   - Furthermore, the greedy approach fails to recognize holistic portfolio composition: in Ante 4+, holding 2–3 economy jokers without xMult leads to rapid death, but `joker_value` alone does not penalize existing portfolio imbalances or compute the net value gain of selling an economy joker to buy an xMult joker.

2. **Feasibility of Counterfactual State Feature Extraction**:
   - `tools/portfolio.py:extract_features_from_state` takes explicit scalar/collection parameters rather than requiring a cloned `BalatroGame`.
   - Therefore, for any hypothetical shop action $a$ from current state $s$, the agent can construct the counterfactual state parameters $s'_a$ in $O(1)$ memory and time without calling `deepcopy` or executing rollouts.
   - For example, evaluating buying joker $k$ with price $p$:
     - $s'.\text{dollars} = s.\text{dollars} - p$
     - $s'.\text{jokers} = s.\text{jokers} + [(k, edition)]$
     - $f(s') = \text{extract\_features\_from\_state}(s')$
     - $V(s') = \text{evaluate\_shop\_model}(f(s'))$
     - $\Delta V(a) = V(s') - V(s)$.

3. **Strict Compliance with Contract & Human-Fairness**:
   - The value model $V(s')$ is trained offline on policy rollouts and evaluated strictly on visible public state components (known deck multiset, visible shop items, current money, owned jokers/vouchers).
   - No draw order or future RNG streams are accessed.
   - The evaluation is purely functional and deterministic: it does not mutate live game state and does not consume the game's RNG stream.
   - All joker interactions respect capability flags (`j.has_flag`), maintaining 0 violations across all 8 static audit gates and passing `ci_gate`.

---

## 3. Caveats

1. **Joker Role Overlaps**:
   - Some jokers serve multiple roles (e.g., `j_wee` provides Chips but scales over time; `j_constellation` scales xMult; `j_gros_michel` provides flat mult but can self-destruct).
   - `tools/portfolio.py` correctly allows non-mutually exclusive classification across sets, but the value model must learn the joint weightings.
2. **Pack Outcome Modeling**:
   - Booster packs (Buffoon, Celestial, Arcana, Standard, Spectral) present stochastic options upon opening. The counterfactual feature representation for buying a pack models the expected value of the pack category rather than peeking into the seeded pack contents before purchase.
3. **Model Generalization Across Antes**:
   - The dataset must sample diverse transitions across Antes 1–8 with sufficient exploration ($\epsilon$-greedy shop actions) to avoid training on degenerate paths where poor early decisions starve late-game data.

---

## 4. Conclusion

- The architecture for Joker Portfolio Classification (`tools/portfolio.py`), Offline Dataset Generation (`tools/gen_shop_dataset.py`), Model Fitting (`tools/fit_shop_model.py`), and True L1 Counterfactual Shop Search (`SearchShopV10` in `agent_v10.py`) is fully surveyed and structurally validated.
- Upgrading `SearchShopV10._search_shop` to rank all candidate actions (buy, sell, swap, reroll, leave) by $\Delta V = V(s') - V(s)$ using `shop_model.json` provides a mathematically principled, human-fair shop decision rule that breaks the byte-identical L1=L0 stagnation and directly addresses Ante 4+ portfolio balance failure modes.
- Baseline integrity is 100% verified: all 4 static audits are CLEAN, and `ci_gate` (`test_seed_exactness.py`) passes 4/4.

---

## 5. Verification Method

To independently verify these findings:

1. **Static Audits**:
   ```bash
   python tools/audit_jokers_static.py
   python tools/audit_consumables_static.py
   python tools/audit_bosses_static.py
   python tools/audit_tags_static.py
   ```
   *Expected output*: All gates report `GATES: CLEAN`.

2. **CI Gate Exactness**:
   ```bash
   python -m pytest vendor/balatro-rl/tests/test_seed_exactness.py -m ci_gate -v
   ```
   *Expected output*: `4 passed in ~9s`.

3. **Feature Extractor Smoke Test**:
   ```bash
   python -c "from tools.portfolio import extract_features_from_state, classify_joker; print(classify_joker('j_cavendish')); print('Features count:', len(extract_features_from_state(1, 0, 10, 4, 3, 5, [('j_cavendish', None)], 2, 0, set(), {}, 52, {'Spades': 13, 'Hearts': 13, 'Clubs': 13, 'Diamonds': 13}, 12, 0, 0)))"
   ```
   *Expected output*: Correct classification dictionary (`is_xmult: True`) and 42-feature extraction vector.

4. **Shop Model Training & Validation**:
   ```bash
   python tools/fit_shop_model.py --dataset tools/shop_dataset.jsonl
   ```
   *Expected output*: Model converges with high Test AUC and outputs `vendor/balatro-rl/balatro_sim/shop_model.json`.
