"""
misc.py — Remaining jokers: retrigger mechanics, hand eval flags,
          blueprint/brainstorm, economy specials, and others.
"""
from .base import JOKER_REGISTRY, ScoreContext, JokerInstance

# ════════════════════════════════════════════════════════════════════════════
# RETRIGGER JOKERS
# These set ctx.card_retriggers[i] in on_score_card (fires during card loop).
# ════════════════════════════════════════════════════════════════════════════

# ── j_hack: retrigger 2s, 3s, 4s, 5s ────────────────────────────────────────
class _Hack:
    def on_score_card(self, inst, card, ctx):
        if card.rank in (2, 3, 4, 5) and not card.debuffed:
            i = ctx.scoring_cards.index(card)
            ctx.card_retriggers[i] = ctx.card_retriggers.get(i, 0) + 1
JOKER_REGISTRY["j_hack"] = _Hack()

# ── j_sock_and_buskin: retrigger all face cards ───────────────────────────────
class _SockAndBuskin:
    def on_score_card(self, inst, card, ctx):
        if ctx.is_face_card(card) and not card.debuffed:
            i = ctx.scoring_cards.index(card)
            ctx.card_retriggers[i] = ctx.card_retriggers.get(i, 0) + 1
JOKER_REGISTRY["j_sock_and_buskin"] = _SockAndBuskin()

# ── j_hanging_chad: retrigger first scored card 2 extra times ────────────────
class _HangingChad:
    def on_score_card(self, inst, card, ctx):
        if not inst.state.get("fired"):
            inst.state["fired"] = True
            i = ctx.scoring_cards.index(card)
            ctx.card_retriggers[i] = ctx.card_retriggers.get(i, 0) + 2
    def on_round_end(self, inst, ctx):
        inst.state["fired"] = False
JOKER_REGISTRY["j_hanging_chad"] = _HangingChad()

# ── j_dusk: retrigger all cards on last hand of round ────────────────────────
# Uses pre_score hook so retriggers are set before the card loop starts.
class _Dusk:
    def pre_score(self, inst, ctx):
        if ctx.hands_left == 0:
            for i in range(len(ctx.scoring_cards)):
                ctx.card_retriggers[i] = ctx.card_retriggers.get(i, 0) + 1
JOKER_REGISTRY["j_dusk"] = _Dusk()

# ── j_seltzer: retrigger all cards for 10 hands, then self-destructs ─────────
class _Seltzer:
    def pre_score(self, inst, ctx):
        remaining = inst.state.get("hands", 10)
        if remaining > 0:
            for i in range(len(ctx.scoring_cards)):
                ctx.card_retriggers[i] = ctx.card_retriggers.get(i, 0) + 1
    def on_hand_scored(self, inst, ctx):
        inst.state["hands"] = inst.state.get("hands", 10) - 1
        if inst.state["hands"] <= 0:
            inst.state["destroyed"] = True
JOKER_REGISTRY["j_seltzer"] = _Seltzer()

# ── j_mime: retrigger held-in-hand card effects (approximated as +1 retrigger all) ──
# True Mime copies held-card on-hold effects (Steel, Gold, etc.). Approximated here.
class _Mime:
    def pre_score(self, inst, ctx):
        # Approximate: retrigger scoring for each card once (Steel held-in-hand)
        for i, card in enumerate(ctx.scoring_cards):
            if card.enhancement in ("Steel", "Gold") and not card.debuffed:
                ctx.card_retriggers[i] = ctx.card_retriggers.get(i, 0) + 1
JOKER_REGISTRY["j_mime"] = _Mime()

# ════════════════════════════════════════════════════════════════════════════
# HAND EVAL FLAG JOKERS
# Set ctx flags that hand_eval.py and scoring respect.
# ════════════════════════════════════════════════════════════════════════════

# ── j_pareidolia: all cards count as face cards ───────────────────────────────
class _Pareidolia:
    def pre_score(self, inst, ctx):
        ctx.all_face_cards = True
