"""
mult.py — Additive mult jokers and xMult jokers.
"""
from .base import JOKER_REGISTRY, ScoreContext

# ── Helpers ──────────────────────────────────────────────────────────────────

def _has_hand(hand_type, *targets):
    return hand_type in targets

def _suit_in_scoring(cards, suit):
    return any(c.suit == suit for c in cards if not c.debuffed)

def _all_suits(cards):
    suits = {c.suit for c in cards if not c.debuffed and c.enhancement != "Stone"}
    return suits

# ── j_joker: +4 Mult ─────────────────────────────────────────────────────────
class _Joker:
    def on_hand_scored(self, inst, ctx):
        ctx.mult += 4
JOKER_REGISTRY["j_joker"] = _Joker()

# ── Greedy/Lusty/Wrathful/Gluttonous: +3 Mult if suit in played hand ─────────
class _SuitMult:
    def __init__(self, suit): self.suit = suit
    def on_hand_scored(self, inst, ctx):
        if _suit_in_scoring(ctx.scoring_cards, self.suit):
            ctx.mult += 3
JOKER_REGISTRY["j_greedy_mult"]     = _SuitMult("Diamonds")
JOKER_REGISTRY["j_lusty_mult"]      = _SuitMult("Hearts")
JOKER_REGISTRY["j_wrathful_mult"]   = _SuitMult("Spades")
JOKER_REGISTRY["j_gluttonous_mult"] = _SuitMult("Clubs")

# ── j_jolly: +8 Mult if Pair ─────────────────────────────────────────────────
class _Jolly:
    def on_hand_scored(self, inst, ctx):
        if _has_hand(ctx.hand_type, "Pair", "Two Pair", "Full House", "Four of a Kind", "Five of a Kind", "Flush House"):
            ctx.mult += 8
JOKER_REGISTRY["j_jolly"] = _Jolly()

# ── j_zany: +12 Mult if Three of a Kind ──────────────────────────────────────
class _Zany:
    def on_hand_scored(self, inst, ctx):
        if _has_hand(ctx.hand_type, "Three of a Kind", "Full House", "Five of a Kind", "Flush House"):
            ctx.mult += 12
JOKER_REGISTRY["j_zany"] = _Zany()

# ── j_mad: +10 Mult if Two Pair ───────────────────────────────────────────────
class _Mad:
    def on_hand_scored(self, inst, ctx):
        if _has_hand(ctx.hand_type, "Two Pair", "Full House"):
            ctx.mult += 10
JOKER_REGISTRY["j_mad"] = _Mad()

# ── j_crazy: +12 Mult if Straight ────────────────────────────────────────────
class _Crazy:
    def on_hand_scored(self, inst, ctx):
        if _has_hand(ctx.hand_type, "Straight", "Straight Flush"):
            ctx.mult += 12
JOKER_REGISTRY["j_crazy"] = _Crazy()

# ── j_droll: +10 Mult if Flush ───────────────────────────────────────────────
class _Droll:
    def on_hand_scored(self, inst, ctx):
        if _has_hand(ctx.hand_type, "Flush", "Straight Flush", "Flush House", "Flush Five"):
            ctx.mult += 10
JOKER_REGISTRY["j_droll"] = _Droll()

# ── j_half: +20 Mult if ≤3 cards played ─────────────────────────────────────
class _Half:
    def on_hand_scored(self, inst, ctx):
        if len(ctx.scoring_cards) <= 3:
            ctx.mult += 20
JOKER_REGISTRY["j_half"] = _Half()

# ── j_abstract: +3 Mult per Joker owned ─────────────────────────────────────
class _Abstract:
    def on_hand_scored(self, inst, ctx):
        ctx.mult += 3 * ctx.n_jokers
JOKER_REGISTRY["j_abstract"] = _Abstract()

# ── j_banner: +30 Chips per remaining Discard ────────────────────────────────
class _Banner:
    def on_hand_scored(self, inst, ctx):
        ctx.chips += 30 * ctx.discards_left
JOKER_REGISTRY["j_banner"] = _Banner()

# ── j_mystic_summit: +15 Mult when 0 discards remaining ──────────────────────
class _MysticSummit:
    def on_hand_scored(self, inst, ctx):
        if ctx.discards_left == 0:
            ctx.mult += 15
JOKER_REGISTRY["j_mystic_summit"] = _MysticSummit()

# ── j_misprint: +0 to +23 Mult (random) ─────────────────────────────────────
class _Misprint:
    def on_hand_scored(self, inst, ctx):
        ctx.mult += inst.chance().randint(0, 23)
