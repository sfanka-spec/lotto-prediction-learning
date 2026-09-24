# Lottery AI V1.5.1 — Concentration & ROI Hardening

## Scope

V1.5.1 is a correctness/diagnostics release built on V1.5.0. It does **not** claim a predictive lottery edge and it does not retroactively rewrite frozen predictions. The release focuses on the exact problems exposed by the new Top-20 / Budget / Portfolio architecture: winner concentration, same-budget validation, package-cost accounting, ROI semantics, and draw-level learning integrity.

## Main corrections

1. **Winner Concentration Efficiency (WCE)**
   - Adds `best_single_ticket_hit / Top-N winning-number coverage`.
   - Adds `winner_dispersion_loss` so a draw such as Coverage 5/6 + Best 3/6 is explicitly diagnosed as a concentration problem instead of merely a coverage success.
   - Champion schema advances to `CHAMP1.5` and long-run summaries track WCE.

2. **New `concentrated` research strategy**
   - Fifth same-candidate Shadow beside `balanced`, `score_only`, `focused`, and `pure_coverage`.
   - Preserves more high-score/model-core repetition and applies a softer overlap penalty.
   - Research-only; it cannot auto-promote directly into Production.
   - Coverage engine provenance advances to `COV1.2`.

3. **Structural Budget-AI monotonicity bug fixed**
   - V1.5.0 rewarded cumulative selected quality/rank mass relative to all Top-20, causing structural Auto to drift toward large portfolios even before evidence existed.
   - V1.5.1 uses average selected quality/rank retention plus explicit model-core concentration and a modest line deployment penalty.
   - Frontier schema advances to `PORTFOLIO_FRONTIER1.1`.

4. **Budget learning no longer mistakes ROI lower bounds for true ROI**
   - Unresolved pari-mutuel/jackpot prizes cannot silently act as zero-return observations when choosing a budget.
   - Exact official prize-breakdown values can resolve Main-line pooled tiers when available.
   - Until monetary outcomes are genuinely complete, line-count learning uses same-budget Best-Match/WCE/Coverage selection efficiency instead of biased monetary ROI.

5. **Retail-package ROI semantics fixed**
   - LOTTO MAX model-directed lines are correctly costed as one $6 purchase each; a $6 purchase also contains three terminal Quick Picks.
   - LOTTO 6/49 model-directed Classic performance does not silently absorb the system-assigned Gold Ball result.
   - Main-line `roi_floor`/`roi_known` are now explicitly identified as **model-directed selection** metrics, not exact purchase ROI.
   - Exact investment ROI is exposed only when `package_payout_by_rank` provides the total terminal/receipt payout for every selected physical purchase.

6. **Same-budget / same-draw validation fixed**
   - Production and Shadow are paired inside the same draw and compared at the Production Auto line count.
   - Missing legacy records can no longer shift two separately truncated lists onto different dates.
   - `judge_frontier()` preserves outcomes for every line count in both Production and Shadow.

7. **Multiple-testing control across budget sizes**
   - 1..20 line-count selection tests now receive Benjamini-Hochberg FDR correction.
   - Evidence grades use FDR-adjusted q values rather than selecting the smallest uncorrected p-value.

8. **Draw-level sample integrity**
   - Portfolio learning de-duplicates multiple version records for the same target draw.
   - Shadow-learning `n` counts only records with complete frozen rows, a real selected subset, and an oracle label.
   - One lottery draw remains one statistical observation regardless of how many subsets were searched.

9. **Stronger same-budget Random Control**
   - Small subset spaces are exhaustively enumerated; larger ones use deterministic Monte Carlo.
   - Baseline reports Avg Hit, Best Hit, winner coverage, WCE, and payout-floor diagnostics.

10. **Regret labels expanded**
    - Adds Best-Match regret and coverage regret in addition to payout-floor and average-hit regret.
    - Oracle remains explicitly post-draw and can never count as forward performance.

11. **Jackpot-state hardening**
    - Unchanged economic state no longer creates a fresh jackpot-history row merely because `observed_at` changed.
    - 6/49 Gold-Ball count is separated from crowd-pressure proxy. Ball count measures conditional prize attractiveness; it is not evidence of ticket-sales volume.

12. **Auto action/evidence gate made internally consistent**
    - Research candidate line count may be displayed during data collection/provisional phases.
    - Strict Auto action remains `0 / NO BET` until the configured same-budget evidence gate is supported.

## Validation

- `pytest -q`: **101 passed**
- Full Python compilation: **PASS**
- Application import: **PASS** (`APP_VERSION=V1.5.1`)
- Static unused-import scan of `app.py` + `lottery_ai/*.py`: no obvious unused imports found
- 12,000-candidate smoke test: five strategies × 20 unique rows for both games
- Exact 20-line subset frontier: `2^20 - 1 = 1,048,575` non-empty subsets

Validation-container smoke timings (machine dependent):
- LOTTO 6/49: five-strategy suite ~4.16 s; exact frontier ~3.54 s
- LOTTO MAX: five-strategy suite ~4.31 s; exact frontier ~3.51 s

## Deliberately unchanged research risks

- `frequency`, `gap`, `pairs`, `structure`, `recent`, and `region` remain **research ranking heuristics**, not claims that one legal exact combination has a higher official draw probability.
- In particular, empirical pair lift is an association heuristic based on historical marginals; it is not labelled as an official fair-draw probability multiplier. Changing that Production factor without forward A/B evidence would create a new model, so V1.5.1 leaves it under existing Ablation/Random/Shadow validation rather than silently changing Production semantics.
- Jackpot crowd pressure remains a jackpot-state proxy until verified sales/issued-selection data is available.
