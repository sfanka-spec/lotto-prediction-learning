# Upgrade to V1.4.1

1. Keep your existing `D:\Lottery_AI\data` folder / `lottery.db` unchanged.
2. Extract the V1.4.1 folder.
3. Run `START_LOTTERY_AI.bat`.
4. Confirm **Analysis > Data** points to the expected persistent database.
5. Open **Analysis > Learning**. The existing 2026-09-12 frozen Production result will be re-read to add Champion ranking calibration (without changing the original prediction).
6. Open **Analysis > Research**. New V1.4 future predictions will freeze Balanced, Score-only, Focused and Pure-Coverage shadows before the draw.

Important: V1.4 does not retro-generate post-draw strategy portfolios for 2026-09-12 and call them pre-draw evidence. The Coverage-vs-Concentration paired monitor begins with future V1.4 pre-draw freezes.


## V1.4.1 notes

- No database reset or migration is required.
- Existing V1.4.0 integrity records are not rewritten. Their Prediction hash can still be rechecked, while Feature/Algorithm layers without V1.4.1 verification inputs are labeled `NOT_VERIFIABLE`.
- New V1.4.1 freezes independently re-hash Prediction, Feature Snapshot, and Algorithm Descriptor. Candidate-pool digest remains provenance-only unless a separate full pool snapshot is retained.
- Production prediction semantics and Balanced Coverage weights are unchanged.
