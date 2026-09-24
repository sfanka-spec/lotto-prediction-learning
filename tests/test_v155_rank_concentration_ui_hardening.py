from datetime import date

from lottery_ai.champion import build_match_diagnostics
from lottery_ai.config import APP_VERSION
from lottery_ai.coverage import candidate_number_profile
from lottery_ai.db import Database
from lottery_ai.engine import PredictionEngine
from lottery_ai.presentation import build_current_draw_snapshot


def _rows_from_user_example():
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
    scores = [76.19,73.85,73.71,72.69,72.31,71.11,70.67,70.49,70.37,70.11,
              70.05,69.93,69.78,69.78,69.65,69.50,69.26,69.25,69.19,69.14]
    return [{"rank": i+1, "numbers": nums, "score": scores[i], "components": {}} for i, nums in enumerate(raw)]


def _profile_with_five_winners_front_loaded():
    first = [23,38,40,44,49,1,3,4,5,6,7,8,9,10,11,12,13,14,15,16]
    rest = [n for n in range(1,53) if n not in first]
    ranked = first + rest
    return [{"rank": i+1, "number": n, "support": float(100-i)} for i,n in enumerate(ranked)]


def test_v155_version():
    assert APP_VERSION == "V1.6.5"


def test_user_example_distinguishes_full_portfolio_coverage_from_rank_concentration():
    draw = {"draw_date":"2026-09-15", "numbers":[2,23,30,38,40,44,49], "bonus":18}
    diag = build_match_diagnostics("max", _rows_from_user_example(), draw, [])
    assert diag["ticket_slots"] == 140
    assert diag["portfolio_unique_numbers"] == 52
    assert diag["top_n_coverage"] == 7
    assert diag["selection_miss"] == 0
    assert diag["combination_gap"] == 5
    assert abs(diag["winner_concentration_efficiency"] - 2/7) < 1e-6
    rc = diag["rank_concentration"]["by_k"]
    assert rc["3"]["cumulative_winner_coverage"] == 2
    assert rc["5"]["cumulative_winner_coverage"] == 3
    assert rc["10"]["cumulative_winner_coverage"] == 4
    assert rc["20"]["cumulative_winner_coverage"] == 7
    assert rc["3"]["best_ticket_hit"] == 1
    assert rc["5"]["best_ticket_hit"] == 2
    assert rc["10"]["best_ticket_hit"] == 2
    assert rc["20"]["best_ticket_hit"] == 2


def test_candidate_number_rank_is_independent_from_ticket_union():
    draw = {"draw_date":"2026-09-15", "numbers":[2,23,30,38,40,44,49], "bonus":18}
    diag = build_match_diagnostics(
        "max", _rows_from_user_example(), draw, [],
        candidate_number_profile=_profile_with_five_winners_front_loaded(),
    )
    cand = diag["candidate_number_ranking"]
    assert cand["available"] is True
    assert cand["by_k"]["10"]["winner_coverage"] == 5
    assert cand["by_k"]["15"]["winner_coverage"] == 5
    assert cand["by_k"]["20"]["winner_coverage"] == 5
    # Portfolio still covers all seven, proving these are separate diagnostics.
    assert diag["top_n_coverage"] == 7


def test_snapshot_reads_frozen_candidate_number_profile(tmp_path):
    db = Database(tmp_path / "lottery.db")
    draw = {"draw_date":"2026-09-15", "numbers":[2,23,30,38,40,44,49], "bonus":18}
    db.upsert_draw("max", draw["draw_date"], "MAX_52", draw["numbers"], draw["bonus"], "test", verified=True)
    rows = _rows_from_user_example()
    profile = _profile_with_five_winners_front_loaded()
    db.save_freeze("max", draw["draw_date"], "P1.0", "2026-09-12", rows, [], {"candidate_number_profile": profile})
    snap = build_current_draw_snapshot(db, "max", today=date(2026,9,15))
    assert snap["portfolio_unique_numbers"] == 52
    assert snap["top_n_coverage"] == 7
    assert snap["rank_concentration"]["by_k"]["10"]["cumulative_winner_coverage"] == 4
    assert snap["candidate_number_ranking"]["by_k"]["10"]["winner_coverage"] == 5
    assert snap["snapshot_consistency"] == "OK"


def test_candidate_number_profile_is_complete_and_deterministic():
    rows = [
        {"score": 80.0, "numbers": [1,2,3,4,5,6]},
        {"score": 79.0, "numbers": [1,2,7,8,9,10]},
        {"score": 78.0, "numbers": [1,11,12,13,14,15]},
    ]
    a = candidate_number_profile(rows, 49)
    b = candidate_number_profile(rows, 49)
    assert a == b
    assert len(a) == 49
    assert sorted(x["number"] for x in a) == list(range(1,50))
    assert a[0]["number"] == 1
