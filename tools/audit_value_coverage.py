"""audit_value_coverage.py — what has actually been MEASURED, and what has not.

WHY
===
The requirement is that jokers, tarots, spectrals, planets, bosses, tags, hand
types and packs have their values *learned in each scenario*, not asserted.
That is only checkable if the uncovered remainder is enumerable, so this tool
turns "is it all covered?" into a number and a work order.

WHAT IT DOES
============
1. Enumerates the scenario grid: every catalogue item x ante 1-8 x support
   bucket 0-2 (support = how many owned jokers share a role with the item,
   i.e. the diminishing-returns dimension).
2. Reads the fitted artifact's cell table and asks, per cell, how much
   evidence backs it (`n_effective`, which walks up the hierarchy).
3. Reports the evidence required for a cell to be meaningful, derived from the
   data rather than typed:

       required_n = (residual_sd / min_detectable_effect) ** 2

   i.e. the sample count at which the standard error of a cell mean is no
   larger than the smallest effect worth acting on. The recorded MDE is the
   return difference of one ante step, because the model's own return function
   is denominated in antes (`value_tables.RETURN_WIN_BONUS == TOTAL_ANTES`).
4. Emits `--focus-out` JSON: the uncovered cells weighted by how far short they
   fall, ready to feed `tools/collect_decisions.py --focus-file`.

USAGE
=====
    python tools/audit_value_coverage.py
    python tools/audit_value_coverage.py --focus-out results/coverage_focus.json
    python tools/audit_value_coverage.py --per-antes 1,2,3   # narrow the grid
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "vendor" / "balatro-rl"))

from balatro_sim import catalogue as CAT      # noqa: E402
from balatro_sim import value_tables as VT    # noqa: E402

# Minimum effect worth resolving, in return units (antes). One ante step is the
# natural resolution: the return function is denominated in antes.
MIN_DETECTABLE_EFFECT = 1.0

# Kinds that are *acquired* and therefore occupy (item x scenario) cells.
# Bosses and tags are deliberately excluded: a boss is never bought, it is the
# environment a decision happens in, so it enters the model as parsed boss
# flags (context) and a per-boss residual — not as an item cell. Counting them
# here would report a permanently uncoverable 156 cells and make the headline
# coverage number meaningless.
PURCHASABLE_KINDS = ("joker", "tarot", "spectral", "planet", "voucher",
                     "pack", "card")
CONTEXT_KINDS = ("boss", "tag")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="vendor/balatro-rl/balatro_sim/value_tables.json")
    ap.add_argument("--focus-out", default="")
    ap.add_argument("--per-antes", default="1,2,3,4,5,6,7,8")
    ap.add_argument("--kinds", default=",".join(PURCHASABLE_KINDS),
                    help="comma-separated kinds to grid (default: purchasable "
                         "items only; bosses/tags are context, not items)")
    ap.add_argument("--top", type=int, default=25)
    ap.add_argument("--budget-runs", type=int, default=250,
                    help="how many runs one collection iteration is worth. A "
                         "cell that cannot reach required_n within this budget "
                         "is supply-limited, not under-collected, and is "
                         "excluded from the work order in favour of its pooled "
                         "key-level evidence.")
    ap.add_argument("--census", default="",
                    help="offer_census.json from tools/offer_census.py. With it, "
                         "cells are weighted by how often the agent is actually "
                         "offered the item, and cells never offered are reported "
                         "as unreachable instead of as coverage debt.")
    args = ap.parse_args()

    # How often each key|ante is actually offered, per run. Without a census
    # every cell counts equally, which spends the same budget on a voucher seen
    # in 0 of 300 runs as on a joker seen every run.
    offer_rate: dict[str, float] = {}
    census_runs = 0
    if args.census:
        cpath = ROOT / args.census
        if cpath.exists():
            cdata = json.loads(cpath.read_text(encoding="utf-8"))
            census_runs = int(cdata.get("runs", 0) or 0)
            if census_runs > 0:
                offer_rate = {k: float(v) / census_runs
                              for k, v in (cdata.get("offers") or {}).items()}
            print(f"census               : {args.census} ({census_runs} runs)")
        else:
            print(f"census               : {args.census} NOT FOUND (ignored)")

    table = VT.ValueTable.load(ROOT / args.model)
    if table is None:
        print(f"no model at {args.model} — coverage is 0% by definition")
        resid_sd = 0.0
        residuals: dict = {}
    else:
        resid_sd = table.resid_sd
        residuals = table.residuals

    antes = [int(a) for a in args.per_antes.split(",") if a.strip()]
    kinds = {k.strip() for k in args.kinds.split(",") if k.strip()}

    required_n = (resid_sd / MIN_DETECTABLE_EFFECT) ** 2 if resid_sd > 0 else 0.0

    def n_eff(cell: str) -> float:
        """Evidence available *to the model*, hierarchy included.

        This is the count that governs how much the model shrinks a cell toward
        its parents, so it is the right number for "how well is this predicted".
        It is the wrong number for "has this scenario been measured": an
        item-level row with n=10 covers all eight of its ante cells here.
        """
        for c in [cell, *VT.cell_parents(cell)]:
            row = residuals.get(c)
            if row and float(row.get("n", 0.0)) > 0:
                return float(row["n"])
        return 0.0

    def n_own(cell: str) -> float:
        """Evidence measured IN THIS CELL, with nothing inherited.

        The requirement is that an item's value is learned *in each scenario*,
        so the headline coverage number must not count a parent's rows as this
        cell's evidence. Reported alongside the inherited figure rather than
        replacing it, because both answer real questions.
        """
        row = residuals.get(cell)
        if row and float(row.get("n", 0.0)) > 0:
            return float(row["n"])
        return 0.0

    def buckets_for(key: str) -> tuple[int, ...]:
        """Reachable support buckets for an item.

        Support means "owned jokers sharing a role with this item". Items with
        no roles (tarots, spectrals, planets, vouchers, packs, cards) can only
        ever be at support 0, so gridding them at 1 and 2 would count cells that
        no amount of data can ever fill — inflating the denominator threefold
        and making the reported coverage meaningless.
        """
        it = CAT.item(key)
        return (0, 1, 2) if (it is not None and it.roles) else (0,)

    def rate_of(key: str, ante: int) -> float:
        """Offers per run for this key at this ante (inf when no census)."""
        if not offer_rate:
            return float("inf")
        return offer_rate.get(f"{key}|a{ante}", 0.0)

    # Per-run offer rate at which one iteration could fill this cell. Below it
    # the cell is not "under-collected", it is uncollectable-in-budget: the
    # agent simply is not shown the item often enough. Measured example: a
    # spectral is offered 0.91 times per run across 18 keys, so its 144 ante
    # cells would need ~1,570 runs — six iterations — to each reach 9.9 rows.
    # Reporting those as coverage debt sends the next iteration's whole budget
    # after items it can never resolve.
    fillable_rate = (required_n / max(1, args.budget_runs)) if required_n else 0.0

    kinds_seen: dict[str, dict[str, int]] = {}
    cells: list[tuple[str, str, float]] = []
    unreachable = 0
    supply_limited = 0
    supply_limited_keys: dict[str, int] = {}
    for key in CAT.keys():
        it = CAT.item(key)
        assert it is not None
        if kinds and it.kind not in kinds:
            continue
        bucket = kinds_seen.setdefault(it.kind, {"items": 0, "fine": 0,
                                                "covered": 0, "covered_own": 0})
        bucket["items"] += 1
        for ante in antes:
            for support in buckets_for(key):
                cell = f"{key}|a{ante}|s{support}"
                n = n_eff(cell)
                if n > 0:
                    bucket["fine"] += 1
                if required_n and n >= required_n:
                    bucket["covered"] += 1
                if required_n and n_own(cell) >= required_n:
                    bucket["covered_own"] += 1
                else:
                    # Urgency is measured against THIS cell's own rows: a cell
                    # with none has no scenario-specific value no matter how
                    # strong its parent is, and that is what collection fills.
                    n_for_gap = n_own(cell)
                    shortfall = ((required_n - n_for_gap) / required_n
                                 if required_n else 1.0)
                    rate = rate_of(key, ante)
                    if offer_rate and rate <= 0.0:
                        # Nobody is offered it, so no budget can fill it. This is
                        # a reportable fact about the item, not coverage debt.
                        unreachable += 1
                        continue
                    if offer_rate and rate < fillable_rate:
                        # Offered, but too rarely to resolve per ante in one
                        # iteration. Its value has to come from the key-level
                        # (pooled) row, which the shrinkage hierarchy does
                        # anyway — so measure it there instead.
                        supply_limited += 1
                        supply_limited_keys[key] = supply_limited_keys.get(key, 0) + 1
                        continue
                    # Frequency in [0,1]: an item offered at least once per run
                    # carries full urgency; a rare one carries proportional
                    # urgency, so budget follows where decisions happen.
                    w = max(0.0, shortfall) * min(1.0, rate)
                    cells.append((key, cell, w))

    total_cells = 0
    covered = 0
    covered_own = 0
    reachable_cells = 0
    reachable_covered = 0
    reachable_covered_own = 0
    for key in CAT.keys():
        it = CAT.item(key)
        if it is None or (kinds and it.kind not in kinds):
            continue
        for ante in antes:
            for support in buckets_for(key):
                cell = f"{key}|a{ante}|s{support}"
                total_cells += 1
                ok = bool(required_n and n_eff(cell) >= required_n)
                ok_own = bool(required_n and n_own(cell) >= required_n)
                covered += 1 if ok else 0
                covered_own += 1 if ok_own else 0
                if not offer_rate or rate_of(key, ante) > 0.0:
                    reachable_cells += 1
                    reachable_covered += 1 if ok else 0
                    reachable_covered_own += 1 if ok_own else 0

    print("=== VALUE COVERAGE ===")
    print(f"model                : {args.model}")
    print(f"catalogue            : {CAT.fingerprint()} "
          f"({len(CAT.keys())} items)")
    print(f"residual_sd          : {resid_sd:.3f}")
    print(f"min detectable effect: {MIN_DETECTABLE_EFFECT} ante")
    print(f"required n per cell  : {required_n:.1f}")
    print(f"grid                 : {total_cells} cells "
          f"({len(antes)} antes x reachable support buckets x purchasable "
          f"items; support is a joker-only dimension, so non-joker kinds "
          f"contribute {len(antes)} cells each)")
    print(f"covered (inherited)  : {covered} "
          f"({(100.0 * covered / total_cells) if total_cells else 0.0:.1f}%) "
          f"<- predicts this cell, but may borrow its parent's rows")
    print(f"covered (own rows)   : {covered_own} "
          f"({(100.0 * covered_own / total_cells) if total_cells else 0.0:.1f}%) "
          f"<- the scenario itself was measured (the headline number)")
    if offer_rate:
        pct = (100.0 * reachable_covered / reachable_cells) if reachable_cells else 0.0
        pct_own = (100.0 * reachable_covered_own / reachable_cells) if reachable_cells else 0.0
        print(f"covered (reachable)  : {reachable_covered}/{reachable_cells} "
              f"({pct:.1f}%) inherited | {reachable_covered_own} "
              f"({pct_own:.1f}%) own rows  <- the denominator budgets can fill")
        print(f"never offered        : {unreachable} cells excluded from the "
              f"work order — no amount of collection fills an item the agent "
              f"is never shown")
        kcov = 0
        for key in supply_limited_keys:
            row = residuals.get(key)
            if required_n and row and float(row.get("n", 0.0)) >= required_n:
                kcov += 1
        print(f"supply-limited       : {supply_limited} cells across "
              f"{len(supply_limited_keys)} keys offered < "
              f"{fillable_rate:.3f}/run — cannot be filled in "
              f"{args.budget_runs} runs; {kcov}/{len(supply_limited_keys)} of "
              f"those keys ARE covered at key level (pooled across antes)")
    print("\nby kind (items / cells w/ any inherited evidence / covered inherited"
          " / covered own):")
    for kind, b in sorted(kinds_seen.items()):
        print(f"  {kind:9} {b['items']:4} / {b['fine']:5} / {b['covered']:5} "
              f"/ {b['covered_own']:5}")
    print(f"context-only kinds (not item cells): {', '.join(CONTEXT_KINDS)}")
    for ck in CONTEXT_KINDS:
        extra = (" + `item|boss:<key>` scenario cells (see above)"
                 if ck == "boss" else "")
        print(f"  {ck:9} {len(CAT.keys(ck)):4} keys — scored via parsed "
              f"flags + per-key residual{extra}")

    cells.sort(key=lambda t: -t[2])
    print(f"\nlargest gaps (of {len(cells)} uncovered cells):")
    for key, cell, short in cells[:args.top]:
        print(f"  {cell:28} shortfall {short:.2f}")

    # ── scenario cells (item x boss / item x hand type) ─────────────────────
    # These are the "learned in each scenario" cells beyond ante. They are
    # reported and targeted separately because they are NOT a property of the
    # shop offer: a decision's boss is whatever the sim pre-selected and its
    # hand type is whatever the run has invested in, so collection can only aim
    # at them through the ITEM. A cell with no rows therefore puts its item on
    # the work order under `key|scenario`, which `_focus_score` reads.
    scn_cells: dict[str, list[str]] = {"boss": [], "hand": []}
    scn_covered: dict[str, int] = {"boss": 0, "hand": 0}
    scn_gap: dict[str, float] = {}
    skipped_thin: set[str] = set()
    for c, row in residuals.items():
        dim = "boss" if "|boss:" in c else ("hand" if "|hand:" in c else None)
        if dim is None:
            continue
        n = float(row.get("n", 0.0))
        scn_cells[dim].append(c)
        if required_n and n >= required_n:
            scn_covered[dim] += 1
            continue
        key = c.split("|")[0]
        short = ((required_n - n) / required_n) if required_n else 1.0
        # Scenario gaps are only worth budget on items that are ALREADY
        # measured at key level. A scenario cell is a property of the RUN the
        # decision happened in (the pre-selected boss, the hand the run has
        # invested in), not of the shop offer, so collection cannot steer it: a
        # decision is forced on the ITEM and the scenario is whatever the run
        # happens to be in. Forcing on an item whose key-level row is also thin
        # would spend the iteration on cells no budget can resolve, which is the
        # exact failure the supply-limited filter above exists to prevent.
        krow = residuals.get(key)
        k_n = float(krow.get("n", 0.0)) if krow else 0.0
        if required_n and k_n < required_n:
            skipped_thin.add(key)
            continue
        # Capped below FOCUS_FORCE_AT (=1.0) on purpose: a scenario gap should
        # bias which of an item's decisions get taken, never force one, because
        # the scenario it needs is not something the collector chooses.
        scn_gap[key] = max(scn_gap.get(key, 0.0), min(0.5, short))
    print(f"\nscenario cells (item x boss / item x hand type,\n"
          f"pooled across antes; required n {required_n:.1f}):")
    for dim in ("boss", "hand"):
        tot = len(scn_cells[dim])
        cov = scn_covered[dim]
        print(f"  {dim:5} {cov:5}/{tot:5} covered "
              f"({(100.0 * cov / tot) if tot else 0.0:.1f}%)")
    if scn_gap:
        print(f"  {len(scn_gap)} items with adequate key-level evidence are short "
              f"on a scenario cell -> work-order bias as `key|scenario` "
              f"(capped below the force threshold: the scenario is a property "
              f"of the run, not of the offer)")
    if skipped_thin:
        print(f"  {len(skipped_thin)} more items are short on a scenario cell AND "
              f"thin at key level; their scenario cells are deferred until the "
              f"key row is measurable")

    if args.focus_out:
        focus = {"model": args.model, "catalogue": CAT.fingerprint(),
                 "required_n": required_n, "cells": {}}
        for key, short in scn_gap.items():
            focus["cells"][f"{key}|scenario"] = {"weight": short}
        for key, cell, short in cells:
            short_key = "|".join(cell.split("|")[:2])  # collector focuses on key+ante
            prev = focus["cells"].get(short_key, {}).get("weight", 0.0)
            focus["cells"][short_key] = {"weight": max(prev, short)}
        out = ROOT / args.focus_out
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(focus, indent=1, sort_keys=True) + "\n",
                       encoding="utf-8")
        # Also record the keys with zero evidence, so the collector can FORCE
        # decisions that offer them instead of hoping the sampling coin lands.
        zero_ev_keys: dict[str, float] = {}
        for key, cell, short in cells:
            if short >= 1.0:
                zero_ev_keys[key] = max(zero_ev_keys.get(key, 0.0), short)
        focus["zero_evidence_keys"] = zero_ev_keys
        focus["scenario_gap_keys"] = scn_gap
        out.write_text(json.dumps(focus, indent=1, sort_keys=True) + "\n",
                       encoding="utf-8")
        print(f"\nfocus work order -> {out} ({len(focus['cells'])} cells, "
              f"{len(zero_ev_keys)} keys with zero evidence, "
              f"{len(scn_gap)} items short on scenario evidence)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
