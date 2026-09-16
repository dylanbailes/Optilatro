"""collect_decisions.py — paired counterfactual decision collector (v2).

WHAT IT MEASURES
================
At a real decision point of a shipped-parity run, fork the seed-exact game and
run two arms from the SAME state:

    acquire arm : force the candidate acquisition, then rollout the policy
    policy arm  : rollout the policy unchanged (skip the candidate)

Because both arms are forked from one state, they share the run's entire prior
random stream (common random numbers), so the contrast

    y_raw   = won_acq   - won_skip          (primary; base rate ~14%)
    d_ante  = ante_acq  - ante_skip         (control variate, fit-time only)

cancels the shop/deck luck the two arms have in common. That is what makes a
per-item, per-scenario number measurable at ~4k runs/hour instead of a curated
guess.

DECISION MODES
==============
  shop    : SHOP state. Candidates are unsold, affordable shop items of any
            kind (joker / voucher / booster / card).
  booster : BOOSTER_OPEN state. Candidates are the pack's offered items —
            this is where tarots, spectrals and planets are actually chosen,
            so it is the only way their values can be learned in-scenario.

CANDIDATE MODES (--candidate-mode)
==================================
  coverage : rank candidates by coverage-work-order shortfall. This is the
             corpus to date, and it measures the items that are
             UNDER-MEASURED — the right rule for learning what an item is
             worth, and the wrong rule for learning which item to buy.
  onpolicy : fork the pair the RUNTIME ORACLE weighs, by calling
             `SearchShopV12._oracle_prior` itself rather than re-deriving its
             pool. Each row carries a `role`:
                 pick        the item the frozen search buys (the anchor)
                 substitute  what the learned prior swaps in for it
                 model_alt   the head's own preference, tie window ignored
                 coverage    work-order fill, as in `coverage` mode
             Shop decisions spend their budget on pick + the alternative
             first; pack decisions stay coverage-driven, because the prior only
             acts on shops.

WHY ONPOLICY EXISTS, measured on the v1..iter1 corpus (11,986 rows / 6,429
decisions): 47.4% of decisions are label-silent — every candidate measured
equivalent — so no ranker can score them; and the labels that do exist describe
candidates chosen for being under-measured. The prior's pool is "offers within
`margin` of the pick's own ranker value", so in (pick, alternative) terms the
corpus was mostly describing pairs the oracle never weighs. `model_alt` exists
to answer the question the 100-200 seed screens kept buying and never resolving:
does the head's preference carry information OUTSIDE the near-tie window? If it
does, the window is too narrow; if it does not, the fix is a better gate, not a
wider one. `tools/fit_value_model.py`'s `intervention` report section reads
these rows without refitting anything.

ARMS ARE ATTEMPTED AND VERIFIED, NEVER ASSUMED
=============================================
Eligibility for a purchase lives in the sim (slot limits, Negative editions,
per-zone rules). Rather than re-implement those rules here — a second copy
that would drift — the collector attempts the forced action, then verifies the
game state actually changed. A rejected attempt is recorded with ``arm_ok=0``
and is excluded from fitting.

HUMAN-FAIR / READ-ONLY
======================
The collector only ever forks copies; the live run is stepped by the policy
and never mutated by the instrumentation, so its RNG stream is untouched.
Features come from `value_tables.decision_features` — the same function the
runtime uses, so train/serve skew is structurally impossible.

OUTPUT  results/decisions/<split><tag>.jsonl
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import multiprocessing as mp
import random
import sys
import time
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENDOR = ROOT / "vendor" / "balatro-rl"
sys.path.insert(0, str(VENDOR))

from balatro_sim.game import BalatroGame, State               # noqa: E402
from balatro_sim.rollout import rollout                        # noqa: E402
from balatro_sim.seed_rng import make_source                   # noqa: E402
from balatro_sim.agent_v11 import SearchShopV11                # noqa: E402
from balatro_sim.agent_v10 import (                            # noqa: E402
    evaluate_shop_value, extract_game_features,
    formulate_counterfactual_state)
from balatro_sim import catalogue as CAT                        # noqa: E402
from balatro_sim import value_tables as VT                      # noqa: E402

OUT_DIR = ROOT / "results" / "decisions"
COLLECTOR_VERSION = 3

SHOP_KINDS = ("joker", "voucher", "booster", "card")

# ── candidate selection modes ───────────────────────────────────────────────
# `coverage` ranks candidates by coverage-work-order shortfall, which is how the
# whole corpus was built: it measures the items that are UNDER-MEASURED. That is
# the right rule for learning what an item is worth, and the wrong rule for
# learning which item to buy, because it never asks what the policy buys or what
# the oracle compares it against.
#
# `onpolicy` forks the pair the RUNTIME ORACLE actually weighs: the item the
# frozen search would buy, plus the item the learned prior would substitute for
# it. The substitution comes from calling `SearchShopV12._oracle_prior` itself --
# the collector does not re-derive the oracle's pool, so there is no second copy
# of that logic to drift from the shipped one.
#
# WHY IT MATTERS, measured on the v1..iter1 corpus (11,986 rows / 6,429
# decisions): 47.4% of decisions are label-silent (every candidate measured
# equivalent), so no ranker can score them; and the labels that do exist
# describe candidates chosen for being under-measured. The prior's pool is
# "offers within `margin` of the pick's own ranker value", so in (pick,
# alternative) terms the corpus was mostly describing pairs the oracle never
# weighs.
CANDIDATE_MODES = ("coverage", "onpolicy")

# The oracle configuration the collector replays. These must match the arm being
# screened, or the collector forks a pair the arm never considers. Defaults are
# the best-measured arm so far: `v12_prior_m02` (margin 0.02, five kinds),
# +7 net wins over 300 paired seeds across four banks.
ORACLE_MARGIN = 0.02
ORACLE_KINDS = ("joker", "tarot", "spectral", "planet", "voucher")

# A coverage work-order cell with shortfall 1.0 is a cell with ZERO evidence
# (shortfall is (required_n - n) / required_n). Meeting this threshold means
# "this offer includes something the model has never measured", which forfeits
# the sampling coin and the per-ante allowance: compute goes to ignorance.
FOCUS_FORCE_AT = 1.0


def _policy():
    """Shipped-parity policy (V11 with v11_shop_v10_l1, learned hooks off)."""
    return SearchShopV11()


# ────────────────────────────────────────────────────────────────────────────
# Candidate normalisation
# ────────────────────────────────────────────────────────────────────────────
#
# The sim exposes three different shapes for offered items:
#   shop item objects   : .kind in {joker,voucher,booster,card}, .key, .price
#   booster tuple       : ("joker", key, edition) or ("card", <Card>)
#   booster plain str   : a planet / tarot / spectral key
# `Cand` normalises all three so the shared feature builder
# (value_tables.decision_features) sees one interface — the alternative would
# be a second feature path for packs, i.e. exactly the train/serve skew the
# shared builder exists to prevent.


@dataclasses.dataclass
class Cand:
    idx: int
    kind: str
    key: str
    price: int = 0
    edition: str = "None"
    enhancement: str = "None"
    seal: str = "None"

    def discounted_price(self, discount: float = 0.0) -> int:  # noqa: ARG002
        return int(self.price)


def _wrap(idx: int, kind: str, key: str, price: int, src=None) -> Cand:
    return Cand(
        idx=idx, kind=kind, key=key, price=int(price),
        edition=str(getattr(src, "edition", "None") or "None"),
        enhancement=str(getattr(src, "enhancement", "None") or "None"),
        seal=str(getattr(src, "seal", "None") or "None"),
    )


def _shop_candidates(game) -> list[Cand]:
    """Affordable, unsold shop items of any kind."""
    out: list[Cand] = []
    dollars = float(getattr(game, "dollars", 0) or 0)
    discount = float(getattr(game, "shop_discount", 0.0) or 0.0)
    for i, item in enumerate(getattr(game, "current_shop", []) or []):
        if getattr(item, "sold", False):
            continue
        kind = str(getattr(item, "kind", "") or "")
        if kind not in SHOP_KINDS:
            continue
        try:
            price = int(item.discounted_price(discount))
        except Exception:
            price = int(getattr(item, "price", 0) or 0)
        if price > dollars:
            continue
        out.append(_wrap(i, kind, str(getattr(item, "key", "") or ""), price, item))
    return out


def _booster_candidates(game) -> list[Cand]:
    """The items offered by an open pack, normalised — and receivable.

    A pack opened with full slots offers items the sim will refuse, and a
    refused arm costs a fork to discover. Measured on iteration 2: ~30% of
    pack arms were dropped as `arm_ok=0`, i.e. roughly a sixth of all
    collection compute spent proving that a full joker slot is still full.
    Filtering here is the same gate the sim applies, applied earlier.
    """
    out: list[Cand] = []
    joker_room = len(getattr(game, "jokers", []) or []) < int(game.joker_slots)
    cons_room = (len(getattr(game, "consumable_hand", []) or [])
                 < int(game.consumable_slots))
    for i, choice in enumerate(getattr(game, "booster_choices", []) or []):
        if isinstance(choice, tuple) and len(choice) >= 2 and choice[0] == "joker":
            if not joker_room:
                continue
            out.append(_wrap(i, "joker", str(choice[1]), 0,
                             Cand(i, "joker", str(choice[1]),
                                  edition=str(choice[2] if len(choice) > 2 else "None"))))
        elif isinstance(choice, tuple) and len(choice) >= 2 and choice[0] == "card":
            card = choice[1]
            out.append(_wrap(i, "card", "card", 0, card))
        elif isinstance(choice, str):
            it = CAT.item(choice)
            kind = it.kind if it is not None else "unknown"
            if kind in ("tarot", "spectral", "planet") and not cons_room:
                continue
            out.append(_wrap(i, kind, choice, 0))
    return out


# ────────────────────────────────────────────────────────────────────────────
# Forced-arm execution with verification
# ────────────────────────────────────────────────────────────────────────────


def _sig(game) -> tuple:
    return (
        int(getattr(game, "dollars", 0) or 0),
        len(getattr(game, "jokers", []) or []),
        len(getattr(game, "consumable_hand", []) or []),
        int(getattr(game, "booster_picks_remaining", 0) or 0),
        len(getattr(game, "booster_choices", []) or []),
        int(getattr(game, "hand_level_total", 0) or 0),
    )


def _force_arm(game, mode: str, idx: int):
    """Fork, force the acquisition, verify it took.

    Returns (game|None, applied, why). `why` exists because a rejected arm is
    otherwise indistinguishable from a bug: the row is dropped and only a
    counter moves. Recording the reason turns that counter into a diagnosis.
    """
    fork = deepcopy(game)
    before = _sig(fork)
    action = ({"type": "buy", "item_idx": idx} if mode == "shop"
              else {"type": "pick_booster", "indices": [idx]})
    try:
        fork.step(action)
    except Exception as exc:
        return None, False, type(exc).__name__
    applied = _sig(fork) != before
    return fork, applied, ("" if applied else "no_state_change")


# ────────────────────────────────────────────────────────────────────────────
# Collection
# ────────────────────────────────────────────────────────────────────────────


# ────────────────────────────────────────────────────────────────────────────
# On-policy candidate selection (the pair the runtime oracle weighs)
# ────────────────────────────────────────────────────────────────────────────

_ORACLES: dict = {}
_TABLE = None
_TABLE_TRIED = False
# Why the oracle declined, counted. A silent `except` here would make "the pool
# was empty" and "the code raised" identical in the output -- which is the same
# failure mode as the rejected-arm counter that had no reasons.
_ORACLE_ISSUES: dict = {}


def _note_issue(why: str) -> None:
    _ORACLE_ISSUES[why] = _ORACLE_ISSUES.get(why, 0) + 1


def _table():
    """The fitted artifact, or None. Cached; a missing artifact is not fatal:
    the collector still runs, it just cannot fork the model's own preference."""
    global _TABLE, _TABLE_TRIED
    if not _TABLE_TRIED:
        _TABLE_TRIED = True
        try:
            _TABLE = VT.load()
        except Exception as exc:
            _note_issue(f"table:{type(exc).__name__}")
            _TABLE = None
    return _TABLE


