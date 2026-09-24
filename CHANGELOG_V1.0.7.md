# Lottery AI V1.0.7

## 6/49 Official Calendar + Model-Clean Audit hardening

- Fixed an important assumption in the fallback calendar: **official LOTTO 6/49 special draws can occur outside the normal Wednesday/Saturday schedule**.
  - When the WCLC since-inception archive is unavailable, an already official-verified off-schedule draw is carried into the provisional expected calendar instead of being mislabeled as contamination.
  - Unverified off-schedule rows remain quarantined and cannot influence prediction, learning, research or judging.
- Strengthened WCLC since-inception ingestion.
  - Retries both official archive URL forms.
  - Uses PDF layout extraction when available.
  - Adds a line-first official parser before the block fallback, reducing interference from GPD/EXTRA/Gold Ball/Super Draw serial-number text.
  - Accepts PDF date text with or without a space after the comma.
- `Repair` no longer treats `Missing = 0` as sufficient when the app is still on `SCHEDULE FALLBACK`; it retries the official WCLC calendar.
- After an official calendar is accepted, history is re-audited before third-party recovery is used. Third-party sources are skipped when the official archive already covers the history and no gaps remain.
- Historical Integrity Audit now separates:
  - **Raw integrity** — quality of every physically stored row.
  - **Model integrity** — quality of the audited rows actually allowed into the model.
  - **Model data status** — `CLEAN` / `WARNING`.
- One-day duplicate-shift diagnostics now match identical six main numbers even if a third-party bonus field is missing/wrong; exact main+bonus matches are separately identified.
- Data UI now shows provisional official special dates, raw/model integrity, model data status, and official-calendar refresh details.
- Suspicious rows remain non-destructively quarantined; V1.0.7 still does not auto-delete history.

## Verification

- `compileall`: PASS
- `pytest`: 26 passed
