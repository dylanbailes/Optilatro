# Handoff Report — Remedy Explorer 3 (`teamwork_preview_explorer_remedy_3_gen2`)

## Executive Summary

This report delivers the comprehensive, verified code fix formulation for Reviewer 2's findings on Consumables, Engine Registries, and Booster Packs in `vendor/balatro-rl/balatro_sim/agent_v10.py` and `vendor/balatro-rl/tests/test_agent_v10.py`.

The four formulated remedies:
1. **`j_golden` Diamond Mapping Removal**: Remove `("j_golden", "Diamonds")` from `_SUIT_ENGINES_FIXED` in `agent_v10.py:604`, and update the three legacy tests in `test_agent_v10.py` to test authentic Diamond jokers (`j_rough_gem`, `j_greedy_joker`) while adding a test asserting Golden Joker does not trigger suit reshaping.
2. **Hex & Ankh Acquisition & Exploits in Booster Packs**: Implement `_v10_spectral_value(game, key)` that values `s_hex` and `s_ankh` at `0.20` when `len(game.jokers) == 1` (zero-risk single-joker states), and invoke it in `_v10_decide_booster` and `_v10_rank_shop_items` so that Spectral booster packs containing Hex or Ankh are bought and opened.
3. **Odd Todd Rank Group Engine Decontamination**: Correct `_RANK_GROUP_ENGINES["j_odd_todd"]` in `agent_v10.py:594` from `{3, 5, 7, 9, 11, 13, 14}` to `{14, 9, 7, 5, 3}` to eliminate face card contamination (Jacks 11 and Kings 13 give 0 chips under Odd Todd).
4. **Hanged Man Fallback Abort & Hack Engine Protection**: In `_v10_tarot_action`, abort with `return None` when all cards in hand are protected engine cards rather than destroying active engine cards. Expand `j_hack` engine card protection across all of ranks `{2, 3, 4, 5}`. Also safeguard `c_death` destination targeting so it returns `None` instead of overwriting protected cards.

---

## 1. Observation

### 1.1 Verbatim Code Observations and Defects

#### Observation 1: `j_golden` mapped to Diamonds in `_SUIT_ENGINES_FIXED`
- **File**: `vendor/balatro-rl/balatro_sim/agent_v10.py`
- **Lines 603–614**:
  ```python
  # Suit engines: fixed suit vs dominant-suit
  _SUIT_ENGINES_FIXED = (
      ("j_golden", "Diamonds"),     # Retained for unit test backward compatibility
      ("j_rough_gem", "Diamonds"),
      ("j_greedy_joker", "Diamonds"),
      ("j_bloodstone", "Hearts"),
      ("j_lusty_joker", "Hearts"),
      ("j_arrowhead", "Spades"),
      ("j_wrathful_joker", "Spades"),
      ("j_onyx_agate", "Clubs"),
      ("j_gluttonous_joker", "Clubs"),
      ("j_seeing_double", "Clubs"),
  )
  ```
- **Observed Behavior**:
  Golden Joker (`j_golden`) is an economy joker that grants $4 at end of round (`on_round_eval`). It has zero suit mechanics. However, `deck_reshape_target(game)` iterates `_SUIT_ENGINES_FIXED` at line 747:
  ```python
  for key, s in _SUIT_ENGINES_FIXED:
      if key in keys:
          t["suit"] = s
          break
  ```
  Owning Golden Joker sets `t["suit"] = "Diamonds"`, which distorts Tarot valuations (boosting Star at lines 967–973), distorts Standard pack card valuation (boosting Diamonds at lines 1007–1013), and causes `_v10_tarot_action` to convert cards to Diamonds.
  Legacy tests in `tests/test_agent_v10.py` at lines 405–409, 473–479, and 512–523 explicitly asserted this erroneous behavior.

#### Observation 2: Hex and Ankh Booster Pack Skip in `_v10_decide_booster`
- **File**: `vendor/balatro-rl/balatro_sim/agent_v10.py`
- **Lines 1472–1474**:
  ```python
              elif c in ALL_SPECTRALS:
                  if room_for_consumable:
                      value = spectral_value(game, c)
  ```
