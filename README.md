# Lottery AI V1.6.5 — Statistical Correctness & Runtime Hardening

V1.6.5 is built directly on V1.6.4. It fixes a without-replacement bias in the pair-co-occurrence feature, removes the large-df t-critical discontinuity, repairs small-pool Monte Carlo diagnostics, and carries forward runtime/performance hardening for candidate generation, CSV import, network retries, model snapshots, UI failure recovery, and Pacific-time cutoffs.

Important compatibility note: the corrected `pair_lift` expectation can legitimately change newly generated Production/Challenger rankings. Existing frozen predictions and their post-draw audit records are not rewritten. Monte Carlo remains diagnostic-only at 0% Production weight.

Key V1.6.5 changes:
- finite-population correction for `pair_lift` under k-of-M sampling without replacement;
- smooth Student-t critical approximation above df=120 instead of jumping directly to 1.96;
- fresh seeded Monte Carlo reference slices for small candidate pools;
- fast float `mean`/`pstdev` plus precomputed historical structure invariants;
- bounded candidate-generation guards for Production and Random Control;
- GB18030/CP1252 CSV fallbacks with skipped-row reporting;
- atomic signed model-snapshot writes with rollback on ordinary write/replace failures;
- HTTP 408/429 retry handling with bounded `Retry-After`;
- UI worker failure recovery and explicit `FAILED` update status;
- Pacific timezone failures are explicit rather than silently using the computer's local timezone;
- test dependencies live in `requirements-dev.txt`.

See `CHANGELOG_V1.6.5.md`, `UPGRADE_V1.6.5.md`, and `VALIDATION_V1.6.5.txt`.

A local Windows/Python research application for **LOTTO MAX** and **LOTTO 6/49**.

> Important: this software ranks combinations and studies statistical structure. A high `Combination Score` is **not** a higher official jackpot probability. National lottery draws use certified RNG systems; the app therefore keeps a Random Baseline, placebo tests, and Shadow models to detect overfitting.


## V1.5.5 Rank Concentration & UI Hardening

V1.5.5 separates three questions that were previously easy to mix together: **did the Top-20 portfolio contain a winning number somewhere, did the model rank winning numbers/tickets toward the front, and did those winners concentrate into one legal ticket?** Portfolio-union coverage is no longer presented as if it were direct number-selection skill.

New frozen diagnostics include:

- **Portfolio breadth:** ticket slots, unique numbers, and winner coverage. A 20-line LOTTO MAX portfolio that spans all 52 numbers is explicitly shown as `52/52 unique`; a resulting `7/7` portfolio coverage is therefore not mistaken for a narrow prediction.
- **CWC@K (Cumulative Winning Coverage):** winner coverage in the first 3, 5, 10 and 20 ranked tickets. This measures whether winners appear early in the model's own ordering.
- **BestHit@K:** the best single-ticket match available within the same rank windows. This separates front-loaded winner presence from actual combination quality.
- **Pre-draw Candidate-Number Support Rank:** a compact number ranking derived only from the already-scored pre-draw candidate pool and frozen with new official predictions. It has 0% direct Production influence and is not presented as a jackpot probability. After the draw, @10/@15/@20 coverage can be judged independently from the Top-20 ticket union.
- **Rolling 20/50 diagnostics:** WCE, combination gap, Champion rank, Spearman, CWC@K, BestHit@K, and Candidate-Number coverage are tracked over rolling forward samples rather than overreacting to one draw.
- **Concentrated research shadow:** the existing concentration strategy is now actually frozen beside Balanced, Score-only, Focused and Pure Coverage from the same candidate pool for future paired validation. It remains research-only and cannot auto-replace Production.
- **UI hardening:** CURRENT DRAW now wraps instead of clipping long diagnostic lines, has a taller panel, and surfaces portfolio breadth, CWC@K, BestHit@K, candidate-number rank, WCE and ranking calibration directly. Freeze/champion identity consistency is checked before displaying the shadow-save state.

V1.5.5 does **not** claim that lottery draws are predictable. These additions improve measurement hygiene: they make it harder for a broad portfolio to look impressive merely because it eventually touches many or all possible numbers.

Validation for V1.5.5: **127 tests passed**, full Python compilation passed, and application import passed. See `VALIDATION_V1.5.5.txt`.



## V1.5.1 Concentration & ROI Hardening

V1.5.1 keeps V1.5.0's Top-20 / Budget / Jackpot architecture but hardens the parts that can most easily create misleading conclusions. It adds Winner Concentration Efficiency (WCE), a `concentrated` same-candidate Shadow strategy, fixes the structural Budget AI's cumulative-line bias, makes Production-vs-Shadow comparisons truly same-draw/same-budget, applies BH-FDR across line-count tests, and de-duplicates version-upgrade records so one draw cannot become two statistical samples.

ROI semantics are now stricter: Main-number payout is a **model-directed selection** metric. It is not called exact retail-package ROI unless terminal/receipt data supplies the total package payout. This matters because a LOTTO MAX purchase contains three companion Quick Picks in addition to the chosen line, and a LOTTO 6/49 play carries a system-assigned Gold Ball selection. Missing companion outcomes are never silently valued at zero.

The new WCE diagnostic separates two questions that Top-N coverage alone cannot answer: *did the model include the eventual winning numbers somewhere?* and *did it concentrate them into a single legal ticket?* A draw with Coverage `5/6` and Best Match `3/6` has WCE `60%`, highlighting dispersion rather than treating 5/6 portfolio coverage as equivalent to a 5/6 ticket.

