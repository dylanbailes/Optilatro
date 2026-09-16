"""fit_buy_model.py — Fit the candidate-conditioned buy model + measure calibration.

INPUT   results/buy_rollouts/{train,holdout}[_TAG].jsonl  (from collect_shop_rollouts.py)
OUTPUT  vendor/balatro-rl/balatro_sim/buy_model.json  + printed calibration report

LABEL
  Primary binary label:  y = 1 if the forced buy flipped the run to a WIN
  that the skip fork did NOT get (label == +1). Rows with label == -1 (the
  buy LOST a win the skip secured) get weight 2.0 as class-0 examples —
  losing a secured win is worse than missing a marginal one.

MODEL
  Logistic regression on extract_buy_features + agent_v10.build_interactions
  (the interaction builder the runtime evaluator applies). Class weighting
  handles the heavy neutral imbalance; L2 keeps it honest.

CALIBRATION REPORT (the deliverable you asked for)
  1. Legacy `evaluate_shop_value` on the same decisions:
     - global AUC of legacy_dv against y
     - within-decision concordance: of pairs (candidate A beats candidate B)
       inside one shop, how often the higher-ΔV row actually has higher y?
       (random = 0.5; this is THE number that proves the old model cannot
       rank open-slot candidates)
  2. The fitted model: holdout AUC, PR-AUC (win rows are rare), and the same
     within-decision concordance.
  3. Reliability bins of the fitted P(win) on holdout.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
VENDOR = ROOT / "vendor" / "balatro-rl"
sys.path.insert(0, str(VENDOR))

from balatro_sim.agent_v10 import build_interactions  # noqa: E402
from balatro_sim.buy_model import (  # noqa: E402
    BUILD_VERSION, MODEL_PATH, load_buy_model)

OUT_DIR = ROOT / "results" / "buy_rollouts"


def load_rows(path: Path) -> list[dict]:
    rows = []
    if not path.exists():
        return rows
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def feat_matrix(rows: list[dict]):
    """Expand feats + build_interactions into a fixed column list."""
    dicts = [build_interactions(r["feats"]) for r in rows]
    cols: list[str] = []
    for d in dicts:
        for k in d:
            if k not in cols:
                cols.append(k)
    X = np.zeros((len(rows), len(cols)), dtype=np.float64)
    col_idx = {c: j for j, c in enumerate(cols)}
    for i, d in enumerate(dicts):
        for k, v in d.items():
            X[i, col_idx[k]] = float(v)
    return X, cols


def y_weight(rows: list[dict]):
    y = np.array([1.0 if r["label"] == 1 else 0.0 for r in rows])
    w = np.array([2.0 if r["label"] == -1 else 1.0 for r in rows])
    return y, w


def auc(y: np.ndarray, s: np.ndarray) -> float:
    pos = s[y == 1]
    neg = s[y == 0]
    if len(pos) == 0 or len(neg) == 0:
        return float("nan")
    order = np.argsort(s)
    ranks = np.empty(len(s), dtype=np.float64)
    ranks[order] = np.arange(1, len(s) + 1)
    # average ranks for ties
    s_sorted = s[order]
    i = 0
    while i < len(s_sorted):
        j = i
        while j + 1 < len(s_sorted) and s_sorted[j + 1] == s_sorted[i]:
            j += 1
        if j > i:
            ranks[order[i:j + 1]] = (i + 1 + j + 1) / 2.0
        i = j + 1
    rp = ranks[y == 1].sum()
    n_pos, n_neg = len(pos), len(neg)
    return float((rp - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg))


def within_decision_concordance(rows: list[dict], scores: np.ndarray) -> float:
    """Of candidate pairs inside one decision, how often does the higher
    score row have the better label? Label ordering: 1 > 0 > -1."""
    rank = {1: 2, 0: 1, -1: 0}
    by_dec: dict[str, list[int]] = {}
    for i, r in enumerate(rows):
        by_dec.setdefault(r["dec_id"], []).append(i)
    good = total = 0
    for idxs in by_dec.values():
        if len(idxs) < 2:
            continue
        for a in range(len(idxs)):
            for b in range(a + 1, len(idxs)):
                ia, ib = idxs[a], idxs[b]
                la, lb = rank[rows[ia]["label"]], rank[rows[ib]["label"]]
                if la == lb:
                    continue
                total += 1
                sa, sb = scores[ia], scores[ib]
                if (sa > sb and la > lb) or (sa < sb and la < lb):
                    good += 1
                elif sa == sb:
                    good += 0.5
    return (good / total) if total else float("nan")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", type=str, default="v1")
    ap.add_argument("--out", type=str, default=str(MODEL_PATH))
    ap.add_argument("--C", type=float, default=0.5)
    args = ap.parse_args()

    train = load_rows(OUT_DIR / f"train_{args.tag}.jsonl")
    hold = load_rows(OUT_DIR / f"holdout_{args.tag}.jsonl")
    if not train or not hold:
        print("missing dataset; run collect_shop_rollouts.py first")
        return

    print(f"train rows={len(train)}  holdout rows={len(hold)}")
    print(f"train label dist: +1={sum(r['label']==1 for r in train)} "
          f"0={sum(r['label']==0 for r in train)} "
          f"-1={sum(r['label']==-1 for r in train)}")
    print(f"holdout  label dist: +1={sum(r['label']==1 for r in hold)} "
          f"0={sum(r['label']==0 for r in hold)} "
          f"-1={sum(r['label']==-1 for r in hold)}")

    # ── 1. Legacy model calibration ─────────────────────────────────────
    for name, rows in (("train", train), ("holdout", hold)):
        s_leg = np.array([r["feats"].get("legacy_dv", 0.0) for r in rows])
        y, _ = y_weight(rows)
        print(f"[legacy evaluate_shop_value] {name}: "
              f"AUC(legacy_dv vs y)={auc(y, s_leg):.4f}  "
              f"concordance={within_decision_concordance(rows, s_leg):.4f}  "
              f"score_range=[{s_leg.min():.4f},{s_leg.max():.4f}]")

    # ── 2. Fit ──────────────────────────────────────────────────────────
    from sklearn.linear_model import LogisticRegression
    X_tr, cols = feat_matrix(train)
    y_tr, w_tr = y_weight(train)
    # 5-fold CV on train for an honest generalization read
    cv_auc = []
    from sklearn.model_selection import StratifiedKFold
    skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=7)
    for tr_i, va_i in skf.split(X_tr, y_tr):
        m = LogisticRegression(C=args.C, max_iter=2000, solver="liblinear")
        m.fit(X_tr[tr_i], y_tr[tr_i], sample_weight=w_tr[tr_i])
        p = m.predict_proba(X_tr[va_i])[:, 1]
        cv_auc.append(auc(y_tr[va_i], p))
    print(f"5-fold CV AUC on train: {np.mean(cv_auc):.4f} ± {np.std(cv_auc):.4f}")

    X_ho, _ = feat_matrix(hold)
    # align holdout columns to train cols
    X_ho_al = np.zeros((len(hold), len(cols)))
    ho_dicts = [build_interactions(r["feats"]) for r in hold]
    col_idx = {c: j for j, c in enumerate(cols)}
    for i, d in enumerate(ho_dicts):
        for k, v in d.items():
            X_ho_al[i, col_idx.get(k, 0)] = float(v)
    y_ho, w_ho = y_weight(hold)

    m = LogisticRegression(C=args.C, max_iter=2000, solver="liblinear")
    m.fit(X_tr, y_tr, sample_weight=w_tr)
    p_ho = m.predict_proba(X_ho_al)[:, 1]
    p_tr = m.predict_proba(X_tr)[:, 1]

    print(f"[fitted buy_model] train AUC={auc(y_tr, p_tr):.4f}  "
          f"holdout AUC={auc(y_ho, p_ho):.4f}")
    print(f"[fitted buy_model] holdout concordance="
          f"{within_decision_concordance(hold, p_ho):.4f} "
          f"(legacy: see above; random=0.5)")

    # legacy on the SAME holdout for the apples-to-apples print
    s_leg_ho = np.array([r["feats"].get("legacy_dv", 0.0) for r in hold])
    print(f"[legacy on holdout for comparison] AUC={auc(y_ho, s_leg_ho):.4f}")

    # ── 3. Reliability bins (holdout) ───────────────────────────────────
    bins = np.linspace(0, 1, 11)
    ids = np.digitize(p_ho, bins) - 1
    print("reliability (holdout): pred_bin  n  emp_win_rate")
    for b in range(10):
        mask = ids == b
        if mask.sum() >= 5:
            print(f"  {bins[b]:.1f}-{bins[b+1]:.1f}  {mask.sum():5d}  "
                  f"{y_ho[mask].mean():.4f}")

    # ── 3b. Threshold sweep (offline policy simulation) ────────────────
    # The runtime hook fires on the BEST candidate of a shop iff its fitted
    # P > threshold. Simulate that per holdout decision: firing on candidate
    # c yields signed outcome +1 / 0 / -1 (label). Sweep thresholds and report
    # net wins (gained - lost) and firing rate so the operating point can be
    # picked on holdout, not train.
    by_dec: dict[str, list[int]] = {}
    for i, r in enumerate(hold):
        by_dec.setdefault(r["dec_id"], []).append(i)
    print("threshold sweep (holdout, per-decision best-candidate firing):")
    print("  thr   fired  gained  lost   net   rate")
    best = (None, -1e9)
    # P(win-flip) has a ~3-6% base rate, so calibrated probabilities live
    # far below 0.5 — sweep the empirical range, not [0.5, 1].
    for thr in [0.02, 0.03, 0.05, 0.08, 0.10, 0.15, 0.20, 0.30, 0.50]:
        fired = gained = lost = 0
        for idxs in by_dec.values():
            cand = [(p_ho[i], hold[i]["label"]) for i in idxs]
            if not cand:
                continue
            p, lab = max(cand, key=lambda t: t[0])
            if p > thr:
                fired += 1
                if lab == 1:
                    gained += 1
                elif lab == -1:
                    lost += 1
        net = gained - lost
        rate = fired / max(1, len(by_dec))
        print(f"  {thr:.2f}  {fired:5d}  {gained:6d}  {lost:5d}  {net:+5d}  {rate:.3f}")
        if net > best[1]:
            best = (thr, net)
    print(f"  best operating point: thr={best[0]} net={best[1]:+d}")

    # ── 4. Weight file ─────────────────────────────────────────────────
    w = m.coef_[0].tolist()
    b = float(m.intercept_[0])
    # top coefficients by |w|
    order = sorted(range(len(cols)), key=lambda j: -abs(w[j]))
    print("top coefficients:")
    for j in order[:15]:
        print(f"  {cols[j]:24s} {w[j]:+.4f}")

    out = {
        "build_version": BUILD_VERSION,
        "feat_order": cols,
        "w": w,
        "bias": b,
        "C": args.C,
        "train_rows": len(train),
        "holdout_rows": len(hold),
        "holdout_auc": float(auc(y_ho, p_ho)),
        "cv_auc_mean": float(np.mean(cv_auc)),
        "n_win_rows": int(y_tr.sum()),
        "best_threshold": best[0],
        "best_threshold_net": best[1],
    }
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f)
    print(f"wrote {args.out}")

    # sanity: reload through the runtime loader
    meta, (names, ww, bb) = load_buy_model(args.out)
    ok = names is not None and len(names) == len(cols)
    print(f"runtime loader check: {'OK' if ok else 'FAILED'}")


if __name__ == "__main__":
    main()
