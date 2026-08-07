"""
misc.py — Remaining jokers: retrigger mechanics, hand eval flags,
          blueprint/brainstorm, economy specials, and others.
"""
from .base import JOKER_REGISTRY, ScoreContext, JokerEffect, register_joker, JokerInstance, full_deck
from ..consumables import ALL_TAROTS, ALL_SPECTRALS
from ..card import Card
from ..constants import SUITS, SEALS

# ════════════════════════════════════════════════════════════════════════════
# RETRIGGER JOKERS
# These set ctx.card_retriggers[i] in on_score_card (fires during card loop).
# ════════════════════════════════════════════════════════════════════════════

# ── j_hack: retrigger 2s, 3s, 4s, 5s ────────────────────────────────────────
@register_joker("j_hack")
class _Hack(JokerEffect):
    def on_score_card(self, inst, card, ctx):
        if card.rank in (2, 3, 4, 5) and not card.debuffed:
            i = ctx.scoring_cards.index(card)
            ctx.card_retriggers[i] = ctx.card_retriggers.get(i, 0) + 1

# ── j_sock_and_buskin: retrigger all face cards ─────────────────────────────
@register_joker("j_sock_and_buskin")
class _SockAndBuskin(JokerEffect):
    def on_score_card(self, inst, card, ctx):
        if ctx.is_face_card(card) and not card.debuffed:
            i = ctx.scoring_cards.index(card)
            ctx.card_retriggers[i] = ctx.card_retriggers.get(i, 0) + 1

# ── j_hanging_chad: retrigger first scored card 2 extra times ───────────────
@register_joker("j_hanging_chad")
class _HangingChad(JokerEffect):
    state_defaults = {"fired": False}
    def on_score_card(self, inst, card, ctx):
        if not inst.state.get("fired"):
            inst.state["fired"] = True
            i = ctx.scoring_cards.index(card)
            ctx.card_retriggers[i] = ctx.card_retriggers.get(i, 0) + 2
    def on_round_end(self, inst, ctx):
        inst.state["fired"] = False

# ── j_dusk: retrigger all cards on last hand of round ────────────────────────
# Uses pre_score hook so retriggers are set before the card loop starts.
@register_joker("j_dusk")
class _Dusk(JokerEffect):
    def pre_score(self, inst, ctx):
        if ctx.hands_left == 0:
            for i in range(len(ctx.scoring_cards)):
                ctx.card_retriggers[i] = ctx.card_retriggers.get(i, 0) + 1

# ── j_seltzer: retrigger all cards for 10 hands, then self-destructs ────────
@register_joker("j_seltzer")
class _Seltzer(JokerEffect):
    state_defaults = {"hands": 10}
    def pre_score(self, inst, ctx):
        remaining = inst.state.get("hands", 10)
        if remaining > 0:
            for i in range(len(ctx.scoring_cards)):
                ctx.card_retriggers[i] = ctx.card_retriggers.get(i, 0) + 1
    def on_hand_scored(self, inst, ctx):
        inst.state["hands"] = inst.state.get("hands", 10) - 1
        if inst.state["hands"] <= 0:
            inst.state["destroyed"] = True

# ── j_mime: retrigger all held-in-hand card abilities ────────────────────────
@register_joker("j_mime")
class _Mime(JokerEffect):
    """Retriggers held-in-hand card abilities (Steel X1.5, Gold $3 at round
    end) — implemented engine-side via the retriggers_held capability flag
    (scoring.py doubles held Steel, game.py doubles held Gold)."""
    flags = frozenset({"retriggers_held"})

# ════════════════════════════════════════════════════════════════════════════
# HAND EVAL FLAG JOKERS
# Set ctx flags that hand_eval.py and scoring respect.
# ════════════════════════════════════════════════════════════════════════════

@register_joker("j_pareidolia")
class _Pareidolia(JokerEffect):
    def pre_score(self, inst, ctx):
        ctx.all_face_cards = True

@register_joker("j_four_fingers")
class _FourFingers(JokerEffect):
    def pre_score(self, inst, ctx):
        ctx.four_finger_mode = True
    def on_hand_scored(self, inst, ctx):
        pass  # Main effect in hand_eval; small chip bonus for holding joker

