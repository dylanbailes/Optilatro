"""
plot_v2.py - Plot V2 training progress
"""
import json
import matplotlib
matplotlib.use('Agg')  # Non-interactive backend
import matplotlib.pyplot as plt

def main():
    lines = open('logs_v2/episode_log.jsonl').readlines()
    eps = [json.loads(l) for l in lines]
    
    if not eps:
        print("No episodes logged yet")
        return
    
    fig, axes = plt.subplots(2, 2, figsize=(12, 8))
    
    # Reward over episodes
    ax1 = axes[0, 0]
    rewards = [e['reward'] for e in eps]
    ax1.plot(rewards, alpha=0.5, linewidth=0.5)
    window = min(50, len(rewards))
    if len(rewards) >= window:
        rolling = [sum(rewards[max(0,i-window):i])/min(i,window) for i in range(1, len(rewards)+1)]
        ax1.plot(rolling, 'r-', linewidth=2, label=f'{window}-ep avg')
    ax1.set_xlabel('Episode')
    ax1.set_ylabel('Reward')
    ax1.set_title('V2: Episode Reward')
    ax1.legend()
    ax1.grid(True, alpha=0.3)
    
    # Ante distribution
    ax2 = axes[0, 1]
    antes = [e.get('ante', 1) for e in eps]
    ante_counts = {}
    for a in antes:
        ante_counts[a] = ante_counts.get(a, 0) + 1
    ax2.bar(ante_counts.keys(), ante_counts.values())
    ax2.set_xlabel('Ante Reached')
    ax2.set_ylabel('Count')
    ax2.set_title('V2: Ante Distribution')
    ax2.grid(True, alpha=0.3)
    
    # Episode length
    ax3 = axes[1, 0]
    lengths = [e['length'] for e in eps]
    ax3.plot(lengths, alpha=0.5)
    ax3.set_xlabel('Episode')
    ax3.set_ylabel('Steps')
    ax3.set_title('V2: Episode Length')
    ax3.grid(True, alpha=0.3)
    
    # Stats text
    ax4 = axes[1, 1]
    ax4.axis('off')
    ante2_plus = sum(v for k,v in ante_counts.items() if k>=2)
    stats = f'''V2 Training Stats
================
Episodes: {len(eps)}
Total steps: {eps[-1]['timestep'] if eps else 0}

Reward:
  Mean: {sum(rewards)/len(rewards):.2f}
  Max: {max(rewards):.2f}
  Min: {min(rewards):.2f}

Ante distribution:
  Ante 1: {ante_counts.get(1, 0)} ({ante_counts.get(1,0)/len(eps)*100:.1f}%)
  Ante 2+: {ante2_plus} ({ante2_plus/len(eps)*100:.1f}%)
'''
    ax4.text(0.1, 0.9, stats, transform=ax4.transAxes, fontsize=11, 
             verticalalignment='top', fontfamily='monospace')
    
    plt.tight_layout()
    plt.savefig('logs_v2/training_progress.png', dpi=150)
    print(f'Saved to logs_v2/training_progress.png')
    print(f'\nQuick stats: {len(eps)} eps | avg={sum(rewards)/len(rewards):.2f} | max={max(rewards):.2f} | ante2+={ante2_plus/len(eps)*100:.1f}%')

if __name__ == "__main__":
    main()
