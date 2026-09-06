# BRIEFING — 2026-09-04T07:35:00Z

## Mission
Remediate defects in agent_v10.py: fix critical discard deadlock bug when discards_left == 0, restrict scaling acceleration to disjoint in-hand knockout reservation (Ante > 1, hands_left >= 3, max 1/blind), and optimize shop finisher/xMult transitions to achieve >= 30 wins (>= 10%) on Red Deck/White Stake.

## 🔒 My Identity
- Archetype: teamwork_preview_worker_remedy_gen3
- Roles: implementer, qa, specialist
- Working directory: D:/Optilatro/.agents/teamwork_preview_worker_remedy_gen3
- Original parent: a6fe01c1-9f17-4c3f-adcb-a097f699dab4
- Milestone: M1 Iteration 2 Remediation

## 🔒 Key Constraints
- Exclusively own vendor/balatro-rl/balatro_sim/agent_v10.py and test files
- Zero draw-order peeking, zero future RNG consumption, zero live game mutation
- Discard candidate generation in tier2_value must strictly require game.discards_left > 0
- Scaling acceleration: Ante > 1, disjoint knockout K in hand with candidate C subset of hand \ K, hands_left >= 3, at most 1 scaling play per blind
- All verification requirements must pass (stress_m1_challenger.py 25/25, test_scaling_acceleration.py, test_agent_v10.py, test_seed_exactness.py -m ci_gate, 4 static audits, full test suite)

## Current Parent
- Conversation ID: a6fe01c1-9f17-4c3f-adcb-a097f699dab4
- Updated: 2026-09-04T07:35:00Z

## Task Summary
- **What to build**: Fix deadlock bug, fix scaling acceleration bug, optimize shop joker transitions in agent_v10.py
- **Success criteria**: 0 deadlocks on stress test, pass all test suites, >= 30 wins / 300 benchmark
- **Interface contracts**: vendor/balatro-rl/balatro_sim/agent_v10.py
- **Code layout**: vendor/balatro-rl/

## Key Decisions Made
- Initializing workspace and reviewing code defects

## Artifact Index
- DISPATCH.md — Dispatch instructions
- BRIEFING.md — Situational awareness
- progress.md — Progress heartbeat

## Change Tracker
- **Files modified**: None yet
- **Build status**: Untested
- **Pending issues**: Deadlock bug, scaling acceleration blind throws, win-rate bridge

## Quality Status
- **Build/test result**: Untested
- **Lint status**: Clean
- **Tests added/modified**: None yet

## Loaded Skills
- None
