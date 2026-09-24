# Lottery AI V1.1.1 — Research Integrity + Frozen Bonus Provenance

Built on V1.1.0. No database reset or model-learning reset is required.

## Main / Bonus orchestration hardening

- Main result label remains **Combination Score**.
- Bonus result label remains **Bonus Conditional Score**.
- Bonus scores never participate in Main combination ranking.
- New official predictions freeze a separate Bonus Top 10 for **every** Main Pick.
- Main numbers are defensively excluded from each bound Bonus ranking before freeze.
- Bonus Production/Challenger model versions and score names are recorded in the existing `factor_context_json` metadata; SQLite schema is unchanged.

## Frozen prediction integrity

- Removed post-freeze Bonus display enrichment for legacy V1.0.x predictions.
- A legacy freeze that only contains Pick #1 Bonus data stays Pick-#1-only forever; Pick #2/#3/... show unavailable instead of being recalculated from later data.
- Frozen V1.1 per-main Bonus rankings are displayed exactly as stored.
- Corrupt frozen bindings are flagged instead of silently repaired after the data cutoff.

## Main-Bonus consistency audit

Audit now detects:

- Bonus number inside its bound Main combination
- duplicate Main binding rank
- stored Main numbers not matching the frozen Main Pick
- duplicate Bonus candidates within one ranking
- Bonus candidate outside the legal game number range
- missing per-Main bindings
- short Bonus rankings (warning)

Legacy partial freezes remain backward-compatible and are labelled `LEGACY PARTIAL`; non-legacy partial freezes are treated as an audit failure.

## Research Engine statistical wording

- `n>=100`, positive edge and `z>=1.96` => **SCREENING SIGNAL**
- `n>=200`, positive edge and `z>=2.58` => **CONFIRMATION SIGNAL**
- Research UI explicitly states that repeated monitoring/backtests do not prove predictive edge.

## Bilingual UI

- Added localized Main/Bonus binding wording for English, Chinese and bilingual modes.
- Bonus page explains that frozen rankings are immutable and legacy missing bindings are intentionally not backfilled.

## Verification

- `pytest`: 42 passed
- `python -m compileall`: PASS
