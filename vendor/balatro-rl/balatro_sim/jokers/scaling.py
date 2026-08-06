"""
scaling.py — Jokers that gain permanent stat increases over time.
These build state across multiple hands/rounds.
"""
from .base import JOKER_REGISTRY, ScoreContext

# ── j_joker: already in mult.py ──────────────────────────────────────────────

# ── j_greedy: scored cards with Diamond suit give +3 mult ───────────────────
class _Greedy:
    def on_score_card(self, inst, card, ctx):
        if card.suit == "Diamonds" and not card.debuffed:
            ctx.mult += 3
JOKER_REGISTRY["j_greedy"] = JOKER_REGISTRY["j_greedy_joker"] = _Greedy()

# ── j_lusty_joker: scored cards with Heart suit give +3 mult ─────────────────
class _Lusty:
    def on_score_card(self, inst, card, ctx):
        if card.suit == "Hearts" and not card.debuffed:
            ctx.mult += 3
JOKER_REGISTRY["j_lusty"] = JOKER_REGISTRY["j_lusty_joker"] = _Lusty()

# ── j_wrathful_joker: scored cards with Spade suit give +3 mult ──────────────
class _Wrathful:
    def on_score_card(self, inst, card, ctx):
        if card.suit == "Spades" and not card.debuffed:
            ctx.mult += 3
JOKER_REGISTRY["j_wrathful"] = JOKER_REGISTRY["j_wrathful_joker"] = _Wrathful()

# ── j_gluttonous_joker: scored cards with Club suit give +3 mult ─────────────
class _Gluttonous:
    def on_score_card(self, inst, card, ctx):
        if card.suit == "Clubs" and not card.debuffed:
            ctx.mult += 3
JOKER_REGISTRY["j_gluttonous"] = JOKER_REGISTRY["j_gluttonous_joker"] = _Gluttonous()

# ── j_jolly: +8 mult if hand contains a Pair ────────────────────────────────
class _Jolly:
    def on_hand_scored(self, inst, ctx):
        if "Pair" in ctx.hand_type:
            ctx.mult += 8
JOKER_REGISTRY["j_jolly"] = _Jolly()

# ── j_zany: +12 mult if hand contains Three of a Kind ───────────────────────
class _Zany:
    def on_hand_scored(self, inst, ctx):
        if "Three" in ctx.hand_type:
            ctx.mult += 12
JOKER_REGISTRY["j_zany"] = _Zany()

# ── j_mad: +10 mult if hand contains Two Pair ───────────────────────────────
class _Mad:
    def on_hand_scored(self, inst, ctx):
        if "Two Pair" in ctx.hand_type:
            ctx.mult += 10
JOKER_REGISTRY["j_mad"] = _Mad()

# ── j_crazy: +12 mult if hand is Straight ───────────────────────────────────
class _Crazy:
    def on_hand_scored(self, inst, ctx):
        if "Straight" in ctx.hand_type and "Flush" not in ctx.hand_type:
            ctx.mult += 12
JOKER_REGISTRY["j_crazy"] = _Crazy()

# ── j_droll: already in chips.py ─────────────────────────────────────────────

# ── j_sly: +50 chips if hand contains a Pair ────────────────────────────────
_PAIR_TYPES = {"Pair", "Two Pair", "Full House", "Four of a Kind", "Five of a Kind", "Flush House", "Flush Five"}
class _Sly:
    def on_hand_scored(self, inst, ctx):
        if ctx.hand_type in _PAIR_TYPES:
            ctx.chips += 50
JOKER_REGISTRY["j_sly"] = _Sly()

# ── j_wily: +100 chips if hand contains Three of a Kind ─────────────────────
class _Wily:
    def on_hand_scored(self, inst, ctx):
        if "Three" in ctx.hand_type:
            ctx.chips += 100
JOKER_REGISTRY["j_wily"] = _Wily()

# ── j_clever: +80 chips if hand contains Two Pair ───────────────────────────
class _Clever:
    def on_hand_scored(self, inst, ctx):
        if "Two Pair" in ctx.hand_type:
            ctx.chips += 80
