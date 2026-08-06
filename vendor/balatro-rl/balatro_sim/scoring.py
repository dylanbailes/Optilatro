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


def _score_single_card(card: Card, ctx: ScoreContext, jokers: list[JokerInstance]):
    """Score one card pass (used for base scoring + each retrigger)."""
    ctx.chips += card.base_chips

    # Enhancement effects
    if card.enhancement == "Bonus":
        ctx.chips += 30
    elif card.enhancement == "Mult":
        ctx.mult += 4
    elif card.enhancement == "Glass":
        ctx.mult_mult *= 2.0
    elif card.enhancement == "Lucky":
        rng = _ctx_rng(ctx)
        if rng.random() < 1/4:   # real Balatro: 1 in 4 chance
            ctx.mult += 20
        if rng.random() < 1/15:
            ctx.pending_money += 20
    elif card.enhancement == "Steel":
        ctx.mult_mult *= 1.5  # applies while held in hand; here approximated per scoring pass

    # Edition effects on card
    if card.edition == "Foil":
        ctx.chips += 50
    elif card.edition == "Holographic":
        ctx.mult += 10
    elif card.edition == "Polychrome":
        ctx.mult_mult *= 1.5

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
        jokers=jokers,
        hands_left=hands_left,
        discards_left=discards_left,
        dollars=dollars,
        ante=ante,
        deck_remaining=deck_remaining,
        planet_levels=planet_levels,
        game=game,
    )

    # Pre-score: jokers that set flags / retrigger counts before the card loop
    # (Blueprint/Brainstorm copy effects here; retrigger jokers like Dusk set
    #  card_retriggers for all cards if on last hand)
    for joker in jokers:
        effect = __import__('balatro_sim.jokers.base', fromlist=['JOKER_REGISTRY']).JOKER_REGISTRY.get(joker.key)
        if effect and hasattr(effect, 'pre_score'):
            effect.pre_score(joker, ctx)

    # Score each card + retriggers
    for i, card in enumerate(scoring_cards):
        if card.debuffed:
            continue

        # Base scoring pass
        _score_single_card(card, ctx, jokers)

        # Red seal: retrigger this card once
        if card.seal == "Red":
            _score_single_card(card, ctx, jokers)

        # Joker-initiated retriggers (e.g. Hack, SockAndBuskin, HangingChad)
        extra = ctx.card_retriggers.get(i, 0)
        for _ in range(extra):
            _score_single_card(card, ctx, jokers)

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
    score = int(total_chips * max(total_mult, 0))
    return score, ctx
