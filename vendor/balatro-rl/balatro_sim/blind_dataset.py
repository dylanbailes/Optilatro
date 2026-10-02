from __future__ import annotations

import hashlib
import json
import math
import os
import platform
import random
import time
from collections import Counter
from contextlib import contextmanager
from copy import deepcopy
from itertools import combinations
from pathlib import Path
from statistics import mean, variance

from . import agent_v9 as V9
from . import agent_v10 as V10
from .card import Card
from .eval_encoder import encode_state, schema
from .eval_metrics import SPLIT_PROTOCOL, SELECTION_RULE, split_world_trials
from .game import State
from .hand_eval import evaluate_hand
from .rollout import clone_game
from .seed_rng import make_source


VERSION = 1
SAMPLER_VERSION = "canonical-observable-undrawn-v1"
SPLIT_VERSION = "sha256-v14-split-v1-80-10-10"
INTERFACE = {
    "candidate": "list of {action: full engine action dict, source: string}; anchor first; full JSON payload dedupe preserves index order",
    "steps": "total engine steps including forced action; max_steps >= 1; terminal auxiliary shares this cap",
    "horizons": "reach root ante + 1, + 2, + 3; targets beyond ante 8 masked null; censored unresolved targets null",
    "terminal": "anchor only; ante-8 boss ROUND_EVAL is exact win with final_ante=9 and dense=17",
    "policy": "fresh HeuristicV10 per trial; reset parameter dictionaries to defaults plus explicit overrides; main trajectory retains instance state",
    "domain": "Red Deck, White Stake, antes 1..8; no flipped cards in any pile or flipped jokers; non-play/discard anchors excluded",
    "coupling": "shared sampled world per index is a coupling proposal, not a common-random-number guarantee",
    "coverage": "finite noisy reference pool, not exhaustive legal-action oracle; tied boundary fractional inclusion",
    "resume": "only newline-terminated seed_complete transactions are committed; terminated incomplete seeds discarded; unterminated lines refused without mutation; config and fingerprints must match",
    "evaluation": "split_world_parity_v1; K >= 2; even indices select, odd indices evaluate; no same-world fallback; sub-K10 estimates remain noisy",
}


class UnsupportedRoot(ValueError):
    pass


class BudgetExceeded(TimeoutError):
    pass


class HiddenObservation(RuntimeError):
    pass


def check_budget(deadline=None):
    if deadline is not None and time.monotonic() >= deadline:
        raise BudgetExceeded("time_budget")


def hidden_observation(game):
    return bool(
        game.jokers_flipped
        or any(getattr(j, "flipped", False) for j in game.jokers)
        or any(c.flipped for pile in (game.hand, game.deck, game.spent) for c in pile)
    )


class GuardedH10(V10.HeuristicV10):
    def decide(self, game):
        if hidden_observation(game):
            raise HiddenObservation("hidden_observation")
        if game.state == State.SHOP:
            return V10.SearchShopV10()._search_shop(game)
        if game.state == State.BOOSTER_OPEN:
            return V10._v10_decide_booster(game)
        return super().decide(game)


@contextmanager
def policy_scope(params=None):
    active, v10 = deepcopy(V9.ACTIVE_PARAMS), deepcopy(V10.V10_PARAMS)
    counter = Card._counter
    continuation = V10._CONT_POLICY
    running_present = hasattr(V10._v10_sampled_pick, "_running")
    running = getattr(V10._v10_sampled_pick, "_running", False)
    try:
        V9.ACTIVE_PARAMS.clear()
        V9.ACTIVE_PARAMS.update(deepcopy(V9.PARAMS))
        V10.V10_PARAMS.clear()
        V10.V10_PARAMS.update(deepcopy(V10.V10_DEFAULTS))
        if params:
            V9.ACTIVE_PARAMS.update(deepcopy(params))
            V10.V10_PARAMS.update(deepcopy(params))
        V10._CONT_POLICY = GuardedH10()
        V10._v10_sampled_pick._running = False
        yield
    finally:
        V9.ACTIVE_PARAMS.clear()
        V9.ACTIVE_PARAMS.update(active)
        V10.V10_PARAMS.clear()
        V10.V10_PARAMS.update(v10)
        V10._CONT_POLICY = continuation
        if running_present:
            V10._v10_sampled_pick._running = running
        else:
            delattr(V10._v10_sampled_pick, "_running")
        Card._counter = counter


