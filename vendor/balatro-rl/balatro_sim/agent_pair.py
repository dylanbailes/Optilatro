"""agent_pair.py — Balatro University-inspired Pair-First Reference Policy ('pair_bot').

Strategic & Mathematical Thesis:
1. Hyper-Consistency: 8-card deal has ~96.5% chance to draw a natural Pair from a standard
   deck, virtually eliminating draw-order brick rate.
2. Value Space: Requires only 2 cards to score, keeping 6+ cards in hand to hold Gold cards,
   Steel cards, Blue seals, and Baron/Shoot the Moon triggers.
3. Multi-Hand Scaling Engines: Pairs thrive on playing multiple hands per round, rapidly
   scaling combat jokers (Supernova, Ride the Bus, Green Joker, Square Joker, Wee Joker).
4. Boss Resilience: Immune to suit debuff bosses (Goad, Window, Club, Head).
5. Dynamic Anchor Rank: Adapts to owned jokers (10s/4s for Walkie Talkie, 8s/5s/2s/A for
   Fibonacci, 2s for Wee/Hack, non-face for Ride the Bus) or modal deck rank.
"""
from __future__ import annotations

import itertools
import math
import random
from collections import Counter, defaultdict
from copy import copy as shallowcopy, deepcopy
from typing import Optional

from .agent_v9 import (
    ACTIVE_PARAMS,
    PLANET_HAND,
    VOUCHER_PRIORITY,
    _boss_play_filter,
    _card_quality,
    _combo_priority,
    _size_priority_bounds,
    _structure_pool,
    deck_condition_bonus,
    econ_per_ante,
    eval_hand_score,
    gen_per_ante,
    lifecycle_bonus,
    next_blind_target,
    pack_value,
)
from .agent_v10 import (
    BAD_BOSSES,
    V10_PARAMS,
    _joker_sell_value,
    _mail_target_rank,
    _trading_used,
    _v10_decide_booster,
    _v10_decide_consumable,
    _v10_decide_hand,
    _v10_maybe_use_planet,
    _v10_tarot_value,
)
from .agent_v11 import (
    SearchShopV11,
    V11_PARAMS,
    _optimize_joker_order_v11,
    _v11_desperate_shop_action,
)
from .card import Card
from .game import BalatroGame, State
from .hand_eval import evaluate_hand
from .jokers.base import JOKER_REGISTRY, JokerInstance


# Shop utility uses score-lift points plus bounded future-run value. These cutoffs
# are intentionally local to PairBot; they are not trained on benchmark outcomes.
_PAIR_JOKER_BUY_THRESHOLD = 1.0
_PAIR_SWAP_MARGIN = 0.20
_PAIR_DISCARD_SEARCH_POOL_SIZE = 4
_PAIR_DISCARD_SEARCH_MAX_CANDIDATES = 6
_PAIR_DISCARD_SEARCH_SAMPLES = 3
_PAIR_DISCARD_SEARCH_SCORES_PER_SAMPLE = 2
_PAIR_DISCARD_SEARCH_MAX_HAND_SIZE = 8
_PAIR_DISCARD_SEARCH_MAX_SUBSETS_PER_HAND = max(
    sum(math.comb(hand_size, size) for size in range(1, min(5, hand_size) + 1))
    for hand_size in range(1, _PAIR_DISCARD_SEARCH_MAX_HAND_SIZE + 1)
)
_PAIR_DISCARD_SEARCH_SUBSET_BUDGET = (
    _PAIR_DISCARD_SEARCH_MAX_CANDIDATES
    * _PAIR_DISCARD_SEARCH_SAMPLES
    * _PAIR_DISCARD_SEARCH_MAX_SUBSETS_PER_HAND
)
_PAIR_DISCARD_SEARCH_SCORE_BUDGET = (
    _PAIR_DISCARD_SEARCH_MAX_CANDIDATES
    * _PAIR_DISCARD_SEARCH_SAMPLES
    * _PAIR_DISCARD_SEARCH_SCORES_PER_SAMPLE
)
_PAIR_DISCARD_SEARCH_SEED = 0xBA1A7
_PAIR_BOOSTER_MULTIPLIER = 4.0
_PAIR_SHOP_KIND_ORDER = {"joker": 0, "voucher": 1, "booster": 2, "pack": 2, "planet": 3, "tarot": 4}
_PAIR_TAROT_BUYS = {
    "c_death", "c_hanged_man", "c_hermit", "c_temperance",
    "c_magician", "c_empress", "c_hierophant",
}
_PAIR_SQUARE_KEYS = {"j_square", "j_square_joker"}
_PAIR_GROWTH_KEYS = {
    "j_supernova", "j_ride_the_bus", "j_green_joker", "j_constellation",
    "j_lucky_cat", "j_hologram", "j_square", "j_square_joker",
    "j_wee", "j_red_card", "j_castle", "j_flash", "j_fortune_teller",
    "j_rocket", "j_erosion", "j_spare_trousers", "j_campfire",
    "j_vampire", "j_caino", "j_gros_michel", "j_madness",
}


def _pair_remaining_blinds(game: BalatroGame) -> float:
    """Estimate remaining blind opportunities without consulting deck order."""
    ante = max(1, int(getattr(game, "ante", 1) or 1))
    if ante > 8 or game.state == State.GAME_OVER:
        return 0.0
    blind_idx = min(2, max(0, int(getattr(game, "blind_idx", 0) or 0)))
    just_cleared = game.state in (State.SHOP, State.BOOSTER_OPEN)
    if just_cleared:
        current_ante_blinds = max(0.0, 3.0 - blind_idx)
    elif game.state == State.SELECTING_HAND:
        base_hands = max(1, int(getattr(game, "base_hands", 4) or 4))
        fraction = min(1.0, max(0.0, float(getattr(game, "hands_left", base_hands)) / base_hands))
        current_ante_blinds = max(0.0, 2.0 - blind_idx + fraction)
    else:
        current_ante_blinds = max(0.0, 3.0 - blind_idx)
    return max(0.0, (8 - ante) * 3.0 + current_ante_blinds)


def _pair_play_opportunities(game: BalatroGame) -> float:
    """A conservative estimate of future Pair plays from hands and runway."""
    blinds = _pair_remaining_blinds(game)
    hands = max(1.0, float(getattr(game, "base_hands", 4) or 4))
    return blinds * min(3.0, max(1.0, hands * 0.55))


def _all_run_cards(game: BalatroGame) -> list[Card]:
    return list(game.deck) + list(game.hand) + list(game.spent)


def _joker_default_state(key: str) -> dict:
    """Return an isolated initial state for a not-yet-owned joker."""
    effect = JOKER_REGISTRY.get(key)
    return deepcopy(getattr(effect, "state_defaults", {}) or {})


def _joker_runtime_state(game: BalatroGame, key: str, state=None) -> dict:
    if state is not None:
        return state
    for joker in getattr(game, "jokers", ()):
        if getattr(joker, "key", None) == key:
            return getattr(joker, "state", {}) or {}
    return _joker_default_state(key)


def _pair_scoring_exposure(game: BalatroGame, key: str, state=None) -> float:
    """Discount snapshot scoring for jokers whose own effect expires over time."""
    state = _joker_runtime_state(game, key, state)
    remaining_blinds = _pair_remaining_blinds(game)
    if remaining_blinds <= 0:
        return 0.0
    if key == "j_gros_michel":
        rounds = max(1.0, remaining_blinds)
        full_rounds = int(rounds)
        fractional_round = rounds - full_rounds
        expected_active = sum((5.0 / 6.0) ** i for i in range(full_rounds))
        expected_active += fractional_round * (5.0 / 6.0) ** full_rounds
        return min(1.0, expected_active / rounds)
    if key == "j_ice_cream":
        strength, decay, opportunities = max(0.0, float(state.get("chips", 100))), 5.0, _pair_play_opportunities(game)
    elif key == "j_popcorn":
        strength, decay, opportunities = max(0.0, float(state.get("mult", 20))), 4.0, remaining_blinds
    elif key == "j_ramen":
        strength = max(1.0, float(state.get("mult", 2.0)))
        decay = 0.01
        opportunities = remaining_blinds * max(0, int(getattr(game, "base_discards", 3) or 0)) * 0.45
    elif key in ("j_seltzer", "j_selzer"):
        strength, decay, opportunities = max(0.0, float(state.get("hands", 10))), 1.0, _pair_play_opportunities(game)
    else:
        return 1.0
    if strength <= 0:
        return 0.0
    # Ramen decays only when discards are made. With no discards available its
    # current multiplier remains intact throughout the modeled runway.
    if opportunities <= 0:
        return 1.0

    lifetime = strength / decay
    active = min(opportunities, lifetime)
    average_strength = max(0.0, strength - decay * max(0.0, active - 1.0) / 2.0)
    effective = active * average_strength / (strength * opportunities)
    # Keep a short-lived scoring joker relevant for the blind it can still save,
    # while making its poor long-run value visible to late-shop comparisons.
    return min(1.0, max(0.45, effective))


