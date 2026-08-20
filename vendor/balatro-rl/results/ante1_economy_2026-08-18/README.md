# Bench A/B results

- seed bank: **0-299 (shared)** · arms: 5 · generated: 2026-08-18 01:36

## Summary

| arm | wins | win % (95% CI) | mean ante | median ante | mean steps | ante-1 deaths | end w/ xMult | end w/ econ | mean $ |
|---|---|---|---|---|---|---|---|---|---|
| struct_v4 baseline (best) | 14/300 | 4.67% [2.80, 7.68] | 4.51 | 4 | 127 | 32 (10.7%) | 66% | 37% | 9.4 |
| blanket_floor (hold >= $5) | 10/300 | 3.33% [1.82, 6.03] | 4.08 | 4 | 106 | 37 (12.3%) | 58% | 46% | 10.0 |
| joker_exempt_floor | 12/300 | 4.00% [2.30, 6.86] | 4.16 | 4 | 109 | 35 (11.7%) | 63% | 40% | 9.7 |
| reroll_gate (max1, min$10) | 14/300 | 4.67% [2.80, 7.68] | 4.53 | 5 | 129 | 31 (10.3%) | 68% | 38% | 11.2 |
| floor_joker_exempt + reroll_gate | 11/300 | 3.67% [2.06, 6.45] | 4.36 | 4 | 124 | 37 (12.3%) | 68% | 43% | 11.4 |

## Death by ante

### struct_v4 baseline (best) — 14/300 wins (4.67%)
  ante 1:   32 (10.67%) ###############################
  ante 2:   34 (11.33%) #################################
  ante 3:   36 (12.00%) ###################################
  ante 4:   51 (17.00%) ##################################################
  ante 5:   46 (15.33%) #############################################
  ante 6:   40 (13.33%) #######################################
  ante 7:   32 (10.67%) ###############################
  ante 8:   15 ( 5.00%) ##############
  ante 9:   14 ( 4.67%) #############

### blanket_floor (hold >= $5) — 10/300 wins (3.33%)
  ante 1:   37 (12.33%) ##############################
  ante 2:   45 (15.00%) ####################################
  ante 3:   36 (12.00%) #############################
  ante 4:   61 (20.33%) ##################################################
  ante 5:   52 (17.33%) ##########################################
  ante 6:   30 (10.00%) ########################
  ante 7:   18 ( 6.00%) ##############
  ante 8:   11 ( 3.67%) #########
  ante 9:   10 ( 3.33%) ########

### joker_exempt_floor — 12/300 wins (4.00%)
  ante 1:   35 (11.67%) ############################
  ante 2:   44 (14.67%) ###################################
  ante 3:   35 (11.67%) ############################
  ante 4:   62 (20.67%) ##################################################
  ante 5:   48 (16.00%) ######################################
  ante 6:   35 (11.67%) ############################
  ante 7:   18 ( 6.00%) ##############
  ante 8:   11 ( 3.67%) ########
  ante 9:   12 ( 4.00%) #########

### reroll_gate (max1, min$10) — 14/300 wins (4.67%)
  ante 1:   31 (10.33%) ###############################
  ante 2:   33 (11.00%) #################################
  ante 3:   37 (12.33%) #####################################
  ante 4:   48 (16.00%) ################################################
  ante 5:   46 (15.33%) ##############################################
  ante 6:   50 (16.67%) ##################################################
  ante 7:   24 ( 8.00%) ########################
  ante 8:   17 ( 5.67%) #################
  ante 9:   14 ( 4.67%) ##############

### floor_joker_exempt + reroll_gate — 11/300 wins (3.67%)
  ante 1:   37 (12.33%) #################################
  ante 2:   37 (12.33%) #################################
  ante 3:   28 ( 9.33%) #########################
  ante 4:   55 (18.33%) #################################################
  ante 5:   56 (18.67%) ##################################################
  ante 6:   30 (10.00%) ##########################
  ante 7:   33 (11.00%) #############################
  ante 8:   13 ( 4.33%) ###########
  ante 9:   11 ( 3.67%) #########


## Survival by ante (runs reaching at least ante N)

