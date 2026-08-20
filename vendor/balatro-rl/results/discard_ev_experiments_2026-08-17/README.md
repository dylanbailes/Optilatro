# Bench A/B results

- seed bank: **0..N-1 (per arm n)** · arms: 5 · generated: 2026-08-17 23:33

## Summary

| arm | wins | win % (95% CI) | mean ante | median ante | mean steps | ante-1 deaths | end w/ xMult | end w/ econ | mean $ |
|---|---|---|---|---|---|---|---|---|---|
| baseline_archived | 18/300 | 6.00% [3.83, 9.28] | 4.13 | 4 | 118 | 59 (19.7%) | 64% | 40% | 8.9 |
| v2_all_on | 12/300 | 4.00% [2.30, 6.86] | 4.32 | 4 | 127 | 44 (14.7%) | 65% | 44% | 9.3 |
| v2_no_gamble_no_econ | 16/300 | 5.33% [3.31, 8.49] | 4.43 | 5 | 130 | 43 (14.3%) | 70% | 32% | 9.9 |
| v2_gamble_no_econ | 14/300 | 4.67% [2.80, 7.68] | 4.44 | 4 | 130 | 43 (14.3%) | 67% | 37% | 9.8 |
| samples10_no_econ | 11/300 | 3.67% [2.06, 6.45] | 4.24 | 4 | 124 | 46 (15.3%) | 68% | 39% | 9.7 |

## Death by ante

### baseline_archived — 18/300 wins (6.00%)
  ante 1:   59 (19.67%) ##################################################
  ante 2:   26 ( 8.67%) ######################
  ante 3:   31 (10.33%) ##########################
  ante 4:   57 (19.00%) ################################################
  ante 5:   48 (16.00%) ########################################
  ante 6:   31 (10.33%) ##########################
  ante 7:   20 ( 6.67%) ################
  ante 8:   10 ( 3.33%) ########
  ante 9:   18 ( 6.00%) ###############

### v2_all_on — 12/300 wins (4.00%)
  ante 1:   44 (14.67%) ########################################
  ante 2:   31 (10.33%) ############################
  ante 3:   29 ( 9.67%) ##########################
  ante 4:   55 (18.33%) ##################################################
  ante 5:   50 (16.67%) #############################################
  ante 6:   40 (13.33%) ####################################
  ante 7:   27 ( 9.00%) ########################
  ante 8:   12 ( 4.00%) ##########
  ante 9:   12 ( 4.00%) ##########

### v2_no_gamble_no_econ — 16/300 wins (5.33%)
  ante 1:   43 (14.33%) ####################################
  ante 2:   30 (10.00%) #########################
  ante 3:   33 (11.00%) ###########################
  ante 4:   41 (13.67%) ##################################
  ante 5:   59 (19.67%) ##################################################
  ante 6:   34 (11.33%) ############################
  ante 7:   31 (10.33%) ##########################
  ante 8:   13 ( 4.33%) ###########
  ante 9:   16 ( 5.33%) #############

### v2_gamble_no_econ — 14/300 wins (4.67%)
  ante 1:   43 (14.33%) ###########################################
  ante 2:   29 ( 9.67%) #############################
  ante 3:   30 (10.00%) ##############################
  ante 4:   49 (16.33%) ##################################################
  ante 5:   49 (16.33%) ##################################################
  ante 6:   44 (14.67%) ############################################
  ante 7:   27 ( 9.00%) ###########################
  ante 8:   15 ( 5.00%) ###############
  ante 9:   14 ( 4.67%) ##############

### samples10_no_econ — 11/300 wins (3.67%)
  ante 1:   46 (15.33%) ######################################
  ante 2:   23 ( 7.67%) ###################
  ante 3:   41 (13.67%) ##################################
  ante 4:   59 (19.67%) ##################################################
  ante 5:   37 (12.33%) ###############################
  ante 6:   52 (17.33%) ############################################
  ante 7:   23 ( 7.67%) ###################
  ante 8:    8 ( 2.67%) ######
  ante 9:   11 ( 3.67%) #########


## Survival by ante (runs reaching at least ante N)

