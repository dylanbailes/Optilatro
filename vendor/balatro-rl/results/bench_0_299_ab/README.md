# Bench A/B results

- seed bank: **Seeds 0-299** · arms: 4 · generated: 2026-09-02 19:10

## Summary

| arm | wins | win % (95% CI) | mean ante | median ante | mean steps | ante-1 deaths | end w/ xMult | end w/ econ | mean $ |
|---|---|---|---|---|---|---|---|---|---|
| Baseline (goal_iter7_D) | 20/300 | 6.67% [4.36, 10.07] | 4.57 | 4 | 133 | 14 (4.7%) | 68% | 70% | 10.2 |
| Heuristic V9 (baseline) | 11/300 | 3.67% [2.06, 6.45] | 4.49 | 5 | 126 | 33 (11.0%) | 71% | 36% | 9.4 |
| Heuristic V10 | 10/300 | 3.33% [1.82, 6.03] | 4.27 | 4 | 123 | 27 (9.0%) | 68% | 67% | 9.4 |
| SearchShop V10 | 18/300 | 6.00% [3.83, 9.28] | 4.35 | 4 | 126 | 25 (8.3%) | 68% | 65% | 9.8 |

## Death by ante

### Baseline (goal_iter7_D) — 20/300 wins (6.67%)
  ante 1:   14 ( 4.67%) ########
  ante 2:   34 (11.33%) #####################
  ante 3:   38 (12.67%) ########################
  ante 4:   79 (26.33%) ##################################################
  ante 5:   50 (16.67%) ###############################
  ante 6:   36 (12.00%) ######################
  ante 7:   20 ( 6.67%) ############
  ante 8:    9 ( 3.00%) #####
  ante 9:   20 ( 6.67%) ############

### Heuristic V9 (baseline) — 11/300 wins (3.67%)
  ante 1:   33 (11.00%) #########################
  ante 2:   31 (10.33%) ########################
  ante 3:   30 (10.00%) #######################
  ante 4:   51 (17.00%) #######################################
  ante 5:   64 (21.33%) ##################################################
  ante 6:   37 (12.33%) ############################
  ante 7:   28 ( 9.33%) #####################
  ante 8:   15 ( 5.00%) ###########
  ante 9:   11 ( 3.67%) ########

### Heuristic V10 — 10/300 wins (3.33%)
  ante 1:   27 ( 9.00%) ###################
  ante 2:   36 (12.00%) ##########################
  ante 3:   39 (13.00%) ############################
  ante 4:   69 (23.00%) ##################################################
  ante 5:   57 (19.00%) #########################################
  ante 6:   25 ( 8.33%) ##################
  ante 7:   31 (10.33%) ######################
  ante 8:    6 ( 2.00%) ####
  ante 9:   10 ( 3.33%) #######

### SearchShop V10 — 18/300 wins (6.00%)
  ante 1:   25 ( 8.33%) #################
  ante 2:   39 (13.00%) ###########################
  ante 3:   38 (12.67%) ###########################
  ante 4:   70 (23.33%) ##################################################
  ante 5:   52 (17.33%) #####################################
  ante 6:   26 ( 8.67%) ##################
  ante 7:   25 ( 8.33%) #################
  ante 8:    7 ( 2.33%) #####
  ante 9:   18 ( 6.00%) ############


## Survival by ante (runs reaching at least ante N)

| arm | a1 | a2 | a3 | a4 | a5 | a6 | a7 | a8 | win |
|---|---|---|---|---|---|---|---|---|---|
| Baseline (goal_iter7_D) | 300 | 286 | 252 | 214 | 135 | 85 | 49 | 29 | 20 |
| Heuristic V9 (baseline) | 300 | 267 | 236 | 206 | 155 | 91 | 54 | 26 | 11 |
| Heuristic V10 | 300 | 273 | 237 | 198 | 129 | 72 | 47 | 16 | 10 |
| SearchShop V10 | 300 | 275 | 236 | 198 | 128 | 76 | 50 | 25 | 18 |

