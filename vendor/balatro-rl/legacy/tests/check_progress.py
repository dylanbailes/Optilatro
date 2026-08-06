import json

with open("logs/episode_log.jsonl") as f:
    eps = [json.loads(l) for l in f]

best = sorted(eps, key=lambda e: (e["ante"], e["reward"]), reverse=True)[:5]
print("Top 5 episodes by ante/reward:")
for e in best:
    print(f"  ep={e['episode']} ante={e['ante']} reward={e['reward']:.2f} score={e['score']} steps={e['length']}")

print(f"\nTotal episodes: {len(eps)}")
ante_counts = {}
for e in eps:
    a = e["ante"]
    ante_counts[a] = ante_counts.get(a, 0) + 1
print("Ante distribution:")
for a in sorted(ante_counts):
    print(f"  ante {a}: {ante_counts[a]} episodes ({100*ante_counts[a]/len(eps):.1f}%)")