Validation for V1.5.1: **101 tests passed**, full Python compilation passed, application import passed, and a deterministic 12,000-candidate / five-strategy / exact-20-line-frontier smoke test passed for both games. See `VALIDATION_V1.5.1.txt` for details.


## V1.5.0 Adaptive Budget, Portfolio & Jackpot Learning

V1.5.0 adds a second decision layer **after** the immutable Top-20 prediction. The number model still decides which 20 combinations are frozen. A new Portfolio AI then decides how to use a user-defined budget *within those 20 lines*; it never regenerates or recombines numbers.

### 1. Frozen Budget Frontier

For every new official Top-20, V1.5 freezes the best structural subset for every line count from 1 through 20 **before the draw**. With 20 lines this is an exact search of `2^20 - 1 = 1,048,575` non-empty subsets. The optimizer uses compact typed-array dynamic caches so the exact search remains practical on a local PC.

The user can choose `Auto`, `$10`, `$20`, `$30`, `$50`, or type a custom budget. A fixed budget is a hard ceiling, not a target that must be fully spent. The selector may leave money unused when another line does not improve the frozen structural frontier enough.

The subset policy balances pre-draw information only: retained Combination quality, number coverage, diversity, controlled concentration, and rank retention. This directly addresses the known coverage-vs-concentration trade-off: the app can keep some overlap when concentration is useful instead of mechanically scattering every strong number across different tickets.

### 2. Draw-level Budget Learning

Every budget decision stores its pre-draw rationale. After the draw, V1.5 records the outcome, same-budget Random control, and a post-draw same-size oracle **only as a regret label**. The oracle can teach the Shadow policy what it missed but never counts as forward performance.

The complete 1..20 line-count frontier is judged after each draw. The Budget learner therefore learns which line counts historically had the best cost/return efficiency, but the statistical sample size remains the **number of draws**, not the number of subsets searched.

Learning phases are intentionally slow: Data Collection `<30`, Exploratory `30–49`, Provisional `50–99`, Screening `100–199`, Confirmation `200+`. A Selection Evidence Grade (`D/C/B/A`) summarizes evidence versus same-budget random subsets. Grade measures selector evidence, **not guaranteed profit**.

### 3. Conservative ROI accounting

V1.5 separates known payout values from unknown/pari-mutuel payouts. `ROI floor` includes only prize values that can be determined without guessing. Higher variable prize tiers are marked unresolved rather than fabricated.

This is especially important for the current game packaging:

- LOTTO 6/49: one user-directed Classic line costs `$3` and also receives a system-assigned Gold Ball selection. Gold Ball value is not falsely credited to the Classic-number model.
- LOTTO MAX: one `$6` purchase contains one user-directed selection plus three terminal Quick Picks. Selecting five model lines therefore means five `$6` purchases; the three random companion lines per purchase are not falsely credited to the model.

The app never uses Martingale/loss chasing and never increases a budget because previous draws lost.

### 4. Latest Official Jackpot layer

A separate WCLC jackpot provider refreshes the latest official jackpot state without changing the frozen number prediction. V1.5 tracks:

- LOTTO MAX jackpot, current `$90M` cap, additional `$100K` MAXPLUS draw count, and MAXMILLIONS count when the official page exposes it;
- LOTTO 6/49 fixed `$5M` Classic Jackpot, Gold Ball Jackpot, and Gold Balls remaining.

If a refresh fails, the cached snapshot is explicitly marked `STALE` with its original observation time; it is not presented as live/current.

### 5. Jackpot economics and crowd context

Jackpot state is frozen alongside each Portfolio decision so later research can ask whether budget efficiency behaves differently at low, medium, or near-cap jackpots. `Crowd Pressure` is deliberately labelled a **jackpot-state proxy**, not measured sales. V1.5 does not invent sales counts or a Gold Ball per-play probability when verified issued-selection counts are unavailable.

Existing combination `Sharing Risk` remains advisory-only at 0% prediction weight. It can discuss possible prize-sharing pressure conditional on winning but cannot change a legal combination's draw probability.

### 6. Automatic self-review loop

The V1.5 closed loop is:

`Prediction -> Top-20 Freeze -> Budget/Portfolio Freeze -> Draw -> ROI-floor/Match/Regret Judge -> Shadow Learn -> Evidence Gate`

Production prediction weights remain isolated. The Portfolio Shadow learner can change only its own research weights until enough out-of-sample evidence exists. The existing V1.4 same-candidate strategy tournament, Champion learning, Random Control, bootstrap/permutation/FDR validation, and integrity audit all remain active.

Validation for V1.5.0: **87 tests passed**, full Python compilation passed, application import passed, and a 12,000-candidate smoke test completed for both games. On the validation container, the 12,000-candidate four-strategy suite took about 3.4 s (6/49) / 3.8 s (Lotto Max), and the exact 20-line budget frontier took about 2.5 s per game. Timing is machine-dependent.


## V1.4.1 Validation Hardening

V1.4 keeps the existing Production prediction semantics conservative and upgrades the **evaluation, comparison, calibration, and audit layers**. It does not claim that historical lottery data creates a reliable future winning edge.


### V1.4.1 hardening changes

