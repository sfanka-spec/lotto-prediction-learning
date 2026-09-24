# Upgrade to V1.6.0

1. Close the existing Lottery AI window.
2. Extract the V1.6.0 ZIP into a new folder.
3. If your active `data` folder is stored beside the old application, copy it into the new folder. If you already use an external data folder, no move is required.
4. Run `START_LOTTERY_AI.bat`.
5. Open the hidden **Research** page and click **Run Research + Bayesian Lab** once for each game.
6. Review the Bayesian table. Historical rows appear immediately when enough rule-compatible history exists; future frozen rows accumulate automatically after subsequent draws.

The first research run can take longer because it reconstructs historical predictions without looking ahead. No database migration is required. Keep the old folder until V1.6.0 has opened successfully with your existing data.
