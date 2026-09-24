# Lottery AI V1.6.5 — Statistical Correctness & Runtime Hardening

V1.6.5 is a correctness/performance update built directly on V1.6.4.

## Statistical correctness
- Corrects `pair_lift` for k-of-M sampling without replacement using the finite-population factor `(k-1)M / (k(M-1))` while preserving the existing empirical-marginal/shrinkage design.
- Replaces the df>120 hard switch to 1.96 with a smooth asymptotic Student-t approximation.
- Small candidate pools now use fresh seeded Monte Carlo reference samples instead of mechanically reusing the first block.

## Performance
- Adds `lottery_ai/fastmath.py` for float-oriented `mean` and population SD without `Fraction` coercion.
- Precomputes historical gap-variance mean/SD and joint-region modal count once per `FeatureEngine`.

## Reliability
- Candidate generation is capped by the legal combination universe and protected by attempt/stagnation limits.
- Manual CSV import tries UTF-8 BOM, GB18030, then CP1252 and reports skipped invalid rows.
- Signed model snapshots are written through temporary files with atomic replace and best-effort rollback.
- HTTP 408 and 429 are retryable; `Retry-After` is honored with a 30-second cap.
- Worker failures reset transient card states before showing the error; update failures mark the header `FAILED`.
- Draw-cutoff logic now fails explicitly if `America/Vancouver` timezone data is unavailable.
- Adds `requirements-dev.txt` for pytest instead of making pytest a runtime dependency.

## Compatibility
- No database migration is required.
- Existing frozen predictions are not rewritten.
- New predictions may rank differently because `pair_lift` is intentionally corrected.
- Monte Carlo remains diagnostic-only with zero ranking weight.