JOKER_REGISTRY["j_misprint"] = _Misprint()

# ── j_raised_fist: adds 2x lowest rank card to Mult ─────────────────────────
class _RaisedFist:
    def on_hand_scored(self, inst, ctx):
        active = [c for c in ctx.all_cards if not c.debuffed and c.enhancement != "Stone"]
        if active:
            lowest = min(c.rank for c in active)
            ctx.mult += 2 * lowest
JOKER_REGISTRY["j_raised_fist"] = _RaisedFist()

# ── j_fibonacci: +8 Mult if scoring card is Ace, 2, 3, 5, or 8 ──────────────
class _Fibonacci:
    FIB = {14, 2, 3, 5, 8}
    def on_score_card(self, inst, card, ctx):
        if card.rank in self.FIB and not card.debuffed:
            ctx.mult += 8
JOKER_REGISTRY["j_fibonacci"] = _Fibonacci()

# ── j_smiley: +5 Mult per scored face card ───────────────────────────────────
class _Smiley:
    def on_score_card(self, inst, card, ctx):
        if card.is_face_card and not card.debuffed:
            ctx.mult += 5
JOKER_REGISTRY["j_smiley"] = _Smiley()

# ── j_shoot_the_moon: +13 Mult per Queen in hand ────────────────────────────
class _ShootTheMoon:
    def on_hand_scored(self, inst, ctx):
        queens = sum(1 for c in ctx.all_cards if c.rank == 12 and not c.debuffed)
        ctx.mult += 13 * queens
JOKER_REGISTRY["j_shoot_the_moon"] = _ShootTheMoon()

# ── j_walkie_talkie: +10 chips +4 mult if card is 10 or 4 ───────────────────
class _WalkieTalkie:
    def on_score_card(self, inst, card, ctx):
        if card.rank in (4, 10) and not card.debuffed:
            ctx.chips += 10
            ctx.mult += 4
JOKER_REGISTRY["j_walkie_talkie"] = _WalkieTalkie()