| arm | a1 | a2 | a3 | a4 | a5 | a6 | a7 | a8 | win |
|---|---|---|---|---|---|---|---|---|---|
| struct_v4 baseline (best) | 300 | 268 | 234 | 198 | 147 | 101 | 61 | 29 | 14 |
| blanket_floor (hold >= $5) | 300 | 263 | 218 | 182 | 121 | 69 | 39 | 21 | 10 |
| joker_exempt_floor | 300 | 265 | 221 | 186 | 124 | 76 | 41 | 23 | 12 |
| reroll_gate (max1, min$10) | 300 | 269 | 236 | 199 | 151 | 105 | 55 | 31 | 14 |
| floor_joker_exempt + reroll_gate | 300 | 263 | 226 | 198 | 143 | 87 | 57 | 24 | 11 |

## Paired comparisons (per-seed, shared bank)

### struct_v4 baseline (best) → blanket_floor (hold >= $5)
- shared seeds: 300 · wins struct_v4 baseline (best): 14 → blanket_floor (hold >= $5): 10 (Δ -1.33pp)
- concordant: both-win 3 / both-loss 279 · discordant: struct_v4 baseline (best)-only 11 / blanket_floor (hold >= $5)-only 7
- mean ante Δ (blanket_floor (hold >= $5) − struct_v4 baseline (best)): -0.43

### struct_v4 baseline (best) → joker_exempt_floor
- shared seeds: 300 · wins struct_v4 baseline (best): 14 → joker_exempt_floor: 12 (Δ -0.67pp)
- concordant: both-win 3 / both-loss 277 · discordant: struct_v4 baseline (best)-only 11 / joker_exempt_floor-only 9
- mean ante Δ (joker_exempt_floor − struct_v4 baseline (best)): -0.35

### struct_v4 baseline (best) → reroll_gate (max1, min$10)
- shared seeds: 300 · wins struct_v4 baseline (best): 14 → reroll_gate (max1, min$10): 14 (Δ +0.00pp)
- concordant: both-win 8 / both-loss 280 · discordant: struct_v4 baseline (best)-only 6 / reroll_gate (max1, min$10)-only 6
- mean ante Δ (reroll_gate (max1, min$10) − struct_v4 baseline (best)): +0.03

### struct_v4 baseline (best) → floor_joker_exempt + reroll_gate
- shared seeds: 300 · wins struct_v4 baseline (best): 14 → floor_joker_exempt + reroll_gate: 11 (Δ -1.00pp)
- concordant: both-win 3 / both-loss 278 · discordant: struct_v4 baseline (best)-only 11 / floor_joker_exempt + reroll_gate-only 8
- mean ante Δ (floor_joker_exempt + reroll_gate − struct_v4 baseline (best)): -0.14

### blanket_floor (hold >= $5) → joker_exempt_floor
- shared seeds: 300 · wins blanket_floor (hold >= $5): 10 → joker_exempt_floor: 12 (Δ +0.67pp)
- concordant: both-win 9 / both-loss 287 · discordant: blanket_floor (hold >= $5)-only 1 / joker_exempt_floor-only 3
- mean ante Δ (joker_exempt_floor − blanket_floor (hold >= $5)): +0.08

### blanket_floor (hold >= $5) → reroll_gate (max1, min$10)
- shared seeds: 300 · wins blanket_floor (hold >= $5): 10 → reroll_gate (max1, min$10): 14 (Δ +1.33pp)
- concordant: both-win 3 / both-loss 279 · discordant: blanket_floor (hold >= $5)-only 7 / reroll_gate (max1, min$10)-only 11
- mean ante Δ (reroll_gate (max1, min$10) − blanket_floor (hold >= $5)): +0.46

### blanket_floor (hold >= $5) → floor_joker_exempt + reroll_gate
- shared seeds: 300 · wins blanket_floor (hold >= $5): 10 → floor_joker_exempt + reroll_gate: 11 (Δ +0.33pp)
- concordant: both-win 1 / both-loss 280 · discordant: blanket_floor (hold >= $5)-only 9 / floor_joker_exempt + reroll_gate-only 10
- mean ante Δ (floor_joker_exempt + reroll_gate − blanket_floor (hold >= $5)): +0.29

### joker_exempt_floor → reroll_gate (max1, min$10)
- shared seeds: 300 · wins joker_exempt_floor: 12 → reroll_gate (max1, min$10): 14 (Δ +0.67pp)
- concordant: both-win 3 / both-loss 277 · discordant: joker_exempt_floor-only 9 / reroll_gate (max1, min$10)-only 11
- mean ante Δ (reroll_gate (max1, min$10) − joker_exempt_floor): +0.37

