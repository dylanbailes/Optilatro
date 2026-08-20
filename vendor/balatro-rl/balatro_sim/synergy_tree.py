"""synergy_tree.py — empirical synergy priors learned from run telemetry.

The static affinity graph (graph_v9.py) is derived from effect TEXT. This
module is the LEARNED counterpart: `tools/gen_synergy_tree.py` mines the
per-run telemetry dumped by `bench/bench_v9.py --telemetry-dir` into
`tools/synergy_tree.json`, recording which jokers actually perform together,
which consumables get used productively with which jokers, which hand types
each joker actually fires in, and which card features builds enhance.

The mined tree feeds `agent_v9.joker_value` as a separate term
(`synergy_weight * (empirical_synergy_score - 0.5)` — differential around a
0.5 neutral, so a missing tree contributes exactly 0). Components:

  joker↔joker      — mean pairwise ante-lift of the candidate vs owned jokers
                     (support-smoothed sigmoid)
  joker↔consumable — mean benefit of the candidate with HELD consumables
  joker↔hand       — empirical activation: share of the run's main hand among
                     the candidate's scored hands
  joker↔card       — deck support for the candidate's most-evidenced target
                     feature (rank/suit/enhancement from tarot targeting)

Everything here READS game state + the tree only — zero RNG consumption, zero
mutation — safe for the seed-exact sim and the isolated eval oracle.
"""
from __future__ import annotations

import math
import os
import warnings
from pathlib import Path
from typing import Optional

from .graph_v9 import deck_groups, main_hand

# ════════════════════════════════════════════════════════════════════════════
# Tree loading (lazy, cached; missing tree → neutral 0.5 everywhere)
# ════════════════════════════════════════════════════════════════════════════

_TREE: Optional[dict] = None
_TREE_WARNED = False
#: Per-path cache for explicitly-loaded trees (e.g. per-policy trees).
#: Workers spawn fresh per bench leg, so a re-mined file is picked up per run;
#: within a process each path loads once.
_TREE_CACHE: dict[str, dict] = {}


def _resolve_tree_path() -> Optional[Path]:
    """tools/synergy_tree.json: env override (SYNERGY_TREE), else the repo-root
    tools dir (synergy_tree lives at vendor/balatro-rl/balatro_sim/ →
    parents[3] is the repo root)."""
    env = os.environ.get("SYNERGY_TREE")
    if env:
        p = Path(env)
        if p.exists():
            return p
    cand = Path(__file__).resolve().parents[3] / "tools" / "synergy_tree.json"
    return cand if cand.exists() else None


def load_tree(path: Optional[str] = None) -> dict:
    """The mined synergy tree (cached per process — a long-lived interactive
    process won't pick up a re-mined tree until restart; the bench harness
    spawns fresh workers per leg, so each picks up the latest file). {}
    when absent — the scorer then returns neutral 0.5 for every component,
    so the agent term is exactly 0."""
    global _TREE, _TREE_WARNED
    if path is not None:
        key = str(Path(path).resolve())
        if key not in _TREE_CACHE:
            _TREE_CACHE[key] = _read_tree(Path(path))
        return _TREE_CACHE[key]
    if _TREE is None:
        tree_path = _resolve_tree_path()
        if tree_path is None:
            if not _TREE_WARNED:
                _TREE_WARNED = True
                warnings.warn("synergy_tree: tools/synergy_tree.json not found "
                              "— empirical priors neutral (0.5); run "
                              "tools/gen_synergy_tree.py after a "
                              "--telemetry-dir bench")
            _TREE = {}
        else:
            _TREE = _read_tree(tree_path)
    return _TREE


def _read_tree(path: Path) -> dict:
    import json
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def clear_tree_cache() -> None:
    """Drop all cached trees (default + per-path) — call after re-mining a
    tree in a long-lived process (or between tests that reuse paths)."""
    global _TREE, _TREE_WARNED
    _TREE = None
    _TREE_WARNED = False
    _TREE_CACHE.clear()


# ════════════════════════════════════════════════════════════════════════════
# Wiki synergy prior (the INITIALIZATION matrix, upgraded by the mined tree)
# ════════════════════════════════════════════════════════════════════════════

_PRIOR: Optional[dict] = None
_PRIOR_WARNED = False


def _resolve_prior_path() -> Optional[Path]:
    """tools/wiki_synergy_prior.json: env override (WIKI_PRIOR), else the
    repo-root tools dir."""
    env = os.environ.get("WIKI_PRIOR")
    if env:
        p = Path(env)
        if p.exists():
            return p
    cand = Path(__file__).resolve().parents[3] / "tools" / "wiki_synergy_prior.json"
    return cand if cand.exists() else None


