"""bench/bench_v11_ablation.py — paired ablation of V11 components vs V10.

Runs `search_shop_v10` and one or more `search_shop_v11` variants (each a set
of V11_PARAMS overrides) over the same deterministic seed bank, in seed mode,
and prints a per-variant paired comparison (wins, ante-1 deaths, mean ante,
econ, jokers bought/sold) plus the win/loss flips against the baseline.

Human-fair by construction: identical to bench_agent_v10.py, only the V11
experiment flags differ.

Usage:
  python bench/bench_v11_ablation.py --seeds 10500-10599 --variants default,no_vn,no_squeeze
  python bench/bench_v11_ablation.py --seeds 10500-10599 --variant-json '{"vn0":{"v11_vn_weight":0.0}}'
"""
from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import os
import sys
import time
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parent.parent
VENDOR = ROOT / "vendor" / "balatro-rl"
sys.path.insert(0, str(VENDOR))

from balatro_sim.agent_v10 import SearchShopV10          # noqa: E402
from balatro_sim.agent_v11 import SearchShopV11         # noqa: E402
from balatro_sim.game import BalatroGame                # noqa: E402
from balatro_sim.rollout import rollout                 # noqa: E402

# Named V11 ablation arms. `default` is the shipped configuration.
#
# V12 arms carry `_policy: "v12"` so `_run_one` builds a SearchShopV12 (frozen
# V10 search + learned-value oracle). They are screened against `__v10__`
# because V12's whole claim is "same search, better object choice", and the
# paired gained/lost column is what decides it.
V12_BASE = {"_policy": "v12", "v12_oracle": True, "v12_mode": "override",
            "v12_head": "relative", "v12_z": 2.0, "v12_kinds": ("joker",)}
