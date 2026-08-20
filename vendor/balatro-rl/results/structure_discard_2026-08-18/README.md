# Bench A/B results

- seed bank: **0-299 (shared)** · arms: 3 · generated: 2026-08-18 01:02

## Summary

| arm | wins | win % (95% CI) | mean ante | median ante | mean steps | ante-1 deaths | end w/ xMult | end w/ econ | mean $ |
|---|---|---|---|---|---|---|---|---|---|
| baseline_archived (2026-08-17) | 18/300 | 6.00% [3.83, 9.28] | 4.13 | 4 | 118 | 59 (19.7%) | 64% | 40% | 8.9 |
| structure_rules_OFF (control) | 14/300 | 4.67% [2.80, 7.68] | 4.45 | 4 | 133 | 40 (13.3%) | 67% | 38% | 8.9 |
| structure_v4 (all rules ON) | 14/300 | 4.67% [2.80, 7.68] | 4.51 | 4 | 127 | 32 (10.7%) | 66% | 37% | 9.4 |

## Death by ante

### baseline_archived (2026-08-17) — 18/300 wins (6.00%)
  ante 1:   59 (19.67%) ##################################################
  ante 2:   26 ( 8.67%) ######################
  ante 3:   31 (10.33%) ##########################
  ante 4:   57 (19.00%) ################################################
  ante 5:   48 (16.00%) ########################################
  ante 6:   31 (10.33%) ##########################
  ante 7:   20 ( 6.67%) ################
  ante 8:   10 ( 3.33%) ########
  ante 9:   18 ( 6.00%) ###############

### structure_rules_OFF (control) — 14/300 wins (4.67%)
  ante 1:   40 (13.33%) ###################################
  ante 2:   25 ( 8.33%) ######################
  ante 3:   36 (12.00%) ################################
  ante 4:   56 (18.67%) ##################################################
  ante 5:   45 (15.00%) ########################################
  ante 6:   42 (14.00%) #####################################
  ante 7:   26 ( 8.67%) #######################
  ante 8:   16 ( 5.33%) ##############
  ante 9:   14 ( 4.67%) ############

### structure_v4 (all rules ON) — 14/300 wins (4.67%)
  ante 1:   32 (10.67%) ###############################
  ante 2:   34 (11.33%) #################################
  ante 3:   36 (12.00%) ###################################
  ante 4:   51 (17.00%) ##################################################
  ante 5:   46 (15.33%) #############################################
  ante 6:   40 (13.33%) #######################################
  ante 7:   32 (10.67%) ###############################
  ante 8:   15 ( 5.00%) ##############
  ante 9:   14 ( 4.67%) #############


## Survival by ante (runs reaching at least ante N)

| arm | a1 | a2 | a3 | a4 | a5 | a6 | a7 | a8 | win |
|---|---|---|---|---|---|---|---|---|---|
| baseline_archived (2026-08-17) | 300 | 241 | 215 | 184 | 127 | 79 | 48 | 28 | 18 |
| structure_rules_OFF (control) | 300 | 260 | 235 | 199 | 143 | 98 | 56 | 30 | 14 |
| structure_v4 (all rules ON) | 300 | 268 | 234 | 198 | 147 | 101 | 61 | 29 | 14 |

## Paired comparisons (per-seed, shared bank)

### baseline_archived (2026-08-17) → structure_rules_OFF (control)
- shared seeds: 300 · wins baseline_archived (2026-08-17): 18 → structure_rules_OFF (control): 14 (Δ -1.33pp)
- concordant: both-win 7 / both-loss 275 · discordant: baseline_archived (2026-08-17)-only 11 / structure_rules_OFF (control)-only 7
- mean ante Δ (structure_rules_OFF (control) − baseline_archived (2026-08-17)): +0.32

### baseline_archived (2026-08-17) → structure_v4 (all rules ON)
- shared seeds: 300 · wins baseline_archived (2026-08-17): 18 → structure_v4 (all rules ON): 14 (Δ -1.33pp)
- concordant: both-win 7 / both-loss 275 · discordant: baseline_archived (2026-08-17)-only 11 / structure_v4 (all rules ON)-only 7
- mean ante Δ (structure_v4 (all rules ON) − baseline_archived (2026-08-17)): +0.37

### structure_rules_OFF (control) → structure_v4 (all rules ON)
- shared seeds: 300 · wins structure_rules_OFF (control): 14 → structure_v4 (all rules ON): 14 (Δ +0.00pp)
- concordant: both-win 5 / both-loss 277 · discordant: structure_rules_OFF (control)-only 9 / structure_v4 (all rules ON)-only 9
- mean ante Δ (structure_v4 (all rules ON) − structure_rules_OFF (control)): +0.06


## End-of-run joker composition