def load_wiki_prior() -> dict:
    """The wiki-scraped synergy prior (cached per process). {} when absent —
    the combined scorer then falls back to the mined tree alone."""
    global _PRIOR, _PRIOR_WARNED
    if _PRIOR is None:
        path = _resolve_prior_path()
        if path is None:
            if not _PRIOR_WARNED:
                _PRIOR_WARNED = True
                warnings.warn("synergy_tree: tools/wiki_synergy_prior.json "
                              "not found — wiki priors neutral (0.5); run "
                              "tools/gen_wiki_prior.py")
            _PRIOR = {}
        else:
            _PRIOR = _read_tree(path)
    return _PRIOR


def clear_prior_cache() -> None:
    """Drop the cached wiki prior (re-scrape / re-test)."""
    global _PRIOR, _PRIOR_WARNED
    _PRIOR = None
    _PRIOR_WARNED = False


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def _sigmoid(lift: float, k: float = 0.7) -> float:
    """Lift → (0,1); 0 lift → 0.5."""
    return 1.0 / (1.0 + math.exp(-k * lift))


def _smoothed(score: float, n: int, floor: int = 3) -> float:
    """Blend a score toward neutral 0.5 by low support (n << floor)."""
    w = n / (n + floor)
    return 0.5 + w * (score - 0.5)


# ════════════════════════════════════════════════════════════════════════════
# Component scores ([0, 1], 0.5 neutral)
# ════════════════════════════════════════════════════════════════════════════

def _pair_score(tree: dict, a: str, b: str) -> float:
    """[0,1] joker↔joker edge weight: sigmoid of the mined ante lift,
    support-smoothed toward 0.5. 0.5 when the pair has no edge."""
    table = tree.get("joker_joker", {})
    edge = table.get(a, {}).get(b)
    if edge is None:
        edge = table.get(b, {}).get(a)
    if edge is None:
        return 0.5
    lift = edge.get("lift_ante", 0.0)
    return _smoothed(_sigmoid(lift), edge.get("n", 0))


def _cons_score(tree: dict, joker: str, consumable: str) -> float:
    """[0,1] joker↔consumable edge weight: sigmoid of the mined mean-ante
    benefit over the edge's EXCLUSIVE baseline (runs owning the joker without
    using the consumable — policy-balanced, stored by the miner), fallback to
    the corpus mean. Support-smoothed. 0.5 when no edge."""
    table = tree.get("joker_consumable", {})
    edge = (table.get(joker, {}) or {}).get(consumable)
    if edge is None:
        return 0.5
    base = edge.get("base_mean_ante")
    if base is None:
        base = tree.get("meta", {}).get("mean_ante", 4.0)
    lift = edge.get("lift_ante")
    if lift is None:  # pre-lift_ante trees (older corpus)
        lift = edge.get("mean_ante", base) - base
    return _smoothed(_sigmoid(lift), edge.get("n", 0))


def _hand_score(tree: dict, key: str, main: str) -> float:
    """[0,1] empirical hand alignment: share of the candidate's scored hands
    that are the run's main hand (0.3 + 0.7·share). 0.5 when the candidate has
    no hand data; 0.2 when the data says it fires on OTHER hands."""
    ht = (tree.get("joker_hand", {}) or {}).get(key) or {}
    if not ht:
        return 0.5
    if main in ht:
        return 0.3 + 0.7 * ht[main].get("share", 0.0)
    return 0.2


def _feature_support(feature: str, game) -> float:
    """[0,1] deck support for ONE card feature (rank_ / suit_ / enh_ / seal_
    / edition_), 0.5 = baseline share. Unknown feature kinds → 0.5."""
    dg = deck_groups(game)
    total = max(1, dg["n"])
    if feature.startswith("rank_"):
        baseline, support = 4 / 52, dg["ranks"].get(int(feature[5:]), 0) / total
    elif feature.startswith("suit_"):
        baseline, support = 0.25, dg["suits"].get(feature[5:], 0) / total
    elif feature.startswith("enh_"):
        baseline, support = 0.0, dg["enhs"].get(feature[4:], 0) / total
    elif feature.startswith("seal_"):
        baseline, support = 0.0, dg["seals"].get(feature[5:], 0) / total
    elif feature.startswith("edition_"):
        baseline, support = 0.0, dg["editions"].get(feature[8:], 0) / total
    else:
        return 0.5
    return _clamp01(0.5 + 0.5 * math.tanh(3.0 * (support - baseline)))