def action_key(action):
    return json.dumps(action, sort_keys=True, separators=(",", ":"), allow_nan=False)


def card_key(game, card):
    return (
        card.rank, card.suit, card.enhancement, card.edition, card.seal,
        bool(card.debuffed), bool(card.flipped), getattr(card, "bonus_chips", 0),
        card.id in game.ante_played_ids, card is game.bell_card,
    )


def sample_world(game, seed):
    if hidden_observation(game):
        raise UnsupportedRoot("hidden_root")
    world = clone_game(game)
    world.deck.sort(key=lambda card: card_key(world, card))
    random.Random(str(seed)).shuffle(world.deck)
    world.rng = make_source(str(seed), "seed")
    return world


def root_reason(game, anchor=None):
    if game.state != State.SELECTING_HAND:
        return "not_selecting_hand"
    if not 1 <= game.ante <= 8 or getattr(game, "deck_config", "red") != "red":
        return "unsupported_domain"
    if hidden_observation(game):
        return "hidden_root"
    if not math.isfinite(game.current_blind.chips_target) or game.current_blind.chips_target <= 0:
        return "invalid_target"
    if anchor is not None:
        if not isinstance(anchor, dict) or anchor.get("type") not in ("play", "discard"):
            return "unsupported_anchor"
        if not legal_action(game, anchor):
            return "invalid_anchor"
    return None


def legal_action(game, action):
    kind = action.get("type")
    indices = action.get("cards", [])
    if kind not in ("play", "discard") or not isinstance(indices, (list, tuple)):
        return False
    if not 1 <= len(indices) <= 5 or any(type(i) is not int or not 0 <= i < len(game.hand) for i in indices):
        return False
    if len(set(indices)) != len(indices):
        return False
    if kind == "discard":
        return game.discards_left > 0
    if game.hands_left <= 0:
        return False
    boss = game.current_blind.boss_key if game._boss_effects_on() else ""
    if boss == "bl_psychic" and len(indices) != 5:
        return False
    cards = [game.hand[i] for i in indices]
    ht, _ = evaluate_hand(cards)
    return bool(V9._boss_play_filter(game, indices, ht, cards, boss))


def candidate_actions(game, anchor, extended=False, *, policy_params=None):
    reason = root_reason(game, anchor)
    if reason:
        raise UnsupportedRoot(reason)
    with policy_scope(policy_params):
        fork = sample_world(game, "v14:candidates")
        candidates, seen = [], set()
        def add(action, source):
            key = action_key(action)
            if key not in seen and legal_action(fork, action):
                candidates.append({"action": deepcopy(action), "source": source})
                seen.add(key)
        add(anchor, "anchor")
        plays = V9.scored_plays(fork, topk=8)
        for _, combo, _ in plays:
            add({"type": "play", "cards": list(combo)}, "scored_play")
        if fork.discards_left > 0:
            discard, _ = V9.best_discard(fork)
            if discard:
                add({"type": "discard", "cards": list(discard)}, "discard_ev")
            ranked = sorted(range(len(fork.hand)), key=lambda i: (V9._card_quality(fork.hand[i]), i))
            for size in (1, 3, 5):
                add({"type": "discard", "cards": ranked[:size]}, "discard_quality")
        if not any(a["action"]["type"] == "play" for a in candidates):
            for size in range(1, min(5, len(fork.hand)) + 1):
                found = False
                for combo in combinations(range(len(fork.hand)), size):
                    action = {"type": "play", "cards": list(combo)}
                    if legal_action(fork, action):
                        add(action, "legal_play_fallback")
                        found = True
                        break
                if found:
                    break
        full = candidates
        candidates = full[:8]
        kinds = {entry["action"]["type"] for entry in candidates}
        if len(kinds) == 1:
            alternative = next((entry for entry in full[8:] if entry["action"]["type"] not in kinds), None)
            if alternative is not None:
                candidates[-1] = alternative
        seen = {action_key(entry["action"]) for entry in candidates}
        if extended:
            for entry in full:
                add(entry["action"], "extended_" + entry["source"])
            for _, combo, _ in V9.scored_plays(fork, topk=32):
                add({"type": "play", "cards": list(combo)}, "extended_scored_play")
            for i in range(len(fork.hand)):
                add({"type": "play", "cards": [i]}, "extended_single")
                if fork.discards_left > 0:
                    add({"type": "discard", "cards": [i]}, "extended_discard_single")
            types = set()
            for size in range(1, min(5, len(fork.hand)) + 1):
                for combo in combinations(range(len(fork.hand)), size):
                    cards = [fork.hand[i] for i in combo]
                    ht, _ = evaluate_hand(cards)
                    action = {"type": "play", "cards": list(combo)}
                    if ht not in types and legal_action(fork, action):
                        add(action, "extended_hand_type")
                        types.add(ht)
            if fork.discards_left > 0:
                for combo in combinations(range(len(fork.hand)), 2):
                    add({"type": "discard", "cards": list(combo)}, "extended_discard_pair")
                for combo, _ in V10._value_discard_candidates(fork, fork.hand):
                    add({"type": "discard", "cards": list(combo)}, "extended_discard_value")
        return candidates


