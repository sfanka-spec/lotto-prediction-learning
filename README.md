# Lottery AI V1.6.6

Research-oriented statistical analysis and prediction-learning software for **LOTTO 6/49** and **LOTTO MAX**.

> **Educational and research use only.** Combination scores, rankings, simulations, and model outputs do **not** represent guaranteed winning probabilities.

## Current release

**V1.6.6 — Public Release Hardening**

Highlights include:

- safer public-sharing defaults and documentation;
- explicit separation between source code and local runtime databases;
- GitHub Actions CI for automated tests on pushes and pull requests;
- public data-handling and privacy guidance;
- a public-release checklist covering secrets, data, licensing, and reproducibility;
- all V1.6.5 statistical/runtime correctness hardening retained.

For detailed version history, see:

- `CHANGELOG_V1.6.6.md`
- `UPGRADE_V1.6.6.md`
- `CHANGELOG_V1.6.5.md`
- `VALIDATION_V1.6.5.txt`

Older release notes are preserved in the other `CHANGELOG_*.md` and `UPGRADE_*.md` files.

## Main features

- LOTTO 6/49 and LOTTO MAX support
- Historical draw ingestion and validation
- Production / Challenger model workflow
- Random Control baseline
- Neural Shadow models
- Freeze -> Judge -> Learn workflow
- Candidate and portfolio analysis
- Combination concentration diagnostics
- Cumulative Winning Coverage (CWC)
- Budget / portfolio research tools
- Data integrity auditing
- Multi-source result recovery
- Research diagnostics for overfitting and model stability

## Installation guide

### 1. Install Python

Install a recent **64-bit Python 3** release for Windows.

During installation, enable:

```text
Add Python to PATH
```

Verify installation in PowerShell:

```powershell
python --version
pip --version
```

If `python` is not recognized, close and reopen PowerShell after installation.

### 2. Get the project

You can clone the GitHub repository:

```powershell
git clone https://github.com/sfanka-spec/lotto-prediction-learning.git
cd lotto-prediction-learning
```

or download the source ZIP from the GitHub Release page and extract it.

### 3. Create a virtual environment

From the project folder:

```powershell
python -m venv .venv
```

Activate it:

```powershell
.\.venv\Scripts\Activate.ps1
```

If PowerShell blocks activation, you can temporarily allow the script for the current window:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

### 4. Install application dependencies

```powershell
python -m pip install --upgrade pip
pip install -r requirements.txt
```

The runtime requirements currently include:

- requests
- beautifulsoup4
- numpy
- scikit-learn
- tzdata
- pypdf

### 5. Run Lottery AI

From the repository root:

```powershell
python app.py
```

The desktop interface should open.

### 6. Optional: install test dependencies

For development and validation:

```powershell
pip install -r requirements-dev.txt
```

Then run:

```powershell
pytest
```

## Updating your local copy

If you cloned with Git and want the newest version:

```powershell
git pull origin main
```

Then update dependencies if needed:

```powershell
pip install -r requirements.txt
```

## Project structure

```text
lotto-prediction-learning/
├─ app.py
├─ lottery_ai/
├─ tests/
├─ data/
├─ requirements.txt
├─ requirements-dev.txt
├─ README.md
├─ README_CN.md
├─ PUBLIC_RELEASE_CHECKLIST.md
├─ CHANGELOG_*.md
└─ UPGRADE_*.md
```

Key modules include:

- `lottery_ai/config.py` — game configuration and model settings
- `lottery_ai/db.py` — database and snapshot handling
- `lottery_ai/providers.py` — result/history providers and validation
- `lottery_ai/analysis.py` — statistical and structural analysis
- `lottery_ai/engine.py` — combination scoring and portfolio logic
- `lottery_ai/models.py` — Shadow models
- `lottery_ai/learning.py` — freeze/judge/learning workflow
- `lottery_ai/backtest.py` — walk-forward and research tests
- `lottery_ai/updater.py` — data refresh and recovery

## First run and local database

A fresh user does **not** need the developer's personal `lottery.db`.

On first use, Lottery AI creates its SQLite schema locally. The user can then populate history through the built-in update/repair workflow or import an approved CSV dataset.

The repository intentionally excludes real runtime databases, learning state, logs, model snapshot binaries, credentials, and local caches. See `data/README.md` and `PUBLIC_RELEASE_CHECKLIST.md`.

## Data and model behavior

The application is designed around a conservative research workflow:

```text
Raw ingest
   -> validation
   -> clean draw data
   -> features
   -> model
   -> frozen prediction
   -> official result
   -> evaluation
   -> learning
```

Historical anomalies can be retained for audit while being excluded from model-ready data.

## Research safeguards

The project includes controls intended to reduce misleading conclusions:

- Random Baseline comparisons
- Shadow-only experimental models
- walk-forward testing
- shuffle placebo testing
- synthetic-null testing
- frozen pre-draw predictions
- post-draw evaluation without rewriting historical predictions
- explicit distinction between portfolio coverage and single-ticket concentration

## Important interpretation note

A higher model score means the software ranks that combination more highly under its research model.

It does **not** mean that a legal lottery combination has a mathematically guaranteed higher official jackpot probability.

Lottery results should be treated as random unless a real non-random effect survives rigorous independent validation.

## Troubleshooting

### `python` is not recognized

Reinstall Python and enable **Add Python to PATH**, then reopen PowerShell.

### Virtual environment will not activate

Run:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

and activate again:

```powershell
.\.venv\Scripts\Activate.ps1
```

### Dependencies fail to install

Upgrade pip first:

```powershell
python -m pip install --upgrade pip
```

Then retry:

```powershell
pip install -r requirements.txt
```

### Application opens but data cannot update

Check internet access first. The application uses multiple data sources and is designed to fail closed rather than write invalid draw data.

## Development

Before committing a new release, run:

```powershell
pytest
```

Keep generated caches, local databases, credentials, logs, and environment files out of Git. The repository `.gitignore` is configured for this purpose.

## License

This project is licensed under the [MIT License](LICENSE).

You may use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the software, subject to the terms of the MIT License.

## Disclaimer

This software is for statistical research and educational use. It does not guarantee prizes, profit, or predictive advantage, and it should not be interpreted as gambling or financial advice.
