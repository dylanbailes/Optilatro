#!/usr/bin/env python3
"""
Apply the verified updates to docs/reference/balatro-mechanics.md.

Sources used (all verified against balatrowiki.org and balatro-rs game data):
  - Joker activation types:  https://balatrowiki.org/w/Activation_Type
  - Stickers + edition odds: https://balatrowiki.org/w/Card_modifiers
  - Boss min antes/rewards:  https://balatrowiki.org/w/Blinds_and_Antes
  - Shop weights:            https://balatrowiki.org/w/The_Shop
  - Sticker exemptions:      balatro-rs balatro-types/src/joker.rs (joker_data! table)
Every replacement is asserted to apply; the script exits non-zero if any misses.
"""
import re
import sys
from pathlib import Path

PATH = str(Path(__file__).resolve().parent.parent / "docs" / "reference" / "balatro-mechanics.md")
src = open(PATH, encoding="utf-8").read()
orig = src

failures = []

def sub(old, new, count=1):
    global src
    if src.count(old) != count:
        failures.append(f"pattern not found {src.count(old)}x: {old[:90]!r}")
        return
    src = src.replace(old, new)

# ---------------------------------------------------------------------------
# 1. Joker activation timing (Section 2) — timing blurb + Timing column
# ---------------------------------------------------------------------------
TIMING = {
    # Common
    "Joker": "Independent", "Greedy Joker": "On Scored", "Lusty Joker": "On Scored",
    "Wrathful Joker": "On Scored", "Gluttonous Joker": "On Scored",
    "Jolly Joker": "Independent", "Zany Joker": "Independent", "Mad Joker": "Independent",
    "Crazy Joker": "Independent", "Droll Joker": "Independent", "Sly Joker": "Independent",
    "Wily Joker": "Independent", "Clever Joker": "Independent",
    "Devious Joker": "Independent", "Crafty Joker": "Independent", "Half Joker": "Independent",
    "Credit Card": "Passive", "Banner": "Independent", "Mystic Summit": "Independent",
    "8 Ball": "On Scored", "Misprint": "Independent", "Raised Fist": "On Held",
    "Chaos the Clown": "Passive", "Scary Face": "On Scored", "Abstract Joker": "Independent",
    "Delayed Gratification": "Passive", "Gros Michel": "Independent",
    "Even Steven": "On Scored", "Odd Todd": "On Scored", "Scholar": "On Scored",
    "Business Card": "On Scored", "Supernova": "Independent", "Ride the Bus": "Mixed",
    "Egg": "Passive", "Runner": "Mixed", "Ice Cream": "Independent", "Splash": "Passive",
    "Blue Joker": "Independent", "Faceless Joker": "On Discard", "Green Joker": "Mixed",
    "Superposition": "Independent", "To Do List": "On Played", "Cavendish": "Independent",
    "Red Card": "Independent", "Square Joker": "Mixed", "Riff-Raff": "On Blind Select",
    "Photograph": "On Scored", "Reserved Parking": "On Held",
    "Mail-In Rebate": "On Discard", "Hallucination": "Passive",
    "Fortune Teller": "Independent", "Juggler": "Passive", "Drunkard": "Passive",
    "Golden Joker": "Passive", "Popcorn": "Independent", "Walkie Talkie": "On Scored",
    "Smiley Face": "On Scored", "Golden Ticket": "On Scored", "Swashbuckler": "Independent",
    "Hanging Chad": "On Scored", "Shoot the Moon": "On Held",
    # Uncommon
    "Joker Stencil": "Independent", "Four Fingers": "Passive", "Mime": "On Held",
    "Ceremonial Dagger": "Independent", "Marble Joker": "On Blind Select",
    "Loyalty Card": "Independent", "Dusk": "On Scored", "Fibonacci": "On Scored",
    "Steel Joker": "Independent", "Hack": "On Scored", "Pareidolia": "Passive",
    "Space Joker": "On Played", "Burglar": "On Blind Select", "Blackboard": "Independent",
    "Sixth Sense": "Passive", "Constellation": "Independent", "Hiker": "On Scored",
    "Card Sharp": "Independent", "Madness": "Independent", "Seance": "Independent",
    "Vampire": "Mixed", "Shortcut": "Passive", "Hologram": "Independent",
    "Cloud 9": "Passive", "Rocket": "Passive", "Midas Mask": "On Played",
    "Luchador": "Passive", "Gift Card": "Passive", "Turtle Bean": "Passive",
    "Erosion": "Independent", "To the Moon": "Passive", "Stone Joker": "Independent",
    "Lucky Cat": "Mixed", "Bull": "Independent", "Diet Cola": "Passive",
    "Trading Card": "On Discard", "Flash Card": "Independent", "Spare Trousers": "Mixed",
    "Ramen": "Mixed", "Seltzer": "On Scored", "Castle": "Mixed", "Mr. Bones": "Passive",
    "Acrobat": "Independent", "Sock and Buskin": "On Scored", "Troubadour": "Passive",
    "Certificate": "Passive", "Smeared Joker": "Passive", "Throwback": "Independent",
    "Rough Gem": "On Scored", "Bloodstone": "On Scored", "Arrowhead": "On Scored",
    "Onyx Agate": "On Scored", "Glass Joker": "Independent", "Showman": "Passive",
    "Flower Pot": "Independent", "Merry Andy": "Passive", "Oops! All 6s": "Passive",
    "The Idol": "On Scored", "Seeing Double": "Independent", "Matador": "Independent",
    "Satellite": "Passive", "Cartomancer": "On Blind Select", "Astronomer": "Passive",
    "Bootstraps": "Independent",
    # Rare
    "DNA": "On Played", "Vagabond": "Independent", "Baron": "On Held",
    "Obelisk": "Mixed", "Baseball Card": "On Other Jokers", "Ancient Joker": "On Scored",
    "Campfire": "Independent", "Blueprint": "On Other Jokers*", "Wee Joker": "Mixed",
    "Hit the Road": "Mixed", "The Duo": "Independent", "The Trio": "Independent",
    "The Family": "Independent", "The Order": "Independent", "The Tribe": "Independent",
    "Stuntman": "Independent", "Invisible Joker": "Passive", "Brainstorm": "On Other Jokers*",
    "Driver's License": "Independent", "Burnt Joker": "On Discard",
    # Legendary
    "Canio": "Mixed", "Triboulet": "On Scored", "Yorick": "Mixed",
    "Chicot": "On Blind Select", "Perkeo": "Passive",
}

