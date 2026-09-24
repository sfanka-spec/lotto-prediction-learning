# V1.6.0 — Bayesian Sample-Efficient Strategy Lab

## Added

- Research-only hierarchical Bayesian strategy evaluator (`BAYES1.0`).
- Leakage-safe historical walk-forward evidence for five portfolio strategies:
  - Score-only
  - Balanced
  - Focused
  - Pure Coverage
  - Concentrated
- Parallel line-count evaluation at 3, 5, 8, 10, and 20 lines.
- Same-draw, same-line-count Random Control pairing.
- Null-anchored partial pooling so sparse variants shrink toward no edge.
- Historical evidence discount of 0.45; pre-draw frozen forward evidence uses weight 1.0.
- Posterior mean edge, 95% credible interval, probability of positive edge, source-consistency status, and evidence gate.
- Persistent historical observations so new forward results automatically update the Bayesian view.
- Rank-concentration monitoring now includes 8 lines in addition to 3, 5, 10, and 20.

## Safety boundaries

- Production impact is fixed at 0%.
- The evaluator cannot auto-promote a strategy.
- The evaluator cannot authorize automatic spending.
- Historical-only evidence can reach `HISTORICAL_CANDIDATE` but never forward screening or confirmation.
- Conflicting historical and forward directions block candidate/screening gates.
- One draw remains one effective sample; multiple strategies from the same draw do not inflate a strategy's draw count.
- No database schema migration is required.

## Unchanged

- Production remains Balanced.
- Main/Bonus separation and frozen-prediction integrity remain unchanged.
- Existing jackpot, data-source, coverage, budget, learning, and hidden-menu structure remain unchanged.