### joker_exempt_floor → floor_joker_exempt + reroll_gate
- shared seeds: 300 · wins joker_exempt_floor: 12 → floor_joker_exempt + reroll_gate: 11 (Δ -0.33pp)
- concordant: both-win 2 / both-loss 279 · discordant: joker_exempt_floor-only 10 / floor_joker_exempt + reroll_gate-only 9
- mean ante Δ (floor_joker_exempt + reroll_gate − joker_exempt_floor): +0.20

### reroll_gate (max1, min$10) → floor_joker_exempt + reroll_gate
- shared seeds: 300 · wins reroll_gate (max1, min$10): 14 → floor_joker_exempt + reroll_gate: 11 (Δ -1.00pp)
- concordant: both-win 3 / both-loss 278 · discordant: reroll_gate (max1, min$10)-only 11 / floor_joker_exempt + reroll_gate-only 8
- mean ante Δ (floor_joker_exempt + reroll_gate − reroll_gate (max1, min$10)): -0.17


## End-of-run joker composition

| arm | xMult % | econ % | tarot-gen % | top end jokers |
|---|---|---|---|---|
| struct_v4 baseline (best) | 66% | 37% | 12% | j_cavendish x54, j_raised_fist x43, j_splash x41, j_even_steven x41 |
| blanket_floor (hold >= $5) | 58% | 46% | 12% | j_cavendish x48, j_splash x39, j_even_steven x35, j_misprint x33 |
| joker_exempt_floor | 63% | 40% | 15% | j_cavendish x50, j_splash x37, j_raised_fist x36, j_misprint x35 |
| reroll_gate (max1, min$10) | 68% | 38% | 14% | j_cavendish x55, j_raised_fist x41, j_splash x41, j_even_steven x37 |
| floor_joker_exempt + reroll_gate | 68% | 43% | 13% | j_cavendish x50, j_splash x42, j_even_steven x39, j_raised_fist x38 |

## Usage stats

### struct_v4 baseline (best)
- money: mean $ 9.4 · spent $124.2 · rerolls 2.0 · packs 11.4
- score: max 527,200 · mean 31,117
- tarots: c_hermit x197, c_fool x169, c_death x161, c_temperance x155, c_magician x139, c_empress x114
- planets: pl_mercury x362, pl_uranus x77, pl_pluto x47, pl_saturn x15, pl_jupiter x15, pl_earth x13
- spectrals: s_black_hole x14, s_aura x10, s_talisman x9, s_deja_vu x8, s_immolate x7, s_medium x6
- jokers bought: j_popcorn x73, j_todo_list x72, j_reserved_parking x68, j_mail x67, j_golden x66, j_faceless x65
- died on blind: Boss (179), Big (75), Small (32)

### blanket_floor (hold >= $5)
- money: mean $ 10.0 · spent $100.5 · rerolls 4.0 · packs 6.2
- score: max 917,936 · mean 24,643
- tarots: c_hermit x119, c_death x100, c_magician x94, c_temperance x90, c_fool x86, c_wheel_of_fortune x75
- planets: pl_mercury x202, pl_uranus x56, pl_pluto x26, pl_saturn x17, pl_venus x7, pl_jupiter x5
- spectrals: s_aura x7, s_ectoplasm x7, s_medium x6, s_black_hole x6, s_trance x3, s_incantation x3
- jokers bought: j_reserved_parking x68, j_golden x68, j_popcorn x65, j_mail x62, j_business x61, j_swashbuckler x58
- died on blind: Boss (152), Big (90), Small (48)

### joker_exempt_floor
- money: mean $ 9.7 · spent $104.6 · rerolls 3.7 · packs 6.3
- score: max 917,936 · mean 26,145
- tarots: c_hermit x125, c_death x91, c_magician x88, c_fool x79, c_temperance x79, c_wheel_of_fortune x78
- planets: pl_mercury x176, pl_uranus x61, pl_pluto x22, pl_saturn x12, pl_jupiter x10, pl_venus x4
- spectrals: s_black_hole x8, s_medium x6, s_aura x6, s_ectoplasm x5, s_talisman x4, s_incantation x3
- jokers bought: j_golden x74, j_reserved_parking x73, j_popcorn x65, j_business x64, j_mail x60, j_faceless x59
- died on blind: Boss (157), Big (87), Small (44)

