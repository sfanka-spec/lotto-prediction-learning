# V1.0.8 — Cross-game quarantine + LOTTO MAX integrity metric correction

- Fixed LOTTO MAX `Model integrity` incorrectly comparing the current MAX_52 era (44 draws) against the entire 2009-present expected calendar, which produced a misleading ~3.5% value.
- Model-ready archive integrity is now calculated from all historical rows after quarantine; current-era coverage is shown separately.
- Added `Model-ready archive draws`, `Current model-era usable / expected`, and `Era coverage` to the Data panel.
- Generalized provisional official special-date handling to both LOTTO 6/49 and LOTTO MAX when only the schedule fallback calendar is available.
- Generalized quarantine: every unverified unexpected/off-calendar row is excluded from model-ready history for both games while remaining in the raw archive for provenance.
- LOTTO MAX historical contamination can therefore remain visible as raw `Unexpected` rows without affecting features, prediction, learning, or judging.
