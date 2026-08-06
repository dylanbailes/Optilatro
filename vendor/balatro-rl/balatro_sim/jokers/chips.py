"""
chips.py — Flat chip bonus jokers.
These add chips in various ways.
"""
from .base import JOKER_REGISTRY, ScoreContext

# ── j_banner: +40 chips per remaining discard ────────────────────────────────
class _Banner:
    def on_hand_scored(self, inst, ctx):
        ctx.chips += 40 * ctx.discards_left
JOKER_REGISTRY["j_banner"] = _Banner()

# ── j_mystic_summit: +15 chips when discards_left == 0 ──────────────────────
class _MysticSummit:
    def on_hand_scored(self, inst, ctx):
        if ctx.discards_left == 0:
            ctx.chips += 15
JOKER_REGISTRY["j_mystic_summit"] = _MysticSummit()

# ── j_fibonacci: +8 chips for Aces, 2s, 3s, 5s, 8s ──────────────────────────
class _Fibonacci:
    def on_score_card(self, inst, card, ctx):
        if not card.debuffed and card.rank in [14, 2, 3, 5, 8]:
            ctx.chips += 8
JOKER_REGISTRY["j_fibonacci"] = _Fibonacci()

# ── j_scary_face: +30 chips per face card scored ────────────────────────────
class _ScaryFace:
    def on_score_card(self, inst, card, ctx):
        if card.is_face_card and not card.debuffed:
            ctx.chips += 30
JOKER_REGISTRY["j_scary_face"] = _ScaryFace()

# ── j_smiley: +5 chips per face card scored ─────────────────────────────────
class _Smiley:
    def on_score_card(self, inst, card, ctx):
        if card.is_face_card and not card.debuffed:
            ctx.chips += 5
JOKER_REGISTRY["j_smiley"] = _Smiley()

# ── j_misprint: random +0 to +23 chips ───────────────────────────────────────
class _Misprint:
    def on_hand_scored(self, inst, ctx):
        ctx.chips += inst.chance().randint(0, 23)
JOKER_REGISTRY["j_misprint"] = _Misprint()

# ── j_stuntman: +250 chips, -2 hand size ─────────────────────────────────────
class _Stuntman:
    def on_hand_scored(self, inst, ctx):
        ctx.chips += 250
    # TODO: hand_size reduction requires game state access
JOKER_REGISTRY["j_stuntman"] = _Stuntman()

# ── j_raised_fist: +50 chips if hand contains only cards from lowest rank ────
class _RaisedFist:
    def on_hand_scored(self, inst, ctx):
        if not ctx.scoring_cards:
            return
        ranks = {c.rank for c in ctx.scoring_cards if not c.debuffed}
        if len(ranks) == 1:  # All same rank
            ctx.chips += 50
JOKER_REGISTRY["j_raised_fist"] = _RaisedFist()

# ── j_dusk: retrigger all cards played in final hand of round ────────────────
# TODO: requires retrigger system

# ── j_loyalty_card: +4 mult per hand played, resets after 5 hands ───────────
# (This is actually mult, but included here for completeness)
class _LoyaltyCard:
    def on_hand_scored(self, inst, ctx):
        plays = inst.state.get("plays", 0)
        if plays < 5:
            ctx.mult += 4 * plays
            inst.state["plays"] = plays + 1
        else:
            inst.state["plays"] = 0  # Reset after 6th hand
JOKER_REGISTRY["j_loyalty_card"] = _LoyaltyCard()

# ── j_8_ball: 1 in 4 chance for +20 chips per 8 scored ──────────────────────
class _EightBall:
    def on_score_card(self, inst, card, ctx):
        if card.rank == 8 and not card.debuffed:
            if inst.chance().random() < 0.25:
                ctx.chips += 20
JOKER_REGISTRY["j_8_ball"] = _EightBall()

# ── j_droll: +30 chips, retrigger all odd cards ─────────────────────────────
class _Droll:
    def on_hand_scored(self, inst, ctx):
        ctx.chips += 30
    # TODO: retrigger system for odd ranks
JOKER_REGISTRY["j_droll"] = _Droll()

# ── j_half_joker: already in mult.py ─────────────────────────────────────────

# ── j_acrobat: +18 chips on final hand of round ─────────────────────────────
class _Acrobat:
    def on_hand_scored(self, inst, ctx):
        if ctx.hands_left == 0:
            ctx.chips += 18
