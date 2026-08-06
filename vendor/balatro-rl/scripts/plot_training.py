"""
plot_training.py — Compare v2 (single-instance), v3 (Lua socket), and v4 (Python sim) training runs.
"""
import re
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import numpy as np
from pathlib import Path

OUT = Path("logs_sim/training_comparison.png")
OUT.parent.mkdir(exist_ok=True)

# ── Parse v3 log ─────────────────────────────────────────────────────────────
# Format: [0.16M] iter=81 steps=1024 sps=109.3 eps=0 ... loss=0.1220 pg=-0.0142 vf=0.3198 ent=2.3747 best_ante=7 (9.4s/iter)

v3 = {"steps_m": [], "sps": [], "reward": [], "loss": [], "ent": [], "best_ante": [], "iter": []}
v3_path = Path("logs_ray_socket/training_v3.log")
v3_re = re.compile(
    r"\[([0-9.]+)M\] iter=(\d+)\s+steps=\d+\s+sps=([0-9.]+)\s+eps=(\d+)"
    r".*?loss=(-?[0-9.]+).*?ent=([0-9.]+).*?best_ante=(\d+)"
)
if v3_path.exists():
    for line in v3_path.read_text().splitlines():
        m = v3_re.search(line)
        if m:
            v3["steps_m"].append(float(m.group(1)))
            v3["iter"].append(int(m.group(2)))
            v3["sps"].append(float(m.group(3)))
            v3["loss"].append(float(m.group(5)))
            v3["ent"].append(float(m.group(6)))
            v3["best_ante"].append(int(m.group(7)))

# ── Parse v4 sim log ──────────────────────────────────────────────────────────
# Format: [0.004M] iter=1 sps=818 eps=356 eps/hr=246667 rew=2.94 loss=0.2644 pg=-0.0221 vf=0.6196 ent=2.3245 best=2 (5.2s)

v4 = {"steps_m": [], "sps": [], "reward": [], "loss": [], "ent": [], "best_ante": [], "iter": []}
v4_path = Path("logs_sim/training_sim.log")
v4_re = re.compile(
    r"\[([0-9.]+)M\] iter=(\d+)\s+sps=([0-9.]+)\s+eps=\d+\s+eps/hr=\d+"
    r"\s+rew=(-?[0-9.]+)\s+loss=(-?[0-9.]+).*?ent=([0-9.]+)\s+best=(\d+)"
)
if v4_path.exists():
    for line in v4_path.read_text().splitlines():
        m = v4_re.search(line)
        if m:
            v4["steps_m"].append(float(m.group(1)))
            v4["iter"].append(int(m.group(2)))
            v4["sps"].append(float(m.group(3)))
            v4["reward"].append(float(m.group(4)))
            v4["loss"].append(float(m.group(5)))
            v4["ent"].append(float(m.group(6)))
            v4["best_ante"].append(int(m.group(7)))

# ── v2 summary (no per-iteration log; use documented values) ─────────────────
V2_SPS         = 6.0
V2_TOTAL_STEPS = 210_000
V2_BEST_ANTE   = 9
V2_ANTE_DIST   = {1: 39.6, 2: 26.2, 3: 24.0, 4: 8.2, 5: 1.6, 6: 0.4}

# ── Detect anomalies in v4 ────────────────────────────────────────────────────
anomalies = []
if v4["sps"]:
    sps_arr = np.array(v4["sps"])
    median_sps = np.median(sps_arr[10:])  # skip warmup
    for i, (it, s) in enumerate(zip(v4["iter"], v4["sps"])):
        if i > 5 and s < median_sps * 0.5:
            anomalies.append((it, v4["steps_m"][i], s, "sps_drop"))

    reward_arr = np.array(v4["reward"])
    for i in range(5, len(reward_arr)):
        window = reward_arr[max(0, i-20):i]
        if reward_arr[i] > np.mean(window) + 3 * np.std(window) + 1:
            anomalies.append((v4["iter"][i], v4["steps_m"][i], reward_arr[i], "reward_spike"))

