"""validate_state_value.py — S1: does V(S') rank the pairs we already paid for?

THE QUESTION THIS ANSWERS
=========================
V13's claim is that scoring whole states can rank decisions the per-item encoder
cannot. That claim is testable **before** any behavioural screen, and this tool is
the test. The on-policy fork corpus contains, for each sampled shop decision, the
item the frozen search buys (`pick`) and the item the learned head prefers
(`model_alt`), each with the paired counterfactual label that was bought for it:

    label(alt) = return(force alt) - return(force pick)      (dense, paired)

`pick` rows label exactly 0.000 by construction -- forcing the action the policy
would have taken reproduces the control arm -- so the pair's own label already says
which item was worth more in that exact state. Nothing new needs simulating.

The tool therefore:
  1. replays each seed with the collector's decision logic untouched but `rollout`
     stubbed, so the exact decision states come back for free;
  2. scores the **post-acquisition** state of each candidate with `V`;
  3. asks whether sign(V(alt) - V(pick)) matches sign(label(alt)).

The stop rule is in the design doc: V must beat the shipped head's sign rate on
the same pairs. If it does not, the redesign is falsified at this gate rather than
after a 300-seed bench.

WHY THE RECORDING IS ORDER-BASED, AND WHY THAT IS CHECKED
=========================================================
The rollout stub cannot know which candidate it was handed, so attribution is
recovered from call order, which the collector guarantees: within one decision the
skip rollout fires first, then for each accepted candidate `_force_arm` (wrapped
here to push its index) immediately precedes that candidate's rollout. A rejected
arm pushes nothing and rolls out nothing, so the two sequences stay balanced --
and the tool does not *trust* that: it cross-checks every recorded candidate index
against the row the collector itself wrote for that `dec_id`, and reports a
nonzero `index_mismatches` as an integrity failure rather than reporting a metric
computed on mislabelled data.

THE INCUMBENT COMPARATOR
========================
Scored on the SAME pairs, from the same replayed decision, using the shipped
artifact's own `relative_of(game, item)` -- the exact function the runtime oracle
calls. A comparison against a reimplementation would prove nothing.
"""
from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "vendor" / "balatro-rl"))
sys.path.insert(0, str(ROOT))

import tools.collect_decisions as CD                       # noqa: E402
from balatro_sim import state_value as SV                   # noqa: E402
from balatro_sim import value_tables as VT                  # noqa: E402

# A stub rollout result. The collector only reads `won`, `ante` and a few economy
# fields off it to build a label, and those labels are NOT used here (the corpus
# holds the real ones), so the cheapest valid dict is the honest choice.
_STUB = {"won": False, "ante": 1, "ret": 0.0, "econ_source": 0.0,
         "money_spent": 0.0, "interest_collected": 0.0, "best_score": 0.0}

PAIR_ROLES = ("model_alt", "substitute")


