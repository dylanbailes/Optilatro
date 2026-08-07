"""
scaling.py — Jokers that gain permanent stat increases over time.
These build state across multiple hands/rounds.
"""
from .base import JOKER_REGISTRY, ScoreContext, JokerEffect, register_joker, full_deck

@register_joker("j_greedy_joker")
class _Greedy(JokerEffect):
    def on_score_card(self, inst, card, ctx):
        if card.suit == "Diamonds" and not card.debuffed:
            ctx.mult += 3

@register_joker("j_lusty_joker")
class _Lusty(JokerEffect):
    def on_score_card(self, inst, card, ctx):
        if card.suit == "Hearts" and not card.debuffed:
            ctx.mult += 3

@register_joker("j_wrathful_joker")
class _Wrathful(JokerEffect):
    def on_score_card(self, inst, card, ctx):
        if card.suit == "Spades" and not card.debuffed:
            ctx.mult += 3

@register_joker("j_gluttonous_joker")
class _Gluttonous(JokerEffect):
    def on_score_card(self, inst, card, ctx):
        if card.suit == "Clubs" and not card.debuffed:
            ctx.mult += 3

# Multiplicative, keyed to the FULL run deck (base.full_deck = deck + hand +
# spent — the persistent pool, not just the played hand). Requires a live
# game; direct-call tests without one get no bonus.
@register_joker("j_steel_joker")
class _SteelJoker(JokerEffect):
    def on_hand_scored(self, inst, ctx):
        steel = sum(1 for c in full_deck(inst.game) if c.enhancement == "Steel")
        if steel:
            ctx.mult_mult *= (1.0 + 0.2 * steel)

_PAIR_TYPES = {"Pair", "Two Pair", "Full House", "Four of a Kind", "Five of a Kind", "Flush House", "Flush Five"}
@register_joker("j_sly")
class _Sly(JokerEffect):
    def on_hand_scored(self, inst, ctx):
        if ctx.hand_type in _PAIR_TYPES:
            ctx.chips += 50

@register_joker("j_wily")
class _Wily(JokerEffect):
    def on_hand_scored(self, inst, ctx):
        if "Three" in ctx.hand_type:
            ctx.chips += 100

@register_joker("j_clever")
class _Clever(JokerEffect):
    def on_hand_scored(self, inst, ctx):
        if "Two Pair" in ctx.hand_type:
            ctx.chips += 80

@register_joker("j_devious")
class _Devious(JokerEffect):
    def on_hand_scored(self, inst, ctx):
        if "Straight" in ctx.hand_type:  # includes Straight Flush
            ctx.chips += 100

@register_joker("j_crafty")
class _Crafty(JokerEffect):
    def on_hand_scored(self, inst, ctx):
        if "Flush" in ctx.hand_type:  # includes Straight Flush, Flush House, Flush Five
            ctx.chips += 80

@register_joker("j_green_joker")
class _GreenJoker(JokerEffect):
    def on_hand_scored(self, inst, ctx):
        inst.state["mult"] = inst.state.get("mult", 0) + 1
        ctx.mult += inst.state.get("mult", 0)
    def on_discard(self, inst, cards, ctx):
        inst.state["mult"] = max(0, inst.state.get("mult", 0) - 1)

@register_joker("j_bull")
class _Bull(JokerEffect):
    def on_hand_scored(self, inst, ctx):
        ctx.chips += 2 * ctx.dollars

@register_joker("j_popcorn")
class _Popcorn(JokerEffect):
    """+20 Mult, -4 per round until destroyed at 0 (real game)."""
    state_defaults = {"mult": 20}
    def on_init(self, inst):
        inst.state["mult"] = 20
    def on_hand_scored(self, inst, ctx):
        ctx.mult += inst.state.get("mult", 20)
    def on_round_end(self, inst, ctx):
        inst.state["mult"] = max(0, inst.state.get("mult", 20) - 4)
        if inst.state["mult"] == 0:
            inst.state["destroyed"] = True

@register_joker("j_ramen")
class _Ramen(JokerEffect):
    """X2 Mult, -X0.01 per card discarded until it self-destructs at X1."""
    state_defaults = {"mult": 2.0}
    def on_init(self, inst):
        inst.state["mult"] = 2.0
    def on_hand_scored(self, inst, ctx):
        ctx.mult_mult *= inst.state.get("mult", 2.0)
    def on_discard(self, inst, cards, ctx):
        inst.state["mult"] = max(1.0, inst.state.get("mult", 2.0) - 0.01 * len(cards))
        if inst.state["mult"] <= 1.0:
            inst.state["destroyed"] = True

