"""
synergy.py — Joker synergy classification and coherence scoring for V7.

Each joker is tagged with the strategies it supports. When the agent buys a joker,
the coherence score measures how well it fits the existing loadout.

Synergy categories:
  Hand types:  flush, straight, pair, two_pair, three_kind, four_kind, full_house, five_kind
  Suits:       suit_spades, suit_hearts, suit_clubs, suit_diamonds
  Card types:  face_cards, even_ranks, odd_ranks
  Mechanics:   scaling, economy, retrigger, discard_synergy, hand_size
  Generic:     generic (flat mult/chips, no conditions — fits any build)
"""
from __future__ import annotations
from collections import Counter
from typing import Optional


# ════════════════════════════════════════════════════════════════════════════
# Joker synergy tags
# ════════════════════════════════════════════════════════════════════════════

# Tags that define "build direction" — these determine coherence
STRATEGY_TAGS = {
    "flush", "straight", "pair", "two_pair", "three_kind", "four_kind",
    "full_house", "five_kind",
    "suit_spades", "suit_hearts", "suit_clubs", "suit_diamonds",
    "face_cards", "even_ranks", "odd_ranks",
}

# Tags that are always useful (don't define a direction)
UNIVERSAL_TAGS = {"scaling", "economy", "retrigger", "generic", "utility",
                  "discard_synergy", "hand_size", "copy"}

# ════════════════════════════════════════════════════════════════════════════
# Run 5 — Joker classification sets
# ════════════════════════════════════════════════════════════════════════════

# Jokers that lose value late-game (scaling decay)
EARLY_GAME_JOKERS = {
    "j_green_joker", "j_space_joker", "j_ride_the_bus", "j_square_joker",
    "j_lucky_cat", "j_hologram", "j_vampire", "j_constellation",
    "j_fortune_teller", "j_steel_joker", "j_stone_joker",
    "j_ice_cream", "j_popcorn", "j_gros_michel", "j_seltzer",
    "j_ceremonial", "j_loyalty_card", "j_madness",
}

# Flat or x-mult jokers that pay off immediately — preferred late game
IMMEDIATE_PAYOFF_JOKERS = {
    "j_joker", "j_stuntman", "j_misprint", "j_half", "j_abstract",
    "j_cavendish", "j_the_duo", "j_duo", "j_the_trio", "j_trio",
    "j_the_family", "j_family", "j_the_order", "j_order",
    "j_the_tribe", "j_tribe", "j_triboulet", "j_perkeo", "j_chicot",
    "j_caino", "j_supernova", "j_banner", "j_blue_joker",
    "j_mystic_summit", "j_raised_fist", "j_splash", "j_acrobat",
}

# Sacrificial jokers — meant to be sold at trigger moment
SACRIFICIAL_JOKERS = {
    "j_luchador",         # sell vs boss blind
    "j_diet_cola",        # sell for free Double Tag
    "j_invisible_joker",  # sell (after 2 rounds) to duplicate a joker
}

# Weak/situational jokers — low base synergy
WEAK_JOKERS = {
    "j_egg",           # just gains sell value
    "j_credit_card",   # only enables debt
    "j_gift_card",     # marginal value
}

# Positional jokers — auto-place on purchase (Run 5)
POSITIONAL_JOKERS = {
    "j_blueprint",    # copies joker to the RIGHT
    "j_brainstorm",   # copies LEFTMOST joker
    "j_ceremonial",   # destroys joker to the RIGHT on blind select
}

# Scaling decay: how much value a scaling joker retains at each ante
# Bought at ante 1: full value. Bought at ante 8: minimal.
SCALING_DECAY_BY_ANTE = {
    1: 1.00, 2: 0.85, 3: 0.70, 4: 0.55,
    5: 0.40, 6: 0.25, 7: 0.15, 8: 0.10,
}

# Late-game bonus for immediate-payoff jokers
IMMEDIATE_BONUS_BY_ANTE = {
    1: 1.00, 2: 1.00, 3: 1.05, 4: 1.10,
    5: 1.20, 6: 1.30, 7: 1.40, 8: 1.50,
}

