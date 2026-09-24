# Lottery AI V1.4.0 — Model Validation Lab

## Scope

V1.4.0 is a validation/diagnostics release. It preserves the conservative Production policy: official Main ranking still uses the existing six predictive/descriptive factors, Monte Carlo remains diagnostic-only at 0% ranking weight, Bonus remains isolated, and Production still uses the Balanced Coverage policy. The release adds stronger post-draw decomposition, same-candidate strategy shadows, statistical validation, and anti-leakage provenance.

## 1. Ranking Calibration

Champion diagnostics now retain and evaluate the original frozen pre-draw ordering:

- Champion original rank;
- Champion frozen Score percentile;
- Score-vs-Hit Spearman rank correlation;
- Top-5, Top-10 and bottom-10 mean hit counts;
- ranking diagnosis: `WELL_RANKED`, `MID_RANKED`, `UNDER_RANKED`;
- staged diagnosis: Number Selection, Combination Concentration, Ranking.

Existing Champion rows are backfillable from the original frozen predictions without rewriting the freeze.

## 2. Same-candidate strategy suite

A new `PredictionEngine.generate_strategy_suite()` scores the candidate pool once and derives four fixed-budget portfolios from that exact same pre-draw pool:

- Balanced;
- Score-only;
- Focused;
- Pure Coverage.

Version prefixes:

- `S14BAL1.0`
- `S14SCORE1.0`
- `S14FOCUS1.0`
- `S14PURE1.0`

These freezes are Shadow-only, never auto-promote directly, and never alter the official Production freeze.

For future V1.4 official predictions, the candidate-pool hash is shared across all four strategy freezes. For an older still-pre-draw official freeze, the upgrade bridge can create V1.4 strategy shadows but explicitly records that they did not share the original Production candidate pool.

## 3. Coverage vs concentration monitor

New paired metrics:

- `Balanced Coverage Gain vs Score-only = Balanced Top-N Coverage - Score-only Top-N Coverage`
- `Concentration Cost = Score-only Best Match - Balanced Best Match`

The monitor starts only when both strategies were actually frozen pre-draw. It never generates a strategy after a result and counts it as pre-draw evidence.

## 4. Statistical validation

New `lottery_ai.evaluation` research layer:

- deterministic bootstrap 95% confidence intervals;
- paired sign-flip permutation tests;
- paired standardized effect size;
- Benjamini-Hochberg False Discovery Rate correction;
- rolling 30/50/100-draw strategy deltas;
- research gates: `WAITING`, `OBSERVE`, `SCREENING_SIGNAL`, `CONFIRMATION_SIGNAL`.

These are model-quality safeguards, not claims that lottery outcomes are predictably non-random.

## 5. Freeze integrity / anti-leakage provenance

New `lottery_ai.integrity` layer stores SHA-256 provenance for new V1.4 freezes:

- frozen prediction payload;
- feature snapshot;
- algorithm/version identity;
- data cutoff;
- candidate pool when applicable.

The Research page reports `PASS`, `LEGACY_NO_HASH`, or `MUTATION_DETECTED` for the current Production freeze.

## 6. UI

Learning page now shows:

- Champion original rank and Score percentile;
- Score-vs-Hit Spearman;
- staged Selection / Concentration / Ranking diagnosis;
- average Champion rank and under-ranked count;
- V1.4 Coverage-vs-Concentration monitor.

Research page now shows:

- strategy freeze status;
- Production freeze integrity;
- Coverage Gain and Concentration Cost;
- paired strategy deltas;
- bootstrap interval, FDR-adjusted q-value, gate;
- rolling 30/50/100-draw deltas.

## 7. 2026-09-12 safety rule

The existing 2026-09-12 Production Top-20 can be re-read to add Ranking Calibration because it was frozen before the result. V1.4 deliberately does **not** manufacture post-draw Score-only/Focused/Pure-Coverage portfolios for that draw and call them out-of-sample evidence.

## Validation

- `pytest -q`: **72 passed**
- `python -m compileall -q app.py lottery_ai tests`: **PASS**
- `import app`: **PASS**, `APP_VERSION == V1.4.0`
- 12,000-candidate same-pool strategy smoke test:
  - LOTTO 6/49: four 20-line portfolios generated, ~4.08 s in validation container
  - LOTTO MAX: four 20-line portfolios generated, ~3.00 s in validation container

Runtime values are environment-specific and are not guarantees for another PC.
