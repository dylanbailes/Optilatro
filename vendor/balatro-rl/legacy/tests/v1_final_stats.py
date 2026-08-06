"""V1 Final Statistics"""
import json

lines = open('logs/episode_log.jsonl').readlines()
eps = [json.loads(l) for l in lines]

# Find session boundaries
sessions = []
cur = []
for ep in eps:
    if ep['episode'] == 1 and cur:
        sessions.append(cur)
        cur = []
    cur.append(ep)
if cur:
    sessions.append(cur)

# Total stats
all_rewards = [e['reward'] for e in eps]
all_antes = [e.get('ante', 1) for e in eps]

print('=== V1 FINAL RESULTS ===')
print(f'Total episodes: {len(eps)}')
print(f'Total sessions: {len(sessions)}')
print(f'Total timesteps: {eps[-1]["timestep"]}')
print()
print('Reward:')
print(f'  Overall avg: {sum(all_rewards)/len(all_rewards):.2f}')
print(f'  Max: {max(all_rewards):.2f}')
print()
print('Ante distribution:')
for a in [1,2,3,4,5]:
    n = sum(1 for x in all_antes if x == a)
    if n: print(f'  Ante {a}: {n} ({n/len(eps)*100:.2f}%)')
print()
ante2 = sum(1 for x in all_antes if x >= 2)
ante3 = sum(1 for x in all_antes if x >= 3)
print(f'Ante 2+ rate: {ante2/len(eps)*100:.2f}%')
print(f'Ante 3+ rate: {ante3/len(eps)*100:.2f}%')
print()

# Last 3 sessions (post-bugfix)
recent = [ep for s in sessions[-3:] for ep in s]
r_rewards = [e['reward'] for e in recent]
r_antes = [e.get('ante',1) for e in recent]
print('Post-bugfix sessions (last 3):')
print(f'  Episodes: {len(recent)}')
print(f'  Avg reward: {sum(r_rewards)/len(r_rewards):.2f}')
print(f'  Ante 2+ rate: {sum(1 for a in r_antes if a>=2)/len(r_antes)*100:.2f}%')
print()

# Best runs ever
print('Top 5 runs by reward:')
top5 = sorted(eps, key=lambda e: -e['reward'])[:5]
for e in top5:
    print(f'  ep={e["episode"]} ante={e.get("ante",1)} reward={e["reward"]:.2f} steps={e["length"]}')
