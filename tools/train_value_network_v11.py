"""tools/train_value_network_v11.py — Train Optilatro V11 Neural Value Network V_theta(s) -> P(Win).

Trains a 2-layer MLP (50 -> 32 -> 16 -> 1) on offline shop decisions and run outcomes.
Exports compact weights (W1, b1, W2, b2, W3, b3, normalization constants) to JSON
for microsecond-level inference in pure NumPy with zero runtime PyTorch dependencies.

Usage:
  python tools/train_value_network_v11.py [--epochs 1000] [--lr 0.005] [--output vendor/balatro-rl/balatro_sim/shop_model_v11.json]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
import numpy as np
import torch
import torch.nn as nn

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.fit_shop_model import build_interactions, auc


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default="tools/shop_dataset.jsonl")
    parser.add_argument("--epochs", type=int, default=1000)
    parser.add_argument("--lr", type=float, default=0.005)
    parser.add_argument("--weight-decay", type=float, default=1e-4)
    parser.add_argument("--output", default="vendor/balatro-rl/balatro_sim/shop_model_v11.json")
    args = parser.parse_args()

    ds_path = ROOT / args.dataset
    if not ds_path.exists():
        sys.exit(f"Dataset not found: {ds_path}")

    rows = []
    feat_order = None
    print(f"Loading dataset from {ds_path}...", flush=True)
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
        rows.append((row_f, float(row["won"])))

    if not rows:
        sys.exit("No rows in dataset")

    print(f"Loaded {len(rows)} samples with {len(feat_order)} features.", flush=True)

    X = np.array([[r[0][k] for k in feat_order] for r in rows], dtype=np.float32)
    y = np.array([r[1] for r in rows], dtype=np.float32)

    rng = np.random.default_rng(42)
    idx = rng.permutation(len(X))
    cut = int(len(X) * 0.8)
    tr, te = idx[:cut], idx[cut:]

    mu = X[tr].mean(axis=0)
    sd = X[tr].std(axis=0) + 1e-7
    X_norm = (X - mu) / sd

    X_tr = torch.from_numpy(X_norm[tr])
    y_tr = torch.from_numpy(y[tr]).unsqueeze(1)
    X_te = torch.from_numpy(X_norm[te])
    y_te = torch.from_numpy(y[te]).unsqueeze(1)

    torch.manual_seed(42)
    model = nn.Sequential(
        nn.Linear(X_tr.shape[1], 32),
        nn.ReLU(),
        nn.Linear(32, 16),
        nn.ReLU(),
        nn.Linear(16, 1)
    )

    opt = torch.optim.Adam(model.parameters(), lr=args.lr, weight_decay=args.weight_decay)
    crit = nn.BCEWithLogitsLoss()

    best_auc = 0.0
    best_weights = None

    print(f"Training MLP (50 -> 32 -> 16 -> 1) for {args.epochs} epochs...", flush=True)
    for epoch in range(args.epochs):
        model.train()
        opt.zero_grad()
        out = model(X_tr)
        loss = crit(out, y_tr)
        loss.backward()
        opt.step()

        if (epoch + 1) % 100 == 0:
            model.eval()
            with torch.no_grad():
                te_out = model(X_te)
                te_loss = crit(te_out, y_te).item()
                te_preds = torch.sigmoid(te_out).squeeze().cpu().numpy()
                te_auc = auc(y[te], te_preds)
                print(f"Epoch {epoch+1:4d} | Train Loss: {loss.item():.4f} | Val Loss: {te_loss:.4f} | Val AUC: {te_auc:.4f}", flush=True)

                if te_auc > best_auc:
                    best_auc = te_auc
                    best_weights = {
                        "W1": model[0].weight.detach().cpu().numpy().T.tolist(),
                        "b1": model[0].bias.detach().cpu().numpy().tolist(),
                        "W2": model[2].weight.detach().cpu().numpy().T.tolist(),
                        "b2": model[2].bias.detach().cpu().numpy().tolist(),
                        "W3": model[4].weight.detach().cpu().numpy().T.tolist(),
                        "b3": model[4].bias.detach().cpu().numpy().tolist(),
                    }

    print(f"\nTraining complete. Peak Validation AUC: {best_auc:.4f}")

    out_file = ROOT / args.output
    out_file.parent.mkdir(parents=True, exist_ok=True)
    export_data = {
        "model_type": "mlp_2layer",
        "feat_order": feat_order,
        "mean": mu.tolist(),
        "std": sd.tolist(),
        "weights": best_weights,
        "val_auc": float(best_auc),
    }

    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(export_data, f, indent=1)
    print(f"Exported trained value network to {out_file} (Size: {out_file.stat().st_size / 1024:.1f} KB)")


if __name__ == "__main__":
    main()
