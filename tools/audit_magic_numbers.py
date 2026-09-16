"""tools/audit_magic_numbers.py — the provenance gate for the learned-model stack.

WHY
===
The heuristic stack carried ~111 tunable knobs and ~20 hand-written numeric
dicts. The value model must not re-acquire that debt quietly, so this gate
refuses to let a *named* numeric constant into the new stack unless the ledger
records where its value came from and why.

WHAT IT CHECKS
==============
1. Every module-level numeric constant (including numbers nested in module
   level dict/list/tuple literals) in the target files must have a ledger
   entry in ``tools/value_model_constants.json`` whose recorded ``value``
   matches, with a ``kind`` of:
       spec-derived — copied from a generated spec file
       fitted       — produced by fitting on collected data
       structural   — a pure code-shape constant (index, sentinel, clip bound)
       measured     — an empirical measurement from a named bench
   A stale value (code changed, ledger not) is an error, not a warning:
   that is exactly the silent-drift failure this gate exists to stop.
2. The target files must not import the legacy curated tables
   (ECON_JOKERS / XMULT_JOKERS / DEAD_ECONOMY_JOKERS / PREMIER_XMULT_FINISHERS
   / ...). Those belong to the frozen baselines; the new stack derives its
   item features from ``balatro_sim/catalogue.py``.

In-function literals are listed for visibility but not failed: they are
dominated by index arithmetic (`[0]`, `hand[:5]`). The failure mode this gate
targets is a *tunable* constant, and those live at module level.

USAGE
=====
    python tools/audit_magic_numbers.py            # gate (exit 1 on failure)
    python tools/audit_magic_numbers.py --report   # show everything found
    python tools/audit_magic_numbers.py --write    # seed/refresh ledger entries

``--write`` records new constants with kind ``UNREVIEWED`` so they still fail
the gate until a human (or an agent) states the provenance. It never invents
provenance.
"""
from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

DEFAULT_TARGETS = (
    "vendor/balatro-rl/balatro_sim/catalogue.py",
    "vendor/balatro-rl/balatro_sim/value_tables.py",
    "vendor/balatro-rl/balatro_sim/agent_v12.py",
    "tools/collect_decisions.py",
    "tools/fit_value_model.py",
    "tools/audit_value_coverage.py",
)

LEDGER = ROOT / "tools" / "value_model_constants.json"

VALID_KINDS = ("spec-derived", "fitted", "structural", "measured")

# Legacy curated tables the new stack must not depend on. Matched as bare
# import names or attribute targets.
FORBIDDEN_IMPORTS = (
    "ECON_JOKERS", "XMULT_JOKERS", "SCALING_JOKERS", "CHIPS_JOKERS",
    "FLAT_MULT_JOKERS", "RETRIGGER_JOKERS", "CONSUMABLE_JOKERS",
    "TAROTGEN_JOKERS", "DECK_CONDITIONS", "BAD_BOSSES", "PACK_VALUE",
    "VOUCHER_PRIORITY", "RELIABLE_XMULT_JOKERS", "HIGH_LEVERAGE_SCORING_JOKERS",
    "PREMIER_XMULT_FINISHERS", "DEAD_ECONOMY_JOKERS", "EARLY_FLAT_CHIPS_JOKERS",
    "COMBAT_SCALING_JOKERS", "PORTFOLIO_XMULT", "PORTFOLIO_FLAT",
    "PORTFOLIO_SCALING", "PORTFOLIO_ECON", "PORTFOLIO_CHIPS",
    "PORTFOLIO_RETRIGGER", "LATE_CONVERT_KEEP", "HAND_SPECIFIC_JOKERS",
)

_NUMERIC = (ast.Constant,)


def _is_num(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) \
        and not isinstance(node.value, bool)


def _collect_numbers(node: ast.AST) -> list[ast.Constant]:
    """Numeric constants nested anywhere under `node` (excluding strings)."""
    out: list[ast.Constant] = []
    for sub in ast.walk(node):
        if _is_num(sub):
            out.append(sub)  # type: ignore[arg-type]
    return out


def _target_name(t: ast.AST) -> str | None:
    if isinstance(t, ast.Name):
        return t.id
    if isinstance(t, ast.Attribute):
        return t.attr
    if isinstance(t, ast.Subscript):
        return None
    return None


