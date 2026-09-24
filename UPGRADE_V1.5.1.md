# Upgrade to V1.5.1 — Concentration & ROI Hardening

1. Extract the V1.5.1 folder anywhere you prefer.
2. **Keep your existing persistent `data` folder / `lottery.db`.** Do not delete it.
3. Run `START_LOTTERY_AI.bat`.
4. Confirm the status bar points to the expected existing database.

No destructive database migration is required. Old frozen predictions and old BUD1.0/BUD1.1 decisions remain immutable. Statistical learning de-duplicates multiple portfolio-policy versions for the same draw rather than rewriting history.

## What changes immediately

- Champion/Learning adds Winner Concentration Efficiency (WCE).
- Research strategy suite adds `concentrated` beside Balanced / Score-only / Focused / Pure Coverage.
- Budget structural Auto no longer drifts toward many lines just because cumulative quality mass grows with line count.
- Auto action stays `NO BET` until the evidence gate is supported; a separate research candidate is still visible.
- Budget learning uses same-budget Best-Match/WCE/Coverage evidence when true package-level ROI is not available.
- Jackpot history and 6/49 crowd-proxy semantics are hardened.

## Important ROI interpretation

`roi_floor` / Main-line payout diagnostics are **model-attributable number-line metrics**, not necessarily the exact return of the physical retail purchase.

- LOTTO MAX: each $6 purchase contains one model-directed selection plus three terminal Quick Picks.
- LOTTO 6/49: each $3 Classic selection also receives a system-assigned Gold Ball selection.

V1.5.1 only reports exact investment/package ROI when a future terminal/receipt import supplies `package_payout_by_rank` for every selected purchase. Missing companion outcomes are never silently treated as zero.