| arm | a1 | a2 | a3 | a4 | a5 | a6 | a7 | a8 | win |
|---|---|---|---|---|---|---|---|---|---|
| baseline_archived | 300 | 241 | 215 | 184 | 127 | 79 | 48 | 28 | 18 |
| v2_all_on | 300 | 256 | 225 | 196 | 141 | 91 | 51 | 24 | 12 |
| v2_no_gamble_no_econ | 300 | 257 | 227 | 194 | 153 | 94 | 60 | 29 | 16 |
| v2_gamble_no_econ | 300 | 257 | 228 | 198 | 149 | 100 | 56 | 29 | 14 |
| samples10_no_econ | 300 | 254 | 231 | 190 | 131 | 94 | 42 | 19 | 11 |

## Paired comparisons (per-seed, shared bank)

### baseline_archived → v2_all_on
- shared seeds: 300 · wins baseline_archived: 18 → v2_all_on: 12 (Δ -2.00pp)
- concordant: both-win 5 / both-loss 275 · discordant: baseline_archived-only 13 / v2_all_on-only 7
- mean ante Δ (v2_all_on − baseline_archived): +0.19

### baseline_archived → v2_no_gamble_no_econ
- shared seeds: 300 · wins baseline_archived: 18 → v2_no_gamble_no_econ: 16 (Δ -0.67pp)
- concordant: both-win 7 / both-loss 273 · discordant: baseline_archived-only 11 / v2_no_gamble_no_econ-only 9
- mean ante Δ (v2_no_gamble_no_econ − baseline_archived): +0.30

### baseline_archived → v2_gamble_no_econ
- shared seeds: 300 · wins baseline_archived: 18 → v2_gamble_no_econ: 14 (Δ -1.33pp)
- concordant: both-win 5 / both-loss 273 · discordant: baseline_archived-only 13 / v2_gamble_no_econ-only 9
- mean ante Δ (v2_gamble_no_econ − baseline_archived): +0.30

### baseline_archived → samples10_no_econ
- shared seeds: 300 · wins baseline_archived: 18 → samples10_no_econ: 11 (Δ -2.33pp)
- concordant: both-win 6 / both-loss 277 · discordant: baseline_archived-only 12 / samples10_no_econ-only 5
- mean ante Δ (samples10_no_econ − baseline_archived): +0.11

### v2_all_on → v2_no_gamble_no_econ
- shared seeds: 300 · wins v2_all_on: 12 → v2_no_gamble_no_econ: 16 (Δ +1.33pp)
- concordant: both-win 6 / both-loss 278 · discordant: v2_all_on-only 6 / v2_no_gamble_no_econ-only 10
- mean ante Δ (v2_no_gamble_no_econ − v2_all_on): +0.11

### v2_all_on → v2_gamble_no_econ
- shared seeds: 300 · wins v2_all_on: 12 → v2_gamble_no_econ: 14 (Δ +0.67pp)
- concordant: both-win 11 / both-loss 285 · discordant: v2_all_on-only 1 / v2_gamble_no_econ-only 3
- mean ante Δ (v2_gamble_no_econ − v2_all_on): +0.12

### v2_all_on → samples10_no_econ
- shared seeds: 300 · wins v2_all_on: 12 → samples10_no_econ: 11 (Δ -0.33pp)
- concordant: both-win 5 / both-loss 282 · discordant: v2_all_on-only 7 / samples10_no_econ-only 6
- mean ante Δ (samples10_no_econ − v2_all_on): -0.08

### v2_no_gamble_no_econ → v2_gamble_no_econ
- shared seeds: 300 · wins v2_no_gamble_no_econ: 16 → v2_gamble_no_econ: 14 (Δ -0.67pp)
- concordant: both-win 9 / both-loss 279 · discordant: v2_no_gamble_no_econ-only 7 / v2_gamble_no_econ-only 5
- mean ante Δ (v2_gamble_no_econ − v2_no_gamble_no_econ): +0.00

### v2_no_gamble_no_econ → samples10_no_econ
- shared seeds: 300 · wins v2_no_gamble_no_econ: 16 → samples10_no_econ: 11 (Δ -1.67pp)
- concordant: both-win 4 / both-loss 277 · discordant: v2_no_gamble_no_econ-only 12 / samples10_no_econ-only 7
- mean ante Δ (samples10_no_econ − v2_no_gamble_no_econ): -0.19