@register_joker("j_smeared_joker")
class _SmearedJoker(JokerEffect):
    def pre_score(self, inst, ctx):
        ctx.smear_suits = True

@register_joker("j_splash")
class _Splash(JokerEffect):
    def pre_score(self, inst, ctx):
        ctx.all_scoring_mode = True
        # Extend scoring_cards to include all played cards
        for card in ctx.all_cards:
            if card not in ctx.scoring_cards and not card.debuffed:
                ctx.scoring_cards.append(card)

@register_joker("j_shortcut")
class _Shortcut(JokerEffect):
    def pre_score(self, inst, ctx):
        ctx.shortcut_mode = True  # honoured in hand_eval when flag present

# ════════════════════════════════════════════════════════════════════════════
# BLUEPRINT / BRAINSTORM — copy adjacent joker effects
# Recursion guard prevents infinite loop when Blueprint copies Brainstorm
# which copies Blueprint (or vice versa).
# ════════════════════════════════════════════════════════════════════════════

_copy_depth = 0
_MAX_COPY_DEPTH = 3

# Every hook the engine dispatches (minus on_init, which seeds acquisition
# state and must NOT be copied — buying a Blueprint never re-inits its
# neighbor, and re-running on_init would reset the neighbor's live state).
_COPY_HOOKS = [
    "pre_score", "on_score_card", "on_hand_scored",
    "on_discard", "on_round_end", "on_blind_selected", "on_blind_skipped",
    "on_boss_beaten", "on_boss_ability_triggered",
    "on_sell", "on_other_sold", "on_shop_enter", "on_shop_leave",
    "on_reroll", "on_booster_opened", "on_booster_skipped",
    "on_planet_used", "on_tarot_used", "on_lucky_trigger",
    "on_card_added", "on_card_destroyed",
]

def _guarded_call(method_name, target, *args):
    """Call a joker effect method with recursion depth guard (Blueprints
    copying Blueprints must terminate). Uses the instance fire() path — the
    base JokerEffect guarantees the method exists (R2)."""
    global _copy_depth
    if _copy_depth >= _MAX_COPY_DEPTH:
        return
    _copy_depth += 1
    try:
        target.fire(method_name, *args)
    finally:
        _copy_depth -= 1

class _CopyJoker(JokerEffect):
    """Base for Blueprint / Brainstorm. Copies the target joker's effect for
    EVERY hook — not just scoring hooks (B6: the real game's copy covers
    discard / round-end / shop / booster hooks too, e.g. Blueprint next to
    Green Joker gains Mult per played hand). The copied hook fires with the
    TARGET as the acting instance, matching the real game (the neighbor's
    ability mutates the neighbor's own counter)."""

    def _jokers(self, inst, ctx):
        """The owned joker list: ctx.jokers during scoring; inst.game.jokers
        for ctx=None hooks (round end, shop, discard)."""
        if ctx is not None and getattr(ctx, "jokers", None):
            return ctx.jokers
        if inst.game is not None:
            return inst.game.jokers
        return []

    def _get_copy_target(self, inst, ctx):
        raise NotImplementedError

    def _copy(self, hook, inst, *args):
        # Resolve the owned-joker list from the real ScoreContext when one is
        # passed, else from inst.game — hook first args like `cards`/`card`/
        # `planet_name` are NOT contexts, so normalize them to None rather than
        # accidentally relying on them lacking a `.jokers` attribute.
        ctx = args[0] if args else None
        if not (ctx is not None and getattr(ctx, "jokers", None)):
            ctx = None
        target = self._get_copy_target(inst, ctx)
        if target is not None:
            _guarded_call(hook, target, *args)

# Generate one delegating method per hook on the concrete copy classes. The
# methods are bound class-level (like any other effect hook), so the audit's
# signature gate sees the correct (inst, ...) shapes.
for _hook in _COPY_HOOKS:
    def _make_delegator(name):
        def delegator(self, inst, *args):
            self._copy(name, inst, *args)
        return delegator
    setattr(_CopyJoker, _hook, _make_delegator(_hook))

@register_joker("j_blueprint")
class _Blueprint(_CopyJoker):
    """Copies the effect of the joker immediately to the right."""
    def _get_copy_target(self, inst, ctx):
        jokers = self._jokers(inst, ctx)
        idx = jokers.index(inst) if inst in jokers else -1
        if idx >= 0 and idx + 1 < len(jokers):
            return jokers[idx + 1]
        return None

