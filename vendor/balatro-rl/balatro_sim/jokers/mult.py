"""
mult.py — Additive mult jokers and xMult jokers.
"""
from .base import JOKER_REGISTRY, ScoreContext, JokerEffect, register_joker

# ── Helpers ──────────────────────────────────────────────────────────────────

def _has_hand(hand_type, *targets):
    return hand_type in targets

def _all_suits(cards):
    suits = {c.suit for c in cards if not c.debuffed and c.enhancement != "Stone"}
    return suits

@register_joker("j_joker")
class _Joker(JokerEffect):
    def on_hand_scored(self, inst, ctx):
        ctx.mult += 4

@register_joker("j_jolly")
class _Jolly(JokerEffect):
    def on_hand_scored(self, inst, ctx):
        if _has_hand(ctx.hand_type, "Pair", "Two Pair", "Full House", "Four of a Kind", "Five of a Kind", "Flush House"):
            ctx.mult += 8

@register_joker("j_zany")
class _Zany(JokerEffect):
    def on_hand_scored(self, inst, ctx):
        if _has_hand(ctx.hand_type, "Three of a Kind", "Full House", "Five of a Kind", "Flush House"):
            ctx.mult += 12

@register_joker("j_mad")
class _Mad(JokerEffect):
    def on_hand_scored(self, inst, ctx):
        if _has_hand(ctx.hand_type, "Two Pair", "Full House"):
            ctx.mult += 10

@register_joker("j_crazy")
class _Crazy(JokerEffect):
    def on_hand_scored(self, inst, ctx):
        if _has_hand(ctx.hand_type, "Straight", "Straight Flush"):
            ctx.mult += 12

@register_joker("j_droll")
class _Droll(JokerEffect):
    def on_hand_scored(self, inst, ctx):
        if _has_hand(ctx.hand_type, "Flush", "Straight Flush", "Flush House", "Flush Five"):
            ctx.mult += 10

@register_joker("j_half")
class _Half(JokerEffect):
    def on_hand_scored(self, inst, ctx):
        if len(ctx.scoring_cards) <= 3:
            ctx.mult += 20

@register_joker("j_abstract")
class _Abstract(JokerEffect):
    def on_hand_scored(self, inst, ctx):
        ctx.mult += 3 * ctx.n_jokers

@register_joker("j_banner")
class _Banner(JokerEffect):
    def on_hand_scored(self, inst, ctx):
        ctx.chips += 30 * ctx.discards_left

@register_joker("j_mystic_summit")
class _MysticSummit(JokerEffect):
    def on_hand_scored(self, inst, ctx):
        if ctx.discards_left == 0:
            ctx.mult += 15

@register_joker("j_misprint")
class _Misprint(JokerEffect):
    def on_hand_scored(self, inst, ctx):
        ctx.mult += inst.chance().randint(0, 23)

@register_joker("j_raised_fist")
class _RaisedFist(JokerEffect):
    def on_hand_scored(self, inst, ctx):
        active = [c for c in ctx.held_cards
                  if not c.debuffed and c.enhancement != "Stone"]
        if active:
            lowest = min(c.rank for c in active)
            ctx.mult += 2 * lowest

@register_joker("j_fibonacci")
class _Fibonacci(JokerEffect):
    FIB = {14, 2, 3, 5, 8}
    def on_score_card(self, inst, card, ctx):
        if card.rank in self.FIB and not card.debuffed:
            ctx.mult += 8

@register_joker("j_smiley")
class _Smiley(JokerEffect):
    def on_score_card(self, inst, card, ctx):
        if card.is_face_card and not card.debuffed:
            ctx.mult += 5

@register_joker("j_shoot_the_moon")
class _ShootTheMoon(JokerEffect):
    def on_hand_scored(self, inst, ctx):
        queens = sum(1 for c in ctx.held_cards if c.rank == 12 and not c.debuffed)
        ctx.mult += 13 * queens

@register_joker("j_walkie_talkie")
class _WalkieTalkie(JokerEffect):
    def on_score_card(self, inst, card, ctx):
        if card.rank in (4, 10) and not card.debuffed:
            ctx.chips += 10
            ctx.mult += 4

