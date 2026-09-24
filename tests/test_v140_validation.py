import copy
import json

from lottery_ai.champion import build_match_diagnostics
from lottery_ai.config import COMMON_WEIGHTS, V14_STRATEGY_VERSIONS
from lottery_ai.db import Database
from lottery_ai.engine import PredictionEngine
from lottery_ai.evaluation import (
    benjamini_hochberg,
    bootstrap_mean_ci,
    paired_sign_flip_test,
    statistical_simulation_self_check,
    strategy_validation_summary,
)
from lottery_ai.integrity import build_freeze_integrity, verify_freeze_integrity


def _draws_649(n=50):
    rows=[]
    for i in range(n):
        nums=sorted({((i*7+j*9) % 49)+1 for j in range(6)})
        x=1
        while len(nums)<6:
            if x not in nums: nums.append(x)
            x+=1
        nums=sorted(nums[:6])
        rows.append({"draw_date":f"2026-01-{(i%28)+1:02d}","numbers":nums,"bonus":49 if 49 not in nums else 48})
    return rows


def test_champion_ranking_diagnostics_match_v124_example():
    # Recreates the key leaderboard pattern shown by the 2026-09-12 frozen portfolio:
    # champion is original rank #12, while several higher-score rows only hit 2 numbers.
    win={1,3,17,20,26,32}
    preds=[]
    explicit={
        2:[2,17,20,25,33,42],
        4:[1,11,17,34,41,45],
        7:[6,14,17,32,33,37],
        12:[3,13,17,32,34,45],
        13:[6,17,20,30,36,41],
    }
    for rank in range(1,21):
        nums=explicit.get(rank,[4,8,12,16,24,40])
        # keep non-explicit rows from accidentally becoming champions
        if rank not in explicit:
            nums=[n+((rank-1)%2) for n in nums]
            nums=[min(49,n) for n in nums]
        score=78.2-rank*0.15
        preds.append({"rank":rank,"numbers":nums,"score":score,"components":{k:50+rank/10 for k in COMMON_WEIGHTS if k!='monte_carlo'}})
    diag=build_match_diagnostics("649",preds,{"draw_date":"2026-09-12","numbers":sorted(win),"bonus":5},[])
    assert diag["best_hit"] == 3
    assert diag["champion_best_original_rank"] == 12
    assert diag["ranking_diagnosis"] == "UNDER_RANKED"
    assert diag["stage_diagnosis"]["best_hit_placement"] == "WEAK"
    assert diag["stage_diagnosis"]["global_rank_association"] in {"NEUTRAL", "WEAK_NEGATIVE", "NEGATIVE", "WEAK_POSITIVE", "POSITIVE"}
    assert diag["stage_diagnosis"]["ranking"] in {"WEAK", "MIXED"}
    assert diag["champions"][0]["matched_numbers"] == [3,17,32]


def test_strategy_suite_uses_one_candidate_pool():
    draws=_draws_649(35)
    eng=PredictionEngine("649",draws,COMMON_WEIGHTS,seed=1400)
    suite=eng.generate_strategy_suite(candidate_count=850,top_n=10,neural_scores=None)
    assert len(suite["candidate_pool_hash"]) == 64
    assert set(suite["portfolios"]) == {"balanced","score_only","focused","pure_coverage","concentrated"}
    assert all(len(v)==10 for v in suite["portfolios"].values())
    assert all(v[0]["rank"]==1 for v in suite["portfolios"].values())
    # Score-only must preserve descending frozen Main score.
    scores=[r["score"] for r in suite["portfolios"]["score_only"]]
    assert scores == sorted(scores,reverse=True)


