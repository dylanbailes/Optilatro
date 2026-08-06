# V5 Training Run Log

Tracks each training run, what changed, what we learned, and what to try next.

V5 = dual-agent PPO: Play agent (374-dim obs) + Shop agent (188-dim obs).
Shop agent produces a 32-dim comm vector fed into play agent obs.

---

## Run 1 (Phase A — frozen play, train shop)
**Config:** Phase A, 500 iters, 16 workers, 4096 steps/iter, play frozen (run 6 weights)
**Result:** Win rate 0%, shop loss 0.0 by iter 31, best ante 1 throughout
**What happened:** Shop steps collapsed to 0 within 30 iters. Frozen play agent (run 6) survives ante 1 long enough that each episode takes hundreds of steps — the 512-step truncation cap means episodes almost never reach the shop naturally.
**Lesson:** Phase A doesn't work. Frozen play + truncation = shop starvation. The better the play agent, the worse the starvation.

---

## Run 2 (Phase B — joint, pretrained play)
**Config:** Phase B, 1000 iters, resume-play=iter_1000.pt (run 6), both unfrozen
**Crashed:** NaN logits in shop agent PPO update
**What happened:** Embed layer shape mismatch (342 v4 vs 374 v5). Also all-False mask rows slipping into PPO minibatch → all-inf logits → NaN.
**Fix:** Resize embed weight (copy 342 cols, zero-pad 32 new comm dims), strict=False load, nan_to_num on logits, safety fallback on masks.

---

## Run 3 (Phase B — joint, pretrained play, NaN fixed)
**Config:** Phase B, 1000 iters, resume-play=iter_1000.pt, 512-step truncation
**Crashed at iter ~1484:** Same NaN crash — guards in forward() not catching it during PPO backward pass.
**What happened:** Advantage/return normalization can produce inf when rollout is near-empty. NaN propagates through backward.
**Fix:** nan_to_num on adv_b and ret_b before PPO update.

---

## Run 4 (Phase B — joint, pretrained play, all NaN fixed)
**Config:** Phase B, 1000 iters, resume-play=iter_1000.pt, 512-step truncation, ENTROPY_COEFF=0.01
**Result:** Play entropy collapsed to 0.002 by iter ~40. Shop still starved (~5 steps/iter). No wins.
**What happened:** Pretrained play weights + low entropy coeff → play agent converges to deterministic policy almost immediately. Shop learns nothing because (a) no data and (b) play dying too fast to see joker benefits.
**Fix needed:** Higher play entropy coeff.

---

## Run 5 (Phase B — joint, pretrained play, entropy fixed)
**Config:** Phase B, 1000 iters, resume-play=iter_1000.pt, 4000-step truncation, ENTROPY_COEFF_PLAY=0.05
**Crashed at iter ~1106:** NaN again, different source. s_loss going negative then exploding.
**What happened:** With 4000-step truncation, episodes occasionally produce extreme advantage values when combined with sparse shop rewards.
**Lesson:** 4000-step truncation helps shop exposure slightly but doesn't solve starvation.

---

## Run 6 (Phase B — joint, pretrained play, full NaN hardening)
**Config:** Phase B, 1000 iters, resume-play=iter_1000.pt, 4000-step truncation, ENTROPY_COEFF_PLAY=0.05, nan_to_num everywhere
**Result:** Play entropy collapsed to ~0.002 again by iter 40 despite 0.05 coeff. Shop entropy 0.01. ~5 shop steps/iter.
**What happened:** Pretrained play agent dominates. Even with high entropy coeff it collapses because the comm vector input (32 dims, all zero) confuses it early. Shop starved throughout.
**Key insight:** Pretrained play agent = worse starvation, not better. Longer survival = fewer shop resets per batch.

---

## Run 7 (Phase B — joint, pretrained play, entropy 0.05)
**Config:** Phase B, 1000 iters, resume-play=iter_1000.pt, MAX_EP_STEPS=4000, ENTROPY_COEFF_PLAY=0.05
**Status:** Survived to iter ~1342 before system reboot. Play entropy healthy (1.1-1.4). Shop entropy low (~0.3-0.5). Shop steps ~5-100/iter.
**Result:** Reward -1.5 → +0.35. No wins. Shop still mostly "leave immediately."
**Lesson:** Pretrained weights confirmed to cause starvation. Starting fresh is better.