| arm | xMult % | econ % | tarot-gen % | top end jokers |
|---|---|---|---|---|
| baseline_archived (2026-08-17) | 64% | 40% | 12% | j_cavendish x48, j_hanging_chad x37, j_splash x36, j_raised_fist x33 |
| structure_rules_OFF (control) | 67% | 38% | 14% | j_cavendish x50, j_splash x41, j_photograph x36, j_misprint x35 |
| structure_v4 (all rules ON) | 66% | 37% | 12% | j_cavendish x54, j_raised_fist x43, j_splash x41, j_even_steven x41 |

## Usage stats

### baseline_archived (2026-08-17)
- money: mean $ 8.9 · spent $109.5 · rerolls 1.8 · packs 10.2
- score: max 1,379,704 · mean 32,007
- tarots: c_death x161, c_hermit x159, c_fool x136, c_magician x128, c_temperance x124, c_empress x103
- planets: pl_mercury x258, pl_uranus x75, pl_pluto x59, pl_saturn x43, pl_jupiter x30, pl_venus x14
- spectrals: s_black_hole x9, s_ectoplasm x8, s_aura x7, s_talisman x6, s_immolate x6, s_incantation x5
- jokers bought: j_popcorn x69, j_todo_list x66, j_golden x66, j_hanging_chad x63, j_faceless x60, j_egg x56
- died on blind: Boss (134), Big (94), Small (54)

### structure_rules_OFF (control)
- money: mean $ 8.9 · spent $125.8 · rerolls 2.1 · packs 11.7
- score: max 6,752,844 · mean 81,899
- tarots: c_hermit x193, c_death x171, c_fool x157, c_temperance x151, c_magician x150, c_empress x120
- planets: pl_mercury x311, pl_uranus x109, pl_pluto x44, pl_jupiter x38, pl_saturn x28, pl_venus x19
- spectrals: s_ectoplasm x10, s_aura x9, s_immolate x8, s_incantation x7, s_talisman x7, s_cryptid x7
- jokers bought: j_faceless x76, j_golden x74, j_todo_list x71, j_popcorn x65, j_hanging_chad x64, j_business x63
- died on blind: Boss (156), Big (81), Small (49)

### structure_v4 (all rules ON)
- money: mean $ 9.4 · spent $124.2 · rerolls 2.0 · packs 11.4
- score: max 527,200 · mean 31,117
- tarots: c_hermit x197, c_fool x169, c_death x161, c_temperance x155, c_magician x139, c_empress x114
- planets: pl_mercury x362, pl_uranus x77, pl_pluto x47, pl_saturn x15, pl_jupiter x15, pl_earth x13
- spectrals: s_black_hole x14, s_aura x10, s_talisman x9, s_deja_vu x8, s_immolate x7, s_medium x6
- jokers bought: j_popcorn x73, j_todo_list x72, j_reserved_parking x68, j_mail x67, j_golden x66, j_faceless x65
- died on blind: Boss (179), Big (75), Small (32)


## Observations

- Highest win rate: baseline_archived (2026-08-17) (6.00%, 18/300); lowest: structure_rules_OFF (control) (4.67%). Gap: 1.33pp.
- Ante-1 death rate (low→high): structure_v4 (all rules ON) 10.7%, structure_rules_OFF (control) 13.3%, baseline_archived (2026-08-17) 19.7%

## Context / notes

- Structure-aware discard + hand-play refinement (2026-08-18). Goal: ante-1 clear via the user's rule — discard toward the most likely best hand, play good hands that score near the blind target. Three rules: (1) structural discard POOL committed to the best line (pairs > flush > straight — the old quality-weakest pool broke pairs/suits: seed 65 discarded its 8s+As pairs chasing a 1-card flush and died on High Card 16), (2) hold-until-clear (weak hands keep discarding instead of burning a hand on a non-clearing play), (3) play-good-hand (a hand scoring >= 50% of the REMAINING target is played — seed 228 held its 240 straight chasing a 5-heart flush and died 298/300; now wins the full run).

## Reproduce

Commands (run from the repo root; each arm's telemetry was produced by its bench invocation — re-run with the same flags + --telemetry-dir --resume to regenerate instantly):
```
# baseline_archived (2026-08-17) — vendor\balatro-rl\results\hf_ab_tel\heuristic_v9
cd vendor/balatro-rl && python ../../bench/bench_v9.py --games 300 --policies heuristic_v9 --telemetry-dir results/hf_ab_tel
```
```
# structure_rules_OFF (control) — vendor\balatro-rl\results\struct_off2_tel\heuristic_v9
cd vendor/balatro-rl && python ../../bench/bench_v9.py --games 300 --policies heuristic_v9 --params '{"discard_structure": false, "discard_hold_until_clear": false, "discard_play_good_hand": 2.0}' --telemetry-dir results/struct_off2_tel
```
```
# structure_v4 (all rules ON) — vendor\balatro-rl\results\struct_v4_tel\heuristic_v9
cd vendor/balatro-rl && python ../../bench/bench_v9.py --games 300 --policies heuristic_v9 --telemetry-dir results/struct_v4_tel
```