JOKER_TAGS: dict[str, set[str]] = {
    # ── Suit-specific mult/chips ──────────────────────────────────────
    "j_greedy_mult":    {"suit_diamonds"},
    "j_lusty_mult":     {"suit_hearts"},
    "j_wrathful_mult":  {"suit_spades"},
    "j_gluttonous_mult":{"suit_clubs"},
    "j_arrowhead":      {"suit_spades"},
    "j_onyx_agate":     {"suit_clubs"},
    "j_rough_gem":      {"suit_diamonds", "economy"},
    "j_bloodstone":     {"suit_hearts", "scaling"},
    "j_ancient":        {"scaling"},
    "j_blackboard":     {"suit_spades", "suit_clubs", "scaling"},
    "j_seeing_double":  {"suit_clubs", "scaling"},

    # ── Hand-type mult/chips ──────────────────────────────────────────
    "j_jolly":          {"pair", "two_pair", "full_house"},
    "j_zany":           {"three_kind", "full_house", "five_kind"},
    "j_mad":            {"two_pair", "full_house"},
    "j_crazy":          {"straight"},
    "j_droll":          {"flush"},
    "j_sly":            {"pair", "two_pair", "full_house"},
    "j_wily":           {"three_kind", "full_house", "five_kind"},
    "j_clever":         {"two_pair"},
    "j_devious":        {"straight"},
    "j_crafty":         {"flush"},
    "j_spare_trousers": {"two_pair"},

    # ── Hand-type x-mult (The family) ─────────────────────────────────
    "j_duo":            {"pair", "scaling"},
    "j_the_duo":        {"pair", "scaling"},
    "j_trio":           {"three_kind", "scaling"},
    "j_the_trio":       {"three_kind", "scaling"},
    "j_family":         {"four_kind", "scaling"},
    "j_the_family":     {"four_kind", "scaling"},
    "j_order":          {"straight", "scaling"},
    "j_the_order":      {"straight", "scaling"},
    "j_tribe":          {"flush", "scaling"},
    "j_the_tribe":      {"flush", "scaling"},

    # ── Straight helpers ──────────────────────────────────────────────
    "j_four_fingers":   {"flush", "straight", "utility"},
    "j_shortcut":       {"straight", "utility"},
    "j_runner":         {"straight", "scaling"},
    "j_superposition":  {"straight"},

    # ── Flush helpers ─────────────────────────────────────────────────
    "j_smeared_joker":  {"flush", "utility"},
    "j_flower_pot":     {"suit_spades", "suit_hearts", "suit_clubs", "suit_diamonds"},
    "j_seance":         {"straight", "flush"},

    # ── Face card synergies ───────────────────────────────────────────
    "j_scary_face":     {"face_cards"},
    "j_smiley":         {"face_cards"},
    "j_photograph":     {"face_cards"},
    "j_shoot_the_moon": {"face_cards"},
    "j_business_card":  {"face_cards", "economy"},
    "j_reserved_parking":{"face_cards", "economy"},
    "j_baron":          {"face_cards", "scaling"},
    "j_sock_and_buskin":{"face_cards", "retrigger"},
    "j_triboulet":      {"face_cards", "scaling"},
    "j_pareidolia":     {"face_cards", "utility"},
    "j_midas_mask":     {"face_cards", "economy"},
    "j_caino":          {"face_cards", "scaling"},
    "j_faceless":       {"face_cards", "economy", "discard_synergy"},

    # ── Rank-parity jokers ────────────────────────────────────────────
    "j_even_steven":    {"even_ranks"},
    "j_odd_todd":       {"odd_ranks"},
    "j_hack":           {"retrigger"},  # 2,3,4,5
    "j_fibonacci":      {"generic"},    # A,2,3,5,8
    "j_scholar":        {"generic"},    # Ace
    "j_walkie_talkie":  {"generic"},    # 4s and 10s

    # ── Scaling jokers (no specific hand type) ────────────────────────
    "j_green_joker":    {"scaling"},
    "j_ride_the_bus":   {"scaling"},
    "j_ice_cream":      {"scaling"},
    "j_popcorn":        {"scaling"},
    "j_gros_michel":    {"scaling"},
    "j_cavendish":      {"scaling"},
    "j_obelisk":        {"scaling"},
    "j_lucky_cat":      {"scaling"},
    "j_flash":          {"scaling"},
    "j_campfire":       {"scaling"},
    "j_constellation":  {"scaling"},
    "j_madness":        {"scaling"},
    "j_hologram":       {"scaling"},
    "j_glass_joker":    {"scaling"},
    "j_card_sharp":     {"scaling"},
    "j_loyalty_card":   {"scaling"},
    "j_erosion":        {"scaling"},
    "j_fortune_teller": {"scaling"},
    "j_hiker":          {"scaling"},
    "j_square_joker":   {"scaling"},
    "j_vampire":        {"scaling"},
    "j_throwback":      {"scaling"},
    "j_baseball":       {"scaling"},
    "j_drivers_license":{"scaling"},
    "j_wee":            {"scaling"},
    "j_wee_joker":      {"scaling"},
    "j_stone_joker":    {"scaling"},

    # ── Generic mult/chips (always useful) ────────────────────────────
    "j_joker":          {"generic"},
    "j_half":           {"generic"},
    "j_abstract":       {"generic"},
    "j_misprint":       {"generic"},
    "j_raised_fist":    {"generic"},
    "j_stuntman":       {"generic"},
    "j_blue_joker":     {"generic"},
    "j_acrobat":        {"generic"},
    "j_bull":           {"generic", "economy"},
    "j_swashbuckler":   {"generic"},
    "j_banner":         {"generic", "discard_synergy"},
    "j_mystic_summit":  {"generic", "discard_synergy"},
    "j_bootstraps":     {"generic", "economy"},
    "j_splash":         {"generic", "utility"},
    "j_lucky_joker":    {"generic"},

    # ── Retrigger jokers ──────────────────────────────────────────────
    "j_dusk":           {"retrigger"},
    "j_mime":           {"retrigger"},
    "j_hanging_chad":   {"retrigger"},
    "j_seltzer":        {"retrigger", "scaling"},

    # ── Copy jokers ───────────────────────────────────────────────────
    "j_blueprint":      {"copy"},
    "j_brainstorm":     {"copy"},

    # ── Economy jokers ────────────────────────────────────────────────
    "j_credit_card":    {"economy"},
    "j_to_the_moon":    {"economy"},
    "j_cloud_9":        {"economy"},
    "j_rocket":         {"economy"},
    "j_golden_ticket":  {"economy"},
    "j_egg":            {"economy"},
    "j_delayed_grat":   {"economy", "discard_synergy"},
    "j_gift_card":      {"economy"},
    "j_matador":        {"economy"},
    "j_satellite":      {"economy"},
    "j_mail_in_rebate": {"economy", "discard_synergy"},
    "j_to_do_list":     {"economy"},
    "j_vagabond":       {"economy"},
    "j_trading_card":   {"economy", "discard_synergy"},

    # ── Hand size / discard modifiers ─────────────────────────────────
    "j_burglar":        {"hand_size", "discard_synergy"},
    "j_troubadour":     {"hand_size"},
    "j_merry_andy":     {"hand_size", "discard_synergy"},
    "j_turtle_bean":    {"hand_size", "scaling"},
    "j_juggler":        {"hand_size"},
    "j_drunkard":       {"discard_synergy"},

    # ── Utility (no clear build direction) ────────────────────────────
    "j_mr_bones":       {"utility"},
    "j_space_joker":    {"utility"},
    "j_8_ball":         {"utility"},
    "j_burnt_joker":    {"utility"},
    "j_cartomancer":    {"utility"},
    "j_astronomer":     {"utility"},
    "j_invisible_joker":{"utility"},
    "j_perkeo":         {"utility"},
    "j_chicot":         {"utility"},
    "j_riff_raff":      {"utility"},
    "j_dna":            {"utility"},
    "j_marble":         {"utility"},
    "j_ceremonial":     {"utility"},
    "j_chaos":          {"utility"},
    "j_sixth_sense":    {"utility"},
    "j_certificate":    {"utility"},
    "j_showman":        {"utility"},
    "j_diet_cola":      {"utility"},
    "j_luchador":       {"utility"},
    "j_stencil":        {"utility"},
    "j_red_card":       {"generic"},
    "j_ramen":          {"scaling", "discard_synergy"},
    "j_castle":         {"scaling"},
    "j_the_idol":       {"scaling"},
    "j_yorick":         {"scaling", "discard_synergy"},
    "j_hit_the_road":   {"scaling", "discard_synergy"},
    "j_oops":           {"utility"},
    "j_steel_joker":    {"scaling"},
    "j_supernova":      {"generic"},
}