# Insert the timing blurb after the rarity-odds paragraph, before Common table.
TIMING_BLURB = """Rarity odds when a Joker slot is randomly generated (shop, packs, etc.): Common 70%, Uncommon 25%, Rare 5%. Legendary Jokers never appear in the shop — only from **The Soul** spectral card. "Type" below is the Joker's primary scoring category (Chips / +Mult / xMult / Chips+Mult / Effect / Retrigger / Economy).

**Activation timing** — *when* in the scoring sequence each Joker fires (source: the Wiki's Activation Type page; the priority order is shown because earlier phases feed or miss later ones):

- **On Played (1)** — fires immediately when a hand is played, before scoring (scaling triggers, hand-level ups, transformations). Affects unscored cards too.
- **On Scored (2)** — fires for each card that scores (per-card Chips/Mult/Money, retriggers). Benefits from card retriggers (Hack, Sock and Buskin, Hanging Chad, Red Seal); does not fire for unscored or debuffed cards.
- **On Held (3)** — fires from cards held in hand during scoring (Raised Fist, Shoot the Moon, Reserved Parking, Baron, Mime's retriggers).
- **Independent (4)** — fires once per hand after all cards have scored (flat +Chips/+Mult, xMult conditions, deck/hand-state checks). A Joker's own Foil/Holographic/Polychrome Edition also applies in this phase. Not affected by card retriggers or card debuffs.
- **On Other Jokers (5)** — fires off other Jokers (Baseball Card is currently the only one). \*Blueprint/Brainstorm have no activation of their own: they execute before everything (priority 0) and copy the targeted Joker's ability at that Joker's own timing.
- **On Discard (6)** — fires when cards or a poker hand are discarded (Faceless Joker, Mail-In Rebate, Trading Card, Burnt Joker, plus the discard-scaling components of Mixed Jokers).
- **On Blind Select (7)** — fires when a Blind is chosen; does not fire if the Blind is skipped (Riff-Raff, Marble Joker, Burglar, Cartomancer, Chicot). Ceremonial Dagger and Madness also act on Blind selection but *score* as Independent.
- **Passive / N/A (7)** — never activates, so it cannot be copied by Blueprint/Brainstorm; effects (economy, hand-size, suit/size modifiers) apply continuously.
- **Mixed** — combines two phases, usually scaling in one phase (On Played/On Scored/On Discard) and delivering the bonus in another (Independent).

Priority order (lowest fires first): **On Played → On Scored → On Held → Independent → On Other Jokers → On Discard → On Blind Select / Passive**. A practical consequence: On-Scored and On-Held xMult apply *before* Independent +Mult, so e.g. Ancient Joker's per-card xMult does not amplify Droll Joker's +10 Mult in the same hand."""

