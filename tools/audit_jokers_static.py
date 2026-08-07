"""Static joker-layer audit (Phase 0b of the joker-fidelity program).

Structural gates, each of which must report 0 before the joker layer is
declared clean:

  DUPES  — joker keys registered in 2+ effect modules. Import order
           (economy → scaling → hand_type → misc → chips → mult) decides which
           class is live, so a duplicated key is an invisible behavior lottery.
  DEAD   — registry keys that are neither canonical JOKER_CATALOGUE keys nor
           the target of a canonical alias: never reachable from shop/packs,
           and worse, a *wrong* class can shadow a canonical key (dead classes
           sitting under canonical keys are caught by the TYPE gate instead).
  STUBS  — registered effect classes whose hook methods are all empty
           (pass / docstring-only bodies).
  GAPS   — catalogue keys and spec keys that don't resolve in the registry
           (missing effect or broken alias).
  TYPE   — an effect class whose code contradicts the reference-doc type
           column (e.g. a spec-Chips joker that only touches ctx.mult, or a
           spec-xMult joker that never touches ctx.mult_mult).
  SIG    — a hook override whose arity diverges from the JokerEffect base
           (a wrong signature fails silently at dispatch — AST-checked).
  STATE  — an effect reads inst.state["k"] bare (no .get default) where k is
           neither in the class's state_defaults nor ever written by the
           class: the value may be missing at first read.
  NOSCAN — the sim ENGINE (game/scoring/shop/consumables/tags/envs) still
           scans joker keys (`j.key == "j_x"` / `j.key in ...`) instead of
           querying capability flags. synergy.py is a heuristic planner, not
           the sim engine, and is exempt.

Usage:  python tools/audit_jokers_static.py [--json]
Exit:   0 when all gates are clean, 1 otherwise.
"""
import ast
import json
import re
import sys

sys.path.insert(0, "vendor/balatro-rl")
from balatro_sim.shop import JOKER_CATALOGUE
from balatro_sim.jokers.base import JOKER_REGISTRY
from balatro_sim.jokers import _CANONICAL_JOKER_ALIASES

JOKER_DIR = "vendor/balatro-rl/balatro_sim/jokers"
# Effect modules in import order (jokers/__init__.py import order).
EFFECT_MODULES = ["economy", "scaling", "hand_type", "misc", "chips", "mult"]
SPEC_PATH = "tools/joker_spec.json"

_ASSIGN_RE = re.compile(r'JOKER_REGISTRY\["([a-z0-9_]+)"\]\s*=\s*(\w+)')
_DECOR_RE = re.compile(r'@register_joker\("([a-z0-9_]+)"\)')


def scan_module(name: str):
    """Return {key: class_name} for every registration in one effect module."""
    src = open(f"{JOKER_DIR}/{name}.py", encoding="utf-8", errors="replace").read()
    out = {}
    for key, cls in _ASSIGN_RE.findall(src):
        out[key] = cls
    for key in _DECOR_RE.findall(src):
        out.setdefault(key, "?")
    return out


ENGINE_FILES = [
    "vendor/balatro-rl/balatro_sim/game.py",
    "vendor/balatro-rl/balatro_sim/scoring.py",
    "vendor/balatro-rl/balatro_sim/shop.py",
    "vendor/balatro-rl/balatro_sim/consumables.py",
    "vendor/balatro-rl/balatro_sim/tags.py",
    "vendor/balatro-rl/balatro_sim/env_v5.py",
    "vendor/balatro-rl/balatro_sim/env_v7.py",
    "vendor/balatro-rl/balatro_sim/env_sim.py",
    "vendor/balatro-rl/balatro_sim/env_mp.py",
]

