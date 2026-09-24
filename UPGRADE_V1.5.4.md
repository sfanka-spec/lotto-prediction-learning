# Upgrade to V1.5.4

1. Close Lottery AI.
2. Extract V1.5.4 to a new folder.
3. Keep your existing long-term `data` folder / `lottery.db`; do not delete it.
4. Start `START_LOTTERY_AI.bat`.
5. Existing predictions and BUD1.x records remain unchanged.
6. The next portfolio freeze uses `BUD1.4` / `PORTFOLIO_FRONTIER1.3`.

## What should look different in Budget AI

- A fixed cap now shows **two explicit rank lists**:
  - Efficiency plan — structural knee; may deliberately leave budget unused.
  - Full-capacity plan — maximum number of legal model-directed purchases that fit under the cap; informational, not a recommendation.
- The two rank lists can differ because every exact-k subset is optimized independently.
- Budget Evidence samples are separated from Shadow-policy learning samples.
- The exact deployment curve labels MV/$ as a frontier spend-level difference, not an add-one-ticket path.

## Data compatibility

No migration of old frozen records is required. As before, keep your real `data` folder when moving to the new program folder.
