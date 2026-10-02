"""tools/trace_pair_run.py — Detailed step-by-step tracer for PairBot runs.

Extracts exact narrative case studies of runs:
- Jokers seen, bought, sold, and skipped in shops and booster packs
- Hand-by-hand execution in the fatal ante (cards played, hand type, chips scored, target left)
- Enhanced cards, seals, and editions in the deck
- Consumables used and planet levels
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Ensure UTF-8 output on Windows consoles
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "vendor" / "balatro-rl"))

from balatro_sim.agent_pair import PairBot
from balatro_sim.game import BalatroGame, State
from balatro_sim.hand_eval import evaluate_hand

SUIT_SYMBOLS = {
    "Spades": "S",
    "Hearts": "H",
    "Clubs": "C",
    "Diamonds": "D",
    "S": "S",
    "H": "H",
    "C": "C",
    "D": "D",
}


def format_card(c) -> str:
    r = {14: "A", 13: "K", 12: "Q", 11: "J", 10: "10"}.get(getattr(c, "rank", None), str(getattr(c, "rank", "?")))
    raw_suit = str(getattr(c, "suit", "?"))
    s = SUIT_SYMBOLS.get(raw_suit, raw_suit[0] if raw_suit else "?")
    enh = f" [{c.enhancement}]" if getattr(c, "enhancement", "None") != "None" else ""
    seal = f" ({c.seal} Seal)" if getattr(c, "seal", "None") != "None" else ""
    ed = f" <{c.edition}>" if getattr(c, "edition", "None") != "None" else ""
    debuff = " [DEBUFFED]" if getattr(c, "debuffed", False) else ""
    return f"{r}{s}{enh}{seal}{ed}{debuff}"


def trace_seed(seed: int, verbose: bool = False) -> dict:
    game = BalatroGame(seed=seed, rng_mode="seed")
    bot = PairBot()

    jokers_seen: list[dict] = []
    jokers_bought: list[dict] = []
    jokers_sold: list[dict] = []
    booster_packs_opened: list[dict] = []
    consumables_used_log: list[dict] = []
    blinds_log: list[dict] = []

    seen_shop_item_keys = set()
    current_blind_hands = None
    last_state = None
    steps = 0

    while game.state != State.GAME_OVER and steps < 2000:
        steps += 1
        st = game.state

        # Snapshot shop items on entering SHOP or rerolling
        if st == State.SHOP:
            for it in game.current_shop:
                if not getattr(it, "sold", False):
                    item_id = (game.ante, it.kind, it.key, id(it))
                    if item_id not in seen_shop_item_keys:
                        seen_shop_item_keys.add(item_id)
                        if it.kind == "joker":
                            jokers_seen.append({
                                "ante": game.ante,
                                "source": "shop",
                                "key": it.key,
                                "price": it.price,
                                "edition": getattr(it, "edition", "None"),
                            })

        # Snapshot booster choices on entering BOOSTER_OPEN
        if st == State.BOOSTER_OPEN and last_state != State.BOOSTER_OPEN:
            pack_jokers = []
            for choice in game.booster_choices:
                if isinstance(choice, tuple) and choice[0] == "joker":
                    _, j_key, j_ed = choice
                    pack_jokers.append((j_key, j_ed))
                    jokers_seen.append({
                        "ante": game.ante,
                        "source": "buffoon_pack",
                        "key": j_key,
                        "price": 0,
                        "edition": j_ed,
                    })
            booster_packs_opened.append({
                "ante": game.ante,
                "choices": [str(c) for c in game.booster_choices],
            })

        # Snapshot blind info on entering SELECTING_HAND
        if st == State.SELECTING_HAND and last_state not in (State.SELECTING_HAND, State.BOOSTER_OPEN):
            b = game.current_blind
            current_blind_hands = {
                "ante": game.ante,
                "kind": b.kind,
                "is_boss": b.is_boss,
                "boss_key": getattr(b, "boss_key", None),
                "chips_target": b.chips_target,
                "plays": [],
                "discards": [],
                "consumables": [],
            }
            blinds_log.append(current_blind_hands)

        # Decide
        act = bot.decide(game)
        act_type = act.get("type")

        # Record action specifics before stepping
        pending_play = None
        if st == State.SHOP:
            if act_type == "buy":
                idx = act.get("item_idx", 0)
                if idx < len(game.current_shop):
                    it = game.current_shop[idx]
                    if it.kind == "joker":
                        jokers_bought.append({
                            "ante": game.ante,
                            "key": it.key,
                            "price": it.price,
                            "edition": getattr(it, "edition", "None"),
                            "source": "shop",
                        })
            elif act_type == "sell_joker":
                j_idx = act.get("joker_idx", 0)
                if j_idx < len(game.jokers):
                    j = game.jokers[j_idx]
                    jokers_sold.append({
                        "ante": game.ante,
                        "key": j.key,
                        "sell_cost": getattr(j, "sell_cost", 0),
                    })
        elif st == State.BOOSTER_OPEN:
            if act_type == "pick_booster":
                indices = act.get("indices", [])
                for idx in indices:
                    if idx < len(game.booster_choices):
                        choice = game.booster_choices[idx]
                        if isinstance(choice, tuple) and choice[0] == "joker":
                            _, j_key, j_ed = choice
                            jokers_bought.append({
                                "ante": game.ante,
                                "key": j_key,
                                "price": 0,
                                "edition": j_ed,
                                "source": "buffoon_pack",
                            })
        elif st == State.SELECTING_HAND:
            if act_type == "play" and current_blind_hands:
                card_objs = [game.hand[i] for i in act["cards"] if i < len(game.hand)]
                ht, scoring = evaluate_hand(card_objs)
                pending_play = {
                    "cards": [format_card(c) for c in card_objs],
                    "hand_type": ht,
                    "chips_target": game.current_blind.chips_target,
                    "chips_before": game.chips_scored,
                    "hands_left": game.hands_left,
                }
            elif act_type == "discard" and current_blind_hands:
                card_objs = [game.hand[i] for i in act["cards"] if i < len(game.hand)]
                current_blind_hands["discards"].append({
                    "cards": [format_card(c) for c in card_objs],
                    "discards_left": game.discards_left,
                })
            elif act_type == "use_consumable":
                c_idx = act.get("consumable_idx", 0)
                if c_idx < len(game.consumable_hand):
                    c_key = game.consumable_hand[c_idx]
                    target_cards = [format_card(game.hand[i]) for i in act.get("selected_cards", []) if i < len(game.hand)]
                    item_desc = f"{c_key} on [{', '.join(target_cards)}]" if target_cards else c_key
                    consumables_used_log.append({
                        "ante": game.ante,
                        "desc": item_desc,
                    })
                    if current_blind_hands:
                        current_blind_hands["consumables"].append(item_desc)

        chips_before_step = game.chips_scored
        last_state = st
        game.step(act)

        # Post-step bookkeeping for play scoring
        if pending_play is not None and current_blind_hands:
            chips_scored_by_hand = game.chips_scored - chips_before_step
            pending_play["chips_scored"] = chips_scored_by_hand
            pending_play["chips_total"] = game.chips_scored
            current_blind_hands["plays"].append(pending_play)

    won = bool(game.ante > 8 and game.state == State.GAME_OVER)

    # Gather full deck deviations
    full_deck = list(game.deck) + list(game.hand) + list(game.spent)
    deviations = [
        format_card(c) for c in full_deck
        if getattr(c, "enhancement", "None") != "None"
        or getattr(c, "seal", "None") != "None"
        or getattr(c, "edition", "None") != "None"
    ]

    result = {
        "seed": seed,
        "won": won,
        "final_ante": game.ante,
        "final_blind": game.current_blind.kind if game.current_blind else "None",
        "final_dollars": game.dollars,
        "final_jokers": [j.key for j in game.jokers],
        "jokers_seen": jokers_seen,
        "jokers_bought": jokers_bought,
        "jokers_sold": jokers_sold,
        "planet_levels": dict(game.planet_levels),
        "tarots_used": list(game.tarots_used),
        "planets_used": list(game.planets_used),
        "consumables_log": consumables_used_log,
        "deck_size": len(full_deck),
        "deviations": deviations,
        "blinds_log": blinds_log,
    }

    print("\n" + "=" * 80)
    outcome_str = "VICTORY (Won Ante 8!)" if won else f"DEFEAT (Died in Ante {game.ante} {result['final_blind']})"
    print(f"CASE STUDY: SEED {seed} — {outcome_str}")
    print("=" * 80)
    print(f"Final Ante Reached : {game.ante}")
    print(f"Final Dollars      : ${game.dollars}")
    print(f"Final Jokers Owned : {[j.key for j in game.jokers]}")
    print(f"Total Deck Cards   : {len(full_deck)} ({len(deviations)} modified cards)")
    print(f"Pair Hand Level    : Level {game.planet_levels.get('Pair', 1)}")
    print(f"All Hand Levels    : {dict(game.planet_levels)}")

    print("\n" + "-" * 80)
    print("JOKER ACTIVITY (Seen vs Bought vs Sold)")
    print("-" * 80)
    bought_keys = {jb["key"] for jb in jokers_bought}
    print("  JOKERS BOUGHT:")
    for jb in jokers_bought:
        ed_str = f" <{jb['edition']}>" if jb['edition'] != "None" else ""
        print(f"    - [Ante {jb['ante']}] {jb['key']}{ed_str} (via {jb['source']}, ${jb['price']})")
    if jokers_sold:
        print("  JOKERS SOLD:")
        for js in jokers_sold:
            print(f"    - [Ante {js['ante']}] {js['key']} (+${js['sell_cost']})")
    print("  OTHER JOKERS SEEN BUT PASSED:")
    skipped_jokers = [js for js in jokers_seen if js["key"] not in bought_keys]
    if skipped_jokers:
        # Deduplicate
        seen_keys = set()
        for js in skipped_jokers:
            if js["key"] not in seen_keys:
                seen_keys.add(js["key"])
                ed_str = f" <{js['edition']}>" if js['edition'] != "None" else ""
                print(f"    - [Ante {js['ante']}] {js['key']}{ed_str} ({js['source']}, ${js['price']})")
    else:
        print("    (None)")

    print("\n" + "-" * 80)
    print("DECK MODIFICATIONS (Cards Deviating from Standard 52)")
    print("-" * 80)
    if deviations:
        for d in deviations:
            print(f"    * {d}")
    else:
        print("    (Standard 52-card deck unmodified)")

    print("\n" + "-" * 80)
    print("CONSUMABLES USED ACROSS RUN")
    print("-" * 80)
    print(f"  Tarots Consumed  ({len(game.tarots_used)}): {list(game.tarots_used)}")
    print(f"  Planets Consumed ({len(game.planets_used)}): {list(game.planets_used)}")
    if consumables_used_log:
        print("  Chronological Log:")
        for cu in consumables_used_log:
            print(f"    - [Ante {cu['ante']}] {cu['desc']}")

    # Fatal Ante breakdown
    if not won and blinds_log:
        fatal_blind = blinds_log[-1]
        print("\n" + "-" * 80)
        print(f"FATAL BLIND PLAY-BY-PLAY (Ante {fatal_blind['ante']} {fatal_blind['kind']})")
        if fatal_blind['is_boss']:
            print(f"Boss Name/Rule: {fatal_blind['boss_key']}")
        print(f"Chips Target  : {fatal_blind['chips_target']:,}")
        print("-" * 80)
        for pi, play in enumerate(fatal_blind["plays"], 1):
            print(f"  [Hand {pi}] ({play['hands_left']} hands remaining before play):")
            print(f"    Played Cards : {', '.join(play['cards'])}")
            print(f"    Evaluated As : {play['hand_type']}")
            print(f"    Scored       : +{play.get('chips_scored', 0):,} chips (Total: {play.get('chips_total', play['chips_before']):,} / {play['chips_target']:,})")
        if fatal_blind["discards"]:
            print("  Discards in Fatal Blind:")
            for di, disc in enumerate(fatal_blind["discards"], 1):
                print(f"    Discard {di} ({disc['discards_left']} discards remaining): {', '.join(disc['cards'])}")
        if fatal_blind["consumables"]:
            print(f"  Consumables Used in Fatal Blind: {fatal_blind['consumables']}")
    print("=" * 80 + "\n")

    return result


def main():
    parser = argparse.ArgumentParser(description="Trace PairBot run on specific seeds")
    parser.add_argument("--seeds", default="10500,10501,10502,10504", help="Comma-separated seeds to trace")
    args = parser.parse_args()

    for s in args.seeds.split(","):
        s = s.strip()
        if s:
            trace_seed(int(s))


if __name__ == "__main__":
    main()
