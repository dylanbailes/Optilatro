"""tools/gen_synergy_tree.py — mine the empirical synergy tree from telemetry.

Reads per-run telemetry JSON written by `bench/bench_v9.py --telemetry-dir`
(each file = one rollout outcome + the observation-only `stats` telemetry:
`co_owned` scored-hand loadouts, `consumable_uses` with targeted-card
features, `jokers_sold`) and learns weighted edges into a JSON tree:

  joker↔joker        — co-ownership at scored hands; the pair's mean-ante and
                       win-rate lift vs EITHER single (the core "works
                       together" signal). Support floor (--min-support).
  joker↔consumable   — consumables used while the joker was owned, with the
                       run's mean ante / win rate (joker↔consumable benefit).
  joker↔hand         — hand types scored while the joker was owned (empirical
                       activation: n, mean score, share of the joker's hands).
  joker↔card         — features (rank/suit/enhancement) of tarot-targeted
                       cards while the joker was owned (what builds enhance).

Determinism: sorted iteration everywhere — same corpus → byte-identical tree.

Usage:
  .venv/Scripts/python.exe bench/bench_v9.py --games 300 --telemetry-dir \\
      vendor/balatro-rl/results/telemetry
  .venv/Scripts/python.exe tools/gen_synergy_tree.py \\
      --in vendor/balatro-rl/results/telemetry --out tools/synergy_tree.json

Hyperparameters (tune the noise floor):
  --min-support N   minimum runs behind an edge (raise for a larger corpus)
  --min-lift L      drop joker-joker / joker-consumable edges with
                    |ante lift| < L — only high-confidence edges survive
  --policy P        mine only P's runs (per-policy tree; the agent loads it
                    via bench_v9.py --per-policy-trees or --synergy-tree)
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean
from typing import Optional

#: Minimum runs with both jokers owned for a joker↔joker edge to be stored
#: (and similarly for joker↔consumable edges).
DEFAULT_MIN_SUPPORT = 3


def _load_runs(telemetry_dir: Path, policy: Optional[str] = None) -> list[dict]:
    """All run telemetry files under the dir (recursively — bench writes one
    subdir per policy). With `policy`, only that policy's runs (matches the
    policy subdir name, which is the run files' parent for both the flat and
    the grouped-corpus layouts)."""
    runs = []
    for p in sorted(telemetry_dir.rglob("run_*.json")):
        if policy is not None and p.parts[-2] != policy:
            continue
        try:
            runs.append(json.loads(p.read_text(encoding="utf-8")))
        except Exception as e:
            print(f"  ! skipping {p}: {e}")
    return runs


def mine(runs: list[dict], min_support: int = DEFAULT_MIN_SUPPORT,
         min_lift: float = 0.0) -> dict:
    """Build the synergy tree from the corpus. Deterministic.

    min_support: hard floor on the number of runs behind an edge.
    min_lift: noise gate — joker↔joker and joker↔consumable edges with
        |ante lift| below this are dropped entirely (only high-confidence
        edges enter the agent's prior).
    """

    def stats_of(r: dict) -> dict:
        return r.get("stats") or {}

    n_runs = len(runs)
    base_wins = sum(1 for r in runs if r.get("won"))
    base_ante = mean(r.get("ante", 1) for r in runs)

    # Per-run owned joker sets (union across scored hands) + run outcomes
    run_owned: list[set] = []
    run_outcome: list[tuple[bool, int]] = []  # (won, ante)
    singles: dict[str, list] = defaultdict(list)      # key -> [(won, ante)]
    for r in runs:
        st = stats_of(r)
        owned = {j for *_ , jkeys, _ in (st.get("co_owned") or []) for j in jkeys}
        run_owned.append(owned)
        out = (bool(r.get("won")), int(r.get("ante", 1)))
        run_outcome.append(out)
        for j in owned:
            singles[j].append(out)

    # ── joker↔joker: pair benefit vs the better single ─────────────────────
    pairs: dict[tuple[str, str], list] = defaultdict(list)
    for owned, out in zip(run_owned, run_outcome):
        for pair in sorted(set((a, b) for a in owned for b in owned if a < b)):
            pairs[pair].append(out)

    jj = {}
    for (a, b), outs in sorted(pairs.items()):
        if len(outs) < min_support:
            continue
        n_both = len(outs)
        # EXCLUSIVE singles: runs owning one but not the other — the honest
        # baseline for "does the pair beat either alone?".
        a_only = [o for owned, o in zip(run_owned, run_outcome)
                  if a in owned and b not in owned]
        b_only = [o for owned, o in zip(run_owned, run_outcome)
                  if b in owned and a not in owned]
        ma = mean(o[1] for o in a_only) if a_only else 0.0
        mb = mean(o[1] for o in b_only) if b_only else 0.0
        wa = sum(o[0] for o in a_only) / len(a_only) if a_only else 0.0
        wb = sum(o[0] for o in b_only) / len(b_only) if b_only else 0.0
        m_both = mean(o[1] for o in outs)
        w_both = sum(o[0] for o in outs) / n_both
        lift_ante = m_both - max(ma, mb)
        win_lift = w_both - max(wa, wb)
        if (lift_ante == 0.0 and win_lift == 0.0) or abs(lift_ante) < min_lift:
            continue
        jj.setdefault(a, {})[b] = {
            "n": n_both, "mean_ante": round(m_both, 3),
            "win_rate": round(w_both, 3),
            "lift_ante": round(lift_ante, 3),
            "win_lift": round(win_lift, 3),
        }

    # ── joker↔consumable: used while owned → run outcome ───────────────────
    jc: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    run_used: list[set] = []  # consumable keys used per run
    for r, out in zip(runs, run_outcome):
        uses = stats_of(r).get("consumable_uses") or []
        run_used.append({key for _, key, _j, _t in uses})
        for _, key, jkeys, _targets in uses:
            for j in jkeys:
                jc[j][key].append(out)
    jc_out = {}
    for j, cons in sorted(jc.items()):
        jc_out[j] = {}
        for c, outs in sorted(cons.items()):
            if len(outs) < min_support:
                continue
            # EXCLUSIVE baseline: runs owning j WITHOUT ever using c — the
            # honest "given you own j, does using c predict better outcomes
            # than not?" comparison. Within-corpus, so policy mix affects
            # numerator and denominator equally (no global-base confounding).
            base_outs = [o for owned, used, o
                         in zip(run_owned, run_used, run_outcome)
                         if j in owned and c not in used]
            if base_outs:
                base_ante = mean(o[1] for o in base_outs)
                base_win = sum(o[0] for o in base_outs) / len(base_outs)
            else:
                base_ante, base_win = base_ante, base_wins / n_runs
            lift_ante = mean(o[1] for o in outs) - base_ante
            if abs(lift_ante) < min_lift:
                continue
            jc_out[j][c] = {
                "n": len(outs),
                "mean_ante": round(mean(o[1] for o in outs), 3),
                "win_rate": round(sum(o[0] for o in outs) / len(outs), 3),
                "base_mean_ante": round(base_ante, 3),
                "base_win_rate": round(base_win, 3),
                "lift_ante": round(lift_ante, 3),
            }

    # ── joker↔hand: scored-hand activation ─────────────────────────────────
    jh: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    for r in runs:
        for _, ht, jkeys, score in (stats_of(r).get("co_owned") or []):
            for j in jkeys:
                jh[j][ht].append(score)
    jh_out = {}
    for j, hands in sorted(jh.items()):
        total = sum(len(v) for v in hands.values())
        jh_out[j] = {
            ht: {"n": len(scores), "mean_score": int(mean(scores)),
                 "share": round(len(scores) / total, 3)}
            for ht, scores in sorted(hands.items())
        }

    # ── joker↔card: tarot-target features while owned ──────────────────────
    jcard: dict[str, Counter] = defaultdict(Counter)
    for r in runs:
        for _, _key, jkeys, targets in (stats_of(r).get("consumable_uses") or []):
            for j in jkeys:
                for t in targets or []:
                    if t.get("rank"):
                        jcard[j][f"rank_{t['rank']}"] += 1
                    if t.get("suit"):
                        jcard[j][f"suit_{t['suit']}"] += 1
                    if t.get("enh") and t["enh"] != "None":
                        jcard[j][f"enh_{t['enh']}"] += 1
    jcard_out = {j: dict(c.most_common()) for j, c in sorted(jcard.items())}

    return {
        "meta": {
            "runs": n_runs,
            "win_rate": round(base_wins / n_runs, 4) if n_runs else 0.0,
            "mean_ante": round(base_ante, 3) if n_runs else 0.0,
            "min_support": min_support,
        },
        "joker_joker": jj,
        "joker_consumable": jc_out,
        "joker_hand": jh_out,
        "joker_card": jcard_out,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="telemetry_dir", required=True,
                    help="bench telemetry dir (bench_v9.py --telemetry-dir)")
    ap.add_argument("--out", default="tools/synergy_tree.json")
    ap.add_argument("--min-support", type=int, default=DEFAULT_MIN_SUPPORT)
    ap.add_argument("--min-lift", type=float, default=0.0,
                    help="drop joker-joker and joker-consumable edges whose "
                         "|ante lift| is below this (noise gate)")
    ap.add_argument("--policy", default=None,
                    help="mine only this policy's runs (per-policy tree, e.g. "
                         "--policy heuristic_v9 --out "
                         "tools/synergy_tree_heuristic_v9.json)")
    args = ap.parse_args()

    tel = Path(args.telemetry_dir)
    runs = _load_runs(tel, args.policy)
    if not runs:
        raise SystemExit(f"no run_*.json telemetry under {tel}"
                         + (f" for policy {args.policy}" if args.policy else ""))
    print(f"mining {len(runs)} runs from {tel} (min-support "
          f"{args.min_support}, min-lift {args.min_lift}"
          + (f", policy {args.policy})" if args.policy else ")"))
    tree = mine(runs, min_support=args.min_support, min_lift=args.min_lift)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(tree, indent=1, sort_keys=True), encoding="utf-8")
    n_edges = sum(len(v) for v in tree["joker_joker"].values())
    n_cons = sum(len(v) for v in tree["joker_consumable"].values())
    n_hand = sum(len(v) for v in tree["joker_hand"].values())
    n_card = sum(len(v) for v in tree["joker_card"].values())
    print(f"wrote {out}: joker_joker {n_edges} edges, joker_consumable "
          f"{n_cons}, joker_hand {n_hand}, joker_card {n_card} "
          f"(base win {tree['meta']['win_rate']:.1%}, "
          f"mean ante {tree['meta']['mean_ante']:.2f})")


if __name__ == "__main__":
    main()