def _pair_joker_lifecycle_value(
    game: BalatroGame,
    key: str,
    state=None,
    rep_pair: Optional[list[Card]] = None,
    base_score: float = 1.0,
) -> float:
    """Context-sensitive future value for the Pair build, independent of RNG.

    Current engine scoring is measured separately by eval_hand_score. This term
    estimates only future growth, supported deck effects, and economy/creation
    over the remaining Pair-play runway; owned joker counters are read live.
    """
    state = _joker_runtime_state(game, key, state)
    remaining_blinds = _pair_remaining_blinds(game)
    if remaining_blinds <= 0:
        return 0.0
    opportunities = _pair_play_opportunities(game)
    cards = _all_run_cards(game)
    deck_size = max(1, len(cards))
    pair_level = max(1, int((getattr(game, "planet_levels", {}) or {}).get("Pair", 1)))
    pair_mult = max(2.0, 1.0 + pair_level)
    pair_chips = max(20.0, 10.0 + 15.0 * (pair_level - 1))
    mult_growth = 0.0
    chip_growth = 0.0
    xmult_growth = 0.0
    context_value = 0.0

    # Finite scoring jokers lose value as their remaining counter runs down.
    # The scoring snapshot is exposure-discounted separately; this small runway
    # term preserves the distinction between a fresh copy and one near expiry.
    finite_defaults = {
        "j_ice_cream": 100.0,
        "j_popcorn": 20.0,
        "j_ramen": 2.0,
        "j_seltzer": 10.0,
        "j_selzer": 10.0,
    }
    if key in finite_defaults:
        if key == "j_ramen":
            remaining_strength = max(0.0, float(state.get("mult", 2.0) or 1.0) - 1.0)
            maximum_strength = finite_defaults[key] - 1.0
        else:
            counter_key = "chips" if key == "j_ice_cream" else "hands" if key in ("j_seltzer", "j_selzer") else "mult"
            remaining_strength = max(0.0, float(state.get(counter_key, finite_defaults[key]) or 0.0))
            maximum_strength = finite_defaults[key]
        remaining_fraction = min(1.0, remaining_strength / max(1.0, maximum_strength))
        context_value += 0.12 * math.log1p(
            remaining_blinds * _pair_scoring_exposure(game, key, state) * remaining_fraction
        )

    # Forecast what this policy actually triggers: Pair plays, non-face scoring
    # under Ride the Bus, four-card Square plays, deck-supported rank/suit effects.
    if key in ("j_green_joker", "j_supernova"):
        mult_growth = max(0.0, opportunities - 1.0) * 0.5
        if key == "j_green_joker":
            mult_growth *= 0.8  # allow for the occasional discard penalty
    elif key == "j_ride_the_bus":
        nonface = sum(1 for card in cards if getattr(card, "rank", None) not in FACE_RANKS) / deck_size
        mult_growth = max(0.0, opportunities - 1.0) * min(1.0, nonface) * 0.45
    elif key == "j_fortune_teller":
        tarot_rate = max(0.0, gen_per_ante(game, "j_cartomancer")) * 0.15
        mult_growth = max(0.0, remaining_blinds / 3.0 * tarot_rate) * 0.5
    elif key == "j_red_card":
        mult_growth = remaining_blinds * 0.075
    elif key == "j_flash":
        bank_factor = min(0.65, max(0.08, (float(getattr(game, "dollars", 0)) + 8.0) / 45.0))
        mult_growth = remaining_blinds * bank_factor * 0.25
    elif key in _PAIR_SQUARE_KEYS:
        # PairBot sometimes attaches two safe cards to realize Square's 4-card
        # condition; weight its +4-chip growth by that policy's partial trigger rate.
        chip_growth = max(0.0, opportunities - 1.0) * 0.45 * 4.0
    elif key == "j_spare_trousers":
        # A Pair-first policy rarely has a Two Pair to trigger this, so discount
        # growth unless the visible deck already contains duplicate ranks.
        rank_counts = Counter(getattr(card, "rank", None) for card in cards)
        pair_ranks = sum(1 for count in rank_counts.values() if count >= 2)
        two_pair_rate = min(0.20, pair_ranks / deck_size * 1.5)
        mult_growth = opportunities * two_pair_rate * 2.0
    elif key == "j_vampire":
        enhanced = sum(
            1 for card in cards
            if getattr(card, "enhancement", None) not in (None, "None", "Base")
        )
        # It only consumes enhancements on played scoring cards; two cards per
        # Pair play are exposed, rather than all five selected cards.
        xmult_growth = opportunities * min(2.0, enhanced * 2.0 / deck_size) * 0.1
    elif key == "j_erosion":
        deck_remaining = max(0, int(getattr(game, "deck_remaining", len(game.deck))))
        missing = max(0, 52 - deck_remaining)
        expected_thinning = min(2.0, float(getattr(game, "base_discards", 3) or 0) * 0.12)
        mult_growth = max(0.0, opportunities - 1.0) * expected_thinning * 4.0
        # Existing deck thinning has already been counted by the scoring oracle.
        context_value += 0.02 * math.log1p(missing)
    elif key == "j_wee":
        twos = sum(1 for card in cards if getattr(card, "rank", None) == 2)
        pair_two_rate = min(0.35, twos / deck_size * 2.5)
        chip_growth = opportunities * pair_two_rate * 4.0
    elif key == "j_castle":
        target_suit = state.get("suit", state.get("target_suit"))
        suit_counts = Counter(getattr(card, "suit", None) for card in cards)
        target_fraction = (suit_counts.get(target_suit, 0) / deck_size if target_suit else 0.25)
        discards = max(0, int(getattr(game, "base_discards", 3) or 0))
        chip_growth = remaining_blinds * discards * target_fraction * 0.55 * 3.0
    elif key == "j_constellation":
        blue_seals = sum(1 for card in cards if getattr(card, "seal", None) == "Blue")
        expected_planets = remaining_blinds * (0.15 + min(0.35, blue_seals * max(1, getattr(game, "hand_size", 8)) / deck_size * 0.4))
        xmult_growth = expected_planets * 0.1
    elif key == "j_lucky_cat":
        lucky_cards = sum(1 for card in cards if getattr(card, "enhancement", None) == "Lucky")
        # Two scoring cards per Pair; Lucky's two independent rolls yield
        # 1/5 + 1/15 expected Cat triggers before Oops! All 6s.
        expected_triggers = opportunities * lucky_cards * 2.0 / deck_size * (1.0 / 5.0 + 1.0 / 15.0)
        xmult_growth = expected_triggers * 0.25
    elif key == "j_hologram":
        expected_added_cards = remaining_blinds * (0.10 + 0.10 * min(1.0, float(getattr(game, "dollars", 0)) / 20.0))
        xmult_growth = expected_added_cards * 0.25
    elif key == "j_turtle_bean":
        bonus = max(0, int(state.get("bonus", 5) or 0))
        active_rounds = min(float(bonus), remaining_blinds)
        full_rounds = int(active_rounds)
        expected_extra_slots = sum(max(0, bonus - i) for i in range(full_rounds))
        if active_rounds % 1.0:
            expected_extra_slots += (active_rounds % 1.0) * max(0, bonus - full_rounds)
        # Temporary hand size improves Pair consistency and held-card capacity;
        # its per-round decay makes it worth less late than Juggler's permanent slot.
        context_value += 0.16 * math.log1p(expected_extra_slots)
    elif key == "j_juggler":
        context_value += 0.16 * math.log1p(remaining_blinds)
    elif key == "j_madness":
        non_boss_blinds = remaining_blinds * (2.0 / 3.0)
        xmult_growth = 0.5 * non_boss_blinds
        # Madness gains power by consuming other jokers, which is a portfolio
        # risk rather than free growth. Discount future gain when alternatives
        # would be destroyed; a lone Madness has no such downside.
        other_jokers = sum(1 for joker in getattr(game, "jokers", ()) if joker.key != key)
        context_value -= min(0.80, other_jokers * non_boss_blinds * 0.035)
    elif key == "j_campfire":
        expected_sales = remaining_blinds / 3.0 * 0.35
        xmult_growth = min(1.0, expected_sales) * 0.25
    elif key == "j_caino":
        expected_face_destructions = remaining_blinds * max(
            0, int(getattr(game, "base_discards", 3) or 0)
        ) * 0.018
        xmult_growth = expected_face_destructions * 0.1
    elif key == "j_burglar":
        # Three extra hands per blind compound the reliability of a Pair plan.
        context_value += 0.20 * math.log1p(remaining_blinds * 0.35)
    elif key == "j_drunkard":
        context_value += 0.08 * math.log1p(remaining_blinds)

    # A Pair level changes the scale of each future flat-stat increment. The
    # scoring-pressure term puts more weight on growth when the next blind is tight.
    try:
        upcoming_target = max(0.0, float(next_blind_target(game)))
    except (AttributeError, KeyError, TypeError, ValueError):
        upcoming_target = 0.0
    projected_score = max(1.0, float(base_score)) * max(1.0, float(getattr(game, "base_hands", 4) or 4)) * 0.60
    pressure = min(1.5, max(0.55, upcoming_target / projected_score)) if upcoming_target else 0.7
    growth_value = (
        0.42 * math.log1p(mult_growth / pair_mult)
        + 0.42 * math.log1p(chip_growth / pair_chips)
        + 0.62 * math.log1p(xmult_growth * max(1.0, float(state.get("xmult", state.get("mult", 1.0)) or 1.0)))
    ) * pressure

    # Pair-specific deck support (e.g. Steel/Baron held assets) supplements the
    # representative hand without counting future cards or using deck order.
    if key == "j_baron":
        kings = sum(1 for card in cards if getattr(card, "rank", None) == 13)
        held_slots = max(0, int(getattr(game, "hand_size", 8)) - 2)
        context_value += 0.45 * math.log1p(0.5 * kings * held_slots / deck_size)
    elif key == "j_mime":
        triggers = sum(
            1 for card in cards
            if getattr(card, "seal", None) in ("Blue", "Red")
            or getattr(card, "enhancement", None) in ("Steel", "Gold")
        )
        expected_held_triggers = triggers * max(0, int(getattr(game, "hand_size", 8)) - 2) / deck_size
        context_value += 0.45 * math.log1p(expected_held_triggers)
    context_value += 2.0 * max(0.0, deck_condition_bonus(game, key))

    # Use the simulator's documented trigger-rate estimates, but project only
    # across this run's remaining blinds and give cash more weight when scarce.
    remaining_antes = remaining_blinds / 3.0
    try:
        expected_money = max(0.0, float(econ_per_ante(game, key))) * remaining_antes
    except (TypeError, ValueError):
        expected_money = 0.0
    if key == "j_egg":
        expected_money += 3.0 * remaining_blinds
    if key == "j_rocket":
        future_bosses = max(0.0, remaining_antes)
        expected_money += max(0.0, float(state.get("bonus", 1) or 1)) * remaining_blinds + 2.0 * future_bosses
    cash_need = max(0.45, 1.0 - min(25.0, max(0.0, float(getattr(game, "dollars", 0)))) / 50.0)
    money_value = 0.40 * math.log1p(expected_money / 10.0) * cash_need

    try:
        expected_generations = max(0.0, float(gen_per_ante(game, key))) * remaining_antes
    except (TypeError, ValueError):
        expected_generations = 0.0
    if len(getattr(game, "consumable_hand", ())) >= getattr(game, "consumable_slots", 2):
        expected_generations *= 0.6
    generation_value = 0.22 * math.log1p(expected_generations)

    # Retain the common lifecycle prior at a small weight; the Pair-specific
    # terms above supply runway, live state, deck support, and scoring pressure.
    common_lifecycle = max(-0.25, min(0.35, float(lifecycle_bonus(game, key))))
    return growth_value + context_value + money_value + generation_value + 0.75 * common_lifecycle


def _pair_scoring_horizon(game: BalatroGame) -> float:
    """Modest early-run premium for repeatable scoring without discounting rescue power."""
    opportunities = min(30.0, _pair_play_opportunities(game))
    return 1.0 + 0.18 * math.log1p(opportunities) / math.log(31.0)