sub(
    "Rarity odds when a Joker slot is randomly generated (shop, packs, etc.): Common 70%, Uncommon 25%, Rare 5%. Legendary Jokers never appear in the shop — only from **The Soul** spectral card. \"Type\" below is the Joker's primary scoring category (Chips / +Mult / xMult / Chips+Mult / Effect / Retrigger / Economy).",
    TIMING_BLURB,
)

# Header rows of the four joker tables get the Timing column.
sub("| Joker | Cost | Type | Effect |", "| Joker | Cost | Type | Effect | Timing |", count=4)

# Fix Riff-raff capitalization to the real-game spelling (also keeps name matching).
sub("| **Riff-raff** | $6 | Effect | When Blind is selected, create 2 Common Jokers |",
    "| **Riff-Raff** | $6 | Effect | When Blind is selected, create 2 Common Jokers |")

# Append a Timing cell to every joker row.
def add_timing(line):
    m = re.match(r"\| \*\*([^*]+)\*\* \|", line)
    if not m:
        return None
    name = m.group(1)
    if name in TIMING:
        return line.rstrip("\n") + f" {TIMING[name]} |\n"
    return None

out_lines = []
matched = 0
for line in src.splitlines(keepends=True):
    new = add_timing(line)
    if new is not None:
        out_lines.append(new)
        matched += 1
    else:
        out_lines.append(line)
if matched != 150:
    failures.append(f"timing cells added: {matched}, expected 150")
src = "".join(out_lines)

# ---------------------------------------------------------------------------
# 2. Boss blinds (Section 10): Min. Ante column + selection algorithm
# ---------------------------------------------------------------------------
sub(
    "Boss Blinds must be played (can't be skipped). Regular boss blinds can appear from Ante 1 onward (some have a minimum Ante); the 5 Finisher blinds are exclusive to Ante 8.",
    "Boss Blinds must be played (can't be skipped). Each regular Boss Blind has a **minimum Ante** (column below; \"1\" = any Ante — Ante 1 has only these 8 bosses). The 5 Showdown blinds (\"Finishers\") are exclusive to Ante 8 and recur at Antes 16/24/32 in Endless mode.",
)

BOSS_OLD = """| Boss Blind | Effect |
|---|---|
| The Hook | Discards 2 random unplayed cards after every played hand |
| The Ox | Sets money to $0 when your most-played poker hand is played |
| The House | First hand of the round is dealt face down |
| The Wall | Requires 4x base Chips instead of 2x |
| The Wheel | 1 in 7 chance for each card *drawn* (not played) to be dealt face down |
| The Arm | Decreases the level of the played poker hand by 1 (floor of level 1; permanent for the rest of the run) |
| The Club | Debuffs all Club cards |
| The Fish | Cards are drawn face down after each played/discarded hand, accumulating |
| The Psychic | Must play exactly 5 cards every hand |
| The Goad | Debuffs all Spade cards |
| The Water | Start the round with 0 discards |
| The Window | Debuffs all Diamond cards |
| The Manacle | -1 hand size |
| The Eye | Cannot play the same poker hand type twice in a row |
| The Mouth | Only the poker hand type of the first played hand can be played this round |
| The Plant | Debuffs all face cards |
| The Serpent | Draw 3 cards after each played/discarded hand, regardless of hand size |
| The Pillar | Cards already played earlier this Ante are debuffed |
| The Needle | Only 1 hand may be played the entire round |
| The Head | Debuffs all Heart cards |
| The Tooth | Lose $1 per card played |
| The Flint | Halves all base Chips and Mult for played hands |
| The Mark | Face cards are dealt face down |
| **Amber Acorn** *(Finisher)* | Flips all Jokers face down and shuffles their positions |
| **Cerulean Bell** *(Finisher)* | Forces a random card to always be selected each hand |
| **Crimson Heart** *(Finisher)* | Debuffs a random Joker each hand |
| **Verdant Leaf** *(Finisher)* | All cards are debuffed until a Joker is sold |
| **Violet Vessel** *(Finisher)* | Requires 6x base Chips instead of 2x |"""

