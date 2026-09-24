# Lottery AI V1.5.3 — Marginal Budget & Frontier Hardening

## Scope

V1.5.3 is a budget-optimizer correctness release. It does **not** change the Main number model, frozen Top-20 logic, Bonus model, Coverage Production mode, or historical draw data. The release fixes a structural bias exposed by the V1.5.2 Budget AI screenshots: a one-line portfolio could receive perfect Diversity and Rank Retention values, causing the structural efficiency selector to confuse "smallest spend" with "best diminishing-return point".

## Corrections

1. **Single-line Diversity bias removed**
   - A one-line portfolio has no between-ticket diversity to measure.
   - `diversity=0.0` and `diversity_applicable=false` for `k=1`.
   - UI displays `N/A (single line)` instead of `1.000`.

2. **Rank Retention changed from bonus to guardrail**
   - Strong rank retention no longer directly rewards buying fewer lines.
   - It is used only as a lower-quality guardrail/tie-break inside a fixed line count.
   - Cross-budget deployment sizing excludes Rank Retention.

3. **Fixed-k selection separated from budget-size selection**
   - First question: for exactly `k` lines, which frozen subset is structurally best?
   - Second question: how many lines should be deployed before structural gains flatten?
   - These are now different objectives and cannot contaminate each other.

4. **Marginal deployment curve replaces arbitrary per-line penalty**
   - Added monotone deployment utility based on Number Coverage, model-core Concentration and applicable Diversity.
   - Added `marginal_deployment_gain` and `marginal_value_per_dollar` for every exact spend level.
   - Structural sweet spot uses a normalized diminishing-return knee instead of `policy_value - fixed penalty * lines`.

5. **Budget-cap stability fix**
   - Once a budget can afford the global structural sweet spot, increasing the budget ceiling no longer changes that efficiency recommendation.
   - If the cap cannot afford the global knee, a local knee is calculated only within the affordable range.

6. **Budget Frontier semantics corrected**
   - UI now shows an **Exact Deployment Curve**: 1 line, 2 lines, ... Top-20, each at its exact legal cost.
   - Standard `$10/$20/$30/$50/$100` rows now show **maximum deployment under cap**, not repeated sweet-spot rows.
   - The sweet spot and maximum deployment are displayed as separate answers.

7. **Data-collection wording hardened**
   - Before sufficient forward samples, fixed-budget output is explicitly labelled `Structural sweet-spot candidate (NOT ROI-VALIDATED)`.
   - No structural score is presented as proven profitable ROI.

8. **Unused-budget explanation**
   - If all frozen Top-20 are already deployed, remaining money is explicitly explained as unused because the model will not invent extra combinations merely to spend the budget.
   - If the next legal play would exceed the cap, the UI says so.

## Versioning

- App: `V1.5.3`
- Portfolio policy: `BUD1.3`
- Portfolio shadow: `BUDS1.3`
- Frontier schema: `PORTFOLIO_FRONTIER1.2`

Old frozen records are not rewritten. New portfolio decisions use BUD1.3.

## Validation

- `pytest -q`: **115 passed**
- `python -m compileall -q app.py lottery_ai tests`: PASS
- `app` import: PASS
- temporary SQLite initialization: PASS
- AST unused-import scan: 0 findings
- randomized frontier/budget invariants: PASS
- 20-line exact subset smoke test: PASS for 6/49 and Lotto Max

See `VALIDATION_V1.5.3.txt` for details.
