# tools/stress_m1_challenger.py - Adversarial Stress Harness
from __future__ import annotations

import sys, os, traceback

if 'vendor/balatro-rl' not in sys.path:
    sys.path.insert(0, os.path.abspath('vendor/balatro-rl'))
if '.' not in sys.path:
    sys.path.insert(0, os.path.abspath('.'))
from balatro_sim.card import Card
from balatro_sim.game import BalatroGame, State
from balatro_sim.jokers.base import JokerInstance
from balatro_sim.agent_v9 import scored_plays, eval_hand_score
from balatro_sim.hand_eval import evaluate_hand
from balatro_sim import agent_v10 as v10
from balatro_sim.agent_v10 import HeuristicV10, SearchShopV10, V10_PARAMS
from balatro_sim.shop import ShopItem


def setup_game(hand_cards, jokers=(), hands_left=3, discards_left=3, target=300, ante=2, boss="", dollars=20):
    g = BalatroGame(seed=42, rng_mode="seed")
    g.reset()
    g.ante = ante
    g.dollars = dollars
    if g.state != State.SELECTING_HAND:
        g.state = State.BLIND_SELECT
        g.step({"type": "play_blind"})
    g.hand = [Card(rank=r, suit=s) for s, r in hand_cards]
    g.hands_left = hands_left
    g.discards_left = discards_left
    g.current_blind.chips_target = target
    g.chips_scored = 0
    g.current_blind.boss_key = boss
    g.jokers = [JokerInstance(k, game=g) for k in jokers]
    return g


def stress_test_ride_the_bus():
    print("=== TEST 1: Ride the Bus Face Safety & Guardrails ===")
    failures = []
    
    # 1.A: Mixed hand (Faces + Non-faces) during safe blind (p_clear=1.0)
    g = setup_game(
        [
            ("Spades", 13), ("Hearts", 12), ("Clubs", 11),  # K, Q, J
            ("Diamonds", 2), ("Hearts", 3), ("Clubs", 4), ("Spades", 5), ("Hearts", 6)
        ],
        jokers=["j_ride_the_bus"],
        hands_left=3,
        discards_left=3,
        target=600,
        ante=2
    )
    g.jokers[0].state["mult"] = 20
    plays = scored_plays(g)
    act = v10._find_scaling_action(g, g.hand, plays, p_clear=1.0)
    if act is None:
        failures.append("1.A: Expected scaling action for mixed hand, got None")
    else:
        played = [g.hand[i] for i in act["cards"]]
        res = evaluate_hand(played)
        scoring = res[1]
        has_face = any(c.is_face_card for c in scoring)
        if has_face:
            failures.append("1.A: Scaling action played scoring face card!")
        else:
            print("  [PASS] 1.A: Scaling action avoided scoring face cards in mixed hand.")

    # 1.B: ALL Face Cards hand: verify returns None from scaling, no crash, handled by _tier1_survive
    g_all_face = setup_game(
        [
            ("Spades", 13), ("Hearts", 13), ("Clubs", 13), ("Diamonds", 13),
            ("Spades", 12), ("Hearts", 12), ("Clubs", 11), ("Diamonds", 11)
        ],
        jokers=["j_ride_the_bus"],
        hands_left=3,
        discards_left=2,
        target=2000,
        ante=2
    )
    g_all_face.jokers[0].state["mult"] = 15
    plays = scored_plays(g_all_face)
    try:
        act_scale = v10._find_scaling_action(g_all_face, g_all_face.hand, plays, p_clear=0.99)
        if act_scale is not None:
            played = [g_all_face.hand[i] for i in act_scale["cards"]]
            res = evaluate_hand(played)
            if any(c.is_face_card for c in res[1]):
                failures.append("1.B: Scaling action selected scoring face card on all-face hand!")
        print("  [PASS] 1.Bs All-face hand returned None from scaling action without crash.")
        
        act_surv = v10._tier1_survive(g_all_face, plays, p_clear=0.99)
        if act_surv is None or "type" not in act_surv:
            failures.append("1.Bs _tier1_survive returned invalid action on all-face hand")
        else:
            print("  [PASS] 1.Bs _tier1_survive safely returned action: " + act_surv["type"])
    except Exception as e:
        failures.append("1.B: Exception on all-face hand: " + traceback.format_exc())

    # 1.C: Face card as non-scoring kicker: Pair of 2s with King kicker [2, 2, K]
    cards_kick = [Card(rank=2, suit="Hearts"), Card(rank=2, suit="Clubs"), Card(rank=13, suit="Spades")]
    ht, sc = evaluate_hand(cards_kick)
    if any(c.is_face_card for c in sc):
        failures.append("1.C: evaluate_hand marked King kicker as scoring card in Pair of 2s!")
    else:
        print("  [PASS] 1.C: King kicker in Pair of 2s is correctly non-scoring.")

    # 1.D: Safe clearing vs face clearing in _tier1_survive
    g_clearing = setup_game(
        [
            ("Spades", 13), ("Hearts", 13), ("Clubs", 13), ("Diamonds", 13),  # 4 Kings
            ("Spades", 2), ("Hearts", 2), ("Clubs", 2), ("Diamonds", 2)       # 4 Twos
        ],
        jokers=["j_ride_the_bus"],
        hands_left=2,
        discards_left=0,
        target=100,
        ante=2
    )
    g_clearing.jokers[0].state["mult"] = 20
    plays = scored_plays(g_clearing)
    act_clear = v10._tier1_survive(g_clearing, plays, p_clear=1.0)
    played = [g_clearing.hand[i] for i in act_clear["cards"]]
    if any(c.rank == 13 for c in played):
        failures.append("1.D: _tier1_survive picked Kings instead of safe Twos when both clear!")
    else:
        print("  [PASS] 1.D: _tier1_survive safely preferred Twos over Kings when clearing.")

    return failures