def test_integrity_hash_detects_post_freeze_mutation(tmp_path):
    db=Database(tmp_path/"lottery.db")
    preds=[{"rank":1,"numbers":[1,2,3,4,5,6],"score":77.1,"components":{"frequency":55.0}}]
    integrity=build_freeze_integrity(
        predictions=preds,weights={"frequency":1.0},game="649",target="2026-09-16",cutoff="2026-09-12",
        app_version="V1.4.0",model_version="P1.0",coverage_mode="balanced",coverage_engine="COV1.1",
        candidate_hash="a"*64,
    )
    db.save_freeze("649","2026-09-16","P1.0","2026-09-12",preds,[],{"integrity":integrity})
    fr=db.official_freeze("649","2026-09-16")
    verified=verify_freeze_integrity(fr)
    assert verified["status"] == "PASS_WITH_LIMITATIONS"
    assert verified["layers"]["prediction"]["status"] == "PASS"
    assert verified["layers"]["feature_snapshot"]["status"] == "PASS"
    assert verified["layers"]["algorithm"]["status"] == "PASS"
    assert verified["layers"]["candidate_pool"]["status"] == "NOT_VERIFIABLE"
    mutated=dict(fr)
    altered=copy.deepcopy(preds)
    altered[0]["numbers"][-1]=7
    mutated["predictions_json"]=json.dumps(altered)
    assert verify_freeze_integrity(mutated)["status"] == "MUTATION_DETECTED"


def test_statistical_helpers_are_deterministic_and_fdr_monotone():
    vals=[0.1,0.0,0.2,-0.1,0.3,0.1]
    assert bootstrap_mean_ci(vals,seed_label="same") == bootstrap_mean_ci(vals,seed_label="same")
    assert paired_sign_flip_test(vals,seed_label="same") == paired_sign_flip_test(vals,seed_label="same")
    q=benjamini_hochberg({"a":0.001,"b":0.02,"c":0.2})
    assert q["a"] <= q["b"] <= q["c"]
    assert all(0 <= q[k] <= 1 for k in q)


def test_strategy_validation_computes_coverage_gain_and_concentration_cost(tmp_path):
    db=Database(tmp_path/"lottery.db")
    for i in range(1,6):
        d=f"2026-08-{i:02d}"
        # dummy freezes are only foreign-key parents for champion diagnostics
        db.save_freeze("649",d,f"P1.{i}","2026-07-31",[{"numbers":[1,2,3,4,5,6]}],[],{})
        pf=db.freeze_by_prefix("649",d,"P1.")
        db.save_champion_learning(pf["id"],"649",d,f"P1.{i}",{
            "draw_date":d,"avg_hit":0.8,"best_hit":3,"top_n_coverage":5,
            "champion_best_original_rank":8,"champion_component_delta":{},"champion_component_signal":{},
            "bottleneck":"COMBINATION_CONCENTRATION",
        })
        ver=V14_STRATEGY_VERSIONS["score_only"]
        db.save_freeze("649",d,ver,"2026-07-31",[{"numbers":[1,2,3,4,5,6]}],[],{})
        sf=db.freeze_by_prefix("649",d,"S14SCORE")
        db.save_champion_learning(sf["id"],"649",d,ver,{
            "draw_date":d,"avg_hit":0.75,"best_hit":4,"top_n_coverage":4,
            "champion_best_original_rank":5,"champion_component_delta":{},"champion_component_signal":{},
            "bottleneck":"NUMBER_SELECTION",
        })
    out=strategy_validation_summary(db,"649")
    trade=out["coverage_tradeoff"]
    assert trade["n"] == 5
    assert trade["balanced_coverage_gain_vs_score_only"] == 1.0
    assert trade["balanced_concentration_cost_vs_score_only"] == 1.0
    assert out["comparisons"]["score_only"]["avg_hit_delta"] == -0.05
    assert out["comparisons"]["score_only"]["gate"] == "WAITING"


def test_sign_flip_uses_exact_small_sample_and_monte_carlo_large_sample():
    exact=paired_sign_flip_test([1.0,1.0,1.0],seed_label="exact")
    assert exact["method"] == "exact_sign_flip"
    assert exact["permutations"] == 8
    assert exact["p_two_sided"] == 0.25

    mc=paired_sign_flip_test([1.0]*17,reps=1000,seed_label="mc")
    assert mc["method"] == "monte_carlo_sign_flip"
    assert mc["permutations"] == 1000
    assert 0 < mc["p_two_sided"] <= 1