- Removed the two review-confirmed dead-code remnants in `evaluation.py` (`pstdev` import and unused `score` assignment).
- Bootstrap percentile endpoints now use linear interpolation rather than integer index truncation.
- Paired sign-flip testing now uses **exact exhaustive enumeration** for up to 16 non-zero paired differences and deterministic Monte Carlo with +1 correction above that threshold.
- Added a deterministic known-distribution simulation self-check for bootstrap coverage and sign-flip Type-I error sanity.
- Champion Score Percentile UI now states the direction explicitly: **higher percentile = stronger pre-draw Combination Score rank**.
- Integrity UI is split into Prediction / Feature Snapshot / Algorithm / Candidate Pool layers. `PASS` is reserved for a layer that was actually re-hashed and matched; `NOT_VERIFIABLE` is shown when the source snapshot needed for recomputation is not retained.
- Production weights, Coverage policy, frozen historical predictions, and Shadow-only boundaries are unchanged.

### 1. Staged diagnosis

Every post-draw frozen Production portfolio is now diagnosed as separate stages:

- **Number Selection** — how many winning numbers were present anywhere in the frozen Top-N portfolio.
- **Combination Concentration** — how many covered winners failed to reach the best single ticket.
- **Ranking Calibration** — where the eventual Champion was originally ranked before the draw.
- **Portfolio Trade-off** — whether coverage optimization gained winner coverage at the cost of best-ticket concentration.

Champion records now include Champion original rank, Score percentile, Score-vs-Hit Spearman correlation, Top-5/Top-10 hit averages, and an explicit ranking diagnosis (`WELL_RANKED`, `MID_RANKED`, or `UNDER_RANKED`). Existing V1.2.4 Champion records are safely refreshed from their immutable frozen predictions.

### 2. Same-candidate strategy shadows

For every **new V1.4 official prediction**, Production candidates are scored once and four fixed 20-line portfolios are derived from that exact same candidate pool:

- `balanced` — current Production portfolio policy;
- `score_only` — Main Combination Score only;
- `focused` — more concentrated/core-pool portfolio;
- `pure_coverage` — coverage-heavy research benchmark.

All four are frozen before the draw. Only Production is official; the other strategy freezes are **Shadow only with 0% Production influence**. This makes later `Coverage Gain` and `Concentration Cost` comparisons fairer because the strategies share the same pre-draw candidates.

For an older prediction already frozen before upgrading, V1.4 may freeze pre-draw strategy shadows only if the target draw is still safely in the future. Provenance explicitly records that those upgrade-bridge shadows did **not** share the original Production candidate pool. V1.4 never retro-generates a strategy after a draw and counts it as pre-draw evidence.

### 3. Coverage-vs-concentration monitor

V1.4 tracks:

- `Balanced Coverage Gain vs Score-only = Balanced Top-N Coverage - Score-only Top-N Coverage`;
- `Concentration Cost = Score-only Best Match - Balanced Best Match`.

Positive Coverage Gain means the diversity optimizer covered more eventual winning numbers. Positive Concentration Cost means the Score-only portfolio produced a better single-ticket match. These values are accumulated over frozen out-of-sample draws rather than inferred from one result.

### 4. Statistical validation

The Research page adds research-only validation on paired frozen draws:

- 95% bootstrap confidence intervals for mean strategy deltas;
- paired sign-flip permutation tests;
- standardized paired effect size;
- Benjamini-Hochberg False Discovery Rate correction across strategy comparisons;
- rolling 30/50/100-draw deltas;
- `WAITING`, `OBSERVE`, `SCREENING_SIGNAL`, and `CONFIRMATION_SIGNAL` gates.

These gates are safeguards against overfitting and multiple-testing accidents. They are **not proof that a fair lottery is predictable**.

### 5. Freeze integrity / anti-leakage audit

New V1.4.1 freezes store SHA-256 provenance for the frozen prediction payload, feature snapshot, algorithm identity, data cutoff, and candidate-pool digest when applicable. The verifier now reports four separate layers: **Prediction**, **Feature Snapshot**, **Algorithm Descriptor**, and **Candidate Pool**. Prediction/feature/algorithm layers are independently re-hashed for new V1.4.1 freezes. The candidate-pool digest is explicitly labeled `NOT_VERIFIABLE` unless an independent candidate snapshot exists, so the UI does not overstate what has actually been re-checked. Legacy V1.4.0 records remain readable and are labeled accurately rather than rewritten.

### 6. 2026-09-12 learning behavior

The existing 2026-09-12 frozen 6/49 Production portfolio can be re-evaluated safely because its original Top-20 and scores were already frozen before the result. V1.4 can therefore add Ranking Calibration to the existing Champion analysis. However, it will **not** manufacture a post-draw Score-only/Focused/Pure-Coverage portfolio for 2026-09-12 and pretend it was frozen before the result. The new paired strategy monitor begins with future V1.4 pre-draw freezes.

Validation for V1.4.1: **77 tests passed**, full Python compilation passed, application import passed, deterministic statistical simulation self-check passed, and a 12,000-candidate same-pool strategy smoke test completed for both 6/49 and Lotto Max.


## V1.2.4 Champion Match Learning

V1.2.4 adds a post-draw **Match Leaderboard + Champion Pool + Shadow Learning** layer without changing the frozen Production prediction. Existing V1.2.3 predictions stay immutable and are backfilled safely after upgrade.

New behavior:

