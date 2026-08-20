"""agent_v9.py — V9 Layer-0 heuristic agent: exact per-hand search on the
deterministic seed-exact sim.

Design (V9_DESIGN_NOTES.md, Layer 0 — zero training):
  1. Per-hand "just enough" solver — enumerate every 1..5-card subset, score
     through the REAL scoring engine (planet levels, jokers, boss modifiers),
     and play the cheapest combo that clears the blind instead of the greediest.
  2. Expected-value discard EV (HUMAN-FAIR) — a human knows WHICH cards
     remain in the deck (played/discarded cards are visible) but NOT the
     draw order, so a discard set is valued by the EXPECTED best-play score
     of the resulting hand over random draws from the known deck composition
     (sampled with a throwaway deterministic RNG — never the run's stream).
     Variants measured on the 300-seed bank: ceiling-ranked top-K sampling
     and a P(clear) target-aware gamble both HURT (the exact-draw agent's
     edge is information, not policy — a human-fair agent can't beat the
     mean by gambling) — the plain all-survivor mean EV is the keeper.
  3. Marginal-value shop policy — each shop joker is valued by its score delta
     on the BEST hand drawable from the deck (exact when the deck is small
     enough to guarantee it; otherwise a reachability-weighted blend with a
     typical sample), adjusted for rarity/edition/scaling potential/price,
     with money management around the $5 interest bands.
  4. Consumable/tag/boss heuristics — planets for the main hand type, Boss
     rerolls vs counter bosses, booster picks.

CRITICAL correctness note: the scoring engine is SIDEFUL — `on_hand_scored`
hooks mutate joker state (Green Joker +1/score call, Hiker writes card
bonus_chips, ...) and scoring draws from the CHANCE_NODE when a game is
attached. Every evaluation in this module therefore runs on ISOLATED COPIES:
fresh JokerInstance objects (state deep-copied), Card copies, and a throwaway
deterministic RNG (seed 0). decide() NEVER mutates the live game and NEVER
perturbs the run's seed stream. (This deliberately avoids the eval-mutation
bug latent in env_sim's combo ranking, which scores the live jokers.)
"""
from __future__ import annotations

import itertools
import random
from collections import Counter, namedtuple
from copy import deepcopy
from math import comb as _ncomb

from .card import Card
from .game import BalatroGame, State
from .hand_eval import evaluate_hand
from .scoring import score_hand
from .jokers.base import JokerInstance
from .seed_rng import make_source
from .consumables import (PLANET_HAND, TAROT_ENHANCEMENT, TAROT_MAX_TARGETS,
                          TAROT_SUIT, ALL_TAROTS, ALL_SPECTRALS)
from .constants import BLIND_CHIPS, INTEREST_RATE, RANK_CHIPS
from .graph_v9 import (boss_counter_value, connectivity_score, deck_groups)
from .synergy_tree import combined_synergy_score, load_tree

# ────────────────────────────────────────────────────────────────────────────
# Tunable parameters (future CMA-ES targets; see V9 design "fallback").
# Instances copy these; ACTIVE_PARAMS is what the component functions read.
# ────────────────────────────────────────────────────────────────────────────

PARAMS = {
    "eval_topk_play": 12,        # combos fully scored for the play decision
    "eval_topk_ev": 6,           # combos fully scored per discard-EV candidate
    "discard_max_size": 2,       # max cards per considered discard set (1-2 covers the vast majority)
    "discard_pool_size": 6,      # discard sets drawn from the N weakest cards only
    "discard_slack": 1.05,       # require the better hand to beat current best by this factor
    "buy_threshold": 0.06,       # min marginal value (score delta ratio) to buy a joker
    "booster_joker_threshold": 0.06,
    "sell_margin": 0.10,         # candidate must beat worst owned joker by this margin
    "reroll_max": 2,             # max rerolls per shop
    "reroll_min_money": 6,
    "use_tarots": True,          # tarot/spectral policy switch (Layer-0 v2)
    "convert_min_majority": 3,   # suit conversion: majority suit count needed
    "hermit_min_gain": 5,        # Hermit: use when doubling gives >= this
    "spectral_junk_max": 8,      # Familiar/Grim/Incantation: weakest-card quality
    "wraith_max_money": 5,       # Wraith zeroes money (doc §5) — only when <= this
    "scaling_bonus": 0.12,       # value boost for known scaling jokers (they outpace static eval)
    "discard_ev_samples": 6,     # best_discard: random draws sampled per candidate
                                  #   for the human-fair expected-value estimate
                                  #   (the deck's draw order is UNKNOWN to a human
                                  #   — only its composition is known). MEASURED
                                  #   BEST at 6: samples=10 alone dropped 18/300 ->
                                  #   11/300 — the mean-over-one-draw objective is
                                  #   systematically conservative, and estimator
                                  #   noise at 6 samples acts as beneficial hedging
                                  #   (implicit exploration the exact-draw agent
                                  #   doesn't need).
    "discard_ev_topk": 0,         # best_discard: 0 = sample EVERY screened candidate
                                  #   (the mean-EV baseline — measured best); > 0
                                  #   caps phase-2 sampling to the top-N by ceiling
                                  #   (measured WORSE: the ceiling ranking favors
                                  #   long-shots over reliable improvements)
    "discard_flush_ceiling": False,  # structural flush-suit bonus in the ceiling
                                  #   screen (measured neutral-to-harmful — kept
                                  #   parametric for A/B)
    "discard_target_aware": False,   # P(clear)-weighted gamble when the hand is
                                  #   short of the round target (measured HARMFUL:
                                  #   the human-fair agent can't know the draw, so
                                  #   gambling is net -EV — the exact-draw agent's
                                  #   edge is information, not decision policy)
    "discard_structure": True,    # STRUCTURE-AWARE discard pool (v3): when the
                                  #   hand holds a strong structural target (4+ of
                                  #   one suit -> flush chase, 4+ in a straight
                                  #   run -> straight chase), the discard POOL is
                                  #   the off-pattern cards ONLY — never the
                                  #   quality-weakest cards (which broke pairs /
                                  #   broke the flush suit in the traced ante-1
                                  #   deaths: seed 120 discarded KH KS from a pair,
                                  #   seed 12 discarded KD from KC KD chasing a
                                  #   never-arriving straight). The mean-EV
                                  #   objective is unchanged; only the candidate
                                  #   pool is structure-committed.
    "discard_structure_max": 4,   # max cards in a structure-committed discard
                                  #   (a 4-card flush draw needs all 4 off-suit
                                  #   cards; the old max_size=2 could never
                                  #   complete it)
    "discard_clear_weight": 0.10, # P(clear) bonus term on the discard value
                                  #   (value += clear_weight * P(best play >= the
                                  #   remaining round target)) — tilts the mean-EV
                                  #   toward draws that can actually clear the
                                  #   blind (ante-1: Small 300 / Big 450 / Boss
                                  #   600, where one straight/flush clears). Small
                                  #   by default — the plain mean is the anchor.
    "discard_struct_min_suit": 4, # flush-chase trigger: cards of one suit
    "discard_struct_min_run": 4,  # straight-chase trigger: cards in one run
    "discard_struct_min_pairs": 2,  # full-house-chase trigger: pairs in hand
                                  #   (the pool is the singletons — a pair
                                  #   is never broken)
    "discard_hold_until_clear": True,  # decide_hand: when the best hand
                                  #   CANNOT clear the remaining target but
                                  #   hands AND discards remain, keep
                                  #   discarding instead of burning a hand
                                  #   on a non-clearing play (seed 202 died
                                  #   on Small playing its 200/300 straight
                                  #   while 2 hands + 1 discard remained —
                                  #   the hand was spent on nothing). The
                                  #   old rule played whenever a discard
                                  #   didn't clear either.
    "discard_play_good_hand": 0.50,  # decide_hand: when the best hand is
                                  #   already a "good hand" — it scores at
                                  #   least this FRACTION OF THE REMAINING
                                  #   TARGET (a 240 straight clears 80% of
                                  #   the 300 Small blind) — PLAY it rather
                                  #   than hold it to chase a bigger one
                                  #   (seed 228 held a 240 straight while
                                  #   its flush line discarded 4H 5H 6S 8H
                                  #   to chase a 5-heart flush, broke the
                                  #   straight, and died 298/300 — a human
                                  #   plays the 240 straight and grinds the
                                  #   last 60). NOT the per-hand share: a
                                  #   76 two-pair is 101% of a 4-way share
                                  #   but only 25% of the blind — measuring
                                  #   against the full target keeps the
                                  #   rule honest. The hold rule is for
                                  #   WEAK hands that can't progress; a
                                  #   good hand scores the same now or
                                  #   later, so playing it frees the discard
                                  #   for the NEXT hand.
    "econ_value_weight": 1.0,     # mean-measure: expected econ $/ante term on
                                  #   joker_value (documented rates x deck
                                  #   composition — the shop search's "econ
                                  #   diff per ante")
    "gen_value_weight": 1.0,      # mean-measure: expected tarot/spectral/card
                                  #   generations/ante term on joker_value (the
                                  #   shop search's "tarot / spectral gen per
                                  #   ante")
    "consumable_discount": 0.45, # finite-lifespan jokers (Popcorn/Ice Cream/…):
                                 #   a single-shot eval sees their fresh +20
                                 #   Mult / +100 Chips, not the decay, so they
                                 #   otherwise top the buy list. Scales with                                   #   ante (a fresh Popcorn is fine ante-1;
                                   #   buying one late wastes a slot).
    # Lifecycle valuation (L3.5): a joker's value is a CURVE over the run, not
    # a snapshot. Cheap flat power gets you out of antes 1-2; economy and
    # tarot-generators fund/reshape the deck mid-run; an xMult engine wins
    # antes 4+. Curves are (early, late) additive bonuses on top of the
    # marginal snapshot — the marginal stays the anchor for what a joker does
    # RIGHT NOW, the lifecycle terms project what it will be worth.
    "lifecycle_weight": 1.0,     # master weight for all lifecycle terms
    "xmult_curve": (0.06, 0.14), # xMult: a small unconditional slice (an
                                   #   engine you can trigger is worth far
                                   #   more — gated by _xmult_support: main-
                                   #   hand match / deck conditions)
    "xmult_support_min": 0.15,   # unsupported engine weight (Duo with no Pair
                                   #   build) — buys only when it's cheap
    "xmult_rush_ante": 4,        # the tight-blind engine rush starts here (an
                                   #   engine at ante 2 is dead weight; at ante
                                   #   5 it's the win condition)
    "econ_curve": (0.20, 0.05),  # economy: compounds early (Mail-in Rebate /
                                   #   Faceless / Business Card), dead late
    "togen_curve": (0.09, 0.16), # tarot/spectral generators: deck-building
                                   #   value rises as the deck needs fixing
    "retrig_curve": (0.10, 0.07),# retriggers: steady — they multiply engines
    "tilt_surplus_margin": 1.35, # next blind beatable by this => power surplus
    "tilt_econ": 0.08,           # surplus: tilt value toward economy/deck
    "tilt_power": 0.15,          # tight OR xMult: rush the engine
    "interest_target": 25,       # save-mode: hold money up to this bank balance
                                   #   (the $25 max-interest cap) before
                                   #   discretionary spends
    "save_strong_value": 0.30,   # save-mode: only items worth >= this get bought
                                   #   (joker_value marginal ratios / pack
                                   #   values; Hermit/Death tarots qualify)
    "save_margin": 1.20,         # save-mode engages only when the reference
                                   #   hand beats the upcoming blind by this
                                   #   factor (confidence gate)
    "booster_pick_threshold": 0.06,  # min value to pick a tarot/spectral/card
    "edition_bonus": {"Foil": 0.06, "Holographic": 0.10,
                      "Polychrome": 0.18, "Negative": 0.25},
    "graph_weight": 0.15,        # L2: graph-connectivity term on joker_value
                                   # (0.0 disables — A/B via --params)
    "boss_buy_bonus": 0.35,       # L2: separate buy term for Boss-counter
                                   # jokers when a Boss is the next blind
                                   # (marginal score eval values them ~0)
    "synergy_weight": 0.30,       # L2.5: synergy prior term on joker_value —
                                   # the wiki-scraped prior (gen_wiki_prior.py)
                                   # INITIALIZES joker/consumable/voucher
                                   # edges and the mined tree (gen_synergy_tree
                                   # .py) UPGRADES them via a pseudo-count;
                                   # 0.5-neutral score → the (score - 0.5)·w
                                   # term contributes 0 when neither has data
    "synergy_tree": None,         # explicit tree path (e.g. a per-policy tree
                                   # mined with --policy); None = default
                                   # tools/synergy_tree.json
    "use_wiki_prior": True,       # L2.5: include the wiki-scraped prior
                                   # (tools/wiki_synergy_prior.json) in the
                                   # synergy blend; False = mined tree only
                                   # (A/B via --params)
}

ACTIVE_PARAMS = dict(PARAMS)

# Jokers whose value compounds over many hands/rounds — static score-delta
# undervalues them, so we add the scaling bonus. (Layer 2's graph/value model
# will replace this list with a learned quantity.)
SCALING_JOKERS = {
    "j_green_joker", "j_runner", "j_trousers", "j_ride_the_bus",
    "j_constellation", "j_lucky_cat", "j_supernova", "j_red_card",
    "j_obelisk", "j_campfire", "j_rocket", "j_hologram", "j_erosion",
    "j_fortune_teller", "j_castle", "j_wee", "j_madness", "j_flash",
    "j_bull", "j_egg", "j_satellite", "j_steel_joker",
}

# Jokers with a finite lifespan (self-decay or self-destruct). A single-shot
# marginal eval values them at their FRESH state, which dominates the buy list
# (Popcorn +20 Mult / Ice Cream +100 Chips). Discounted in joker_value.
CONSUMABLE_JOKERS = {
    "j_popcorn", "j_ice_cream", "j_ramen", "j_selzer",
    "j_gros_michel", "j_cavendish", "j_turtle_bean", "j_mr_bones",
    "j_troubadour", "j_diet_cola",
}

