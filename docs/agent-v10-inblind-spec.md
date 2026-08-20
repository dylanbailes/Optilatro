# agent-v10-inblind-spec.md

**In-blind goal hierarchy & value farming (agent_v10)**
Status: Implemented — knobs confirmed 2026-08-18; this spec is the design record.
Location: moved from the repo root to `docs/agent-v10-inblind-spec.md`.
Milestone label: **M12** (tentative; follows M11 sim-perf audit + the HUMAN-FAIR pivot)

---

## 1. Problem statement

The agent does not fundamentally understand *why* a hand is played or a discard
is made. `decide_hand` today is a single-objective, score-only loop: it plays the
cheapest combo that clears the blind ("just enough"), or discards to raise the
best-play score's expected value. It has **no concept of value in the blind** —
no holding gold cards / blue seals at round end, no purple-seal discard farming,
no Faceless face-discard farming, no "win slower on purpose to extract economy."

The requester's mental model is a **tiered goal hierarchy**:

1. **Survive the blind.** Can we get out? In how many hands, and how hard is it
   to draw the hand that does it? This depends on both the owned jokers and the
   deck composition. If strong flat +Chips / +Mult jokers mean a mere Pair
   clears, then the remaining hands/discards are *surplus* and can be spent on
   value instead of score.
2. **Extract value in the blind.** Once survival is secured with margin, spend
   the surplus hands/discards on economy: hold gold cards and blue seals at
   round end, discard purple seals, play weaker gold-seal hands, farm Faceless
   (3-face discards). There is a standing trade-off: winning every blind ASAP
   leaves value on the table, but over-seeking value loses runs. Value farming
   must be conditional ("only if I can easily win; otherwise opportunistically").
3. **Hand-type consistency over the run.** Early antes: 5-card combos (flush,
   full house, straight) are strong because scoring comes mostly from the hand
   itself. Later antes: consistency with your draw and what your jokers need
   dominates, so pairs / two pairs are often correct.

**Outcome goal (requester, verbatim intent):** "Overall this should lead to less
ante-1 deaths, and far better economy which by consequence should lead to more
wins."

---

## 2. Current state (what exists today)

All in `vendor/balatro-rl/balatro_sim/agent_v9.py` (L0 heuristic).

- `decide_hand(game)` — Verdant sell → planet → tarot/spectral → just-enough play
  → discard EV → play best. Purely score/clear driven. When a play clears, it is
  played **immediately** (the round ends ASAP — the exact behavior this work
  changes).
- `best_discard(game, ...)` — human-fair expected-value discard over the known
  deck composition (sampled with a throwaway seed-0 RNG). Structure-aware pool.
- `reference_hand(game)` — RefHand(ceiling, typical, reach, base_c, base_t) for
  shop valuation.
- `scored_plays` / `best_play_score` / `eval_hand_score` — the isolated scoring
  oracle (side-effect-free on the live game; throwaway RNG).
- Shop-time econ valuation exists but is **joker-level only** (`econ_per_ante`,
  `gen_per_ante`, `lifecycle_bonus`, `power_tilt`). None of it reaches the
  in-blind play/discard decision.

The L1 search (`agent_l1.py`, comparative mean-measure) reuses L0's shop ranking
and `rollout.clone_game`. It does not model in-blind value either.

---

## 3. Sim fidelity: required fixes + seal/enhancement audit

Source of truth: `docs/reference/balatro-mechanics.md` §6 (Enhancements), §7
(Editions), §8 (Seals).

### 3.1 Confirmed bugs (blocking — these are directly implicated by the request)

| Thing | Doc says | Sim currently does | Fix |
|---|---|---|---|
| **Gold Seal** | "Earns $3 when this card is **scored**" (§8) | `$3 * gold_mult` when **held at round end** (`game._end_round`, the same branch as Gold enhancement) | Add `ctx.pending_money += 3` in `scoring._score_single_card` when `card.seal == "Gold"`; remove the Gold-seal branch from `_end_round`. |
| **Purple Seal** | "Creates a Tarot card when this card is **discarded**" (§8) | Adds a Tarot when the card is **played** (`game._play_hand`, `for c in selected`) | Move the grant to `game._discard` (fire on the discarded cards), keep the `PURPLE_SEAL_NODE` RNG and consumable-slot room check. |

Consequences to verify after fixing (now resolved):

- **Mime (`retriggers_held`)** must NOT double Gold Seal anymore (Gold Seal is a
  scored ability, not held — the `gold_mult` in `_end_round` should apply to Gold
  **enhancement** only).
- **Mime DOES double Blue Seal** (resolved): Mime = "retrigger all card held in
  hand abilities" (doc §2); Blue Seal = "held in hand at end of round" (doc §8).
  The Balatro wiki (fandom + balatrowiki) confirms Mime retriggers "gold cards,
  steel cards, and blue seals." So the `_end_round` Blue-seal loop must double
  the planet grant when any joker has `retriggers_held` (a NEW fix — §3.2 FIX-B).

### 3.2 Seal & enhancement audit (completed)

Sources: doc §6/§8 (authoritative for the sim), balatro-rs `core/src/game.rs`
(cross-ref — has divergences, do NOT follow them), Balatro wiki (resolves the
Mime / Red-seal "held" interactions the doc leaves implicit).

**Enhancements (doc §6):**

| Enhancement | Doc | Sim (`scoring.py` / `hand_eval.py`) | Verdict |
|---|---|---|---|
| Bonus | +30 chips scored | `_score_single_card` | ✓ |
| Mult | +4 mult scored | `_score_single_card` | ✓ |
| Wild | counts as every suit | flush via `_is_flush` (wilds → one suit); **suit-jokers use `card.suit == X` and miss Wild** | ⚠ gap W |
| Glass | ×2 mult, 1-in-4 destroy | ×2 in `_score_single_card`, shatter 1-in-4 (+Oops) | ✓ |
| Steel | ×1.5 held | held pass in `score_hand`, Mime doubles | ✓ (see note R) |
| Stone | +50, always scores, no rank/suit | `base_chips=50`, excluded from hand type, scores as kicker; **rank/suit-jokers still read its rank/suit** | ⚠ gap S |
| Gold | $3 held at round end | `_end_round`, Mime doubles | ✓ (balatro-rs pays per-hand — do NOT follow) |
| Lucky | 1-in-5 +20 mult, 1-in-15 +$20 | `_score_single_card` (+Oops) | ✓ |

**Seals (doc §8):**

| Seal | Doc | Sim | Verdict |
|---|---|---|---|
| Red | retrigger scoring AND held 1× | `scoring.py` retriggers the scored card only | ✗ FIX-R (add held retrigger — RULING-R) |
| Gold | $3 when scored | `_end_round` (held, `$3·gold_mult`) | ✗ FIX (§3.1) — scored + retriggered |
| Blue | planet of final hand, held at round end | `_end_round`, final-hand planet, **no Mime doubling** | ⚠ FIX-B |
| Purple | tarot when discarded | `_play_hand` (played) | ✗ FIX (§3.1) — discard |