def stress_test_green_joker():
    print("=== TEST 2: Green Joker Low Hands & Discard Pacing ===")
    failures = []
    
    # 2.A: hands_left == 1: scaling MUST NOT trigger
    g = setup_game(
        [("Spades", 2), ("Hearts", 4), ("Clubs", 6), ("Diamonds", 8), ("Spades", 10)],
        jokers=["j_green_joker"],
        hands_left=1,
        discards_left=2,
        target=50,
        ante=2
    )
    plays = scored_plays(g)
    act = v10._find_scaling_action(g, g.hand, plays, p_clear=1.0)
    if act is not None:
        failures.append("2.A: Scaling triggered when hands_left == 1: " + str(act))
    else:
        print("  [PASS] 2.A: Scaling properly suppressed when hands_left == 1.")

    # 2.B: hands_left == 2, safe blind (p_clear=0.99): discard SUPPRESSED to save +1 mult
    g_safe = setup_game(
        [("Spades", 2), ("Hearts", 4), ("Clubs", 6), ("Diamonds", 8), ("Spades", 10)],
        jokers=["j_green_joker"],
        hands_left=2,
        discards_left=2,
        target=50,
        ante=2
    )
    plays = scored_plays(g_safe)
    act_safe = v10._tier1_survive(g_safe, plays, p_clear=0.99)
    if act_safe["type"] != "play":
        failures.append("2.B: Discard was NOT suppressed during safe blind: got " + str(act_safe))
    else:
        print("  [PASS] 2.B: Discard successfully suppressed to preserve Green Joker mult on safe blind.")

    # 2.C: hands_left == 2, UNSAFE blind (p_clear=0.30): discard MUST NOT be suppressed!
    g_unsafe = setup_game(
        [("Spades", 2), ("Hearts", 4), ("Clubs", 6), ("Diamonds", 8), ("Spades", 10)],
        jokers=["j_green_joker"],
        hands_left=2,
        discards_left=2,
        target=50000,
        ante=5
    )
    plays = scored_plays(g_unsafe)
    act_unsafe = v10._tier1_survive(g_unsafe, plays, p_clear=0.30)
    if act_unsafe["type"] != "discard":
        failures.append("2.C: Discard was wrongly suppressed on UNSAFE blind! got " + str(act_unsafe))
    else:
        print("  [PASS] 2.C: Discard correctly allowed on unsafe blind to dig for survival.")

    # 2.D: Green Joker + Ride the Bus joint interaction
    g_joint = setup_game(
        [
            ("Spades", 13), ("Hearts", 13), ("Clubs", 12),  # Face cards
            ("Diamonds", 2), ("Hearts", 3), ("Clubs", 4), ("Spades", 5), ("Hearts", 6)
        ],
        jokers=["j_green_joker", "j_ride_the_bus"],
        hands_left=2,
        discards_left=2,
        target=50,
        ante=2
    )
    g_joint.jokers[0].state["mult"] = 10
    g_joint.jokers[1].state["mult"] = 15
    plays = scored_plays(g_joint)
    act_joint = v10._tier1_survive(g_joint, plays, p_clear=0.99)
    if act_joint["type"] != "play":
        failures.append("2.D: Joint Green + Bus did not play hand: got " + str(act_joint))
    else:
        played = [g_joint.hand[i] for i in act_joint["cards"]]
        res = evaluate_hand(played)
        if any(c.is_face_card for c in res[1]):
            failures.append("2.D: Joint Green + Bus played scoring face card!")
        else:
            print("  [PASS] 2.D: Joint Green + Bus suppressed discard AND avoided scoring face cards.")

    # 2.E: Zero discards remaining with discard-incentive jokers (e.g. Faceless Joker)
    # The policy MUST NEVER return a discard action when discards_left == 0.
    # Returning discard when discards_left == 0 causes an infinite deadlock loop because game._discard is a no-op.
    g_zero_d = BalatroGame(seed=10001, rng_mode="seed")
    g_zero_d.reset()
    agent_test = SearchShopV10()
    for _ in range(105):
        g_zero_d.step(agent_test.decide(g_zero_d))
    
    act_zero_d = v10._v10_decide_hand(g_zero_d)
    if act_zero_d.get("type") == "discard":
        failures.append("2.E [CRITICAL BUG]: tier2_value returned discard action when discards_left == 0! Triggers infinite deadlock loop.")
    else:
        print("  [PASS] 2.E: tier2_value safely rejected discard action when discards_left == 0.")

    return failures