print(f"\n{'='*60}")
print(f"  Training Comparison Report")
print(f"{'='*60}")
print(f"\nv2 (single Lua instance, file IPC, SB3 PPO):")
print(f"  Throughput:  {V2_SPS:.0f} sps (flat)")
print(f"  Total steps: {V2_TOTAL_STEPS:,}")
print(f"  Best ante:   {V2_BEST_ANTE}")

if v3["sps"]:
    print(f"\nv3 (8x Lua instances, socket IPC, custom PPO) [iters {v3['iter'][0]}-{v3['iter'][-1]}]:")
    print(f"  Throughput:  {np.median(v3['sps']):.1f} sps median (degraded from RAM issues)")
    print(f"  sps range:   {min(v3['sps']):.1f} - {max(v3['sps']):.1f}")
    print(f"  Total steps: {v3['steps_m'][-1]*1e6:,.0f}")
    print(f"  Best ante:   {max(v3['best_ante'])}")
    # Detect v3 anomalies
    slow_iters = sum(1 for s in v3["sps"] if s < 10)
    print(f"  Slow iters (<10 sps): {slow_iters}/{len(v3['iter'])} — RAM degradation + instance freezes")
    pos_pg = sum(1 for line in Path("logs_ray_socket/training_v3.log").read_text().splitlines()
                 if "pg=0." in line or (re.search(r"pg=([0-9.]+)", line) and
                                        float(re.search(r"pg=([0-9.]+)", line).group(1)) > 0.001))
    if pos_pg:
        print(f"  Positive pg loss: {pos_pg} iter(s) — policy moving in wrong direction briefly")

if v4["sps"]:
    print(f"\nv4 (Python sim, 16-worker multiprocessing PPO) [iters {v4['iter'][0]}-{v4['iter'][-1]}]:")
    print(f"  Throughput:  {np.median(v4['sps']):.0f} sps median")
    print(f"  sps range:   {min(v4['sps']):.0f} - {max(v4['sps']):.0f} (drops as eps get longer)")
    print(f"  Total steps: {v4['steps_m'][-1]*1e6:,.0f}")
    print(f"  Best ante:   {max(v4['best_ante'])}")
    print(f"  Reward:      {v4['reward'][0]:.1f} -> {np.mean(v4['reward'][-20:]):.1f} (last 20 iter avg)")
    peak_rew_idx = int(np.argmax(v4["reward"]))
    print(f"  Peak reward: {max(v4['reward']):.1f} at iter {v4['iter'][peak_rew_idx]}")
    print(f"  Entropy:     {v4['ent'][0]:.3f} -> {v4['ent'][-1]:.3f} (healthy decay)")
    print(f"  Loss:        {v4['loss'][0]:.4f} -> {np.mean(list(v4['loss'])[-20:]):.4f}")
    if anomalies:
        print(f"\n  Anomalies detected in v4:")
        for (it, sm, val, kind) in anomalies[:10]:
            print(f"    iter {it:>4} [{sm:.3f}M steps]: {kind} = {val:.1f}")
    else:
        print(f"\n  No anomalies detected in v4.")
    ante7_first = next((v4["iter"][i] for i, a in enumerate(v4["best_ante"]) if a >= 7), None)
    print(f"\n  Ante 7 first reached: iter {ante7_first} ({v4['steps_m'][v4['iter'].index(ante7_first)]:.3f}M steps)")
    print(f"  Ante 7 plateau: {v4['iter'][-1] - (ante7_first or 0)} iters without breaking through")

print(f"\nSpeedup vs v2:  {np.median(v4['sps'])/V2_SPS:.0f}x")
print(f"Speedup vs v3:  {np.median(v4['sps'])/np.median(v3['sps']):.0f}x" if v3["sps"] else "")

# ── Plot ──────────────────────────────────────────────────────────────────────
fig = plt.figure(figsize=(18, 14))
fig.patch.set_facecolor("#0d1117")
gs  = gridspec.GridSpec(3, 2, figure=fig, hspace=0.42, wspace=0.32)

