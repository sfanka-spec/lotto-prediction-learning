# Lottery AI V1.0.6

## 6/49 Historical Data Identity & Integrity hardening

- Added a **dataset identity gate** for GitHub historical 6/49 sources.
  - Calendar compatibility is measured before a repository can contribute rows.
  - Off-schedule third-party rows are held out instead of entering Canadian LOTTO 6/49 history.
  - The Data panel shows identity status, calendar-match percentage, filtered row count and samples.
- Added direct **WCLC since-inception HTML-table parsing**.
  - Parses date, six winning numbers and bonus from the official row cells.
  - Avoids accidental capture of EXTRA values/page text.
  - Makes the WCLC archive a much more reliable canonical draw calendar when reachable.
- Strengthened **Historical Integrity Audit**.
  - Unverified off-calendar 6/49 rows are quarantined even when the official archive is temporarily unavailable.
  - Unexpected-row provenance is displayed.
  - Exact-number one-day date-shift duplicates are detected and reported separately.
- No suspicious row is deleted automatically. Quarantine prevents it from affecting prediction, learning, research or judging while preserving it for inspection.
- Production/Challenger/Neural algorithms and menu structure otherwise remain unchanged.

## Verification

- `py_compile`: PASS
- `pytest`: 23 passed
