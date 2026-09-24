from pathlib import Path
import json

from lottery_ai.bonus import (
    build_bonus_payload,
    normalize_bonus_payload,
    bonus_top_for_pick,
    main_bonus_consistency,
    sanitize_and_complete_bonus_payload,
)
from lottery_ai.config import BONUS_WEIGHTS, GAMES
from lottery_ai.db import Database
from lottery_ai.engine import PredictionEngine
from lottery_ai.learning import LearningManager


def _draws_649(n=40):
    out=[]
    for i in range(n):
        start=(i*3)%40+1
        nums=sorted({((start+j*7-1)%49)+1 for j in range(6)})
        while len(nums)<6:
            x=((nums[-1]+5-1)%49)+1
            if x not in nums:
                nums.append(x); nums.sort()
        bonus=next(x for x in range(1,50) if x not in nums)
        out.append({"draw_date":f"2026-01-{(i%28)+1:02d}","numbers":nums[:6],"bonus":bonus})
    return out


def test_bonus_payload_is_bound_to_every_main_pick_and_excludes_main_numbers():
    draws=_draws_649()
    eng=PredictionEngine("649",draws,GAMES["649"].default_weights,seed=123)
    preds=eng.generate(candidate_count=300,top_n=5)
    payload=build_bonus_payload(preds,lambda main,lim: eng.bonus_rank(main,lim,weights=BONUS_WEIGHTS),limit=10)
    assert payload["schema"] == "per_main_v1"
    assert len(payload["by_pick"]) == len(preds)
    for bound in payload["by_pick"]:
        main=set(bound["main_numbers"])
        assert len(bound["ranking"]) == 10
        assert all(int(n) not in main for n,_ in bound["ranking"])
    rep=main_bonus_consistency(preds,payload)
    assert rep["status"] == "PASS"
    assert rep["bound_main_picks"] == 5


def test_legacy_bonus_payload_is_recognized_as_pick1_only():
    preds=[
        {"rank":1,"numbers":[1,2,3,4,5,6]},
        {"rank":2,"numbers":[7,8,9,10,11,12]},
    ]
    legacy=[[20,88.5],[21,82.0]]
    norm=normalize_bonus_payload(legacy,preds)
    assert norm["legacy"] is True
    assert norm["by_pick"][0]["main_rank"] == 1
    rep=main_bonus_consistency(preds,norm)
    assert rep["status"] == "PARTIAL"
    assert rep["missing_bindings"] == [2]


def test_invalid_bonus_is_auto_reselected_without_changing_main_predictions():
    draws=_draws_649()
    eng=PredictionEngine("649",draws,GAMES["649"].default_weights,seed=321)
    preds=eng.generate(candidate_count=250,top_n=3)
    before=[tuple(p["numbers"]) for p in preds]
    # Deliberately inject an invalid Bonus that is inside Pick #1.
    bad={
        "schema":"per_main_v1",
        "by_pick":[{
            "main_rank":1,
            "main_numbers":list(preds[0]["numbers"]),
            "ranking":[[int(preds[0]["numbers"][0]),99.0]],
        }],
    }
    fixed=sanitize_and_complete_bonus_payload(
        preds,bad,lambda main,lim: eng.bonus_rank(main,lim,weights=BONUS_WEIGHTS),limit=10)
    after=[tuple(p["numbers"]) for p in preds]
    assert before == after  # Bonus orchestration may never modify Main combinations.
    assert fixed["auto_reselected"] >= 1
    assert fixed["completed_bindings"] == 2
    assert main_bonus_consistency(preds,fixed)["status"] == "PASS"
    assert bonus_top_for_pick(fixed,1,preds) not in set(preds[0]["numbers"])


def test_bonus_score_generation_does_not_change_main_ranking():
    draws=_draws_649()
    eng=PredictionEngine("649",draws,GAMES["649"].default_weights,seed=999)
    preds=eng.generate(candidate_count=300,top_n=4)
    snapshot=[(p["rank"],tuple(p["numbers"]),p["score"]) for p in preds]
    _=build_bonus_payload(preds,lambda main,lim: eng.bonus_rank(main,lim,weights={
        "bonus_frequency":0.05,"bonus_gap":0.90,"recent":0.05
    }),limit=10)
    assert snapshot == [(p["rank"],tuple(p["numbers"]),p["score"]) for p in preds]


