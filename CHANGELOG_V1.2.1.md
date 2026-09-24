# Lottery AI V1.2.1 — Model Quality Integrity

## Main changes

1. Removed Monte Carlo from prediction voting. It remains visible as a diagnostic percentile with **0% Production/Challenger weight**.
2. Added backward-compatible normalization for old P1.0/C1.0 snapshots that stored Monte Carlo at 15%; the six real factors are renormalized to 100% at runtime.
3. Challenger learning and Promotion Gate can no longer learn/promote a Monte Carlo weight.
4. Added **Feature Ablation Shadow** and **Rank Stability Shadow** to Research Tests.
5. Extended WCLC since-inception official-calendar bootstrap to **LOTTO MAX and LOTTO 6/49**.
6. Added explicit classification of off-calendar archive rows while preserving fail-closed model quarantine.
7. Fixed `random_control_walk_forward`'s missing `pstdev` import.

No existing frozen prediction is rewritten. Historical freeze provenance remains immutable.
