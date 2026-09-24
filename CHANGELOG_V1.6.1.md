# Lottery AI V1.6.1 — Evaluation Integrity Hardening

V1.6.1 is based directly on V1.6.0 and focuses on evidence quality, reproducibility, database integrity, and deterministic performance. It does not claim that any strategy can increase the probability of a fair lottery draw.

## Statistical integrity

- Replaced V1.6.0 small-sample `pstdev + 1.96` inference with sample SD (`ddof=1`) and sample-size-aware Student-t critical values.
- Rebuilt the timeline shuffle diagnostic around target-date paired differences, percentile bootstrap confidence intervals, and paired sign-flip p-values; the old fixed `real - placebo > 0.03` rule is removed.
- Added fair-lottery **self-null** benchmarking. Each frozen portfolio is compared with the null expectation of its own structure rather than a deliberately diversified Random Control portfolio.
- Random Control remains available as a descriptive structure-control diagnostic but is not promotion evidence.
- Historical and forward Bayesian samples are deduplicated by `(game, draw_date, variant)`; a genuine forward freeze replaces the same replayed historical sample.
- Forward variant gates include BH-FDR adjustment and an always-valid sequential sign e-process diagnostic to reduce repeated-look false evidence.
- Historical Bayesian replay uses fixed default weights rather than weights learned from later draws.
- Near-zero source-direction tolerance was widened to avoid treating immaterial floating-point noise as a conflict.

## Production / Challenger fairness

- Production and Challenger now use the same candidate budget, same RNG seed, and a verified identical candidate-universe hash.
- Old unequal-budget P/C judgments remain in the audit history but are excluded from V1.6.1 promotion evidence.
- A deterministic `prediction_run_id` links the official P/C freeze, same-pool strategy shadows, and the budget snapshot generated in the same prediction run.

## Freeze and database integrity

- Production + Challenger freeze writes use one immediate transaction and roll back together on failure.
- Judgment rows are deduplicated and protected by a unique `freeze_id` constraint/upsert path.
- Frozen prediction payload/model/context fields are protected from later updates by a database trigger.
- A local append-only SHA-256 freeze ledger detects accidental or local post-freeze mutation. This is tamper-evident, not a substitute for an external trusted anchor.
- Missing legacy strategy shadows are no longer regenerated later from a different candidate universe; the backfill is recorded as skipped instead.

## Runtime / architecture hardening

- Update-pipeline re-entry is blocked so startup/manual/timer refreshes cannot overlap the same pipeline.
- Worker-to-Tk UI updates are routed through a queue drained by the main Tk thread.
- Lotto Max regime boundaries and draw schedules are centralized in configuration and reused by database, updater, provider validation, and regime logic.
- Data-path resolution is deterministic: explicit `LOTTERY_AI_DATA` -> existing local database -> stable Windows database -> legacy discovery.
- Automatic `.pkl` model loading requires a matching SHA-256 sidecar; unsigned legacy pickles are not deserialized automatically.
- Crowd-risk classification uses one shared implementation.

## Performance

- Top-20 exact subset-frontier search is NumPy-vectorized while retaining the original Python exact algorithm as a fallback/reference oracle.
- Coverage optimization caches row number/pair/triple/signature features instead of recomputing them inside every greedy scan.
- Exact distribution normalization used by region scoring is precomputed.

## Diagnostics

- `number_selection = GOOD` was removed as a near-trivial diagnostic; the stage is marked non-diagnostic and portfolio coverage is reported separately.
- All current product branding, launcher references, log names, and environment-variable guidance use **Lottery AI**; the previous personal-name branding has been removed.
