# Balatro Mechanics Reference Sheet

A reference for building a Balatro simulator/engine. Covers hand types & scoring, all 150 Jokers, 22 Tarots, 12 Planets, 18 Spectrals, card Enhancements/Editions/Seals, all 32 Vouchers, all 28 (standard) Boss Blinds, the 15 standard Decks, 24 Tags, 8 Stakes, and Booster Packs. **Does not cover** the 20 Challenge Decks or per-Joker unlock conditions — see Section 18 for the full list of gaps.

Data cross-checked against the [balatro-rs](https://github.com/evanofslack/balatro-rs) engine source (`balatro-types` crate) and the Balatro Wiki as of August 2026. `X` in an effect (e.g. `X1.5 Mult`) denotes a multiplicative Mult bonus; a bare `+N Mult`/`+N Chips` is additive.

---

## 0. Starting Run Parameters

Default state at the start of every run (White Stake, no deck modifier): **$4** starting money, **8** hand size, **4** hands per round, **3** discards per round, **5** Joker slots, **2** consumable slots. Blind rewards are flat per tier and do not scale with Ante: Small Blind **$3** (skippable; **$0** on Red Stake or higher), Big Blind **$4** (skippable), Boss Blind **$5** (mandatory; **$8** for the Ante-8 Showdown blinds). See Section 12 for Stakes and Section 16 for the full reward table.

### "Debuffed" (referenced throughout Section 10)

A card or Joker marked **debuffed** (usually by a Boss Blind) has all of its modifier effects disabled:
- A debuffed **playing card** contributes **0 Chips and 0 Mult** when scored, and its Enhancement/Edition/Seal effects do not trigger — *except* the Negative edition (still grants its slot bonus) and the Stone enhancement's "no rank/suit" property, which persist. A debuffed Wild Card reverts to its original printed suit.
- A debuffed **Joker** cannot trigger its effect (but keeps its sell value and can still be targeted by Swashbuckler, Temperance, Madness, etc.).
- Debuffed cards still occupy a position in the played hand and still count toward hand-type identification (e.g. a debuffed card can still complete a Flush), they simply score nothing.
- Debuffs from suit/rank-targeting Boss Blinds (The Club, The Goad, The Window, The Head, The Plant, The Mark) last only for that round; The Pillar's debuff is specific to cards already played earlier in the Ante.

## 1. Scoring Basics

**Formula:** `Score = Chips × Mult`, evaluated for the played poker hand.

**Scoring resolves in this order** (matches the engine's evaluation order):
1. **Hand level base** — the played hand's current level Chips/Mult are added first (e.g. a level-1 Pair adds 10 Chips and 2 Mult before anything else).
2. **Scored cards, left to right** — each card in the scoring hand (not just the highest hand type's cards, but any that count) adds its own rank chip value, then its Enhancement effect, then its Edition effect, then its Seal effect, in that order per card.
3. **Held-in-hand cards** — cards left in hand (not played) trigger their effects, e.g. Steel Card Mult, Baron, Shoot the Moon.
4. **Jokers, left to right** — each Joker's effect fires in its shop-slot order, sandwiched by its own Edition bonus (Foil/Holo/Polychrome) if it has one.
5. Some effects (e.g. the Observatory voucher's Planet-card xMult) are explicitly applied last.

**Card chip values:** 2–10 = face value, Jack/Queen/King = 10, Ace = 11.

**Face cards** = Jack, Queen, King (Ace is not a face card). **Even ranks** = 10,8,6,4,2. **Odd ranks** = A,9,7,5,3 (Ace counts as odd).

**"Contains" vs "Is":** A Joker that triggers on a hand that "contains" X counts hands that include X as a sub-hand (e.g. a Three of a Kind *contains* a Pair; a Four of a Kind *contains* a Two Pair is **false**, since Two Pair needs two distinct ranks). A Joker that requires the poker hand *is* X only triggers if the hand is classified as exactly X, not a higher hand built on top of it.

### Poker Hand Types, Base Values & Planet Cards

Each hand type has a level (starts at 1) with its own Chips/Mult that increase permanently when its Planet card is used. Values below are level 1 (base); "+per level" is the increment each additional level adds.

| Hand | Planet Card | Base Chips | Base Mult | Chips/level | Mult/level |
|---|---|---|---|---|---|
| High Card | Pluto | 5 | 1 | +10 | +1 |
| Pair | Mercury | 10 | 2 | +15 | +1 |
| Two Pair | Uranus | 20 | 2 | +20 | +1 |
| Three of a Kind | Venus | 30 | 3 | +20 | +2 |
| Straight | Saturn | 30 | 4 | +30 | +3 |
| Flush | Jupiter | 35 | 4 | +15 | +2 |
| Full House | Earth | 40 | 4 | +25 | +2 |
| Four of a Kind | Mars | 60 | 7 | +30 | +3 |
| Straight Flush | Neptune | 100 | 8 | +40 | +4 |
| Five of a Kind* | Planet X | 120 | 12 | +35 | +3 |
| Flush House* | Ceres | 140 | 14 | +40 | +4 |
| Flush Five* | Eris | 160 | 16 | +50 | +3 |

\* "Secret" hands — only achievable with 5+ card hands (via enhancements/duplication) and their Planet cards aren't sold in the shop by default; obtained via Black Hole, packs, or specific Jokers.

Royal Flush is detected separately (for Jokers checking "is a Royal Flush") but shares Straight Flush's level/scoring — there's no 13th separate leveled hand.

Tarot/Planet cards cost **$3** and sell for **$1**. Spectral cards cost **$4** and sell for **$2**. (See Section 17 for the general sell-value formula these follow.)

---

## 2. Jokers (150 total)

Rarity odds when a Joker slot is randomly generated (shop, packs, etc.): Common 70%, Uncommon 25%, Rare 5%. Legendary Jokers never appear in the shop — only from **The Soul** spectral card. "Type" below is the Joker's primary scoring category (Chips / +Mult / xMult / Chips+Mult / Effect / Retrigger / Economy).

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

Priority order (lowest fires first): **On Played → On Scored → On Held → Independent → On Other Jokers → On Discard → On Blind Select / Passive**. A practical consequence: On-Scored and On-Held xMult apply *before* Independent +Mult, so e.g. Ancient Joker's per-card xMult does not amplify Droll Joker's +10 Mult in the same hand.

### Common Jokers (61)

| Joker | Cost | Type | Effect | Timing |
|---|---|---|---|---|
| **Joker** | $2 | +Mult | +4 Mult | Independent |
| **Greedy Joker** | $5 | +Mult | Played cards with Diamond suit give +3 Mult when scored | On Scored |
| **Lusty Joker** | $5 | +Mult | Played cards with Heart suit give +3 Mult when scored | On Scored |
| **Wrathful Joker** | $5 | +Mult | Played cards with Spade suit give +3 Mult when scored | On Scored |
| **Gluttonous Joker** | $5 | +Mult | Played cards with Club suit give +3 Mult when scored | On Scored |
| **Jolly Joker** | $3 | +Mult | +8 Mult if played hand contains a Pair | Independent |
| **Zany Joker** | $4 | +Mult | +12 Mult if played hand contains a Three of a Kind | Independent |
| **Mad Joker** | $4 | +Mult | +10 Mult if played hand contains a Two Pair | Independent |
| **Crazy Joker** | $4 | +Mult | +12 Mult if played hand contains a Straight | Independent |
| **Droll Joker** | $4 | +Mult | +10 Mult if played hand contains a Flush | Independent |
| **Sly Joker** | $3 | Chips | +50 Chips if played hand contains a Pair | Independent |
| **Wily Joker** | $4 | Chips | +100 Chips if played hand contains a Three of a Kind | Independent |
| **Clever Joker** | $4 | Chips | +80 Chips if played hand contains a Two Pair | Independent |
| **Devious Joker** | $4 | Chips | +100 Chips if played hand contains a Straight | Independent |
| **Crafty Joker** | $4 | Chips | +80 Chips if played hand contains a Flush | Independent |
| **Half Joker** | $5 | +Mult | +20 Mult if played hand contains 3 or fewer cards | Independent |
| **Credit Card** | $1 | Economy | Go up to -$20 in debt | Passive |
| **Banner** | $5 | Chips | +30 Chips for each remaining discard | Independent |
| **Mystic Summit** | $5 | +Mult | +15 Mult when 0 discards remaining | Independent |
| **8 Ball** | $5 | Effect | 1 in 4 chance for each played 8 to create a Tarot card when scored | On Scored |
| **Misprint** | $4 | +Mult | +0-23 Mult | Independent |
| **Raised Fist** | $5 | +Mult | Adds double the rank of lowest ranked card held in hand to Mult | On Held |
| **Chaos the Clown** | $4 | Effect | 1 free Reroll per shop | Passive |
| **Scary Face** | $4 | Chips | Played face cards give +30 Chips when scored | On Scored |
| **Abstract Joker** | $4 | +Mult | +3 Mult for each Joker card | Independent |
| **Delayed Gratification** | $4 | Economy | Earn $2 per discard if no discards are used by end of the round | Passive |
| **Gros Michel** | $5 | +Mult | +15 Mult. 1 in 6 chance this card is destroyed at the end of round. | Independent |
| **Even Steven** | $4 | +Mult | Played cards with even rank give +4 Mult when scored (10, 8, 6, 4, 2) | On Scored |
| **Odd Todd** | $4 | Chips | Played cards with odd rank give +31 Chips when scored (A, 9, 7, 5, 3) | On Scored |
| **Scholar** | $4 | Chips+Mult | Played Aces give +20 Chips and +4 Mult when scored | On Scored |
| **Business Card** | $4 | Economy | Played face cards have a 1 in 2 chance to give $2 when scored | On Scored |
| **Supernova** | $5 | +Mult | Adds the number of times poker hand has been played this run to Mult | Independent |
| **Ride the Bus** | $6 | +Mult | This Joker gains +1 Mult per consecutive hand played without a scoring face card | Mixed |
| **Egg** | $4 | Economy | Gains $3 of sell value at end of round | Passive |
| **Runner** | $5 | Chips | Gains +15 Chips if played hand contains a Straight | Mixed |
| **Ice Cream** | $5 | Chips | +100 Chips. -5 Chips for every hand played | Independent |
| **Splash** | $3 | Effect | Every played card counts in scoring | Passive |
| **Blue Joker** | $5 | Chips | +2 Chips for each remaining card in deck | Independent |
| **Faceless Joker** | $4 | Economy | Earn $5 if 3 or more face cards are discarded at the same time | On Discard |
| **Green Joker** | $4 | +Mult | +1 Mult per hand played. -1 Mult per discard | Mixed |
| **Superposition** | $4 | Effect | Create a Tarot card if poker hand contains an Ace and a Straight | Independent |
| **To Do List** | $4 | Economy | Earn $4 if poker hand is a [Poker Hand], poker hand changes at end of round | On Played |
| **Cavendish** | $4 | xMult | X3 Mult. 1 in 1000 chance this card is destroyed at the end of round | Independent |
| **Red Card** | $5 | +Mult | This Joker gains +3 Mult when any Booster Pack is skipped | Independent |
| **Square Joker** | $4 | Chips | This Joker gains +4 Chips if played hand has exactly 4 cards | Mixed |
| **Riff-Raff** | $6 | Effect | When Blind is selected, create 2 Common Jokers | On Blind Select |
| **Photograph** | $5 | xMult | First played face card gives X2 Mult when scored | On Scored |
| **Reserved Parking** | $6 | Economy | Each face card held in hand has a 1 in 2 chance to give $1 | On Held |
| **Mail-In Rebate** | $4 | Economy | Earn $5 for each discarded [rank], rank changes every round | On Discard |
| **Hallucination** | $4 | Effect | 1 in 2 chance to create a Tarot card when any Booster Pack is opened | Passive |
| **Fortune Teller** | $6 | +Mult | +1 Mult per Tarot card used this run | Independent |
| **Juggler** | $4 | Effect | +1 hand size | Passive |
| **Drunkard** | $4 | Effect | +1 discard each round | Passive |
| **Golden Joker** | $6 | Economy | Earn $4 at end of round | Passive |
| **Popcorn** | $5 | +Mult | +20 Mult. -4 Mult per round played | Independent |
| **Walkie Talkie** | $4 | Chips+Mult | Each played 10 or 4 gives +10 Chips and +4 Mult when scored | On Scored |
| **Smiley Face** | $4 | +Mult | Played face cards give +5 Mult when scored | On Scored |
| **Golden Ticket** | $5 | Economy | Played Gold cards earn $4 when scored | On Scored |
| **Swashbuckler** | $4 | +Mult | Adds the sell value of all other owned Jokers to Mult | Independent |
| **Hanging Chad** | $4 | Retrigger | Retrigger first played card used in scoring 2 additional times | On Scored |
| **Shoot the Moon** | $5 | +Mult | Each Queen held in hand gives +13 Mult | On Held |

### Uncommon Jokers (64)

| Joker | Cost | Type | Effect | Timing |
|---|---|---|---|---|
| **Joker Stencil** | $8 | xMult | X1 Mult for each empty Joker slot. Joker Stencil included | Independent |
| **Four Fingers** | $7 | Effect | All Flushes and Straights can be made with 4 cards | Passive |
| **Mime** | $5 | Retrigger | Retrigger all card held in hand abilities | On Held |
| **Ceremonial Dagger** | $6 | +Mult | When Blind is selected, destroy Joker to the right and permanently add double its sell value to it's Mult | Independent |
| **Marble Joker** | $6 | Effect | Adds one Stone card to the deck when Blind is selected | On Blind Select |
| **Loyalty Card** | $5 | xMult | X4 Mult every 6 hands played | Independent |
| **Dusk** | $5 | Retrigger | Retrigger all played cards in final hand of the round | On Scored |
| **Fibonacci** | $8 | +Mult | Each played Ace, 2, 3, 5, or 8 gives +8 Mult when scored | On Scored |
| **Steel Joker** | $7 | xMult | Gives X0.2 Mult for each Steel Card in your full deck | Independent |
| **Hack** | $6 | Retrigger | Retrigger each played 2, 3, 4, or 5 | On Scored |
| **Pareidolia** | $5 | Effect | All cards are considered face cards | Passive |
| **Space Joker** | $5 | Effect | 1 in 4 chance to upgrade level of played poker hand | On Played |
| **Burglar** | $6 | Effect | When Blind is selected, gain +3 Hands and lose all discards | On Blind Select |
| **Blackboard** | $6 | xMult | X3 Mult if all cards held in hand are Spades or Clubs | Independent |
| **Sixth Sense** | $6 | Effect | If first hand of round is a single 6, destroy it and create a Spectral card | Passive |
| **Constellation** | $6 | xMult | This Joker gains X0.1 Mult every time a Planet card is used | Independent |
| **Hiker** | $5 | Chips | Every played card permanently gains +5 Chips when scored | On Scored |
| **Card Sharp** | $6 | xMult | X3 Mult if played poker hand has already been played this round | Independent |
| **Madness** | $7 | xMult | When Small Blind or Big Blind is selected, gain X0.5 Mult and destroy a random Joker | Independent |
| **Seance** | $6 | Effect | If poker hand is a Straight Flush, create a random Spectral card | Independent |
| **Vampire** | $7 | xMult | This Joker gains X0.1 Mult per scoring Enhanced card played, removes card Enhancement | Mixed |
| **Shortcut** | $7 | Effect | Allows Straights to be made with gaps of 1 rank (ex: 10 8 6 5 3) | Passive |
| **Hologram** | $7 | xMult | This Joker gains X0.25 Mult every time a playing card is added to your deck | Independent |
| **Cloud 9** | $7 | Economy | Earn $1 for each 9 in your full deck at end of round | Passive |
| **Rocket** | $6 | Economy | Earn $1 at end of round. Payout increases by $2 when Boss Blind is defeated | Passive |
| **Midas Mask** | $7 | Effect | All played face cards become Gold cards when scored | On Played |
| **Luchador** | $5 | Effect | Sell this card to disable the current Boss Blind | Passive |
| **Gift Card** | $6 | Economy | Add $1 of sell value to every Joker and Consumable card at end of round | Passive |
| **Turtle Bean** | $6 | Effect | +5 hand size, reduces by 1 each round | Passive |
| **Erosion** | $6 | +Mult | +4 Mult for each card below the deck's starting size in your full deck | Independent |
| **To the Moon** | $5 | Economy | Earn an extra $1 of interest for every $5 you have at end of round | Passive |
| **Stone Joker** | $6 | Chips | Gives +25 Chips for each Stone Card in your full deck | Independent |
| **Lucky Cat** | $6 | xMult | This Joker gains X0.25 Mult every time a Lucky card successfully triggers | Mixed |
| **Bull** | $6 | Chips | +2 Chips for each $1 you have | Independent |
| **Diet Cola** | $6 | Effect | Sell this card to create a free Double Tag | Passive |
| **Trading Card** | $6 | Economy | If first discard of round has only 1 card, destroy it and earn $3 | On Discard |
| **Flash Card** | $5 | +Mult | This Joker gains +2 Mult per reroll in the shop | Independent |
| **Spare Trousers** | $6 | +Mult | This Joker gains +2 Mult if played hand contains a Two Pair | Mixed |
| **Ramen** | $6 | xMult | X2 Mult, loses X0.01 Mult per card discarded | Mixed |
| **Seltzer** | $6 | Retrigger | Retrigger all cards played for the next 10 hands | On Scored |
| **Castle** | $6 | Chips | This Joker gains +3 Chips per discarded [suit] card, suit changes every round | Mixed |
| **Mr. Bones** | $5 | Effect | Prevents Death if chips scored are at least 25% of required chips. self destructs | Passive |
| **Acrobat** | $6 | xMult | X3 Mult on final hand of round | Independent |
| **Sock and Buskin** | $6 | Retrigger | Retrigger all played face cards | On Scored |
| **Troubadour** | $6 | Effect | +2 hand size, -1 hand per round | Passive |
| **Certificate** | $6 | Effect | When round begins, add a random playing card with a random seal to your hand | Passive |
| **Smeared Joker** | $7 | Effect | Hearts and Diamonds count as the same suit, Spades and Clubs count as the same suit | Passive |
| **Throwback** | $6 | xMult | X0.25 Mult for each Blind skipped this run | Independent |
| **Rough Gem** | $7 | Economy | Played cards with Diamond suit earn $1 when scored | On Scored |
| **Bloodstone** | $7 | xMult | 1 in 2 chance for played cards with Heart suit to give X1.5 Mult when scored | On Scored |
| **Arrowhead** | $7 | Chips | Played cards with Spade suit give +50 Chips when scored | On Scored |
| **Onyx Agate** | $7 | +Mult | Played cards with Club suit give +7 Mult when scored | On Scored |
| **Glass Joker** | $6 | xMult | This Joker gains X0.75 Mult for every Glass Card that is destroyed | Independent |
| **Showman** | $5 | Effect | Joker, Tarot, Planet, and Spectral cards may appear multiple times | Passive |
| **Flower Pot** | $6 | xMult | X3 Mult if poker hand contains a Diamond card, Club card, Heart card, and Spade card | Independent |
| **Merry Andy** | $7 | Effect | +3 discards each round, -1 hand size | Passive |
| **Oops! All 6s** | $4 | Effect | Doubles all listed probabilities (ex: 1 in 3 -> 2 in 3) | Passive |
| **The Idol** | $6 | xMult | Each played [rank] of [suit] gives X2 Mult when scored, card changes every round | On Scored |
| **Seeing Double** | $6 | xMult | X2 Mult if played hand has a scoring Club card and a scoring card of any other suit | Independent |
| **Matador** | $7 | Economy | Earn $8 if played hand triggers the Boss Blind ability | Independent |
| **Satellite** | $6 | Economy | Earn $1 at end of round per unique Planet card used this run | Passive |
| **Cartomancer** | $6 | Effect | Create a Tarot card when Blind is selected | On Blind Select |
| **Astronomer** | $8 | Effect | All Planet cards and Celestial Packs in the shop are free | Passive |
| **Bootstraps** | $7 | +Mult | +2 Mult for every $5 you have | Independent |

### Rare Jokers (20)

| Joker | Cost | Type | Effect | Timing |
|---|---|---|---|---|
| **DNA** | $8 | Effect | If first hand of round has only 1 card, add a permanent copy to deck and draw it to hand | On Played |
| **Vagabond** | $8 | Effect | Create a Tarot card if hand is played with $4 or less | Independent |
| **Baron** | $8 | xMult | Each King held in hand gives X1.5 Mult | On Held |
| **Obelisk** | $8 | xMult | This Joker gains X0.2 Mult per consecutive hand played without playing your most played poker hand | Mixed |
| **Baseball Card** | $8 | xMult | Uncommon Jokers each give X1.5 Mult | On Other Jokers |
| **Ancient Joker** | $8 | xMult | Each played card with [suit] gives X1.5 Mult when scored, suit changes at end of round | On Scored |
| **Campfire** | $9 | xMult | This Joker gains X0.25 Mult for each card sold, resets when Boss Blind is defeated | Independent |
| **Blueprint** | $10 | Effect | Copies ability of Joker to the right | On Other Jokers* |
| **Wee Joker** | $8 | Chips | This Joker gains +8 Chips when each played 2 is scored | Mixed |
| **Hit the Road** | $8 | xMult | This Joker gains X0.5 Mult for every Jack discarded this round | Mixed |
| **The Duo** | $8 | xMult | X2 Mult if played hand contains a Pair | Independent |
| **The Trio** | $8 | xMult | X3 Mult if played hand contains a Three of a Kind | Independent |
| **The Family** | $8 | xMult | X4 Mult if played hand contains a Four of a Kind | Independent |
| **The Order** | $8 | xMult | X3 Mult if played hand contains a Straight | Independent |
| **The Tribe** | $8 | xMult | X2 Mult if played hand contains a Flush | Independent |
| **Stuntman** | $7 | Chips | +250 Chips, -2 hand size | Independent |
| **Invisible Joker** | $8 | Effect | After 2 rounds, sell this card to Duplicate a random Joker (Removes Negative from copy) | Passive |
| **Brainstorm** | $10 | Effect | Copies the ability of leftmost Joker | On Other Jokers* |
| **Driver's License** | $7 | xMult | X3 Mult if you have at least 16 Enhanced cards in your full deck | Independent |
| **Burnt Joker** | $8 | Effect | Upgrade the level of the first discarded poker hand each round | On Discard |

\* Blueprint/Brainstorm copy another Joker's ability and fire at that Joker's own timing — see the activation-timing blurb above.

### Legendary Jokers (5)

| Joker | Cost | Type | Effect | Timing |
|---|---|---|---|---|
| **Canio** | $20 | xMult | This Joker gains X1 Mult when a face card is destroyed | Mixed |
| **Triboulet** | $20 | xMult | Played Kings and Queens each give X2 Mult when scored | On Scored |
| **Yorick** | $20 | xMult | This Joker gains X1 Mult every 23 cards discarded | Mixed |
| **Chicot** | $20 | Effect | Disables effect of every Boss Blind | On Blind Select |
| **Perkeo** | $20 | Effect | Creates a Negative copy of 1 random consumable card in your possession at the end of the shop | Passive |
---

## 3. Tarot Cards (22 total)

Cost $3, sell $1. Applied immediately on use (not held like Jokers). "Targets" = cards you select from your hand before applying.

| Tarot | Effect | Targets |
|---|---|---|
| **The Fool** | Creates a copy of the last Tarot or Planet card used this run (The Fool itself excluded) | 0 |
| **The Magician** | Enhances up to 2 selected cards into Lucky Cards | 1–2 |
| **The High Priestess** | Creates up to 2 random Planet cards (must have room) | 0 |
| **The Empress** | Enhances up to 2 selected cards into Mult Cards | 1–2 |
| **The Emperor** | Creates up to 2 random Tarot cards (must have room) | 0 |
| **The Hierophant** | Enhances up to 2 selected cards into Bonus Cards | 1–2 |
| **The Lovers** | Enhances 1 selected card into a Wild Card | 1 |
| **The Chariot** | Enhances 1 selected card into a Steel Card | 1 |
| **Justice** | Enhances 1 selected card into a Glass Card | 1 |
| **The Hermit** | Doubles money in hand, up to a gain of $20 | 0 |
| **The Wheel of Fortune** | 1 in 4 chance to add Foil, Holographic, or Polychrome to a random Joker | 0 |
| **Strength** | Increases the rank of up to 2 selected cards by 1 | 1–2 |
| **The Hanged Man** | Destroys up to 2 selected cards | 1–2 |
| **Death** | Select 2 cards: converts the left card into a copy of the right card (rank, suit, enhancement, edition, seal) | 2 |
| **Temperance** | Gives total sell value of all owned Jokers as money, capped at $50 | 0 |
| **The Devil** | Enhances 1 selected card into a Gold Card | 1 |
| **The Tower** | Enhances 1 selected card into a Stone Card | 1 |
| **The Star** | Converts up to 3 selected cards to Diamonds | 1–3 |
| **The Moon** | Converts up to 3 selected cards to Clubs | 1–3 |
| **The Sun** | Converts up to 3 selected cards to Hearts | 1–3 |
| **Judgement** | Creates a random Joker card (must have room) | 0 |
| **The World** | Converts up to 3 selected cards to Spades | 1–3 |

## 4. Planet Cards (12 total)

Cost $3, sell $1. Each levels up one poker hand type (see table in Section 1). Pluto/Mercury/Uranus/Venus/Saturn/Jupiter/Earth/Mars/Neptune appear normally in the shop and Celestial Packs; **Planet X, Ceres, and Eris are secret** — obtained only via the hand types they upgrade (Five of a Kind, Flush House, Flush Five) being played, or via Black Hole / specific card generation.

| Planet | Levels Up |
|---|---|
| Pluto | High Card |
| Mercury | Pair |
| Uranus | Two Pair |
| Venus | Three of a Kind |
| Saturn | Straight |
| Jupiter | Flush |
| Earth | Full House |
| Mars | Four of a Kind |
| Neptune | Straight Flush |
| Planet X | Five of a Kind |
| Ceres | Flush House |
| Eris | Flush Five |

## 5. Spectral Cards (18 total)

Cost $4, sell $2. Applied immediately. Rarer and more run-altering than Tarots — several destroy cards or Jokers as a tradeoff. **The Soul** and **Black Hole** are excluded from normal Spectral pack odds (each has an independent ~0.3%-per-card chance to appear in eligible packs instead) and cannot be created by Sixth Sense/Séance.

| Spectral | Effect | Targets |
|---|---|---|
| **Familiar** | Destroys 1 random card in hand, adds 3 random Enhanced face cards to hand | 0 |
| **Grim** | Destroys 1 random card in hand, adds 2 random Enhanced Aces to hand | 0 |
| **Incantation** | Destroys 1 random card in hand, adds 4 random Enhanced numbered cards to hand | 0 |
| **Talisman** | Adds a Gold Seal to 1 selected card | 1 |
| **Aura** | Adds Foil, Holographic, or Polychrome to 1 selected card | 1 |
| **Wraith** | Creates a random Rare Joker (must have room), sets money to $0 | 0 |
| **Sigil** | Converts all cards in hand to a single random suit | 0 |
| **Ouija** | Converts all cards in hand to a single random rank, -1 hand size (permanent) | 0 |
| **Ectoplasm** | Adds Negative edition to a random Joker, -1 hand size (permanent) | 0 |
| **Immolate** | Destroys 5 random cards in hand, gain $20 | 0 |
| **Ankh** | Creates a copy of a random Joker, destroys all other Jokers | 0 |
| **Deja Vu** | Adds a Red Seal to 1 selected card | 1 |
| **Hex** | Adds Polychrome to a random Joker, destroys all other Jokers | 0 |
| **Trance** | Adds a Blue Seal to 1 selected card | 1 |
| **Medium** | Adds a Purple Seal to 1 selected card | 1 |
| **Cryptid** | Creates 2 copies of 1 selected card | 1 |
| **The Soul** | Creates a Legendary Joker (must have room) | 0 |
| **Black Hole** | Upgrades every poker hand type by 1 level | 0 |

## 6. Card Enhancements (8 total)

Applied to individual playing cards (not Jokers). A card can have at most one Enhancement, plus independently one Edition and one Seal.

| Enhancement | Effect |
|---|---|
| **Bonus Card** | +30 Chips when scored |
| **Mult Card** | +4 Mult when scored |
| **Wild Card** | Counts as every suit simultaneously for scoring purposes |
| **Glass Card** | X2 Mult when scored; 1 in 4 chance to be destroyed after being played |
| **Steel Card** | X1.5 Mult while this card is held in hand (not played) |
| **Stone Card** | Always scores; +50 Chips; has no rank or suit (can't satisfy rank/suit-based hand or Joker requirements) |
| **Gold Card** | $3 if this card is held in hand at end of round |
| **Lucky Card** | When scored: 1 in 5 chance for +20 Mult; independently, 1 in 15 chance for +$20 |

## 7. Editions (5 total)

Editions apply to Jokers, playing cards, or consumables (rules differ per type).

| Edition | Effect | Valid on |
|---|---|---|
| **Base** | No extra effect | Everything |
| **Foil** | +50 Chips | Jokers, playing cards |
| **Holographic** | +10 Mult | Jokers, playing cards |
| **Polychrome** | X1.5 Mult | Jokers, playing cards |
| **Negative** | +1 Joker slot (on a Joker) / +1 consumable slot (on a Tarot/Planet/Spectral) | Jokers, consumables (never playing cards) |

## 8. Seals (4 total)

Seals apply only to playing cards, independent of Enhancement/Edition.

| Seal | Effect |
|---|---|
| **Red Seal** | Retriggers this card's scoring AND held-in-hand effects 1 extra time |
| **Gold Seal** | Earns $3 when this card is scored |
| **Blue Seal** | If held in hand at end of round, creates the Planet card matching the *final poker hand played that round* (not random; must have room) |
| **Purple Seal** | Creates a Tarot card when this card is discarded (must have room) |

---
## 9. Vouchers (32 total — 16 base/upgrade pairs)

Cost $10 each. Vouchers are permanent for the run. Each pair's upgrade only enters the shop's voucher pool after its base voucher has been purchased in that run.

| Base Voucher | Effect | Upgrade | Effect |
|---|---|---|---|
| **Overstock** | +1 card slot in shop | **Overstock Plus** | +1 additional card slot in shop |
| **Clearance Sale** | All cards & packs in shop are 25% off | **Liquidation** | All cards & packs in shop are 50% off |
| **Hone** | Foil/Holo/Polychrome cards appear 2x more often | **Glow Up** | ...4x more often |
| **Reroll Surplus** | Rerolls cost $2 less | **Reroll Glut** | Rerolls cost $2 less again |
| **Crystal Ball** | +1 consumable slot | **Omen Globe** | Spectral cards may appear in Arcana Packs |
| **Telescope** | Celestial Packs always contain the Planet card for your most-played hand | **Observatory** | Planet cards in your consumables give X1.5 Mult for their hand |
| **Grabber** | +1 hand per round | **Nacho Tong** | +1 additional hand per round |
| **Wasteful** | +1 discard per round | **Recyclomancy** | +1 additional discard per round |
| **Tarot Merchant** | Tarot cards appear 2x more often in shop | **Tarot Tycoon** | ...4x more often |
| **Planet Merchant** | Planet cards appear 2x more often in shop | **Planet Tycoon** | ...4x more often |
| **Seed Money** | Raises interest cap by $5 | **Money Tree** | Raises interest cap by $10 more |
| **Blank** | Does nothing | **Antimatter** | +1 Joker slot |
| **Magic Trick** | Playing cards can be purchased from the shop | **Illusion** | Shop playing cards may have an Enhancement, Edition, and/or Seal |
| **Hieroglyph** | -1 Ante, -1 hand per round | **Petroglyph** | -1 Ante, -1 discard per round |
| **Director's Cut** | Reroll the Boss Blind once per Ante, $10 per reroll | **Retcon** | Reroll the Boss Blind unlimited times per Ante, $10 per reroll |
| **Paint Brush** | +1 hand size | **Palette** | +1 additional hand size |

## 10. Boss Blinds (28 total — 23 regular + 5 Ante-8 Finishers)

Boss Blinds must be played (can't be skipped). Each regular Boss Blind has a **minimum Ante** (column below; "1" = any Ante — Ante 1 has only these 8 bosses). The 5 Showdown blinds ("Finishers") are exclusive to Ante 8 and recur at Antes 16/24/32 in Endless mode.

| Boss Blind | Min. Ante | Effect |
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

**Matador-compatible Bosses** (a played hand can trigger the Boss ability for Matador's $8): The Ox, The Arm, The Club, The Psychic, The Goad, The Window, The Eye, The Mouth, The Plant, The Pillar, The Head, The Flint, and Verdant Leaf.

## 11. Starting Decks (15 total)

Each run picks one starting deck; its modifier applies for the whole run.

| Deck | Effect |
|---|---|
| Red Deck | +1 discard every round |
| Blue Deck | +1 hand every round |
| Yellow Deck | Start with an extra $10 |
| Green Deck | At end of round: gain $2 per remaining hand and $1 per remaining discard; earn no interest |
| Black Deck | +1 Joker slot, -1 hand every round |
| Magic Deck | Start with the Crystal Ball voucher and 2 copies of The Fool |
| Nebula Deck | Start with the Telescope voucher, -1 consumable slot |
| Ghost Deck | Start with a Hex card; Spectral cards may appear in the shop |
| Abandoned Deck | Start with no face cards in the deck |
| Checkered Deck | Start with only Spades and Hearts in the deck |
| Zodiac Deck | Start with the Tarot Merchant, Planet Merchant, and Overstock vouchers |
| Painted Deck | +2 hand size, -1 Joker slot |
| Anaglyph Deck | Gain a Double Tag after defeating each Boss Blind |
| Plasma Deck | Balances Chips and Mult when scoring (averages them); Blind score requirements are doubled |
| Erratic Deck | Every card in the deck has a random rank and suit |

## 12. Stakes (8 total, ascending difficulty)

Each stake stacks its modifier on top of every stake before it.

| Stake | Added Modifier |
|---|---|
| White | Base difficulty |
| Red | Small Blind no longer gives a cash reward on win |
| Green | Score requirements scale up faster each Ante |
| Black | Shop Jokers may spawn with the Eternal sticker (can't be sold/destroyed) |
| Blue | -1 discard every round |
| Purple | Score requirements scale up faster again |
| Orange | Shop Jokers may spawn with the Perishable sticker (debuffed after 5 rounds unless a blind is beaten) |
| Gold | Shop/pack Jokers may spawn with the Rental sticker (costs $1 to buy, charges $3 at end of each round — see Section 13) |

## 13. Sticker Mechanics

Stickers are modifiers on Jokers. Three **in-run** stickers affect gameplay; eight **stake** stickers are purely cosmetic (they mark that a Joker or Deck has won a run at a given Stake) and are not covered here. Vouchers, Booster Packs, and Consumables can never have stickers. Stickers are permanent for the run and can be applied to an existing Joker only when it is generated.

**Spawn chances.** Each in-run sticker has a flat **30%** chance to appear on an eligible Joker generated by the Shop or a Booster Pack (no Ante scaling — as documented by the wiki; verify against the game's `shop.lua` before building seed-accurate sticker simulation). Eternal and Perishable are rolled together and are **mutually exclusive** (60% combined, so a Joker is clean of both 40% of the time); Rental is rolled independently (30%). On Gold Stake this gives a Joker a 28% (40% × 70%) chance of having no in-run stickers. Jokers created mid-run (Riff-Raff, The Soul, Invisible Joker copies, etc.) do not get sticker rolls — Legendary Jokers are sticker-compatible in principle but have no way to receive one.

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

## 14. Tags (24 total)

Skipping a Small or Big Blind grants a random Tag instead of playing it; its effect applies in the next shop (or immediately, for some).

| Tag | Effect |
|---|---|
| Uncommon Tag | Next shop guarantees an Uncommon Joker |
| Rare Tag | Next shop guarantees a Rare Joker |
| Negative Tag | Next base-edition Joker in shop is free and becomes Negative |
| Foil Tag | Next base-edition Joker in shop is free and becomes Foil |
| Holographic Tag | Next base-edition Joker in shop is free and becomes Holographic |
| Polychrome Tag | Next base-edition Joker in shop is free and becomes Polychrome |
| Investment Tag | Gain $25 after defeating the next Boss Blind |
| Voucher Tag | Next shop has an additional Voucher available |
| Boss Tag | Rerolls the upcoming Boss Blind |
| Standard Tag | Gives a free Mega Standard Pack |
| Charm Tag | Gives a free Mega Arcana Pack |
| Meteor Tag | Gives a free Mega Celestial Pack |
| Buffoon Tag | Gives a free Mega Buffoon Pack |
| Handy Tag | Gives $1 for each hand played so far this run |
| Garbage Tag | Gives $1 for each unused discard so far this run |
| Ethereal Tag | Gives a free Spectral Pack |
| Coupon Tag | Jokers, Consumables, and Booster Packs in the next shop's initial stock are free (Vouchers excluded) |
| Double Tag | Doubles the next Tag applied (after skipping another Blind) |
| Juggle Tag | +3 hand size for the next round only |
| D6 Tag | Next shop's rerolls start at $0 |
| Top-up Tag | Spawns up to 2 Common Jokers with no stickers, filling available slots |
| Speed Tag | Gives $5 for each Blind skipped so far this run, including this one |
| Orbital Tag | Upgrades the poker hand type shown on the tag by 3 levels |
| Economy Tag | Doubles your money, capped at +$40 |

## 15. Booster Packs

| Pack | Contents | Choose |
|---|---|---|
| Standard Pack (Normal/Jumbo/Mega) | 3 / 5 / 5 Playing Cards to add to your deck | 1 / 1 / 2 |
| Arcana Pack (Normal/Jumbo/Mega) | 3 / 5 / 5 Tarot cards to use immediately | 1 / 1 / 2 |
| Celestial Pack (Normal/Jumbo/Mega) | 3 / 5 / 5 Planet cards to use immediately | 1 / 1 / 2 |
| Buffoon Pack (Normal/Jumbo/Mega) | 2 / 4 / 4 Jokers | 1 / 1 / 2 |
| Spectral Pack (Normal/Jumbo/Mega) | 2 / 4 / 4 Spectral cards to use immediately | 1 / 1 / 2 |

Pack cost: Normal $4, Jumbo $6, Mega $8.

## 16. Ante, Blind Score Requirements & Reward Money

Blind score required = Ante's **base chip target** × a per-blind multiplier: Small Blind 1x, Big Blind 1.5x, Boss Blind 2x. Exceptions: The Wall 4x, Violet Vessel 6x, **The Needle 1x**; The Flint halves the hand's own scoring instead of raising the target. Disabling a Boss (Luchador / Chicot) restores The Wall / Violet Vessel to 2x base (The Needle stays at 1x).

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

Skipping a Small or Big Blind pays nothing — you receive a Tag instead (Section 14). Reward money is paid on top of hand-payouts and interest (Section 0).

---

## 17. Shop Pricing, Sell Value & Generation Weights

Every shop item recalculates its buy cost and sell value on the fly from the same base formula (sourced from the game's own `Card:set_cost()` logic):

```
buy_cost   = round_half_down( (base_cost + edition_cost + inflation_cost) × discount_percent )
sell_value = floor( buy_cost / 2 )
```

- **Rounding:** buy cost rounds *half down* (8.5 → 8); sell value always rounds *down* (3.75 → 3).
- **Floor of $1:** both buy cost and sell value are clamped to a minimum of $1 if the formula would put them at $0 or below.
- `discount_percent` is 1.0 normally, 0.75 with the Clearance Sale voucher, or 0.5 with Liquidation (its upgrade) — these stack as a single multiplier, not compounded.
- `inflation_cost` only applies in the Inflation Challenge Deck, where every item's price permanently increases by $1 on every purchase made in the run.

### Base cost by item type

| Item | Base Cost |
|---|---|
| Joker — Common | $1–6 (varies per Joker) |
| Joker — Uncommon | $4–8 (varies per Joker) |
| Joker — Rare | $7–10 (varies per Joker) |
| Joker — Legendary | $20 |
| Playing card | $1 |
| Tarot card | $3 |
| Planet card | $3 |
| Spectral card | $4 |
| Booster Pack — Normal / Jumbo / Mega | $4 / $6 / $8 |
| Voucher | $10 |

### Edition cost (added to base cost before the discount multiplier)

| Edition | Jokers | Consumables | Playing cards |
|---|---|---|---|
| Foil | +$2 | N/A | +$2 |
| Holographic | +$3 | N/A | +$3 |
| Polychrome | +$5 | N/A | +$5 |
| Negative | +$5 | +$5 | N/A (can't appear on playing cards) |

So, e.g., a Polychrome Common Joker with a $4 base cost has a buy cost of $9 and a sell value of $4 (floor(9/2)). Consumables can only carry a Negative edition (from Perkeo), and it's never found on shop-offered consumables — only generated mid-run.

### Sell value: worked examples

- **Joker, $4 base, no edition:** sell = floor(4/2) = **$2**
- **Tarot/Planet, $3 base:** sell = floor(3/2) = **$1**
- **Spectral, $4 base:** sell = floor(4/2) = **$2**
- **Legendary Joker, $20 base:** sell = floor(20/2) = **$10**
- **Foil Uncommon Joker, $6 base + $2 Foil = $8 buy cost:** sell = floor(8/2) = **$4**

### Special cases that override the formula

- **Egg** (+$3 sell value at end of round) and **Gift Card** (+$1 sell value to every Joker/Consumable at end of round) add flat bonus sell value *after* the formula above, unaffected by discount vouchers.
- **Astronomer** sets Planet cards' and Celestial Packs' buy cost to $0.
- **Coupon Tag** sets the buy cost of everything in the next shop to $0 except Vouchers (which keep normal pricing).
- **Rental sticker** on a Joker fixes its buy cost at $1 regardless of the formula (it costs $1/round to keep instead).
- Rerolling the shop is priced separately: starts at $5, +$1 per reroll that shop visit, resets to $5 on entering a new shop (Reroll Surplus/Reroll Glut lower the starting price to $3/$1; the D6 Tag zeroes it for the next shop only).

### Shop card-type & modifier generation weights

**Card-type odds** (per random card slot; weight → probability): Joker 20 (**71.4%**), Tarot 4 (**14.3%**), Planet 4 (**14.3%**). Tarot Merchant raises Tarot's weight to 9.6 (**≈28.6%**); Tarot Tycoon to 32 (**≈57.1%**). Planet Merchant/Tycoon do the same for Planets. Magic Trick adds Playing Cards at weight 4; the Ghost Deck adds Spectral cards at weight 2.

**Joker rarity odds** (once a Joker is rolled): Common 70%, Uncommon 25%, Rare 5% — unchanged by Ante. Legendary Jokers never roll in the shop (The Soul only).

**Duplicate suppression (Showman rule):** without Showman, any Joker/Tarot/Planet/Spectral already in the player's possession is excluded from the pool for the rest of the run, in the Shop and Booster Packs alike. Merely *seeing* a card does not exclude it (it can reappear on a reroll). Showman lifts the restriction for all four types — even The Soul and Black Hole can then duplicate, at very low odds.

**Edition odds (Jokers):** Negative 0.3%, Polychrome 0.3%, Holographic 1.4%, Foil 2%. Hone raises Foil/Holo/Poly to 4% / 2.8% / 0.9% and Glow Up to 8% / 5.6% / 2.1% (per the wiki's poll structure, Polychrome lands at ~3× / ~7× its base rather than exactly 2× / 4×). Negative stays 0.3% regardless.

**Illusion (shop Playing Cards):** Enhancement 40%, Edition 20%, and Seals **never** (bugged in v1.0.1o — the described Seal effect never rolls); Illusion cards are unaffected by Hone/Glow Up. Booster-Pack Playing Cards (Standard Packs) use different odds: Foil 4% / Holographic 2.8% / Polychrome 1.2%, Enhancement 40%, Seal 20% (evenly split across variants).

**Booster Pack & Voucher slots:** the Shop always offers 2 Booster Packs (the first pack of a run is always a normal Buffoon Pack). Pack type/size is drawn by weight (wiki Booster Packs page): Standard / Arcana / Celestial 4 / 2 / 0.5; Buffoon 1.2 / 0.6 / 0.15; Spectral 0.6 / 0.3 / 0.07 (Normal / Jumbo / Mega). Rerolling does not restock Packs or the Voucher — Packs restock on entering a new Shop; the Voucher restocks only after beating the Boss Blind.

---

## 18. Known Gaps (Not Covered by This Sheet)

This sheet is not yet comprehensive enough for a full engine implementation in the following areas:

- **Challenge Decks (20 total).** Only the 15 standard/Stake-linked Decks (Section 11) are covered. Balatro also has 20 separate Challenge Decks (White Stake only), each with its own custom rule set and banned-item list — entirely absent here.
- **Joker unlock requirements.** None of the 150 Jokers' unlock conditions are listed (105 are available from the start; 45 require specific achievements).

## 19. Audit Log

This sheet was reviewed against the Balatro Wiki (balatrowiki.org) and Balatro Fandom Wiki in August 2026. Confirmed corrections made in this pass:

| Section | Item | Was | Corrected To |
|---|---|---|---|
| 8. Seals | Blue Seal | "Creates a Planet card if held in hand at end of round" | Creates *the specific* Planet card matching the final poker hand played that round, if held in hand at end of round |
| 10. Boss Blinds | The Wheel | "1 in 4 chance for each played card to add a random Edition to a random Joker" (this is actually the *Wheel of Fortune Tarot's* effect) | 1 in 7 chance for each card drawn (not played) to be dealt face down |
| 10. Boss Blinds | The Arm | "Delevels the poker hand played down to level 1" | Decreases the played poker hand's level by 1 (floor of level 1) |
| 14. Tags | Investment Tag | "Jokers, Consumables, and Booster Packs in the next shop's initial stock are free" (this is actually the *Coupon Tag's* effect) | Gain $25 after defeating the next Boss Blind |
| 14. Tags | Coupon Tag | "Jokers and Consumables in the next shop's initial stock are free" (missing Booster Packs; was also inconsistent with Section 17's own description of Coupon Tag) | Jokers, Consumables, and Booster Packs are free (Vouchers excluded) |

| Section | Item | Was | Corrected To |
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
| 15. Booster Packs | Spectral Pack contents | "3 / 5 / 5" | Normal 2 / Jumbo 4 / Mega 4 (wiki Booster Packs page — the sim was correct) |
| 17. Shop | Booster Pack rates | Not documented | Type/size weights added (Standard/Arcana/Celestial 4/2/0.5, Buffoon 1.2/0.6/0.15, Spectral 0.6/0.3/0.07) |
Also added: Section 0 (starting run parameters) and a "debuffed" definition, both referenced implicitly elsewhere in the sheet but never defined. Everything else — hand-type base values, the full 150-Joker table, Tarot/Planet/Spectral effects, Enhancements/Editions, the other 30 Vouchers, the other 26 Boss Blinds, Decks, Stakes, and the shop pricing formulas — was spot-checked against the sources below and no further discrepancies were found, though a table of this size (400+ discrete facts) was not verified line-by-line against source, so treat it as high-confidence rather than exhaustively confirmed.

---

*Sources: [balatro-rs](https://github.com/evanofslack/balatro-rs) `balatro-types`/`core` crates (exact game data/formulas), the [Balatro Wiki](https://balatrowiki.org), and the [Balatro Fandom Wiki](https://balatrogame.fandom.com) (cross-checked terminology, boss-blind, seal, and tag descriptions). Game version referenced: 1.0.1o-FULL. Audited against sources current as of August 2026; no public 1.1 gameplay patch had shipped as of that date, so 1.0.1-line mechanics remain current.*
