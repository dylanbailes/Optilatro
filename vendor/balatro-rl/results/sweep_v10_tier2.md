# agent-v10 tier2-knob sweep (tier2_opp_bonus / tier2_min_value)

Run 2026-08-18 22:00:24 · calibration 300 seeds · confirm 1000 seeds · farm defaults fixed at the §10.3 winner (0.9/0.75/1) · seed-mode, per-seed paired vs `heuristic_v9`.

**Baseline (heuristic_v9, 300 seeds):** win 3.33% · ante-1 deaths 32 · econ-source $10.3 · interest $15.1 · mean ante 4.49

Selection rule: drop configs with MORE ante-1 deaths than the baseline (non-negotiable); among survivors pick the highest win rate (tie-break econ-source $, then mean ante).

## Phase 1d — tier2_opp_bonus (min_value 0.0 fixed)
| config | win % | ante-1 deaths | econ-source $ | interest $ | mean ante | mean steps |
|---|---|---|---|---|---|---|
| opp=0.00 OK  | 5.00 | 30 | 13.8 | 15.0 | 4.38 | 125 |
| opp=0.02 OK  | 5.00 | 30 | 13.5 | 14.8 | 4.37 | 125 |
| opp=0.05 OK  | 5.00 | 30 | 13.6 | 14.8 | 4.37 | 124 |
| opp=0.10 OK  | 4.67 | 30 | 12.7 | 14.6 | 4.36 | 123 |

**Winner: opp=0.00** (opp_bonus=0.00)

## Phase 1e — tier2_min_value (opp_bonus fixed)
| config | win % | ante-1 deaths | econ-source $ | interest $ | mean ante | mean steps |
|---|---|---|---|---|---|---|
| minv=0.00 OK  | 5.00 | 30 | 13.8 | 15.0 | 4.38 | 125 |
| minv=0.10 OK  | 4.00 | 30 | 13.3 | 15.1 | 4.41 | 126 |
| minv=0.25 OK  | 3.33 | 32 | 10.8 | 15.0 | 4.48 | 127 |
| minv=0.50 OK  | 3.00 | 32 | 10.7 | 15.1 | 4.49 | 127 |

**Winner: minv=0.00** (min_value=0.00)

## Phase 2b — opp_bonus × min_value interaction
| config | win % | ante-1 deaths | econ-source $ | interest $ | mean ante | mean steps |
|---|---|---|---|---|---|---|
| x2b_0_0 OK  | 5.00 | 30 | 13.8 | 15.0 | 4.38 | 125 |
| x2b_0_10 OK  | 4.00 | 30 | 13.3 | 15.1 | 4.41 | 126 |
| x2b_5_0 OK  | 5.00 | 30 | 13.6 | 14.8 | 4.37 | 124 |
| x2b_5_10 OK  | 4.00 | 30 | 13.2 | 14.9 | 4.40 | 125 |

**Winner: x2b_0_0** (opp_bonus=0.00, min_value=0.00)

## Phase 3b — 1000-seed confirm

| arm | win % | ante-1 deaths | econ-source $ | interest $ | mean ante |
|---|---|---|---|---|---|
| v9_1000 | 4.10 | 109 | 10.5 | 14.6 | 4.43 |
| winner_1000 | 4.30 | 105 | 14.2 | 14.9 | 4.34 |
| farmoff_1000 | 4.10 | 109 | 10.5 | 14.6 | 4.43 |

`farmoff_1000` == `v9_1000` (threshold=1.0 disables farming and the survive tier reproduces v9 byte-for-byte), so the row doubles as the farming-attribution control.

## Final winning config

```
{
  "farm_clear_threshold": 0.9,
  "abandon_clear_floor": 0.75,
  "farm_spare_hands": 1,
  "tier2_opp_bonus": 0.0,
  "tier2_min_value": 0.0
}
```

- win 5.00% vs baseline 3.33%
- ante-1 deaths 30 vs baseline 32
- econ-source $13.8/run vs $10.3/run
- interest $15.0/run vs $15.1/run
- mean ante 4.38 vs 4.49

## Verdict

**`tier2_min_value` = 0.0 is confirmed optimal** — the gate degrades strictly
and monotonically as it rises (5.00 → 4.00 → 3.33 → 3.00% win, econ-source
$13.8 → $10.7): every small value action (a single gold seal, a Faceless
discard that also fixes the hand) is worth its hand/discard cost at this
agent's economy, so the default 0.0 stands.

**`tier2_opp_bonus` is inert within noise** — 0.00, 0.02 (the documented
default), and 0.05 all land on 15/300 = 5.00% (the mechanical picker chose
0.00 only on the econ tie-break, $13.8 vs $13.5/13.6 — a $0.2-0.3/run
spread). The 1000-seed confirm cross-checks this: the winner here
(opp_bonus=0.0) posts 4.30% / 105 ante-1 deaths / $14.2 econ vs the §10.3
default confirm (opp_bonus=0.02) at 4.40% / 105 / $14.1 — 43 vs 44 wins/1000,
within noise. **The code keeps the documented 0.02** (no statistical reason
to churn it; the bonus is what biases ties toward free opportunistic value).

**Success gate ✓** at both sample sizes: ante-1 deaths never worse
(30≤32 at 300, 105≤109 at 1000), econ-source +34%, win rate ≥ baseline.

**Net: the §10.2/§5.3 defaults are the optimum across all five knobs** —
`farm_clear_threshold 0.90 / abandon_clear_floor 0.75 / farm_spare_hands 1 /
tier2_opp_bonus 0.02 / tier2_min_value 0.0` — no code change required.