JOKER_REGISTRY["j_pareidolia"] = _Pareidolia()

# ── j_four_fingers: Flush/Straight valid with 4 cards ────────────────────────
class _FourFingers:
    def pre_score(self, inst, ctx):
        ctx.four_finger_mode = True
    def on_hand_scored(self, inst, ctx):
        pass  # Main effect in hand_eval; small chip bonus for holding joker
JOKER_REGISTRY["j_four_fingers"] = _FourFingers()

# ── j_smeared_joker: Hearts=Diamonds, Spades=Clubs for suit checks ───────────
class _SmearedJoker:
    def pre_score(self, inst, ctx):
        ctx.smear_suits = True
JOKER_REGISTRY["j_smeared_joker"] = _SmearedJoker()

# ── j_splash: all played cards count in scoring ───────────────────────────────
class _Splash:
    def pre_score(self, inst, ctx):
        ctx.all_scoring_mode = True
        # Extend scoring_cards to include all played cards
        for card in ctx.all_cards:
            if card not in ctx.scoring_cards and not card.debuffed:
                ctx.scoring_cards.append(card)
JOKER_REGISTRY["j_splash"] = _Splash()

# ── j_shortcut: Straights can skip one rank (gaps of 1 allowed) ──────────────
class _Shortcut:
    def pre_score(self, inst, ctx):
        ctx.shortcut_mode = True  # honoured in hand_eval when flag present
JOKER_REGISTRY["j_shortcut"] = _Shortcut()

# ════════════════════════════════════════════════════════════════════════════
# BLUEPRINT / BRAINSTORM — copy adjacent joker effects
# Recursion guard prevents infinite loop when Blueprint copies Brainstorm
# which copies Blueprint (or vice versa).
# ════════════════════════════════════════════════════════════════════════════

_copy_depth = 0
_MAX_COPY_DEPTH = 3


def _guarded_call(method_name, target, ctx, card=None):
    """Call a joker effect method with recursion depth guard."""
    global _copy_depth
    if _copy_depth >= _MAX_COPY_DEPTH:
        return
    effect = JOKER_REGISTRY.get(target.key)
    if effect and hasattr(effect, method_name):
        _copy_depth += 1
        try:
            fn = getattr(effect, method_name)
            if card is not None:
                fn(target, card, ctx)
            else:
                fn(target, ctx)
        finally:
            _copy_depth -= 1


class _Blueprint:
    """Copies the effect of the joker immediately to the right."""
    def _get_copy_target(self, inst, ctx):
        idx = ctx.jokers.index(inst)
        if idx + 1 < len(ctx.jokers):
            return ctx.jokers[idx + 1]
        return None

    def pre_score(self, inst, ctx):
        target = self._get_copy_target(inst, ctx)
        if target: _guarded_call("pre_score", target, ctx)

    def on_score_card(self, inst, card, ctx):
        target = self._get_copy_target(inst, ctx)
        if target: _guarded_call("on_score_card", target, ctx, card)

    def on_hand_scored(self, inst, ctx):
        target = self._get_copy_target(inst, ctx)
        if target: _guarded_call("on_hand_scored", target, ctx)

JOKER_REGISTRY["j_blueprint"] = _Blueprint()


class _Brainstorm:
    """Copies the effect of the leftmost joker."""
    def _get_copy_target(self, inst, ctx):
        if ctx.jokers and ctx.jokers[0] is not inst:
            return ctx.jokers[0]
        return None

    def pre_score(self, inst, ctx):
        target = self._get_copy_target(inst, ctx)
        if target: _guarded_call("pre_score", target, ctx)

    def on_score_card(self, inst, card, ctx):
        target = self._get_copy_target(inst, ctx)
        if target: _guarded_call("on_score_card", target, ctx, card)

    def on_hand_scored(self, inst, ctx):
        target = self._get_copy_target(inst, ctx)
        if target: _guarded_call("on_hand_scored", target, ctx)

JOKER_REGISTRY["j_brainstorm"] = _Brainstorm()

