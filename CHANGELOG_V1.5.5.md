# Lottery AI V1.5.5 — Rank Concentration & UI Hardening

## Why this release exists

A Top-20 portfolio can cover many winning numbers simply because it covers a very large fraction of the legal number pool. That is different from ranking useful numbers early or concentrating them into a strong legal ticket. V1.5.5 makes those layers explicit.

## Changes

1. **Portfolio breadth is explicit**
   - Adds `ticket_slots`, `portfolio_unique_numbers`, `number_pool_size`, and `portfolio_number_pool_pct`.
   - Keeps `top_n_coverage` for compatibility but also names it `portfolio_winner_coverage`.
   - `selection_miss` remains for old readers; new UI labels it **Portfolio miss** so it is not confused with independent number-selection skill.

2. **Rank-concentration diagnostics**
   - Adds CWC@3/@5/@10/@20.
   - Adds BestHit@3/@5/@10/@20.
   - Adds WCE by rank window, unique-number breadth by rank window, and a theoretical-random CWC reference.
   - Adds a front-load edge diagnostic for rolling analysis.

3. **Independent pre-draw candidate-number support rank**
   - New freezes retain a deterministic ranking of numbers derived from the scored candidate pool before portfolio selection.
   - Post-draw diagnostics evaluate winner coverage at Candidate @10/@15/@20.
   - The rank is diagnostic only; it does not change Combination Score or official Production weighting.

4. **Rolling 20/50 evaluation**
   - Champion summaries now include rolling WCE, combination gap, Champion rank, Spearman, CWC@K, BestHit@K, and candidate-number coverage.
   - This is designed to prevent one unusually good or bad draw from driving model changes.

5. **Concentrated shadow wiring completed**
   - Production generation now freezes the existing `concentrated` research strategy from the same scored candidate pool as Balanced/Score-only/Focused/Pure-Coverage.
   - It remains shadow-only and cannot auto-promote into Production.

6. **CURRENT DRAW UI hardening**
   - Panel height increased and text wrap changed from `none` to `word` so long diagnostics are not horizontally clipped.
   - The compact summary now shows portfolio breadth, CWC@K, BestHit@K, candidate-number rank, WCE, Champion rank, Score percentile and Spearman.
   - A freeze/champion consistency guard flags a mismatched saved Champion record instead of silently presenting it as current.

7. **Coverage page explainability**
   - New official freezes show Top-10 and Top-20 pre-draw candidate-number support ranks.
   - Legacy freezes clearly show that the ranking was not retained rather than reconstructing it with post-draw information.

## Scientific boundary

These are diagnostics and research controls. They do not establish a positive expected-value edge in a random lottery. Main Combination scoring remains unchanged by this release.