VARIANTS: dict[str, dict] = {
    "default": {},
    # ── V12 learned-oracle arms ─────────────────────────────────────────
    "v12_rel_z2": dict(V12_BASE),
    "v12_rel_z1": {**V12_BASE, "v12_z": 1.0},
    "v12_rel_z3": {**V12_BASE, "v12_z": 3.0},
    "v12_abs_z2": {**V12_BASE, "v12_head": "absolute"},
    "v12_allkinds_z2": {**V12_BASE, "v12_kinds": ("joker", "tarot",
                                                  "spectral", "planet")},
    # ── V12 prior arms: the learned head breaks only the search's near-ties ──
    # Margin is in the frozen ranker's OWN value units (measured top-value
    # median 0.15, within-shop spread median 0.03). m0 is "exact ties only",
    # NOT a no-op: the ranker ties in ~a quarter of shops, and an 8-seed probe
    # showed m0 already substituting 5 times and moving 2/8 seeds. The sweep is
    # therefore a dose-response in margin, with the flag-level arm as the real
    # parity control.
    # Exact ties only (measured NOT to be identity — see note above).
    "v12_prior_m0": {**V12_BASE, "v12_mode": "prior",
                     "v12_prior_margin": 0.0,
                     "v12_kinds": ("joker", "tarot", "spectral", "planet",
                                   "voucher")},
    "v12_prior_m02": {**V12_BASE, "v12_mode": "prior",
                      "v12_prior_margin": 0.02,
                      "v12_kinds": ("joker", "tarot", "spectral", "planet",
                                    "voucher")},
    "v12_prior_m05": {**V12_BASE, "v12_mode": "prior",
                      "v12_prior_margin": 0.05,
                      "v12_kinds": ("joker", "tarot", "spectral", "planet",
                                    "voucher")},
    "v12_prior_m10": {**V12_BASE, "v12_mode": "prior",
                      "v12_prior_margin": 0.10,
                      "v12_kinds": ("joker", "tarot", "spectral", "planet",
                                    "voucher")},
    "v12_prior_jokers_m05": {**V12_BASE, "v12_mode": "prior",
                             "v12_prior_margin": 0.05,
                             "v12_kinds": ("joker",)},
    # Band arms: same margin, but never substitute on an EXACT ranker tie.
    # Rationale is measured in agent_v12.V12_DEFAULTS['v12_prior_band']:
    # exact-tie pairs differ in measured return 36% of the time versus 57% for
    # pairs the ranker separated by < 0.01, so the tie end of the window is the
    # least informative place to intervene. These arms hold the margin fixed and
    # change ONLY that, so the comparison isolates the firing domain.
    "v12_prior_band_m02": {**V12_BASE, "v12_mode": "prior",
                           "v12_prior_margin": 0.02, "v12_prior_band": True,
                           "v12_kinds": ("joker", "tarot", "spectral",
                                         "planet", "voucher")},
    "v12_prior_band_m05": {**V12_BASE, "v12_mode": "prior",
                           "v12_prior_margin": 0.05, "v12_prior_band": True,
                           "v12_kinds": ("joker", "tarot", "spectral",
                                         "planet", "voucher")},
    # Rank with the frozen V10 shop-ranker instead of the V11 ranker.
    "shop_v10_rank": {"v11_shop_v10_rank": True},
    # Disable the Value Network delta term only.
    "no_vn": {"v11_vn_weight": 0.0},
    # Disable each remaining V11 component individually.
    "no_seq": {"v11_seq_plan": False},
    "no_squeeze": {"v11_squeeze": False},
    "no_boosters": {"v11_boosters": False},
    "no_filters": {"v11_filters": False},
    "no_pack_bonus": {"v11_pack_bonus": False},
    "no_growth": {"v11_growth": 0.0},
    "no_swap_limit": {"v11_swap_limit": False},
    # Late-game xMult conversion (stale +mult/chips/scaling -> xMult finisher).
    "convert5": {"v11_xmult_convert_ante": 5},
    "convert6": {"v11_xmult_convert_ante": 6},
    "convert7": {"v11_xmult_convert_ante": 7},
    "convert5_multi": {"v11_xmult_convert_ante": 5,
                       "v11_convert_multi_swap": True},
    # Full delegation of the shop loop + everything else off = V10 exactly.
    "pure_v10": {"v11_shop_v10_full": True},
    # Exactly V10: V11 shop loop bypassed AND every V11 component off.
    "x1_control": {
        "v11_shop_v10_full": True, "v11_squeeze": False,
        "v11_boosters": False, "v11_pack_bonus": False, "v11_growth": 1.0,
        "v11_filters": False, "v11_vn_weight": 0.0, "v11_seq_plan": False,
    },
    # V10 shop loop, V11 in-blind squeeze off (isolates the booster change).
    "x3_v10shop_nosq": {"v11_shop_v10_full": True, "v11_squeeze": False},
    # V11 but open-slot jokers bypass save-mode / worth_spending gating.
    "x4_open_exempt": {"v11_open_joker_exempt": True},
    # V11 in-blind squeeze alone, on the V10 shop loop.
    "x5_v10shop_only": {"v11_shop_v10_full": True, "v11_boosters": False},
    # --- L1 delegation: the frozen V10 counterfactual swap search on top of
    # _v10_decide_shop (the +3-win component `v11_shop_v10_full` bypasses). ---
    # Pure V10 parity control through V11 (NO V11-only economic override, so
    # this must reproduce `search_shop_v10` exactly).
    "l1_parity": {
        "v11_shop_v10_l1": True, "v11_squeeze": False, "v11_boosters": False,
        "v11_pack_bonus": False, "v11_growth": 1.0, "v11_filters": False,
        "v11_vn_weight": 0.0, "v11_seq_plan": False,
        "v11_interest_target": None, "v11_save_strong_value": None,
        "v11_xmult_convert_hook": False, "v11_swap_limit": False,
    },
    # The SHIPPED configuration after the regression fix (Component G was
    # measured and rejected at n=300, so it is dormant here too).
    "shipped": {
        "v11_shop_v10_l1": True, "v11_squeeze": False, "v11_boosters": False,
        "v11_pack_bonus": False, "v11_growth": 1.0, "v11_filters": False,
        "v11_vn_weight": 0.0, "v11_seq_plan": False,
        "v11_interest_target": None, "v11_save_strong_value": None,
        "v11_xmult_convert_hook": False, "v11_swap_limit": False,
    },
    # --- Component I: additive open-slot counterfactual search ---
    "oss02": {"_l1_base": True, "v11_open_slot_search": True,
              "v11_open_slot_threshold": 0.02},
    "oss05": {"_l1_base": True, "v11_open_slot_search": True,
              "v11_open_slot_threshold": 0.05},
    "oss10": {"_l1_base": True, "v11_open_slot_search": True,
              "v11_open_slot_threshold": 0.10},
    "oss20": {"_l1_base": True, "v11_open_slot_search": True,
              "v11_open_slot_threshold": 0.20},
    # Pure V10 + the V11 in-blind squeezing / booster rules.
    "l1_v11hand": {
        "v11_shop_v10_l1": True, "v11_pack_bonus": False,
        "v11_growth": 1.0, "v11_filters": False, "v11_vn_weight": 0.0,
        "v11_seq_plan": False,
    },
    # Pure V10 + the late-game xMult conversion hook.
    "l1_convert5": {
        "v11_shop_v10_l1": True, "v11_squeeze": False, "v11_boosters": False,
        "v11_pack_bonus": False, "v11_growth": 1.0, "v11_filters": False,
        "v11_vn_weight": 0.0, "v11_seq_plan": False,
        "v11_xmult_convert_ante": 5,
    },
    "l1_convert6": {
        "v11_shop_v10_l1": True, "v11_squeeze": False, "v11_boosters": False,
        "v11_pack_bonus": False, "v11_growth": 1.0, "v11_filters": False,
        "v11_vn_weight": 0.0, "v11_seq_plan": False,
        "v11_xmult_convert_ante": 6,
    },
    "l1_convert5_multi": {
        "v11_shop_v10_l1": True, "v11_squeeze": False, "v11_boosters": False,
        "v11_pack_bonus": False, "v11_growth": 1.0, "v11_filters": False,
        "v11_vn_weight": 0.0, "v11_seq_plan": False,
        "v11_xmult_convert_ante": 5, "v11_convert_multi_swap": True,
    },
    # --- Early-game survival candidates on the V10-delegating base. ---
    # Runs that die in antes 2-3 die with 4.0 jokers and $5.7 on hand; V10's
    # engineless-urgency shop bias currently stops at ante 2.
    "urg3": {"_l1_base": True, "engineless_urgency_ante": 3},
    "urg4": {"_l1_base": True, "engineless_urgency_ante": 4},
    "reroll3": {"_l1_base": True, "reroll_max": 3},
    # Early deaths reroll only 0.2 times per run because the reroll gate needs
    # max(cost, reroll_min_money=$6) on hand; they die holding ~$5.7.
    "rmin4": {"_l1_base": True, "reroll_min_money": 4},
    "urg3_rmin4": {"_l1_base": True, "engineless_urgency_ante": 3,
                   "reroll_min_money": 4},
    "urg3_convert5": {"_l1_base": True, "engineless_urgency_ante": 3,
                      "v11_xmult_convert_ante": 5},
    # --- Component G/H: blind-honest desperation + in-blind salvage. ---
    # Verified failure mode (10510/10501/10511): the agent banks ~$13 and
    # rerolls <=2 times in the shop before an Ante-3 Big Blind it cannot beat
    # (3,000 target vs ~1,300 forecast), then burns all discards on single-card
    # value farming and dies holding the cash.
    "l1_desp": {"_l1_base": True, "v11_desperate": True},
    "l1_salv": {"_l1_base": True, "v11_salvage": True},
    "l1_both": {"_l1_base": True, "v11_desperate": True,
                "v11_salvage": True},
    "l1_both15": {"_l1_base": True, "v11_desperate": True,
                  "v11_salvage": True, "v11_desperate_margin": 1.5},
    "l1_both12": {"_l1_base": True, "v11_desperate": True,
                  "v11_salvage": True, "v11_desperate_margin": 1.2},
    "l1_desp_rr12": {"_l1_base": True, "v11_desperate": True,
                     "v11_salvage": True, "v11_desperate_rerolls": 12},
    # --- Component G: mid-game interest floor (the one measured-positive
    # knob on the 100-seed screen; reroll widening lost 2 wins each). ---
    "l1_int20": {"_l1_base": True, "v11_interest_target": 20},
    "l1_int15": {"_l1_base": True, "v11_interest_target": 15},
    "l1_int12": {"_l1_base": True, "v11_interest_target": 12},
    "l1_int15_sv02": {"_l1_base": True, "v11_interest_target": 15,
                      "v11_save_strong_value": 0.2},
    # --- Exploration sweep: which knobs actually move the win rate? ---
    # `_actp`/`_v10p` are EXPERIMENT-ONLY runtime overrides of the frozen
    # V9/V10 globals (agent_v10.py on disk is never edited). A winning knob is
    # re-implemented inside agent_v11.py.
    "sw_reroll4": {"_l1_base": True, "_actp": {"reroll_max": 4}},
    "sw_reroll6": {"_l1_base": True, "_actp": {"reroll_max": 6}},
    "sw_rmin3": {"_l1_base": True, "_actp": {"reroll_min_money": 3}},
    "sw_int15": {"_l1_base": True, "_actp": {"interest_target": 15}},
    "sw_int5": {"_l1_base": True, "_actp": {"interest_target": 5}},
    "sw_sv02": {"_l1_base": True, "_actp": {"save_strong_value": 0.2}},
    "sw_sm15": {"_l1_base": True, "_actp": {"save_margin": 1.5}},
    "sw_farm80": {"_l1_base": True, "_v10p": {"farm_clear_threshold": 0.80}},
    "sw_combo": {"_l1_base": True,
                 "_actp": {"reroll_max": 6, "reroll_min_money": 3,
                           "interest_target": 15}},
    # Everything non-V10 off at once (V11 shop loop still active).
    "all_off": {
        "v11_vn_weight": 0.0,
        "v11_seq_plan": False,
        "v11_squeeze": False,
        "v11_boosters": False,
        "v11_filters": False,
        "v11_pack_bonus": False,
        "v11_growth": 1.0,
        "v11_swap_limit": False,
    },
}