@register_joker("j_castle")
class _Castle(JokerEffect):
    """+3 chips per discarded card of the chosen suit; suit rotates each round.
    Chips are permanent (scaling joker); suit is lazy-picked on first discard
    so the joker works from round 1 even before on_init dispatches."""
    state_defaults = {"chips": 0}
    def __init__(self):
        self.suits = ["Clubs", "Diamonds", "Hearts", "Spades"]
    def on_init(self, inst):
        inst.state["suit"] = inst.chance().choice(self.suits)
    def _suit(self, inst):
        suit = inst.state.get("suit")
        if suit is None:
            suit = inst.chance().choice(self.suits)
            inst.state["suit"] = suit
        return suit
    def on_discard(self, inst, cards, ctx):
        suit = self._suit(inst)
        for card in cards:
            if card.suit == suit:
                inst.state["chips"] = inst.state.get("chips", 0) + 3
    def on_hand_scored(self, inst, ctx):
        ctx.chips += inst.state.get("chips", 0)
    def on_round_end(self, inst, ctx):
        inst.state["suit"] = inst.chance().choice(self.suits)

# X0.25 Mult per joker sold — resets when a Boss Blind is defeated.
# Dispatch: on_other_sold after each sale; on_boss_beaten from _end_round.
@register_joker("j_campfire")
class _Campfire(JokerEffect):
    def on_hand_scored(self, inst, ctx):
        xm = 1.0 + inst.state.get("sold", 0) * 0.25
        ctx.mult_mult *= xm
    def on_other_sold(self, inst, ctx):
        inst.state["sold"] = inst.state.get("sold", 0) + 1
    def on_boss_beaten(self, inst, ctx):
        inst.state["sold"] = 0  # reset on boss defeat

@register_joker("j_rough_gem")
class _RoughGem(JokerEffect):
    def on_score_card(self, inst, card, ctx):
        if card.suit == "Diamonds" and not card.debuffed:
            ctx.pending_money += 1

@register_joker("j_arrowhead")
class _Arrowhead(JokerEffect):
    def on_score_card(self, inst, card, ctx):
        if card.suit == "Spades" and not card.debuffed:
            ctx.chips += 50

@register_joker("j_onyx_agate")
class _OnyxAgate(JokerEffect):
    def on_score_card(self, inst, card, ctx):
        if card.suit == "Clubs" and not card.debuffed:
            ctx.mult += 7

@register_joker("j_glass_joker")
class _GlassJoker(JokerEffect):
    def on_hand_scored(self, inst, ctx):
        glass_count = sum(1 for c in full_deck(inst.game) if c.enhancement == "Glass")
        if glass_count > 0:
            ctx.mult_mult *= (1.0 + 0.75 * glass_count)

# Real j_flower_pot checks context.scoring_hand (the scoring cards), not the
# full played hand.
@register_joker("j_flower_pot")
class _FlowerPot(JokerEffect):
    def on_hand_scored(self, inst, ctx):
        suits = {c.suit for c in ctx.scoring_cards if not c.debuffed}
        if len(suits) == 4:
            ctx.mult_mult *= 3

@register_joker("j_obelisk")
class _Obelisk(JokerEffect):
    def on_hand_scored(self, inst, ctx):
        counts = inst.state.setdefault("counts", {})
        counts[ctx.hand_type] = counts.get(ctx.hand_type, 0) + 1
        most_played = max(counts, key=counts.get)
        if ctx.hand_type != most_played:
            inst.state["streak"] = inst.state.get("streak", 0) + 1
        else:
            inst.state["streak"] = 0
        xm = 1.0 + inst.state.get("streak", 0) * 0.2
        ctx.mult_mult *= xm

@register_joker("j_erosion")
class _Erosion(JokerEffect):
    def on_hand_scored(self, inst, ctx):
        missing = max(0, 52 - ctx.deck_remaining)
        ctx.mult += 4 * missing

@register_joker("j_fortune_teller")
class _FortuneTeller(JokerEffect):
    def on_tarot_used(self, inst, ctx):
        inst.state["mult"] = inst.state.get("mult", 0) + 1
    def on_hand_scored(self, inst, ctx):
        ctx.mult += inst.state.get("mult", 0)