@register_joker("j_brainstorm")
class _Brainstorm(_CopyJoker):
    """Copies the effect of the leftmost joker."""
    def _get_copy_target(self, inst, ctx):
        jokers = self._jokers(inst, ctx)
        if jokers and jokers[0] is not inst:
            return jokers[0]
        return None

# ════════════════════════════════════════════════════════════════════════════
# SURVIVABILITY / GAME-STATE JOKERS
# ════════════════════════════════════════════════════════════════════════════

@register_joker("j_mr_bones")
class _MrBones(JokerEffect):
    state_defaults = {"active": False}
    def on_hand_scored(self, inst, ctx):
        # Sets flag; game.py checks ctx.prevent_loss after scoring
        # Activation: if current_score / score_target >= 0.25
        inst.state["active"] = True  # game.py reads this
        ctx.prevent_loss = True      # always set; game.py validates threshold

# ── j_drivers_license: X3 Mult if 16+ Enhanced cards in your FULL deck ──────
# "Enhanced" excludes Stone (the real game's check skips Stone Card effects)
# and non-enhanced cards.
@register_joker("j_drivers_license")
class _DriversLicense(JokerEffect):
    def on_hand_scored(self, inst, ctx):
        enhanced = sum(
            1 for c in full_deck(inst.game)
            if c.enhancement and c.enhancement not in ("Base", "None", "Stone")
        )
        if enhanced >= 16:
            ctx.mult_mult *= 3

@register_joker("j_satellite")
class _Satellite(JokerEffect):
    state_defaults = {"planets_used": set()}
    def on_round_end(self, inst, ctx):
        n = len(inst.state.get("planets_used", set()))
        inst.state["pending_money"] = inst.state.get("pending_money", 0) + n
    def on_planet_used(self, inst, planet_name):
        if "planets_used" not in inst.state:
            inst.state["planets_used"] = set()
        inst.state["planets_used"].add(planet_name)

# The count is set by game.py before calling on_round_end (via joker state)
@register_joker("j_cloud_9")
class _Cloud9(JokerEffect):
    state_defaults = {"deck_nines": 0}
    def on_round_end(self, inst, ctx):
        nines = inst.state.get("deck_nines", 0)
        inst.state["pending_money"] = inst.state.get("pending_money", 0) + nines

# ── j_wee (wee joker): permanently gains +8 chips each time a 2 is scored ────
@register_joker("j_wee")
class _Wee(JokerEffect):
    state_defaults = {"chips": 0}
    def on_score_card(self, inst, card, ctx):
        if card.rank == 2 and not card.debuffed:
            inst.state["chips"] = inst.state.get("chips", 0) + 8
    def on_hand_scored(self, inst, ctx):
        ctx.chips += inst.state.get("chips", 0)

# ── j_stone_joker: +25 chips per Stone card in FULL deck ────────────────────
@register_joker("j_stone_joker")
class _StoneJoker(JokerEffect):
    def on_hand_scored(self, inst, ctx):
        stones = sum(1 for c in full_deck(inst.game) if c.enhancement == "Stone")
        ctx.chips += 25 * stones

# ════════════════════════════════════════════════════════════════════════════
# PROBABILISTIC / TAROT-CREATION JOKERS
# These use pending_consumables to signal the game loop (M1 B1: they park
# REAL keys / object tuples, never unresolvable placeholder strings — game.py
# `_grant_pending` materializes them).
# ════════════════════════════════════════════════════════════════════════════

# ── Reward-draw helpers ──────────────────────────────────────────────────────
# The real game draws these through in-game create_card / poll_consumable call
# sites that balatro-seed does not pin, so every draw goes through the
# documented sim-internal CHANCE_NODE (inst.chance()) — deterministic per seed
# in seed mode.

def _random_tarot(inst) -> str:
    """A random real Tarot key (8-Ball, Superposition, Cartomancer, ...)."""
    return inst.chance().choice(ALL_TAROTS)

def _random_spectral(inst) -> str:
    """A random real Spectral key (Seance, Sixth Sense)."""
    return inst.chance().choice(ALL_SPECTRALS)

