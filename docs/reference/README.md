# Mechanics reference

[balatro-mechanics.md](balatro-mechanics.md) is the **source of truth** the
sim is audited against (wiki + balatro-rs cross-check).

It used to live at the repo root as `balatro-mechanics-reference(2).md`.
Generators resolve it through `tools/_paths.py` (`REFERENCE_DOC`).

After you edit the sheet:

```bash
python tools/gen_joker_spec.py
python tools/gen_consumable_spec.py
python tools/gen_boss_spec.py
python tools/gen_tag_spec.py
```

Then run the four `tools/audit_*_static.py` scripts. `apply_reference_updates.py`
is a one-shot historical patcher — do not re-run it on the current file.