JOKER_REGISTRY["j_clever"] = _Clever()

# ── j_devious: +100 chips if hand contains a Straight ───────────────────────
class _Devious:
    def on_hand_scored(self, inst, ctx):
        if "Straight" in ctx.hand_type:  # includes Straight Flush
            ctx.chips += 100
JOKER_REGISTRY["j_devious"] = _Devious()

# ── j_crafty: +80 chips if hand contains a Flush ────────────────────────────
class _Crafty:
    def on_hand_scored(self, inst, ctx):
        if "Flush" in ctx.hand_type:  # includes Straight Flush, Flush House, Flush Five
            ctx.chips += 80
JOKER_REGISTRY["j_crafty"] = _Crafty()

# ── j_green_joker: +1 mult per hand played, -1 mult per discard ────────────
class _GreenJoker:
    def on_hand_scored(self, inst, ctx):
        inst.state["mult"] = inst.state.get("mult", 0) + 1
        ctx.mult += inst.state.get("mult", 0)
    def on_discard(self, inst, cards, ctx):
        inst.state["mult"] = max(0, inst.state.get("mult", 0) - 1)
JOKER_REGISTRY["j_green_joker"] = _GreenJoker()

# ── j_superposition: create a Tarot if hand contains Ace and Straight ───────
# TODO: consumable creation

# ── j_to_do_list: earn $4 if hand is {specific hand type}, changes ──────────
# TODO: requires tracking target hand type

# ── j_cavendish: already in chips.py ─────────────────────────────────────────

# ── j_card_sharp: already in chips.py ────────────────────────────────────────

# ── j_red_card: already in economy.py and chips.py ──────────────────────────

# ── j_madness: already in chips.py ───────────────────────────────────────────

# ── j_square_joker: already in chips.py ──────────────────────────────────────

# ── j_seance: already in chips.py ────────────────────────────────────────────

# ── j_riff_raff: already in chips.py ─────────────────────────────────────────

# ── j_vampire: already in chips.py ───────────────────────────────────────────

# ── j_shortcut: already in chips.py ──────────────────────────────────────────

# ── j_hologram: already in chips.py ──────────────────────────────────────────

# ── j_vagabond: already in chips.py ──────────────────────────────────────────

# ── j_cloud_9: already in chips.py ───────────────────────────────────────────

# ── j_rocket: already in economy.py ──────────────────────────────────────────

# ── j_merry_andy: already in chips.py ────────────────────────────────────────

# ── j_oops: already in chips.py ──────────────────────────────────────────────

# ── j_idol: already in chips.py ──────────────────────────────────────────────

# ── j_seeing_double: already in chips.py ─────────────────────────────────────

# ── j_matador: already in chips.py ───────────────────────────────────────────

# ── j_hit_the_road: already in chips.py ──────────────────────────────────────

# ── j_duo: already in chips.py ───────────────────────────────────────────────

# ── j_trio: already in chips.py ──────────────────────────────────────────────

# ── j_family: already in chips.py ────────────────────────────────────────────

# ── j_order: already in chips.py ─────────────────────────────────────────────

# ── j_tribe: already in chips.py ─────────────────────────────────────────────

# ── j_stuntman: already in chips.py ──────────────────────────────────────────

# ── j_invisible: already in chips.py ─────────────────────────────────────────

# ── j_brainstorm: already in chips.py ────────────────────────────────────────

# ── j_satellite: already in mult.py ──────────────────────────────────────────

# ── j_shoot_the_moon: already in chips.py ────────────────────────────────────

# ── j_drivers_license: already in chips.py ───────────────────────────────────

# ── j_cartomancer: already in chips.py ───────────────────────────────────────

# ── j_astronomer: already in chips.py ────────────────────────────────────────

# ── j_burnt: already in chips.py ─────────────────────────────────────────────

# ── j_bootstraps: already in chips.py ────────────────────────────────────────

# ── j_caino: already in chips.py ─────────────────────────────────────────────