def _random_common_joker(inst) -> str:
    """A random Common joker key (Riff-Raff), honoring BANNED_JOKERS."""
    from ..shop import JOKER_CATALOGUE, BANNED_JOKERS
    pool = [k for k, v in JOKER_CATALOGUE.items()
            if v["rarity"] == "Common" and k not in BANNED_JOKERS]
    return inst.chance().choice(pool)

def _random_playing_card(inst) -> Card:
    """A random rank/suit playing card (Marble / Certificate bases)."""
    return Card(inst.chance().randint(2, 14), inst.chance().choice(SUITS))

@register_joker("j_8_ball")
class _EightBall(JokerEffect):
    def on_score_card(self, inst, card, ctx):
        if card.rank == 8 and not card.debuffed and inst.chance().random() < 0.25:
            ctx.pending_consumables.append(_random_tarot(inst))

@register_joker("j_seance")
class _Seance(JokerEffect):
    def on_hand_scored(self, inst, ctx):
        if ctx.hand_type == "Straight Flush":
            ctx.pending_consumables.append(_random_spectral(inst))

# Created jokers park ("joker", key, edition) tuples; game.py grants them into
# the joker slots AFTER the blind-selected hook loop finishes, so a created
# joker's own on_blind_selected never fires for the same blind (real game).
@register_joker("j_riff_raff")
class _RiffRaff(JokerEffect):
    def on_blind_selected(self, inst, ctx):
        pc = inst.state.setdefault("pending_consumables", [])
        pc.append(("joker", _random_common_joker(inst), "None"))
        pc.append(("joker", _random_common_joker(inst), "None"))

@register_joker("j_superposition")
class _Superposition(JokerEffect):
    def on_hand_scored(self, inst, ctx):
        has_ace = any(c.rank == 14 for c in ctx.scoring_cards if not c.debuffed)
        if "Straight" in ctx.hand_type and has_ace:
            ctx.pending_consumables.append(_random_tarot(inst))

@register_joker("j_sixth_sense")
class _SixthSense(JokerEffect):
    state_defaults = {"used": False}
    def on_hand_scored(self, inst, ctx):
        if inst.state.get("used"):
            return
        if len(ctx.scoring_cards) == 1 and ctx.scoring_cards[0].rank == 6:
            # Real destroy (B6): the played 6 is removed from the run
            # permanently — the game's ctx.destroyed mechanism (same channel
            # as Glass shatter) removes it from hand/deck/spent and fires
            # on_card_destroyed for face cards.
            ctx.destroyed.append(ctx.scoring_cards[0])
            ctx.pending_consumables.append(_random_spectral(inst))
            inst.state["used"] = True

# ── j_hallucination: 1/2 chance of a random Tarot per Booster pack opened ────
# (M1 B2: dispatched from shop._open_booster; parks on its own state like the
# other reward-creating hooks, then shop.py grants it via _grant_pending.)
@register_joker("j_hallucination")
class _Hallucination(JokerEffect):
    def on_booster_opened(self, inst, ctx):
        if inst.chance().random() < 0.5:
            inst.state.setdefault("pending_consumables", []).append(_random_tarot(inst))

@register_joker("j_cartomancer")
class _Cartomancer(JokerEffect):
    def on_blind_selected(self, inst, ctx):
        inst.state.setdefault("pending_consumables", []).append(_random_tarot(inst))

@register_joker("j_astronomer")
class _Astronomer(JokerEffect):
    """Planet cards cost $0 in the shop — free_planets capability flag read by
    shop._random_shop_item (R3)."""
    flags = frozenset({"free_planets"})

@register_joker("j_burnt_joker")
class _BurntJoker(JokerEffect):
    state_defaults = {"counts": {}, "most_played": None}
    def on_blind_selected(self, inst, ctx):
        most_played = inst.state.get("most_played")
        if most_played:
            inst.state["planet_upgrade"] = most_played  # game.py applies this
    def on_hand_scored(self, inst, ctx):
        # Track most played hand
        counts = inst.state.setdefault("counts", {})
        counts[ctx.hand_type] = counts.get(ctx.hand_type, 0) + 1
        inst.state["most_played"] = max(counts, key=counts.get)

