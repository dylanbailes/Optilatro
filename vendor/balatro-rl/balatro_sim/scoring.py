"""
scoring.py — Chip x mult scoring engine.

Scoring order (mirrors Balatro source):
  1. Base chips + base mult from hand type (adjusted for planet level)
  2. Pre-score phase: jokers set retrigger counts, hand eval flags (Blueprint, etc.)
  3. For each scoring card (in order played):
     a. Card base chips
     b. Enhancement effects (Bonus +30, Mult +4, Glass x2 mult, etc.)
     c. Edition effects on card (Foil +50 chips, Holo +10 mult, Poly x1.5 mult)
     d. Seal effects (Red seal retrigger, Blue seal planet, etc.)
     e. Each joker fires on_score_card(card, ctx)
     f. Repeat (a-e) for each extra retrigger in ctx.card_retriggers[i]
  4. After all cards: each joker fires on_hand_scored(ctx)
  5. Joker editions applied
  6. Final score = (base_chips + ctx.chips) * (base_mult + ctx.mult) * ctx.mult_mult
"""
import random as _random

from .card import Card
from .constants import HAND_BASE, HAND_LEVEL_CHIPS, HAND_LEVEL_MULT
from .jokers.base import JokerInstance, ScoreContext
from .seed_rng import CHANCE_NODE


def _ctx_rng(ctx: ScoreContext):
    """The game's per-node 'chance' source, or module random when the hand is
    scored without a game (direct-call tests)."""
    if ctx.game is not None:
        return ctx.game.rng.node(CHANCE_NODE)
    return _random


def _lucky_trigger(jokers: list[JokerInstance], ctx: ScoreContext):
    """Fire on_lucky_trigger on every owned joker (Lucky Cat: X0.25 per
    successful Lucky trigger — one call per successful roll). The base
    JokerEffect guarantees the hook exists; no hasattr needed (R2)."""
    for joker in jokers:
        joker.fire("on_lucky_trigger", ctx)


def _score_single_card(card: Card, ctx: ScoreContext, jokers: list[JokerInstance],
                       oops: bool = False):
    """Score one card pass (used for base scoring + each retrigger).

    oops: Oops! All 6s owned — doubles listed probabilities (Lucky card rolls;
    Glass shatter is handled separately)."""
    ctx.chips += card.base_chips
    # Hiker: every played card permanently gains +5 chips (stored on the card
    # by scaling._Hiker); applied on every scoring pass like the real game.
    ctx.chips += getattr(card, "bonus_chips", 0)

    # Enhancement effects
    if card.enhancement == "Bonus":
        ctx.chips += 30
    elif card.enhancement == "Mult":
        ctx.mult += 4
    elif card.enhancement == "Glass":
        ctx.mult_mult *= 2.0
    elif card.enhancement == "Lucky":
        # Real Balatro: 1-in-5 chance for +20 Mult, 1-in-15 chance for $20
        # (two independent rolls; balatro-rs game.rs prob_roll(1,5)/(1,15), ref
        # doc §6). Oops! All 6s doubles both (2/5, 2/15). Lucky Cat gains
        # X0.25 per SUCCESSFUL TRIGGER (each successful roll fires it — both
        # rolling true grants X0.5, matching the real lucky_trigger loop).
        rng = _ctx_rng(ctx)
        if rng.random() < (0.4 if oops else 0.2):
            ctx.mult += 20
            _lucky_trigger(jokers, ctx)
        if rng.random() < (2/15 if oops else 1/15):
            ctx.pending_money += 20
            _lucky_trigger(jokers, ctx)
    # NOTE: Steel is NOT scored here — it is a held-in-hand effect applied in
    # the held-in-hand pass of score_hand (B3 fix: held, not scored).
    # Edition effects on card
    if card.edition == "Foil":
        ctx.chips += 50
    elif card.edition == "Holographic":
        ctx.mult += 10
    elif card.edition == "Polychrome":
        ctx.mult_mult *= 1.5

    # Gold seal: $3 when this card is SCORED (doc §8). This is per scoring
    # pass, so Red seal and retrigger jokers multiply it like any other scored
    # ability (§3.1 fix — was wrongly paid as a held-at-round-end effect).
    if card.seal == "Gold":
        ctx.pending_money += 3

    # Jokers: on_score_card
    for joker in jokers:
        joker.on_score_card(card, ctx)


