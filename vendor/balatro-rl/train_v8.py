"""
train_v8.py — V8 self-play training using MultiplayerBalatroEnv.

Forked from train_v7.py. Key differences:

  1. Workers run MultiplayerBalatroEnv (two policies playing head-to-head)
  2. Same seed per game means both sides play identical starting conditions —
     stochastic sampling diverges them naturally, giving same-seed strategy comparison
  3. Both players' trajectories are collected and trained on (2x data per seed)
  4. V7 rewards still fire per-player PLUS multiplayer rewards:
     - PvP win: +3.0 / loss: -2.0
     - Life lost (any cause): -1.5
     - Game win (opponent at 0 lives): +20.0 / Game loss: -10.0
     - HOUSE RULE: failing regular blind also costs a life

For V8 Phase 1 (this script), both players share ONE policy network. Stochastic
sampling creates meaningful divergence. Phase 2 (future) will use multiple
policies with differentiated reward shaping.

Default: 20 workers x 1 MP env x 1024 MP steps = 40,960 agent-steps/batch
(each MP step produces 2 agent trajectory records)

Usage:
    python train_v8.py
    python train_v8.py --workers 20 --iterations 1000
    python train_v8.py --migrate-v7 checkpoints_v7_run4/iter_0920.pt
"""

import argparse
import json
import multiprocessing as mp
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim

from balatro_sim.env_mp import MultiplayerBalatroEnv, OBS_DIM
from balatro_sim.env_v7 import (
    N_PHASE_ACTIONS, N_HAND_SLOTS, PHASE_SELECTING_HAND,
)
from balatro_sim.card_selection import (
    INTENT_PLAY, INTENT_DISCARD, INTENT_USE_CONSUMABLE, N_INTENTS,
    enumerate_subsets, compute_subset_logits,
)

# Reuse network architecture + subset mask infrastructure from V7.
# ActorCriticV7 accepts obs_dim parameter — V8 passes MP OBS_DIM (438).
from train_v7 import (
    ActorCriticV7, compute_gae, ppo_update,
    LR, GAMMA, LAMBDA, CLIP, ENTROPY_COEFF, VF_COEFF, GRAD_CLIP,
    N_EPOCHS, MINIBATCH_SIZE, SUBSET_TEMPERATURE,
    INTENT_ENTROPY_COEFF, SUBSET_ENTROPY_COEFF,
    _get_subset_mask,
)

# ════════════════════════════════════════════════════════════════════════════
# V8-specific config
# ════════════════════════════════════════════════════════════════════════════

LOG_DIR  = Path("logs_v8")
CKPT_DIR = Path("checkpoints_v8")
LOG_DIR.mkdir(exist_ok=True)
CKPT_DIR.mkdir(exist_ok=True)

# V8 Run 2: temperature asymmetry between players
# P1 samples at temperature 1.0 (base policy)
# P2 samples at higher temperature → flatter distribution → more exploration
# Breaks symmetry between two copies of the same policy to reduce draw rate.
P2_TEMPERATURE = 1.4


# ════════════════════════════════════════════════════════════════════════════
# V7 migration removed — Run 3 uses extended obs (438) incompatible with
# V7 checkpoints (434). V8 trains from scratch with the multiplayer-aware
# observation from day 1.
# ════════════════════════════════════════════════════════════════════════════


# ════════════════════════════════════════════════════════════════════════════
# Worker process — MP self-play
# ════════════════════════════════════════════════════════════════════════════