def test_v141_integrity_detects_feature_and_algorithm_descriptor_mutation(tmp_path):
    db=Database(tmp_path/"lottery.db")
    preds=[{"rank":1,"numbers":[1,2,3,4,5,6],"score":77.1,"components":{"frequency":55.0}}]
    integrity=build_freeze_integrity(
        predictions=preds,weights={"frequency":1.0},game="649",target="2026-09-16",cutoff="2026-09-12",
        app_version="V1.4.1",model_version="P1.0",coverage_mode="balanced",coverage_engine="COV1.1",
        candidate_hash="b"*64,
    )
    db.save_freeze("649","2026-09-16","P1.0","2026-09-12",preds,[],{"integrity":integrity})
    fr=db.official_freeze("649","2026-09-16")

    feature_mut=copy.deepcopy(fr)
    ctx=json.loads(feature_mut["factor_context_json"])
    ctx["integrity"]["verification_inputs"]["feature_snapshot"]["weights"]["frequency"]=0.5
    feature_mut["factor_context_json"]=json.dumps(ctx)
    out=verify_freeze_integrity(feature_mut)
    assert out["status"] == "MUTATION_DETECTED"
    assert out["layers"]["feature_snapshot"]["status"] == "MUTATION_DETECTED"

    algo_mut=copy.deepcopy(fr)
    ctx=json.loads(algo_mut["factor_context_json"])
    ctx["integrity"]["verification_inputs"]["algorithm"]["coverage_mode"]="pure_coverage"
    algo_mut["factor_context_json"]=json.dumps(ctx)
    out=verify_freeze_integrity(algo_mut)
    assert out["status"] == "MUTATION_DETECTED"
    assert out["layers"]["algorithm"]["status"] == "MUTATION_DETECTED"


def test_v140_legacy_hash_is_not_overclaimed_as_fully_verified():
    preds=[{"rank":1,"numbers":[1,2,3,4,5,6],"score":77.1,"components":{"frequency":55.0}}]
    legacy_integrity={
        "schema":"INTEGRITY1.0",
        "prediction_sha256":build_freeze_integrity(
            predictions=preds,weights={"frequency":1.0},game="649",target="2026-09-16",cutoff="2026-09-12",
            app_version="V1.4.0",model_version="P1.0",coverage_mode="balanced",coverage_engine="COV1.1",candidate_hash=None,
        )["prediction_sha256"],
        "feature_snapshot_sha256":"c"*64,
        "algorithm_sha256":"d"*64,
        "candidate_pool_sha256":"e"*64,
    }
    freeze={
        "predictions_json":json.dumps(preds),
        "factor_context_json":json.dumps({"integrity":legacy_integrity}),
        "data_cutoff":"2026-09-12",
    }
    out=verify_freeze_integrity(freeze)
    assert out["status"] == "PASS_WITH_LIMITATIONS"
    assert out["layers"]["prediction"]["status"] == "PASS"
    assert out["layers"]["feature_snapshot"]["status"] == "NOT_VERIFIABLE"
    assert out["layers"]["algorithm"]["status"] == "NOT_VERIFIABLE"
    assert out["layers"]["candidate_pool"]["status"] == "NOT_VERIFIABLE"


def test_statistical_simulation_regression_sanity():
    check=statistical_simulation_self_check(simulations=60,sample_n=20,bootstrap_reps=800)
    assert check["bootstrap_pass"] is True
    assert check["sign_flip_pass"] is True
    assert 0.80 <= check["bootstrap_observed_coverage"] <= 1.0
    assert 0.0 <= check["sign_flip_observed_type1"] <= 0.15


def test_strategy_suite_is_mode_order_invariant_and_uncontaminated():
    draws=_draws_649(35)
    a=PredictionEngine("649",draws,COMMON_WEIGHTS,seed=1411).generate_strategy_suite(
        candidate_count=900,top_n=10,neural_scores=None,
        modes=("balanced","score_only","focused","pure_coverage"),
    )
    b=PredictionEngine("649",draws,COMMON_WEIGHTS,seed=1411).generate_strategy_suite(
        candidate_count=900,top_n=10,neural_scores=None,
        modes=("pure_coverage","focused","score_only","balanced"),
    )
    assert a["candidate_pool_hash"] == b["candidate_pool_hash"]
    for mode in ("balanced","score_only","focused","pure_coverage"):
        assert a["portfolios"][mode] == b["portfolios"][mode]