---

## Run 8 (Phase B — both from scratch)
**Config:** Phase B, 1000 iters, NO resume, both agents init from scratch, MAX_EP_STEPS=4000
**Result:** 841 iters completed. Reward -1.18 → +0.08. Play entropy 1.6 (healthy). Shop entropy 0.25 (collapsed). Shop steps ~77/iter by iter 841.
**What happened:** Starting fresh gave much better early shop exposure (600-1300 steps/iter early on) confirming the pretrained-agent starvation hypothesis. But as the play agent learned, shop steps dried up to same starvation pattern.
**Shop strategy converged to:** ~80% leave immediately. Credit assignment gap too large to connect joker purchases to downstream outcomes.
**Key insight:** Both-from-scratch is better for early training. Starvation is structural — it's the game's ratio of play-to-shop steps, not a hyperparameter problem.

---

## Run 9 (Phase B — scratch, leave penalty, higher shop entropy)
**Config:** Phase B, 1000 iters, scratch, MAX_EP_STEPS=4000, ENTROPY_COEFF=0.03 (shop), ENTROPY_COEFF_PLAY=0.05, R_LEAVE_SHOP=-0.1
**Result:** ~230 iters. Reward -1.18 → -0.23. Play entropy 1.6. Shop entropy 0.35-0.55.
**Shop action dist at iter 220:** leave=0.43, use0=0.35, reroll=0.07 — leave penalty working.
**What happened:** Leave penalty helped but shop still not buying jokers. R_QUALITY_SCALE and R_SPEND were added to env_v5.py (bumped from 0.2→0.5, added 0.05/dollar). Run was stopped to apply combo scoring bug fix.

---

