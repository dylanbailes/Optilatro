# Lua Replay Mod — Implementation Plan

**Purpose:** produce a polished video of the V7 Run 4 agent playing a won seed, for embedding in the `balatro-rl` README, LinkedIn Featured section, and portfolio.

**Status as of 2026-04-21:**
- Python eval + trajectory logging infrastructure complete (see "What's done" below)
- Lua mod work not started — this document is the handoff
- Project itself concluded; this is a portfolio/media task, not research

---

## 1. Goal

A 60–90 second video showing the V7 Run 4 agent playing one of its winning
Balatro seeds end-to-end, with on-screen overlays showing the agent's
top-3 action probabilities at each decision point. Uploaded to YouTube
(unlisted or public), embedded in the project README, pinned to LinkedIn.

**What this adds that the sim-only evidence doesn't:**
- Proof the project connects to the actual game (not just a Python sim)
- Visual interpretability — viewers see *why* the agent chose each action
- A scannable artifact for recruiters who won't read the retrospective

---

## 2. What's done (Python side — do not redo)

### Scripts (in `balatro-rl/scripts/`)

| File | What it does |
|------|-------------|
| `eval_with_trajectory.py` | Loads a V7 checkpoint, plays N episodes deterministically from random seeds, writes full per-step trajectory to JSONL |
| `find_replay_candidates.py` | Scores episodes by "interestingness" (win, discard rate, joker diversity, uncertainty, length), ranks top-N, dumps a CSV of seeds ready for the Lua mod |

### Trajectory schema (`results/eval_trajectories.jsonl`, one line per episode)

```json
{
  "episode_id": 0,
  "seed": 905672844,
  "outcome": {"ante": 9, "reward": 245.3, "steps": 187, "dollars": 43, "won": true},
  "trajectory": [
    {
      "step": 0,
      "phase": "blind_select",
      "ante": 1, "round": 1, "money": 0,
      "hand_cards": ["KH", "10C", ...],
      "jokers": ["Green Joker", ...],
      "value_estimate": 12.3,
      "action": {"type": "phase", "action": 0, "name": "select_blind"},
      "top_probs": [["select_blind", 0.95], ["skip_blind", 0.05]],
      "reward": 0.0
    },
    {
      "step": 1,
      "phase": "hand",
      "action": {"type": "hand", "intent": "play", "subset": [0, 2, 4, 6]},
      "top_probs": [["play", 0.88], ["discard", 0.10], ["use_consumable", 0.02]],
      "...": "..."
    }
  ]
}
```

**Phase names:** `"hand"`, `"blind_select"`, `"shop"`, `"game_over"`
**Hand action:** `{type: "hand", intent: "play"|"discard"|"use_consumable", subset: [0..7]}`
**Phase action:** `{type: "phase", action: int, name: string}`
 - For `blind_select`: action 0 = select, 1 = skip
 - For `shop`: action is an index (0..16) into the current shop menu;
   exact item mapping depends on shop contents at that moment

---

## 3. Lua mod work — what needs to change

The current training mod (`mod_v2/BalatroRL_v2.lua` or
`BalatroRL_parallel.lua`) was optimized for throughput: skips animations,
reads actions from an IPC file socket, re-uses state across instances.
For replay we need a separate variant — copy the parallel mod and modify.

### New file: `mod_v2/BalatroRL_replay.lua`

#### Required capabilities (in rough order of implementation)

1. **Config loading** — at mod start, read a JSON file at a fixed path (e.g.
   `C:/Users/Taggart/balatro_replay_config.json`) that contains:
   ```json
   {
     "seed": 905672844,
     "trajectory_path": "C:/Users/Taggart/balatro_replay_trajectory.json",
     "delay_ms": 1000,
     "show_overlays": true
   }
   ```

2. **Seed injection** — before the first game state is generated, force
   the game's RNG state from the config seed. Balatro uses `G.GAME.pseudorandom`
   and `pseudoseed()` functions; need to set `G.GAME.pseudorandom.seed = seed`
   *before* the first `new_round()` call. Verify reproducibility by playing
   the first 2–3 actions and confirming the deck order matches the sim's.

3. **Trajectory reader** — load the full trajectory JSON into a Lua table at
   startup. Maintain a `step_index` counter that advances each time an
   action is consumed.

