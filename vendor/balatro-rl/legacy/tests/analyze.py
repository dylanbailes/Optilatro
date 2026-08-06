import json, collections

with open("logs/episode_log.jsonl") as f:
    eps = [json.loads(l) for l in f]

eps.sort(key=lambda e: e["episode"])
bins = collections.defaultdict(list)
for e in eps:
    bins[e["episode"] // 100].append(e["reward"])

print("Reward trend (per 100 episodes):")
for b in sorted(bins)[:15]:
    rewards = bins[b]
    avg = sum(rewards) / len(rewards)
    bar = "#" * int((avg + 2) * 10)
    print(f"  ep {b*100:4d}-{b*100+99:4d}: avg={avg:+.3f}  n={len(rewards):3d}  {bar}")

# Strategy from best runs
print()
try:
    with open("logs/best_runs.jsonl") as f:
        best = [json.loads(l) for l in f]
    best.sort(key=lambda r: r.get("reward", 0), reverse=True)
    print("Top 3 best runs (action breakdown):")
    for r in best[:3]:
        acts = r.get("actions", [])
        plays = sum(1 for a in acts if a[-1] == 1)
        discs = sum(1 for a in acts if a[-1] == 0)
        cards_per_play = [sum(a[:8]) for a in acts if a[-1] == 1]
        avg_cards = sum(cards_per_play) / len(cards_per_play) if cards_per_play else 0
        ep = r.get("episode", "?")
        rew = r.get("reward", 0)
        print(f"  ep={ep} reward={rew:.2f} steps={len(acts)} plays={plays} discards={discs} avg_cards/play={avg_cards:.1f}")
except Exception as e:
    print(f"  (best_runs unavailable: {e})")
