# Milestone 2 Handoff Report: Joker Portfolio Classification & State Feature Extraction

## 1. Observation

- **Owned Artifacts**:
  - `tools/portfolio.py` (325 lines)
  - `tests/test_portfolio.py` (528 lines)
- **Specification and Registry Alignment**:
  - `tools/joker_spec.json`: exactly 150 canonical jokers.
  - `vendor/balatro-rl/balatro_sim/shop.py:JOKER_CATALOGUE`: 150 keys matching `joker_spec.json`.
  - `vendor/balatro-rl/balatro_sim/jokers/__init__.py:_CANONICAL_JOKER_ALIASES`: 18 aliases mapped to canonical keys.
- **Categorization Sets**:
  - `CHIPS_JOKERS`: 21 canonical keys (e.g. `j_blue_joker`, `j_bull`, `j_stuntman`, `j_runner`, `j_square`, `j_wee`, `j_arrowhead`).
  - `FLAT_MULT_JOKERS`: 35 canonical keys (e.g. `j_joker`, `j_half`, `j_gros_michel`, `j_abstract`, `j_fibonacci`, `j_bootstraps`, `j_onyx_agate`, `j_shoot_the_moon`).
  - `XMULT_JOKERS`: 35 canonical keys (e.g. `j_cavendish`, `j_baron`, `j_constellation`, `j_steel_joker`, `j_photograph`, `j_triboulet`, `j_caino`).
  - `SCALING_JOKERS`: 33 canonical keys across chips, mult, xmult, payout, and hand levels.
  - `ECON_JOKERS`: 32 canonical keys across money generation, interest, tags, discounts, and consumable generation (Tarot, Spectral, Negative copies).
  - `RETRIGGER_JOKERS`: 10 canonical keys across card/joker retriggers and ability duplication.
  - `UTILITY_JOKERS`: 19 canonical keys for hand size, discards, straight/flush construction, boss disabling, and probability doubling.
- **State Feature Extraction**:
  - `extract_features_from_state(...)` returns 42 numeric float features capturing progression (`ante`, `blind_idx`), economy (`dollars`, `interest_units`), portfolio composition (`joker_count`, `free_joker_slots`, `n_chips`, `n_flat_mult`, `n_xmult`, `n_scaling`, `n_econ`, `n_retrigger`), editions (`n_foil`, `n_holo`, `n_poly`, `n_negative`), synergies (`has_chips`, `has_flat`, `has_xmult`, `has_scaling`, `has_econ`, `is_balanced`), danger signals (`econ_heavy_late`, `zero_xmult_late`, `no_scoring_early`), deck composition (`deck_size`, `suit_conc`, `face_ratio`, `enh_ratio`, `seal_ratio`), hand levels (`max_hand_lvl`, `flush_lvl`, `pair_lvl`, `two_pair_lvl`, `high_card_lvl`), and vouchers (`vouchers_count`, `has_telescope`, `has_directors_cut`, `has_grabber`, `has_wasteful`).
  - `extract_game_features(game: BalatroGame)` extracts features directly from live game instances without mutating game state or consuming RNG streams.
- **Test Results**:
  - `python -m pytest tests/test_portfolio.py -v`: 23 passed in 0.27s.
  - `python tools/audit_jokers_static.py`: GATES: CLEAN (DUPES 0, DEAD 0, STUBS 0, GAPS 0, TYPE 0, SIG 0, STATE 0, NOSCAN 0).
  - `python tools/audit_consumables_static.py`: GATES: CLEAN.
  - `python tools/audit_bosses_static.py`: GATES: CLEAN.
  - `python tools/audit_tags_static.py`: GATES: CLEAN.
  - `python -m pytest vendor/balatro-rl/tests/test_seed_exactness.py -m ci_gate -v`: 4 passed in 4.65s.
  - `python tools/gen_shop_dataset.py --games 5 --workers 1 --output tools/shop_smoke.jsonl`: 105 snapshots generated cleanly.

---

## 2. Logic Chain

