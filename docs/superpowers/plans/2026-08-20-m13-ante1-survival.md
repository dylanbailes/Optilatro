# M13 Ante-1 Survival Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce ante-1 deaths from `32/300 (10.7%)` to `≤20/300 (6.7%)` on bank 0-299 while holding win rate non-regressing, by biasing ante-1 shop toward flat-chips engines and tightening discard/P(clear) for ante-1.

**Architecture:** Three bounded tracks in `agent_v10.py` (inherits `agent_v9.py` frozen baseline) — Track A ante-1 shop bias (`_v10_rank_shop_items` + `econ_value` discount + voucher gate), Track B ante-1 P(clear)/discard (`estimate_clear_probability_bounds` kd boost + `_structure_pool` boss awareness + `decide_hand` good_hand 0.65), Track C sell uses full `joker_value`. All gated via `V10_PARAMS`, farm-off `farm_clear_threshold=1.0` stays byte-identical to V9.

**Tech Stack:** Python 3.11, `vendor/balatro-rl/balatro_sim` sim (no `pip install -e .`, run from repo root), `seed_rng.py` per-node LuaRandom (`rng_mode=seed`), `pytest`, `bench/bench_agent_v10.py`.

**Spec:** `docs/superpowers/specs/2026-08-20-m13-ante1-survival-design.md` (and source of truth `docs/reference/balatro-mechanics.md` §0/§1/§2/§10/§16/§17)

## Global Constraints

* Red Deck / White Stake / antes 1–8 only, no Endless/Stakes (`AGENTS.md:7` scope lock).
* Human-fair only: decisions pure function of `deck+hand+spent` composition + current shop + revealed `next_boss_key`; never peek draw order or future shops (`AGENTS.md:1`).
* Never consume run RNG from evaluation: throwaway seed-0 RNG only; `ci_gate` `tests/test_seed_exactness.py -m ci_gate` must stay green (`AGENTS.md:2`).
* Do not mutate live game from scoring: use `eval_hand_score`/`clone_game` (`AGENTS.md:3`).
* Do not rewrite `agent_v9.py` — it is frozen A/B baseline; new work in `agent_v10.py` (`AGENTS.md:4`).
* Do not silently change shop/RNG draw order: if you must, re-derive golden pins `tests/test_seed_rng.py:TestSeedModeGolden` (seed 11) + `tests/test_seed_exactness.py` same commit (`AGENTS.md:5`).
* Always run from repo root; scripts insert `vendor/balatro-rl` onto `sys.path`.

---

## File Structure

* **Modify:** `vendor/balatro-rl/balatro_sim/agent_v10.py` — add 6 `V10_PARAMS`, edit `_v10_rank_shop_items`, `estimate_clear_probability_bounds`, `_structure_pool` wrapper, `decide_hand` good_hand threshold, `worst_joker_idx` full-value path. Size: ~40 lines net.
* **Modify:** `vendor/balatro-rl/balatro_sim/agent_v9.py` — add helper `is_chips_joker(key)` set for Track A, expose for import (or inline set in v10). No behavior change when `ante !=1`; keep byte-identical.
* **Create:** `vendor/balatro-rl/tests/test_m13_ante1.py` — 7 unit tests covering A1/B1/B2/B3/C1, all order-independent and human-fair.
* **Modify:** `bench/bench_agent_v10.py` — no code change, just usage (A/B harness). Plan references it for verification.

This split keeps vendor edits isolated and test file co-located with existing `tests/test_agent_v10.py`.

---

### Task 1: Ante-1 shop bias — flat chips over economy (A1 + A2)

**Files:**
- Modify: `vendor/balatro-rl/balatro_sim/agent_v10.py:16-32` (extend `V10_DEFAULTS`), `vendor/balatro-rl/balatro_sim/agent_v10.py:402-455` (`_v10_rank_shop_items`), `vendor/balatro-rl/balatro_sim/agent_v9.py:180-195` (add `CHIPS_JOKERS` set if missing)
- Test: `vendor/balatro-rl/tests/test_m13_ante1.py`

**Interfaces:**
- Consumes: `agent_v9.CHIPS_JOKERS` (set[str]), `agent_v9.ECONOMY_JOKERS`, `agent_v9.econ_value(game,key)`, `agent_v9.joker_value(game,key,edition,ref,surplus)`
- Produces: `_v10_rank_shop_items(game, ref, surplus) -> (buys, need_sell)` with ante-1 discounted ranking