# ════════════════════════════════════════════════════════════════════════════
# SURVIVABILITY / GAME-STATE JOKERS
# ════════════════════════════════════════════════════════════════════════════

# ── j_mr_bones: prevent death if score >= 25% of required chips ──────────────
class _MrBones:
    def on_hand_scored(self, inst, ctx):
        # Sets flag; game.py checks ctx.prevent_loss after scoring
        # Activation: if current_score / score_target >= 0.25
        inst.state["active"] = True  # game.py reads this
        ctx.prevent_loss = True      # always set; game.py validates threshold
JOKER_REGISTRY["j_mr_bones"] = _MrBones()

# ── j_drivers_license: x3 mult if >= 16 enhanced cards in deck ───────────────
# (Needs full deck count; approximated via all_cards here)
class _DriversLicense:
    def on_hand_scored(self, inst, ctx):
        enhanced = sum(
            1 for c in ctx.all_cards
            if c.enhancement and c.enhancement not in ("Base", "Stone")
        )
        if enhanced >= 16:
            ctx.mult_mult *= 3
JOKER_REGISTRY["j_drivers_license"] = _DriversLicense()

# ── j_satellite: +$1 per unique Planet card used this run ────────────────────
class _Satellite:
    def on_round_end(self, inst, ctx):
        n = len(inst.state.get("planets_used", set()))
        inst.state["pending_money"] = inst.state.get("pending_money", 0) + n
    def on_planet_used(self, inst, planet_name):
        if "planets_used" not in inst.state:
            inst.state["planets_used"] = set()
        inst.state["planets_used"].add(planet_name)
JOKER_REGISTRY["j_satellite"] = _Satellite()

# ── j_cloud_9: +$1 per 9 in FULL DECK at end of round ────────────────────────
# game.py passes ctx=None for on_round_end, so we track 9s via game state
# The count is set by game.py before calling on_round_end (via joker state)
class _Cloud9:
    def on_round_end(self, inst, ctx):
        nines = inst.state.get("deck_nines", 0)
        inst.state["pending_money"] = inst.state.get("pending_money", 0) + nines
JOKER_REGISTRY["j_cloud_9"] = _Cloud9()

# ── j_wee (wee joker): permanently gains +8 chips each time a 2 is scored ────
class _Wee:
    def on_score_card(self, inst, card, ctx):
        if card.rank == 2 and not card.debuffed:
            inst.state["chips"] = inst.state.get("chips", 0) + 8
    def on_hand_scored(self, inst, ctx):
        ctx.chips += inst.state.get("chips", 0)
JOKER_REGISTRY["j_wee"] = _Wee()

# ── j_stone_joker: +25 chips per Stone card in full deck ─────────────────────
class _StoneJoker:
    def on_hand_scored(self, inst, ctx):
        stones = sum(1 for c in ctx.all_cards if c.enhancement == "Stone")
        ctx.chips += 25 * stones
JOKER_REGISTRY["j_stone_joker"] = _StoneJoker()

# ════════════════════════════════════════════════════════════════════════════
# PROBABILISTIC / TAROT-CREATION JOKERS
# These use pending_consumables to signal the game loop.
# ════════════════════════════════════════════════════════════════════════════

# ── j_8_ball: 1/4 chance of Tarot per 8 scored ───────────────────────────────
class _EightBall:
    def on_score_card(self, inst, card, ctx):
        if card.rank == 8 and not card.debuffed and inst.chance().random() < 0.25:
            ctx.pending_consumables.append("tarot")
JOKER_REGISTRY["j_8_ball"] = _EightBall()

# ── j_seance: if hand is Straight Flush, create random Spectral ─────────────
class _Seance:
    def on_hand_scored(self, inst, ctx):
        if ctx.hand_type == "Straight Flush":
            ctx.pending_consumables.append("spectral")
JOKER_REGISTRY["j_seance"] = _Seance()