#: Hook name -> positional param count (excluding self/inst) on the base
#: JokerEffect. Parsed from base.py so the table can never drift from the
#: actual protocol.
def _base_hook_arities() -> dict:
    src = open("vendor/balatro-rl/balatro_sim/jokers/base.py",
               encoding="utf-8", errors="replace").read()
    tree = ast.parse(src)
    out = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef) or node.name != "JokerEffect":
            continue
        for fn in node.body:
            if isinstance(fn, ast.FunctionDef) \
                    and (fn.name.startswith("on_") or fn.name.startswith("pre_")):
                out[fn.name] = len(fn.args.args) - 1  # drop self
    return out


def _is_effect_class(node: ast.ClassDef) -> bool:
    return any(isinstance(b, ast.Name)
               and b.id in ("JokerEffect", "_CopyJoker")
               for b in node.bases)


def signature_violations(mods) -> dict:
    """Hook overrides whose positional-arg count diverges from the base.
    Overrides taking *args are the Blueprint/Brainstorm delegators (variadic
    by design) and are skipped."""
    base = _base_hook_arities()
    bad = {}
    for m in mods:
        try:
            tree = ast.parse(open(f"{JOKER_DIR}/{m}.py", encoding="utf-8",
                                  errors="replace").read())
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef) or not _is_effect_class(node):
                continue
            for fn in node.body:
                if not isinstance(fn, ast.FunctionDef) or fn.name not in base:
                    continue
                if fn.args.vararg is not None:   # variadic delegator
                    continue
                n = len(fn.args.args) - 1
                if n != base[fn.name]:
                    bad.setdefault(f"{m}.{node.name}", {})[fn.name] = \
                        f"got {n} params, base has {base[fn.name]}"
    return bad


def state_violations(mods) -> dict:
    """Effects that bare-read inst.state["k"] where k is neither declared in
    state_defaults nor ever written by the class (.get/.setdefault count as
    safe)."""
    bad = {}
    for m in mods:
        try:
            tree = ast.parse(open(f"{JOKER_DIR}/{m}.py", encoding="utf-8",
                                  errors="replace").read())
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            # state_defaults keys declared on the class
            defaults = set()
            for stmt in node.body:
                if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 \
                        and isinstance(stmt.targets[0], ast.Name) \
                        and stmt.targets[0].id == "state_defaults":
                    for k in ast.walk(stmt.value):
                        if isinstance(k, ast.Constant) and isinstance(k.value, str):
                            defaults.add(k.value)
            # subscript keys written / read (bare) / safely .get()
            written, reads, safe = set(), set(), set()
            write_targets = set()      # Subscript ids that are assign targets
            safe_subscripts = set()    # Subscript ids used as .get/.setdefault receiver
            for stmt in ast.walk(node):
                if isinstance(stmt, (ast.Assign, ast.AugAssign)):
                    targets = stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]
                    for t in targets:
                        for sub in ast.walk(t):
                            if isinstance(sub, ast.Subscript):
                                write_targets.add(id(sub))
                if isinstance(stmt, ast.Call) and isinstance(stmt.func, ast.Attribute) \
                        and stmt.func.attr in ("get", "setdefault") \
                        and isinstance(stmt.func.value, ast.Subscript):
                    safe_subscripts.add(id(stmt.func.value))
            for sub in ast.walk(node):
                if not (isinstance(sub, ast.Subscript)
                        and isinstance(sub.value, ast.Attribute)
                        and isinstance(sub.value.value, ast.Name)
                        and sub.value.value.id == "inst"
                        and sub.value.attr == "state"
                        and isinstance(sub.slice, ast.Constant)
                        and isinstance(sub.slice.value, str)):
                    continue
                key = sub.slice.value
                if id(sub) in safe_subscripts:
                    safe.add(key)
                elif id(sub) in write_targets:
                    written.add(key)
                else:
                    reads.add(key)
            for k in sorted(reads - written - safe - defaults):
                bad.setdefault(f"{m}.{node.name}", []).append(k)
    return bad


