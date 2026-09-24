from dataclasses import dataclass, field
from datetime import date

@dataclass(frozen=True)
class GameConfig:
    key: str
    name: str
    pick: int
    max_number: int
    draw_weekdays: tuple[int, ...]  # Monday=0
    era_start: date
    historical_slug: str
    official_url: str
    lines_per_play: int = 1
    play_cost: float = 0.0
    jackpot_cap_million: float | None = None
    default_weights: dict[str, float] = field(default_factory=dict)

# Only genuinely predictive/descriptive feature families are allowed to vote in
# Main Combination ranking. Monte Carlo is a diagnostic percentile derived from
# those same scores, so giving it a second ranking weight would double-count the
# model's own output.
PREDICTIVE_FACTORS = (
    "frequency", "gap", "structure", "pairs", "recent", "region",
)

_BASE_MAIN_WEIGHTS = {
    "frequency": 0.18,
    "gap": 0.07,
    "structure": 0.28,
    "pairs": 0.10,
    "recent": 0.12,
    "region": 0.10,
}


def normalize_main_weights(weights=None) -> dict[str, float]:
    """Return effective Main-model weights with diagnostic factors at 0%.

    Old databases can contain the V1.0-V1.2.0 ``monte_carlo=0.15`` snapshot.
    This compatibility layer preserves the relative six-factor Production model,
    renormalizes it to 100%, and forces Monte Carlo to 0% without rewriting old
    historical snapshots. Explicit zeroes are preserved, which is required by
    feature-ablation research.
    """
    src = dict(weights or {})
    vals = {}
    for k in PREDICTIVE_FACTORS:
        if k in src:
            try:
                vals[k] = max(0.0, float(src[k]))
            except Exception:
                vals[k] = float(_BASE_MAIN_WEIGHTS[k])
        else:
            vals[k] = float(_BASE_MAIN_WEIGHTS[k])
    total = sum(vals.values())
    if total <= 0:
        vals = dict(_BASE_MAIN_WEIGHTS)
        total = sum(vals.values())
    out = {k: vals[k] / total for k in PREDICTIVE_FACTORS}
    out["monte_carlo"] = 0.0  # diagnostic-only, never a prediction vote
    return out


COMMON_WEIGHTS = normalize_main_weights(_BASE_MAIN_WEIGHTS)

BONUS_WEIGHTS = {
    "bonus_frequency": 0.55,
    "bonus_gap": 0.20,
    "recent": 0.25,
}


# Centralized game-era registry. Other modules must reference this table instead of
# hard-coding rule-change dates.
GAME_REGIMES = {
    "max": (
        {"name": "MAX_49", "start": "2009-09-25", "end": "2019-05-13", "max_number": 49},
        {"name": "MAX_50", "start": "2019-05-14", "end": "2026-04-13", "max_number": 50},
        {"name": "MAX_52", "start": "2026-04-14", "end": None, "max_number": 52},
    ),
    "649": (
        {"name": "649_CLASSIC", "start": "1982-06-12", "end": None, "max_number": 49},
    ),
}

# Historical schedule transitions belong here as well so updater/calendar logic has
# one source of truth. These are schedule dates, not predictive-model evidence.
DRAW_SCHEDULES = {
    "max": {"start": "2009-09-25", "twice_weekly_start": "2019-05-14"},
    "649": {"start": "1982-06-12", "twice_weekly_start": "1985-09-11"},
}

GAMES = {
    "max": GameConfig(
        key="max",
        name="LOTTO MAX",
        pick=7,
        max_number=52,
        draw_weekdays=(1, 4),  # Tue / Fri
        era_start=date(2026, 4, 14),
        historical_slug="lotto-max",
        official_url="https://www.wclc.com/winning-numbers/lotto-max-extra.htm",
        lines_per_play=4,
        play_cost=6.0,
        jackpot_cap_million=90.0,
        default_weights=COMMON_WEIGHTS,
    ),
    "649": GameConfig(
        key="649",
        name="LOTTO 6/49",
        pick=6,
        max_number=49,
        draw_weekdays=(2, 5),  # Wed / Sat
        era_start=date(1982, 6, 12),
        historical_slug="lotto-649",
        official_url="https://www.wclc.com/winning-numbers/lotto-649-extra.htm",
        lines_per_play=1,
        play_cost=3.0,
        jackpot_cap_million=68.0,
        default_weights=COMMON_WEIGHTS,
    ),
}

APP_NAME = "Lottery AI"
APP_VERSION = "V1.6.6"
DEFAULT_TOP_N = 20
DEFAULT_CANDIDATES = 12000
AUTO_UPDATE_MINUTES = 30
# Operational guards only. These are centralized application cutoffs, not a claim
# about an officially verified ticket-sales deadline.
PREDICTION_CUTOFF_HOUR = 19
PREDICTION_CUTOFF_MINUTE = 30
RESULT_GRACE_HOUR = 20
MIN_NN_DRAWS = 100
MIN_PROMOTION_EVALS = 100

RANDOM_CONTROL_VERSION = "RND1.0"
RESEARCH_PORTFOLIO_VERSION = "RES1.5"
RESEARCH_PORTFOLIO_SIZE = 20

# V1.4 same-budget strategy shadows. Production remains Balanced; these frozen
# variants are research-only comparators and can never auto-promote directly.
V14_STRATEGY_VERSIONS = {
    "balanced": "S14BAL1.0",
    "score_only": "S14SCORE1.0",
    "focused": "S14FOCUS1.0",
    "pure_coverage": "S14PURE1.0",
    "concentrated": "S15CONC1.0",
}
V14_STRATEGY_PREFIXES = {
    "balanced": "S14BAL",
    "score_only": "S14SCORE",
    "focused": "S14FOCUS",
    "pure_coverage": "S14PURE",
    "concentrated": "S15CONC",
}


# V1.5 Adaptive Budget & Portfolio Learning
PORTFOLIO_POLICY_VERSION = "BUD1.4"
PORTFOLIO_SHADOW_VERSION = "BUDS1.4"
PORTFOLIO_DEFAULT_BUDGETS = (10.0, 20.0, 30.0, 50.0, 100.0)
PORTFOLIO_DATA_COLLECTION_N = 30
PORTFOLIO_PROVISIONAL_N = 50
PORTFOLIO_SCREENING_N = 100
PORTFOLIO_CONFIRMATION_N = 200

# These weights select a subset from the already-frozen Top-20. They do not
# rescore lottery numbers and do not alter Combination Score.
PORTFOLIO_POLICY_WEIGHTS = {
    # V1.5.1 shifts part of the old single-line quality bias into explicit
    # model-core concentration and coverage. These weights still operate only on
    # the already-frozen Top-20 and remain subject to forward validation.
    "quality": 0.24,
    "number_coverage": 0.24,
    "diversity": 0.08,
    "concentration": 0.34,
    "rank_retention": 0.10,
}