def test_learning_judgment_accepts_per_main_bonus_payload_without_schema_change(tmp_path: Path):
    db=Database(tmp_path/"bonus.db")
    preds=[
        {"rank":1,"numbers":[1,2,3,4,5,6],"components":{}},
        {"rank":2,"numbers":[7,8,9,10,11,12],"components":{}},
    ]
    payload={
        "schema":"per_main_v1",
        "by_pick":[
            {"main_rank":1,"main_numbers":[1,2,3,4,5,6],"ranking":[[20,90.0],[21,80.0]]},
            {"main_rank":2,"main_numbers":[7,8,9,10,11,12],"ranking":[[21,95.0],[20,85.0]]},
        ],
    }
    db.save_freeze("649","2026-09-12","P1.0","2026-09-09",preds,payload,{})
    draw={"draw_date":"2026-09-12","numbers":[1,8,20,30,40,49],"bonus":21}
    LearningManager(db).judge_new_draw("649",draw)
    rows=db.recent_judgments("649",10)
    assert len(rows)==1
    # Existing scalar DB column stays Pick #1 conditional rank for backward compatibility.
    assert rows[0]["bonus_rank_hit"] == 2
    details=json.loads(rows[0]["details_json"])
    assert details["bonus_conditional_rank_by_main_pick"] == {"1":2,"2":1}
    assert details["main_bonus_consistency"]["status"] == "PASS"


def test_consistency_detects_binding_mismatch_duplicate_rank_and_out_of_range():
    preds=[
        {"rank":1,"numbers":[1,2,3,4,5,6]},
        {"rank":2,"numbers":[7,8,9,10,11,12]},
    ]
    payload={
        "schema":"per_main_v1",
        "by_pick":[
            {"main_rank":1,"main_numbers":[1,2,3,4,5,9],"ranking":[[20,90],[20,80],[50,70]]},
            {"main_rank":1,"main_numbers":[1,2,3,4,5,6],"ranking":[[1,60]]},
        ],
    }
    rep=main_bonus_consistency(preds,payload,max_number=49,expected_limit=10)
    reasons={e["reason"] for e in rep["errors"]}
    assert rep["status"] == "FAIL"
    assert "main_numbers_mismatch" in reasons
    assert "duplicate_main_binding" in reasons
    assert "duplicate_bonus_candidate" in reasons
    assert "bonus_out_of_range" in reasons
    assert "bonus_in_main" in reasons
    assert rep["missing_bindings"] == [2]


def test_normalizing_legacy_payload_does_not_backfill_missing_main_picks():
    preds=[
        {"rank":1,"numbers":[1,2,3,4,5,6]},
        {"rank":2,"numbers":[7,8,9,10,11,12]},
        {"rank":3,"numbers":[13,14,15,16,17,18]},
    ]
    legacy=[[20,88.5],[21,82.0]]
    norm=normalize_bonus_payload(legacy,preds)
    assert norm["legacy"] is True
    assert [x["main_rank"] for x in norm["by_pick"]] == [1]
    assert bonus_top_for_pick(norm,2,preds) is None
    assert bonus_top_for_pick(norm,3,preds) is None


def test_freeze_context_records_bonus_provenance_without_schema_migration(tmp_path: Path):
    db=Database(tmp_path/"freeze_meta.db")
    lm=LearningManager(db)
    draws=[{"draw_date":"2026-09-09","numbers":[1,2,3,4,5,6],"bonus":7}]
    pp=[{"rank":1,"numbers":[8,9,10,11,12,13],"score":70,"components":{}}]
    cp=[{"rank":1,"numbers":[14,15,16,17,18,19],"score":69,"components":{}}]
    pb={"schema":"per_main_v1","by_pick":[{"main_rank":1,"main_numbers":pp[0]["numbers"],"ranking":[[20,80.0]]}]}
    cb={"schema":"per_main_v1","by_pick":[{"main_rank":1,"main_numbers":cp[0]["numbers"],"ranking":[[21,79.0]]}]}
    target=lm.freeze_next(
        "649",draws,pp,cp,"P1.0","C1.0",pb,cb,
        production_bonus_version="BP1.2",challenger_bonus_version="BC1.4",app_version="V1.1.1")
    pfreeze=db.official_freeze("649",target)
    ctx=json.loads(pfreeze["factor_context_json"])
    assert ctx["main_score_name"] == "Combination Score"
    assert ctx["bonus_score_name"] == "Bonus Conditional Score"
    assert ctx["bonus_binding_schema"] == "per_main_v1"
    assert ctx["bonus_model_version"] == "BP1.2"
    assert ctx["bonus_rankings_frozen"] is True