- Every frozen portfolio is ranked after the draw by **Main Match descending -> confirmed Bonus hit -> original frozen Combination Score**.
- All ties at the maximum Main Match become the **Champion Pool**; no arbitrary single winner is chosen.
- The Current Draw panel now shows the actual Champion rank(s), matched numbers, Top-N covered winners, missed winners, **selection miss**, and **combination concentration gap**.
- `Analysis > Learning` keeps the full Top-20 post-draw Match Leaderboard and Champion Pool.
- Champion learning compares only **pre-draw frozen component values** of Champion vs non-Champion tickets. It never learns by simply boosting the numbers that happened to win.
- Champion-derived weights are stored as a separate `champion_shadow` model (`CS1.x`) with **0% Production influence**. The first calibration milestone is 30 evaluated Production draws.
- A new `champion_learning` SQLite table stores diagnostics by `freeze_id`; it does not rewrite old freezes or judgments.
- On startup/update, already-judged V1.2.3 freezes are automatically backfilled, so a result that arrived before the upgrade can be learned immediately.
- The existing Challenger correlation learner, Random Control, Research Portfolio, Coverage optimizer, Bonus model, and strict Production Promotion Gate remain intact.

For the 2026-09-12 6/49 result shown in the upgrade request, the known aggregate diagnostic is **Best 3/6, Top-20 Coverage 5/6**, which corresponds to **selection miss = 1** and **combination concentration gap = 2**. The exact Champion ticket/rank is read from the user's persistent frozen `lottery.db` when V1.2.4 starts; it is not guessed from the source package.

Validation for this release: **67 tests passed**, including a regression fixture matching the visible 2026-09-12 aggregate pattern and a legacy-judgment backfill test.

## V1.2.3 Coverage Performance & Diagnostics

V1.2.3 is a review-driven maintenance release on top of V1.2.2. It does **not** change the Main Combination Score, Bonus Conditional Score, Balanced coverage weights, quality floor, overlap policy, or official freeze cadence.

Changes:

- Coverage engine provenance advances to **COV1.1**.
- `_local_swap` now evaluates one-row replacements with exact incremental Number/Pair/Triple/signature/overlap deltas instead of rebuilding the full portfolio for every candidate trial.
- The incremental objective is regression-tested against the full rebuild objective and must match exactly.
- The greedy selector keeps the same deterministic tie-break but caches `best_key` directly for clarity.
- Auto Promotion now writes a Production learning-log entry containing old Production weights, promoted Challenger weights, z-score/mean-edge evidence, and version provenance.
- The unused `COVERAGE_ENGINE_VERSION` import in `app.py` is removed.
- Provider diagnostics are added at meaningful source/fallback boundaries (Atlantic verifier, National-Lottery archive fallback, Lotto.net yearly fallback) without logging every expected malformed historical row.
- Test suite: **64 passed**.

A deterministic 2,500-candidate / Top-20 Balanced benchmark produced the **same final portfolio hash** in V1.2.2 and V1.2.3 while reducing median optimizer time from about **1.77 s to 0.78 s** on the validation container (~2.27x faster). This benchmark is directional, not a guarantee for every PC.

## V1.2.2 Combination Coverage Optimizer

V1.2.2 keeps the V1.2.1 **Main Combination Score**, Bonus model, data-integrity safeguards, Current Draw panel, and Sharing-Risk separation intact. It replaces the old simple overlap penalty with a separate Mandel-inspired **portfolio-selection layer**.

Official flow:

`scored candidate pool -> Combination Score (unchanged) -> COV1.0 Balanced Coverage Optimizer -> frozen 20-line portfolio -> per-Main Bonus freeze`

The optimizer never edits a candidate's Main score. It only chooses which already-scored candidates coexist in the official fixed portfolio. The default **Balanced** objective is:

- 50% Combination quality
- 20% marginal Pair coverage
- 15% marginal Triple coverage
- 10% marginal Number coverage
- 5% coarse structural diversity
- dynamic overlap penalty for near-duplicate selections

A score-quality floor prevents the optimizer from accepting clearly inferior Main combinations merely to gain coverage. The highest Main-score candidate remains anchored, and a deterministic local-swap pass can improve the final portfolio without repeated regeneration.

### Coverage metrics

**Analysis > Coverage** shows explicit-denominator metrics:

- unique numbers and full-pool coverage
- unique Pair slots, Pair reuse, Pair efficiency
- unique Triple slots, Triple reuse, Triple efficiency
- average/max ticket overlap
- structural diversity
- Coverage Efficiency and Portfolio Score
- a shared-number overlap matrix for the first 12 displayed picks

LOTTO MAX metadata uses the current 7/52 configuration and 4 lines per play; LOTTO 6/49 uses 6/49 and one Classic line per play for portfolio-count display. These fields are packaging metadata only; they do not change prediction scoring.

### Research-only modes

`focused` performs conditional core-pool compression (15-number pool for 6/49; 18 for Lotto Max) and `pure_coverage` acts as a benchmark. Neither can auto-replace Production. The Research tab adds a same-budget historical shadow comparison of `score_only`, `balanced`, `focused`, `pure_coverage`, and Random Control using the same pre-draw candidate pool.

**Important:** combinatorial coverage can reduce redundant tickets under a fixed budget; it does **not** make an individual legal lottery combination more likely to be drawn.

### Version/provenance rule

There was already an earlier file named V1.2.0 in this project history, followed by V1.2.1. This package therefore uses **V1.2.2 / COV1.0** internally rather than reusing V1.2.0 for a different algorithm. Existing frozen predictions remain immutable and are never rewritten.

## V1.1.2 Stability & Data Integrity

V1.1.2 keeps all V1.1.1 Production/Combination/Bonus scoring behavior unchanged and hardens runtime reliability and data integrity:

- fixes the asynchronous Tk worker error-dialog closure bug;
- centralizes paired z-score handling across Promotion/UI/Backtest;
- rejects malformed provider rows again immediately before clean DB writes;
- records provider failures in a rotating `data/logs/lottery_ai.log`;
- adds regression tests for worker errors, zero-variance z behavior and final DB-write validation.