def _exact_win(game):
    return bool(
        (game.state == State.GAME_OVER and game.ante > 8)
        or (game.state == State.ROUND_EVAL and game.ante == 8 and game.blind_idx == 2)
    )


def _terminal(game, root_ante, censored):
    won = _exact_win(game)
    final_ante = 9 if won else game.ante
    horizons = []
    for delta in (1, 2, 3):
        target = root_ante + delta
        horizons.append(None if target > 8 else True if final_ante >= target else None if censored else False)
    return {
        "won": won, "final_ante": final_ante, "dense": final_ante + 8 * int(won),
        "horizons": horizons, "censored": bool(censored),
    }


def _trial(world, action, seed, max_steps, terminal, params, deadline, sample_index):
    target, root_ante, root_blind = world.current_blind.chips_target, world.ante, world.blind_idx
    start_dollars = world.dollars
    result = {"seed": str(seed), "sample_index": sample_index, "state": None, "clear": None, "surplus": None,
              "score": world.chips_scored, "target": target, "steps": 0, "censored": True, "terminal": None}
    with policy_scope(params):
        policy = GuardedH10()
        try:
            check_budget(deadline)
            world.step(deepcopy(action))
            result["steps"] = 1
            result["state"] = encode_state(world)
            while True:
                if world.state == State.ROUND_EVAL or _exact_win(world):
                    result.update(clear=True, censored=False)
                    break
                if world.state == State.GAME_OVER:
                    result.update(clear=False, censored=False)
                    break
                if hidden_observation(world):
                    result["censor_reason"] = "hidden_observation"
                    break
                if (world.ante, world.blind_idx) != (root_ante, root_blind) or world.state != State.SELECTING_HAND:
                    result["censor_reason"] = "unexpected_phase"
                    break
                if result["steps"] >= max_steps:
                    result["censor_reason"] = "max_steps"
                    break
                check_budget(deadline)
                world.step(policy.decide(world))
                result["steps"] += 1
            result["score"] = world.chips_scored
            if not result.get("censored", False) and result["clear"] is not None:
                if result["clear"]:
                    ratio = min(4.0, world.chips_scored / max(1.0, float(target)))
                    dollars_delta = max(0.0, float(world.dollars - start_dollars))
                    result["surplus"] = (
                        math.log2(1.0 + ratio)
                        + 0.25 * float(world.hands_left)
                        + 0.10 * dollars_delta
                    )
                else:
                    ratio = min(1.0, world.chips_scored / max(1.0, float(target)))
                    result["surplus"] = -(1.0 - ratio)
            if terminal:
                reason = result.get("censor_reason")
                while not reason and world.state != State.GAME_OVER and not _exact_win(world):
                    if hidden_observation(world):
                        reason = "hidden_observation"
                        break
                    if result["steps"] + result.get("terminal_steps", 0) >= max_steps:
                        reason = "max_steps"
                        break
                    check_budget(deadline)
                    world.step(policy.decide(world))
                    result["terminal_steps"] = result.get("terminal_steps", 0) + 1
                result["terminal"] = _terminal(world, root_ante, bool(reason))
                if reason:
                    result["terminal_censor_reason"] = reason
        except BudgetExceeded:
            raise
        except Exception as exc:
            reason = "hidden_observation" if isinstance(exc, HiddenObservation) else "error:" + type(exc).__name__
            if result["state"] is None:
                raise
            if result["clear"] is None:
                result.update(censored=True, censor_reason=reason, score=world.chips_scored)
            if terminal:
                result["terminal"] = _terminal(world, root_ante, True)
                result["terminal_censor_reason"] = reason
    return result


