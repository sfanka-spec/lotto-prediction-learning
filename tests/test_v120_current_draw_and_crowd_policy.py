import json
from datetime import date
from unittest.mock import patch

from lottery_ai.bonus import build_bonus_payload
from lottery_ai.config import GAMES
from lottery_ai.db import Database
from lottery_ai.engine import PredictionEngine
from lottery_ai.presentation import build_current_draw_snapshot, format_bc_timestamp
from lottery_ai.research_engine import ResearchPortfolioOptimizer


def _draws_649(n=35):
    rows=[]
    for i in range(n):
        nums=sorted({((i*3+j*7)%49)+1 for j in range(6)})
        while len(nums)<6:
            candidate=(max(nums)+2) if nums else 1
            if candidate>49: candidate=((candidate-1)%49)+1
            if candidate not in nums: nums.append(candidate)
        nums=sorted(nums[:6])
        bonus=next(x for x in range(1,50) if x not in nums)
        rows.append({"draw_date":f"2026-08-{(i%28)+1:02d}","numbers":nums,"bonus":bonus})
    return rows


def test_production_prediction_is_independent_of_crowd_label():
    draws=_draws_649()
    with patch("lottery_ai.engine.crowd_risk", lambda combo: "HIGH"):
        a=PredictionEngine("649",draws,GAMES["649"].default_weights,seed=123).generate(candidate_count=350,top_n=8)
    with patch("lottery_ai.engine.crowd_risk", lambda combo: "LOW"):
        b=PredictionEngine("649",draws,GAMES["649"].default_weights,seed=123).generate(candidate_count=350,top_n=8)
    assert [(x["numbers"],x["score"]) for x in a] == [(x["numbers"],x["score"]) for x in b]


def test_research_ranking_is_independent_of_crowd_proxy():
    history=[{"draw_date":f"2026-05-{i:02d}","numbers":[1,8,15,22,29,36,43],"bonus":50} for i in range(1,20)]
    candidates=[
        {"numbers":(1,8,15,22,29,36,43),"score":80.0,"components":{}},
        {"numbers":(2,9,16,23,30,37,44),"score":79.5,"components":{}},
        {"numbers":(3,10,17,24,31,38,45),"score":79.0,"components":{}},
        {"numbers":(4,11,18,25,32,39,46),"score":78.5,"components":{}},
    ]
    with patch("lottery_ai.research_engine.crowd_proxy", lambda combo: {"risk":"HIGH","avoidance":0.0}):
        a=ResearchPortfolioOptimizer("max",history).optimize(candidates,top_n=4)
    with patch("lottery_ai.research_engine.crowd_proxy", lambda combo: {"risk":"LOW","avoidance":100.0}):
        b=ResearchPortfolioOptimizer("max",history).optimize(candidates,top_n=4)
    assert [(x["numbers"],x["research_score"]) for x in a] == [(x["numbers"],x["research_score"]) for x in b]


def test_current_draw_snapshot_waits_then_scores_frozen_prediction(tmp_path):
    db=Database(tmp_path/"draw.db")
    preds=[
        {"rank":1,"numbers":[1,2,3,4,5,6],"score":80.0,"components":{}},
        {"rank":2,"numbers":[7,8,9,10,11,12],"score":79.0,"components":{}},
        {"rank":3,"numbers":[13,14,15,16,17,18],"score":78.0,"components":{}},
    ]
    payload={"schema":"per_main_v1","by_pick":[
        {"main_rank":1,"main_numbers":preds[0]["numbers"],"ranking":[[20,90.0],[21,80.0]]},
        {"main_rank":2,"main_numbers":preds[1]["numbers"],"ranking":[[21,90.0],[20,80.0]]},
        {"main_rank":3,"main_numbers":preds[2]["numbers"],"ranking":[[22,90.0],[21,80.0]]},
    ]}
    db.save_freeze("649","2026-09-12","P1.0","2026-09-09",preds,payload,{})
    wait=build_current_draw_snapshot(db,"649",today=date(2026,9,12))
    assert wait["status"] == "AWAITING_OFFICIAL_RESULT"
    assert wait["prediction_locked"] is True

    db.upsert_draw("649","2026-09-12","649_CLASSIC",[1,8,15,30,40,49],21,"WCLC official",verified=True)
    done=build_current_draw_snapshot(db,"649",today=date(2026,9,12))
    assert done["status"] == "VERIFIED_RESULT"
    assert done["best_hit"] == 1
    assert done["top_n_coverage"] == 3
    assert [x["bonus_hit"] for x in done["top3"]] == [False,True,False]


def test_current_draw_non_draw_day_points_to_next_scheduled_draw(tmp_path):
    db=Database(tmp_path/"next.db")
    snap=build_current_draw_snapshot(db,"max",today=date(2026,9,12))  # Saturday -> Tuesday
    assert snap["draw_date"] == "2026-09-15"
    assert snap["scheduled_today"] is False


def test_bc_timestamp_format_converts_utc():
    # Sep 12, 2026 is PDT (UTC-7).
    assert format_bc_timestamp("2026-09-12T18:40:12Z").startswith("2026-09-12 11:40:12 PDT")