## Run 10 (Phase B — combo scoring bug fix, from scratch)
**Config:** Phase B, 1000 iters, scratch, R_QUALITY_SCALE=0.5, R_SPEND=0.05, _prev_quality bug fixed
**Result:** 280 iters completed. Reward -0.99 → +4.85. **46% blind clear rate.** Still 0 wins, 0 ante 2.
**The breakthrough:** Discovered critical combo scoring bug in `_update_play_combos()`:
```python
# BROKEN — passes list of indices as all_cards, game object as hand_type
score, _ = score_hand(cards, list(combo), gs)
# Every call threw exception → score = 0 → all combos tied → random play
```
This single bug was why runs 1-9 never cleared ante 1. With the fix, the play agent
immediately started scoring 300+ chips and clearing blinds.
**Shop starvation persisted:** 0.1% of steps were shop steps. Play agent cleared blinds
but never advanced past ante 1 (couldn't beat all 3 blinds in sequence without jokers).

---

## Run 11 (Phase B — heuristic shop rewards)
**Config:** Phase B, 1000 iters, scratch + combo fix + heuristic rewards (R_HEUR_BUY_JOKER=0.3, R_HEUR_UPGRADE=0.5, R_HEUR_USE_PLANET=0.2, R_HEUR_LEAVE_EMPTY=-0.2)
**Result:** 1000 iters completed (with restart at iter 280 after system reboot).

**Two distinct phases:**
- Iter 1-700: Healthy learning. Reward +1.5 → +4.85. Blind clear rate 6% → 46%.
  Shop action dist: buy0=28%, buy1=23%, leave=45%. Agent actually buying jokers.
- Iter 750+: **Complete collapse.** Both entropies hit 0.0. Shop steps dropped to 0.
  Reward plateaued at +7.99 with "100% clears" but 0 ante 2. Agent converged to fixed
  strategy: clear small+big blind, die on boss every time.

**What happened:** Play agent mastered "always play best combo" (action 45 at 97%).
Clears small/big blind reliably but can't beat boss (600 chips) without jokers. Shop
agent completely collapsed because it got zero data for hundreds of iterations. The
heuristic rewards gave signal when data existed but couldn't fix the volume problem.

**15x overcollection problem discovered:** Requested 4096 steps/iter but collected 61,452
due to asymmetric collection trying to meet min_shop_steps. PPO was processing 15x more
data than intended, wasting ~30s/iter on unnecessary gradient steps.

---

## Run 12 (various configurations — all failed)
Three sub-runs attempted to fix shop starvation with architectural changes:

**12a: Shop-focused workers + play rollout cap**
- Config: 8 play workers + 8 heuristic-play workers (scripted play, only collect shop data)
- Result: Workers crashed — bootstrap GAE tried to pass play obs to shop policy.
- Fix: Conditional bootstrap based on agent type.

**12b: Fixed bootstrap + entropy floors**
- Config: Same workers + ENTROPY_FLOOR_PLAY=0.3 + ENTROPY_FLOOR_SHOP=0.3
- Result: Play entropy oscillated wildly (0.02 ↔ 1.8). NaN losses by iter 40.
- What happened: Direct entropy floor penalty `(floor - entropy) * 2.0` destabilized
  gradient. Removed in favor of smooth coefficient ramp.

**12c: Smooth entropy ramp + no play floor**
- Config: Shop-focused workers, ENTROPY_COEFF_PLAY=0.01 (no floor), shop floor only
- Result: Reward stuck at +1.85, 0.2% blind clears. Heuristic workers generated short
  episodes that diluted the reward signal. Play agent trained on half the data (only 8
  workers contributing play rollouts).
- What happened: Shop-focused workers helped the shop agent (buy0=49%, sell0=20%) but
  starved the play agent. The worker split hurt overall performance vs Run 11.

---

## V5 Post-Mortem

### Why V5 failed

The dual-agent architecture created an **irreconcilable data imbalance**. The game's
natural play/shop step ratio is ~20:1, worsening as the play agent improves (longer
episodes = fewer shop resets). Every mitigation attempted had a corresponding cost:

| Fix Attempted | Helped | Hurt |
|---------------|--------|------|
| Min shop steps per iter | Shop got more data | Play overcollected 15x, slow iters |
| Shop-focused workers | Shop agent learned to buy | Play agent lost half its training data |
| Entropy floors (play) | Prevented play collapse | Fought natural gradient, degraded play |
| Entropy floors (shop) | Prevented shop collapse | Couldn't fix zero-data problem |
| Heuristic shop rewards | Dense signal for shop | Couldn't overcome data volume issue |
| Quality delta reward | Shorter credit horizon | Required shop data to compute |
| Leave penalty | Reduced leave-immediately bias | Agent pivoted to other no-ops |
| Force-reset on drought | Generated shop episodes | Reset episodes had $4 and no jokers |

### The fundamental tension

Play agent needs massive data (65k steps/iter) to learn. Shop agent needs data it
almost never gets organically (0.1% of steps). Capping play data starves play.
Dedicated shop workers dilute play training. There is no configuration of the
dual-agent architecture that satisfies both simultaneously.

### What would have been needed

For dual-agent to work, the shop agent would need to be **pretrained** before joint
training begins — either via supervised imitation of a heuristic, or by training a
single agent first (V6) and transferring its shop knowledge. This is exactly the
approach V6 enables as a future upgrade path.

### Bugs discovered during V5

1. **Combo scoring bug** (`env_v5.py:793`): `score_hand(cards, list(combo), gs)` passed
   wrong argument types. All combos scored 0. Root cause of runs 1-9 failing.
2. **j_card_sharp override** (`jokers/chips.py`): No-op stub overwrote misc.py's working
   implementation due to import order.
3. **_prev_quality not set on skip** (`env_v5.py`): Quality baseline wasn't initialized
   when skipping a blind entered the shop, causing wrong quality delta rewards.

### V5 is deprecated

V5 code is preserved in `env_v5.py` and `train_v5.py` for potential future use
(weight transfer from V6, pretrained shop agent experiments). Active development
moved to V6 (single agent with enhanced shop obs) on 2026-04-09.
