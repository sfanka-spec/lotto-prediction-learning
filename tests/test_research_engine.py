from pathlib import Path

from lottery_ai.db import Database
from lottery_ai.regime import eligible_number_profile, regime_for, regime_summary
from lottery_ai.research_engine import RandomControlEngine, ResearchPortfolioOptimizer, crowd_proxy, portfolio_summary


def test_lotto_max_regime_boundaries():
    assert regime_for("max", "2019-05-13")["max_number"] == 49
    assert regime_for("max", "2019-05-14")["max_number"] == 50
    assert regime_for("max", "2026-04-13")["max_number"] == 50
    assert regime_for("max", "2026-04-14")["max_number"] == 52


def test_51_52_not_penalized_for_pre_52_history():
    draws = [
        {"draw_date":"2018-01-01","numbers":[1,2,3,4,5,6,7],"bonus":8},
        {"draw_date":"2020-01-01","numbers":[1,2,3,4,5,6,50],"bonus":8},
        {"draw_date":"2026-04-14","numbers":[1,2,3,4,5,51,52],"bonus":8},
        {"draw_date":"2026-04-17","numbers":[10,11,12,13,14,51,52],"bonus":8},
    ]
    p = eligible_number_profile("max", draws)
    assert p[51]["eligible_draws"] == 2
    assert p[52]["eligible_draws"] == 2
    assert p[50]["eligible_draws"] == 3


def test_random_control_is_deterministic_and_unique():
    a = RandomControlEngine("649", seed=1234).generate(top_n=12, candidate_count=200)
    b = RandomControlEngine("649", seed=1234).generate(top_n=12, candidate_count=200)
    assert [x["numbers"] for x in a] == [x["numbers"] for x in b]
    assert len({tuple(x["numbers"]) for x in a}) == 12


def test_crowd_proxy_date_heavy_is_riskier():
    date_heavy = crowd_proxy([1, 7, 11, 18, 21, 25])
    spread = crowd_proxy([33, 36, 39, 42, 46, 49])
    assert date_heavy["risk_score"] > spread["risk_score"]
    assert date_heavy["avoidance"] < spread["avoidance"]


def test_research_optimizer_outputs_ranked_diverse_portfolio():
    all_draws = [
        {"draw_date":f"2026-05-{i:02d}","numbers":[1,8,15,22,29,36,43],"bonus":50}
        for i in range(1, 20)
    ]
    candidates=[]
    for i in range(30):
        nums=tuple(sorted({1+i%10, 12+i%15, 25+i%20, 31+i%18, 38+i%14, 44+i%9, 52-i%8}))
        if len(nums) != 7:
            continue
        candidates.append({"numbers":nums,"score":80-i*0.2,"components":{}})
    out=ResearchPortfolioOptimizer("max",all_draws).optimize(candidates,top_n=min(8,len(candidates)))
    assert out
    assert all("research_score" in r and "crowd_avoidance" in r and "regime_score" in r for r in out)
    summary=portfolio_summary(out,"max")
    assert summary["tickets"] == len(out)
    assert summary["unique_numbers"] >= 7


def test_shadow_freezes_do_not_pollute_challenger_pairing(tmp_path: Path):
    db=Database(tmp_path / "t.db")
    # One draw with P/C/RND/RES judgments. Only P/C may count as paired model performance.
    for ver,avg in [("P1.0",1.0),("C1.0",1.1),("RND1.0",0.8),("RES1.0",1.2)]:
        ctx = ({"search_budget_equal_to_challenger": True, "candidate_universe_equal_to_challenger": True}
               if ver.startswith("P") else
               ({"search_budget_equal_to_production": True, "candidate_universe_equal_to_production": True}
                if ver.startswith("C") else {}))
        db.save_freeze("649","2026-09-12",ver,"2026-09-09",[{"numbers":[1,2,3,4,5,6]}],[],ctx)
    with db.connect() as con:
        rows=con.execute("SELECT id,model_version FROM freezes ORDER BY id").fetchall()
    for row in rows:
        avg={"P1.0":1.0,"C1.0":1.1,"RND1.0":0.8,"RES1.0":1.2}[row["model_version"]]
        db.save_judgment(row["id"],"649","2026-09-12",2,avg,avg,None,36/49,{})
    pairs=db.paired_model_performance("649")
    assert len(pairs) == 1
    assert pairs[0][1] == 1.0 and pairs[0][2] == 1.1
    rnd=db.paired_shadow_performance("649","RND")
    res=db.paired_shadow_performance("649","RES")
    assert rnd[0][2] == 0.8
    assert res[0][2] == 1.2