# ── j_riff_raff: when blind selected, create 2 common jokers ────────────────
class _RiffRaff:
    def on_blind_selected(self, inst, ctx):
        pc = inst.state.setdefault("pending_consumables", [])
        pc.append("common_joker")
        pc.append("common_joker")
JOKER_REGISTRY["j_riff_raff"] = _RiffRaff()

# ── j_superposition: Tarot if played Straight with Ace ───────────────────────
class _Superposition:
    def on_hand_scored(self, inst, ctx):
        has_ace = any(c.rank == 14 for c in ctx.scoring_cards if not c.debuffed)
        if "Straight" in ctx.hand_type and has_ace:
            ctx.pending_consumables.append("tarot")
JOKER_REGISTRY["j_superposition"] = _Superposition()

# ── j_sixth_sense: first hand with single 6 → Spectral, destroy the 6 ───────
class _SixthSense:
    def on_hand_scored(self, inst, ctx):
        if inst.state.get("used"):
            return
        if len(ctx.scoring_cards) == 1 and ctx.scoring_cards[0].rank == 6:
            ctx.scoring_cards[0].debuffed = True  # approximate destroy
            ctx.pending_consumables.append("spectral")
            inst.state["used"] = True
JOKER_REGISTRY["j_sixth_sense"] = _SixthSense()

# ── j_hallucination: 1/2 chance of Tarot per Booster pack opened ─────────────
class _Hallucination:
    def on_booster_opened(self, inst, ctx):
        if inst.chance().random() < 0.5:
            ctx.pending_consumables.append("tarot")
JOKER_REGISTRY["j_hallucination"] = _Hallucination()

# ── j_cartomancer: create 1 Tarot at start of each blind ─────────────────────
class _Cartomancer:
    def on_blind_selected(self, inst, ctx):
        inst.state.setdefault("pending_consumables", []).append("tarot")
JOKER_REGISTRY["j_cartomancer"] = _Cartomancer()

# ── j_astronomer: Planet cards cost $0 in shop ───────────────────────────────
class _Astronomer:
    def on_shop_enter(self, inst, ctx):
        inst.state["free_planets"] = True  # shop reads this flag
JOKER_REGISTRY["j_astronomer"] = _Astronomer()

# ── j_burnt_joker: upgrade most-played hand at start of round ────────────────
class _BurntJoker:
    def on_blind_selected(self, inst, ctx):
        most_played = inst.state.get("most_played")
        if most_played:
            inst.state["planet_upgrade"] = most_played  # game.py applies this
    def on_hand_scored(self, inst, ctx):
        # Track most played hand
        counts = inst.state.setdefault("counts", {})
        counts[ctx.hand_type] = counts.get(ctx.hand_type, 0) + 1
        inst.state["most_played"] = max(counts, key=counts.get)
JOKER_REGISTRY["j_burnt_joker"] = _BurntJoker()

# ── j_invisible_joker: after 2 rounds, SELL to duplicate a random joker ──────
class _InvisibleJoker:
    def on_round_end(self, inst, ctx):
        inst.state["rounds"] = inst.state.get("rounds", 0) + 1
    def on_sell(self, inst, ctx):
        if inst.state.get("rounds", 0) >= 2:
            inst.state.setdefault("pending_consumables", []).append("duplicate_joker")
JOKER_REGISTRY["j_invisible_joker"] = _InvisibleJoker()

# ── j_perkeo: create Negative Tarot of last consumed card at end of shop ─────
class _Perkeo:
    def on_shop_leave(self, inst, ctx):
        ctx.pending_consumables.append("negative_tarot")
JOKER_REGISTRY["j_perkeo"] = _Perkeo()

# ════════════════════════════════════════════════════════════════════════════
# BOSS BLIND EFFECTS
# ════════════════════════════════════════════════════════════════════════════

# ── j_chicot: disables the effect of every Boss Blind (Legendary) ────────────
# game.py disables boss abilities by PRESENCE of this key in the joker list
# (game._boss_effects_on) — matching the real game's permanent passive. No
# hook needed; the class exists so the joker resolves in the registry.
class _Chicot:
    pass
