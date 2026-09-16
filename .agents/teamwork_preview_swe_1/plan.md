# Orchestration Plan: Optilatro V11 Search Policy Scaling

## Task Assessment
- **Objective**: Scale V11 search policy (`agent_v11.py`) from 14% to 20%-25% win rate on Red Deck / White Stake against frozen V10 baseline on seeds 10500–10799 (N=300).
- **Complexity**: High (complex simulation, neural network valuation deltas, in-blind search/heuristic refinement, strict game invariants, paired benchmarks).
- **Pattern**: SWE Light sequential refinement.

## Steps
1. **Dispatch Implementation**:
   - Spawn `teamwork_preview_implementer` with verbatim task requirements.
   - Implement R1 (Universal Value Network shop scoring & early scaling growth), R2 (High-capital economy scaling & in-blind value squeezing), R3 (Mid-game deficit capital deployment), R4 (Human-fair invariants & preservation of baseline strengths).
   - Implementer runs static audits, seed exactness CI gate, and paired benchmark against V10 on seeds 10500-10799.
2. **Orchestrator Independent Verification 1**:
   - Inspect git diff in `vendor/balatro-rl/balatro_sim/agent_v11.py`.
   - Verify static audits and seed exactness pass.
   - Check paired benchmark metrics.
   - Maintain Open-Issues Ledger.
3. **Refinement Round 1 (teamwork_preview_reviewer)**:
   - Pass verbatim task + implementer's full report + open-issues ledger.
   - Reviewer stress-tests, breaks diff, fixes flaws, optimizes win rate, re-verifies.
4. **Refinement Round 2 (teamwork_preview_reviewer)**:
   - Second adversarial review round.
5. **Refinement Round 3 (teamwork_preview_reviewer)**:
   - Third adversarial review round (satisfying minimum 3 review rounds).
6. **Victory Audit**:
   - Dispatch `teamwork_preview_victory_auditor` to independently audit code, invariants, and benchmark results.
7. **Final Reporting**:
   - Deliver human report and message parent agent with full evidence bundle.