# ── j_bootstraps: +2 Mult per $5 held ───────────────────────────────────────
class _Bootstraps:
    def on_hand_scored(self, inst, ctx):
        ctx.mult += 2 * (ctx.dollars // 5)
JOKER_REGISTRY["j_bootstraps"] = _Bootstraps()

# ── j_photograph: x2 Mult for first face card scored each round ──────────────
class _Photograph:
    def on_score_card(self, inst, card, ctx):
        if card.is_face_card and not card.debuffed and not inst.state.get("fired"):
            inst.state["fired"] = True
            ctx.mult_mult *= 2
    def on_round_end(self, inst, ctx):
        inst.state["fired"] = False
JOKER_REGISTRY["j_photograph"] = _Photograph()

# ── j_scary_face: +30 chips if scoring card is face card ────────────────────
class _ScaryFace:
    def on_score_card(self, inst, card, ctx):
        if card.is_face_card and not card.debuffed:
            ctx.chips += 30
JOKER_REGISTRY["j_scary_face"] = _ScaryFace()

# ── j_pareidolia: treat all cards as face cards ──────────────────────────────
# (affects j_smiley, j_photograph, j_scary_face, etc. — requires engine support)
# TODO: implement flag on ScoreContext

# ── j_wee_joker: +8 chips each time a 2 is scored ───────────────────────────
class _WeeJoker:
    def on_score_card(self, inst, card, ctx):
        if card.rank == 2 and not card.debuffed:
            ctx.chips += 8
JOKER_REGISTRY["j_wee_joker"] = _WeeJoker()

# ── j_acrobat: x3 Mult on last hand of round ────────────────────────────────
class _Acrobat:
    def on_hand_scored(self, inst, ctx):
        if ctx.hands_left == 0:
            ctx.mult_mult *= 3
JOKER_REGISTRY["j_acrobat"] = _Acrobat()

# ── xMult jokers (The Duo, Trio, etc.) ───────────────────────────────────────
class _TheDuo:
    def on_hand_scored(self, inst, ctx):
        if _has_hand(ctx.hand_type, "Pair", "Two Pair", "Full House", "Four of a Kind", "Five of a Kind", "Flush House"):
            ctx.mult_mult *= 2
JOKER_REGISTRY["j_the_duo"] = _TheDuo()

class _TheTrio:
    def on_hand_scored(self, inst, ctx):
        if _has_hand(ctx.hand_type, "Three of a Kind", "Full House", "Five of a Kind", "Flush House"):
            ctx.mult_mult *= 3
JOKER_REGISTRY["j_the_trio"] = _TheTrio()

class _TheFamily:
    def on_hand_scored(self, inst, ctx):
        if _has_hand(ctx.hand_type, "Four of a Kind", "Five of a Kind"):
            ctx.mult_mult *= 4
JOKER_REGISTRY["j_the_family"] = _TheFamily()

class _TheOrder:
    def on_hand_scored(self, inst, ctx):
        if _has_hand(ctx.hand_type, "Straight", "Straight Flush"):
            ctx.mult_mult *= 3
JOKER_REGISTRY["j_the_order"] = _TheOrder()

class _TheTribe:
    def on_hand_scored(self, inst, ctx):
        if _has_hand(ctx.hand_type, "Flush", "Straight Flush", "Flush House", "Flush Five"):
            ctx.mult_mult *= 2
JOKER_REGISTRY["j_the_tribe"] = _TheTribe()

# ── j_stencil: x1 Mult per empty Joker slot (max 5 joker slots) ──────────────
class _Stencil:
    MAX_SLOTS = 5
    def on_hand_scored(self, inst, ctx):
        empty = max(0, self.MAX_SLOTS - ctx.n_jokers)
        ctx.mult_mult *= max(1, empty)
JOKER_REGISTRY["j_stencil"] = _Stencil()

# ── j_flower_pot: x3 Mult if all 4 suits in played hand ─────────────────────
class _FlowerPot:
    def on_hand_scored(self, inst, ctx):
        suits = _all_suits(ctx.all_cards)
        if len(suits) >= 4:
            ctx.mult_mult *= 3
JOKER_REGISTRY["j_flower_pot"] = _FlowerPot()

# ── j_triboulet: x2 Mult per King or Queen scored ───────────────────────────
class _Triboulet:
    def on_score_card(self, inst, card, ctx):
        if card.rank in (12, 13) and not card.debuffed:
            ctx.mult_mult *= 2
JOKER_REGISTRY["j_triboulet"] = _Triboulet()

# ── j_seeing_double: x2 Mult if Club + another suit in scoring hand ──────────
class _SeeingDouble:
    def on_hand_scored(self, inst, ctx):
        suits = _all_suits(ctx.scoring_cards)
        if "Clubs" in suits and len(suits) >= 2:
            ctx.mult_mult *= 2
JOKER_REGISTRY["j_seeing_double"] = _SeeingDouble()

# ── j_loyalty_card: x4 Mult every 6th hand played ───────────────────────────
class _LoyaltyCard:
    def on_hand_scored(self, inst, ctx):
        inst.state.setdefault("count", 0)
        inst.state["count"] += 1
        if inst.state["count"] % 6 == 0:
            ctx.mult_mult *= 4
JOKER_REGISTRY["j_loyalty_card"] = _LoyaltyCard()

# ── j_bloodstone: 1/2 chance x1.5 Mult per Heart scored ─────────────────────
class _Bloodstone:
    def on_score_card(self, inst, card, ctx):
        if card.suit == "Hearts" and not card.debuffed and inst.chance().random() < 0.5:
            ctx.mult_mult *= 1.5
JOKER_REGISTRY["j_bloodstone"] = _Bloodstone()

# ── j_ancient: x1.5 Mult if scoring card matches chosen suit ─────────────────
# Suit chosen randomly on creation (stored in state)
class _Ancient:
    SUITS = ["Spades", "Hearts", "Clubs", "Diamonds"]
    def on_score_card(self, inst, card, ctx):
        suit = inst.state.get("suit") or inst.chance().choice(self.SUITS)
        inst.state["suit"] = suit
        if card.suit == suit and not card.debuffed:
            ctx.mult_mult *= 1.5
JOKER_REGISTRY["j_ancient"] = _Ancient()

# ── j_throwback: x0.25 Mult per Blind skipped, starts at x1 ─────────────────
class _Throwback:
    def on_hand_scored(self, inst, ctx):
        bonus = inst.state.get("bonus", 1.0)
        ctx.mult_mult *= bonus
    def on_blind_skipped(self, inst, ctx):
        inst.state["bonus"] = inst.state.get("bonus", 1.0) + 0.25
JOKER_REGISTRY["j_throwback"] = _Throwback()

# ── j_the_idol: x2 Mult if specific card is played ───────────────────────────
# Card chosen randomly (rank+suit), changes each round
class _TheIdol:
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
JOKER_REGISTRY["j_the_idol"] = _TheIdol()

# ── j_dusk: retrigger all cards on last hand of round ────────────────────────
# TODO: retrigger requires engine support (mark last hand in ctx)

# ── j_mime: retrigger held cards ─────────────────────────────────────────────
# TODO: retrigger requires engine support

# ── j_sock_and_buskin: retrigger face cards ───────────────────────────────────
# TODO: retrigger requires engine support

# ── j_hanging_chad: retrigger first scored card twice ────────────────────────
# TODO: retrigger requires engine support

# ── j_seltzer: retrigger all cards, vanishes after 10 hands ──────────────────
# TODO: retrigger + vanish requires engine support

# ── j_hack: retrigger 2s, 3s, 4s, 5s ────────────────────────────────────────
# TODO: retrigger requires engine support

# ── j_blueprint: copy joker to right ─────────────────────────────────────────
# TODO: complex chain - requires engine support

# ── j_brainstorm: copy leftmost joker ────────────────────────────────────────
# TODO: complex chain

# ── j_burnt_joker: upgrade most played hand ───────────────────────────────────
# TODO: requires tracking most played hand + planet upgrade

# ── j_mr_bones: prevent loss if ≥25% of blind ────────────────────────────────
# TODO: requires engine hook on loss condition (not a scoring joker)

# ── j_four_fingers: Flushes/Straights with 4 cards ───────────────────────────
# TODO: requires hand eval modification flag

# ── j_smeared_joker: Hearts/Diamonds same suit, Spades/Clubs same suit ───────
# TODO: requires hand eval modification flag

# ── j_oops_all_sixes: double all listed probabilities ────────────────────────
# TODO: requires probability system

# ── j_8_ball: 1/4 chance of Tarot if 4+ 8s played ───────────────────────────
# TODO: requires consumable creation system

# ── j_cartomancer: create Tarot card each round ───────────────────────────────
# TODO: requires consumable creation system

# ── j_astronomer: free Planet cards ──────────────────────────────────────────
# TODO: requires shop system integration

# ── j_invisible_joker: after 2 rounds, duplicate a random joker ──────────────
# TODO: complex - requires joker creation system

# ── j_perkeo: creates Negative Tarot copy of last consumed card ──────────────
# TODO: requires consumable tracking + creation

# ── j_chicot: disables boss blind effect ─────────────────────────────────────
# TODO: requires boss blind system integration

# ── j_matador: earns $8 if boss blind ability triggered ──────────────────────
# TODO: requires boss event hook

# ── j_ring_master: reroll boss blind ─────────────────────────────────────────
# TODO: requires shop system integration

# ── j_credit_card: go up to $20 in debt ──────────────────────────────────────
# TODO: requires economic system integration (not a scoring joker)

# ── j_merry_andy: +3 discards, -1 hand size ──────────────────────────────────
# TODO: game state modification (not scoring)

# ── j_troubadour: +2 hand size, -1 hand count ────────────────────────────────
# TODO: game state modification

# ── j_stuntman: +250 chips, -2 hand size ─────────────────────────────────────
class _Stuntman:
    def on_hand_scored(self, inst, ctx):
        ctx.chips += 250
JOKER_REGISTRY["j_stuntman"] = _Stuntman()

# ── j_space_joker: 1 in 4 chance to level up played hand ─────────────────────
class _SpaceJoker:
    def on_hand_scored(self, inst, ctx):
        if inst.chance().random() < 0.25:
            ctx.planet_levels[ctx.hand_type] = ctx.planet_levels.get(ctx.hand_type, 1) + 1
JOKER_REGISTRY["j_space_joker"] = _SpaceJoker()

# ── j_drivers_license: +3 Mult per enhanced card if ≥16 enhanced in deck ─────
# TODO: needs full deck access for enhanced card count

# ── j_satellite: earns $1 per unique Planet card used this run ───────────────
class _Satellite:
    def on_round_end(self, inst, ctx):
        pass  # TODO: needs planet usage tracking across run
JOKER_REGISTRY["j_satellite"] = _Satellite()

# ── j_supernova: +Mult equal to the number of times the played hand type has
# been played this run (Common) ──────────────────────────────────────────────
class _Supernova:
    def on_hand_scored(self, inst, ctx):
        if inst.game is not None:
            ctx.mult += inst.game.run_hand_counts.get(ctx.hand_type, 0)
JOKER_REGISTRY["j_supernova"] = _Supernova()
