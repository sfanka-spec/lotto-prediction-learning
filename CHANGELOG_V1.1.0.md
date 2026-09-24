# Lottery AI V1.1.0 — Research Engine

Built on the audited V1.0.8 data layer. No database reset is required.

## New research components

- **Random Control (`RND1.0`)**
  - no historical signal
  - deterministic pre-draw seed
  - diversity-matched portfolio construction
  - frozen and judged independently of Production
- **Regime Engine**
  - explicit MAX_49 / MAX_50 / MAX_52 eras
  - eligible-draw normalization for every number
  - 51/52 are evaluated only on draws in which they were legal
  - current-regime sample-strength / Neural gate display
- **Crowd Model**
  - numeric human-selection proxy
  - birthday/date concentration, consecutive patterns, repeated endings/gaps
  - payout-sharing proxy only; never treated as draw probability
- **Research Portfolio Optimizer (`RES1.0`)**
  - 70% Production model rank
  - 20% Crowd Avoidance
  - 10% regime-normalized research signal
  - explicit overlap penalty / diversity diagnostics
  - shadow-only; cannot alter or auto-promote into Production
- **Forward Research Scorecard**
  - Production vs Random Control paired results
  - Production vs Research Portfolio paired results
  - forward-only z-score gates
- **Historical research**
  - added paired Random-Control walk-forward test
  - retained walk-forward, shuffle placebo and synthetic-null tests

## Safety / integrity

- Existing V1.0.8 Production freezes are preserved.
- V1.1 shadow freezes use separate model versions (`RND1.0`, `RES1.0`).
- Fixed Production/Challenger performance pairing so RND/RES rows can never be misclassified as Challenger judgments.
- Research shadows share the same target draw and data cutoff as the official Production freeze.
- Existing V1.0.8 historical integrity quarantine and model-clean data rules are retained unchanged.
- Neural minimum gate increased to 100 current-regime draws; Neural remains 0% Production weight.

## Tests

- Existing V1.0.8 suite retained.
- Added regime-boundary / eligible-number normalization tests.
- Added Random Control determinism test.
- Added Crowd Proxy direction test.
- Added Research Portfolio output/diversity test.
- Added database test proving RND/RES freezes do not contaminate Production/Challenger pairing.