# ── j_triboulet: already in chips.py ─────────────────────────────────────────

# ── j_yorick: already in chips.py ────────────────────────────────────────────

# ── j_chicot: already in chips.py ────────────────────────────────────────────

# ── j_perkeo: already in chips.py ────────────────────────────────────────────

# ── j_stone_joker: +25 chips per Stone card in full deck ────────────────────
class _StoneJoker:
    def on_hand_scored(self, inst, ctx):
        # TODO: requires full deck access
        pass
JOKER_REGISTRY["j_stone_joker"] = _StoneJoker()

# ── j_bull: +2 chips per $1 held ────────────────────────────────────────────
class _Bull:
    def on_hand_scored(self, inst, ctx):
        ctx.chips += 2 * ctx.dollars
JOKER_REGISTRY["j_bull"] = _Bull()

# ── j_diet_cola: sell to create free Double Tag ─────────────────────────────
# TODO: tag system

# ── j_trading: first discard each round costs $3 but creates Foil/Holo/Poly ──
# TODO: discard modification

# ── j_flash: +5 mult per replay in hand ─────────────────────────────────────
class _Flash:
    def on_hand_scored(self, inst, ctx):
        # TODO: requires replay tracking
        pass
JOKER_REGISTRY["j_flash"] = _Flash()

# ── j_popcorn: +20 mult, -4 mult per round played ───────────────────────────
class _Popcorn:
    def __init__(self):
        pass
    def on_init(self, inst):
        inst.state["mult"] = 20
    def on_hand_scored(self, inst, ctx):
        ctx.mult += inst.state.get("mult", 20)
    def on_round_end(self, inst, ctx):
        inst.state["mult"] = max(0, inst.state.get("mult", 20) - 4)
JOKER_REGISTRY["j_popcorn"] = _Popcorn()

# ── j_ramen: x2 mult, loses x0.01 mult per card discarded ───────────────────
class _Ramen:
    def __init__(self):
        pass
    def on_init(self, inst):
        inst.state["mult"] = 2.0
    def on_hand_scored(self, inst, ctx):
        ctx.mult_mult *= inst.state.get("mult", 2.0)
    def on_discard(self, inst, cards, ctx):
        inst.state["mult"] = max(1.0, inst.state.get("mult", 2.0) - 0.01 * len(cards))
JOKER_REGISTRY["j_ramen"] = _Ramen()

# ── j_seltzer: retrigger all cards for next 3 hands ─────────────────────────
# TODO: retrigger system

# ── j_castle: +3 chips per discarded {suit}, suit changes per round ─────────
class _Castle:
    def __init__(self):
        self.suits = ["Clubs", "Diamonds", "Hearts", "Spades"]
    def on_init(self, inst):
        inst.state["suit"] = inst.chance().choice(self.suits)
        inst.state["chips"] = 0
    def on_discard(self, inst, cards, ctx):
        for card in cards:
            if card.suit == inst.state.get("suit"):
                inst.state["chips"] = inst.state.get("chips", 0) + 3
    def on_hand_scored(self, inst, ctx):
        ctx.chips += inst.state.get("chips", 0)
    def on_round_end(self, inst, ctx):
        inst.state["suit"] = inst.chance().choice(self.suits)
        inst.state["chips"] = 0  # reset each round
JOKER_REGISTRY["j_castle"] = _Castle()

# ── j_smiley: already in chips.py ────────────────────────────────────────────

# ── j_campfire: x0.25 Mult per card sold, resets when Boss Blind is defeated ─
class _Campfire:
    def on_hand_scored(self, inst, ctx):
        xm = 1.0 + inst.state.get("sold", 0) * 0.25
        ctx.mult_mult *= xm
    def on_sell(self, inst, ctx):
        inst.state["sold"] = inst.state.get("sold", 0) + 1
    def on_boss_beaten(self, inst, ctx):
        inst.state["sold"] = 0  # reset on boss defeat
JOKER_REGISTRY["j_campfire"] = _Campfire()