def collect_decision(game, anchor, seeds, max_steps=100, terminal=False, *, extended=False,
                     independent=False, policy_params=None, deadline=None, reuse_arms=None):
    reason = root_reason(game, anchor)
    if reason:
        raise UnsupportedRoot(reason)
    if type(max_steps) is not int or max_steps < 1:
        raise ValueError("max_steps must be positive")
    seeds = [str(seed) for seed in seeds]
    if len(seeds) < 2 or any(not seed for seed in seeds) or len(seeds) != len(set(seeds)):
        raise ValueError("at least 2 distinct nonempty seeds required for disjoint world halves")
    candidates = candidate_actions(game, anchor, extended, policy_params=policy_params)
    reused = {action_key(a["action"]): a for a in (reuse_arms or [])}
    arms = [deepcopy(reused[action_key(candidate["action"])]) if action_key(candidate["action"]) in reused
            else dict(candidate, trials=[]) for candidate in candidates]
    for k, seed in enumerate(seeds):
        check_budget(deadline)
        shared = None if independent else sample_world(game, seed)
        for arm in arms:
            if action_key(arm["action"]) in reused:
                continue
            check_budget(deadline)
            actual_seed = seed
            if independent:
                actual_seed = seed + ":independent:" + hashlib.sha256(action_key(arm["action"]).encode()).hexdigest()
            world = sample_world(game, actual_seed) if independent else clone_game(shared)
            trial = _trial(world, arm["action"], actual_seed, max_steps,
                           terminal and arm["source"] == "anchor", policy_params, deadline, k)
            arm["trials"].append(trial)
    return arms


def seed_split(seed):
    if type(seed) is not int:
        raise ValueError("seed must be int")
    bucket = int.from_bytes(hashlib.sha256(f"{SPLIT_VERSION}:{seed}".encode()).digest()[:8], "big") % 10
    return "test" if bucket == 9 else "validation" if bucket == 8 else "train"


def trajectory_step(game, policy, seed, decision_id, seeds, *, counters=None, coupling_probe=False, **kwargs):
    counters = counters if counters is not None else Counter()
    check_budget(kwargs.get("deadline"))
    if hidden_observation(game):
        raise HiddenObservation("hidden_trajectory")
    action = policy.decide(game)
    row = None
    if game.state == State.SELECTING_HAND:
        counters["roots_seen"] += 1
        reason = root_reason(game, action)
        if reason:
            counters["excluded:" + reason] += 1
        else:
            try:
                primary_kwargs = dict(kwargs, extended=False)
                arms = collect_decision(game, action, seeds, **primary_kwargs)
                row = {"version": VERSION, "seed": seed, "decision_id": decision_id,
                       "split": seed_split(seed), "ante": game.ante, "blind_idx": game.blind_idx,
                       "anchor": 0, "arms": arms}
                if kwargs.get("extended"):
                    reference = collect_decision(game, action, seeds, **dict(kwargs, reuse_arms=arms))
                    row["coverage_arms"] = reference
                    row["coverage"] = coverage_report(arms, reference)
                if coupling_probe:
                    probe_kwargs = dict(primary_kwargs, independent=True, terminal=False)
                    independent = collect_decision(game, action, seeds, **probe_kwargs)
                    row["coupling"] = coupling_report(arms, independent)
                    row["independent_arms"] = independent
                counters["decisions"] += 1
                for arm in arms:
                    for trial in arm["trials"]:
                        counters["trials"] += 1
                        if trial["censored"]:
                            counters["censored:" + trial.get("censor_reason", "unknown")] += 1
                        if trial.get("terminal_censor_reason"):
                            counters["terminal_censored:" + trial["terminal_censor_reason"]] += 1
            except BudgetExceeded:
                raise
            except Exception as exc:
                row = None
                counters["error:" + type(exc).__name__] += 1
    game.step(action)
    return row


def _usable(trial):
    return type(trial.get("clear")) is bool and not trial.get("censored", False)