def module_constants(path: Path) -> tuple[list[dict], list[dict]]:
    """Return (named_constants, in_function_literals) for one file."""
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src, filename=str(path))
    named: list[dict] = []
    in_func: list[dict] = []

    def record_named(name: str, node: ast.AST, lineno: int, container: str) -> None:
        for c in _collect_numbers(node):
            named.append({
                "name": name, "value": c.value, "line": lineno,
                "container": container,
            })

    for node in tree.body:
        if isinstance(node, ast.Assign):
            for t in node.targets:
                nm = _target_name(t)
                if nm:
                    if _is_num(node.value):
                        record_named(nm, node.value, node.lineno, "scalar")
                    elif isinstance(node.value, (ast.Dict, ast.List, ast.Tuple)):
                        record_named(nm, node.value, node.lineno,
                                     type(node.value).__name__.lower())
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            nm = _target_name(node.target)
            if nm:
                if _is_num(node.value):
                    record_named(nm, node.value, node.lineno, "scalar")
                elif isinstance(node.value, (ast.Dict, ast.List, ast.Tuple)):
                    record_named(nm, node.value, node.lineno,
                                 type(node.value).__name__.lower())

    # Informational: numeric literals inside function bodies.
    for fn in [n for n in ast.walk(tree)
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
        for c in _collect_numbers(fn):
            in_func.append({"line": c.lineno, "value": c.value, "fn": fn.name})
    return named, in_func


def forbidden_imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    hits: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for a in node.names:
                if a.name in FORBIDDEN_IMPORTS:
                    hits.append(f"{path.name}: from ... import {a.name} (line {node.lineno})")
        elif isinstance(node, ast.Import):
            for a in node.names:
                base = a.name.rsplit(".", 1)[-1]
                if base in FORBIDDEN_IMPORTS:
                    hits.append(f"{path.name}: import {a.name} (line {node.lineno})")
    return hits


def load_ledger() -> dict:
    if not LEDGER.exists():
        return {"_doc": "Provenance for numeric constants in the learned-value "
                        "stack. Kinds: spec-derived | fitted | structural | measured.",
                "constants": {}}
    return json.loads(LEDGER.read_text(encoding="utf-8"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--files", nargs="*", default=list(DEFAULT_TARGETS))
    ap.add_argument("--report", action="store_true", help="list all literals found")
    ap.add_argument("--write", action="store_true",
                    help="seed ledger entries for new constants (kind UNREVIEWED)")
    args = ap.parse_args()

    ledger = load_ledger()
    known: dict = ledger.setdefault("constants", {})

    missing: list[str] = []
    stale: list[str] = []
    unreviewed: list[str] = []
    bad_kind: list[str] = []
    bad_imports: list[str] = []
    total_named = 0
    present_files = 0

    for rel in args.files:
        path = ROOT / rel
        if not path.exists():
            continue
        present_files += 1
        named, in_func = module_constants(path)
        total_named += len(named)
        seen: set[str] = set()
        for c in named:
            base = f"{rel}::{c['name']}@L{c['line']}"
            # A dict/list literal carries several numbers, so each VALUE needs
            # its own accountable entry: a single key per container would let
            # a second number slip in behind the first one's provenance.
            # Container keys deliberately omit the line number, so they stay
            # valid when unrelated edits shift the literal down the file.
            entry_key = (base if c["container"] == "scalar"
                         else f"{rel}::{c['name']}::{c['value']}")
            seen.add(entry_key)
            entry = known.get(entry_key)
            if entry is None:
                entry = known.get(base) or known.get(f"{rel}::{c['name']}")
            if entry is None:
                missing.append(f"{entry_key} = {c['value']} ({c['container']})")
                if args.write:
                    known[entry_key] = {
                        "value": c["value"], "kind": "UNREVIEWED",
                        "note": "auto-seeded; state provenance to pass the gate",
                    }
                else:
                    continue
                continue
            if (entry.get("values") is None
                    and entry.get("value") != c["value"]):
                stale.append(f"{entry_key}: ledger {entry.get('value')} != code {c['value']}")
            if isinstance(entry.get("values"), list) \
                    and c["value"] not in entry["values"]:
                stale.append(f"{entry_key}: {c['value']} not in ledger values")
            kind = entry.get("kind", "")
            if kind == "UNREVIEWED":
                unreviewed.append(entry_key)
            elif kind not in VALID_KINDS:
                bad_kind.append(f"{entry_key}: kind={kind!r}")
        bad_imports.extend(forbidden_imports(path))

        if args.report:
            print(f"— {rel}: {len(named)} module-level constants, "
                  f"{len(in_func)} in-function literals")
            for c in named:
                print(f"    L{c['line']:>4} {c['name']} = {c['value']} ({c['container']})")
            for c in in_func[:40]:
                print(f"      (fn {c['fn']}, L{c['line']}) {c['value']}")
            if len(in_func) > 40:
                print(f"      ... {len(in_func) - 40} more in-function literals")

    if args.write:
        LEDGER.write_text(json.dumps(ledger, indent=1, sort_keys=True) + "\n",
                          encoding="utf-8")
        print(f"ledger written: {LEDGER}")

    print(f"\n=== MAGIC-NUMBER GATE ===")
    print(f"files checked        : {present_files}")
    print(f"module constants     : {total_named}")
    print(f"unledgered           : {len(missing)}")
    print(f"stale ledger entries : {len(stale)}")
    print(f"UNREVIEWED           : {len(unreviewed)}")
    print(f"invalid kinds        : {len(bad_kind)}")
    print(f"forbidden imports    : {len(bad_imports)}")

    for label, rows in (("UNLEDGERED", missing), ("STALE", stale),
                        ("UNREVIEWED", unreviewed), ("BAD KIND", bad_kind),
                        ("FORBIDDEN IMPORT", bad_imports)):
        for r in rows:
            print(f"  [{label}] {r}")

    ok = not (missing or stale or unreviewed or bad_kind or bad_imports)
    print("GATE: CLEAN" if ok else "GATE: FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
