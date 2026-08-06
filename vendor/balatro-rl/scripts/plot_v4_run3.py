"""
plot_v4.py — v4 sim training dashboard with stats table.
"""
import re, json
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import numpy as np
from pathlib import Path

OUT = Path("logs_sim/v4_dashboard.png")

# ── Parse per-iteration log ───────────────────────────────────────────────────
iters = {"steps_m": [], "sps": [], "reward": [], "loss": [], "pg": [],
         "vf": [], "ent": [], "best_ante": [], "iter": [], "eps": []}

v4_re = re.compile(
    r"\[([0-9.]+)M\] iter=(\d+)\s+sps=([0-9.]+)\s+eps=(\d+).*?"
    r"rew=(-?[0-9.]+)\s+loss=(-?[0-9.]+)\s+pg=(-?[0-9.]+)\s+vf=([0-9.]+)\s+ent=([0-9.]+)\s+best=(\d+)"
)
for line in Path("logs_sim/training_sim_run3.log").read_text().splitlines():
    m = v4_re.search(line)
    if m:
        iters["steps_m"].append(float(m.group(1)))
        iters["iter"].append(int(m.group(2)))
        iters["sps"].append(float(m.group(3)))
        iters["eps"].append(int(m.group(4)))
        iters["reward"].append(float(m.group(5)))
        iters["loss"].append(float(m.group(6)))
        iters["pg"].append(float(m.group(7)))
        iters["vf"].append(float(m.group(8)))
        iters["ent"].append(float(m.group(9)))
        iters["best_ante"].append(int(m.group(10)))

# ── Parse episode log ─────────────────────────────────────────────────────────
episodes = []
for line in Path("checkpoints_sim/episode_log.jsonl").read_text().splitlines():
    try:
        episodes.append(json.loads(line))
    except:
        pass

ep_ante    = np.array([e["ante"]   for e in episodes])
ep_reward  = np.array([e["reward"] for e in episodes])
ep_steps   = np.array([e["steps"]  for e in episodes])
N          = len(episodes)
LAST       = 500

