# Bench A/B results

- seed bank: **0..299 (300 seeds, White Stake, rng_mode=seed)** · arms: 4 · generated: 2026-08-17 23:02

## Summary

| arm | wins | win % (95% CI) | mean ante | median ante | mean steps | ante-1 deaths | end w/ xMult | end w/ econ | mean $ |
|---|---|---|---|---|---|---|---|---|---|
| heuristic_v9 (human-fair) | 18/300 | 6.00% [3.83, 9.28] | 4.13 | 4 | 118 | 59 (19.7%) | 64% | 40% | 8.9 |
| search_shop_v9 (comparative) | 18/300 | 6.00% [3.83, 9.28] | 4.13 | 4 | 118 | 59 (19.7%) | 64% | 40% | 8.9 |
| search_shop_v9 --lookahead (oracle) | 32/300 | 10.67% [7.66, 14.67] | 5.33 | 5 | 164 | 26 (8.7%) | 77% | 35% | 11.3 |
| heuristic_v9 (econ/gen terms OFF) | 19/300 | 6.33% [4.09, 9.68] | 4.22 | 4 | 122 | 56 (18.7%) | 67% | 33% | 8.8 |

## Death by ante

### heuristic_v9 (human-fair) — 18/300 wins (6.00%)
  ante 1:   59 (19.67%) ##################################################
  ante 2:   26 ( 8.67%) ######################
  ante 3:   31 (10.33%) ##########################
  ante 4:   57 (19.00%) ################################################
  ante 5:   48 (16.00%) ########################################
  ante 6:   31 (10.33%) ##########################
  ante 7:   20 ( 6.67%) ################
  ante 8:   10 ( 3.33%) ########
  ante 9:   18 ( 6.00%) ###############

### search_shop_v9 (comparative) — 18/300 wins (6.00%)
  ante 1:   59 (19.67%) ##################################################
  ante 2:   26 ( 8.67%) ######################
  ante 3:   31 (10.33%) ##########################
  ante 4:   57 (19.00%) ################################################
  ante 5:   48 (16.00%) ########################################
  ante 6:   31 (10.33%) ##########################
  ante 7:   20 ( 6.67%) ################
  ante 8:   10 ( 3.33%) ########
  ante 9:   18 ( 6.00%) ###############

### search_shop_v9 --lookahead (oracle) — 32/300 wins (10.67%)
  ante 1:   26 ( 8.67%) ####################
  ante 2:   15 ( 5.00%) ############
  ante 3:   11 ( 3.67%) ########
  ante 4:   47 (15.67%) #####################################
  ante 5:   62 (20.67%) ##################################################
  ante 6:   44 (14.67%) ###################################
  ante 7:   43 (14.33%) ##################################
  ante 8:   20 ( 6.67%) ################
  ante 9:   32 (10.67%) #########################

### heuristic_v9 (econ/gen terms OFF) — 19/300 wins (6.33%)
  ante 1:   56 (18.67%) ##################################################
  ante 2:   27 ( 9.00%) ########################
  ante 3:   32 (10.67%) ############################
  ante 4:   55 (18.33%) #################################################
  ante 5:   42 (14.00%) #####################################
  ante 6:   35 (11.67%) ###############################
  ante 7:   22 ( 7.33%) ###################
  ante 8:   12 ( 4.00%) ##########
  ante 9:   19 ( 6.33%) ################


## Survival by ante (runs reaching at least ante N)

| arm | a1 | a2 | a3 | a4 | a5 | a6 | a7 | a8 | win |
|---|---|---|---|---|---|---|---|---|---|
| heuristic_v9 (human-fair) | 300 | 241 | 215 | 184 | 127 | 79 | 48 | 28 | 18 |
| search_shop_v9 (comparative) | 300 | 241 | 215 | 184 | 127 | 79 | 48 | 28 | 18 |
| search_shop_v9 --lookahead (oracle) | 300 | 274 | 259 | 248 | 201 | 139 | 95 | 52 | 32 |
| heuristic_v9 (econ/gen terms OFF) | 300 | 244 | 217 | 185 | 130 | 88 | 53 | 31 | 19 |

## Paired comparisons (per-seed, shared bank)

### heuristic_v9 (human-fair) → search_shop_v9 (comparative)
- shared seeds: 300 · wins heuristic_v9 (human-fair): 18 → search_shop_v9 (comparative): 18 (Δ +0.00pp)
- concordant: both-win 18 / both-loss 282 · discordant: heuristic_v9 (human-fair)-only 0 / search_shop_v9 (comparative)-only 0
- mean ante Δ (search_shop_v9 (comparative) − heuristic_v9 (human-fair)): +0.00

