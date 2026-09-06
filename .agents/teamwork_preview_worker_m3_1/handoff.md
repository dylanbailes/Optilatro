# Milestone 3 Handoff Report: Rollout Dataset Generation & Offline Value Model (R3)

## 1. Observation

- **Owned Artifacts**:
  - `tools/gen_shop_dataset.py` (153 lines)
  - `tools/fit_shop_model.py` (156 lines)
  - `vendor/balatro-rl/balatro_sim/shop_model.json` (205 lines, 4,155 bytes)
  - `tools/shop_dataset.jsonl` (67,860 lines, ~61.4 MB)

- **Dataset Generation Output**:
  - Command: `python tools/gen_shop_dataset.py --games 3000 --output tools/shop_dataset.jsonl --workers 8 --start-seed 1000`
  - Total Games: 3,000 games simulated on seeds 1000–3999 (strictly isolated from benchmark/holdout seeds 0–699).
  - Snapshot Count: 67,860 shop entry feature snapshots.
  - Overall Win Rate: 115 wins / 3,000 games (3.83%).
  - Features per Snapshot: 42 base portfolio features + final run outcomes (`won`, `ante_norm`, `final_ante`, `seed`).

- **Value Model Training Output**:
  - Command: `python tools/fit_shop_model.py --dataset tools/shop_dataset.jsonl --epochs 5000`
  - Training Samples: 67,860 (80% train = 54,288, 20% test holdout = 13,572).
  - Feature Dimensions: 48 total features (42 base + 6 non-linear interaction terms).
  - Positive Class Rate: 9.39% in shop entry states.
  - Final Test AUC: **0.7819** (substantially exceeding the target > 0.70 threshold).
  - Train Loss: 0.2491.
  - Model Schema:
    - `"feat_order"`: 48 feature names (alphabetical order).
    - `"mean"`: 48 floats (training set mean vector).
    - `"std"`: 48 floats (training set standard deviation vector + 1e-9).
    - `"w"`: 49 floats (48 standardized feature weights + 1 intercept bias).
    - `"bias"`: `-2.7751153676878397` (explicit scalar matching `w[-1]`).
    - `"test_auc"`: `0.7819189013373024`.

- **Learned Feature Interpretability**:
  - Top Positive Weights:
    - `ante`: +0.6274 (later ante states are inherently closer to Ante 8 win)
    - `hands_left`: +0.3176 (surplus hands indicate robust deck/scoring margin)
    - `inter_ante_xmult`: +0.2991 (xMult scaling with Ante progression)
    - `blind_idx`: +0.2248
    - `deck_size`: +0.2128
    - `inter_mult_xmult`: +0.1713 (synergistic multiplication of Flat/Scaling Mult and xMult)
    - `inter_late_econ_penalty`: +0.1395
    - `free_joker_slots`: +0.1298 (capacity for strategic acquisitions)
    - `n_scaling`: +0.1208 (growing score floor)
    - `interest_units`: +0.1094 (financial health and reroll power)
  - Top Negative Weights:
    - `n_xmult`: -0.2112 (raw un-synergized xmult without mult/ante interaction)
    - `joker_count`: -0.1692 (overcrowded low-quality joker slots)
    - `econ_heavy_late`: -0.1158 (holding economy jokers late without scoring power)
    - `has_econ`: -0.1112
    - `n_flat_mult`: -0.1081
    - `has_xmult`: -0.0847
    - `n_retrigger`: -0.0829
    - `suit_conc`: -0.0687
    - `is_balanced`: -0.0439
    - `n_holo`: -0.0391
    - `[bias]`: -2.7751

- **Verification & Test Results**:
  - `python -m pytest tests/test_portfolio.py vendor/balatro-rl/tests/test_e2e_v10_requirements.py -v`: **65 passed in 47.56s**.
  - `python tools/audit_jokers_static.py`: **GATES: CLEAN** (DUPES 0, DEAD 0, STUBS 0, GAPS 0, TYPE 0, SIG 0, STATE 0, NOSCAN 0).
  - `python tools/audit_consumables_static.py`: **GATES: CLEAN**.
  - `python tools/audit_bosses_static.py`: **GATES: CLEAN**.
  - `python tools/audit_tags_static.py`: **GATES: CLEAN**.
  - `python -m pytest vendor/balatro-rl/tests/test_seed_exactness.py -m ci_gate -v`: **4 passed in 4.73s**.
  - Inference Latency: Evaluated across 500 iterations, average latency was **< 30 µs per evaluation**, far below the 1,000 µs (1 ms) limit.