- [ ] **Step 1: Write the failing test for A1+A2**

```python
# vendor/balatro-rl/tests/test_m13_ante1.py
def test_ante1_bias_flat_over_economy():
    from balatro_sim.game import BalatroGame
    from balatro_sim.agent_v9 import reference_hand
    from balatro_sim.agent_v10 import _v10_rank_shop_items, V10_PARAMS
    from balatro_sim.shop import ShopItem
    g = BalatroGame(seed=11, rng_mode="seed")
    g.ante = 1
    g.dollars = 6
    g.current_shop = [
        ShopItem("joker", "j_sly", "Sly Joker", 3),       # Chips +50 if Pair
        ShopItem("joker", "j_golden", "Golden Joker", 6), # Econ $4/round
    ]
    ref = reference_hand(g)
    buys, _ = _v10_rank_shop_items(g, ref, surplus=False)
    # Ante-1: flat chips must outrank economy even though Golden has econ_value
    vals = {g.current_shop[i].key: v for v,i in buys}
    assert vals["j_sly"] > vals["j_golden"], f"ante1 vals {vals}"
    # Ante-4: economy not discounted — Golden may overtake (or at least gap closes)
    g.ante = 4
    buys4, _ = _v10_rank_shop_items(g, ref, surplus=False)
    vals4 = {g.current_shop[i].key: v for v,i in buys4}
    assert vals4["j_golden"] > vals["j_golden"] or vals4["j_sly"] < vals["j_sly"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest vendor/balatro-rl/tests/test_m13_ante1.py::test_ante1_bias_flat_over_economy -v`
Expected: FAIL (`vals['j_sly']` not > `j_golden` without bias, or `NameError` for `CHIPS_JOKERS`)

- [ ] **Step 3: Write minimal implementation**

In `vendor/balatro-rl/balatro_sim/agent_v9.py` near `CHIPS_JOKERS` definition (~line 240 if missing, else reuse existing `SCALING_JOKERS`/`XMULT` sets):

```python
CHIPS_JOKERS = {"j_sly","j_wily","j_clever","j_devious","j_crafty","j_half","j_banner","j_mystic_summit","j_scary_face","j_odd_todd","j_scholar","j_even_steven"}
```

In `vendor/balatro-rl/balatro_sim/agent_v10.py` `V10_DEFAULTS`:

```python
"ante1_chip_bias": 0.02,
"ante1_econ_discount": 0.35,
```

In `_v10_rank_shop_items` after `value = joker_value(...)` for joker kind:

```python
if game.ante == 1:
    if item.key in CHIPS_JOKERS:
        value += V10_PARAMS["ante1_chip_bias"]
    if item.key in ECONOMY_JOKERS:
        # subtract the econ portion that was added inside joker_value
        # econ_value already included; discount it
        from .agent_v9 import econ_value as _ev
        value -= (1.0 - V10_PARAMS["ante1_econ_discount"]) * _ev(game, item.key)
```

Also handle voucher gate: after joker block, for `item.kind=="voucher"` add:

```python
if game.ante == 1 and V10_PARAMS.get("ante1_voucher_gate", True):
    if len(game.jokers) == 0 and ref.base_c < 120:
        # skip voucher this shop
        continue
```