JOKER_REGISTRY["j_acrobat"] = _Acrobat()

# ── j_hack: retrigger all 2,3,4,5 ───────────────────────────────────────────
# TODO: retrigger system

# ── j_stencil: +50 chips for each empty joker slot ──────────────────────────
class _Stencil:
    def on_hand_scored(self, inst, ctx):
        empty_slots = 5 - ctx.n_jokers
        ctx.chips += 50 * empty_slots
JOKER_REGISTRY["j_stencil"] = _Stencil()

# ── j_four_fingers: +10 chips, all Flushes and Straights can be made with 4 cards
class _FourFingers:
    def on_hand_scored(self, inst, ctx):
        ctx.chips += 10
    # TODO: hand eval modification
JOKER_REGISTRY["j_four_fingers"] = _FourFingers()

# ── j_mime: retrigger all held-in-hand card abilities ───────────────────────
# TODO: requires held_in_hand tracking

# ── j_credit_card: go up to -$20 in debt ────────────────────────────────────
# TODO: requires money system

# ── j_ceremonial: multiplies all jokers in shop ─────────────────────────────
# TODO: shop system

# ── j_banner already done above ──────────────────────────────────────────────

# ── j_mystic_summit already done above ───────────────────────────────────────

# ── j_marble: add Stone card to deck on blind select ────────────────────────
# TODO: deck modification system

# ── j_loyalty_card already done above ────────────────────────────────────────

# ── j_8_ball already done above ──────────────────────────────────────────────

# ── j_misprint already done above ────────────────────────────────────────────

# ── j_dusk: already stubbed above ────────────────────────────────────────────

# ── j_raised_fist already done above ─────────────────────────────────────────

# ── j_fibonacci already done above ───────────────────────────────────────────

# ── j_steel_joker: +0.2 mult per steel card ─────────────────────────────────
# (Actually mult, but included here for organization)
class _SteelJoker:
    def on_hand_scored(self, inst, ctx):
        steel_count = sum(1 for c in ctx.all_cards if c.enhancement == "Steel")
        ctx.mult += steel_count * 0.2
JOKER_REGISTRY["j_steel_joker"] = _SteelJoker()

# ── j_scary_face already done above ──────────────────────────────────────────

# ── j_abstract_joker: already in mult.py ─────────────────────────────────────

# ── j_delayed_grat: earn $2 per discard if no discards by end of round ──────
# TODO: round tracking

# ── j_pareidolia: all face cards are also considered Kings ──────────────────
# TODO: card eval modification

# ── j_gros_michel: +15 mult, 1 in 6 chance to be destroyed at end of round ──
class _GrosMichel:
    def on_hand_scored(self, inst, ctx):
        ctx.mult += 15
    def on_round_end(self, inst, ctx):
        if inst.chance().random() < 1/6:
            inst.state["destroyed"] = True  # Signal to remove this joker
JOKER_REGISTRY["j_gros_michel"] = _GrosMichel()

# ── j_cavendish: x3 Mult, 1 in 1000 chance of being destroyed at end of round
class _Cavendish:
    def on_hand_scored(self, inst, ctx):
        ctx.mult_mult *= 3
    def on_round_end(self, inst, ctx):
        if inst.chance().random() < 0.001:
            inst.state["destroyed"] = True
JOKER_REGISTRY["j_cavendish"] = _Cavendish()

# ── j_card_sharp: already in misc.py (tracks played hands this round) ───────

# ── j_red_card: already in economy.py ────────────────────────────────────────

# ── j_madness: x0.5 Mult, destroys random joker when Small/Big blind selected
# Gains x0.5 Mult each time. Very dangerous but powerful scaling.
class _Madness:
    def on_blind_selected(self, inst, ctx):
        # Only on Small/Big, not Boss
        inst.state["xmult"] = inst.state.get("xmult", 0.0) + 0.5
        inst.state["destroy_random"] = True  # game.py handles destruction
    def on_hand_scored(self, inst, ctx):
        xm = inst.state.get("xmult", 0.5)
        if xm > 0:
            ctx.mult_mult *= xm
JOKER_REGISTRY["j_madness"] = _Madness()