# ── j_invisible_joker: after 2 rounds, SELL to duplicate a random joker ──────
# Real game: the duplicate copies the target's properties but never the
# Negative edition (wiki subtext "Removes Negative from copy"). Applied
# directly via inst.game — sell_joker pops the instance before firing on_sell,
# so a state-parked reward would never be read by the game loop.
@register_joker("j_invisible")
class _InvisibleJoker(JokerEffect):
    state_defaults = {"rounds": 0}
    def on_round_end(self, inst, ctx):
        inst.state["rounds"] = inst.state.get("rounds", 0) + 1
    def on_sell(self, inst, ctx):
        game = inst.game
        if game is None or inst.state.get("rounds", 0) < 2 or not game.jokers:
            return
        import copy as _copy
        target = inst.chance().choice(game.jokers)
        ed = target.edition if target.edition != "Negative" else "None"
        # grant_joker with fire_init=False — the duplicate copies the target's
        # live state; on_init would reset it (R5).
        dup = game.grant_joker(target.key, ed, fire_init=False)
        if dup is None:
            return
        dup.state = _copy.deepcopy(target.state)
        if target.key in ("j_invisible", "j_invisible_joker"):
            # Real game: a duplicated Invisible Joker starts at 0/2 again
            dup.state["rounds"] = 0
# Registered under the canonical catalogue key (what the shop sells) AND the
# legacy internal key — same dual-key pattern as j_oops; synergy.py / env_v7
# reward heuristics still reference the legacy spelling.
JOKER_REGISTRY["j_invisible_joker"] = JOKER_REGISTRY["j_invisible"]

# ── j_perkeo: Negative copy of a random consumable at end of shop ────────────
# Real game: "Creates a Negative copy of 1 random consumable card in your
# possession at the end of the shop". Negative consumables grant +1 slot, so
# the copy always fits even when the area is maxed — approximated as an append
# past the slot cap (the sim does not track per-consumable editions). Hook
# dispatch is wired in M1 B2 (on_shop_leave); the resolver is correct now.
@register_joker("j_perkeo")
class _Perkeo(JokerEffect):
    def on_shop_leave(self, inst, ctx):
        game = inst.game
        if game is None or not game.consumable_hand:
            return
        key = inst.chance().choice(game.consumable_hand)
        game.consumable_hand.append(key)

# ════════════════════════════════════════════════════════════════════════════
# BOSS BLIND EFFECTS
# ════════════════════════════════════════════════════════════════════════════

# ── j_chicot: disables the effect of every Boss Blind (Legendary) ────────────
# (game._boss_effects_on) — matching the real game's permanent passive. No
# hook needed; the class exists so the joker resolves in the registry.
@register_joker("j_chicot")
class _Chicot(JokerEffect):
    """Disables the effect of every Boss Blind (Legendary) — implemented
    engine-side via the disables_bosses capability flag (game._boss_effects_on)."""
    flags = frozenset({"disables_bosses"})

@register_joker("j_matador")
class _Matador(JokerEffect):
    def on_boss_ability_triggered(self, inst, ctx):
        inst.state["pending_money"] = inst.state.get("pending_money", 0) + 8

@register_joker("j_luchador")
class _Luchador(JokerEffect):
    def on_sell(self, inst, ctx):
        # Set a GAME-level flag: the joker instance is destroyed on sale, so the
        # flag must outlive it. game._boss_effects_on() reads it until the next
        # Boss Blind resolves (_end_round clears it).
        if inst.game is not None:
            inst.game.boss_disabled_override = True

# ════════════════════════════════════════════════════════════════════════════
# DECK MODIFICATION JOKERS
# ════════════════════════════════════════════════════════════════════════════

@register_joker("j_marble")
class _Marble(JokerEffect):
    def on_blind_selected(self, inst, ctx):
        card = _random_playing_card(inst)
        card.enhancement = "Stone"
        inst.state.setdefault("pending_consumables", []).append(("card", card))

# ── j_dna: if first hand has 1 card, add permanent copy to deck and hand ────
# Real game: "If first hand of round has only 1 card, add a permanent copy to
# deck and draw it to hand" — the copy keeps the card's modifiers and stays in
# the run deck (the sim's deck persists across blinds).
@register_joker("j_dna")
class _DNA(JokerEffect):
    state_defaults = {"used": False}
    def on_hand_scored(self, inst, ctx):
        if inst.state.get("used"):
            return
        if len(ctx.scoring_cards) == 1:
            ctx.pending_consumables.append(("hand_card", ctx.scoring_cards[0].copy()))
            inst.state["used"] = True