BOSS_NEW = """| Boss Blind | Min. Ante | Effect |
|---|---|---|
| The Hook | 1 | Discards 2 random unplayed cards after every played hand |
| The Ox | 6 | Sets money to $0 when your most-played poker hand is played |
| The House | 2 | First hand of the round is dealt face down |
| The Wall | 2 | Requires 4x base Chips instead of 2x |
| The Wheel | 2 | 1 in 7 chance for each card *drawn* (not played) to be dealt face down |
| The Arm | 2 | Decreases the level of the played poker hand by 1 (floor of level 1; permanent for the rest of the run) |
| The Club | 1 | Debuffs all Club cards |
| The Fish | 2 | Cards are drawn face down after each played/discarded hand, accumulating |
| The Psychic | 1 | Must play exactly 5 cards every hand |
| The Goad | 1 | Debuffs all Spade cards |
| The Water | 2 | Start the round with 0 discards |
| The Window | 1 | Debuffs all Diamond cards |
| The Manacle | 1 | -1 hand size |
| The Eye | 3 | Cannot play the same poker hand type twice in a row |
| The Mouth | 2 | Only the poker hand type of the first played hand can be played this round |
| The Plant | 4 | Debuffs all face cards |
| The Serpent | 5 | Draw 3 cards after each played/discarded hand, regardless of hand size |
| The Pillar | 1 | Cards already played earlier this Ante are debuffed |
| The Needle | 2 | Only 1 hand may be played the entire round (score requirement is 1x base — see Section 16) |
| The Head | 1 | Debuffs all Heart cards |
| The Tooth | 3 | Lose $1 per card played |
| The Flint | 2 | Halves all base Chips and Mult for played hands |
| The Mark | 2 | Face cards are dealt face down |
| **Amber Acorn** *(Finisher)* | 8 | Flips all Jokers face down and shuffles their positions |
| **Cerulean Bell** *(Finisher)* | 8 | Forces a random card to always be selected each hand |
| **Crimson Heart** *(Finisher)* | 8 | Debuffs a random Joker each hand |
| **Verdant Leaf** *(Finisher)* | 8 | All cards are debuffed until a Joker is sold |
| **Violet Vessel** *(Finisher)* | 8 | Requires 6x base Chips instead of 2x |

**Selection algorithm.** When a Boss is chosen the game first filters to Bosses whose Min. Ante ≤ current Ante, then restricts further to those with the **fewest appearances** so far in the run (a Boss cannot reappear until every eligible Boss has appeared at least once, whether defeated or rerolled away), and draws the final pick from that set via the run's seeded RNG. Antes that are multiples of 8 (8/16/24/32…) draw exclusively from the 5-Boss Showdown pool. Rerolling (Director's Cut / Retcon) re-rolls within the same pool; on Ante 8 a reroll always produces a Showdown Blind. Disabling a Boss (Luchador / Chicot) restores The Wall's and Violet Vessel's requirement to 2x base, while The Needle stays at its 1x requirement.

**Matador-compatible Bosses** (a played hand can trigger the Boss ability for Matador's $8): The Ox, The Arm, The Club, The Psychic, The Goad, The Window, The Eye, The Mouth, The Plant, The Pillar, The Head, The Flint, and Verdant Leaf."""
sub(BOSS_OLD, BOSS_NEW)