def noscan_violations() -> dict:
    """Engine-side joker key scans. Matches `.key == "j_..."` and
    `.key in ...` on joker instances (item/pack keys are unaffected)."""
    pat = re.compile(r"\.key\s*(==|in)\s*")
    pat_j = re.compile(r'==\s*["\']j_|\.key\s+in\s+')
    bad = {}
    for path in ENGINE_FILES:
        try:
            lines = open(path, encoding="utf-8", errors="replace").readlines()
        except OSError:
            continue
        for i, line in enumerate(lines, 1):
            if pat.search(line) and pat_j.search(line) and "j_" in line:
                bad.setdefault(path, []).append((i, line.strip()))
    return bad


def find_stub_classes(name: str) -> set:
    """AST-detect classes in a module whose every method body is empty."""
    try:
        tree = ast.parse(open(f"{JOKER_DIR}/{name}.py", encoding="utf-8",
                              errors="replace").read())
    except SyntaxError:
        return set()
    stubs = set()

    def _empty(body: list) -> bool:
        for stmt in body:
            if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant) \
                    and isinstance(stmt.value.value, str):
                continue  # docstring
            if isinstance(stmt, ast.Pass):
                continue
            return False
        return True

    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        methods = [n for n in node.body if isinstance(n, ast.FunctionDef)]
        if not methods:
            continue
        if all(_empty(m.body) for m in methods):
            stubs.add(node.name)
    return stubs


