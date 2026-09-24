# Lottery AI V1.1.2 — Stability & Data Integrity

Built on V1.1.1. No database reset, prediction reset, or model-learning reset is required.

## Runtime reliability
- Fixed `_safe_worker` asynchronous exception handling by capturing the message before the deferred Tk callback.
- Added a regression test for the worker exception path.
- Added best-effort rotating diagnostics at `data/logs/lottery_ai.log` (1 MB × 3 backups). Logging failure never blocks startup.

## Statistical consistency
- Added one shared `paired_z_score()` helper used by Promotion Gate, Performance UI and walk-forward reporting.
- Zero variance remains deliberately conservative: `z = 0`, not infinite evidence.
- Production scoring weights, candidate ranking, Monte Carlo scoring and Bonus ranking are unchanged.

## Provider / database integrity
- Added final date-aware validation immediately before clean history/latest database writes.
- Invalid provider data is fail-closed and preserved as rejected raw-ingest diagnostics rather than entering `draws`.
- Added warning/debug logging for network retries and important provider fallback failures.
- Removed misleading or unused imports/variables left by earlier refactors.

## Compatibility
- Existing `lottery.db`, frozen predictions and learning snapshots remain compatible.
- V1.1.1 frozen Main/Bonus bindings are not recalculated.
- Data-directory auto-discovery is unchanged.

## Verification
- Full pytest suite: `45 passed`
- `python -m compileall`: PASS