JOKER_REGISTRY["j_chicot"] = _Chicot()

# ── j_matador: earn $8 if Boss Blind ability triggers ────────────────────────
class _Matador:
    def on_boss_ability_triggered(self, inst, ctx):
        inst.state["pending_money"] = inst.state.get("pending_money", 0) + 8
JOKER_REGISTRY["j_matador"] = _Matador()

# ── j_luchador: sell this to disable the Boss Blind ─────────────────────────
class _Luchador:
    def on_sell(self, inst, ctx):
        # Set a GAME-level flag: the joker instance is destroyed on sale, so the
        # flag must outlive it. game._boss_effects_on() reads it until the next
        # Boss Blind resolves (_end_round clears it).
        if inst.game is not None:
            inst.game.boss_disabled_override = True
JOKER_REGISTRY["j_luchador"] = _Luchador()

# ── j_ring_master: real game = "Showman" (Joker/Tarot/Planet/Spectral cards
# may appear multiple times). The sim never dedupes shop/pack items, so this
# effect is already the sim's default — kept as a registered no-op marker. The
# previous "reroll boss blind" implementation was NOT a real Balatro joker
# effect (boss rerolls belong to the Director's Cut voucher) and has been
# removed rather than wired into a non-existent mechanic.
class _RingMaster:
    pass
JOKER_REGISTRY["j_ring_master"] = _RingMaster()

# ════════════════════════════════════════════════════════════════════════════
# DECK MODIFICATION JOKERS
# ════════════════════════════════════════════════════════════════════════════

# ── j_marble: add 1 Stone card to deck when a Blind is selected ─────────────
class _Marble:
    def on_blind_selected(self, inst, ctx):
        inst.state.setdefault("pending_consumables", []).append("stone_card")
JOKER_REGISTRY["j_marble"] = _Marble()

# ── j_dna: if first hand has 1 card, add permanent copy to deck ─────────────
class _DNA:
    def on_hand_scored(self, inst, ctx):
        if inst.state.get("used"):
            return
        if len(ctx.scoring_cards) == 1:
            ctx.pending_consumables.append(f"copy_card:{ctx.scoring_cards[0].rank}:{ctx.scoring_cards[0].suit}")
            inst.state["used"] = True
JOKER_REGISTRY["j_dna"] = _DNA()

# ── j_oops_all_sixes (catalogue key "j_oops"): double all listed probabilities ─
# scoring.py detects the key by presence in the active joker list and doubles
# Glass shatter / Lucky rolls (real-game behavior). Registered under both the
# catalogue key ("j_oops" — what the shop sells) and the old internal key.
class _OopsAllSixes:
    def pre_score(self, inst, ctx):
        inst.state["double_prob"] = True  # informational; scoring uses presence
JOKER_REGISTRY["j_oops"] = _OopsAllSixes()
JOKER_REGISTRY["j_oops_all_sixes"] = _OopsAllSixes()

# ── j_trading_card: first discard each round destroys random card, earn $3 ────
class _TradingCard:
    def on_discard(self, inst, cards, ctx):
        if inst.state.get("used"):
            return
        inst.state["used"] = True
        inst.state["pending_money"] = inst.state.get("pending_money", 0) + 3
        if cards:
            import random as _r
            target = _r.choice(cards)
            target.debuffed = True  # approximate destroy
    def on_round_end(self, inst, ctx):
        inst.state["used"] = False
JOKER_REGISTRY["j_trading_card"] = _TradingCard()

# ════════════════════════════════════════════════════════════════════════════
# ECONOMY / GAME STATE JOKERS
# ════════════════════════════════════════════════════════════════════════════

# ── j_merry_andy: +3 discards, -1 hand size (passive, constant while owned) ──
# Applied in game.py _start_blind via joker key check, not cumulative hooks
class _MerryAndy:
    pass
JOKER_REGISTRY["j_merry_andy"] = _MerryAndy()

# ── j_troubadour: +2 hand size, -1 hand per round (passive, constant) ────────
class _Troubadour:
    pass