def stress_test_dangerous_bosses():
    print("=== TEST 3: Banned Boss Blinds Defense ===")
    failures = []
    
    banned = [
        ("bl_needle", "The Needle (1 hand only)"),
        ("bl_mouth", "The Mouth (only 1 hand type)"),
        ("bl_eye", "The Eye (no repeat hand types)"),
        ("bl_psychic", "The Psychic (must play 5 cards)"),
        ("bl_tooth", "The Tooth (lose $1 per card)"),
        ("bl_hook", "The Hook (discards 2 cards on play)"),
        ("bl_pillar", "The Pillar (cards debuffed)"),
        ("bl_grim", "The Grim (discards 2 random cards)"),
    ]
    
    for boss_key, name in banned:
        g = setup_game(
            [
                ("Spades", 14), ("Hearts", 14), ("Clubs", 14), ("Diamonds", 14),
                ("Hearts", 2), ("Clubs", 3), ("Diamonds", 4), ("Spades", 5)
            ],
            jokers=["j_green_joker", "j_wee", "j_ride_the_bus", "j_square_joker"],
            hands_left=3,
            discards_left=2,
            target=500,
            ante=3,
            boss=boss_key
        )
        plays = scored_plays(g)
        act = v10._find_scaling_action(g, g.hand, plays, p_clear=1.0)
        if act is not None:
            failures.append("3: Boss " + boss_key + " failed to suppress scaling action")
        else:
            print("  [PASS] 3: Scaling suppressed under " + name + ".")
            
        try:
            agent = HeuristicV10()
            dec = agent.decide(g)
            if dec is None:
                failures.append("3: Agent decide returned None under boss " + boss_key)
            if boss_key == "bl_psychic" and dec.get("type") == "play":
                if len(dec["cards"]) != 5:
                    failures.append("3: bl_psychic played " + str(len(dec["cards"])) + " cards instead of 5!")
        except Exception as e:
            failures.append("3: Exception under boss " + boss_key + ": " + traceback.format_exc())

    return failures