def _card_score(tree: dict, key: str, game) -> float:
    """[0,1] empirical card affinity: deck support for the candidate's
    most-evidenced targeted feature, compared against that feature type's
    baseline share. 0.5 when no card data."""
    ct = (tree.get("joker_card", {}) or {}).get(key) or {}
    if not ct:
        return 0.5
    feature, n = max(ct.items(), key=lambda kv: kv[1])
    return _smoothed(_feature_support(feature, game), n)


# ════════════════════════════════════════════════════════════════════════════
# Blended score
# ════════════════════════════════════════════════════════════════════════════

#: Component blend weights for empirical_synergy_score (all [0,1], 0.5 neutral
#: → the blend is 0.5 neutral too; the agent term uses (score - 0.5)).
EMPIRICAL_WEIGHTS = {"joker": 0.45, "consumable": 0.30,
                     "hand": 0.15, "card": 0.10}


def empirical_synergy(game, key: str, tree=None) -> dict:
    """The four [0,1] empirical components for candidate joker `key` in
    `game` (0.5 neutral each). Pure reads — no RNG, no mutation.
    `tree`: an explicitly-loaded tree (e.g. a per-policy one); None → the
    default tools/synergy_tree.json."""
    if tree is None:
        tree = load_tree()
    if not tree:
        return {"joker": 0.5, "consumable": 0.5, "hand": 0.5, "card": 0.5}
    owned = [j.key for j in game.jokers]
    if owned:
        joker_c = sum(_pair_score(tree, key, o) for o in owned) / len(owned)
    else:
        joker_c = 0.5
    held = list(getattr(game, "consumable_hand", ()) or ())
    if held:
        cons_c = sum(_cons_score(tree, key, c) for c in held) / len(held)
    else:
        cons_c = 0.5
    return {
        "joker": joker_c,
        "consumable": cons_c,
        "hand": _hand_score(tree, key, main_hand(game)),
        "card": _card_score(tree, key, game),
    }


def empirical_synergy_score(game, key: str, tree=None) -> float:
    """Blended [0,1] empirical synergy score (0.5 neutral)."""
    comps = empirical_synergy(game, key, tree)
    return sum(EMPIRICAL_WEIGHTS[k] * comps[k] for k in EMPIRICAL_WEIGHTS)


# ════════════════════════════════════════════════════════════════════════════
# Combined score: wiki prior (initialization) ⊕ mined tree (upgrade)
# ════════════════════════════════════════════════════════════════════════════

#: Component blend weights for combined_synergy_score. Adds `voucher` (the
#: wiki prior knows joker↔voucher edges the miner doesn't mine yet) and
#: renormalizes the empirical blend accordingly.
COMBINED_WEIGHTS = {"joker": 0.40, "consumable": 0.25, "voucher": 0.15,
                    "hand": 0.12, "card": 0.08}


def _prior_strength(prior: dict) -> float:
    """How many mined runs a wiki synergy is worth (pseudo-count)."""
    return float((prior.get("meta") or {}).get("prior_strength", 3.0))


def _wiki_pair_score(prior: dict, a: str, b: str) -> float:
    """[0,1] wiki joker↔joker prior: 1.0 when either page lists the other as
    a synergy, else 0.5 (no info)."""
    table = prior.get("joker_joker", {}) or {}
    if b in table.get(a, {}) or a in table.get(b, {}):
        return 1.0
    return 0.5


def _wiki_cons_score(prior: dict, joker: str, consumable: str) -> float:
    """[0,1] wiki joker↔consumable prior."""
    table = prior.get("joker_consumable", {}) or {}
    if consumable in table.get(joker, {}):
        return 1.0
    return 0.5


def _wiki_voucher_score(prior: dict, joker: str, voucher: str) -> float:
    """[0,1] wiki joker↔voucher prior."""
    table = prior.get("joker_voucher", {}) or {}
    if voucher in table.get(joker, {}):
        return 1.0
    return 0.5


def _pair_edge_support(tree: dict, a: str, b: str) -> int:
    """Mined-support `n` for the joker↔joker edge (0 when absent)."""
    table = tree.get("joker_joker", {}) or {}
    edge = table.get(a, {}).get(b)
    if edge is None:
        edge = table.get(b, {}).get(a)
    return int((edge or {}).get("n", 0))


def _cons_edge_support(tree: dict, joker: str, consumable: str) -> int:
    """Mined-support `n` for the joker↔consumable edge (0 when absent)."""
    edge = ((tree.get("joker_consumable", {}) or {}).get(joker, {}) or {}).get(
        consumable)
    return int((edge or {}).get("n", 0))


