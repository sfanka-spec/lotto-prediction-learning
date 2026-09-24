# Upgrade to Lottery AI V1.6.1

1. Close the currently running Lottery AI application.
2. Keep a backup of your existing `lottery.db` before first launch of a new build.
3. Extract V1.6.1 into a new folder. Do not overwrite your only copy of the previous program folder.
4. Run `START_LOTTERY_AI.bat`.
5. Open **Analysis > Data** and verify the active data directory and historical draw count before deleting any older folder.

## Data path precedence

V1.6.1 uses: explicit `LOTTERY_AI_DATA` -> this build's existing local `data\lottery.db` -> existing `D:\Lottery_AI\data\lottery.db` on Windows -> discovered legacy Lottery AI databases.

An explicit environment path or an existing local database can no longer be overridden merely because another old database is larger.

## Existing frozen evidence

Existing frozen predictions remain historical evidence and are not rewritten. Old Production/Challenger pairs that were generated with unequal candidate budgets remain visible in the audit database but do not contribute to V1.6.1 auto-promotion statistics.

If an old prediction is missing a strategy shadow and the exact original candidate universe was not frozen, V1.6.1 leaves that comparator missing rather than regenerating a different candidate pool after the fact.

Unsigned legacy neural `.pkl` snapshots are not loaded automatically. They may be retrained from trusted historical data when the normal training requirements are met.
