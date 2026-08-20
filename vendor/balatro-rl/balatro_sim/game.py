"""
game.py — Top-level Balatro game state machine.

States:
  BLIND_SELECT   -> agent chooses to play or skip a blind
  SELECTING_HAND -> agent plays or discards cards
  ROUND_EVAL     -> end-of-round payout (auto-advances)
  SHOP           -> agent buys, sells, uses consumables, rerolls, then leaves
  BOOSTER_OPEN   -> agent picks from opened booster pack
  GAME_OVER      -> terminal state

Actions (passed as dict to game.step()):
  BLIND_SELECT:
    {"type": "play_blind"}
    {"type": "skip_blind"}

  SELECTING_HAND:
    {"type": "play",    "cards": [0, 2, 4]}
    {"type": "discard", "cards": [1, 3]}
    {"type": "use_consumable", "consumable_idx": 0, "target_cards": [0, 1]}

  SHOP:
    {"type": "buy",          "item_idx": 0}
    {"type": "sell_joker",   "joker_idx": 1}
    {"type": "use_consumable","consumable_idx": 0, "target_cards": [2]}
    {"type": "reroll"}
    {"type": "leave_shop"}

  BOOSTER_OPEN:
    {"type": "pick_booster", "indices": [0, 2]}  # which items to keep
    {"type": "skip_booster"}
"""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional

from .card import Card, make_standard_deck
from .hand_eval import evaluate_hand
from .scoring import score_hand
from .constants import (
    BLIND_CHIPS, STARTING_HANDS, STARTING_DISCARDS, HAND_SIZE,
    INTEREST_RATE, INTEREST_CAP, HAND_PAYOUT, STARTING_MONEY,
    BLIND_REWARDS, SHOWDOWN_REWARD,
)
from .jokers.base import JokerInstance, JOKER_REGISTRY
from .consumables import (
    apply_planet, apply_tarot, apply_spectral,
    PLANET_HAND, ALL_TAROTS, ALL_PLANETS, ALL_SPECTRALS,
    TAROT_NAME, PLANET_NAME, SPECTRAL_NAME,
)
from .shop import ShopItem, generate_shop, buy_item, sell_joker, reroll_shop
from .seed_rng import (
    make_source, node_boss,
    DECK_SHUFFLE_NODE, RESHUFFLE_NODE, AMBER_NODE, WHEEL_NODE, BELL_NODE,
    HOOK_NODE, CRIMSON_NODE, MADNESS_NODE, PURPLE_SEAL_NODE,
)
from .tags import roll_tag, apply_tag, _open_next_pack

# Hand type order used for run-wide tracking (The Pillar / The Ox). High Card
# first matches the real game's default tie-break for the most-played hand.
_HAND_TYPE_ORDER = [
    "High Card", "Pair", "Two Pair", "Three of a Kind", "Straight", "Flush",
    "Full House", "Four of a Kind", "Straight Flush", "Five of a Kind",
    "Flush House", "Flush Five",
]

#: hand_type -> planet key, for Blue Seal's round-end grant (reference doc §8).
_HAND_TO_PLANET = {v: k for k, v in PLANET_HAND.items()}


class State(Enum):
    BLIND_SELECT   = auto()
    SELECTING_HAND = auto()
    ROUND_EVAL     = auto()
    SHOP           = auto()
    BOOSTER_OPEN   = auto()
    GAME_OVER      = auto()


@dataclass
class BlindInfo:
    name: str
    kind: str           # "Small" | "Big" | "Boss"
    chips_target: int
    is_boss: bool = False
    boss_key: str = ""


@dataclass
class GameState:
    """Full observable game state snapshot."""
    state: State
    ante: int
    blind_kind: str
    chips_target: int
    chips_scored: int
    hands_left: int
    discards_left: int
    dollars: int
    hand: list[Card]
    deck_remaining: int
    jokers: list[JokerInstance]
    consumable_hand: list[str]      # list of consumable keys held
    planet_levels: dict[str, int]
    shop_items: list[ShopItem]
    hand_type: str = ""
    done: bool = False
    won: bool = False
    info: dict = field(default_factory=dict)


# Reference list of implemented boss keys and their real effects (documentation
# only — selection uses BOSS_MIN_ANTE / SHOWDOWN_BOSSES / UNIMPLEMENTED_BOSSES
# below, not this list).
BOSS_BLINDS = [
    "bl_hook",        # discard 2 random unplayed cards after every play
    "bl_goad",        # all Spades debuffed (real: The Goad)
    "bl_window",      # all Diamonds debuffed
    "bl_club",        # all Clubs debuffed (real: The Club)
    "bl_wheel",       # 1-in-7 cards drawn face down (real: The Wheel)
    "bl_manacle",     # -1 hand size
    "bl_eye",         # can't play same hand type twice
    "bl_mouth",       # can only play 1 hand type
    "bl_fish",        # cards drawn after a played hand are face down
    "bl_plant",       # all face cards debuffed
    "bl_needle",      # only 1 hand
    "bl_head",        # all Hearts debuffed
    "bl_tooth",       # lose $1 per card played
    "bl_wall",        # 4x base blind size
    "bl_house",       # first hand (opening deal) drawn face down
    "bl_mark",        # all face cards drawn face down
    "bl_flint",       # base chips + mult halved for the round
    "bl_psychic",     # must play exactly 5 cards
    "bl_grim",        # The Arm: permanently decrease played hand level by 1
    "bl_verdant",     # all cards debuffed until 1 joker sold
    "bl_serpent",     # draw 3 after each play/discard, ignoring hand size
    "bl_pillar",      # cards played earlier this ante are debuffed
    "bl_water",       # start with 0 discards
    "bl_ox",          # playing the most-played hand this run sets money to $0
    "bl_cerulean",    # forces 1 card in hand to always be selected
    "bl_amber",       # flips and shuffles all joker cards
    "bl_violet",      # 6x base blind size (Violet Vessel)
    "bl_crimson",     # one random joker disabled every hand (Crimson Heart)
]

# Real-game boss selection data (balatrowiki.org/w/Blinds_and_Antes).
# BOSS_MIN_ANTE holds the minimum-ante eligibility for every real boss. The five
# SHOWDOWN_BOSSES only appear at ante 8 (and 16/24 in Endless). Keys in
# UNIMPLEMENTED_BOSSES are excluded from selection until their effects are
# implemented — the same allow-list approach used for jokers — so the sim never
# presents a boss whose effect it cannot model faithfully.
BOSS_MIN_ANTE = {
    "bl_hook": 1, "bl_goad": 1, "bl_window": 1, "bl_manacle": 1,
    "bl_eye": 3, "bl_mouth": 2, "bl_fish": 2, "bl_plant": 4,
    "bl_needle": 2, "bl_head": 1, "bl_tooth": 3, "bl_wall": 2,
    "bl_house": 2,   # The House: first hand drawn face down
    "bl_mark": 2, "bl_flint": 2, "bl_psychic": 1,
    "bl_grim": 2,    # The Arm: decrease played hand level by 1
    "bl_verdant": 8, "bl_serpent": 5, "bl_pillar": 1, "bl_water": 2,
    "bl_ox": 6, "bl_cerulean": 8, "bl_amber": 8, "bl_violet": 8,
    "bl_crimson": 8,
    "bl_club": 1,    # The Club: all Clubs debuffed
    "bl_wheel": 2,   # The Wheel: 1-in-7 cards drawn face down
}

SHOWDOWN_BOSSES = {"bl_amber", "bl_verdant", "bl_violet", "bl_crimson", "bl_cerulean"}
# All 28 real bosses are now implemented — the allow-list is kept (empty) as
# infrastructure in case future coverage gaps need to exclude a boss again.
UNIMPLEMENTED_BOSSES: set[str] = set()

#: Boss blinds that trigger Matador's +$8 (wiki j_matador — 13 blinds, all
#: per-hand; the other 15 never pay, a real-game oversight where
#: Hook/Tooth/Crimson set the flag with the wrong timing). This is the
#: authoritative table: _play_hand's trigger logic is gated on it AND
#: graph_v9's boss-counter valuation consults it (Matador is only worth
#: buying when the UPCOMING boss is one of these). bl_psychic triggers via
#: the <5-card rejected-hand path (separate early branch in _play_hand).
MATADOR_BOSSES = frozenset({
    "bl_flint", "bl_goad", "bl_club", "bl_window", "bl_head", "bl_plant",
    "bl_pillar", "bl_eye", "bl_mouth", "bl_grim", "bl_ox", "bl_verdant",
    "bl_psychic",
})


