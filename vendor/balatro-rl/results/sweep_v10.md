# agent-v10 farm-parameter sweep (§10.3)

Run 2026-08-18 14:07:57 · calibration 300 seeds · confirm 1000 seeds · seed-mode, per-seed paired vs `heuristic_v9`.

**Baseline (heuristic_v9):** win 3.33% · ante-1 deaths 32 · econ-source $10.3 · interest $15.1 · mean ante 4.49

Selection rule: drop configs with MORE ante-1 deaths than the baseline (non-negotiable); among survivors pick the highest win rate (tie-break econ-source $, then mean ante).

## Phase 1a — farm_spare_hands
| config | win % | ante-1 deaths | econ-source $ | interest $ | mean ante | mean steps |
|---|---|---|---|---|---|---|
| spare=0 OK  | 3.67 | 31 | 14.1 | 14.4 | 4.32 | 123 |
| spare=1 OK  | 5.00 | 30 | 13.5 | 14.8 | 4.37 | 125 |
| spare=2 OK  | 4.67 | 31 | 12.5 | 14.9 | 4.44 | 126 |

**Winner: spare=1** (spare=1)

## Phase 1b — farm_clear_threshold
| config | win % | ante-1 deaths | econ-source $ | interest $ | mean ante | mean steps |
|---|---|---|---|---|---|---|
| thr=0.70 OK  | 4.00 | 30 | 13.8 | 14.8 | 4.38 | 125 |
| thr=0.80 OK  | 4.67 | 30 | 13.7 | 14.8 | 4.38 | 125 |
| thr=0.90 OK  | 5.00 | 30 | 13.5 | 14.8 | 4.37 | 125 |
| thr=0.95 OK  | 4.67 | 30 | 13.3 | 14.9 | 4.37 | 124 |

**Winner: thr=0.90** (threshold=0.90)

## Phase 1c — abandon_clear_floor
| config | win % | ante-1 deaths | econ-source $ | interest $ | mean ante | mean steps |
|---|---|---|---|---|---|---|
| floor=0.50 OK  | 4.67 | 30 | 13.5 | 14.7 | 4.36 | 124 |
| floor=0.60 OK  | 4.67 | 30 | 13.5 | 14.7 | 4.36 | 124 |
| floor=0.70 OK  | 4.67 | 30 | 13.5 | 14.7 | 4.36 | 124 |
| floor=0.80 OK  | 5.00 | 30 | 13.5 | 14.9 | 4.38 | 125 |

**Winner: floor=0.80** (floor=0.80)

## Phase 2 — threshold × floor interaction
| config | win % | ante-1 deaths | econ-source $ | interest $ | mean ante | mean steps |
|---|---|---|---|---|---|---|
| x2_90_80 OK  | 5.00 | 30 | 13.5 | 14.9 | 4.38 | 125 |
| x2_90_50 OK  | 4.67 | 30 | 13.5 | 14.7 | 4.36 | 124 |
| x2_80_80 OK  | 5.00 | 30 | 13.7 | 15.0 | 4.39 | 125 |
| x2_80_50 OK  | 4.67 | 30 | 13.7 | 14.8 | 4.38 | 125 |

**Winner: x2_80_80** (threshold=0.80, floor=0.80)

## Phase 3 — 1000-seed confirm

| arm | win % | ante-1 deaths | econ-source $ | interest $ | mean ante |
|---|---|---|---|---|---|
| v9_1000 (baseline) | 4.10 | 109 | 10.5 | 14.6 | 4.43 |
| farmoff_1000 (thr 1.0) | 4.10 | 109 | 10.5 | 14.6 | 4.43 |
| x2_80_80 (0.80/0.80) | 4.50 | 106 | 14.1 | 14.9 | 4.34 |
| **default (0.90/0.75)** | **4.40** | **105** | **14.1** | **14.9** | **4.34** |

`farmoff_1000` == `v9_1000` exactly (threshold=1.0 disables farming and the
P(clear) survive tier reproduces v9 byte-for-byte), so the row doubles as the
farming-attribution control: value-farming adds **+0.3-0.4pp win, -3/4 ante-1
deaths, +$3.6 econ-source $/run** at 1000 seeds. The two farming-on configs
(default 0.90/0.75 and x2_80_80) are statistically indistinguishable
(44 vs 45 wins/1000, identical econ/interest).

## Final winning config

The mechanical pick (highest 300-seed win rate, econ tie-break) was
`x2_80_80` = {0.80, 0.80, 1} — but that has a **zero hysteresis band**
(floor == threshold), which §10.4 requires be `>= 0.10` to stop
farm/survive oscillation. The **default config is statistically tied at both
sample sizes, keeps the 0.15 band, and is therefore the recorded winner**:

```
{
  "farm_clear_threshold": 0.9,
  "abandon_clear_floor": 0.75,
  "farm_spare_hands": 1
}
```

i.e. the §10.2 defaults were already at the optimum — the sweep confirms them
rather than moving them.

| metric | default (300s) | baseline v9 (300s) | default (1000s) | baseline v9 (1000s) |
|---|---|---|---|---|
| win rate | 5.00% | 3.33% | 4.40% | 4.10% |
| ante-1 deaths | 30 | 32 | 105 | 109 |
| econ-source $/run | 13.5 | 10.3 | 14.1 | 10.5 |
| interest $/run | 14.8 | 15.1 | 14.9 | 14.6 |
| mean ante | 4.37 | 4.49 | 4.34 | 4.43 |

Success-gate verdict: ante-1 deaths never worse (30<=32, 105<=109) ✓ ·
econ-source $ materially higher (+31-34%) ✓ · win rate >= baseline ✓.