- **Observed Behavior in `agent_v9.py:1734–1735`**:
  ```python
  def spectral_value(game, key: str) -> float:
      if key in ("s_ankh", "s_hex", "s_ouija", "s_sigil"):
          return 0.0
  ```
- **Reproduction Result**:
  Running:
  ```bash
  python -c "import sys; sys.path.insert(0, 'vendor/balatro-rl'); from balatro_sim.game import BalatroGame; from balatro_sim.jokers import JokerInstance; from balatro_sim.agent_v10 import _v10_decide_booster; g = BalatroGame(); g.jokers = [JokerInstance('j_joker', game=g)]; g.booster_choices = ['s_hex', 's_ankh']; g.booster_picks_remaining = 1; g.consumable_hand = []; g.consumable_slots = 2; print(_v10_decide_booster(g))"
  ```
  Yields:
  `{'type': 'skip_booster'}`
  Because `spectral_value` returns `0.0 < booster_pick_threshold (0.06)`, both choices are skipped. Even though `_v10_spectral_action` contains the logic to execute `s_hex` and `s_ankh` when `len(game.jokers) == 1`, the agent can never pick them from a Spectral booster pack!

#### Observation 3: Face Card Contamination in `_RANK_GROUP_ENGINES["j_odd_todd"]`
- **File**: `vendor/balatro-rl/balatro_sim/agent_v10.py`
- **Lines 592–597**:
  ```python
  _RANK_GROUP_ENGINES = {
      "j_even_steven": {2, 4, 6, 8, 10},
      "j_odd_todd": {3, 5, 7, 9, 11, 13, 14},
      "j_fibonacci": {14, 2, 3, 5, 8},
      "j_hack": {2, 3, 4, 5},
  }
  ```
- **Game Mechanics Definition (`vendor/balatro-rl/balatro_sim/jokers/economy.py:50–54`)**:
  ```python
  @register_joker("j_odd_todd")
  class _OddTodd(JokerEffect):
      ODD_RANKS = {14, 9, 7, 5, 3}  # A=14, 9, 7, 5, 3
      def on_score_card(self, inst, card, ctx):
          if card.rank in self.ODD_RANKS and not card.debuffed:
              ctx.chips += 31
  ```
- **Observed Behavior**:
  In Balatro rules and the sim engine, Jacks (11) and Kings (13) are face cards and are NOT in `ODD_RANKS`. When a deck has more Jacks or Kings than any single odd card, `_majority_rank_in_set(dg, _RANK_GROUP_ENGINES["j_odd_todd"])` selects rank 11 or 13. Tarot reshaping then duplicates Jacks or Kings, which award +0 chips when scored under Odd Todd.

#### Observation 4: Destructive Fallback in `c_hanged_man` and Hack Rank Gaps
- **File**: `vendor/balatro-rl/balatro_sim/agent_v10.py`
- **Lines 1045, 1056, 1071**:
  ```python
  1045:             if c.rank == 2 and any(jk in keys for jk in ("j_wee", "j_hack")):
  1046:                 continue
  ...
  1056:         targets = safe_junk[:2] if safe_junk else [i for i in weakest if hand[i].enhancement == "None" and hand[i].seal == "None"][:2]
  ...
  1071:                         and not (hand[i].rank == 2 and any(jk in keys for jk in ("j_wee", "j_hack")))
  ```
- **Reproduction Result**:
  Running:
  ```bash
  python -c "import sys; sys.path.insert(0, 'vendor/balatro-rl'); from balatro_sim.game import BalatroGame, Card, State; from balatro_sim.jokers import JokerInstance; from balatro_sim.agent_v10 import _v10_tarot_action, _target_lists; g = BalatroGame(deck=[Card(2, 'Hearts')]*4); g.state = State.SHOP; g.hand = [Card(2, 'Hearts') for _ in range(4)]; g.jokers = [JokerInstance('j_wee', game=g)]; g.consumable_hand = ['c_hanged_man']; best, weakest = _target_lists(g.hand); act = _v10_tarot_action(g, 0, 'c_hanged_man', g.hand, best, weakest); print('Action:', act); [print('Destroyed rank:', g.hand[i].rank) for i in act['target_cards']]"
  ```
  Yields:
  `Action: {'type': 'use_consumable', 'consumable_idx': 0, 'target_cards': [3, 2]}`
  `Destroyed rank: 2`
  `Destroyed rank: 2`
  When `safe_junk` is empty, the ternary fallback actively destroys the exact engine cards it intended to protect. Furthermore, line 1045 and 1071 only protect `c.rank == 2` for `j_hack`, omitting ranks 3, 4, and 5 which are also retriggered by Hack.

