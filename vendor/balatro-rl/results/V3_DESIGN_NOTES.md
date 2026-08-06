# V3 Design Notes — Socket IPC + Custom Threaded Training Loop

*Socket IPC developed 2026-03-27. Ray abandoned same day. Custom training loop: next.*

---

## Overview

V3 replaces file-based IPC with TCP socket IPC and replaces Ray RLlib with a custom
threaded PPO training loop. Action/observation space is unchanged from V2 (Discrete(20),
206-feature obs). The gain is throughput: ~90 steps/sec vs v2 parallel's ~6 steps/sec.

---

## Why We Moved Away From File IPC + Ray

**File IPC problems:**
- Polling introduces latency (50ms minimum round-trip)
- File writes can be missed at high game speeds (64x+)
- 3.31x slower than socket IPC at identical game speed

**Ray problems:**
- New API stack hangs on init (upstream Ray bug #53727)
- Old API VectorEnv steps all envs sequentially in one thread — no parallelism gained
- 8 envs sequential at best = 11.7 steps/sec total (same as 1 env)
- Sample timeout (600s) exceeded with 8 envs under normal step times
- After 10 bugs fixed over a full day, still stuck at 0.06-0.07 steps/sec

---

## Socket IPC Protocol

- **Transport:** TCP, IPv6 (Lua's `bind("*")` on Windows binds IPv6 only)
- **Format:** Newline-delimited JSON (`{"event": "selecting_hand", ...}\n`)
- **Ports:** 5000 + INSTANCE_ID → ports 5001-5008 for instances 1-8
- **Roles:** Lua = server, Python = client
- **Connection:** Persistent — connect once in `__init__`, reconnect only on drop

### State Send Protocol (no keep_fresh)
State is only sent on meaningful events — no continuous polling:
- **On connect:** Send current state immediately (`_send_on_connect` flag)
- **Play action:** G.STATE transitions fire naturally (SELECTING_HAND → HAND_PLAYED → ... → SELECTING_HAND)
- **Discard action:** Track `_prev_discards`; send when `current_round.discards_left` decreases
- **Fallback:** If no state sent within 4 game.update ticks (~200ms), send current state
  (handles invalid actions from random policy — e.g. discard when discards_left=0)

### Validated Performance
| Config | Steps/sec |
|--------|-----------|
| Socket, 64x, 1 env | 6.1 |
| Socket, 128x, 1 env | 11.7 |
| Socket, 128x, 8 envs (target) | ~90 |
| File IPC, 64x, 1 env | 1.8 |

Linear scaling confirmed: 64x → 128x = 2x throughput. No timing issues.

---

## Custom Threaded PPO Training Loop

### Why Custom vs Ray
Ray's VectorEnv is sequential — 8 envs gain nothing over 1 env in throughput.
Python's GIL releases during socket `recv()` calls (I/O), so threads genuinely overlap.
8 threads × 11.7 steps/sec = ~90 steps/sec actual concurrency.

### Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Training Process                      │
│                                                          │
│  Thread 1: Env 1 (port 5001) ──→ experience queue       │
│  Thread 2: Env 2 (port 5002) ──→ experience queue       │
│  ...                                                     │
│  Thread 8: Env 8 (port 5008) ──→ experience queue       │
│                                                          │
│  Main thread: drain queue → PPO update (PyTorch)        │
└─────────────────────────────────────────────────────────┘
```

### Implementation Plan (~200 lines PyTorch)

**Rollout collector (per thread):**
- Step env, store (obs, action, reward, done, log_prob, value) tuples
- On episode end: reset(), continue
- Fill until batch_size / num_envs steps collected, then push to shared queue

**PPO update (main thread):**
- Pull batch from queue when full
- Compute advantages (GAE)
- Run N epochs of minibatch gradient updates
- Log metrics, save checkpoint

**Hyperparameters (carry over from V2):**
- `batch_size=2048`, `minibatch_size=64`, `n_epochs=10`
- `lr=3e-4`, `gamma=0.99`, `lambda=0.95`
- `clip_param=0.2`, `entropy_coeff=0.01`

---

## Files

| File | Purpose |
|------|---------|
| `balatro_rl/env_socket.py` | Gymnasium env with socket IPC (validated) |
| `BalatroRL_v3.lua` | Lua socket server mod (all 8 instances, 128x speed) |
| `train_v3.py` | Custom threaded PPO training loop (to be written) |
| `train_ray_socket.py` | Ray attempt (abandoned, kept for reference) |
| `debug_ray.py` | 1-env Ray diagnostic (kept for reference) |

**Lua mod location (all instances):**
`C:\Users\Taggart\AppData\Roaming\Balatro\Mods\BalatroRL_v3\BalatroRL_v3.lua`

---

## Instance Setup

- 8 Balatro instances, 128x game speed
- Ports 5001-5008, IPv6, all listening at startup
- Instance 1: Steam install (`C:\Program Files (x86)\Steam\...`)
- Instances 2-8: `C:\BalatroParallel\Balatro_N\`
- Launch script: `launch_parallel.ps1`

---

## Current Status (2026-03-27)

- Socket IPC: fully validated (3 episodes, all transitions correct)
- Lua mod: deployed to all 8 instances, all bugs fixed
- env_socket.py: persistent connection, fallback timer, discard detection — all working
- Ray: abandoned after full-day debugging (see NOTES.md for complete bug log)
- train_v3.py: not yet written — next step