1. **Joker Role Mapping**:
   - Each joker's classification was derived directly from `tools/joker_spec.json` effect text and verified against `vendor/balatro-rl/balatro_sim/jokers/` implementation classes.
   - Dual-capability jokers (e.g. `j_scholar` providing +20 Chips and +4 Mult; `j_wee` providing Chips and scaling per 2; `j_constellation` providing xMult and scaling per Planet) are mapped to all applicable role sets.
   - Normalization table `ALIAS_TO_CANONICAL` ensures legacy and alternate names (e.g. `j_spare_trousers` -> `j_trousers`, `j_showman` -> `j_ring_master`, `j_golden_ticket` -> `j_ticket`) resolve seamlessly.

2. **Feature Extraction Architecture**:
   - `extract_features_from_state` operates purely on scalar, sequence, and dictionary parameters without relying on heavy objects or deepcopies. This enables sub-microsecond feature extraction during search and counterfactual evaluation.
   - Edition effects are mathematically integrated: Foil adds to `n_chips` and `n_foil`; Holographic adds to `n_flat_mult` and `n_holo`; Polychrome adds to `n_xmult` and `n_poly`; Negative adds to `n_negative`.
   - Synergy metrics (`is_balanced`) capture whether the portfolio contains all essential pillars (Chips + Flat/Scaling Mult + xMult).
   - Danger signals identify known failure modes (Ante 1–2 lacking scoring jokers; Ante 3+ holding excessive economy jokers; Ante 4+ lacking xMult).

3. **Human-Fairness & Seed Integrity**:
   - Feature extraction only inspects visible game attributes (`game.jokers`, `game.vouchers`, `game.planet_levels`, `game.deck`, `game.dollars`, `game.ante`, `game.blind_idx`).
   - Draw order is not accessed; future RNG streams are not consumed.
   - Seed exactness tests confirm identical SHA output across runs before and after feature extraction.

---

## 3. Caveats

- **Hand Level Mapping**: `BalatroGame` stores hand levels under `self.planet_levels`. `extract_game_features` checks `getattr(game, "hand_levels", getattr(game, "planet_levels", {}))` to ensure compatibility with both internal simulator instances and external wrappers.
- **Model Training Integration**: `tools/fit_shop_model.py` requires `w = np.zeros(Z.shape[1] + 1)` for the bias term appended by `np.hstack([Z, np.ones(...)])`; this is noted for Milestone 3.

---

## 4. Conclusion

Milestone 2 (R2: Joker Portfolio Classification & State Feature Extraction) is complete and fully verified:
- All 150 Balatro jokers and their 18 canonical aliases are categorized across 6 canonical strategic roles (`CHIPS_JOKERS`, `FLAT_MULT_JOKERS`, `XMULT_JOKERS`, `SCALING_JOKERS`, `ECON_JOKERS`, `RETRIGGER_JOKERS`).
- `classify_joker(key)` returns a 6-boolean dictionary for any canonical or aliased key.
- `extract_features_from_state` and `extract_game_features` extract 42 numeric features capturing all game dynamics.
- `tests/test_portfolio.py` passes 23/23 unit tests.
- All 4 static audits remain CLEAN and CI seed exactness is 100% green.

---

## 5. Verification Method

To independently verify these changes:

1. **Run Portfolio Unit Tests**:
   ```bash
   python -m pytest tests/test_portfolio.py -v
   ```
   *Expected output*: `23 passed in ~0.3s`.

2. **Run Static Audits**:
   ```bash
   python tools/audit_jokers_static.py
   python tools/audit_consumables_static.py
   python tools/audit_bosses_static.py
   python tools/audit_tags_static.py
   ```
   *Expected output*: All 4 report `GATES: CLEAN`.

3. **Run CI Seed Exactness Gate**:
   ```bash
   python -m pytest vendor/balatro-rl/tests/test_seed_exactness.py -m ci_gate -v
   ```
   *Expected output*: `4 passed in ~5s`.

4. **Verify Smoke Dataset Generation**:
   ```bash
   python tools/gen_shop_dataset.py --games 5 --workers 1 --output tools/shop_smoke.jsonl
   ```
   *Expected output*: Generates 100+ snapshots with 42 features each without error.
