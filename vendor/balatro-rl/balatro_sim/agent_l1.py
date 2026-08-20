"""agent_l1.py — Layer-1 shop search: comparative mean-measure evaluation.

Wraps the Layer-0 heuristic (agent_v9.HeuristicV9). At each of the first
`search_shops` shop visits of a run the policy ranks EVERY affordable shop
item with the same mean measures a human can compute — expected score delta
on the best/typical drawable hands (composition, not draw order), expected
econ $/ante, expected tarot/spectral/card generations/ante, lifecycle/deck/
graph/synergy terms — and plays the single best first action (or leaves).

HUMAN-FAIR BY DESIGN: only information a human has access to is used. The
deck's DRAW ORDER, the contents of FUTURE shops, and the identities of FUTURE
bosses are never consulted — what cards remain in the deck (composition) is
legal, what order they will be drawn in is not. This policy is therefore
valid for benchmarks and usable for real runs.

`lookahead=True` (RESEARCH ONLY — NOT benchmark-valid): the legacy rollout
mode exploits the seed-exact sim as a perfect forward model, forking the game
with rollout.clone_game and rolling out the rest of the run for each
candidate. Reserved exclusively for prior-refinement / search-method research
runs (e.g. mining synergy priors); it must never appear in benchmark results
and is not usable for real runs (a real game has no forkable future).

Deterministic per seed: pure reads of game state (the isolated eval oracle
uses a throwaway RNG), so identical states always decide identically.
"""
from __future__ import annotations

from .agent_v9 import (
    ACTIVE_PARAMS,
    HeuristicV9,
    PLANET_HAND,
    VOUCHER_PRIORITY,
    _KIND_RANK,
    _rank_shop_items,
    decide_shop,
    forecast_beatable,
    joker_value,
    main_hand_type,
    pack_value,
    reference_hand,
    spectral_value,
    tarot_value,
    worth_spending,
)
from .game import State
from .rollout import clone_game, rollout


