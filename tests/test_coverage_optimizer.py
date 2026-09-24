from itertools import combinations

from lottery_ai.config import GAMES
from lottery_ai.coverage import CoverageOptimizer, coverage_summary, overlap_matrix, COVERAGE_ENGINE_VERSION
from lottery_ai.engine import PredictionEngine


def _row(nums, score):
    return {"numbers": tuple(nums), "score": float(score), "components": {}}


def test_balanced_optimizer_keeps_scores_immutable_and_unique():
    rows = [
        _row((1,2,3,4,5,6), 90),
        _row((1,2,3,4,5,7), 89.9),
        _row((1,2,3,4,6,7), 89.8),
        _row((8,9,10,11,12,13), 88.7),
        _row((14,15,16,17,18,19), 88.5),
        _row((20,21,22,23,24,25), 88.4),
    ]
    original = {tuple(r["numbers"]): r["score"] for r in rows}
    out = CoverageOptimizer("649", "balanced").optimize(rows, top_n=3)
    assert len(out) == 3
    assert len({tuple(r["numbers"]) for r in out}) == 3
    assert tuple(rows[0]["numbers"]) in {tuple(r["numbers"]) for r in out}  # strongest seed stays anchored
    for r in out:
        assert r["score"] == original[tuple(r["numbers"])]
        assert r["coverage_engine"] == COVERAGE_ENGINE_VERSION
        assert r["coverage_mode"] == "balanced"


def test_balanced_coverage_beats_simple_top_score_on_redundant_fixture():
    rows = [
        _row((1,2,3,4,5,6), 95),
        _row((1,2,3,4,5,7), 94.9),
        _row((1,2,3,4,5,8), 94.8),
        _row((9,10,11,12,13,14), 93.9),
        _row((15,16,17,18,19,20), 93.8),
        _row((21,22,23,24,25,26), 93.7),
    ]
    top = CoverageOptimizer("649", "score_only").optimize(rows, top_n=3)
    bal = CoverageOptimizer("649", "balanced").optimize(rows, top_n=3)
    ts = coverage_summary(top, "649")
    bs = coverage_summary(bal, "649")
    assert bs["unique_pairs"] > ts["unique_pairs"]
    assert bs["unique_triples"] > ts["unique_triples"]
    assert bs["coverage_efficiency"] > ts["coverage_efficiency"]


def test_coverage_summary_denominators_are_explicit():
    rows = [_row((1,2,3,4,5,6), 80), _row((7,8,9,10,11,12), 79)]
    s = coverage_summary(rows, "649")
    assert s["pair_slots"] == 2 * len(list(combinations(range(6), 2)))
    assert s["triple_slots"] == 2 * len(list(combinations(range(6), 3)))
    assert s["pair_reuse"] == 0
    assert s["triple_reuse"] == 0
    assert s["lines_per_play"] == 1


def test_lotto_max_line_packaging_metadata():
    assert GAMES["max"].pick == 7
    assert GAMES["max"].max_number == 52
    assert GAMES["max"].lines_per_play == 4
    rows = [_row((1,2,3,4,5,6,7), 80) for _ in range(4)]
    s = coverage_summary(rows, "max")
    # Four displayed model-directed lines require four $6 purchases because only one
    # selection per LOTTO MAX play can be user-directed; the other three are Quick Picks.
    assert s["equivalent_plays"] == 4.0
    assert s["model_directed_purchases"] == 4
    assert s["companion_quick_pick_lines_if_all"] == 12
    assert s["total_physical_lines_if_all"] == 16


def test_overlap_matrix_counts_shared_numbers():
    rows = [_row((1,2,3,4,5,6),80), _row((1,2,7,8,9,10),79), _row((11,12,13,14,15,16),78)]
    m = overlap_matrix(rows)
    assert m[0][1] == 2 and m[1][0] == 2
    assert m[0][2] == 0
    assert m[0][0] == 0


def test_prediction_engine_balanced_metadata_and_score_range():
    draws=[]
    for i in range(1,32):
        nums=sorted({((i+j*7)%49)+1 for j in range(6)})
        while len(nums)<6:
            nums.append(max(nums)+1)
        nums=sorted(nums[:6])
        bonus=next(n for n in range(1,50) if n not in nums)
        draws.append({"draw_date":f"2026-01-{(i-1)%28+1:02d}-{i:02d}","numbers":nums,"bonus":bonus})
    e=PredictionEngine("649",draws,GAMES["649"].default_weights,seed=77)
    rows=e.generate(candidate_count=320,top_n=6,coverage_mode="balanced")
    assert len(rows) == 6
    assert all(r.get("coverage_mode") == "balanced" for r in rows)
    assert all(0 <= r["score"] <= 100 for r in rows)
    assert e.last_portfolio_summary["tickets"] == 6


def test_freeze_provenance_records_coverage_engine(tmp_path):
    import json
    from lottery_ai.db import Database
    from lottery_ai.learning import LearningManager
    db=Database(tmp_path/'cov.db')
    lm=LearningManager(db)
    draws=[{"draw_date":"2026-09-12","numbers":[1,2,3,4,5,6],"bonus":7}]
    preds=[{"rank":1,"numbers":[1,8,9,10,11,12],"score":80.0,"components":{},"coverage_engine":COVERAGE_ENGINE_VERSION,"coverage_mode":"balanced"}]
    bonus={"schema":"per_main_v1","by_pick":[{"main_rank":1,"main_numbers":[1,8,9,10,11,12],"ranking":[[7,60.0]]}]}
    target=lm.freeze_next("649",draws,preds,preds,"P9.9","C9.9",bonus,bonus,app_version="V1.2.2")
    f=db.official_freeze("649",target)
    ctx=json.loads(f["factor_context_json"])
    assert ctx["coverage_engine"] == COVERAGE_ENGINE_VERSION
    assert ctx["coverage_mode"] == "balanced"
    assert ctx["coverage_portfolio_frozen"] is True


def test_incremental_swap_objective_matches_full_rebuild():
    rows = [
        _row((1,2,3,4,5,6), 91.2),
        _row((7,8,9,10,11,12), 88.4),
        _row((13,14,15,16,17,18), 87.9),
        _row((19,20,21,22,23,24), 86.7),
        _row((25,26,27,28,29,30), 85.1),
        _row((1,8,15,22,31,40), 86.1),
    ]
    opt = CoverageOptimizer("649", "balanced")
    current = rows[:5]
    state = opt._build_portfolio_state(current)
    for idx in range(len(current)):
        trial = current[:idx] + [rows[5]] + current[idx + 1:]
        inc = opt._swap_objective(state, idx, rows[5])
        full = opt._portfolio_objective(trial)
        assert abs(inc - full) < 1e-12