The V1.1 Research Engine and frozen Main/Bonus provenance remain intact. V1.1.1 introduced:

- `Score` is explicitly named **Combination Score** on Main results.
- Bonus results use **Bonus Conditional Score** and are never fed back into Main ranking.
- every new V1.1 freeze stores a separate conditional Bonus Top 10 for every Main Pick.
- existing V1.0.x legacy freezes remain immutable: missing Pick #2/#3/... Bonus rankings are shown as unavailable rather than being backfilled with later data.
- Main-Bonus audit now detects duplicate bindings, mismatched stored Main numbers, duplicate Bonus candidates, out-of-range Bonus values, and Bonus-in-Main errors.
- Bonus model/version provenance is stored in the existing `factor_context_json`; no database schema migration or learning reset is required.
- Research forward gates distinguish **SCREENING SIGNAL** (`n>=100`, `z>=1.96`) from the stricter **CONFIRMATION SIGNAL** (`n>=200`, `z>=2.58`). A signal is not presented as proof of a predictive edge.
- English / Chinese / bilingual UI modes are retained; Main/Bonus naming and binding explanations follow the selected language mode.

**Compatibility:** no historical database reset, no existing learning reset, and no rewrite of already frozen Production combinations.


## V1.1 Research Engine

V1.1 keeps the audited V1.0.8 Production/Challenger pipeline unchanged and adds a separate **shadow-only research layer**. Existing frozen Production numbers are never rewritten by the Research Engine.

### Random Control — `RND1.0`

- frozen for the same target date and data cutoff as Production
- uses no historical features
- deterministic pre-draw seed for reproducibility
- uniform random candidate generation followed by a fixed no-signal diversity step; primary paired comparisons use average hits per ticket
- judged after the draw alongside Production/Challenger

### Regime Engine

Lotto Max archive rows are normalized by the legal pool that existed on each draw date:

- `MAX_49`: 2009-09-25 through 2019-05-13
- `MAX_50`: 2019-05-14 through 2026-04-13
- `MAX_52`: 2026-04-14 onward

For each number, eligible draws and expected hits are accumulated using the correct pool size for that draw. This prevents 51/52 from being falsely labelled historically cold simply because they were not legal before the 1-52 regime. Regime deviations remain descriptive research statistics only.

### Crowd Model

V1.1 adds a numeric human-selection proxy based on date-heavy selections, conspicuous consecutive patterns, repeated endings/gaps, and similar hand-picked patterns. The score estimates possible **prize-sharing pressure only**. It never changes the mathematical probability that a legal combination is drawn.

### Research Portfolio Optimizer — `RES1.0`

The shadow Research portfolio combines:

- 70% existing Production model rank
- 20% crowd avoidance proxy
- 10% regime-normalized research score
- an additional overlap penalty to improve portfolio diversity

The resulting portfolio is frozen and judged separately. It has **0% Production weight** and cannot auto-promote.

### Forward scorecard

The Research tab tracks:

- Production vs frozen Random Control
- Production vs Research Portfolio
- paired average-hit deltas
- z-score gates after sufficient forward observations

A historical Random-Control walk-forward test is also included beside the existing walk-forward, shuffled-timeline placebo, and synthetic-null tests.

### How to use after upgrading

Normally, extract V1.6.5 and run `START_LOTTERY_AI.bat`; the existing persistent `lottery.db` is reused. V1.6.5 inherits the V1.6.1 rule that it does **not** fabricate missing historical strategy shadows: if the exact original Production candidate universe is unavailable, that comparator is left missing and recorded as skipped. This preserves evidence integrity across upgrades.

## Quick start on Windows

1. Install current 64-bit Python from python.org (Python 3.11+; Python 3.13 is supported by the dependency set used in V1).
2. Extract this folder anywhere, for example `D:\Lottery_AI_V1.6.5`.
3. Double-click `START_LOTTERY_AI.bat`.
4. On the first run, the launcher creates `.venv` and installs the required Python packages.
5. The app starts with bundled recent seed draws, then automatically attempts historical backfill and current-result refresh.

### Upgrade / data-folder behavior

V1.6.5 retains the deterministic persistent-data precedence introduced in V1.6.1 so a larger stale database cannot override an explicitly selected or local database.

Selection priority is: explicit `LOTTERY_AI_DATA` environment variable -> this build's existing local `data\lottery.db` -> existing stable Windows `D:\Lottery_AI\data\lottery.db` -> discovered legacy Lottery AI data folders. Only the final legacy fallback candidates compete by recency/size. The active path is shown in **Analysis > Data**.

When upgrading, keep the old data folder until V1.6.5 confirms the expected database path and draw count. Existing database content is migrated in place; frozen prediction payloads are not rewritten.

## Main-screen layout

The main page is intentionally vertical and simple:

1. **LOTTO MAX window**
   - latest draw
   - current Production/Challenger/Neural status
   - Top 3 by default; button cycles Top 10 and Top 20
   - hidden `Analysis` panel
2. **LOTTO 6/49 window**
   - same structure
   - includes a hidden **Gold Ball** status/probability page

Complex information stays inside the hidden analysis menus.

## Automatic data update

### Latest result
The newest draw uses a BC-first multi-source failover chain:

1. **WCLC official** (primary for BC)
2. **OLG official static results page** (second official fallback/cross-check)
3. **Loto-Québec official** (best-effort official cross-check; its page may require JavaScript)
4. **Atlantic Lottery** (optional cross-check)
5. historical fallback only if no official current source returns a valid result

