from __future__ import annotations

from pathlib import Path

from lottery_ai.champion import build_match_diagnostics
from lottery_ai.config import COMMON_WEIGHTS, GAMES
from lottery_ai.coverage import CoverageOptimizer, coverage_summary
from lottery_ai.db import Database
from lottery_ai.engine import PredictionEngine
from lottery_ai.jackpot import crowd_pressure_proxy, jackpot_economics
from lottery_ai.portfolio import (
    PortfolioOptimizer,
    budget_frontier_learning,
    evaluate_portfolio_choice,
    learn_shadow_policy,
    portfolio_validation_summary,
    resolved_ticket_payout,
)


def _rows():
    return [
        {"rank": 1, "numbers": [1, 2, 3, 4, 5, 6], "score": 80.0, "components": {}},
        {"rank": 2, "numbers": [1, 7, 8, 9, 10, 11], "score": 79.0, "components": {}},
        {"rank": 3, "numbers": [2, 12, 13, 14, 15, 16], "score": 78.0, "components": {}},
        {"rank": 4, "numbers": [3, 17, 18, 19, 20, 21], "score": 77.0, "components": {}},
        {"rank": 5, "numbers": [4, 22, 23, 24, 25, 26], "score": 76.0, "components": {}},
        {"rank": 6, "numbers": [5, 27, 28, 29, 30, 31], "score": 75.0, "components": {}},
    ]


def test_champion_reports_winner_concentration_efficiency():
    draw = {"draw_date": "2026-09-12", "numbers": [1, 2, 3, 17, 28, 40], "bonus": 7}
    diag = build_match_diagnostics("649", _rows(), draw, [])
    assert diag["top_n_coverage"] == 5
    assert diag["best_hit"] == 3
    assert diag["winner_dispersion_loss"] == 2
    assert diag["winner_concentration_efficiency"] == 0.6


def test_lotto_max_model_lines_require_one_purchase_each():
    rows = [{"numbers": [1,2,3,4,5,6,7], "score": 80.0, "components": {}} for _ in range(4)]
    s = coverage_summary(rows, "max")
    assert s["model_directed_purchases"] == 4
    assert s["model_directed_cost_if_all"] == 24.0
    assert s["companion_quick_pick_lines_if_all"] == 12
    assert s["total_physical_lines_if_all"] == 16


def test_gold_ball_ball_count_does_not_fake_crowd_pressure():
    a = crowd_pressure_proxy("649", {"gold_ball_jackpot_million": 30.0, "jackpot_cap_million": 68.0, "gold_balls_remaining": 29})
    b = crowd_pressure_proxy("649", {"gold_ball_jackpot_million": 30.0, "jackpot_cap_million": 68.0, "gold_balls_remaining": 2})
    assert a["score"] == b["score"]
    ea = jackpot_economics("649", {"gold_ball_jackpot_million": 30.0, "jackpot_cap_million": 68.0, "gold_balls_remaining": 29})
    eb = jackpot_economics("649", {"gold_ball_jackpot_million": 30.0, "jackpot_cap_million": 68.0, "gold_balls_remaining": 2})
    assert eb["gold_ball_conditional_value_score"] > ea["gold_ball_conditional_value_score"]


def test_jackpot_history_dedupes_same_economic_state(tmp_path: Path):
    db = Database(tmp_path / "dedupe.db")
    one = {"game":"649","observed_at":"2026-09-13T10:00:00Z","source":"official","source_url":"u",
           "gold_ball_jackpot_million":30.0,"gold_balls_remaining":20,"classic_jackpot_million":5.0,"jackpot_cap_million":68.0}
    two = dict(one, observed_at="2026-09-13T10:30:00Z")
    assert db.save_jackpot_snapshot("649", one) is True
    assert db.save_jackpot_snapshot("649", two) is False
    assert len(db.jackpot_history("649")) == 1
    assert db.latest_jackpot_snapshot("649")["observed_at"] == "2026-09-13T10:30:00Z"


