"""bench/compare_m14_arms.py — paired cross-arm comparison of M14 jsonl banks.

Loads several /tmp/*.jsonl files (rows carry tag/seed/policy/won/ante1_death),
builds per-(file, tag, policy) seed->outcome maps and prints:
  - headline win / ante-1-death counts
  - paired flips vs heuristic_v9 within the same file+tag (McNemar counts)
  - paired flips between two v10 arms (arm A vs arm B) via --pair
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def load(paths):
    """-> {(file, tag, policy): {seed: row}}"""
    out = {}
    for p in paths:
        for ln in Path(p).read_text().splitlines():
            if not ln.strip():
                continue
            r = json.loads(ln)
            key = (Path(p).name, r.get("tag", "base"), r["policy"])
            out.setdefault(key, {})[r["seed"]] = r
    return out


def headline(arms):
    for (f, tag, pol), seeds in sorted(arms.items()):
        n = len(seeds)
        wins = sum(r["won"] for r in seeds.values())
        a1 = sum(r["ante1_death"] for r in seeds.values())
        lo, hi = min(seeds), max(seeds)
        print(f"{f:28} [{tag:8}] {pol:14} n={n:3} ({lo}..{hi})  "
              f"wins {wins:2}/{n} = {wins/n:5.1%}  "
              f"a1deaths {a1:2}/{n} = {a1/n:5.1%}")


def flips(a, b, metric):
    """Paired flip counts a-vs-b on a metric ('won' or 'ante1_death')."""
    common = sorted(set(a) & set(b))
    a_only = len(set(a) - set(b))
    b_only = len(set(b) - set(a))
    aw = sum(1 for s in common if a[s][metric] and not b[s][metric])
    bw = sum(1 for s in common if b[s][metric] and not a[s][metric])
    return len(common), aw, bw, a_only, b_only


def report(arms, key_a, key_b, metric, label):
    a, b = arms.get(key_a, {}), arms.get(key_b, {})
    if not a or not b:
        print(f"  (missing {key_a if not a else key_b} for {label})")
        return
    n, aw, bw, ao, bo = flips(a, b, metric)
    print(f"  {label}: n={n}  A={aw} B={bw}  (A better on {aw - bw:+d}; "
          f"unpaired A-only={ao} B-only={bo})")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--pair", nargs=2, action="append", default=[],
                    metavar=("TAG_A", "TAG_B"),
                    help="compare v10 arms by tag across all files")
    a = ap.parse_args()
    arms = load(a.files)
    print("== headline ==")
    headline(arms)

    print("\n== paired vs heuristic_v9 (same file+tag) ==")
    for (f, tag, pol) in sorted(arms):
        if pol == "heuristic_v9":
            continue
        k9 = (f, tag, "heuristic_v9")
        if k9 in arms:
            report(arms, (f, tag, pol), k9, "ante1_death",
                   f"{f}[{tag}] {pol} a1deaths")
            report(arms, (f, tag, pol), k9, "won",
                   f"{f}[{tag}] {pol} wins")

    for tag_a, tag_b in a.pair:
        print(f"\n== paired v10 arms {tag_a} vs {tag_b} ==")
        # merge same-tag rows across files (dedupe by seed, first wins)
        def merged(tag):
            m = {}
            for (f, t, pol), seeds in arms.items():
                if pol == "heuristic_v10" and t == tag:
                    for s, r in seeds.items():
                        m.setdefault(s, r)
            return m
        report({tag_a: merged(tag_a), tag_b: merged(tag_b)},
               tag_a, tag_b, "won", "wins")
        report({tag_a: merged(tag_a), tag_b: merged(tag_b)},
               tag_a, tag_b, "ante1_death", "a1deaths")
