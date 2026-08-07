"""
economy.py — Money-generating jokers.
These fire primarily on round_end to give dollars.
"""
from .base import JOKER_REGISTRY, ScoreContext, JokerEffect, register_joker

@register_joker("j_golden")
class _Golden(JokerEffect):
    def on_round_end(self, inst, ctx):
        inst.state["pending_money"] = inst.state.get("pending_money", 0) + 4

# Note: on_round_end receives ctx=None, so we track dollars via joker state
@register_joker("j_to_the_moon")
class _ToTheMoon(JokerEffect):
    def on_hand_scored(self, inst, ctx):
        inst.state["dollars"] = ctx.dollars  # track for round_end
    def on_round_end(self, inst, ctx):
        dollars = inst.state.get("dollars", 0)
        extra = dollars // 5
        inst.state["pending_money"] = inst.state.get("pending_money", 0) + extra

@register_joker("j_business_card")
class _BusinessCard(JokerEffect):
    def on_score_card(self, inst, card, ctx):
        if card.is_face_card and not card.debuffed and inst.chance().random() < 0.5:
            inst.state["pending_money"] = inst.state.get("pending_money", 0) + 2

@register_joker("j_golden_ticket")
class _GoldenTicket(JokerEffect):
    def on_score_card(self, inst, card, ctx):
        if card.enhancement == "Gold" and not card.debuffed:
            inst.state["pending_money"] = inst.state.get("pending_money", 0) + 4

@register_joker("j_rocket")
class _Rocket(JokerEffect):
    def on_round_end(self, inst, ctx):
        bonus = inst.state.get("bonus", 1)
        inst.state["pending_money"] = inst.state.get("pending_money", 0) + bonus
    def on_boss_beaten(self, inst, ctx):
        inst.state["bonus"] = inst.state.get("bonus", 1) + 2

@register_joker("j_red_card")
class _RedCard(JokerEffect):
    def on_booster_skipped(self, inst, ctx):
        inst.state["mult"] = inst.state.get("mult", 0) + 3
    def on_hand_scored(self, inst, ctx):
        ctx.mult += inst.state.get("mult", 0)

@register_joker("j_odd_todd")
class _OddTodd(JokerEffect):
    ODD_RANKS = {14, 9, 7, 5, 3}  # A=14, 9, 7, 5, 3
    def on_score_card(self, inst, card, ctx):
        if card.rank in self.ODD_RANKS and not card.debuffed:
            ctx.chips += 31

@register_joker("j_scholar")
class _Scholar(JokerEffect):
    def on_score_card(self, inst, card, ctx):
        if card.rank == 14 and not card.debuffed:
            ctx.chips += 20
            ctx.mult += 4

@register_joker("j_even_steven")
class _EvenSteven(JokerEffect):
    def on_score_card(self, inst, card, ctx):
        if card.rank % 2 == 0 and not card.debuffed:
            ctx.mult += 4
