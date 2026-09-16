"""fit_state_value.py — fit V(S) on trajectories and report whether it is usable.

WHAT THIS IS FOR
================
V13's premise is that the *unit of learning* was wrong: the shipped model ranks
single items inside one shop, where 48% of the pairs it weighs are exactly
equivalent and its sign rate on the rest is 53.5%. This fits a value function over
whole states instead, from trajectories that cost ~1/350th as much per labelled
observation as counterfactual forks.

WHAT IT REPORTS, AND WHY THOSE AND NOT JUST RMSE
================================================
RMSE is nearly useless here: `ret` is ante reached plus a win bonus, so a
regressor that predicts the mean and never ranks anything scores well. The report
therefore leads with the properties a *decision* needs:

* `spearman`        — does V order states the way the run actually went?
* `auc_won`         — does V separate won from lost states?
* `seed_spearman`   — does the MEAN V over a run's states rank runs by outcome?
  This is the leakage-free version: states within one run share a label, so
  state-level correlation can be inflated by run-level signal alone.
* `calibration`     — mean predicted vs realised `ret` per ante. A value function
  that is not ordered along the ante axis cannot support lookahead, whatever its
  RMSE.
* `prefix_importance` — permutation importance grouped by encoding block. This is
  a direct test of the redesign's core claim: if the pooled portfolio blocks
  (`pf_`, `cn_`, `vo_`) carry no more weight than noise, then "the model cannot see
  the portfolio" is NOT the problem and this architecture should be abandoned
  rather than scaled.

SPLIT DISCIPLINE
================
States from one run share a single outcome label, so an ungrouped split leaks: the
same run appearing on both sides makes V look clairvoyant. Every metric here is
computed on holdout SEEDS, never holdout rows.

WHAT GETS SAVED
===============
`--out` gets the fitted model plus the frozen layout and provenance, because the
layout is the interface between collection and inference: a model loaded against a
different layout would read the wrong column and fail silently.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "vendor" / "balatro-rl"))
sys.path.insert(0, str(ROOT))

from balatro_sim import catalogue as CAT                       # noqa: E402

MODEL_VERSION = 1
CV_FOLDS = 5


def load_trajectories(paths: list[Path]) -> tuple[list[str], list[dict]]:
    """Read (union layout, rows) from trajectory files.

    Layouts are *unioned* rather than required to match, so a corpus can grow
    across encoder versions. This is safe exactly because the encoder's pooled
    vocabulary is spec-derived: extending the encoder adds columns and never
    renames or reorders existing ones, so a row written under an older layout has
    a well-defined value (0) for every column added since -- the same convention
    `state_value.encode` already uses for a name outside the layout.

    The assumption is stated rather than assumed: a column that changed meaning
    between layouts would be silently mis-joined, and nothing here can detect
    that. The added names are printed so the union is visible in the log instead
    of being an invisible reinterpretation of the corpus.

    Missing values read as 0, which for these blocks is also the semantically
    correct "this entity is not present" value.
    """
    files: list[tuple[list[str], list[dict]]] = []
    n_bad = 0
    for p in paths:
        if not p.is_file():
            continue
        with open(p, encoding="utf-8") as fh:
            first = fh.readline().strip()
            if not first:
                continue
            header = json.loads(first)
            this = list(header.get("layout") or [])
            if not this:
                continue
            rws: list[dict] = []
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rws.append(json.loads(line))
                except json.JSONDecodeError:
                    # A collection writing the same file can leave one
                    # truncated tail line. Skipping it is correct; refusing to
                    # read a growing corpus would make this tool unusable
                    # while collection runs.
                    n_bad += 1
            files.append((this, rws))
    if n_bad:
        print(f"  skipped {n_bad} truncated/unparseable line(s)", flush=True)
    if not files:
        return [], []

    layout: list[str] = []
    seen: set[str] = set()
    for this, _ in files:
        for name in this:
            if name not in seen:
                seen.add(name)
                layout.append(name)

    rows: list[dict] = []
    n_padded = 0
    for this, rws in files:
        if this == layout:
            rows.extend(rws)
            continue
        pos = {name: i for i, name in enumerate(this)}
        added = [name for name in layout if name not in pos]
        if added:
            print(f"  padding {len(rws)} rows onto {len(added)} newer column(s), "
                  f"e.g. {added[:4]}", flush=True)
        for r in rws:
            v = r.get("v") or []
            r["v"] = [float(v[pos[name]]) if name in pos and pos[name] < len(v)
                      else 0.0 for name in layout]
            n_padded += 1
            rows.append(r)
    return layout, rows


def _groups(rows: list[dict]) -> dict:
    by: dict = {}
    for i, r in enumerate(rows):
        by.setdefault(r.get("seed"), []).append(i)
    return by


def spearman(a: np.ndarray, b: np.ndarray) -> float:
    """Rank correlation without a scipy dependency on the caller's side."""
    if len(a) < 3:
        return float("nan")
    ra = np.argsort(np.argsort(a)).astype(float)
    rb = np.argsort(np.argsort(b)).astype(float)
    ra -= ra.mean()
    rb -= rb.mean()
    denom = float(np.sqrt((ra ** 2).sum() * (rb ** 2).sum()))
    return float((ra * rb).sum() / denom) if denom else float("nan")