### heuristic_v9 (human-fair) → search_shop_v9 --lookahead (oracle)
- shared seeds: 300 · wins heuristic_v9 (human-fair): 18 → search_shop_v9 --lookahead (oracle): 32 (Δ +4.67pp)
- concordant: both-win 18 / both-loss 268 · discordant: heuristic_v9 (human-fair)-only 0 / search_shop_v9 --lookahead (oracle)-only 14
- mean ante Δ (search_shop_v9 --lookahead (oracle) − heuristic_v9 (human-fair)): +1.20

### heuristic_v9 (human-fair) → heuristic_v9 (econ/gen terms OFF)
- shared seeds: 300 · wins heuristic_v9 (human-fair): 18 → heuristic_v9 (econ/gen terms OFF): 19 (Δ +0.33pp)
- concordant: both-win 12 / both-loss 275 · discordant: heuristic_v9 (human-fair)-only 6 / heuristic_v9 (econ/gen terms OFF)-only 7
- mean ante Δ (heuristic_v9 (econ/gen terms OFF) − heuristic_v9 (human-fair)): +0.09

### search_shop_v9 (comparative) → search_shop_v9 --lookahead (oracle)
- shared seeds: 300 · wins search_shop_v9 (comparative): 18 → search_shop_v9 --lookahead (oracle): 32 (Δ +4.67pp)
- concordant: both-win 18 / both-loss 268 · discordant: search_shop_v9 (comparative)-only 0 / search_shop_v9 --lookahead (oracle)-only 14
- mean ante Δ (search_shop_v9 --lookahead (oracle) − search_shop_v9 (comparative)): +1.20

### search_shop_v9 (comparative) → heuristic_v9 (econ/gen terms OFF)
- shared seeds: 300 · wins search_shop_v9 (comparative): 18 → heuristic_v9 (econ/gen terms OFF): 19 (Δ +0.33pp)
- concordant: both-win 12 / both-loss 275 · discordant: search_shop_v9 (comparative)-only 6 / heuristic_v9 (econ/gen terms OFF)-only 7
- mean ante Δ (heuristic_v9 (econ/gen terms OFF) − search_shop_v9 (comparative)): +0.09

### search_shop_v9 --lookahead (oracle) → heuristic_v9 (econ/gen terms OFF)
- shared seeds: 300 · wins search_shop_v9 --lookahead (oracle): 32 → heuristic_v9 (econ/gen terms OFF): 19 (Δ -4.33pp)
- concordant: both-win 12 / both-loss 261 · discordant: search_shop_v9 --lookahead (oracle)-only 20 / heuristic_v9 (econ/gen terms OFF)-only 7
- mean ante Δ (heuristic_v9 (econ/gen terms OFF) − search_shop_v9 --lookahead (oracle)): -1.11


## End-of-run joker composition

| arm | xMult % | econ % | tarot-gen % | top end jokers |
|---|---|---|---|---|
| heuristic_v9 (human-fair) | 64% | 40% | 12% | j_cavendish x48, j_hanging_chad x37, j_splash x36, j_raised_fist x33 |
| search_shop_v9 (comparative) | 64% | 40% | 12% | j_cavendish x48, j_hanging_chad x37, j_splash x36, j_raised_fist x33 |
| search_shop_v9 --lookahead (oracle) | 77% | 35% | 10% | j_cavendish x68, j_splash x46, j_raised_fist x44, j_even_steven x41 |
| heuristic_v9 (econ/gen terms OFF) | 67% | 33% | 10% | j_cavendish x51, j_splash x38, j_raised_fist x37, j_hanging_chad x36 |

## Usage stats

### heuristic_v9 (human-fair)
- money: mean $ 8.9 · spent $109.5 · rerolls 1.8 · packs 10.2
- score: max 1,379,704 · mean 32,007
- tarots: c_death x161, c_hermit x159, c_fool x136, c_magician x128, c_temperance x124, c_empress x103
- planets: pl_mercury x258, pl_uranus x75, pl_pluto x59, pl_saturn x43, pl_jupiter x30, pl_venus x14
- spectrals: s_black_hole x9, s_ectoplasm x8, s_aura x7, s_talisman x6, s_immolate x6, s_incantation x5
- jokers bought: j_popcorn x69, j_todo_list x66, j_golden x66, j_hanging_chad x63, j_faceless x60, j_egg x56
- died on blind: Boss (134), Big (94), Small (54)

### search_shop_v9 (comparative)
- money: mean $ 8.9 · spent $109.5 · rerolls 1.8 · packs 10.2
- score: max 1,379,704 · mean 32,007
- tarots: c_death x161, c_hermit x159, c_fool x136, c_magician x128, c_temperance x124, c_empress x103
- planets: pl_mercury x258, pl_uranus x75, pl_pluto x59, pl_saturn x43, pl_jupiter x30, pl_venus x14
- spectrals: s_black_hole x9, s_ectoplasm x8, s_aura x7, s_talisman x6, s_immolate x6, s_incantation x5
- jokers bought: j_popcorn x69, j_todo_list x66, j_golden x66, j_hanging_chad x63, j_faceless x60, j_egg x56
- died on blind: Boss (134), Big (94), Small (54)

