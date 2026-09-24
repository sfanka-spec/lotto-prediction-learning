# Lottery AI V1.5.0 — Adaptive Budget, Portfolio & Jackpot Learning

## Scope

V1.5.0 adds a decision/economics layer **after** the existing immutable Top-20 prediction. It does not change the official number-draw probability and does not claim that historical lottery data makes a fair draw predictable.

## 1. Adaptive Budget & Portfolio AI

- New exact subset optimizer over the frozen Top-20.
- Searches all `2^20 - 1 = 1,048,575` non-empty subsets when 20 lines are present.
- Never regenerates or recombines numbers; it can only select from the already-frozen Production lines.
- Freezes the best portfolio for every line count 1..20 before the draw.
- Supports `Auto`, `$10`, `$20`, `$30`, `$50`, and custom dollar ceilings.
- A fixed budget is a hard maximum. The optimizer may leave money unspent.
- Structural policy uses pre-draw Combination quality, Number coverage, Diversity, controlled Concentration, and Rank retention.
- Complete frontier is frozen pre-draw so a later custom budget maps to a pre-existing portfolio rather than being recomputed with post-draw information.

## 2. Budget learning / decision memory

- New `portfolio_decisions` table stores the pre-draw Top-20, Production frontier, Shadow frontier, budget-learning state, jackpot context, and hard safety rules.
- New `portfolio_learning` table stores one post-draw judgment per decision/draw.
- Same-budget Random control is evaluated after the draw.
- A same-size post-draw oracle is stored only as a regret label and never counted as forward performance.
- Shadow Portfolio policy learns from one regret signal per draw, not from the millions of correlated subsets.
- Complete 1..20 line-count outcomes are accumulated so the software can learn which spend levels historically had the strongest cost/return efficiency.
- Selection Evidence Grades: `D`, `C`, `B`, `A`.
- Evidence Grade measures subset-selection support versus same-budget Random; it is not a claim of positive expected profit.

## 3. Conservative investment/output accounting

- New `play_cost` metadata: LOTTO 6/49 `$3`, LOTTO MAX `$6`.
- `ROI floor` uses only prize amounts that can be determined without guessing.
- Pari-mutuel and jackpot tiers are marked unresolved instead of assigning fictional payouts.
- LOTTO 6/49 Gold Ball value is kept separate from the Classic-number model.
- LOTTO MAX accounting recognizes that each `$6` purchase provides one user-directed selection plus three terminal Quick Picks. Random companion lines are not falsely attributed to the model.
- No Martingale, no loss chasing, and no budget increase caused by prior losses.

## 4. Latest Official Jackpot layer

- New WCLC jackpot provider, independent of winning-number ingestion.
- LOTTO MAX snapshot fields: jackpot amount, `$90M` cap, MAXPLUS `$100K` draw count, and MAXMILLIONS count when exposed by the official page.
- LOTTO 6/49 snapshot fields: Classic `$5M`, Gold Ball jackpot, Gold Balls remaining.
- New `jackpot_snapshots` table stores observed official state over time.
- Refresh failures do not block winning-number/history updates.
- Cached data is explicitly marked `STALE` after a failed refresh instead of being presented as current.

## 5. Jackpot economics / crowd context

- Jackpot context is frozen with each Portfolio decision for future regime/economics research.
- `crowd_pressure_proxy` is explicitly a jackpot-state proxy, not measured sales volume.
- Gold Ball conditional probability is computed only from verified balls remaining; per-play Gold Ball odds are not invented without verified issued-selection counts.
- Existing combination Sharing Risk remains advisory-only and has 0% Production prediction weight.

## 6. Coverage/concentration integration

- V1.5 Portfolio AI is deliberately allowed to preserve useful overlap; it does not mechanically maximize dispersion.
- This adds an economic/selection layer above the V1.4 `Coverage Gain` vs `Concentration Cost` monitor.
- Existing `balanced`, `score_only`, `focused`, and `pure_coverage` same-candidate Shadow strategies remain unchanged.

## 7. Validation and engineering hardening

- Fixed a stale-jackpot state issue: a failed official refresh now remains visibly `STALE` in the UI while preserving the last verified snapshot and timestamp.
- Corrected conservative LOTTO MAX payout handling for `4/7 + Bonus`: it is treated as an unresolved pari-mutuel tier, not mislabeled as the fixed `$20` `4/7` tier.
- Added draw-level budget frontier statistics, bootstrap confidence intervals, same-budget sign-flip tests, and Evidence Grade gating.
- Added regression coverage for budget learning, evidence gating, stale-jackpot behavior, and the `4/7 + Bonus` payout distinction.

## Compatibility

- Additive SQLite schema only; existing draw/freeze data is not rewritten.
- Existing V1.4.1 Production weights and prediction semantics are preserved.
- An older still-future frozen Top-20 may receive the V1.5 Budget frontier only while it remains safely pre-draw; post-draw retro-generation is not counted as forward evidence.

## Validation result

- `pytest -q`: **87 passed**
- `python -m compileall -q app.py lottery_ai tests`: **PASS**
- application import: **PASS**
- APP_VERSION: **V1.5.0**
- 12,000-candidate / four-strategy smoke test: **PASS** for both games
- exact 20-line frontier: **1,048,575 subsets** searched for each game
- observed validation-container timings:
  - LOTTO 6/49 strategy suite ~3.42 s; exact frontier ~2.45 s
  - LOTTO MAX strategy suite ~3.80 s; exact frontier ~2.57 s

Performance is machine-dependent and is not a runtime guarantee.
