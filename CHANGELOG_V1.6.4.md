# Lottery AI V1.6.4 — Learning Center Semantic Hardening

V1.6.4 is a diagnostic-clarity and error-hardening update on top of V1.6.3. Production ranking, candidate generation, model weights, frozen predictions, promotion rules, research weights, and spending behavior are unchanged.

## Learning Center clarity
- Renames `Paired evaluated draws` to `Production-Challenger paired draws` so it cannot be confused with Champion/Portfolio forward sample counts.
- Splits ranking diagnostics into two independent concepts:
  - **Best-hit placement**: where the best-hit ticket originally ranked before the draw.
  - **Global rank association**: the within-draw Score-vs-Hit Spearman descriptor.
- A well-placed champion no longer makes the combined stage say `GOOD` when the overall Spearman association is neutral.
- Adds `FULL-POOL COVERAGE — NOT NUMBER-SELECTION EVIDENCE` when the displayed portfolio spans the entire number pool.
- Adds an explicit `full_pool_coverage` diagnostic field for auditing.

## Consistency hardening
- Current Draw and Learning Center now share one Spearman descriptor function and the same thresholds, preventing label drift between pages.
- Champion diagnostic schema advanced to `CHAMP1.7`; existing freezes remain immutable and old Champion rows can be safely refreshed from frozen predictions.
- Backward-compatible `stage_diagnosis["ranking"]` remains available, but it is now conservative: it only reports GOOD/WEAK when best-hit placement and global association agree directionally.

## Integrity
- No database migration required.
- No Production or Challenger predictive weights changed.
- No historical freeze is rewritten.