---

## 2. Logic Chain

1. **Item 1 (`j_golden` Removal)**:
   - *Observation*: Line 604 contains `("j_golden", "Diamonds")`.
   - *Mechanics*: `j_golden` yields money, not Diamonds.
   - *Logic*: Removing `("j_golden", "Diamonds")` from `_SUIT_ENGINES_FIXED` ensures owning Golden Joker never forces Diamond reshaping.
   - *Test Alignment*: The three tests in `test_agent_v10.py` that checked `j_golden` were written for backwards compatibility during early scaffolding. Replacing them with `j_rough_gem` and asserting `t["suit"] is None` for `j_golden` verifies both positive Diamond joker functionality and regression protection.

2. **Item 2 (Hex & Ankh Valuation)**:
   - *Observation*: `_v10_decide_booster` line 1474 calls `spectral_value(game, c)` which returns `0.0` for `s_hex` and `s_ankh`.
   - *Mechanics*: When `len(game.jokers) == 1`, Hex applies Polychrome (x1.5 Mult) and destroys 0 jokers. Ankh duplicates the joker and destroys 0 jokers (when `game.joker_slots >= 2`).
   - *Logic*: Introducing `_v10_spectral_value(game, key)` returning `0.20` for `s_hex` (when joker has no edition) and `s_ankh` (when slots >= 2) on 1-joker states allows `_v10_decide_booster` to pick them. Adding `value += 0.08` for `p_spectral` in `_v10_rank_shop_items` when `len(game.jokers) == 1` ensures Spectral packs are bought in shop.

3. **Item 3 (Odd Todd Decontamination)**:
   - *Observation*: Line 594 defines `"j_odd_todd": {3, 5, 7, 9, 11, 13, 14}`.
   - *Mechanics*: In Balatro, 11 (Jack) and 13 (King) are face cards and are excluded from `_OddTodd.ODD_RANKS = {14, 9, 7, 5, 3}`.
   - *Logic*: Changing the set to `{14, 9, 7, 5, 3}` prevents `_majority_rank_in_set` from ever targeting Jacks or Kings when holding Odd Todd.

4. **Item 4 (Hanged Man & Death Protection)**:
   - *Observation*: Line 1056 falls back to `weakest[:2]` when `safe_junk` is empty. Line 1045 only checked `c.rank == 2` for `j_hack`.
   - *Mechanics*: Hack retriggers 2, 3, 4, 5. Hanged Man should never destroy active engine cards.
   - *Logic*: Changing `targets = safe_junk[:2]` and returning `None` if empty guarantees the agent never destroys protected cards. Protecting `(c.rank in (2, 3, 4, 5) and "j_hack" in keys)` prevents Hack engine cards from being destroyed. For `c_death`, returning `None` when `src is None` or `dst is None` prevents falling back to overwriting engine cards.

---

## 3. Caveats

- **Existing Unit Tests**: Currently 50/50 unit tests pass in `test_agent_v10.py` because lines 405–409, 473–479, and 512–523 explicitly test `j_golden`. Modifying `agent_v10.py` without updating those tests will cause 3 tests to fail. The worker MUST apply both the `agent_v10.py` and `test_agent_v10.py` changes together.
- **Spectral Slot Availability**: Picking a spectral card from a booster pack requires an available consumable slot (`len(game.consumable_hand) < game.consumable_slots`). Feature F7 already clears consumable slots prior to booster purchases in shop, ensuring room exists.
- **Farm-Off Baseline**: All v10 logic is gated by `V10_PARAMS.get("farm_clear_threshold", 0.90) >= 1.0` to preserve exact byte-for-byte reproduction of V9 when farm-off is set.