def main() -> int:
    spec = json.load(open(SPEC_PATH, encoding="utf-8")) if __import__("os").path.exists(SPEC_PATH) else {}
    reg = dict(JOKER_REGISTRY)
    aliases = dict(_CANONICAL_JOKER_ALIASES)

    per_module = {m: scan_module(m) for m in EFFECT_MODULES}
    stub_classes = {m: find_stub_classes(m) for m in EFFECT_MODULES}

    # ── DUPES ────────────────────────────────────────────────────────────────
    dupes = {}
    for key in reg:
        mods = [m for m in EFFECT_MODULES if key in per_module[m]]
        if len(mods) > 1:
            dupes[key] = mods
    # Alias targets registered natively under both their own key and via the
    # alias loop are fine — DUPES counts only module-level re-registrations.

    # ── DEAD keys ────────────────────────────────────────────────────────────
    alias_values = set(aliases.values())
    dead = sorted(k for k in reg if k not in JOKER_CATALOGUE and k not in alias_values)

    # ── GAPS (catalogue + spec coverage) ─────────────────────────────────────
    def resolve(key):
        return key if key in reg else aliases.get(key) if aliases.get(key) in reg else None

    missing_cat = sorted(k for k in JOKER_CATALOGUE if resolve(k) is None)
    missing_spec = sorted(k for k in spec if resolve(k) is None)
    broken_aliases = sorted(a for a, t in aliases.items() if t not in reg)

    # ── STUBS (registered classes that are all-empty) ───────────────────────
    stubs = {}
    for m in EFFECT_MODULES:
        for key, cls in per_module[m].items():
            if cls != "?" and cls in stub_classes[m]:
                stubs.setdefault(key, []).append(f"{m}.{cls}")

    # ── TYPE gate ────────────────────────────────────────────────────────────
    # spec type → expected mutation attr(s) in the class source.
    type_expect = {
        # bonus_chips: Hiker writes card.bonus_chips, consumed by scoring.py
        "Chips": (r"ctx\.chips\b|bonus_chips", "Chips"),
        "+Mult": (r"ctx\.mult\b", "+Mult"),
        "xMult": (r"ctx\.mult_mult\b", "xMult"),
        # debt_limit: Credit Card sets game-state, read by shop buy validation
        "Economy": (r"pending_money|ctx\.dollars\b|\$\w*dollars\b|state\[\"sell_value\"\]|debt_limit", "Economy"),
        "Retrigger": (r"card_retriggers", "Retrigger"),
    }
    # Jokers whose effect lives in the scoring/shop/game engine rather than a
    # class hook — the class is a presence marker (often literally `pass`), so
    # the source-text TYPE check cannot see the effect. Each entry is verified
    # by tests/test_joker_spec.py + engine tests.
    engine_detected = {
        # Mime: scoring.py doubles held Steel / held Gold-seal procs (B3 fix).
        "j_mime",
    }
    type_mismatch = {}
    for key, entry in spec.items():
        st = entry["type"]
        if st not in type_expect or key in engine_detected:
            continue
        target = resolve(key)
        if target is None:
            continue
        # find the module + class that registered the RESOLVED key
        mod = next((m for m in EFFECT_MODULES if target in per_module[m]), None)
        if mod is None:
            continue
        cls = per_module[mod][target]
        if cls == "?":
            continue
        src = open(f"{JOKER_DIR}/{mod}.py", encoding="utf-8",
                   errors="replace").read()
        m = re.search(rf"class {cls}\b.*?(?=\nclass |\Z)", src, re.S)
        body = m.group(0) if m else ""
        pat, label = type_expect[st]
        if not re.search(pat, body):
            type_mismatch[key] = f"{mod}.{cls} (spec {label})"

    # ── report ───────────────────────────────────────────────────────────────
    lines = []
    lines.append(f"catalogue: {len(JOKER_CATALOGUE)}  registry: {len(reg)}  "
                 f"aliases: {len(aliases)}  spec: {len(spec)}")
    lines.append(f"DUPES  {len(dupes)}")
    for k, mods in sorted(dupes.items()):
        lines.append(f"    {k:26s} {', '.join(mods)}")
    lines.append(f"DEAD   {len(dead)}")
    for k in dead:
        lines.append(f"    {k}")
    lines.append(f"STUBS  {len(stubs)}")
    for k, where in sorted(stubs.items()):
        lines.append(f"    {k:26s} {', '.join(where)}")
    lines.append(f"GAPS   cat={len(missing_cat)} spec={len(missing_spec)} "
                 f"broken_aliases={len(broken_aliases)}")
    for k in missing_cat:
        lines.append(f"    missing catalogue effect: {k}")
    for k in missing_spec:
        lines.append(f"    missing spec coverage:    {k}")
    for k in broken_aliases:
        lines.append(f"    broken alias: {k} -> {aliases[k]}")
    lines.append(f"TYPE   {len(type_mismatch)}")
    for k, why in sorted(type_mismatch.items()):
        lines.append(f"    {k:26s} {why}")

    # ── SIG / STATE / NOSCAN (R7 hardening gates) ────────────────────────────
    sig = signature_violations(EFFECT_MODULES)
    lines.append(f"SIG    {len(sig)}")
    for k, why in sorted(sig.items()):
        for hook, msg in sorted(why.items()):
            lines.append(f"    {k:26s} {hook}: {msg}")

    st = state_violations(EFFECT_MODULES)
    lines.append(f"STATE  {len(st)}")
    for k, keys in sorted(st.items()):
        lines.append(f"    {k:26s} bare-read keys without defaults: {', '.join(keys)}")

    nosc = noscan_violations()
    lines.append(f"NOSCAN {len(nosc)}")
    for path, hits in sorted(nosc.items()):
        for i, text in hits:
            lines.append(f"    {path}:{i}  {text}")

    report = "\n".join(lines)
    print(report)

    if "--json" in sys.argv:
        json.dump({"dupes": dupes, "dead": dead, "stubs": {k: v for k, v in stubs.items()},
                   "missing_cat": missing_cat, "missing_spec": missing_spec,
                   "broken_aliases": broken_aliases, "type_mismatch": type_mismatch,
                   "signature": {k: v for k, v in sig.items()},
                   "state": {k: v for k, v in st.items()},
                   "noscan": nosc},
                  open("tools/out_audit_jokers.json", "w", encoding="utf-8"),
                  indent=2, sort_keys=True)

    ok = not (dupes or dead or stubs or missing_cat or missing_spec
              or broken_aliases or type_mismatch or sig or st or nosc)
    print("GATES:", "CLEAN" if ok else "ISSUES FOUND")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