# ── j_golden_ticket: already in economy.py ───────────────────────────────────

# ── j_mr_bones: prevents death once, then destroys itself ───────────────────
# TODO: death prevention system

# ── j_acrobat: already in chips.py ───────────────────────────────────────────

# ── j_sock_and_buskin: retrigger all face cards ─────────────────────────────
# TODO: retrigger system

# ── j_swashbuckler: +1 mult per Joker owned (adds mult, not x) ──────────────
class _Swashbuckler:
    def on_hand_scored(self, inst, ctx):
        ctx.mult += ctx.n_jokers
JOKER_REGISTRY["j_swashbuckler"] = _Swashbuckler()

# ── j_troubadour: +2 hand size, -1 hand per round ───────────────────────────
# TODO: hand size/hand count modification

# ── j_certificate: +1 dollar per round, each copy of held scored card +1 more
# TODO: held card tracking

# ── j_smeared_joker: Hearts and Diamonds count as same suit ─────────────────
# TODO: suit evaluation modification

# ── j_throwback: x2 mult for each skip taken this run ───────────────────────
class _Throwback:
    def on_blind_skipped(self, inst, ctx):
        inst.state["skips"] = inst.state.get("skips", 0) + 1
    def on_hand_scored(self, inst, ctx):
        for _ in range(inst.state.get("skips", 0)):
            ctx.mult_mult *= 2
JOKER_REGISTRY["j_throwback"] = _Throwback()

# ── j_hanging_chad: retrigger first played card 2 times ─────────────────────
# TODO: retrigger system

# ── j_rough_gem: +$1 per Diamond card scored ────────────────────────────────
class _RoughGem:
    def on_score_card(self, inst, card, ctx):
        if card.suit == "Diamonds" and not card.debuffed:
            ctx.pending_money += 1
JOKER_REGISTRY["j_rough_gem"] = _RoughGem()

# ── j_bloodstone: 1 in 2 chance for scored Heart to give +1.5 mult ──────────
class _Bloodstone:
    def on_score_card(self, inst, card, ctx):
        if card.suit == "Hearts" and not card.debuffed and inst.chance().random() < 0.5:
            ctx.mult_mult *= 1.5
JOKER_REGISTRY["j_bloodstone"] = _Bloodstone()

# ── j_arrowhead: +50 chips per Spade card scored ────────────────────────────
class _Arrowhead:
    def on_score_card(self, inst, card, ctx):
        if card.suit == "Spades" and not card.debuffed:
            ctx.chips += 50
JOKER_REGISTRY["j_arrowhead"] = _Arrowhead()

# ── j_onyx_agate: scored cards with Club suit give +7 mult ──────────────────
class _OnyxAgate:
    def on_score_card(self, inst, card, ctx):
        if card.suit == "Clubs" and not card.debuffed:
            ctx.mult += 7
JOKER_REGISTRY["j_onyx_agate"] = _OnyxAgate()

# ── j_glass_joker: x0.75 Mult for each Glass card in your full deck ──────────
class _GlassJoker:
    def on_hand_scored(self, inst, ctx):
        glass_count = sum(1 for c in ctx.all_cards if c.enhancement == "Glass")
        if glass_count > 0:
            ctx.mult_mult *= (1.0 + 0.75 * glass_count)
JOKER_REGISTRY["j_glass_joker"] = _GlassJoker()

# ── j_showman: for each Joker, reroll shop 1 time ───────────────────────────
# TODO: shop system

# ── j_flower_pot: x3 mult if hand contains Diamond, Club, Heart, Spade ──────
class _FlowerPot:
    def on_hand_scored(self, inst, ctx):
        suits = {c.suit for c in ctx.scoring_cards if not c.debuffed}
        if len(suits) == 4:
            ctx.mult_mult *= 3
JOKER_REGISTRY["j_flower_pot"] = _FlowerPot()

# ── j_blueprint: copy right-most Joker ──────────────────────────────────────
# TODO: joker copying

