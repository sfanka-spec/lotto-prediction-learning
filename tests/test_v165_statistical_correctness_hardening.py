from __future__ import annotations

import math
import os
import random
from pathlib import Path
from types import SimpleNamespace

import pytest

from lottery_ai.analysis import FeatureEngine, paired_t_critical_95
from lottery_ai.config import APP_VERSION, GAMES
from lottery_ai.engine import PredictionEngine
from lottery_ai.fastmath import mean as fast_mean, pstdev as fast_pstdev
from lottery_ai.models import _trusted_pickle_load, _trusted_pickle_save
from lottery_ai.providers import resilient_get
from lottery_ai.updater import DataUpdater


def _draw(date, numbers, bonus):
    return {"draw_date": date, "numbers": numbers, "bonus": bonus}


def test_v165_version():
    assert APP_VERSION == "V1.6.5"


def test_fastmath_matches_float_statistics_and_supports_generators():
    values = [1.25, 2.5, 5.75, -3.0, 11.125]
    expected_mean = sum(values) / len(values)
    expected_sd = math.sqrt(sum((x - expected_mean) ** 2 for x in values) / len(values))
    assert fast_mean(values) == pytest.approx(expected_mean, abs=1e-15)
    assert fast_pstdev(values) == pytest.approx(expected_sd, abs=1e-15)
    assert fast_mean((x for x in values)) == pytest.approx(expected_mean, abs=1e-15)
    assert fast_pstdev((x for x in values)) == pytest.approx(expected_sd, abs=1e-15)


def test_t_critical_is_smooth_after_df_120():
    # n=121 -> df=120 exact table value; n=122 -> df=121 asymptotic expansion.
    at_120 = paired_t_critical_95(121)
    at_121 = paired_t_critical_95(122)
    at_200 = paired_t_critical_95(201)
    assert at_120 == pytest.approx(1.980, abs=1e-12)
    assert 1.979 < at_121 < 1.980
    assert abs(at_120 - at_121) < 0.001
    assert 1.971 < at_200 < 1.973


def test_pair_lift_uses_without_replacement_correction():
    draws = [
        _draw("2026-01-01", [1, 2, 3, 4, 5, 6], 7),
        _draw("2026-01-02", [1, 2, 8, 9, 10, 11], 12),
        _draw("2026-01-03", [1, 3, 13, 14, 15, 16], 17),
        _draw("2026-01-04", [2, 3, 18, 19, 20, 21], 22),
    ]
    f = FeatureEngine("649", draws)
    obs = 2  # pair (1,2) appears in first two draws
    n = 4
    pa = 3 / n
    pb = 3 / n
    k = GAMES["649"].pick
    M = GAMES["649"].max_number
    corr = (k - 1) * M / (k * (M - 1))
    expected = n * pa * pb * corr
    raw_lift = obs / expected
    shrink = obs / (obs + 12)
    expected_shrunk = 1 + shrink * (raw_lift - 1)
    assert f.pair_lift[(1, 2)] == pytest.approx(expected_shrunk, rel=1e-12)


def test_historical_structure_constants_are_precomputed():
    draws = [
        _draw("2026-01-01", [1, 5, 10, 20, 30, 40], 41),
        _draw("2026-01-02", [2, 7, 12, 21, 31, 45], 46),
        _draw("2026-01-03", [3, 8, 14, 22, 33, 47], 48),
    ]
    f = FeatureEngine("649", draws)
    assert f._gap_var_mu == pytest.approx(fast_mean(f.hist_gap_var))
    assert f._gap_var_sd == pytest.approx(fast_pstdev(f.hist_gap_var) or 1.0)
    assert f._joint_modal == max(f.joint_region_counts.values())


def test_candidate_generation_caps_to_legal_universe():
    class FakeFeatures:
        def component_scores(self, combo):
            return {"frequency": float(sum(combo)), "monte_carlo": 50.0}

    eng = PredictionEngine.__new__(PredictionEngine)
    eng.cfg = SimpleNamespace(max_number=5, pick=4)
    eng.features = FakeFeatures()
    eng.weights = {"frequency": 1.0, "monte_carlo": 0.0}
    eng.rng = random.Random(7)
    eng.game_key = "tiny"
    rows = eng._scored_candidates(candidate_count=100)
    assert len(rows) == math.comb(5, 4)
    assert eng.last_candidate_generation["target"] == 5
    assert eng.last_candidate_generation["generated"] == 5
    assert not eng.last_candidate_generation["guard_triggered"]


def test_csv_import_accepts_gb18030_and_counts_skipped(tmp_path):
    csv_text = (
        "date,num1,num2,num3,num4,num5,num6,bonus,备注\n"
        "2026-09-16,1,2,3,4,5,6,7,有效\n"
        "bad-date,1,2,3,4,5,6,7,无效\n"
    )
    path = tmp_path / "history_gbk.csv"
    path.write_bytes(csv_text.encode("gb18030"))

    updater = DataUpdater.__new__(DataUpdater)
    updater._merge_history_records = lambda game_key, rows: {"added": len(rows), "updated": 0}
    updater.audit_history = lambda game_key: {"percent": 100.0}
    result = updater.import_history_csv("649", path)
    assert result["encoding"] == "gb18030"
    assert result["skipped"] == 1
    assert result["added"] == 1
    assert "1 row(s) skipped" in result["message"]