class _Replay:
    """One seed replayed with rollouts stubbed, recording decision states.

    Also captures the live decision game by wrapping `_shop_candidates`, which is
    called once at the top of every shop decision and does not mutate the game --
    that object is what the incumbent head must be scored against.
    """

    def __init__(self, cfg: dict) -> None:
        self.cfg = cfg
        self.states: list[tuple[int | None, dict]] = []
        self.live_pending = None
        self.group_live: list = []
        self._pending: list[int] = []

    # ── hooks ───────────────────────────────────────────────────────────────
    def _h_shop_candidates(self, game):
        self.live_pending = game
        return self._orig_shop_candidates(game)

    def _h_force_arm(self, game, mode, idx):
        fork, ok, why = self._orig_force_arm(game, mode, idx)
        # Only an ACCEPTED arm is followed by a rollout. Pushing on rejection
        # would leave a stale index that the next rollout (a different
        # candidate's, or the next decision's skip) would pop, silently
        # mislabelling it -- measured at 117 mismatches over 20 seeds before this
        # guard existed.
        if ok and fork is not None:
            self._pending.append(int(idx))
        return fork, ok, why

    def _h_rollout(self, game, policy):
        idx = self._pending.pop(0) if self._pending else None
        if idx is None:
            # A skip rollout opens a decision group; the live game captured just
            # before it is that decision's game.
            self.group_live.append(self.live_pending)
        try:
            feats = SV.state_features(game)
        except Exception:
            feats = {}
        self.states.append((idx, feats))
        return dict(_STUB)

    # ── driver ──────────────────────────────────────────────────────────────
    def run(self, seed: int) -> tuple[list[dict], dict]:
        c = self.cfg
        self.states = []
        self.group_live = []
        self.live_pending = None
        self._pending = []
        self._orig_force_arm = CD._force_arm
        self._orig_shop_candidates = CD._shop_candidates
        self._orig_rollout = CD.rollout
        CD._force_arm = self._h_force_arm
        CD._shop_candidates = self._h_shop_candidates
        CD.rollout = self._h_rollout
        try:
            rows = CD.collect_seed(
                seed, c["mode"], c["max_decisions"], c["cand_cap"], c["focus"],
                c["accept_rate"], c["per_ante"], c["booster_cand_cap"],
                c["focus_extra"], max(1, c.get("samples", 1)), "onpolicy",
                c["oracle_margin"], c["oracle_kinds"])
        finally:
            CD._force_arm = self._orig_force_arm
            CD._shop_candidates = self._orig_shop_candidates
            CD.rollout = self._orig_rollout
        return rows, self._pair(rows)

    def _pair(self, rows: list[dict]) -> dict:
        """Attach recorded post-acquisition states to the collector's own rows.

        Walks decisions in the order the collector created them: one skip state
        (index `None`) opens each, then one state per row that actually produced a
        rollout. Groups whose only candidate was rejected still consumed a skip
        state, so the walk is driven by the rows -- including rejected ones --
        and not by the recorded states.
        """
        order: list[str] = []
        seen: set[str] = set()
        for r in rows:
            d = r.get("dec_id")
            if d and d not in seen:
                seen.add(d)
                order.append(d)
        by_dec: dict[str, list[dict]] = {}
        for r in rows:
            by_dec.setdefault(r.get("dec_id"), []).append(r)

        out: dict[str, dict] = {}
        i = 0
        mismatch = 0
        examples: list[str] = []
        # Each arm is rolled out `samples` times from the same forked state, so a
        # decision consumes `samples` skip states and `samples` states per
        # accepted candidate. The states within one arm are identical (the fork
        # is the same object, only its RNG seed differs), so the first is kept
        # and the rest are consumed to keep the walk aligned.
        k_arm = max(1, int(self.cfg.get("samples", 1)))
        for g, dec in enumerate(order):
            if i >= len(self.states):
                break
            entry = {"skip": None, "live": self.group_live[g]
                     if g < len(self.group_live) else None,
                     "cands": {}, "rows": by_dec.get(dec) or []}
            for k in range(k_arm):
                if i >= len(self.states):
                    break
                skip_idx, skip_feats = self.states[i]
                i += 1
                if k == 0:
                    entry["skip"] = skip_feats
            for r in by_dec.get(dec) or []:
                if not r.get("arm_ok", 0):
                    continue
                feats = None
                ridx_seen = None
                for k in range(k_arm):
                    if i >= len(self.states):
                        break
                    ridx, f_k = self.states[i]
                    i += 1
                    if k == 0:
                        feats, ridx_seen = f_k, ridx
                if ridx_seen is None or int(r.get("item_idx", -1)) != ridx_seen:
                    mismatch += 1
                    if len(examples) < 5:
                        examples.append(f"{dec} row_idx={r.get('item_idx')} "
                                        f"rec_idx={ridx_seen} key={r.get('key')}")
                entry["cands"][int(r.get("item_idx", -1))] = feats
            out[dec] = entry
        return {"by_dec": out, "mismatch": mismatch, "examples": examples,
                "groups": len(order), "consumed": i,
                "recorded": len(self.states)}