# Economy jokers (spec type "Economy", minus Matador — that one is a Boss
# counter valued by boss_counter_value). Marginal score eval values them ~0
# (they generate money, not chips/mult), so joker_value adds a dedicated term
# or Mail-in Rebate / Golden / Rocket would never be bought.
ECONOMY_JOKERS = {
    "j_business", "j_cloud_9", "j_credit_card", "j_delayed_grat", "j_egg",
    "j_faceless", "j_gift", "j_golden", "j_mail", "j_reserved_parking",
    "j_rocket", "j_rough_gem", "j_satellite", "j_ticket", "j_to_the_moon",
    "j_todo_list", "j_trading",
}

CHIPS_JOKERS = {"j_sly","j_wily","j_clever","j_devious","j_crafty","j_half","j_banner","j_mystic_summit","j_scary_face","j_odd_todd","j_scholar","j_even_steven"}

# ── Lifecycle archetypes (L3.5) ────────────────────────────────────────────
# Curated from tools/joker_spec.json `type` column + effect strings. These
# drive the phase-valued bonus curve in joker_value — a joker's worth changes
# over the run, and the marginal snapshot alone can't see it.

# Multiplicative-mult jokers (spec type "xMult") — the late-game engines.
XMULT_JOKERS = {
    "j_acrobat", "j_ancient", "j_baron", "j_baseball", "j_blackboard",
    "j_bloodstone", "j_caino", "j_campfire", "j_card_sharp", "j_cavendish",
    "j_constellation", "j_drivers_license", "j_duo", "j_family",
    "j_flower_pot", "j_glass", "j_hit_the_road", "j_hologram", "j_idol",
    "j_loyalty_card", "j_lucky_cat", "j_madness", "j_obelisk", "j_order",
    "j_photograph", "j_ramen", "j_seeing_double", "j_steel_joker",
    "j_stencil", "j_throwback", "j_tribe", "j_triboulet", "j_trio",
    "j_vampire", "j_yorick",
}

# Retrigger jokers (spec type "Retrigger"): score-multipliers that stack on
# engines (Chad/retriggered Photograph, Mime/held cards, Sock on faces).
RETRIGGER_JOKERS = {
    "j_dusk", "j_hack", "j_hanging_chad", "j_mime", "j_selzer",
    "j_sock_and_buskin",
}

# Deck-improving jokers: generate tarots/spectrals/cards that reshape the deck
# toward the final engine (Curated from the Effect-type generators).
TAROTGEN_JOKERS = {
    "j_8_ball", "j_cartomancer", "j_certificate", "j_dna", "j_hallucination",
    "j_marble", "j_seance", "j_vagabond",
}

# Deck-state conditions: (feature, min_count, bonus) — a joker whose real
# value depends on the FULL DECK (deck_groups read: deck+hand+spent), not the
# next-8-cards reference hand. Applies the best matching bonus. Pure reads.
DECK_CONDITIONS = {
    # (feature, min, bonus) — feature in {rank, rank9, face, diamond, heart,
    #                                  gold, enh, steel, glass, stones, n}
    "j_family":        (("rank", 7, 0.30),),          # x4 Four-of-a-kind
    "j_cloud_9":       (("rank9", 1, 0.10),),         # $1 per 9 in deck
    "j_photograph":    (("face", 8, 0.16),),          # x2 per first face
    "j_sock_and_buskin": (("face", 8, 0.16),),        # retrigger faces
    "j_baron":         (("rank", 6, 0.20),),          # x1.5 per King held
    "j_drivers_license": (("enh", 16, 0.24),),        # X3 with 16+ enhanced
    "j_golden":        (("diamond", 6, 0.08),),       # cheap: needs suit deck
    "j_rough_gem":     (("diamond", 8, 0.10),),       # $1 per diamond scored
    "j_bloodstone":    (("heart", 8, 0.10),),         # 1/2 x1.5 per heart
    "j_ancient":       (("suits", 7, 0.10),),         # x1.5 per dominant suit
    "j_steel_joker":   (("steel", 6, 0.12),),         # 0.2x per Steel in deck
    "j_glass":         (("glass", 6, 0.10),),         # gains per Glass break
    "j_blackboard":    (("suits", 7, 0.12),),         # X3 no red/black in hand
}

# Boss blinds that hard-counter an unplanned build — reroll when possible.
BAD_BOSSES = {
    "bl_needle",   # 1 hand only
    "bl_ox",       # most-played hand zeroes money
    "bl_water",    # no discards
    "bl_verdant",  # everything debuffed until a joker is sold
    "bl_eye",      # can't repeat a hand type
}

# Booster pack value by type (score-delta proxy, no pack contents known yet).
# Arcana/Spectral bumped so tarots/spectrals (now actually USED by the Layer-0
# policy) are occasionally acquired; jokers/celestial still outrank them.
PACK_VALUE = {
    "p_buffoon": 0.25, "p_buffoon_jumbo": 0.27, "p_buffoon_mega": 0.30,
    "p_celestial": 0.15, "p_celestial_jumbo": 0.17, "p_celestial_mega": 0.19,
    "p_arcana": 0.09, "p_arcana_jumbo": 0.10, "p_arcana_mega": 0.12,
    "p_spectral": 0.08, "p_spectral_jumbo": 0.10, "p_spectral_mega": 0.12,
    "p_standard": 0.07, "p_standard_jumbo": 0.08, "p_standard_mega": 0.09,
}


def pack_value(game, key: str) -> float:
    """Ante-aware booster-pack value (the shop-buy AND L1-search term).

    Base weights come from PACK_VALUE; the ante curve encodes the intended
    preference (V9 design): Buffoon strongest early while joker slots are open
    and fading as the build fills, Spectral rising mid-to-late once a build can
    absorb its risk and money is on hand, Arcana/Standard/Celestial steady
    throughout when money is spare. Pure reads — no RNG."""
    base = PACK_VALUE.get(key, 0.05)
    if key.startswith("p_buffoon"):
        filled = len(game.jokers) / max(1, game.joker_slots)
        return base * (1.0 - 0.5 * min(1.0, filled))
    if key.startswith("p_spectral"):
        ramp = 0.0 if game.ante <= 1 else min(1.0, (game.ante - 1) / 5.0)
        return base * (0.4 + 0.8 * ramp)
    return base


def _pack_card_value(card) -> float:
    """Value of a Standard-pack playing card: a modified card (enhancement /
    edition / seal) is worth taking; a plain card is not (below the pick
    threshold)."""
    v = 0.05
    if card.enhancement != "None":
        v += 0.04
    if card.edition != "None":
        v += 0.06
    if card.seal != "None":
        v += 0.05
    return v

# Vouchers worth buying when offered (key -> priority). Unknown keys are just
# never prioritized (harmless). 
VOUCHER_PRIORITY = {
    "v_overstock": 3, "v_overstock_plus": 3,
    "v_seed_money": 3, "v_money_tree": 3,
    "v_paint_brush": 2, "v_palette": 2,
    "v_hone": 2, "v_glow_up": 2,
    "v_tarot_merchant": 1, "v_planet_merchant": 1,
    "v_tarot_tycoon": 1, "v_planet_tycoon": 1,
}

HAND_TYPES = [
    "High Card", "Pair", "Two Pair", "Three of a Kind", "Straight", "Flush",
    "Full House", "Four of a Kind", "Straight Flush", "Five of a Kind",
    "Flush House", "Flush Five",
]
HAND_PRIORITY = {ht: i for i, ht in enumerate(HAND_TYPES)}


# ────────────────────────────────────────────────────────────────────────────
# Evaluation oracle (isolated, side-effect-free)
# ────────────────────────────────────────────────────────────────────────────

class _EvalGame:
    """Minimal game stand-in for evaluation scoring: an isolated deterministic
    RNG (seed 0) and no vouchers, so eval draws never touch the real stream.
    `consumable_hand` is read by Observatory (short-circuited while vouchers
    stay empty) — provided for robustness."""

    __slots__ = ("rng", "vouchers", "consumable_hand")

    def __init__(self):
        self.rng = make_source(0, "seed")
        self.vouchers = set()
        self.consumable_hand = []


def _copy_state(state: dict) -> dict:
    """Isolated copy of a joker's runtime state for the eval oracle.

    Most joker states are flat scalars (ints/floats/strs/bools/None) where
    `deepcopy` is ~5x slower than a plain dict copy — and state deepcopy is
    one of the top profiled costs (286k copies/run). Only j_satellite
    (planets_used set), j_todo_list (counts dict) and j_obelisk
    (played_hands set / runtime counts dict) hold containers, and those are
    deep-copied here so mutations can never leak to the live game.
    Byte-identical to deepcopy for every registered joker (scalars and
    tuples/frozensets are immutable — sharing them is equivalent).
    """
    out = {}
    for k, v in state.items():
        if isinstance(v, (dict, list, set)):
            out[k] = deepcopy(v)
        else:
            out[k] = v
    return out


def eval_hand_score(game, hand_type, scoring_cards, all_cards,
                    held_cards=None, extra_joker=None,
                    exclude_joker=None, level_override=None) -> int:
    """Score a hand through the REAL scoring engine on isolated copies.

    - Joker state is deep-copied (scaling values preserved) into fresh
      JokerInstance objects bound to a throwaway deterministic RNG.
    - Cards are copied (Hiker / Glass shatter never touch the real deck).
    - extra_joker: (key, edition) appended (shop/pack valuation).
    - exclude_joker: index of an owned joker to drop (sell valuation).
    """
    eg = _EvalGame()
    jokers = []
    for i, j in enumerate(game.jokers):
        if i == exclude_joker:
            continue
        # `state=` skips the fresh instance's state_defaults deepcopy — it
        # would be thrown away a line later anyway (R4's per-instance copy
        # is preserved: _copy_state gives the instance its own isolated
        # state).
        ji = JokerInstance(j.key, j.edition, game=eg,
                           state=_copy_state(j.state))
        jokers.append(ji)
    if extra_joker is not None:
        key, edition = extra_joker
        jokers.append(JokerInstance(key, edition, game=eg))
    cards = [c.copy() for c in all_cards]
    sc = [c.copy() for c in scoring_cards]
    held = [c.copy() for c in (held_cards or [])]
    pl = dict(game.planet_levels)
    if level_override:
        for ht, delta in level_override.items():
            pl[ht] = max(1, pl.get(ht, 1) + delta)
    score, _ = score_hand(
        scoring_cards=sc,
        all_cards=cards,
        hand_type=hand_type,
        jokers=jokers,
        planet_levels=pl,
        hands_left=max(1, game.hands_left),
        discards_left=game.discards_left,
        dollars=game.dollars,
        ante=game.ante,
        deck_remaining=len(game.deck),
        half_base=(game._boss_effects_on()
                   and game.current_blind.boss_key == "bl_flint"),
        game=eg,
        held_cards=held,
    )
    return score


# ────────────────────────────────────────────────────────────────────────────
# Hand enumeration + scoring
# ────────────────────────────────────────────────────────────────────────────

def enumerate_combos(hand, boss=""):
    """All playable 1..5-card subsets of `hand`.

    Returns [(indices, hand_type, scoring_cards, cards)] — the FULL
    enumeration (pure evaluate_hand, no scoring side effects).
    """
    out = []
    n = len(hand)
    if not n:
        return out
    for k in range(1, min(6, n + 1)):
        if boss == "bl_psychic" and k != 5:
            continue
        for combo in itertools.combinations(range(n), k):
            cards = [hand[i] for i in combo]
            try:
                ht, sc = evaluate_hand(cards)
            except Exception:
                continue
            out.append((combo, ht, sc, cards))
    return out


def _has_straight_ranks(uniq) -> bool:
    """True when the sorted distinct ranks contain 5 consecutive (incl. the
    A-2-3-4-5 wheel)."""
    for i in range(len(uniq) - 4):
        if uniq[i + 4] - uniq[i] == 4:
            return True
    return 14 in uniq and all(r in uniq for r in (2, 3, 4, 5))


def _size_priority_bounds(hand) -> dict:
    """Exact max achievable HAND_PRIORITY per combo size for THIS hand's rank
    and suit multisets — safe UPPER bounds used to prune the enumeration.

    A loose bound only reduces pruning, never correctness; a tight one
    (flush house needs 3+2 in-suit, straight flush needs in-suit consecutive
    ranks, etc.) is what makes the prune effective. Property-tested: for
    random + adversarial hands, bound[m] >= every m-card combo's priority.
    """
    rank_counts = {}
    suit_counts = {}
    for c in hand:
        rank_counts[c.rank] = rank_counts.get(c.rank, 0) + 1
        suit_counts[c.suit] = suit_counts.get(c.suit, 0) + 1
    max_freq = max(rank_counts.values(), default=0)
    n_pairs = sum(1 for v in rank_counts.values() if v >= 2)
    has_trips = max_freq >= 3
    has_quads = max_freq >= 4
    # Best flush-family priority: per-suit rank pattern of a 5-card flush.
    # Wild cards count as ANY suit (hand_eval._is_flush), so fold them into
    # every suit's pool — a wild-completed flush (priority 5+) is otherwise
    # invisible to the literal suit counts and the bound under-cuts a real
    # combo, letting the prune drop the flush size (an UNSOUND bound that
    # regressed flush/straight-flush plays — caught by the differential
    # test on real hands with Wild enhancements).
    def _flush_family_bound(in_suit) -> int:
        if len(in_suit) < 5:
            return 0
        rk = {}
        for c in in_suit:
            rk[c.rank] = rk.get(c.rank, 0) + 1
        mf = max(rk.values())
        if mf >= 5:
            return 11                         # Flush Five
        if (any(v >= 3 for v in rk.values())
                and sum(1 for v in rk.values() if v >= 2) >= 2):
            return 10                         # Flush House (3+2 in-suit)
        if len(rk) >= 5 and _has_straight_ranks(sorted(rk)):
            return 8                          # Straight Flush
        return 5                              # Flush
    flush_bound = 0
    for suit in ("Spades", "Hearts", "Clubs", "Diamonds"):
        in_suit = [c for c in hand
                   if c.suit == suit or c.enhancement == "Wild"]
        if len(in_suit) >= 5:
            flush_bound = max(flush_bound, _flush_family_bound(in_suit))
    straightable = _has_straight_ranks(sorted(rank_counts))

    def rank_b(m):
        if m >= 5:
            if max_freq >= 5:
                b = 9                         # Five of a Kind
            elif has_quads:
                b = 7                         # Four of a Kind
            elif has_trips and n_pairs >= 2:
                b = 6                         # Full House (3 + another 2)
            elif has_trips:
                b = 3
            elif n_pairs >= 2:
                b = 2
            elif n_pairs >= 1:
                b = 1
            else:
                b = 0
            if straightable:
                b = max(b, 4)                 # Straight
            return max(b, flush_bound)
        if m == 4:
            if has_quads:
                return 7
            if has_trips:
                return 3
            if n_pairs >= 2:
                return 2
            return 1 if n_pairs >= 1 else 0
        if m == 3:
            return 3 if has_trips else (1 if n_pairs >= 1 else 0)
        if m == 2:
            return 1 if n_pairs >= 1 else 0
        return 0

    return {m: rank_b(m) for m in range(1, 6)}


