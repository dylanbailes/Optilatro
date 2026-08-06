import re
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

iters, rewards, p_ent, s_ent, p_loss, s_loss, shop_steps, play_steps, eps_list = [],[],[],[],[],[],[],[],[]

with open('logs_sim/training_v5_run8.log', encoding='utf-16', errors='ignore') as f:
    for line in f:
        m = re.search(
            r'iter=(\d+)\s+sps=\d+\s+steps=\((\d+)p\+(\d+)s\)\s+eps=(\d+)\s+rew=([-\d.]+)'
            r'\s+wr=[\d.]+\s+p_loss=([-\d.]+)\s+s_loss=([-\d.]+)\s+p_ent=([-\d.]+)\s+s_ent=([-\d.]+)',
            line
        )
        if m:
            iters.append(int(m.group(1)))
            play_steps.append(int(m.group(2)))
            shop_steps.append(int(m.group(3)))
            eps_list.append(int(m.group(4)))
            rewards.append(float(m.group(5)))
            p_loss.append(float(m.group(6)))
            s_loss.append(float(m.group(7)))
            p_ent.append(float(m.group(8)))
            s_ent.append(float(m.group(9)))

print(f"Parsed {len(iters)} iterations")
if len(iters) == 0:
    print("No data found — check log format")
    exit()

iters      = np.array(iters)
rewards    = np.array(rewards)
p_ent      = np.array(p_ent)
s_ent      = np.array(s_ent)
shop_steps = np.array(shop_steps, dtype=float)
play_steps = np.array(play_steps, dtype=float)
eps_arr    = np.array(eps_list, dtype=float)

def smooth(x, w=20):
    if len(x) < w:
        return x
    return np.convolve(x, np.ones(w)/w, mode='valid')

fig, axes = plt.subplots(2, 2, figsize=(12, 8))
fig.suptitle(f'V5 Run 8 — Both Agents from Scratch ({len(iters)} iters)', fontsize=13)

# Reward
ax = axes[0,0]
ax.plot(iters, rewards, alpha=0.3, color='steelblue')
s = smooth(rewards)
ax.plot(iters[len(iters)-len(s):], s, color='steelblue', linewidth=2, label='smoothed')
ax.axhline(0, color='gray', linestyle='--', linewidth=0.8)
ax.set_title('Mean Reward'); ax.set_xlabel('Iter'); ax.grid(True, alpha=0.3)

# Entropy
ax = axes[0,1]
ax.plot(iters, p_ent, alpha=0.3, color='orange', label='Play')
ax.plot(iters, s_ent, alpha=0.3, color='green', label='Shop')
sp = smooth(p_ent); ss = smooth(s_ent)
ax.plot(iters[len(iters)-len(sp):], sp, color='orange', linewidth=2)
ax.plot(iters[len(iters)-len(ss):], ss, color='green', linewidth=2)
ax.set_title('Entropy'); ax.set_xlabel('Iter'); ax.legend(); ax.grid(True, alpha=0.3)

# Shop vs Play steps
ax = axes[1,0]
ax.plot(iters, shop_steps, alpha=0.3, color='green', label='Shop')
ax.plot(iters, play_steps, alpha=0.2, color='orange', label='Play')
sshop = smooth(shop_steps); splay = smooth(play_steps)
ax.plot(iters[len(iters)-len(sshop):], sshop, color='green', linewidth=2)
ax.plot(iters[len(iters)-len(splay):], splay, color='orange', linewidth=2)
ax.set_title('Steps per Iter (Play vs Shop)'); ax.set_xlabel('Iter'); ax.legend(); ax.grid(True, alpha=0.3)

# Episodes per iter
ax = axes[1,1]
ax.plot(iters, eps_arr, alpha=0.3, color='purple')
se = smooth(eps_arr)
ax.plot(iters[len(iters)-len(se):], se, color='purple', linewidth=2)
ax.set_title('Episodes per Iter'); ax.set_xlabel('Iter'); ax.grid(True, alpha=0.3)

plt.tight_layout()
plt.savefig('logs_sim/v5_run8_progress.png', dpi=150, bbox_inches='tight')
print(f"Saved to logs_sim/v5_run8_progress.png")
print(f"Last iter: {iters[-1]} | reward: {rewards[-1]:.3f} | p_ent: {p_ent[-1]:.3f} | s_ent: {s_ent[-1]:.3f} | shop_steps: {int(shop_steps[-1])}")