---

## 4. Conclusion & Exact Code Changes

### 4.1 Changes in `vendor/balatro-rl/balatro_sim/agent_v10.py`

#### Patch 1: Odd Todd and `j_golden` Removal (Lines 591–615)
```diff
--- a/vendor/balatro-rl/balatro_sim/agent_v10.py
+++ b/vendor/balatro-rl/balatro_sim/agent_v10.py
@@ -591,7 +591,7 @@
 # Rank group engines: owning one targets valid rank subset
 _RANK_GROUP_ENGINES = {
     "j_even_steven": {2, 4, 6, 8, 10},
-    "j_odd_todd": {3, 5, 7, 9, 11, 13, 14},
+    "j_odd_todd": {14, 9, 7, 5, 3},
     "j_fibonacci": {14, 2, 3, 5, 8},
     "j_hack": {2, 3, 4, 5},
 }
@@ -601,7 +601,6 @@
 
 # Suit engines: fixed suit vs dominant-suit
 _SUIT_ENGINES_FIXED = (
-    ("j_golden", "Diamonds"),     # Retained for unit test backward compatibility
     ("j_rough_gem", "Diamonds"),
     ("j_greedy_joker", "Diamonds"),
     ("j_bloodstone", "Hearts"),
```

#### Patch 2: Hanged Man Fallback Abort & Hack Rank Protection (Lines 1040–1085)
```diff
--- a/vendor/balatro-rl/balatro_sim/agent_v10.py
+++ b/vendor/balatro-rl/balatro_sim/agent_v10.py
@@ -1042,7 +1042,7 @@
                 continue
             if t.get("rank_set") and c.rank in t["rank_set"]:
                 continue
-            if c.rank == 2 and any(jk in keys for jk in ("j_wee", "j_hack")):
+            if (c.rank == 2 and "j_wee" in keys) or (c.rank in (2, 3, 4, 5) and "j_hack" in keys):
                 continue
             if c.rank in (14, 2, 3, 5, 8) and "j_fibonacci" in keys:
                 continue
@@ -1053,7 +1053,7 @@
             if c.enhancement != "None" or c.edition != "None" or c.seal != "None":
                 continue
             safe_junk.append(i)
-        targets = safe_junk[:2] if safe_junk else [i for i in weakest if hand[i].enhancement == "None" and hand[i].seal == "None"][:2]
+        targets = safe_junk[:2]
         if targets:
             return {"type": "use_consumable", "consumable_idx": ci, "target_cards": targets}
         return None
@@ -1068,7 +1068,8 @@
             src = next((i for i in best if hand[i].rank == t["rank"]), None)
             dst = next((i for i in weakest if hand[i].rank != t["rank"]
                         and not (t.get("rank_set") and hand[i].rank in t["rank_set"])
-                        and not (hand[i].rank == 2 and any(jk in keys for jk in ("j_wee", "j_hack")))
+                        and not (hand[i].rank == 2 and "j_wee" in keys)
+                        and not (hand[i].rank in (2, 3, 4, 5) and "j_hack" in keys)
                         and not (hand[i].rank in (14, 2, 3, 5, 8) and "j_fibonacci" in keys)), None)
         else:
             src = next((i for i in best if hand[i].suit == t["suit"]), None)
@@ -1076,7 +1077,7 @@
         if src is not None and dst is not None and src != dst:
             return {"type": "use_consumable", "consumable_idx": ci,
                     "target_cards": [dst, src]}
-        return _tarot_action(game, ci, key, hand, best, weakest)
+        return None
 
     if key == "c_strength" and (t["rank"] is not None or t.get("rank_set")):
```