def _combo_priority(cards) -> int:
    """Hand-type priority (0-11) for a 1..5-card combo — the ranking-only
    subset of evaluate_hand.

    MUST match evaluate_hand's type determination EXACTLY: Stones are excluded
    from the type eval (debuffed ones dropped entirely), Wilds count as any
    suit, and the check order is Flush Five > Flush House > Five of a Kind >
    Straight Flush > Four of a Kind > Full House > Flush > Straight > Three of
    a Kind > Two Pair > Pair. Differential-tested against evaluate_hand on
    random + adversarial combos (0 mismatches over millions).

    Skips the scoring-card extraction, so ranking the ~160 combos per
    scored_plays call is ~2x cheaper than evaluate_hand (~720k calls/run —
    the #1 profiled hot spot after the prune).
    """
    active = [c for c in cards if c.enhancement != "Stone"]
    if not active:
        return 0
    rank_counts = {}
    suits = set()
    for c in active:
        rank_counts[c.rank] = rank_counts.get(c.rank, 0) + 1
        if c.enhancement != "Wild":
            suits.add(c.suit)
    n = len(active)
    flush = n >= 5 and len(suits) <= 1
    # straight over the distinct ranks (same as hand_eval._is_straight,
    # including the A-2-3-4-5 wheel)
    uniq = sorted(rank_counts)
    straight = False
    if len(uniq) >= 5:
        for i in range(len(uniq) - 4):
            if uniq[i + 4] - uniq[i] == 4:
                straight = True
                break
        if not straight and 14 in uniq and all(r in uniq for r in (2, 3, 4, 5)):
            straight = True
    # Single pass: max frequency + pair count. The first version used
    # any()/sum() genexprs per count — ~2.4M generator calls, SLOWER than
    # evaluate_hand's Counter path. max_freq >= N is equivalent to the
    # exact-count checks at every use site (a freq-4/5 rank returns at the
    # Four/Five-of-a-Kind checks before any freq-3 test is reached).
    max_freq = 0
    n_pairs = 0
    for v in rank_counts.values():
        if v > max_freq:
            max_freq = v
        if v >= 2:
            n_pairs += 1
    if n >= 5 and max_freq >= 5 and flush:
        return 11                       # Flush Five
    if n >= 5 and max_freq >= 3 and n_pairs >= 2 and flush:
        return 10                       # Flush House
    if max_freq >= 5:
        return 9                        # Five of a Kind
    if straight and flush:
        return 8                        # Straight Flush
    if max_freq >= 4:
        return 7                        # Four of a Kind
    if max_freq >= 3 and n_pairs >= 2:
        return 6                        # Full House
    if flush:
        return 5                        # Flush
    if straight:
        return 4                        # Straight
    if max_freq >= 3:
        return 3                        # Three of a Kind
    if n_pairs >= 2:
        return 2                        # Two Pair
    if n_pairs >= 1:
        return 1                        # Pair
    return 0                            # High Card


def _boss_play_filter(game, combo, ht, sc_cards, boss=None) -> bool:
    """Boss-restriction filter for a candidate play (eye/mouth/cerulean).

    The Hook imposes no play restriction: the played hand always scores
    fully; the discard hits 2 unplayed cards (doc §10).

    `boss` is the already-resolved boss key from scored_plays — recomputing
    `_boss_effects_on()` per combo cost ~228k calls per run for the same
    value (the boss never changes mid-hand).
    """
    if boss is None:
        boss = game.current_blind.boss_key if game._boss_effects_on() else ""
    if boss == "bl_eye" and ht in game.played_hand_types_this_round:
        return False
    if (boss == "bl_mouth" and game.played_hand_types_this_round
            and ht not in game.played_hand_types_this_round):
        return False
    if (boss == "bl_cerulean" and game.bell_card is not None
            and game.bell_card not in sc_cards):
        return False
    return True


def scored_plays(game, hand=None, extra_joker=None, exclude_joker=None,
                 topk=None, filter_boss=True, level_override=None):
    """The best candidate plays from `hand` (default: the live hand), each
    scored by the isolated oracle, sorted by (score, hand priority) desc.

    Only the top `topk` combos BY HAND PRIORITY are fully scored (scoring all
    218 would cost ~30 ms; priority ranking finds the winner in practice —
    a documented Layer-0 approximation). When every combo is boss-blocked
    (eye/mouth/cerulean), the unfiltered best is returned so play always
    advances (the game consumes the hand on rejection).
    """
    hand = hand if hand is not None else game.hand
    p = ACTIVE_PARAMS
    topk = topk if topk is not None else p["eval_topk_play"]
    boss = game.current_blind.boss_key if game._boss_effects_on() else ""

    n = len(hand)
    sizes = [5] if boss == "bl_psychic" else range(1, min(6, n + 1))
    total = sum(_ncomb(n, m) for m in sizes)
    limit = min(total, topk + 8)

    # Priority-aware enumeration prune: scored_plays only ever SCORES the
    # top-`limit` combos by (HAND_PRIORITY desc, enumeration order) — the
    # other ~198 evaluate_hand calls only exist to rank them. `_size_priority_`
    # `bounds` gives the exact max achievable priority per combo size from
    # the hand's rank/suit multiset, so a whole size can be skipped once
    # enough strictly-better combos are in hand. Every entry keeps its
    # ORIGINAL k-ascending enumeration index and the final sort is
    # (priority desc, index asc) — byte-identical to the full enumeration
    # (ties resolve the same way; the boss-blocked fallback is unaffected
    # because it selects the same top-`limit` by priority).
    nb = _size_priority_bounds(hand)
    offsets = {}
    acc = 0
    for m in range(1, 6):
        offsets[m] = acc
        acc += _ncomb(n, m)
    order = sorted((m for m in sizes), key=lambda m: (-nb[m], m))

    candidates = []
    fallback = []
    evaluated = []  # (priority, original_index) — prune counters
    for m in order:
        X = nb[m]
        if evaluated:
            # Combos sorting before ANY size-m combo: processed combos with
            # priority > X, plus priority == X with a smaller original index
            # (the tie-break). If that already fills the top-`limit`, no
            # size-m combo can enter it — skip the whole size.
            gt = sum(1 for p, _ in evaluated if p > X)
            eq = sum(1 for p, i in evaluated if p == X and i < offsets[m])
            if gt + eq >= limit:
                continue
        for j, combo in enumerate(itertools.combinations(range(n), m)):
            cards = [hand[i] for i in combo]
            # Ranking: hand-type priority only. evaluate_hand's scoring-card
            # extraction is wasted for the ~146 combos that never get scored
            # — _combo_priority is the EXACT same type test (differential-
            # tested over 2M combos, 0 mismatches) at ~2x the speed.
            priority = _combo_priority(cards)
            idx = offsets[m] + j
            evaluated.append((priority, idx))
            # ht is the exact hand-type string for the priority (the boss
            # filter reads ht; evaluate_hand runs only for the combos that
            # get scored below).
            ht = HAND_TYPES[priority]
            # The Cerulean Bell's play filter needs the SCORING cards (the
            # bell card must be among them) — compute them via evaluate_hand
            # only for that one boss (rare); every other boss reads ht only.
            if boss == "bl_cerulean" and game.bell_card is not None:
                _, sc = evaluate_hand(cards)
            else:
                sc = None
            valid = (not filter_boss) or _boss_play_filter(game, combo, ht,
                                                           cards, boss)
            # held = hand minus the played cards. Card is a dataclass whose
            # `__eq__` compares every field (~1 us) — the old `c not in cards`
            # listcomp was ~4.5M __eq__ calls per run (the #1 profiled hot
            # spot). The combo index tuple gives the exact same result with
            # cheap int-set lookups.
            cset = set(combo)
            held = [hand[i] for i in range(n) if i not in cset]
            entry = (priority, valid, idx, combo, ht, sc, cards, held)
            candidates.append(entry)
            if not valid:
                fallback.append(entry)

    if not any(c[1] for c in candidates):
        # boss-blocked: fall back to the unfiltered best (game rejects it,
        # consuming the hand, rather than the rollout stalling). The
        # top-`limit` of the fallback equals the top-`limit` of the full
        # enumeration (same priorities, same tie-break), so the prune is
        # unaffected.
        candidates = [(e[0], True, e[2], e[3], e[4], e[5], e[6], e[7])
                      for e in fallback]

    # (priority desc, original index asc) == the full enumeration's stable
    # sort by priority (the enumeration order IS the tie-break). NOTE: the
    # key must be (-priority, +index) — sorting on (+priority, -index) puts
    # the LOWEST-priority combos first, so the scoring window would only
    # ever contain High Cards (a real regression caught by
    # test_just_enough_plays_cheapest_clearing / test_planet_used_for_...).
    candidates.sort(key=lambda c: (-c[0], c[2]))
    # Score the top `topk` by priority plus a bounded tie window (same-priority
    # variants stay in) — never the full 218 (profiling: tie expansion used to
    # score ~80+ combos per call).
    scored = []
    for priority, valid, idx, combo, ht, sc, cards, held in candidates[:limit]:
        if sc is None:
            # lazy: only the scored window needs the scoring cards — this is
            # the ONLY evaluate_hand call left in the hot enumeration (was
            # one per combo, ~720k/run; now ~15k for the window + cerulean).
            try:
                _, sc = evaluate_hand(cards)
            except Exception:
                continue
        try:
            score = eval_hand_score(game, ht, sc, cards, held_cards=held,
                                    extra_joker=extra_joker,
                                    exclude_joker=exclude_joker,
                                    level_override=level_override)
        except Exception:
            continue
        scored.append((score, combo, ht))
    scored.sort(key=lambda e: (e[0], HAND_PRIORITY.get(e[2], 0)), reverse=True)
    return scored


def best_play_score(game, hand=None, extra_joker=None, exclude_joker=None,
                    filter_boss=True, topk=None, level_override=None) -> float:
    """Best playable score from `hand` (0 when the hand is empty)."""
    plays = scored_plays(game, hand=hand, extra_joker=extra_joker,
                         exclude_joker=exclude_joker,
                         topk=topk if topk is not None else ACTIVE_PARAMS["eval_topk_play"],
                         filter_boss=filter_boss,
                         level_override=level_override)
    return plays[0][0] if plays else 0.0


# ────────────────────────────────────────────────────────────────────────────
# Reference-hand valuation: the best hand we can draw, not a random slice
# ────────────────────────────────────────────────────────────────────────────
#
# The old reference was "the next 8 cards in draw order" — noise on a large
# deck, so conditional jokers (Photograph without faces, Duo without a Pair,
# The Family without a rank stack) read ~0 and were never bought. The new
# reference is the BEST hand drawable from the next blind's deck:
#
#   - Small deck (fits in hand, or fully visible across a round with the
#     hands+discards) -> the best hand is EXACT (reachability = 1) and the
#     valuation looks only at it.
#   - Large deck (can't guarantee the draw) -> the value is a reachability-
#     weighted blend of the best-hand marginal (ceiling) and the marginal on
#     a typical sample (what we'd get on an average draw).
#
# Everything here is deterministic (no RNG) — pure reads of game state, safe
# for the seed-exact sim.


def _next_blind_pool(game):
    """All cards that will form the deck at the next blind start — the
    undrawn pile plus the held and spent cards (merged + reshuffled in
    _start_blind). During a shop this is the complete remaining deck."""
    return list(game.deck) + list(game.hand) + list(game.spent)


def _reachability(game, n: int) -> float:
    """P(draw the best hand) in [0, 1]. 1 when the deck fits in hand or is
    fully visible across a full round with typical 5-card plays/discards;
    otherwise the visible fraction of the deck."""
    hs = game.hand_size
    if n <= hs:
        return 1.0
    # Cards visible across a full round: opening hand + draws after each
    # play (back to hand size) + draws after each discard (up to 5).
    visible = (hs + game.base_hands * max(0, hs - 5)
               + game.base_discards * min(5, hs))
    return min(1.0, visible / n)


def _best_straight_cards(ranked):
    """The best 5-card straight from a quality-sorted pool (highest quality
    sum), or None when the pool can't make one. Deterministic."""
    by_rank = {}
    for c in ranked:
        if c.rank not in by_rank:
            by_rank[c.rank] = c
    ranks = sorted(by_rank)
    best, best_sum = None, None
    for i in range(len(ranks) - 4):
        window = ranks[i:i + 5]
        if window[4] - window[0] == 4:
            cards = [by_rank[r] for r in window]
            s = sum(_card_quality(c) for c in cards)
            if best_sum is None or s > best_sum:
                best, best_sum = cards, s
    if 14 in by_rank and all(r in by_rank for r in (2, 3, 4, 5)):  # wheel
        cards = [by_rank[14], by_rank[2], by_rank[3], by_rank[4], by_rank[5]]
        s = sum(_card_quality(c) for c in cards)
        if best_sum is None or s > best_sum:
            best, best_sum = cards, s
    return best


