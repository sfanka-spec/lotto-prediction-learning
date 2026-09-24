from datetime import date, timedelta

from lottery_ai.config import GAMES, PREDICTIVE_FACTORS, normalize_main_weights
from lottery_ai.engine import PredictionEngine
from lottery_ai.backtest import feature_ablation_test, rank_stability_test
from lottery_ai.db import Database
from lottery_ai.updater import DataUpdater


def _draws_649(n=40):
    out = []
    d = date(2025, 1, 1)
    for i in range(n):
        # deterministic legal synthetic history; dates are only ordering labels here
        nums = sorted({((i * 3 + j * 7) % 49) + 1 for j in range(6)})
        x = 1
        while len(nums) < 6:
            if x not in nums:
                nums.append(x)
            x += 1
        nums = sorted(nums[:6])
        bonus = next(x for x in range(1, 50) if x not in nums)
        out.append({"draw_date": (d + timedelta(days=i)).isoformat(), "numbers": nums, "bonus": bonus})
    return out


def test_legacy_monte_carlo_weight_is_forced_to_zero_and_six_factors_sum_to_one():
    legacy = {
        "frequency": 0.18, "gap": 0.07, "structure": 0.28,
        "pairs": 0.10, "recent": 0.12, "region": 0.10,
        "monte_carlo": 0.15,
    }
    eff = normalize_main_weights(legacy)
    assert eff["monte_carlo"] == 0.0
    assert abs(sum(eff[k] for k in PREDICTIVE_FACTORS) - 1.0) < 1e-12
    assert abs(eff["structure"] / eff["frequency"] - 0.28 / 0.18) < 1e-12


def test_monte_carlo_input_weight_cannot_change_prediction_ranking():
    draws = _draws_649(36)
    w1 = dict(GAMES["649"].default_weights)
    w2 = dict(w1)
    w2["monte_carlo"] = 0.99
    a = PredictionEngine("649", draws, w1, seed=991).generate(candidate_count=220, top_n=6)
    b = PredictionEngine("649", draws, w2, seed=991).generate(candidate_count=220, top_n=6)
    assert [r["numbers"] for r in a] == [r["numbers"] for r in b]
    assert [r["score"] for r in a] == [r["score"] for r in b]
    assert all("monte_carlo_diagnostic" in r for r in a)


def test_max_can_use_official_calendar_state_not_only_schedule_fallback(tmp_path):
    db = Database(tmp_path / "cal.db")
    db.set_state("official_calendar_max", ["2026-04-14", "2026-04-17"])
    u = DataUpdater(db)
    dates, source = u._canonical_expected_dates("max", date(2026, 4, 17))
    assert source == "WCLC OFFICIAL ARCHIVE"
    assert dates == ["2026-04-14", "2026-04-17"]


def test_unexpected_rows_receive_explicit_classification(tmp_path):
    db = Database(tmp_path / "class.db")
    db.upsert_draw("max", "2026-04-14", "MAX_52", [1,2,3,4,5,6,7], 8, "official", verified=True)
    db.upsert_draw("max", "2026-04-15", "MAX_52", [1,2,3,4,5,6,7], 8, "bad recovery", verified=False)
    u = DataUpdater(db)
    u._canonical_expected_dates = lambda game_key, end_date=None: (["2026-04-14"], "WCLC OFFICIAL ARCHIVE")
    h = u.history_health("max")
    assert h["unexpected_classes"]["ADJACENT_DATE_DUPLICATE"] == 1
    assert h["unexpected_details"][0]["classification"] == "ADJACENT_DATE_DUPLICATE"
    assert "2026-04-15" in h["model_exclusions"]


def test_ablation_and_rank_stability_are_shadow_diagnostics():
    draws = _draws_649(38)
    weights = GAMES["649"].default_weights
    abl = feature_ablation_test("649", draws, weights, eval_draws=2, candidate_count=90, top_n=4, seed=120)
    assert abl["status"] == "ok"
    assert {x["factor"] for x in abl["factors"]} == set(PREDICTIVE_FACTORS)
    stab = rank_stability_test("649", draws, weights, transitions=2, candidate_count=100, top_n=5, seed=220)
    assert stab["status"] == "ok"
    assert stab["stability"] in {"LOW", "MEDIUM", "HIGH"}
    assert 0 <= stab["number_pool_jaccard_pct"] <= 100
