import tokenize

files = [
    'vendor/balatro-rl/balatro_sim/agent_v10.py',
    'vendor/balatro-rl/balatro_sim/agent_v9.py',
    'vendor/balatro-rl/balatro_sim/agent_l1.py',
    'tools/portfolio.py'
]

for fp in files:
    print(f"Checking strings in {fp}...")
    with open(fp, "rb") as f:
        tokens = list(tokenize.tokenize(f.readline))
    matches = [tok for tok in tokens if tok.type == tokenize.STRING and "seed" in tok.string.lower()]
    for m in matches:
        line_str = m.line.strip()
        if not line_str.startswith('"""') and not line_str.startswith("'''"):
            print(f"  Line {m.start[0]}: {line_str}")