# ── j_oops (catalogue key "j_oops", real name "Oops! All 6s"): doubles all
# listed probabilities via the doubles_lucky capability flag.
@register_joker("j_oops")
class _OopsAllSixes(JokerEffect):
    """Oops! All 6s: doubles listed probabilities — implemented engine-side via
    the doubles_lucky capability flag (scoring.py Lucky + Glass shatter)."""
    flags = frozenset({"doubles_lucky"})

@register_joker("j_trading_card")
class _TradingCard(JokerEffect):
    state_defaults = {"used": False}
    def on_discard(self, inst, cards, ctx):
        if inst.state.get("used"):
            return
        inst.state["used"] = True
        inst.state["pending_money"] = inst.state.get("pending_money", 0) + 3
        if cards:
            # Real destroy (B6): the random discarded card is removed from the
            # run permanently. Drawn from inst.chance() — per-node seeded RNG
            # (was `import random`, a genuine seed-exactness leak). Parks a
            # ("destroy_card", card) tuple that game._discard → _grant_pending
            # materializes (removes from deck/hand/spent, fires on_card_destroyed).
            target = inst.chance().choice(cards)
            inst.state.setdefault("pending_consumables", []).append(("destroy_card", target))
    def on_round_end(self, inst, ctx):
        inst.state["used"] = False

# ════════════════════════════════════════════════════════════════════════════
# ECONOMY / GAME STATE JOKERS
# ════════════════════════════════════════════════════════════════════════════

# ── j_merry_andy: +3 discards, -1 hand size (passive, constant while owned) ──
@register_joker("j_merry_andy")
class _MerryAndy(JokerEffect):
    """+3 discards, -1 hand size (constant while owned) — declared as a
    passive so game._start_blind applies it without key scans (R3)."""
    def passives(self, inst) -> dict:
        return {"discards": 3, "hand_size": -1}

@register_joker("j_troubadour")
class _Troubadour(JokerEffect):
    """+2 hand size, -1 hand per round (constant while owned) — passive (R3)."""
    def passives(self, inst) -> dict:
        return {"hand_size": 2, "hands": -1}

@register_joker("j_credit_card")
class _CreditCard(JokerEffect):
    """Go up to -$20 in debt — debt capability flag read by shop.buy_item (R3)."""
    flags = frozenset({"debt"})

@register_joker("j_turtle_bean")
class _TurtleBean(JokerEffect):
    """+5 hand size, -1 per round until it self-destructs at 0 — hand size is
    a passive (R3); decay + destruction fire on_round_end."""
    state_defaults = {"bonus": 5}
    def passives(self, inst) -> dict:
        return {"hand_size": inst.state.get("bonus", 5)}
    def on_round_end(self, inst, ctx):
        inst.state["bonus"] = max(0, inst.state.get("bonus", 5) - 1)
        if inst.state["bonus"] == 0:
            inst.state["destroyed"] = True

@register_joker("j_juggler")
class _Juggler(JokerEffect):
    """+1 hand size (constant while owned) — passive (R3)."""
    def passives(self, inst) -> dict:
        return {"hand_size": 1}

@register_joker("j_drunkard")
class _Drunkard(JokerEffect):
    """+1 discard per round (constant while owned) — passive (R3)."""
    def passives(self, inst) -> dict:
        return {"discards": 1}

@register_joker("j_chaos")
class _Chaos(JokerEffect):
    state_defaults = {"free_reroll": False}
    def on_shop_enter(self, inst, ctx):
        inst.state["free_reroll"] = True

@register_joker("j_gift_card")
class _GiftCard(JokerEffect):
    state_defaults = {"pending_shop_buff": False}
    def on_round_end(self, inst, ctx):
        inst.state["pending_shop_buff"] = True  # shop applies extra $1 to items

@register_joker("j_egg")
class _Egg(JokerEffect):
    state_defaults = {"sell_value": 1}
    def on_round_end(self, inst, ctx):
        inst.state["sell_value"] = inst.state.get("sell_value", 1) + 3