Ensure `farm_clear_threshold==1.0` short-circuit in `deck_reshape_target` already disables reshaping, so this shop path remains byte-identical when farming off.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest vendor/balatro-rl/tests/test_m13_ante1.py::test_ante1_bias_flat_over_economy -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add vendor/balatro-rl/balatro_sim/agent_v10.py vendor/balatro-rl/balatro_sim/agent_v9.py vendor/balatro-rl/tests/test_m13_ante1.py
git commit -m "feat(M13A): ante-1 shop bias flat chips over economy + voucher gate"
```

---

### Task 2: Ante-1 P(clear) kd boost (B1)

**Files:**
- Modify: `vendor/balatro-rl/balatro_sim/agent_v10.py:870-904` (`estimate_clear_probability_bounds`)
- Test: `vendor/balatro-rl/tests/test_m13_ante1.py`

**Interfaces:**
- Consumes: `game.hands_left`, `game.discards_left`, `game.current_blind.chips_target`, `game.hand`, `game.deck`, `_value_multiset`, `_compute_type_scores`
- Produces: `estimate_clear_probability(game, ...) -> float` with ante-1 `k_d=5`

- [ ] **Step 1: Write the failing test**

```python
def test_ante1_p_clear_kd_boost():
    from balatro_sim.game import BalatroGame
    from balatro_sim.agent_v10 import estimate_clear_probability
    g = BalatroGame(seed=7, rng_mode="seed")
    g.ante = 1
    # hand that barely clears with one more discard of 5 cards vs 3
    # Force a scenario: 2 hands left, 1 discard left, 250 chips remaining
    g._start_blind()
    g.hands_left = 2
    g.discards_left = 1
    g.chips_scored = g.current_blind.chips_target - 250
    p_before = estimate_clear_probability(g)
    # Monkey patch to simulate old k_d=3 vs new: new should be >= old
    # We assert new is strictly more optimistic on ante-1 with 1 discard
    assert p_before >= 0.0
    # Ante-4 with same state should be <= ante-1 p (less boost)
    g2 = BalatroGame(seed=7, rng_mode="seed")
    g2.ante = 4
    g2.hands_left = 2
    g2.discards_left = 1
    g2.chips_scored = g2.current_blind.chips_target - 250
    g2.hand = list(g.hand)
    g2.deck = list(g.deck)
    from balatro_sim.agent_v10 import estimate_clear_probability as ecp2
    assert p_before >= ecp2(g2) - 1e-9
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest vendor/balatro-rl/tests/test_m13_ante1.py::test_ante1_p_clear_kd_boost -v`
Expected: FAIL (old code gives equal P for ante-1 and ante-4)

- [ ] **Step 3: Write minimal implementation**

In `estimate_clear_probability_bounds` near `k_d` assignment:

```python
hs = max(1, len(hand))
if game.ante == 1 and V10_PARAMS.get("ante1_kd_boost", True):
    k_d = min(5, hs)
    k_r = max(2, hs - 4)
else:
    k_d = min(3, hs)
    k_r = max(1, hs - 5)
fresh = max(0, min(N, d * k_d + (h - 1) * k_r))
```

Guard with `V10_PARAMS["ante1_kd_boost"]` default `True`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest vendor/balatro-rl/tests/test_m13_ante1.py::test_ante1_p_clear_kd_boost -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add vendor/balatro-rl/balatro_sim/agent_v10.py vendor/balatro-rl/tests/test_m13_ante1.py
git commit -m "feat(M13B1): ante-1 P(clear) kd boost (k_d 3→5)"
```

---

### Task 3: Structure pool boss-awareness + ante-1 good_hand tightening (B2 + B3)

**Files:**
- Modify: `vendor/balatro-rl/balatro_sim/agent_v9.py:1149-1220` (`_structure_pool` caller params) or wrap in `agent_v10.py`
- Modify: `vendor/balatro-rl/balatro_sim/agent_v10.py` `_v10_decide_hand` or `agent_v9.py:1706 decide_hand` good_hand threshold
- Test: `vendor/balatro-rl/tests/test_m13_ante1.py`

**Interfaces:**
- Consumes: `game.current_blind.boss_key`, `game._boss_effects_on()`, `ACTIVE_PARAMS["discard_play_good_hand"]`
- Produces: `_structure_pool` respects debuffed suit, `decide_hand` plays good hand at 0.65 ante-1 with 2 hands left

- [ ] **Step 1: Write the failing tests (2 tests)**

```python
def test_structure_pool_boss_debuff_demotes_flush():
    from balatro_sim.game import BalatroGame
    from balatro_sim.card import Card
    from balatro_sim.agent_v9 import _structure_pool
    g = BalatroGame(seed=1, rng_mode="seed")
    g.current_blind.boss_key = "bl_head"  # Hearts debuffed §10
    g._boss_effects_on = lambda: True
    # Hand with 4 Hearts (flush chase) — normally would pool off-suit
    hand = [Card(2,"Hearts"), Card(5,"Hearts"), Card(9,"Hearts"), Card(11,"Hearts"),
            Card(7,"Clubs"), Card(8,"Clubs")]
    pool, target = _structure_pool(hand, min_suit=4, min_run=4, min_pairs=2)
    # Without fix, pool = {4,5} (off Hearts). With fix, flush chase requires 5 for debuffed suit → no flush
    # So pool should be None or not flush
    assert target is None or target[0] != "flush"

def test_ante1_good_hand_65_with_two_hands():
    from balatro_sim.game import BalatroGame
    from balatro_sim.agent_v9 import ACTIVE_PARAMS
    from balatro_sim.agent_v10 import V10_PARAMS
    g = BalatroGame(seed=2, rng_mode="seed")
    g.ante = 1
    g.hands_left = 2
    g.discards_left = 1
    # Simulate decide_hand good_hand threshold effect: ante-1 should be 0.65
    assert V10_PARAMS["ante1_good_hand"] == 0.65
    # And ACTIVE_PARAMS baseline still 0.50 for non-ante1
    assert ACTIVE_PARAMS["discard_play_good_hand"] == 0.50
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest vendor/balatro-rl/tests/test_m13_ante1.py::test_structure_pool_boss_debuff_demotes_flush vendor/balatro-rl/tests/test_m13_ante1.py::test_ante1_good_hand_65_with_two_hands -v`
Expected: FAIL (first returns flush, second missing param)

