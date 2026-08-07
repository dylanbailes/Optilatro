"""One-time codemod (joker-fidelity refactor R1).

Converts every effect module from:

    class _Foo:
        def on_hand_scored(...): ...
    JOKER_REGISTRY["j_foo"] = _Foo()

to:

    @register_joker("j_foo")
    class _Foo(JokerEffect):
        def on_hand_scored(...): ...

and adds JokerEffect/register_joker to the base import. Alias assignments
(JOKER_REGISTRY["a"] = JOKER_REGISTRY["b"]) are left untouched.
"""
import re
import sys

MODULES = ["economy", "scaling", "hand_type", "misc", "chips", "mult"]
DIR = "vendor/balatro-rl/balatro_sim/jokers"

_ASSIGN = re.compile(r'^JOKER_REGISTRY\["([a-z0-9_]+)"\]\s*=\s*(\w+)\(\)\s*$')
_ALIAS = re.compile(r'^JOKER_REGISTRY\["([a-z0-9_]+)"\]\s*=\s*JOKER_REGISTRY\[')
_CLASS = re.compile(r'^class (\w+):\s*$')
_BASE_IMPORT = re.compile(r'^from \.base import (.+)$')


def convert(path: str) -> tuple[int, int]:
    src = open(path, encoding="utf-8", errors="replace").read()
    lines = src.split("\n")
    class_names = set()
    for i, ln in enumerate(lines):
        m = _CLASS.match(ln)
        if m:
            class_names.add(m.group(1))

    # key -> class name for direct assignments whose RHS is a defined class
    assignments = {}
    for ln in lines:
        m = _ASSIGN.match(ln.strip())
        if m and m.group(2) in class_names:
            assignments[m.group(1)] = m.group(2)
    aliases = [ln for ln in lines if _ALIAS.match(ln.strip())]

    out = []
    removed = 0
    decorated = set()
    for ln in lines:
        m = _CLASS.match(ln)
        if m and m.group(1) in assignments.values():
            key = next(k for k, v in assignments.items() if v == m.group(1))
            if key not in decorated:
                out.append(f'@register_joker("{key}")')
                decorated.add(key)
            out.append(f"class {m.group(1)}(JokerEffect):")
            continue
        if _ASSIGN.match(ln.strip()) and ln.strip().split("=")[1].strip()[:-2] in class_names:
            removed += 1
            continue  # drop the assignment line (decorator takes its place)
        out.append(ln)

    # Rewrite the base import line to also bring in JokerEffect + register_joker
    # (line-based to avoid multiline anchor issues).
    fixed = []
    for ln in out:
        m = _BASE_IMPORT.match(ln)
        if m:
            names = [n.strip() for n in m.group(1).split(",")]
            if "JokerEffect" not in names:
                names.append("JokerEffect")
            if "register_joker" not in names:
                names.append("register_joker")
            fixed.append(f"from .base import {', '.join(names)}")
        else:
            fixed.append(ln)
    txt = "\n".join(fixed)
    open(path, "w", encoding="utf-8", newline="\n").write(txt)
    return len(assignments), removed


def main() -> int:
    for mod in MODULES:
        n_assign, n_removed = convert(f"{DIR}/{mod}.py")
        print(f"{mod}: decorated {n_assign}, removed {n_removed}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
