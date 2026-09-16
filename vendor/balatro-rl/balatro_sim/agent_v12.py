"""agent_v12.py — frozen search + learned value oracle (additive, flag-gated).

ARCHITECTURE, AND WHY IT ONLY SUBSTITUTES
========================================
Every historical gain in this repo came from the L1 counterfactual shop
search (V9 3.67% -> search_shop_v10 10.67% -> V11 14.0%), and the one time
that search was replaced wholesale the policy silently lost 9 wins. So V12
does not touch it:

    SearchShopV12  inherits the frozen SearchShopV10 search unchanged.
    By default (`v12_mode="override"`) the learned oracle may only change
    WHICH item a decision already spends money on, and only when the learned
    value beats the policy's own pick by more than the combined noise of the
    two estimates. Spending decisions, slots and capital flow are untouched, so
    the intervention cannot stall a build or drain a bank — the failure modes
    measured for the "entry" mode (which picks instead of the search: -2/100).

That is the same shape as V11's own successful hooks (`_v11_open_slot_search`)
and it has a hard consequence that makes the change auditable: with
``v12_oracle=False`` the policy is byte-identical to frozen V10 on the seed
bank. That parity control is not optional — `TestV12Parity` in
`tests/test_value_model.py` asserts it, because a silent regression here is
exactly the failure this repo already paid for once.

THREE MODES, AND WHAT EACH ONE COST WHEN MEASURED
=================================================
    entry    pick instead of the search   -2 wins / 100 seeds
    override substitute the search's pick  win-neutral, monotone in firing
                                            rate (net -3/-8/-11 at 150 seeds)
    prior    break only the search's ties  the architecture the override
                                            screen points at (see V12_DEFAULTS)

The measured ordering is the design argument: every mode that lets a ~0.53
concordance model REPLACE a better-than-chance counterfactual loses wins in
proportion to how often it fires, while the search itself is the only thing in
this repo that has ever added wins. A prior is the weakest possible
intervention that still lets the learned values act: it consumes the search's
own candidate ranking and only re-orders entries the search scored as
equivalent (within `v12_prior_margin` of the chosen item's value).

MEASURED, AND IT CONTRADICTS THE OBVIOUS ASSUMPTION: margin 0 is NOT the
identity. The ranker emits exact ties often (within-shop spread q25 = 0.00,
q50 = 0.03), so a margin-0 pool has more than one member in a large share of
shops and the learned head does re-order them. On an 8-seed probe, prior m0
took 5 substitutions and diverged from V10 on 2 seeds. The honest parity
control is therefore the flag-level one (`v12_oracle=False`, byte-identical),
and the prior arms are read as a dose-response in margin — with m0 labelled
"exact ties only" rather than "no-op".

WHAT THE ORACLE REPLACES
========================
V11's open-slot hook asked `evaluate_shop_value` (a model of post-buy *state*)
whether buying a candidate helped. Adding one joker barely moves a 50-feature
state vector, so every candidate scored ΔV ≈ 0.000-0.005 and the hook never
fired; measured on counterfactual rows its ΔV ranked candidates *worse than a
coin flip* (within-decision concordance 0.462). The oracle here scores the
candidate itself with `value_tables`, which is fitted directly on the
counterfactual contrast and already beats the legacy ΔV on identical pairs.

THE DECISION RULE HAS NO TUNED CONSTANT
=======================================
Buy when the learned effect exceeds `z` standard errors of its own estimate:

    value  = linear_head(features) + shrunk_residual(cell)
    stderr = resid_sd / sqrt(n_effective(cell))
    act if value > z * stderr

`z` is the only free number and it is declared, not fitted-and-hidden: z = 1
is "one standard error". `n_effective` walks up the cell hierarchy, so an item
with no evidence must show a large effect before the oracle will spend money
on it — conservative where it should be, permissive where the data is thick.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Optional

from .agent_v10 import (V10_DEFAULTS, SearchShopV10, ACTIVE_PARAMS,
                        _v10_rank_shop_items, forecast_beatable, reference_hand)
from .game import State
from . import value_tables as VT

# ────────────────────────────────────────────────────────────────────────────
# Tunables (V12-only; the A/B `--params` override targets these)
# ────────────────────────────────────────────────────────────────────────────

V12_DEFAULTS = {
    # Master switch. OFF by default: an un-switched V12 must be
    # indistinguishable from frozen V10 (the parity control).
    "v12_oracle": False,
    # Confidence multiple: act only when the learned effect exceeds this many
    # standard errors of its own estimate. 1.0 == one standard error.
    "v12_z": 1.0,
    # At most this many learned purchases per shop visit (mirrors the repo's
    # `_swapped_this_visit` churn guard). 1 == one deliberate decision.
    "v12_max_buys_per_visit": 1,
    # Which shop kinds the oracle may add. Jokers first: that is the case the
    # legacy state model provably could not rank.
    "v12_kinds": ("joker",),
    # Treat a joker with an open slot as the only slot-free case; consumables
    # and vouchers are gated by the sim on purchase and rejected harmlessly.
    "v12_require_slot": True,
    # Where the oracle may act:
    #   "entry"    - at the first decision of a shop visit with an open slot,
    #                pick by learned value instead of the heuristic ranking.
    #                MEASURED NECESSITY: the frozen search fills every open
    #                slot before it leaves, so an end-of-visit hook observes an
    #                empty candidate list and can never fire. MEASURED COST: on
    #                100 seeds this mode was V10 12 wins vs V12 10, because an
    #                absolute significance test let a near-chance model spend
    #                money and a slot the search would have spent elsewhere.
    #   "override" - let the frozen policy choose, then substitute a *different
    #                item of the same allowed kinds* only when the learned
    #                value beats the policy's own pick by more than the combined
    #                noise (a paired contrast, not an absolute test). Spending
    #                still happens exactly when the search wanted to spend, so
    #                the intervention cannot drain capital or stall the build —
    #                it can only change *which* item is bought.
    #   "additive" - only add a purchase the frozen search declined.
    #   "both"     - entry pick, plus the end-of-visit fallback.
    #   "prior"    - the search decides; the learned head only re-orders
    #                candidates the search itself scores as near-ties, inside a
    #                window of `v12_prior_margin` in the search's OWN value
    #                units. This is the architecture the override screen points
    #                at: override REPLACES the search's choice, and at 0.531
    #                within-decision concordance a partially-informed model
    #                displacing a better-than-chance counterfactual loses wins
    #                monotonically with how often it fires. A prior cannot
    #                lose that way: where the search has an opinion (spread >
    #                margin) it is untouched, and the learned head acts only
    #                where the heuristic is indifferent. INVARIANT THIS BUYS:
    #                the learned head can never show the policy an item the
    #                frozen ranker had not already put on the table, so it
    #                cannot drain capital or stall a build. margin 0 is NOT a
    #                no-op (the ranker ties often — measured 2/8 seeds moved).
    # DEFAULT IS "prior": the only mode that has ever reproduced a POSITIVE
    # paired result on a fresh seed bank. Two independent 150-seed banks:
    #   10500-10649  V10 20 | prior_m0 19 (-1) | prior_m05 22 (+2) | rel_z2 17 (-3)
    #   10700-10849  V10 23 | prior_m05 24 (+1) | prior_m10 23 (+0)
    # Pooled over 300 paired seeds prior_m05 is +3 wins (12 gained / 9 lost,
    # binomial p = 0.66) with a better mean ante on BOTH banks (4.91 vs 4.80 and
    # 5.53 vs 5.41) and unchanged ante-1 deaths. The magnitude is inside noise;
    # what is not inside noise is the ordering of the modes — every mode that
    # replaces the search's choice loses, and the one that only breaks its ties
    # gains slightly.
    "v12_mode": "prior",
    # v12_prior_margin: see the measured note in tools/value_model_constants.json.
    # Near-tie window for "prior" mode, in the frozen ranker's own value units
    # (NOT return units). MEASURED on 556 candidate-bearing shop decisions
    # across 14 seeds: top candidate value q05/q25/q50/q75 = 0.07/0.09/0.15/
    # 0.25 and within-shop spread q05/q25/q50/q75 = 0.00/0.00/0.03/0.14, i.e.
    # a quarter of shops are exact ties and half differ by <= 0.03. 0.05 is
    # the median-to-q75 window: it covers the indifferent majority without
    # reaching values the ranker actually distinguishes.
    "v12_prior_margin": 0.05,
    # Which head scores candidates. "relative" is the within-decision head,
    # which is the one fitted for comparing candidates inside a single shop;
    # "absolute" scores the item's level and is the right head for deciding
    # whether to buy *anything*.
    "v12_head": "relative",
    # v12_prior_band: refuse to break an EXACT tie in the frozen ranker.
    #
    # WHY, measured (11,986 collected rows / 6,429 decisions): bucket every
    # candidate pair inside a decision by |legacy_dV gap| and ask how often the
    # two items' measured returns differ at all:
    #
    #   exact tie   2,818 pairs   36.3% differ   mean |dlabel| 1.30
    #   < 0.01      2,543 pairs   57.0% differ   mean |dlabel| 1.88
    #   0.01-0.05   1,081 pairs   52.0% differ   mean |dlabel| 2.09
    #
    # So when the ranker has NO opinion the two items are measurably equivalent
    # roughly two times in three, and when it has a *small* opinion they differ
    # most of the time. `margin` gates on the ranker's value gap, which makes
    # the exact-tie end of that window the least informative place to spend an
    # intervention — and margin 0 lives entirely there. That is a mechanism for
    # the measured dose-response (m0 -1, m02 +5, m05 +3, m10 +3 net over the
    # three screened banks): the wider the window, the larger the share of
    # firings spent on pairs our own data says are equivalent.
    #
    # With this on, a substitution requires the ranker to have PREFERRED its own
    # pick by a strictly positive margin, i.e. it corrects an expressed ordering
    # rather than supplying a missing one. Default OFF, because it is a new
    # behaviour: the prior arms' recorded numbers were all produced without it.
    "v12_prior_band": False,
}

V12_PARAMS = dict(V12_DEFAULTS)


# ────────────────────────────────────────────────────────────────────────────
# Eligibility (mirrors the sim; a candidate that fails is simply not offered)
# ────────────────────────────────────────────────────────────────────────────


def _slot_open(game, kind: str) -> bool:
    if kind == "joker":
        return len(getattr(game, "jokers", []) or []) < int(game.joker_slots)
    if kind in ("tarot", "spectral", "planet"):
        return len(getattr(game, "consumable_hand", []) or []) < int(game.consumable_slots)
    return True  # vouchers, packs, cards


def candidates(game, kinds) -> list[tuple[int, Any]]:
    """(shop index, item) for affordable, unsold items of the allowed kinds."""
    out = []
    dollars = float(getattr(game, "dollars", 0) or 0)
    discount = float(getattr(game, "shop_discount", 0.0) or 0.0)
    for i, item in enumerate(getattr(game, "current_shop", []) or []):
        if getattr(item, "sold", False):
            continue
        kind = str(getattr(item, "kind", "") or "")
        if kind not in kinds:
            continue
        try:
            price = int(item.discounted_price(discount))
        except Exception:
            price = int(getattr(item, "price", 0) or 0)
        if price > dollars:
            continue
        if V12_PARAMS.get("v12_require_slot", True) and not _slot_open(game, kind):
            continue
        out.append((i, item))
    return out


# ────────────────────────────────────────────────────────────────────────────
# Policy
# ────────────────────────────────────────────────────────────────────────────


class SearchShopV12(SearchShopV10):
    """Frozen V10 search + an additive learned-value purchase oracle."""

    policy_name = "search_shop_v12"

    def __init__(self, params=None, search_shops: int = 999,
                 candidate_cap: int = 4, lookahead: bool = False,
                 max_rollout_steps: int = 4000,
                 model_path: Optional[Path | str] = None, **kwargs):
        given = dict(params or {})
        # Only pass V10-shaped knobs down: polluting V10_PARAMS with v12_* keys
        # would make an unrelated consumer's A/B read settings it cannot use.
        v10_only = {k: v for k, v in given.items() if k in V10_DEFAULTS}
        super().__init__(params=v10_only or None, search_shops=search_shops,
                         candidate_cap=candidate_cap, lookahead=lookahead,
                         max_rollout_steps=max_rollout_steps)
        V12_PARAMS.update({k: v for k, v in given.items() if k in V12_DEFAULTS})
        self._table = VT.load(model_path)
        self._buys_this_visit = 0
        self._oracle_stats = {"offered": 0, "accepted": 0, "vetoed": 0}

    # -- oracle ------------------------------------------------------------
    def _oracle_pick(self, game) -> Optional[int]:
        """Best shop index whose learned value clears the confidence test."""
        kinds = tuple(V12_PARAMS.get("v12_kinds", ("joker",)))
        z = float(V12_PARAMS.get("v12_z", 1.0))
        best_idx, best_val = None, float("-inf")
        for idx, item in candidates(game, kinds):
            ok, value, _se = self._table.significant(game, item, z)
            self._oracle_stats["offered"] += 1
            if ok:
                if value > best_val:
                    best_idx, best_val = idx, value
            else:
                self._oracle_stats["vetoed"] += 1
        return best_idx

    def _oracle_prior(self, game, act) -> Optional[int]:
        """Re-order the search's OWN near-ties with the learned relative head.

        Returns a shop index to buy instead of the frozen pick, or None.

        Unlike `_oracle_override` this never introduces an item the search had
        not already ranked: the candidate pool is `_v10_rank_shop_items`'s own
        output — the same list, computed by the same pure-read code, that        the frozen decision was taken from. The learned head can therefore only
        choose *among items the heuristic considers equivalent*, which is the
        invariant that matters: the arm cannot drain capital or stall a build,
        because spending happens exactly when the search wanted to spend, on
        exactly the same slot budget. It is NOT identity-equivalent at margin
        0 — the ranker produces exact ties in a quarter of shops, so m0 still
        substitutes (measured: 5 substitutions, 2/8 seeds changed).

        Cost: one extra `_v10_rank_shop_items` call per shop visit where the
        frozen policy buys. That routine is pure reads (the search itself calls
        it every shop decision), so the live run's RNG stream is untouched.
        """
        kinds = tuple(V12_PARAMS.get("v12_kinds", ("joker",)))
        margin = float(V12_PARAMS.get("v12_prior_margin", 0.0))
        head = str(V12_PARAMS.get("v12_head", "relative"))
        try:
            idx = int(act.get("item_idx"))
        except (TypeError, ValueError):
            return None
        shop = list(getattr(game, "current_shop", []) or [])
        if not (0 <= idx < len(shop)):
            return None
        try:
            ref = reference_hand(game)
            surplus = forecast_beatable(
                game, ACTIVE_PARAMS["tilt_surplus_margin"], ref)
            buys, _need_sell = _v10_rank_shop_items(
                game, ref, surplus,
                rerolls_used=getattr(self, "_rerolls_this_shop", 0))
        except Exception:
            return None
        if not buys:
            return None
        by_idx = {int(i): float(v) for v, i in buys}
        if idx not in by_idx:
            # The frozen buy came from a path this ranker did not score (a
            # pending swap target, say). Do not second-guess a decision we
            # cannot compare against its alternatives.
            return None
        floor = by_idx[idx] - margin
        pick_v = by_idx[idx]
        band = bool(V12_PARAMS.get("v12_prior_band", False))
        pool = []
        for cand_idx, cand in candidates(game, kinds):
            ci = int(cand_idx)
            v = by_idx.get(ci)
            if v is None or v < floor:
                continue
            if band and ci != idx and v >= pick_v:
                # The ranker called these two equivalent (or preferred this one),
                # so there is no expressed ordering for the head to correct.
                # Measured: exact-tie pairs differ in return only 36% of the
                # time, versus 57% when the ranker separated them by < 0.01 --
                # a coin flip is not where an intervention belongs. The pick
                # itself stays in the pool so the `len(pool) < 2` guard keeps
                # meaning "there was at least one alternative worth ranking".
                continue
            pool.append((ci, cand, v))
        if len(pool) < 2:
            return None
        self._oracle_stats["offered"] += len(pool)
        score = (self._table.relative_of if head == "relative"
                 else self._table.value_of)
        best_idx, best_key = idx, None
        for cand_idx, cand, v in pool:
            s = score(game, cand)
            # Ties in the learned head fall back to the search's own order, so
            # the prior can never randomise a decision the search made.
            key = (s, v)
            if best_key is None or key > best_key:
                best_idx, best_key = cand_idx, key
        if best_idx == idx:
            self._oracle_stats["vetoed"] += 1
            return None
        self._oracle_stats["accepted"] += 1
        return best_idx

    def _oracle_override(self, game, act) -> Optional[int]:
        """Substitute the frozen policy's pick for a strictly better one.

        Returns the shop index to buy *instead*, or None to keep the policy's
        own action. The substitute is restricted to the allowed kinds and must
        already satisfy the sim's slot and affordability gates, so a
        substitution can never make an otherwise-valid action invalid.
        """
        kinds = tuple(V12_PARAMS.get("v12_kinds", ("joker",)))
        z = float(V12_PARAMS.get("v12_z", 1.0))
        head = str(V12_PARAMS.get("v12_head", "relative"))
        try:
            idx = int(act.get("item_idx"))
        except (TypeError, ValueError):
            return None
        shop = list(getattr(game, "current_shop", []) or [])
        if not (0 <= idx < len(shop)):
            return None
        chosen = shop[idx]
        if str(getattr(chosen, "kind", "") or "") not in kinds:
            return None
        best_idx, best_margin = None, 0.0
        for cand_idx, cand in candidates(game, kinds):
            if cand_idx == idx:
                continue
            ok, margin, _se = self._table.beats(game, cand, chosen, z,
                                                head=head)
            self._oracle_stats["offered"] += 1
            if ok and margin > best_margin:
                best_idx, best_margin = cand_idx, margin
        if best_idx is None:
            self._oracle_stats["vetoed"] += 1
            return None
        self._oracle_stats["accepted"] += 1
        return best_idx

    # -- hook --------------------------------------------------------------
    def decide(self, game) -> dict:
        """Frozen decision, with an optional learned intervention.

        The seam is `decide`, not `_search_shop`: the frozen search almost
        always finds *something* (often a swap, returned as `sell_joker`), and
        the "nothing worth buying" case falls through to `_v10_decide_shop`
        without `_search_shop` ever returning `leave_shop`.

        With `v12_oracle` off this method is a pure pass-through, which is what
        makes the parity control (byte-identical to frozen V10) meaningful.
        """
        if game.state != State.SHOP:
            self._buys_this_visit = 0
            return super().decide(game)

        enabled = (bool(V12_PARAMS.get("v12_oracle", False))
                   and self._table is not None)
        if not enabled:
            return super().decide(game)

        mode = str(V12_PARAMS.get("v12_mode", "entry"))
        max_buys = int(V12_PARAMS.get("v12_max_buys_per_visit", 1))
        budget = self._buys_this_visit < max_buys

        # (1) Shop entry with an open slot: choose by learned value. This is
        #     the decision the legacy state model could not rank, and the only
        #     moment where a candidate is actually still on the table.
        if budget and mode in ("entry", "both") and not self._in_shop:
            pick = self._oracle_pick(game)
            if pick is not None:
                self._buys_this_visit += 1
                self._oracle_stats["accepted"] += 1
                return {"type": "buy", "item_idx": pick}

        act = super().decide(game)

        # (1a) Prior: keep the policy's decision to spend AND its own ranking,
        #      and only break the near-ties that ranking leaves open.
        if (budget and mode == "prior"
                and str(act.get("type", "")) == "buy"):
            sub = self._oracle_prior(game, act)
            if sub is not None:
                self._buys_this_visit += 1
                return {"type": "buy", "item_idx": sub}

        # (1b) Override: keep the policy's decision to spend, change the object.
        if (budget and mode == "override"
                and str(act.get("type", "")) == "buy"):
            sub = self._oracle_override(game, act)
            if sub is not None:
                self._buys_this_visit += 1
                return {"type": "buy", "item_idx": sub}

        # (2) End of visit: add a purchase the frozen search declined. Rarely
        #     fires (the search fills open slots first), kept for completeness
        #     and measured in the ablation.
        if (budget and mode in ("additive", "both")
                and str(act.get("type", "")) == "leave_shop"):
            pick = self._oracle_pick(game)
            if pick is not None:
                self._buys_this_visit += 1
                self._oracle_stats["accepted"] += 1
                return {"type": "buy", "item_idx": pick}
        return act

    # -- introspection (bench/report) -------------------------------------
    def model_fingerprint(self) -> str:
        return self._table.fingerprint() if self._table else ""

    def oracle_stats(self) -> dict:
        return dict(self._oracle_stats)


# Convenience for benches/tools that want a pre-configured policy.
def make(model_path: Optional[Path | str] = None, **params) -> SearchShopV12:
    return SearchShopV12(params=params or None, model_path=model_path)
