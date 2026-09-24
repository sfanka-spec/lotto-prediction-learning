# Lottery AI V1.2.4 — Champion Match Learning

## Scope

Post-draw evaluation and learning upgrade. Production prediction semantics are unchanged: frozen Main combinations, Combination Score, Bonus Conditional Score, COV1.1 Balanced Coverage, Sharing Risk policy, and official freeze cadence are preserved.

## Changes

1. **Match Leaderboard**
   - Sorts frozen tickets after the draw by Main Match descending, then confirmed Bonus hit, then original frozen Combination Score.
   - Preserves each ticket's original Production rank for auditability.

2. **Champion Pool**
   - All tickets tied at the maximum Main Match are retained as Champions.
   - Saves matched numbers, structural profile, frozen pre-draw components, and Champion-vs-rest deltas.

3. **Selection vs Combination diagnosis**
   - `selection_miss = pick_size - Top-N coverage`.
   - `combination_gap = Top-N coverage - best single-ticket match`.
   - Classifies the dominant diagnostic as Number Selection, Combination Concentration, Mixed, or None.

4. **Champion Shadow learning**
   - Adds a separate `CS1.x` Champion Shadow weight profile.
   - Uses evidence-damped Champion-vs-rest frozen component signals.
   - Anchored to current Production weights and sample-size damped.
   - Production influence remains exactly 0%.
   - Calibration milestone is 30 Production Champion samples.

5. **Backward-compatible SQLite backfill**
   - Adds `champion_learning` keyed by immutable `freeze_id`.
   - Already-judged V1.2.3 freezes are automatically analyzed after upgrade.
   - No frozen prediction, historical judgment, or Production score is rewritten.

6. **UI upgrade**
   - Current Draw panel shows Match leaders, Champion ticket(s), matched numbers, covered/missed winners, selection miss, combination gap, and learning-save state.
   - Learning Center shows the complete Top-20 Match Leaderboard plus long-run Champion Shadow diagnostics.
   - Latest evaluated draw remains visible in Learning Center after the calendar advances to the next draw.

7. **Learning-log separation**
   - Weight page continues to show the latest Challenger adaptive update instead of accidentally treating a Champion Shadow log as Challenger learning.

## 2026-09-12 visible-result diagnostic

From the supplied Current Draw screenshot for LOTTO 6/49:

- Winning: `01 03 17 20 26 32`, Bonus `05`
- Original Top 3: `#1 0/6`, `#2 2/6`, `#3 1/6`
- Best single frozen ticket: `3/6`
- Top-20 coverage: `5/6`
- Selection miss: `1`
- Combination concentration gap: `2`
- Primary diagnostic: `COMBINATION_CONCENTRATION`

The source ZIP does not contain the user's persistent `lottery.db`, so the exact Champion rank/numbers are intentionally not fabricated. V1.2.4 reads the existing database automatically (normally `D:\Lottery_AI\data\lottery.db`) and backfills the exact Champion record on first update/startup.

## Validation

- `pytest -q`: **67 passed**
- Full Python compilation: passed
- Champion aggregate regression for the visible 2026-09-12 pattern: passed
- Tie sorting Main Match -> Bonus -> frozen Score: passed
- Already-judged V1.2.3 freeze backfill: passed and idempotent
- Current Draw snapshot Champion fields: passed