# ════════════════════════════════════════════════════════════════════════════
# Coherence scoring
# ════════════════════════════════════════════════════════════════════════════

def get_loadout_tags(joker_keys: list[str]) -> Counter:
    """Count strategy tags across the current joker loadout."""
    tag_counts = Counter()
    for key in joker_keys:
        tags = JOKER_TAGS.get(key, set())
        for tag in tags:
            if tag in STRATEGY_TAGS:
                tag_counts[tag] += 1
    return tag_counts


def coherence_score(candidate_key: str, existing_keys: list[str],
                    ante: int = 1) -> float:
    """
    Score how well a candidate joker fits the existing loadout, ante-aware.

    Returns 0.0 to 1.0 where:
      1.0 = perfect synergy (candidate shares strategy tags with majority of loadout)
      0.5 = neutral (generic joker, or first purchase)
      0.0 = anti-synergy (candidate's strategy conflicts with loadout direction)

    Run 5 additions:
      - Scaling/early-game jokers get decayed synergy at later antes
      - Immediate-payoff jokers get bonus at later antes
      - Weak jokers get a base penalty (capped at 0.3)
      - Sacrificial jokers get neutral base (they need to be sold, not held)
      - Positional jokers (Blueprint/Brainstorm/Ceremonial) get full synergy since
        we auto-optimize their placement
    """
    # Weak jokers capped at 0.3 synergy
    if candidate_key in WEAK_JOKERS:
        return 0.3

    # Sacrificial jokers: neutral on purchase (reward comes on correct sell)
    if candidate_key in SACRIFICIAL_JOKERS:
        return 0.5

    # Compute base synergy
    if not existing_keys:
        base = 0.5
    else:
        candidate_tags = JOKER_TAGS.get(candidate_key, set())
        candidate_strat = candidate_tags & STRATEGY_TAGS

        if not candidate_strat:
            base = 0.5
        else:
            base = _compute_strategic_overlap(candidate_strat, existing_keys)

    # Ante-aware adjustments
    ante = max(1, min(8, ante))
    if candidate_key in EARLY_GAME_JOKERS:
        base *= SCALING_DECAY_BY_ANTE[ante]
    elif candidate_key in IMMEDIATE_PAYOFF_JOKERS:
        base *= IMMEDIATE_BONUS_BY_ANTE[ante]
        base = min(base, 1.0)  # cap at 1.0

    return base


