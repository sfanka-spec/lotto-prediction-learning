# Lottery AI V1.0.2

- Replaced **Regenerate** with **Generate Official Prediction**.
- One Production prediction per target draw; lock persists in SQLite across restarts.
- New draw ingestion/judgment automatically unlocks the next scheduled draw.
- No automatic prediction generation during ordinary data updates.
- Deterministic official prediction seed for reproducible results.
- Compact update status now shows success/partial/failure, completion time, added-draw count and source success counts.
- Added bounded HTTP retry/backoff for transient reset/timeout/5xx failures before source failover.
- Existing D-drive/shared `data` discovery remains unchanged.
- Auto Promotion remains OFF by default and still uses the strict gate.
