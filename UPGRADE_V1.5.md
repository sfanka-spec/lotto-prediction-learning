# Upgrade to V1.5.0

1. Extract the new folder anywhere you prefer.
2. Keep your existing persistent `data` folder / `lottery.db` intact.
3. Run `START_LOTTERY_AI.bat`.
4. Confirm the status bar points to the expected database before deleting any older program folder.

V1.5.0 uses additive SQLite tables (`jackpot_snapshots`, `portfolio_decisions`, `portfolio_learning`). It does not destructively migrate or rewrite old frozen predictions.

For a target draw that is still safely in the future, V1.5 may attach the missing Budget/Portfolio frontier to an already-frozen Top-20. It will not create post-draw portfolio decisions and pretend they were pre-draw evidence.

New UI areas:
- `Budget AI / 预算AI` — Auto, preset, or custom maximum budget; selected frozen subset; budget frontier; learning/evidence status.
- `Jackpot / 奖池` — latest official WCLC snapshot, timestamp/status, Gold Ball or Lotto Max jackpot context.
- `Learning / 学习` — Portfolio Decision Memory and Shadow-learning diagnostics.

Important accounting note:
- LOTTO MAX: each model-directed selection requires one $6 purchase; the three terminal Quick Picks that come with the purchase are not counted as model-generated lines.
- LOTTO 6/49: the $3 play's system-assigned Gold Ball selection is tracked separately from Classic-number model performance.

`ROI floor` is intentionally conservative. Variable/pari-mutuel prizes are not guessed.