def _compute_strategic_overlap(candidate_strat: set, existing_keys: list[str]) -> float:
    """Internal: compute overlap between candidate strategy tags and loadout direction."""
    candidate_tags = candidate_strat  # already filtered to strategy tags

    loadout_tags = get_loadout_tags(existing_keys)

    if not loadout_tags:
        # Existing jokers are all generic — any direction is fine
        return 0.5

    # Find the loadout's dominant strategy direction
    top_count = loadout_tags.most_common(1)[0][1]
    dominant_tags = {tag for tag, count in loadout_tags.items() if count >= top_count}

    # Score based on overlap with dominant direction
    overlap = candidate_strat & dominant_tags
    any_overlap = candidate_strat & set(loadout_tags.keys())

    if overlap:
        # Matches the dominant strategy — high synergy
        return 0.8 + 0.2 * (len(overlap) / len(candidate_strat))
    elif any_overlap:
        # Matches a secondary strategy — moderate synergy
        return 0.5 + 0.2 * (len(any_overlap) / len(candidate_strat))
    else:
        # No overlap — this joker pulls in a different direction
        return 0.2


def estimate_joker_strength(joker_key: str) -> float:
    """
    Rough heuristic for joker "strength" used in auto-positioning.
    Higher = stronger. Used to decide Blueprint/Brainstorm placement.
    """
    # S-tier scaling jokers
    S_TIER = {"j_green_joker": 9.0, "j_space_joker": 9.0, "j_caino": 9.0,
              "j_triboulet": 10.0, "j_perkeo": 10.0, "j_chicot": 10.0}
    if joker_key in S_TIER:
        return S_TIER[joker_key]
    # Scaling jokers
    if joker_key in EARLY_GAME_JOKERS:
        return 6.0
    # Immediate payoff
    if joker_key in IMMEDIATE_PAYOFF_JOKERS:
        return 7.0
    # Weak jokers
    if joker_key in WEAK_JOKERS:
        return 2.0
    # Sacrificial jokers (shouldn't be copied)
    if joker_key in SACRIFICIAL_JOKERS:
        return 1.0
    # Positional jokers
    if joker_key in POSITIONAL_JOKERS:
        return 3.0
    # Default: medium
    return 5.0


