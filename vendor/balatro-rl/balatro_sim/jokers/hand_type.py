"""
hand_type.py — Jokers that modify or respond to poker hand types.

The hand-type chip/mult bonuses (Sly/Wily/Clever/Devious/Crafty, the +Mult
Pair/Three/TwoPair/Straight/Flush set, and the xMult Duo family) live in
scaling.py and mult.py under their canonical keys.
"""
from .base import JOKER_REGISTRY, ScoreContext, JokerEffect, register_joker


# ── j_mail_in_rebate: earn $3 per discarded rank, one rank per round ─────────
@register_joker("j_mail_in_rebate")
class _MailInRebate(JokerEffect):
    def on_discard(self, inst, cards, ctx):
        for card in cards:
            if "rebate_rank" not in inst.state:
                inst.state["rebate_rank"] = card.rank
                inst.state["pending_money"] = inst.state.get("pending_money", 0) + 3