def _type_candidates(ranked, ht):
    """5-card candidate plays for hand type `ht` from a quality-sorted pool
    (deterministic construction; the winner is scored through the real
    engine). Falls back to the top-5 by quality when the type can't be
    built."""
    out = []
    if ht in ("Flush", "Flush House", "Flush Five", "Straight Flush"):
        suits = {}
        for c in ranked:
            suits[c.suit] = suits.get(c.suit, 0) + 1
        if suits:
            top_suit = max(suits, key=suits.get)
            flush = [c for c in ranked if c.suit == top_suit][:5]
            if len(flush) == 5:
                out.append(flush)
    if ht in ("Straight", "Straight Flush"):
        st = _best_straight_cards(ranked)
        if st:
            out.append(st)
    if ht in ("Pair", "Two Pair", "Three of a Kind", "Four of a Kind",
              "Five of a Kind", "Full House", "Flush House", "Flush Five"):
        ranks = {}
        for c in ranked:
            ranks[c.rank] = ranks.get(c.rank, 0) + 1
        if ranks:
            top_rank = max(ranks, key=ranks.get)
            kind = [c for c in ranked if c.rank == top_rank][:5]
            if len(kind) >= 2:
                out.append(kind)
            if len(kind) >= 3:  # full house: top 3 + top 2 of the next rank
                rest = [c for c in ranked if c.rank != top_rank]
                r2 = {}
                for c in rest:
                    r2[c.rank] = r2.get(c.rank, 0) + 1
                if r2:
                    rank2 = max(r2, key=r2.get)
                    pair = [c for c in rest if c.rank == rank2][:2]
                    if len(pair) == 2:
                        out.append(kind[:3] + pair)
    if ht == "High Card" or not out:
        out.append(ranked[:5])
    return out


def _best_drawable_hand(game, pool, k, ht=None):
    """The best k-card hand drawable from `pool` (deterministic, no RNG).
    Constructs the strongest 5-card play of the requested hand type (or of
    the major types when none is committed), scores each candidate through
    the real engine, and returns the winner's 5 cards padded to k with the
    best remaining cards."""
    n = len(pool)
    if n == 0:
        return []
    if n <= k:
        return list(pool)
    ranked = sorted(pool, key=_card_quality, reverse=True)
    if ht:
        cands = _type_candidates(ranked, ht)
    else:
        cands = (_type_candidates(ranked, "Flush")
                 + _type_candidates(ranked, "Straight")
                 + _type_candidates(ranked, "Pair")
                 + _type_candidates(ranked, "High Card"))
    seen = set()
    uniq = []
    for c5 in cands:
        key = tuple(sorted(id(c) for c in c5))
        if key not in seen:
            seen.add(key)
            uniq.append(c5)
    # Card is a dataclass — membership tests via `in` pay full field-wise
    # __eq__; id() sets are ~10x cheaper and exact (pool cards are unique).
    best_cards, best_score = None, None
    for c5 in uniq:
        ht5, sc = evaluate_hand(c5)
        in5 = {id(c) for c in c5}
        pad = [c for c in ranked if id(c) not in in5][:k - 5]
        try:
            s = eval_hand_score(game, ht5, sc, c5 + pad)
        except Exception:
            continue
        if best_score is None or s > best_score:
            best_score, best_cards = s, c5
    if best_cards is None:
        return ranked[:k]
    ref = list(best_cards)
    in_ref = {id(c) for c in best_cards}
    for c in ranked:
        if len(ref) >= k:
            break
        if id(c) not in in_ref:
            in_ref.add(id(c))
            ref.append(c)
    return ref


def _typical_hand(game, pool, k):
    """A deterministic representative sample of `pool` — one card per quality
    band — approximating the hand we'd play on an average draw (the "floor"
    against which the best-hand ceiling is blended)."""
    n = len(pool)
    if n <= k:
        return list(pool)
    ranked = sorted(pool, key=_card_quality, reverse=True)
    step = n / k
    return [ranked[int(i * step)] for i in range(k)]


# (ceiling, typical, reachability, base_c, base_t) — the valuation reference.
# base_c / base_t are the reference hands' best-play scores, computed once
# per reference so every joker in a shop shares them (no per-joker re-eval).
RefHand = namedtuple("RefHand", "ceiling typical reach base_c base_t")


def reference_hand(game):
    """The reference hand(s) for shop valuation — replaces the old 'next 8
    cards in draw order' sample.

    Returns a RefHand(ceiling, typical, reach, base_c, base_t):
      - ceiling: the BEST hand drawable from the next blind's deck. When the
        deck is small enough to guarantee the draw (fits in hand, or fully
        visible across a round with hands+discards) this is exact and
        reach = 1 — the valuation looks ONLY at the best hand.
      - typical: a deterministic quality-stratified sample — the hand we'd
        play on an average draw.
      - reach: P(draw the best hand) = _reachability. The valuation blends
        the ceiling and typical marginals by it.
      - base_c / base_t: best-play scores of each reference (shared across
        all jokers in a shop visit).

    Deterministic (no RNG) — pure reads, safe for the seed-exact sim.
    """
    pool = _next_blind_pool(game)
    n = len(pool)
    if n == 0:
        return RefHand([], [], 0.0, 0.0, 0.0)
    hs = game.hand_size
    if n <= hs:
        # The whole deck fits in the opening hand: the best hand IS the deck.
        base = best_play_score(game, hand=pool, filter_boss=False)
        return RefHand(list(pool), list(pool), 1.0, base, base)
    reach = _reachability(game, n)
    # When the run is committed to a main hand type (played it >= 2 times),
    # the best hand to value against is the best hand OF that type — the one
    # the agent actually plays (Duo must read on a Pair build, not a flush).
    main = main_hand_type(game)
    committed = game.run_hand_counts.get(main, 0) >= 2
    ceiling = _best_drawable_hand(game, pool, hs, main if committed else None)
    typical = _typical_hand(game, pool, hs)
    base_c = best_play_score(game, hand=ceiling, filter_boss=False)
    base_t = best_play_score(game, hand=typical, filter_boss=False)
    return RefHand(ceiling, typical, reach, base_c, base_t)


# ────────────────────────────────────────────────────────────────────────────
# Per-hand decision: just-enough play + exact-discard EV
# ────────────────────────────────────────────────────────────────────────────

def _card_quality(card) -> float:
    """Cheap play-quality proxy used to prune discard candidates: chips +
    modifiers for enhancements/editions/seals. Suit-affinity (flush chases)
    is NOT captured — a documented Layer-0 approximation (the discard pool
    can miss a strong off-suit card the flush build would drop)."""
    return (card.base_chips
            + 5.0 * (card.enhancement != "None")
            + 8.0 * (card.edition != "None")
            + 6.0 * (card.seal != "None")
            - 2.0 * (card.debuffed or card.flipped))


def _value_multiset(deck):
    """Canonical card-VALUE multiset of the remaining deck — (rank, suit,
    enhancement, edition, seal) -> count, keys SORTED so the EV is a pure
    function of the composition. The human-fair belief is over card VALUES:
    a human knows WHICH cards remain (played/discarded cards are visible),
    never the draw order — so order-independence is a hard requirement, and
    the old exact-draw peek (deck[-i-1]) is the exact thing being replaced."""
    counts = {}
    for c in deck:
        key = (c.rank, c.suit, c.enhancement, c.edition, c.seal)
        counts[key] = counts.get(key, 0) + 1
    return {k: counts[k] for k in sorted(counts)}


def _sample_value_keys(rng, multiset, k):
    """k distinct card-VALUE keys sampled uniformly from the composition
    multiset without replacement (the exact human-fair belief)."""
    remaining = dict(multiset)
    out = []
    for _ in range(k):
        total = sum(remaining.values())
        r = rng.randrange(total)
        for key, cnt in remaining.items():
            if r < cnt:
                out.append(key)
                if cnt == 1:
                    del remaining[key]
                else:
                    remaining[key] = cnt - 1
                break
            r -= cnt
    return out


def _keys_to_cards(keys):
    """Fresh Card objects for sampled value keys (un-drawn deck cards carry
    only rank/suit/enhancement/edition/seal state)."""
    return [Card(rank, suit, enhancement=enh, edition=ed, seal=seal)
            for rank, suit, enh, ed, seal in keys]


def _quality_of_key(key) -> float:
    """_card_quality of a fresh card with this VALUE key (un-drawn deck cards
    are never debuffed/flipped — only the live hand is)."""
    rank, _, enh, ed, seal = key
    base = 50 if enh == "Stone" else RANK_CHIPS.get(rank, 0)
    return (base + 5.0 * (enh != "None") + 8.0 * (ed != "None")
            + 6.0 * (seal != "None"))


def _expand_keys(multiset, order, k):
    """The k best card VALUES from `order` (a canonical quality-desc key
    list), expanded with multiplicity into fresh Cards."""
    out = []
    for key in order:
        n = min(multiset[key], k - len(out))
        out.extend([key] * n)
        if len(out) == k:
            break
    return _keys_to_cards(out)


def _ceiling_order(keep, multiset, flush_bonus: bool = False):
    """Canonical quality-desc VALUE-key order for the discard ceiling. With
    `flush_bonus` (parametric — measured neutral-to-harmful), when the kept
    hand is chasing a flush (>= 4 of one suit) cards of that suit rank first;
    without it the ceiling is plain card quality. Ties break by key, so the
    order (and the ceiling) is order-independent."""
    suits = Counter(c.suit for c in keep)
    flush_suit = None
    if flush_bonus and suits:
        s, cnt = suits.most_common(1)[0]
        if cnt >= 4:
            flush_suit = s

    def key(k):
        q = _quality_of_key(k)
        if flush_suit is not None and k[1] == flush_suit:
            q += 100.0
        return (q, k)

    return sorted(multiset, key=key, reverse=True)


def _structure_pool(hand, min_suit=4, min_run=4, min_pairs=2):
    """Structure-aware discard POOL: when the hand holds a strong structural
    target, return (pool_indices, target) where the pool is ONLY the
    off-pattern cards — the pool is COMMITTED to the best line, in PRIORITY
    order (a hand can hold several lines; the most valuable wins):

      full-house: >= min_pairs pairs (or a triplet) -> keep ALL pair/triplet
                  ranks (pool the singleton off-pattern cards) — the rank
                  line, so the discard NEVER breaks a pair. HIGHEST priority:
                  pairs are immediately valuable and never discarded (seed
                  65 held 8C 8D AH AS KD KS — three pairs worth 124 — yet
                  the old flush-first ordering discarded the 8s and As to
                  chase a 1-card spade flush and died playing High Card 16).
      flush:      >= min_suit of one suit -> keep that suit, pool the rest
      straight:   >= min_run consecutive ranks -> keep the run, pool the rest

    This fixes the traced ante-1 deaths where the quality-weakest pool broke
    structure (seed 120 discarded KH KS from a K pair, seed 12 discarded KD
    from KC KD and AS from a 3-pair hand chasing a flush that never came,
    seed 117 discarded 3C 5D from a 5-diamond straight draw): a human
    holding 4 spades never discards a spade to "improve" the pair, and a
    human holding three pairs never breaks one to chase a flush.

    The returned pool is a set of HAND indices, order-independent (suit /
    rank-run / rank-group membership, never deck position)."""
    n = len(hand)
    if n < min_suit + 1:
        return None, None
    # Rank line FIRST (pairs are the safest, most valuable structure — a
    # flush chase is a gamble, a pair is a point on the board; a human
    # never discards from 3 pairs to chase a 1-card flush).
    groups = {}
    for i, c in enumerate(hand):
        groups.setdefault(c.rank, []).append(i)
    paired = [g for g in groups.values() if len(g) >= 2]
    if len(paired) >= min_pairs:
        keep = {i for g in paired for i in g}
        return ({i for i in range(n) if i not in keep},
                ("full_house", tuple(sorted((len(g) for g in paired),
                                             reverse=True))))
    # Flush chase: >= min_suit of one suit -> keep that suit, pool the rest.
    suits = {}
    for i, c in enumerate(hand):
        suits.setdefault(c.suit, []).append(i)
    suit, idxs = max(suits.items(), key=lambda kv: len(kv[1]))
    if len(idxs) >= min_suit:
        return {i for i in range(n) if i not in idxs}, ("flush", suit)
    # Straight chase: the longest rank run (consecutive ranks, gaps break
    # the run). Pool = cards whose rank is NOT inside the run.
    ranks = sorted({c.rank for c in hand}, reverse=True)
    best_run = []
    run = [ranks[0]]
    for r in ranks[1:]:
        if run[-1] - r == 1:
            run.append(r)
        else:
            if len(run) > len(best_run):
                best_run = run
            run = [r]
    if len(run) > len(best_run):
        best_run = run
    if len(best_run) >= min_run:
        # Keep the run AND every paired rank inside it (a 4-5-6 run with a
        # 5-pair keeps the pair — the full-house draw is the stronger line,
        # and the pool stays the singletons so the pair is never broken).
        in_run = set(best_run) | {c.rank for c in hand
                                  if c.rank in set(best_run)
                                  and sum(1 for h in hand if h.rank == c.rank) >= 2}
        return ({i for i, c in enumerate(hand) if c.rank not in in_run},
                ("straight", tuple(sorted(best_run, reverse=True))))
    return None, None


