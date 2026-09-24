# Lottery AI V1.6.3 — Current Draw Spacious UI Hardening

V1.6.3 is a UI-only refinement on top of V1.6.2. Production ranking, weights, candidate generation, frozen predictions, learning, research gates, and spending behavior are unchanged.

## Current Draw panel
- Increased panel height from 12 to 16 text rows.
- Increased text width from 76 to 94 monospace columns.
- Increased wrap length from 610 px to 790 px so long diagnostics stay on one line more often.
- Increased render allowance from 14 to 18 logical diagnostic lines, so lower diagnostics such as Concentration, Champion placement, Overall rank correlation, freeze consistency and Champion Shadow are not silently omitted.
- Keeps wrapping enabled as a safety net for narrower Windows scaling/DPI settings.

## Integrity
- No Production model or data changes.
- No database migration required.
- Existing V1.6.2 data directory is reusable.
