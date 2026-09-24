from __future__ import annotations

from pathlib import Path

from lottery_ai.db import Database
from lottery_ai.updater import DataUpdater
from lottery_ai.jackpot import parse_wclc_jackpot_widgets, jackpot_economics
from lottery_ai.portfolio import (
    PortfolioOptimizer, fixed_tier_payout_floor, judge_frontier,
    learn_shadow_policy, portfolio_validation_summary, budget_frontier_learning,
)


def _rows649():
    return [
        {"rank":1,"numbers":[1,2,3,4,5,6],"score":80.0,"components":{"structure":80}},
        {"rank":2,"numbers":[1,7,8,9,10,11],"score":79.0,"components":{"structure":78}},
        {"rank":3,"numbers":[2,12,13,14,15,16],"score":78.0,"components":{"structure":77}},
        {"rank":4,"numbers":[3,17,18,19,20,21],"score":77.0,"components":{"structure":76}},
        {"rank":5,"numbers":[4,22,23,24,25,26],"score":76.0,"components":{"structure":75}},
        {"rank":6,"numbers":[5,27,28,29,30,31],"score":75.0,"components":{"structure":74}},
    ]


def test_wclc_widget_parser_keeps_games_separate():
    text = (
        "GOLD BALL JACKPOT $ 30 Million or Guaranteed $1 Million "
        "20 Balls Remaining Exact Match Only Wednesday, September 16, 2026 "
        "$ 40 Million 40 x $100,000 Tuesday, September 15, 2026"
    )
    got=parse_wclc_jackpot_widgets(text)
    assert got["649"]["gold_ball_jackpot_million"] == 30.0
    assert got["649"]["gold_balls_remaining"] == 20
    assert got["max"]["jackpot_million"] == 40.0
    assert got["max"]["maxplus_100k_count"] == 40


def test_gold_ball_economics_does_not_invent_sales_odds():
    e=jackpot_economics("649",{
        "gold_ball_jackpot_million":30.0,"gold_balls_remaining":20,
        "classic_jackpot_million":5.0,"jackpot_cap_million":68.0,
    })
    assert e["conditional_gold_ball_probability"] == 0.05
    assert "number of issued selections" in e["note"]
    assert "per_play_gold_ball_probability" not in e


def test_exact_frontier_uses_only_frozen_lines_and_respects_budget():
    rows=_rows649()
    opt=PortfolioOptimizer("649")
    frontier=opt.frontier(rows)
    assert frontier["search_space"] == 2**len(rows)-1
    frozen={tuple(r["numbers"]) for r in rows}
    for item in frontier["frontier"].values():
        assert all(tuple(x) in frozen for x in item["selected_numbers"])
    choice=opt.for_budget(frontier,10)
    assert choice["cost"] <= 10
    assert choice["lines"] <= 3  # $3 each
    assert choice["unused"] >= 0


def test_fixed_tier_roi_floor_is_conservative():
    draw={"draw_date":"2026-09-16","numbers":[1,2,3,20,30,40],"bonus":7}
    p=fixed_tier_payout_floor("649",{"numbers":[1,2,3,8,9,10]},draw)
    assert p["hits"] == 3 and p["payout_floor"] == 10.0 and p["fully_resolved"]
    unresolved=fixed_tier_payout_floor("649",{"numbers":[1,2,3,20,30,9]},draw)
    assert unresolved["hits"] == 5 and unresolved["payout_floor"] == 0.0
    assert not unresolved["fully_resolved"]


def test_lotto_max_4_plus_bonus_is_not_mislabeled_as_fixed_20():
    draw={"draw_date":"2026-09-15","numbers":[1,2,3,4,20,30,40],"bonus":7}
    r=fixed_tier_payout_floor("max",{"numbers":[1,2,3,4,7,50,51]},draw)
    assert r["hits"] == 4 and r["bonus_hit"]
    assert r["tier"] == "4/7+BONUS"
    assert r["payout_floor"] == 0.0 and not r["fully_resolved"]


