# GitHub Upload Checklist

Before each push:

- Run `python -m pytest -q` and confirm the test suite passes.
- Confirm `.env`, API keys, passwords, tokens, private keys, and credentials are not tracked.
- Do not commit `data/lottery.db*`, runtime logs, or local model snapshots unless intentionally publishing them.
- Review `git status` before committing.
- Keep the repository private until you are comfortable with the source and data being shared.

Suggested first commit message:

`Initial private release: Lottery AI V1.6.5`