### v2_gamble_no_econ → samples10_no_econ
- shared seeds: 300 · wins v2_gamble_no_econ: 14 → samples10_no_econ: 11 (Δ -1.00pp)
- concordant: both-win 5 / both-loss 280 · discordant: v2_gamble_no_econ-only 9 / samples10_no_econ-only 6
- mean ante Δ (samples10_no_econ − v2_gamble_no_econ): -0.20


## End-of-run joker composition

| arm | xMult % | econ % | tarot-gen % | top end jokers |
|---|---|---|---|---|
| baseline_archived | 64% | 40% | 12% | j_cavendish x48, j_hanging_chad x37, j_splash x36, j_raised_fist x33 |
| v2_all_on | 65% | 44% | 13% | j_cavendish x54, j_splash x46, j_even_steven x34, j_blue_joker x33 |
| v2_no_gamble_no_econ | 70% | 32% | 9% | j_cavendish x55, j_splash x46, j_abstract x41, j_photograph x40 |
| v2_gamble_no_econ | 67% | 37% | 9% | j_cavendish x57, j_splash x47, j_blue_joker x34, j_photograph x34 |
| samples10_no_econ | 68% | 39% | 13% | j_cavendish x49, j_splash x43, j_photograph x39, j_raised_fist x37 |

## Usage stats

### baseline_archived
- money: mean $ 8.9 · spent $109.5 · rerolls 1.8 · packs 10.2
- score: max 1,379,704 · mean 32,007
- tarots: c_death x161, c_hermit x159, c_fool x136, c_magician x128, c_temperance x124, c_empress x103
- planets: pl_mercury x258, pl_uranus x75, pl_pluto x59, pl_saturn x43, pl_jupiter x30, pl_venus x14
- spectrals: s_black_hole x9, s_ectoplasm x8, s_aura x7, s_talisman x6, s_immolate x6, s_incantation x5
- jokers bought: j_popcorn x69, j_todo_list x66, j_golden x66, j_hanging_chad x63, j_faceless x60, j_egg x56
- died on blind: Boss (134), Big (94), Small (54)

### v2_all_on
- money: mean $ 9.3 · spent $118.8 · rerolls 2.1 · packs 11.2
- score: max 13,128,570 · mean 71,086
- tarots: c_hermit x201, c_death x175, c_fool x148, c_magician x141, c_temperance x129, c_wheel_of_fortune x116
- planets: pl_mercury x271, pl_uranus x105, pl_pluto x41, pl_saturn x33, pl_jupiter x24, pl_venus x20
- spectrals: s_black_hole x10, s_ectoplasm x10, s_immolate x7, s_talisman x7, s_aura x6, s_grim x6
- jokers bought: j_popcorn x76, j_todo_list x72, j_egg x68, j_reserved_parking x63, j_faceless x62, j_golden x61
- died on blind: Boss (145), Big (80), Small (63)

### v2_no_gamble_no_econ
- money: mean $ 9.9 · spent $123.2 · rerolls 2.2 · packs 11.9
- score: max 745,800 · mean 30,691
- tarots: c_hermit x220, c_death x191, c_fool x173, c_temperance x149, c_magician x149, c_wheel_of_fortune x126
- planets: pl_mercury x291, pl_uranus x107, pl_pluto x56, pl_saturn x54, pl_venus x26, pl_jupiter x14
- spectrals: s_black_hole x11, s_aura x8, s_ectoplasm x8, s_medium x7, s_talisman x7, s_grim x6
- jokers bought: j_popcorn x73, j_egg x66, j_abstract x62, j_swashbuckler x62, j_ice_cream x57, j_golden x56
- died on blind: Boss (149), Big (77), Small (58)

