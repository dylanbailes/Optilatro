"""
chips.py — Flat chip bonus jokers.
These add chips in various ways.
"""
from .base import JOKER_REGISTRY, ScoreContext, JokerEffect, register_joker

@register_joker("j_scary_face")
class _ScaryFace(JokerEffect):
    def on_score_card(self, inst, card, ctx):
        if card.is_face_card and not card.debuffed:
            ctx.chips += 30

@register_joker("j_stuntman")
class _Stuntman(JokerEffect):
    """+250 chips, -2 hand size — hand size is a passive (R3), so game
    applies it at blind start without a key scan."""
    def on_hand_scored(self, inst, ctx):
        ctx.chips += 250
    def passives(self, inst) -> dict:
        return {"hand_size": -2}

@register_joker("j_gros_michel")
class _GrosMichel(JokerEffect):
    def on_hand_scored(self, inst, ctx):
        ctx.mult += 15
    def on_round_end(self, inst, ctx):
        if inst.chance().random() < 1/6:
            inst.state["destroyed"] = True  # Signal to remove this joker

@register_joker("j_cavendish")
class _Cavendish(JokerEffect):
    def on_hand_scored(self, inst, ctx):
        ctx.mult_mult *= 3
    def on_round_end(self, inst, ctx):
        if inst.chance().random() < 0.001:
            inst.state["destroyed"] = True

# destroys a random Joker when a Small or Big Blind is selected (Boss blinds
# never trigger either — real game). Starts at X1, not X0.5.
@register_joker("j_madness")
class _Madness(JokerEffect):
    state_defaults = {"blinds": 0}
    def on_blind_selected(self, inst, ctx):
        game = inst.game
        if game is not None and game.current_blind.kind == "Boss":
            return
        inst.state["blinds"] = inst.state.get("blinds", 0) + 1
        inst.state["destroy_random"] = True  # game.py destroys a random other joker
    def on_hand_scored(self, inst, ctx):
        xm = 1.0 + 0.5 * inst.state.get("blinds", 0)
        if xm > 1.0:
            ctx.mult_mult *= xm

@register_joker("j_square_joker")
class _SquareJoker(JokerEffect):
    state_defaults = {"chips": 0}
    def on_hand_scored(self, inst, ctx):
        if len(ctx.scoring_cards) == 4:
            inst.state["chips"] = inst.state.get("chips", 0) + 4
        ctx.chips += inst.state.get("chips", 0)

@register_joker("j_vampire")
class _Vampire(JokerEffect):
    state_defaults = {"xmult": 1.0}
    def on_score_card(self, inst, card, ctx):
        if card.enhancement and card.enhancement not in ("None", "Base") and not card.debuffed:
            inst.state["xmult"] = inst.state.get("xmult", 1.0) + 0.1
            card.enhancement = "None"
    def on_hand_scored(self, inst, ctx):
        xm = inst.state.get("xmult", 1.0)
        if xm > 1.0:
            ctx.mult_mult *= xm

@register_joker("j_hologram")
class _Hologram(JokerEffect):
    state_defaults = {"xmult": 1.0}
    def on_card_added(self, inst, ctx):
        inst.state["xmult"] = inst.state.get("xmult", 1.0) + 0.25
    def on_hand_scored(self, inst, ctx):
        xm = inst.state.get("xmult", 1.0)
        if xm > 1.0:
            ctx.mult_mult *= xm

@register_joker("j_vagabond")
class _Vagabond(JokerEffect):
    def on_hand_scored(self, inst, ctx):
        if ctx.dollars <= 4:
            from ..consumables import ALL_TAROTS
            ctx.pending_consumables.append(inst.chance().choice(ALL_TAROTS))

@register_joker("j_hit_the_road")
class _HitTheRoad(JokerEffect):
    state_defaults = {"xmult": 1.0}
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

@register_joker("j_caino")
class _Caino(JokerEffect):
    state_defaults = {"xmult": 1.0}
    def on_card_destroyed(self, inst, card, ctx):
        if card.is_face_card:
            inst.state["xmult"] = inst.state.get("xmult", 1.0) + 0.1
    def on_hand_scored(self, inst, ctx):
        ctx.mult_mult *= inst.state.get("xmult", 1.0)

@register_joker("j_yorick")
class _Yorick(JokerEffect):
    state_defaults = {"discarded": 0}
    def on_discard(self, inst, cards, ctx):
        inst.state["discarded"] = inst.state.get("discarded", 0) + len(cards)
    def on_hand_scored(self, inst, ctx):
        sets = inst.state.get("discarded", 0) // 23
        ctx.mult_mult *= (1.0 + sets)