4. **Action decoder** — translate the logged action format to the mod's
   existing action handlers:
   - `type="phase", name="select_blind"` → `G.FUNCS.select_blind()` (or whatever the mod currently calls)
   - `type="phase", name="skip_blind"` → `G.FUNCS.skip_blind()`
   - `type="phase", name="shop_action_N"` → resolve N against current shop (see §4 Gotchas)
   - `type="hand", intent="play", subset=[0,2,4]` → select cards at those hand indices, then `G.FUNCS.play_cards_from_highlighted()`
   - `type="hand", intent="discard", subset=[...]` → select cards, then `G.FUNCS.discard_cards_from_highlighted()`
   - `type="hand", intent="use_consumable"` → call the consumable-use handler

5. **Per-action delay** — after each action executes, wait `delay_ms`
   milliseconds before consuming the next. Balatro's `Game:update(dt)`
   loop is where we'd hook this — maintain a `next_action_at` timestamp
   and only advance when `love.timer.getTime() >= next_action_at`.

6. **Animation re-enablement** — the training mod likely skips
   `G.SETTINGS.GAMESPEED = 4` or similar. Replay should use normal speed
   (1.0) and NOT skip any animations. Also restore `G.SETTINGS.reduced_motion = false`
   if that was disabled for training.

7. **Overlay rendering** (optional but high-value) — draw a small floating
   panel on-screen showing the top-3 action probabilities from
   `top_probs` for the current step. Use `love.graphics.print` in
   `G:draw()`. Position bottom-left to not obscure game UI. Fade
   in/out as each decision point begins/ends.

8. **Auto-quit at game end** — when `trajectory` is exhausted OR the
   game reaches `PHASE_GAME_OVER`, print a final "REPLAY COMPLETE" banner
   and quit the game (or hold for 3 seconds then quit) for clean
   video capture.

### Files to touch

| File | Action |
|------|--------|
| `mod_v2/BalatroRL_parallel.lua` | Read for reference only (do not edit) |
| `mod_v2/BalatroRL_replay.lua` | **New file** — start from a copy of `BalatroRL_v2.lua` |
| `mod_v2/metadata.json` | Update to declare the replay variant as a mod option |
| `scripts/prepare_replay.py` | **New script** — extracts a single episode from the JSONL into the format the Lua mod expects, and writes the config file |

---

## 4. Known gotchas (read before starting)

### Shop actions

The `shop_action_N` log format records action *indices* but not the
actual shop items at that moment. Shop contents are seed-determined,
so if the seed reproduces correctly, the same index will correspond
to the same item. **Verify this.** If Balatro's shop shuffling depends
on earlier RNG calls (it likely does), then any divergence in RNG
consumption between the Python sim and the real Lua game will cause
action indices to point at different items, breaking the replay.

**Mitigation:** during `prepare_replay.py`, enrich each shop action
with the human-readable item name by inspecting the sim's shop state
from the trajectory's `hand_cards`/`jokers`/`state` fields (the sim
has helper methods to introspect shop contents; see `balatro_sim/shop.py`).
Then the Lua mod can do a name-based lookup instead of index-based,
which is robust to tiny RNG divergences.

### Consumable use

The sim's `intent="use_consumable"` doesn't record *which* consumable
or *what target* the agent used. This was fine for training (there's
only one consumable slot and the env decides), but for replay we may
need to extend the log format. **Check** whether V7 Run 4 actually
uses consumables often; if not (low-priority action in shaped reward),
a degraded replay that just "uses consumable slot 0 on card 0" may
be acceptable.

### RNG reproducibility gap

The Python sim (`balatro_sim/`) is an approximation of the real game.
V6's joker audit fixed 30% implementation errors, but small RNG-
consumption differences between sim and real game are possible. Test
this on episode step 0 first:
 1. Play a logged episode's seed in the real game
 2. Play the first action from the log
 3. Compare resulting hand/state to what the sim recorded

If they match for ~10 steps, the replay will work. If they diverge
within 3 steps, the sim's RNG model doesn't align with the real game's,
and you'll need either to (a) fix the sim or (b) do a best-effort
"human-guided replay" where the script offers the agent's choice
and a human hits confirm if the state still looks right.

### Balatro mod APIs

