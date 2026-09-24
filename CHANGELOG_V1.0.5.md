# Lottery AI V1.0.5 — 6/49 Historical Integrity Audit

This release is intentionally focused on the Lotto 6/49 data problem before adding new prediction models.

## What changed

- Added **WCLC LOTTO 6/49 Since Inception** as the canonical historical source.
- Added a date-aware parser for the WCLC archive and uses the official draw dates as the historical calendar when the archive passes completeness checks.
- Fixed archive acceptance so the WCLC PDF is evaluated only through **its own latest date**. A lagging official archive is no longer rejected merely because newer live draws exist.
- Added **Historical Integrity Audit** with separate metrics for:
  - Coverage
  - Missing scheduled draws
  - Unexpected/off-calendar rows
  - Invalid number/bonus rows
  - Unresolved source conflicts
  - Model quarantine/exclusions
- Added **Repair + Audit Historical Database** and **Run Integrity Audit** buttons in the Data panel.
- Official WCLC historical rows can resolve third-party disagreements and safely overwrite an unverified row for the same date.
- Existing verified current/official results remain protected from unverified recovery sources.
- Invalid, unresolved-conflict, and (when the official calendar is available) unverified off-calendar rows are quarantined from model training rather than silently used.
- Prediction, research, judging, and adaptive learning now use only **model-ready** historical rows.
- Manual CSV imports use date-aware validation.

## Why this matters

V1.0.4 could report a high history percentage while simultaneously showing missing dates and more database rows than expected. V1.0.5 separates **coverage** from **integrity** and uses WCLC's official historical calendar to distinguish real draws from bad/imported rows.

No Random Control, Crowd Model, Regime Engine expansion, or new neural model was added in this release. Those remain later-stage work after the 6/49 database is clean.
