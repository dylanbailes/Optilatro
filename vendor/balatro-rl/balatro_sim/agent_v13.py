"""agent_v13.py — V13: choose a shop action by looking ahead with a learned V(S).

WHY THIS EXISTS
===============
V12's oracle asks a hard question and asks it in the worst place. Its decision is
"the search picked item A; should I buy item B instead?", where A and B are two
candidates a heuristic had already ranked within a hair of each other. Measured on
86 replayed on-policy seeds: **48% of those pairs measure exactly identical**, and
on the ones that differ the shipped head is right 48.5% of the time. A near-tie is
the one region where no ranker can win, and five seed banks of screens (net
deltas -4, +6, +4, +3, -1) are what a 53.5%-correct rule produces.

S1 then tested the state-value model on that same near-tie question and it was also
at chance (sign rate 0.454 vs the incumbent's 0.485). But the S0 fit says V is
*strong* at the question the run-level objective actually poses: seed-ranked
correlation 0.808 over 100 held-out runs, AUC(won) 0.767, calibration monotone
across the whole ante axis. So V knows which portfolio is better and cannot
arbitrate hairline item differences — and V12 only ever asked it the latter.

V13 therefore changes the *question*, not the model: score the state each action
leads to, and take the best action, rather than substituting into a choice already
made. The candidate set stops being "the heuristic's own pick plus one rival" and
becomes every affordable action plus the action the frozen search wanted.

WHAT MAKES THIS CHEAP AND SAFE
==============================
* A buy transition is a `deepcopy` plus one `step` on the clone — NOT a rollout.
  Measured at ~1.7 ms, against ~4 s for the counterfactual rollout V12's corpus is
  built from. Scoring every affordable action costs a few milliseconds per shop.
* `state_features` is RNG-free and mutates nothing (pinned by
  `tests/test_state_value.py`), and every transition happens on a clone, so this
  cannot move the seed-exact stream.
* The frozen search's own action is always in the option set, and a replacement
  must beat it by `v13_margin`. So the mechanism can only act when V prefers a
  different action by a stated amount — the same "the learned component must clear
  a declared bar" discipline `v12_z` uses.
* `v13_lookahead` is OFF by default, and with it off `decide` is an exact
  pass-through to V12 (which with its own oracle off is byte-identical to frozen
  V10). That is the parity control, and it is the reason a null result here is
  interpretable.
* `lookahead_stats()` counts what actually happened — considered, replaced, added,
  and *fired*. An earlier lesson in this repo is that an inert mechanism looks
  exactly like a null result, so an arm must be able to show it engaged.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Optional

from .agent_v10 import V10_DEFAULTS
from .agent_v12 import V12_DEFAULTS, V12_PARAMS, SearchShopV12, candidates
from .game import State
from . import state_value as SV

# ────────────────────────────────────────────────────────────────────────────
# Tunables (V13-only)
# ────────────────────────────────────────────────────────────────────────────

V13_DEFAULTS = {
    # Master switch. OFF by default: an un-switched V13 must be
    # indistinguishable from V12 (and V12 with its oracle off, from frozen V10).
    "v13_lookahead": False,
    # Which shop kinds may be bought as a lookahead action. Jokers first, for the
    # same reason V12 started there: the slot-holding decision is the one the
    # shipped stack provably could not rank.
    "v13_kinds": ("joker",),
    # How much better an alternative action must score, in the value model's own
    # units (dense run return: ante plus a win term). 0 admits any improvement.
    # Exposed because the sweep is the instrument: the measured lesson from the
    # `prior` family is that the ordering of margins is more reproducible than
    # any single arm's net delta.
    "v13_margin": 0.0,
    # At most this many V13-chosen purchases per shop visit. Mirrors the repo's
    # churn guards; 1 == one deliberate decision per visit.
    "v13_max_buys_per_visit": 1,
    # Whether a lookahead action may be a purchase the frozen search declined.
    # With this off V13 only ever *replaces* an action the search already wanted
    # to take, which keeps V12's invariant that spending happens exactly when the
    # search wanted to spend. ON by default because leaving it off reproduces the
    # near-tie framing the measurements above say cannot work.
    "v13_allow_add": True,
}

V13_PARAMS = dict(V13_DEFAULTS)

# Default artifact, resolved from the package location the way
# `value_tables.DEFAULT_PATH` is, so the policy works from any CWD.
_MODEL_PATH = (Path(__file__).resolve().parents[3] / "results"
               / "state_value_model.joblib")


class SearchShopV13(SearchShopV12):
    """Frozen V10 search, plus a one-step lookahead over affordable actions."""

    policy_name = "search_shop_v13"

    def __init__(self, params=None, model_path: Optional[Path | str] = None,
                 **kwargs):
        given = dict(params or {})
        v12_only = {k: v for k, v in given.items() if k in V12_DEFAULTS}
        v10_only = {k: v for k, v in given.items() if k in V10_DEFAULTS}
        # V12's ctor forwards only V10-shaped keys to V10 and takes the rest, so
        # pass it its own plus the V10 ones and keep v13_* for ourselves.
        super().__init__(params={**v10_only, **v12_only}, **kwargs)
        V13_PARAMS.update({k: v for k, v in given.items() if k in V13_DEFAULTS})
        self._sv = self._load_model(model_path)
        self._v13_buys_this_visit = 0
        self._stats = {"considered": 0, "scored": 0, "replaced": 0, "added": 0,
                       "fired": 0, "no_model": 0, "transition_failed": 0}

    # -- model -------------------------------------------------------------
    @staticmethod
    def _load_model(path: Optional[Path | str]):
        """Load the fitted V(S) artifact, or None. Never raises.

        Returning None rather than raising keeps a missing artifact a *disabled
        feature* instead of a crashed run: the arm then behaves exactly like its
        control, which is the correct failure direction for an experiment.
        """
        import joblib
        candidates_paths = [Path(path)] if path else [_MODEL_PATH]
        for p in candidates_paths:
            try:
                if p.is_file():
                    pkg = joblib.load(p)
                    if pkg.get("layout") and pkg.get("model") is not None:
                        return pkg
            except Exception:
                continue
        return None

    def _value(self, game: Any) -> float:
        """V(S) for one state, in dense run-return units."""
        pkg = self._sv
        feats = SV.state_features(game)
        x = SV.encode(feats, pkg["layout"])
        return float(pkg["model"].predict([x])[0])

    # -- transitions -------------------------------------------------------
    @staticmethod
    def _after(game: Any, action: dict):
        """The state `action` leads to, or None if it is not applicable.

        A clone plus one step. RNG-free with respect to the live game and ~1.7 ms,
        which is what makes scoring every affordable action affordable.
        """
        try:
            g2 = deepcopy(game)
            g2.step(action)
        except Exception:
            return None
        return g2

    # -- hook --------------------------------------------------------------
    def decide(self, game) -> dict:
        """The frozen action, optionally replaced by a better-scoring one.

        With `v13_lookahead` off this is a pure pass-through, which is what makes
        the parity control meaningful.
        """
        if game.state != State.SHOP:
            self._v13_buys_this_visit = 0
            return super().decide(game)

        act = super().decide(game)

        if not bool(V13_PARAMS.get("v13_lookahead", False)):
            return act
        if self._sv is None:
            self._stats["no_model"] += 1
            return act
        if self._v13_buys_this_visit >= int(
                V13_PARAMS.get("v13_max_buys_per_visit", 1)):
            return act
        if not isinstance(act, dict):
            return act

        base_state = self._after(game, act)
        base_val = (self._value(base_state) if base_state is not None
                    else self._value(game))

        kinds = tuple(V13_PARAMS.get("v13_kinds", ("joker",)))
        allow_add = bool(V13_PARAMS.get("v13_allow_add", True))
        act_type = str(act.get("type", ""))
        act_idx = act.get("item_idx")
        base_is_buy = act_type == "buy" and act_idx is not None

        best_idx, best_val = None, base_val
        for idx, _item in candidates(game, kinds):
            if base_is_buy and idx == act_idx:
                continue
            # Without `allow_add`, only an action that *is* a purchase may be
            # changed: the search still controls whether money is spent at all.
            if not allow_add and not base_is_buy:
                continue
            self._stats["considered"] += 1
            nxt = self._after(game, {"type": "buy", "item_idx": idx})
            if nxt is None:
                self._stats["transition_failed"] += 1
                continue
            val = self._value(nxt)
            self._stats["scored"] += 1
            if val > best_val:
                best_idx, best_val = idx, val

        margin = float(V13_PARAMS.get("v13_margin", 0.0))
        if best_idx is None or (best_val - base_val) <= margin:
            return act

        if base_is_buy:
            self._stats["replaced"] += 1
        else:
            self._stats["added"] += 1
        self._stats["fired"] += 1
        self._v13_buys_this_visit += 1
        return {"type": "buy", "item_idx": int(best_idx)}

    # -- introspection (bench/report) --------------------------------------
    def lookahead_stats(self) -> dict:
        return dict(self._stats)

    def lookahead_enabled(self) -> bool:
        return bool(V13_PARAMS.get("v13_lookahead", False)) and self._sv is not None


def make(model_path: Optional[Path | str] = None, **params) -> SearchShopV13:
    return SearchShopV13(params=params or None, model_path=model_path)