JOKER_REGISTRY["j_troubadour"] = _Troubadour()

# ── j_credit_card: can go up to -$20 in debt ─────────────────────────────────
# game.py checks for this joker when validating purchases
class _CreditCard:
    def on_shop_enter(self, inst, ctx):
        inst.state["debt_limit"] = -20
JOKER_REGISTRY["j_credit_card"] = _CreditCard()

# ── j_turtle_bean: +5 hand size, -1 per round ────────────────────────────────
class _TurtleBean:
    def pre_score(self, inst, ctx):
        pass  # hand size modification in game state
    def on_round_end(self, inst, ctx):
        inst.state["bonus"] = max(0, inst.state.get("bonus", 5) - 1)
        if inst.state["bonus"] == 0:
            inst.state["destroyed"] = True
JOKER_REGISTRY["j_turtle_bean"] = _TurtleBean()

# ── j_juggler: +1 hand size (passive, constant while owned) ──────────────────
class _Juggler:
    pass
JOKER_REGISTRY["j_juggler"] = _Juggler()

# ── j_drunkard: +1 discard per round (passive, constant while owned) ─────────
class _Drunkard:
    pass
JOKER_REGISTRY["j_drunkard"] = _Drunkard()

# ── j_chaos: first reroll in shop is free ─────────────────────────────────────
class _Chaos:
    def on_shop_enter(self, inst, ctx):
        inst.state["free_reroll"] = True
JOKER_REGISTRY["j_chaos"] = _Chaos()

# ── j_gift_card: +$1 to each Joker and Consumable in shop at end of round ────
class _GiftCard:
    def on_round_end(self, inst, ctx):
        inst.state["pending_shop_buff"] = True  # shop applies extra $1 to items
JOKER_REGISTRY["j_gift_card"] = _GiftCard()

# ── j_egg: gains $3 of sell value each round ──────────────────────────────────
class _Egg:
    def on_round_end(self, inst, ctx):
        inst.state["sell_value"] = inst.state.get("sell_value", 1) + 3
JOKER_REGISTRY["j_egg"] = _Egg()

# ── j_delayed_grat: earn $2 per remaining discard if none used by round end ──
# Note: on_round_end receives ctx=None, so we track discards_left via joker state
class _DelayedGrat:
    def on_round_end(self, inst, ctx):
        if not inst.state.get("discarded"):
            remaining = inst.state.get("discards_left", 3)
            inst.state["pending_money"] = inst.state.get("pending_money", 0) + 2 * remaining
        inst.state["discarded"] = False
    def on_discard(self, inst, cards, ctx):
        inst.state["discarded"] = True
    def on_hand_scored(self, inst, ctx):
        # Track discards_left for round_end (ctx is available here)
        inst.state["discards_left"] = ctx.discards_left
JOKER_REGISTRY["j_delayed_grat"] = _DelayedGrat()

# ── j_faceless: earn $5 if 3+ face cards discarded at once ────────────────────
class _Faceless:
    def on_discard(self, inst, cards, ctx):
        face_count = sum(1 for c in cards if c.is_face_card)
        if face_count >= 3:
            inst.state["pending_money"] = inst.state.get("pending_money", 0) + 5
JOKER_REGISTRY["j_faceless"] = _Faceless()

# ── j_to_do_list: earn $4 if played hand matches target; target changes ───────
class _ToDoList:
    HANDS = [
        "High Card", "Pair", "Two Pair", "Three of a Kind",
        "Straight", "Flush", "Full House", "Four of a Kind", "Straight Flush"
    ]
    def on_init(self, inst):
        inst.state["target"] = inst.chance().choice(self.HANDS)
    def on_hand_scored(self, inst, ctx):
        target = inst.state.get("target", "High Card")
        if ctx.hand_type == target:
            ctx.pending_money = getattr(ctx, "pending_money", 0) + 4
            inst.state["target"] = inst.chance().choice(self.HANDS)
