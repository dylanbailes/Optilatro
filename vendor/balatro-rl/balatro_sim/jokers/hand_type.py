"""
hand_type.py — Jokers that modify or respond to poker hand types.
"""
from .base import JOKER_REGISTRY, ScoreContext

# Many hand type jokers already implemented in chips.py and scaling.py:
# j_jolly, j_zany, j_mad, j_crazy (mult bonuses for Pair/Three/TwoPair/Straight)
# j_sly, j_wily, j_clever, j_devious, j_crafty (chip bonuses for hand types)
# j_duo, j_trio, j_family, j_order, j_tribe (small bonuses for hand types)

# ── j_even_steven: already in economy.py ─────────────────────────────────────

# ── j_odd_todd: already in economy.py ────────────────────────────────────────

# ── j_scholar: already in economy.py ─────────────────────────────────────────

# ── j_business_card: already in economy.py ───────────────────────────────────

# ── j_reserved_parking: already in economy.py ────────────────────────────────

# ── j_mail_in_rebate: earn $3 per discarded rank, max one rank per round ────
class _MailInRebate:
    def on_discard(self, inst, cards, ctx):
        for card in cards:
            if "rebate_rank" not in inst.state:
                inst.state["rebate_rank"] = card.rank
                inst.state["pending_money"] = inst.state.get("pending_money", 0) + 3
JOKER_REGISTRY["j_mail_in_rebate"] = _MailInRebate()

# ── j_to_the_moon: already in economy.py ─────────────────────────────────────

# ── j_hallucination: already stubbed in scaling.py ───────────────────────────

# ── j_fortune_teller: already in scaling.py ──────────────────────────────────

# ── j_juggler: already stubbed in scaling.py ─────────────────────────────────

# ── j_drunkard: already stubbed in scaling.py ────────────────────────────────

# ── j_stone: already stubbed in scaling.py ───────────────────────────────────

# ── j_golden: already in economy.py ──────────────────────────────────────────

# ── j_lucky_cat: already in scaling.py ───────────────────────────────────────

# ── j_baseball: already stubbed in scaling.py ────────────────────────────────

# ── j_bull: already in scaling.py ────────────────────────────────────────────

# ── j_diet_cola: already stubbed in scaling.py ───────────────────────────────

# ── j_trading: already stubbed in scaling.py ─────────────────────────────────

# ── j_flash: already stubbed in scaling.py ───────────────────────────────────

# ── j_popcorn: already in scaling.py ─────────────────────────────────────────

# ── j_spare_trousers: already in scaling.py ──────────────────────────────────

# ── j_ancient: already in scaling.py ─────────────────────────────────────────

# ── j_ramen: already in scaling.py ───────────────────────────────────────────

# ── j_walkie_talkie: already in scaling.py ───────────────────────────────────

# ── j_seltzer: already stubbed in scaling.py ─────────────────────────────────

# ── j_castle: already in scaling.py ──────────────────────────────────────────

# ── j_smiley: already in chips.py ────────────────────────────────────────────

# ── j_campfire: already in scaling.py ────────────────────────────────────────

# ── j_ticket: already in scaling.py ──────────────────────────────────────────

# ── j_mr_bones: already stubbed in scaling.py ────────────────────────────────

# ── j_acrobat: already in chips.py ───────────────────────────────────────────

# ── j_sock_and_buskin: already stubbed in scaling.py ─────────────────────────

# ── j_swashbuckler: already in scaling.py ────────────────────────────────────

# ── j_troubadour: already stubbed in scaling.py ──────────────────────────────

# ── j_certificate: already stubbed in scaling.py ─────────────────────────────

# ── j_smeared_joker: already stubbed in scaling.py ───────────────────────────

# ── j_throwback: already in scaling.py ───────────────────────────────────────

# ── j_hanging_chad: already stubbed in scaling.py ────────────────────────────

# ── j_rough_gem: already in scaling.py ───────────────────────────────────────

# ── j_bloodstone: already in scaling.py ──────────────────────────────────────

# ── j_arrowhead: already in scaling.py ───────────────────────────────────────

# ── j_onyx_agate: already in scaling.py ──────────────────────────────────────

# ── j_glass_joker: already in scaling.py ─────────────────────────────────────

# ── j_showman: already stubbed in scaling.py ─────────────────────────────────

# ── j_flower_pot: already in scaling.py ──────────────────────────────────────

# ── j_blueprint: already stubbed in scaling.py ───────────────────────────────

# ── j_wee: already stubbed in scaling.py ─────────────────────────────────────