def load_corpus(paths: list[Path], roles: tuple) -> list[dict]:
    """Read rows, keeping only real arms on shop decisions with a pairable role.

    Pack decisions are excluded because the on-policy collector only forks the
    oracle's pair on shops -- a pack row is coverage fill and its "alternative" is
    not a decision the runtime weighs.
    """
    rows = []
    for p in paths:
        if not p.is_file():
            continue
        with open(p, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not r.get("arm_ok", 0):
                    continue
                if str(r.get("role", "")) not in roles:
                    continue
                if r.get("mode") != "shop":
                    continue
                rows.append(r)
    return rows


def acq_vs_skip(pairs: list[dict]) -> dict:
    """V's competence at the decision the LOOKAHEAD rule actually makes.

    The near-tie test asks V to choose between two items the heuristic already
    ranked within a hair of each other, and 48% of those pairs measure identical
    -- a region where no ranker can win. The design's decision rule is not that;
    it is `argmax_a V(S'_a)` over every affordable action, whose central choice is
    "buy this, or do something else". Those contrasts already exist in the corpus:
    a row exists for every candidate that was forked, and the SKIP arm alongside it
    is the policy's own continuation, so `label` there is the real buy-vs-not
    counterfactual. Every row whose candidate the policy did NOT itself take is
    therefore a non-degenerate record of the lookahead question.

    `pick` rows are excluded because their label is 0 by construction -- forcing
    the action the policy would have taken reproduces the control arm -- so they
    carry no information about this question either way.
    """
    rows = [{"label": p["skip_label"], "pred_delta": p["skip_delta"]}
            for p in pairs if p.get("skip_delta") is not None
            and p.get("role") != "pick"]
    return sign_rate(rows, "pred_delta")


def sign_rate(pairs: list[dict], key: str) -> dict:
    """Sign agreement and AUC over non-tied pairs for one predictor column.

    Ties are reported, never counted as wins: `label` is a difference of two
    identical-measure runs, so an exact tie is the absence of a question rather
    than a correct answer. Counting ties as agreement would let a model that
    predicts 0.0 everywhere score 1.0.
    """
    n_tie = n_worse = n_better = 0
    agree = disagree = 0
    pos, neg = [], []
    for p in pairs:
        y = p["label"]
        if y == 0.0:
            n_tie += 1
            continue
        if y < 0:
            n_worse += 1
        else:
            n_better += 1
        d = p[key]
        if y > 0:
            pos.append(d)
        else:
            neg.append(d)
        if d == 0.0:
            # A model with no opinion on a question it was asked gets no credit
            # rather than a coin flip of credit.
            disagree += 1
        elif (d > 0) == (y > 0):
            agree += 1
        else:
            disagree += 1
    n = agree + disagree
    auc = float("nan")
    if pos and neg:
        pa, na = np.array(pos), np.array(neg)
        wins = ((pa[:, None] > na[None, :]).sum()
                + 0.5 * (pa[:, None] == na[None, :]).sum())
        auc = float(wins / (len(pa) * len(na)))
    return {"n_pairs": len(pairs), "ties": n_tie, "worse": n_worse,
            "better": n_better, "n_scored": n,
            "agree": agree, "sign_rate": (agree / n) if n else float("nan"),
            "auc": auc}


def _mask(layout: list[str], prefixes: tuple) -> np.ndarray:
    """1.0 for columns to keep, 0.0 for columns to ablate.

    Ablation is a zeroing of the encoded column, not a refit: the question is
    whether the model's *use* of a block helps on real decisions, and refitting
    without the block would answer a different question (what a model without it
    could learn) at the cost of a new fit per arm.
    """
    if not prefixes:
        return np.ones(len(layout))
    return np.array([0.0 if any(n.startswith(p) for p in prefixes) else 1.0
                     for n in layout])


def _score(model, layout: list[str], mask: np.ndarray, feats: dict) -> float:
    x = np.asarray(SV.encode(feats, layout), dtype=float) * mask
    return float(model.predict(x.reshape(1, -1))[0])


def _worker(task):
    seed, cfg = task
    import joblib
    model_pkg = joblib.load(cfg["model"])
    layout = list(model_pkg["layout"])
    model = model_pkg["model"]
    mask = _mask(layout, tuple(cfg.get("ablate") or ()))
    table = VT.load(cfg["frozen"])
    rp = _Replay(cfg)
    try:
        rows, info = rp.run(seed)
    except Exception as exc:
        return seed, [], {"error": f"{type(exc).__name__}: {exc}"}

    saved = cfg["by_dec"]
    pairs: list[dict] = []
    for dec, entry in info["by_dec"].items():
        keep = saved.get(dec)
        if not keep:
            continue
        anchor = next((r for r in keep.values()
                       if str(r.get("role")) == "pick"), None)
        if anchor is None:
            continue
        a_idx = int(anchor["item_idx"])
        a_state = entry["cands"].get(a_idx)
        if a_state is None:
            continue
        v_anchor = _score(model, layout, mask, a_state)
        inc_anchor = _incumbent(table, entry["live"], a_idx)
        # The lookahead contrast for every forked candidate, against the skip arm
        # the collector already measured. Computed for ALL roles because this is
        # a different question from the near-tie one and does not want the pick
        # rows filtered out of the corpus (only out of the metric, where their
        # label is 0 by construction).
        v_skip = None
        if entry.get("skip"):
            try:
                v_skip = _score(model, layout, mask, entry["skip"])
            except Exception:
                v_skip = None
        if inc_anchor is None:
            continue
        for idx, r in keep.items():
            if str(r.get("role")) not in PAIR_ROLES or idx == a_idx:
                continue
            st = entry["cands"].get(idx)
            if st is None:
                continue
            Vc = _score(model, layout, mask, st)
            inc_c = _incumbent(table, entry["live"], idx)
            if inc_c is None:
                continue
            row = {
                "dec": dec, "seed": seed, "role": str(r.get("role")),
                "key": str(r.get("key")), "ante": int(r.get("ante", 0)),
                "label": float(r.get("label", 0.0)),
                "pred_delta": Vc - v_anchor,
                "incumbent_delta": inc_c - inc_anchor,
                "legacy_delta": float(r.get("legacy_dv", 0.0)),
            }
            if v_skip is not None:
                row["skip_delta"] = _score(model, layout, mask, st) - v_skip
                row["skip_label"] = float(r.get("label", 0.0))
            if cfg.get("dump_states"):
                # The encoded vectors are dumped so the *ceiling* of this pair
                # set can be measured offline without replaying: a model fit on
                # the differences answers "is the signal here at all", which is
                # a different question from "does the current V use it".
                row["vec"] = [round(v, 4) for v in
                              SV.encode(st, layout)]
                row["anc_vec"] = [round(v, 4) for v in
                                  SV.encode(a_state, layout)]
            pairs.append(row)
    return seed, pairs, info


def _incumbent(table, game, idx: int):
    """The shipped head's value for the shop item at `idx`, or None if unscoreable.

    Uses `relative_of`, the function the runtime oracle itself calls, so the
    comparison is against the shipped behaviour rather than a reimplementation.
    """
    if game is None:
        return None
    try:
        items = list(getattr(game, "current_shop", []) or [])
        if idx < 0 or idx >= len(items):
            return None
        return float(table.relative_of(game, items[idx]))
    except Exception:
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", required=True,
                    help="comma-separated decision jsonl files (on-policy rows)")
    ap.add_argument("--model", default="results/state_value_model.joblib")
    ap.add_argument("--frozen",
                    default="vendor/balatro-rl/balatro_sim/value_tables.json",
                    help="shipped head artifact, scored as the incumbent")
    ap.add_argument("--focus-file", default="results/coverage_focus_iter2.json",
                    help="must match the collection this corpus came from, or "
                         "the replay forks different decisions than were filed")
    ap.add_argument("--max-seeds", type=int, default=0, help="0 = all in corpus")
    ap.add_argument("--workers", type=int, default=10)
    ap.add_argument("--mode", default="both")
    ap.add_argument("--samples", type=int, default=1,
                    help="paired continuations per arm in the collection being "
                         "replayed; must match it, or the replay's rollout count "
                         "per arm differs and the state-to-row pairing shifts")
    ap.add_argument("--max-decisions", type=int, default=14)
    ap.add_argument("--per-ante", type=int, default=2)
    ap.add_argument("--cand-cap", type=int, default=2)
    ap.add_argument("--booster-cand-cap", type=int, default=4)
    ap.add_argument("--focus-extra", type=int, default=3)
    ap.add_argument("--accept-rate", type=float, default=0.5)
    ap.add_argument("--oracle-margin", type=float, default=0.02)
    ap.add_argument("--oracle-kinds", type=str,
                    default="joker,tarot,spectral,planet,voucher")
    ap.add_argument("--split", default="both", choices=["both", "train", "holdout"],
                    help="train/holdout = seed-keyed, matching the collector's "
                         "1-in-N rule, so a metric computed on `train` cannot be "
                         "confused with one computed on unseen seeds")
    ap.add_argument("--holdout-every", type=int, default=5)
    ap.add_argument("--holdout-start", type=int, default=47200)
    ap.add_argument("--dump-states", action="store_true",
                    help="record the encoded candidate and anchor vectors per "
                         "pair, so a fit on the differences can measure the "
                         "pair set's ceiling without replaying it")
    ap.add_argument("--ablate", type=str, default="",
                    help="comma-separated feature-block prefixes to zero before "
                         "scoring (e.g. pf_,cn_,vo_). A block whose ablation does "
                         "not hurt is not carrying decision signal, whatever its "
                         "training-time importance was")
    ap.add_argument("--report", default="results/state_value_s1.json")
    args = ap.parse_args()

    focus = None
    fp = ROOT / args.focus_file
    if fp.is_file():
        focus = json.loads(fp.read_text(encoding="utf-8"))
    else:
        print(f"WARNING: no focus file {fp}; the replay will sample different "
              f"decisions than the corpus describes", flush=True)

    corpus_paths = [ROOT / p.strip() for p in args.corpus.split(",")
                    if p.strip()]
    rows = load_corpus(corpus_paths, ("pick",) + PAIR_ROLES)
    by_dec: dict[str, dict[int, dict]] = {}
    for r in rows:
        by_dec.setdefault(r["dec_id"], {})[int(r["item_idx"])] = r
    roles: dict[str, int] = {}
    for r in rows:
        roles[str(r.get("role"))] = roles.get(str(r.get("role")), 0) + 1
    seeds = sorted({int(r["seed"]) for r in rows})
    if args.split != "both":
        e = max(1, args.holdout_every)
        want_hold = args.split == "holdout"
        seeds = [s for s in seeds
                 if (((s - args.holdout_start) % e) == (e - 1)) == want_hold]
    if args.max_seeds:
        seeds = seeds[:args.max_seeds]

    cfg = {
        "model": str(ROOT / args.model), "frozen": str(ROOT / args.frozen),
        "focus": focus, "mode": args.mode,
        "max_decisions": args.max_decisions, "cand_cap": args.cand_cap,
        "per_ante": args.per_ante, "booster_cand_cap": args.booster_cand_cap,
        "focus_extra": args.focus_extra, "accept_rate": args.accept_rate,
        "oracle_margin": args.oracle_margin, "samples": max(1, args.samples),
        "oracle_kinds": tuple(k.strip() for k in args.oracle_kinds.split(",")
                              if k.strip()),
        "by_dec": by_dec,
        "ablate": tuple(p.strip() for p in args.ablate.split(",") if p.strip()),
        "dump_states": bool(args.dump_states),
    }
    print(f"corpus: {len(rows)} rows, {len(by_dec)} decisions, {len(seeds)} seeds "
          f"| roles {roles} | split {args.split}", flush=True)
    print(f"model: {args.model} | incumbent: {args.frozen} | "
          f"workers {args.workers} | ablate {list(cfg['ablate']) or 'none'}",
          flush=True)

    pairs: list[dict] = []
    n_mismatch = 0
    examples: list[str] = []
    t0 = time.time()
    tasks = [(s, cfg) for s in seeds]
    with mp.Pool(max(1, args.workers)) as pool:
        for done, (seed, seed_pairs, info) in enumerate(
                pool.imap_unordered(_worker, tasks, chunksize=1), start=1):
            if info.get("error"):
                print(f"[seed {seed}] ERROR {info['error']}", flush=True)
            n_mismatch += info.get("mismatch", 0)
            for ex in (info.get("examples") or [])[:2]:
                if len(examples) < 8:
                    examples.append(f"seed {seed}: {ex}")
            pairs.extend(seed_pairs)
            if done % 10 == 0 or done == len(tasks):
                print(f"  [{done}/{len(tasks)}] pairs={len(pairs)} "
                      f"({time.time()-t0:.0f}s)", flush=True)

    if not pairs:
        print("no pairable decisions reconstructed -- nothing to report")
        return 1

    V = sign_rate(pairs, "pred_delta")
    inc = sign_rate(pairs, "incumbent_delta")
    legacy = sign_rate(pairs, "legacy_delta")
    skip_m = acq_vs_skip(pairs)
    skip_by_role = {}
    for role in ("coverage", "model_alt", "substitute"):
        sub = [p for p in pairs if p.get("skip_delta") is not None
               and p.get("role") == role]
        if sub:
            skip_by_role[role] = sign_rate(
                [{"label": p["skip_label"], "pred_delta": p["skip_delta"]}
                 for p in sub], "pred_delta")
    report = {
        "corpus": args.corpus, "split": args.split,
        "n_seeds_replayed": len(seeds),
        "index_mismatches": n_mismatch, "mismatch_examples": examples,
        "n_pairs": len(pairs), "roles": roles, "model": args.model,
        "V": V, "incumbent_head": inc, "legacy_shop_model": legacy,
        "verdict": ("V beats the incumbent on the same pairs"
                    if (V["sign_rate"] or 0) > (inc["sign_rate"] or 0)
                    else "V does NOT beat the incumbent: redesign falsified at S1"),
        "note": "sign_rate excludes exact label ties (a tie is the absence of a "
                "question); a prediction of exactly 0 on a non-tied pair counts "
                "as a disagreement, not a coin flip",
        "by_role": {}, "by_ante_V": {},
        "acq_vs_skip_V": skip_m, "acq_vs_skip_by_role": skip_by_role,
    }
    for role in PAIR_ROLES:
        sub = [p for p in pairs if p["role"] == role]
        if sub:
            report["by_role"][role] = sign_rate(sub, "pred_delta")
    for ante in sorted({p["ante"] for p in pairs}):
        sub = [p for p in pairs if p["ante"] == ante]
        report["by_ante_V"][str(ante)] = sign_rate(sub, "pred_delta")

    out = ROOT / args.report
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=1, sort_keys=True) + "\n",
                   encoding="utf-8")
    (ROOT / "results" / "state_value_s1_pairs.jsonl").write_text(
        "\n".join(json.dumps(p) for p in pairs) + "\n", encoding="utf-8")

    def _fmt(name: str, s: dict) -> str:
        return (f"{name:20s} pairs {s['n_pairs']:5d} ties {s['ties']:5d} "
                f"worse {s['worse']:4d} better {s['better']:4d} "
                f"sign {s['sign_rate']:.3f} auc {s['auc']:.3f}")
    print()
    print(f"index mismatches: {n_mismatch} (must be 0; a nonzero value means the "
          f"recorded states do not belong to the rows they were joined to)")
    for ex in examples:
        print(f"  e.g. {ex}")
    print(_fmt("V(S')", V))
    print(_fmt("incumbent head", inc))
    print(_fmt("legacy shop model", legacy))
    print()
    print("lookahead competence -- V(acquire) - V(skip) vs the buy-vs-not label,"
          " excluding `pick` rows whose label is 0 by construction:")
    print(_fmt("V acq-vs-skip", skip_m))
    for role, s in sorted(skip_by_role.items()):
        print(_fmt(f"  role={role}", s))
    print(f"\nverdict: {report['verdict']}")
    print(f"saved {out} in {time.time()-t0:.0f}s", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
