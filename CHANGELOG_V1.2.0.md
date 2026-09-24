# Lottery AI V1.2.0 — Current Draw + Prediction/Sharing-Risk Separation

## Main-screen Current Draw panel
- Uses the previously empty horizontal area inside each LOTTO MAX / LOTTO 6/49 card.
- On a draw day: shows WAITING FOR OFFICIAL RESULT until a result is stored.
- After the official result arrives: shows winning numbers, Bonus, verified/unverified state, Top-3 ticket hit counts, per-pick top-Bonus hit markers, best single-ticket hit, and Top-N winning-number coverage.
- On a non-draw day: shows the next scheduled draw and whether an official prediction is already frozen.
- The panel is read-only. It never regenerates or changes a frozen prediction.

## Freeze timestamps
- UTC database timestamps are displayed in America/Vancouver local lottery time (PST/PDT).
- Existing DB values remain unchanged.

## Sharing Risk is advisory only
- Main Production Combination Score already did not contain Crowd Risk; V1.2 makes this policy explicit in UI and tests.
- `Sharing Risk` has **0% prediction-ranking weight** and cannot promote, demote, remove, or replace a Main combination.
- The Research Portfolio also removes the former crowd-avoidance ranking contribution. Research weighting is now 90% model score + 10% regime descriptor; crowd/sharing risk is display-only.
- Research shadow version increments to `RES1.1`; existing frozen RES1.0 records remain immutable.

## Bonus integrity
- Per-Main Bonus binding remains the V1.1+ rule for newly frozen predictions.
- Legacy frozen predictions that only stored Pick #1 Bonus are **not** backfilled after the cutoff. This prevents future-data leakage.

## Production model continuity
- No Production factor weights, Main scoring equations, Monte Carlo logic, or portfolio-overlap rules were changed.
- Existing official freezes remain immutable and can continue as first forward-test samples.
