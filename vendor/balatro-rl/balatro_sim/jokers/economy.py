"""
economy.py — Money-generating jokers.
These fire primarily on round_end to give dollars.
"""
from .base import JOKER_REGISTRY, ScoreContext

# ── j_golden: earn $4 at end of round ────────────────────────────────────────
class _Golden:
    def on_round_end(self, inst, ctx):
        inst.state["pending_money"] = inst.state.get("pending_money", 0) + 4
JOKER_REGISTRY["j_golden"] = _Golden()

# ── j_to_the_moon: +$1 interest per $5 held (extra interest) ─────────────────
# Note: on_round_end receives ctx=None, so we track dollars via joker state
class _ToTheMoon:
    def on_hand_scored(self, inst, ctx):
        inst.state["dollars"] = ctx.dollars  # track for round_end
    def on_round_end(self, inst, ctx):
        dollars = inst.state.get("dollars", 0)
        extra = dollars // 5
        inst.state["pending_money"] = inst.state.get("pending_money", 0) + extra
JOKER_REGISTRY["j_to_the_moon"] = _ToTheMoon()

# ── j_business_card: face cards have 1 in 2 chance of giving $2 ──────────────
class _BusinessCard:
    def on_score_card(self, inst, card, ctx):
        if card.is_face_card and not card.debuffed and inst.chance().random() < 0.5:
            inst.state["pending_money"] = inst.state.get("pending_money", 0) + 2
JOKER_REGISTRY["j_business_card"] = _BusinessCard()

# ── j_reserved_parking: face cards have 1 in 2 chance of giving $1 ──────────
class _ReservedParking:
    def on_score_card(self, inst, card, ctx):
        if card.is_face_card and not card.debuffed and inst.chance().random() < 0.5:
            inst.state["pending_money"] = inst.state.get("pending_money", 0) + 1
JOKER_REGISTRY["j_reserved_parking"] = _ReservedParking()

# ── j_satellite: earn $1 per unique Planet used this run (defined in mult.py) ─

# ── j_golden_ticket: played Gold card gives $4 ───────────────────────────────
class _GoldenTicket:
    def on_score_card(self, inst, card, ctx):
        if card.enhancement == "Gold" and not card.debuffed:
            inst.state["pending_money"] = inst.state.get("pending_money", 0) + 4
JOKER_REGISTRY["j_golden_ticket"] = _GoldenTicket()

# ── j_rocket: earn $1 per round, +$2 when boss blind beaten ──────────────────
class _Rocket:
    def on_round_end(self, inst, ctx):
        bonus = inst.state.get("bonus", 1)
        inst.state["pending_money"] = inst.state.get("pending_money", 0) + bonus
    def on_boss_beaten(self, inst, ctx):
        inst.state["bonus"] = inst.state.get("bonus", 1) + 2
JOKER_REGISTRY["j_rocket"] = _Rocket()

# ── j_lucky_joker: +20 mult each time Lucky card triggers ────────────────────
# Note: this is in economy because it has a $ component in some versions
# Actually j_lucky_joker: +20 mult per lucky trigger — this is mult. Put here for completeness.
class _LuckyJoker:
    def on_lucky_trigger(self, inst, ctx):
        ctx.mult += 20
JOKER_REGISTRY["j_lucky_joker"] = _LuckyJoker()

# ── j_gift_card: +$1 to every Joker in shop at end of round ──────────────────
# TODO: requires shop state access

# ── j_chaos: free reroll in shop ──────────────────────────────────────────────
# TODO: shop system

# ── j_red_card: +3 Mult permanently when any Booster Pack is skipped ─────────
class _RedCard:
    def on_booster_skipped(self, inst, ctx):
        inst.state["mult"] = inst.state.get("mult", 0) + 3
    def on_hand_scored(self, inst, ctx):
        ctx.mult += inst.state.get("mult", 0)
JOKER_REGISTRY["j_red_card"] = _RedCard()

# ── j_odd_todd: +31 chips per played card with odd rank (A,9,7,5,3) ──────────
class _OddTodd:
    ODD_RANKS = {14, 9, 7, 5, 3}  # A=14, 9, 7, 5, 3
    def on_score_card(self, inst, card, ctx):
        if card.rank in self.ODD_RANKS and not card.debuffed:
            ctx.chips += 31
JOKER_REGISTRY["j_odd_todd"] = _OddTodd()

# ── j_scholar: +20 chips and +4 mult if Ace is scored ────────────────────────
class _Scholar:
    def on_score_card(self, inst, card, ctx):
        if card.rank == 14 and not card.debuffed:
            ctx.chips += 20
            ctx.mult += 4
JOKER_REGISTRY["j_scholar"] = _Scholar()

# ── j_even_steven: +4 mult if scored card is even rank ───────────────────────
class _EvenSteven:
    def on_score_card(self, inst, card, ctx):
        if card.rank % 2 == 0 and not card.debuffed:
            ctx.mult += 4
JOKER_REGISTRY["j_even_steven"] = _EvenSteven()

# ── j_odd_todd (chips per odd card) already done above ───────────────────────

# ── j_spare_trousers: already in scaling.py ──────────────────────────────────