## Paired comparisons (per-seed, shared bank)

### Baseline (goal_iter7_D) → Heuristic V9 (baseline)
- shared seeds: 300 · wins Baseline (goal_iter7_D): 20 → Heuristic V9 (baseline): 11 (Δ -3.00pp)
- concordant: both-win 3 / both-loss 272 · discordant: Baseline (goal_iter7_D)-only 17 / Heuristic V9 (baseline)-only 8
- mean ante Δ (Heuristic V9 (baseline) − Baseline (goal_iter7_D)): -0.08

### Baseline (goal_iter7_D) → Heuristic V10
- shared seeds: 300 · wins Baseline (goal_iter7_D): 20 → Heuristic V10: 10 (Δ -3.33pp)
- concordant: both-win 6 / both-loss 276 · discordant: Baseline (goal_iter7_D)-only 14 / Heuristic V10-only 4
- mean ante Δ (Heuristic V10 − Baseline (goal_iter7_D)): -0.29

### Baseline (goal_iter7_D) → SearchShop V10
- shared seeds: 300 · wins Baseline (goal_iter7_D): 20 → SearchShop V10: 18 (Δ -0.67pp)
- concordant: both-win 8 / both-loss 270 · discordant: Baseline (goal_iter7_D)-only 12 / SearchShop V10-only 10
- mean ante Δ (SearchShop V10 − Baseline (goal_iter7_D)): -0.21

### Heuristic V9 (baseline) → Heuristic V10
- shared seeds: 300 · wins Heuristic V9 (baseline): 11 → Heuristic V10: 10 (Δ -0.33pp)
- concordant: both-win 3 / both-loss 282 · discordant: Heuristic V9 (baseline)-only 8 / Heuristic V10-only 7
- mean ante Δ (Heuristic V10 − Heuristic V9 (baseline)): -0.21

### Heuristic V9 (baseline) → SearchShop V10
- shared seeds: 300 · wins Heuristic V9 (baseline): 11 → SearchShop V10: 18 (Δ +2.33pp)
- concordant: both-win 4 / both-loss 275 · discordant: Heuristic V9 (baseline)-only 7 / SearchShop V10-only 14
- mean ante Δ (SearchShop V10 − Heuristic V9 (baseline)): -0.13

### Heuristic V10 → SearchShop V10
- shared seeds: 300 · wins Heuristic V10: 10 → SearchShop V10: 18 (Δ +2.67pp)
- concordant: both-win 9 / both-loss 281 · discordant: Heuristic V10-only 1 / SearchShop V10-only 9
- mean ante Δ (SearchShop V10 − Heuristic V10): +0.08


## End-of-run joker composition

| arm | xMult % | econ % | tarot-gen % | top end jokers |
|---|---|---|---|---|
| Baseline (goal_iter7_D) | 68% | 70% | 16% | j_cavendish x61, j_photograph x47, j_golden x43, j_abstract x39 |
| Heuristic V9 (baseline) | 71% | 36% | 14% | j_cavendish x50, j_raised_fist x43, j_abstract x39, j_splash x36 |
| Heuristic V10 | 68% | 67% | 16% | j_photograph x53, j_cavendish x49, j_golden x41, j_abstract x38 |
| SearchShop V10 | 68% | 65% | 16% | j_photograph x50, j_cavendish x50, j_raised_fist x40, j_abstract x38 |

## Usage stats

### Baseline (goal_iter7_D)
- money: mean $ 10.2 · spent $135.7 · rerolls 2.8 · packs 13.3
- score: max 467,859 · mean 28,735
- tarots: c_hermit x206, c_death x186, c_fool x181, c_magician x169, c_temperance x166, c_empress x133
- planets: pl_mercury x352, pl_uranus x98, pl_pluto x75, pl_jupiter x27, pl_earth x14, pl_venus x11
- spectrals: s_black_hole x11, s_ectoplasm x10, s_aura x8, s_immolate x8, s_cryptid x7, s_talisman x6
- jokers bought: j_popcorn x74, j_business x63, j_todo_list x62, j_faceless x61, j_hanging_chad x60, j_gros_michel x60
- died on blind: Boss (154), Big (72), Small (54)