### search_shop_v9 --lookahead (oracle)
- money: mean $ 11.3 · spent $156.7 · rerolls 2.8 · packs 14.6
- score: max 3,288,600 · mean 66,673
- tarots: c_hermit x261, c_fool x212, c_death x211, c_magician x206, c_temperance x181, c_empress x146
- planets: pl_mercury x386, pl_uranus x125, pl_pluto x71, pl_saturn x64, pl_jupiter x58, pl_venus x31
- spectrals: s_black_hole x15, s_aura x13, s_ectoplasm x10, s_immolate x9, s_deja_vu x8, s_talisman x8
- jokers bought: j_popcorn x91, j_todo_list x86, j_golden x85, j_business x83, j_hanging_chad x80, j_mail x76
- died on blind: Boss (151), Big (71), Small (46)

### heuristic_v9 (econ/gen terms OFF)
- money: mean $ 8.8 · spent $112.8 · rerolls 2.0 · packs 11.0
- score: max 14,826,636 · mean 78,472
- tarots: c_death x181, c_hermit x169, c_fool x148, c_temperance x141, c_magician x135, c_wheel_of_fortune x111
- planets: pl_mercury x272, pl_pluto x76, pl_uranus x70, pl_saturn x42, pl_jupiter x32, pl_venus x14
- spectrals: s_aura x11, s_black_hole x9, s_ectoplasm x9, s_medium x7, s_talisman x7, s_immolate x6
- jokers bought: j_popcorn x70, j_hanging_chad x64, j_swashbuckler x56, j_golden x55, j_misprint x54, j_egg x54
- died on blind: Boss (133), Big (95), Small (53)


## Observations

- Highest win rate: search_shop_v9 --lookahead (oracle) (10.67%, 32/300); lowest: heuristic_v9 (human-fair) (6.00%). Gap: 4.67pp.
- IDENTICAL results: heuristic_v9 (human-fair) == search_shop_v9 (comparative) (heuristic_v9 (human-fair) wins 18/300, same deaths) — these arms make the same decisions.
- No seed-level disagreement between 'heuristic_v9 (human-fair)' and 'search_shop_v9 (comparative)' — byte-identical policies.
- Ante-1 death rate (low→high): search_shop_v9 --lookahead (oracle) 8.7%, heuristic_v9 (econ/gen terms OFF) 18.7%, heuristic_v9 (human-fair) 19.7%, search_shop_v9 (comparative) 19.7%

## Context / notes

- Human-fair pivot benchmark: agents use only human-known info (deck composition, current shop, revealed boss); draw order / future shops / future bosses are never consulted.
- The comparative search shares _rank_shop_items + the same money gates + the same first-passing-argmax rule as L0, so it is byte-identical to the heuristic — it needs a different decision rule to add value.
- Isolation arm (econ/gen terms OFF) attributes the heuristic drop: 19/300 vs 18/300 — the new mean-measure valuation terms are neutral; the drop vs the recorded M9 heuristic (34/300 = 11.33%) is the discard-EV change (exact draw-order peek -> composition EV).
- The recorded M9 lookahead peak (70/300 = 23.33%) is not reproducible on this code: the rollout policy is now human-fair, so the historic peak bundled the shop-search oracle WITH exact-discard per-hand play.

## Reproduce

Commands (run from the repo root; each arm's telemetry was produced by its bench invocation — re-run with the same flags + --telemetry-dir --resume to regenerate instantly):
```
# heuristic_v9 (human-fair) — vendor\balatro-rl\results\hf_ab_tel\heuristic_v9
cd vendor/balatro-rl && python ../../bench/bench_v9.py --games 300 --policies heuristic_v9,search_shop_v9 --workers 16 --telemetry-dir results/hf_ab_tel
```
```
# search_shop_v9 (comparative) — vendor\balatro-rl\results\hf_ab_tel\search_shop_v9
same invocation as heuristic_v9 (human-fair) — one bench run, two policies
```
```
# search_shop_v9 --lookahead (oracle) — vendor\balatro-rl\results\lookahead_tel\search_shop_v9
cd vendor/balatro-rl && python ../../bench/bench_v9.py --games 300 --policies search_shop_v9 --lookahead --workers 16 --telemetry-dir results/lookahead_tel
```
```
# heuristic_v9 (econ/gen terms OFF) — vendor\balatro-rl\results\hf_iso_tel\heuristic_v9
cd vendor/balatro-rl && python ../../bench/bench_v9.py --games 300 --policies heuristic_v9 --workers 16 --telemetry-dir results/hf_iso_tel --params '{"econ_value_weight": 0, "gen_value_weight": 0}'
```