# ── j_wee: +10 chips per 2 in full deck (max 20 2s) ─────────────────────────
class _Wee:
    def on_hand_scored(self, inst, ctx):
        # TODO: requires full deck access
        pass
JOKER_REGISTRY["j_wee"] = _Wee()

# ── j_merry_andy: already stubbed in chips.py ───────────────────────────────

# ── j_obelisk: x0.2 Mult per consecutive hand that isn't your most played type
class _Obelisk:
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
JOKER_REGISTRY["j_obelisk"] = _Obelisk()

# ── j_midas_mask: all face cards become Gold when scored ────────────────────
class _MidasMask:
    def on_score_card(self, inst, card, ctx):
        if card.is_face_card and not card.debuffed:
            card.enhancement = "Gold"
JOKER_REGISTRY["j_midas_mask"] = _MidasMask()

# ── j_luchador: sell to disable current Boss Blind ──────────────────────────
# TODO: boss blind system

# ── j_photograph: +2 mult per scored face card on first hand ────────────────
class _Photograph:
    def on_score_card(self, inst, card, ctx):
        # First hand check needed
        if card.is_face_card and not card.debuffed:
            ctx.mult += 2
JOKER_REGISTRY["j_photograph"] = _Photograph()

# ── j_gift_card: already in economy.py (TODO stubbed) ────────────────────────

# ── j_turtle_bean: +5 hand size, reduce by 1 per round ──────────────────────
# TODO: hand size modification

# ── j_erosion: +4 mult per card below 52 in deck ────────────────────────────
class _Erosion:
    def on_hand_scored(self, inst, ctx):
        missing = max(0, 52 - ctx.deck_remaining)
        ctx.mult += 4 * missing
JOKER_REGISTRY["j_erosion"] = _Erosion()

# ── j_to_the_moon: already in economy.py ─────────────────────────────────────

# ── j_hallucination: 1 in 4 chance create Tarot when any Booster opened ─────
# TODO: booster system

# ── j_fortune_teller: +1 mult per Tarot used this run ───────────────────────
class _FortuneTeller:
    def on_tarot_used(self, inst, ctx):
        inst.state["mult"] = inst.state.get("mult", 0) + 1
    def on_hand_scored(self, inst, ctx):
        ctx.mult += inst.state.get("mult", 0)
JOKER_REGISTRY["j_fortune_teller"] = _FortuneTeller()

# ── j_juggler: +1 hand size ──────────────────────────────────────────────────
# TODO: hand size modification

# ── j_drunkard: +1 discard ──────────────────────────────────────────────────
# TODO: discard modification

# ── j_stone: full deck gives +25 chips per Stone card ───────────────────────
# (same as j_stone_joker above)

# ── j_golden: already in economy.py ──────────────────────────────────────────

# ── j_lucky_cat: x0.25 xMult per successful Lucky trigger (permanent) ───────
class _LuckyCat:
    def on_lucky_trigger(self, inst, ctx):
        inst.state["xmult"] = inst.state.get("xmult", 1.0) + 0.25
    def on_hand_scored(self, inst, ctx):
        xm = inst.state.get("xmult", 1.0)
        if xm > 1.0:
            ctx.mult_mult *= xm
JOKER_REGISTRY["j_lucky_cat"] = _LuckyCat()

# ── j_baseball: each Uncommon Joker gives x1.5 Mult ─────────────────────────
class _Baseball:
    def on_hand_scored(self, inst, ctx):
        from ..shop import JOKER_CATALOGUE
        for j in ctx.jokers:
            meta = JOKER_CATALOGUE.get(j.key, {})
            if meta.get("rarity") == "Uncommon":
                ctx.mult_mult *= 1.5
JOKER_REGISTRY["j_baseball"] = _Baseball()

# ── j_bull: already done above ───────────────────────────────────────────────

# ── j_diet_cola: already stubbed above ───────────────────────────────────────

# ── j_trading: already stubbed above ─────────────────────────────────────────

# ── j_flash: already stubbed above ───────────────────────────────────────────

# ── j_popcorn: already done above ────────────────────────────────────────────