def _model_alt(game, cands, exclude, kinds: tuple):
    """The learned head's own preferred alternative, ignoring the tie window.

    Role `model_alt` is the row that answers the question the margin sweep
    cannot answer with a 150-seed screen: does the head's preference carry
    information OUTSIDE the near-tie window? If yes, the window is too narrow
    and there are interventions the arm is not taking; if no, the prior is at
    its ceiling and the fix is a better gate, not a wider one.

    Restricted to the arm's own kinds and to affordable unsold shop items, so a
    `model_alt` row is always something the policy COULD have bought. That is
    the difference between this and the retired `override` arms, which are
    measured offline here instead of bought at 150 seeds per question.
    """
    table = _table()
    if table is None:
        return None
    best, best_s = None, None
    for c in cands:
        if c.idx in exclude or c.kind not in kinds:
            continue
        try:
            s = float(table.relative_of(game, c))
        except Exception as exc:
            _note_issue(f"score:{type(exc).__name__}")
            continue
        if best_s is None or s > best_s:
            best, best_s = c, s
    return best


def _oracle(margin: float, kinds: tuple):
    """The shipped prior itself, cached per (margin, kinds) per process.

    Imported lazily: `tools/` must stay runnable when the learned artifact has
    not been fitted yet, and the oracle is only needed in `onpolicy` mode.
    """
    key = (float(margin), tuple(kinds))
    if key not in _ORACLES:
        from balatro_sim.agent_v12 import SearchShopV12
        _ORACLES[key] = SearchShopV12(params={
            "v12_oracle": True, "v12_mode": "prior", "v12_head": "relative",
            "v12_prior_margin": float(margin), "v12_kinds": tuple(kinds)})
    return _ORACLES[key]