@register_joker("j_bootstraps")
class _Bootstraps(JokerEffect):
    def on_hand_scored(self, inst, ctx):
        ctx.mult += 2 * (ctx.dollars // 5)

@register_joker("j_photograph")
class _Photograph(JokerEffect):
    def on_score_card(self, inst, card, ctx):
        if card.is_face_card and not card.debuffed and not inst.state.get("fired"):
            inst.state["fired"] = True
            ctx.mult_mult *= 2
    def on_round_end(self, inst, ctx):
        inst.state["fired"] = False

@register_joker("j_acrobat")
class _Acrobat(JokerEffect):
    def on_hand_scored(self, inst, ctx):
        if ctx.hands_left == 0:
            ctx.mult_mult *= 3

# ── xMult jokers (The Duo, Trio, etc.) — registered under the CANONICAL
# keys the shop sells (j_duo...j_tribe); the old j_the_* spellings were dead.
@register_joker("j_duo")
class _TheDuo(JokerEffect):
    def on_hand_scored(self, inst, ctx):
        if _has_hand(ctx.hand_type, "Pair", "Two Pair", "Full House", "Four of a Kind", "Five of a Kind", "Flush House"):
            ctx.mult_mult *= 2

@register_joker("j_trio")
class _TheTrio(JokerEffect):
    def on_hand_scored(self, inst, ctx):
        if _has_hand(ctx.hand_type, "Three of a Kind", "Full House", "Five of a Kind", "Flush House"):
            ctx.mult_mult *= 3

@register_joker("j_family")
class _TheFamily(JokerEffect):
    def on_hand_scored(self, inst, ctx):
        if _has_hand(ctx.hand_type, "Four of a Kind", "Five of a Kind"):
            ctx.mult_mult *= 4

@register_joker("j_order")
class _TheOrder(JokerEffect):
    def on_hand_scored(self, inst, ctx):
        if _has_hand(ctx.hand_type, "Straight", "Straight Flush"):
            ctx.mult_mult *= 3

@register_joker("j_tribe")
class _TheTribe(JokerEffect):
    def on_hand_scored(self, inst, ctx):
        if _has_hand(ctx.hand_type, "Flush", "Straight Flush", "Flush House", "Flush Five"):
            ctx.mult_mult *= 2

@register_joker("j_stencil")
class _Stencil(JokerEffect):
    MAX_SLOTS = 5
    def on_hand_scored(self, inst, ctx):
        empty = max(0, self.MAX_SLOTS - ctx.n_jokers)
        ctx.mult_mult *= max(1, empty)

@register_joker("j_triboulet")
class _Triboulet(JokerEffect):
    def on_score_card(self, inst, card, ctx):
        if card.rank in (12, 13) and not card.debuffed:
            ctx.mult_mult *= 2

@register_joker("j_seeing_double")
class _SeeingDouble(JokerEffect):
    def on_hand_scored(self, inst, ctx):
        suits = _all_suits(ctx.scoring_cards)
        if "Clubs" in suits and len(suits) >= 2:
            ctx.mult_mult *= 2

@register_joker("j_loyalty_card")
class _LoyaltyCard(JokerEffect):
    def on_hand_scored(self, inst, ctx):
        inst.state.setdefault("count", 0)
        inst.state["count"] += 1
        if inst.state["count"] % 6 == 0:
            ctx.mult_mult *= 4

@register_joker("j_bloodstone")
class _Bloodstone(JokerEffect):
    def on_score_card(self, inst, card, ctx):
        if card.suit == "Hearts" and not card.debuffed and inst.chance().random() < 0.5:
            ctx.mult_mult *= 1.5

# Suit chosen randomly on creation (stored in state)
@register_joker("j_ancient")
class _Ancient(JokerEffect):
    SUITS = ["Spades", "Hearts", "Clubs", "Diamonds"]
    def on_score_card(self, inst, card, ctx):
        suit = inst.state.get("suit") or inst.chance().choice(self.SUITS)
        inst.state["suit"] = suit
        if card.suit == suit and not card.debuffed:
            ctx.mult_mult *= 1.5

@register_joker("j_throwback")
class _Throwback(JokerEffect):
    def on_hand_scored(self, inst, ctx):
        bonus = inst.state.get("bonus", 1.0)
        ctx.mult_mult *= bonus
    def on_blind_skipped(self, inst, ctx):
        inst.state["bonus"] = inst.state.get("bonus", 1.0) + 0.25

# Card chosen randomly (rank+suit), changes each round
@register_joker("j_the_idol")
class _TheIdol(JokerEffect):
    def on_hand_scored(self, inst, ctx):
        target_rank = inst.state.get("rank", 14)
        target_suit = inst.state.get("suit", "Spades")
        match = any(c.rank == target_rank and c.suit == target_suit
                    for c in ctx.scoring_cards if not c.debuffed)
        if match:
            ctx.mult_mult *= 2
    def on_round_end(self, inst, ctx):
        inst.state["rank"] = inst.chance().randint(2, 14)
        inst.state["suit"] = inst.chance().choice(["Spades", "Hearts", "Clubs", "Diamonds"])

@register_joker("j_space_joker")
class _SpaceJoker(JokerEffect):
    def on_hand_scored(self, inst, ctx):
        if inst.chance().random() < 0.25:
            ctx.planet_levels[ctx.hand_type] = ctx.planet_levels.get(ctx.hand_type, 1) + 1

@register_joker("j_supernova")
class _Supernova(JokerEffect):
    def on_hand_scored(self, inst, ctx):
        if inst.game is not None:
            ctx.mult += inst.game.run_hand_counts.get(ctx.hand_type, 0)
