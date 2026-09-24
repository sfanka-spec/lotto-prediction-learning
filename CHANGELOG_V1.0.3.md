# Lottery AI V1.0.3 — Historical Data Recovery

## Main changes

- Added OLG as a second official current-result source behind BC-primary WCLC.
- Added LottoDatabase and Lotto.net yearly history providers for both games.
- Added public GitHub CSV history recovery layer.
- Kept WCLC recent history and National-Lottery 6/49 as additional fallbacks.
- Added estimated historical draw-calendar integrity checking and completeness percentage.
- Added `Repair Historical Database` and `Import History CSV` buttons in each Data tab.
- History repair targets missing years rather than repeatedly downloading everything after the initial repair.
- Official verified database rows can no longer be overwritten by an unverified historical source.
- Historical source conflicts are held out unless a source consensus exists.
- Update banner now separates latest-result success from history completeness and source redundancy.
- Corrected Lotto Max era labels: MAX_49, MAX_50, MAX_52. Current Production remains MAX_52 only.
- Preserves the shared long-term data directory, normally `D:\Lottery_AI\data`.

## Validation

- Python compile check passed.
- 11 core tests passed, including WCLC/OLG parser tests, two history parser tests, draw-calendar tests, exact-combination tests, official-freeze uniqueness, and verified-row overwrite protection.