def _onpolicy_choice(game, act, cands, policy, margin: float,
                     kinds: tuple) -> tuple[list, int, int]:
    """The candidates the oracle actually weighs, in priority order.

    Returns ([(Cand, role)], offered, substituted). `offered`/`substituted` are
    per-decision deltas of the oracle's own counters, so a row can record not
    just what it measured but whether it was in a decision the oracle acted on
    -- which is what lets the next work order target those decisions.

    The pick is always included when the policy is buying, because a
    substitution is only meaningful against the thing it replaces. (Its label is
    near-zero by construction -- forcing the action the policy would have taken
    reproduces the control arm -- and that is the point: it is the anchor the
    alternative has to beat.)
    """
    by_idx = {c.idx: c for c in cands}
    chosen: list = []
    pick = None
    if isinstance(act, dict):
        try:
            pick = int(act.get("item_idx"))
        except (TypeError, ValueError):
            pick = None
    orc = _oracle(margin, kinds)
    try:
        # Mirror the live policy's reroll count: the runtime oracle IS the
        # playing policy, so it ranks with its own shop-local counter.
        setattr(orc, "_rerolls_this_shop",
                int(getattr(policy, "_rerolls_this_shop", 0) or 0))
        before = dict(getattr(orc, "_oracle_stats", {}) or {})
        sub = orc._oracle_prior(game, act)
        after = dict(getattr(orc, "_oracle_stats", {}) or {})
        offered = int(after.get("offered", 0)) - int(before.get("offered", 0))
        subbed = int(after.get("accepted", 0)) - int(before.get("accepted", 0))
    except Exception as exc:
        _note_issue(f"oracle:{type(exc).__name__}")
        sub, offered, subbed = None, 0, 0
    if pick is not None and pick in by_idx:
        chosen.append((by_idx[pick], "pick"))
    if sub is not None:
        try:
            sub = int(sub)
        except (TypeError, ValueError):
            sub = None
    if sub is not None and sub in by_idx and sub != pick:
        chosen.append((by_idx[sub], "substitute"))
    alt = _model_alt(game, cands, {c.idx for c, _r in chosen}, kinds)
    if alt is not None:
        chosen.append((alt, "model_alt"))
    return chosen, offered, subbed


