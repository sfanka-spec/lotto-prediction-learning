# Upgrade to V1.5.3

1. Close the running Lottery AI application.
2. Extract V1.5.3 to a new folder.
3. Keep your existing long-term `data` folder / `lottery.db`; do not delete it.
4. Start with `START_LOTTERY_AI.bat`.
5. Existing frozen predictions and old BUD1.x decisions remain untouched.
6. The next portfolio freeze uses `BUD1.3` and the corrected diminishing-return budget logic.

## What you should notice in Budget AI

- One-line portfolios show Diversity as `N/A`, not `1.000`.
- `Rank retention` is labelled as a guardrail rather than a cross-budget bonus.
- `Structural sweet-spot candidate` is separate from `Max deployment under cap`.
- The exact spend curve shows every legal line count and its marginal value per dollar.
- Once the global structural sweet spot is affordable, raising the maximum budget does not move the efficiency sweet spot merely because the ceiling is larger.
- With 6/49, if all frozen Top-20 cost only $60 and the cap is $100, the extra $40 remains unused because the system will not invent a 21st prediction.