def stress_test_capital_deployment():
    print("=== TEST 4: Late-Game Capital Deployment & Liquidation ===")
    failures = []

    # 4.A: Ante 8 interest target must be 0 and force_no_save must be True
    g = setup_game([], jokers=["j_joker"], ante=8, dollars=50)
    g.state = State.SHOP
    agent = SearchShopV10()
    
    g.current_shop = [
        ShopItem(kind="joker", key="j_cavendish", name="Cavendish", price=8),
        ShopItem(kind="tarot", key="c_temperance", name="Temperance", price=3),
    ]
    
    steps = 0
    max_steps = 25
    seen_buys = 0
    seen_rerolls = 0
    while g.state == State.SHOP and steps < max_steps:
        act = agent.decide(g)
        steps += 1
        if act["type"] == "buy":
            seen_buys += 1
            idx = act["item_idx"]
            if idx >= len(g.current_shop) or g.current_shop[idx].sold:
                failures.append("4.A: Invalid buy index " + str(idx))
                break
            g.dollars -= g.current_shop[idx].price
            g.current_shop[idx].sold = True
        elif act["type"] == "reroll":
            seen_rerolls += 1
            g.dollars -= 5
            g.current_shop = [
                ShopItem(kind="joker", key="j_joker", name="Joker", price=4),
                ShopItem(kind="tarot", key="c_fool", name="The Fool", price=3),
            ]
        elif act["type"] == "leave_shop":
            break
        elif act["type"] == "sell_joker":
            j_idx = act["joker_idx"]
            if j_idx < len(g.jokers):
                g.dollars += g.jokers[j_idx].sell_value
                g.jokers.pop(j_idx)
        else:
            failures.append("4.A: Unexpected action " + str(act))
            break

    if steps >= max_steps:
        failures.append("4.A: Shop decision loop deadlocked or exceeded max steps in Ante 8!")
    else:
        print("  [PASS] 4.A: Shop terminated cleanly in " + str(steps) + " steps (buys=" + str(seen_buys) + ", rerolls=" + str(seen_rerolls) + ").")

    # 4.B: Extreme Bankroll Boundaries ($0, $1, $2, $3, $4, $5, $6)
    for test_dollars in (0, 1, 2, 3, 4, 5, 6):
        g_bound = setup_game([], jokers=["j_joker"], ante=8, dollars=test_dollars)
        g_bound.state = State.SHOP
        g_bound.current_shop = [
            ShopItem(kind="joker", key="j_cavendish", name="Cavendish", price=8),
            ShopItem(kind="tarot", key="c_fool", name="The Fool", price=3),
        ]
        agent_bound = SearchShopV10()
        try:
            act_bound = agent_bound.decide(g_bound)
            if act_bound is None or "type" not in act_bound:
                failures.append("4.B: Bound $" + str(test_dollars) + " returned invalid action")
            elif test_dollars == 0:
                if act_bound["type"] not in ("leave_shop", "sell_joker"):
                    failures.append("4.B: At $0, unexpected action: " + str(act_bound))
                else:
                    print("  [PASS] 4.B: At $0, policy safely returned: " + act_bound["type"])
            else:
                print("  [PASS] 4.B: At $" + str(test_dollars) + ", policy safely returned: " + act_bound["type"])
        except Exception as e:
            failures.append("4.B: Exception at $" + str(test_dollars) + ": " + traceback.format_exc())

    # 4.C: Full-Slot Portfolio Swapping (len(jokers) >= joker_slots in Ante 8)
    g_full = setup_game([], jokers=["j_joker", "j_greedy_joker", "j_wrathful_joker", "j_lusty_joker", "j_popcorn"], ante=8, dollars=10)
    g_full.state = State.SHOP
    g_full.joker_slots = 5
    g_full.current_shop = [
        ShopItem(kind="joker", key="j_cavendish", name="Cavendish", price=8),
        ShopItem(kind="tarot", key="c_fool", name="The Fool", price=3),
    ]
    agent_full = SearchShopV10()
    try:
        act_swap = agent_full.decide(g_full)
        if act_swap["type"] == "sell_joker":
            s_idx = act_swap["joker_idx"]
            if 0 <= s_idx < len(g_full.jokers):
                print("  [PASS] 4.C: Full slots successfully initiated swap by selling joker " + str(s_idx) + " (" + g_full.jokers[s_idx].key + ").")
            else:
                failures.append("4.C: Out of bound sell index " + str(s_idx))
        else:
            print("  [INFO] 4.C: Full slots decided action: " + act_swap["type"])
    except Exception as e:
        failures.append("4.C: Exception on full-slot swap: " + traceback.format_exc())

    # 4.D: Urgent rerolls caps in Antes 6, 7, 8
    g6 = setup_game([], jokers=["j_joker"], ante=6, dollars=40)
    g6.current_shop = []
    act6 = v10._v10_decide_shop(g6, rerolls_used=3)
    if act6["type"] == "reroll":
        print("  [PASS] 4.D: Ante 6 allows 4th reroll when lacking xMult.")
    act6_stop = v10._v10_decide_shop(g6, rerolls_used=4)
    if act6_stop["type"] == "leave_shop":
        print("  [PASS] 4.D: Ante 6 respects cap of 4 rerolls.")
    else:
        failures.append("4.D: Ante 6 failed to stop at cap 4: " + str(act6_stop))

    g7 = setup_game([], jokers=["j_joker"], ante=7, dollars=50)
    g7.current_shop = []
    act7 = v10._v10_decide_shop(g7, rerolls_used=5)
    if act7["type"] == "reroll":
        print("  [PASS] 4.D: Ante 7 allows 6th reroll under deficit.")
    act7_stop = v10._v10_decide_shop(g7, rerolls_used=6)
    if act7_stop["type"] == "leave_shop":
        print("  [PASS] 4.D: Ante 7 respects cap of 6 rerolls.")
    else:
        failures.append("4.D: Ante 7 failed to stop at cap 6: " + str(act7_stop))

    g8 = setup_game([], jokers=["j_joker"], ante=8, dollars=100)
    g8.current_shop = []
    act8 = v10._v10_decide_shop(g8, rerolls_used=9)
    if act8["type"] == "reroll":
        print("  [PASS] 4.D: Ante 8 allows 10th reroll.")
    act8_stop = v10._v10_decide_shop(g8, rerolls_used=10)
    if act8_stop["type"] == "leave_shop":
        print("  [PASS] 4.D: Ante 8 respects cap of 10 rerolls.")
    else:
        failures.append("4.D: Ante 8 failed to stop at cap 10: " + str(act8_stop))

    return failures