class BalatroGame:
    """
    Full stateful Balatro game engine.

    Usage:
        game = BalatroGame(seed=42)
        obs = game.reset()
        while not obs.done:
            action = agent.act(obs)
            obs = game.step(action)
    """

    def __init__(self, seed: Optional[int] = None, rng_mode: str = "generic",
                 deck: str = "red"):
        """seed: run seed. rng_mode: "generic" (shared stream, legacy default)
        or "seed" (per-node LuaRandom, Balatro's real scheme — seed_rng.py).
        deck: "red" (spec lock — +1 discard per round) or "white" (base)."""
        self.rng = make_source(seed, rng_mode)
        self.deck_config = deck
        self._init_game_vars()

    # ── Initialization ───────────────────────────────────────────────────────

    def _init_game_vars(self):
        """Set all mutable game state to starting values."""
        self.ante = 1
        self.blind_idx = 0                  # 0=Small, 1=Big, 2=Boss
        self.dollars = STARTING_MONEY
        self.jokers: list[JokerInstance] = []
        self.joker_slots = 5
        self.consumable_hand: list[str] = []  # held consumable keys
        self.consumable_slots = 2
        self.planet_levels: dict[str, int] = {h: 1 for h in [
            "High Card", "Pair", "Two Pair", "Three of a Kind",
            "Straight", "Flush", "Full House", "Four of a Kind",
            "Straight Flush", "Five of a Kind", "Flush House", "Flush Five",
        ]}
        self.vouchers: set[str] = set()
        self.planets_used: list[str] = []
        self.tarots_used: list[str] = []
        #: Every tarot/planet used this run, in order, The Fool excluded — the
        #: copy source for The Fool (consumables.py _note_use / apply_planet).
        self.consumables_used: list[str] = []
        self.spectrals_used: list[str] = []
        #: Observation-only run statistics (plain data, ZERO RNG consumption —
        #: safe for the seed-exactness gate). Aggregated by bench/bench_v9.py
        #: into per-run reports + the HTML visualization.
        self.run_stats: dict = {
            "jokers_bought": [],      # joker keys as bought (may be sold later)
            "consumables_bought": 0,
            "cards_bought": 0,
            "packs_bought": 0,
            "vouchers_bought": 0,
            "money_spent": 0,
            "rerolls": 0,
            "packs_opened": 0,
            "best_score": 0,          # max chips_scored across the run
            # M12 telemetry (observation-only, ZERO RNG): money from seals /
            # gold / econ jokers (isolated from blind rewards + interest), and
            # total interest collected — the "better economy" headline.
            "econ_source": 0,          # $ from gold seal, lucky, business card,
                                       #   golden ticket, rough gem, to do list,
                                       #   faceless, mail, trading, golden,
                                       #   cloud 9, satellite, to the moon,
                                       #   rocket, reserved parking, matador,
                                       #   gold-card enhancement.
            "interest_collected": 0,   # $ from the $5-interest bands
            # ── Synergy-tree telemetry (observation-only, ZERO RNG / mutation;
            #    consumed by tools/gen_synergy_tree.py via the bench's
            #    --telemetry-dir dump — see synergy_tree.py for the mined
            #    priors that feed back into joker_value) ────────────────
            "jokers_sold": [],        # (ante, key) as sold (shop + mid-blind)
            "co_owned": [],           # (ante, hand_type, owned_joker_keys, score)
                                      #   per scored hand — the joker↔joker
                                      #   co-ownership + joker↔hand basis
            "consumable_uses": [],    # (ante, key, owned_joker_keys, targets)
                                      #   per consumable use — the
                                      #   joker↔consumable + joker↔card basis;
                                      #   targets = [{rank,suit,enh,edition,
                                      #   seal}] of up to 2 targeted cards
        }

        # Hand / discard / hand-size settings (Red Deck: +1 discard per round)
        self.base_hands = STARTING_HANDS
        self.base_discards = STARTING_DISCARDS + (1 if self.deck_config == "red" else 0)
        self.hand_size = HAND_SIZE
        #: Permanent hand-size modifier (Ouija / Ectoplasm -1s). hand_size
        #: resets to HAND_SIZE every blind, so permanent reductions live here
        #: and are re-applied in _start_blind.
        self.hand_size_mod = 0

        # Shop settings — the real game's shop has `joker_max` cdt-polled
        # random slots (2 base; Overstock / Overstock Plus +1 each), plus a
        # voucher slot and 2 booster-pack slots.
        self.shop_item_slots = 2
        self.shop_discount = 0.0
        # Real game: G.GAME.first_shop_buffoon — the first pack generated in a
        # run is always a normal Buffoon Pack (get_pack in common_events.lua).
        self.first_shop_buffoon = False
        # Real game: the shop's Voucher slot restocks only after the Boss Blind
        # is defeated — the same voucher persists across non-Boss blinds and
        # rerolls (shop.py generate_shop). None = nothing offered yet (roll on
        # the run's first shop).
        self.offered_voucher: Optional[str] = None
        self.reroll_cost = 5
        self.reroll_discount = 0
        self.free_rerolls_per_round = 0
        self.free_rerolls_remaining = 0
        self.current_shop: list[ShopItem] = []
        # Interest cap (Seed Money $10 / Money Tree $20; base $5)
        self.interest_cap = INTEREST_CAP
        # Director's Cut: the ante on which the 1x-per-Ante Boss reroll was used
        self.dc_reroll_ante: Optional[int] = None
        # The UPCOMING Boss Blind's key, selected at shop entry (real game:
        # the boss is revealed with the shop; Director's Cut rerolls it IN the
        # shop). None outside the shop-before-a-Boss. Set by
        # _preselect_next_boss(); consumed by _prepare_next_blind.
        self.next_boss_key: Optional[str] = None

        # Booster state
        self.booster_choices: list = []
        self.booster_picks_remaining: int = 0

        # ── Skip-blind Tag state (Phase 1: all 24 real tags) ───────────────
        self.current_tag: Optional[str] = None   # tag offered for the current blind
        self.skipped_blinds = 0                  # Speed Tag: $5 × skips this run
        self.run_hands_played = 0                # Handy Tag: $1 per played hand this run
        self.run_unused_discards = 0             # Garbage Tag: $1 per unused discard this run
        self.investment_pending = False          # Investment Tag: +$25 after next Boss
        self.double_tag_active = False           # Double Tag: copy the next tag
        self.boss_reroll_pending = False         # Boss Tag: reroll the next Boss Blind
        self.hand_size_bonus_next_round = 0      # Juggle Tag: +3 hand size next round
        self.pending_coupon = False              # Coupon Tag: next shop cards/packs free
        self.pending_reroll_free = False         # D6 Tag: next shop rerolls start at $0
        self.pending_free_rarity: Optional[str] = None   # Uncommon/Rare Tag
        self.pending_free_edition: Optional[str] = None  # Foil/Holo/Poly/Negative Tag
        self.pending_voucher = False             # Voucher Tag: extra voucher next shop
        self.pending_packs: list[str] = []       # queued free-pack Tag boosters
        self._shop_after_pack = False            # free-pack tag → generate shop after picks

        # Blind state
        self.current_blind: BlindInfo = BlindInfo("", "Small", 0)
        self.chips_scored = 0
        self.hands_left = self.base_hands
        self.discards_left = self.base_discards
        self.hand: list[Card] = []
        # The run deck is created ONCE and persists across blinds. Cards are
        # drawn from it each round and returned at the start of the next blind;
        # permanently destroyed cards (Hanged Man, Immolate, ...) leave it for
        # good — real Balatro deck behavior.
        self.deck: list[Card] = make_standard_deck()
        # Cards played or discarded during the current round. When the deck
        # runs out mid-round they are reshuffled back in (real game); any
        # cards still spent return to the deck at the next blind's start.
        self.spent: list[Card] = []
        self.played_hand_types_this_round: set[str] = set()
        # The LAST (final) hand type played this round — Blue Seal's Planet
        # grant keys off it (reference doc §8: "final poker hand played that
        # round"). None until a non-rejected hand is played.
        self.last_hand_played: Optional[str] = None

        # ── Boss-blind runtime state ──────────────────────────────────────
        self.verdant_debuff = False             # Verdant Leaf: all cards debuffed until a joker is sold
        self.jokers_flipped = False             # Amber Acorn: joker identities hidden, order shuffled
        self.bell_card: Optional[Card] = None   # Cerulean Bell: card forced into every played hand
        self._last_crimson_idx = None           # Crimson Heart: joker disabled this hand (no repeat)
        self.boss_disabled_override = False     # Luchador: sold → next Boss Blind disabled
        self.ante_played_ids: set[int] = set()  # The Pillar: cards played this ante
        self.run_hand_counts: dict[str, int] = {h: 0 for h in _HAND_TYPE_ORDER}  # The Ox
        # Boss rotation: appearances per boss this run. Selection only picks from
        # bosses with the fewest appearances, so a boss cannot repeat until every
        # eligible boss has appeared once (real-game no-repeat rule).
        self.boss_appearances: dict[str, int] = {}

        self.state = State.BLIND_SELECT
        self._prepare_next_blind()

    def reset(self) -> GameState:
        self._init_game_vars()
        return self._obs()

    # ── Blind setup ──────────────────────────────────────────────────────────

    def _select_boss(self, ante: int, exclude: Optional[str] = None) -> str:
        """Choose the next boss blind using the real-game selection rules.

        - Min-ante eligibility: only bosses with BOSS_MIN_ANTE[key] <= ante may
          appear; ante 8 (and 16/24 in Endless) draws from the Showdown pool.
        - No-repeat rotation: only bosses with the FEWEST appearances in the run
          are candidates, so a boss cannot reappear until every eligible boss
          has appeared at least once (wiki: "Only the Boss Blinds with the
          fewest appearances will be selected").
        - Driven by the game's RNG (self.rng.node("boss")); candidates are
          sorted so the pick is stable across processes.
        - exclude: a boss to skip (Boss Tag reroll).
        """
        if ante >= 8 and ante % 8 == 0:
            pool = SHOWDOWN_BOSSES
        else:
            pool = {
                key for key, min_ante in BOSS_MIN_ANTE.items()
                if min_ante <= ante
                and key not in SHOWDOWN_BOSSES
                and key not in UNIMPLEMENTED_BOSSES
            }
        if not pool:
            # ante >= 1 always has a non-empty eligible pool; if this ever fires,
            # the tables are broken and a loud failure beats silently ignoring
            # the min-ante rule.
            raise ValueError(f"no selectable boss for ante {ante}")
        min_count = min(self.boss_appearances.get(k, 0) for k in pool)
        candidates = [
            k for k in sorted(pool)
            if k != exclude
            and self.boss_appearances.get(k, 0) == min_count
        ]
        if not candidates:
            # exclude removed the whole pool (unreachable with current tables —
            # insurance against a future table change).
            candidates = [
                k for k in sorted(pool)
                if self.boss_appearances.get(k, 0) == min_count
            ]
        boss = self.rng.node(node_boss()).choice(candidates)
        self.boss_appearances[boss] = self.boss_appearances.get(boss, 0) + 1
        return boss

    def _prepare_next_blind(self):
        """Set up current_blind without starting play yet."""
        kind = ["Small", "Big", "Boss"][self.blind_idx]
        chips = BLIND_CHIPS[self.ante][self.blind_idx]
        boss_key = ""
        if kind == "Boss":
            # The upcoming boss is normally PRE-SELECTED at shop entry
            # (_preselect_next_boss) — the real game reveals the boss with the
            # shop. The legacy select path below is the safety net for
            # hand-constructed states that skip the shop entirely.
            if self.next_boss_key is not None:
                boss_key = self.next_boss_key
                self.next_boss_key = None
                # Invariant: the Boss Tag was already consumed at pre-selection
                # (_preselect_next_boss); clear defensively for hand-constructed
                # states that skipped the shop.
                self.boss_reroll_pending = False
            else:
                boss_key = self._select_boss(self.ante)
                # Boss Tag: reroll the Boss Blind — undo the no-repeat
                # increment from the first pick so the rotation stays correct.
                if self.boss_reroll_pending:
                    self.boss_reroll_pending = False
                    self.boss_appearances[boss_key] = max(
                        0, self.boss_appearances.get(boss_key, 0) - 1
                    )
                    boss_key = self._select_boss(self.ante, exclude=boss_key)
            # Large-blind bosses scale the required score (base chips = 1x).
            # The Wall (4x) and Violet Vessel (6x) scaling is part of the boss
            # ability, so it is skipped when abilities are disabled (Chicot /
            # Luchador) — they revert to the normal 2x baseline. The Needle is
            # a 1x score requirement and stays 1x regardless (real game:
            # bl_needle.mult = 1; not part of the disableable ability set).
            if boss_key == "bl_needle":
                chips = BLIND_CHIPS[self.ante][0]          # The Needle: 1x base
            elif self._boss_effects_on():
                if boss_key == "bl_wall":
                    chips = BLIND_CHIPS[self.ante][0] * 4   # The Wall: 4x base
                elif boss_key == "bl_violet":
                    chips = BLIND_CHIPS[self.ante][0] * 6   # Violet Vessel: 6x base
        self.current_blind = BlindInfo(
            name=f"Ante {self.ante} {kind}",
            kind=kind,
            chips_target=chips,
            is_boss=(kind == "Boss"),
            boss_key=boss_key,
        )
        self.state = State.BLIND_SELECT
        # Roll the skip-blind Tag offered for this blind (Boss blinds offer none)
        self.current_tag = roll_tag(self)

    def _preselect_next_boss(self):
        """Select the upcoming Boss Blind BEFORE the shop so the agent (and
        Director's Cut / Retcon rerolls) know the boss at shop time — the real
        game reveals the boss with the shop.

        Fires only when the next blind is a Boss (blind_idx == 1 — the shop
        after the Big blind, whether beaten or skipped). The Boss Tag's reroll
        is consumed here (undo + reselect-exclude, preserving the no-repeat
        rotation). Idempotent: a boss already selected (e.g. a free-pack tag
        flow re-entering the shop) is left untouched, so no extra boss-node
        draw.

        Drawn on the per-node "boss" stream, exactly as _prepare_next_blind
        used to — the same draws, one shop earlier; every other node is
        independently seeded, so shop contents and later boss values are
        byte-identical to the old ordering.
        """
        if self.blind_idx != 1 or self.next_boss_key is not None:
            return
        # NOTE: also called from _skip_blind (after tag application, before
        # any free-pack BOOSTER_OPEN window) so the boss is known even while
        # the pack is open — the idempotent guard above makes the later call
        # in _end_blind_and_enter_shop a no-op.
        boss_key = self._select_boss(self.ante)
        if self.boss_reroll_pending:
            self.boss_reroll_pending = False
            self.boss_appearances[boss_key] = max(
                0, self.boss_appearances.get(boss_key, 0) - 1
            )
            boss_key = self._select_boss(self.ante, exclude=boss_key)
        self.next_boss_key = boss_key

    def _start_blind(self):
        """Begin playing the current blind."""
        self.chips_scored = 0
        self.hands_left = self.base_hands
        self.discards_left = self.base_discards
        # Reset to base + PERMANENT modifiers (Ouija/Ectoplasm -1s survive
        # every blind via hand_size_mod) before applying joker passives.
        self.hand_size = HAND_SIZE + self.hand_size_mod
        # Juggle Tag: +3 hand size for the next round only
        if self.hand_size_bonus_next_round:
            self.hand_size += self.hand_size_bonus_next_round
            self.hand_size_bonus_next_round = 0
        self.played_hand_types_this_round = set()
        # Blue Seal keys off the FINAL hand of THIS round — stale from a
        # previous round must not leak (set by _play_hand on each valid play).
        self.last_hand_played = None
        # Reset per-blind boss effects
        self.verdant_debuff = False
        self.jokers_flipped = False
        self.bell_card = None

        # Passive hand-size/discard/hand modifiers from joker effects (R3:
        # declared per-effect `passives()`, not key scans). Hand size is floored
        # at 1 AFTER the passives are summed (Stuntman -2, Merry Andy -1).
        for j in self.jokers:
            self.hand_size += j.effect.passives(j).get("hand_size", 0)
            self.discards_left += j.effect.passives(j).get("discards", 0)
            self.hands_left += j.effect.passives(j).get("hands", 0)
        self.hand_size = max(1, self.hand_size)
        self.hands_left = max(1, self.hands_left)

        # Apply voucher hand size adjustments
        if "v_paint_brush" in self.vouchers:
            self.hand_size += 1
        if "v_palette" in self.vouchers:
            self.hand_size += 1

        # Return cards played/discarded last round (and any cards still held,
        # e.g. left in hand through the shop phase) to the persistent deck,
        # then shuffle and draw the opening hand. Destroyed cards are neither
        # in hand nor spent, so they stay removed from the run.
        self.deck.extend(self.spent)
        self.deck.extend(self.hand)
        self.spent = []
        self.hand = []
        self.rng.node(DECK_SHUFFLE_NODE).shuffle(self.deck)
        self._draw_to_full()
        # Apply boss debuffs (skipped entirely when abilities are disabled)
        if self.current_blind.is_boss and self._boss_effects_on():
            self._apply_boss_start(self.current_blind.boss_key)
        # Fire blind_selected joker hooks; collect created rewards so they apply
        # AFTER the whole loop — a joker Riff-Raff creates (parked as a
        # ("joker", ...) tuple) must not have its own on_blind_selected fire
        # for the same blind (real game).
        deferred = []
        for j in self.jokers:
            j.fire("on_blind_selected", None)
            # Collect pending consumables / planet upgrades from joker state
            deferred.extend(j.state.pop("pending_consumables", []))
            if "planet_upgrade" in j.state:
                ht = j.state.pop("planet_upgrade")
                self.planet_levels[ht] = self.planet_levels.get(ht, 1) + 1
            # Event-based game-state modifiers (Burglar — fires once per blind)
            extra_hands = j.state.pop("extra_hands", 0)
            if extra_hands:
                self.hands_left += extra_hands
            if j.state.pop("zero_discards", False):
                self.discards_left = 0
        self._grant_pending(deferred)
        # Ceremonial Dagger: destroy joker to the right, gain 2x sell value as mult
        to_destroy = []
        for i, j in enumerate(self.jokers):
            if j.state.pop("destroy_right", False) and i + 1 < len(self.jokers):
                target = self.jokers[i + 1]
                sell_val = target.state.get("sell_value", 2)
                j.state["mult"] = j.state.get("mult", 0) + sell_val * 2
                to_destroy.append(i + 1)
        for idx in sorted(to_destroy, reverse=True):
            self.jokers.pop(idx)
        # Madness: destroy a random OTHER joker on Small/Big blind
        madness_destroy = []
        for i, j in enumerate(self.jokers):
            if j.state.pop("destroy_random", False):
                others = [k for k in range(len(self.jokers)) if k != i]
                if others:
                    madness_destroy.append(self.rng.node(MADNESS_NODE).choice(others))
        for idx in sorted(set(madness_destroy), reverse=True):
            if idx < len(self.jokers):
                self.jokers.pop(idx)
        self.state = State.SELECTING_HAND

    def _apply_boss_start(self, boss_key: str):
        """Apply start-of-blind boss effects."""
        if boss_key == "bl_manacle":
            self.hand_size = max(1, self.hand_size - 1)
        elif boss_key == "bl_needle":
            self.hands_left = 1
        elif boss_key == "bl_water":
            self.discards_left = 0
        elif boss_key == "bl_goad":
            # The Goad debuffs Spades in the real game (Clubs are The Club,
            # handled separately below).
            for c in self.deck + self.hand:
                if c.suit == "Spades":
                    c.debuffed = True
        elif boss_key == "bl_club":
            # The Club: all Club cards are debuffed
            for c in self.deck + self.hand:
                if c.suit == "Clubs":
                    c.debuffed = True
        elif boss_key == "bl_window":
            for c in self.deck + self.hand:
                if c.suit == "Diamonds":
                    c.debuffed = True
        elif boss_key == "bl_head":
            for c in self.deck + self.hand:
                if c.suit == "Hearts":
                    c.debuffed = True
        elif boss_key == "bl_plant":
            for c in self.deck + self.hand:
                if c.is_face_card:
                    c.debuffed = True
        elif boss_key == "bl_fish":
            pass  # handled in _draw_to_full
        elif boss_key == "bl_psychic":
            pass  # enforced in _play_hand validation
        elif boss_key == "bl_verdant":
            # Verdant Leaf: every card is debuffed until a joker is sold
            self.verdant_debuff = True
            for c in self.deck + self.hand:
                c.debuffed = True
        elif boss_key == "bl_pillar":
            # The Pillar: cards played earlier this ante are debuffed
            for c in self.deck + self.hand:
                if c.id in self.ante_played_ids:
                    c.debuffed = True
        elif boss_key == "bl_cerulean":
            self._pick_bell_card()
        elif boss_key == "bl_amber":
            # Amber Acorn: shuffle joker order (matters for scoring) and hide identities
            self.rng.node(AMBER_NODE).shuffle(self.jokers)
            self.jokers_flipped = True
        elif boss_key == "bl_house":
            # The House: the opening hand (dealt at blind start) is face down;
            # cards drawn later in the round come face up.
            for c in self.hand:
                c.flipped = True
        # NOTE: Matador pays only per PLAYED hand that triggers the boss
        # ability (see _play_hand) — there is no blind-start payout.

    def _undo_boss_debuffs(self, boss_key: str):
        """Re-enable cards after boss blind ends."""
        if boss_key in ("bl_goad", "bl_club", "bl_window", "bl_head", "bl_plant"):
            # Include spent (played/discarded) cards: they return to the deck at
            # the next blind, so their debuff must not carry over with them.
            for c in self.deck + self.hand + self.spent:
                c.debuffed = False
        elif boss_key in ("bl_pillar", "bl_verdant"):
            self.verdant_debuff = False
            for c in self.deck + self.hand + self.spent:
                c.debuffed = False
        elif boss_key in ("bl_mark", "bl_wheel", "bl_house", "bl_fish"):
            # Face-down cards (The Mark / The Wheel / The House / Fish's
            # post-play draws) are revealed when the blind ends so they don't
            # stay face-down into later blinds.
            for c in self.deck + self.hand + self.spent:
                c.flipped = False
        elif boss_key == "bl_amber":
            self.jokers_flipped = False
        elif boss_key == "bl_cerulean":
            self.bell_card = None

    def _draw_cards(self, n: int, flip_for_fish: bool = False) -> int:
        """Draw up to `n` cards from the deck into the hand, ignoring hand
        size (The Serpent's draw-3 / Fish's face-down replacement draws).
        Mid-round deck exhaustion reshuffles the spent pile back in (real
        Balatro behavior); destroyed cards are never in spent, so they stay
        removed for good. Returns the number actually drawn — if deck+spent
        are both empty fewer than n are drawn (no infinite loop).
        """
        drawn = 0
        for _ in range(n):
            if not self.deck:
                # Mid-round deck exhaustion: reshuffle the spent pile (cards
                # played or discarded this round) back into the deck so play
                # can continue — real Balatro behavior. Destroyed cards are
                # never in spent, so they stay removed from the run for good.
                # If even the spent pile is empty there is nothing left to
                # draw, so the hand stays short (can happen with heavy
                # destruction) rather than looping forever.
                if not self.spent:
                    break
                self.deck.extend(self.spent)
                self.spent = []
                # RESHUFFLE_NODE is a sim-internal node (like WHEEL_NODE) —
                # balatro-seed does not pin the in-game reshuffle call site,
                # so it is deterministic per seed in seed mode but not
                # byte-exact against the real game.
                self.rng.node(RESHUFFLE_NODE).shuffle(self.deck)
            c = self.deck.pop()
            self._on_card_drawn(c)
            if flip_for_fish and self._boss_effects_on() \
                    and self.current_blind.boss_key == "bl_fish":
                # The Fish: cards drawn after a PLAYED hand are dealt face
                # down (draws after discards come face up — real-game text:
                # "Cards drawn face down after each hand played").
                c.flipped = True
            self.hand.append(c)
            drawn += 1
        return drawn

    def _draw_to_full(self, face_down_for_fish: bool = False):
        """Draw until the hand reaches hand_size. Under The Fish the
        replacement cards drawn after a played hand are dealt face down
        (face_down_for_fish=True from _play_hand); the hand size itself is
        UNCHANGED — the real Fish reduces information, not hand size.
        """
        target = self.hand_size
        while len(self.hand) < target:
            if not self._draw_cards(1, flip_for_fish=face_down_for_fish):
                break

    def _on_card_drawn(self, card: Card):
        """Apply boss-blind effects to a card the moment it is drawn."""
        boss = self.current_blind.boss_key if self._boss_effects_on() else ""
        if boss == "bl_mark" and card.is_face_card:
            card.flipped = True          # The Mark: face cards are drawn face down
        if boss == "bl_wheel" and self.rng.node(WHEEL_NODE).random() < 1 / 7:
            card.flipped = True          # The Wheel: 1-in-7 cards drawn face down
            # WHEEL_NODE is a sim-internal node (balatro-seed does not pin the
            # in-game Wheel call site), so it is deterministic per seed in seed
            # mode but not byte-exact against the real game — see M0 audit 4.2.
        if boss == "bl_verdant" and self.verdant_debuff:
            card.debuffed = True         # Verdant Leaf: every drawn card stays debuffed
        if boss == "bl_pillar" and card.id in self.ante_played_ids:
            card.debuffed = True         # The Pillar: cards played earlier this ante are debuffed

    def _pick_bell_card(self):
        """Cerulean Bell: choose a random card in hand as the forced card."""
        if self.hand:
            self.bell_card = self.rng.node(BELL_NODE).choice(self.hand)

    def _maybe_repick_bell_card(self):
        """Cerulean Bell: re-choose a forced card once the old one leaves the hand."""
        if self.bell_card is None or self.bell_card not in self.hand:
            self._pick_bell_card()

    def _most_played_hand(self) -> str:
        """The hand type played most this run; ties break toward High Card (game default)."""
        best = "High Card"
        best_key = (-1, -1)
        for ht, count in self.run_hand_counts.items():
            # Negate the order index so ties favor High Card (index 0)
            key = (count, -_HAND_TYPE_ORDER.index(ht))
            if key > best_key:
                best_key, best = key, ht
        return best

    def _boss_effects_on(self) -> bool:
        """False when Boss Blind abilities are disabled: Chicot's permanent
        passive (presence-based — the real game disables every boss while
        owned) or Luchador's sell-to-disable (one-shot override, consumed
        when the boss blind resolves). Capability flag, not a key scan (R3)."""
        if self.boss_disabled_override:
            return False
        return not any(j.has_flag("disables_bosses") for j in self.jokers)

    def _fire_boss_trigger(self):
        """Fire Matador's on_boss_ability_triggered: +$8 for the current played
        hand, paid once per qualifying hand. Called from _play_hand only (the
        real game has no blind-start payout). No-op while boss abilities are
        disabled or Matador is not owned."""
        if not self._boss_effects_on():
            return
        for j in self.jokers:
            j.fire("on_boss_ability_triggered", None)
            pm = j.state.pop("pending_money", 0)
            self.dollars += pm
            self.run_stats["econ_source"] += pm

    # ── Main step ────────────────────────────────────────────────────────────

    def step(self, action: dict) -> GameState:
        atype = action.get("type", "")

        if self.state == State.BLIND_SELECT:
            if atype == "play_blind":
                self._start_blind()
            elif atype == "skip_blind":
                self._skip_blind()

        elif self.state == State.SELECTING_HAND:
            if atype == "play":
                self._play_hand(action.get("cards", []))
            elif atype == "discard":
                self._discard(action.get("cards", []))
            elif atype == "use_consumable":
                self._use_consumable(
                    action.get("consumable_idx", 0),
                    action.get("target_cards", [])
                )
            elif atype == "sell_joker":
                # Selling mid-blind is only allowed under Verdant Leaf, where
                # selling any joker lifts the all-cards debuff
                if self.current_blind.boss_key == "bl_verdant":
                    if sell_joker(self, action.get("joker_idx", 0)):
                        self.verdant_debuff = False
                        for c in self.deck + self.hand:
                            c.debuffed = False

        elif self.state == State.ROUND_EVAL:
            self._end_round()

        elif self.state == State.SHOP:
            if atype == "buy":
                idx = action.get("item_idx", 0)
                if idx < len(self.current_shop):
                    buy_item(self, self.current_shop[idx])
            elif atype == "sell_joker":
                sell_joker(self, action.get("joker_idx", 0))
            elif atype == "use_consumable":
                self._use_consumable(
                    action.get("consumable_idx", 0),
                    action.get("target_cards", [])
                )
            elif atype == "reroll":
                reroll_shop(self)
            elif atype == "reroll_boss":
                self._reroll_boss()
            elif atype == "leave_shop":
                self._end_shop()

        elif self.state == State.BOOSTER_OPEN:
            if atype == "pick_booster":
                self._pick_booster(action.get("indices", []))
            elif atype == "skip_booster":
                # Red Card (j_red_card): +3 Mult permanently per Booster Pack
                # skipped (M1 B2 on_booster_skipped dispatch).
                self._fire_joker_hook("on_booster_skipped", None)
                self.booster_choices = []
                if self.pending_packs:
                    # Double Tag on a pack tag: another free pack awaits
                    _open_next_pack(self)
                elif self._shop_after_pack:
                    # Free-pack Tag: enter the skipped blind's shop after the pack
                    self._shop_after_pack = False
                    self._end_blind_and_enter_shop()
                else:
                    self.state = State.SHOP

        return self._obs()

    # ── Play ─────────────────────────────────────────────────────────────────

    def _play_hand(self, card_indices: list[int]):
        selected = [self.hand[i] for i in card_indices if i < len(self.hand)]
        if not selected:
            return

        # Boss effects are skipped entirely while disabled (Chicot / Luchador)
        boss = self.current_blind.boss_key if self._boss_effects_on() else ""

        # Boss: psychic — must play exactly 5. A <5-card play is a non-scoring
        # hand: it still consumes a hand (real game) and triggers Matador
        # (wiki: Psychic triggers on "less than 5 cards"). Consuming the hand
        # also stops an agent from farming Matador's $8 with free rejected
        # plays.
        if boss == "bl_psychic" and len(selected) != 5:
            self._fire_boss_trigger()
            self.hands_left -= 1
            if self.hands_left <= 0:
                self.state = State.GAME_OVER
            return

        # Boss: cerulean bell — the forced card is automatically added to every
        # played hand (the player cannot leave it out)
        if boss == "bl_cerulean" and self.bell_card is not None \
                and self.bell_card in self.hand and self.bell_card not in selected:
            selected.append(self.bell_card)

        # Handy Tag: $1 per played hand this run. Counted only after boss
        # rejections (psychic wrong count) that do not consume a hand.
        self.run_hands_played += 1
        hand_type, scoring_cards = evaluate_hand(selected)

        # Boss: eye — no repeat hand types this round.
        # Boss: mouth — only one hand type can be played this round.
        # A disallowed hand is still played and wastes a hand, but scores 0
        # ("Not allowed!") and does NOT count as that hand type for the round's
        # restriction tracking.
        # NOTE: bool() is required — `and`/`or` return OPERANDS, not bools, and
        # the empty `played_hand_types_this_round` set is a falsy operand. Without
        # it, `rejected` aliases the live set and flips truthy after the add below.
        rejected = bool(
            (boss == "bl_eye" and hand_type in self.played_hand_types_this_round)
            or (boss == "bl_mouth" and self.played_hand_types_this_round
                and hand_type not in self.played_hand_types_this_round)
        )
        if not rejected:
            self.played_hand_types_this_round.add(hand_type)

        # Boss: ox — playing the most-played hand type of the run sets money to $0
        if boss == "bl_ox" and hand_type == self._most_played_hand():
            self.dollars = 0

        # Boss: crimson heart — one random joker is disabled for this hand
        active_jokers = self.jokers
        if boss == "bl_crimson" and self.jokers:
            idx = self.rng.node(CRIMSON_NODE).randrange(len(self.jokers))
            if len(self.jokers) > 1 and idx == self._last_crimson_idx:
                idx = (idx + 1) % len(self.jokers)
            self._last_crimson_idx = idx
            active_jokers = [j for i, j in enumerate(self.jokers) if i != idx]

        # Matador: +$8 per played hand that triggers the Boss Blind ability.
        # Real-game semantics (wiki j_matador page) — 13 triggering blinds, all
        # per-hand, once per qualifying hand; the other 15 blinds never pay
        # (Wheel, House, Fish, Water, Wall, Manacle, Serpent, Needle, Tooth,
        # Mark, Hook, Amber, Violet, Crimson, Cerulean — a real-game oversight
        # where Hook/Tooth/Crimson set the flag with the wrong timing).
        matador = False
        # MATADOR_BOSSES is the authoritative trigger set. NOTE: bl_psychic is
        # in the set but has NO branch here — its trigger is the <5-card
        # rejected-hand early-return above, which fires the boss trigger before
        # this block. 5-card psychic plays do not trigger Matador.
        if boss in MATADOR_BOSSES:
            if boss == "bl_flint":
                matador = True   # every played hand is halved
            elif boss in ("bl_goad", "bl_club", "bl_window", "bl_head",
                          "bl_plant", "bl_pillar"):
                # Suit/face/pillar debuffs: a DEBUFFED card must actually
                # score (debuffed cards outside the hand's scoring cards
                # don't count).
                matador = any(c.debuffed for c in scoring_cards)
            elif boss in ("bl_eye", "bl_mouth"):
                matador = rejected   # a disallowed (non-scoring) hand
            elif boss == "bl_grim":
                # The Arm: only when the played hand's level can be decreased
                matador = self.planet_levels.get(hand_type, 1) >= 2
            elif boss == "bl_ox":
                # The Ox: only when the hand sets your money to zero
                matador = hand_type == self._most_played_hand()
            elif boss == "bl_verdant":
                # Verdant Leaf: until a joker is sold this blind
                matador = self.verdant_debuff
        if matador:
            self._fire_boss_trigger()

        # Boss: arm (bl_grim) — permanently decrease the played hand type's
        # level by 1 (floor at level 1), applied BEFORE scoring so this hand
        # scores at the reduced level. Levels lost persist for the rest of the
        # run (planet_levels is run-wide).
        if boss == "bl_grim":
            self.planet_levels[hand_type] = max(
                1, self.planet_levels.get(hand_type, 1) - 1
            )

        score, ctx = score_hand(
            scoring_cards=scoring_cards,
            all_cards=selected,
            hand_type=hand_type,
            jokers=active_jokers,
            planet_levels=self.planet_levels,
            hands_left=self.hands_left - 1,
            discards_left=self.discards_left,
            dollars=self.dollars,
            ante=self.ante,
            deck_remaining=len(self.deck),
            half_base=(boss == "bl_flint"),
            game=self,
            held_cards=[c for c in self.hand if c not in selected],
        )

        # Boss: tooth — lose $1 per card played
        if boss == "bl_tooth":
            self.dollars = max(0, self.dollars - len(selected))

        # Boss: eye/mouth — a disallowed hand scores 0 for the blind (the cards
        # still play and the hand is still consumed)
        if rejected:
            score = 0

        self.chips_scored += score
        if self.chips_scored > self.run_stats["best_score"]:
            self.run_stats["best_score"] = self.chips_scored
        self.hands_left -= 1

        # Apply pending side-effects from scoring (real consumable keys, plus
        # ("joker"/"card"/"hand_card", ...) tuples from object-creating jokers)
        self.dollars += ctx.pending_money
        self.run_stats["econ_source"] += ctx.pending_money
        self._grant_pending(ctx.pending_consumables)

        # Seltzer self-destructs after its 10 hands are spent (sets
        # state["destroyed"] in on_hand_scored) — remove it immediately.
        self.jokers = [j for j in self.jokers if not j.state.pop("destroyed", False)]

        # Move played cards out of hand (they return to the deck at the next blind)
        for c in selected:
            if c in self.hand:
                self.hand.remove(c)
                self.spent.append(c)

        # Glass shatter / Sixth Sense: destroyed cards are removed from the
        # run permanently — they do not return to the deck with the spent pile.
        for c in ctx.destroyed:
            self._destroy_card(c)

        # Run-wide tracking for boss blinds:
        #  - The Pillar debuffs cards played earlier this ante (and as they are played)
        #  - The Ox keys off the most-played hand type of the run
        # A rejected eye/mouth hand does NOT count toward either (it is not a
        # valid play of that hand type). Bosses never coexist, but keep the
        # semantics uniform.
        if not rejected:
            for c in selected:
                self.ante_played_ids.add(c.id)
            self.run_hand_counts[hand_type] = self.run_hand_counts.get(hand_type, 0) + 1
            # Blue Seal: the Planet keys off the FINAL hand played this round
            self.last_hand_played = hand_type
            # Synergy-tree telemetry (observation-only): the loadout at scoring
            # time — the joker↔joker co-ownership and joker↔hand activation
            # basis for tools/gen_synergy_tree.py. Zero RNG, zero mutation.
            self.run_stats["co_owned"].append(
                (self.ante, hand_type,
                 tuple(sorted(j.key for j in self.jokers)), score))

        # The Mark / The Wheel / The House: face-down cards are revealed once played
        if boss in ("bl_mark", "bl_wheel", "bl_house"):
            for c in selected:
                c.flipped = False

        if boss == "bl_serpent":
            self._draw_cards(3)
        else:
            # The Fish: replacement cards drawn on a played hand are face
            # down (hand size unchanged); all other draws come face up.
            self._draw_to_full(face_down_for_fish=(boss == "bl_fish"))

        # Boss: The Hook — "Discards 2 random unplayed cards after every
        # played hand" (reference doc §10, balatro-rs blind.rs). The played
        # hand scores FULLY; after the refill draw, 2 random cards from the
        # remaining hand are discarded (hand may have fewer; discard what's
        # there). Discarded cards return to the deck with the spent pile.
        if boss == "bl_hook" and self.hand:
            unplayed = list(self.hand)
            self.rng.node(HOOK_NODE).shuffle(unplayed)
            for c in unplayed[:2]:
                self.hand.remove(c)
                self.spent.append(c)

        # Cerulean Bell: the forced card left the hand — choose a new one if any remain
        if boss == "bl_cerulean":
            self._maybe_repick_bell_card()

        # NOTE: Blue Seal does NOT fire here — it keys off cards HELD in hand
        # at ROUND END, granting the Planet of the final hand played (reference
        # doc §8; wiki: "Creates the Planet card for final played poker hand of
        # round if held in hand"). Implemented in _end_round.

        # (Purple seal moved to _discard — it keys off DISCARDED cards, doc §8.)

        # Check win / loss
        if ctx.prevent_loss and self.chips_scored >= self.current_blind.chips_target * 0.25:
            # Mr. Bones: prevent death if >= 25% reached
            self.chips_scored = self.current_blind.chips_target
            self.state = State.ROUND_EVAL
        elif self.chips_scored >= self.current_blind.chips_target:
            self.state = State.ROUND_EVAL
        elif self.hands_left <= 0:
            self.state = State.GAME_OVER

    def _discard(self, card_indices: list[int]):
        if self.discards_left <= 0:
            return
        selected = [self.hand[i] for i in card_indices if i < len(self.hand)]
        if not selected:
            return

        # Fire on_discard joker hooks; collect pending money/consumables
        deferred = []
        for j in self.jokers:
            j.fire("on_discard", selected, None)
            pm = j.state.pop("pending_money", 0)
            self.dollars += pm
            self.run_stats["econ_source"] += pm
            deferred.extend(j.state.pop("pending_consumables", []))

        for c in selected:
            self.hand.remove(c)
            self.spent.append(c)
        self.discards_left -= 1
        # Purple seal: creates a Tarot when this card is DISCARDED (doc §8;
        # §3.1 fix — was wrongly firing on play). Debuffed cards are worthless.
        for c in selected:
            if (c.seal == "Purple" and not c.debuffed
                    and len(self.consumable_hand) < self.consumable_slots):
                self.consumable_hand.append(
                    self.rng.node(PURPLE_SEAL_NODE).choice(ALL_TAROTS))
        # Grant AFTER the card-move loop: Trading Card's ("destroy_card", c)
        # removes the target from hand/spent — it must not still be expected
        # in the hand-removal loop above (real destroy, B6).
        self._grant_pending(deferred)
        # The Serpent: draw 3 after every discard too, ignoring hand size
        # (real text: "After Play or Discard, always draw 3 cards").
        if self._boss_effects_on() and self.current_blind.boss_key == "bl_serpent":
            self._draw_cards(3)
        else:
            self._draw_to_full()
        # Cerulean Bell: the forced card was discarded — pick a new one if any remain
        if self._boss_effects_on() and self.current_blind.boss_key == "bl_cerulean":
            self._maybe_repick_bell_card()

    def _fire_joker_hook(self, hook: str, *args):
        """Dispatch a named hook to every owned joker effect (M1 B2 family).
        Every hook exists as a no-op on the JokerEffect base, so this is a
        plain per-instance fire — no registry lookup or hasattr probe (R2)."""
        for j in self.jokers:
            j.fire(hook, *args)

    def _use_consumable(self, consumable_idx: int, target_cards: list[int]):
        if consumable_idx >= len(self.consumable_hand):
            return
        key = self.consumable_hand[consumable_idx]

        # on_planet_used / on_tarot_used hooks are dispatched inside
        # apply_planet / apply_tarot (consumables.py) — do NOT re-dispatch here
        # or Satellite/Constellation/Fortune Teller would double-count.
        #
        # The used card is consumed BEFORE the effect resolves (the real game
        # removes the consumable first): create-effect consumables (The Fool,
        # High Priestess, Emperor) build into the freed slot.
        #
        # NOTE: the pop is unconditional for recognized keys because every
        # recognized key's apply_* returns True (unknown keys return above).
        # Keep that invariant if a new consumable with a failing apply path
        # is ever added.
        #
        # Synergy-tree telemetry (observation-only): which jokers were owned
        # when this consumable was used, and the features of up to 2 targeted
        # cards (read BEFORE apply mutates them). Zero RNG, zero mutation.
        targets = []
        for i in list(target_cards)[:2]:
            if 0 <= i < len(self.hand):
                c = self.hand[i]
                targets.append({"rank": c.rank, "suit": c.suit,
                                "enh": c.enhancement, "edition": c.edition,
                                "seal": c.seal})
        self.run_stats["consumable_uses"].append(
            (self.ante, key, tuple(sorted(j.key for j in self.jokers)),
             targets))
        if key in PLANET_HAND:
            self.consumable_hand.pop(consumable_idx)
            apply_planet(self, key)
        elif key in ALL_TAROTS:
            self.consumable_hand.pop(consumable_idx)
            apply_tarot(self, key, target_cards)
        elif key in ALL_SPECTRALS:
            self.consumable_hand.pop(consumable_idx)
            apply_spectral(self, key, target_cards)

    def grant_joker(self, key: str, edition: str = "None", *, fire_init: bool = True):
        """The SINGLE acquisition path for jokers (R5).

        Slot check, instance construction, state seeding, and on_init dispatch
        all happen here — buy_item, packs, tags, Judgement/Wraith/Soul,
        Riff-Raff grants, and the envs all route through this method. Negative
        edition jokers do not consume a slot (real game).

        Returns the new JokerInstance, or None if the slot was full.
        """
        if len(self.jokers) >= self.joker_slots and edition != "Negative":
            return None
        j = JokerInstance(key, edition, game=self)
        self.jokers.append(j)
        if fire_init:
            j.fire("on_init")
        return j

    def _grant_pending(self, items: list):
        """Materialize joker-created rewards (the `pending_consumables` payloads
        collected from hooks) into the game.

    Plain entries are real tarot/planet/spectral keys → consumable hand
    (slot-capped, M1 B1). Tuples carry object creations:
      ("joker", key, edition)     → a joker slot (Riff-Raff)
      ("card", card)              → into the run deck (Marble)
      ("hand_card", card)         → drawn to hand now; returns to the run deck
                                   at the next blind's start (Certificate, DNA)
    """
        for item in items:
            if isinstance(item, tuple) and item and item[0] == "joker":
                _, key, edition = item
                self.grant_joker(key, edition)
            elif isinstance(item, tuple) and item and item[0] == "card":
                # Marble: straight into the run deck (the round is already
                # dealt, so it cannot be drawn until the next blind's shuffle)
                self.deck.insert(0, item[1])
                self._fire_joker_hook("on_card_added", None)
            elif isinstance(item, tuple) and item and item[0] == "destroy_card":
                # Trading Card: the discarded card is destroyed permanently
                self._destroy_card(item[1])
            elif isinstance(item, tuple) and item and item[0] == "hand_card":
                # Certificate / DNA: drawn to hand now; it returns to the run
                # deck at the next blind's start (persistent-deck rule), so
                # only the hand append is needed here — adding it to the deck
                # too would duplicate the card when the hand is collected.
                self.hand.append(item[1])
                # Hologram: X0.25 per card added to the run (M1 B2).
                self._fire_joker_hook("on_card_added", None)
            elif len(self.consumable_hand) < self.consumable_slots:
                self.consumable_hand.append(item)

    def _destroy_card(self, card: Card):
        """Permanently remove a card from the run (real destroys — Glass
        shatter, Sixth Sense, Trading Card). The card is dropped from the
        persistent deck, hand, and spent pile so it never returns to play;
        Canio gains X1 Mult when a face card is destroyed (M1 B2
        on_card_destroyed dispatch). Idempotent: duplicate destroy signals
        (e.g. a Glass 6 that shatters AND is Sixth-Sense'd) are safe."""
        for pile in (self.deck, self.hand, self.spent):
            if card in pile:
                pile.remove(card)
        if card.is_face_card:
            self._fire_joker_hook("on_card_destroyed", card, None)

    # ── Round end / shop ─────────────────────────────────────────────────────

    def _end_round(self):
        # Payout (interest cap raised by Seed Money / Money Tree)
        earnings = self.hands_left * HAND_PAYOUT
        interest = min(self.dollars // INTEREST_RATE, self.interest_cap)
        self.run_stats["interest_collected"] += interest
        # Blind reward — flat per tier (Small $3 / Big $4 / Boss $5); the
        # Ante-8 Showdown finisher pays $8. Real game blind table.
        if self.current_blind.is_boss and self.ante % 8 == 0:
            reward = SHOWDOWN_REWARD
        else:
            reward = BLIND_REWARDS[self.current_blind.kind]
        self.dollars += earnings + interest + reward
        # Garbage Tag: unused discards this round count toward the run total
        self.run_unused_discards += self.discards_left

        # Blue Seal: a Blue-sealed card HELD in hand at round end creates the
        # Planet of the final hand played this round (reference doc §8 — not
        # the hand the seal was scored in, and only if still held).
        if self.last_hand_played is not None:
            planet_key = _HAND_TO_PLANET.get(self.last_hand_played)
            if planet_key:
                # Mime retriggers held-in-hand abilities (doc §2), doubling the
                # planet grant (FIX-B). Debuffed cards are worthless (skip).
                mime = any(j.has_flag("retriggers_held") for j in self.jokers)
                for c in self.hand:
                    if c.seal != "Blue" or c.debuffed:
                        continue
                    for _ in range(2 if mime else 1):
                        if len(self.consumable_hand) >= self.consumable_slots:
                            break
                        self.consumable_hand.append(planet_key)
                    if len(self.consumable_hand) >= self.consumable_slots:
                        break

        # Boss blind beaten: fire on_boss_beaten hooks
        if self.current_blind.is_boss:
            self._fire_joker_hook("on_boss_beaten", None)
            self._undo_boss_debuffs(self.current_blind.boss_key)
            # The Boss Blind resolved — Luchador's one-shot disable is consumed
            self.boss_disabled_override = False
            # Investment Tag: +$25 after defeating the next Boss Blind
            if self.investment_pending:
                self.investment_pending = False
                self.dollars += 25

        # Pre-compute deck stats for jokers that need them (e.g. Cloud 9)
        deck_nines = sum(1 for c in self.deck + self.hand + self.spent if c.rank == 9)
        # Fire on_round_end hooks; collect pending money and consumables
        deferred = []
        for j in self.jokers:
            j.state["deck_nines"] = deck_nines  # for Cloud 9
            j.fire("on_round_end", None)
            pm = j.state.pop("pending_money", 0)
            self.dollars += pm
            self.run_stats["econ_source"] += pm
            deferred.extend(j.state.pop("pending_consumables", []))
        self._grant_pending(deferred)

        # Self-destructing jokers (Gros Michel 1/6, Cavendish 1/1000, Turtle
        # Bean at 0) set state["destroyed"] in on_round_end — honor it.
        self.jokers = [j for j in self.jokers if not j.state.pop("destroyed", False)]

        # Gold ENHANCEMENT: $3 per card held in hand at round end (doc §6).
        # Mime retriggers held-in-hand abilities (capability flag, R3) and a
        # Red seal on the card itself retriggers it too (RULING-R); a debuffed
        # card is worthless. (Gold SEAL was moved to scoring — it pays $3 when
        # SCORED, §3.1.)
        mime = any(j.has_flag("retriggers_held") for j in self.jokers)
        for c in self.hand:
            if c.debuffed or c.enhancement != "Gold":
                continue
            triggers = 1 + (1 if mime else 0) + (1 if c.seal == "Red" else 0)
            self.dollars += 3 * triggers
            self.run_stats["econ_source"] += 3 * triggers

        # Reset hand size mods from boss (bl_manacle) — permanent hand_size_mod
        # (Ouija/Ectoplasm) survives the restore
        if self.current_blind.boss_key == "bl_manacle":
            self.hand_size = HAND_SIZE + self.hand_size_mod

        # Reset reroll cost and free rerolls
        self.reroll_cost = 5
        self.free_rerolls_remaining = self.free_rerolls_per_round

        # Pre-select the upcoming Boss Blind (when the next blind is the
        # Boss) so the shop knows the boss — Director's Cut rerolls and the
        # graph's boss-counter term both need it (real game: boss revealed
        # with the shop).
        self._preselect_next_boss()
        # Generate shop. The Voucher slot restocks only after a Boss Blind is
        # defeated (real game §17); non-Boss blinds keep the same voucher.
        self.current_shop = generate_shop(self, restock_voucher=self.current_blind.is_boss)
        self.state = State.SHOP
        # Entering the shop: Astronomer (free Planets), Chaos (free reroll),
        # Credit Card (debt) read presence; on_shop_enter also parks any
        # state the shop logic consumes (M1 B2).
        self._fire_joker_hook("on_shop_enter", None)

    def _end_shop(self):
        # Perkeo: "Creates a Negative copy of 1 random consumable card in your
        # possession at the end of the shop" (M1 B2 on_shop_leave dispatch).
        self._fire_joker_hook("on_shop_leave", None)
        # Advance blind
        self.blind_idx += 1
        if self.blind_idx >= 3:
            self.blind_idx = 0
            self.ante += 1
            self.ante_played_ids.clear()   # The Pillar: "played this ante" resets each ante
            if self.ante > 8:
                self.state = State.GAME_OVER
                return
        self._prepare_next_blind()

    def _reroll_boss(self):
        """Pay $10 to reroll the upcoming Boss Blind.

        Director's Cut allows this once per Ante; Retcon makes it unlimited.
        Only available in the shop before the Boss (the boss was pre-selected
        at shop entry — `next_boss_key`; the old guard fired only after the
        boss was beaten, i.e. never at the right time). The no-repeat rotation
        is preserved (the first pick's appearance is undone and the reselect
        excludes it). The rerolled boss's score scaling (Wall / Violet / The
        Needle) is applied when the blind is set up (_prepare_next_blind)."""
        if self.next_boss_key is None:
            return
        has_retcon = "v_retcon" in self.vouchers
        has_dc = "v_directors_cut" in self.vouchers
        if not (has_retcon or has_dc):
            return
        if not has_retcon and self.dc_reroll_ante == self.ante:
            return  # Director's Cut: once per Ante
        if self.dollars < 10:
            return
        self.dollars -= 10
        if not has_retcon:
            self.dc_reroll_ante = self.ante
        cur = self.next_boss_key
        self.boss_appearances[cur] = max(0, self.boss_appearances.get(cur, 0) - 1)
        new = self._select_boss(self.ante, exclude=cur)
        self.boss_appearances[new] = self.boss_appearances.get(new, 0) + 1
        self.next_boss_key = new

    def _skip_blind(self):
        """Skip a non-Boss blind (Boss can't be skipped) and claim its Tag."""
        if self.current_blind.kind == "Boss":
            return
        # Fire blind_skipped joker hooks
        self._fire_joker_hook("on_blind_skipped", None)
        # Claim the skip-blind Tag. The Double Tag copies the NEXT tag selected
        # (never itself); every other tag auto-applies at skip time.
        self.skipped_blinds += 1
        key = self.current_tag
        if key == "t_double":
            self.double_tag_active = True
        elif key and self.double_tag_active:
            self.double_tag_active = False
            apply_tag(self, key)
            apply_tag(self, key)
        elif key:
            apply_tag(self, key)
        # Pre-select the upcoming Boss Blind (when the skipped blind was the
        # Big one) BEFORE any free-pack BOOSTER_OPEN window, so the graph
        # knows the boss even while the pack is open. Idempotent — the later
        # _end_blind_and_enter_shop call is a no-op.
        self._preselect_next_boss()
        # Free-pack tags queue a booster — open the first one now (a doubled
        # pack tag queues more, resolved after each pick).
        if self.pending_packs:
            _open_next_pack(self)
        if self.state != State.BOOSTER_OPEN:
            self._end_blind_and_enter_shop()

    def _end_blind_and_enter_shop(self):
        self.reroll_cost = 5
        self.free_rerolls_remaining = self.free_rerolls_per_round
        # Pre-select the upcoming Boss Blind (when the skipped blind was the
        # Big one — the Boss Tag, if claimed, is consumed here). Idempotent.
        self._preselect_next_boss()
        # A skipped blind is never a Boss, so the Voucher slot persists
        # (restock_voucher defaults to False — real game §17).
        self.current_shop = generate_shop(self)
        self.state = State.SHOP
        self._fire_joker_hook("on_shop_enter", None)

    def _pick_booster(self, indices: list[int]):
        self.run_stats["packs_opened"] += 1
        picks = min(self.booster_picks_remaining, len(indices))
        for idx in indices[:picks]:
            if idx < len(self.booster_choices):
                choice = self.booster_choices[idx]
                if isinstance(choice, tuple) and choice[0] == "joker":
                    # Joker from a Buffoon pack — carries its rolled edition
                    _, key, edition = choice
                    self.grant_joker(key, edition)
                elif isinstance(choice, tuple) and choice[0] == "card":
                    # Playing card from Standard pack
                    self.deck.insert(0, choice[1])
                    # Hologram: X0.25 per card added to the run (M1 B2)
                    self._fire_joker_hook("on_card_added", None)
                elif isinstance(choice, str):
                    # Planet, tarot, or spectral key. Jokers never arrive as
                    # plain strings (they are ("joker", key, edition) tuples,
                    # handled above) — keeping them out of the consumable hand.
                    if len(self.consumable_hand) < self.consumable_slots:
                        self.consumable_hand.append(choice)
        self.booster_choices = []
        self.booster_picks_remaining = 0
        if self.pending_packs:
            # Double Tag on a pack tag: another free pack awaits before the shop
            _open_next_pack(self)
        elif self._shop_after_pack:
            # Free-pack Tag: enter the skipped blind's shop after the pack
            self._shop_after_pack = False
            self._end_blind_and_enter_shop()
        else:
            self.state = State.SHOP

    # ── Observation ──────────────────────────────────────────────────────────

    def _obs(self) -> GameState:
        return GameState(
            state=self.state,
            ante=self.ante,
            blind_kind=self.current_blind.kind,
            chips_target=self.current_blind.chips_target,
            chips_scored=self.chips_scored,
            hands_left=self.hands_left,
            discards_left=self.discards_left,
            dollars=self.dollars,
            hand=list(self.hand),
            deck_remaining=len(self.deck),
            jokers=list(self.jokers),
            consumable_hand=list(self.consumable_hand),
            planet_levels=dict(self.planet_levels),
            shop_items=list(self.current_shop),
            done=(self.state == State.GAME_OVER),
            won=(self.ante > 8 and self.state == State.GAME_OVER),
            info={
                "boss_key": self.current_blind.boss_key,
                "vouchers": list(self.vouchers),
                "booster_choices": list(self.booster_choices),
                "tag": self.current_tag,
            }
        )