def auto_position_on_buy(jokers: list, new_joker):
    """
    Decide the best insertion position for a newly-purchased joker.

    Args:
        jokers: current list of JokerInstance objects (will be mutated)
        new_joker: JokerInstance being added

    Returns:
        None. Modifies jokers in place via insert or append.

    Handles positional jokers:
      - Blueprint (copies right): place immediately LEFT of strongest non-positional joker
      - Brainstorm (copies leftmost): ensure strongest joker at position 0, place Brainstorm after
      - Ceremonial Dagger (destroys right on blind): place before a weak joker or at end
      - All others: normal append
    """
    key = new_joker.key

    def strength(j):
        return estimate_joker_strength(j.key)

    if key == "j_blueprint":
        # Find strongest non-positional joker, place Blueprint immediately left of it
        non_positional = [(i, j) for i, j in enumerate(jokers)
                          if j.key not in POSITIONAL_JOKERS]
        if non_positional:
            strongest_idx, _ = max(non_positional, key=lambda x: strength(x[1]))
            jokers.insert(strongest_idx, new_joker)
        else:
            jokers.append(new_joker)
        return

    if key == "j_brainstorm":
        # Ensure strongest joker at position 0
        non_positional = [(i, j) for i, j in enumerate(jokers)
                          if j.key not in POSITIONAL_JOKERS]
        if non_positional:
            strongest_idx, strongest_j = max(non_positional, key=lambda x: strength(x[1]))
            if strongest_idx != 0:
                jokers[0], jokers[strongest_idx] = jokers[strongest_idx], jokers[0]
        jokers.append(new_joker)  # Brainstorm at end
        return

    if key == "j_ceremonial":
        # Place before a weak joker (so Dagger destroys that weak one)
        # If no weak joker, place at end (destroys nothing, still builds +2 mult)
        weak_candidates = [(i, j) for i, j in enumerate(jokers)
                           if j.key in WEAK_JOKERS or j.key in SACRIFICIAL_JOKERS]
        if weak_candidates:
            # Place Ceremonial immediately before the weakest joker
            target_idx, _ = min(weak_candidates, key=lambda x: strength(x[1]))
            jokers.insert(target_idx, new_joker)
        else:
            # No weak joker to sacrifice — place at end, destroys nothing
            jokers.append(new_joker)
        return

    # Non-positional: normal append
    jokers.append(new_joker)


def loadout_coherence(joker_keys: list[str]) -> float:
    """
    Score the overall coherence of a joker loadout (0.0 to 1.0).

    High coherence = jokers share strategy tags (focused build).
    Low coherence = jokers pull in different directions (unfocused).
    """
    if len(joker_keys) <= 1:
        return 0.5

    tag_counts = get_loadout_tags(joker_keys)
    if not tag_counts:
        return 0.5  # all generic

    total_tags = sum(tag_counts.values())
    top_count = tag_counts.most_common(1)[0][1]

    # Coherence = fraction of tags that match the dominant direction
    return top_count / total_tags


# ════════════════════════════════════════════════════════════════════════════
# Display helpers
# ════════════════════════════════════════════════════════════════════════════

def get_category_summary() -> dict[str, list[str]]:
    """Group jokers by their primary strategy tag for display."""
    groups: dict[str, list[str]] = {}
    for key, tags in sorted(JOKER_TAGS.items()):
        strat = tags & STRATEGY_TAGS
        if strat:
            primary = sorted(strat)[0]  # alphabetical first strategy tag
        elif "scaling" in tags:
            primary = "scaling"
        elif "economy" in tags:
            primary = "economy"
        elif "generic" in tags:
            primary = "generic"
        else:
            primary = "utility"
        groups.setdefault(primary, []).append(key)
    return groups
