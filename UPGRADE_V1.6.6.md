# UPGRADE V1.6.6 — Public Release Hardening

## From V1.6.5

1. Pull or download V1.6.6.
2. Keep your existing runtime data directory and `lottery.db` local.
3. Reinstall/update dependencies if needed:
   ```powershell
   pip install -r requirements.txt
   ```
4. Run tests:
   ```powershell
   pip install -r requirements-dev.txt
   pytest
   ```
5. Start the application:
   ```powershell
   python app.py
   ```

## Fresh public installation

A fresh user does not need the developer's personal database.

The application creates the SQLite schema automatically. Historical data can then be populated using the built-in update, repair, and import workflows.

## What not to copy into Git

Do not commit your local:

- `lottery.db`
- `*.db`, `*.sqlite`, `*.sqlite3`
- `data/logs/`
- `data/models/*.pkl`
- `.env`
- API tokens or passwords
- `.venv/`

These remain local runtime state.
