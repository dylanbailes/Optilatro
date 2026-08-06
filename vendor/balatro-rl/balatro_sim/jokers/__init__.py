"""
jokers/ — Joker effect implementations.

JOKER_REGISTRY maps joker key -> singleton effect object.
Import order matters: later imports override earlier ones for the same key.
mult.py contains the canonical implementations for most scoring jokers and
is imported last so its implementations take precedence.

Trigger points:
  pre_score(context)               — fires before card loop (retrigger setup, flags)
  on_score_card(card, context)     — fires once per scoring card
  on_hand_scored(context)          — fires after all cards scored
  on_discard(cards, context)       — fires when player discards
  on_round_end(context)            — fires at end of round (cash out)
  on_blind_selected(context)       — fires when blind is selected
  on_boss_beaten(context)          — fires when boss blind is beaten
  on_planet_used(planet, context)  — fires when planet card is used
  on_tarot_used(context)           — fires when tarot card is used
  on_sell(context)                 — fires when this joker is sold
  on_shop_enter(context)           — fires when shop is entered
  on_shop_leave(context)           — fires when shop is left
  on_lucky_trigger(context)        — fires when a Lucky card triggers
  on_card_destroyed(card, context) — fires when a card is destroyed
  on_card_added(context)           — fires when a card is added to deck
  on_blind_skipped(context)        — fires when a blind is skipped
"""
from .base import JOKER_REGISTRY, JokerInstance, register_joker

# Import order: later imports win on duplicate keys.
# economy/chips/scaling/hand_type/misc provide broad coverage;
# mult.py is last so its carefully-tuned implementations take final precedence.
from . import economy     # noqa: F401  — money jokers
from . import scaling     # noqa: F401  — persistent state jokers
from . import hand_type   # noqa: F401  — hand-type conditional jokers
from . import misc        # noqa: F401  — retrigger, blueprint, special mechanics
from . import chips       # noqa: F401  — flat bonus jokers
from . import mult        # noqa: F401  — mult/xMult jokers (canonical, loads last)