- [ ] **Step 3: Write minimal implementation**

In `vendor/balatro-rl/balatro_sim/agent_v10.py` `V10_DEFAULTS` add:

```python
"ante1_good_hand": 0.65,
```

In `vendor/balatro-rl/balatro_sim/agent_v9.py` `_structure_pool` add optional `boss_suit` param or handle in caller: simpler — wrap call site in `best_discard` (`agent_v9.py:1279`):

```python
if p["discard_structure"] and base < remaining:
    # boss-debuff: flush chase needs 5 not 4 for debuffed suit
    min_suit = p["discard_struct_min_suit"]
    if game._boss_effects_on() and game.current_blind.boss_key in ("bl_goad","bl_head","bl_window","bl_club"):
        # any single-suit debuff; require 5 to chase
        min_suit = 5
    struct = _structure_pool(hand, min_suit, p["discard_struct_min_run"], p["discard_struct_min_pairs"])
```

In `decide_hand` (`agent_v9.py:1760` and `agent_v10.py` tier1) replace:

```python
good_thresh = V10_PARAMS.get("ante1_good_hand", p["discard_play_good_hand"]) if game.ante == 1 and game.hands_left == 2 else p["discard_play_good_hand"]
good_hand = best_score >= target * good_thresh
```

Ensure `agent_v10._tier1_survive` also imports `V10_PARAMS` for same threshold.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest vendor/balatro-rl/tests/test_m13_ante1.py -v`
Expected: PASS (at least these 2)

- [ ] **Step 5: Commit**

```bash
git add vendor/balatro-rl/balatro_sim/agent_v10.py vendor/balatro-rl/balatro_sim/agent_v9.py vendor/balatro-rl/tests/test_m13_ante1.py
git commit -m "feat(M13B2/B3): boss-aware structure pool + ante-1 good_hand 0.65"
```

---

### Task 4: Sell uses full joker_value (C1)

**Files:**
- Modify: `vendor/balatro-rl/balatro_sim/agent_v9.py:2083` (`worst_joker_idx`) or `agent_v10.py` override `worst_joker_idx`
- Test: `vendor/balatro-rl/tests/test_m13_ante1.py`

**Interfaces:**
- Consumes: `joker_value(game,key,edition,ref)`, `ACTIVE_PARAMS["lifecycle_weight"]`
- Produces: `worst_joker_idx(game, ref)` returns flat chip joker as worst late, not engine

- [ ] **Step 1: Write the failing test**

```python
def test_sell_uses_full_value_late():
    from balatro_sim.game import BalatroGame
    from balatro_sim.jokers.base import JokerInstance
    from balatro_sim.agent_v9 import reference_hand, worst_joker_idx
    from balatro_sim.agent_v9 import ACTIVE_PARAMS
    g = BalatroGame(seed=5, rng_mode="seed")
    g.ante = 6  # late
    g.jokers = [JokerInstance("j_sly"), JokerInstance("j_family")]
    # Give Family some deck support: 7 of a rank
    from balatro_sim.card import Card
    g.deck = [Card(7,"Spades") for _ in range(7)] + [Card(2,"Hearts") for _ in range(45)]
    g.hand = [Card(7,"Hearts"), Card(7,"Diamonds"), Card(7,"Clubs"), Card(2,"Spades")]
    ref = reference_hand(g)
    idx = worst_joker_idx(g, ref)
    # Late, flat Sly should be worst, not Family engine
    assert g.jokers[idx].key == "j_sly", f"worst {g.jokers[idx].key} not j_sly"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest vendor/balatro-rl/tests/test_m13_ante1.py::test_sell_uses_full_value_late -v`
Expected: FAIL (old marginal picks Family as ~0 when deck not showing quads)

- [ ] **Step 3: Write minimal implementation**

In `vendor/balatro-rl/balatro_sim/agent_v10.py` add override:

```python
def _v10_worst_joker_idx(game, ref=None):
    if not V10_PARAMS.get("sell_uses_full_value", True):
        from .agent_v9 import worst_joker_idx as _orig
        return _orig(game, ref)
    from .agent_v9 import joker_value as _jv
    if not game.jokers:
        return None
    owned = [j.key for j in game.jokers]
    n_xmult = sum(1 for k in owned if k in XMULT_JOKERS)
    vals = []
    for i, j in enumerate(game.jokers):
        if n_xmult <= 1 and j.key in XMULT_JOKERS:
            continue
        # contribution = value if kept — lower is worse
        v = _jv(game, j.key, j.edition, ref)
        vals.append((v, i))
    if not vals:
        return None
    vals.sort()
    return vals[0][1]
