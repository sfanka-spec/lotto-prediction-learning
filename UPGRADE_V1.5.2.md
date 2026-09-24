# Upgrade to V1.5.2

1. Keep your existing `data` folder and `lottery.db`.
2. Extract V1.5.2 to a new folder.
3. Run `START_LOTTERY_AI.bat`.
4. Do not delete older frozen predictions; V1.5.2 reads them but does not rewrite them.

## What changes on the next pre-draw freeze
A new `BUD1.2` portfolio decision will be frozen for the next target draw. It contains line roles, dual deployment views, and the current Shadow line-learning state.

## After the draw
The app evaluates each selected line separately and also evaluates the portfolio as a whole. The Learning page summarizes role and rank-band behavior using one effective observation per draw.