The right side of the title bar separates **LATEST** update status from **History** completeness and **Redundancy** health. A backup-site failure no longer makes a successfully updated official WCLC/OLG result look like a failed latest update. Detailed per-source status is shown in **Analysis > Data**.

- LOTTO MAX: `https://www.wclc.com/winning-numbers/lotto-max-extra.htm`
- LOTTO 6/49: `https://www.wclc.com/winning-numbers/lotto-649-extra.htm`

The official parser validates:

- correct count of main numbers
- legal number range
- no duplicate main numbers
- Bonus is legal and not one of the main numbers

### Historical backfill / repair
V1.0.5 treats Lotto 6/49 history more conservatively. For 6/49 the repair chain is:

1. **WCLC LOTTO 6/49 Since Inception** as the canonical historical archive/calendar
2. **Multiple GitHub CSV repositories** as a recovery/cross-check layer
3. **LottoDatabase yearly archive** as an independent historical source
4. **Lotto.net yearly archive** to repair remaining holes and cross-check recent years
5. **WCLC recent-history parser** for recent official data
6. **National-Lottery 6/49 archive** as a last fallback

The Data panel now separates **Coverage** from **Integrity**. `Run Integrity Audit` reports missing scheduled dates, unexpected/off-calendar rows, invalid rows, unresolved conflicts, and the number of rows quarantined from model training. `Repair + Audit Historical Database` performs recovery and then reruns the audit.

The GitHub layer understands several common CSV layouts (`PlayDate/No1...`, `DRAW DATE/NUMBER DRAWN 1...`, `Date/Num1...`, and packed `Numbers` lists). Multiple GitHub repositories are deliberately treated as **one logical recovery source**, so copied/mirrored datasets cannot create artificial consensus. If GitHub repositories disagree on the same draw date, that GitHub date is held out rather than guessed.

Historical Lotto Max rows are validated against the legal pool for their draw date (1-49, then 1-50, then 1-52). Third-party historical rows are not promoted to official-verified status merely because they were downloaded. An existing official-verified draw is protected from being overwritten by an unverified history source.

The **Data** tab now estimates the expected draw calendar, displays history completeness/missing dates, and provides **Repair Historical Database**. It also provides **Import History CSV** as a fail-safe if websites block automated requests. Recognized CSV formats include `Date,Num1...Bonus` and `PlayDate,No1...Bonus`.

### Smart polling
The application checks every 30 minutes internally, but it only calls remote sources when a scheduled draw should exist and is missing locally. This avoids unnecessary requests.

### Offline recovery
If the computer is off for days or weeks, the next startup pulls from before the last known local draw and fills missing draws.

### Data pipeline

`RAW ingest -> validation -> clean SQLite draws -> features -> model -> freeze -> judge -> learning`

Raw provider payloads are preserved in `raw_ingest`; clean validated records live in `draws`.

## Game-era handling

### LOTTO MAX
The first draw under the current rules is **April 14, 2026**:

- 7 main numbers from 1-52
- 1 Bonus number, different from all main numbers
- V1 trains the current LOTTO MAX Production model only on the current 7/52 era

Older 7/50 results may remain in the database for research, but they are excluded from the current-era model.

### LOTTO 6/49

- 6 main numbers from 1-49
- 1 Bonus number
- Gold Ball is not treated as a selectable main-number prediction target

## Production factor system

Default main-model weights:

| Factor | Effective runtime weight |
|---|---:|
| Frequency | 21.18% |
| Gap | 8.24% |
| Structure | 32.94% |
| Pair/Lift | 11.76% |
| Recent | 14.12% |
| Region | 11.76% |
| Monte Carlo Stability | 0% (diagnostic only) |

The score is normalized to a ranking scale. It is **not** displayed as a win probability.

### Bayesian shrinkage
Short-window frequency and recent-trend rates are shrunk toward the fair-draw base rate before ranking. This is designed to reduce false “hot-number” signals from tiny samples.

### Gap logic
Gap/overdue information is deliberately low weight. An overdue number is not assumed to be “due.” Extreme gaps are treated as a noisy descriptive feature rather than proof of increased chance.

### Pair model
Pair counts use expected co-occurrence and shrinkage. Raw pair counts alone cannot dominate the score.

## Probability/Region Engine

V1 contains an **exact combinatorial engine** rather than relying only on simulation.

Verified totals:

- `C(49,6) = 13,983,816`
- `C(52,7) = 133,784,560`

Exact distributions are used for:

- sum
- span
- odd/even count

The Region score combines exact marginal density with a **coarse joint historical region** built from:

- sum bin
- span bin
- odd count
- low/high count
- consecutive-number count

Joint bins are intentionally coarse to reduce overfitting.

## Spacing / structure model

For a sorted combination, V1 studies the spacing vector between adjacent numbers.

Examples of features:

- gap variance
- consecutive count
- low/high balance
- span
- sum

This is more informative structurally than checking only for a single consecutive pair.

## Monte Carlo diagnostic and Coverage Portfolio Optimizer

Monte Carlo Stability remains visible as a diagnostic percentile but has **0% Production/Challenger ranking weight**. It is derived from the Main score and is not allowed to vote a second time.

V1.2.3 uses `COV1.1` after Main scoring; V1.2.2 introduced `COV1.0`. Balanced coverage selects a fixed-size portfolio using Combination Score plus marginal Number/Pair/Triple coverage, coarse structural diversity, and a soft near-duplicate penalty. The optimizer does not alter the underlying Combination Score and Sharing Risk remains advisory-only at 0% prediction weight.