def score_hand(
    scoring_cards: list[Card],
    all_cards: list[Card],
    hand_type: str,
    jokers: list[JokerInstance],
    planet_levels: dict[str, int],
    hands_left: int,
    discards_left: int,
    dollars: int,
    ante: int,
    deck_remaining: int,
    half_base: bool = False,
    game=None,
    held_cards: list[Card] | None = None,
) -> tuple[int, ScoreContext]:
    """
    Compute the total score for a played hand.

    Returns:
        (int score, ScoreContext) — score is chips*mult floored; ctx holds
        side-effects like pending_money and prevent_loss.
    """
    base_chips, base_mult = HAND_BASE.get(hand_type, (5, 1))

    # Apply planet card level bonuses
    level = planet_levels.get(hand_type, 1)
    if level > 1:
        base_chips += HAND_LEVEL_CHIPS.get(hand_type, 0) * (level - 1)
        base_mult  += HAND_LEVEL_MULT.get(hand_type, 0)  * (level - 1)

    # The Flint: base chips and mult for the played hand are halved for the round
    if half_base:
        base_chips //= 2
        base_mult //= 2

    ctx = ScoreContext(
        chips=0.0,
        mult=0.0,
        mult_mult=1.0,
        hand_type=hand_type,
        scoring_cards=scoring_cards,
        all_cards=all_cards,
        held_cards=held_cards or [],
        jokers=jokers,
        hands_left=hands_left,
        discards_left=discards_left,
        dollars=dollars,
        ante=ante,
        deck_remaining=deck_remaining,
        planet_levels=planet_levels,
        game=game,
    )

    # Oops! All 6s owned — doubles listed probabilities (Glass shatter, Lucky).
    # Capability flag (R3), not a key scan.
    oops = any(j.has_flag("doubles_lucky") for j in jokers)

    # Pre-score: jokers that set flags / retrigger counts before the card loop
    # (Blueprint/Brainstorm copy effects here; retrigger jokers like Dusk set
    #  card_retriggers for all cards if on last hand)
    for joker in jokers:
        joker.fire("pre_score", ctx)

    # Score each card + retriggers
    for i, card in enumerate(scoring_cards):
        if card.debuffed:
            continue

        # Base scoring pass
        _score_single_card(card, ctx, jokers, oops)

        # Red seal: retrigger this card once
        if card.seal == "Red":
            _score_single_card(card, ctx, jokers, oops)

        # Joker-initiated retriggers (e.g. Hack, SockAndBuskin, HangingChad)
        extra = ctx.card_retriggers.get(i, 0)
        for _ in range(extra):
            _score_single_card(card, ctx, jokers, oops)

    # Held-in-hand effects: Steel cards give X1.5 Mult while HELD in hand
    # (B3 fix — previously they fired on scored cards). Mime retriggers
    # held-in-hand abilities (capability flag, R3), doubling each Steel proc.
    mime = any(j.has_flag("retriggers_held") for j in jokers)
    held_steel = [c for c in ctx.held_cards
                  if c.enhancement == "Steel" and not c.debuffed]
    for c in held_steel:
        # Mime retriggers held-in-hand abilities; a Red seal on the card itself
        # retriggers them too (RULING-R: Steel X2.25 when Red-sealed).
        triggers = 1 + (1 if mime else 0) + (1 if c.seal == "Red" else 0)
        for _ in range(triggers):
            ctx.mult_mult *= 1.5

    # Glass shatter: 1-in-4 per non-debuffed Glass card scored, rolled once per
    # card per hand after all scoring passes (real-game timing). Oops! All 6s
    # doubles the chance. Shattered cards are collected for the game to remove
    # permanently — they never return to the deck.
    rng = _ctx_rng(ctx)
    for card in scoring_cards:
        if card.enhancement == "Glass" and not card.debuffed:
            if rng.random() < (0.5 if oops else 0.25):
                ctx.destroyed.append(card)

    # Jokers: on_hand_scored (fires after all cards)
    for joker in jokers:
        joker.on_hand_scored(ctx)

    # Joker editions (fire after joker effects)
    for joker in jokers:
        if joker.edition == "Foil":
            ctx.chips += 50
        elif joker.edition == "Holographic":
            ctx.mult += 10
        elif joker.edition == "Polychrome":
            ctx.mult_mult *= 1.5
        elif joker.edition == "Negative":
            pass  # Negative gives +1 joker slot, no scoring effect

    total_chips = base_chips + ctx.chips
    total_mult  = (base_mult + ctx.mult) * ctx.mult_mult
    # Observatory: Planet cards in the consumable area give X1.5 Mult for
    # their specified poker hand.
    if game is not None and "v_observatory" in game.vouchers:
        from .consumables import PLANET_HAND
        hand_to_planet = {v: k for k, v in PLANET_HAND.items()}
        if hand_to_planet.get(hand_type) in game.consumable_hand:
            total_mult *= 1.5
    score = int(total_chips * max(total_mult, 0))
    return score, ctx