# ── j_delayed_grat: earn $2 per remaining discard if none used by round end ──
# Note: on_round_end receives ctx=None, so we track discards_left via joker state
@register_joker("j_delayed_grat")
class _DelayedGrat(JokerEffect):
    state_defaults = {"discards_left": 3, "discarded": False}
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

@register_joker("j_faceless")
class _Faceless(JokerEffect):
    def on_discard(self, inst, cards, ctx):
        face_count = sum(1 for c in cards if c.is_face_card)
        if face_count >= 3:
            inst.state["pending_money"] = inst.state.get("pending_money", 0) + 5

@register_joker("j_to_do_list")
class _ToDoList(JokerEffect):
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

@register_joker("j_showman")
class _Showman(JokerEffect):
    """Joker/Tarot/Planet/Spectral may appear multiple times — allow_dupes
    capability flag read by shop._has_showman (R3)."""
    flags = frozenset({"allow_dupes"})

# Real game: "Sell this card to create a free Double Tag". The Double Tag
# queues a copy of the next selected skip-blind Tag — the same flag the
# t_double skip path sets (game._skip_blind). Applied directly: sell_joker
# pops the instance before firing on_sell, so no state-parked reward is read.
@register_joker("j_diet_cola")
class _DietCola(JokerEffect):
    def on_sell(self, inst, ctx):
        if inst.game is not None:
            inst.game.double_tag_active = True

# ── j_flash: +2 Mult permanently per shop reroll used ────────────────────────
# Tracks rerolls via on_reroll hook (called from shop.py reroll_shop)
@register_joker("j_flash")
class _Flash(JokerEffect):
    state_defaults = {"mult": 0}
    def on_reroll(self, inst, ctx):
        inst.state["mult"] = inst.state.get("mult", 0) + 2
    def on_hand_scored(self, inst, ctx):
        ctx.mult += inst.state.get("mult", 0)

@register_joker("j_ceremonial")
class _Ceremonial(JokerEffect):
    state_defaults = {"mult": 0, "destroy_right": False}
    def on_blind_selected(self, inst, ctx):
        # Find this joker's index and destroy the one to its right
        # (handled via pending state — game.py applies after all hooks fire)
        inst.state["destroy_right"] = True
    def on_hand_scored(self, inst, ctx):
        ctx.mult += inst.state.get("mult", 0)

# ── j_midas_mask: all played face cards become Gold during scoring ───────────
@register_joker("j_midas_mask")
class _MidasMask(JokerEffect):
    def on_score_card(self, inst, card, ctx):
        if ctx.is_face_card(card) and not card.debuffed:
            card.enhancement = "Gold"

# ── j_certificate: when round begins, add random card with random seal ───────
# Real text (wiki j_certificate): "When round begins, add a random playing card
# with a random seal to your hand". The card also stays in the run deck for
# future rounds (hand -> deck at the next blind's start).
@register_joker("j_certificate")
class _Certificate(JokerEffect):
    def on_blind_selected(self, inst, ctx):
        card = _random_playing_card(inst)
        card.seal = inst.chance().choice([s for s in SEALS if s != "None"])
        inst.state.setdefault("pending_consumables", []).append(("hand_card", card))

@register_joker("j_swashbuckler")
class _Swashbuckler(JokerEffect):
    def on_hand_scored(self, inst, ctx):
        total_sell = sum(j.state.get("sell_value", 2) for j in ctx.jokers)
        ctx.mult += total_sell

@register_joker("j_card_sharp")
class _CardSharp(JokerEffect):
    state_defaults = {"played_hands": set()}
    def on_hand_scored(self, inst, ctx):
        if ctx.hand_type in inst.state.get("played_hands", set()):
            ctx.mult_mult *= 3
        played = inst.state.setdefault("played_hands", set())
        played.add(ctx.hand_type)
    def on_round_end(self, inst, ctx):
        inst.state["played_hands"] = set()

# ── j_reserved_parking: 1/2 chance +$1 per face card held in hand ───────────
@register_joker("j_reserved_parking")
class _ReservedParking(JokerEffect):
    def on_hand_scored(self, inst, ctx):
        for c in ctx.held_cards:
            if ctx.is_face_card(c) and not c.debuffed and inst.chance().random() < 0.5:
                ctx.pending_money += 1

