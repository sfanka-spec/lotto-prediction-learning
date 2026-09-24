# Lottery AI V1.2.3 — Coverage Performance & Diagnostics

## Scope

Review-driven maintenance release. Prediction semantics remain unchanged: Main Combination Score and Bonus Conditional Score are preserved, Balanced Coverage weights remain 50/20/15/10/5, Sharing Risk remains advisory-only, and official predictions remain one frozen portfolio per draw.

## Changes

1. **COV1.1 incremental local-swap evaluator**
   - Candidate swap trials update Number/Pair/Triple/signature counts and pairwise-overlap deltas instead of rebuilding the entire portfolio.
   - The global objective and rounding behavior are intentionally identical to V1.2.2.
   - Added regression test comparing incremental and full-rebuild objectives at every swap position.

2. **Greedy readability cleanup**
   - `best_key` is cached directly instead of being reconstructed from `remaining[best_index]` each iteration.
   - Deterministic tie-breaking is unchanged.

3. **Promotion provenance**
   - Auto Promotion now records old Production weights, promoted Challenger weights, paired z-score, mean edge, Challenger mean, random-baseline mean, and old/new version IDs in `learning_log`.
   - This makes the previously unused normalized `pw` value meaningful and auditable.

4. **Provider diagnostics**
   - Added targeted diagnostics to the Atlantic Lottery verifier, National-Lottery archive fallback, and Lotto.net yearly fallback.
   - Expected row-level parse rejects remain quiet to avoid flooding the rotating log.

5. **Dead-code cleanup**
   - Removed unused `COVERAGE_ENGINE_VERSION` import from `app.py`.

## Validation

- `pytest -q`: **64 passed**
- Full Python compilation: passed
- Incremental swap objective vs full rebuild: exact match test passed
- Deterministic benchmark portfolio hash: identical between V1.2.2 and V1.2.3
- 2,500-candidate / Top-20 Balanced median benchmark: ~1.77 s -> ~0.78 s (~2.27x faster) in the validation container

## Static-analysis note

The build container did not have `pyflakes` installed and outbound package installation was unavailable, so this package does not claim a fresh full pyflakes run. The two exact findings from the review were independently verified and fixed, and syntax/tests were rerun.