This changes portfolio coverage; it does not change the official probability of any individual legal combination.

## Anti-crowd indicator

Each selected combination is tagged `LOW`, `MEDIUM`, or `HIGH` Crowd Risk using simple proxies such as:

- too many 1-31 birthday-style numbers
- conspicuous consecutive patterns
- repeated final digits

This indicator is **not** part of the official win probability. Its purpose is to flag combinations that may resemble common human choices and therefore could carry more prize-sharing risk if selected by many players.

## Bonus submodel

Main and Bonus are separated.

### Bonus Production defaults

- Bonus frequency: 55%
- Bonus gap: 20%
- recent main-number trend: 25%

For each main selection, the Bonus rank excludes all numbers already present in that main selection.

### Bonus Challenger learning
After an actual Bonus is known, the program recreates the pre-draw information set and adjusts a **Bonus Challenger** with a very small bounded learning rate. It does not contaminate the main-number weights.

## Gold Ball

For 6/49, Gold Ball is displayed separately.

The app does **not** attempt to predict the assigned 10-digit Gold Ball ticket number. When the official page exposes the current prize-ball count, the app shows the simple conditional probability `1 / balls remaining` and current jackpot information.

## Freeze -> Judge -> Learn loop

Before the next scheduled draw, both Production and Challenger predictions are frozen into SQLite with:

- target draw date
- model version
- data cutoff date
- Top predictions
- Bonus ranking

After the new draw is downloaded:

1. each frozen prediction receives main-number hit counts
2. the Bonus rank hit is recorded separately
3. average/best hit statistics are stored
4. expected random overlap is stored as a baseline
5. Challenger factor weights receive a **small bounded update** based on how factor scores correlated with actual hit counts
6. Bonus Challenger learns separately

Production does not change after every draw.

## Production / Challenger / Promotion Gate

V1 maintains:

- **Production**: stable model used on the main page
- **Challenger**: adaptive weight model
- **Number Neural Shadow**: 0% Production weight
- **Region Neural Shadow**: 0% Production weight

If `Auto Promotion (strict gate)` is enabled, Challenger can only replace Production after at least 100 paired evaluations and a positive paired result that passes a basic 95% z-score gate plus the random baseline test.

Auto Promotion is **OFF by default** in V1. Automatic learning still occurs in Challenger.

## Neural Shadows

### Number Neural Shadow
A small regularized MLP estimates a relative score for each possible number using rolling features such as:

- 10/20/50/100-draw occurrence rates
- current gap
- number position
- parity
- low/high region

It uses only past data. V1 assigns it **0% Production weight**.

### Region Neural Shadow
A separate MLP predicts coarse next-draw structure classes:

- sum bin
- span bin
- odd-number count

It also has **0% Production weight**. It exists to test whether structural temporal information survives out-of-sample evaluation.

## Research Lab

The hidden `Research` menu runs three defenses against self-deception:

### 1. Walk-forward test
Only data before each historical target draw is allowed into that prediction.

### 2. Shuffle placebo
Historical draw order is shuffled. If “recent trends” perform just as well after time order is destroyed, there is no convincing temporal edge.

### 3. Synthetic null test
The same model is run on computer-generated fair lottery histories. If it also appears to discover an “edge” there, the apparent real-history edge is likely overfitting/noise.

The Research Lab reports model-vs-random performance rather than an invented “AI accuracy percentage.”

## Files

- `app.py` — Tkinter application and workflow
- `lottery_ai/config.py` — game rules and starting weights
- `lottery_ai/db.py` — SQLite schema/snapshots
- `lottery_ai/providers.py` — official/current + historical providers and validators
- `lottery_ai/analysis.py` — Bayesian statistics, exact probability and region/spacing features
- `lottery_ai/engine.py` — combination scoring and portfolio optimizer
- `lottery_ai/models.py` — neural Shadow models
- `lottery_ai/learning.py` — Freeze/Judge/Challenger learning/Promotion Gate
- `lottery_ai/backtest.py` — walk-forward, shuffle and null tests
- `lottery_ai/updater.py` — automatic backfill, recovery and smart polling
- `data/seed_recent.json` — small startup seed only
- `tests/test_core.py` — core mathematical/parser tests

## Validation performed before packaging

V1 source was compiled with `py_compile` and the included unit suite checks:

- exact 6/49 combination total
- exact 7/52 Lotto Max combination total
- legal/illegal draw validation
- WCLC Lotto Max latest-result parsing fixture
- WCLC 6/49 latest-result parsing fixture
- prediction engine output shape/range

## Limitations of V1

- Bulk historical backfill depends on an external structured data provider. The official newest-result path is independent and remains usable if bulk history is temporarily unavailable.
- Website markup can change. The parser is deliberately fail-closed: bad or incomplete parses are rejected rather than written as valid draws.
- Statistical and neural models can fit noise. That is why Shadow, Random Baseline, walk-forward, shuffle and null tests are integral to the design.
- No legal lottery selection receives a mathematically higher official jackpot probability simply because its Model Score is higher, unless a real non-random draw bias exists and survives rigorous independent validation.



## V1.0.3 official-prediction lock

The old **Regenerate** button has been removed. Each game now uses **Generate Official Prediction**.

- One official Production prediction is allowed per target draw.
- The prediction is written to the persistent SQLite database and remains locked after app restart or version restart.
- Once the target draw is ingested and judged, the next scheduled draw becomes eligible for a new official prediction.
- If the latest database result is stale and the calculated target draw is already in the past, prediction generation is disabled until data is updated.
- Production and Challenger outputs, Bonus ranking, model version and data cutoff are frozen together for fair post-draw judging.
- A fixed deterministic seed tied to the data cutoff is used so the same data/model/algorithm yields the same official candidate set.