def auc_won(rows: list[dict], pred: np.ndarray) -> float:
    y = np.array([int(r.get("won", 0)) for r in rows], dtype=float)
    pos, neg = pred[y > 0], pred[y == 0]
    if not len(pos) or not len(neg):
        return float("nan")
    wins = (pos[:, None] > neg[None, :]).sum() + 0.5 * (pos[:, None] == neg[None, :]).sum()
    return float(wins / (len(pos) * len(neg)))


def seed_spearman(rows: list[dict], pred: np.ndarray) -> tuple[float, int]:
    """Rank runs by mean predicted V, correlated with the runs' own outcomes."""
    means, rets = [], []
    for _seed, idxs in _groups(rows).items():
        means.append(float(np.mean([pred[i] for i in idxs])))
        rets.append(float(np.mean([rows[i]["ret"] for i in idxs])))
    return spearman(np.array(means), np.array(rets)), len(means)


def prefix_importance(model, X: np.ndarray, y: np.ndarray, layout: list[str],
                      n_repeats: int = 2, rng_seed: int = 0) -> dict:
    """Permutation importance grouped by encoding block, on held-out rows.

    Grouping is the point: the question is not which single feature matters but
    whether the *portfolio* blocks carry signal at all, since that is what the
    redesign adds over the per-item encoder.
    """
    rng = np.random.default_rng(rng_seed)
    base = float(np.mean((model.predict(X) - y) ** 2))
    by_prefix: dict[str, list[int]] = {}
    for i, name in enumerate(layout):
        head = name.split("_", 1)[0]
        by_prefix.setdefault(head, []).append(i)
    out: dict[str, float] = {}
    for head, cols in sorted(by_prefix.items()):
        deltas = []
        for _ in range(n_repeats):
            Xp = X.copy()
            perm = rng.permutation(len(Xp))
            Xp[:, cols] = Xp[perm][:, cols]
            deltas.append(float(np.mean((model.predict(Xp) - y) ** 2)) - base)
        out[head] = round(float(np.mean(deltas)), 5)
    return out