def coverage_report(restricted, reference):
    keys = {action_key(arm["action"]) for arm in restricted}
    values = []
    excluded = 0
    for arm in reference:
        trials = arm["trials"]
        if not trials or not all(_usable(t) for t in trials):
            excluded += 1
            continue
        values.append((mean(int(t["clear"]) for t in trials), action_key(arm["action"])))
    values.sort(reverse=True)
    report = {"noisy_reference_pool": True, "exhaustive_oracle": False,
              "reference_arms": len(reference), "usable_arms": len(values),
              "excluded_censored_arms": excluded, "top1_coverage": None, "top3_coverage": None, "regret": None}
    for k in (1, 3):
        remaining, included = min(k, len(values)), 0.0
        total = remaining
        for value in sorted({v for v, _ in values}, reverse=True):
            tied = [key for v, key in values if v == value]
            take = min(remaining, len(tied))
            included += take * sum(key in keys for key in tied) / len(tied)
            remaining -= take
            if remaining == 0:
                break
        report[f"top{k}_coverage"] = included / total if total else None
    restricted_values = [v for v, key in values if key in keys]
    if restricted_values:
        report["regret"] = values[0][0] - max(restricted_values)
    return report


def coupling_report(shared, independent):
    independent_by_key = {action_key(a["action"]): a for a in independent}
    pairs = []
    if not shared:
        return {"pairs": [], "claim": "empirical coupling probe, not a CRN guarantee"}
    anchor = shared[0]
    for arm in shared[1:]:
        ia = independent_by_key[action_key(anchor["action"])]
        ib = independent_by_key[action_key(arm["action"]) ]
        observations = [(a, b, c, d) for a, b, c, d in zip(anchor["trials"], arm["trials"], ia["trials"], ib["trials"])
                        if all(_usable(t) for t in (a, b, c, d))]
        correlation = ratio = shared_var = independent_var = None
        if len(observations) >= 2:
            x, y, u, v = ([int(row[i]["clear"]) for row in observations] for i in range(4))
            vx, vy = variance(x), variance(y)
            if vx > 0 and vy > 0:
                covariance = sum((a - mean(x)) * (b - mean(y)) for a, b in zip(x, y)) / (len(x) - 1)
                correlation = covariance / math.sqrt(vx * vy)
            shared_var = variance([b - a for a, b in zip(x, y)])
            independent_var = variance([b - a for a, b in zip(u, v)])
            if independent_var > 0:
                ratio = shared_var / independent_var
        pairs.append({"action": arm["action"], "n": len(observations), "outcome_correlation": correlation,
                      "shared_difference_variance": shared_var, "independent_difference_variance": independent_var,
                      "variance_ratio": ratio})
    return {"pairs": pairs, "claim": "empirical coupling probe, not a CRN guarantee"}


def metadata(config, policy_params=None):
    if "samples" in config and (type(config["samples"]) is not int or config["samples"] < 2):
        raise ValueError("samples must be an integer >= 2")
    package = Path(__file__).resolve().parent
    root = package.parents[2]
    paths = list(package.rglob("*.py")) + list(package.glob("*.json"))
    paths += [root / "tools" / "portfolio.py", root / "tools" / "collect_blind_decisions.py"]
    fingerprints = {str(path.relative_to(root)).replace("\\", "/"): hashlib.sha256(path.read_bytes()).hexdigest()
                    for path in sorted(paths) if path.is_file()}
    with policy_scope(policy_params):
        params = {"active": deepcopy(V9.ACTIVE_PARAMS), "v10": deepcopy(V10.V10_PARAMS)}
    return {"type": "metadata", "version": VERSION, "schema": schema(), "policy_params": params,
            "policy_overrides": deepcopy(policy_params or {}), "policy": "heuristic_v10",
            "fingerprints": fingerprints, "config": deepcopy(config), "world_sampler": SAMPLER_VERSION,
            "rng_mode": "seed", "split_version": SPLIT_VERSION, "python": platform.python_version(),
            "seed_manifest": {"start": config.get("seed_start"), "count": config.get("n_seeds"), "freshness": "not audited"},
            "evaluation_protocol": SPLIT_PROTOCOL, "selection_rule": SELECTION_RULE,
            "interfaces": INTERFACE}


