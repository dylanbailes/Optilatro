"""
training_report.py -- Training progress dashboard for V6 runs.

Usage:
    python scripts/training_report.py
    python scripts/training_report.py --log logs_sim/run_v6_r4_spendexcess.log
    python scripts/training_report.py --last 100   # compare last 100 iters instead of 50
"""
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

# ============================================================================

def parse_log(log_path: Path) -> list[dict]:
    """Parse training log lines into structured dicts."""
    entries = []
    for line in log_path.open():
        m = re.search(
            r'iter=(\d+)\s+sps=(\d+)\s+eps=(\d+)\s+.*?'
            r'rew=([0-9.\-+]+)\s+loss=([0-9.\-+nan]+)\s+'
            r'pg=([0-9.\-+nan]+)\s+vf=([0-9.\-+nan]+)\s+'
            r'ent=([0-9.\-+nan]+)\s+best=(\d+)\s+\(([0-9.]+)s\)',
            line
        )
        if m:
            entries.append({
                "iter": int(m[1]),
                "sps": int(m[2]),
                "eps": int(m[3]),
                "reward": float(m[4]),
                "loss": m[5],
                "pg_loss": m[6],
                "vf_loss": float(m[7]),
                "entropy": float(m[8]),
                "best_ante": int(m[9]),
                "time": float(m[10]),
            })
    return entries


def load_episodes(ckpt_dir: Path) -> list[dict]:
    """Load episode log, finding the latest run boundary."""
    ep_path = ckpt_dir / "episode_log.jsonl"
    if not ep_path.exists():
        return []
    lines = ep_path.read_text().splitlines()
    prev_iter = 0
    new_start = 0
    for i, l in enumerate(lines):
        try:
            it = json.loads(l).get("iteration", 0)
            if it < prev_iter - 10:
                new_start = i
            prev_iter = it
        except json.JSONDecodeError:
            continue
    eps = []
    for l in lines[new_start:]:
        try:
            eps.append(json.loads(l))
        except json.JSONDecodeError:
            continue
    return eps


def load_highlights(log_dir: Path) -> list[dict]:
    """Load highlight episodes."""
    hl_path = log_dir / "highlights.jsonl"
    if not hl_path.exists():
        return []
    highlights = []
    for line in hl_path.open():
        line = line.strip()
        if not line:
            continue
        try:
            highlights.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return highlights


def episode_stats(eps: list[dict]) -> dict:
    """Compute stats from a list of episodes."""
    if not eps:
        return {}
    n = len(eps)
    wins = sum(1 for e in eps if e.get("won", False))
    antes = [e.get("ante", 1) for e in eps]
    rewards = [e["reward"] for e in eps]
    dollars = [e.get("dollars", 0) for e in eps]
    steps = [e["steps"] for e in eps]

    return {
        "episodes": n,
        "win_rate": 100 * wins / n,
        "wins": wins,
        "avg_reward": sum(rewards) / n,
        "max_reward": max(rewards),
        "avg_ante": sum(antes) / n,
        "max_ante": max(antes),
        "past_ante1": 100 * sum(1 for a in antes if a >= 2) / n,
        "past_ante4": 100 * sum(1 for a in antes if a >= 5) / n,
        "ante6_plus": 100 * sum(1 for a in antes if a >= 6) / n,
        "avg_dollars": sum(dollars) / n,
        "avg_steps": sum(steps) / n,
        "ante_dist": Counter(antes),
    }


def highlight_stats(highlights: list[dict]) -> dict:
    """Compute strategy stats from highlight episodes."""
    if not highlights:
        return {}
    wins = [h for h in highlights if h.get("won")]
    if not wins:
        return {"total_highlights": len(highlights), "wins": 0}

    joker_counts = Counter(len(h["jokers_final"]) for h in wins)
    avg_jokers = sum(len(h["jokers_final"]) for h in wins) / len(wins)

    joker_freq = Counter()
    for h in wins:
        for j in h["jokers_final"]:
            joker_freq[j] += 1

    hand_freq = Counter()
    for h in wins:
        for p in h["plays"]:
            hand_freq[p["hand_type"]] += 1

    unique_seeds = len(set(h["seed"] for h in wins))

    return {
        "total_highlights": len(highlights),
        "wins": len(wins),
        "avg_jokers": avg_jokers,
        "joker_dist": dict(sorted(joker_counts.items())),
        "top_jokers": joker_freq.most_common(5),
        "top_hands": hand_freq.most_common(5),
        "unique_seeds": unique_seeds,
    }