DARK  = "#0d1117"
GRID  = "#21262d"
C_V2  = "#58a6ff"
C_V3  = "#f85149"
C_V4  = "#3fb950"
TEXT  = "#e6edf3"
MUTED = "#8b949e"

ax_style = dict(facecolor="#161b22", labelcolor=TEXT, titlecolor=TEXT)

def style(ax, title):
    ax.set_facecolor("#161b22")
    ax.set_title(title, color=TEXT, fontsize=11, fontweight="bold", pad=8)
    ax.tick_params(colors=MUTED, labelsize=8)
    ax.spines[:].set_color(GRID)
    ax.xaxis.label.set_color(MUTED)
    ax.yaxis.label.set_color(MUTED)
    ax.grid(True, color=GRID, linewidth=0.6, alpha=0.8)

# ── 1. Throughput over steps ──────────────────────────────────────────────────
ax1 = fig.add_subplot(gs[0, 0])
style(ax1, "Throughput (sps) over Training Steps")
# v2: flat line
ax1.axhline(V2_SPS, color=C_V2, linewidth=2, linestyle="--", label=f"v2 single-inst ({V2_SPS:.0f} sps)")
# v3
if v3["sps"]:
    ax1.plot(v3["steps_m"], v3["sps"], color=C_V3, linewidth=1.2, alpha=0.85, label="v3 Lua 8x socket")
    ax1.axhline(np.median(v3["sps"]), color=C_V3, linewidth=0.8, linestyle=":", alpha=0.5)
# v4
if v4["sps"]:
    ax1.plot(v4["steps_m"], v4["sps"], color=C_V4, linewidth=1.4, label="v4 Python sim 16-worker")
    ax1.axhline(np.median(v4["sps"]), color=C_V4, linewidth=0.8, linestyle=":", alpha=0.5)
ax1.set_xlabel("Total Steps (M)")
ax1.set_ylabel("Steps / Second")
ax1.legend(fontsize=8, facecolor=DARK, labelcolor=TEXT, edgecolor=GRID)
ax1.set_yscale("log")

