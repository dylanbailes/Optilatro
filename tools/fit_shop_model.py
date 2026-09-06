"""tools/fit_shop_model.py — Fit shop value function V(s) -> P(Win).

Reads tools/shop_dataset.jsonl, computes portfolio features + critical non-linear
interaction terms (e.g. chips * mult, mult * xmult, ante * zero_xmult_penalty),
standardizes features, and fits an L2-regularized logistic model.
Outputs weights to vendor/balatro-rl/balatro_sim/shop_model.json for SearchShopV10.

Usage:
  python tools/fit_shop_model.py [--dataset tools/shop_dataset.jsonl] [--epochs 5000]
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


def build_interactions(f: dict[str, float]) -> dict[str, float]:
    """Add explicit domain interaction terms representing Balatro mechanics."""
    res = dict(f)
    ante = f.get("ante", 1.0)
    n_chips = f.get("n_chips", 0.0)
    n_flat = f.get("n_flat_mult", 0.0)
    n_xmult = f.get("n_xmult", 0.0)
    n_scaling = f.get("n_scaling", 0.0)
    n_econ = f.get("n_econ", 0.0)

    # Multiplicative scoring synergy
    res["inter_chips_mult"] = n_chips * (n_flat + n_scaling)
    res["inter_mult_xmult"] = (n_flat + n_scaling) * n_xmult
    res["inter_chips_xmult"] = n_chips * n_xmult
    res["inter_ante_xmult"] = ante * n_xmult
    res["inter_late_econ_penalty"] = max(0.0, ante - 3.0) * n_econ
    res["early_econ"] = n_econ if ante <= 3.0 else 0.0
    res["late_econ"] = n_econ if ante >= 4.0 else 0.0
    res["inter_late_zero_xmult"] = (1.0 if (ante >= 4.0 and n_xmult == 0.0) else 0.0)
    return res


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default="tools/shop_dataset.jsonl")
    parser.add_argument("--epochs", type=int, default=5000)
    parser.add_argument("--lr", type=float, default=0.2)
    parser.add_argument("--l2", type=float, default=0.005)
    parser.add_argument("--output", default="vendor/balatro-rl/balatro_sim/shop_model.json")
    args = parser.parse_args()

    ds_path = ROOT / args.dataset
    if not ds_path.exists():
        sys.exit(f"Dataset not found: {ds_path}")

    rows = []
    feat_order = None
    for line in open(ds_path, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        row_f = build_interactions(row["f"])
        if feat_order is None:
            feat_order = sorted(row_f.keys())
        rows.append((row_f, row["won"]))

    if not rows:
        sys.exit("No rows in dataset")

    print(f"Loaded {len(rows)} samples with {len(feat_order)} features.", flush=True)

    X = np.array([[r[0][k] for k in feat_order] for r in rows], dtype=float)
    y = np.array([r[1] for r in rows], dtype=float)

    print(f"Positive win rate in dataset: {y.mean()*100:.2f}%", flush=True)

    rng = np.random.default_rng(42)
    idx = rng.permutation(len(X))
    cut = int(len(X) * 0.8)
    tr, te = idx[:cut], idx[cut:]

    mu = X[tr].mean(axis=0)
    sd = X[tr].std(axis=0) + 1e-9
    Z = (X - mu) / sd
    Zt = np.hstack([Z, np.ones((len(Z), 1))])

    w = np.zeros(Zt.shape[1])
    # Bias initialization to prior log-odds
    prior = np.clip(y[tr].mean(), 1e-4, 1.0 - 1e-4)
    w[-1] = np.log(prior / (1.0 - prior))

    best_loss = 1e9
    for epoch in range(args.epochs):
        logits = np.clip(Zt[tr] @ w, -30, 30)
        p = 1.0 / (1.0 + np.exp(-logits))
        grad = Zt[tr].T @ (p - y[tr]) / len(tr)
        grad[:-1] += args.l2 * w[:-1]
        w -= args.lr * grad

        if (epoch + 1) % 500 == 0:
            loss = -np.mean(y[tr] * np.log(p + 1e-12) + (1.0 - y[tr]) * np.log(1.0 - p + 1e-12))
            te_logits = np.clip(Zt[te] @ w, -30, 30)
            te_p = 1.0 / (1.0 + np.exp(-te_logits))
            te_auc = auc(y[te], te_p)
            print(f"Epoch {epoch+1:5d} | Train Loss: {loss:.4f} | Test AUC: {te_auc:.4f}", flush=True)

    # Final holdout evaluation
    te_logits = np.clip(Zt[te] @ w, -30, 30)
    te_p = 1.0 / (1.0 + np.exp(-te_logits))
    final_auc = auc(y[te], te_p)
    print(f"\nFinal Test AUC: {final_auc:.4f}")

    print("\nTop 10 Positive Features:")
    feat_weights = [(feat_order[i], w[i]) for i in range(len(feat_order))]
    feat_weights.sort(key=lambda x: x[1], reverse=True)
    for name, weight in feat_weights[:10]:
        print(f"  {name:30s}: {weight:+.4f}")

    print("\nTop 10 Negative Features:")
    for name, weight in feat_weights[-10:]:
        print(f"  {name:30s}: {weight:+.4f}")
    print(f"  {'[bias]':30s}: {w[-1]:+.4f}\n")

    out_file = ROOT / args.output
    out_file.parent.mkdir(parents=True, exist_ok=True)
    model_data = {
        "feat_order": feat_order,
        "mean": mu.tolist(),
        "std": sd.tolist(),
        "w": w.tolist(),
        "bias": float(w[-1]),
        "test_auc": float(final_auc),
    }
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(model_data, f, indent=1)
    print(f"Saved shop value model to {out_file}")


if __name__ == "__main__":
    main()