---

## 2. Logic Chain

1. **Seed Isolation**:
   - Training rollouts strictly utilized seeds 1000 to 3999 (`--start-seed 1000 --games 3000`).
   - Benchmark bank (seeds 0–299) and holdout banks (seeds 300–499, 500–699) were never touched during dataset generation, ensuring zero data leakage or evaluation contamination.

2. **Exploration-Augmented Perturbations**:
   - In `tools/gen_shop_dataset.py`, `explore_shop_action` injects an $\epsilon = 0.15$ perturbation probability during Antes 2–5 to sample counterfactual transitions (e.g., buying xMult/scaling jokers and selling redundant economy jokers).
   - This provided diverse state coverage across different portfolio compositions, enabling the offline model to accurately evaluate counterfactual candidate states.

3. **Domain Interaction Feature Engineering**:
   - The 6 explicit interaction terms (`inter_chips_mult`, `inter_mult_xmult`, `inter_chips_xmult`, `inter_ante_xmult`, `inter_late_econ_penalty`, `inter_late_zero_xmult`) capture the fundamental non-linear mechanics of Balatro scoring (chips $\times$ mult $\times$ xmult).
   - The learned weights confirm this domain behavior: `inter_ante_xmult` (+0.2991) and `inter_mult_xmult` (+0.1713) emerge as top predictors of winning runs.

4. **Pure Python & Zero Runtime Dependencies**:
   - The exported JSON schema (`feat_order`, `mean`, `std`, `w`, `bias`, `test_auc`) requires only basic arithmetic (`math.exp` and dot products), allowing `SearchShopV10` to evaluate arbitrary candidate post-action states in $<30\,\mu\text{s}$ without external dependencies (Torch, Scikit-learn, etc.).

---

## 3. Caveats

- **Linear Logistic Decision Boundary**: The model is an L2-regularized logistic regression over engineered non-linear features. While fast and highly interpretable, higher-order interactions beyond the 6 explicit terms rely on the linear combination of standardized features.
- **Backwards and Forwards Compatibility**: `w` contains $D+1$ floats (where `w[-1]` is the bias term) and `"bias"` is also exported as a separate top-level key. Evaluators indexing `w[:D]` with `"bias"` or indexing `w[-1]` as the intercept will both produce identical predictions.

---

## 4. Conclusion

Milestone 3 (Rollout Dataset Generation & Offline Value Model - R3) is complete, verified, and ready for production:
- 3,000 games simulated on seeds 1000–3999 yielding 67,860 labeled state snapshots.
- Offline value model trained to a holdout Test AUC of **0.7819** (target > 0.70).
- Production weights exported to `vendor/balatro-rl/balatro_sim/shop_model.json`.
- Pure-Python evaluation latency verified at $<30\,\mu\text{s}$.
- All 65 unit tests, 4 static audits, and CI seed exactness gate pass 100% green.

---

## 5. Verification Method

To independently reproduce and verify these results:

1. **Verify Unit Tests & E2E Requirements**:
   ```bash
   python -m pytest tests/test_portfolio.py vendor/balatro-rl/tests/test_e2e_v10_requirements.py -v
   ```
   *Expected output*: `65 passed in ~45-50s`.

2. **Verify Static Audits**:
   ```bash
   python tools/audit_jokers_static.py
   python tools/audit_consumables_static.py
   python tools/audit_bosses_static.py
   python tools/audit_tags_static.py
   ```
   *Expected output*: All 4 report `GATES: CLEAN`.

3. **Verify CI Seed Exactness Gate**:
   ```bash
   python -m pytest vendor/balatro-rl/tests/test_seed_exactness.py -m ci_gate -v
   ```
   *Expected output*: `4 passed in ~5s`.

4. **Verify Model Weights & Schema**:
   ```python
   import json
   with open("vendor/balatro-rl/balatro_sim/shop_model.json") as f:
       m = json.load(f)
   assert len(m["feat_order"]) == 48
   assert len(m["mean"]) == 48
   assert len(m["std"]) == 48
   assert len(m["w"]) == 49
   assert m["test_auc"] > 0.70
   assert "bias" in m
   ```
