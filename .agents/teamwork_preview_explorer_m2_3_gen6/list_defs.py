with open('vendor/balatro-rl/balatro_sim/agent_v10.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

for i, line in enumerate(lines):
    if line.startswith('def ') or line.startswith('class '):
        print(f"{i+1}: {line.strip()}")