### reroll_gate (max1, min$10)
- money: mean $ 11.2 · spent $126.1 · rerolls 1.7 · packs 12.0
- score: max 3,586,005 · mean 44,961
- tarots: c_hermit x208, c_fool x178, c_death x177, c_magician x152, c_temperance x150, c_empress x126
- planets: pl_mercury x389, pl_uranus x88, pl_pluto x59, pl_jupiter x22, pl_earth x16, pl_venus x12
- spectrals: s_black_hole x12, s_aura x9, s_immolate x9, s_talisman x8, s_deja_vu x7, s_medium x6
- jokers bought: j_popcorn x70, j_todo_list x69, j_reserved_parking x68, j_faceless x67, j_ice_cream x64, j_golden x64
- died on blind: Boss (179), Big (77), Small (30)

### floor_joker_exempt + reroll_gate
- money: mean $ 11.4 · spent $123.2 · rerolls 2.0 · packs 10.6
- score: max 1,404,000 · mean 32,419
- tarots: c_hermit x187, c_magician x150, c_death x148, c_fool x147, c_temperance x147, c_empress x109
- planets: pl_mercury x293, pl_uranus x73, pl_pluto x44, pl_jupiter x18, pl_earth x17, pl_saturn x16
- spectrals: s_black_hole x10, s_aura x9, s_immolate x8, s_deja_vu x7, s_talisman x7, s_medium x6
- jokers bought: j_popcorn x85, j_golden x78, j_faceless x71, j_todo_list x69, j_mail x64, j_ice_cream x62
- died on blind: Boss (168), Big (82), Small (39)


## Observations

- Highest win rate: struct_v4 baseline (best) (4.67%, 14/300); lowest: blanket_floor (hold >= $5) (3.33%). Gap: 1.33pp.
- Ante-1 death rate (low→high): reroll_gate (max1, min$10) 10.3%, struct_v4 baseline (best) 10.7%, joker_exempt_floor 11.7%, blanket_floor (hold >= $5) 12.3%, floor_joker_exempt + reroll_gate 12.3%

## Context / notes

- Ante-1 economy audit + fix attempts (2026-08-18). MOTIVATION: seeds die at the ante-1 Boss with /usr/bin/bash-2 and 1-3 weak commons. AUDIT FINDINGS: interest is paid on dollars at round end (min(dollars//5, cap)) but the agent enters the Big blind with /usr/bin/bash-4 in 287/300 seeds and the Boss with /usr/bin/bash-4 in 282/300 — interest collected in all of ante 1 totals ~3 across 100 seeds (near zero). Base income is fine (-11/blind at 0 held: 4 hands +  interest + -5 reward). VERDICT: every fix measured FLAT or WORSE and all were REVERTED — the bank's ante-1 ceiling is the lookahead oracle's 91.3% (26 deaths; the 18 Boss-death seeds hold 1-3 weak commons (Crazy/Square/Ticket/Droll) that the exact-draw oracle also cannot turn into clears); preserving cash at the expense of joker/booster power leaves runs underpowered.

## Reproduce

Commands (run from the repo root; each arm's telemetry was produced by its bench invocation — re-run with the same flags + --telemetry-dir --resume to regenerate instantly):
```
# struct_v4 baseline (best) — vendor\balatro-rl\results\struct_v4_tel\heuristic_v9
cd vendor/balatro-rl && python ../../bench/bench_v9.py --games 300 --policies heuristic_v9 --telemetry-dir results/struct_v4_tel
```
```
# blanket_floor (hold >= $5) — vendor\balatro-rl\results\econ_v1_tel\heuristic_v9
cd vendor/balatro-rl && python ../../bench/bench_v9.py --games 300 --policies heuristic_v9 --telemetry-dir results/econ_v1_tel
```
```
# joker_exempt_floor — vendor\balatro-rl\results\econ_v2_tel\heuristic_v9
cd vendor/balatro-rl && python ../../bench/bench_v9.py --games 300 --policies heuristic_v9 --telemetry-dir results/econ_v2_tel
```
```
# reroll_gate (max1, min$10) — vendor\balatro-rl\results\econ_rr_tel\heuristic_v9
cd vendor/balatro-rl && python ../../bench/bench_v9.py --games 300 --policies heuristic_v9 --params '{"reroll_max": 1, "reroll_min_money": 10}' --telemetry-dir results/econ_rr_tel
```
```
# floor_joker_exempt + reroll_gate — vendor\balatro-rl\results\econ_v4_tel\heuristic_v9
cd vendor/balatro-rl && python ../../bench/bench_v9.py --games 300 --policies heuristic_v9 --params '{"reroll_max": 1, "reroll_min_money": 10}' --telemetry-dir results/econ_v4_tel
```