def _focus_score(focus: dict | None, key: str, ante: int) -> float:
    """Importance weight from the coverage work order.

    Zero for cells the work order does not list. That default matters: the
    work order contains *every uncovered* cell, so an unlisted cell is already
    covered — returning a non-zero default here would mark every shop in the
    run as needing attention, forfeit the sampling coin for all of them, and
    burn the decision budget inside the first two antes (measured: ante
    coverage collapsed to 1-3 when the default was 1.0).
    """
    if not focus:
        return 0.0
    cell = f"{key}|a{ante}"
    wants = focus.get("cells", {}) if isinstance(focus, dict) else {}
    # `key|scenario` is the item x scenario (boss / hand type) work order: those
    # cells are a property of the RUN a decision happens in, not of the shop
    # offer, so they can only be targeted through the item. Taking the max of
    # the two entries is what lets one item count as urgent for either reason.
    entry = wants.get(cell) or wants.get(key) or wants.get(f"{key}|scenario")
    if entry is None:
        return 0.0
    return float(entry.get("weight", 0.0)) if isinstance(entry, dict) else float(entry)


def _accept_decision(seed: int, n_dec: int, rate: float) -> bool:
    """Deterministic spread-sampling of decision points.

    Taking the FIRST N eligible shops would sample only antes 1-2, so the
    late-game cells the model most needs (scaling payoffs, xMult conversion)
    would never be observed. Sampling each eligible decision with a fixed
    per-(seed, decision) coin spreads the budget across the whole run.
    `random.Random(str)` seeding is stable across processes, so a re-run
    reproduces the same sample set.
    """
    if rate >= 1.0:
        return True
    return random.Random(f"decide|{seed}|{n_dec}").random() < rate


def _reseed(game, seed: int, k: int, samples: int):
    """Give a fork its k-th continuation stream.

    With samples == 1 the fork keeps the run's own stream (the original
    behaviour). Otherwise the RNG source is rebuilt from a derived seed, which
    changes every future draw while leaving the deck, hand and jokers exactly
    as they are — a different continuation FROM THE SAME STATE.

    The acquire and skip arms of one sample are given the SAME derived seed, so
    the pairing (common random numbers) that cancels shared luck is preserved
    inside each sample; the samples themselves are independent.
    """
    if samples <= 1 or game is None:
        return game
    game.rng = make_source(f"{seed}:s{k}", "seed")
    return game