@register_joker("j_lucky_cat")
class _LuckyCat(JokerEffect):
    def on_lucky_trigger(self, inst, ctx):
        inst.state["xmult"] = inst.state.get("xmult", 1.0) + 0.25
    def on_hand_scored(self, inst, ctx):
        xm = inst.state.get("xmult", 1.0)
        if xm > 1.0:
            ctx.mult_mult *= xm

@register_joker("j_baseball")
class _Baseball(JokerEffect):
    def on_hand_scored(self, inst, ctx):
        from ..shop import JOKER_CATALOGUE
        for j in ctx.jokers:
            meta = JOKER_CATALOGUE.get(j.key, {})
            if meta.get("rarity") == "Uncommon":
                ctx.mult_mult *= 1.5

@register_joker("j_spare_trousers")
class _SpareTrousers(JokerEffect):
    def on_hand_scored(self, inst, ctx):
        if "Two Pair" in ctx.hand_type:
            inst.state["mult"] = inst.state.get("mult", 0) + 2
        ctx.mult += inst.state.get("mult", 0)

@register_joker("j_ticket")
class _Ticket(JokerEffect):
    def on_hand_scored(self, inst, ctx):
        gold_played = inst.state.get("gold_played", 0)
        if gold_played < 5:
            ctx.chips += 3 * (ctx.dollars // 10)
    def on_score_card(self, inst, card, ctx):
        if card.enhancement == "Gold" and not card.debuffed:
            inst.state["gold_played"] = inst.state.get("gold_played", 0) + 1

# Real Balatro: game-state modifier, not a scoring joker. Gives extra hands
# but removes all discards. Applied via on_blind_selected hook in game.py.
@register_joker("j_burglar")
class _Burglar(JokerEffect):
    def on_blind_selected(self, inst, ctx):
        inst.state["extra_hands"] = 3
        inst.state["zero_discards"] = True

@register_joker("j_blackboard")
class _Blackboard(JokerEffect):
    def on_hand_scored(self, inst, ctx):
        held = [c for c in ctx.held_cards if not c.debuffed]
        if held and all(c.suit in ("Spades", "Clubs") for c in held):
            ctx.mult_mult *= 3

@register_joker("j_runner")
class _Runner(JokerEffect):
    def on_hand_scored(self, inst, ctx):
        if "Straight" in ctx.hand_type:
            inst.state["chips"] = inst.state.get("chips", 0) + 15
        ctx.chips += inst.state.get("chips", 0)

@register_joker("j_ice_cream")
class _IceCream(JokerEffect):
    """+100 chips, -5 per hand until destroyed at 0 (real game)."""
    state_defaults = {"chips": 100}
    def on_init(self, inst):
        inst.state["chips"] = 100
    def on_hand_scored(self, inst, ctx):
        ctx.chips += inst.state.get("chips", 100)
        inst.state["chips"] = max(0, inst.state.get("chips", 100) - 5)
        if inst.state["chips"] == 0:
            inst.state["destroyed"] = True

@register_joker("j_blue_joker")
class _BlueJoker(JokerEffect):
    def on_hand_scored(self, inst, ctx):
        ctx.chips += 2 * ctx.deck_remaining

@register_joker("j_constellation")
class _Constellation(JokerEffect):
    def on_planet_used(self, inst, planet_name):
        inst.state["mult"] = inst.state.get("mult", 1.0) + 0.1
    def on_hand_scored(self, inst, ctx):
        ctx.mult_mult *= inst.state.get("mult", 1.0)

# The +5 chip bonus is applied to the card itself; scoring.py reads
# card.bonus_chips when scoring it.
@register_joker("j_hiker")
class _Hiker(JokerEffect):
    def on_score_card(self, inst, card, ctx):
        if not card.debuffed:
            card.bonus_chips = getattr(card, "bonus_chips", 0) + 5

@register_joker("j_ride_the_bus")
class _RideTheBus(JokerEffect):
    def on_hand_scored(self, inst, ctx):
        has_face = any(c.is_face_card for c in ctx.scoring_cards if not c.debuffed)
        if has_face:
            inst.state["mult"] = 0
        else:
            inst.state["mult"] = inst.state.get("mult", 0) + 1
        ctx.mult += inst.state.get("mult", 0)

# Real effect keys off the Kings still held in hand after the play.
@register_joker("j_baron")
class _Baron(JokerEffect):
    def on_hand_scored(self, inst, ctx):
        king_count = sum(1 for c in ctx.held_cards if c.rank == 13 and not c.debuffed)
        for _ in range(king_count):
            ctx.mult_mult *= 1.5
