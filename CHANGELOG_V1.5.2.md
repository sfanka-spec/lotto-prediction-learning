# Lottery AI V1.5.2 — Per-Line Learning & Deployment Hardening

## Purpose
V1.5.2 extends V1.5.1 without changing the frozen Top-20 number-generation model. The release adds auditable per-line post-draw learning and separates an efficiency sweet spot from a spend-to-budget deployment plan.

## New per-line learning
- Every selected frozen line now keeps a PRE-DRAW role label: `CORE`, `COVERAGE`, `DIVERSITY`, or `BALANCED`.
- Role labels are derived only from frozen score/rank, model-consensus core retention, marginal unique-number contribution, and overlap. They do not use the draw result.
- After the draw, every selected line is reviewed separately for:
  - Main hits and matched numbers;
  - unique winning-number contribution within the selected portfolio;
  - Bonus hit;
  - fixed/known payout state;
  - one-at-a-time replacement regret against unselected frozen lines.
- Replacement alternatives are post-draw regret labels only; they never count as forward predictions.

## Draw-level statistical guardrail
- Individual selected lines are diagnostic units, not independent statistical samples.
- Role/rank-band learning is first averaged within each draw and only then aggregated across draws.
- Effective sample size remains the number of forward draws.
- Same-draw BUD version duplicates are deduplicated before learning.

## Budget/deployment clarification
- Fixed budget is now presented as a MAXIMUM budget.
- For a requested budget the UI shows both:
  - `Efficiency sweet spot`: may leave money unused;
  - `Max deployment under cap`: uses the largest legal model-directed spend under the budget.
- Added `$100` to the standard budget frontier.
- LOTTO MAX package display distinguishes model-directed combinations, companion terminal Quick Picks, and total physical selections.

## Decision freeze provenance
- Policy version advanced from `BUD1.1` to `BUD1.2`.
- New freezes use schema `BUDGET_PORTFOLIO1.2`.
- Frozen decisions now include:
  - per-line PRE-DRAW roles in every frontier choice;
  - line-learning state at freeze;
  - both efficiency and max-deployment views for standard budgets.
- Existing historical freezes remain immutable.

## Bug fixes found during review
1. Fixed a UI key mismatch: the Learning page requested `production_vs_random_avg_hit_edge`, while the validator actually returns `production_vs_random_best_hit_edge`.
2. Single-line portfolios no longer get a misleading `COVERAGE` role solely because the only line contributes all of its own numbers.
3. Budget wording now distinguishes maximum budget, recommended spend, and unused budget.
4. LOTTO MAX budget display now makes the 1 model-directed + 3 terminal Quick Pick packaging explicit.

## Production impact
- Number-model scoring: unchanged.
- Coverage Production mode: unchanged.
- Per-line learning: Shadow-only, 0% Production impact.
- No historical prediction is regenerated or rewritten.