**Findings to fold into the implementation milestone:**

- **FIX-B (Blue seal × Mime):** the `_end_round` Blue-seal loop grants one planet
  per Blue-sealed held card with no `retriggers_held` check. It must grant 2×
  when any owned joker has `retriggers_held` (the same flag the Gold enhancement
  already uses). Matches doc §2 Mime + wiki; balatro-rs is wrong to omit it.
- **RULING-R (Red seal "held" retrigger) — DECIDED: amend to the real game.** Doc
  §8's "scoring effects" is an under-specification, not a deliberate divergence:
  the real game, balatrowiki ("Red Seal retriggers both played and held in hand
  effects — Steel X2.25, Gold card $6"), and balatro-rs `trigger_count_held`
  (returns 2 for a Red-sealed held card) all retrigger HELD abilities. Ruling:
  **Red seal retriggers held-in-hand abilities exactly like Mime, per card.**
  Per-card trigger count for every held-in-hand ability (Steel, Gold card, Blue
  seal):
      triggers = 1 + (1 if any joker has `retriggers_held` else 0)
                   + (1 if card.seal == "Red" else 0)
  Directly attested: Steel X2.25, Gold card $6. Blue seal → 2 planets is the
  consistent extension (same held-retrigger class as Mime, confirmed to double
  Blue seal). Implementation:
    - `scoring.py` held-Steel pass: multiply X1.5 `triggers` times per held
      Steel (currently `1 + mime`).
    - `game._end_round` Gold-card loop: pay `$3 * triggers` per held Gold card
      (currently `$3 * gold_mult`, Mime-only).
    - `game._end_round` Blue-seal loop (FIX-B): grant `triggers` planets per
      held Blue-sealed card (currently 1).
  Caveat: `retriggers_held` is a boolean (any-Mime), so multi-Mime stacks to +1
  not +N — a pre-existing simplification out of scope here.
- **GAP-W (Wild × suit-jokers):** Wild counts as every suit, but suit-based
  jokers (Greedy/Lusty/Wrathful/Gluttonous, Rough Gem, Bloodstone, Ancient,
  Castle, Arrowhead, Onyx Agate) compare `card.suit == X` and miss Wild cards.
  Needs a `Card.matches_suit(suit)` helper honoring Wild (balatro-rs has
  `card.matches_suit`). P2 — broad sweep, not blocking value-farming.
- **GAP-S (Stone × rank/suit-jokers):** Stone "has no rank or suit," but
  rank/suit-jokers (Walkie Talkie, Even Steven, Odd Todd, Scholars, the
  suit-jokers) read `card.rank` / `card.suit` on Stone cards and would trigger
  on a Stone that happens to carry that rank/suit. `Driver's License` already
  excludes Stone (the real-game rule) but the exclusion isn't systematic. P2 —
  same helper sweep as GAP-W.

**balatro-rs divergences (recorded so they are NOT followed):** Gold card is
paid per-hand during scoring (real game/doc: round-end); Blue seal grants a
random planet (real game/doc: the final hand's planet); Red seal also retriggers
held abilities (this one matches the real game — see RULING-R).

---

## 4. Decisions (from the interview)

| Decision | Answer |
|---|---|
| **Where the code lives** | New `agent_v10` module (agent_v9 stays untouched as the A/B baseline). |
| **Decision model** | **Sequential tiers** — establish survival (with margin) first, then spend surplus on value; fall back to survival when it starts to fail. |
| **Survive check** | **Probabilistic P(clear)** — an estimate from deck composition only (human-fair, no draw-order peek). |
| **Farm gate** | **Parametric P(clear) threshold** — a tunable threshold gates value-farming; tuned/A-B'd on the seed bank. |
| **Value trigger set (v1)** | **Full economy set** (see §6), not just the core five. |
| **Draw difficulty** | **Analytic composition probability** (hypergeometric-style, exact & fast). |
| **Early-5-card / late-pair shift** | **Hybrid** — a weak default preference, overridden by the survive/value tiers. |
| **Hold-value modeling** | **Extend the eval oracle** — `eval_hand_score` (and/or its caller) returns the expected round-end hold value for the cards left in hand, alongside score. |
| **Constraints** | **Strictly human-fair** — P(clear) and value estimates are pure functions of deck composition; RNG-purity and seed-exactness invariants hold. |
| **Validation** | **Minimal** — A/B bench first; unit tests follow later. (Note: the §3.1 fidelity fixes still deserve at least targeted regression tests so the sim doesn't silently regress.) |
| **Econ metric** | **Telemetry bundle** — dollars, interest, econ-source $, tarots/planets generated; headline on win rate + ante-1 deaths. |
| **Benchmarking** | **New bench script** (`bench_agent_v10.py`), separate from `bench_v9.py`. |
| **Recovery** | **Abandon-farm trigger** — an explicit condition (P(clear) < floor) forces survival mode. |

---

## 5. Architecture

New file(s) under `vendor/balatro-rl/balatro_sim/`:

- `agent_v10.py` — the new policy (`class HeuristicV10`, `policy_name = "heuristic_v10"`),
  reusing the existing isolated scoring oracle (`scored_plays`, `best_play_score`,
  `eval_hand_score`, `reference_hand`, `_value_multiset`, `_sample_value_keys`,
  `main_hand_type`, `decide_consumable`, `maybe_use_planet`, `_structure_pool`,
  `_card_quality`) from `agent_v9.py` **by import** (no copy-paste; agent_v9 stays
  frozen as the baseline).
- `SearchShopV10(HeuristicV10)` — the L1 counterpart (RULING-L1): inherits the
  tiered in-blind decisions; keeps the comparative shop search unchanged.
- `bench_agent_v10.py` — the A/B harness (per-seed paired vs `heuristic_v9`), with
  the telemetry bundle (see §8).

The decision entry point `decide_hand` becomes a tier cascade:

```
decide_hand(game):
  1. Verdant sell / no-hand / planet / consumable  (unchanged from agent_v9)
  2. P_clear = estimate_clear_probability(game)      # NEW — §5.1
  3. if P_clear < ABANDON_FLOOR:                      # survive mode
         return tier1_survive(game)                   # §5.2
  4. if P_clear >= FARM_THRESHOLD:                    # value mode
         act = tier2_value(game)                      # §5.3
         if act: return act
         return tier1_survive(game)                   # nothing worth farming
  5. return tier1_survive(game)                       # default
```

### 5.1 `estimate_clear_probability(game)` (Tier 0 — the survive check)

A human-fair probability that the remaining target is cleared within the
remaining hands/discards, as a **pure function of deck composition** (no draw
order). Deterministic, order-independent, no RNG. Signature:

```
P_clear(h, d, T, H, M, jokers) ∈ [0, 1]
  h = hands_left, d = discards_left        (boss-modified)
  T = chips_target - chips_scored          (boss-modified target)
  H = held cards (the live hand)
  M = _value_multiset(game.deck)           (draw pile: (rank,suit,enh,ed,seal) → count)
  jokers = owned jokers (isolated oracle only)
```

**Step 1 — feasible hand types and their score.** For each hand type `ht` the
build can score (High Card … Straight Flush / Five of a Kind), compute the
expected one-hand score `S(ht)` via the isolated oracle on a representative hand
of that type (reuse `_type_candidates` + `eval_hand_score`, exactly as
`_best_drawable_hand` does). A type is *finishing* iff it clears within the hand
budget: `m_ht = ceil(T / max(S(ht), 1)) ≤ h`.

**Step 2 — seen budget.** The number of distinct draw-pile cards we can expect
to inspect across the blind:

```
fresh = min(N, d·k_d + (h − 1)·k_r)   # cards drawn from the pile over the blind
n     = |H| + fresh                    # total distinct cards seen (held + drawn)
  N   = Σ M  (draw-pile size)
  k_d = typical cards discarded per discard (default 3 — conservative; ≤ min(5, hs))
  k_r = typical refill per play after the first (default hs − 5 = 3 for a 5-card play)
```

`fresh` errs LOW by construction (typical, not maximal, discard/refill), so every
assembly probability below errs LOW → `P_clear` errs LOW → the survival gate is
conservative. `k_d` / `k_r` are tunable knobs.

**Step 3 — assembly probability `a_ht` (the *draw difficulty*).** The
hypergeometric probability that `fresh` fresh draws from `M` (plus what `H`
already holds, conditioned out) contain the support for `ht`. Per-type support
predicates, all closed-form (`hg≥k(c, N, n)` = hypergeometric CDF tail:
P(draw ≥ k of a rank/suit with `c` copies in `n` draws)):

- **K-kind** (Pair k=2 … Five of a Kind k=5):
  `a = P(∃ rank with ≥ k copies among the n seen cards)`,
  per-rank term `= hg≥k(c_r, N, fresh)`; combined by the Bonferroni union bound
  `min(1, Σ_r hg≥k(c_r, N, fresh))`.
- **Flush** (5 of one suit): same form over the 4 suits.
- **Straight**: `a = P(∃ a 5-consecutive-rank window all present)` =
  `1 − ∏_windows (1 − ∏_{r∈window} (1 − P(rank r absent in fresh draws)))`,
  including the A-2-3-4-5 wheel. Near-exact (windows are rank-disjoint).
- **Full House**: `P(∃ r1 with ≥ 3 AND ∃ r2 ≠ r1 with ≥ 2)`.
- **Straight Flush**: straight within one suit — rare; approximate as
  `a_straight · 4/13`, or omit from `Ω` (flagged for a later milestone).
- **High Card**: `a = 1` (always drawable).

**Step 4 — per-type clear probability.** Combine assembly × score-adequacy:

```
p_ht = a_ht                if m_ht == 1
p_ht = a_ht(fresh/m_ht)^m_ht   if m_ht ≥ 2   (m_ht independent assemblies)
p_ht = 0                   if not finishing (m_ht > h)
```

**Step 5 — combine (with explicit bias):**

- **Pessimistic base (what the gates use):** `P_clear = max_ht p_ht` — the best
  single *committed* strategy's success probability. It never double-counts the
  correlated hand types, so it under-estimates the true union — the correct
  direction for survival (under-estimating P(clear) means we farm only when
  genuinely safe).
- **Optimistic ceiling (diagnostic/telemetry only):**
  `P_clear⁺ = min(1, 1 − ∏_ht (1 − p_ht))` — the independence union bound.
  Record both to bracket the true value.

**Bias & calibration.** `farm_clear_threshold` / `abandon_clear_floor` (§10)
compare against the **pessimistic** `P_clear`. `draw difficulty = 1/a_ht`
(expected attempts to assemble `ht`) is the Tier-1 "how hard is it to draw that
hand" quantity, surfaced for telemetry and the surplus-hands count. Two
second-order bias notes, so the direction is explicit: the per-type `min(1, Σ …)`
union bound is an UPPER bound on "∃ rank/suit ≥ k" (optimistic — it can
over-state a pair's drawability); the final `max_ht` combine is the pessimistic
control that dominates at the gate. If a strictly conservative per-type value is
needed later, swap the union bound for the single-best-rank term (a lower bound)
or exact inclusion-exclusion. Boss modifiers adjust the inputs first: Wall ×4 /
Violet ×6 / Needle (1×, 1 hand) / Water (0 discards) / Mouth & Eye (hand-type
bans) / The Arm (halved base). This supersedes the crude `_reachability`
visibility proxy for the in-blind decision (shop valuation keeps `_reachability`
until a later milestone unifies them).

### 5.2 `tier1_survive(game)` (Tier 1 — get out of the blind)

The survival behavior, essentially today's `decide_hand` core but re-armed with
P(clear):

- Play the cheapest clearing combo when P(clear) says we are safe; else discard
  (reuse `best_discard`) / play the best hand with the existing hold-until-clear
  and good-hand rules.
- The "how many hands does it take / how hard to draw" quantity is surfaced here
  so surplus hands/discards can be counted for Tier 2.

### 5.3 `tier2_value(game)` (Tier 2 — extract value with the surplus)

Runs **only** when `P_clear >= FARM_THRESHOLD` (the §5 cascade). Returns a value
action (`{"type": "play", "cards": [...]}` / `{"type": "discard", "cards": [...]}`)
or `None` when nothing is worth farming (the caller falls through to
`tier1_survive`).

**"Hold" is not its own action — it is a property of a play.** A play candidate's
value = (play-trigger value of the cards it SCORES, §6 Play levers) + (held value
of the cards it LEAVES IN HAND, §5.5). The held term is realized only when the
play ENDS the round (score `>=` remaining target): that is the moment the
left-in-hand cards become "held at round end." A non-clearing play is mid-round
and its held cards can still be spent later, so its held term is 0 (v1 rule —
see the timing note below).

`tier2_value` ranks two action families against one shared guard:

**1. Play candidates.** The top-K `scored_plays` combos (K = `eval_topk_play`,
already computed by the cascade) UNION value-targeted combos built around the
valuable cards (a gold-seal / Lucky / Business-face / Rough-Gem-Diamond /
Ticket-Gold card, played as a cheap combo even if low hand-priority). For each:

```
play_value = Σ_scored play_trigger_value(card)                    # §6 Play levers
           + (expected_round_end_value(held) if clearing else 0)  # §5.5
```

`play_trigger_value(card)` per §6 (each `/10` → value points): Gold seal
`3·triggers_played`, Lucky `(20/15)·triggers_played`, Business
`1·triggers_played`/face, Rough Gem `1·triggers_played`/Diamond, Ticket
`4·triggers_played`/Gold, plus `4/10 · [hand_type == To-Do-List target]`.

**2. Discard candidates.** Subsets of the hand drawn from two pools:

- the structure-aware survival pool (`_structure_pool`) — **opportunistic**:
  value that rides a discard the survive tier would make anyway;
- the value-specific pool — a 3-face set (Faceless), target-rank cards (Mail),
  purple-sealed cards (Purple seal), one junk card (Trading) — **committed**.

```
discard_value = (5/10)·[faces ≥ 3]                 # Faceless
              + (5/10)·count(discard, target_rank)  # Mail-in Rebate
              + E[Tarot]·purple_cards(discard)      # Purple seal
              + (3/10)·[first discard of round]     # Trading Card
              + deck-thin value of Trading's destroy
```

**The guard (the standing trade-off).** Simulate each candidate on an isolated
copy (throwaway RNG, no live mutation) and re-estimate Survival P(clear) via
§5.1 for the resulting state. Drop any candidate with Survival P(clear) `<`
`ABANDON_FLOOR`. Additionally, **committed** candidates (value-specific-pool
discards, and plays the survive tier would not choose) must keep Farm P(clear)
`>=` `FARM_THRESHOLD` (clear with `farm_spare_hands` to spare) — the requester's
Faceless rule: farm a line only while "easily winning," else take the value only
if it happens to align.

**Ranking.** For every surviving candidate:

```
score = value_points + tier2_opp_bonus · [opportunistic]   # tier2_opp_bonus ≈ 0.02
```

Ties break by P(clear) (safer first), then by chip score. Return the argmax as
the action; return `None` if no candidate clears the guard, or if the max value
is 0 and it is not an aligned survive action (nothing to farm — the round just
gets cleared by the survive tier).

**Timing note (held term).** v1 realizes the held term only on a clearing play.
The flagged refinement is to also let a non-clearing play carry held value when
a round PLAN commits to holding those cards through the remaining hands (a plan,
not a per-decision snapshot).

Parameters (new, tunable): `tier2_opp_bonus` (0.02), `tier2_min_value` (0.0).

### 5.4 Tier 3 — hand-type preference (hybrid)

A weak default weight: 5-card combos (flush/full house/straight) favored at low
ante, pairs/two-pairs at high ante, interpolated like the existing lifecycle
curves. It is a **tie-break / prior only** — the survive and value tiers
override it. The primary late-game shift toward consistency should *emerge* from
P(clear) + draw difficulty + joker needs (a Pair build that Duo/Supernova reward
already scores it higher); the explicit weight only nudges ties.

### 5.5 Hold-value in the eval oracle (RULING-BLUE)

Extend the isolated scoring path so a play candidate returns
`(score, expected_round_end_value)`. `expected_round_end_value` is a
**dimensionless "value point"** — the same band `joker_value` uses (dollars ÷ 10,
fractional score gains, all added together). It is the sum over the cards LEFT
IN HAND at round end:

```
expected_round_end_value = Σ_held [ gold_card_term + blue_seal_term ]

gold_card_term = min(0.25, 3 · triggers / 10)      # $3 held → value points
blue_seal_term = triggers · planet_value(ht*)      # 0 when consumables full
triggers       = 1 + (1 if any joker has retriggers_held else 0)
                     + (1 if that card.seal == "Red" else 0)      # RULING-R
```

**RULING-BLUE — how a Blue-seal planet is valued (hand + run dependent):**

```
planet_value(ht*) = play_share(ht*) · Δ_level(ht*)

Δ_level(ht*)    = ( best_play_score(hand=ref.ceiling, level_override={ht*: +1})
                    − best_play_score(hand=ref.ceiling) ) / base
play_share(ht*) = 1.0                                     if ht* == main_hand_type(game)
                = run_hand_counts[ht*] / Σ run_hand_counts   otherwise
ht*             = main_hand_type(game) when committed (run_hand_counts[main] ≥ 2),
                  else the hand type of the best play on the reference hand
                  (what the agent would naturally play LAST — the Blue seal
                  planet keys off the FINAL hand played, which the agent steers).
```

- `Δ_level(ht*)` is the fractional score gain of one +1 planet level on the
  reference hand, measured through the oracle — one extra isolated eval with the
  hand type's planet level bumped by 1 (a new `level_override` hook on
  `best_play_score` / `eval_hand_score`, or the analytic chips/mult delta). It
  captures the hand's base chips/mult, its CURRENT level, and the jokers'
  `mult_mult` amplification, so a planet for a hand the build actually scores is
  worth more than a flat constant.
- `play_share(ht*)` is the run dependence: a planet for a hand type the run never
  plays contributes ~0 (matching the shop, which values a non-main planet at 0).
  The `main_hand_type` branch keeps the value anchored near the shop's existing
  ~0.08-0.10 main-planet constant early, then lets it grow/shrink with the build.
- `blue_seal_term` is 0 when `len(consumable_hand) >= consumable_slots` (no room
  → no planet, per doc §8 "must have room").
- Gold seal contributes nothing here (it is SCORED, not held — §3.1); its $3 is
  already in the score via `_score_single_card`.

The oracle stays side-effect-free on the live game and uses a throwaway seed-0
RNG where any randomness is involved (the existing `eval_hand_score` contract).
`decide_hand`'s live play path keeps the real scoring engine untouched.

### 5.6 L1 integration (RULING-L1)

**RULING: the in-blind tiers flow into L1 automatically via inheritance — they
are NOT L0-only.**

`SearchShopV9.decide` already delegates every non-shop state to
`HeuristicV9.decide` (`if st != State.SHOP: return super().decide(game)`), so its
in-blind behavior IS the L0 `decide_hand`. The shop search only wraps the SHOP
decision (comparative argmax over `_rank_shop_items`). The two are orthogonal.

Therefore:

- `SearchShopV10(HeuristicV10)` inherits the tier cascade (`decide_hand` →
  survive/value tiers) for free, and keeps the existing comparative mean-measure
  shop search unchanged. No shop-search change is needed for v1: the shop
  valuation composite (`_rank_shop_items`, `joker_value`, `econ_per_ante`,
  `lifecycle`) already prices economy jokers (Faceless / Mail / Reserved Parking
  …), so the shop already buys the enablers — v10 makes the in-blind decisions
  that EXTRACT that value.
- The `--search-shops N` knob stays orthogonal (it only controls how many early
  shop visits get the comparative search; the in-blind tiers apply on every hand
  regardless of `N`, and on `N = 0` which is pure L0-with-tiers).

**Benchmark implication.** The A/B now has four policies of interest:
`heuristic_v9` (baseline), `heuristic_v10` (L0 + tiers), `search_shop_v9`
(current flagship), `search_shop_v10` (L1 shop search + tiers). The headline is
`search_shop_v10` vs `search_shop_v9` (the flagship comparison — the user's goal
is measured on the strongest agent), with `heuristic_v10` vs `heuristic_v9` as
the tier-only isolation and the `farm_clear_threshold = 1.0` farming-off arm for
attribution (§10.3).

**Optional future (NOT v1):** a shop-side "value-farming synergy" term — e.g.
boost `joker_value` for econ/held enablers (Faceless, Mail, Reserved Parking,
blue-seal decks) because the new agent actually harvests them in-blind. Deferred:
the existing lifecycle/econ terms already price these jokers, and the in-blind
harvest is the v10 deliverable.

### 5.7 Boss interaction with the farm gate and tier2 (RULING-BOSS)

`estimate_clear_probability` already consumes boss-modified inputs (`h`, `d`, `T`,
`Ω`, `hs`) before the formula runs (§5.1). The farm gate and `tier2_value` then
inherit those inputs, so most bosses need no special code — but a few have
non-obvious interactions worth pinning down.

| Boss | Inputs modified | Farm-gate / tier2 effect |
|---|---|---|
| The Needle (`bl_needle`) | `h = 1` (1× target) | Committed farming auto-disables: Farm P(clear) = `P_clear(1 − spare_hands, …)` ≈ 0 for `spare_hands ≥ 1`, so only opportunistic discard-value that ALSO helps draw the single clearing hand survives. |
| The Water (`bl_water`) | `d = 0` | Discard candidates empty (§6 Discard levers have nothing to trigger); only Play + Hold levers remain. |
| The Mouth (`bl_mouth`) | `Ω` → one committed type | `P_clear` = max over single-type strategies (the type you commit to first); `ht*` for Blue seal is that one type (deterministic planet). |
| The Eye (`bl_eye`) | `Ω` restricted (no repeat types) | Multi-hand `P_clear` must use DISTINCT hand types per hand; play-trigger farming of one type is capped at once. |
| The Psychic (`bl_psychic`) | play size fixed 5 | `k_r = hs − 5` (always 5-card plays); no cheap 1-card "play the gold seal" — a gold-seal card must ride a 5-card hand; a <5 play wastes a hand. |
| The Wall (`bl_wall`) / Violet Vessel (`bl_violet`) | `T = 4×` / `6×` | `m_ht = ceil(T/S)` up → lower P(clear) → farming more conservative (automatic via the formula). |
| The Flint (`bl_flint`) | base chips/mult halved | `S(ht)` down → same as Wall (automatic). Flat jokers matter more (not halved). |
| The Arm (`bl_grim`) | played hand's level −1 (persistent) | Playing a hand type DE-LEVELS it → prefer NOT to replay the main hand type; play-trigger farming that repeats a type is punished. |
| The Hook (`bl_hook`) | discards 2 random unplayed cards after each play | **Held value is unreliable** — a gold/blue card left in hand may be Hook-discarded before round end. Discount `expected_round_end_value` by `(hs − 2)/hs` (the chance a held card survives the 2-of-hand discard), or conservatively zero it in v1. The Hook's forced discard goes to `spent` (NOT `_discard`), so it triggers NO discard-value joker and NO purple seal — pure downside to holding. |
| The Manacle (`bl_manacle`) | `hs − 1` | Smaller held set → less hold value; `k_r = hs − 5` shrinks. |
| Debuff bosses (Goad/Club/Window/Head/Plant/Pillar/Verdant) | certain cards debuffed | Debuffed cards are worth 0 in BOTH score and value: every §6 trigger must multiply by `[not debuffed]`, and `tier2` must not farm a debuffed card. **Sim gap to close:** `_end_round`'s Gold-card and Blue-seal loops currently ignore `debuffed` (Steel already checks it in `scoring.py`) — add the check. |

**Two structural rules** (no per-boss `boss_key` switch in `tier2_value`):

1. **The farm gate is entirely downstream of P(clear).** Because `tier2_value`
   re-estimates Survival/Farm P(clear) on an isolated copy after each candidate
   (§5.3), a boss that lowers P(clear) (Wall/Violet/Flint/Needle/Arm/Mouth/Eye)
   automatically tightens the gate. The one thing the gate needs beyond P(clear)
   is the **Hook held-value discount** (held value is not a P(clear) input, so
   the gate alone won't catch it).
2. **Debuffed = worthless** — a debuffed card contributes 0 to score and 0 to
   every value trigger; `tier2` candidates are built from non-debuffed cards only
   (matching the survive tier's boss filter, which already drops debuffed scoring
   cards).

**Secondary (money/consistency effects):** The Tooth (`bl_tooth`, −$1 per card
played) nets against play-trigger value — a gold-seal play of one card is +$3−$1
= +$2, but a 5-card value hand costs $5, so play-farming under Tooth should
subtract `1 × cards_played`. The Ox (`bl_ox`) zeroes money when you play the
run's most-played hand type — never farm by playing the most-played hand. Crimson
Heart (`bl_crimson`) disables one random joker per hand, discounting whatever
trigger depends on that joker (treat as an expected-value haircut).

**Recommendation:** implement bosses purely as input overrides (`h`, `d`, `T`,
`Ω`, `hs`, debuff set) plus the Hook held-value discount and the Tooth/Ox money
adjustments. Do NOT special-case boss keys inside the tier logic.

Source of truth: `docs/reference/balatro-mechanics.md`. `$` = economy; all in-blind
decisions that can be influenced by hold/play/discard are listed. (Verify each
hook/fidelity during the §3.2 audit; the sim's RNG nodes / pending-money /
pending-consumable mechanisms are the plumbing to reuse.)

Notation:

- `triggers_played(card) = 1 + [card.seal == "Red"] + [Hack / Sock & Buskin /
  Hanging Chad / Dusk retriggers on that card]` — the count of scoring passes,
  applied to every per-scored-card ability AND to joker `on_score_card` effects.
- `triggers_held(card) = 1 + [any joker has retriggers_held] + [card.seal ==
  "Red"]` (RULING-R) — applied to every held-in-hand card ability.
- Dollar returns map to value points via `min(0.25, $ / 10)` (the `econ_value`
  band), so they add directly into `joker_value` / the Tier-2 action rank.
- `E[Tarot] = mean_{k ∈ ALL_TAROTS} tarot_value(game, k)` (state-aware).
- `planet_value(ht*) = play_share(ht*) · Δ_level(ht*)` (RULING-BLUE).
- These are GROSS per-action returns; the P(clear) guard (§5.3, §10.1) decides
  whether the action is worth the hand/discard it spends.

### Discard levers (value per discard action)

| Trigger (key) | Effect | Expected return |
|---|---|---|
| Faceless (`j_faceless`) | $5 when the discard has ≥3 face cards | `5 · [faces(discard) ≥ 3]` |
| Mail-in Rebate (`j_mail`) | $5 per discarded card of the round's target rank | `5 · count(discard, target_rank)` (target rank is displayed) |
| Purple seal | 1 Tarot per Purple-sealed card discarded | `E[Tarot] · purple_cards(discard)` (0 when consumables full) |
| Trading Card (`j_trading`) | destroy a card + $3 on the FIRST discard of the round | `3 · [first discard of round]` (+ the deck-thin value of the destroyed junk) |

### Play levers (per scored card / hand, scaled by `triggers_played`)

| Trigger (key) | Effect | Expected return |
|---|---|---|
| Gold seal | $3 per trigger | `3 · triggers_played(card)` per Gold-sealed card scored |
| Lucky card | 1-in-5 +20 mult, 1-in-15 +$20 | `(20/15) · triggers_played(card)` $ per Lucky card scored (the +20-mult is a separate score term) |
| Business Card (`j_business`) | 1/2 × $2 per face played | `1 · triggers_played(card)` per face card scored |
| Rough Gem (`j_rough_gem`) | $1 per Diamond played | `1 · triggers_played(card)` per Diamond scored |
| Ticket (`j_ticket`) | $4 per Gold card played | `4 · triggers_played(card)` per Gold card scored |
| To Do List (`j_todo_list`) | $4 when the scored hand is the displayed target | `4 · [hand_type == target]` (once per hand) |

### Hold levers (per card left in hand at round end, scaled by `triggers_held`)

| Trigger (key) | Effect | Expected return |
|---|---|---|
| Gold card (enhancement) | $3 per trigger | `3 · triggers_held(card)` |
| Blue seal | planet of the FINAL hand, per trigger | `triggers_held(card) · planet_value(ht*)` (0 when consumables full) |
| Reserved Parking (`j_reserved_parking`) | 1/2 × $1 per face held | `0.5 · faces(held)` (once — a joker effect, not a card ability, so NO `triggers_held`) |

### Passive (round-end, no in-blind lever — for telemetry only)

| Trigger (key) | Effect | Expected $/round |
|---|---|---|
| Golden Joker (`j_golden`) | $4 at round end | 4 |
| Cloud 9 (`j_cloud_9`) | $1 per 9 in deck, round end | `count_9(deck+hand+spent)` |
| Satellite (`j_satellite`) | $1 per unique planet | `len(unique planets used)` |
| To the Moon (`j_to_the_moon`) | +$1 per $5 held | `dollars // 5` |
| Rocket (`j_rocket`) | $1 round end (+$2 boss) | `1 + 1·[boss]` |

Two precision notes:

- **Red seal is a multiplier, not a standalone trigger** — it adds +1 to
  `triggers_played`/`triggers_held` for the card it is on (RULING-R), scaling
  the Play and Hold returns above rather than producing its own row.
- **Card abilities scale with the trigger count; joker effects mostly don't.**
  Held/played CARD abilities (Gold card, Gold seal, Blue seal, Lucky) multiply by
  `triggers_*`. Joker `on_score_card` effects (Business Card, Rough Gem, Ticket)
  ALSO scale by `triggers_played` because they fire once per scoring pass. The
  remaining joker effects (Faceless, Mail-in Rebate, Trading Card, To Do List,
  Reserved Parking) fire once per action and do NOT multiply.

The three levers define the value strategies the agent can execute:

- **Hold** valuable cards out of the played hand (gold card, blue seal, faces
  for Reserved Parking).
- **Play** valuable cards deliberately ("play a weaker gold-seal hand" =
  deliberately scoring the gold-seal card in a low-scoring combo).
- **Discard** for value (Faceless face-triples, Mail target ranks, purple seals,
  Trading Card fodder).

---

## 7. Human-fair / correctness invariants (hard requirements)

1. No draw-order peek. P(clear), draw difficulty, and all value estimates are
   pure functions of the known composition (deck+hand+spent). The existing
   discard-EV sampler is the precedent.
2. RNG purity — any randomness uses a throwaway seed-0 RNG, never the run's
   stream. Seed-exactness and the `ci_gate` must stay green.
3. No live-game mutation from evaluation — reuse the isolated eval oracle.
4. Decisions must be order-independent (reversed/shuffled deck composition →
   byte-identical decision), provable by a dedicated test when tests are added.

---

## 8. Benchmarking & telemetry

- `bench_agent_v10.py`: per-seed paired A/B vs `heuristic_v9` on the existing
  300-seed bank (and a larger 1000-seed run once stable), mirroring `bench_v9.py`
  conventions (`--games`, `--batch-size` progress, seed-mode determinism).
- **Telemetry bundle** recorded per run, then aggregated:
  - win (ante-8 clear) / death ante / death blind kind / steps
  - dollars (end of run), total interest collected
  - **econ-source $** (sum of $ earned from seals / gold / econ jokers —
    isolated from blind rewards) — the "better economy" headline
  - tarots / planets / spectrals generated (incl. purple/blue seal grants)
  - ante-1 death count (the regression headline)
- Success criteria: ante-1 deaths down, econ-source $ and interest up, mean ante
  up, win rate up — with no per-seed regression where the tiers are pure
  valuation (paired A/B, like M9/M10's methodology).

---

## 9. Validation

Per the requester: **minimal** — A/B bench first, unit tests later. Recommended
(not blocking the spec) minimums once tests are written:

- §3.1 seal fixes: Gold Seal scored (+$3, not at round end), Purple Seal
  discard (not play) — these change sim behavior and deserve a regression test
  each so the fidelity work isn't silently re-broken.
- P(clear) order-independence; farm gate (below/above threshold); abandon-farm
  trigger recovery; hold-vs-play value choice; Tier-3 hand-type preference.

The four static audits (joker/consumable/boss/tag) and `ci_gate` must stay clean.

---

## 10. FARM_THRESHOLD / ABANDON_FLOOR — defaults & A/B sweep plan

### 10.1 P(clear) definition (anchors the thresholds)

`P_clear(n_hands, n_discards)` = probability the remaining blind target
(`chips_target - chips_scored`) is reached within `n_hands` played hands and
`n_discards` discards, as a **pure function of the known deck composition**
(deck+hand+spent) and the owned jokers. Computed analytically (hypergeometric)
over the card-value multiset `_value_multiset`, with hand scores from the
isolated oracle applied on the typical/expected card support. Deterministic,
order-independent, no draw-order peek (invariants from §7).

Three derived quantities:

- **Survival P(clear)** = `P_clear(hands_left, discards_left)` — "can we get out
  at all" (Tier 1's first question, and the **abandon-farm trigger**).
- **Farm P(clear)** = `P_clear(hands_left - farm_spare_hands, discards_left)` —
  "can we clear with a hand to spare" — the **enter value mode** signal.
  Reserving a hand means a knife's-edge clear never reads as "safe to farm".
- **Action-level P(clear)** = `P_clear(hands_left - 1, discards_left - used)`
  re-estimated after each candidate value play/discard — the standing-tradeoff
  guard inside Tier 2: a value action is taken only if it keeps Survival
  P(clear) `>= abandon_clear_floor`.

### 10.2 Defaults

| Param | Default | Meaning |
|---|---|---|
| `farm_clear_threshold` | **0.90** | Enter value mode when Farm P(clear) `>=` this. High on purpose — "only farm when easily winning" (the requester's Faceless framing). |
| `abandon_clear_floor` | **0.75** | Hard-survive when Survival P(clear) `<` this — the abandon-farm trigger. Below the threshold it leaves a ~0.15 hysteresis band that stops farm/survive oscillation. |
| `farm_spare_hands` | **1** | Hands reserved when measuring Farm P(clear) — the "clear with a hand to spare" knob. |

**SWEEP COMPLETE (2026-08-18, `tools/sweep_v10.py` → `results/sweep_v10.md`):**
the §10.3 calibration ran to completion and **the defaults above are the
recorded winner** — confirmed rather than moved. 300-seed ladder: `spare=1`
(5.00% win; spare 0/2 = 3.67/4.67%) → `threshold=0.90` (5.00%; 0.70/0.80/0.95
= 4.00/4.67/4.67%) → `floor=0.75` default (0.50-0.70 all 4.67%, 0.80 ties at
5.00% but with a ZERO hysteresis band → rejected per §10.4). The 2×2
interaction and the 1000-seed confirm: default and the zero-hysteresis
`x2_80_80` are statistically indistinguishable (44 vs 45 wins/1000, identical
econ $14.1/interest $14.9), so the hysteresis-preserving default wins. Farming
attribution at 1000 seeds (farmoff == v9 byte-for-byte): **+0.3-0.4pp win,
-3/4 ante-1 deaths, +$3.6 econ-source $/run**. Success gate ✓ (ante-1 deaths
never worse, econ-source +31-34%, win rate >= baseline at both sample sizes).

**TIER2-KNOB SWEEP COMPLETE (2026-08-18, `tools/sweep_v10.py --tier2-only` →
`results/sweep_v10_tier2.md`):** the two remaining tunables are also confirmed
at their defaults. `tier2_min_value` = 0.0 is **strictly optimal** — raising the
gate degrades monotonically (0.0 → 5.00% win/$13.8 econ, 0.10 → 4.00%/$13.3,
0.25 → 3.33%/$10.8, 0.50 → 3.00%/$10.7 at 300 seeds): every small value action
is worth its hand/discard cost, so the default stands. `tier2_opp_bonus` is
**inert within noise** — 0.00/0.02/0.05 all 15/300 = 5.00% (the mechanical
picker chose 0.00 only on a $0.2-0.3/run econ tie-break; the 1000-seed confirm
cross-checks: opp_bonus=0.0 posts 4.30%/105/$14.2 vs the §10.3 default confirm
at opp_bonus=0.02's 4.40%/105/$14.1 — 43 vs 44 wins/1000, within noise). The
code keeps the **documented 0.02** (no statistical reason to churn; the bonus
biases ties toward free opportunistic value). Net: **all five knobs at their
§10.2/§5.3 defaults are the recorded optimum** — no code change from either
sweep.

Relationship: `abandon_clear_floor = farm_clear_threshold - 0.15` by default
(kept as an explicit knob so the band is independently tunable). Both thresholds
sit far above the coin-flip midpoint by design: the #1 outcome is **fewer ante-1
deaths**, so farming must never be the cause of a death.

### 10.3 A/B sweep plan

All runs on `bench/bench_agent_v10.py` (new), per-seed paired `heuristic_v9`
(frozen baseline) vs `heuristic_v10` on the same 300-seed bank (seeds 0..299),
rng_mode=seed. `--params '{...}'` overrides only the v10 knobs (v9 ignores
unknown keys). Headline per run: ante-1 deaths, win rate, mean ante, and the
§8 telemetry bundle (econ-source $, interest, tarots/planets generated).

The **farming-off arm is the key control**: `farm_clear_threshold = 1.0` turns
value-farming off while keeping the P(clear) survive tier + the hand-type hybrid,
so the *value-farming contribution* is isolated from the rest of the rework.

```bash
# Phase 1 — 1-D calibration (300 seeds each; fix two, sweep one)
# 1a. farm_spare_hands  (threshold 0.90 / floor 0.75 fixed)
python bench/bench_agent_v10.py --games 300 --policies heuristic_v9,heuristic_v10 \
    --params '{"farm_spare_hands": 0}'   # then 1, then 2

# 1b. farm_clear_threshold  (floor = threshold - 0.15; spare = winner of 1a)
python bench/bench_agent_v10.py --games 300 --policies heuristic_v9,heuristic_v10 \
    --params '{"farm_clear_threshold": 0.80}'   # sweep 0.70/0.80/0.90/0.95

# 1c. abandon_clear_floor  (threshold = winner of 1b; spare = winner of 1a)
python bench/bench_agent_v10.py --games 300 --policies heuristic_v9,heuristic_v10 \
    --params '{"abandon_clear_floor": 0.70}'    # sweep 0.50/0.60/0.70/0.80
```

| Phase | Knobs swept | Grid | Pick |
|---|---|---|---|
| 1a | `farm_spare_hands` | {0, 1, 2} at default t/f | default spare |
| 1b | `farm_clear_threshold` | {0.70, 0.80, 0.90, 0.95} | default threshold |
| 1c | `abandon_clear_floor` | {0.50, 0.60, 0.70, 0.80} | default floor |
| 2 | threshold × floor | top-2 each (2×2 = 4 runs) | interaction check |
| 3 | winner vs baseline + farming-off arm | 1000 seeds | confirm |

Success gate (Phase 3, 1000 seeds):

- ante-1 deaths: winner `<=` baseline (never worse — this is non-negotiable)
- econ-source $/run and interest/run: materially higher
- win rate: `>=` baseline within noise (1000 seeds ≈ ±2-3pp at current rates)

A threshold that adds ante-1 deaths but doesn't lift econ-source $ is rejected
regardless of win rate — the trade-off is one-directional: value is only worth
farming when survival is not put at risk.

### 10.4 Notes

- Ante-1 is the acid test (targets 300/450/600, 4 hands + 3 discards): raw
  Survival P(clear) at blind start can read high because a full round is many
  draw attempts — the `farm_spare_hands` reservation is what keeps ante-1
  farming from reading "safe" too early.
- Keep the hysteresis band `>= 0.10`; below that the agent can flip between
  farm/survive every decision and the telemetry becomes unreadable.

---

## 11. Open questions / follow-ups

- (Resolved → §10) `farm_clear_threshold` / `abandon_clear_floor` defaults + A/B sweep.
- (Resolved → §10.2) `tier2_opp_bonus` / `tier2_min_value` sweep — `min_value=0.0` strictly optimal, `opp_bonus` inert within noise; both defaults kept.
- (Resolved → §3.2 FIX-B) Mime DOES double Blue seal; add `retriggers_held` to the Blue-seal loop.
- (Resolved → §3.2 RULING-R) Red seal retriggers held abilities — doc §8 amended + sim per-card `1 + Mime + Red` trigger count.
- (Resolved → §5.6 RULING-L1) The tiers flow into L1 by inheritance: `SearchShopV10(HeuristicV10)`; shop search unchanged; headline A/B is `search_shop_v10` vs `search_shop_v9`.
- Whether Tier 2 should hold value **across** the last hand (when holding gold
  means *not* playing the winning hand, needing a spare hand to still clear).
- (Resolved → §5.5 RULING-BLUE) Blue-seal planet = `play_share(ht*) · Δ_level(ht*)`, hand + run dependent.

---

## 12. Implementation plan (ordered, with dependencies)

Critical path: **sim fixes → oracle hook → P(clear) → tier1 → tier2 → cascade →
bench**. Tier 3 (hand-type prior) and the bench harness are parallelizable (no
dependencies). Each phase has a "done when" checkpoint; the full suite, `ci_gate`,
and the four static audits stay green throughout.

**Headline risk:** the Purple-seal fix (0.2) moves a `PURPLE_SEAL_NODE` draw from
play-time to discard-time, so the seed-exactness golden pins and any per-seed
baselines SHIFT — re-derive the pins and re-baseline in the same change. The
other Phase-0 fixes are deterministic (no RNG movement).

### Phase 0 — Sim fidelity (blocking; §3.1, §3.2)

| # | Step | Notes / done-when |
|---|---|---|
| 0.1 | Gold seal → scored: `ctx.pending_money += 3` in `_score_single_card` when `seal == "Gold"`; remove the `_end_round` Gold-seal branch | Deterministic. Test: pays on score (and on retriggers), not round end. |
| 0.2 | Purple seal → discard: move the tarot grant from `_play_hand` to `_discard` | **Shifts RNG** (see headline risk). Test: tarot on discard, not play. |
| 0.3 | FIX-B: Blue seal × Mime — grant `triggers_held` planets in `_end_round` | Deterministic. Test: Mime doubles blue-seal planets. |
| 0.4 | RULING-R: Red seal held retrigger — `triggers = 1 + Mime + Red` in the held-Steel pass + Gold-card + Blue-seal loops | Deterministic. Test: red-sealed held Steel X2.25 / Gold card $6. |

Checkpoint: sim-fix tests pass; seed-exactness re-pinned; audits + `ci_gate` clean.

### Phase 1 — Oracle hook (RULING-BLUE; §5.5)

| # | Step | Depends on |
|---|---|---|
| 1.1 | `level_override={ht: +1}` on `best_play_score` / `eval_hand_score` (or analytic chips/mult delta) | 0 |
| 1.2 | `expected_round_end_value(held)` — gold card + blue seal + Reserved Parking, using `triggers_held` | 0, 1.1 |

Checkpoint: hand-crafted cases return the correct held value (gold card × Mime/Red, blue seal with a known `planet_value`).

### Phase 2 — P(clear) (§5.1)

| # | Step | Depends on |
|---|---|---|
| 2.1 | `estimate_clear_probability(game)` — the 5-step hypergeometric formula | 0 (accurate `S(ht)`), the isolated oracle |

Checkpoint: order-independence (reversed deck → identical P(clear)); sanity
(monotonic in hands/discards; →1 when the deck fits in hand; →0 when no finishing
hand type exists).

### Phase 3 — Tier 1 survive (§5.2)

| # | Step | Depends on |
|---|---|---|
| 3.1 | `tier1_survive(game)` — v9's `decide_hand` core re-armed with P(clear) | 2 |

Checkpoint: with farming off (`farm_clear_threshold = 1.0`), tier1 reproduces
v9's `decide_hand` decisions (no in-blind regression).

### Phase 4 — Tier 2 value + Tier 3 prior (§5.3, §5.4, §6)

| # | Step | Depends on |
|---|---|---|
| 4.1 | `tier2_value(game)` — enumerate / guard / rank | 0, 1.2, 2 |
| 4.2 | Tier 3 hand-type prior (independent) | — (parallelizable) |

Checkpoint: farming-off arm (threshold = 1.0) byte-matches tier1; farming-on
picks the correct hold/play/discard on scripted states.

### Phase 5 — Cascade + policies (§5, §5.6)

| # | Step | Depends on |
|---|---|---|
| 5.1 | `HeuristicV10.decide` — the §5 cascade + farm params (`farm_clear_threshold`, `abandon_clear_floor`, `farm_spare_hands`) | 3, 4 |
| 5.2 | `SearchShopV10(HeuristicV10)` — shop search unchanged (RULING-L1) | 5.1 |

### Phase 6 — Bench + telemetry + sweep (§8, §10.3, §5.6)

| # | Step | Depends on |
|---|---|---|
| 6.1 | `bench_agent_v10.py` + the §8 telemetry bundle | 5 (scaffoldable earlier with stubs) |
| 6.2 | Four-policy matrix + `--params` farm-threshold override | 6.1 |
| 6.3 | Run the §10.3 sweep (spare_hands → threshold → floor → 2×2 → 1000-seed) | 6.2 |

### Phase 7 — Validation (deferred per "minimal"; recommended minimums)

| # | Step | Depends on |
|---|---|---|
| 7.1 | Regression tests for the Phase-0 sim fixes | 0 (recommended even in minimal mode) |
| 7.2 | P(clear) order-independence; farm gate; tier2 ranking; tier3 prior | 2, 4 (follow-up) |

**Parallelization.** Tier 3 (4.2), the bench scaffold (6.1), and the sim-fix
tests (7.1) can all proceed off the critical path. The two unavoidable serial
links are **0 → 1 → 4.1** (correct triggers → correct value formulas → tier2)
and **2 → 3 → 5.1** (P(clear) → survive tier → cascade).
