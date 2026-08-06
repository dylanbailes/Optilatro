"""
plot_runs.py — overlay all training runs on shared axes for comparison.
"""
import re, math
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import numpy as np
from pathlib import Path

LOGS = [
    ("Run 5 — 8k, 6-layer, flat rewards",           "logs_sim/training_sim_run5.log",  "#bc8cff"),
    ("Run 6 — 8k, 6-layer, inverse rewards",        "logs_sim/training_sim_run6.log",  "#f0883e"),
    ("Run 6b — resumed iters 1001-2000",             "logs_sim/training_sim_run6b.log", "#f7c948"),
]

PAT = re.compile(
    r"\[([0-9.]+)M\] iter=(\d+)\s+sps=([0-9.]+)\s+eps=(\d+).*?"
    r"rew=(-?[0-9.]+)\s+loss=(-?[0-9.]+)\s+pg=(-?[0-9.]+)\s+vf=([0-9.]+)\s+ent=([0-9.]+)\s+best=(\d+)"
)

def parse(path):
    d = dict(steps=[], iter=[], sps=[], reward=[], loss=[], ent=[], best=[])
    p = Path(path)
    if not p.exists():
        return d
    for line in p.read_text().splitlines():
        m = PAT.search(line)
        if m:
            d["steps"].append(float(m.group(1)))
            d["iter"].append(int(m.group(2)))
            d["sps"].append(float(m.group(3)))
            d["reward"].append(float(m.group(5)))
            d["loss"].append(float(m.group(6)))
            d["ent"].append(float(m.group(9)))
            d["best"].append(int(m.group(10)))
    return {k: np.array(v) for k, v in d.items()}

runs = [(label, parse(path), color) for label, path, color in LOGS]

def smooth(arr, w=10):
    if len(arr) < w:
        return arr
    pad = np.pad(arr, (w//2, w//2), mode="edge")
    return np.convolve(pad, np.ones(w)/w, mode="valid")[:len(arr)]

DARK  = "#0d1117"
GRID  = "#21262d"
TEXT  = "#e6edf3"
MUTED = "#8b949e"

fig = plt.figure(figsize=(16, 10))
fig.patch.set_facecolor(DARK)
gs = gridspec.GridSpec(2, 2, figure=fig, hspace=0.38, wspace=0.28)

def style(ax, title):
    ax.set_facecolor("#161b22")
    ax.set_title(title, color=TEXT, fontsize=11, fontweight="bold", pad=8)
    ax.tick_params(colors=MUTED, labelsize=8)
    ax.spines[:].set_color(GRID)
    ax.xaxis.label.set_color(MUTED)
    ax.yaxis.label.set_color(MUTED)
    ax.grid(True, color=GRID, linewidth=0.6, alpha=0.8)

ax1 = fig.add_subplot(gs[0, 0])
style(ax1, "Mean Episode Reward")
ax1.set_xlabel("Iteration")

ax2 = fig.add_subplot(gs[0, 1])
style(ax2, "Best Ante (Running Max)")
ax2.set_yticks(range(1, 10))
ax2.set_ylim(0.5, 9.5)
ax2.set_xlabel("Iteration")

ax3 = fig.add_subplot(gs[1, 0])
style(ax3, "Total Loss")
ax3.set_xlabel("Iteration")

ax4 = fig.add_subplot(gs[1, 1])
style(ax4, "Policy Entropy")
ax4.set_xlabel("Iteration")
ax4.axhline(math.log(46), color=MUTED, linewidth=0.8, linestyle=":",
            label=f"Uniform max ({math.log(46):.2f})", alpha=0.5)

for label, d, color in runs:
    if len(d["iter"]) == 0:
        continue
    iters = d["iter"]
    n = len(iters)
    alpha_raw = 0.2

    ax1.plot(iters, d["reward"], color=color, linewidth=0.5, alpha=alpha_raw)
    ax1.plot(iters, smooth(d["reward"]), color=color, linewidth=2.0,
             label=f"{label}  (n={n})")

    ax2.plot(iters, d["best"], color=color, linewidth=2.2,
             drawstyle="steps-post", label=label)

    ax3.plot(iters, d["loss"], color=color, linewidth=0.5, alpha=alpha_raw)
    ax3.plot(iters, smooth(d["loss"]), color=color, linewidth=2.0, label=label)

    ax4.plot(iters, d["ent"], color=color, linewidth=0.5, alpha=alpha_raw)
    ax4.plot(iters, smooth(d["ent"]), color=color, linewidth=2.0, label=label)

for ax in [ax1, ax2, ax3, ax4]:
    ax.legend(fontsize=7.5, facecolor=DARK, labelcolor=TEXT, edgecolor=GRID,
              loc="best")

# Totals summary
titles = "  |  ".join(f"{label.split('—')[0].strip()}: {len(d['iter'])} iters"
                     for label, d, _ in runs if len(d["iter"]) > 0)
fig.suptitle(
    f"Training Runs Comparison  |  {titles}",
    color=TEXT, fontsize=12, fontweight="bold", y=0.99
)

OUT = "logs_sim/runs_comparison.png"
plt.savefig(OUT, dpi=150, bbox_inches="tight", facecolor=DARK)
print(f"Saved: {OUT}")

# Quick stats printout
print()
for label, d, _ in runs:
    if len(d["iter"]) == 0:
        print(f"{label}: no data")
        continue
    n = len(d["iter"])
    print(f"{label}  [{n} iters]")
    print(f"  reward: min={d['reward'].min():.2f}  max={d['reward'].max():.2f}  "
          f"last10_avg={np.mean(d['reward'][-10:]):.2f}")
    print(f"  best ante: {d['best'][-1]}  |  entropy now: {d['ent'][-1]:.3f}  "
          f"|  loss now: {d['loss'][-1]:.4f}")