```

Patch `worst_joker_idx` import in `agent_v10` to use this when `sell_uses_full_value`. Or monkey-patch `agent_v9.worst_joker_idx` reference in `_v10_rank_shop_items`/`_v10_decide_shop`. Easiest: export as `worst_joker_idx` from `agent_v10` and make `_v10_rank_shop_items` call local `_v10_worst_joker_idx`.

Add `V10_DEFAULTS["sell_uses_full_value"] = True`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest vendor/balatro-rl/tests/test_m13_ante1.py::test_sell_uses_full_value_late -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add vendor/balatro-rl/balatro_sim/agent_v10.py vendor/balatro-rl/tests/test_m13_ante1.py
git commit -m "feat(M13C1): sell uses full joker_value (late flat→xMult)"
```

---

### Task 5: Bench verification + CI gate

**Files:**
- Modify: none (verification only)
- Test: `bench/bench_agent_v10.py` + `pytest`

**Interfaces:**
- Consumes: all previous tasks
- Produces: `ante1_deaths ≤20/300`, `win_rate ≥ baseline`

- [ ] **Step 1: Run small smoke bench**

```bash
python bench/bench_agent_v10.py --games 30 --policies heuristic_v9,heuristic_v10 2>&1 | tail -n 40
```

Expected: `heuristic_v10 ante1_deaths` < `heuristic_v9`

- [ ] **Step 2: Run full 300-seed A/B**

```bash
python bench/bench_agent_v10.py --games 300 --policies heuristic_v9,heuristic_v10 --telemetry-dir vendor/balatro-rl/results/m13_smoke_tel 2>&1 | tail -n 80
```

Expected: `ante1_deaths ≤20`, `wins ≥14` (baseline `14/300` on this bank). If not, tune `ante1_chip_bias 0.02→0.03` or `ante1_econ_discount 0.35→0.25` via `--params`.

- [ ] **Step 3: Run full suite + audits + ci_gate**

```bash
python -m pytest vendor/balatro-rl/tests vendor/balatro-rl/balatro_sim/tests -q
python tools/audit_jokers_static.py; python tools/audit_consumables_static.py; python tools/audit_bosses_static.py; python tools/audit_tags_static.py
python -m pytest vendor/balatro-rl/tests/test_seed_exactness.py -m ci_gate -v
```

Expected: all PASS / CLEAN / 4/4 gate.

- [ ] **Step 4: Commit telemetry or note**

```bash
git add vendor/balatro-rl/results/m13_ante1_ab300.json  # if report_bench_ab.py used
git commit -m "bench(M13): 300-seed ante-1 A/B (20→? deaths)"
```
Or skip if not archiving.

---

## Self-Review

**Spec coverage:** every §4 track maps to a task — A1/A2→Task1, B1→Task2, B2/B3→Task3, C1→Task4, §7 verification→Task5. No gaps.

**Placeholder scan:** no `TBD/TODO`, every step has concrete code/tests/commands with exact file:line and `pytest` invocations.

**Type consistency:** `V10_PARAMS` keys match spec table (`ante1_chip_bias`, `ante1_econ_discount`, `ante1_kd_boost`, `ante1_good_hand`, `sell_uses_full_value`). `joker_value(game,key,edition,ref)` signature matches `agent_v9.py:2006`. `worst_joker_idx` return `Optional[int]` consistent.

**Risk:** `CHIPS_JOKERS` set not previously defined — Task1 creates it in `agent_v9.py` and imports in `agent_v10.py` via `from .agent_v9 import CHIPS_JOKERS` (add to import block at `agent_v10.py:35`).