# ── j_spare_trousers: +2 mult if played hand contains Two Pair ──────────────
class _SpareTrousers:
    def on_hand_scored(self, inst, ctx):
        if "Two Pair" in ctx.hand_type:
            inst.state["mult"] = inst.state.get("mult", 0) + 2
        ctx.mult += inst.state.get("mult", 0)
JOKER_REGISTRY["j_spare_trousers"] = _SpareTrousers()

# ── j_ancient: scored face cards with {suit} give x1.5 mult, suit changes ────
class _Ancient:
    def __init__(self):
        self.suits = ["Clubs", "Diamonds", "Hearts", "Spades"]
    def on_init(self, inst):
        inst.state["suit"] = inst.chance().choice(self.suits)
    def on_score_card(self, inst, card, ctx):
        if card.is_face_card and card.suit == inst.state.get("suit") and not card.debuffed:
            ctx.mult_mult *= 1.5
    def on_round_end(self, inst, ctx):
        inst.state["suit"] = inst.chance().choice(self.suits)
JOKER_REGISTRY["j_ancient"] = _Ancient()

# ── j_ramen: already done above ──────────────────────────────────────────────

# ── j_walkie_talkie: each 10 or 4 gives +10 chips and +4 mult ───────────────
class _WalkieTalkie:
    def on_score_card(self, inst, card, ctx):
        if card.rank in [10, 4] and not card.debuffed:
            ctx.chips += 10
            ctx.mult += 4
JOKER_REGISTRY["j_walkie_talkie"] = _WalkieTalkie()

# ── j_seltzer: already stubbed above ─────────────────────────────────────────

# ── j_castle: already done above ─────────────────────────────────────────────

# ── j_smiley: already in chips.py ────────────────────────────────────────────

# ── j_campfire: already done above ───────────────────────────────────────────