def _blend(prior_score: float, has_prior: bool, mined: float, n: int,
           strength: float) -> float:
    """Pseudo-count blend of the wiki prior with the mined score.

    `has_prior` False → leave the mined score untouched. Otherwise the prior
    (prior_score ∈ [0,1]) is the INITIALIZATION and the mined score overrides
    it as support `n` grows.
    """
    if not has_prior:
        return mined
    return (strength * prior_score + n * mined) / (strength + n)


def _hand_edge_support(tree: dict, key: str) -> int:
    """Total mined scored-hand support for `key` (0 when absent)."""
    ht = (tree.get("joker_hand", {}) or {}).get(key) or {}
    return sum(e.get("n", 0) for e in ht.values())


def _card_edge_support(tree: dict, key: str) -> int:
    """Mined card-target support for `key` (the max feature count)."""
    ct = (tree.get("joker_card", {}) or {}).get(key) or {}
    return max(ct.values(), default=0)


def _wiki_hand_score(prior: dict, key: str, game) -> float:
    """[0,1] wiki poker-hand prior vs the run's main/played hands. 0.5 when
    the wiki lists no hands for `key`."""
    hands = (prior.get("joker_hand", {}) or {}).get(key) or {}
    if not hands:
        return 0.5
    main = main_hand(game)
    played = {h for h, c in game.run_hand_counts.items() if c > 0}
    if main in hands:
        return 1.0
    if set(hands) & played:
        return 0.7
    return 0.3


def _wiki_card_score(prior: dict, key: str, game) -> float:
    """[0,1] wiki card prior: the deck's support for the wiki-listed target
    features (best one wins). 0.5 when the wiki lists no features."""
    feats = (prior.get("joker_card", {}) or {}).get(key) or {}
    if not feats:
        return 0.5
    return max((_feature_support(f, game) for f in feats), default=0.5)


def combined_synergy(game, key: str, tree=None, prior=None) -> dict:
    """The five [0,1] synergy components for candidate joker `key` (0.5
    neutral each): joker / consumable / voucher / hand / card each blend the
    wiki prior (initialization) with the mined tree (upgrade) via a
    pseudo-count.

    Pure reads — no RNG, no mutation. With no wiki prior AND no mined tree,
    every component is neutral 0.5.
    """
    if tree is None:
        tree = load_tree()
    if prior is None:
        prior = load_wiki_prior()
    emp = empirical_synergy(game, key, tree)
    s = _prior_strength(prior)
    owned = [j.key for j in game.jokers]
    held = list(getattr(game, "consumable_hand", ()) or ())
    vouchers = list(getattr(game, "vouchers", ()) or ())

    if owned:
        joker_c = sum(
            _blend(1.0, _wiki_pair_score(prior, key, o) > 0.5,
                   _pair_score(tree, key, o),
                   _pair_edge_support(tree, key, o), s)
            for o in owned) / len(owned)
    else:
        joker_c = 0.5

    if held:
        cons_c = sum(
            _blend(1.0, _wiki_cons_score(prior, key, c) > 0.5,
                   _cons_score(tree, key, c),
                   _cons_edge_support(tree, key, c), s)
            for c in held) / len(held)
    else:
        cons_c = 0.5

    if vouchers:
        vou_c = sum(_wiki_voucher_score(prior, key, v)
                    for v in vouchers) / len(vouchers)
    else:
        vou_c = 0.5

    # hand + card: the wiki prior initializes, the mined tree upgrades.
    wiki_hand = _wiki_hand_score(prior, key, game)
    has_hand = bool((prior.get("joker_hand", {}) or {}).get(key))
    hand_c = _blend(wiki_hand, has_hand, emp["hand"],
                    _hand_edge_support(tree, key), s)

    wiki_card = _wiki_card_score(prior, key, game)
    has_card = bool((prior.get("joker_card", {}) or {}).get(key))
    card_c = _blend(wiki_card, has_card, emp["card"],
                    _card_edge_support(tree, key), s)

    return {"joker": joker_c, "consumable": cons_c, "voucher": vou_c,
            "hand": hand_c, "card": card_c}


def combined_synergy_score(game, key: str, tree=None, prior=None) -> float:
    """Blended [0,1] synergy score: the wiki prior initializes joker↔joker /
    joker↔consumable / joker↔voucher edges and the mined tree upgrades them
    (0.5 neutral → the agent's (score - 0.5) term contributes exactly 0 when
    neither prior nor data has an opinion)."""
    comps = combined_synergy(game, key, tree, prior)
    return sum(COMBINED_WEIGHTS[k] * comps[k] for k in COMBINED_WEIGHTS)