def iter_stats(log_entries: list[dict]) -> dict:
    """Compute stats from log entries."""
    if not log_entries:
        return {}
    return {
        "avg_sps": sum(e["sps"] for e in log_entries) / len(log_entries),
        "avg_time": sum(e["time"] for e in log_entries) / len(log_entries),
        "avg_entropy": sum(e["entropy"] for e in log_entries) / len(log_entries),
        "avg_reward_log": sum(e["reward"] for e in log_entries) / len(log_entries),
        "min_entropy": min(e["entropy"] for e in log_entries),
        "max_entropy": max(e["entropy"] for e in log_entries),
        "best_ante": max(e["best_ante"] for e in log_entries),
    }


def fmt(val, fmt_str=".1f"):
    """Format a value, handling None."""
    if val is None:
        return "--"
    return f"{val:{fmt_str}}"


# ============================================================================

def print_report(log_path: Path, ckpt_dir: Path, log_dir: Path, last_n: int = 50):
    log_entries = parse_log(log_path)
    episodes = load_episodes(ckpt_dir)
    highlights = load_highlights(log_dir)

    if not log_entries:
        print(f"No log entries found in {log_path}")
        return

    latest_iter = log_entries[-1]["iter"]
    recent_entries = [e for e in log_entries if e["iter"] > latest_iter - last_n]

    # Split episodes
    recent_ep_cutoff = latest_iter - last_n
    all_eps = episodes
    recent_eps = [e for e in episodes if e.get("iteration", 0) > recent_ep_cutoff]

    # Split highlights (by recency -- last 500 wins)
    all_hl = highlights
    recent_hl_wins = [h for h in highlights if h.get("won")][-500:]

    all_ep = episode_stats(all_eps)
    rec_ep = episode_stats(recent_eps)
    all_it = iter_stats(log_entries)
    rec_it = iter_stats(recent_entries)
    all_hl = highlight_stats(highlights)
    rec_hl = highlight_stats(recent_hl_wins)

    # -- Header ------------------------------------------------------------
    print()
    print(f"{'=' * 70}")
    print(f"  TRAINING REPORT -- iter {latest_iter}")
    print(f"  Log: {log_path.name}")
    total_time = sum(e["time"] for e in log_entries)
    remaining = (1000 - latest_iter) * (rec_it.get("avg_time", 20))
    print(f"  Elapsed: {total_time/3600:.1f}h | ETA: {remaining/3600:.1f}h")
    print(f"{'=' * 70}")
    print()

    # -- Main metrics table ------------------------------------------------
    hdr = f"{'Metric':<30s} {'Total':>15s} {'Last ' + str(last_n) + ' iters':>15s}"
    print(hdr)
    print("-" * len(hdr))

    rows = [
        ("Win Rate",
         f"{all_ep.get('win_rate', 0):.1f}%",
         f"{rec_ep.get('win_rate', 0):.1f}%"),
        ("Avg Reward",
         fmt(all_ep.get("avg_reward"), "+.1f"),
         fmt(rec_ep.get("avg_reward"), "+.1f")),
        ("Max Reward",
         fmt(all_ep.get("max_reward"), "+.1f"),
         fmt(rec_ep.get("max_reward"), "+.1f")),
        ("Avg Ante",
         fmt(all_ep.get("avg_ante"), ".2f"),
         fmt(rec_ep.get("avg_ante"), ".2f")),
        ("Max Ante",
         str(all_ep.get("max_ante", "--")),
         str(rec_ep.get("max_ante", "--"))),
        ("Past Ante 1",
         f"{all_ep.get('past_ante1', 0):.1f}%",
         f"{rec_ep.get('past_ante1', 0):.1f}%"),
        ("Past Ante 4",
         f"{all_ep.get('past_ante4', 0):.1f}%",
         f"{rec_ep.get('past_ante4', 0):.1f}%"),
        ("Ante 6+",
         f"{all_ep.get('ante6_plus', 0):.1f}%",
         f"{rec_ep.get('ante6_plus', 0):.1f}%"),
        ("", "", ""),
        ("Avg Entropy",
         fmt(all_it.get("avg_entropy"), ".3f"),
         fmt(rec_it.get("avg_entropy"), ".3f")),
        ("Entropy Range",
         f"{all_it.get('min_entropy', 0):.2f}-{all_it.get('max_entropy', 0):.2f}",
         f"{rec_it.get('min_entropy', 0):.2f}-{rec_it.get('max_entropy', 0):.2f}"),
        ("Avg Steps/Episode",
         fmt(all_ep.get("avg_steps"), ".0f"),
         fmt(rec_ep.get("avg_steps"), ".0f")),
        ("Avg $/Episode",
         f"${all_ep.get('avg_dollars', 0):.0f}",
         f"${rec_ep.get('avg_dollars', 0):.0f}"),
        ("Episodes",
         f"{all_ep.get('episodes', 0):,}",
         f"{rec_ep.get('episodes', 0):,}"),
        ("", "", ""),
        ("Steps/Sec",
         fmt(all_it.get("avg_sps"), ",.0f"),
         fmt(rec_it.get("avg_sps"), ",.0f")),
        ("Time/Iter",
         f"{all_it.get('avg_time', 0):.1f}s",
         f"{rec_it.get('avg_time', 0):.1f}s"),
    ]

    for label, total_val, recent_val in rows:
        if not label:
            print()
            continue
        print(f"  {label:<28s} {total_val:>15s} {recent_val:>15s}")

    # -- Strategy ----------------------------------------------------------
    if rec_hl:
        print()
        print(f"{'-' * 50}")
        print(f"  STRATEGY (last 500 wins)")
        print(f"{'-' * 50}")
        print(f"  Avg jokers at win: {rec_hl.get('avg_jokers', 0):.1f}")
        print(f"  Joker count dist:  {rec_hl.get('joker_dist', {})}")
        print(f"  Unique seeds:      {rec_hl.get('unique_seeds', 0)}")
        print()
        if rec_hl.get("top_jokers"):
            print(f"  Top Jokers:")
            for j, n in rec_hl["top_jokers"]:
                pct = 100 * n / rec_hl.get("wins", 1)
                print(f"    {j:25s} {n:4d} ({pct:.0f}%)")
        print()
        if rec_hl.get("top_hands"):
            print(f"  Top Hand Types:")
            total_hands = sum(n for _, n in rec_hl["top_hands"])
            for ht, n in rec_hl["top_hands"]:
                pct = 100 * n / max(total_hands, 1)
                print(f"    {ht:25s} {n:5d} ({pct:.0f}%)")

    # -- Health checks -----------------------------------------------------
    print()
    print(f"{'-' * 50}")
    print(f"  HEALTH CHECKS")
    print(f"{'-' * 50}")
    issues = []
    rec_ent = rec_it.get("avg_entropy", 1.0)
    if rec_ent < 0.3:
        issues.append(f"  !! Entropy collapsed ({rec_ent:.3f}) -- agent may be stuck")
    elif rec_ent < 0.8:
        issues.append(f"  ?? Entropy low ({rec_ent:.3f}) -- may be converging or collapsing")

    if rec_ep.get("win_rate", 0) < all_ep.get("win_rate", 0) * 0.5 and latest_iter > 50:
        issues.append(f"  !! Win rate declining: {all_ep['win_rate']:.1f}% total vs {rec_ep['win_rate']:.1f}% recent")

    if rec_ep.get("avg_steps", 10) < 8:
        issues.append(f"  !! Very short episodes ({rec_ep['avg_steps']:.0f} steps) -- agent dying instantly")

    rec_wr = rec_ep.get("win_rate", 0)
    if rec_wr > 0 and rec_hl.get("avg_jokers", 0) < 2.0:
        issues.append(f"  ?? Winning with few jokers ({rec_hl['avg_jokers']:.1f} avg) -- shop underutilized")

    if rec_ep.get("avg_dollars", 0) > 30:
        issues.append(f"  ?? Hoarding money (${rec_ep['avg_dollars']:.0f} avg) -- not spending in shop")

    nan_iters = sum(1 for e in recent_entries if "nan" in str(e.get("loss", "")))
    if nan_iters > 0:
        issues.append(f"  !! NaN loss in {nan_iters}/{len(recent_entries)} recent iters")

    if not issues:
        print("  All clear.")
    else:
        for issue in issues:
            print(issue)

    print()


# ============================================================================

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--log", type=str, default=None, help="Training log path")
    parser.add_argument("--last", type=int, default=50, help="Compare last N iters (default 50)")
    args = parser.parse_args()

    base = Path(".")
    log_dir = base / "logs_sim"
    ckpt_dir = base / "checkpoints_sim"

    if args.log:
        log_path = Path(args.log)
    else:
        # Find most recent log
        logs = sorted(log_dir.glob("run_*.log"), key=lambda p: p.stat().st_mtime)
        if not logs:
            print("No training logs found in logs_sim/")
            sys.exit(1)
        log_path = logs[-1]

    print_report(log_path, ckpt_dir, log_dir, last_n=args.last)