#### Patch 3: `_v10_spectral_value` Definition and Integration (Lines 1170–1480)
```diff
--- a/vendor/balatro-rl/balatro_sim/agent_v10.py
+++ b/vendor/balatro-rl/balatro_sim/agent_v10.py
@@ -1168,6 +1168,23 @@
 
     return _spectral_action(game, ci, key, hand, best, weakest)
 
+def _v10_spectral_value(game, key: str) -> float:
+    """Spectral valuation with zero-risk exploit awareness."""
+    if V10_PARAMS.get("farm_clear_threshold", 0.90) >= 1.0:
+        return spectral_value(game, key)
+
+    if key == "s_hex":
+        # Free Polychrome (x1.5 Mult) on single-joker states with 0 jokers destroyed
+        if len(game.jokers) == 1 and getattr(game.jokers[0], "edition", "None") in ("None", None, ""):
+            return 0.20
+        return 0.0
+
+    if key == "s_ankh":
+        # Free joker duplication on single-joker states with 0 jokers destroyed
+        if len(game.jokers) == 1 and game.joker_slots >= 2:
+            return 0.20
+        return 0.0
+
+    return spectral_value(game, key)
+
 
 def _v10_maybe_use_planet(game, plays=None) -> dict | None:
@@ -1297,6 +1314,8 @@
                 # Planet levels on the main hand type are permanent chips/mult —
                 # exactly the missing margin on ante-1 boss close misses.
                 value += V10_PARAMS.get("ante1_celestial_bonus", 0.0)
+            if item.key.startswith("p_spectral") and len(game.jokers) == 1 and V10_PARAMS.get("farm_clear_threshold", 0.90) < 1.0:
+                value += 0.08
             if value >= p["buy_threshold"]:
                 buys.append((value, i))
         elif item.kind == "voucher":
@@ -1332,7 +1351,7 @@
                     and len(game.consumable_hand) < game.consumable_slots):
                 buys.append((value, i))
         elif item.kind == "spectral":
-            value = spectral_value(game, item.key)
+            value = _v10_spectral_value(game, item.key)
             if (value >= p["buy_threshold"]
                     and len(game.consumable_hand) < game.consumable_slots):
                 buys.append((value, i))
@@ -1471,7 +1490,7 @@
                     value = _v10_tarot_value(game, c)
             elif c in ALL_SPECTRALS:
                 if room_for_consumable:
-                    value = spectral_value(game, c)
+                    value = _v10_spectral_value(game, c)
         if value is None:
             continue
```

---

### 4.2 Changes in `vendor/balatro-rl/tests/test_agent_v10.py`

