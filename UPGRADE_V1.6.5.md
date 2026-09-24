# Upgrade to V1.6.5

V1.6.5 is a drop-in upgrade from V1.6.4. Reuse the same data directory and SQLite database; no schema migration is required.

Because `pair_lift` changes from a with-replacement expectation to a without-replacement expectation, newly generated Production/Challenger rankings can differ from V1.6.4. This is expected and should not be treated as a regression. Existing freezes remain immutable and continue to be evaluated against the predictions that were actually frozen before their draw.

Runtime dependencies remain in `requirements.txt`. For local validation, install `requirements-dev.txt` and run:

```text
python -m pytest -q
```

If Pacific timezone data cannot be loaded, V1.6.5 raises a clear configuration error instead of silently using the machine's local timezone. `tzdata` remains included in the runtime requirements for Windows installations.
