# CHANGELOG V1.6.6 — Public Release Hardening

V1.6.6 prepares Lottery AI for safer public sharing without changing the core prediction model or historical frozen predictions.

## Changes

- Application version advanced to V1.6.6.
- Added public-release documentation and a dedicated data-handling guide.
- Clarified that runtime SQLite databases, model snapshots, logs, credentials, and local state are not part of the source repository.
- Added GitHub Actions CI to install dependencies and run the automated test suite on pushes and pull requests.
- Updated English and Chinese README files with public-installation, first-run, data, privacy, and reproducibility guidance.
- Added a public-release checklist for repository visibility, secrets review, licensing, release notes, and reproducibility.
- Preserved existing V1.6.5 statistical/runtime hardening; no historical freeze or judgment is rewritten.

## Compatibility

Existing local `lottery.db` files remain local and are not migrated into Git.

Users upgrading from V1.6.5 can continue using their existing data directory. A fresh installation creates the database schema automatically and can rebuild history through the application's data update/repair workflow.

## Public-release boundary

The repository is intended to contain source code, tests, documentation, configuration, and small non-sensitive seed/sample files.

It intentionally excludes:

- runtime SQLite databases;
- logs and caches;
- model snapshot binaries;
- API keys, tokens, credentials, and `.env` files;
- virtual environments and build artifacts.

## License

No public software license is added by this hardening release unless the repository owner explicitly chooses one.
