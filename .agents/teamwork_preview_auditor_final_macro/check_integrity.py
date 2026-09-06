import ast
import re
import sys

def analyze_file(filepath):
    print(f"\n==========================================")
    print(f"Deep Forensic AST & Syntax Audit: {filepath}")
    print(f"==========================================")
    with open(filepath, "r", encoding="utf-8") as f:
        src = f.read()

    tree = ast.parse(src, filename=filepath)

    # 1. Check for any access to game.seed, game.rng, game._rng, game.seed_rng
    banned_attrs = {"seed", "seed_rng", "_rng"}
    found_banned_attrs = []
    
    # 2. Check for game mutation during evaluation / search functions
    # (e.g. .step() called on something named game or self, rather than cloned game g2/eg/sim)
    step_calls = []

    # 3. Check for deck access patterns
    deck_accesses = []

    # 4. Check for test branches (e.g., inspecting sys.argv, pytest, __file__, os.environ)
    env_argv_checks = []

    # 5. Check for hardcoded numeric comparisons to known seeds
    # 0-299, 9000-9599, 205, 275, etc.
    seed_numbers = {205, 275}
    found_magic_numbers = []

    for node in ast.walk(tree):
        # Attribute access
        if isinstance(node, ast.Attribute):
            if node.attr in banned_attrs:
                found_banned_attrs.append((node.lineno, node.attr, ast.unparse(node)))
            if node.attr == "deck":
                deck_accesses.append((node.lineno, ast.unparse(node)))
        
        # Method calls
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute) and node.func.attr == "step":
                step_calls.append((node.lineno, ast.unparse(node)))

        # Magic constants / seeds
        if isinstance(node, ast.Constant) and isinstance(node.value, int):
            if node.value in seed_numbers:
                found_magic_numbers.append((node.lineno, node.value))

        # Check for test detection (pytest, sys._called_from_test, etc.)
        if isinstance(node, ast.Name):
            if node.id in ("pytest", "mock", "unittest"):
                env_argv_checks.append((node.lineno, node.id))

    print(f"1. Banned attribute accesses ({len(found_banned_attrs)}):")
    for lineno, attr, text in found_banned_attrs:
        print(f"   Line {lineno}: {text}")
    if not found_banned_attrs:
        print("   CLEAN: None found.")

    print(f"\n2. Magic seed numbers checked ({len(found_magic_numbers)}):")
    for lineno, val in found_magic_numbers:
        print(f"   Line {lineno}: {val}")
    if not found_magic_numbers:
        print("   CLEAN: None found.")

    print(f"\n3. Test-environment detection ({len(env_argv_checks)}):")
    for lineno, name in env_argv_checks:
        print(f"   Line {lineno}: {name}")
    if not env_argv_checks:
        print("   CLEAN: None found.")

    print(f"\n4. Direct .step() calls ({len(step_calls)}):")
    for lineno, text in step_calls:
        print(f"   Line {lineno}: {text}")

    print(f"\n5. Deck attribute accesses ({len(deck_accesses)}):")
    for lineno, text in deck_accesses[:15]:
        print(f"   Line {lineno}: {text}")
    if len(deck_accesses) > 15:
        print(f"   ... ({len(deck_accesses) - 15} more)")

for p in [
    'vendor/balatro-rl/balatro_sim/agent_v10.py',
    'vendor/balatro-rl/balatro_sim/agent_v9.py',
    'vendor/balatro-rl/balatro_sim/agent_l1.py',
    'tools/portfolio.py'
]:
    analyze_file(p)
