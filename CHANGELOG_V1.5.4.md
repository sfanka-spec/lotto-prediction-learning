# Lottery AI V1.5.4 — Budget Evidence & Oracle Hardening

## Scope

V1.5.4 is a correctness and explainability release for Adaptive Budget & Portfolio AI. It does **not** change the six-factor Main Combination Score, Bonus scoring, frozen Top-20 generation, Coverage Production mode, or historical draw database.

## Corrections

1. **Diminishing-return knee normalization fixed**
   - V1.5.3 divided deployment axes by their maxima but did not subtract their minima.
   - Because a one-line portfolio already has substantial utility, that positive intercept could bias the knee toward very small line counts.
   - V1.5.4 uses endpoint min-max normalization on both axes before the `y - x` curvature test.
   - The result is invariant to adding a constant baseline to the utility curve.

2. **Marginal-value semantics clarified**
   - Exact-k subsets are optimized independently; an 8-line subset is not guaranteed to contain the 3-line subset.
   - `frontier_marginal_value_per_dollar` is therefore explicitly a difference between optimized spend levels, not a literal “keep the old tickets and add one more” return.
   - Compatibility aliases remain so older UI/database readers do not break.

3. **Budget evidence now uses one paired draw cohort**
   - Different line counts are no longer ranked from different historical windows.
   - Only draws where every compared line count has its same-budget Random control are admitted to the comparison cohort.
   - Sparse legacy rows remain visible as `raw_n`, but cannot inflate evidence.

4. **Evidence sample-size bug fixed**
   - V1.5.3 could grade confidence from the largest sample count anywhere in the table even when the selected line count had fewer valid comparison draws.
   - V1.5.4 grades A/B/C/D from the comparator-bearing sample actually used by the selected line count.

5. **Post-draw oracle corrected**
   - V1.5.3 ranked tickets individually by `payout_known`. Unresolved pari-mutuel/jackpot tiers can have a payout floor of zero, so a genuinely stronger high-match ticket could be mislabeled below a small fixed-cash prize.
   - V1.5.4 uses an exact, non-monetary subset oracle over the frozen Top-20.
   - The oracle jointly optimizes Best Match, same-hit Bonus status, winning-number coverage, WCE, and average hit rate.
   - It is post-draw diagnostic/regret labeling only and never counts as forward performance.

6. **Budget screen ambiguity fixed**
   - `Efficiency plan` and `Full-capacity plan` are now shown separately with their own rank lists.
   - A $50 LOTTO MAX cap can therefore visibly show, for example, a 3-purchase efficiency plan **and** the 8-purchase full-capacity plan instead of displaying only the 3 selected ranks.
   - Remaining budget for the efficiency plan is described as deliberately unspent; the full-capacity remainder is described separately.
   - The screen states that exact-k plans are independently optimized and are not necessarily nested.

7. **Evidence labels aligned**
   - Budget Evidence Phase / sample count now comes from the budget learner itself rather than the separate Shadow-policy learner.
   - If the two sample counts differ, both are displayed explicitly.

## Versioning

- App: `V1.5.4`
- Portfolio policy: `BUD1.4`
- Portfolio shadow: `BUDS1.4`
- Frontier schema: `PORTFOLIO_FRONTIER1.3`
- Budget decision schema: `BUDGET_PORTFOLIO1.3`
- Judgment schema: `PORTFOLIO_JUDGMENT1.2`

Old frozen records remain immutable. New portfolio freezes use BUD1.4.

## Validation

- `pytest -q`: **122 passed**
- `python -m compileall -q app.py lottery_ai tests`: PASS
- `app` import: PASS
- Exact 20-line frontier smoke test: PASS for 6/49 and LOTTO MAX
- Exact post-draw Top-20 subset-oracle smoke test: PASS
- Paired-cohort evidence regression test: PASS
- Endpoint-normalization invariance test: PASS
