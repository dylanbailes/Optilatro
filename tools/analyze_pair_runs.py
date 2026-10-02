"""tools/analyze_pair_runs.py — Deep forensics and metric collection for Pair strategy.

Runs a bank of seeds, collects rich telemetry for each run, and compares
successful runs (ante 8 won) vs failed runs (early death) across:
- Deck composition (deck size, steel cards, blue seals, purple seals, enhancements)
- Planet scaling (Mercury uses, Pair level, base chips/mult)
- Economy dynamics (money spent, interest, econ_source, ending dollars)
- Hand execution (hands played, % pairs, multi-hand scaling plays, discards saved)
- Joker win attribution (win rate per joker when acquired)
- Death causes (ante distribution, blind kind, specific boss blinds)
"""
from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import sys
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean, median

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "vendor" / "balatro-rl"))

from balatro_sim.agent_pair import PairBot
from balatro_sim.game import BalatroGame
from balatro_sim.rollout import rollout


def _parse_seeds(spec: str) -> list[int]:
    out = []
    for chunk in spec.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "-" in chunk:
            start, end = chunk.split("-", 1)
            out.extend(range(int(start), int(end) + 1))
        else:
            out.append(int(chunk))
    return out


def _run_seed(seed: int) -> dict:
    game = BalatroGame(seed=seed, rng_mode="seed")
    bot = PairBot()
    res = rollout(game, bot)
    res["seed"] = seed
    return res