# ---------------------------------------------------------------------------
# 3. Stakes (Section 12): fix the Rental wording
# ---------------------------------------------------------------------------
sub(
    "| Gold | Shop/pack Jokers may spawn with the Rental sticker (costs $1/round) |",
    "| Gold | Shop/pack Jokers may spawn with the Rental sticker (costs $1 to buy, charges $3 at end of each round — see Section 13) |",
)

# ---------------------------------------------------------------------------
# 4. New Section 13: Sticker Mechanics (insert before Tags)
# ---------------------------------------------------------------------------
STICKERS = """## 13. Sticker Mechanics

Stickers are modifiers on Jokers. Three **in-run** stickers affect gameplay; eight **stake** stickers are purely cosmetic (they mark that a Joker or Deck has won a run at a given Stake) and are not covered here. Vouchers, Booster Packs, and Consumables can never have stickers. Stickers are permanent for the run and can be applied to an existing Joker only when it is generated.

**Spawn chances.** Each in-run sticker has a flat **30%** chance to appear on an eligible Joker generated by the Shop or a Booster Pack (no Ante scaling). Eternal and Perishable are rolled together and are **mutually exclusive** (60% combined, so a Joker is clean of both 40% of the time); Rental is rolled independently (30%). On Gold Stake this gives a Joker a 28% (40% × 70%) chance of having no in-run stickers. Jokers created mid-run (Riff-Raff, The Soul, Invisible Joker copies, etc.) do not get sticker rolls — Legendary Jokers are sticker-compatible in principle but have no way to receive one.

| Stake | Sticker | Effect |
|---|---|---|
| Black+ | **Eternal** | The Joker cannot be **sold or destroyed** — immune to Madness, Ceremonial Dagger, Ankh, Hex, trading, etc. It keeps its sell value. |
| Orange+ | **Perishable** | The Joker is **debuffed after 5 rounds**. The counter decreases by 1 at the end of each round; on the 5th round the Joker is debuffed *before* the cash-out payout, so end-of-round money Jokers (Golden Joker, Cloud 9, Rocket, etc.) only pay out for 4 full rounds. The debuff is permanent. |
| Gold | **Rental** | Costs **$1 to buy** regardless of the Joker's base cost, and charges **$3 at the end of every round** (before cash-out; can put you into debt). |

**Exemptions.** 11 Jokers cannot receive the Eternal sticker (self-destructing, decaying, or sell-reliant Jokers): Gros Michel, Ice Cream, Cavendish, Popcorn, Ramen, Seltzer, Turtle Bean, Diet Cola, Luchador, Mr. Bones, Invisible Joker.

18 Jokers cannot receive the Perishable sticker (non-retroactive scaling Jokers, which start at 0 and would be useless if debuffed before they can scale): Ceremonial Dagger, Ride the Bus, Runner, Constellation, Green Joker, Red Card, Madness, Square Joker, Vampire, Hologram, Rocket, Obelisk, Lucky Cat, Flash Card, Spare Trousers, Castle, Glass Joker, Wee Joker.

**Rules & interactions.**
- Stacking: Eternal + Rental and Perishable + Rental are both allowed; Eternal + Perishable is not.
- Copies: Invisible Joker and Ankh copy the original Joker's Edition (except Negative) **and** Stickers.
- A debuffed (e.g. Perishable) Joker's own effect and Edition are disabled, but it still contributes its sell value to Swashbuckler / Temperance, its +3 Mult to Abstract Joker, and its rarity to Baseball Card.

---

"""
sub("## 13. Tags", STICKERS + "## 14. Tags")

# ---------------------------------------------------------------------------
# 5. Renumber remaining sections
# ---------------------------------------------------------------------------
sub("## 14. Booster Packs", "## 15. Booster Packs")
sub("## 15. Ante & Blind Score Requirements", "## 16. Ante, Blind Score Requirements & Reward Money")
sub("## 16. Shop Pricing & Sell Value Formulas", "## 17. Shop Pricing, Sell Value & Generation Weights")
sub("## 17. Known Gaps (Not Covered by This Sheet)", "## 18. Known Gaps (Not Covered by This Sheet)")
sub("## 18. Audit Log", "## 19. Audit Log")