def _pair_price_penalty(game: BalatroGame, price: int) -> float:
    """Small deterministic liquidity/interest penalty for comparing purchases."""
    price = max(0, int(price))
    if price == 0:
        return 0.0
    dollars = max(0, int(getattr(game, "dollars", 0)))
    after = max(0, dollars - price)
    interest_lost = max(0, dollars // 5 - after // 5)
    penalty = 0.18 * price / max(5.0, float(dollars)) + 0.12 * interest_lost
    if after < 5 and int(getattr(game, "ante", 1)) > 1:
        penalty += 0.18
    return penalty


def _pair_card_stable_key(card: Card, j_keys: set[str]) -> tuple:
    """Canonical card ordering for valuation; never let shuffled deck order leak in."""
    held = _is_held_in_hand_value_card(card, j_keys)
    return (
        0 if held else 1,
        -_card_quality(card),
        int(getattr(card, "rank", 0) or 0),
        str(getattr(card, "suit", "")),
        str(getattr(card, "enhancement", "None")),
        str(getattr(card, "edition", "None")),
        str(getattr(card, "seal", "None")),
    )



def _pair_play_details(game: BalatroGame, indices, boss: str):
    """Resolve explicit selections to the hand the engine will actually score.

    Cerulean Bell appends its forced card even when the player omits it from the
    selection. That card can be played without scoring, so the shared V9 filter
    (which expects the Bell among scoring cards) is not a correct legality test
    for PairBot. Include the forced card before hand evaluation and apply only
    selection restrictions that exist on top of the engine's automatic add.
    """
    requested_indices = list(indices)
    played_indices = list(requested_indices)
    played_cards = [game.hand[index] for index in requested_indices]

    if boss == "bl_cerulean" and game.bell_card is not None:
        for bell_idx, card in enumerate(game.hand):
            if card is game.bell_card:
                if all(card is not played for played in played_cards):
                    played_indices.append(bell_idx)
                    played_cards.append(card)
                break

    hand_type, scoring_cards = evaluate_hand(played_cards)
    # Cerulean's one-card constraint is implemented by the engine's forced
    # inclusion, not by requiring that card to score. Eye/Mouth still inspect
    # the resolved hand type through the standard filter.
    filter_boss = "" if boss == "bl_cerulean" else boss
    legal = _boss_play_filter(
        game, requested_indices, hand_type, scoring_cards, filter_boss,
    )
    return played_indices, played_cards, hand_type, scoring_cards, legal


def _best_non_pair_play(game: BalatroGame, allow_pair: bool = False) -> Optional[dict]:
    """Best bounded, boss-legal option; tactical pivots exclude Pair by default."""
    hand = game.hand
    if not hand:
        return None
    boss = game.current_blind.boss_key if game._boss_effects_on() else ""
    bounds = _size_priority_bounds(hand)
    sizes = [5] if boss == "bl_psychic" else range(1, min(5, len(hand)) + 1)
    candidates = []
    # Preserve representation diversity across play sizes: a single global
    # enumeration cap can be exhausted by 1-4 card subsets before any 5-card
    # flush/straight/full-house candidate is considered.
    for size in sizes:
        if size not in bounds:
            continue
        for combo in itertools.combinations(range(len(hand)), size):
            cards = [hand[i] for i in combo]
            try:
                played_indices, played_cards, hand_type, scoring_cards, legal = _pair_play_details(
                    game, combo, boss,
                )
            except Exception:
                continue
            if (hand_type == "Pair" and not allow_pair) or not legal:
                continue
            candidates.append((
                _combo_priority(played_cards), combo, played_indices,
                hand_type, scoring_cards, played_cards,
            ))

    # Keep each play size represented before capping: otherwise a large number
    # of low-size subsets can crowd out five-card patterns that score best.
    by_priority = sorted(candidates, key=lambda item: (-item[0], item[1]))
    selected = []
    seen_sizes = set()
    for candidate in by_priority:
        size = len(candidate[1])
        if size not in seen_sizes:
            selected.append(candidate)
            seen_sizes.add(size)
    selected.extend(candidate for candidate in by_priority if candidate not in selected)
    best = None
    for _, combo, played_indices, hand_type, scoring_cards, test_cards in selected[:36]:
        played_set = set(played_indices)
        held = [card for i, card in enumerate(hand) if i not in played_set]
        try:
            score = eval_hand_score(
                game, hand_type, scoring_cards, test_cards, held_cards=held
            )
        except Exception:
            continue
        candidate = {"score": score, "indices": list(combo), "hand_type": hand_type}
        if best is None or (candidate["score"], -len(combo), tuple(-i for i in combo)) > (
            best["score"], -len(best["indices"]), tuple(-i for i in best["indices"])
        ):
            best = candidate
    return best


def _pair_plan_card_value(card: Card) -> tuple:
    """Visible card-composition key; excludes identity but retains card state."""
    return (
        int(card.rank), str(card.suit), str(card.enhancement),
        str(card.edition), str(card.seal), bool(card.debuffed), bool(card.flipped),
    )


def _pair_plan_card_from_value(value: tuple, card_id: int) -> Card:
    """Make an isolated known-value card without advancing Card's global ID counter."""
    card = Card.__new__(Card)
    (
        card.rank, card.suit, card.enhancement, card.edition, card.seal,
        card.debuffed, card.flipped,
    ) = value
    card.id = card_id
    card._id_counter = 0
    return card


def _pair_plan_sample_value(
    game: BalatroGame,
    hand: list[Card],
    drawn_values: list[tuple],
    boss: str,
    score_budget: list[int],
    subset_budget: list[int],
) -> float:
    """Best Pair-first continuation score from one composition-sampled hand.

    Hand subsets are enumerated without sampling card identity. Only the best
    proxy-ranked Pair and tactical candidate are run through the real isolated
    scorer, keeping the expensive oracle calls bounded to two per sample.
    """
    view = shallowcopy(game)
    view.hand = hand
    # Scoring hooks receive an isolated game view too. Remove sampled cards
    # from the remaining composition, then rebuild its hidden pile in canonical
    # order so hooks cannot observe identities or simulator draw order.
    remaining_counts = Counter(_pair_plan_card_value(card) for card in game.deck)
    for value in drawn_values:
        if remaining_counts[value] > 0:
            remaining_counts[value] -= 1
    visible_deck = sorted(
        value for value, count in remaining_counts.items() for _ in range(count)
    )
    view.deck = [
        _pair_plan_card_from_value(value, -(index + 1))
        for index, value in enumerate(visible_deck)
    ]
    if boss == "bl_psychic":
        sizes = (5,)
    else:
        sizes = range(1, min(5, len(hand)) + 1)

    best_pair = None
    best_tactical = None
    subset_budget_exhausted = False
    for size in sizes:
        for combo in itertools.combinations(range(len(hand)), size):
            if subset_budget[0] >= _PAIR_DISCARD_SEARCH_SUBSET_BUDGET:
                subset_budget_exhausted = True
                break

            subset_budget[0] += 1
            try:
                played_indices, played_cards, hand_type, scoring_cards, legal = _pair_play_details(
                    view, combo, boss,
                )
            except (IndexError, ValueError):
                continue
            if not legal:
                continue

            if boss == "bl_psychic":
                rank_counts = Counter(
                    hand[index].rank for index in combo
                    if hand[index].enhancement != "Stone"
                )
                pair_driven = any(count >= 2 for count in rank_counts.values())
            else:
                pair_driven = hand_type == "Pair"

            if hand_type == "Pair" or pair_driven:
                bucket = "pair"
            elif hand_type != "Pair":
                bucket = "tactical"
            else:
                continue

            proxy = (
                _combo_priority(played_cards),
                sum(_card_quality(card) for card in scoring_cards if not card.debuffed),
                -len(combo),
                tuple(_pair_plan_card_value(hand[index]) for index in combo),
            )
            candidate = (proxy, tuple(combo), hand_type, scoring_cards, played_indices, played_cards)
            if bucket == "pair":
                if best_pair is None or proxy > best_pair[0]:
                    best_pair = candidate
            elif best_tactical is None or proxy > best_tactical[0]:
                best_tactical = candidate
        if subset_budget_exhausted:
            break

    best_score = 0.0
    for candidate in (best_pair, best_tactical):
        if candidate is None or score_budget[0] >= _PAIR_DISCARD_SEARCH_SCORE_BUDGET:
            continue
        _proxy, _combo, hand_type, scoring_cards, played_indices, played_cards = candidate
        played_set = set(played_indices)
        held_cards = [card for index, card in enumerate(hand) if index not in played_set]
        score_budget[0] += 1
        try:
            score = eval_hand_score(
                view, hand_type, scoring_cards, played_cards, held_cards=held_cards,
            )
        except Exception:
            continue
        best_score = max(best_score, float(score))
    return best_score


def _pair_plan_discard(
    game: BalatroGame,
    discard_indices,
    baseline_score: float = 0.0,
    protected_indices=(),
) -> Optional[dict]:
    """Choose a bounded human-fair discard by sampled remaining-deck composition.

    The search considers at most six discard sets from four weak candidates,
    three deterministic without-replacement draws per set, and at most two
    isolated real-score evaluations per draw (36 total). The sampled pool is
    sorted by visible card value before sampling, so the choice cannot depend
    on the remaining deck's hidden order. It is deliberately skipped for
    overfilled hands and Cerulean Bell, where future forced-card state needs a
    separate model.
    """
    hand = game.hand
    if (
        not hand
        or game.discards_left <= 0
        or not game.deck
        or len(hand) > _PAIR_DISCARD_SEARCH_MAX_HAND_SIZE
    ):
        return None
    boss = game.current_blind.boss_key if game._boss_effects_on() else ""
    if boss in {"bl_cerulean", "bl_serpent"}:
        # Bell adds a forced card, while Serpent draws three regardless of the
        # discard count. Neither has the planner's simple refill semantics.
        return None

    j_keys = {getattr(joker, "key", "") for joker in getattr(game, "jokers", ())}
    protected = set(protected_indices)
    pool = sorted(
        {
            index for index in discard_indices
            if 0 <= index < len(hand)
            and index not in protected
            and not _is_held_in_hand_value_card(hand[index], j_keys)
        },
        key=lambda index: (
            _card_quality(hand[index]), _pair_plan_card_value(hand[index]), index,
        ),
    )[:_PAIR_DISCARD_SEARCH_POOL_SIZE]
    # Preserve visible poker structures before searching: do not discard cards
    # from a flush/straight chase or break a pair/triplet for a speculative draw.
    structure_pool, _structure_target = _structure_pool(
        hand, min_suit=4, min_run=4, min_pairs=2,
    )
    if structure_pool is not None:
        pool = [index for index in pool if index in structure_pool]

    max_discard = min(2, len(pool), len(game.deck), len(hand) - 1)
    if max_discard <= 0:
        return None

    singletons = [(index,) for index in pool]
    pairs = list(itertools.combinations(pool, 2)) if max_discard >= 2 else []

    def candidate_key(combo):
        # Order by discard count and visible values; hand indices are only a
        # final tie-break between otherwise indistinguishable visible cards.
        return (
            len(combo),
            sum(_card_quality(hand[index]) for index in combo),
            tuple(sorted(_pair_plan_card_value(hand[index]) for index in combo)),
            tuple(combo),
        )

    candidates = sorted(
        singletons + pairs, key=candidate_key,
    )[:_PAIR_DISCARD_SEARCH_MAX_CANDIDATES]
    if not candidates:
        return None

    composition = sorted(_pair_plan_card_value(card) for card in game.deck)
    rng = random.Random(_PAIR_DISCARD_SEARCH_SEED)
    sample_draws = {
        size: [rng.sample(composition, size) for _ in range(_PAIR_DISCARD_SEARCH_SAMPLES)]
        for size in sorted({len(candidate) for candidate in candidates})
    }
    score_budget = [0]
    subset_budget = [0]
    best_candidate = None
    best_value = float(baseline_score)
    for candidate in candidates:
        kept = [card for index, card in enumerate(hand) if index not in candidate]
        sampled_scores = []
        for sample_index, draw in enumerate(sample_draws[len(candidate)]):
            drawn_cards = [
                _pair_plan_card_from_value(
                    value, -(len(composition) + 1 + sample_index * len(draw) + draw_index),
                )
                for draw_index, value in enumerate(draw)
            ]
            sampled_scores.append(
                _pair_plan_sample_value(
                    game, kept + drawn_cards, draw, boss, score_budget, subset_budget,
                )
            )
        expected_score = sum(sampled_scores) / len(sampled_scores)
        if expected_score > best_value + 1e-9:
            best_value = expected_score
            best_candidate = candidate

    if best_candidate is None:
        return None
    return {
        "indices": list(best_candidate),
        "expected_score": best_value,
        "baseline_score": float(baseline_score),
        "candidate_count": len(candidates),
        "sample_count": _PAIR_DISCARD_SEARCH_SAMPLES,
        "score_evaluations": score_budget[0],
        "subset_evaluations": subset_budget[0],
    }


def _shop_kind_order(item) -> int:
    return _PAIR_SHOP_KIND_ORDER.get(getattr(item, "kind", ""), 4)


def _shop_item_key(item) -> str:
    return str(getattr(item, "key", ""))


def _item_price(item, game) -> int:
    return int(item.discounted_price(game.shop_discount))


def _pair_tarot_shop_value(game: BalatroGame, key: str, rep_pair: list[Card], rep_held: list[Card], base_score: float) -> float:
    if key in ("c_mercury", "pl_mercury"):
        leveled = _pair_eval_hand_score(
            game, "Pair", rep_pair, rep_pair, held_cards=rep_held,
            level_override={"Pair": 1},
        )
        return 0.25 + 3.5 * max(0.0, (leveled - base_score) / max(1.0, float(base_score)))
    if key in _PAIR_TAROT_BUYS:
        return 0.35 + 3.0 * max(0.0, float(_v10_tarot_value(game, key)))
    return 0.0


def _pair_booster_shop_value(game: BalatroGame, item) -> float:
    key = _shop_item_key(item)
    base = _PAIR_BOOSTER_MULTIPLIER * max(0.0, float(pack_value(game, key)))
    if key.startswith("p_buffoon"):
        return base + 0.25 + (0.25 if not game.jokers else 0.0)
    if key.startswith("p_celestial"):
        pair_level = max(1, int((getattr(game, "planet_levels", {}) or {}).get("Pair", 1)))
        return base + 0.20 + (0.18 if pair_level <= 2 else 0.0)
    if key.startswith("p_standard"):
        return base + 0.12 + (0.18 if any(j.key == "j_hologram" for j in game.jokers) else 0.0)
    return base


def _pair_shop_item_value(game: BalatroGame, item, rep_pair, rep_held, base_score) -> float:
    kind = getattr(item, "kind", "")
    key = _shop_item_key(item)
    if kind == "joker":
        has_room = len(game.jokers) < game.joker_slots or getattr(item, "edition", "None") == "Negative"
        if not has_room:
            return -math.inf
        return _eval_joker_utility(
            game, key, getattr(item, "edition", "None"), _item_price(item, game),
            rep_pair, rep_held,
        )
    if kind == "planet":
        if key not in ("c_mercury", "pl_mercury") or len(game.consumable_hand) >= game.consumable_slots:
            return -math.inf
        return _pair_tarot_shop_value(game, key, rep_pair, rep_held, base_score)
    if kind == "tarot":
        if key not in _PAIR_TAROT_BUYS or len(game.consumable_hand) >= game.consumable_slots:
            return -math.inf
        return _pair_tarot_shop_value(game, key, rep_pair, rep_held, base_score)
    if kind == "voucher":
        priority = VOUCHER_PRIORITY.get(key, 0)
        if priority < 2 or key in getattr(game, "vouchers", ()) or game.ante <= 2 or not game.jokers:
            return -math.inf
        if game.dollars - _item_price(item, game) < 5:
            return -math.inf
        return 0.35 + 0.14 * priority
    if kind in ("booster", "pack"):
        if key.startswith(("p_celestial", "p_arcana", "p_spectral")) and len(game.consumable_hand) >= game.consumable_slots:
            return -math.inf
        if key.startswith("p_buffoon") and len(game.jokers) >= game.joker_slots:
            return -math.inf
        if key.startswith(("p_celestial", "p_buffoon")) and game.dollars < 8 and game.ante != 1:
            return -math.inf
        if key.startswith("p_standard") and game.dollars < 8 and game.ante > 2:
            return -math.inf
        if not key.startswith(("p_celestial", "p_buffoon", "p_standard")):
            return -math.inf
        return _pair_booster_shop_value(game, item)
    return -math.inf


def _rank_shop_items(game: BalatroGame, rep_pair=None, rep_held=None, base_score=None):
    """Return actionable PairBot shop buys and the best full-slot upgrade."""
    if rep_pair is None or rep_held is None:
        rep_pair, rep_held = _get_representative_cards(game)
    if base_score is None:
        base_score = _pair_eval_hand_score(game, "Pair", rep_pair, rep_pair, held_cards=rep_held)

    buys = []
    swaps = []
    full = len(game.jokers) >= game.joker_slots
    owned_values = None
    if full and game.jokers:
        owned_values = [
            _eval_owned_joker_value(game, i, rep_pair, rep_held, base_score)
            for i in range(len(game.jokers))
        ]

    for idx, item in enumerate(getattr(game, "current_shop", ()) or ()):
        if getattr(item, "sold", False):
            continue
        price = _item_price(item, game)
        kind = getattr(item, "kind", "")
        if kind == "joker" and _shop_item_key(item) in {joker.key for joker in game.jokers}:
            continue
        if kind == "joker" and full and getattr(item, "edition", "None") != "Negative":
            for sell_idx, owned in enumerate(game.jokers):
                candidate_key = _shop_item_key(item)
                if not _pair_safe_to_sell(game, sell_idx, candidate_key):
                    continue
                sell_value = _joker_sell_value(owned)
                if not _pair_can_afford_after_sale(game, sell_idx, price):
                    continue
                delta = _eval_candidate_swap_utility(
                    game, candidate_key, getattr(item, "edition", "None"),
                    sell_idx, price, rep_pair, rep_held, base_score, owned_values[sell_idx],
                )
                delta -= _pair_price_penalty(game, max(0, price - sell_value))
                if delta > _PAIR_SWAP_MARGIN:
                    swaps.append((delta, sell_idx, idx, candidate_key))
            continue

        if not _pair_can_afford(game, price):
            continue
        value = _pair_shop_item_value(game, item, rep_pair, rep_held, base_score)
        if not math.isfinite(value):
            continue
        if kind == "joker" and value < _PAIR_JOKER_BUY_THRESHOLD:
            continue
        # Joker utility already includes the supplied price; other shop item
        # values are gross and receive their liquidity cost here.
        if kind != "joker":
            value -= _pair_price_penalty(game, price)
        minimum = 0.25 if kind in ("planet", "tarot") else 0.30 if kind in ("booster", "pack") else _PAIR_JOKER_BUY_THRESHOLD
        if value >= minimum:
            buys.append((value, idx))

    buys.sort(key=lambda pair: (
        -pair[0], _shop_kind_order(game.current_shop[pair[1]]),
        _item_price(game.current_shop[pair[1]], game), _shop_item_key(game.current_shop[pair[1]]), pair[1],
    ))
    swaps.sort(key=lambda entry: (-entry[0], entry[3], entry[1], entry[2]))
    best_swap = (swaps[0][0], swaps[0][1], swaps[0][2]) if swaps else None
    return buys, best_swap


# ────────────────────────────────────────────────────────────────────────────
# Pair Ecosystem Trigger & Compatibility Definitions
# ────────────────────────────────────────────────────────────────────────────

INCOMPATIBLE_HAND_TRIGGERS = {
    "j_runner": -999.0,
    "j_shortcut": -999.0,
    "j_order": -999.0,
    "j_four_fingers": -999.0,
    "j_tribe": -999.0,
    "j_flower_pot": -999.0,
    "j_seance": -999.0,
    "j_superposition": -999.0,
    "j_troubadour": -10.0,
    "j_family": -10.0,
    "j_ancient": -5.0,
    # PairBot may play exactly 2 cards, so jokers keyed to other hands must
    # demonstrate an explicit high-value exception before purchase.
    "j_trio": -8.0,
    "j_wily": -8.0,
    "j_clever": -8.0,
    "j_devious": -8.0,
    "j_crafty": -8.0,
    "j_zany": -8.0,
    "j_mad": -8.0,
    "j_crazy": -8.0,
    "j_droll": -8.0,
}

SCALING_JOKERS_RATES = {
    "j_supernova": 4.5,
    "j_ride_the_bus": 4.5,
    "j_green_joker": 4.0,
    "j_constellation": 5.0,
    "j_lucky_cat": 4.5,
    "j_hologram": 5.0,
    "j_square": 3.0,
    "j_square_joker": 3.0,
    "j_wee": 4.5,
    "j_red_card": 3.5,
}

FIBONACCI_RANKS = {14, 2, 3, 5, 8}
HACK_RANKS = {2, 3, 4, 5}
WALKIE_RANKS = {10, 4}
FACE_RANKS = {11, 12, 13}


def _determine_anchor_rank(game: BalatroGame) -> int:
    """Determine the optimal Pair rank to build toward based on jokers and deck."""
    j_keys = {j.key for j in game.jokers}
    all_cards = list(game.deck) + list(game.hand) + list(game.spent)
    rank_counts = Counter(c.rank for c in all_cards if hasattr(c, "rank") and c.rank is not None)

    # 1. Joker-directed rank affinities
    if "j_wee" in j_keys:
        return 2
    if "j_hack" in j_keys:
        candidates = [r for r in (2, 3, 4, 5) if rank_counts.get(r, 0) > 0]
        if candidates:
            return max(candidates, key=lambda r: (rank_counts.get(r, 0), r))
        return 2
    if "j_walkie_talkie" in j_keys:
        return 10 if rank_counts.get(10, 0) >= rank_counts.get(4, 0) else 4
    if "j_fibonacci" in j_keys:
        fib_candidates = sorted(r for r in FIBONACCI_RANKS if rank_counts.get(r, 0) > 0)
        if fib_candidates:
            return max(fib_candidates, key=lambda r: (rank_counts.get(r, 0), r))
        return 8
    if "j_scholar" in j_keys:
        return 14

    # 2. If Ride the Bus is active, strictly avoid face cards (J, Q, K)
    if "j_ride_the_bus" in j_keys:
        non_face_counts = {r: c for r, c in rank_counts.items() if r not in FACE_RANKS}
        if non_face_counts:
            return max(non_face_counts, key=lambda r: (non_face_counts[r], r))

    # 3. Default: Modal rank in deck, breaking ties by enhancement value
    if rank_counts:
        best_rank = 14
        best_score = (-1, -1, -1)
        for r, cnt in rank_counts.items():
            enhanced_cnt = sum(
                1 for c in all_cards
                if getattr(c, "rank", None) == r
                and (getattr(c, "enhancement", "None") != "None" or getattr(c, "seal", "None") != "None")
            )
            score = (cnt, enhanced_cnt, r)
            if score > best_score:
                best_score = score
                best_rank = r
        return best_rank

    return 10


def _is_held_in_hand_value_card(card: Card, j_keys: set[str]) -> bool:
    """Return True if this card generates value by staying held in hand at round end."""
    if getattr(card, "seal", None) == "Blue":
        return True
    if getattr(card, "enhancement", None) in ("Gold", "Steel"):
        return True
    if card.rank == 13 and "j_baron" in j_keys:
        return True
    if card.rank == 12 and "j_shoot_the_moon" in j_keys:
        return True
    return False


def _get_representative_cards(game: BalatroGame) -> tuple[list[Card], list[Card]]:
    """Return a representative Pair and representative held cards from game deck."""
    all_cards = list(game.deck) + list(game.hand) + list(game.spent)
    if not all_cards:
        all_cards = [Card(10, "Spades"), Card(10, "Hearts")]

    anchor_rank = _determine_anchor_rank(game)
    rank_cards = sorted(
        (c for c in all_cards if getattr(c, "rank", None) == anchor_rank),
        key=lambda c: (-_card_quality(c), str(c.suit), str(c.enhancement), str(c.edition), str(c.seal)),
    )
    if len(rank_cards) >= 2:
        rep_pair = [rank_cards[0].copy(), rank_cards[1].copy()]
        used_ids = {id(rank_cards[0]), id(rank_cards[1])}
    else:
        counts = Counter(getattr(c, "rank", None) for c in all_cards if getattr(c, "rank", None) is not None)
        modal_rank = max(counts, key=lambda rank: (counts[rank], rank)) if counts else 10
        modal_cards = sorted(
            (c for c in all_cards if getattr(c, "rank", None) == modal_rank),
            key=lambda c: (-_card_quality(c), str(c.suit), str(c.enhancement), str(c.edition), str(c.seal)),
        )
        if len(modal_cards) >= 2:
            rep_pair = [modal_cards[0].copy(), modal_cards[1].copy()]
            used_ids = {id(modal_cards[0]), id(modal_cards[1])}
        else:
            rep_pair = [Card(10, "Spades"), Card(10, "Hearts")]
            used_ids = set()

    remaining = [c for c in all_cards if id(c) not in used_ids]
    if not remaining:
        remaining = [Card(3, "Clubs"), Card(5, "Diamonds"), Card(7, "Hearts"), Card(9, "Spades")]

    j_keys = {j.key for j in game.jokers}
    remaining.sort(key=lambda c: _pair_card_stable_key(c, j_keys))
    # In Balatro with 8-card hands, playing a 2-card Pair leaves 5-6 cards held in hand.
    rep_held = [card.copy() for card in remaining[:5]]
    return rep_pair, rep_held


def _pair_eval_hand_score(
    game: BalatroGame,
    hand_type: str,
    scoring_cards: list[Card],
    all_cards: list[Card],
    held_cards: Optional[list[Card]] = None,
    extra_joker: Optional[tuple[str, str]] = None,
    exclude_joker: Optional[int] = None,
    level_override: Optional[dict] = None,
) -> int:
    """Evaluate an isolated Pair counterfactual with legal copy-joker ordering.

    Copying/reordering occurs only on a shallow game shell with a private joker
    list; the live game, its joker states, and its RNG are never touched.
    """
    hypothetical = shallowcopy(game)
    hypothetical.jokers = [
        joker for index, joker in enumerate(getattr(game, "jokers", ()))
        if index != exclude_joker
    ]
    if extra_joker is not None:
        key, edition = extra_joker
        hypothetical.jokers.append(JokerInstance(
            key, edition or "None", game=hypothetical,
            state=_joker_default_state(key),
        ))
    copy_keys = {"j_blueprint", "j_brainstorm"}
    copy_jokers = [j for j in hypothetical.jokers if j.key in copy_keys]
    if copy_jokers:
        # Keep ordinary joker order stable and enumerate legal slots for the
        # copies. With the normal five-slot cap this is at most 60 arrangements
        # for two copies; larger negative-edition portfolios use V11's bounded
        # target heuristic instead of factorial search.
        ordinary = [j for j in hypothetical.jokers if j.key not in copy_keys | {"j_ceremonial"}]
        ceremonial = [j for j in hypothetical.jokers if j.key == "j_ceremonial"]
        if len(copy_jokers) <= 2 and len(hypothetical.jokers) <= 6:
            best_score = None
            for copy_order in itertools.permutations(copy_jokers):
                orders = [tuple(ordinary)]
                for copied in copy_order:
                    orders = [
                        order[:position] + (copied,) + order[position:]
                        for order in orders
                        for position in range(len(order) + 1)
                    ]
                for order in orders:
                    hypothetical.jokers = list(order) + ceremonial
                    score = eval_hand_score(
                        hypothetical, hand_type, scoring_cards, all_cards,
                        held_cards=held_cards, level_override=level_override,
                    )
                    best_score = score if best_score is None else max(best_score, score)
            if best_score is not None:
                return best_score
        _optimize_joker_order_v11(hypothetical)
    return eval_hand_score(
        hypothetical, hand_type, scoring_cards, all_cards,
        held_cards=held_cards, level_override=level_override,
    )



def _eval_joker_utility(
    game: BalatroGame,
    key: str,
    edition: str = "None",
    price: int = 0,
    rep_pair: Optional[list[Card]] = None,
    rep_held: Optional[list[Card]] = None,
    exclude_joker: Optional[int] = None,
) -> float:
    """Estimate candidate value for the Pair build from current score and runway."""
    if key in INCOMPATIBLE_HAND_TRIGGERS:
        return INCOMPATIBLE_HAND_TRIGGERS[key]
    if key == "j_madness":
        # It destroys another owned joker on blind selection; without an
        # explicit safe-target model, price that portfolio risk conservatively.
        return -1.25 - 2.0 * min(2, len(getattr(game, "jokers", ())))

    if rep_pair is None or rep_held is None:
        rep_pair, rep_held = _get_representative_cards(game)

    scenario = shallowcopy(game)
    scenario.jokers = [
        joker for index, joker in enumerate(getattr(game, "jokers", ()))
        if index != exclude_joker
    ]
    s_base, s_cand = _pair_score_with_candidate(
        scenario, key, edition, rep_pair, rep_held,
    )
    candidate_state = _joker_default_state(key)
    lift = s_cand / max(1.0, float(s_base))
    exposure = _pair_scoring_exposure(game, key, candidate_state)
    utility = (lift - 1.0) * 3.5 * exposure * _pair_scoring_horizon(game)
    utility += _pair_joker_lifecycle_value(scenario, key, candidate_state, rep_pair, s_base)
    # Copy jokers are valued by the isolated portfolio scorer above; do not add
    # a separate synergy premium that could count the copied effect twice.
    if edition == "Polychrome":
        utility += 0.45
    elif edition == "Holographic":
        utility += 0.20
    elif edition == "Foil":
        utility += 0.10
    elif edition == "Negative":
        utility += 0.35
    utility -= _pair_price_penalty(game, price)

    if game.ante == 1:
        has_scoring = any(
            _pair_eval_hand_score(
                scenario, "Pair", rep_pair, rep_pair, held_cards=rep_held,
                exclude_joker=i,
            ) < s_base * 0.85
            for i in range(len(scenario.jokers))
        )
        if not has_scoring and lift < 1.25:
            return -5.0

    return utility


def _eval_owned_joker_value(
    game: BalatroGame,
    j_idx: int,
    rep_pair: list[Card],
    rep_held: list[Card],
    s_base: int,
) -> float:
    """Marginal current and future value of an owned joker; lower means sell first."""
    joker = game.jokers[j_idx]
    if joker.key in INCOMPATIBLE_HAND_TRIGGERS:
        return INCOMPATIBLE_HAND_TRIGGERS[joker.key]

    score_without = _pair_eval_hand_score(
        game, "Pair", rep_pair, rep_pair, held_cards=rep_held,
        exclude_joker=j_idx,
    )
    current_lift = float(s_base) / max(1.0, float(score_without)) - 1.0
    exposure = _pair_scoring_exposure(game, joker.key, joker.state)
    if joker.key in {"j_blueprint", "j_brainstorm"}:
        candidate_scores = [
            _pair_eval_hand_score(
                game, "Pair", rep_pair, rep_pair, held_cards=rep_held,
                exclude_joker=j_idx,
            )
            for _key in ("j_blueprint", "j_brainstorm")
        ]
        score_without = max(candidate_scores)
        current_lift = float(s_base) / max(1.0, float(score_without)) - 1.0
    current_value = current_lift * 3.5 * exposure * _pair_scoring_horizon(game)
    return current_value + _pair_joker_lifecycle_value(
        game, joker.key, joker.state, rep_pair, s_base,
    )


def _eval_candidate_swap_utility(
    game: BalatroGame,
    key: str,
    edition: str,
    sell_idx: int,
    price: int,
    rep_pair: list[Card],
    rep_held: list[Card],
    base_score: int,
    owned_value: float,
) -> float:
    """Return candidate portfolio lift over the joker being sold, before cash cost."""
    candidate_value = _eval_joker_utility(
        game, key, edition, price=0, rep_pair=rep_pair, rep_held=rep_held,
        exclude_joker=sell_idx,
    )
    # The shared utility path runs the copy-order optimizer against an isolated
    # post-sale portfolio, so Blueprint/Brainstorm effects are counted once.
    return candidate_value - owned_value



def _pair_score_with_candidate(
    game: BalatroGame,
    key: str,
    edition: str,
    rep_pair: list[Card],
    rep_held: list[Card],
    exclude_joker: Optional[int] = None,
) -> tuple[int, int]:
    """Return baseline and candidate scores using the same isolated oracle."""
    baseline = _pair_eval_hand_score(
        game, "Pair", rep_pair, rep_pair, held_cards=rep_held,
        exclude_joker=exclude_joker,
    )
    candidate = _pair_eval_hand_score(
        game, "Pair", rep_pair, rep_pair, held_cards=rep_held,
        extra_joker=(key, edition), exclude_joker=exclude_joker,
    )
    return baseline, candidate


def _pair_can_afford(game: BalatroGame, price: int) -> bool:
    debt = any(getattr(joker, "has_flag", lambda _flag: False)("debt") for joker in game.jokers)
    return int(game.dollars) - max(0, int(price)) >= (-20 if debt else 0)


def _pair_can_afford_after_sale(game: BalatroGame, sell_idx: int, price: int) -> bool:
    """Use the real sell proceeds and only retain Credit Card debt after the sale."""
    if sell_idx < 0 or sell_idx >= len(game.jokers):
        return False
    remaining = [joker for index, joker in enumerate(game.jokers) if index != sell_idx]
    credit = any(getattr(joker, "has_flag", lambda _flag: False)("debt") for joker in remaining)
    proceeds = _joker_sell_value(game.jokers[sell_idx])
    return int(game.dollars) + proceeds - max(0, int(price)) >= (-20 if credit else 0)


def _pair_safe_to_sell(game: BalatroGame, sell_idx: int, candidate_key: str) -> bool:
    """Guard portfolio anchors and destructive jokers from speculative swaps."""
    owned = game.jokers[sell_idx]
    key = getattr(owned, "key", "")
    if key in {"j_blueprint", "j_brainstorm", "j_cavendish", "j_hanging_chad", "j_mime", "j_sock_and_buskin", "j_dusk"}:
        return False
    if key in _PAIR_GROWTH_KEYS and game.ante < 7:
        return False
    if key in {"j_egg", "j_golden", "j_satellite", "j_business", "j_to_the_moon"} and game.ante < 6:
        return False
    if key in {"j_madness", "j_obelisk", "j_idol", "j_the_idol"}:
        return False
    # Do not remove the only currently-owned member of a core scoring category,
    # unless the incoming joker replaces that category.
    from .agent_v10 import PORTFOLIO_CHIPS, PORTFOLIO_FLAT, PORTFOLIO_XMULT
    replacements = (
        (PORTFOLIO_CHIPS, candidate_key in PORTFOLIO_CHIPS),
        (PORTFOLIO_FLAT, candidate_key in PORTFOLIO_FLAT),
        (PORTFOLIO_XMULT, candidate_key in PORTFOLIO_XMULT),
    )
    for category, candidate_replaces_category in replacements:
        if (
            key in category
            and not candidate_replaces_category
            and sum(j.key in category for j in game.jokers) <= 1
        ):
            return False
    return True



def _pair_discard_farming_action(game: BalatroGame, anchor_rank: int, j_keys: set[str]) -> Optional[dict]:
    """Take advantage of spare discards to generate economy, tarots, or permanent scaling."""
    if game.discards_left <= 0 or game.hands_left < 2:
        return None

    hand = game.hand
    # 1. Trading Card: Destroy 1 non-anchor junk card on first discard for $3
    if ("j_trading" in j_keys or "j_trading_card" in j_keys) and not _trading_used(game):
        junk_indices = [
            i for i, c in enumerate(hand)
            if c.rank != anchor_rank and not _is_held_in_hand_value_card(c, j_keys)
        ]
        if junk_indices:
            worst = min(junk_indices, key=lambda i: _card_quality(hand[i]))
            return {"type": "discard", "cards": [worst]}

    # 2. Purple Seal: Discard purple seal to generate a free Tarot card
    if len(game.consumable_hand) < game.consumable_slots:
        purple_indices = [i for i, c in enumerate(hand) if getattr(c, "seal", None) == "Purple" and not c.debuffed]
        if purple_indices:
            return {"type": "discard", "cards": [purple_indices[0]]}

    # 3. Mail-In Rebate: Discard cards matching rebate rank for $5 each
    if "j_mail" in j_keys or "j_mail_in_rebate" in j_keys:
        target_rank = _mail_target_rank(game)
        if target_rank is not None:
            rebate_indices = [
                i for i, c in enumerate(hand)
                if c.rank == target_rank and not c.debuffed and c.rank != anchor_rank
            ]
            if rebate_indices:
                return {"type": "discard", "cards": rebate_indices[:5]}

    # 4. Faceless Joker: Discard 3 non-scoring face cards for $5
    if "j_faceless" in j_keys:
        face_indices = [
            i for i, c in enumerate(hand)
            if c.is_face_card and not c.debuffed and c.rank != anchor_rank
        ]
        if len(face_indices) >= 3:
            return {"type": "discard", "cards": face_indices[:3]}

    # 5. Castle: Discard cards of the castle suit to gain permanent chips
    if "j_castle" in j_keys:
        target_suit = _castle_target_suit(game)
        if target_suit is not None:
            castle_indices = [
                i for i, c in enumerate(hand)
                if c.suit == target_suit and c.rank != anchor_rank and not _is_held_in_hand_value_card(c, j_keys)
            ]
            if castle_indices:
                return {"type": "discard", "cards": castle_indices[:5]}

    return None


def _castle_target_suit(game: BalatroGame) -> Optional[str]:
    for j in game.jokers:
        if j.key == "j_castle":
            return j.state.get("target_suit")
    return None


# ════════════════════════════════════════════════════════════════════════════
# PairBot Agent Class
# ════════════════════════════════════════════════════════════════════════════

class PairBot(SearchShopV11):
    """Balatro University-inspired Pair-First reference agent.
    Always builds towards Pairs as its macro core while adapting to joker synergies."""

    policy_name = "pair_bot"

    def __init__(self, params=None, **kwargs):
        super().__init__(params=params, **kwargs)
        self._pair_stats = {
            "decisions": 0,
            "pairs_played": 0,
            "mercury_used": 0,
            "scaling_plays": 0,
            "discards_saved": 0,
        }

    # ────────────────────────────────────────────────────────────────────────
    # 1. In-Blind Decision Engine
    # ────────────────────────────────────────────────────────────────────────

    def _pair_decide_hand(self, game: BalatroGame) -> dict:
        self._pair_stats["decisions"] += 1
        j_keys = {j.key for j in game.jokers}
        target = game.current_blind.chips_target - game.chips_scored

        # ── Step 1: Consumables (Mercury & Tarots) ──────────────────────────
        if game.consumable_hand:
            for ci, key in enumerate(game.consumable_hand):
                if key in ("c_mercury", "pl_mercury"):
                    self._pair_stats["mercury_used"] += 1
                    return {"type": "use_consumable", "consumable_idx": ci, "target_cards": []}

            anchor_rank = _determine_anchor_rank(game)
            tarot_act = self._pair_tarot_action(game, anchor_rank)
            if tarot_act is not None:
                return tarot_act

            cons_act = _v10_decide_consumable(game)
            if cons_act is not None:
                return cons_act

        boss = game.current_blind.boss_key if game._boss_effects_on() else ""
        if target <= 0:
            safe = _v10_decide_hand(game)
            if safe.get("type") == "play":
                selected = safe.get("cards", ())
                if selected and (boss != "bl_psychic" or len(selected) == 5):
                    try:
                        _, _, _, _, legal = _pair_play_details(game, selected, boss)
                    except (IndexError, ValueError):
                        legal = False
                    if legal:
                        return safe
            legal_fallback = _best_non_pair_play(game, allow_pair=True)
            if legal_fallback is not None:
                return {"type": "play", "cards": legal_fallback["indices"]}
            fallback = list(range(5 if boss == "bl_psychic" else min(5, len(game.hand))))
            fallback = [i for i in fallback if i < len(game.hand)]
            if fallback and (boss != "bl_psychic" or len(fallback) == 5):
                return {"type": "play", "cards": fallback}
            return {"type": "play", "cards": list(range(len(game.hand)))}

        # Boss restrictions are applied to each candidate. An unavailable Pair
        # is a tactical exception, not a reason to abandon the Pair policy.

        # ── Step 1c: Ante 1 Opening Safety ──────────────────────────────────
        # In Ante 1 without jokers or Pair levels, 4 pairs mathematically cannot
        # reach 300 chips (max 256). Follow standard opening until reaching shop.
        if game.ante == 1 and not game.jokers and game.planet_levels.get("Pair", 1) == 1:
            opening = _v10_decide_hand(game)
            if opening.get("type") == "play":
                selected = opening.get("cards", ())
                psychic_size_ok = boss != "bl_psychic" or len(selected) == 5
                try:
                    _, _, _, _, legal = _pair_play_details(game, selected, boss)
                except (IndexError, ValueError):
                    legal = False
                if selected and psychic_size_ok and legal:
                    return opening
            # V10 returns an unfiltered fallback when a boss rejects every
            # scored candidate; continue into PairBot's legal tactical path.

        anchor_rank = _determine_anchor_rank(game)
        has_bus = "j_ride_the_bus" in j_keys

        # ── Step 2: Group Hand and Find Candidate Pairs ─────────────────────
        rank_groups = defaultdict(list)
        for i, card in enumerate(game.hand):
            if hasattr(card, "rank") and card.rank is not None:
                rank_groups[card.rank].append(i)

        # Retain every legal two-card combination for a rank. Card editions,
        # debuffs, and held-card interactions can make two copies non-equivalent.
        pair_legal = []
        for rank, indices in rank_groups.items():
            if len(indices) < 2:
                continue
            for pair_indices in itertools.combinations(indices, 2):
                pair_cards = [game.hand[i] for i in pair_indices]
                hand_type, _ = evaluate_hand(pair_cards)
                if hand_type == "Pair":
                    try:
                        _, _, _, _, legal = _pair_play_details(game, pair_indices, boss)
                    except Exception:
                        legal = False
                    if legal:
                        pair_legal.append((rank, tuple(pair_indices)))

        if not pair_legal:
            # _best_non_pair_play applies the Eye/Mouth hand-type filter, so it
            # may still find a legal, materially better type under those bosses.
            tactical = _best_non_pair_play(game)
            if tactical is not None and (
                game.discards_left <= 0
                or tactical["score"] >= target / max(1, game.hands_left)
                or tactical["score"] >= target
            ):
                return {"type": "play", "cards": tactical["indices"]}
            if game.discards_left > 0:
                keep_set = {
                    i for i, card in enumerate(game.hand)
                    if _is_held_in_hand_value_card(card, j_keys) or card.rank == anchor_rank
                }
                discard_cands = [i for i in range(len(game.hand)) if i not in keep_set]
                plan = _pair_plan_discard(
                    game, discard_cands,
                    baseline_score=tactical["score"] if tactical is not None else 0.0,
                    protected_indices=keep_set,
                )
                if plan is not None:
                    return {"type": "discard", "cards": plan["indices"]}
                discard_cands.sort(key=lambda i: (_card_quality(game.hand[i]), i))
                if discard_cands:
                    return {"type": "discard", "cards": discard_cands[:5]}
            if tactical is not None:
                return {"type": "play", "cards": tactical["indices"]}
            fallback_act = _v10_decide_hand(game)
            if fallback_act.get("type") == "play":
                selected = fallback_act.get("cards", ())
                try:
                    _, _, _, _, legal = _pair_play_details(game, selected, boss)
                except (IndexError, ValueError):
                    legal = False
                psychic_size_ok = boss != "bl_psychic" or len(selected) == 5
                if selected and psychic_size_ok and legal:
                    return fallback_act
            # If every legal play type is exhausted under Eye/Mouth, dig rather
            # than knowingly submit an invalid play and lose a hand.
            sorted_by_q = sorted(range(len(game.hand)), key=lambda i: (_card_quality(game.hand[i]), i))
            if game.discards_left > 0:
                return {"type": "discard", "cards": sorted_by_q[:min(5, len(game.hand))]}
            if boss == "bl_psychic" and len(game.hand) < 5:
                # The engine rejects and consumes a short Psychic play; there is
                # no legal play while fewer than five cards remain.
                return {"type": "play", "cards": sorted_by_q}
            return {"type": "play", "cards": sorted_by_q[:min(5, len(game.hand))]}

        # ── Step 4: Evaluate Pair plays and the boss-mandated Psychic size ──
        evaluated_pairs = []
        is_psychic = boss == "bl_psychic"
        for r, pair_indices in pair_legal:
            pair_cards = [game.hand[i] for i in pair_indices]
            remaining_indices = [i for i in range(len(game.hand)) if i not in pair_indices]
            held = [game.hand[i] for i in remaining_indices]
            candidate_plays = [list(pair_indices)]

            if is_psychic:
                # Psychic requires five selected cards. With an eight-card
                # hand there are at most 20 fillers per pair, a small bounded
                # search; fillers may be held-value cards because the boss
                # makes selecting exactly five mandatory.
                candidate_plays = [
                    list(pair_indices) + list(extras)
                    for extras in itertools.combinations(remaining_indices, 3)
                ]
            else:
                safe_junk = [
                    i for i in remaining_indices
                    if not _is_held_in_hand_value_card(game.hand[i], j_keys)
                    and (not has_bus or not game.hand[i].is_face_card)
                ]
                safe_junk.sort(key=lambda i: (
                    getattr(game.hand[i], "rank", 0),
                    _card_quality(game.hand[i]),
                    i,
                ))
                # Try a bounded set of low-value, distinct-rank attachments.
                extras = []
                seen_ranks = {r}
                for ci in safe_junk:
                    card_rank = getattr(game.hand[ci], "rank", 0)
                    if card_rank not in seen_ranks:
                        seen_ranks.add(card_rank)
                        extras.append(ci)
                    if len(extras) >= 3:
                        break
                candidate_plays.extend(
                    list(pair_indices) + list(extra_combo)
                    for count in range(1, len(extras) + 1)
                    for extra_combo in itertools.combinations(extras, count)
                )

            best_score = -1.0
            best_utility = -1.0
            best_play_indices = []
            for test_idxs in candidate_plays:
                test_cards = [game.hand[i] for i in test_idxs]
                try:
                    played_indices, test_cards, test_type, test_scoring, legal = _pair_play_details(
                        game, test_idxs, boss,
                    )
                except Exception:
                    continue
                if not is_psychic and boss != "bl_cerulean" and test_type != "Pair":
                    continue
                if not legal:
                    continue
                played_set = set(played_indices)
                test_held = [
                    game.hand[i] for i in range(len(game.hand)) if i not in played_set
                ]
                try:
                    score = eval_hand_score(
                        game, test_type, test_scoring, test_cards, held_cards=test_held
                    )
                except Exception:
                    continue
                # Future scaling is a tie-break/selection bonus, never counted
                # as chips already scored toward the blind.
                utility = score
                if j_keys & _PAIR_SQUARE_KEYS and len(test_idxs) == 4 and "j_half" not in j_keys:
                    utility += 25.0
                tie_key = (utility, score, -len(test_idxs), tuple(-i for i in test_idxs))
                best_key = (
                    best_utility,
                    best_score,
                    -len(best_play_indices) if best_play_indices else -999,
                    tuple(-i for i in best_play_indices),
                )
                if tie_key > best_key:
                    best_score = score
                    best_utility = utility
                    best_play_indices = list(test_idxs)

            if best_score >= 0:
                evaluated_pairs.append({
                    "rank": r,
                    "indices": best_play_indices,
                    "score": best_score,
                    "utility": best_utility,
                    "is_face": r in FACE_RANKS,
                })

        if not evaluated_pairs:
            tactical = _best_non_pair_play(game)
            if tactical is not None and (
                game.discards_left <= 0
                or tactical["score"] >= target / max(1, game.hands_left)
                or tactical["score"] >= target
            ):
                return {"type": "play", "cards": tactical["indices"]}
            if game.discards_left > 0:
                keep_set = {
                    index for index, card in enumerate(game.hand)
                    if _is_held_in_hand_value_card(card, j_keys) or card.rank == anchor_rank
                }
                discard_cands = [index for index in range(len(game.hand)) if index not in keep_set]
                plan = _pair_plan_discard(
                    game, discard_cands,
                    baseline_score=tactical["score"] if tactical is not None else 0.0,
                    protected_indices=keep_set,
                )
                if plan is not None:
                    return {"type": "discard", "cards": plan["indices"]}
                discard_cands.sort(key=lambda index: (_card_quality(game.hand[index]), index))
                if discard_cands:
                    return {"type": "discard", "cards": discard_cands[:5]}
            if tactical is not None:
                return {"type": "play", "cards": tactical["indices"]}
            fallback_act = _v10_decide_hand(game)
            if fallback_act.get("type") == "play":
                selected = fallback_act.get("cards", ())
                psychic_size_ok = boss != "bl_psychic" or len(selected) == 5
                try:
                    _, _, _, _, legal = _pair_play_details(game, selected, boss)
                except (IndexError, ValueError):
                    legal = False
                if selected and psychic_size_ok and legal:
                    return fallback_act
            if boss == "bl_psychic" and len(game.hand) < 5 and game.discards_left <= 0:
                # No legal action exists; submit every remaining card and let
                # the engine's rejected-short-play transition consume the hand.
                return {"type": "play", "cards": list(range(len(game.hand)))}
            return fallback_act if fallback_act.get("type") == "discard" else {"type": "play", "cards": [0]}

        evaluated_pairs.sort(key=lambda p: (
            -p.get("utility", p["score"]), -p["score"], p["rank"], tuple(p["indices"])
        ))
        best_pair = evaluated_pairs[0]

        # ── Step 5: Multi-Hand Scaling Farming ────────────────────────────────

        # Farm only when the strongest Pair leaves a safe route to clear and the
        # weaker Pair still contributes useful chips toward this blind.
        has_scalers = bool(_PAIR_GROWTH_KEYS & j_keys)
        if has_scalers and game.hands_left >= 3 and len(evaluated_pairs) >= 2:
            lower_pair = evaluated_pairs[-1]
            safe_after_farm = best_pair["score"] * max(1, game.hands_left - 1) >= target - lower_pair["score"]
            meaningful_progress = lower_pair["score"] >= max(1.0, target / max(1, game.hands_left) * 0.45)
            if safe_after_farm and meaningful_progress and (not has_bus or not lower_pair["is_face"]):
                self._pair_stats["scaling_plays"] += 1
                return {"type": "play", "cards": lower_pair["indices"]}

        # Bounded tactical pivot: retain Pairs unless all available Pair plays
        # fall short over the remaining hands and a legal alternate materially
        # improves this turn's chance to avoid a blind loss.
        pair_can_clear_run = best_pair["score"] * max(1, game.hands_left) >= target
        best_alternate = None
        if not pair_can_clear_run and (game.discards_left <= 0 or best_pair["score"] < target):
            best_alternate = _best_non_pair_play(game)
        if (
            best_alternate is not None
            and not pair_can_clear_run
            and (game.discards_left <= 0 or best_alternate["score"] >= target)
            and best_alternate["score"] * max(1, game.hands_left) >= target
            and best_alternate["score"] >= best_pair["score"] * 1.35
        ):
            return {"type": "play", "cards": best_alternate["indices"]}

        # ── Step 6: Play vs Discard Decision ─────────────────────────────────
        can_clear_now = (best_pair["score"] >= target)
        can_clear_run = pair_can_clear_run

        if can_clear_now:
            if game.discards_left > 0 and game.hands_left >= 2:
                farm_act = _pair_discard_farming_action(game, anchor_rank, j_keys)
                if farm_act is not None:
                    self._pair_stats["discards_saved"] += 1
                    return farm_act
            self._pair_stats["pairs_played"] += 1
            return {"type": "play", "cards": best_pair["indices"]}

        if can_clear_run:
            self._pair_stats["pairs_played"] += 1
            return {"type": "play", "cards": best_pair["indices"]}

        # DEFICIT CASE: Current pair cannot clear across remaining hands!
        if game.discards_left > 0:
            # Discard non-pair junk to dig for better hands, steels, or seals
            keep_set = set(best_pair["indices"])
            for i, c in enumerate(game.hand):
                if _is_held_in_hand_value_card(c, j_keys) or c.rank == anchor_rank:
                    keep_set.add(i)

            discard_cands = [i for i in range(len(game.hand)) if i not in keep_set]
            plan = _pair_plan_discard(
                game, discard_cands, baseline_score=best_pair["score"],
                protected_indices=keep_set,
            )
            if plan is not None:
                return {"type": "discard", "cards": plan["indices"]}
            discard_cands.sort(key=lambda i: (_card_quality(game.hand[i]), i))
            to_discard = discard_cands[:5]
            if to_discard:
                return {"type": "discard", "cards": to_discard}

        # Out of discards: MUST play best available scoring hand
        self._pair_stats["pairs_played"] += 1
        return {"type": "play", "cards": best_pair["indices"]}

    # ────────────────────────────────────────────────────────────────────────
    # 2. Targeted Tarot Actions for Pairs
    # ────────────────────────────────────────────────────────────────────────

    def _pair_tarot_action(self, game: BalatroGame, anchor_rank: int) -> Optional[dict]:
        """Tarot targeting shaped for Pairs.
        Enhancements avoid face cards under Ride the Bus; Death duplicates Blue Seal -> Steel."""
        hand = game.hand
        j_keys = {j.key for j in game.jokers}
        has_bus = "j_ride_the_bus" in j_keys

        for ci, key in enumerate(game.consumable_hand):
            # Death: Duplicate highest-value asset onto lowest-quality junk
            if key == "c_death" and len(hand) >= 2:
                src = None
                blue_indices = [i for i, c in enumerate(hand) if getattr(c, "seal", None) == "Blue"]
                if blue_indices:
                    src = blue_indices[0]
                elif any(getattr(c, "enhancement", None) == "Steel" for c in hand):
                    steel_indices = [i for i, c in enumerate(hand) if getattr(c, "enhancement", None) == "Steel"]
                    src = steel_indices[0]
                elif any(getattr(c, "seal", None) in ("Purple", "Red") for c in hand):
                    seal_indices = [i for i, c in enumerate(hand) if getattr(c, "seal", None) in ("Purple", "Red")]
                    src = seal_indices[0]
                else:
                    anchor_indices = [i for i, c in enumerate(hand) if c.rank == anchor_rank]
                    if anchor_indices:
                        src = max(anchor_indices, key=lambda i: _card_quality(hand[i]))

                if src is not None:
                    dst_cands = [
                        i for i, c in enumerate(hand)
                        if i != src
                        and getattr(c, "seal", None) != "Blue"
                        and getattr(c, "enhancement", None) not in ("Steel", "Gold")
                        and c.rank != anchor_rank
                    ]
                    if not dst_cands:
                        dst_cands = [i for i, c in enumerate(hand) if i != src]
                    if dst_cands:
                        dst = min(dst_cands, key=lambda i: _card_quality(hand[i]))
                        return {"type": "use_consumable", "consumable_idx": ci, "target_cards": [dst, src]}

            # Hanged Man: Destroy up to 2 useless cards (face cards if Ride the Bus active)
            if key == "c_hanged_man" and hand:
                if has_bus:
                    to_destroy = [i for i, c in enumerate(hand) if c.is_face_card]
                else:
                    to_destroy = []
                if len(to_destroy) < 2:
                    junk = [
                        i for i, c in enumerate(hand)
                        if i not in to_destroy and c.rank != anchor_rank and not _is_held_in_hand_value_card(c, j_keys)
                    ]
                    junk.sort(key=lambda i: _card_quality(hand[i]))
                    to_destroy.extend(junk[:2 - len(to_destroy)])
                if to_destroy:
                    return {"type": "use_consumable", "consumable_idx": ci, "target_cards": to_destroy[:2]}

            # Enhancement Tarots: Lucky (c_magician), Mult (c_empress), Bonus (c_hierophant), Glass (c_justice)
            if key in ("c_magician", "c_empress", "c_hierophant", "c_justice") and hand:
                if has_bus:
                    cands = [
                        i for i, c in enumerate(hand)
                        if not c.is_face_card and getattr(c, "enhancement", "None") == "None"
                    ]
                else:
                    cands = [
                        i for i, c in enumerate(hand)
                        if getattr(c, "enhancement", "None") == "None"
                    ]
                if cands:
                    cands.sort(
                        key=lambda i: (
                            100 if hand[i].rank == anchor_rank else (50 if hand[i].rank == 14 else hand[i].rank)
                        ),
                        reverse=True
                    )
                    max_targets = 2 if key != "c_justice" else 1
                    return {"type": "use_consumable", "consumable_idx": ci, "target_cards": cands[:max_targets]}

            # Strength: Increment cards into anchor rank
            if key == "c_strength" and hand:
                target_from = (anchor_rank - 1) if anchor_rank > 2 else 14
                near_cands = [i for i, c in enumerate(hand) if c.rank == target_from]
                if near_cands:
                    return {"type": "use_consumable", "consumable_idx": ci, "target_cards": near_cands[:2]}

        return None

    # ────────────────────────────────────────────────────────────────────────
    # 3. Shop & Booster Valuation Overrides
    # ────────────────────────────────────────────────────────────────────────

    def _search_shop(self, game: BalatroGame) -> dict:
        """Principled Shop Engine:
        Evaluates immediate lift, remaining scaling runway, and replaces the true weakest joker."""
        if getattr(self, "_action_queue", None):
            return self._action_queue.pop(0)

        if not game.current_shop or all(getattr(item, "sold", False) for item in game.current_shop):
            self._rerolls_this_shop = 0
            return {"type": "leave_shop"}

        if not self._in_shop or getattr(self, "_last_ante", None) != game.ante:
            self._in_shop = True
            self._last_ante = game.ante
            self._rerolls_this_shop = 0
            self._searched_this_visit = False
            self._swapped_this_visit = False
            self._action_queue.clear()
            self._pending_swap_target_idx = None

        # Finish a previously selected swap only if its slot and price remain valid.
        if getattr(self, "_pending_swap_target_idx", None) is not None:
            target_idx = self._pending_swap_target_idx
            self._pending_swap_target_idx = None
            if 0 <= target_idx < len(game.current_shop):
                pending_item = game.current_shop[target_idx]
                pending_price = _item_price(pending_item, game)
                has_room = len(game.jokers) < game.joker_slots or getattr(pending_item, "edition", "None") == "Negative"
                if not pending_item.sold and has_room and _pair_can_afford(game, pending_price):
                    return {"type": "buy", "item_idx": target_idx}

        # 0. Consume Mercury immediately
        for ci, c_key in enumerate(game.consumable_hand):
            if c_key in ("c_mercury", "pl_mercury"):
                return {"type": "use_consumable", "consumable_idx": ci, "target_cards": []}

        rep_pair, rep_held = _get_representative_cards(game)
        s_base = _pair_eval_hand_score(game, "Pair", rep_pair, rep_pair, held_cards=rep_held)

        # Compare every eligible item, then choose the best purchase or swap.
        buys, best_swap = _rank_shop_items(game, rep_pair, rep_held, s_base)
        best_buy = buys[0] if buys else None

        if self._swapped_this_visit:
            best_swap = None
        if best_swap is not None and (best_buy is None or best_swap[0] > best_buy[0]):
            _delta, weakest_idx, item_idx = best_swap
            self._pending_swap_target_idx = item_idx
            self._swapped_this_visit = True
            self._searched_this_visit = True
            return {"type": "sell_joker", "joker_idx": weakest_idx}

        if best_buy is not None:
            self._searched_this_visit = True
            return {"type": "buy", "item_idx": best_buy[1]}

        # Keep V11's targeted deficit behavior; PairBot ranking is still used
        # first and any follow-up action is revalidated on the next call.
        _optimize_joker_order_v11(game)
        if not self._swapped_this_visit:
            action = _v11_desperate_shop_action(game, getattr(self, "_rerolls_this_shop", 0))
            if action is not None and action.get("type") not in ("buy", "sell_joker"):
                return action
        reroll_cost = max(0, game.reroll_cost - game.reroll_discount)
        if (
            getattr(self, "_rerolls_this_shop", 0) == 0
            and game.dollars - reroll_cost >= 25
        ):
            return {"type": "reroll"}
        self._searched_this_visit = True
        return {"type": "leave_shop"}

    def _rank_shop_items(self, game: BalatroGame, ref=None, surplus: bool = False, rerolls_used: int = 0):
        """Pair-aware ranking used directly by the actual shop decision path."""
        rep_pair, rep_held = _get_representative_cards(game)
        base_score = _pair_eval_hand_score(game, "Pair", rep_pair, rep_pair, held_cards=rep_held)
        buys, swap = _rank_shop_items(game, rep_pair, rep_held, base_score)
        need_sell = (swap[0], swap[1], swap[2]) if swap is not None else None
        return buys, need_sell

    def _decide_booster(self, game: BalatroGame) -> dict:
        """Picks booster items using simulation-driven utility for jokers and cards."""
        choices = game.booster_choices
        picks = game.booster_picks_remaining
        if not choices or picks <= 0:
            return {"type": "skip_booster"}

        # 1. Celestial Pack: Always pick Mercury first
        mercury_indices = [i for i, c in enumerate(choices) if c in ("c_mercury", "pl_mercury")]
        if mercury_indices:
            return {"type": "pick_booster", "indices": [mercury_indices[0]]}

        # 2. Buffoon Pack: Evaluated through principled utility
        buffoon_candidates = []
        for i, c in enumerate(choices):
            if isinstance(c, tuple) and c and c[0] == "joker":
                key = c[1]
                edition = c[2] if len(c) > 2 else "None"
                score = _eval_joker_utility(game, key, edition, price=0)
                buffoon_candidates.append((score, i))

        if buffoon_candidates:
            buffoon_candidates.sort(key=lambda x: x[0], reverse=True)
            if buffoon_candidates[0][0] > 0:
                return {"type": "pick_booster", "indices": [buffoon_candidates[0][1]]}

        # 3. Standard Pack: Evaluate cards specifically for Pairs
        card_candidates = []
        anchor_rank = _determine_anchor_rank(game)
        for i, c in enumerate(choices):
            if isinstance(c, tuple) and c and c[0] == "card":
                card = c[1]
                score = 0.0
                if getattr(card, "seal", None) == "Blue":
                    score += 5.0
                elif getattr(card, "seal", None) in ("Purple", "Red"):
                    score += 3.5
                elif getattr(card, "seal", None) == "Gold":
                    score += 2.0

                if getattr(card, "enhancement", None) == "Steel":
                    score += 4.0
                elif getattr(card, "enhancement", None) == "Gold":
                    score += 2.5
                elif getattr(card, "enhancement", None) == "Lucky":
                    score += 2.0
                elif getattr(card, "enhancement", None) == "Glass":
                    score += 2.0

                if getattr(card, "edition", None) == "Polychrome":
                    score += 2.5
                elif getattr(card, "edition", None) in ("Holographic", "Foil"):
                    score += 1.5

                if getattr(card, "rank", None) == anchor_rank:
                    score += 1.5

                if score > 0:
                    card_candidates.append((score, i))

        if card_candidates:
            card_candidates.sort(key=lambda x: x[0], reverse=True)
            return {"type": "pick_booster", "indices": [card_candidates[0][1]]}

        return _v10_decide_booster(game)

    def decide(self, game: BalatroGame) -> dict:
        """Dispatches in-blind decisions to the PairBot engine."""
        if game.state == State.SELECTING_HAND:
            return self._pair_decide_hand(game)
        if game.state == State.SHOP:
            # Keep V11's per-visit state machine (reroll accounting, swap state,
            # and reset on leave); dispatch still reaches PairBot._search_shop.
            return super().decide(game)
        if game.state == State.BOOSTER_OPEN:
            return self._decide_booster(game)
        return super().decide(game)
