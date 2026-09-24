import random

from lottery_ai.backtest import bayesian_strategy_walk_forward
from lottery_ai.bayesian_strategy import (
    BAYESIAN_STRATEGY_VERSION,
    forward_strategy_observations,
    hierarchical_strategy_posterior,
)
from lottery_ai.config import APP_VERSION, GAMES


def _obs(source, n, edge, variant="balanced@5", start=0):
    strategy, lines = variant.split("@")
    return [
        {
            "source": source,
            "game": "649",
            "draw_date": f"D{start+i:04d}",
            "strategy": strategy,
            "lines": int(lines),
            "variant": variant,
            "best_hit_edge": float(edge),
            "coverage_edge": 0.0,
            "wce_edge": 0.0,
        }
        for i in range(n)
    ]


def test_v160_version_and_schema():
    assert APP_VERSION == "V1.6.5"
    assert BAYESIAN_STRATEGY_VERSION == "BAYES1.1"


def test_forward_evidence_can_reach_screening_but_never_promotes():
    result = hierarchical_strategy_posterior(_obs("forward", 40, 1.0), "649")
    item = result["variants"]["balanced@5"]
    assert item["gate"] == "FORWARD_SCREENING"
    assert item["evidence_grade"] == "B"
    assert item["credible_interval_95"]["low"] > 0
    assert result["production_impact"] == 0.0
    assert result["promotion_allowed"] is False


def test_historical_evidence_is_discounted_and_cannot_confirm():
    result = hierarchical_strategy_posterior(_obs("historical", 20, 1.0), "649")
    item = result["variants"]["balanced@5"]
    assert item["historical"]["n"] == 20
    assert item["forward"]["n"] == 0
    assert item["effective_n"] == 9.0
    assert item["gate"] == "HISTORICAL_CANDIDATE"


def test_history_forward_disagreement_is_explicit():
    rows = _obs("historical", 20, 1.0) + _obs("forward", 10, -1.0, start=100)
    item = hierarchical_strategy_posterior(rows, "649")["variants"]["balanced@5"]
    assert item["source_consistency"] == "CONFLICT"
    assert item["gate"] not in {"FORWARD_SCREENING", "FORWARD_CONFIRMATION", "HISTORICAL_CANDIDATE"}


def test_duplicate_variant_draw_does_not_inflate_effective_sample_count():
    row = _obs("forward", 1, 1.0)[0]
    result = hierarchical_strategy_posterior([row, dict(row), dict(row)], "649")
    item = result["variants"]["balanced@5"]
    assert item["forward"]["n"] == 1
    assert item["effective_n"] == 1.0


class _FakeDB:
    def __init__(self):
        self.predictions = [
            {"rank": 1, "numbers": [1, 2, 3, 4, 5, 6], "score": 70},
            {"rank": 2, "numbers": [1, 7, 8, 9, 10, 11], "score": 69},
            {"rank": 3, "numbers": [12, 13, 14, 15, 16, 17], "score": 68},
        ]
        self.data = {
            "P": [{"freeze_id": 10, "record": {
                "draw_date": "2026-09-19",
                "rank_concentration": {"by_k": {"3": {
                    "best_ticket_hit": 3,
                    "cumulative_winner_coverage": 4,
                    "wce": 0.75,
                }}},
            }}],
            "S14SCORE": [], "S14FOCUS": [], "S14PURE": [], "S15CONC": [],
        }

    def champion_learning_records(self, game, prefix="P", limit=300):
        return self.data.get(prefix, [])

    def freeze_by_id(self, freeze_id):
        import json
        return {"id": freeze_id, "predictions_json": json.dumps(self.predictions)}


def test_forward_observations_use_frozen_portfolio_self_null():
    from lottery_ai.null_benchmark import portfolio_null_prefix_expectations
    db = _FakeDB()
    null = portfolio_null_prefix_expectations("649", db.predictions, (3,))[3]
    rows = forward_strategy_observations(db, "649", line_counts=(3,))
    assert len(rows) == 1
    assert rows[0]["variant"] == "balanced@3"
    assert rows[0]["best_hit_edge"] == round(3.0 - null["best_hit"], 8)
    assert rows[0]["coverage_edge"] == round(4.0 - null["coverage"], 8)
    assert rows[0]["null_schema"] == "SELFNULL1.0"


def test_walk_forward_builds_all_requested_strategy_line_variants_without_leakage():
    rng = random.Random(160)
    draws = []
    for i in range(34):
        nums = sorted(rng.sample(range(1, 50), 6))
        bonus = next(n for n in range(1, 50) if n not in nums)
        draws.append({"draw_date": f"D{i:04d}", "numbers": nums, "bonus": bonus})
    result = bayesian_strategy_walk_forward(
        "649", draws, GAMES["649"].default_weights,
        eval_draws=2, candidate_count=60, line_counts=(3, 5), seed=77,
    )
    assert result["status"] == "ok"
    assert result["n_draws"] == 2
    assert len(result["observations"]) == 2 * 5 * 2
    assert all(row["draw_date"] in {"D0032", "D0033"} for row in result["observations"])
    assert {row["variant"] for row in result["observations"]} == {
        f"{mode}@{k}"
        for mode in ("score_only", "balanced", "focused", "pure_coverage", "concentrated")
        for k in (3, 5)
    }
