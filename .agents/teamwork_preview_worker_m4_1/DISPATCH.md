## 2026-09-02T22:51:09Z
You are teamwork_preview_worker for Milestone 4: True L1 Counterfactual Shop Search (SearchShopV10) (R4).
Your working directory is: D:/Optilatro/.agents/teamwork_preview_worker_m4_1

Read ORIGINAL_REQUEST.md at: D:/Optilatro/ORIGINAL_REQUEST.md
Read PROJECT.md at: D:/Optilatro/PROJECT.md
Read M2 handoff at: D:/Optilatro/.agents/teamwork_preview_worker_m2_1/handoff.md
Read M3 handoff at: D:/Optilatro/.agents/teamwork_preview_worker_m3_1/handoff.md
Also review AGENTS.md at: D:/Optilatro/AGENTS.md.

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A teamwork_preview_auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

Scope & Tasks:
1. You exclusively own: `vendor/balatro-rl/balatro_sim/agent_v10.py` (specifically `SearchShopV10`, `_search_shop`, and helper value model evaluation functions) and `vendor/balatro-rl/balatro_sim/agent_l1.py`. Do NOT touch `agent_v9.py`.
2. Implement pure-Python evaluation of `vendor/balatro-rl/balatro_sim/shop_model.json` in `agent_v10.py` (caching weights upon module load, evaluating $V(s') = \sigma(\text{bias} + \sum w_i (f_i - \mu_i)/\sigma_i)$ in $<30\,\mu\text{s}$).
3. Upgrade `SearchShopV10._search_shop` to perform true L1 Counterfactual Shop Search:
   - For all available candidate shop actions $a \in \{\text{leave}, \text{buy}(i), \text{sell}(j), \text{swap}(j, i), \text{reroll}\}$:
     - Formulate the counterfactual post-action state $s'_a$ (e.g. deducting dollars, adding/removing joker, updating roles/features).
     - Compute predicted state value $V(s'_a)$.
     - Compute value gain $\Delta V(a) = V(s'_a) - V(s)$.
   - For items requiring room (jokers when slots are full), evaluate potential swaps: if selling redundant/economy joker $j$ to buy joker $i$ yields $\Delta V(\text{swap}(j, i)) > 0$, execute the sell and buy sequence.
   - Respect financial discipline ($25 interest target baseline when safe) and reroll budget.
   - Fall back safely if no positive $\Delta V$ action is found.
4. Verify that `SearchShopV10` produces differentiated, high-quality decisions compared to L0 (`HeuristicV9`/`HeuristicV10`) without peeking at draw order or future RNG.
5. Run unit tests, E2E requirement tests (`test_e2e_v10_requirements.py`), static audits, and CI seed exactness gate.
6. Write your handoff report to `D:/Optilatro/.agents/teamwork_preview_worker_m4_1/handoff.md` and send a completion message to parent.
