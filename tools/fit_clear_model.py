"""tools/fit_clear_model.py — fit the logistic clear-model (numpy only).

Reads tools/clear_dataset.jsonl rows {y, f:{...}}, standardizes features,
fits L2 logistic regression by gradient descent, reports holdout
accuracy/AUC, and writes weights to balatro_sim/clear_model.json for
_v10_model_clear_prob() to load.

Usage:
  python tools/fit_clear_model.py [--dataset tools/clear_dataset.jsonl]
      [--epochs 4000] [--lr 0.3] [--l2 0.001]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent


def auc(y: np.ndarray, s: np.ndarray) -> float:
    order = np.argsort(s)
    ranks = np.empty(len(s), dtype=float)
    ranks[order] = np.arange(1, len(s) + 1)
    pos = y == 1
    n_pos = pos.sum()
    n_neg = len(y) - n_pos
    if n_pos == 0 or n_neg == 0:
        return 0.5
    return (ranks[pos].sum() - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", default="tools/clear_dataset.jsonl")
    ap.add_argument("--epochs", type=int, default=6000)
    ap.add_argument("--lr", type=float, default=0.3)
    ap.add_argument("--l2", type=float, default=0.001)
    args = ap.parse_args()

    rows = []
    feat_order = None
    for line in open(ROOT / args.dataset, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("y") is None:
            continue
        if feat_order is None:
            feat_order = sorted(row["f"].keys())
        rows.append(row)
    if not rows:
        sys.exit("no rows")

    X = np.array([[row["f"][k] for k in feat_order] for row in rows],
                 dtype=float)
    y = np.array([row["y"] for row in rows], dtype=float)

    rng = np.random.default_rng(0)
    idx = rng.permutation(len(X))
    cut = int(len(X) * 0.75)
    tr, te = idx[:cut], idx[cut:]
    mu = X[tr].mean(axis=0)
    sd = X[tr].std(axis=0) + 1e-9
    Z = (X - mu) / sd
    Zt = np.hstack([Z, np.ones((len(Z), 1))])

    w = np.zeros(Z.shape[1] + 1)
    for epoch in range(args.epochs):
        p = 1.0 / (1.0 + np.exp(-np.clip(Zt[tr] @ w, -30, 30)))
        grad = Zt[tr].T @ (p - y[tr]) / len(tr)
        grad[:-1] += args.l2 * w[:-1]
        w -= args.lr * grad
        if epoch % 1000 == 0:
            loss = -np.mean(y[tr] * np.log(p + 1e-9)
                            + (1 - y[tr]) * np.log(1 - p + 1e-9))
            print(f"epoch {epoch} loss {loss:.4f}", flush=True)

    def metrics(mask):
        p = 1.0 / (1.0 + np.exp(-np.clip(Zt[mask] @ w, -30, 30)))
        acc = ((p >= 0.5).astype(float) == y[mask]).mean()
        return acc, auc(y[mask], p)

    tr_acc, tr_auc = metrics(tr)
    te_acc, te_auc = metrics(te)
    print(f"train acc {tr_acc:.3f} auc {tr_auc:.3f} | "
          f"holdout acc {te_acc:.3f} auc {te_auc:.3f}")

    out = {
        "features": feat_order,
        "mean": mu.tolist(),
        "std": sd.tolist(),
        "w": w[:-1].tolist(),
        "b": float(w[-1]),
    }
    dest = ROOT / "vendor" / "balatro-rl" / "balatro_sim" / "clear_model.json"
    dest.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"wrote {dest}")


if __name__ == "__main__":
    main()