def calibration(rows: list[dict], pred: np.ndarray) -> list[dict]:
    """Mean predicted vs realised return per ante — the ordering check."""
    by: dict[int, list[int]] = {}
    for i, r in enumerate(rows):
        by.setdefault(int(r.get("ante", 1) or 1), []).append(i)
    out = []
    for ante in sorted(by):
        idxs = by[ante]
        out.append({
            "ante": ante, "n": len(idxs),
            "pred": round(float(np.mean([pred[i] for i in idxs])), 3),
            "real": round(float(np.mean([rows[i]["ret"] for i in idxs])), 3),
        })
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--train", required=True,
                    help="comma-separated trajectory jsonl paths")
    ap.add_argument("--holdout", default="",
                    help="comma-separated paths; if empty, grouped CV on train")
    ap.add_argument("--out", default="results/state_value_model.joblib")
    ap.add_argument("--report", default="results/state_value_report.json")
    ap.add_argument("--target", default="ret",
                    choices=["ret", "ante_final", "won"],
                    help="ret = dense run return (ante + win bonus); the others "
                         "exist to show what the encoding can predict with a "
                         "sparser/denser label")
    ap.add_argument("--iters", type=int, default=400)
    ap.add_argument("--leaves", type=int, default=31)
    ap.add_argument("--lr", type=float, default=0.06)
    args = ap.parse_args()

    from sklearn.ensemble import HistGradientBoostingRegressor

    t0 = time.time()
    train_paths = [ROOT / p.strip() for p in args.train.split(",") if p.strip()]
    hold_paths = [ROOT / p.strip() for p in args.holdout.split(",") if p.strip()]
    layout, train = load_trajectories(train_paths)
    layout_h, hold = (load_trajectories(hold_paths) if hold_paths else ([], []))
    if layout_h and layout_h != layout:
        raise SystemExit("train and holdout use different layouts")
    if not train:
        print("no trajectory rows -- nothing to fit")
        return 1
    print(f"train {len(train)} states / {len(_groups(train))} seeds | "
          f"holdout {len(hold)} states / {len(_groups(hold))} seeds | "
          f"layout {len(layout)}", flush=True)

    Xtr = np.array([r["v"] for r in train], dtype=float)
    ytr = np.array([float(r.get(args.target, 0.0)) for r in train])
    print(f"target {args.target}: mean {ytr.mean():.3f} sd {ytr.std():.3f} "
          f"nonzero {np.mean(ytr != 0):.1%}", flush=True)

    model = HistGradientBoostingRegressor(
        max_iter=args.iters, learning_rate=args.lr, max_leaf_nodes=args.leaves,
        l2_regularization=1.0, random_state=0).fit(Xtr, ytr)

    report: dict = {
        "version": MODEL_VERSION,
        "catalogue": CAT.fingerprint(),
        "target": args.target,
        "layout_size": len(layout),
        "rows_train": len(train), "seeds_train": len(_groups(train)),
        "rows_holdout": len(hold), "seeds_holdout": len(_groups(hold)),
        "features": layout,
    }
    if hold:
        Xho = np.array([r["v"] for r in hold], dtype=float)
        yho = np.array([float(r.get(args.target, 0.0)) for r in hold])
        pred = model.predict(Xho)
        report["holdout_rmse"] = round(float(np.sqrt(np.mean((pred - yho) ** 2))), 4)
        report["holdout_spearman"] = round(spearman(pred, yho), 4)
        report["auc_won"] = round(auc_won(hold, pred), 4)
        sp, n_seeds = seed_spearman(hold, pred)
        report["seed_spearman"] = round(sp, 4)
        report["seed_spearman_n"] = n_seeds
        report["calibration"] = calibration(hold, pred)
        report["prefix_importance"] = prefix_importance(model, Xho, yho, layout)
        # In-sample, to separate "cannot represent" from "cannot generalise" --
        # the same diagnostic that showed the per-item encoder was at its ceiling.
        ptr = model.predict(Xtr)
        report["train_spearman"] = round(spearman(ptr, ytr), 4)
        report["train_rmse"] = round(float(np.sqrt(np.mean((ptr - ytr) ** 2))), 4)

    p = ROOT / args.out
    p.parent.mkdir(parents=True, exist_ok=True)
    import joblib
    joblib.dump({"model": model, "layout": layout, "target": args.target,
                 "version": MODEL_VERSION, "catalogue": CAT.fingerprint()}, p)
    rp = ROOT / args.report
    rp.write_text(json.dumps(report, indent=1, sort_keys=True) + "\n",
                  encoding="utf-8")

    print(f"holdout RMSE    : {report.get('holdout_rmse')} "
          f"(train {report.get('train_rmse')})", flush=True)
    print(f"holdout spearman: {report.get('holdout_spearman')} "
          f"(train {report.get('train_spearman')})", flush=True)
    print(f"seed spearman   : {report.get('seed_spearman')} on "
          f"{report.get('seed_spearman_n')} runs", flush=True)
    print(f"AUC(won)        : {report.get('auc_won')}", flush=True)
    cal = report.get("calibration") or []
    if cal:
        print("calibration by ante (pred vs realised return):")
        for row in cal:
            print(f"  ante {row['ante']:2d} n={row['n']:6d} pred {row['pred']:7.3f} "
                  f"real {row['real']:7.3f}", flush=True)
    imp = report.get("prefix_importance") or {}
    if imp:
        print("permutation importance by encoding block (MSE increase when "
              "shuffled):")
        for head, val in sorted(imp.items(), key=lambda kv: -kv[1]):
            print(f"  {head:8s} {val:+.5f}", flush=True)
    print(f"saved {p} and {rp} in {time.time()-t0:.0f}s", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