# ── Rolling smooth helper ─────────────────────────────────────────────────────
def smooth(arr, w=30):
    arr = np.array(arr)
    pad = np.pad(arr, (w//2, w//2), mode="edge")
    return np.convolve(pad, np.ones(w)/w, mode="valid")[:len(arr)]

# ── Stats table ───────────────────────────────────────────────────────────────
def stats_block(label, arr):
    last = arr[-LAST:]
    return {
        "label":     label,
        "all_mean":  np.mean(arr),
        "all_min":   np.min(arr),
        "all_max":   np.max(arr),
        "last_mean": np.mean(last),
        "last_min":  np.min(last),
        "last_max":  np.max(last),
    }

table_rows = [
    stats_block("Reward/ep",   ep_reward),
    stats_block("Ante reached", ep_ante),
    stats_block("Steps/ep",    ep_steps),
    stats_block("SPS",         np.array(iters["sps"])),
    stats_block("Total loss",  np.array(iters["loss"])),
    stats_block("VF loss",     np.array(iters["vf"])),
    stats_block("Entropy",     np.array(iters["ent"])),
]

print(f"\n{'='*72}")
print(f"  v4 Sim Training Stats   ({len(iters['iter'])} iters | "
      f"{iters['steps_m'][-1]:.2f}M steps | {N:,} episodes)")
print(f"{'='*72}")
print(f"{'Metric':<16}  {'--- All time ---':^28}  {'--- Last 500 eps ---':^28}")
print(f"{'':16}  {'Mean':>8}  {'Min':>8}  {'Max':>8}  {'Mean':>8}  {'Min':>8}  {'Max':>8}")
print(f"{'-'*72}")
for r in table_rows:
    print(f"{r['label']:<16}  {r['all_mean']:>8.2f}  {r['all_min']:>8.2f}  "
          f"{r['all_max']:>8.2f}  {r['last_mean']:>8.2f}  {r['last_min']:>8.2f}  {r['last_max']:>8.2f}")

# Ante distribution
print(f"\n  Ante distribution (all {N:,} episodes):")
for a in sorted(set(ep_ante.tolist())):
    cnt = int((ep_ante == a).sum())
    pct = cnt / N * 100
    bar = '#' * int(pct / 2)
    print(f"    Ante {int(a)}: {pct:5.1f}%  {bar}")

wins = int((ep_ante >= 9).sum())
print(f"\n  Full wins (ante 9+): {wins} / {N} = {wins/N*100:.2f}%")
print(f"{'='*72}\n")

# ── Plot ──────────────────────────────────────────────────────────────────────
DARK  = "#0d1117"
GRID  = "#21262d"
C     = "#3fb950"
C2    = "#58a6ff"
TEXT  = "#e6edf3"
MUTED = "#8b949e"
C_LOSS = "#f0883e"
C_ENT  = "#bc8cff"

fig = plt.figure(figsize=(18, 13))
fig.patch.set_facecolor(DARK)
gs = gridspec.GridSpec(3, 2, figure=fig, hspace=0.40, wspace=0.30)

def style(ax, title):
    ax.set_facecolor("#161b22")
    ax.set_title(title, color=TEXT, fontsize=11, fontweight="bold", pad=8)
    ax.tick_params(colors=MUTED, labelsize=8)
    ax.spines[:].set_color(GRID)
    ax.xaxis.label.set_color(MUTED)
    ax.yaxis.label.set_color(MUTED)
    ax.grid(True, color=GRID, linewidth=0.6, alpha=0.8)

sm = np.array(iters["steps_m"])

# ── 1. Throughput ─────────────────────────────────────────────────────────────
ax1 = fig.add_subplot(gs[0, 0])
style(ax1, "Throughput (Steps/sec)")
sps = np.array(iters["sps"])
ax1.plot(sm, sps, color=C, linewidth=0.8, alpha=0.35)
ax1.plot(sm, smooth(sps, 30), color=C, linewidth=2.2, label=f"30-iter MA  (median {np.median(sps):.0f})")
ax1.axhline(np.median(sps), color=C, linewidth=0.8, linestyle=":", alpha=0.4)
ax1.set_xlabel("Steps (M)")
ax1.set_ylabel("SPS")
ax1.legend(fontsize=8, facecolor=DARK, labelcolor=TEXT, edgecolor=GRID)

# ── 2. Reward / episode ───────────────────────────────────────────────────────
ax2 = fig.add_subplot(gs[0, 1])
style(ax2, "Mean Episode Reward (per iteration)")
rew = np.array(iters["reward"])
ax2.plot(sm, rew, color=C, linewidth=0.6, alpha=0.3)
ax2.plot(sm, smooth(rew, 30), color=C, linewidth=2.2, label=f"30-iter MA  (last 50 avg {np.mean(rew[-50:]):.1f})")
ax2.axhline(np.mean(rew), color=MUTED, linewidth=0.8, linestyle="--", label=f"all-time mean {np.mean(rew):.1f}", alpha=0.7)
ax2.set_xlabel("Steps (M)")
ax2.set_ylabel("Mean Reward")
ax2.legend(fontsize=8, facecolor=DARK, labelcolor=TEXT, edgecolor=GRID)

# ── 3. Best ante running max ──────────────────────────────────────────────────
ax3 = fig.add_subplot(gs[1, 0])
style(ax3, "Best Ante (Running Max) + Ante per Episode")
# scatter of episode antes (use iteration as proxy x-axis)
ep_iter = np.array([e["iteration"] for e in episodes])
ep_sm   = ep_iter / max(ep_iter) * sm[-1]   # rescale to step domain
ax3.scatter(ep_sm, ep_ante, color=C, s=1.5, alpha=0.15)
# running max
best = np.array(iters["best_ante"])
ax3.plot(sm, best, color="#f85149", linewidth=2.5, drawstyle="steps-post",
         label=f"Running max (current: {best[-1]})")
ax3.set_yticks(range(1, 10))
ax3.set_ylim(0.5, 9.5)
ax3.set_xlabel("Steps (M)")
ax3.set_ylabel("Ante")
ax3.legend(fontsize=8, facecolor=DARK, labelcolor=TEXT, edgecolor=GRID)

# ── 4. Loss breakdown ─────────────────────────────────────────────────────────
ax4 = fig.add_subplot(gs[1, 1])
style(ax4, "Loss Components")
loss = np.array(iters["loss"])
vf   = np.array(iters["vf"])
pg   = np.array(iters["pg"])
ax4.plot(sm, smooth(loss, 30), color=C_LOSS, linewidth=2.0, label=f"Total  (now {np.mean(loss[-20:]):.3f})")
ax4.plot(sm, smooth(vf,   30), color=C2,     linewidth=1.5, linestyle="--",
         label=f"VF     (now {np.mean(vf[-20:]):.3f})", alpha=0.85)
ax4.plot(sm, smooth(np.abs(pg), 30), color=MUTED, linewidth=1.2, linestyle=":",
         label=f"|PG|   (now {abs(np.mean(pg[-20:])):.3f})", alpha=0.8)
ax4.axhline(0, color=MUTED, linewidth=0.4)
ax4.set_xlabel("Steps (M)")
ax4.set_ylabel("Loss (30-iter MA)")
ax4.set_ylim(bottom=-0.02)
ax4.legend(fontsize=8, facecolor=DARK, labelcolor=TEXT, edgecolor=GRID)

# ── 5. Entropy ────────────────────────────────────────────────────────────────
ax5 = fig.add_subplot(gs[2, 0])
style(ax5, "Policy Entropy")
ent = np.array(iters["ent"])
ax5.plot(sm, ent, color=C_ENT, linewidth=0.6, alpha=0.3)
ax5.plot(sm, smooth(ent, 30), color=C_ENT, linewidth=2.2,
         label=f"30-iter MA  (now {ent[-1]:.3f})")
ax5.axhline(np.log(46), color=MUTED, linewidth=0.8, linestyle=":",
            label=f"Uniform max ({np.log(46):.2f})", alpha=0.7)
ax5.set_xlabel("Steps (M)")
ax5.set_ylabel("Entropy (nats)")
ax5.legend(fontsize=8, facecolor=DARK, labelcolor=TEXT, edgecolor=GRID)

# ── 6. Stats table ────────────────────────────────────────────────────────────
ax6 = fig.add_subplot(gs[2, 1])
ax6.set_facecolor("#161b22")
ax6.axis("off")
ax6.set_title("Stats Summary", color=TEXT, fontsize=11, fontweight="bold", pad=8)

col_labels = ["Metric", "All Mean", "All Min", "All Max", "L500 Mean", "L500 Min", "L500 Max"]
cell_data  = []
for r in table_rows:
    cell_data.append([
        r["label"],
        f"{r['all_mean']:.2f}",
        f"{r['all_min']:.2f}",
        f"{r['all_max']:.2f}",
        f"{r['last_mean']:.2f}",
        f"{r['last_min']:.2f}",
        f"{r['last_max']:.2f}",
    ])

tbl = ax6.table(
    cellText=cell_data,
    colLabels=col_labels,
    cellLoc="center",
    loc="center",
    bbox=[0.0, 0.0, 1.0, 1.0],
)
tbl.auto_set_font_size(False)
tbl.set_fontsize(8)
for (row, col), cell in tbl.get_celld().items():
    cell.set_facecolor("#21262d" if row % 2 == 0 else "#161b22")
    cell.set_text_props(color=TEXT if row > 0 else "#f0883e")
    cell.set_edgecolor(GRID)
    if row == 0:
        cell.set_facecolor("#21262d")
        cell.set_text_props(color="#f0883e", fontweight="bold")

wins = int((ep_ante >= 9).sum())
fig.suptitle(
    f"v4 Python Sim Training  |  {iters['iter'][-1]} iters  |  "
    f"{iters['steps_m'][-1]:.2f}M steps  |  {N:,} episodes  |  "
    f"{wins} full wins ({wins/N*100:.1f}%)",
    color=TEXT, fontsize=12, fontweight="bold", y=0.99
)

plt.savefig(OUT, dpi=150, bbox_inches="tight", facecolor=DARK)
print(f"Saved: {OUT}")