#### Patch: Update Legacy `j_golden` Tests & Add Remedy Verification Tests
```diff
--- a/vendor/balatro-rl/tests/test_agent_v10.py
+++ b/vendor/balatro-rl/tests/test_agent_v10.py
@@ -402,8 +402,14 @@
         t = v10.deck_reshape_target(g)
         assert t["rank"] == 7
 
-    def test_golden_targets_diamonds(self):
+    def test_diamond_joker_targets_diamonds(self):
+        g = _game([Card(14, "Spades")], deck=_std_deck(), jokers=("j_rough_gem",))
+        t = v10.deck_reshape_target(g)
+        assert t["suit"] == "Diamonds"
+
+    def test_golden_does_not_target_diamonds(self):
+        """Golden Joker is an economy joker and must NOT trigger Diamond reshaping."""
         g = _game([Card(14, "Spades")], deck=_std_deck(), jokers=("j_golden",))
         t = v10.deck_reshape_target(g)
-        assert t["suit"] == "Diamonds"
+        assert t["suit"] is None
 
@@ -471,7 +477,7 @@
         assert v10._v10_pack_card_value(g, five) == v10._pack_card_value(five)
 
     def test_pack_card_suit_bonus(self):
-        g = _game([Card(14, "Spades")], deck=_std_deck(), jokers=("j_golden",))
+        g = _game([Card(14, "Spades")], deck=_std_deck(), jokers=("j_rough_gem",))
         dia = Card(5, "Diamonds")
         spade = Card(5, "Spades")
         assert v10._v10_pack_card_value(g, dia) > v10._pack_card_value(dia)
@@ -511,10 +517,10 @@
         assert all(g.hand[i].rank == 12 for i in act["target_cards"])
 
     def test_suit_convert_in_shop(self):
-        """With Golden Joker (Diamonds), a Star tarot converts the best
+        """With Rough Gem (Diamonds), a Star tarot converts the best
         non-Diamond cards toward Diamonds in the SHOP phase."""
         hand = [Card(13, "Hearts"), Card(12, "Spades"), Card(11, "Clubs"),
                 Card(10, "Diamonds")]
-        g = self._shop_game(hand, ("j_golden",))
+        g = self._shop_game(hand, ("j_rough_gem",))
         g.consumable_hand = ["c_star"]
         best, weakest = v10._target_lists(g.hand)
@@ -590,3 +596,73 @@
             assert game.ante > 1, f"Seed {seed} failed to clear Ante 1 (state: {game.state})"
 
 
+# ────────────────────────────────────────────────────────────────────────────
+# Reviewer 2 Remedies Verification (Consumables, Registries, Boosters)
+# ────────────────────────────────────────────────────────────────────────────
+
+class TestReviewer2Remedies:
+    def test_odd_todd_ranks_exclude_face_cards(self):
+        """Odd Todd must only include odd non-face ranks {14, 9, 7, 5, 3}."""
+        assert v10._RANK_GROUP_ENGINES["j_odd_todd"] == {14, 9, 7, 5, 3}
+        assert 11 not in v10._RANK_GROUP_ENGINES["j_odd_todd"]
+        assert 13 not in v10._RANK_GROUP_ENGINES["j_odd_todd"]
+
+    def test_odd_todd_deck_targeting_skips_jacks_and_kings(self):
+        """Even with many Jacks/Kings in deck, Odd Todd only targets valid odd ranks."""
+        g = BalatroGame()
+        g.deck.append(Card(11, "Hearts"))
+        g.deck.append(Card(11, "Spades"))  # 6 Jacks total
+        g.jokers = [JokerInstance("j_odd_todd", game=g)]
+        t = v10.deck_reshape_target(g)
+        assert t["rank"] in {14, 9, 7, 5, 3}
+        assert t["rank"] != 11
+
+    def test_hanged_man_aborts_when_hand_is_all_engine_cards(self):
+        """Hanged Man returns None rather than destroying active Rank 2 engine cards."""
+        g = BalatroGame(deck=[Card(2, "Hearts")] * 4)
+        g.state = State.SHOP
+        g.hand = [Card(2, "Hearts") for _ in range(4)]
+        g.jokers = [JokerInstance("j_wee", game=g)]
+        g.consumable_hand = ["c_hanged_man"]
+        best, weakest = v10._target_lists(g.hand)
+        act = v10._v10_tarot_action(g, 0, "c_hanged_man", g.hand, best, weakest)
+        assert act is None
+
+    def test_hanged_man_hack_protects_ranks_2_through_5(self):
+        """Hack protects ranks 2, 3, 4, 5 and destroys only other ranks."""
+        g = BalatroGame()
+        g.state = State.SHOP
+        g.hand = [Card(2, "Hearts"), Card(3, "Clubs"), Card(4, "Diamonds"),
+                  Card(5, "Spades"), Card(8, "Hearts")]
+        g.jokers = [JokerInstance("j_hack", game=g)]
+        g.consumable_hand = ["c_hanged_man"]
+        best, weakest = v10._target_lists(g.hand)
+        act = v10._v10_tarot_action(g, 0, "c_hanged_man", g.hand, best, weakest)
+        assert act is not None
+        assert act["type"] == "use_consumable"
+        assert act["target_cards"] == [4]
+        assert g.hand[act["target_cards"][0]].rank == 8
+
+    def test_death_aborts_when_no_safe_destination(self):
+        """Death returns None rather than overwriting engine cards when all cards are protected."""
+        g = BalatroGame(deck=[Card(2, "Hearts")] * 4)
+        g.state = State.SHOP
+        g.hand = [Card(2, "Hearts") for _ in range(4)]
+        g.jokers = [JokerInstance("j_wee", game=g)]
+        g.consumable_hand = ["c_death"]
+        best, weakest = v10._target_lists(g.hand)
+        act = v10._v10_tarot_action(g, 0, "c_death", g.hand, best, weakest)
+        assert act is None
+
+    def test_spectral_booster_picks_hex_and_ankh_on_single_joker(self):
+        """Spectral packs pick s_hex or s_ankh when holding exactly 1 joker."""
+        g = BalatroGame()
+        g.jokers = [JokerInstance("j_joker", game=g)]
+        g.booster_choices = ["s_hex", "s_ankh"]
+        g.booster_picks_remaining = 1
+        g.consumable_hand = []
+        g.consumable_slots = 2
+        act = v10._v10_decide_booster(g)
+        assert act["type"] == "pick_booster"
+        assert act["indices"] == [0]
```