def best_discard(game, max_size=None, pool_size=None, base_score=None):
    """Expected-value discard over the KNOWN deck composition (human-fair).

    A human knows which cards remain in the deck but NOT the draw order, so
    the value of a discard set D is the EXPECTED best-play score of
    (keep + |D| random cards drawn from the remaining composition). Phase 1
    screens every candidate by its best-possible (ceiling) hand and keeps
    only candidates some draw could improve; phase 2 samples the EV of every
    screened candidate (or the top `discard_ev_topk` by ceiling, parametric).

    Measured on the 300-seed bank (2026-08-17): ceiling-ranked top-K sampling
    (`discard_ev_topk`) and the P(clear) target-aware gamble
    (`discard_target_aware`) both HURT vs the plain all-survivor mean EV —
    the exact-draw agent's edge is INFORMATION (it knows the draw), not
    decision policy, and a human-fair agent can't recover it by gambling.

    Everything uses a throwaway deterministic RNG (seed 0, never the run's
    stream: the seed-exact gate and RNG-purity invariants hold, and
    identical states always decide identically). Returns (discard_set,
    value); the empty set with the current best when no discard helps.

    Candidates are the 1..max_size subsets of the `pool_size` weakest cards
    (quality proxy) — discarding your strongest cards is rarely right, and
    pruning keeps each decision cheap (profiled).

    `base_score`: the current hand's best play score when the caller already
    computed it (decide_hand has scored_plays in hand) — recomputing it here
    costs one full scored_plays per discard decision (~141/run, the biggest
    redundancy in the hot loop).
    """
    hand = game.hand
    deck = game.deck
    p = ACTIVE_PARAMS
    if not hand or game.discards_left <= 0:
        return (), best_play_score(game, filter_boss=True)

    max_size = max_size if max_size is not None else p["discard_max_size"]
    max_size = min(max_size, len(hand) - 1, len(deck))

    # Structure-aware pool: when the hand holds a strong structural target
    # (4+ of one suit -> flush chase; 4+ in a rank run -> straight chase;
    # 2+ pairs -> full-house chase, the pool is the singletons so a pair is
    # never broken), the discard pool is ONLY the off-pattern cards. The
    # chase is GATED on the current best not clearing the remaining target —
    # a human doesn't break up a working hand to gamble on a flush (the
    # pre-gate version chased on 61% of decisions and bled cost + broke
    # pairs; the gate makes it an ante-1 survival tool). The structural max
    # size can exceed discard_max_size (a 4-card flush draw needs all 4
    # off-suit cards gone).
    base = (base_score if base_score is not None
            else best_play_score(game, filter_boss=True))
    remaining = max(0, game.current_blind.chips_target - game.chips_scored)
    struct = None
    if p["discard_structure"] and base < remaining:
        min_suit = p["discard_struct_min_suit"]
        # Small blind ante-1: chase flush for most suited suit (3+), makes Small impossible to lose per §16 300
        if game.ante == 1 and game.current_blind.kind == "Small":
            try:
                from .agent_v10 import V10_PARAMS as _V10P2
                if _V10P2.get("farm_clear_threshold", 0.9) < 1.0:
                    min_suit = min(min_suit, 3)
            except Exception:
                pass
        # Boss-aware flush demotion: gated on farming (I1) and suit-specific (I3).
        # Keep HeuristicV9 byte-identical when farm_clear_threshold>=1.0.
        # Only demote flush chase (4->5) when chase suit == debuff suit.
        _BOSS_DEBUFF_SUIT = {"bl_goad": "Spades", "bl_head": "Hearts", "bl_window": "Diamonds", "bl_club": "Clubs"}
        if game._boss_effects_on() and game.current_blind.boss_key in _BOSS_DEBUFF_SUIT:
            try:
                from .agent_v10 import V10_PARAMS as _V10P
                _farming_on = _V10P.get("farm_clear_threshold", 0.9) < 1.0
            except Exception:
                _farming_on = False
            if _farming_on:
                _debuff_suit = _BOSS_DEBUFF_SUIT[game.current_blind.boss_key]
                # Probe with min_suit=4; only demote if flush chase targets debuff suit (I3)
                _probe = _structure_pool(hand, min_suit, p["discard_struct_min_run"], p["discard_struct_min_pairs"])
                if _probe[0] is not None and _probe[1] is not None and _probe[1][0] == "flush" and _probe[1][1] == _debuff_suit:
                    min_suit = 5
                    struct = _structure_pool(hand, min_suit, p["discard_struct_min_run"], p["discard_struct_min_pairs"])
                else:
                    struct = _probe
            else:
                struct = _structure_pool(hand, min_suit, p["discard_struct_min_run"], p["discard_struct_min_pairs"])
        else:
            struct = _structure_pool(hand, min_suit,
                                     p["discard_struct_min_run"],
                                     p["discard_struct_min_pairs"])
    if struct is not None and struct[0]:
        pool_indices, target = struct
        pool = list(pool_indices)
        max_size = min(max(p["discard_structure_max"], p["discard_max_size"]),
                       len(hand) - 1, len(deck), len(pool))
    else:
        pool = pool_size if pool_size is not None else p["discard_pool_size"]
        pool = sorted(range(len(hand)),
                      key=lambda i: _card_quality(hand[i]))[:pool]
    # Joker-aware keep: never discard cards a joker needs (photograph faces, Duo Pair etc) — gated farm<1.0 so farm_off stays identical
    try:
        from balatro_sim.agent_v10 import joker_keep_indices as _jk
        _keep = _jk(hand, game)
        if _keep:
            pool = [i for i in pool if i not in _keep]
            if struct is not None and struct[0]:
                # keep at least 1 discard if pool emptied but we still need to discard something — fall back to weakest non-keep
                if not pool:
                    # pool emptied by joker keep — no joker-breaking discard
                    return (), base
    except Exception:
        pass
    if max_size < 1 or not pool:
        return (), base

    slack = p["discard_slack"]
    ev_topk = ACTIVE_PARAMS["eval_topk_ev"]
    multiset = _value_multiset(deck)
    bar = base * slack

    # Phase 1 — screen every candidate by its best-possible (ceiling) hand.
    screened = []   # (ceiling_score, dset, keep)
    flush_bonus = p["discard_flush_ceiling"]
    for k in range(1, max_size + 1):
        for dset in itertools.combinations(pool, k):
            keep = [c for i, c in enumerate(hand) if i not in dset]
            ceiling = keep + _expand_keys(multiset,
                                          _ceiling_order(keep, multiset,
                                                         flush_bonus), k)
            cscore = best_play_score(game, hand=ceiling, topk=ev_topk,
                                     filter_boss=True)
            if cscore <= bar:
                continue
            screened.append((cscore, dset, keep))
    if not screened:
        return (), base

    # Phase 2 — sample the EV of every screened candidate (mean-EV baseline;
    # `discard_ev_topk` > 0 optionally caps to the top-N by ceiling).
    screened.sort(key=lambda t: t[0], reverse=True)
    topk = p["discard_ev_topk"]
    samples = p["discard_ev_samples"]
    candidates = screened[:topk] if topk > 0 else screened
    # Per-hand share of the round's remaining target — the urgency bar for
    # the optional target-aware gamble (late in the round -> share large;
    # early -> share small -> grind).
    share = remaining / max(1, game.hands_left)
    target_aware = p["discard_target_aware"] and base < share
    clear_weight = p["discard_clear_weight"]
    rng = random.Random(0)   # throwaway deterministic sampler — never the run's
    best_val, best_set = base, ()
    for _cscore, dset, keep in candidates:
        k = len(dset)
        mean = 0.0
        clears = 0
        for _ in range(samples):
            drawn = _keys_to_cards(_sample_value_keys(rng, multiset, k))
            s = best_play_score(game, hand=keep + drawn, topk=ev_topk,
                                filter_boss=True)
            mean += s
            clears += s >= share
        mean /= samples
        p_clear = clears / samples
        if target_aware:
            val = p_clear * share + (1.0 - p_clear) * mean
        else:
            val = mean + clear_weight * p_clear * max(1.0, share)
        if val > best_val:
            best_val, best_set = val, dset
    return best_set, best_val


def main_hand_type(game) -> str:
    """The hand type the run is building: most played, tie-break by planet level."""
    counts = game.run_hand_counts
    best, best_key = "High Card", (-1, -1)
    for ht, c in counts.items():
        key = (c, game.planet_levels.get(ht, 1))
        if key > best_key:
            best_key, best = key, ht
    return best


def maybe_use_planet(game, plays=None):
    """Use a held Planet card for the intended play (blind) or the main hand
    type (shop). Returns an action dict or None. v1: planets only — tarot and
    spectral targeting is a Layer-0 follow-up."""
    if not game.consumable_hand:
        return None
    main = main_hand_type(game)
    for ci, key in enumerate(game.consumable_hand):
        if key not in PLANET_HAND:
            continue
        ht = PLANET_HAND[key]
        if game.state == State.SELECTING_HAND:
            if plays is None:
                plays = scored_plays(game)
            if plays and ht in {e[2] for e in plays[:3]}:
                return {"type": "use_consumable",
                        "consumable_idx": ci, "target_cards": []}
        else:  # SHOP
            if ht == main:
                return {"type": "use_consumable",
                        "consumable_idx": ci, "target_cards": []}
    return None


def _target_lists(hand):
    """(best_idx, weakest_idx) — hand indices sorted by play quality (see
    _card_quality). Weakest is ascending quality, best descending."""
    q = [(i, _card_quality(c)) for i, c in enumerate(hand)]
    q.sort(key=lambda t: t[1], reverse=True)
    return [i for i, _ in q], [i for i, _ in q[::-1]]


def _enhance_targets(hand, best_idx, n=2):
    """The top-`n` highest-quality cards that can still take an enhancement
    (not already enhanced, not Stone — enhancing a Stone would drop its 50
    chip bonus)."""
    out = []
    for i in best_idx:
        if len(out) >= n:
            break
        c = hand[i]
        if c.enhancement == "None" and c.enhancement != "Stone":
            out.append(i)
    return out


def _tarot_action(game, ci, key, hand, best, weakest):
    """Return a use_consumable action for tarot `key` at index `ci`, or None.

    Card-targeting tarots run in BOTH phases: during a blind they upgrade the
    live hand; in the shop the targets are the leftover hand cards, which
    return to the deck at the next blind — so shop usage permanently upgrades
    deck cards (the optimal time to use most of them)."""
    p = ACTIVE_PARAMS

    if key in TAROT_ENHANCEMENT:
        # Magician/Empress/Hierophant/Lovers/Chariot/Devil: enhance the best
        # cards. Justice (Glass — shatter risk) and Tower (Stone — niche
        # Stone-Joker builds) are deliberately excluded.
        if key in ("c_justice", "c_tower"):
            return None
        # Single-card tarots (Lovers/Chariot/Devil) target exactly 1 card;
        # Magician/Empress/Hierophant target up to 2 (reference doc §3).
        n = TAROT_MAX_TARGETS.get(key, 2)
        t = _enhance_targets(hand, best, n)
        if not t:
            return None
        return {"type": "use_consumable", "consumable_idx": ci,
                "target_cards": t}

    if key in TAROT_SUIT:
        # Star/Moon/Sun/World: each converts cards to ITS OWN suit (TAROT_SUIT).
        # Only use it when that suit is already the plurality in hand (>= the
        # majority threshold) — otherwise the tarot would fragment the hand's
        # strongest suit. (The old code converted toward whichever suit was
        # the majority REGARDLESS of the tarot, so Moon could turn cards INTO
        # Clubs while a Hearts flush was being built.) Never convert Stones
        # (they don't count toward hand types).
        target_suit = TAROT_SUIT[key]
        n_suit = sum(1 for c in hand
                     if c.suit == target_suit and c.enhancement != "Stone")
        if n_suit < p["convert_min_majority"]:
            return None
        t = [i for i in best if hand[i].suit != target_suit
             and hand[i].enhancement != "Stone"][:3]
        if not t:
            return None
        return {"type": "use_consumable", "consumable_idx": ci,
                "target_cards": t}

    if key == "c_strength":
        # +1 rank on the 2 weakest cards. Never target Aces (A wraps to 2!).
        t = [i for i in weakest if hand[i].rank < 14][:2]
        if not t:
            return None
        return {"type": "use_consumable", "consumable_idx": ci,
                "target_cards": t}

    if key == "c_death":
        # Convert the weakest card into a copy of the strongest.
        if len(hand) >= 2 and best[0] != weakest[0]:
            return {"type": "use_consumable", "consumable_idx": ci,
                    "target_cards": [weakest[0], best[0]]}
        return None

    if key == "c_hanged_man":
        # Destroy up to 2 cards = permanent deck thinning. Only in the shop:
        # destroying in-hand cards mid-blind shortens the live hand, but the
        # shop's leftover hand returns to the deck next blind.
        if game.state != State.SHOP or not weakest:
            return None
        t = weakest[:2]
        if not t:
            return None
        return {"type": "use_consumable", "consumable_idx": ci,
                "target_cards": t}

    # ── self-tarots (no targets) ────────────────────────────────────────────
    if key in ("c_high_priestess", "c_emperor"):
        # Creates 2 cards — needs a free consumable slot afterwards (the sim
        # appends without a slot check, so gate conservatively).
        if len(game.consumable_hand) <= 1:
            return {"type": "use_consumable", "consumable_idx": ci,
                    "target_cards": []}
        return None

    if key == "c_fool":
        # Copies the last used Tarot/Planet — almost always worth it.
        if game.consumables_used:
            return {"type": "use_consumable", "consumable_idx": ci,
                    "target_cards": []}
        return None

    if key == "c_hermit":
        # Doubles money (gain = min(dollars, 20) — the sim's formula per the
        # reference doc) — gain is monotonic in dollars, so use whenever it
        # clears the floor. NO upper bound: at dollars >= 20 the gain is the
        # max +$20, which an upper gate would wrongly skip.
        if game.dollars >= p["hermit_min_gain"]:
            return {"type": "use_consumable", "consumable_idx": ci,
                    "target_cards": []}
        return None

    if key == "c_temperance":
        sell_total = sum(j.state.get("sell_value", 2) for j in game.jokers)
        # Money from sell values is always useful (packs/rerolls) — no dollar
        # upper bound either.
        if sell_total >= 5:
            return {"type": "use_consumable", "consumable_idx": ci,
                    "target_cards": []}
        return None

    if key == "c_wheel_of_fortune":
        if game.jokers:
            return {"type": "use_consumable", "consumable_idx": ci,
                    "target_cards": []}
        return None

    if key == "c_judgement":
        if len(game.jokers) < game.joker_slots:
            return {"type": "use_consumable", "consumable_idx": ci,
                    "target_cards": []}
        return None

    return None