# Pure frozen-V10 parity through V11: every V11 component off AND no V11-only
# economic override, so this arm must reproduce `search_shop_v10`.
L1_BASE = {
    "v11_shop_v10_l1": True, "v11_squeeze": False, "v11_boosters": False,
    "v11_pack_bonus": False, "v11_growth": 1.0, "v11_filters": False,
    "v11_vn_weight": 0.0, "v11_seq_plan": False,
    "v11_interest_target": None, "v11_save_strong_value": None,
    "v11_xmult_convert_hook": False, "v11_swap_limit": False,
}


def _resolve(name: str) -> dict:
    p = dict(VARIANTS[name])
    base = p.pop("_l1_base", False)
    if base:
        merged = dict(L1_BASE)
        merged.update(p)
        return merged
    return p


def _apply_runtime_params(p: dict) -> None:
    """EXPERIMENT-ONLY: push `_v10p` / `_actp` overrides into the frozen V10/V9
    module globals so the exploration sweep can measure which knobs move the
    win rate. agent_v10.py/agent_v9.py on disk are untouched; a winning knob is
    then re-implemented properly inside agent_v11.py."""
    if not p:
        return
    from balatro_sim import agent_v9, agent_v10
    for k, v in (p.get("_v10p") or {}).items():
        agent_v10.V10_PARAMS[k] = v
    for k, v in (p.get("_actp") or {}).items():
        agent_v9.ACTIVE_PARAMS[k] = v
        agent_v10.ACTIVE_PARAMS[k] = v


