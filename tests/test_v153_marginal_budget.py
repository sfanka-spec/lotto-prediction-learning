from lottery_ai.config import APP_VERSION, PORTFOLIO_POLICY_VERSION
from lottery_ai.portfolio import PortfolioOptimizer


def _spread_rows(game="649", n=20):
    max_number = 49 if game == "649" else 52
    pick = 6 if game == "649" else 7
    rows = []
    for i in range(n):
        nums = []
        step = 7 if game == "649" else 9
        for j in range(pick):
            v = ((i * 3 + j * step) % max_number) + 1
            while v in nums:
                v = (v % max_number) + 1
            nums.append(v)
        rows.append({"rank": i + 1, "numbers": sorted(nums), "score": 80.0 - 0.2 * i, "components": {}})
    return rows


def test_v153_versions():
    assert APP_VERSION == "V1.6.6"
    assert PORTFOLIO_POLICY_VERSION == "BUD1.4"


def test_single_line_diversity_is_not_applicable_or_rewarded():
    fr = PortfolioOptimizer("649").frontier(_spread_rows("649", 8))
    one = fr["frontier"]["1"]
    assert one["features"]["diversity_applicable"] is False
    assert one["features"]["diversity"] == 0.0
    assert fr["single_line_diversity_policy"] == "NOT_APPLICABLE_ZERO_CONTRIBUTION"


def test_rank_retention_is_guardrail_not_cross_budget_bonus():
    fr = PortfolioOptimizer("649").frontier(_spread_rows("649", 8))
    assert fr["rank_retention_policy"] == "GUARDRAIL_NOT_BONUS"
    assert all(x["rank_retention_mode"] == "GUARDRAIL_TIEBREAK" for x in fr["frontier"].values())


def test_diminishing_return_curve_has_explicit_marginal_value_per_dollar():
    fr = PortfolioOptimizer("649").frontier(_spread_rows("649", 20))
    assert fr["schema"] == "PORTFOLIO_FRONTIER1.3"
    assert fr["cross_k_method"] == "DIMINISHING_RETURN_KNEE"
    assert 1 <= fr["auto"]["lines"] <= 20
    prev = 0.0
    for k in range(1, 21):
        row = fr["frontier"][str(k)]
        env = row["deployment_utility_envelope"]
        assert env + 1e-9 >= prev
        expected = max(0.0, env - prev) / 3.0
        assert abs(row["marginal_value_per_dollar"] - expected) < 1e-7
        prev = env


def test_diversified_649_frontier_does_not_collapse_to_one_ticket():
    fr = PortfolioOptimizer("649").frontier(_spread_rows("649", 20))
    # This fixture deliberately has substantial incremental coverage. The old
    # V1.5.2 objective often stopped at one line because diversity/rank were
    # perfect for k=1. The marginal-knee logic must recognize later value.
    assert fr["auto"]["lines"] > 1
    under_100 = PortfolioOptimizer("649").for_budget(fr, 100.0, allow_unspent=True)
    assert under_100["lines"] > 1
    assert under_100["status"] == "STRUCTURAL_DIMINISHING_RETURN_SWEET_SPOT"


def test_budget_cap_separates_sweet_spot_from_max_deployment():
    fr = PortfolioOptimizer("649").frontier(_spread_rows("649", 20))
    sweet = PortfolioOptimizer("649").for_budget(fr, 20.0, allow_unspent=True)
    full = PortfolioOptimizer("649").for_budget(fr, 20.0, allow_unspent=False)
    assert sweet["cost"] <= 20.0
    assert full["cost"] == 18.0  # six $3 model-directed plays fit under $20
    assert full["lines"] == 6
    assert full["status"] == "MAX_DEPLOYMENT_UNDER_CAP"
    assert sweet["lines"] <= full["lines"]


def test_exact_k_curve_maps_each_line_count_to_exact_cost():
    fr = PortfolioOptimizer("max").frontier(_spread_rows("max", 20))
    for k in range(1, 21):
        row = fr["frontier"][str(k)]
        assert row["lines"] == k
        assert row["cost"] == 6.0 * k


def test_sweet_spot_stays_constant_once_global_knee_is_affordable():
    fr = PortfolioOptimizer("649").frontier(_spread_rows("649", 20))
    global_k = int(fr["auto"]["lines"])
    global_cost = float(fr["auto"]["cost"])
    assert global_k >= 1
    for budget in (global_cost, global_cost + 20.0, 100.0):
        got = PortfolioOptimizer("649").for_budget(fr, budget, allow_unspent=True)
        assert got["lines"] == global_k
        assert got["cost"] == global_cost