def _spectral_action(game, ci, key, hand, best, weakest):
    """Return a use_consumable action for spectral `key`, or None. Risky/
    build-destroying spectrals (Ankh, Hex, Ouija, Sigil) are skipped in v1."""
    p = ACTIVE_PARAMS

    if key == "s_black_hole":
        return {"type": "use_consumable", "consumable_idx": ci,
                "target_cards": []}

    if key in ("s_soul", "s_wraith"):
        # Soul = random Legendary (slot-gated). Wraith = random Rare but SETS
        # MONEY TO $0 (reference doc §5) — only worth it when little to lose.
        if len(game.jokers) < game.joker_slots and (
                key == "s_soul" or game.dollars <= p["wraith_max_money"]):
            return {"type": "use_consumable", "consumable_idx": ci,
                    "target_cards": []}
        return None

    if key == "s_ectoplasm":
        # Negative on a random joker (+1 slot) for a PERMANENT -1 hand size —
        # worth it once the build has enough jokers to benefit from the extra
        # slot and can absorb the hand-size hit.
        if len(game.jokers) >= 3:
            return {"type": "use_consumable", "consumable_idx": ci,
                    "target_cards": []}
        return None

    if key == "s_immolate":
        # Destroy 5 random hand cards (deck thinning) + $20. Only in the shop
        # (mid-blind it could gut the live hand), and mainly when money-poor
        # or the deck is bloated.
        if game.state == State.SHOP and (
                game.dollars < 10 or len(game.deck) + len(game.hand) > 40):
            return {"type": "use_consumable", "consumable_idx": ci,
                    "target_cards": []}
        return None

    if key in ("s_talisman", "s_deja_vu", "s_trance", "s_medium"):
        # Gold/Red/Blue/Purple seal on the best card.
        if best:
            return {"type": "use_consumable", "consumable_idx": ci,
                    "target_cards": [best[0]]}
        return None

    if key in ("s_familiar", "s_grim", "s_incantation"):
        # Destroy the weakest held card, add enhanced cards to the HAND.
        if weakest and _card_quality(hand[weakest[0]]) <= p["spectral_junk_max"]:
            return {"type": "use_consumable", "consumable_idx": ci,
                    "target_cards": [weakest[0]]}
        return None

    if key == "s_cryptid":
        # 2 copies of the best card into the HAND — worth it when the best
        # card is enhanced/editioned/sealed or a high face card.
        if best:
            c = hand[best[0]]
            if c.enhancement != "None" or c.edition != "None" \
                    or c.seal != "None" or c.rank >= 13:
                return {"type": "use_consumable", "consumable_idx": ci,
                        "target_cards": [best[0]]}
        return None

    if key == "s_aura":
        # Random edition on the best un-editioned PLAYING CARD (reference doc
        # §5: Aura targets a card in hand, NOT a joker — the sim was wrong).
        for i in best:
            if hand[i].edition == "None":
                return {"type": "use_consumable", "consumable_idx": ci,
                        "target_cards": [i]}
        return None

    return None


def tarot_value(game, key: str) -> float:
    """Shop-buy AND pack-pick value of a tarot (dimensionless priority weight,
    compared against buy_threshold / booster_pick_threshold).

    Hermit (money) / Death (deck fixing) / The Fool (copy) / The Magician
    (Lucky) are the best; enhancement + economy tarots are mid; suit-conversion
    tarots are situational (flush builds only); Justice/Tower are skipped
    entirely (Glass shatter / Stone niche — the usage policy also skips them)."""
    p = ACTIVE_PARAMS
    if key in ("c_justice", "c_tower"):
        return 0.0
    if key == "c_hermit":
        # Doubling money (gain = min(dollars, 20)) compounds into interest —
        # one of the best tarots. Slightly stronger when money is already on
        # hand (bigger immediate gain).
        return 0.18 + 0.002 * min(game.dollars, 20)
    if key == "c_death":
        return 0.16   # copy the best card onto the worst — permanent fixing
    if key == "c_fool":
        return 0.15   # copies the last-used tarot/planet
    if key == "c_magician":
        return 0.13   # Lucky on the 2 best cards
    if key == "c_empress":
        return 0.12   # +Mult is the strongest enhancement
    if key == "c_wheel_of_fortune":
        return 0.11   # 1/4 edition on a random joker
    if key == "c_temperance":
        sell = sum(j.state.get("sell_value", 2) for j in game.jokers)
        return 0.08 + 0.004 * min(sell, 20)
    if key == "c_judgement":
        return 0.10 if len(game.jokers) < game.joker_slots else 0.0
    if key == "c_chariot":
        return 0.10   # Steel
    if key == "c_hierophant":
        return 0.09   # Bonus
    if key == "c_hanged_man":
        return 0.09   # deck thinning (shop-phase)
    if key == "c_strength":
        return 0.08   # +1 rank on the 2 weakest
    if key == "c_lovers":
        return 0.08   # Wild
    if key == "c_devil":
        return 0.08   # Gold
    if key in ("c_high_priestess", "c_emperor"):
        return 0.07   # create 2 cards
    if key in TAROT_SUIT:
        return 0.06   # suit conversion — only a flush build wants it
    return 0.05


def spectral_value(game, key: str) -> float:
    """Pack-pick value of a spectral card. Ankh/Hex/Ouija/Sigil are 0 (risky,
    build-destroying — the usage policy skips them, so picking them would just
    occupy a consumable slot forever). Soul/Wraith are slot-gated. The rest get
    a steady positive weight: the hand is dealt fresh next blind, so card-target
    spectrals (Aura/Cryptid/seals/Familiar/…) are valued without inspecting the
    current (often empty, shop-phase) hand."""
    if key in ("s_ankh", "s_hex", "s_ouija", "s_sigil"):
        return 0.0
    if key == "s_black_hole":
        return 0.30    # levels every hand type — always great
    if key == "s_soul":
        return 0.25 if len(game.jokers) < game.joker_slots else 0.0
    if key == "s_ectoplasm":
        return 0.16    # Negative (+1 slot) for -1 hand size
    if key == "s_aura":
        return 0.14    # edition on a playing card
    if key == "s_wraith":
        # Random Rare but money -> $0 — only worth it with little to lose and
        # an open joker slot.
        if (len(game.jokers) < game.joker_slots
                and game.dollars <= ACTIVE_PARAMS["wraith_max_money"]):
            return 0.12
        return 0.0
    if key == "s_immolate":
        return 0.12    # destroy 5 + $20 (shop thinning)
    if key == "s_cryptid":
        return 0.12    # 2 copies of the best card
    if key in ("s_talisman", "s_deja_vu", "s_trance", "s_medium"):
        return 0.11    # seal on the best card
    if key in ("s_familiar", "s_grim", "s_incantation"):
        return 0.10    # destroy weakest -> add enhanced cards
    return 0.05


def decide_consumable(game):
    """Pick a tarot/spectral worth using right now, or None.

    Runs in SELECTING_HAND (upgrades the live hand before playing) and SHOP
    (self-tarots + upgrading leftover hand cards that return to the deck).
    Each consumable is considered once, in hand order; the first worthwhile
    action wins (one consume per decide call)."""
    cons = game.consumable_hand
    if not cons:
        return None
    hand = game.hand
    best, weakest = _target_lists(hand)
    for ci, key in enumerate(cons):
        act = _tarot_action(game, ci, key, hand, best, weakest)
        if act is None and key in ALL_SPECTRALS:
            act = _spectral_action(game, ci, key, hand, best, weakest)
        if act is not None:
            return act
    return None


def decide_hand(game) -> dict:
    """SELECTING_HAND: Verdant sell -> planet -> tarot/spectral -> just-enough
    play -> discard EV."""
    p = ACTIVE_PARAMS

    # Verdant Leaf: selling any joker lifts the all-cards debuff — do it once.
    if (game.current_blind.boss_key == "bl_verdant"
            and game.verdant_debuff and game.jokers):
        worst = worst_joker_idx(game)
        if worst is not None:
            return {"type": "sell_joker", "joker_idx": worst}

    if not game.hand:
        return {"type": "play", "cards": []}

    plays = scored_plays(game, topk=p["eval_topk_play"])
    act = maybe_use_planet(game, plays)
    if act is not None:
        return act

    if p["use_tarots"]:
        act = decide_consumable(game)
        if act is not None:
            return act

    if not plays:
        return {"type": "play", "cards": [0] if game.hand else []}

    best_score, best_combo, _ = plays[0]
    target = game.current_blind.chips_target - game.chips_scored

    if best_score >= target:
        # Just enough: fewest cards, then least overkill, among clearing plays.
        clearing = [pl for pl in plays if pl[0] >= target]
        clearing.sort(key=lambda e: (len(e[1]), e[0]))
        return {"type": "play", "cards": list(clearing[0][1])}

    # Hold-until-clear: when the best hand can't clear the remaining target
    # but hands AND discards remain, keep discarding — burning a hand on a
    # non-clearing play (seed 202: straight 200/300 while 2 hands + 1
    # discard remained) spends the round's capital on nothing, and the same
    # hand scores the same whether played now or later. Only the last hand,
    # or no-discards, plays the best available. EXCEPTION: a "good hand"
    # (clears a large per-hand share — the user's "play all good hands that
    # score near 300") is played immediately: it makes real progress toward
    # the blind, and holding it to chase a bigger hand risks breaking it
    # (seed 228 discarded a 240 straight chasing a 5-heart flush). A good
    # hand ALSO skips the slack-discard below — the discard-EV can always
    # invent a higher ceiling, but a 240 straight is worth more on the
    # board than in the deck.
    # good-hand is measured against the FULL remaining target (240 of 300 =
    # 80% — a straight that near-clears is played; 76 of 300 = 25% is not),
    # not the per-hand share (a share-relative 76 two-pair was "101% of a
    # 4-way share" and got played — regressing 16/300 -> 8/300).
    good_hand = best_score >= target * p["discard_play_good_hand"]
    if (not good_hand and game.discards_left > 0 and len(game.deck) > 0
            and p["discard_hold_until_clear"] and game.hands_left >= 2):
        dset, dscore = best_discard(game, base_score=best_score)
        if dset:
            return {"type": "discard", "cards": list(dset)}

    if not good_hand and game.discards_left > 0 and len(game.deck) > 0:
        dset, dscore = best_discard(game, base_score=best_score)
        if dscore > best_score * p["discard_slack"]:
            return {"type": "discard", "cards": list(dset)}

    return {"type": "play", "cards": list(best_combo)}


# ────────────────────────────────────────────────────────────────────────────
# Shop decision: marginal-value buys, sell-to-upgrade, econ, boss reroll
# ────────────────────────────────────────────────────────────────────────────

def _run_progress(game) -> float:
    """Run progress t in [0,1]: ante 1 -> 0, ante 8 -> 1 (smooth)."""
    return min(1.0, max(0.0, (game.ante - 1) / 7.0))


def _curve(game, pair: tuple[float, float]) -> float:
    """Linear interpolation of a (early, late) bonus pair by run progress."""
    a, b = pair
    return a + (b - a) * _run_progress(game)


# Hand-type xMult engines and the hand they need (spec effect text). An
# engine you can't trigger is dead weight — Duo in a High-Card build scores 0.
_HAND_XMULT = {
    "j_duo": "Pair", "j_trio": "Three of a Kind", "j_family": "Four of a Kind",
    "j_order": "Straight", "j_tribe": "Flush",
}


def _xmult_support(game, key: str) -> float:
    """[0.15, 1.0] how triggerable an xMult is in the current run:
    hand-type engines match the main hand; deck-conditioned engines lean on
    deck_condition_bonus; unconditional engines (Cavendish/Stencil/...) are 1.0.
    """
    if key in _HAND_XMULT:
        return 1.0 if main_hand_type(game) == _HAND_XMULT[key] else \
            ACTIVE_PARAMS["xmult_support_min"]
    if key in DECK_CONDITIONS:
        return 0.3 + 2.0 * deck_condition_bonus(game, key)
    return 1.0


def lifecycle_bonus(game, key: str) -> float:
    """Phase-valued archetype bonus: the marginal snapshot says what a joker
    does NOW; this says what it's worth as the run progresses.

    - xMult: a small unconditional slice, scaled by how triggerable the
      engine is (_xmult_support: main-hand match / deck conditions) — an
      unsupported Duo is worth ~nothing, a supported Family is huge.
    - Economy: strong early (Mail-in Rebate / Faceless compound over many
      rounds), fades late (money matters less than the final engine).
    - Tarot/spectral generators: rise mid-run as the deck needs fixing.
    - Retriggers: steady — they multiply whatever engine emerges.
    """
    if key in XMULT_JOKERS:
        return (_curve(game, ACTIVE_PARAMS["xmult_curve"])
                * _xmult_support(game, key))
    if key in ECONOMY_JOKERS:
        return _curve(game, ACTIVE_PARAMS["econ_curve"])
    if key in TAROTGEN_JOKERS:
        return _curve(game, ACTIVE_PARAMS["togen_curve"])
    if key in RETRIGGER_JOKERS:
        return _curve(game, ACTIVE_PARAMS["retrig_curve"])
    return 0.0


def deck_condition_bonus(game, key: str) -> float:
    """[0, 0.3] bonus when the FULL-DECK composition supports a deck-dependent
    joker (The Family needs 7+ of one rank, Golden needs Diamonds, Photo/
    Sock want faces, Driver's License wants 16+ enhanced ...). The single
    reference hand (next 8 deck cards) can't see these — the deck can.
    """
    conds = DECK_CONDITIONS.get(key)
    if not conds:
        return 0.0
    dg = deck_groups(game)
    suits, ranks, enh = dg["suits"], dg["ranks"], dg["enhs"]
    best = 0.0
    for feat, minc, bonus in conds:
        if feat == "rank":
            m = max(ranks.values(), default=0)
        elif feat == "rank9":
            m = ranks.get(9, 0)
        elif feat == "face":
            m = sum(ranks.get(r, 0) for r in (11, 12, 13))
        elif feat == "diamond":
            m = suits.get("Diamonds", 0)
        elif feat == "heart":
            m = suits.get("Hearts", 0)
        elif feat == "suits":
            m = max(suits.values(), default=0)
        elif feat == "enh":
            m = sum(enh.values())
        elif feat == "steel":
            m = enh.get("Steel", 0)
        elif feat == "glass":
            m = enh.get("Glass", 0)
        elif feat == "gold":
            m = enh.get("Gold", 0)
        elif feat == "n":
            m = dg["n"]
        else:
            continue
        if m >= minc:
            best = max(best, bonus)
    return best


