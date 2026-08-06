"""
find_replay_candidates.py

Filters eval_trajectories.jsonl for "interesting" episodes worth replaying
in the Lua mod for the project video.

Default heuristic: prioritize episodes that
  1. Won (ante > 8)
  2. Reached high ante (>= 6) without winning
  3. Had high strategic-discard usage during SELECTING_HAND
  4. Featured uncommon joker mixes (not the Green+Space-only plateau signature)

Prints a ranked candidate list. Pick one or two and feed the seed to the
Lua replay-mode mod.

Usage:
    python scripts/find_replay_candidates.py results/eval_trajectories.jsonl
    python scripts/find_replay_candidates.py results/eval_trajectories.jsonl --top 20
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


def load_episodes(path: Path):
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


def score_episode(ep: dict) -> tuple[float, dict]:
    """Compute an 'interestingness' score for an episode."""
    outcome = ep["outcome"]
    traj = ep["trajectory"]

    base = 0.0
    reasons: list[str] = []

    # 1. Winning is the strongest signal
    if outcome["won"]:
        base += 100.0
        reasons.append("WON")

    # 2. High ante without winning still valuable
    if outcome["ante"] >= 7 and not outcome["won"]:
        base += 30.0 * (outcome["ante"] - 6)
        reasons.append(f"ante-{outcome['ante']}")

    # 3. Strategic discard usage
    hand_steps = [s for s in traj if s["phase"] == "hand"]
    if hand_steps:
        discard_count = sum(
            1 for s in hand_steps
            if s.get("action", {}).get("intent") == "discard"
        )
        discard_rate = discard_count / len(hand_steps)
        if discard_rate > 0.15:
            base += 20.0
            reasons.append(f"discard_rate={discard_rate:.0%}")

    # 4. Joker diversity (non-plateau signatures)
    all_jokers: list[str] = []
    for s in traj:
        all_jokers.extend(s.get("jokers", []))
    if all_jokers:
        joker_set = set(all_jokers)
        plateau_jokers = {"Green Joker", "Space Joker"}
        has_plateau = plateau_jokers.issubset(joker_set)
        unique_non_plateau = joker_set - plateau_jokers
        if not has_plateau and len(unique_non_plateau) >= 3:
            base += 15.0
            reasons.append(f"unusual_jokers=[{', '.join(sorted(unique_non_plateau))[:60]}]")
        elif len(joker_set) >= 5:
            base += 5.0
            reasons.append(f"joker_variety={len(joker_set)}")

    # 5. Surprising / low-confidence decisions (agent wasn't sure)
    uncertain_steps = 0
    for s in traj:
        probs = s.get("top_probs", [])
        if probs and len(probs) >= 2:
            top = probs[0][1]
            if 0.3 < top < 0.6:
                uncertain_steps += 1
    if uncertain_steps >= 5:
        base += 10.0
        reasons.append(f"uncertain_decisions={uncertain_steps}")

    # 6. Video length sweet spot (60-200 steps is watchable)
    steps = outcome["steps"]
    if 60 <= steps <= 200:
        base += 5.0
    elif steps < 40 or steps > 400:
        base -= 10.0

    return base, {
        "score":    round(base, 2),
        "reasons":  reasons,
        "outcome":  outcome,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input", help="eval_trajectories.jsonl from eval_with_trajectory.py")
    ap.add_argument("--top", type=int, default=15, help="Show top N candidates")
    args = ap.parse_args()

    episodes = list(load_episodes(Path(args.input)))
    print(f"Loaded {len(episodes)} episodes\n")

    scored = []
    for ep in episodes:
        score, meta = score_episode(ep)
        scored.append((score, ep, meta))

    scored.sort(key=lambda x: -x[0])

    print(f"{'Rank':<6}{'Score':<8}{'Seed':<14}{'Ante':<6}{'Won':<6}{'Steps':<8}Reasons")
    print("-" * 120)
    for rank, (score, ep, meta) in enumerate(scored[:args.top], 1):
        o = meta["outcome"]
        reasons = "; ".join(meta["reasons"])
        print(f"{rank:<6}{score:<8.1f}{ep['seed']:<14}{o['ante']:<6}"
              f"{'Y' if o['won'] else 'N':<6}{o['steps']:<8}{reasons}")

    wins = sum(1 for _, ep, _ in scored if ep["outcome"]["won"])
    if wins:
        print(f"\nWin-rate summary: {wins}/{len(episodes)} = {100*wins/len(episodes):.2f}%")

    # Dump top-N seeds to a ready-to-use file
    top_seeds_path = Path(args.input).parent / "replay_candidates.txt"
    with open(top_seeds_path, "w") as f:
        f.write("# seed, ante, won, steps, score, reasons\n")
        for rank, (score, ep, meta) in enumerate(scored[:args.top], 1):
            o = meta["outcome"]
            f.write(f"{ep['seed']},{o['ante']},{1 if o['won'] else 0},"
                    f"{o['steps']},{score:.1f},"
                    f"\"{'; '.join(meta['reasons'])}\"\n")
    print(f"\nTop-{args.top} seeds written to {top_seeds_path}")


if __name__ == "__main__":
    main()