Balatro is written in LÖVE2D and uses Steamodded for modding. API
references:
 - Steamodded docs: `https://github.com/Steamopollys/Steamodded/wiki`
 - Key globals: `G` (top-level game state), `G.FUNCS` (action handlers),
   `G.GAME` (current game state), `G.STATE` (UI state machine)
 - Hook into `Game:update(dt)` for per-frame logic
 - Draw overlays in `Game:draw()`

The training mod already hooks these; the replay mod just needs
different behavior at the same hooks.

---

## 5. Execution checklist

### Milestone 1 — RNG reproducibility proof (highest risk, do first)

- [ ] Copy `BalatroRL_v2.lua` → `BalatroRL_replay.lua`, strip training IPC code
- [ ] Hard-code one seed from `eval_trajectories.jsonl`, force it at game start
- [ ] Print `G.playing_cards` (deck order) after first deal
- [ ] Compare to the same seed run in the sim (`balatro_sim/game.py`)
- [ ] **Gate:** if deck orders differ, stop and fix before any replay work

### Milestone 2 — action replay, no overlays

- [ ] Trajectory loader: read JSON into Lua table
- [ ] Action decoder: implement `play`, `discard`, `select_blind`, `skip_blind`
- [ ] Per-action delay loop
- [ ] Animation restoration (normal gamespeed)
- [ ] Test on a short 20-step episode; expect to hand-verify it plays correctly

### Milestone 3 — shop action support

- [ ] Implement shop action handler (resolving indices to names, see §4)
- [ ] Test on an episode that reaches ante 3+

### Milestone 4 — overlay rendering

- [ ] Draw top-3 probs panel (bottom-left, small font, semi-transparent bg)
- [ ] Fade logic: show panel when new action arrives, fade after ~700 ms
- [ ] Color-code: chosen action green, others gray

### Milestone 5 — recording + post

- [ ] Pick 2–3 candidate seeds from `results/replay_candidates.txt`
- [ ] Record each replay with OBS Studio (1080p, 60fps, game audio on)
- [ ] Trim to 60–90 seconds in any video editor (OBS output works in DaVinci Resolve free tier)
- [ ] Upload to YouTube, generate thumbnail showing peak moment
- [ ] Embed in `README.md` (use `[![thumbnail](url)](youtube-url)` pattern)
- [ ] Cross-post to LinkedIn Featured section

---

## 6. Decisions already made (do not re-debate)

- **Use V7 Run 4 checkpoint `iter_0920.pt`** — this is the peak 2.35% WR model
- **Source of truth for actions = the JSONL log**, not the real Lua game's parallel run — the sim is what the policy was trained against
- **Overlay shows top-3 probabilities, not full distribution** — full dist is too busy
- **Video length target = 60–90s** — short enough to embed, long enough to show progression from ante 1 to win
- **No live inference in the Lua mod** — logged actions only. Running PyTorch from Lua is out of scope

---

## 7. Out of scope

- Live policy inference from inside Balatro (would need PyTorch ↔ Lua bridge; huge project)
- Multiplayer / self-play replay (V8 failed anyway; not the story to tell)
- Alternative-policy overlay showing "what V6 would have done here" (interesting but too long for this video)
- Architecture animation / training-time visualizations (separate project)

---

## 8. Fresh-session primer for Claude Code

If you're starting a new Claude Code session and want to pick this up:

1. **Read this file first** — it's the full context.
2. **Then skim:**
   - `results/PROJECT_RETROSPECTIVE.md` for project context
   - `mod_v2/BalatroRL_v2.lua` for the existing Lua patterns
   - `balatro_sim/env_v7.py` around the action-handling logic
   - `scripts/eval_with_trajectory.py` (already written) for trajectory format
3. **Run the eval first** to generate `results/eval_trajectories.jsonl`:
   ```bash
   python scripts/eval_with_trajectory.py \
       --checkpoint checkpoints_v7_run4/iter_0920.pt \
       --n-episodes 2000 \
       --output results/eval_trajectories.jsonl
   python scripts/find_replay_candidates.py results/eval_trajectories.jsonl --top 20
   ```
4. **Start with Milestone 1 (RNG proof)** — everything else depends on it working.

Good luck, future-Claude. The Python infrastructure is solid. The Lua work is
bounded — probably 4–8 hours of focused work if the RNG gate passes on
first try, 10–15 hours if it doesn't and you need to fix the sim.

---

*Plan written 2026-04-21 after the Python logging pipeline was validated.
Project author: Taggart Tufte, Montana State '26.*
