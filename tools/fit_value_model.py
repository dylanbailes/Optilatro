"""fit_value_model.py — fit the two-level value model on counterfactual rows.

MODEL
=====
    V(features) = linear_head(features) + shrunk_residual(cell)

  linear_head  : ridge regression over the spec+scenario feature layout
                 (value_tables.FEATURE_ORDER), standardised on train. This is
                 what generalises: a joker never offered in the data still gets
                 a sensible value from its spec features and the scenario.
  residual     : per-cell mean of the head's out-of-fold error, shrunk toward
                 the cell's parent by `(n*mean + tau*parent)/(n + tau)` up the
                 hierarchy item|ante|support -> item|ante -> item -> role.
                 This is what captures idiosyncrasy (a joker that is bad *here*
                 despite looking fine in general).

EVERY FREE PARAMETER IS FITTED
==============================
  * ridge alpha  -> chosen by grouped cross-validation (folds split BY SEED, so
                    the same run never appears in train and validation)
  * tau          -> chosen by holdout error over a log-spaced grid derived from
                    the observed cell counts, not a hand-picked weight
  * coefficients -> least squares
Nothing in the resulting artifact is a human-typed tuning constant, which is
what `tools/audit_magic_numbers.py` enforces for the code side.

WHAT IT REPORTS
===============
The headline number is not AUC — it is **within-decision concordance**: given
two candidates offered in the SAME decision, does the model rank the one that
actually produced the better run higher? That is precisely the job the old
`evaluate_shop_value` failed (measured on these rows, its ΔV ranked worse than
a coin flip), because it scored post-buy *states* rather than candidates.

The legacy model's concordance is computed on the identical row set, so the
comparison is apples-to-apples rather than a claim.

USAGE
=====
    python tools/fit_value_model.py \
        --train results/decisions/train_v1.jsonl \
        --holdout results/decisions/holdout_v1.jsonl \
        --out vendor/balatro-rl/balatro_sim/value_tables.json
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "vendor" / "balatro-rl"))

from balatro_sim import catalogue as CAT              # noqa: E402
from balatro_sim import value_tables as VT            # noqa: E402

# The near-tie window whose PERMISSION the intervention test conditions on.
# This must match the arm under study -- it is `v12_prior_m02`'s
# `v12_prior_margin`, the best-measured arm so far (+7 net wins / 300 paired
# seeds across four banks). It is a module constant, and therefore ledgered,
# because it is the line between "in-window" and "out-window" in the report:
# an unstated value there would make the headline split unreproducible.
ORACLE_MARGIN_FOR_REPORT = 0.02

GRID_POINTS = 25  # resolution of the tau grid (a search resolution, not a tuning value)


# ────────────────────────────────────────────────────────────────────────────
# Data
# ────────────────────────────────────────────────────────────────────────────


def load_rows(paths: list[Path]) -> list[dict]:
    rows: list[dict] = []
    for p in paths:
        if not p.is_file():
            continue
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not r.get("arm_ok", 0) or "feats" not in r:
                continue
            rows.append(r)
    return rows


def design(rows: list[dict]) -> np.ndarray:
    return np.array([VT.build_vector(r["feats"]) for r in rows], dtype=float)


# ────────────────────────────────────────────────────────────────────────────
# Metrics
# ────────────────────────────────────────────────────────────────────────────


def bootstrap_ratio_ci(good: list[float], bad: list[float], n_boot: int = 400,
                       seed: int = 0) -> tuple[float, float]:
    """Percentile bootstrap CI for a pooled ratio, resampling DECISIONS.

    Within-decision concordance is measured on a few dozen decisions, so its
    standard error is large enough that a point estimate cannot settle whether
    one model beats another. Decisions — not pairs — are the independent unit
    (pairs inside one decision share a shop and a run), so they are what gets
    resampled. Reporting the interval is what keeps the comparison honest: this
    repo has already adopted a +2/100 result that a larger run later reversed.
    """
    if len(good) < 2 or (sum(good) + sum(bad)) == 0:
        return (float("nan"), float("nan"))
    rng = np.random.default_rng(seed)
    g = np.asarray(good, dtype=float)
    b = np.asarray(bad, dtype=float)
    n = len(g)
    out: list[float] = []
    for _ in range(n_boot):
        idx = rng.integers(0, n, size=n)
        gs, bs = float(g[idx].sum()), float(b[idx].sum())
        if gs + bs > 0:
            out.append(gs / (gs + bs))
    if not out:
        return (float("nan"), float("nan"))
    return (float(np.quantile(out, 0.025)), float(np.quantile(out, 0.975)))


def scenario_summary(rows: list[dict], residuals: dict) -> dict:
    """How much item x scenario evidence exists, split by dimension.

    Reported rather than assumed: an item x boss cell needs decisions that were
    taken while the upcoming boss was known (the sim pre-selects it at shop
    entry), and an item x hand cell needs the run to have raised a hand's level
    past 1. Both rates are properties of the corpus, so they belong in the fit
    report next to the item evidence, not in a comment.
    """
    key_counts = Counter(str(r.get("key")) for r in rows)
    labelled = {"boss": 0, "hand": 0}
    cells: dict[str, list[int]] = {"boss": [], "hand": []}
    for r in rows:
        for c in VT.row_scenario_cells(r):
            dim = "boss" if "|boss:" in c else "hand"
            labelled[dim] += 1
            row = residuals.get(c)
            if row:
                cells[dim].append(int(row.get("n", 0.0)))
    out: dict = {"rows": len(rows), "items_seen": len(key_counts)}
    for dim in ("boss", "hand"):
        ns = sorted(cells[dim])
        out[dim] = {
            "rows_labelled": labelled[dim],
            "cells": len(ns),
            "cells_with_3plus": sum(1 for n in ns if n >= 3),
            "cells_with_8plus": sum(1 for n in ns if n >= 8),
            "max_n": ns[-1] if ns else 0,
        }
    return out


def row_cells(row: dict) -> list[str]:
    """Every residual cell this row contributes to / is predicted by.

    The primary cell (item x ante x support) plus the item's scenario cells
    (`value_tables.row_scenario_cells`: item x upcoming boss, item x the hand
    type the run is investing in). Both the accumulation and ALL THREE
    prediction paths must go through this one function — an offline report that
    scores a row differently from the shipped evaluator is exactly the
    train/serve skew the shared feature builder exists to prevent.
    """
    cell = str(row.get("cell", "") or "")
    if not cell:
        return []
    return [cell, *VT.cell_parents(cell), *VT.row_scenario_cells(row)]


def shrunk_sum(residuals: dict, row: dict, tau: float) -> float:
    cell = str(row.get("cell", "") or "")
    total = VT.ValueTable._shrunk_from(residuals, cell, tau) if cell else 0.0
    for c in VT.row_scenario_cells(row):
        total += VT.ValueTable._shrunk_from(residuals, c, tau)
    return total


def stderr_for(rows: list[dict], residuals: dict, tau: float,
               resid_sd: float) -> np.ndarray:
    """Per-row standard error of the value estimate (mirrors ValueTable).

    Runtime gates a purchase on ``value > z * stderr``, where stderr walks the
    cell hierarchy. The offline operating curve must use the same quantity or
    it would recommend a `z` the shipped policy does not actually implement.
    """
    # Deliberately the primary cell only, scenario cells excluded: the gate must
    # stay a LOWER bound on the estimate's uncertainty. Scenario cells pool
    # across antes and would only add evidence, i.e. loosen the bar; the
    # scenario terms add variance, so counting them as confidence would
    # overstate support. Mirrors ValueTable.cell_stderr.
    out = np.empty(len(rows), dtype=float)
    for i, r in enumerate(rows):
        n = 0.0
        for c in [r["cell"], *VT.cell_parents(r["cell"])]:
            row = residuals.get(c)
            if row and float(row.get("n", 0.0)) > 0.0:
                n = float(row["n"])
                break
        out[i] = resid_sd if n <= 0.0 else resid_sd / math.sqrt(n)
    return out


def selective_curve(rows: list[dict], pred: np.ndarray, ses: np.ndarray,
                    zs: list[float]) -> list[dict]:
    """Operating curve of the runtime rule ``value > z * stderr``.

    For each `z` this answers three questions the design has to satisfy at
    once: how often the oracle acts (coverage), whether it ranks correctly
    when it does (within-decision concordance on the acted decisions), and
    whether the picks are good in expectation (context-matched delta: the
    chosen candidate's return minus the mean return of that decision's
    candidates, which removes the item-mix confound).
    """
    by_dec: dict[str, list[int]] = defaultdict(list)
    for i, r in enumerate(rows):
        by_dec[str(r.get("dec_id"))].append(i)
    group = []
    for _dec, idxs in by_dec.items():
        if len(idxs) < 1:
            continue
        group.append(idxs)

    curve = []
    for z in zs:
        acted = 0
        deltas: list[float] = []
        good = bad = 0
        for idxs in group:
            passes = [i for i in idxs if pred[i] > z * ses[i]]
            if not passes:
                continue
            acted += 1
            best = max(passes, key=lambda i: pred[i])
            ctx = float(np.mean([rows[i]["label"] for i in idxs]))
            deltas.append(float(rows[best]["label"] - ctx))
            for j in passes:
                if j == best:
                    continue
                yj, yb = rows[j]["label"], rows[best]["label"]
                if yj == yb:
                    continue
                if yb > yj:
                    good += 1
                else:
                    bad += 1
        cov = acted / max(1, len(group))
        curve.append({
            "z": float(z),
            "coverage": round(cov, 4),
            "decisions": acted,
            "mean_ctx_delta": (round(float(np.mean(deltas)), 4) if deltas else None),
            "frac_positive": (round(float(np.mean([d > 0 for d in deltas])), 4)
                              if deltas else None),
            "concordance": (round(good / (good + bad), 4) if (good + bad) else None),
            "pairs": good + bad,
        })
    return curve


def decision_means(rows: list[dict]) -> dict[str, float]:
    """Mean label per decision — the centring target for the relative head."""
    tot: dict[str, float] = defaultdict(float)
    cnt: dict[str, float] = defaultdict(float)
    for r in rows:
        d = str(r.get("dec_id"))
        tot[d] += float(r["label"])
        cnt[d] += 1.0
    return {d: tot[d] / cnt[d] for d in tot if cnt[d] > 0}


def centred_labels(rows: list[dict], means: dict[str, float]) -> np.ndarray:
    return np.array([float(r["label"]) - means.get(str(r.get("dec_id")), 0.0)
                     for r in rows], dtype=float)


def rank_quality(rows: list[dict], pred: np.ndarray,
                 score_key: str | None = None) -> dict:
    """Does the score pick the BEST candidate of the shop? (the decision task)

    This is the metric that matches what the shipped oracle does: rank the
    candidates in one shop and buy the top one. It counts ties as half, and it
    also reports the *context-matched* margin — the chosen candidate's return
    minus the mean return of that shop's candidates — which removes the
    "this item is good everywhere" confound that flatters population metrics.
    """
    by_dec: dict[str, list[int]] = defaultdict(list)
    for i, r in enumerate(rows):
        by_dec[str(r.get("dec_id"))].append(i)
    wins = halves = losses = 0
    deltas: list[float] = []
    for _dec, idxs in by_dec.items():
        if len(idxs) < 2:
            continue
        if score_key:
            best = max(idxs, key=lambda i: rows[i].get(score_key, 0.0))
        else:
            best = max(idxs, key=lambda i: pred[i])
        top = max(rows[i]["label"] for i in idxs)
        if abs(rows[best]["label"] - top) < 1e-9:
            n_top = sum(1 for i in idxs if abs(rows[i]["label"] - top) < 1e-9)
            if n_top == 1:
                wins += 1
            else:
                halves += 1
        else:
            losses += 1
        ctx = float(np.mean([rows[i]["label"] for i in idxs]))
        deltas.append(float(rows[best]["label"] - ctx))
    n = wins + halves + losses
    return {
        "decisions": n,
        "top1_rate": ((wins + 0.5 * halves) / n) if n else float("nan"),
        "ctx_delta": float(np.mean(deltas)) if deltas else float("nan"),
        "frac_positive": (float(np.mean([d > 0 for d in deltas])) if deltas
                          else float("nan")),
    }


def concordance(rows: list[dict], pred: np.ndarray,
                score_key: str | None = None) -> dict:
    """Within-decision pairwise ranking accuracy.

    For every decision with >= 2 candidates, look at all pairs whose observed
    returns differ; count a win when the model orders them the way the run
    actually went. `score_key` scores an external column (e.g. legacy_dv)
    instead of the model prediction, for a like-for-like comparison.
    """
    by_dec: dict[str, list[int]] = defaultdict(list)
    for i, r in enumerate(rows):
        by_dec[str(r.get("dec_id"))].append(i)
    good = bad = ties = 0
    dec_good: list[float] = []
    dec_bad: list[float] = []
    for _dec, idxs in by_dec.items():
        if len(idxs) < 2:
            continue
        d_good = d_bad = 0
        for a in range(len(idxs)):
            for b in range(a + 1, len(idxs)):
                ia, ib = idxs[a], idxs[b]
                ya, yb = rows[ia]["label"], rows[ib]["label"]
                if ya == yb:
                    ties += 1
                    continue
                if score_key:
                    sa, sb = rows[ia].get(score_key, 0.0), rows[ib].get(score_key, 0.0)
                else:
                    sa, sb = pred[ia], pred[ib]
                if (sa > sb) == (ya > yb):
                    good += 1
                    d_good += 1
                else:
                    bad += 1
                    d_bad += 1
        if d_good or d_bad:
            dec_good.append(float(d_good))
            dec_bad.append(float(d_bad))
    n = good + bad
    return {
        "pairs": n,
        "accuracy": (good / n) if n else float("nan"),
        "mean_per_decision": (float(np.mean([g / (g + b) for g, b in
                                             zip(dec_good, dec_bad)]))
                               if dec_good else float("nan")),
        "decisions": len(dec_good),
        "ties": ties,
        "ci95": list(bootstrap_ratio_ci(dec_good, dec_bad)),
    }


def win_auc(rows: list[dict], pred: np.ndarray) -> float:
    """AUC of the model score against the sparse win-flip label."""
    y = np.array([r.get("label_win", 0) for r in rows], dtype=float)
    pos = y > 0
    neg = y < 0
    if pos.sum() == 0 or neg.sum() == 0:
        return float("nan")
    # Rank-based AUC restricted to the disagreeing pairs.
    sp, sn = pred[pos], pred[neg]
    wins = (sp[:, None] > sn[None, :]).sum() + 0.5 * (sp[:, None] == sn[None, :]).sum()
    return float(wins / (len(sp) * len(sn)))


def rmse(y: np.ndarray, p: np.ndarray) -> float:
    return float(np.sqrt(np.mean((y - p) ** 2)))


def intervention_test(rows: list[dict], margin: float) -> dict:
    """Did the head's preference actually beat the frozen pick, and where?

    Uses `onpolicy` rows only. `role` records WHY a row exists, so a decision
    containing a `pick` row plus an alternative (`substitute` = what the prior
    swaps in, `model_alt` = what the head prefers ignoring the tie window) is a
    decision the arm could act on. The pair's label difference is the REALIZED
    value of that intervention, measured directly -- no model refit, no
    behavioural screen.

    WHY THIS EXISTS. Three arms (override z2, prior m0, band m02) have now been
    judged by 100-200 seed screens whose net deltas were +-3 inside noise, and
    each screen costs ~15 minutes per question. The corpus can answer the
    question those screens were buying: rank the pairs by whether the CURRENT
    margin window would have permitted the substitution

        in-window  |legacy_dV(alt) - legacy_dV(pick)| <= margin
        out-window > margin

    If alternatives also win out-of-window, the window is too narrow and there
    are interventions the arm is not taking; if they only win in-window, the
    prior is at its ceiling and the fix is a better GATE, not a wider one.
    """
    by_dec: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        if str(r.get("candidate_mode")) != "onpolicy":
            continue
        by_dec[str(r.get("dec_id"))].append(r)
    buckets: dict[tuple, list[float]] = defaultdict(list)
    n_decs = n_with_pick = 0
    for dec, rs in by_dec.items():
        n_decs += 1
        picks = [r for r in rs if r.get("role") == "pick"]
        alts = [r for r in rs if r.get("role") in ("substitute", "model_alt")]
        if not picks or not alts:
            continue
        n_with_pick += 1
        pick = picks[0]
        for alt in alts:
            try:
                d = float(alt["label"]) - float(pick["label"])
                gap = abs(float(alt.get("legacy_dv", 0.0))
                          - float(pick.get("legacy_dv", 0.0)))
            except (TypeError, ValueError):
                continue
            where = "in_window" if gap <= margin else "out_window"
            buckets[(str(alt.get("role")), where)].append(d)

    def summarise(vals: list[float]) -> dict:
        n = len(vals)
        if not n:
            return {"n": 0}
        mean = sum(vals) / n
        if n > 1:
            var = sum((v - mean) ** 2 for v in vals) / (n - 1)
            se = (var / n) ** 0.5
        else:
            se = 0.0
        # Sign counts, not the mean, are the headline. These deltas are priced
        # in ante units with a win bonus, so a single +13 swamps a hundred
        # zeros and the mean is a tail statistic; worse/ties/better is what
        # answers "is the head's preference informative here at all?".
        worse = sum(1 for v in vals if v < 0)
        better = sum(1 for v in vals if v > 0)
        decided = worse + better
        return {"n": n, "mean_delta": round(mean, 3), "se": round(se, 3),
                "frac_positive": round(better / n, 3),
                "worse": worse, "ties": n - decided, "better": better,
                "sign_rate": (round(better / decided, 3) if decided else None),
                "ci95": [round(mean - 1.96 * se, 3), round(mean + 1.96 * se, 3)]}

    out = {"decisions": n_decs, "decisions_with_pair": n_with_pick,
           "margin": margin}
    for role in ("substitute", "model_alt"):
        for where in ("in_window", "out_window"):
            out[f"{role}_{where}"] = summarise(buckets.get((role, where), []))
    all_vals = [v for vs in buckets.values() for v in vs]
    out["all"] = summarise(all_vals)
    return out


def selection_quality(eval_rows: list[dict], pred: np.ndarray,
                      ref_rows: list[dict], score_key: str | None = None,
                      min_ref: int = 3) -> dict:
    """Does the model pick items whose POPULATION average outcome is better?

    Single-seed pairwise concordance is the wrong yardstick for a human-fair
    agent. For a fixed seed the label is deterministic, so a two-candidate
    contrast can be decided entirely by the future draw order — information a
    human-fair policy cannot have. Measured on iteration 1: 80 holdout pairs
    with a median margin of 2.0 return units against a pooled residual spread
    of 2.76, i.e. most pairs are luck, and no feature set could rank them.

    What the model *should* be judged on is whether it selects the item with
    the better EXPECTED outcome, where expectations are averaged over runs.
    Mean outcomes per item are estimated from `ref_rows` (the training split)
    and applied to `eval_rows`, so the comparison is out-of-sample:

        delta = mean_ref(model's pick) - max(mean_ref(items it rejected))

    A positive mean delta means the model's choices are better in expectation,
    which is exactly the property a decision rule needs.
    """
    by_cell: dict[str, list[float]] = defaultdict(list)
    by_key: dict[str, list[float]] = defaultdict(list)
    for r in ref_rows:
        y = float(r["label"])
        by_key[str(r.get("key"))].append(y)
        by_cell[f"{r.get('key')}|a{int(r.get('ante', 0) or 0)}"].append(y)

    def mean_of(key: str, ante: int) -> float | None:
        """Context-matched reference mean, falling back to the item mean.

        Preferring `key|ante` matters: an item's global mean inherits the
        average context it appeared in (early-ante shops are easier), so an
        item-level comparison across two candidates of the same shop can be
        an artefact of WHERE each item usually shows up rather than of how
        good it is. Matching on ante removes most of that.
        """
        cell = by_cell.get(f"{key}|a{ante}", [])
        if len(cell) >= min_ref:
            return sum(cell) / len(cell)
        key_rows = by_key.get(key, [])
        if len(key_rows) >= min_ref:
            return sum(key_rows) / len(key_rows)
        return None

    by_dec: dict[str, list[int]] = defaultdict(list)
    for i, r in enumerate(eval_rows):
        by_dec[str(r.get("dec_id"))].append(i)

    deltas: list[float] = []
    for _dec, idxs in by_dec.items():
        if len(idxs) < 2:
            continue
        if score_key:
            order = sorted(idxs, key=lambda i: eval_rows[i].get(score_key, 0.0),
                           reverse=True)
        else:
            order = sorted(idxs, key=lambda i: pred[i], reverse=True)
        head = eval_rows[order[0]]
        pick_mean = mean_of(str(head.get("key")), int(head.get("ante", 0) or 0))
        if pick_mean is None:
            continue
        rej_means = [
            m for i in order[1:]
            if (m := mean_of(str(eval_rows[i].get("key")),
                             int(eval_rows[i].get("ante", 0) or 0))) is not None]
        if not rej_means:
            continue
        deltas.append(pick_mean - max(rej_means))

    if not deltas:
        return {"decisions": 0, "mean_delta": float("nan"),
                "frac_positive": float("nan")}
    arr = np.array(deltas)
    return {
        "decisions": len(arr),
        "mean_delta": float(arr.mean()),
        "median_delta": float(np.median(arr)),
        "frac_positive": float((arr > 0).mean()),
        "se": float(arr.std(ddof=1) / math.sqrt(len(arr))) if len(arr) > 1 else float("nan"),
    }


# ────────────────────────────────────────────────────────────────────────────
# Fit
# ────────────────────────────────────────────────────────────────────────────


def grouped_folds(seeds: np.ndarray, k: int) -> list[np.ndarray]:
    """Fold assignment by seed, so no run contributes to two sides."""
    uniq = np.unique(seeds)
    fold_of = {s: i % k for i, s in enumerate(uniq)}
    return [np.array([i for i, s in enumerate(seeds) if fold_of[s] == f])
            for f in range(k)]


def fit_ridge(X: np.ndarray, y: np.ndarray, alpha: float) -> np.ndarray:
    n, d = X.shape
    A = X.T @ X + alpha * np.eye(d)
    b = X.T @ y
    return np.linalg.solve(A, b)


def sigma_grid(alpha_scale: float) -> list[float]:
    """Log-spaced alphas around the mean column energy — data-derived scale."""
    base = max(1e-9, alpha_scale)
    return [base * (10 ** (i * 6.0 / (GRID_POINTS - 1) - 3.0)) for i in range(GRID_POINTS)]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--train", default="results/decisions/train_v1.jsonl",
                    help="comma-separated jsonl paths (iterations are concatenated)")
    ap.add_argument("--holdout", default="results/decisions/holdout_v1.jsonl",
                    help="comma-separated jsonl paths")
    ap.add_argument("--out", default="vendor/balatro-rl/balatro_sim/value_tables.json")
    ap.add_argument("--report", default="results/value_model_report.json")
    ap.add_argument("--folds", type=int, default=5)
    args = ap.parse_args()

    t0 = time.time()
    train_rows = load_rows([ROOT / p.strip() for p in args.train.split(",") if p.strip()])
    hold_rows = load_rows([ROOT / p.strip() for p in args.holdout.split(",") if p.strip()])
    if not train_rows:
        print("no training rows — nothing to fit")
        return 1

    Xtr = design(train_rows)
    Xho = design(hold_rows) if hold_rows else np.zeros((0, Xtr.shape[1]))
    ytr = np.array([r["label"] for r in train_rows], dtype=float)
    yho = np.array([r["label"] for r in hold_rows], dtype=float)
    key_counts = Counter(str(r.get("key")) for r in train_rows)

    mu = Xtr.mean(axis=0)
    sd = Xtr.std(axis=0)
    sd[sd < 1e-9] = 1.0
    Ztr = (Xtr - mu) / sd
    Zho = (Xho - mu) / sd if len(Xho) else Xho

    seeds = np.array([int(r["seed"]) for r in train_rows])
    k = max(2, min(args.folds, len(np.unique(seeds))))
    folds = grouped_folds(seeds, k)

    # ── alpha by grouped CV ──────────────────────────────────────────────
    energy = float(np.mean(np.sum(Ztr ** 2, axis=1)) / Ztr.shape[1])
    alphas = sigma_grid(energy)
    best_alpha, best_err = alphas[0], float("inf")
    oof = np.zeros(len(ytr))
    for alpha in alphas:
        preds = np.zeros(len(ytr))
        for f in folds:
            tr = np.setdiff1d(np.arange(len(ytr)), f)
            if len(tr) == 0 or len(f) == 0:
                continue
            w = fit_ridge(Ztr[tr], ytr[tr], alpha)
            preds[f] = Ztr[f] @ w
        err = rmse(ytr, preds)
        if err < best_err:
            best_err, best_alpha = err, alpha
            oof = preds.copy()
    print(f"alpha* = {best_alpha:.3e} (CV RMSE {best_err:.4f})", flush=True)

    w = fit_ridge(Ztr, ytr, best_alpha)
    # Predictions use the ORIGINAL feature scale; coefficients are rescaled so
    # inference can standardise with the stored mu/sd.
    w_orig = w / sd
    b_orig = -float(w @ (mu / sd))

    # ── residual table from out-of-fold errors ───────────────────────────
    # Out-of-fold (not in-sample) errors, so a cell's mean is not the head's
    # own training residual reproduced back to itself.
    resid = ytr - oof
    resid_sd = float(np.std(resid))
    cells: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0, 0.0])  # n,total,sumsq
    for r, e in zip(train_rows, resid):
        for cell in row_cells(r):
            cells[cell][0] += 1.0
            cells[cell][1] += float(e)
            cells[cell][2] += float(e) * float(e)
    residuals = {c: {"n": v[0], "total": v[1], "sumsq": v[2]}
                 for c, v in cells.items()}

    # ── tau by holdout-selected grid (for the freeze judged on holdout) ──
    def predict_with(rows: list[dict], X: np.ndarray, tau: float) -> np.ndarray:
        base = (X - mu) / sd @ w
        out = np.empty(len(rows))
        for i, r in enumerate(rows):
            out[i] = base[i] + shrunk_sum(residuals, r, tau)
        return out

    hold_ok = len(hold_rows) >= 2
    counts = np.array([v["n"] for v in residuals.values()], dtype=float)
    lo = max(1e-6, float(np.quantile(counts, 0.05)))
    hi = max(lo * 10, float(np.quantile(counts, 0.95)))
    tau_candidates = np.logspace(math.log10(lo), math.log10(hi), GRID_POINTS)
    best_tau, best_tau_err = 1.0, float("inf")
    sweep = []
    for tau in tau_candidates:
        if hold_ok:
            p = predict_with(hold_rows, Xho, float(tau))
            err = rmse(yho, p)
        else:
            err = float("nan")
        sweep.append({"tau": float(tau), "holdout_rmse": err})
        if hold_ok and err < best_tau_err:
            best_tau_err, best_tau = err, float(tau)
    if not hold_ok:
        best_tau = 1.0
    print(f"tau* = {best_tau:.4f} (holdout RMSE {best_tau_err:.4f})", flush=True)

    # ── relative head: the same regression on WITHIN-DECISION centred labels ─
    # Choosing among the items in one shop is a within-shop comparison. The
    # absolute head spends most of its capacity on between-decision variation
    # (how rich/far along the run is), which is identical across the candidates
    # of a decision and therefore carries no information about which to buy.
    tr_means = decision_means(train_rows)
    ho_means = decision_means(hold_rows)
    ytr_rel = centred_labels(train_rows, tr_means)
    yho_rel = centred_labels(hold_rows, ho_means) if hold_rows else np.zeros(0)

    # Its own alpha by grouped CV. The relative target lives on a much smaller
    # scale than the absolute one (within-decision variation rather than
    # run-to-run spread), so reusing the absolute head's alpha over-shrinks it —
    # and this is the head that ranks candidates, i.e. the one the override rule
    # reads. Regularisation for each head is therefore chosen for its own target.
    best_alpha_rel, best_err_rel = best_alpha, float("inf")
    for alpha in alphas:
        preds = np.zeros(len(ytr_rel))
        for f in folds:
            tr = np.setdiff1d(np.arange(len(ytr_rel)), f)
            if len(tr) == 0 or len(f) == 0:
                continue
            wr = fit_ridge(Ztr[tr], ytr_rel[tr], alpha)
            preds[f] = Ztr[f] @ wr
        err = rmse(ytr_rel, preds)
        if err < best_err_rel:
            best_err_rel, best_alpha_rel = err, alpha
    print(f"alpha*rel = {best_alpha_rel:.3e} (CV RMSE {best_err_rel:.4f})",
          flush=True)

    oof_rel = np.zeros(len(ytr_rel))
    for f in folds:
        tr = np.setdiff1d(np.arange(len(ytr_rel)), f)
        if len(tr) == 0 or len(f) == 0:
            continue
        wr = fit_ridge(Ztr[tr], ytr_rel[tr], best_alpha_rel)
        oof_rel[f] = Ztr[f] @ wr
    w_rel = fit_ridge(Ztr, ytr_rel, best_alpha_rel)
    w_rel_orig = w_rel / sd
    b_rel_orig = -float(w_rel @ (mu / sd))
    resid_rel = ytr_rel - oof_rel
    resid_sd_rel = float(np.std(resid_rel))
    cells_rel: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0, 0.0])
    for r, e in zip(train_rows, resid_rel):
        for cell in row_cells(r):
            cells_rel[cell][0] += 1.0
            cells_rel[cell][1] += float(e)
            cells_rel[cell][2] += float(e) * float(e)
    residuals_rel = {c: {"n": v[0], "total": v[1], "sumsq": v[2]}
                     for c, v in cells_rel.items()}

    # The relative head's outputs are compared within a decision, so a
    # gain/shrink rescale here would only move both sides of every contrast
    # together. Kept for symmetry with the absolute head and reported.
    def predict_rel(rows: list[dict], X: np.ndarray, tau: float) -> np.ndarray:
        base = (X - mu) / sd @ w_rel
        out = np.empty(len(rows))
        for i, r in enumerate(rows):
            out[i] = base[i] + shrunk_sum(residuals_rel, r, tau)
        return out

    best_tau_rel, best_tau_rel_err = 1.0, float("inf")
    if hold_ok:
        for tau in tau_candidates:
            err = rmse(yho_rel, predict_rel(hold_rows, Xho, float(tau)))
            if err < best_tau_rel_err:
                best_tau_rel_err, best_tau_rel = err, float(tau)
    print(f"tau*rel = {best_tau_rel:.4f} (holdout RMSE "
          f"{best_tau_rel_err if hold_ok else float('nan'):.4f})", flush=True)

    # ── evaluate ─────────────────────────────────────────────────────────
    eval_rows = hold_rows if hold_ok else train_rows
    Xev = Xho if hold_ok else Ztr * sd + mu
    base_ev = ((Xev - mu) / sd) @ w
    pred_ev = np.array([
        base_ev[i] + shrunk_sum(residuals, r, best_tau)
        for i, r in enumerate(eval_rows)])
    pred_rel_ev = predict_rel(eval_rows, Xev, best_tau_rel)

    report = {
        "rows_train": len(train_rows),
        "rows_holdout": len(hold_rows),
        "seeds_train": int(len(np.unique(seeds))),
        "folds": k,
        "alpha": best_alpha,
        "tau": best_tau,
        "cv_rmse": best_err,
        "holdout_rmse_linear": rmse(yho, base_ev) if hold_ok else None,
        "holdout_rmse_full": rmse(yho, pred_ev) if hold_ok else None,
        "concordance_model": concordance(eval_rows, pred_ev),
        "concordance_legacy_dv": concordance(eval_rows, pred_ev, score_key="legacy_dv"),
        "selective_curve": selective_curve(
            eval_rows, pred_ev,
            stderr_for(eval_rows, residuals, best_tau, resid_sd),
            [0.0, 0.5, 1.0, 1.5, 2.0, 3.0, 4.0]),
        "rank_head_absolute": rank_quality(eval_rows, pred_ev),
        "rank_head_relative": rank_quality(eval_rows, pred_rel_ev),
        "rank_legacy_dv": rank_quality(eval_rows, pred_ev, score_key="legacy_dv"),
        "holdout_rmse_rel": (rmse(yho_rel, pred_rel_ev) if hold_ok else None),
        "tau_rel": best_tau_rel,
        "resid_sd_rel": resid_sd_rel,
        "selection_model": selection_quality(eval_rows, pred_ev, train_rows),
        "selection_legacy_dv": selection_quality(eval_rows, pred_ev, train_rows,
                                                 score_key="legacy_dv"),
        "item_evidence": {
            "keys_seen_train": len(key_counts),
            "keys_with_3plus": sum(1 for c in key_counts.values() if c >= 3),
            "keys_with_8plus": sum(1 for c in key_counts.values() if c >= 8),
            "top_keys": key_counts.most_common(10),
        },
        "scenario_evidence": scenario_summary(train_rows, residuals),
        "win_auc_model": win_auc(eval_rows, pred_ev),
        # POOLED across train and holdout on purpose, unlike every other
        # number in this report. The test uses no fitted quantity -- it only
        # compares the labels of the pick and the alternative the oracle
        # weighed -- so there is nothing to overfit to and holding rows out
        # would just cut `n` on the scarcest rows in the corpus (on-policy pairs
        # are only produced by `--candidate-mode onpolicy`).
        "intervention": intervention_test(train_rows + hold_rows,
                                          ORACLE_MARGIN_FOR_REPORT),
        "win_auc_legacy_dv": win_auc(eval_rows,
                                     np.array([r.get("legacy_dv", 0.0) for r in eval_rows])),
        "resid_sd": resid_sd,
        "cell_stats": {
            "cells": len(residuals),
            "cells_finest": sum(1 for c in residuals if c.count("|") == 2),
            "max_n": float(counts.max()) if len(counts) else 0.0,
            "median_n": float(np.median(counts)) if len(counts) else 0.0,
        },
        "tau_sweep": sweep,
        "catalogue_fingerprint": CAT.fingerprint(),
        "feature_count": len(VT.FEATURE_ORDER),
        "elapsed_s": round(time.time() - t0, 1),
    }

    # ── artifact ─────────────────────────────────────────────────────────
    artifact = {
        "version": VT.MODEL_VERSION,
        "catalogue_fingerprint": CAT.fingerprint(),
        "feature_order": list(VT.FEATURE_ORDER),
        "w": [float(x) for x in w_orig],
        "b": float(b_orig),
        "mu": [float(x) for x in mu],
        "sd": [float(x) for x in sd],
        "residuals": {c: {"n": float(v["n"]), "total": float(v["total"]),
                           "sumsq": float(v["sumsq"])}
                      for c, v in residuals.items()},
        "w_rel": [float(x) for x in w_rel_orig],
        "b_rel": float(b_rel_orig),
        "residuals_rel": {c: {"n": float(v["n"]), "total": float(v["total"]),
                              "sumsq": float(v["sumsq"])}
                          for c, v in residuals_rel.items()},
        "tau_rel": float(best_tau_rel),
        "resid_sd_rel": resid_sd_rel,
        "tau": float(best_tau),
        "beta": 0.0,
        "resid_sd": resid_sd,
        "meta": {
            "fitted_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "rows_train": len(train_rows),
            "alpha": best_alpha,
            "cv_rmse": best_err,
            "concordance_model": report["concordance_model"],
            "concordance_legacy_dv": report["concordance_legacy_dv"],
            "collector": "tools/collect_decisions.py",
            "note": "beta is unused: the dense return label already blends depth "
                    "and win, so no separate control variate is needed.",
        },
    }
    out_path = ROOT / args.out
    VT.dump(out_path, artifact)
    rep_path = ROOT / args.report
    rep_path.parent.mkdir(parents=True, exist_ok=True)
    rep_path.write_text(json.dumps(report, indent=1, sort_keys=True) + "\n",
                        encoding="utf-8")

    print("\n=== VALUE MODEL REPORT ===")
    print(f"train rows      : {report['rows_train']} "
          f"({report['seeds_train']} seeds, {k} CV folds)")
    print(f"holdout rows    : {report['rows_holdout']}")
    print(f"features        : {report['feature_count']}")
    print(f"cells           : {report['cell_stats']}")
    print(f"holdout RMSE    : linear {report['holdout_rmse_linear']} "
          f"-> full {report['holdout_rmse_full']}")
    cm, cl = report["concordance_model"], report["concordance_legacy_dv"]
    print(f"within-decision : model {cm['accuracy']} ({cm['pairs']} pairs, "
          f"ci95 {cm['ci95']}) | legacy dV {cl['accuracy']} ({cl['pairs']} pairs)")
    for name, key in (("absolute head  ", "rank_head_absolute"),
                      ("relative head  ", "rank_head_relative"),
                      ("legacy dV      ", "rank_legacy_dv")):
        rk = report[key]
        print(f"top1 pick       : {name} {rk['top1_rate']:.3f} on {rk['decisions']} "
              f"shops | ctx_delta {rk['ctx_delta']:+.3f} "
              f"(frac>0 {rk['frac_positive']:.2f})")
    print("operating curve : z  coverage  decisions  ctx_delta  frac>0  concordance")
    for row in report["selective_curve"]:
        print(f"                  {row['z']:<4} {row['coverage']:<9} {row['decisions']:<10} "
              f"{str(row['mean_ctx_delta']):<10} {str(row['frac_positive']):<7} "
              f"{row['concordance']} ({row['pairs']} pairs)")
    sm, sl = report["selection_model"], report["selection_legacy_dv"]
    print(f"selection (pop) : model {sm['mean_delta']:+.3f} "
          f"(frac>0 {sm['frac_positive']}, n={sm['decisions']}) "
          f"| legacy dV {sl['mean_delta']:+.3f} (n={sl['decisions']})")
    print(f"win-flip AUC    : model {report['win_auc_model']} "
          f"| legacy dV {report['win_auc_legacy_dv']}")
    iv = report.get("intervention", {})
    if iv.get("decisions_with_pair"):
        print(f"intervention    : {iv['decisions_with_pair']} of {iv['decisions']} "
              f"on-policy decisions carry a pick+alternative pair "
              f"(margin {iv['margin']})")
        for role in ("substitute", "model_alt"):
            for where in ("in_window", "out_window"):
                s = iv.get(f"{role}_{where}", {})
                if not s.get("n"):
                    continue
                print(f"  {role:11} {where:11} n={s['n']:<4} worse/ties/better "
                      f"{s['worse']}/{s['ties']}/{s['better']} "
                      f"sign_rate {s['sign_rate']} | mean d={s['mean_delta']:+.3f} "
                      f"se {s['se']:.3f} ci95 {s['ci95']}")
        tot = iv.get("all", {})
        if tot.get("n"):
            print(f"  {'ALL':11} {'':11} n={tot['n']:<4} worse/ties/better "
                  f"{tot['worse']}/{tot['ties']}/{tot['better']} "
                  f"sign_rate {tot['sign_rate']} | mean d={tot['mean_delta']:+.3f} "
                  f"se {tot['se']:.3f} ci95 {tot['ci95']}")
        print("                (sign_rate is the robust statistic: the mean is "
              "a tail statistic in ante+win units)")
    else:
        print("intervention    : no on-policy rows in the corpus yet "
              "(collect with --candidate-mode onpolicy)")
    se = report["scenario_evidence"]
    for dim, label in (("boss", "boss"), ("hand", "hand type")):
        s = se[dim]
        print(f"scenario {label:9} : {s['rows_labelled']} rows labelled, "
              f"{s['cells']} item cells ({s['cells_with_3plus']} with n>=3, "
              f"max {s['max_n']})")
    if se["hand"]["rows_labelled"] == 0:
        print("                 hand-type cells are EMPTY because no collected "
              "row carries `hand_key` yet; they populate from the next "
              "collection run (the collector records it from v6 on)")
    print(f"wrote {out_path}")
    print(f"wrote {rep_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
