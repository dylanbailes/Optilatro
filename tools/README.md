# tools/

First-party scripts. Run from the **repo root**. Shared paths live in
[`_paths.py`](_paths.py).

## Spec generators (sheet → JSON)

| Script | Reads | Writes |
|---|---|---|
| `gen_joker_spec.py` | mechanics §2 + `JOKER_CATALOGUE` | `joker_spec.json` |
| `gen_consumable_spec.py` | mechanics §3–§5, §9 | `consumable_spec.json` |
| `gen_boss_spec.py` | mechanics §10, §16 | `boss_spec.json` |
| `gen_tag_spec.py` | mechanics §14 | `tag_spec.json` |
| `gen_joker_catalogue.py` | balatro-rs `joker_data!` | used to rebuild the shop catalogue |

A generator that cannot match doc ↔ sim keys exits 1.

## Static audits (CI)

| Script | Gates |
|---|---|
| `audit_jokers_static.py` | DUPES DEAD STUBS GAPS TYPE SIG STATE NOSCAN |
| `audit_consumables_static.py` | names, counts, planet map, targets, effects, wired |
| `audit_bosses_static.py` | min-ante, showdown, scaling, Matador 13, effects |
| `audit_tags_static.py` | names, ante gates, apply sites |
| `audit_diff_jokers.py` | name-level catalogue vs balatro-rs |
| `audit_dump_joker_data.py` | dump helper for the above |

```bash
python tools/audit_jokers_static.py
python tools/audit_consumables_static.py
python tools/audit_bosses_static.py
python tools/audit_tags_static.py
```

## Experiment / analysis

| Script | Use |
|---|---|
| `trace_run.py` | Per-blind replay of one seed (interest bookkeeping) |
| `report_bench_ab.py` | Pack telemetry dirs into a results folder + README |
| `sweep_v10.py` | V10 farm-knob ladder (`--tier2-only` for the second sweep) |
| `gen_synergy_tree.py` | Mine `co_owned` telemetry → `synergy_tree.json` |
| `gen_wiki_prior.py` | Scrape wiki synergy sections → `wiki_synergy_prior.json` |

## One-shot / do not re-run casually

| Script | Why |
|---|---|
| `apply_reference_updates.py` | Historical patch of the mechanics sheet. Already applied. |
| `apply_catalogue.py` | Catalogue rewrite helper from the joker-fidelity program. |
| `convert_joker_registry.py` | Registry migration leftover. |

## Generated JSON in this folder

- `*_spec.json` — commit with the sheet.
- `synergy_tree.json`, `synergy_tree_heuristic_v9.json`,
  `synergy_tree_search_shop_v9.json` — mined, large, do not hand-edit.
- `wiki_synergy_prior.json` — scraped prior.