def test_official_prize_breakdown_can_resolve_pool_tier():
    draw = {"draw_date":"2026-09-09","numbers":[14,18,27,35,41,47],"bonus":17,
            "prize_breakdown":{"4/6":100.9}}
    t = {"numbers":[14,18,27,35,1,2]}
    r = resolved_ticket_payout("649", t, draw)
    assert r["hits"] == 4
    assert r["fully_resolved"] is True
    assert r["payout_known"] == 100.9
    assert r["payout_source"] == "OFFICIAL_PRIZE_BREAKDOWN"


def test_random_control_tracks_best_hit_coverage_and_wce():
    draw = {"draw_date":"2026-09-12","numbers":[1,2,3,17,28,40],"bonus":7}
    choice = {"selected_ranks":[1,4], "lines":2, "cost":6.0}
    out = evaluate_portfolio_choice("649", _rows(), choice, draw)
    assert out["random_same_budget_best_hit"] is not None
    assert out["random_same_budget_coverage"] is not None
    assert out["random_same_budget_wce"] is not None
    assert out["random_control_method"] == "EXACT_ENUMERATION"


def test_shadow_learning_effective_n_excludes_incomplete_records():
    rows = _rows()
    prod = PortfolioOptimizer("649").frontier(rows)
    choice = prod["auto"]
    complete = {
        "id": 2, "game":"649", "draw_date":"2026-09-12",
        "decision":{"game":"649","frozen_rows":rows,"production_frontier":prod},
        "judgment":{"production_auto":{"lines":choice["lines"],"oracle_same_budget_ranks":choice["selected_ranks"],
                                        "avg_hit_regret":0.0,"best_hit_regret":0,"coverage_regret":0,"payout_regret_floor":0}},
    }
    incomplete = {"id": 1, "game":"649", "draw_date":"2026-09-09", "decision":{}, "judgment":{}}
    got = learn_shadow_policy([incomplete, complete])
    assert got["stored_records"] == 2
    assert got["n"] == 1


def test_portfolio_validation_pairs_same_draw_same_k():
    rec = {
        "id": 1, "draw_date":"2026-09-12", "decision":{},
        "judgment":{
            "production_auto":{"lines":2},
            "by_lines":{"2":{"lines":2,"avg_hit":1.0,"best_hit":2,"winner_concentration_efficiency":0.5,
                               "roi_floor":-0.5,"roi_known":-0.5,"random_same_budget_best_hit":1.8}},
            "shadow_by_lines":{"2":{"lines":2,"avg_hit":1.2,"best_hit":3,"winner_concentration_efficiency":0.75}},
            "shadow_auto":{"lines":5,"avg_hit":9.9},
        },
    }
    got = portfolio_validation_summary([rec])
    assert got["n"] == 1
    assert got["comparison"].startswith("same draw")
    assert got["shadow_avg_hit"] == 1.2
    assert got["shadow_minus_production_best_hit"] == 1.0


def test_budget_learning_dedupes_two_versions_of_same_draw():
    def rec(i, version):
        ev={"lines":1,"cost":3.0,"roi_floor":-1.0,"roi_known":-1.0,"payout_floor":0.0,"any_prize":False,
            "best_hit":1,"avg_hit":0.8,"winning_number_coverage":1,"winner_concentration_efficiency":1.0,
            "random_same_budget_avg_hit":0.7,"random_same_budget_best_hit":0.9,"random_same_budget_coverage":0.9,
            "random_same_budget_wce":0.9,"random_same_budget_payout_floor":0.0,"unresolved_parimutuel_or_jackpot_tickets":0}
        return {"id":i,"game":"649","draw_date":"2026-09-12","model_version":version,"judgment":{"by_lines":{"1":ev}}}
    got=budget_frontier_learning([rec(1,"BUD1.0"),rec(2,"BUD1.1")],"649")
    assert got["n"] == 1
    assert got["by_lines"]["1"]["n"] == 1


