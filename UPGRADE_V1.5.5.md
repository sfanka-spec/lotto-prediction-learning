# Upgrade to V1.5.5

1. Close Lottery AI.
2. Extract the V1.5.5 folder.
3. Start with `START_LOTTERY_AI.bat`.
4. Your persistent data folder/database remains compatible; old freezes are not rewritten.

## Legacy freeze behavior

Old official freezes do not contain the new pre-draw Candidate-Number Support Rank. V1.5.5 therefore displays that field as unavailable for those historical freezes. Portfolio breadth, CWC@K and BestHit@K are safely derivable from the immutable frozen tickets and can be backfilled without changing the prediction.

## New future freezes

New Production freezes save the compact candidate-number support ranking in `factor_context_json` and freeze the Concentrated research strategy beside the other same-candidate shadows. These additions have 0% direct Production prediction weight.