def analyze_runs(results: list[dict]) -> dict:
    wins = [r for r in results if r["won"]]
    losses = [r for r in results if not r["won"]]

    n_total = len(results)
    n_wins = len(wins)
    n_losses = len(losses)

    def safe_mean(items, default=0.0):
        return mean(items) if items else default

    def extract_metric(run_list, extractor):
        return [extractor(r) for r in run_list]

    # 1. Macro Progression
    macro_stats = {
        "total_runs": n_total,
        "wins": n_wins,
        "win_rate": (n_wins / n_total * 100.0) if n_total else 0.0,
        "mean_ante_wins": safe_mean(extract_metric(wins, lambda r: r["ante"])),
        "mean_ante_losses": safe_mean(extract_metric(losses, lambda r: r["ante"])),
        "mean_steps_wins": safe_mean(extract_metric(wins, lambda r: r["steps"])),
        "mean_steps_losses": safe_mean(extract_metric(losses, lambda r: r["steps"])),
    }

    # 2. Deck Architecture
    deck_stats = {
        "mean_deck_size_wins": safe_mean(extract_metric(wins, lambda r: r["stats"].get("deck_size", 52))),
        "mean_deck_size_losses": safe_mean(extract_metric(losses, lambda r: r["stats"].get("deck_size", 52))),
        "mean_steel_cards_wins": safe_mean(extract_metric(wins, lambda r: r["stats"].get("steel_cards", 0))),
        "mean_steel_cards_losses": safe_mean(extract_metric(losses, lambda r: r["stats"].get("steel_cards", 0))),
        "mean_blue_seals_wins": safe_mean(extract_metric(wins, lambda r: r["stats"].get("blue_seals", 0))),
        "mean_blue_seals_losses": safe_mean(extract_metric(losses, lambda r: r["stats"].get("blue_seals", 0))),
        "mean_purple_seals_wins": safe_mean(extract_metric(wins, lambda r: r["stats"].get("purple_seals", 0))),
        "mean_purple_seals_losses": safe_mean(extract_metric(losses, lambda r: r["stats"].get("purple_seals", 0))),
        "mean_gold_cards_wins": safe_mean(extract_metric(wins, lambda r: r["stats"].get("gold_cards", 0))),
        "mean_gold_cards_losses": safe_mean(extract_metric(losses, lambda r: r["stats"].get("gold_cards", 0))),
        "mean_lucky_cards_wins": safe_mean(extract_metric(wins, lambda r: r["stats"].get("lucky_cards", 0))),
        "mean_lucky_cards_losses": safe_mean(extract_metric(losses, lambda r: r["stats"].get("lucky_cards", 0))),
        "mean_glass_cards_wins": safe_mean(extract_metric(wins, lambda r: r["stats"].get("glass_cards", 0))),
        "mean_glass_cards_losses": safe_mean(extract_metric(losses, lambda r: r["stats"].get("glass_cards", 0))),
    }

    # 3. Planet Levels & Consumables
    def get_pair_level(r):
        return r["stats"].get("planet_levels", {}).get("Pair", 1)

    def count_mercury(r):
        return sum(1 for p in r["stats"].get("planets", []) if p in ("c_mercury", "pl_mercury"))

    planet_stats = {
        "mean_pair_level_wins": safe_mean(extract_metric(wins, get_pair_level)),
        "mean_pair_level_losses": safe_mean(extract_metric(losses, get_pair_level)),
        "mean_mercuries_used_wins": safe_mean(extract_metric(wins, count_mercury)),
        "mean_mercuries_used_losses": safe_mean(extract_metric(losses, count_mercury)),
        "mean_tarots_used_wins": safe_mean(extract_metric(wins, lambda r: len(r["stats"].get("tarots", [])))),
        "mean_tarots_used_losses": safe_mean(extract_metric(losses, lambda r: len(r["stats"].get("tarots", [])))),
        "mean_total_planets_wins": safe_mean(extract_metric(wins, lambda r: len(r["stats"].get("planets", [])))),
        "mean_total_planets_losses": safe_mean(extract_metric(losses, lambda r: len(r["stats"].get("planets", [])))),
    }

    # 4. Economy & Spend Dynamics
    econ_stats = {
        "mean_money_spent_wins": safe_mean(extract_metric(wins, lambda r: r["stats"].get("money_spent", 0))),
        "mean_money_spent_losses": safe_mean(extract_metric(losses, lambda r: r["stats"].get("money_spent", 0))),
        "mean_interest_wins": safe_mean(extract_metric(wins, lambda r: r["stats"].get("interest_collected", 0))),
        "mean_interest_losses": safe_mean(extract_metric(losses, lambda r: r["stats"].get("interest_collected", 0))),
        "mean_econ_source_wins": safe_mean(extract_metric(wins, lambda r: r["stats"].get("econ_source", 0))),
        "mean_econ_source_losses": safe_mean(extract_metric(losses, lambda r: r["stats"].get("econ_source", 0))),
        "mean_ending_dollars_wins": safe_mean(extract_metric(wins, lambda r: r.get("dollars", 0))),
        "mean_ending_dollars_losses": safe_mean(extract_metric(losses, lambda r: r.get("dollars", 0))),
        "mean_packs_bought_wins": safe_mean(extract_metric(wins, lambda r: r["stats"].get("packs_bought", 0))),
        "mean_packs_bought_losses": safe_mean(extract_metric(losses, lambda r: r["stats"].get("packs_bought", 0))),
    }

    # 5. Hand Execution & Pair Ratio
    def pair_ratio(r):
        rh = r["stats"].get("run_hand_counts", {})
        pairs = rh.get("Pair", 0)
        total = sum(rh.values())
        return (pairs / total * 100.0) if total > 0 else 0.0

    def total_hands(r):
        return sum(r["stats"].get("run_hand_counts", {}).values())

    hand_stats = {
        "mean_total_hands_wins": safe_mean(extract_metric(wins, total_hands)),
        "mean_total_hands_losses": safe_mean(extract_metric(losses, total_hands)),
        "mean_pair_percentage_wins": safe_mean(extract_metric(wins, pair_ratio)),
        "mean_pair_percentage_losses": safe_mean(extract_metric(losses, pair_ratio)),
        "mean_scaling_plays_wins": safe_mean(extract_metric(wins, lambda r: r.get("policy_stats", {}).get("scaling_plays", 0))),
        "mean_scaling_plays_losses": safe_mean(extract_metric(losses, lambda r: r.get("policy_stats", {}).get("scaling_plays", 0))),
        "mean_discards_saved_wins": safe_mean(extract_metric(wins, lambda r: r.get("policy_stats", {}).get("discards_saved", 0))),
        "mean_discards_saved_losses": safe_mean(extract_metric(losses, lambda r: r.get("policy_stats", {}).get("discards_saved", 0))),
    }

    # 6. Death Causes & Ante Breakdown
    ante_death_counts = Counter(r["ante"] for r in losses)
    blind_kind_deaths = Counter(r.get("death_kind", "") for r in losses)
    boss_deaths = Counter(r["stats"].get("boss_key") for r in losses if r.get("death_kind") == "Boss" and r["stats"].get("boss_key"))

    # 7. Joker Attribution (Win Rate when acquired)
    joker_wins = Counter()
    joker_losses = Counter()
    for r in results:
        all_jokers = set(r.get("jokers", [])) | set(r["stats"].get("jokers_bought", []))
        for j in all_jokers:
            if r["won"]:
                joker_wins[j] += 1
            else:
                joker_losses[j] += 1

    joker_performance = []
    all_seen_jokers = set(joker_wins.keys()) | set(joker_losses.keys())
    for j in all_seen_jokers:
        w = joker_wins[j]
        l = joker_losses[j]
        total = w + l
        wr = (w / total * 100.0) if total > 0 else 0.0
        joker_performance.append({
            "joker": j,
            "wins": w,
            "losses": l,
            "total_runs": total,
            "win_rate": wr,
        })
    joker_performance.sort(key=lambda x: (x["win_rate"], x["total_runs"]), reverse=True)

    return {
        "macro": macro_stats,
        "deck": deck_stats,
        "planets": planet_stats,
        "economy": econ_stats,
        "hands": hand_stats,
        "losses": {
            "by_ante": dict(ante_death_counts),
            "by_blind_kind": dict(blind_kind_deaths),
            "top_lethal_bosses": dict(boss_deaths.most_common(10)),
        },
        "jokers": joker_performance,
        "raw_runs": results,
    }


