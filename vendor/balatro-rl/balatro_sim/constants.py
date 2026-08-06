"""
constants.py — Static game tables ported from Balatro source.
All values verified against game source (game.lua, back.lua).
"""

# Hand base chips and mult (level 1)
# Source: G.GAME.hands in game.lua
HAND_BASE = {
    "High Card":       (5,  1),
    "Pair":            (10, 2),
    "Two Pair":        (20, 2),
    "Three of a Kind": (30, 3),
    "Straight":        (30, 4),
    "Flush":           (35, 4),
    "Full House":      (40, 4),
    "Four of a Kind":  (60, 7),
    "Straight Flush":  (100, 8),
    "Five of a Kind":  (120, 12),
    "Flush House":     (140, 14),
    "Flush Five":      (160, 16),
}

# Chips added per hand level (additive)
HAND_LEVEL_CHIPS = {
    "High Card":       10,
    "Pair":            15,
    "Two Pair":        20,
    "Three of a Kind": 20,
    "Straight":        30,
    "Flush":           15,
    "Full House":      25,
    "Four of a Kind":  30,
    "Straight Flush":  40,
    "Five of a Kind":  35,
    "Flush House":     40,
    "Flush Five":      50,
}

# Mult added per hand level (additive)
HAND_LEVEL_MULT = {
    "High Card":       1,
    "Pair":            1,
    "Two Pair":        1,
    "Three of a Kind": 2,
    "Straight":        3,
    "Flush":           2,
    "Full House":      2,
    "Four of a Kind":  3,
    "Straight Flush":  4,
    "Five of a Kind":  3,
    "Flush House":     4,
    "Flush Five":      6,
}

# Blind chip targets by ante (ante 1-8, small/big/boss)
# Source: G.GAME.blind_on_deck chip scaling in game.lua
# Format: {ante: (small, big, boss)} — boss same as big (varies by boss type)
BLIND_CHIPS = {
    1: (300,   450,   600),
    2: (800,   1200,  1600),
    3: (2000,  3000,  4000),
    4: (5000,  7500,  10000),
    5: (11000, 16500, 22000),
    6: (20000, 30000, 40000),
    7: (35000, 52500, 70000),
    8: (50000, 75000, 100000),
}

# Interest: $1 per $5 held, capped at $5/round (i.e., max $25 in bank earns interest)
INTEREST_RATE   = 5    # $1 per $5 held
INTEREST_CAP    = 5    # max $5 interest per round

# Starting hand/discard counts
STARTING_HANDS    = 4
STARTING_DISCARDS = 3
HAND_SIZE         = 8

# Card rank chip values (for scoring)
RANK_CHIPS = {
    2: 2, 3: 3, 4: 4, 5: 5, 6: 6, 7: 7, 8: 8,
    9: 9, 10: 10, 11: 10, 12: 10, 13: 10, 14: 11,  # J=11, Q=12, K=13, A=14
}

# Suits
SUITS = ["Spades", "Hearts", "Clubs", "Diamonds"]
SUIT_ID = {s: i for i, s in enumerate(SUITS)}

# Ranks (2-14, where 11=J, 12=Q, 13=K, 14=A)
RANKS = list(range(2, 15))
RANK_NAMES = {2:'2',3:'3',4:'4',5:'5',6:'6',7:'7',8:'8',
              9:'9',10:'10',11:'J',12:'Q',13:'K',14:'A'}

# Enhancements
ENHANCEMENTS = ["None", "Bonus", "Mult", "Wild", "Glass", "Steel", "Stone", "Gold", "Lucky"]

# Editions
EDITIONS = ["None", "Foil", "Holographic", "Polychrome", "Negative"]

# Seals
SEALS = ["None", "Gold", "Red", "Blue", "Purple"]

# Shop reroll cost (increases by $1 each reroll, resets each round)
REROLL_BASE_COST = 5

# Starting money
STARTING_MONEY = 4

# Round end payout: $1 per hand remaining + interest
HAND_PAYOUT = 1
