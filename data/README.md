# Data directory

This directory contains only small repository-safe seed/sample assets.

## Runtime database

Lottery AI creates and uses a local SQLite database named `lottery.db`.

The runtime database may contain:

- validated draw history;
- raw-ingest audit records;
- Production/Challenger weights;
- frozen predictions;
- post-draw judgments;
- learning logs;
- champion-learning records;
- portfolio decisions and learning records;
- application state.

Because those records are mutable local runtime/research state, the real database is intentionally **not committed to Git**.

The database schema is defined in `lottery_ai/db.py`, so a fresh installation can create the required tables automatically.

## Rebuilding data on a fresh install

1. Install the application dependencies.
2. Run `python app.py`.
3. Use the application's data update/repair workflow to retrieve and validate historical results.
4. If needed, use the CSV import function for an approved historical dataset.

## Public repository policy

Safe to commit:

- small seed/sample JSON or CSV files;
- schema and parsing code;
- tests and fixtures that contain no private information.

Do not commit:

- `lottery.db` or other SQLite databases;
- logs;
- model snapshot binaries;
- credentials or tokens;
- private user data;
- local caches.

See the root `.gitignore` and `PUBLIC_RELEASE_CHECKLIST.md`.
