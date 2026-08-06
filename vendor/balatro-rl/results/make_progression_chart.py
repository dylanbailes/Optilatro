"""
V1 -> V8 progression chart for the Balatro RL project README / Featured section.
Data sourced from results/PROJECT_RETROSPECTIVE.md cross-version summary table.

Styled for GitHub dark-mode README display. Color palette matches the viz/ UI.
V4 is rendered as a distinct "INVALIDATED" bar so the full story arc is visible.
"""
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Patch

# ── Color palette (matches viz/style.css) ──────────────────────────────────
BG          = "#0d1117"   # GitHub dark mode background
PANEL       = "#151c2a"
TEXT        = "#e6edf3"
TEXT_MUTED  = "#8b95a5"
TEXT_FAINT  = "#5a6478"
GRID        = "#262d3d"

C_FAIL      = "#4b5463"   # V1-V3, V5, V8 — real zeros
C_INVALID   = "#6e7681"   # V4 — existed but measurements invalidated
C_FIRST     = "#f4c430"   # V6 — first legitimate
C_PEAK      = "#4ade80"   # V7 Run 4 — the peak
C_PLATEAU   = "#22a852"   # V7 Runs 5-6 — plateau
C_SCALE     = "#60a5fa"   # V7 Run 7 — scaling test

# (label, peak_wr_pct, annotation, color, is_invalidated)
versions = [
    ("V1-V3",        0.01, "Live-game IPC · <0.01%\nRAM leak, ~14 sps",              C_FAIL,    False),
    ("V4",           2.80, "Python-sim pivot · INVALIDATED\nfixed seeds + joker bugs", C_INVALID, True),
    ("V5",           0.00, "Dual-agent split · 0%\nshop starvation (12 runs)",        C_FAIL,    False),
    ("V6",           1.90, "Single-agent + combo ranker · 1.9%\nfirst legitimate result", C_FIRST,  False),
    ("V7 Run 4",     2.35, "Hierarchical intent + card head · 2.35%\nPEAK",          C_PEAK,    False),
    ("V7 Runs 5-6",  2.15, "Reward-shape retunes · 2.07 – 2.23%\nplateau confirmed", C_PLATEAU, False),
    ("V7 Run 7",     0.16, "5.5× network scaling · 0.16%\nsame plateau, killed early", C_SCALE,   False),
    ("V8 Runs 1-4",  0.00, "Self-play multiplayer · 0%\nsymmetry failures",          C_FAIL,    False),
]

labels       = [v[0] for v in versions]
vals         = [v[1] for v in versions]
annotations  = [v[2] for v in versions]
colors       = [v[3] for v in versions]
invalidated  = [v[4] for v in versions]

# ── Figure ─────────────────────────────────────────────────────────────────
fig, ax = plt.subplots(figsize=(12, 7), facecolor=BG)
ax.set_facecolor(BG)

y_pos = np.arange(len(versions))
bars = ax.barh(
    y_pos, vals, color=colors, alpha=0.95,
    edgecolor=BG, linewidth=1.2,
    height=0.62,
)

# Dash pattern for V4 (invalidated) bar
for bar, inv in zip(bars, invalidated):
    if inv:
        bar.set_hatch("////")
        bar.set_edgecolor(TEXT_FAINT)
        bar.set_linewidth(0.8)
        bar.set_alpha(0.55)

# Highlight V7 Run 4 (the peak) with a glow-like double edge
peak_idx = next(i for i, l in enumerate(labels) if l == "V7 Run 4")
bars[peak_idx].set_edgecolor(C_PEAK)
bars[peak_idx].set_linewidth(2.2)

# ── Axes styling ───────────────────────────────────────────────────────────
ax.set_yticks(y_pos)
ax.set_yticklabels(labels, fontsize=12, fontweight="bold", color=TEXT)
ax.invert_yaxis()
ax.tick_params(axis="x", colors=TEXT_MUTED, labelsize=10)
ax.tick_params(axis="y", colors=TEXT, length=0, pad=8)

ax.set_xlabel("Peak Solo Win Rate (%)", fontsize=11, color=TEXT_MUTED, labelpad=10)
ax.set_title(
    "Balatro RL · Version Progression\n"
    "8 architecture iterations · ~366 GPU-hours · RTX 3080 Ti",
    fontsize=14, pad=18, fontweight="bold", color=TEXT, loc="left",
)

# Per-bar annotations to the right of each bar
for i, (v, ann, inv) in enumerate(zip(vals, annotations, invalidated)):
    x_pos = max(v, 0.02) + 0.08
    ax.text(
        x_pos, i, ann,
        va="center", fontsize=9.5,
        color=TEXT_FAINT if inv else TEXT_MUTED,
    )

# Reference lines
ax.axvline(x=0.01, color=TEXT_FAINT, linestyle=":", alpha=0.5, linewidth=1.0)
ax.text(0.03, -0.7, "random play ≈ 0.01%", fontsize=8.5,
        color=TEXT_FAINT, style="italic")

# Human-level benchmark callout (top-right)
ax.text(
    0.985, 0.97,
    "skilled human ≈ 70% win rate\n(off-chart at this scale)",
    transform=ax.transAxes, ha="right", va="top",
    fontsize=9, style="italic", color=TEXT_MUTED,
    bbox=dict(boxstyle="round,pad=0.5",
              facecolor=PANEL, edgecolor=GRID, linewidth=1),
)

# V4 disclaimer
ax.text(
    0.0, -0.13,
    "V4 bar shown hatched: reported ~2.8% win rate was memorization on fixed seeds "
    "+ broken Burglar joker; both fixed in the V6 sim audit.",
    transform=ax.transAxes, ha="left", va="top",
    fontsize=8.5, style="italic", color=TEXT_FAINT,
)

# ── Clean up spines and grid ───────────────────────────────────────────────
ax.set_xlim(0, 3.2)
ax.grid(axis="x", color=GRID, alpha=0.7, linewidth=0.8)
ax.set_axisbelow(True)
for side in ("top", "right", "left"):
    ax.spines[side].set_visible(False)
ax.spines["bottom"].set_color(GRID)

plt.tight_layout()
out = "v1_v8_progression.png"
plt.savefig(out, dpi=180, bbox_inches="tight", facecolor=BG)
print(f"Saved {out}")