# ---------------------------------------------------------------------------
# 6. Section 16 (Ante & Blind): exact chip table + rewards + Endless formula
# ---------------------------------------------------------------------------
ANTE_OLD = """Blind score required = Ante's **base chip target** × a per-blind multiplier: Small Blind 1x, Big Blind 1.5x, Boss Blind 2x (unless a boss overrides it, e.g. The Wall 4x, Violet Vessel 6x, or The Flint halves the hand's own scoring instead of raising the target).

Approximate White Stake base chip targets by Ante (each ante = 1 Small + 1 Big + 1 Boss Blind; clearing the Boss Blind advances the Ante):

| Ante | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 |
|---|---|---|---|---|---|---|---|---|
| Base Chips | 300 | 800 | 2,000 | 5,000 | 11,000 | 20,000 | 35,000 | 50,000 |

Higher Stakes (Green/Purple onward) scale these targets up faster per Ante; the Plasma Deck doubles them outright. Beating the Ante 8 Boss Blind wins the run; Endless mode continues scaling requirements past Ante 8 (values overflow floating-point precision around Ante 39)."""

ANTE_NEW = """Blind score required = Ante's **base chip target** × a per-blind multiplier: Small Blind 1x, Big Blind 1.5x, Boss Blind 2x. Exceptions: The Wall 4x, Violet Vessel 6x, **The Needle 1x**; The Flint halves the hand's own scoring instead of raising the target. Disabling a Boss (Luchador / Chicot) restores The Wall / Violet Vessel to 2x base (The Needle stays at 1x).

Base chip targets by Ante and Stake (each Ante = 1 Small + 1 Big + 1 Boss Blind; clearing the Boss Blind advances the Ante). Green+ = Green Stake or higher; Purple+ = Purple Stake or higher:

| Ante | White | Green+ | Purple+ |
|---|---|---|---|
| 0 and lower | 100 | 100 | 100 |
| 1 | 300 | 300 | 300 |
| 2 | 800 | 900 | 1,000 |
| 3 | 2,000 | 2,600 | 3,200 |
| 4 | 5,000 | 8,000 | 9,000 |
| 5 | 11,000 | 20,000 | 25,000 |
| 6 | 20,000 | 36,000 | 60,000 |
| 7 | 35,000 | 60,000 | 110,000 |
| 8 (Showdown) | 50,000 | 100,000 | 200,000 |

The Plasma Deck doubles the requirement on all Stakes. Beating the Ante 8 Showdown Blind wins the run.

**Endless mode (Ante 9+):** requirements follow `req(A) = req(8) × (1.6 + (0.75·(A−8)) / (1 + 0.2·(A−8)))^(A−8)`, rounded to 2 significant figures. At **Ante 39** the requirement exceeds 2^1024 (≈1.8×10^308) and overflows to `naneinf`, making Ante 39 the effective ceiling.

### Blind reward money

Rewards are **flat per blind tier and do not scale with Ante** (Stake/Deck/Challenge modifiers aside):

| Blind | Reward |
|---|---|
| Small Blind | $3 ($0 on Red Stake or higher) |
| Big Blind | $4 |
| Boss Blind (Antes 1–7) | $5 |
| Showdown Blind (Ante 8 / 16 / 24 / 32) | $8 |

Skipping a Small or Big Blind pays nothing — you receive a Tag instead (Section 14). Reward money is paid on top of hand-payouts and interest (Section 0)."""
sub(ANTE_OLD, ANTE_NEW)