def collect_seed(seed: int, mode: str, max_decisions: int, cand_cap: int,
                 focus: dict | None, accept_rate: float,
                 per_ante: int, booster_cand_cap: int,
                 focus_extra: int, samples: int = 1,
                 candidate_mode: str = "coverage",
                 oracle_margin: float = ORACLE_MARGIN,
                 oracle_kinds: tuple = ORACLE_KINDS) -> list[dict]:
    game = BalatroGame(seed=seed, rng_mode="seed")
    policy = _policy()
    rows: list[dict] = []
    n_dec = 0
    steps = 0
    ref = None
    ante_count: dict[int, int] = {}
    forced_count: dict[int, int] = {}

    while game.state != State.GAME_OVER and steps < 100_000:
        state = game.state
        is_shop = state == State.SHOP and mode in ("shop", "both")
        is_pack = state == State.BOOSTER_OPEN and mode in ("booster", "both")
        # ONE decide call per iteration, hoisted from the bottom of the loop so
        # `onpolicy` mode can fork the action this run is actually about to
        # take. Every path made exactly one call before, so the count is
        # unchanged and the live RNG stream (and the seed-exactness gate) is
        # untouched.
        act = policy.decide(game)

        if (is_shop or is_pack) and n_dec < max_decisions:
            cands = _shop_candidates(game) if is_shop else _booster_candidates(game)
            if cands:
                dmode = "shop" if is_shop else "booster"
                ante = int(getattr(game, "ante", 1) or 1)
                # Per-ante allowance, not a global first-N cap: a global cap is
                # spent inside the first two antes, which is exactly how the
                # late-game cells the model most needs would go unobserved.
                taken = ante_count.get(ante, 0)
                best_focus = max(_focus_score(focus, c.key, ante) for c in cands)
                forced = bool(focus) and best_focus >= FOCUS_FORCE_AT
                f_taken = forced_count.get(ante, 0)

                if forced and f_taken < focus_extra:
                    # Ignorance-directed: this shop offers something with no
                    # measured evidence at all, so take the decision whatever
                    # the coin says and whatever the per-ante allowance is.
                    forced_count[ante] = f_taken + 1
                elif taken >= per_ante:
                    game.step(act)
                    steps += 1
                    continue
                elif taken > 0 and not _accept_decision(seed, n_dec, accept_rate):
                    # First decision in each ante is free (no scenario dimension
                    # structurally absent); later ones ride the spread coin so
                    # samples land after different blinds, not always the first.
                    game.step(act)
                    steps += 1
                    continue
                else:
                    ante_count[ante] = taken + 1
                n_dec += 1
                # Keep the highest-need cells, then cap for budget.
                ranked = sorted(
                    cands,
                    key=lambda c: _focus_score(focus, c.key, ante),
                    reverse=True)
                # Packs are the only place tarots, spectrals and planets are
                # chosen, and the skip arm is shared across candidates, so
                # taking every offer costs one rollout each and is the cheapest
                # coverage available.
                cap = booster_cand_cap if is_pack else cand_cap
                oracle_offered = oracle_substituted = 0
                if candidate_mode == "onpolicy" and is_shop:
                    chosen, oracle_offered, oracle_substituted = _onpolicy_choice(
                        game, act, cands, policy, oracle_margin, oracle_kinds)
                    seen = {c.idx for c, _role in chosen}
                    # pick + substitute + model_alt is the full on-policy set;
                    # each extra candidate costs one rollout (the skip arm is
                    # shared), which is the compute this mode exists to spend.
                    cap = max(cap, 3) if chosen else cap
                    for c in ranked:  # spend the rest of the budget on coverage
                        if len(chosen) >= max(1, cap):
                            break
                        if c.idx in seen:
                            continue
                        chosen.append((c, "coverage"))
                        seen.add(c.idx)
                else:
                    chosen = [(c, "coverage") for c in ranked[:max(1, cap)]]

                if ref is None:
                    try:
                        from balatro_sim.agent_v9 import reference_hand
                        ref = reference_hand(game)
                    except Exception:
                        ref = None

                # K independent continuations per arm. The label is a step
                # function of the draw order, so one sample per candidate is
                # mostly luck: measured on iteration 1, the split-half
                # correlation of (item, ante) mean labels was -0.20 — a cell's
                # average was not reproducible even at n >= 8. Averaging K
                # paired continuations trades rollout time for reliability,
                # which is the only currency that makes an item's value
                # measurable at all.
                skips = [rollout(_reseed(deepcopy(game), seed, k, samples), _policy())
                         for k in range(samples)]
                out_skip = skips[0]
                v10_before = evaluate_shop_value(extract_game_features(game))
                for cand, role in chosen:
                    idx = cand.idx
                    acqs = []
                    why = ""
                    for k in range(samples):
                        # The reseed happens BEFORE the forced action, which is
                        # what keeps the arms paired. Forcing a buy consumes RNG
                        # nodes (the shop refills the sold slot), and a seed-mode
                        # source hashes the node id into every draw, so reseeding
                        # AFTER the buy leaves the acquire arm's node table ahead
                        # of the skip arm's and the two arms then diverge even
                        # when their states are identical. Measured: `pick` rows
                        # -- whose forced action IS the policy's own, so the
                        # anchor must measure exactly 0 -- carry label 0.000 in
                        # 267/270 rows at samples=1 but 11/20 non-zero at
                        # samples=3. Reseeding the base first restores the
                        # common-random-numbers pairing inside each sample.
                        fork, ok, why = _force_arm(
                            _reseed(deepcopy(game), seed, k, samples), dmode, idx)
                        if not ok or fork is None:
                            acqs = []
                            break
                        acqs.append(rollout(fork, _policy()))
                    if not acqs:
                        rows.append({
                            "v": COLLECTOR_VERSION, "seed": seed,
                            "dec_id": f"{seed}:{n_dec}", "mode": dmode,
                            "arm_ok": 0, "key": cand.key, "kind": cand.kind,
                            "role": role, "candidate_mode": candidate_mode,
                            "_why": why or "unknown",
                        })
                        continue
                    out_acq = acqs[0]
                    d_dense = [VT.run_return(a) - VT.run_return(s)
                               for a, s in zip(acqs, skips)]
                    d_win = [int(bool(a["won"])) - int(bool(s["won"]))
                             for a, s in zip(acqs, skips)]
                    d_ante = [int(a["ante"]) - int(s["ante"])
                              for a, s in zip(acqs, skips)]
                    label = sum(d_dense) / len(d_dense)
                    label_win = sum(d_win) / len(d_win)
                    ante_delta = sum(d_ante) / len(d_ante)
                    if len(d_dense) > 1:
                        mu = label
                        label_sd = (sum((x - mu) ** 2 for x in d_dense)
                                    / (len(d_dense) - 1)) ** 0.5
                    else:
                        label_sd = 0.0
                    try:
                        feats = VT.decision_features(game, cand, ref=ref)
                    except Exception:
                        feats = {}

                    # Legacy state-model ΔV on the SAME counterfactual
                    # post-acquisition state, so the calibration comparison in
                    # M4 is apples-to-apples with the new model's target.
                    legacy_dv = 0.0
                    if dmode == "shop":
                        try:
                            legacy_dv = float(
                                evaluate_shop_value(formulate_counterfactual_state(
                                    game, {"type": "buy", "item_idx": idx}))
                                - v10_before)
                        except Exception:
                            legacy_dv = 0.0

                    rows.append({
                        "v": COLLECTOR_VERSION,
                        "seed": seed,
                        "dec_id": f"{seed}:{n_dec}",
                        "mode": dmode,
                        "arm_ok": 1,
                        "kind": cand.kind,
                        "key": cand.key,
                        # `role` is how the corpus says WHY this row exists:
                        #   pick       the item the frozen search buys (anchor)
                        #   substitute the item the learned prior swaps in
                        #   coverage   a work-order candidate (the old mode)
                        # Only an `onpolicy` row is a pair the runtime weighs.
                        "role": role,
                        "candidate_mode": candidate_mode,
                        "oracle_offered": int(oracle_offered),
                        "oracle_substituted": int(oracle_substituted),
                        "edition": cand.edition,
                        "price": cand.price,
                        "item_idx": idx,
                        "ante": ante,
                        "blind_idx": int(getattr(game, "blind_idx", 0) or 0),
                        "is_boss": 1.0 if int(getattr(game, "blind_idx", 0) or 0) == 2 else 0.0,
                        "boss_key": str(getattr(game, "next_boss_key", "") or ""),
                        # Scenario labels for the item x scenario residual cells
                        # (value_tables.scenario_cells). Both are free, RNG-free
                        # reads, and both are needed at FIT time, so they are
                        # recorded per row rather than recomputed later from a
                        # game object that no longer exists.
                        "hand_key": VT.hand_scenario(game),
                        "cell": VT.cell_key(game, cand.key),
                        "catalogue_fingerprint": CAT.fingerprint(),
                        "feats": feats,
                        "legacy_dv": legacy_dv,
                        "samples": int(samples),
                        "won_acq": float(sum(bool(a["won"]) for a in acqs) / len(acqs)),
                        "won_skip": float(sum(bool(s["won"]) for s in skips) / len(skips)),
                        "ante_acq": float(sum(a["ante"] for a in acqs) / len(acqs)),
                        "ante_skip": float(sum(s["ante"] for s in skips) / len(skips)),
                        # Dense primary label: the contrast in run return,
                        # averaged over the K paired continuations. `label_sd`
                        # is the spread ACROSS continuations, i.e. how much of
                        # this row's number is luck — the quantity that decides
                        # how many samples a cell needs.
                        "label": float(label),
                        "label_sd": float(label_sd),
                        "label_win": float(label_win),
                        "ante_delta": float(ante_delta),
                        "dense_samples": [round(float(x), 4) for x in d_dense],
                    })

        # Advance the LIVE run with the policy. Instrumentation never touches
        # this object, so its RNG stream is byte-identical to a plain run.
        game.step(act)
        steps += 1

    live = {
        "live_won": int(bool(game.ante > 8)),
        "live_ante": int(game.ante),
    }
    for r in rows:
        r.update(live)
        r["seed_exact_marker"] = f"{seed}:{game.ante}:{int(bool(game.ante > 8))}"
    return rows


