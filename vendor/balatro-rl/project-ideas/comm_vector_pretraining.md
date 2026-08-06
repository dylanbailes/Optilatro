# Idea: Comm Vector Pretraining via Evaluation Head

**Origin:** Tagg, 2026-03-31

## The Problem
V5 dual-agent training suffers because:
1. The play agent has never learned to use the 32-dim comm vector (initialized to zeros)
2. The shop agent has no idea what hand type the play agent is building
3. Both agents need to learn communication AND strategy simultaneously from scratch

## The Idea
Pretrain the communication channel before introducing a real shop agent.

Add a learned `EvalHead` module that generates a synthetic comm vector from game state features.
Train it jointly with the play agent in a v4-style single-agent loop.
The play agent learns to consume a meaningful 32-dim signal.
The eval head learns to produce something useful for the play agent.

```
GameState → EvalHead (32-dim comm vec) → PlayAgent obs (374-dim)
                 ↑
    trained jointly, gradients flow back through it
```

## Transfer to V5
After play agent reaches ante 4-5 reliably:
- Save eval head weights
- Initialize shop agent's comm_head from eval head weights
- The shop agent already knows the right output space
- The play agent already knows how to consume the signal

## Key Constraint
EvalHead should only use features available to the shop agent (188-dim shop obs space), not full privileged game state. This ensures the transfer from eval head → shop comm_head is valid.

## Connection to Research
- **Distillation:** Teacher (eval head with game state) → Student (shop agent with limited obs)
- **Auxiliary tasks in RL:** Side objective shapes representation without directly optimizing main reward
- **HIRO / Feudal Networks:** High-level policy sets goals for low-level policy — eval head is essentially learning what goal signal is useful

## Implementation Plan
1. Add `EvalHead` to train_sim.py (small MLP, game_state_features → 32-dim)
2. Modify `PlayActorCritic` to accept external comm vec or use eval head output
3. Train v4-style until ante 4-5 reliable (existing run 6 might already work as base)
4. Save eval head weights alongside play weights
5. In train_v5.py Phase B: init shop comm_head from eval head weights
6. Optionally: use eval head as auxiliary loss target for shop comm_head during early v5 training

## Priority
Medium — save for when v5 baseline is more stable or when there's time to implement properly.
Current v5 focus: get basic joint training working with replay buffer first.