class DatasetWriter:
    def __init__(self, path, expected_metadata, resume=False):
        self.path = Path(path)
        self.metadata = json.loads(action_key(expected_metadata))
        self.completed = set()
        self.summaries = []
        if not self.path.parent.is_dir():
            raise ValueError("output parent directory must exist")
        if self.path.exists():
            if not resume:
                raise FileExistsError(self.path)
            self._resume()
        else:
            with self.path.open("x", encoding="utf-8", newline="\n") as stream:
                stream.write(action_key(expected_metadata) + "\n")
                stream.flush()
                os.fsync(stream.fileno())

    def _resume(self, recover=True):
        with self.path.open("rb") as stream:
            raw_header = stream.readline()
            if not raw_header.endswith(b"\n"):
                raise ValueError("unterminated metadata JSONL line")
            try:
                actual = json.loads(raw_header)
            except (ValueError, UnicodeDecodeError) as exc:
                raise ValueError("invalid metadata") from exc
            if actual != self.metadata:
                raise ValueError("incompatible metadata/config/fingerprints")
            committed = stream.tell()
            pending, pending_seed = [], None
            while True:
                raw = stream.readline()
                if not raw:
                    break
                if not raw.endswith(b"\n"):
                    raise ValueError("unterminated trailing JSONL line")
                try:
                    row = json.loads(raw)
                except (ValueError, UnicodeDecodeError):
                    if stream.read():
                        raise ValueError("corrupt nontrailing JSONL")
                    break
                if row.get("type") == "seed_complete":
                    seed = row.get("seed")
                    if type(seed) is not int or seed in self.completed or (pending_seed is not None and seed != pending_seed):
                        raise ValueError("invalid complete seed marker")
                    digest = hashlib.sha256(b"".join(pending)).hexdigest()
                    if row.get("rows") != len(pending) or row.get("sha256") != digest:
                        raise ValueError("complete seed checksum mismatch")
                    self.completed.add(seed)
                    self.summaries.append(row)
                    committed = stream.tell()
                    pending, pending_seed = [], None
                else:
                    seed = row.get("seed")
                    if type(seed) is not int or seed in self.completed or (pending_seed is not None and seed != pending_seed):
                        raise ValueError("interleaved or duplicate partial seed")
                    if row.get("version") != VERSION or row.get("split") != seed_split(seed):
                        raise ValueError("invalid decision row")
                    validate_row(row, self.metadata)
                    pending_seed = seed
                    pending.append(raw)
        self.committed_offset = committed
        if recover:
            with self.path.open("r+b") as stream:
                stream.truncate(committed)

    def write_seed(self, seed, rows, summary):
        if seed in self.completed:
            raise ValueError("seed already complete")
        if type(seed) is not int or any(row.get("seed") != seed or row.get("split") != seed_split(seed) for row in rows):
            raise ValueError("seed/split mismatch")
        decision_ids = [row.get("decision_id") for row in rows]
        if any(type(i) is not int for i in decision_ids) or len(set(decision_ids)) != len(decision_ids):
            raise ValueError("invalid decision ids")
        for row in rows:
            validate_row(row, self.metadata)
        payload = "".join(action_key(row) + "\n" for row in rows).encode("utf-8")
        marker = {"type": "seed_complete", "version": VERSION, "seed": seed, "rows": len(rows),
                  "sha256": hashlib.sha256(payload).hexdigest(), "summary": summary}
        with self.path.open("ab") as stream:
            stream.write(payload)
            stream.write((action_key(marker) + "\n").encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
        self.completed.add(seed)
        self.summaries.append(marker)


def validate_row(row, metadata=None):
    if row.get("version") != VERSION or row.get("split") != seed_split(row.get("seed")):
        raise ValueError("invalid decision row")
    declared = (metadata or {}).get("config", {}).get("samples")
    if declared is not None and (type(declared) is not int or declared < 2):
        raise ValueError("samples must be an integer >= 2")
    pools = [row.get("arms", [])]
    if "independent_arms" in row:
        pools.append(row["independent_arms"])
    if "coverage_arms" in row:
        pools.append(row["coverage_arms"])
    for arms in pools:
        for arm in arms:
            count = len(arm.get("trials", []))
            if declared is not None and count != declared:
                raise ValueError(f"arm trial count {count} != declared samples {declared}")
        _, reason = split_world_trials({"arms": arms})
        if reason:
            raise ValueError("invalid trial sample_index/seed: " + reason)
    return True


def read_dataset(path):
    reader = DatasetWriter.__new__(DatasetWriter)
    reader.path = Path(path)
    reader.completed = set()
    reader.summaries = []
    with reader.path.open("rb") as stream:
        reader.metadata = json.loads(stream.readline())
    if reader.metadata.get("type") != "metadata" or reader.metadata.get("version") != VERSION:
        raise ValueError("invalid metadata")
    reader._resume(recover=False)
    with reader.path.open("rb") as stream:
        stream.readline()
        while stream.tell() < reader.committed_offset:
            row = json.loads(stream.readline())
            if row.get("type") != "seed_complete":
                validate_row(row, reader.metadata)
                yield row