def test_resilient_get_retries_429_and_honors_retry_after(monkeypatch):
    class Response:
        def __init__(self, status, headers=None):
            self.status_code = status
            self.headers = headers or {}

    class Session:
        def __init__(self):
            self.calls = 0
        def get(self, *args, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return Response(429, {"Retry-After": "0"})
            return Response(200)

    sleeps = []
    monkeypatch.setattr("lottery_ai.providers.time.sleep", sleeps.append)
    session = Session()
    response = resilient_get(session, "https://example.invalid", retries=2)
    assert response.status_code == 200
    assert session.calls == 2
    assert sleeps == [0.0]


def test_atomic_snapshot_rolls_back_if_sidecar_replace_fails(tmp_path, monkeypatch):
    path = tmp_path / "model.pkl"
    _trusted_pickle_save(path, {"version": "old"})
    real_replace = os.replace
    calls = {"n": 0}

    def fail_second_replace(src, dst):
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError("simulated sidecar replace failure")
        return real_replace(src, dst)

    monkeypatch.setattr("lottery_ai.models.os.replace", fail_second_replace)
    with pytest.raises(OSError):
        _trusted_pickle_save(path, {"version": "new"})
    assert _trusted_pickle_load(path) == {"version": "old"}


def test_pacific_time_fails_loudly_without_zoneinfo(monkeypatch):
    import sys
    from lottery_ai.timeutil import pacific_now

    monkeypatch.setitem(sys.modules, "zoneinfo", None)
    with pytest.raises(RuntimeError, match="Pacific timezone data is unavailable"):
        pacific_now()


def test_small_pool_monte_carlo_fallback_uses_fresh_reference_samples():
    class FakeFeatures:
        def component_scores(self, combo):
            return {"frequency": float(sum(combo) % 37), "monte_carlo": 50.0}

    class RecordingRng:
        def __init__(self, seed):
            self.inner = random.Random(seed)
            self.reference_samples = []
        def sample(self, population, k):
            out = self.inner.sample(population, k)
            if population and isinstance(population[0], dict):
                self.reference_samples.append(tuple(tuple(r["numbers"]) for r in out))
            return out
        def shuffle(self, values):
            return self.inner.shuffle(values)

    eng = PredictionEngine.__new__(PredictionEngine)
    eng.cfg = GAMES["649"]
    eng.features = FakeFeatures()
    eng.weights = {"frequency": 1.0, "monte_carlo": 0.0}
    eng.rng = RecordingRng(12345)
    eng.game_key = "649"
    rows = eng._scored_candidates(candidate_count=900)
    assert len(rows) == 900
    # At 900 candidates the old implementation reused the exact same first block
    # three times. V1.6.5 creates three fresh seeded 200-row reference samples.
    assert len(eng.rng.reference_samples) == 3
    assert len(set(eng.rng.reference_samples)) == 3


def test_safe_worker_resets_transient_card_state_before_error_popup(monkeypatch):
    import app as app_module

    order = []
    class Card:
        def refresh(self):
            order.append("refresh")

    shell = SimpleNamespace(
        game_state={"649": {"status": "Running…"}, "max": {"status": "Updating data…"}},
        cards={"649": Card(), "max": Card()},
    )
    shell.after = lambda delay, callback: callback()
    monkeypatch.setattr(app_module.messagebox, "showerror", lambda *args, **kwargs: order.append("error"))

    def fail():
        raise RuntimeError("boom")

    app_module.LotteryApp._safe_worker(shell, fail)
    assert shell.game_state["649"]["status"] == "Ready"
    assert shell.game_state["max"]["status"] == "Ready"
    assert order[-1] == "error"
    assert order[:-1] == ["refresh", "refresh"]


def test_update_pipeline_marks_header_failed_before_reraising():
    import app as app_module

    events = []
    class Updater:
        def update_all(self):
            raise RuntimeError("network down")

    shell = SimpleNamespace(updater=Updater())
    shell._set_global_status = lambda text: events.append(("global", text))
    shell._refresh_update_status = lambda status, finished: events.append(("header", status))
    shell._ui_call = lambda callback: callback()

    with pytest.raises(RuntimeError, match="network down"):
        app_module.LotteryApp._update_pipeline_body(shell)
    assert events == [
        ("global", "Updating data…"),
        ("header", "UPDATING"),
        ("header", "FAILED"),
    ]


def test_pair_lift_centres_near_one_on_seeded_fair_random_history():
    import statistics

    rng = random.Random(20260919)
    draws = []
    for i in range(1500):
        nums = sorted(rng.sample(range(1, 50), 6))
        bonus = next(n for n in range(1, 50) if n not in nums)
        draws.append({"draw_date": "2000-01-01", "numbers": nums, "bonus": bonus})
    f = FeatureEngine("649", draws)
    avg = statistics.mean(f.pair_lift.values())
    assert 0.98 <= avg <= 1.04