### Heuristic V9 (baseline)
- money: mean $ 9.4 · spent $120.7 · rerolls 2.0 · packs 11.1
- score: max 306,025 · mean 29,865
- tarots: c_hermit x186, c_fool x165, c_death x155, c_temperance x140, c_magician x122, c_wheel_of_fortune x111
- planets: pl_mercury x351, pl_uranus x80, pl_pluto x46, pl_jupiter x18, pl_earth x12, pl_saturn x12
- spectrals: s_black_hole x10, s_aura x10, s_medium x7, s_immolate x7, s_ectoplasm x6, s_talisman x6
- jokers bought: j_reserved_parking x70, j_golden x68, j_swashbuckler x68, j_popcorn x68, j_faceless x66, j_todo_list x64
- died on blind: Boss (171), Big (89), Small (29)

### Heuristic V10
- money: mean $ 9.4 · spent $123.1 · rerolls 2.4 · packs 12.1
- score: max 172,656 · mean 21,636
- tarots: c_hermit x186, c_death x168, c_magician x157, c_fool x157, c_temperance x152, c_empress x122
- planets: pl_mercury x301, pl_uranus x114, pl_pluto x66, pl_jupiter x23, pl_saturn x15, pl_venus x11
- spectrals: s_black_hole x14, s_medium x8, s_aura x8, s_cryptid x7, s_immolate x6, s_incantation x5
- jokers bought: j_popcorn x70, j_ice_cream x62, j_egg x60, j_faceless x58, j_golden x57, j_blue_joker x56
- died on blind: Boss (166), Big (77), Small (47)

### SearchShop V10
- money: mean $ 9.8 · spent $126.6 · rerolls 2.5 · packs 12.8
- score: max 1,252,992 · mean 28,902
- tarots: c_hermit x202, c_death x170, c_temperance x163, c_magician x155, c_fool x149, c_empress x120
- planets: pl_mercury x280, pl_uranus x130, pl_pluto x82, pl_jupiter x24, pl_saturn x17, pl_venus x13
- spectrals: s_black_hole x14, s_medium x10, s_aura x7, s_immolate x6, s_talisman x6, s_cryptid x6
- jokers bought: j_popcorn x68, j_faceless x62, j_egg x59, j_ice_cream x56, j_golden x56, j_todo_list x54
- died on blind: Boss (174), Big (68), Small (40)


## Observations

- Highest win rate: Baseline (goal_iter7_D) (6.67%, 20/300); lowest: Heuristic V10 (3.33%). Gap: 3.33pp.
- Ante-1 death rate (low→high): Baseline (goal_iter7_D) 4.7%, SearchShop V10 8.3%, Heuristic V10 9.0%, Heuristic V9 (baseline) 11.0%

## Context / notes

- Full benchmark bank evaluation comparing V10 against frozen V9 and goal_iter7_final_D.json baseline.

## Reproduce

Commands (run from the repo root; each arm's telemetry was produced by its bench invocation — re-run with the same flags + --telemetry-dir --resume to regenerate instantly):
```
# Baseline (goal_iter7_D) — vendor\balatro-rl\results\bench_0_299_tel\goal_iter7_baseline
python bench/bench_agent_v10.py --games 300 --policies heuristic_v10
```
```
# Heuristic V9 (baseline) — vendor\balatro-rl\results\bench_0_299_tel\heuristic_v9
python bench/bench_agent_v10.py --games 300 --policies heuristic_v9
```
```
# Heuristic V10 — vendor\balatro-rl\results\bench_0_299_tel\heuristic_v10
python bench/bench_agent_v10.py --games 300 --policies heuristic_v10
```
```
# SearchShop V10 — vendor\balatro-rl\results\bench_0_299_tel\search_shop_v10
python bench/bench_agent_v10.py --games 300 --policies search_shop_v10
```