def _worker_fn(worker_id: int, n_envs: int, steps_target: int,
               conn: mp.connection.Connection, seed_base: int):
    """
    Worker process running multiplayer Balatro envs with shared policy.

    Each MP env produces 2 agent trajectories per step (one for each player).
    We batch inference across both players in each env, then across all envs
    in the worker — so one forward call handles 2 * n_envs agent-steps.
    """
    import os, random as _random_mod
    os.environ["CUDA_VISIBLE_DEVICES"] = ""
    _rng = _random_mod.Random(seed_base + worker_id * 1000)

    # Each env has 2 players, so total "logical agents" in this worker is 2 * n_envs
    envs = [MultiplayerBalatroEnv(seed=_rng.randint(0, 2**31 - 1), lives=4)
            for _ in range(n_envs)]
    obs_pairs = [e.reset() for e in envs]  # list of (p1_obs, p2_obs)

    policy = ActorCriticV7(obs_dim=OBS_DIM).cpu().eval()

    # Per-env tracking for episode logging
    ep_steps = [0] * n_envs
    ep_reward_p1 = [0.0] * n_envs
    ep_reward_p2 = [0.0] * n_envs

    while True:
        msg = conn.recv()
        if msg is None:
            break
        policy.load_state_dict({k: v.cpu() for k, v in msg.items()})
        policy.eval()

        rollout: list[dict] = []
        episodes: list[dict] = []
        deadline = time.time() + 120  # longer deadline for MP

        steps_per_env = max(1, steps_target // n_envs)

        for step_i in range(steps_per_env):
            if time.time() > deadline:
                break

            # ── Gather obs from both players across all envs ───────────────
            # Total logical agents = 2 * n_envs (ordered as: env0_p1, env0_p2, env1_p1, ...)
            all_obs = []
            agent_meta = []  # list of (env_idx, player) pairs
            for i, env in enumerate(envs):
                p1_obs, p2_obs = obs_pairs[i]
                all_obs.append(p1_obs)
                agent_meta.append((i, 1))
                all_obs.append(p2_obs)
                agent_meta.append((i, 2))

            obs_batch = torch.from_numpy(np.stack(all_obs)).float()

            # Determine each agent's phase
            phases = []
            for (env_i, player) in agent_meta:
                phases.append(envs[env_i].get_phase(player))

            # Batched trunk + value
            with torch.no_grad():
                trunk = policy.get_trunk(obs_batch)
                values_b = policy.forward_value(trunk).cpu().numpy()

            # Split by phase
            hand_indices = [i for i, p in enumerate(phases) if p == PHASE_SELECTING_HAND]
            phase_indices = [i for i, p in enumerate(phases) if p != PHASE_SELECTING_HAND]

            # SELECTING_HAND batched inference
            hand_intents = {}
            hand_log_probs = {}
            hand_subset_idxs = {}
            hand_n_cards = {}
            hand_intent_masks = {}

            if hand_indices:
                hand_masks_np = np.stack([
                    envs[agent_meta[i][0]].get_intent_mask(agent_meta[i][1])
                    for i in hand_indices
                ])
                hand_mask_t = torch.from_numpy(hand_masks_np).bool()
                hand_trunk = trunk[hand_indices]

                # Build per-agent temperature vector (P2 gets higher temp)
                hand_temps = np.array([
                    P2_TEMPERATURE if agent_meta[i][1] == 2 else 1.0
                    for i in hand_indices
                ], dtype=np.float32)
                hand_temps_t = torch.from_numpy(hand_temps).float().unsqueeze(1)

                with torch.no_grad():
                    # Get raw logits, apply per-agent temperature, then sample
                    intent_logits = policy.intent_head(hand_trunk)
                    intent_logits = intent_logits.masked_fill(~hand_mask_t, float("-inf"))
                    scaled_logits = intent_logits / hand_temps_t
                    intent_dist = torch.distributions.Categorical(logits=scaled_logits)
                    intents_t = intent_dist.sample()
                    intent_lp = intent_dist.log_prob(intents_t).cpu().numpy()
                    intents_np = intents_t.cpu().numpy()

                    card_scores_t = policy.forward_card_scores(hand_trunk, intents_t)
                    card_scores_np = card_scores_t.cpu().numpy()

                for j, i in enumerate(hand_indices):
                    env_i, player = agent_meta[i]
                    intent_val = int(intents_np[j])
                    game = envs[env_i].mp.get_player_game(player)
                    n_cards = min(len(game.hand), N_HAND_SLOTS)
                    log_prob = float(intent_lp[j])
                    subset_idx = 0
                    # Per-player temperature for subset sampling too
                    temp = P2_TEMPERATURE if player == 2 else 1.0

                    if intent_val in (INTENT_PLAY, INTENT_DISCARD) and n_cards > 0:
                        subsets = enumerate_subsets(n_cards)
                        cs = card_scores_np[j, :n_cards]
                        subset_logits = compute_subset_logits(cs, subsets, intent_val)
                        sl_t = torch.from_numpy(subset_logits).float() / temp
                        sub_dist = torch.distributions.Categorical(logits=sl_t)
                        si_t = sub_dist.sample()
                        subset_idx = int(si_t.item())
                        log_prob += float(sub_dist.log_prob(si_t).item())

                    hand_intents[i] = intent_val
                    hand_log_probs[i] = log_prob
                    hand_subset_idxs[i] = subset_idx
                    hand_n_cards[i] = n_cards
                    hand_intent_masks[i] = hand_masks_np[j]

            # Other-phase batched inference
            phase_actions = {}
            phase_log_probs = {}
            phase_masks_dict = {}

            if phase_indices:
                phase_masks_np = np.stack([
                    envs[agent_meta[i][0]].get_phase_mask(agent_meta[i][1])
                    for i in phase_indices
                ])
                phase_mask_t = torch.from_numpy(phase_masks_np).bool()
                phase_trunk = trunk[phase_indices]

                # Per-agent temperature (P2 gets higher temp)
                phase_temps = np.array([
                    P2_TEMPERATURE if agent_meta[i][1] == 2 else 1.0
                    for i in phase_indices
                ], dtype=np.float32)
                phase_temps_t = torch.from_numpy(phase_temps).float().unsqueeze(1)

                with torch.no_grad():
                    phase_logits = policy.phase_head(phase_trunk)
                    phase_logits = phase_logits.masked_fill(~phase_mask_t, float("-inf"))
                    scaled_phase_logits = phase_logits / phase_temps_t
                    phase_dist = torch.distributions.Categorical(logits=scaled_phase_logits)
                    actions_t = phase_dist.sample()
                    phase_lp = phase_dist.log_prob(actions_t).cpu().numpy()
                    actions_np = actions_t.cpu().numpy()

                for j, i in enumerate(phase_indices):
                    phase_actions[i] = int(actions_np[j])
                    phase_log_probs[i] = float(phase_lp[j])
                    phase_masks_dict[i] = phase_masks_np[j]

            # ── Apply actions per env ──────────────────────────────────────
            for env_i, env in enumerate(envs):
                # Build p1 and p2 actions
                p1_agent_i = 2 * env_i
                p2_agent_i = 2 * env_i + 1

                actions = {}
                for agent_i, (is_p1) in [(p1_agent_i, True), (p2_agent_i, False)]:
                    phase_id = phases[agent_i]
                    if phase_id == PHASE_SELECTING_HAND:
                        intent = hand_intents[agent_i]
                        subset_idx = hand_subset_idxs[agent_i]
                        n_cards = hand_n_cards[agent_i]
                        if intent in (INTENT_PLAY, INTENT_DISCARD) and n_cards > 0:
                            subsets = enumerate_subsets(n_cards)
                            subset_idx_clamped = min(subset_idx, len(subsets) - 1)
                            subset = subsets[subset_idx_clamped]
                        else:
                            subset = (0,)
                        actions["p1" if is_p1 else "p2"] = {
                            "type": "hand", "intent": intent, "subset": subset,
                        }
                    else:
                        actions["p1" if is_p1 else "p2"] = {
                            "type": "phase", "action": phase_actions[agent_i],
                        }

                (p1_obs_next, p2_obs_next), (p1_r, p2_r), done, info = env.step(
                    actions["p1"], actions["p2"]
                )

                # Record rollout entries for both players
                for agent_i, (player, obs_cur, reward) in [
                    (p1_agent_i, (1, all_obs[p1_agent_i], p1_r)),
                    (p2_agent_i, (2, all_obs[p2_agent_i], p2_r)),
                ]:
                    phase_id = phases[agent_i]
                    value = float(values_b[agent_i])
                    if phase_id == PHASE_SELECTING_HAND:
                        rollout.append({
                            "obs": obs_cur.copy(),
                            "log_prob": hand_log_probs[agent_i],
                            "value": value,
                            "reward": float(reward),
                            "done": float(done),
                            "phase_id": PHASE_SELECTING_HAND,
                            "intent": hand_intents[agent_i],
                            "subset_idx": hand_subset_idxs[agent_i],
                            "n_cards": hand_n_cards[agent_i],
                            "intent_mask": hand_intent_masks[agent_i].copy(),
                            "player": player,
                        })
                    else:
                        rollout.append({
                            "obs": obs_cur.copy(),
                            "log_prob": phase_log_probs[agent_i],
                            "value": value,
                            "reward": float(reward),
                            "done": float(done),
                            "phase_id": phase_id,
                            "phase_action": phase_actions[agent_i],
                            "phase_mask": phase_masks_dict[agent_i].copy(),
                            "player": player,
                        })

                ep_steps[env_i] += 1
                ep_reward_p1[env_i] += p1_r
                ep_reward_p2[env_i] += p2_r

                # Safety truncation
                if not done and ep_steps[env_i] >= 3000:
                    done = True

                if done:
                    episodes.append({
                        "steps": ep_steps[env_i],
                        "p1_ante": info.get("p1_ante", 1),
                        "p2_ante": info.get("p2_ante", 1),
                        "p1_lives": info.get("p1_lives", 0),
                        "p2_lives": info.get("p2_lives", 0),
                        "winner": info.get("winner", 0),
                        "p1_reward": ep_reward_p1[env_i],
                        "p2_reward": ep_reward_p2[env_i],
                        # Best ante reached across both players
                        "best_ante": max(info.get("p1_ante", 1), info.get("p2_ante", 1)),
                    })
                    # Reset env with new seed
                    env._seed = _rng.randint(0, 2**31 - 1)
                    obs_pairs[env_i] = env.reset()
                    ep_steps[env_i] = 0
                    ep_reward_p1[env_i] = 0.0
                    ep_reward_p2[env_i] = 0.0
                else:
                    obs_pairs[env_i] = (p1_obs_next, p2_obs_next)

        # Bootstrap values (batched)
        bootstrap_obs = []
        for i in range(n_envs):
            p1_obs, p2_obs = obs_pairs[i]
            bootstrap_obs.append(p1_obs)
            bootstrap_obs.append(p2_obs)
        with torch.no_grad():
            obs_batch = torch.from_numpy(np.stack(bootstrap_obs)).float()
            trunk = policy.get_trunk(obs_batch)
            next_values = policy.forward_value(trunk).cpu().numpy().tolist()

        conn.send({
            "rollout": rollout,
            "next_values": next_values,
            "episodes": episodes,
        })


# ════════════════════════════════════════════════════════════════════════════
# Main training loop
# ════════════════════════════════════════════════════════════════════════════

def train(num_workers: int, envs_per_worker: int, steps_per_worker: int,
          num_iterations: int, resume_path: str | None,
          minibatch_size: int = MINIBATCH_SIZE):

    device      = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    # batch_size = agent-steps per iter (each MP step produces 2 agent records)
    batch_size  = num_workers * envs_per_worker * steps_per_worker * 2

    policy    = ActorCriticV7(obs_dim=OBS_DIM).to(device)
    optimizer = optim.Adam(policy.parameters(), lr=LR, eps=1e-5)

    start_iter  = 0
    total_steps = 0
    best_ante   = 1
    episode_log: list[dict] = []

    if resume_path and Path(resume_path).exists():
        ckpt = torch.load(resume_path, map_location=device)
        policy.load_state_dict(ckpt["policy"])
        optimizer.load_state_dict(ckpt["optimizer"])
        start_iter  = ckpt.get("iteration", 0)
        total_steps = ckpt.get("total_steps", 0)
        best_ante   = ckpt.get("best_ante", 1)
        print(f"Resumed from {resume_path}  (iter {start_iter}, {total_steps:,} steps)")

    # Spawn workers
    seed_base = int(time.time()) % 100000
    workers: list[mp.Process] = []
    conns_main: list[mp.connection.Connection] = []

    for wid in range(num_workers):
        conn_main, conn_worker = mp.Pipe()
        p = mp.Process(
            target=_worker_fn,
            args=(wid, envs_per_worker, steps_per_worker, conn_worker, seed_base),
            daemon=True,
        )
        p.start()
        workers.append(p)
        conns_main.append(conn_main)

    n_params = sum(p.numel() for p in policy.parameters())
    print(f"\n{'='*75}")
    print(f"train_v8.py — Self-Play Multiplayer Balatro")
    print(f"  workers={num_workers}  envs/worker={envs_per_worker}  "
          f"steps/worker={steps_per_worker}")
    print(f"  agent-steps/iter={batch_size:,}  minibatch={minibatch_size}  epochs={N_EPOCHS}")
    print(f"  obs={OBS_DIM}  intents={N_INTENTS}  phase_actions={N_PHASE_ACTIONS}  "
          f"params={n_params:,}")
    print(f"  device={device}")
    print(f"  intent_ent={INTENT_ENTROPY_COEFF}  subset_ent={SUBSET_ENTROPY_COEFF}  "
          f"phase_ent={ENTROPY_COEFF}")
    print(f"{'='*75}\n")

    log_path = LOG_DIR / "training_v8.log"
    t_start  = time.time()
    t_iter   = t_start

    weights = {k: v.cpu() for k, v in policy.state_dict().items()}

    for iteration in range(start_iter, start_iter + num_iterations):

        # Send weights
        for conn in conns_main:
            conn.send(weights)

        # Collect rollouts
        all_obs, all_ret, all_adv, all_logp = [], [], [], []
        all_phase_ids, all_intents, all_subset_idxs, all_n_cards = [], [], [], []
        all_intent_masks, all_phase_actions, all_phase_masks = [], [], []
        iter_episodes: list[dict] = []
        intent_counts = [0, 0, 0]

        for conn in conns_main:
            data = conn.recv()
            r    = data["rollout"]
            nvs  = data["next_values"]
            eps  = data["episodes"]
            iter_episodes.extend(eps)

            if not r:
                continue

            rewards = np.array([s["reward"]  for s in r], dtype=np.float32)
            values  = np.array([s["value"]   for s in r], dtype=np.float32)
            dones   = np.array([s["done"]    for s in r], dtype=np.float32)
            logps   = np.array([s["log_prob"] for s in r], dtype=np.float32)
            obs_arr = np.stack([s["obs"]     for s in r])

            phase_ids = np.array([s["phase_id"] for s in r], dtype=np.int64)
            intents = np.array([s.get("intent", 0) for s in r], dtype=np.int64)
            subset_idxs = np.array([s.get("subset_idx", 0) for s in r], dtype=np.int64)
            n_cards = np.array([s.get("n_cards", 0) for s in r], dtype=np.int64)

            intent_masks = np.zeros((len(r), N_INTENTS), dtype=bool)
            phase_masks = np.zeros((len(r), N_PHASE_ACTIONS), dtype=bool)
            phase_actions = np.zeros(len(r), dtype=np.int64)

            for j, s in enumerate(r):
                if s["phase_id"] == PHASE_SELECTING_HAND:
                    intent_masks[j] = s.get("intent_mask", np.ones(N_INTENTS, dtype=bool))
                    intent_counts[s.get("intent", 0)] += 1
                else:
                    phase_masks[j] = s.get("phase_mask", np.ones(N_PHASE_ACTIONS, dtype=bool))
                    phase_actions[j] = s.get("phase_action", 0)

            # GAE — we have 2 * envs_per_worker interleaved agent trajectories per worker
            # The worker records them in order: env0_p1, env0_p2, env0_p1, env0_p2, ...
            # (Each env's two players are updated simultaneously.)
            # So we interleave-split: even indices = env0_p1, odd = env0_p2
            # Then for multi-env workers, records are grouped by env per step.

            # For simplicity, each MP env's two players are treated as independent
            # trajectories. Since per-step they interleave (p1, p2, p1, p2, ...),
            # we split into 2 * envs_per_worker trajectories.

            # The rollout records order per step is: [env0_p1, env0_p2, env1_p1, env1_p2, ...]
            # Across steps: [step0_env0_p1, step0_env0_p2, step0_env1_p1, step0_env1_p2,
            #                step1_env0_p1, step1_env0_p2, ...]
            # So trajectory stride = 2 * envs_per_worker per agent
            stride = 2 * envs_per_worker
            n_agents = stride  # each agent gets one trajectory
            assert len(r) % stride == 0, f"rollout len {len(r)} not divisible by stride {stride}"
            n_per_agent = len(r) // stride

            for agent_i in range(n_agents):
                idxs = np.arange(agent_i, len(r), stride)
                r_agent = rewards[idxs]
                v_agent = values[idxs]
                d_agent = dones[idxs]
                nv = nvs[agent_i] if agent_i < len(nvs) else 0.0
                adv, ret = compute_gae(r_agent, v_agent, d_agent, nv)
                all_obs.append(obs_arr[idxs])
                all_ret.append(ret)
                all_adv.append(adv)
                all_logp.append(logps[idxs])
                all_phase_ids.append(phase_ids[idxs])
                all_intents.append(intents[idxs])
                all_subset_idxs.append(subset_idxs[idxs])
                all_n_cards.append(n_cards[idxs])
                all_intent_masks.append(intent_masks[idxs])
                all_phase_actions.append(phase_actions[idxs])
                all_phase_masks.append(phase_masks[idxs])

        if not all_obs:
            continue

        rollout_batch = {
            "obs":           np.concatenate(all_obs),
            "returns":       np.concatenate(all_ret),
            "advantages":    np.concatenate(all_adv),
            "log_probs":     np.concatenate(all_logp),
            "phase_ids":     np.concatenate(all_phase_ids),
            "intents":       np.concatenate(all_intents),
            "subset_idxs":   np.concatenate(all_subset_idxs),
            "n_cards":       np.concatenate(all_n_cards),
            "intent_masks":  np.concatenate(all_intent_masks),
            "phase_actions": np.concatenate(all_phase_actions),
            "phase_masks":   np.concatenate(all_phase_masks),
        }

        total_steps += len(rollout_batch["obs"])

        # PPO update (reuses V7's update)
        metrics = ppo_update(policy, optimizer, rollout_batch, device, minibatch_size)
        weights = {k: v.cpu() for k, v in policy.state_dict().items()}

        # Logging
        t_now    = time.time()
        iter_sec = max(t_now - t_iter, 1e-6)
        t_iter   = t_now
        sps      = len(rollout_batch["obs"]) / iter_sec
        eps      = len(iter_episodes)

        if iter_episodes:
            iter_best = max(e["best_ante"] for e in iter_episodes)
            if iter_best > best_ante:
                best_ante = iter_best
                tag = f"  *** NEW BEST ante={best_ante} ***"
            else:
                tag = ""
            mean_reward_p1 = np.mean([e["p1_reward"] for e in iter_episodes])
            mean_reward_p2 = np.mean([e["p2_reward"] for e in iter_episodes])
            p1_wins = sum(1 for e in iter_episodes if e["winner"] == 1)
            p2_wins = sum(1 for e in iter_episodes if e["winner"] == 2)
            draws   = sum(1 for e in iter_episodes if e["winner"] == 0)
        else:
            iter_best = best_ante
            tag = ""
            mean_reward_p1 = 0.0
            mean_reward_p2 = 0.0
            p1_wins = p2_wins = draws = 0

        total_intents = sum(intent_counts)
        if total_intents > 0:
            pct_play = intent_counts[0] / total_intents * 100
            pct_disc = intent_counts[1] / total_intents * 100
            pct_cons = intent_counts[2] / total_intents * 100
            intent_str = f"P={pct_play:.0f}% D={pct_disc:.0f}% C={pct_cons:.0f}%"
        else:
            intent_str = "N/A"

        status = (
            f"[{total_steps/1e6:.3f}M] iter={iteration+1:<5d} "
            f"sps={sps:<7.0f} eps={eps:<4d} p1W={p1_wins:<3d} p2W={p2_wins:<3d} dr={draws:<3d} "
            f"rew={mean_reward_p1:<6.1f}/{mean_reward_p2:<6.1f} "
            f"loss={metrics['loss']:.4f} pg={metrics['pg_loss']:.4f} "
            f"vf={metrics['vf_loss']:.4f} "
            f"ent_i={metrics['ent_intent']:.3f} ent_p={metrics['ent_phase']:.3f} "
            f"intents=[{intent_str}] "
            f"best={best_ante} ({iter_sec:.1f}s){tag}"
        )
        print(status)
        with open(log_path, "a") as f:
            f.write(status + "\n")

        for ep in iter_episodes:
            ep["iteration"] = iteration + 1
        episode_log.extend(iter_episodes)

        # Checkpoint
        if (iteration + 1) % 10 == 0:
            ckpt_path = CKPT_DIR / f"iter_{iteration+1:04d}.pt"
            torch.save({
                "policy":      policy.state_dict(),
                "optimizer":   optimizer.state_dict(),
                "iteration":   iteration + 1,
                "total_steps": total_steps,
                "best_ante":   best_ante,
            }, ckpt_path)
            with open(CKPT_DIR / "episode_log.jsonl", "a") as f:
                for ep in episode_log:
                    f.write(json.dumps(ep) + "\n")
            episode_log.clear()
            print(f"  -> checkpoint saved: {ckpt_path}")

    # Shutdown
    for conn in conns_main:
        conn.send(None)
    for p in workers:
        p.join(timeout=5)

    total_time = time.time() - t_start
    print(f"\nDone. {num_iterations} iters | {total_steps:,} steps | "
          f"{total_time/60:.1f} min | best ante: {best_ante}")


# ════════════════════════════════════════════════════════════════════════════
# Entry point
# ════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    mp.set_start_method("spawn", force=True)

    parser = argparse.ArgumentParser()
    parser.add_argument("--workers",          type=int, default=20)
    parser.add_argument("--envs-per-worker",  type=int, default=1)
    parser.add_argument("--steps-per-worker", type=int, default=1024)
    parser.add_argument("--iterations",       type=int, default=1000)
    parser.add_argument("--resume",           type=str, default=None,
                        help="Resume a V8 checkpoint (same obs_dim required)")
    parser.add_argument("--minibatch",        type=int, default=MINIBATCH_SIZE)
    args = parser.parse_args()

    train(
        num_workers      = args.workers,
        envs_per_worker  = args.envs_per_worker,
        steps_per_worker = args.steps_per_worker,
        num_iterations   = args.iterations,
        resume_path      = args.resume,
        minibatch_size   = args.minibatch,
    )
