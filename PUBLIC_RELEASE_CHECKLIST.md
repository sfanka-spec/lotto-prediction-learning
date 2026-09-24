# Public Release Checklist

Use this checklist before changing the repository from Private to Public or publishing a new public release.

## Code and tests

- [ ] Application version is correct.
- [ ] `pytest` passes.
- [ ] Source compiles/imports successfully.
- [ ] No local absolute paths are required for normal use.
- [ ] Fresh install can create its own runtime database.

## Secrets and privacy

- [ ] No API keys, passwords, tokens, cookies, or credentials are committed.
- [ ] No `.env` file is committed.
- [ ] No private keys/certificates are committed.
- [ ] No personal runtime database is committed.
- [ ] No logs containing personal paths or tokens are committed.
- [ ] Git history has been reviewed for previously committed secrets.

## Data

- [ ] Only repository-safe seed/sample data is committed.
- [ ] Data sources and limitations are documented.
- [ ] Third-party dataset redistribution rights have been checked before bundling data.
- [ ] Runtime SQLite databases remain excluded by `.gitignore`.

## Documentation

- [ ] README installation steps match the current release.
- [ ] README_CN installation steps match the current release.
- [ ] CHANGELOG and UPGRADE notes are present.
- [ ] Educational/research disclaimer is visible.
- [ ] Model scores are not described as guaranteed win probabilities.

## Repository settings

- [ ] Repository description is current.
- [ ] Issues are enabled if public feedback is desired.
- [ ] Discussions/Sponsorships are enabled only if intentionally needed.
- [ ] Branch protection is considered for `main`.
- [ ] GitHub Actions CI is green.

## Licensing

- [ ] Repository owner has explicitly chosen a license, or intentionally leaves the project with no public license.
- [ ] If a license is added, README and release notes match that choice.

## Release

- [ ] Tag follows the version, e.g. `v1.6.6`.
- [ ] Release title and notes are accurate.
- [ ] Release is not marked pre-release unless intended.
- [ ] Optional binary/data attachments contain no private runtime state.