def test_unresolved_roi_floor_is_not_used_as_budget_objective():
    records=[]
    for d in range(60):
        by={}
        for k in (1,2):
            by[str(k)]={
                "lines":k,"cost":3*k,"roi_floor":0.5 if k==1 else -0.9,"roi_known":None,"payout_floor":0.0,
                "any_prize":True,"best_hit":2 if k==1 else 3,"avg_hit":1.0 if k==1 else 1.3,
                "winning_number_coverage":2 if k==1 else 4,"winner_concentration_efficiency":1.0 if k==1 else 0.75,
                "random_same_budget_avg_hit":1.0,"random_same_budget_best_hit":2.0,"random_same_budget_coverage":2.0,
                "random_same_budget_wce":0.7,"random_same_budget_payout_floor":0.0,
                "unresolved_parimutuel_or_jackpot_tickets":1,
            }
        records.append({"id":d+1,"game":"649","draw_date":f"2026-01-{d+1:02d}","judgment":{"by_lines":by}})
    got=budget_frontier_learning(records,"649")
    assert got["monetary_comparable"] is False
    assert got["budget_selection_objective"] == "SELECTION_EFFICIENCY_UNTIL_EXACT_PAYOUTS"
    assert got["research_best_lines"] == 2


def test_concentrated_strategy_is_research_only_and_more_overlap_tolerant():
    # A redundant high-score cluster plus diverse alternatives.
    rows=[
        {"numbers":(1,2,3,4,5,6),"score":95.0,"components":{}},
        {"numbers":(1,2,3,4,5,7),"score":94.9,"components":{}},
        {"numbers":(1,2,3,4,6,7),"score":94.8,"components":{}},
        {"numbers":(8,9,10,11,12,13),"score":93.0,"components":{}},
        {"numbers":(14,15,16,17,18,19),"score":92.9,"components":{}},
        {"numbers":(20,21,22,23,24,25),"score":92.8,"components":{}},
    ]
    bal=CoverageOptimizer("649","balanced").optimize(rows,3)
    con=CoverageOptimizer("649","concentrated").optimize(rows,3)
    def avg_overlap(xs):
        sets=[set(r["numbers"]) for r in xs]
        vals=[len(sets[i]&sets[j]) for i in range(len(sets)) for j in range(i+1,len(sets))]
        return sum(vals)/len(vals)
    assert avg_overlap(con) >= avg_overlap(bal)
    assert all(r["coverage_mode"] == "concentrated" for r in con)


def test_structural_frontier_no_longer_forced_monotonic_by_cumulative_mass():
    fr=PortfolioOptimizer("649").frontier(_rows())
    vals=[fr["frontier"][str(k)]["policy_value"] for k in range(1,7)]
    assert not all(b >= a for a,b in zip(vals, vals[1:]))
    assert fr["schema"] == "PORTFOLIO_FRONTIER1.3"


def test_model_line_roi_is_not_mislabeled_as_exact_purchase_roi():
    from lottery_ai.portfolio import evaluate_portfolio_choice
    rows=[{"rank":1,"numbers":[1,2,3,4,5,6],"score":80.0}]
    draw={"draw_date":"2026-09-12","numbers":[1,2,3,10,11,12],"bonus":7}
    out=evaluate_portfolio_choice("649",rows,{"selected_ranks":[1]},draw)
    assert out["model_directed_payout_status"] == "EXACT"
    assert out["model_directed_roi_known"] is not None
    assert out["package_payout_status"] == "NOT_AVAILABLE"
    assert out["package_roi_known"] is None


def test_exact_package_roi_requires_explicit_terminal_receipt_payout():
    from lottery_ai.portfolio import evaluate_portfolio_choice
    rows=[{"rank":1,"numbers":[1,2,3,4,5,6,7],"score":80.0}]
    draw={
        "draw_date":"2026-09-15","numbers":[1,2,3,20,21,22,23],"bonus":24,
        # Total physical $6 purchase payout, including the chosen line and its three
        # terminal Quick Picks / secondary entries, imported from terminal/receipt data.
        "package_payout_by_rank":{"1":26.0},
    }
    out=evaluate_portfolio_choice("max",rows,{"selected_ranks":[1]},draw)
    assert out["cost"] == 6.0
    assert out["package_payout_status"] == "EXACT"
    assert out["package_payout_known"] == 26.0
    assert out["package_roi_known"] == round((26.0-6.0)/6.0,6)