# ── j_merry_andy: already stubbed in chips.py/scaling.py ─────────────────────

# ── j_obelisk: already stubbed in scaling.py ─────────────────────────────────

# ── j_midas_mask: already in scaling.py ──────────────────────────────────────

# ── j_luchador: already stubbed in scaling.py ────────────────────────────────

# ── j_photograph: already in scaling.py ──────────────────────────────────────

# ── j_gift_card: already stubbed in economy.py/scaling.py ────────────────────

# ── j_turtle_bean: already stubbed in scaling.py ─────────────────────────────

# ── j_erosion: already in scaling.py ─────────────────────────────────────────

# ── j_to_the_moon: already in economy.py ─────────────────────────────────────

# ── j_hallucination: already stubbed ─────────────────────────────────────────

# ── j_fortune_teller: already in scaling.py ──────────────────────────────────

# ── j_juggler: already stubbed ───────────────────────────────────────────────

# ── j_drunkard: already stubbed ──────────────────────────────────────────────

# ── j_stone: already stubbed ─────────────────────────────────────────────────

# ── j_golden: already in economy.py ──────────────────────────────────────────

# ── j_lucky_cat: already in scaling.py ───────────────────────────────────────

# ── j_baseball: already stubbed ──────────────────────────────────────────────

# ── j_bull: already in scaling.py ────────────────────────────────────────────

# ── j_diet_cola: already stubbed ─────────────────────────────────────────────

# ── j_trading: already stubbed ───────────────────────────────────────────────

# ── j_flash: already stubbed ─────────────────────────────────────────────────

# ── j_popcorn: already in scaling.py ─────────────────────────────────────────

# ── j_spare_trousers: already in scaling.py ──────────────────────────────────

# ── j_ancient: already in scaling.py ─────────────────────────────────────────

# ── j_ramen: already in scaling.py ───────────────────────────────────────────

# ── j_walkie_talkie: already in scaling.py ───────────────────────────────────

# ── j_seltzer: already stubbed ───────────────────────────────────────────────

# ── j_castle: already in scaling.py ──────────────────────────────────────────

# ── j_smiley: already in chips.py ────────────────────────────────────────────

# ── j_campfire: already in scaling.py ────────────────────────────────────────

# ── j_ticket: already in scaling.py ──────────────────────────────────────────

# Most hand type jokers are now implemented across the other modules.
# This file can remain as a reference/organizational layer.

# Add a few more unique hand mechanics:

# ── j_fibonacci: already in chips.py ─────────────────────────────────────────

# ── j_pareidolia: already stubbed in chips.py (all face cards become Kings) ──

# ── j_shortcut: already stubbed in chips.py (Straights with 1 rank gap) ──────

# ── j_four_fingers: already in chips.py (Flush/Straight with 4 cards) ────────

# ── j_splash: already stubbed in scaling.py (all played cards score) ─────────

# ── j_hack: already stubbed in chips.py (retrigger 2,3,4,5) ──────────────────

# ── j_sock_and_buskin: already stubbed (retrigger face cards) ────────────────

# ── j_dusk: already stubbed in chips.py (retrigger all on final hand) ────────

# ── j_hanging_chad: already stubbed (retrigger first played card 2 times) ────

# ── j_seltzer: already stubbed (retrigger all for next 3 hands) ──────────────

# ── j_mime: already stubbed in chips.py (retrigger held-in-hand abilities) ───

# ── j_seance: already stubbed in chips.py (Straight Flush → Spectral) ────────

# ── j_riff_raff: already stubbed in chips.py (create 2 common jokers) ────────

# ── j_superposition: already stubbed in scaling.py (Ace+Straight → Tarot) ────

# ── j_sixth_sense: already stubbed in scaling.py (single 6 → Spectral) ───────

# ── j_space: already stubbed in scaling.py (1 in 4 hand upgrade) ─────────────

# ── j_cartomancer: already stubbed in chips.py (create Tarot) ────────────────

# ── j_astronomer: already stubbed in chips.py (upgrade Planet in shop) ───────

# ── j_burnt: already stubbed in chips.py (upgrade first discard) ─────────────

# These are mostly implemented or stubbed. The key remaining work is:
# 1. Retrigger system
# 2. Consumable creation/upgrade
# 3. Shop system
# 4. Boss blind effects
# 5. Deck modification
# 6. Hand eval modification (Shortcut, FourFingers, Pareidolia, Splash, etc.)

# For now, this file serves as an organizational reference.