class SearchShopV9(HeuristicV9):
    """Layer-1 policy: Layer-0 heuristic + comparative mean-measure shop
    search (human-fair) or, with lookahead=True, rollout-verified shop
    decisions (research only)."""

    policy_name = "search_shop_v9"

    def __init__(self, params=None, search_shops: int = 1,
                 candidate_cap: int = 4, lookahead: bool = False,
                 max_rollout_steps: int = 4000):
        super().__init__(params)
        self._search_shops = search_shops
        self._candidate_cap = candidate_cap
        self._lookahead = lookahead
        self._max_rollout_steps = max_rollout_steps
        if lookahead:
            # Plain L0 for rollouts — a SearchShopV9 inside the search would
            # recurse. Lookahead is RESEARCH ONLY (not human-fair).
            self._rollout_policy = HeuristicV9()
        self._searches_done = 0
        self._searched_this_visit = False

    # ── decide ──────────────────────────────────────────────────────────────

    def decide(self, game) -> dict:
        st = game.state
        if st != State.SHOP:
            return super().decide(game)
        if not self._in_shop:
            self._in_shop = True
            self._rerolls_this_shop = 0
            self._searched_this_visit = False
        if (self._searches_done < self._search_shops
                and not self._searched_this_visit):
            # Search once per shop visit: pick the first action of the visit,
            # then L0 handles the rest of the visit.
            self._searched_this_visit = True
            act = (self._search_shop_rollout(game) if self._lookahead
                   else self._search_shop(game))
            if act.get("type") == "leave_shop":
                self._searches_done += 1
                self._in_shop = False
            return act
        act = decide_shop(game, self._rerolls_this_shop)
        if act.get("type") == "reroll":
            self._rerolls_this_shop += 1
        elif act.get("type") == "leave_shop":
            self._in_shop = False
            if self._searched_this_visit:
                self._searches_done += 1
                self._searched_this_visit = False
        return act

    # ── search (human-fair: comparative mean-measure evaluation) ────────────

    def _search_shop(self, game) -> dict:
        """Rank every affordable shop item by the human-fair composite value
        and play the argmax (or leave). No exact future prediction: the value
        is the same mean-measure composite L0 buys by (score delta on the
        best/typical drawable hands, econ $/ante, tarot/spectral gen/ante,
        lifecycle, deck support, graph, synergy), and the search simply makes
        the comparison explicit across ALL items instead of L0's greedy
        first-accept. Bounded: at most `candidate_cap` items are buyable
        first-actions; the rest of the visit is left to L0."""
        p = ACTIVE_PARAMS
        ref = reference_hand(game)
        surplus = forecast_beatable(game, p["tilt_surplus_margin"], ref)
        buys, need_sell = _rank_shop_items(game, ref, surplus)
        if need_sell is not None:
            # Make room first; the buy follows on the next decide call.
            return {"type": "sell_joker", "joker_idx": need_sell[1]}

        # Leave-vs-buy with the same money gates as L0: below the $25 interest
        # cap, when nothing strong is offered and the upcoming blind is
        # comfortably beatable, hold the money.
        save_mode = (
            game.ante > 2
            and game.dollars < p["interest_target"]
            and max((v for v, _ in buys), default=0.0) < p["save_strong_value"]
            and forecast_beatable(game, p["save_margin"], ref)
        )
        if buys:
            buys.sort(key=lambda b: (b[0], _KIND_RANK.get(
                game.current_shop[b[1]].kind, 1)), reverse=True)
            for value, idx in buys[:self._candidate_cap]:
                item = game.current_shop[idx]
                price = item.discounted_price(game.shop_discount)
                if (price <= game.dollars
                        and (not save_mode or value >= p["save_strong_value"])
                        and worth_spending(game, price, value)):
                    return {"type": "buy", "item_idx": idx}
        return {"type": "leave_shop"}

    # ── search (RESEARCH ONLY: rollout lookahead, not human-fair) ───────────

    def _search_shop_rollout(self, game) -> dict:
        """Legacy rollout-verified shop search — lookahead=True only.

        WARNING: exploits the seed-exact sim as a perfect forward model
        (exact future shops/draws/bosses). NOT human-fair, NOT benchmark-
        valid, NOT usable for real runs. Reserved for prior-refinement and
        search-method research.
        """
        ref = None
        ranked = []   # (value, item_idx)
        for i, item in enumerate(game.current_shop):
            if item.sold:
                continue
            price = item.discounted_price(game.shop_discount)
            if price > game.dollars:
                continue
            if item.kind == "joker":
                has_room = (len(game.jokers) < game.joker_slots
                            or item.edition == "Negative")
                if not has_room:
                    continue
                if ref is None:
                    ref = reference_hand(game)
                ranked.append((joker_value(game, item.key, item.edition, ref),
                               i))
            elif item.kind == "booster":
                ranked.append((pack_value(game, item.key), i))
            elif (item.kind == "planet"
                    and PLANET_HAND.get(item.key) == main_hand_type(game)
                    and len(game.consumable_hand) < game.consumable_slots):
                ranked.append((0.08, i))
            elif item.kind == "tarot":
                if len(game.consumable_hand) < game.consumable_slots:
                    ranked.append((tarot_value(game, item.key), i))
            elif item.kind == "spectral":
                if len(game.consumable_hand) < game.consumable_slots:
                    ranked.append((spectral_value(game, item.key), i))
            elif (item.kind == "voucher"
                    and VOUCHER_PRIORITY.get(item.key, 0) >= 2
                    and item.key not in game.vouchers):
                ranked.append((0.10 + 0.05 * VOUCHER_PRIORITY.get(item.key, 0),
                               i))
        ranked.sort(key=lambda t: t[0], reverse=True)
        candidates = [{"type": "leave_shop"}] + [
            {"type": "buy", "item_idx": i} for _, i in ranked[:self._candidate_cap]
        ]

        best_action, best_score = None, None
        for cand in candidates:
            fork = clone_game(game)
            fork.step(cand)
            out = rollout(fork, self._rollout_policy,
                          max_steps=self._max_rollout_steps)
            score = self._score(out)
            if best_score is None or score > best_score:
                best_action, best_score = cand, score
        return best_action

    @staticmethod
    def _score(out: dict) -> float:
        """Win dominates, then survival (ante > blind index), then assets."""
        if out["won"]:
            return 1e12
        return (out["ante"] * 1e6 + out["death_blind"] * 1e4
                + out["dollars"] * 10 + len(out["jokers"]) * 100)