# ── j_square_joker: gains +4 chips if hand has exactly 4 cards ──────────────
class _SquareJoker:
    def on_hand_scored(self, inst, ctx):
        if len(ctx.scoring_cards) == 4:
            inst.state["chips"] = inst.state.get("chips", 0) + 4
        ctx.chips += inst.state.get("chips", 0)
JOKER_REGISTRY["j_square_joker"] = _SquareJoker()

# ── j_seance: if hand is Straight Flush, create random spectral card ────────
# TODO: consumable creation

# ── j_riff_raff: when blind selected, create 2 common jokers ────────────────
# TODO: joker creation

# ── j_vampire: remove enhancement from scored card, gain x0.1 xMult per card ─
class _Vampire:
    def on_score_card(self, inst, card, ctx):
        if card.enhancement and card.enhancement not in ("None", "Base") and not card.debuffed:
            inst.state["xmult"] = inst.state.get("xmult", 1.0) + 0.1
            card.enhancement = "None"
    def on_hand_scored(self, inst, ctx):
        xm = inst.state.get("xmult", 1.0)
        if xm > 1.0:
            ctx.mult_mult *= xm
JOKER_REGISTRY["j_vampire"] = _Vampire()

# ── j_shortcut: allows Straights to be made with gaps of 1 rank ─────────────
# TODO: hand eval modification

# ── j_hologram: x0.25 Mult per playing card added to deck ────────────────────
class _Hologram:
    def on_card_added(self, inst, ctx):
        inst.state["xmult"] = inst.state.get("xmult", 1.0) + 0.25
    def on_hand_scored(self, inst, ctx):
        xm = inst.state.get("xmult", 1.0)
        if xm > 1.0:
            ctx.mult_mult *= xm
JOKER_REGISTRY["j_hologram"] = _Hologram()

# ── j_vagabond: create Tarot if $4 or less when hand is played ───────────────
class _Vagabond:
    def on_hand_scored(self, inst, ctx):
        if ctx.dollars <= 4:
            ctx.pending_consumables.append("tarot")
JOKER_REGISTRY["j_vagabond"] = _Vagabond()

# ── j_cloud_9: +5 mult per 9 in full deck (max 1 per 9) ─────────────────────
# TODO: requires full deck access

# ── j_rocket: already in economy.py ──────────────────────────────────────────

# ── j_merry_andy: +3 discards, +1 mult per discard ──────────────────────────
# TODO: discard modification

# ── j_oops: doubles all listed probabilities ────────────────────────────────
# TODO: probability system

# ── j_idol: each rank of held scored card gives +2 mult, changes rank ───────
# TODO: requires held card tracking

# ── j_seeing_double: x2 mult if hand has Club and any other suit ────────────
class _SeeingDouble:
    def on_hand_scored(self, inst, ctx):
        suits = {c.suit for c in ctx.scoring_cards if not c.debuffed}
        if "Clubs" in suits and len(suits) > 1:
            ctx.mult_mult *= 2
JOKER_REGISTRY["j_seeing_double"] = _SeeingDouble()

# ── j_matador: earn $8 if triggered Boss Blind ability is blocked ───────────
# TODO: boss blind system

# ── j_hit_the_road: x0.5 xMult per Jack discarded this round ────────────────
class _HitTheRoad:
    def on_discard(self, inst, cards, ctx):
        for card in cards:
            if card.rank == 11:  # Jack
                inst.state["xmult"] = inst.state.get("xmult", 1.0) + 0.5
    def on_hand_scored(self, inst, ctx):
        xm = inst.state.get("xmult", 1.0)
        if xm > 1.0:
            ctx.mult_mult *= xm
    def on_round_end(self, inst, ctx):
        inst.state["xmult"] = 1.0  # reset each round
JOKER_REGISTRY["j_hit_the_road"] = _HitTheRoad()

# ── j_duo: +2 mult if hand contains a Pair ──────────────────────────────────
class _Duo:
    def on_hand_scored(self, inst, ctx):
        if "Pair" in ctx.hand_type or "Two Pair" in ctx.hand_type:
            ctx.mult += 2
JOKER_REGISTRY["j_duo"] = _Duo()

# ── j_trio: +4 mult if hand contains Three of a Kind ────────────────────────
class _Trio:
    def on_hand_scored(self, inst, ctx):
        if "Three" in ctx.hand_type:
            ctx.mult += 4