# ---------------------------------------------------------------------------
# 7. Section 17 (Shop): add generation-weights subsection
# ---------------------------------------------------------------------------
WEIGHTS = """- Rerolling the shop is priced separately: starts at $5, +$1 per reroll that shop visit, resets to $5 on entering a new shop (Reroll Surplus/Reroll Glut lower the starting price to $3/$1; the D6 Tag zeroes it for the next shop only).

### Shop card-type & modifier generation weights

**Card-type odds** (per random card slot; weight → probability): Joker 20 (**71.4%**), Tarot 4 (**14.3%**), Planet 4 (**14.3%**). Tarot Merchant raises Tarot's weight to 9.6 (**≈28.6%**); Tarot Tycoon to 32 (**≈57.1%**). Planet Merchant/Tycoon do the same for Planets. Magic Trick adds Playing Cards at weight 4; the Ghost Deck adds Spectral cards at weight 2.

**Joker rarity odds** (once a Joker is rolled): Common 70%, Uncommon 25%, Rare 5% — unchanged by Ante. Legendary Jokers never roll in the shop (The Soul only).

**Duplicate suppression (Showman rule):** without Showman, any Joker/Tarot/Planet/Spectral already in the player's possession is excluded from the pool for the rest of the run, in the Shop and Booster Packs alike. Merely *seeing* a card does not exclude it (it can reappear on a reroll). Showman lifts the restriction for all four types — even The Soul and Black Hole can then duplicate, at very low odds.

**Edition odds (Jokers):** Negative 0.3%, Polychrome 0.3%, Holographic 1.4%, Foil 2%. Hone roughly doubles Foil/Holo/Poly (4% / 2.8% / 0.9%); Glow Up quadruples them (8% / 5.6% / 2.1%). Negative stays 0.3% regardless.

**Illusion (shop Playing Cards):** Enhancement 40%, Edition 20%, and Seals **never** (bugged in v1.0.1o — the described Seal effect never rolls); Illusion cards are unaffected by Hone/Glow Up. Booster-Pack Playing Cards (Standard Packs) use different odds: Foil 4% / Holographic 2.8% / Polychrome 1.2%, Enhancement 40%, Seal 20% (evenly split across variants).

**Booster Pack & Voucher slots:** the Shop always offers 2 Booster Packs (the first Shop of a run guarantees one normal Buffoon Pack). Rerolling does not restock Packs or the Voucher — Packs restock on entering a new Shop; the Voucher restocks only after beating the Boss Blind."""
sub(
    "- Rerolling the shop is priced separately: starts at $5, +$1 per reroll that shop visit, resets to $5 on entering a new shop (Reroll Surplus/Reroll Glut lower the starting price to $3/$1; the D6 Tag zeroes it for the next shop only).",
    WEIGHTS,
)

# ---------------------------------------------------------------------------
# 8. Known Gaps rewrite (now only Challenge Decks + unlock requirements)
# ---------------------------------------------------------------------------
GAPS_OLD = """This sheet is not yet comprehensive enough for a full engine implementation in the following areas:

- **Challenge Decks (20 total).** Only the 15 standard/Stake-linked Decks (Section 11) are covered. Balatro also has 20 separate Challenge Decks (White Stake only), each with its own custom rule set and banned-item list — entirely absent here.
- **Joker activation timing.** The "Type" column in Section 2 (Chips/+Mult/xMult/etc.) describes *what* a Joker does, not *when* it fires. Engine-critical timing categories (Independent, On Scored, On Held, On Discard, On Blind Selected, Retrigger) are not encoded per-Joker and would need to be added for accurate simulation of trigger order.
- **Joker unlock requirements.** None of the 150 Jokers' unlock conditions are listed (105 are available from the start; 45 require specific achievements).
- **Sticker mechanics as a standalone topic.** Eternal, Perishable, and Rental stickers are only mentioned in passing under Stakes (Section 12). Their full rules (e.g. Perishable's 5-round countdown and how it displays, Eternal's interaction with sell/destroy effects, Rental's $1/round end-of-round charge) deserve their own section since they matter independent of Stake.
- **Per-Boss-Blind minimum Ante.** Section 10 notes "some have a minimum Ante" but doesn't specify which or what the minimum is.
- **Exact rarity/appearance-weight algorithm.** Section 2's 70/25/5 Joker odds are the base rarity weights, but actual shop-slot generation also weighs against owned/seen cards, vouchers like Hone/Glow Up, and Showman; the precise weighting algorithm isn't documented.
- **Endless-mode scaling formula.** Section 15 notes score requirements keep scaling past Ante 8 but doesn't give the growth formula or confirm the exact overflow Ante.
- **Score-required reward-money formula.** Blind cash rewards (Small/Big/Boss) aren't broken out with exact values or how they scale per Ante/Stake beyond the new Section 0 summary."""

