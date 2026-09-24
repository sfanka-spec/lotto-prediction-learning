from lottery_ai.config import APP_VERSION, PORTFOLIO_POLICY_VERSION
from lottery_ai.portfolio import PortfolioOptimizer, evaluate_portfolio_choice, line_selection_learning


def _rows():
    return [
        {"rank":1,"numbers":[1,2,3,4,5,6],"score":80.0,"components":{}},
        {"rank":2,"numbers":[1,2,7,8,9,10],"score":79.0,"components":{}},
        {"rank":3,"numbers":[11,12,13,14,15,16],"score":78.0,"components":{}},
        {"rank":4,"numbers":[17,18,19,20,21,22],"score":77.0,"components":{}},
        {"rank":5,"numbers":[23,24,25,26,27,28],"score":76.0,"components":{}},
        {"rank":6,"numbers":[29,30,31,32,33,34],"score":75.0,"components":{}},
    ]


def test_version_bumped_for_line_learning():
    assert APP_VERSION == "V1.6.5"
    assert PORTFOLIO_POLICY_VERSION == "BUD1.4"


def test_frontier_freezes_predraw_line_roles():
    fr=PortfolioOptimizer("649").frontier(_rows())
    item=fr["frontier"]["3"]
    assert len(item["line_roles"]) == 3
    assert {x["rank"] for x in item["line_roles"]} == set(item["selected_ranks"])
    assert all(x["role"] in {"CORE","COVERAGE","DIVERSITY","BALANCED"} for x in item["line_roles"])


def test_postdraw_line_review_keeps_each_selected_line_separate():
    rows=_rows()
    fr=PortfolioOptimizer("649").frontier(rows)
    choice=fr["frontier"]["3"]
    draw={"draw_date":"2026-09-16","numbers":[1,2,3,17,23,40],"bonus":7}
    out=evaluate_portfolio_choice("649",rows,choice,draw)
    line=out["line_learning"]
    assert len(line["per_line"]) == 3
    assert len(line["replacement_review"]) == 3
    assert all("matched_numbers" in x for x in line["per_line"])
    assert all("role" in x for x in line["per_line"])


def test_line_learning_effective_n_is_draw_count_not_line_count():
    rows=_rows()
    fr=PortfolioOptimizer("649").frontier(rows)
    choice=fr["auto"]
    draw={"draw_date":"2026-09-16","numbers":[1,2,3,17,23,40],"bonus":7}
    ev=evaluate_portfolio_choice("649",rows,choice,draw)
    rec={"id":1,"game":"649","draw_date":"2026-09-16","judgment":{"production_auto":ev}}
    got=line_selection_learning([rec])
    assert got["n"] == 1
    assert sum(x["draws"] for x in got["by_role"].values()) >= 1


def test_same_draw_two_versions_do_not_double_count_line_learning():
    rows=_rows(); fr=PortfolioOptimizer("649").frontier(rows); choice=fr["auto"]
    draw={"draw_date":"2026-09-16","numbers":[1,2,3,17,23,40],"bonus":7}
    ev=evaluate_portfolio_choice("649",rows,choice,draw)
    a={"id":1,"game":"649","draw_date":"2026-09-16","judgment":{"production_auto":ev}}
    b={"id":2,"game":"649","draw_date":"2026-09-16","judgment":{"production_auto":ev}}
    got=line_selection_learning([a,b])
    assert got["n"] == 1


def test_budget_can_show_efficiency_and_spend_to_cap_separately():
    fr=PortfolioOptimizer("649").frontier(_rows())
    opt=PortfolioOptimizer("649")
    eff=opt.for_budget(fr,18,allow_unspent=True)
    full=opt.for_budget(fr,18,allow_unspent=False)
    assert eff["cost"] <= 18
    assert full["cost"] == 18
    assert full["unused"] == 0
    assert full["lines"] == 6
