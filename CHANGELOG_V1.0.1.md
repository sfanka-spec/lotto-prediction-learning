# Lottery AI V1.0.1

## Main changes

- Automatic reuse of an existing Lottery AI `data` folder/database after extracting a new version.
- Windows preference for shared long-term data at `D:\Lottery_AI\data` when no prior database exists.
- BC-first multi-source latest-result chain: WCLC official -> Loto-Québec official -> Atlantic Lottery official cross-check -> archive fallback.
- Right-top update status now shows UPDATING / SUCCESS / PARTIAL / FAILED and completion time.
- Data tab shows the active data-folder path and source-by-source update results.
- Lotto 6/49 Region Engine now has exact-math fallback and no longer depends on loaded historical draws to display theoretical ranges.
- Top portfolio selections remain diversity-optimized but are displayed in descending Model Score order.
- Replaced the circular single-run Monte Carlo percentile with repeated-reference Monte Carlo Stability.
- Historical backfill hardened: structured archive first; 6/49 full archive fallback; WCLC official past-results fallback for Lotto Max current era.
- Source conflicts fail closed: conflicting official results are not written into the clean model database.