def test_decision_memory_judges_once_per_draw_not_per_subset(tmp_path: Path):
    db=Database(tmp_path/"v15.db")
    rows=_rows649()
    prod=PortfolioOptimizer("649").frontier(rows)
    shadow=PortfolioOptimizer("649",{"quality":.4,"number_coverage":.3,"diversity":.1,"concentration":.1,"rank_retention":.1}).frontier(rows)
    decision={
        "schema":"BUDGET_PORTFOLIO1.0","game":"649","target_draw_date":"2026-09-16",
        "frozen_rows":rows,"production_frontier":prod,"shadow_frontier":shadow,
    }
    rec=db.save_portfolio_decision("649","2026-09-16","BUD1.0",decision)
    draw={"draw_date":"2026-09-16","numbers":[1,2,3,17,29,40],"bonus":7}
    judgment=judge_frontier("649",rows,decision,draw)
    db.save_portfolio_judgment(rec["id"],"649","2026-09-16","BUD1.0",judgment)
    records=db.portfolio_learning_records("649")
    assert len(records) == 1
    learned=learn_shadow_policy(records)
    assert learned["n"] == 1
    assert learned["production_impact"] == 0.0
    val=portfolio_validation_summary(records)
    assert val["n"] == 1


def test_post_draw_oracle_is_label_only_and_does_not_mutate_choice():
    rows=_rows649()
    opt=PortfolioOptimizer("649")
    frontier=opt.frontier(rows)
    choice=dict(frontier["frontier"]["2"])
    before=list(choice["selected_ranks"])
    draw={"draw_date":"2026-09-16","numbers":[17,18,19,27,28,29],"bonus":40}
    decision={"production_frontier":frontier,"shadow_frontier":frontier}
    out=judge_frontier("649",rows,decision,draw)
    assert frontier["frontier"]["2"]["selected_ranks"] == before
    assert "oracle_same_budget_ranks" in out["by_lines"]["2"]



def _learning_record(k1_roi=-0.5, k2_roi=-0.4, hit_edge=0.1, payout_edge=1.0):
    def ev(k, roi):
        cost=3.0*k
        payout=cost*(1.0+roi)
        return {
            "lines":k,"cost":cost,"roi_floor":roi,"payout_floor":payout,
            "any_prize":payout>0,"best_hit":2 if k==1 else 3,"avg_hit":1.2 if k==1 else 1.3,
            "winning_number_coverage":3 if k==1 else 4,
            "random_same_budget_avg_hit":(1.2 if k==1 else 1.3)-hit_edge,
            "random_same_budget_payout_floor":payout-payout_edge,
            "unresolved_parimutuel_or_jackpot_tickets":0,
        }
    return {"judgment":{"by_lines":{"1":ev(1,k1_roi),"2":ev(2,k2_roi)}}}


def test_budget_learning_uses_draw_count_and_does_not_treat_model_line_roi_as_package_roi():
    records=[_learning_record() for _ in range(60)]
    got=budget_frontier_learning(records,"649")
    assert got["n"] == 60
    # Legacy fixture has no exact retail-package payout. V1.5.1 must therefore
    # choose by same-budget selection efficiency, not the apparently better Main-line ROI.
    assert got["research_best_lines"] == 1
    assert got["selection_evidence_grade"] == "C"
    assert got["selection_supported"] is False
    assert got["auto_spend_research_ceiling"] == 0.0
    assert got["by_lines"]["2"]["n"] == 60
    assert "ROI floor" in got["note"]


def test_budget_learning_can_reach_screening_selection_evidence_without_claiming_profit():
    records=[_learning_record(k1_roi=-0.6,k2_roi=-0.5,hit_edge=0.2,payout_edge=1.0) for _ in range(120)]
    got=budget_frontier_learning(records,"649")
    assert got["n"] == 120
    assert got["selection_evidence_grade"] == "B"
    assert got["selection_supported"] is True
    assert got["research_best_roi_floor"] < 0  # support is about selector edge, not guaranteed profit


def test_failed_jackpot_refresh_marks_cached_snapshot_stale(tmp_path: Path):
    db=Database(tmp_path/"stale.db")
    db.save_jackpot_snapshot("649",{
        "game":"649","observed_at":"2026-09-13T20:00:00Z","source":"official",
        "gold_ball_jackpot_million":28.0,"gold_balls_remaining":21,
        "classic_jackpot_million":5.0,"jackpot_cap_million":68.0,"status":"CURRENT",
    })
    up=DataUpdater(db)
    class Broken:
        def latest(self, game):
            raise RuntimeError("network down")
    up.jackpot=Broken()
    out=up.update_jackpot("649")
    assert out["status"] == "STALE"
    assert out["snapshot"]["status"] == "STALE"
    refresh=db.get_state("jackpot_refresh_649",{})
    assert refresh["status"] == "STALE"
