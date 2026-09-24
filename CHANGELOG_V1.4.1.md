# Lottery AI V1.4.1 — Validation Hardening

## Scope

V1.4.1 is a hardening release on top of V1.4.0. It does **not** change Production Main scoring, Balanced Coverage weights, Bonus ranking, one-freeze-per-draw behavior, or Shadow-only promotion boundaries. The release tightens statistical implementation details, makes integrity claims more precise, and removes two review-confirmed dead-code remnants.

## 1. Statistical validation hardening

- Removed unused `pstdev` import.
- Removed unused `score` local in `strategy_validation_summary()`.
- Bootstrap mean CI remains a deterministic percentile bootstrap, but endpoints now use linear interpolation instead of integer index truncation.
- `paired_sign_flip_test()` now uses exact exhaustive sign enumeration when the number of non-zero paired differences is <= 16.
- Larger samples use deterministic Monte Carlo sign-flips with +1 continuity correction, so simulated p-values never become zero.
- Results expose the test method and number of permutations used.
- Added deterministic known-distribution simulation self-checks for bootstrap coverage and sign-flip Type-I error sanity.

## 2. Integrity semantics hardened

`INTEGRITY1.1` stores the minimum verification inputs required to independently reconstruct new V1.4.1 hashes:

- Prediction payload: re-hashed from frozen `predictions_json`.
- Feature snapshot: re-hashed from frozen predictions plus saved weights/game/target/cutoff verification inputs.
- Algorithm descriptor: re-hashed from saved app/model/coverage descriptor inputs.
- Candidate pool: digest retained for provenance, but explicitly labeled `NOT_VERIFIABLE` unless an independent source snapshot exists.

Overall states now avoid overclaiming:

- `MUTATION_DETECTED`
- `PASS_WITH_LIMITATIONS`
- `PASS`
- `PARTIAL_UNVERIFIED`
- `LEGACY_NO_HASH`

Legacy V1.4.0 freezes are never rewritten. If their feature/algorithm verification inputs were not stored, those layers report `NOT_VERIFIABLE` rather than pretending a re-check occurred.

## 3. UI clarity

- Champion Score Percentile now includes a direction note: **higher = stronger pre-draw Combination Score rank**.
- Research integrity display now shows separate Prediction / Features / Algorithm / Candidate Pool layer states.
- Candidate-pool digest is explicitly described as provenance-only unless a separate pool snapshot exists.

## 4. Validation

- `pytest -q`: **77 passed**
- `python -m compileall -q app.py lottery_ai tests`: **PASS**
- `import app`: **PASS**, `APP_VERSION == V1.4.1`
- Deterministic statistical self-check (60 simulations, n=20, 800 bootstrap reps): bootstrap observed coverage **0.95** vs nominal 0.95; sign-flip observed Type-I rate **0.0333** vs nominal 0.05.
- 12,000-candidate / 20-line same-pool strategy smoke test: four unique portfolios generated for both LOTTO 6/49 and LOTTO MAX.

## Interpretation boundary

These changes improve implementation quality and auditability. They do not establish that a fair lottery process has a reliable exploitable predictive pattern.