def _run_one(job) -> dict:
    variant, seed, rng_mode = job
    resolved = {} if variant == "__v10__" else _resolve(variant)
    _apply_runtime_params(resolved)
    game = BalatroGame(seed=seed, rng_mode=rng_mode)
    if variant == "__v10__":
        policy = SearchShopV10()
    elif resolved.get("_policy") == "v12":
        from balatro_sim.agent_v12 import SearchShopV12
        policy = SearchShopV12(params=resolved)
    else:
        policy = SearchShopV11(params=resolved)
    r = rollout(game, policy)
    r["seed"] = seed
    r["variant"] = variant
    return r


def _agg(results: list[dict]) -> dict:
    n = len(results)
    wins = sum(1 for r in results if r["won"])
    a1 = sum(1 for r in results if not r["won"] and r["ante"] <= 1)
    st = [r.get("stats") or {} for r in results]
    return {
        "n": n,
        "wins": wins,
        "win_rate": 100.0 * wins / n,
        "ante1_deaths": a1,
        "mean_ante": mean(r["ante"] for r in results),
        "mean_dollars": mean(r["dollars"] for r in results),
        "spent": mean(s.get("money_spent", 0) for s in st),
        "econ": mean(s.get("econ_source", 0) for s in st),
        "interest": mean(s.get("interest_collected", 0) for s in st),
        "rerolls": mean(s.get("rerolls", 0) for s in st),
        "bought": mean(len(s.get("jokers_bought", [])) for s in st),
        "sold": mean(len(s.get("jokers_sold", [])) for s in st),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", default="10500-10599",
                    help="Seed range like '10500-10599'")
    ap.add_argument("--variants", default="default",
                    help="Comma-separated arm names (" + ", ".join(VARIANTS) + ")")
    ap.add_argument("--variant-json", default=None,
                    help="Extra arm as JSON: '{\"name\": {...V11_PARAMS...}}'")
    ap.add_argument("--workers", type=int, default=max(1, os.cpu_count() or 1))
    ap.add_argument("--no-v10", action="store_true",
                    help="Skip the V10 baseline arm (reuse nothing)")
    ap.add_argument("--v10-from", default=None,
                    help="Reuse the search_shop_v10 results from a paired-bench "
                         "sidecar JSON instead of re-running the baseline arm")
    ap.add_argument("--out", default=None, help="Write raw JSON here")
    args = ap.parse_args()

    if args.variant_json:
        VARIANTS.update(json.loads(args.variant_json))

    lo, hi = (int(x) for x in args.seeds.split("-"))
    seeds = list(range(lo, hi + 1))
    arms = [a.strip() for a in args.variants.split(",") if a.strip()]
    for a in arms:
        if a not in VARIANTS:
            sys.exit(f"unknown variant {a!r}; have {sorted(VARIANTS)}")

    order = ([] if args.no_v10 else ["__v10__"]) + arms
    if args.v10_from:
        order = [a for a in order if a != "__v10__"]
    print(f"ablation: seeds {lo}..{hi} (n={len(seeds)}), workers={args.workers}, arms={order}",
          flush=True)

    results_by_arm: dict[str, list[dict]] = {}
    if args.v10_from and not args.no_v10:
        reused = json.loads(Path(args.v10_from).read_text(encoding="utf-8"))
        if "search_shop_v10" in reused:
            results_by_arm["__v10__"] = reused["search_shop_v10"]["results"]
            print(f"  [__v10__] reused {len(results_by_arm['__v10__'])} runs "
                  f"from {args.v10_from}", flush=True)
    for arm in order:
        t0 = time.perf_counter()
        jobs = [(arm, s, "seed") for s in seeds]
        out: list[dict] = []
        ctx = mp.get_context("spawn")
        with ctx.Pool(args.workers) as pool:
            for r in pool.imap_unordered(_run_one, jobs, chunksize=1):
                out.append(r)
        out.sort(key=lambda r: r["seed"])
        results_by_arm[arm] = out
        agg = _agg(out)
        print(f"  [{arm}] {agg['wins']}/{agg['n']} wins ({agg['win_rate']:.2f}%) | "
              f"a1d {agg['ante1_deaths']} | mean ante {agg['mean_ante']:.2f} | "
              f"spent ${agg['spent']:.1f} | econ ${agg['econ']:.1f} | "
              f"bought {agg['bought']:.1f} sold {agg['sold']:.1f} | "
              f"{time.perf_counter()-t0:.0f}s", flush=True)

    base = results_by_arm.get("__v10__")
    if base:
        bmap = {r["seed"]: r["won"] for r in base}
        print("\npaired vs V10 (flips)")
        print(f"  {'arm':<16} {'wins':>5} {'a1d':>4} {'meanAnte':>9} "
              f"{'gained':>7} {'lost':>5} {'net':>4}")
        for arm in arms:
            rmap = {r["seed"]: r["won"] for r in results_by_arm[arm]}
            gained = sum(1 for s in seeds if rmap[s] and not bmap[s])
            lost = sum(1 for s in seeds if bmap[s] and not rmap[s])
            agg = _agg(results_by_arm[arm])
            print(f"  {arm:<16} {agg['wins']:>5} {agg['ante1_deaths']:>4} "
                  f"{agg['mean_ante']:>9.2f} {gained:>7} {lost:>5} {gained-lost:>+4}")

    if args.out:
        Path(args.out).write_text(json.dumps(results_by_arm, indent=1, default=str),
                                  encoding="utf-8")
        print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
