# Balatro RL — Version Archive

## Lua Mod Versions

| File | Description | Use for |
|------|-------------|---------|
| `BalatroRL_lua_nav.lua` | Lua handles blind select automatically via `new_round()`. Card play from Python. | Background training (no mouse needed) |
| `BalatroRL_no_nav.lua` | State writing + card play only. Zero autopilot. | When Python handles ALL navigation via mouse clicks |

**To switch:** copy the desired file to the active mod location:
```
Copy-Item versions\BalatroRL_lua_nav.lua  ..\AppData\Roaming\Balatro\Mods\BalatroRL\BalatroRL.lua
Copy-Item versions\BalatroRL_no_nav.lua   ..\AppData\Roaming\Balatro\Mods\BalatroRL\BalatroRL.lua
```
Then restart Balatro.

## Python Nav Versions

| File | Description | Use for |
|------|-------------|---------|
| `nav_mouse.py` | pyautogui + win32api physical mouse clicks. Window must be focused. | Manual testing / debugging |
| `balatro_rl/nav.py` | Active version (currently mouse-based) | Imported by test_nav.py and env.py |

**To switch nav.py:**
```
Copy-Item versions\nav_mouse.py balatro_rl\nav.py
```

## Test Scripts

| File | Description |
|------|-------------|
| `test_nav_mouse.py` | Full Python nav via mouse (you play cards, script clicks everything else) |
| `test_nav.py` | Active test script |

## Training

- `train.py --resume` — PPO training, uses env.py which calls nav.py internally
- Always use `--resume` after crashes to preserve model weights

## Active Config (as of 2026-03-18)

- Lua mod: `BalatroRL_lua_nav.lua` (Lua blind select + Python cash out/shop/restart via mouse)
- Nav: `nav_mouse.py` (physical mouse)
- Status: Lua blind select being tested via `new_round()` bypass