# ── 2. Mean reward per episode over steps ────────────────────────────────────
ax2 = fig.add_subplot(gs[0, 1])
style(ax2, "Mean Episode Reward over Steps")
if v4["reward"]:
    ax2.plot(v4["steps_m"], v4["reward"], color=C_V4, linewidth=1.0, alpha=0.5, label="raw")
    # rolling mean
    w = 20
    pad = np.pad(v4["reward"], (w//2, w//2), mode="edge")
    smooth = np.convolve(pad, np.ones(w)/w, mode="valid")[:len(v4["reward"])]
    ax2.plot(v4["steps_m"], smooth, color=C_V4, linewidth=2.2, label="20-iter MA")
ax2.axhline(0, color=MUTED, linewidth=0.5, linestyle="--")
ax2.set_xlabel("Total Steps (M)")
ax2.set_ylabel("Mean Reward / Episode")
ax2.legend(fontsize=8, facecolor=DARK, labelcolor=TEXT, edgecolor=GRID)

# ── 3. Best ante reached (running max) ───────────────────────────────────────
ax3 = fig.add_subplot(gs[1, 0])
style(ax3, "Best Ante Reached (Running Max)")
ax3.axhline(V2_BEST_ANTE, color=C_V2, linewidth=2, linestyle="--",
            label=f"v2 all-time best (ante {V2_BEST_ANTE})")
if v3["best_ante"]:
    ax3.plot(v3["steps_m"], v3["best_ante"], color=C_V3, linewidth=2,
             drawstyle="steps-post", label=f"v3 best (ante {max(v3['best_ante'])})")
if v4["best_ante"]:
    ax3.plot(v4["steps_m"], v4["best_ante"], color=C_V4, linewidth=2,
             drawstyle="steps-post", label=f"v4 best (ante {max(v4['best_ante'])})")
ax3.set_xlabel("Total Steps (M)")
ax3.set_ylabel("Best Ante")
ax3.set_yticks(range(1, 10))
ax3.legend(fontsize=8, facecolor=DARK, labelcolor=TEXT, edgecolor=GRID)

# ── 4. Training loss over steps ───────────────────────────────────────────────
ax4 = fig.add_subplot(gs[1, 1])
style(ax4, "Total Loss over Steps")
if v3["loss"]:
    ax4.plot(v3["steps_m"], v3["loss"], color=C_V3, linewidth=1.0, alpha=0.7, label="v3")
if v4["loss"]:
    ax4.plot(v4["steps_m"], v4["loss"], color=C_V4, linewidth=1.0, alpha=0.6, label="v4 raw")
    smooth_loss = np.convolve(
        np.pad(v4["loss"], (10, 10), mode="edge"), np.ones(20)/20, mode="valid"
    )[:len(v4["loss"])]
    ax4.plot(v4["steps_m"], smooth_loss, color=C_V4, linewidth=2.2, label="v4 20-iter MA")
ax4.set_xlabel("Total Steps (M)")
ax4.set_ylabel("Loss")
ax4.legend(fontsize=8, facecolor=DARK, labelcolor=TEXT, edgecolor=GRID)
ax4.set_ylim(bottom=-0.05)

# ── 5. Entropy over steps (exploration health) ────────────────────────────────
ax5 = fig.add_subplot(gs[2, 0])
style(ax5, "Policy Entropy (Exploration)")
if v3["ent"]:
    ax5.plot(v3["steps_m"], v3["ent"], color=C_V3, linewidth=1.2, alpha=0.8, label="v3")
if v4["ent"]:
    ax5.plot(v4["steps_m"], v4["ent"], color=C_V4, linewidth=1.4, alpha=0.8, label="v4")
ax5.axhline(np.log(46), color=MUTED, linewidth=0.8, linestyle=":",
            label=f"max entropy (uniform, {np.log(46):.2f})")
ax5.set_xlabel("Total Steps (M)")
ax5.set_ylabel("Entropy (nats)")
ax5.legend(fontsize=8, facecolor=DARK, labelcolor=TEXT, edgecolor=GRID)

# ── 6. v2 ante distribution bar + speedup summary ────────────────────────────
ax6 = fig.add_subplot(gs[2, 1])
style(ax6, "v2 Final Ante Distribution  vs  Sim Speedup")
ax6.set_facecolor("#161b22")

antes = list(V2_ANTE_DIST.keys())
pcts  = list(V2_ANTE_DIST.values())
bars  = ax6.bar([str(a) for a in antes], pcts, color=C_V2, alpha=0.75, width=0.6)
for bar, pct in zip(bars, pcts):
    ax6.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.3,
             f"{pct:.1f}%", ha="center", va="bottom", fontsize=8, color=TEXT)
ax6.set_xlabel("Ante Reached (v2 @ 8,732 eps)")
ax6.set_ylabel("% of Episodes")

# Annotate speedup
speedup_sim  = int(np.median(v4["sps"]) / V2_SPS) if v4["sps"] else 0
speedup_v3   = int(np.median(v4["sps"]) / np.median(v3["sps"])) if v3["sps"] else 0

ax6.text(0.97, 0.95, f"v4 sim vs v2:  ~{speedup_sim}x faster",
         transform=ax6.transAxes, ha="right", va="top",
         fontsize=9, color=C_V4, fontweight="bold")
ax6.text(0.97, 0.85, f"v4 sim vs v3:  ~{speedup_v3}x faster",
         transform=ax6.transAxes, ha="right", va="top",
         fontsize=9, color=C_V4)

fig.suptitle(
    "Balatro RL — v2 (single Lua)  vs  v3 (8x Lua socket)  vs  v4 (Python sim)\n"
    f"v4: {v4['steps_m'][-1] if v4['steps_m'] else 0:.2f}M steps | "
    f"{v4['iter'][-1] if v4['iter'] else 0} iters | best ante {max(v4['best_ante']) if v4['best_ante'] else '?'}",
    color=TEXT, fontsize=13, fontweight="bold", y=0.98
)

plt.savefig(OUT, dpi=150, bbox_inches="tight", facecolor=DARK)
print(f"\nSaved: {OUT}")