JOKER_REGISTRY["j_trio"] = _Trio()

# ── j_family: +8 mult if hand contains Four of a Kind ───────────────────────
class _Family:
    def on_hand_scored(self, inst, ctx):
        if "Four" in ctx.hand_type:
            ctx.mult += 8
JOKER_REGISTRY["j_family"] = _Family()

# ── j_order: +3 mult if hand is Straight ────────────────────────────────────
class _Order:
    def on_hand_scored(self, inst, ctx):
        if "Straight" in ctx.hand_type and "Flush" not in ctx.hand_type:
            ctx.mult += 3
JOKER_REGISTRY["j_order"] = _Order()

# ── j_tribe: +2 mult if hand is Flush ───────────────────────────────────────
class _Tribe:
    def on_hand_scored(self, inst, ctx):
        if "Flush" in ctx.hand_type and "Straight" not in ctx.hand_type:
            ctx.mult += 2
JOKER_REGISTRY["j_tribe"] = _Tribe()

# ── j_stuntman already done above ────────────────────────────────────────────

# ── j_invisible: after 2 rounds, sell this for random joker ─────────────────
# TODO: requires round counter

# ── j_brainstorm: copy leftmost joker ───────────────────────────────────────
# TODO: joker copying

# ── j_satellite: already in mult.py ──────────────────────────────────────────

# ── j_shoot_the_moon: +13 mult per Queen in hand ────────────────────────────
class _ShootTheMoon:
    def on_hand_scored(self, inst, ctx):
        queen_count = sum(1 for c in ctx.all_cards if c.rank == 12 and not c.debuffed)
        ctx.mult += 13 * queen_count
JOKER_REGISTRY["j_shoot_the_moon"] = _ShootTheMoon()

# ── j_drivers_license: x3 mult if you have >= 16 enhanced cards ─────────────
class _DriversLicense:
    def on_hand_scored(self, inst, ctx):
        enhanced = sum(1 for c in ctx.all_cards if c.enhancement and c.enhancement != "Base")
        if enhanced >= 16:
            ctx.mult_mult *= 3
JOKER_REGISTRY["j_drivers_license"] = _DriversLicense()

# ── j_cartomancer: create Tarot when blind selected ─────────────────────────
# TODO: consumable creation

# ── j_astronomer: upgrade all planet cards in shop ──────────────────────────
# TODO: shop system

# ── j_burnt: upgrade first discard of each round ────────────────────────────
# TODO: consumable system

# ── j_bootstraps: +2 mult per $5 held (max $50) ─────────────────────────────
class _Bootstraps:
    def on_hand_scored(self, inst, ctx):
        bonus = min(ctx.dollars // 5, 10) * 2
        ctx.mult += bonus
JOKER_REGISTRY["j_bootstraps"] = _Bootstraps()

# ── j_caino: x1 Mult, gains x0.1 when a face card is destroyed ──────────────
class _Caino:
    def on_card_destroyed(self, inst, card, ctx):
        if card.is_face_card:
            inst.state["xmult"] = inst.state.get("xmult", 1.0) + 0.1
    def on_hand_scored(self, inst, ctx):
        ctx.mult_mult *= inst.state.get("xmult", 1.0)
JOKER_REGISTRY["j_caino"] = _Caino()

# ── j_triboulet: x2 mult per King or Queen scored ───────────────────────────
class _Triboulet:
    def on_score_card(self, inst, card, ctx):
        if card.rank in [12, 13] and not card.debuffed:  # Queen or King
            ctx.mult_mult *= 2
JOKER_REGISTRY["j_triboulet"] = _Triboulet()

# ── j_yorick: x1 Mult, gains x1 per 23 cards discarded ──────────────────────
class _Yorick:
    def on_discard(self, inst, cards, ctx):
        inst.state["discarded"] = inst.state.get("discarded", 0) + len(cards)
    def on_hand_scored(self, inst, ctx):
        sets = inst.state.get("discarded", 0) // 23
        ctx.mult_mult *= (1.0 + sets)
JOKER_REGISTRY["j_yorick"] = _Yorick()

# ── j_chicot: disables all Boss Blind effects ───────────────────────────────
# TODO: boss blind system

# ── j_perkeo: create negative copy of random consumable at end of shop ──────
# TODO: consumable system