def _worker(args):
    (seed, mode, max_dec, cap, focus, accept_rate, per_ante,
     booster_cap, focus_extra, samples, candidate_mode, oracle_margin,
     oracle_kinds) = args
    try:
        return collect_seed(seed, mode, max_dec, cap, focus, accept_rate,
                            per_ante, booster_cap, focus_extra, samples,
                            candidate_mode, oracle_margin, oracle_kinds)
    except Exception as e:  # keep the sweep alive
        return [{"v": COLLECTOR_VERSION, "seed": seed,
                 "_error": f"{type(e).__name__}: {e}"}]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed-start", type=int, default=40000)
    ap.add_argument("--n-seeds", type=int, default=400)
    ap.add_argument("--holdout-every", type=int, default=5,
                    help="every Nth seed is holdout; keyed on the seed value "
                         "so an early stop (time budget) cannot corrupt the split")
    ap.add_argument("--time-budget-min", type=float, default=55.0,
                    help="stop launching new work past this; keeps an "
                         "iteration inside the 1-hour budget")
    ap.add_argument("--mode", default="both", choices=["shop", "booster", "both"])
    ap.add_argument("--max-decisions", type=int, default=14,
                    help="global safety cap per seed")
    ap.add_argument("--per-ante", type=int, default=2,
                    help="max sampled decisions per ante (coverage balance)")
    ap.add_argument("--cand-cap", type=int, default=2,
                    help="candidates forked per shop decision")
    ap.add_argument("--booster-cand-cap", type=int, default=4,
                    help="candidates forked per pack decision (packs are where "
                         "tarots/spectrals/planets are chosen; the skip arm is "
                         "shared, so extra candidates are cheap)")
    ap.add_argument("--samples", type=int, default=1,
                    help="independent paired continuations per arm; K>1 averages "
                         "out the draw-order luck that makes K=1 labels ~pure noise")
    ap.add_argument("--focus-extra", type=int, default=3,
                    help="extra per-ante decisions forced on zero-evidence cells")
    ap.add_argument("--accept-rate", type=float, default=0.5,
                    help="fraction of eligible decisions sampled after the "
                         "first decision in each ante (spreads coverage)")
    ap.add_argument("--workers", type=int, default=12,
                    help="default leaves 4 cores free for development work")
    ap.add_argument("--out-tag", type=str, default="")
    ap.add_argument("--focus-file", type=str, default="",
                    help="coverage work order from tools/audit_value_coverage.py")
    ap.add_argument("--candidate-mode", type=str, default="coverage",
                    choices=list(CANDIDATE_MODES),
                    help="coverage: fork the most under-measured candidates "
                         "(the corpus to date). onpolicy: fork the pair the "
                         "runtime oracle weighs -- the frozen search's pick "
                         "plus the item the learned prior substitutes -- so "
                         "the rows describe decisions the arm can act on")
    ap.add_argument("--oracle-margin", type=float, default=ORACLE_MARGIN,
                    help="near-tie window of the arm being replayed in "
                         "onpolicy mode; must match that arm's "
                         "v12_prior_margin or the collector forks a pair the "
                         "arm never considers")
    ap.add_argument("--oracle-kinds", type=str,
                    default=",".join(ORACLE_KINDS),
                    help="item kinds the replayed oracle considers")
    args = ap.parse_args()
    oracle_kinds = tuple(k.strip() for k in args.oracle_kinds.split(",")
                         if k.strip())

    focus = None
    if args.focus_file:
        focus = json.loads(Path(args.focus_file).read_text(encoding="utf-8"))
        print(f"focus file: {args.focus_file} "
              f"({len(focus.get('cells', {}))} cells)", flush=True)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    tag = f"_{args.out_tag}" if args.out_tag else ""
    train_path = OUT_DIR / f"train{tag}.jsonl"
    hold_path = OUT_DIR / f"holdout{tag}.jsonl"

    seeds = list(range(args.seed_start, args.seed_start + args.n_seeds))
    work = [(s, args.mode, args.max_decisions, args.cand_cap, focus,
             args.accept_rate, args.per_ante, args.booster_cand_cap,
             args.focus_extra, max(1, args.samples), args.candidate_mode,
             args.oracle_margin, oracle_kinds) for s in seeds]
    hold_every = max(1, args.holdout_every)

    def _is_holdout(seed: int) -> bool:
        return ((seed - args.seed_start) % hold_every) == (hold_every - 1)

    print(f"collector v{COLLECTOR_VERSION} | catalogue {CAT.fingerprint()} "
          f"| mode={args.mode} | candidates={args.candidate_mode} "
          f"| seeds {seeds[0]}..{seeds[-1]} "
          f"({len(seeds)}, holdout 1/{hold_every}) | workers={args.workers} "
          f"| samples={max(1, args.samples)} "
          f"| budget {args.time_budget_min:.0f}m", flush=True)
    if args.candidate_mode == "onpolicy":
        print(f"onpolicy oracle: margin {args.oracle_margin} "
              f"kinds {list(oracle_kinds)} -- these must match the screened "
              f"arm (defaults track v12_prior_m02)", flush=True)

    t0 = time.time()
    n_rows = n_pos = n_neg = n_flip = n_err = n_rejected = 0
    role_counts: dict[str, int] = {}
    rej_why: dict[str, int] = {}
    with mp.Pool(args.workers) as pool, \
            open(train_path, "w", encoding="utf-8") as f_tr, \
            open(hold_path, "w", encoding="utf-8") as f_ho:
        for si, rows in enumerate(pool.imap_unordered(_worker, work, chunksize=1)):
            if args.time_budget_min and \
                    (time.time() - t0) / 60.0 > args.time_budget_min:
                print(f"time budget reached after {si}/{len(seeds)} seeds; "
                      f"stopping cleanly (split is seed-keyed, so the "
                      f"holdout stays valid)", flush=True)
                break
            seed_of = rows[0].get("seed") if rows else None
            is_hold = _is_holdout(seed_of) if seed_of is not None else (si % hold_every == hold_every - 1)
            fh = f_ho if is_hold else f_tr
            for r in rows:
                if "_error" in r:
                    n_err += 1
                    print(f"[seed {r.get('seed')}] ERROR {r['_error']}", flush=True)
                    continue
                if not r.get("arm_ok", 0):
                    n_rejected += 1
                    why = str(r.get("_why", "unknown"))
                    rej_why[why] = rej_why.get(why, 0) + 1
                    continue
                fh.write(json.dumps(r) + "\n")
                n_rows += 1
                role = str(r.get("role", "?"))
                role_counts[role] = role_counts.get(role, 0) + 1
                n_flip += 1 if r.get("label_win") else 0
                n_pos += 1 if r["label"] > 0 else 0
                n_neg += 1 if r["label"] < 0 else 0
            done = si + 1
            if done % 10 == 0 or done == len(seeds):
                rate = done / max(1e-9, time.time() - t0)
                eta = (len(seeds) - done) / max(1e-9, rate)
                print(f"[{done}/{len(seeds)}] rows={n_rows} flips={n_flip} "
                      f"(+{n_pos}/-{n_neg}) rejected={n_rejected} err={n_err} "
                      f"{rate:.2f} seeds/s ETA {eta/60:.1f}m", flush=True)
            fh.flush()

    print(f"DONE rows={n_rows} flips={n_flip} (+{n_pos}/-{n_neg}) "
          f"rejected={n_rejected} errors={n_err} "
          f"in {time.time()-t0:.0f}s -> {train_path} / {hold_path}")
    if role_counts:
        roles = ", ".join(f"{k}={v}" for k, v in sorted(role_counts.items()))
        print(f"roles: {roles} (pick=the frozen buy, substitute=what the prior "
              f"swaps in, model_alt=the head's own preference outside the "
              f"window, coverage=work-order fill)", flush=True)
    if _ORACLE_ISSUES:
        issues = ", ".join(f"{k}={v}" for k, v in
                           sorted(_ORACLE_ISSUES.items(), key=lambda kv: -kv[1]))
        print(f"oracle issues: {issues}", flush=True)
    if rej_why:
        why_str = ", ".join(f"{k}={v}" for k, v in
                            sorted(rej_why.items(), key=lambda kv: -kv[1]))
        print(f"rejected reasons: {why_str}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