---

## 5. Verification Method

Once Worker M1 applies the patches above:

1. **Verify Unit Test Suite**:
   ```bash
   python -m pytest vendor/balatro-rl/tests/test_agent_v10.py -v
   ```
   *Expected*: All 56+ tests pass with 100% success rate.

2. **Verify E2E Requirements Suite**:
   ```bash
   python -m pytest vendor/balatro-rl/tests/test_e2e_v10_requirements.py -v
   ```
   *Expected*: All 42 tests pass.

3. **Verify Seed Exactness Gate (RNG Isolation)**:
   ```bash
   python -m pytest vendor/balatro-rl/tests/test_seed_exactness.py -m ci_gate -v
   ```
   *Expected*: 4 passed in ~5s.

4. **Verify Static Audits**:
   ```bash
   python tools/audit_jokers_static.py
   python tools/audit_consumables_static.py
   python tools/audit_bosses_static.py
   python tools/audit_tags_static.py
   ```
   *Expected*: All 4 static audits report `GATES: CLEAN`.

5. **Direct Semantic Verifications (One-Liners)**:
   - `j_golden` does NOT map to Diamonds:
     ```bash
     python -c "import sys; sys.path.insert(0, 'vendor/balatro-rl'); from balatro_sim.game import BalatroGame, Card; from balatro_sim.jokers import JokerInstance; from balatro_sim.agent_v10 import deck_reshape_target; g = BalatroGame(deck=[Card(14, 'Spades')]); g.jokers = [JokerInstance('j_golden', game=g)]; assert deck_reshape_target(g)['suit'] is None; print('PASS: Golden Joker does not target Diamonds')"
     ```
   - Odd Todd excludes face cards:
     ```bash
     python -c "import sys; sys.path.insert(0, 'vendor/balatro-rl'); from balatro_sim.agent_v10 import _RANK_GROUP_ENGINES; assert _RANK_GROUP_ENGINES['j_odd_todd'] == {14, 9, 7, 5, 3}; print('PASS: Odd Todd ranks are clean')"
     ```
   - Booster packs pick Hex / Ankh on 1 joker:
     ```bash
     python -c "import sys; sys.path.insert(0, 'vendor/balatro-rl'); from balatro_sim.game import BalatroGame; from balatro_sim.jokers import JokerInstance; from balatro_sim.agent_v10 import _v10_decide_booster; g = BalatroGame(); g.jokers = [JokerInstance('j_joker', game=g)]; g.booster_choices = ['s_hex', 's_ankh']; g.booster_picks_remaining = 1; g.consumable_hand = []; g.consumable_slots = 2; act = _v10_decide_booster(g); assert act['type'] == 'pick_booster'; print('PASS: Booster picks Hex on single joker')"
     ```
   - Hanged Man aborts on pure engine cards:
     ```bash
     python -c "import sys; sys.path.insert(0, 'vendor/balatro-rl'); from balatro_sim.game import BalatroGame, Card, State; from balatro_sim.jokers import JokerInstance; from balatro_sim.agent_v10 import _v10_tarot_action, _target_lists; g = BalatroGame(deck=[Card(2, 'Hearts')]*4); g.state = State.SHOP; g.hand = [Card(2, 'Hearts') for _ in range(4)]; g.jokers = [JokerInstance('j_wee', game=g)]; g.consumable_hand = ['c_hanged_man']; best, weakest = _target_lists(g.hand); act = _v10_tarot_action(g, 0, 'c_hanged_man', g.hand, best, weakest); assert act is None; print('PASS: Hanged Man aborts without destroying engine cards')"
     ```