JOKER_REGISTRY["j_to_do_list"] = _ToDoList()

# ── j_showman: each Joker name can appear multiple times in shop ─────────────
class _Showman:
    def on_shop_enter(self, inst, ctx):
        inst.state["no_duplicate_limit"] = True
JOKER_REGISTRY["j_showman"] = _Showman()

# ── j_diet_cola: sell to create a free Double Tag ────────────────────────────
class _DietCola:
    def on_sell(self, inst, ctx):
        inst.state["pending_consumables"] = inst.state.get("pending_consumables", []) + ["double_tag"]
JOKER_REGISTRY["j_diet_cola"] = _DietCola()

# ── j_flash: +2 Mult permanently per shop reroll used ────────────────────────
# Tracks rerolls via on_reroll hook (called from shop.py reroll_shop)
class _Flash:
    def on_reroll(self, inst, ctx):
        inst.state["mult"] = inst.state.get("mult", 0) + 2
    def on_hand_scored(self, inst, ctx):
        ctx.mult += inst.state.get("mult", 0)
JOKER_REGISTRY["j_flash"] = _Flash()

# ── j_ceremonial: destroy Joker to right on blind select, gain 2x its sell value as Mult
class _Ceremonial:
    def on_blind_selected(self, inst, ctx):
        # Find this joker's index and destroy the one to its right
        # (handled via pending state — game.py applies after all hooks fire)
        inst.state["destroy_right"] = True
    def on_hand_scored(self, inst, ctx):
        ctx.mult += inst.state.get("mult", 0)
JOKER_REGISTRY["j_ceremonial"] = _Ceremonial()

# ── j_midas_mask: all played face cards become Gold during scoring ───────────
# Already in scaling.py; re-register here with correct behavior
class _MidasMask:
    def on_score_card(self, inst, card, ctx):
        if ctx.is_face_card(card) and not card.debuffed:
            card.enhancement = "Gold"
JOKER_REGISTRY["j_midas_mask"] = _MidasMask()

# ── j_certificate: when Blind selected, add random card with random enhancement
class _Certificate:
    def on_blind_selected(self, inst, ctx):
        inst.state.setdefault("pending_consumables", []).append("random_enhanced_card")
JOKER_REGISTRY["j_certificate"] = _Certificate()

# ── j_swashbuckler: Mult equals total sell value of all owned Jokers ─────────
class _Swashbuckler:
    def on_hand_scored(self, inst, ctx):
        total_sell = sum(j.state.get("sell_value", 2) for j in ctx.jokers)
        ctx.mult += total_sell
JOKER_REGISTRY["j_swashbuckler"] = _Swashbuckler()

# ── j_smeared_joker: already handled by pre_score flag above ─────────────────

# ── j_card_sharp: +3 mult if hand already played this round ──────────────────
class _CardSharp:
    def on_hand_scored(self, inst, ctx):
        if ctx.hand_type in inst.state.get("played_hands", set()):
            ctx.mult_mult *= 3
        played = inst.state.setdefault("played_hands", set())
        played.add(ctx.hand_type)
    def on_round_end(self, inst, ctx):
        inst.state["played_hands"] = set()
JOKER_REGISTRY["j_card_sharp"] = _CardSharp()

# ── j_reserved_parking: 1/2 chance +$1 per face card HELD IN HAND ────────────
class _ReservedParking:
    def on_hand_scored(self, inst, ctx):
        for c in ctx.all_cards:
            if ctx.is_face_card(c) and not c.debuffed and inst.chance().random() < 0.5:
                ctx.pending_money += 1
JOKER_REGISTRY["j_reserved_parking"] = _ReservedParking()

# ── j_throwback_fix: x0.25 per blind skipped since this joker owned ──────────
# (Already in mult.py as j_throwback — no override needed)

# ── j_oops_all_6s: Already registered above as j_oops_all_sixes ─────────────
# Add the canonical key alias
JOKER_REGISTRY["j_oops"] = JOKER_REGISTRY["j_oops_all_sixes"]
