# Lottery AI V1.2.2 — Combination Coverage Optimizer

## Why V1.2.2 instead of reusing V1.2.0

The project library already contained an earlier V1.2.0 build and a V1.2.1 Model Quality Integrity build. This release therefore advances the internal application version to **V1.2.2** so one version number never refers to two different algorithms.

## Production changes

1. **New COV1.0 Coverage Engine**
   - Runs only after Main Combination Score is finalized.
   - Never edits/recalculates the Main score.
   - Official/default mode is `balanced`.

2. **Balanced portfolio objective**
   - 50% Main Combination quality
   - 20% marginal Pair coverage
   - 15% marginal Triple coverage
   - 10% marginal Number coverage
   - 5% coarse structural diversity
   - soft overlap penalty for near-duplicate selections

3. **Quality guardrails**
   - highest-score candidate is kept as the anchor;
   - optimizer works inside a high-quality shortlist;
   - candidates more than 12 score points below the best shortlisted Main score are excluded;
   - deterministic local-swap optimization improves the final set without repeated regeneration.

4. **Frozen provenance**
   - new frozen Production/Challenger records carry `coverage_engine=COV1.0`, `coverage_mode=balanced`, and `coverage_portfolio_frozen=true` inside the existing `factor_context_json`;
   - no database schema migration;
   - no historical freeze rewrite.

## UI changes

- Main screen labels new portfolios as **COVERAGE OPTIMIZED PICKS**.
- Each new pick can show both `Combination Score` and `Portfolio Value`.
- New **Analysis > Coverage** page shows:
  - unique-number coverage;
  - Pair/Triple unique slots and reuse;
  - Pair/Triple efficiency;
  - average/max inter-ticket overlap;
  - structural diversity;
  - Coverage Efficiency;
  - Portfolio Score;
  - first-12-pick overlap matrix.

## Research-only modes

- `score_only`: simple Main-score ranking baseline.
- `focused`: conditional core-pool compression (15 numbers for 6/49; 18 for Lotto Max).
- `pure_coverage`: coverage-heavy benchmark with only a small quality weight.
- same-budget shadow backtest compares `score_only`, `balanced`, `focused`, `pure_coverage`, and Random Control using the same historical pre-draw candidate pool.
- these research modes cannot auto-promote into Production.

## Game packaging metadata

- LOTTO MAX: 7/52, 4 lines per play metadata.
- LOTTO 6/49: 6/49, 1 Classic line per play metadata.
- packaging metadata does not affect Main score or official draw probability.

## Preserved from V1.2.1

- Monte Carlo diagnostic remains 0% Production/Challenger weight.
- Sharing Risk remains advisory-only at 0% prediction weight.
- per-Main Bonus binding remains isolated from Main ranking.
- current-draw panel, data-integrity quarantine, official-history precedence, Feature Ablation Shadow, and Rank Stability Shadow are retained.
- automatic D-drive/existing-data-folder discovery remains unchanged.

## Interpretation boundary

Coverage optimization improves how a fixed set of tickets spans Number/Pair/Triple structures. It does **not** make any individual legal lottery combination more likely to be drawn.
