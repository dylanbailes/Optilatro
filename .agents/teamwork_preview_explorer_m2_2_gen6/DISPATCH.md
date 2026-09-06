## 2026-09-05T00:40:11Z
Task:
Investigate hand-type specialization traps with xMult jokers (j_family, j_order, j_duo, etc.) and portfolio_target_hand in tools/portfolio.py and agent_v10.py.
Problem Statement:
In the 300-seed benchmark, acquiring hand-specialized xMult jokers had a 0% win rate:
- j_family (Four of a Kind x4): 0 wins out of 14 runs (0.0%).
- j_order (Straight x3): 0 wins out of 8 runs (0.0%).
- j_duo (Pair x2): 0 wins out of 8 runs (0.0%).
Why? In tools/portfolio.py lines 612–678, portfolio_target_hand() unconditionally returns "Four of a Kind" if j_family is owned, or "Straight" if j_order is owned. But a standard 52-card deck has at most 4 of any rank and drawing Four of a Kind naturally is extremely rare without heavy deck-fixing (Strength/Death/Hanged Man). As a result, the agent stops leveling Flush / Two Pair / Pair and tries to fish for Four of a Kind, whiffing and dying in Antes 3–6.
1. Read D:/Optilatro/.agents/ORIGINAL_REQUEST.md and D:/Optilatro/PROJECT.md.
2. Read tools/portfolio.py lines 600–678 (portfolio_target_hand) and how it affects tarot/planet purchases and discards in agent_v10.py.
3. Investigate how portfolio_target_hand and card discarding can be made deck-aware:
   - If holding j_family, should it only target Four of a Kind if the deck actually has >= 5 or 6 cards of the same rank, or should it maintain a high-frequency base hand (e.g. Three of a Kind or Pair or Flush) as target hand until reshaped?
   - What about j_order (Straight) or j_duo (Pair)?
4. Formulate concrete recommendations for portfolio_target_hand() and joker valuation so hand-specialized jokers don't trap the agent into unmakeable hands.
5. Write your report to D:/Optilatro/.agents/teamwork_preview_explorer_m2_2_gen6/handoff.md.