# ────────────────────────────────────────────────────────────────────────────
# Human-fair mean measures: expected econ / generator output per ante
# ────────────────────────────────────────────────────────────────────────────
# A human can estimate a joker's run value from (a) its documented card text
# and (b) what they know about the deck — WHICH cards remain (played and
# discarded cards are visible), never the draw order. These functions turn
# that into expected $ / ante and expected tarot+spectral+card generations /
# ante — the "mean measures" the shop search compares jokers by (L1's
# comparative evaluation). Pure composition reads: no RNG, no order, no
# future state.

ROUNDS_PER_ANTE = 3            # Small + Big + Boss blinds per ante


def econ_per_ante(game, key: str) -> float:
    """Expected dollars per ante an economy joker generates, from documented
    rates x composition-based trigger odds (which cards remain in the deck).
    Hand-scoped rates assume base_hands hands/round with 5 played cards — a
    mean measure a human can reason from, never the draw order."""
    dg = deck_groups(game)
    pool = max(1, len(_next_blind_pool(game)))
    hands = max(1, game.base_hands)
    faces = sum(dg["ranks"].get(r, 0) for r in (11, 12, 13))
    if key == "j_golden":
        return 4.0 * ROUNDS_PER_ANTE                     # $4 at end of round
    if key == "j_rocket":
        return 1.0 * ROUNDS_PER_ANTE                     # $1/round (+$2 per boss)
    if key == "j_cloud_9":
        return dg["ranks"].get(9, 0) * ROUNDS_PER_ANTE   # $1 per 9 in the deck
    if key == "j_todo_list":
        return 3.2 * ROUNDS_PER_ANTE                     # $4 on the main hand
    if key == "j_satellite":
        return 1.0 * ROUNDS_PER_ANTE                     # $1 per unique planet
    if key == "j_to_the_moon":
        return (game.dollars // 5) * ROUNDS_PER_ANTE     # +$1 per $5 held
    if key == "j_mail":
        # $5 when the target rank is discarded; the target is random each
        # round (4 copies in a 52-card deck) -> P(hit) = 1-(1-4/52)^discards
        n = max(1, len(_next_blind_pool(game)))
        miss = 1.0 - 4.0 / n
        hit = 1.0 - miss ** max(0, game.base_discards)
        return 5.0 * hit * ROUNDS_PER_ANTE
    if key == "j_business":                             # 1/2 x $2 per face played
        return (0.5 * 2.0 * faces / pool * 5.0) * hands * ROUNDS_PER_ANTE
    if key == "j_reserved_parking":                     # 1/2 x $1 per face held
        return (0.5 * faces / pool * game.hand_size) * hands * ROUNDS_PER_ANTE
    if key == "j_rough_gem":                            # $1 per Diamond played
        return (dg["suits"].get("Diamonds", 0) / pool * 5.0
                ) * hands * ROUNDS_PER_ANTE
    if key == "j_ticket":                               # $4 per Gold card played
        return (4.0 * dg["enhs"].get("Gold", 0) / pool * 5.0
                ) * hands * ROUNDS_PER_ANTE
    if key == "j_faceless":
        return 0.25 * ROUNDS_PER_ANTE                    # $5 on 3+ faces discarded
    # Egg / Gift Card / Credit Card / Delayed Gratification / Trading Card:
    # sell-value growth or conditional cash — no standing rate.
    return 0.0


def gen_per_ante(game, key: str) -> float:
    """Expected tarot/spectral/card generations per ante for deck-shaping
    jokers (documented rates x composition where conditional)."""
    dg = deck_groups(game)
    pool = max(1, len(_next_blind_pool(game)))
    hands = max(1, game.base_hands)
    if key == "j_cartomancer":
        return 1.0 * ROUNDS_PER_ANTE                     # 1 Tarot per Blind selected
    if key == "j_hallucination":
        return 0.5 * 2.0                                 # 1/2 per pack, ~2 packs/ante
    if key == "j_vagabond":
        return 0.5 * ROUNDS_PER_ANTE                     # conditional on low money
    if key == "j_8_ball":                                # 1/4 per played 8
        eights = dg["ranks"].get(8, 0) / pool
        return (0.25 * eights * 5.0) * hands * ROUNDS_PER_ANTE
    if key == "j_seance":
        return 0.1 * ROUNDS_PER_ANTE                     # straight-flush conditional
    if key == "j_certificate":
        return 1.0 * ROUNDS_PER_ANTE                     # 1 sealed card per round
    if key == "j_marble":
        return 1.0 * ROUNDS_PER_ANTE                     # 1 Stone per round
    if key == "j_dna":
        return 1.0 * ROUNDS_PER_ANTE                     # 1 copy per round (single-card)
    return 0.0


def _remaining_antes(game) -> float:
    """Antes remaining this run as a multiple: ante 1 -> 8, ante 8 -> 1."""
    return max(0.0, 8.0 - game.ante + 1.0)


def econ_value(game, key: str) -> float:
    """joker_value term: expected total $ over the rest of the run mapped
    into the value band ($10/run -> +0.10, $25+/run -> cap +0.25)."""
    total = econ_per_ante(game, key) * _remaining_antes(game)
    return min(0.25, total / 10.0) * ACTIVE_PARAMS["econ_value_weight"]


def gen_value(game, key: str) -> float:
    """joker_value term: expected generations/ante mapped into the value band
    (3 tarots/ante -> +0.15, cap +0.25)."""
    return (min(0.25, gen_per_ante(game, key) * 0.05)
            * ACTIVE_PARAMS["gen_value_weight"])


def power_tilt(game, key: str, surplus: bool) -> float:
    """Scoring-easy / scoring-tight feedback tilt: when the next blind is
    trivially beatable, money accrues value over power (economy/deck terms
    up, engine rush down); when the run is on the ropes, the xMult rush
    engages so the agent reaches for the engine instead of a +4 Mult."""
    late_enough = game.ante >= ACTIVE_PARAMS["xmult_rush_ante"]
    if key in XMULT_JOKERS:
        if not surplus and late_enough:
            return ACTIVE_PARAMS["tilt_power"]
        if surplus and late_enough:
            return -0.03
        return 0.0
    if surplus:
        if key in ECONOMY_JOKERS:
            return ACTIVE_PARAMS["tilt_econ"]
        if key in TAROTGEN_JOKERS:
            return 0.06
    else:
        if key in ECONOMY_JOKERS:
            return -0.05
        if key in TAROTGEN_JOKERS:
            return -0.03
    return 0.0


def joker_value(game, key, edition, ref=None, surplus=None) -> float:
    """Marginal value of a joker: the expected score delta on the reference
    hands — the best drawable hand (ceiling) blended with a typical sample by
    reachability — plus scaling/edition bonuses.

    When the deck guarantees the best hand (reach == 1) this looks ONLY at
    the best hand; otherwise it is the reachability-weighted expectation, so
    a conditional joker's value reflects both what it could be (if we draw
    its trigger) and what it is on an average draw."""
    p = ACTIVE_PARAMS
    ceiling, typical, reach, base_c, base_t = (
        ref if ref is not None else reference_hand(game))
    base = base_c if base_c > 0 else 1.0
    with_c = best_play_score(game, hand=ceiling, extra_joker=(key, edition),
                             filter_boss=False)
    marginal = (with_c - base) / base
    if reach < 1.0 and typical:
        base_t = base_t if base_t > 0 else 1.0
        with_t = best_play_score(game, hand=typical,
                                 extra_joker=(key, edition),
                                 filter_boss=False)
        marg_t = (with_t - base_t) / base_t
        marginal = reach * marginal + (1.0 - reach) * marg_t
    value = (marginal
             + p["scaling_bonus"] * (key in SCALING_JOKERS)
             + p["edition_bonus"].get(edition, 0.0))
    # Finite-lifespan jokers: a single-shot eval sees their FRESH state
    # (Popcorn +20 Mult / Ice Cream +100 Chips) but not the decay, so they
    # would otherwise top the buy list. Discount them, scaling with how late
    # in the run we are (a fresh Popcorn is a fine ante-1 buy; buying one at
    # ante 7 spends a slot on ~5 rounds of decaying value).
    if key in CONSUMABLE_JOKERS:
        late = min(1.0, max(0.0, (game.ante - 2) / 6.0))
        value *= (1.0 - p["consumable_discount"] * late)
    # Lifecycle terms (L3.5): the marginal above is a snapshot — what the
    # joker does NOW. The phase curve projects its worth over the run
    # (xMult ramps late, economy compounds early), the deck-state term reads
    # the FULL DECK (The Family needs 7 of a rank; Golden wants Diamonds),
    # and the surplus/tight tilt shifts priority between economy/deck and
    # engine power depending on whether the next blind is comfortably
    # beatable. Pure reads; `surplus` is computed once per call site.
    sup = surplus if surplus is not None else forecast_beatable(
        game, p["tilt_surplus_margin"], ref)
    value += p["lifecycle_weight"] * (lifecycle_bonus(game, key)
                                       + deck_condition_bonus(game, key)
                                       + power_tilt(game, key, sup))
    # Human-fair mean measures (L1 comparative search): expected econ $/ante
    # and expected tarot/spectral/card generations/ante from documented rates
    # x deck composition — the "econ diff per ante" / "tarot · spectral gen
    # per ante" terms the shop search compares jokers by.
    value += econ_value(game, key) + gen_value(game, key)
    # L2 graph-connectivity: coherence with the loadout, deck support for the
    # joker's suit/rank/enhancement affinities, alignment with the main hand
    # type. Plus a dedicated Boss-counter term (those jokers add ~0 score, so
    # marginal eval alone would never buy them). Pure reads of game state (no
    # RNG, no mutation — safe for the seed-exact sim and isolated eval).
    if p["graph_weight"] > 0:
        value += p["graph_weight"] * connectivity_score(game, key)
    if p["boss_buy_bonus"] > 0:
        value += p["boss_buy_bonus"] * boss_counter_value(game, key)
    # L2.5 empirical synergy prior: mined co-performance of the candidate with
    # the owned loadout / held consumables / main hand / deck (synergy_tree.py).
    # Differential around 0.5 so a missing/neutral tree adds nothing. Pure
    # reads of game state + the mined tree (no RNG, no mutation).
    if p.get("synergy_weight", 0) > 0:
        tree = (load_tree(p["synergy_tree"]) if p.get("synergy_tree")
                else None)
        # The wiki prior is the INITIALIZATION; passing an empty dict
        # disables it (all wiki lookups go neutral, hand/card fall through
        # to the mined tree) — the "prior off" A/B arm.
        prior = None if p.get("use_wiki_prior", True) else {}
        value += p["synergy_weight"] * (combined_synergy_score(game, key,
                                                                tree,
                                                                prior) - 0.5)
    return value


def worst_joker_idx(game, ref=None):
    """Index of the owned joker with the lowest marginal contribution on the
    best drawable hand (the run's ceiling — what we're building toward).

    The last xMult joker is never a sell candidate: a marginal snapshot on
    one reference hand reads Photograph ~0 on a face-less draw — the exact
    underestimate that would sell the run's engine for a +4 Mult."""
    if not game.jokers:
        return None
    owned = [j.key for j in game.jokers]
    n_xmult = sum(1 for k in owned if k in XMULT_JOKERS)
    ceiling, typical, reach, base_c, base_t = (
        ref if ref is not None else reference_hand(game))
    base = base_c if base_c > 0 else 1.0
    worst, worst_val = 0, None
    for i in range(len(game.jokers)):
        if n_xmult <= 1 and owned[i] in XMULT_JOKERS:
            continue  # protect the run's only engine
        without = best_play_score(game, hand=ceiling, exclude_joker=i,
                                  filter_boss=False)
        contrib = (base - without) / base
        if worst_val is None or contrib < worst_val:
            worst, worst_val = i, contrib
    if worst_val is None:
        return None  # every joker is a protected engine
    return worst


# Buy tie-break: jokers > boosters > consumables/cards > vouchers (used only
# when two items value identically — see decide_shop).
_KIND_RANK = {"joker": 3, "booster": 2, "tarot": 1, "planet": 1,
               "spectral": 1, "card": 1, "voucher": 0}


def next_blind_target(game) -> float:
    """Chips required by the UPCOMING blind during a shop (current_blind is
    the just-beaten one). Mirrors game.py's boss-scaling (Needle 1x base /
    Wall 4x / Violet 6x); a post-boss shop targets next ante's Small; ante-8
    + post-boss = the banked win, return 0 (never save-gate a final shop)."""
    nxt = game.blind_idx + 1
    if nxt >= 3:
        if game.ante >= 8:
            return 0.0
        return float(BLIND_CHIPS[game.ante + 1][0])
    chips = BLIND_CHIPS[game.ante][nxt]
    if nxt == 2:  # upcoming Boss blind — apply its score scaling
        boss = game.next_boss_key
        if boss == "bl_needle":
            chips = BLIND_CHIPS[game.ante][0]
        elif boss == "bl_wall":
            chips = BLIND_CHIPS[game.ante][0] * 4
        elif boss == "bl_violet":
            chips = BLIND_CHIPS[game.ante][0] * 6
    return float(chips)


def forecast_beatable(game, margin: float, ref=None) -> bool:
    """True when the expected best play clears the upcoming blind by `margin`
    (score vs chips target — the save-mode confidence gate). Uses the
    reachability-blended expected score: the best drawable hand when the deck
    guarantees it, else the blend with a typical sample. `ref` (a RefHand)
    carries the precomputed base scores, so this costs no extra evals."""
    if ref is None:
        ref = reference_hand(game)
    ceiling, typical, reach, base_c, base_t = ref
    expected = reach * base_c + (1.0 - reach) * base_t
    return expected >= next_blind_target(game) * margin


def worth_spending(game, price: int, value: float) -> bool:
    """Money-management gate: never pay more than one $5 interest band for an
    item below the interest cap, unless it's exceptional value or we're
    broke/early. Above the cap, surplus is spent instead of hoarded.

    MEASURED (2026-08-18): ante-1 economy fixes were A/B'd on the 300-seed
    bank and ALL measured flat or WORSE, so this stays the plain band rule:
    (a) blanket interest floor (hold >= $5) 14 -> 10 wins, ante-1 deaths
    32 -> 37; (b) joker-exempt floor 14 -> 11-12 wins, deaths 32 -> 35-37;
    (c) reroll gating (max 1, min $10) flat 14 wins / 31-32 deaths; (d)
    floor + reroll gate 11 wins / 37 deaths. Ante-1 income (~$9-11/blind)
    is too tight to both buy power AND hold the floor — preserving cash
    at the expense of jokers/boosters leaves runs underpowered and the
    Boss-death seeds (18/32, all holding 1-3 weak commons: Crazy/Square/
    Ticket/Droll) are shop-RNG losses the exact-draw oracle also can't
    save (its own ante-1 clear is 91.3% — the bank's ceiling)."""
    if price == 0:
        return True
    d = game.dollars
    if price > d:
        return False
    if d < 5 or game.ante <= 2:
        return True
    interest_loss = (d // 5) - ((d - price) // 5)
    if d > game.interest_cap * INTEREST_RATE:
        # Above the $25 max-interest cap: "spend what you make" — a purchase
        # may cross up to one band below the cap (keeps >= $20) unless it's
        # exceptional value, then more.
        if interest_loss <= 1:
            return True
        return value >= 0.25
    if interest_loss <= 1:
        return True
    return value >= 0.25


def _rank_shop_items(game, ref, surplus):
    """(buys, need_sell) — every affordable unsold shop item valued by the
    human-fair composite (joker_value / pack_value / tarot_value / ...),
    plus a sell-to-upgrade candidate when joker slots are full. Pure reads.

    Shared by L0's decide_shop (greedy first-accept) and L1's comparative
    search (explicit argmax over the same values) — one valuation, two
    decision rules. `ref` is the RefHand, `surplus` the precomputed power-
    surplus flag (both free once reference_hand ran)."""
    p = ACTIVE_PARAMS
    buys = []  # (value, item_idx)
    need_sell = None  # (candidate_value, worst_idx) when slots are full
    worst_cache = None
    for i, item in enumerate(game.current_shop):
        if item.sold:
            continue
        price = item.discounted_price(game.shop_discount)
        if price > game.dollars:
            continue
        if item.kind == "joker":
            value = joker_value(game, item.key, item.edition, ref, surplus)
            has_room = (len(game.jokers) < game.joker_slots
                        or item.edition == "Negative")
            # Ante 1-2 with an EMPTY build: the FIRST scoring joker is a
            # must-have (ante-1 blinds die without one) — drop the
            # threshold to 0. NOT for the second+ joker: the old rule kept
            # the zero threshold while `game.ante <= 2` regardless of build,
            # buying 18 sub-0.12 jokers in 100 seeds (Superposition / Card
            # Sharp / Loyalty Card at $3-5 each — the ante-1 money leak; the
            # interest-floor fix that would have held the cash instead
            # measured WORSE, 14->10 wins, so the threshold is the lever).
            thr = 0.0 if (game.ante <= 2 and not game.jokers) else p["buy_threshold"]
            if has_room and value >= thr:
                buys.append((value, i))
            elif not has_room:
                if worst_cache is None:
                    worst_cache = worst_joker_idx(game, ref)
                if (worst_cache is not None
                        and value - joker_value_of(game, worst_cache, ref)
                        >= p["sell_margin"]):
                    need_sell = (value, worst_cache)
        elif item.kind == "booster":
            value = pack_value(game, item.key)
            if value >= p["buy_threshold"]:
                buys.append((value, i))
        elif item.kind == "voucher":
            prio = VOUCHER_PRIORITY.get(item.key, 0)
            # Vouchers are long-term econ: never buy while the build doesn't
            # exist (no jokers), never before ante 3 (early money buys jokers
            # and packs), and never drain the bank below its first $5 band.
            if (prio >= 2 and len(game.jokers) > 0 and game.ante > 2
                    and game.dollars - price >= 5):
                buys.append((0.10 + 0.05 * prio, i))
        elif item.kind == "planet" and PLANET_HAND.get(item.key) == main_hand_type(game):
            buys.append((0.08, i))
        elif item.kind == "tarot":
            # Buy worth-while tarots when a consumable slot is free. tarot_value
            # ranks Hermit/Death/Magician/Fool high, suit-conversion low, and
            # Justice/Tower 0 (the usage policy skips them).
            value = tarot_value(game, item.key)
            if (value >= p["buy_threshold"]
                    and len(game.consumable_hand) < game.consumable_slots):
                buys.append((value, i))
        elif item.kind == "spectral":
            # Spectrals never appear in the Red-Deck shop (Ghost-Deck only),
            # but if they ever do, value them like a pack pick.
            value = spectral_value(game, item.key)
            if (value >= p["buy_threshold"]
                    and len(game.consumable_hand) < game.consumable_slots):
                buys.append((value, i))
        elif item.kind == "card" and item.card is not None:
            value = _pack_card_value(item.card)
            if value >= p["buy_threshold"]:
                buys.append((value, i))
    return buys, need_sell


def decide_shop(game, rerolls_used: int) -> dict:
    """SHOP: boss reroll -> use planet -> buy best item -> sell-to-upgrade ->
    reroll -> leave. One purchase per call; the driver re-enters each step."""
    p = ACTIVE_PARAMS

    # Boss reroll (Director's Cut / Retcon) against a counter boss. The
    # upcoming Boss Blind is pre-selected at shop entry (game.next_boss_key),
    # so this fires BEFORE the boss — the old guard (current_blind.kind ==
    # "Boss") only matched after the boss was beaten, wasting $10 per Ante.
    if (game.next_boss_key in BAD_BOSSES and game.dollars >= 10):
        can_dc = ("v_directors_cut" in game.vouchers
                  and game.dc_reroll_ante != game.ante)
        can_retcon = "v_retcon" in game.vouchers
        if can_dc or can_retcon:
            return {"type": "reroll_boss"}

    act = maybe_use_planet(game)
    if act is not None:
        return act

    if p["use_tarots"]:
        act = decide_consumable(game)
        if act is not None:
            return act

    ref = reference_hand(game)
    # Power-surplus flag for the lifecycle tilt: computed ONCE per shop visit
    # (the RefHand carries the precomputed base scores, so this is free).
    surplus = forecast_beatable(game, p["tilt_surplus_margin"], ref)
    buys, need_sell = _rank_shop_items(game, ref, surplus)

    if need_sell is not None:
        # Make room first; the buy follows on the next decide call.
        return {"type": "sell_joker", "joker_idx": need_sell[1]}

    # Interest-aware save mode: while below the $25 max-interest cap, if the
    # shop has nothing strong AND the upcoming blind is comfortably beatable,
    # hold the money (only exceptional items check out; no rerolls). Once the
    # build can't clear the blind or something strong is offered, spend.
    save_mode = (
        game.ante > 2
        and game.dollars < p["interest_target"]
        and max((v for v, _ in buys), default=0.0) < p["save_strong_value"]
        and forecast_beatable(game, p["save_margin"], ref)
    )

    if buys:
        # Tie-break by kind: a joker/pack must never lose to a voucher of the
        # same value (shop order used to decide — the ante-1 Seed-Money
        # voucher drained $10 while a Buffoon pack sat next to it).
        buys.sort(key=lambda b: (b[0], _KIND_RANK.get(
            game.current_shop[b[1]].kind, 1)), reverse=True)
        for value, idx in buys:
            item = game.current_shop[idx]
            price = item.discounted_price(game.shop_discount)
            if (price <= game.dollars
                    and (not save_mode or value >= p["save_strong_value"])
                    and worth_spending(game, price, value)):
                return {"type": "buy", "item_idx": idx}
        # Affordable but not worth spending on (interest cost) — fall through.

    reroll_cost = max(0, game.reroll_cost - game.reroll_discount)
    if (not save_mode
            and game.dollars >= max(reroll_cost, p["reroll_min_money"])
            and rerolls_used < p["reroll_max"]):
        return {"type": "reroll"}

    return {"type": "leave_shop"}


def joker_value_of(game, idx, ref=None) -> float:
    """Marginal value of an OWNED joker at index idx (for sell comparisons),
    computed on the best drawable hand (the shared base score from the
    RefHand makes this free)."""
    ceiling, typical, reach, base_c, base_t = (
        ref if ref is not None else reference_hand(game))
    base = base_c if base_c > 0 else 1.0
    without = best_play_score(game, hand=ceiling, exclude_joker=idx,
                              filter_boss=False)
    return (base - without) / base


# ────────────────────────────────────────────────────────────────────────────
# Booster picks
# ────────────────────────────────────────────────────────────────────────────

def decide_booster(game) -> dict:
    """BOOSTER_OPEN: pick the highest-value choices across EVERY pack kind —
    jokers (slot permitting), main-hand Planets, Tarots, Spectrals, and
    modified Standard-pack cards. (The old code only handled jokers and
    planets, so Arcana/Spectral/Standard packs were bought and then skipped —
    spectrals were never acquired at all.)"""
    p = ACTIVE_PARAMS
    choices = game.booster_choices
    picks = game.booster_picks_remaining
    if not choices or picks <= 0:
        return {"type": "skip_booster"}

    ref = None  # lazy: only joker choices need the valuation reference
    main = main_hand_type(game)
    ranked = []  # (value, index)
    for i, c in enumerate(choices):
        value = None
        is_joker = isinstance(c, tuple) and c and c[0] == "joker"
        if is_joker:
            key, edition = c[1], c[2]
            if len(game.jokers) >= game.joker_slots and edition != "Negative":
                continue
            if ref is None:
                ref = reference_hand(game)
            value = joker_value(game, key, edition, ref)
        elif isinstance(c, tuple) and c and c[0] == "card":
            value = _pack_card_value(c[1])
        elif isinstance(c, str):
            if c in PLANET_HAND:
                value = (0.10 if (PLANET_HAND[c] == main
                                  and len(game.consumable_hand) < game.consumable_slots)
                         else 0.0)
            elif c in ALL_TAROTS:
                if len(game.consumable_hand) < game.consumable_slots:
                    value = tarot_value(game, c)
            elif c in ALL_SPECTRALS:
                if len(game.consumable_hand) < game.consumable_slots:
                    value = spectral_value(game, c)
        if value is None:
            continue
        threshold = (p["booster_joker_threshold"] if is_joker
                     else p["booster_pick_threshold"])
        if value >= threshold:
            ranked.append((value, i))
    if ranked:
        ranked.sort(key=lambda t: t[0], reverse=True)
        return {"type": "pick_booster",
                "indices": [i for _, i in ranked[:picks]]}
    return {"type": "skip_booster"}


# ────────────────────────────────────────────────────────────────────────────
# Policies
# ────────────────────────────────────────────────────────────────────────────

class HeuristicV9:
    """Layer-0 heuristic policy. decide(game) -> action dict.

    Instantiate once per process (module-level ACTIVE_PARAMS are shared by the
    component functions; per-process state like the shop reroll counter lives
    on the instance)."""
    policy_name = "heuristic_v9"

    def __init__(self, params=None):
        if params:
            ACTIVE_PARAMS.update(params)
        self._rerolls_this_shop = 0
        self._in_shop = False

    def decide(self, game) -> dict:
        st = game.state
        if st == State.SELECTING_HAND:
            return decide_hand(game)
        if st == State.SHOP:
            if not self._in_shop:
                self._in_shop = True
                self._rerolls_this_shop = 0
            act = decide_shop(game, self._rerolls_this_shop)
            if act.get("type") == "reroll":
                self._rerolls_this_shop += 1
            elif act.get("type") == "leave_shop":
                self._in_shop = False
            return act
        if st == State.BLIND_SELECT:
            return {"type": "play_blind"}
        if st == State.BOOSTER_OPEN:
            return decide_booster(game)
        return {"type": "noop"}  # ROUND_EVAL / GAME_OVER


class RandomPolicy:
    """A reasonable random baseline for A/B benchmarks (rollout-compatible)."""

    policy_name = "random"

    def __init__(self, rng=None):
        import random as _r
        self._rng = _r

    def decide(self, game) -> dict:
        st = game.state
        r = self._rng
        if st == State.BLIND_SELECT:
            return {"type": "play_blind" if r.random() < 0.8 else "skip_blind"}
        if st == State.SELECTING_HAND:
            hand = game.hand
            if not hand:
                return {"type": "play", "cards": []}
            roll = r.random()
            if roll < 0.5:
                k = r.randint(1, min(5, len(hand)))
                return {"type": "play", "cards": list(r.sample(range(len(hand)), k))}
            if roll < 0.8 and game.discards_left > 0:
                k = r.randint(1, min(3, len(hand)))
                return {"type": "discard", "cards": list(r.sample(range(len(hand)), k))}
            if game.consumable_hand:
                return {"type": "use_consumable",
                        "consumable_idx": 0, "target_cards": []}
            return {"type": "play", "cards": list(r.sample(range(len(hand)), 1))}
        if st == State.SHOP:
            unsold = [i for i, it in enumerate(game.current_shop)
                      if not it.sold and it.discounted_price(game.shop_discount) <= game.dollars]
            roll = r.random()
            if unsold and roll < 0.4:
                return {"type": "buy", "item_idx": r.choice(unsold)}
            if game.jokers and roll < 0.5:
                return {"type": "sell_joker", "joker_idx": r.randrange(len(game.jokers))}
            if roll < 0.6:
                return {"type": "reroll"}
            return {"type": "leave_shop"}
        if st == State.BOOSTER_OPEN:
            if game.booster_choices and r.random() < 0.5:
                return {"type": "pick_booster",
                        "indices": list(range(min(game.booster_picks_remaining,
                                                 len(game.booster_choices))))}
            return {"type": "skip_booster"}
        return {"type": "noop"}