def print_report(analysis: dict):
    m = analysis["macro"]
    d = analysis["deck"]
    p = analysis["planets"]
    e = analysis["economy"]
    h = analysis["hands"]
    l = analysis["losses"]

    print("\n" + "=" * 80)
    print(f"PAIR_BOT RUN FORENSICS & METRIC ANALYSIS ({m['total_runs']} Runs)")
    print("=" * 80)
    print(f"Overall Result: {m['wins']}/{m['total_runs']} Wins ({m['win_rate']:.1f}% Win Rate)")
    print(f"Average Ante: Wins = {m['mean_ante_wins']:.2f} | Losses = {m['mean_ante_losses']:.2f}")
    print(f"Average Steps: Wins = {m['mean_steps_wins']:.1f} | Losses = {m['mean_steps_losses']:.1f}")

    print("\n" + "-" * 80)
    print("1. DECK COMPOSITION & CARD ARCHITECTURE")
    print("-" * 80)
    print(f"{'Metric':<35} | {'Successful Runs (Wins)':<22} | {'Failed Runs (Losses)':<20} | {'Delta':<10}")
    print(f"{'-'*35}-+-{'-'*22}-+-{'-'*20}-+-{'-'*10}")
    print(f"{'Final Deck Size':<35} | {d['mean_deck_size_wins']:<22.2f} | {d['mean_deck_size_losses']:<20.2f} | {d['mean_deck_size_wins'] - d['mean_deck_size_losses']:+.2f}")
    print(f"{'Steel Cards in Deck':<35} | {d['mean_steel_cards_wins']:<22.2f} | {d['mean_steel_cards_losses']:<20.2f} | {d['mean_steel_cards_wins'] - d['mean_steel_cards_losses']:+.2f}")
    print(f"{'Blue Seals in Deck':<35} | {d['mean_blue_seals_wins']:<22.2f} | {d['mean_blue_seals_losses']:<20.2f} | {d['mean_blue_seals_wins'] - d['mean_blue_seals_losses']:+.2f}")
    print(f"{'Purple Seals in Deck':<35} | {d['mean_purple_seals_wins']:<22.2f} | {d['mean_purple_seals_losses']:<20.2f} | {d['mean_purple_seals_wins'] - d['mean_purple_seals_losses']:+.2f}")
    print(f"{'Gold Cards in Deck':<35} | {d['mean_gold_cards_wins']:<22.2f} | {d['mean_gold_cards_losses']:<20.2f} | {d['mean_gold_cards_wins'] - d['mean_gold_cards_losses']:+.2f}")
    print(f"{'Lucky Cards in Deck':<35} | {d['mean_lucky_cards_wins']:<22.2f} | {d['mean_lucky_cards_losses']:<20.2f} | {d['mean_lucky_cards_wins'] - d['mean_lucky_cards_losses']:+.2f}")
    print(f"{'Glass Cards in Deck':<35} | {d['mean_glass_cards_wins']:<22.2f} | {d['mean_glass_cards_losses']:<20.2f} | {d['mean_glass_cards_wins'] - d['mean_glass_cards_losses']:+.2f}")

    print("\n" + "-" * 80)
    print("2. PLANET SCALING & CONSUMABLE USAGE")
    print("-" * 80)
    print(f"{'Metric':<35} | {'Successful Runs (Wins)':<22} | {'Failed Runs (Losses)':<20} | {'Delta':<10}")
    print(f"{'-'*35}-+-{'-'*22}-+-{'-'*20}-+-{'-'*10}")
    print(f"{'Pair Planet Level at Finish':<35} | {p['mean_pair_level_wins']:<22.2f} | {p['mean_pair_level_losses']:<20.2f} | {p['mean_pair_level_wins'] - p['mean_pair_level_losses']:+.2f}")
    print(f"{'Mercury Cards Consumed':<35} | {p['mean_mercuries_used_wins']:<22.2f} | {p['mean_mercuries_used_losses']:<20.2f} | {p['mean_mercuries_used_wins'] - p['mean_mercuries_used_losses']:+.2f}")
    print(f"{'Total Tarots Consumed':<35} | {p['mean_tarots_used_wins']:<22.2f} | {p['mean_tarots_used_losses']:<20.2f} | {p['mean_tarots_used_wins'] - p['mean_tarots_used_losses']:+.2f}")
    print(f"{'Total Planets Consumed':<35} | {p['mean_total_planets_wins']:<22.2f} | {p['mean_total_planets_losses']:<20.2f} | {p['mean_total_planets_wins'] - p['mean_total_planets_losses']:+.2f}")

    print("\n" + "-" * 80)
    print("3. ECONOMY & SHOP ALLOCATION")
    print("-" * 80)
    print(f"{'Metric':<35} | {'Successful Runs (Wins)':<22} | {'Failed Runs (Losses)':<20} | {'Delta':<10}")
    print(f"{'-'*35}-+-{'-'*22}-+-{'-'*20}-+-{'-'*10}")
    print(f"{'Total Money Spent ($)':<35} | ${e['mean_money_spent_wins']:<21.2f} | ${e['mean_money_spent_losses']:<19.2f} | ${e['mean_money_spent_wins'] - e['mean_money_spent_losses']:+.2f}")
    print(f"{'Interest Collected ($)':<35} | ${e['mean_interest_wins']:<21.2f} | ${e['mean_interest_losses']:<19.2f} | ${e['mean_interest_wins'] - e['mean_interest_losses']:+.2f}")
    print(f"{'Joker Econ Revenue ($)':<35} | ${e['mean_econ_source_wins']:<21.2f} | ${e['mean_econ_source_losses']:<19.2f} | ${e['mean_econ_source_wins'] - e['mean_econ_source_losses']:+.2f}")
    print(f"{'Packs Purchased':<35} | {e['mean_packs_bought_wins']:<22.2f} | {e['mean_packs_bought_losses']:<20.2f} | {e['mean_packs_bought_wins'] - e['mean_packs_bought_losses']:+.2f}")

    print("\n" + "-" * 80)
    print("4. HAND PLAY & STRATEGY EXECUTION")
    print("-" * 80)
    print(f"{'Metric':<35} | {'Successful Runs (Wins)':<22} | {'Failed Runs (Losses)':<20} | {'Delta':<10}")
    print(f"{'-'*35}-+-{'-'*22}-+-{'-'*20}-+-{'-'*10}")
    print(f"{'Total Hands Played':<35} | {h['mean_total_hands_wins']:<22.2f} | {h['mean_total_hands_losses']:<20.2f} | {h['mean_total_hands_wins'] - h['mean_total_hands_losses']:+.2f}")
    print(f"{'Pair Play Concentration (%)':<35} | {h['mean_pair_percentage_wins']:<21.1f}% | {h['mean_pair_percentage_losses']:<19.1f}% | {h['mean_pair_percentage_wins'] - h['mean_pair_percentage_losses']:+.1f}%")
    print(f"{'Scaling Plays Farmed':<35} | {h['mean_scaling_plays_wins']:<22.2f} | {h['mean_scaling_plays_losses']:<20.2f} | {h['mean_scaling_plays_wins'] - h['mean_scaling_plays_losses']:+.2f}")
    print(f"{'Discards Farmed / Saved':<35} | {h['mean_discards_saved_wins']:<22.2f} | {h['mean_discards_saved_losses']:<20.2f} | {h['mean_discards_saved_wins'] - h['mean_discards_saved_losses']:+.2f}")

    print("\n" + "-" * 80)
    print("5. DEATH FORENSICS (WHERE RUNS FAIL)")
    print("-" * 80)
    print(f"Deaths by Ante: {dict(sorted(l['by_ante'].items()))}")
    print(f"Deaths by Blind Type: {l['by_blind_kind']}")
    print(f"Top Lethal Bosses: {l['top_lethal_bosses']}")

    print("\n" + "-" * 80)
    print("6. JOKER WIN ATTRIBUTION (TOP SYNERGIES & TRAPS)")
    print("-" * 80)
    print(f"{'Joker':<25} | {'Runs With Joker':<15} | {'Wins':<6} | {'Losses':<8} | {'Win Rate':<10}")
    print(f"{'-'*25}-+-{'-'*15}-+-{'-'*6}-+-{'-'*8}-+-{'-'*10}")
    top_synergies = [j for j in analysis["jokers"] if j["total_runs"] >= 2 and j["win_rate"] >= 20.0][:10]
    for j in top_synergies:
        print(f"{j['joker']:<25} | {j['total_runs']:<15} | {j['wins']:<6} | {j['losses']:<8} | {j['win_rate']:<9.1f}%")

    print("\nLowest Win Rate / High Loss Jokers (Traps):")
    traps = [j for j in analysis["jokers"] if j["total_runs"] >= 5 and j["win_rate"] == 0.0][:10]
    for j in traps:
        print(f"{j['joker']:<25} | {j['total_runs']:<15} | {j['wins']:<6} | {j['losses']:<8} | {j['win_rate']:<9.1f}%")
    print("=" * 80 + "\n")


def main():
    parser = argparse.ArgumentParser(description="Analyze PairBot runs with deep metrics")
    parser.add_argument("--seeds", default="10500-10599", help="Seed range (e.g. 10500-10599)")
    parser.add_argument("--workers", type=int, default=12, help="Number of parallel worker processes")
    parser.add_argument("--output", default=str(REPO_ROOT / "vendor/balatro-rl/results/pair_run_forensics.json"),
                        help="Path to save full JSON analysis telemetry")
    args = parser.parse_args()

    seeds = _parse_seeds(args.seeds)
    print(f"Analyzing {len(seeds)} seeds across {args.workers} workers...")

    if args.workers > 1:
        with mp.Pool(args.workers) as pool:
            results = pool.map(_run_seed, seeds)
    else:
        results = [_run_seed(s) for s in seeds]

    analysis = analyze_runs(results)
    print_report(analysis)

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(analysis, f, indent=2)
    print(f"Saved full forensic analysis telemetry to {out_path}")


if __name__ == "__main__":
    main()