GAPS_NEW = """This sheet is not yet comprehensive enough for a full engine implementation in the following areas:

- **Challenge Decks (20 total).** Only the 15 standard/Stake-linked Decks (Section 11) are covered. Balatro also has 20 separate Challenge Decks (White Stake only), each with its own custom rule set and banned-item list — entirely absent here.
- **Joker unlock requirements.** None of the 150 Jokers' unlock conditions are listed (105 are available from the start; 45 require specific achievements)."""
sub(GAPS_OLD, GAPS_NEW)

# ---------------------------------------------------------------------------
# 9. Audit Log: fix stale section refs + add this pass's corrections
# ---------------------------------------------------------------------------
sub("| 13. Tags | Investment Tag |", "| 14. Tags | Investment Tag |")
sub("| 13. Tags | Coupon Tag |", "| 14. Tags | Coupon Tag |")
sub(
    "inconsistent with Section 16's own description of Coupon Tag",
    "inconsistent with Section 17's own description of Coupon Tag",
)

AUDIT_ADD = """| Section | Item | Was | Corrected To |
|---|---|---|---|
| 0. Starting params | Blind rewards | "Small $3–4, Big $4–5, Boss $5–8, scales up slightly with Ante" | Flat per tier — Small $3, Big $4, Boss $5, Showdown $8 — no Ante scaling (Section 16) |
| 12. Stakes | Rental sticker (Gold) | "costs $1/round" | Costs $1 to buy, charges $3 at end of every round (Section 13) |
| 15→16. Antes | The Needle score req | Boss multiplier always 2x | The Needle is 1x base; The Wall 4x; Violet Vessel 6x |
| 2. Jokers | Ceremonial Dagger text | "it's Mult" | "its Mult" (typo) |
| 2. Jokers | Activation timing | A Known Gap | "Timing" column added to all 150 Jokers (Wiki Activation Type categories) |
| 10. Boss Blinds | Minimum Ante | "some have a minimum Ante" | Full Min. Ante column + selection algorithm added |
| 13. Stickers | In-run stickers | Mentioned only under Stakes | New Section 13: spawn chances, countdown, exemptions (11 Eternal / 18 Perishable), stacking |
| 16. Antes | Rewards / stakes / Endless | No reward table, White-only targets, no growth formula | Flat $3/$4/$5/$8 rewards, Green/Purple stake targets, Endless formula + Ante-39 overflow |
| 17. Shop | Generation weights | A Known Gap | Card-type odds, rarity odds, Showman rule, edition odds, Illusion odds added |
"""
sub("Also added: Section 0 (starting run parameters)", AUDIT_ADD + "Also added: Section 0 (starting run parameters)")

# ---------------------------------------------------------------------------
# 10. Cross-reference fixes
# ---------------------------------------------------------------------------
sub(
    "**Does not cover** the 20 Challenge Decks or per-Joker unlock conditions/activation timing — see Section 17 for the full list of gaps.",
    "**Does not cover** the 20 Challenge Decks or per-Joker unlock conditions — see Section 18 for the full list of gaps.",
)
sub(
    "Small Blind reward $3–4 (skippable), Big Blind reward $4–5 (skippable), Boss Blind reward $5–8 (mandatory) — reward money scales up slightly with Ante and resets/varies by Stake (e.g. Red Stake removes the Small Blind reward entirely; see Section 12).",
    "Blind rewards are flat per tier and do not scale with Ante: Small Blind **$3** (skippable; **$0** on Red Stake or higher), Big Blind **$4** (skippable), Boss Blind **$5** (mandatory; **$8** for the Ante-8 Showdown blinds). See Section 12 for Stakes and Section 16 for the full reward table.",
)
sub(
    "(See Section 16 for the general sell-value formula these follow.)",
    "(See Section 17 for the general sell-value formula these follow.)",
)

# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------
if failures:
    print("FAILURES:")
    for f in failures:
        print("  -", f)
    sys.exit(1)

open(PATH, "w", encoding="utf-8").write(src)
print(f"OK — applied all updates ({len(orig)} -> {len(src)} chars)")
