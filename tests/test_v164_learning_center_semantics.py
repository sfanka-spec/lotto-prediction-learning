from lottery_ai.champion import build_match_diagnostics, classify_rank_association
from lottery_ai.config import APP_VERSION


def _current_portfolio_rows():
    raw = [
        [12,15,25,29,48,49,52],
        [1,11,15,34,35,38,48],
        [4,8,18,35,38,39,43],
        [7,18,22,25,27,38,49],
        [6,13,18,24,41,44,51],
        [1,9,25,36,37,41,49],
        [1,18,23,32,41,45,47],
        [4,15,17,31,32,36,44],
        [3,17,21,26,43,44,49],
        [8,12,20,23,37,51,52],
        [5,13,21,36,39,47,48],
        [4,10,14,31,40,48,49],
        [6,9,22,28,43,48,52],
        [6,24,25,31,35,39,46],
        [10,12,13,16,30,43,50],
        [1,7,10,28,30,39,42],
        [5,11,23,36,40,43,46],
        [2,5,18,31,37,50,52],
        [3,5,12,22,34,39,51],
        [1,19,24,33,37,44,48],
    ]
    scores = [
        76.19,73.85,73.71,72.69,72.31,71.11,70.67,70.49,70.37,70.11,
        70.05,69.93,69.78,69.78,69.65,69.50,69.26,69.25,69.19,69.14,
    ]
    return [
        {"rank": i + 1, "numbers": nums, "score": scores[i], "components": {}}
        for i, nums in enumerate(raw)
    ]


def test_v164_version_and_rank_association_thresholds():
    assert APP_VERSION == "V1.6.6"
    assert classify_rank_association(0.012) == "NEUTRAL"
    assert classify_rank_association(0.10) == "WEAK_POSITIVE"
    assert classify_rank_association(-0.10) == "WEAK_NEGATIVE"
    assert classify_rank_association(0.30) == "POSITIVE"
    assert classify_rank_association(-0.30) == "NEGATIVE"


def test_current_draw_separates_best_hit_placement_from_global_rank_association():
    draw = {
        "draw_date": "2026-09-18",
        "numbers": [6,8,11,14,30,39,41],
        "bonus": 47,
    }
    diag = build_match_diagnostics("max", _current_portfolio_rows(), draw, [])

    assert diag["portfolio_unique_numbers"] == 52
    assert diag["full_pool_coverage"] is True
    assert diag["top_n_coverage"] == 7
    assert diag["best_hit"] == 2
    assert diag["combination_gap"] == 5

    # A strong best-ticket placement must not be presented as proof that the entire
    # score ordering worked when the within-draw Spearman association is ~0.
    assert diag["champion_best_original_rank"] == 3
    assert diag["ranking_diagnosis"] == "WELL_RANKED"
    assert diag["score_hit_spearman"] == 0.012295
    assert diag["stage_diagnosis"]["best_hit_placement"] == "GOOD"
    assert diag["stage_diagnosis"]["global_rank_association"] == "NEUTRAL"
    assert diag["stage_diagnosis"]["ranking"] == "MIXED"
    assert diag["stage_diagnosis"]["number_selection"] == "NON_DIAGNOSTIC"