# ── j_ticket: +3 chips per $10 held (up to 5 Gold played) ───────────────────
class _Ticket:
    def on_hand_scored(self, inst, ctx):
        gold_played = inst.state.get("gold_played", 0)
        if gold_played < 5:
            ctx.chips += 3 * (ctx.dollars // 10)
    def on_score_card(self, inst, card, ctx):
        if card.enhancement == "Gold" and not card.debuffed:
            inst.state["gold_played"] = inst.state.get("gold_played", 0) + 1
JOKER_REGISTRY["j_ticket"] = _Ticket()

# ── j_mr_bones: already stubbed above ────────────────────────────────────────

# ── j_acrobat: already in chips.py ───────────────────────────────────────────

# ── j_sock_and_buskin: already stubbed above ─────────────────────────────────

# ── j_swashbuckler: already done above ───────────────────────────────────────

# ── j_troubadour: already stubbed above ──────────────────────────────────────

# ── j_certificate: already stubbed above ─────────────────────────────────────

# ── j_smeared_joker: already stubbed above ───────────────────────────────────

# ── j_throwback: already done above ──────────────────────────────────────────

# ── j_hanging_chad: already stubbed above ────────────────────────────────────

# ── j_rough_gem: already done above ──────────────────────────────────────────

# ── j_bloodstone: already done above ─────────────────────────────────────────

# ── j_arrowhead: already done above ──────────────────────────────────────────

# ── j_onyx_agate: already done above ─────────────────────────────────────────

# ── j_glass_joker: already done above ────────────────────────────────────────

# ── j_showman: already stubbed above ─────────────────────────────────────────

# ── j_flower_pot: already done above ─────────────────────────────────────────

# ── j_blueprint: already stubbed above ───────────────────────────────────────

# ── j_wee: already stubbed above ─────────────────────────────────────────────

# ── j_merry_andy: already stubbed ────────────────────────────────────────────

# ── j_obelisk: already stubbed above ─────────────────────────────────────────

# ── j_midas_mask: already done above ─────────────────────────────────────────

# ── j_luchador: already stubbed above ────────────────────────────────────────

# ── j_photograph: already done above ─────────────────────────────────────────

# ── j_gift_card: already stubbed ─────────────────────────────────────────────

# ── j_turtle_bean: already stubbed above ─────────────────────────────────────

# ── j_erosion: already done above ────────────────────────────────────────────

# ── j_to_the_moon: already in economy.py ─────────────────────────────────────

# ── j_hallucination: already stubbed above ───────────────────────────────────

# ── j_fortune_teller: already done above ─────────────────────────────────────

# ── j_juggler: already stubbed above ─────────────────────────────────────────

# ── j_drunkard: already stubbed above ────────────────────────────────────────

# ── j_burglar: +3 hands, -3 discards when blind is selected ─────────────────
# Real Balatro: game-state modifier, not a scoring joker. Gives extra hands
# but removes all discards. Applied via on_blind_selected hook in game.py.
class _Burglar:
    def on_blind_selected(self, inst, ctx):
        # game.py reads this state and applies +3 hands, sets discards to 0
        inst.state["extra_hands"] = 3
        inst.state["zero_discards"] = True
JOKER_REGISTRY["j_burglar"] = _Burglar()

# ── j_blackboard: x3 mult if all cards in hand are Spades or Clubs ──────────
class _Blackboard:
    def on_hand_scored(self, inst, ctx):
        all_black = all(c.suit in ["Spades", "Clubs"] for c in ctx.all_cards if not c.debuffed)
        if all_black:
            ctx.mult_mult *= 3
JOKER_REGISTRY["j_blackboard"] = _Blackboard()

# ── j_runner: +15 chips per Straight made this run ──────────────────────────
class _Runner:
    def on_hand_scored(self, inst, ctx):
        if "Straight" in ctx.hand_type:
            inst.state["chips"] = inst.state.get("chips", 0) + 15
        ctx.chips += inst.state.get("chips", 0)
JOKER_REGISTRY["j_runner"] = _Runner()

# ── j_ice_cream: +100 chips, -5 chips per hand played ───────────────────────
class _IceCream:
    def __init__(self):
        pass
    def on_init(self, inst):
        inst.state["chips"] = 100
    def on_hand_scored(self, inst, ctx):
        ctx.chips += inst.state.get("chips", 100)
        inst.state["chips"] = max(0, inst.state.get("chips", 100) - 5)
JOKER_REGISTRY["j_ice_cream"] = _IceCream()

# ── j_dna: if first hand has only 1 card, permanent copy added to deck ──────
# TODO: deck modification

# ── j_splash: every played card counts in scoring ───────────────────────────
# TODO: hand eval modification

# ── j_blue_joker: +2 chips per remaining card in deck ───────────────────────
class _BlueJoker:
    def on_hand_scored(self, inst, ctx):
        ctx.chips += 2 * ctx.deck_remaining
JOKER_REGISTRY["j_blue_joker"] = _BlueJoker()

# ── j_sixth_sense: if first hand is single 6, destroy it and create Spectral ─
# TODO: consumable creation

# ── j_constellation: x0.1 mult per Planet card used ─────────────────────────
class _Constellation:
    def on_planet_used(self, inst, planet_name):
        inst.state["mult"] = inst.state.get("mult", 1.0) + 0.1
    def on_hand_scored(self, inst, ctx):
        ctx.mult_mult *= inst.state.get("mult", 1.0)
JOKER_REGISTRY["j_constellation"] = _Constellation()

# ── j_hiker: every played card gives +4 chips permanently ───────────────────
class _Hiker:
    def on_score_card(self, inst, card, ctx):
        if not card.debuffed:
            card.bonus_chips = getattr(card, 'bonus_chips', 0) + 4
JOKER_REGISTRY["j_hiker"] = _Hiker()

# ── j_faceless: earn $5 if 3+ face cards discarded at once ──────────────────
# TODO: batch discard tracking

# ── j_todo_list: already stubbed above ───────────────────────────────────────

# ── j_ticket: already done above ─────────────────────────────────────────────

# ── j_mr_bones: already stubbed ──────────────────────────────────────────────

# ── j_acrobat: already in chips.py ───────────────────────────────────────────

# ── j_sock_and_buskin: already stubbed ───────────────────────────────────────

# ── j_superposition: already stubbed ─────────────────────────────────────────

# ── j_seance: already stubbed ────────────────────────────────────────────────

# ── j_riff_raff: already stubbed ─────────────────────────────────────────────

# ── j_space: 1 in 4 chance to upgrade played hand ───────────────────────────
class _Space:
    def on_hand_scored(self, inst, ctx):
        if inst.chance().random() < 0.25:
            # TODO: hand upgrade system
            pass
JOKER_REGISTRY["j_space"] = _Space()

# ── j_burglar: already done above ────────────────────────────────────────────

# ── j_blackboard: already done above ─────────────────────────────────────────

# ── j_runner: already done above ─────────────────────────────────────────────

# ── j_ice_cream: already done above ──────────────────────────────────────────

# ── j_dna: already stubbed above ─────────────────────────────────────────────

# ── j_splash: already stubbed above ──────────────────────────────────────────

# ── j_blue_joker: already done above ─────────────────────────────────────────

# ── j_sixth_sense: already stubbed above ─────────────────────────────────────

# ── j_constellation: already done above ──────────────────────────────────────

# ── j_hiker: already done above ──────────────────────────────────────────────

# ── j_faceless: already stubbed above ────────────────────────────────────────

# ── j_superposition: already stubbed ─────────────────────────────────────────

# ── j_ride_the_bus: +1 mult per consecutive hand without face card, resets ──
class _RideTheBus:
    def on_hand_scored(self, inst, ctx):
        has_face = any(c.is_face_card for c in ctx.scoring_cards if not c.debuffed)
        if has_face:
            inst.state["mult"] = 0
        else:
            inst.state["mult"] = inst.state.get("mult", 0) + 1
        ctx.mult += inst.state.get("mult", 0)
JOKER_REGISTRY["j_ride_the_bus"] = _RideTheBus()

# ── j_egg: sell to gain $3 of sell value ────────────────────────────────────
# TODO: sell system

# ── j_runner: already done ───────────────────────────────────────────────────

# ── j_ice_cream: already done ────────────────────────────────────────────────

# ── j_dna: already stubbed ───────────────────────────────────────────────────

# ── j_splash: already stubbed ────────────────────────────────────────────────

# ── j_blue_joker: already done ───────────────────────────────────────────────

# ── j_sixth_sense: already stubbed ───────────────────────────────────────────

# ── j_constellation: already done ────────────────────────────────────────────

# ── j_hiker: already done ────────────────────────────────────────────────────

# ── j_faceless: already stubbed ──────────────────────────────────────────────

# ── j_green_joker: already done ──────────────────────────────────────────────

# ── j_superposition: already stubbed ─────────────────────────────────────────

# ── j_to_do_list: already stubbed ────────────────────────────────────────────

# ── j_cavendish: already in chips.py ─────────────────────────────────────────

# ── j_card_sharp: already in chips.py ────────────────────────────────────────

# ── j_red_card: already in economy.py/chips.py ───────────────────────────────

# ── j_madness: already in chips.py ───────────────────────────────────────────

# ── j_square_joker: already in chips.py ──────────────────────────────────────

# ── j_baron: x1.5 mult per King in hand ─────────────────────────────────────
class _Baron:
    def on_hand_scored(self, inst, ctx):
        king_count = sum(1 for c in ctx.all_cards if c.rank == 13 and not c.debuffed)
        for _ in range(king_count):
            ctx.mult_mult *= 1.5
JOKER_REGISTRY["j_baron"] = _Baron()

# ── j_cloud_9: already stubbed in chips.py ───────────────────────────────────

# ── j_rocket: already in economy.py ──────────────────────────────────────────

# ── j_oops_all_6s: all cards are considered 6s, doubles probabilities ───────
# TODO: card eval modification

# ── j_bootstraps: already in chips.py ────────────────────────────────────────

# ── j_canio: already in chips.py ─────────────────────────────────────────────