### v2_gamble_no_econ
- money: mean $ 9.8 · spent $121.6 · rerolls 2.2 · packs 11.9
- score: max 431,568 · mean 29,200
- tarots: c_hermit x208, c_death x188, c_fool x159, c_magician x152, c_temperance x137, c_wheel_of_fortune x124
- planets: pl_mercury x296, pl_uranus x111, pl_pluto x43, pl_saturn x40, pl_venus x26, pl_jupiter x17
- spectrals: s_black_hole x12, s_ectoplasm x10, s_aura x8, s_immolate x7, s_talisman x7, s_medium x5
- jokers bought: j_popcorn x82, j_egg x68, j_abstract x60, j_gros_michel x58, j_ice_cream x56, j_misprint x55
- died on blind: Boss (153), Big (71), Small (62)

### samples10_no_econ
- money: mean $ 9.7 · spent $115.4 · rerolls 1.8 · packs 10.7
- score: max 617,076 · mean 27,527
- tarots: c_death x174, c_hermit x173, c_fool x162, c_temperance x141, c_magician x122, c_empress x111
- planets: pl_mercury x257, pl_uranus x85, pl_saturn x61, pl_jupiter x38, pl_pluto x28, pl_venus x18
- spectrals: s_talisman x9, s_ectoplasm x8, s_immolate x8, s_aura x7, s_black_hole x6, s_cryptid x5
- jokers bought: j_popcorn x71, j_faceless x70, j_golden x68, j_todo_list x66, j_reserved_parking x63, j_abstract x59
- died on blind: Boss (150), Big (73), Small (66)


## Observations

- Highest win rate: baseline_archived (6.00%, 18/300); lowest: samples10_no_econ (3.67%). Gap: 2.33pp.
- Ante-1 death rate (low→high): v2_no_gamble_no_econ 14.3%, v2_gamble_no_econ 14.3%, v2_all_on 14.7%, samples10_no_econ 15.3%, baseline_archived 19.7%

## Context / notes

- Archived discard-EV A/B vs the 2026-08-17 human-fair baseline (18/300 = 6.00%, tel hf_ab_tel). All arms on the same 300-seed bank (0-299). v2 variants: structure-aware ceiling + top-K EV sampling, target-aware gamble, samples=10. Verdict: every variant measured WORSE than archived v1 (A 12, B 16, C 14, s10 11 vs 18/19); default reverted to v1-equivalent with samples=6.

## Reproduce

Commands (run from the repo root; each arm's telemetry was produced by its bench invocation — re-run with the same flags + --telemetry-dir --resume to regenerate instantly):
```
# baseline_archived — vendor\balatro-rl\results\hf_ab_tel\heuristic_v9
cd vendor/balatro-rl && python ../../bench/bench_v9.py --games 300 --policy heuristic_v9 --tel results/hf_ab_tel
```
```
# v2_all_on — vendor\balatro-rl\results\discard_v2_tel\heuristic_v9
cd vendor/balatro-rl && python ../../bench/bench_v9.py --games 300 --policy heuristic_v9 --params '{"discard_top_k": 4, "discard_flush_bonus": 0.06, "discard_target_aware": true, "discard_ev_samples": 6}' --tel results/discard_v2_tel
```
```
# v2_no_gamble_no_econ — vendor\balatro-rl\results\discard_v2b_tel\heuristic_v9
cd vendor/balatro-rl && python ../../bench/bench_v9.py --games 300 --policy heuristic_v9 --params '{"discard_top_k": 4, "discard_flush_bonus": 0.06, "discard_target_aware": false, "discard_ev_samples": 6, "econ_value_weight": 0.0, "gen_value_weight": 0.0}' --tel results/discard_v2b_tel
```
```
# v2_gamble_no_econ — vendor\balatro-rl\results\discard_v2c_tel\heuristic_v9
cd vendor/balatro-rl && python ../../bench/bench_v9.py --games 300 --policy heuristic_v9 --params '{"discard_top_k": 4, "discard_flush_bonus": 0.06, "discard_target_aware": true, "discard_ev_samples": 6, "econ_value_weight": 0.0, "gen_value_weight": 0.0}' --tel results/discard_v2c_tel
```
```
# samples10_no_econ — vendor\balatro-rl\results\discard_s10_tel\heuristic_v9
cd vendor/balatro-rl && python ../../bench/bench_v9.py --games 300 --policy heuristic_v9 --params '{"discard_ev_samples": 10, "econ_value_weight": 0.0, "gen_value_weight": 0.0}' --tel results/discard_s10_tel
```
