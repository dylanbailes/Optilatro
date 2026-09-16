"""tools/analyze_v11_regression.py — macro analysis of a paired V10/V11 bench.

Usage:
  python tools/analyze_v11_regression.py [path/to/paired.json] [--bank 10500-10799]

Reads the sidecar JSON written by bench/bench_agent_v10.py and reports
macro-patterns: death ante distribution, money held at death, loss/gain
clusters, econ deltas, and per-ante conversion rates. No per-seed
cherry-picking — aggregate only (per user steering).
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parent.parent


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _pair(data: dict, base: str, chal: str):
    b = {r["seed"]: r for r in data[base]["results"]}
    c = {r["seed"]: r for r in data[chal]["results"]}
    return b, c


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("path", nargs="?", default=str(
        ROOT / "vendor/balatro-rl/results/bench_10500_10799_paired.json"))
    ap.add_argument("--base", default="search_shop_v10")
    ap.add_argument("--chal", default="search_shop_v11")
    args = ap.parse_args()

    data = _load(Path(args.path))
    base, chal = args.base, args.chal
    b, c = _pair(data, base, chal)
    seeds = sorted(set(b) & set(c))
    print(f"bank {seeds[0]}..{seeds[-1]}  n={len(seeds)}  base={base}  chal={chal}")

    B = data[base]["aggregate"]
    C = data[chal]["aggregate"]
    for name, agg in ((base, B), (chal, C)):
        print(f"  {name:<18} wins {agg['wins']:>3} ({agg['win_rate']:5.2f}%) "
              f"a1d {agg['ante1_deaths']:>2} mean ante {agg['mean_ante']:.2f} "
              f"econ ${agg['mean_econ_source']:.1f} spent "
              f"${agg.get('mean_money_spent', mean(r['stats'].get('money_spent', 0) for r in data[name]['results'])):.1f}")

    both = [s for s in seeds if b[s]["won"] and c[s]["won"]]
    only_b = [s for s in seeds if b[s]["won"] and not c[s]["won"]]
    only_c = [s for s in seeds if c[s]["won"] and not b[s]["won"]]
    print(f"\nconcordant wins {len(both)} | {base}-only {len(only_b)} | {chal}-only {len(only_c)}")

    def dist(rs):
        d = Counter()
        for r in rs:
            d[9 if r["won"] else min(r["ante"], 8)] += 1
        return d

    db, dc = dist(b[s] for s in seeds), dist(c[s] for s in seeds)
    print("\nante reached (death bucket; 9=win)")
    print(f"  {'ante':>5} {base:>7} {chal:>7} {'delta':>7}")
    for a in range(1, 10):
        print(f"  {a:>5} {db.get(a,0):>7} {dc.get(a,0):>7} {dc.get(a,0)-db.get(a,0):>+7}")

    print(f"\nwhere {chal} died on the {len(only_b)} seeds {base} won")
    dd = Counter()
    money = []
    for s in only_b:
        r = c[s]
        dd[min(r["ante"], 8)] += 1
        money.append(r["dollars"])
    for a in sorted(dd):
        print(f"  ante {a}: {dd[a]}")
    print(f"  mean $ held at death: ${mean(money):.1f} "
          f"(base on those seeds: ${mean(b[s]['dollars'] for s in only_b):.1f})")

    print(f"\nwhere {base} died on the {len(only_c)} seeds {chal} won")
    dd = Counter()
    for s in only_c:
        dd[min(b[s]["ante"], 8)] += 1
    for a in sorted(dd):
        print(f"  ante {a}: {dd[a]}")

    # jokers held at death: systemic misbuild detection
    print(f"\ntop jokers held at death ({chal})")
    deaths = [c[s] for s in seeds if not c[s]["won"]]
    cnt = Counter()
    for r in deaths:
        for j in r.get("jokers", []):
            key = j[0] if isinstance(j, (list, tuple)) else str(j)
            cnt[key] += 1
    for k, n in cnt.most_common(15):
        frac = 100.0 * n / max(1, len(deaths))
        print(f"  {k:<24} {n:>4}  {frac:5.1f}% of deaths")

    print(f"\ntop jokers held at death ({base})")
    deaths_b = [b[s] for s in seeds if not b[s]["won"]]
    cnt = Counter()
    for r in deaths_b:
        for j in r.get("jokers", []):
            key = j[0] if isinstance(j, (list, tuple)) else str(j)
            cnt[key] += 1
    for k, n in cnt.most_common(15):
        frac = 100.0 * n / max(1, len(deaths_b))
        print(f"  {k:<24} {n:>4}  {frac:5.1f}% of deaths")

    # per-ante conversion: of runs that REACH ante a, how many win?
    def reached(rs, a):
        return sum(1 for r in rs if r["won"] or r["ante"] >= a)

    print("\nconversion by ante (runs reaching ante a that eventually win)")
    print(f"  {'ante':>5} {base:>18} {chal:>18}")
    for a in range(1, 9):
        rb = reached([b[s] for s in seeds], a)
        rc = reached([c[s] for s in seeds], a)
        wb = data[base]["aggregate"]["wins"]
        wc = data[chal]["aggregate"]["wins"]
        fb = 100.0 * wb / rb if rb else 0
        fc = 100.0 * wc / rc if rc else 0
        print(f"  {a:>5} {rb:>6} -> {fb:5.1f}%   {rc:>6} -> {fc:5.1f}%")

    # consumable / pack behavior
    def avg(rs, fn):
        vals = [fn(r) for r in rs]
        return mean(vals) if vals else 0.0

    print("\nbehavior averages")
    for name, rs in ((base, [b[s] for s in seeds]), (chal, [c[s] for s in seeds])):
        st = [r.get("stats") or {} for r in rs]
        print(f"  {name:<18} "
              f"spent ${avg(st, lambda x: x.get('money_spent',0)):6.1f} | "
              f"rerolls {avg(st, lambda x: x.get('rerolls',0)):5.1f} | "
              f"packs {avg(st, lambda x: x.get('packs_bought',0)):5.1f} | "
              f"jokers bought {avg(st, lambda x: len(x.get('jokers_bought',[]))):5.1f} | "
              f"sold {avg(st, lambda x: len(x.get('jokers_sold',[]))):5.1f} | "
              f"econ ${avg(st, lambda x: x.get('econ_source',0)):5.1f} | "
              f"interest ${avg(st, lambda x: x.get('interest_collected',0)):5.1f}")

    # wins: what do winning runs look like
    print("\nwinning-run profile")
    for name, rs in ((base, [b[s] for s in seeds]), (chal, [c[s] for s in seeds])):
        wins = [r for r in rs if r["won"]]
        st = [r.get("stats") or {} for r in wins]
        print(f"  {name:<18} n={len(wins):>3} "
              f"spent ${avg(st, lambda x: x.get('money_spent',0)):6.1f} | "
              f"best_score {avg(st, lambda x: x.get('best_score',0)):9.0f} | "
              f"econ ${avg(st, lambda x: x.get('econ_source',0)):5.1f} | "
              f"packs {avg(st, lambda x: x.get('packs_bought',0)):5.1f}")

    # deep-run deaths (ante>=6) money held
    print("\ndepth>=6 deaths: money held at death")
    for name, rs in ((base, [b[s] for s in seeds]), (chal, [c[s] for s in seeds])):
        deep = [r for r in rs if not r["won"] and r["ante"] >= 6]
        if deep:
            print(f"  {name:<18} n={len(deep):>3} mean ${mean(r['dollars'] for r in deep):6.1f} "
                  f"median ${sorted(r['dollars'] for r in deep)[len(deep)//2]}")


if __name__ == "__main__":
    main()