## V1.0.3 network resilience

Official-source HTTP requests now use bounded retry/backoff for transient connection resets, timeouts and HTTP 5xx responses. The delays are approximately 2, 5 and 12 seconds, after which normal provider failover applies. A failed request never overwrites a validated database draw.


## V1.0.6 6/49 dataset identity gate

V1.0.6 treats the phrase "6/49" as insufficient proof that a public dataset belongs to Canada's LOTTO 6/49. GitHub recovery sources now pass a calendar-identity gate before their rows can enter the recovery consensus. Off-schedule third-party rows are held out and reported.

The WCLC since-inception endpoint is now parsed directly as an HTML table when possible, making the official archive the preferred historical calendar. If that official calendar is temporarily unavailable, unverified off-calendar 6/49 rows are still quarantined from model use rather than silently influencing predictions.

The integrity audit now reports provenance for unexpected dates and identifies exact-number one-day date-shift duplicates. Quarantine is non-destructive: suspicious database rows remain available for inspection but are excluded from model-ready history.

## V1.0.8 official-calendar and model-clean audit

V1.0.8 distinguishes the normal 6/49 Wednesday/Saturday schedule from the authoritative WCLC historical calendar. Official special draw dates are not automatically treated as contamination merely because they fall on another weekday. If the full WCLC calendar is not yet available, only **official-verified** off-schedule rows are provisionally accepted; unverified rows remain quarantined.

The WCLC since-inception importer now retries alternate official URL forms, prefers layout-aware PDF extraction, and parses ordinary draw rows line-by-line before using the older block parser. The Repair action also retries the official calendar even when the schedule-based audit says there are zero missing draws.

The Data page separates **Raw integrity** from **Model integrity**. This lets the database retain suspicious rows for provenance/audit while ensuring that quarantined records do not enter model-ready history. A clean model set can therefore show `Model data: CLEAN` even while the raw archive remains `WARNING` because retained artifacts are still present.


## V1.2.0 UI and ranking policy

Each game card now contains a **Current Draw / 当期开奖** panel. It follows the BC draw date, waits for an official result, and after the result is stored shows read-only hit diagnostics against the prediction that was frozen before that draw.

**Sharing Risk is advisory only.** It is a human-selection/prize-sharing proxy and contributes **0%** to Main prediction ranking. A high-sharing-risk combination is never removed or demoted merely because other players may choose similar numbers.


## V1.2.1 Model Quality Integrity

- **Monte Carlo is diagnostic-only (0% rank weight).** The percentile is derived from the six-factor Main score, so it is no longer allowed to vote a second time in Combination Score. Legacy databases containing `monte_carlo=0.15` are read through a compatibility normalizer; the six genuine factors are renormalized to 100% without rewriting historical snapshots.
- **Feature Ablation Shadow** runs leave-one-factor-out historical diagnostics with identical candidate pools. Positive removal deltas are investigation flags only, never automatic weight changes.
- **Rank Stability Shadow** measures Top-N ticket retention and number-pool Jaccard stability after one additional historical draw.
- **Official WCLC calendar for both games.** The since-inception archive is now used as the preferred canonical date calendar for LOTTO MAX as well as 6/49, with weekday schedules retained only as fallback.
- Unexpected historical rows are classified as adjacent-date duplicates, verified off-calendar rows, or unverified off-schedule rows; unverified rows remain quarantined from model-ready data.
- Sharing Risk remains advisory-only at 0% prediction weight.

## V1.5.2
- Per-line post-draw learning with pre-draw roles.
- Draw-level aggregation prevents pseudo-replication.
- Efficiency sweet spot and max-deployment plan shown separately.
- Standard budget frontier now includes $100.
- See CHANGELOG_V1.5.2.md.

## V1.5.3 — Marginal Budget & Frontier Hardening

V1.5.3 corrects the Budget AI single-line bias discovered in V1.5.2. A single ticket no longer receives a perfect Diversity score, Rank Retention is treated as a guardrail rather than a reason to buy fewer tickets, and portfolio-size selection is separated from fixed-k subset selection.

Budget AI now reports an exact deployment curve with marginal value per dollar, a structural diminishing-return sweet spot, and a separate maximum-deployment plan under the user's cap. During insufficient forward-sample phases, the sweet spot is explicitly labelled structural and not ROI-validated.

See `CHANGELOG_V1.5.3.md`, `UPGRADE_V1.5.3.md`, and `VALIDATION_V1.5.3.txt`.

## V1.5.4 — Budget Evidence & Oracle Hardening

V1.5.4 fixes four correctness issues in the Adaptive Budget layer without changing Main Combination scoring. The structural knee now uses proper endpoint min-max normalization; budget line counts are compared on the same paired forward-draw cohort; evidence grade uses the actual comparator-bearing sample of the selected line count; and post-draw regret labels use an exact non-monetary subset oracle instead of treating unresolved payout floors as exact money.

The Budget screen also separates the **Efficiency plan** from the **Full-capacity plan** and prints both rank lists. This resolves the confusing case where a $50 LOTTO MAX cap says eight purchases fit but only the three-line structural sweet spot was visible. Exact-k portfolios are independently optimized, so the eight-line plan is not guaranteed to be the three-line plan plus five additional ranks.

See `CHANGELOG_V1.5.4.md`, `UPGRADE_V1.5.4.md`, and `VALIDATION_V1.5.4.txt`.