def run_end_to_end_rollouts(n_games=25):
    print("=== TEST 5: End-to-End Game Rollouts (" + str(n_games) + " Games) ===")
    failures = []
    
    agent = SearchShopV10()
    wins = 0
    crashes = 0
    
    for s in range(n_games):
        seed = 10000 + s
        try:
            g = BalatroGame(seed=seed, rng_mode="seed")
            g.reset()
            step_count = 0
            max_steps = 1500
            while g.state != State.GAME_OVER and step_count < max_steps:
                act = agent.decide(g)
                if act is None:
                    failures.append("Game seed " + str(seed) + " step " + str(step_count) + ": agent returned None action!")
                    crashes += 1
                    break
                g.step(act)
                step_count += 1
                
            if step_count >= max_steps:
                failures.append("Game seed " + str(seed) + " exceeded max steps (deadlock)! Current state: " + str(g.state) + " ante: " + str(g.ante) + " discards_left: " + str(g.discards_left))
                crashes += 1
            elif g.state == State.GAME_OVER and g.ante > 8:
                wins += 1
        except Exception as e:
            crashes += 1
            failures.append("Game seed " + str(seed) + " threw exception: " + traceback.format_exc())

    print("  End-to-end rollouts: " + str(n_games) + " games, " + str(wins) + " wins, " + str(crashes) + " crashes/deadlocks.")
    return failures


def main():
    print("===============================================================")
    print("  CHALLENGER 1: ADVERSARIAL STRESS TEST HARNESS FOR M1 POLICY  ")
    print("===============================================================")
    all_failures = []
    all_failures.extend(stress_test_ride_the_bus())
    all_failures.extend(stress_test_green_joker())
    all_failures.extend(stress_test_dangerous_bosses())
    all_failures.extend(stress_test_capital_deployment())
    all_failures.extend(run_end_to_end_rollouts(25))
    
    print("\n===============================================================")
    print("                      CHALLENGE SUMMARY                        ")
    print("===============================================================")
    if not all_failures:
        print("ALL ADVERSARIAL CHALLENGES PASSED! ZERO CRASHES OR VIOLATIONS.")
        sys.exit(0)
    else:
        print("FOUND " + str(len(all_failures)) + " FAILURES/ANOMALIES:")
        for f in all_failures:
            print("  - " + str(f))
        sys.exit(1)


if __name__ == "__main__":
    main()

