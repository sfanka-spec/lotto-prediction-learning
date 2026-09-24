from lottery_ai.config import APP_VERSION, PORTFOLIO_POLICY_VERSION
from lottery_ai.portfolio import (
    PortfolioOptimizer,
    _normalized_knee_scores,
    _postdraw_selection_oracle_frontier,
    budget_frontier_learning,
    judge_frontier,
)


def _rows_649(n=20):
    rows=[]
    for i in range(n):
        nums=[]
        for j in range(6):
            v=((i*4+j*7)%49)+1
            while v in nums:
                v=(v%49)+1
            nums.append(v)
        rows.append({"rank":i+1,"numbers":sorted(nums),"score":80.0-i*0.2,"components":{}})
    return rows


def test_v154_versions():
    assert APP_VERSION == "V1.6.5"
    assert PORTFOLIO_POLICY_VERSION == "BUD1.4"


def test_knee_is_endpoint_normalized_not_positive_intercept_biased():
    ks=[1,2,3,4,5]
    # Same curvature, but with a large positive baseline.  Correct min-max endpoint
    # normalization should be invariant to adding a constant to every y value.
    a={1:0.10,2:0.55,3:0.75,4:0.88,5:1.00}
    b={k:v+10.0 for k,v in a.items()}
    sa=_normalized_knee_scores(ks,a)
    sb=_normalized_knee_scores(ks,b)
    assert all(abs(sa[k]-sb[k]) < 1e-12 for k in ks)
    assert max(ks,key=lambda k:(sa[k],-k)) == max(ks,key=lambda k:(sb[k],-k))


def test_frontier_declares_corrected_knee_semantics():
    fr=PortfolioOptimizer("649").frontier(_rows_649())
    assert fr["schema"] == "PORTFOLIO_FRONTIER1.3"
    assert fr["auto"]["knee_normalization"] == "MIN_MAX_ENDPOINTS"
    assert fr["auto"]["marginal_semantics"] == "FRONTIER_SPEND_LEVEL_DIFFERENCE_NOT_NESTED_ADD_ONE"
    assert "frontier_marginal_value_per_dollar" in fr["frontier"]["2"]


def test_exact_oracle_jointly_optimizes_subset_coverage_not_individual_ticket_sort():
    rows=[
        {"rank":1,"numbers":[1,2,3,10,11,12],"score":90,"components":{}},
        {"rank":2,"numbers":[1,2,3,13,14,15],"score":89,"components":{}},
        {"rank":3,"numbers":[4,5,6,16,17,18],"score":88,"components":{}},
    ]
    draw={"draw_date":"2026-09-16","numbers":[1,2,3,4,5,6],"bonus":7}
    oracle=_postdraw_selection_oracle_frontier(rows,draw)
    # For k=2, ranks 1+2 each have 3 hits but cover only 3 winning numbers together.
    # A joint subset oracle must pair one of them with rank 3 to cover all 6.
    assert set(oracle["2"]["selected_ranks"]) in ({1,3},{2,3})
    assert oracle["2"]["oracle_method"] == "EXACT_NON_MONETARY_SUBSET_ORACLE"


def test_unresolved_high_tier_is_not_lost_to_fixed_cash_in_oracle():
    rows=[
        {"rank":1,"numbers":[1,2,3,4,5,20],"score":90,"components":{}},  # 5/6 unresolved
        {"rank":2,"numbers":[1,2,3,21,22,23],"score":89,"components":{}}, # 3/6 fixed $10
    ]
    draw={"draw_date":"2026-09-16","numbers":[1,2,3,4,5,6],"bonus":7}
    oracle=_postdraw_selection_oracle_frontier(rows,draw)
    assert oracle["1"]["selected_ranks"] == [1]


def _ev(k, edge=0.2):
    return {
        "lines":k,"cost":3*k,"roi_floor":-1.0,"payout_floor":0.0,
        "any_prize":False,"best_hit":2,"avg_hit":1.0,"winning_number_coverage":2,
        "winner_concentration_efficiency":1.0,
        "random_same_budget_best_hit":2-edge,
        "random_same_budget_avg_hit":1.0-edge,
        "random_same_budget_coverage":2.0,
        "random_same_budget_wce":1.0,
        "random_same_budget_payout_floor":0.0,
        "unresolved_parimutuel_or_jackpot_tickets":0,
    }


def test_budget_evidence_uses_common_paired_cohort_not_max_sample_anywhere():
    records=[]
    # 120 draws have k=1, but only the latest 60 also have k=2.  V1.5.3 could use
    # max n=120 for the evidence phase while comparing k=2 on a smaller period.
    for i in range(120):
        by={"1":_ev(1)}
        if i >= 60:
            by["2"]=_ev(2)
        records.append({"id":i+1,"game":"649","draw_date":f"D{i:03d}","judgment":{"by_lines":by}})
    got=budget_frontier_learning(records,"649")
    assert got["comparison_cohort_n"] == 60
    assert got["n"] == 60
    assert got["common_n_across_line_counts"] == 60
    assert got["by_lines"]["1"]["raw_n"] == 120
    assert got["by_lines"]["1"]["n"] == 60
    assert got["by_lines"]["2"]["n"] == 60


def test_judgment_reuses_exact_non_monetary_oracle():
    rows=_rows_649(8)
    fr=PortfolioOptimizer("649").frontier(rows)
    decision={"production_frontier":fr,"shadow_frontier":fr}
    draw={"draw_date":"2026-09-16","numbers":[1,2,3,4,5,6],"bonus":7}
    out=judge_frontier("649",rows,decision,draw)
    assert out["schema"] == "PORTFOLIO_JUDGMENT1.2"
    assert out["oracle_method"] == "EXACT_NON_MONETARY_SUBSET_ORACLE"
    assert out["by_lines"]["1"]["oracle_same_budget_method"] == "EXACT_NON_MONETARY_SUBSET_ORACLE"
