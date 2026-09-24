# Lottery AI V1.0.4

## Historical-data repair upgrade

- Expanded GitHub history recovery from one repository to multiple public CSV repositories for both LOTTO 6/49 and LOTTO MAX.
- Added flexible GitHub CSV parsing for `PlayDate/No1...`, `Date/Num1...`, official-style `DRAW DATE/NUMBER DRAWN ...`, and packed `Numbers` list formats.
- GitHub mirrors are intentionally treated as one logical recovery source. Conflicting GitHub rows for the same date are held out rather than counted as independent consensus.
- Added per-repository GitHub diagnostics under **Analysis > Data**.
- Moved GitHub recovery to the first history-repair pass; official current-result priority remains WCLC -> OLG -> Loto-Quebec.

## Validation fixes

- Added date-aware LOTTO MAX history validation:
  - before 2019-05-14: 1-49
  - 2019-05-14 through 2026-04-13: 1-50
  - from 2026-04-14: 1-52
- Corrected the LOTTO 6/49 twice-weekly calendar transition: the first Wednesday draw is 1985-09-11, not 1985-09-04.
- Historical merge/import now uses date-aware validation, preventing impossible old-era LOTTO MAX values from entering the database.

## Compatibility

- Existing `lottery.db` discovery/reuse behavior is unchanged.
- No database reset is required.
- The existing **Repair Historical Database** button now performs the expanded GitHub recovery automatically.
