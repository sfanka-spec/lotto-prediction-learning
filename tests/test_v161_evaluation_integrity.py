import math
import random
from statistics import mean, stdev

import pytest

from lottery_ai.analysis import paired_t_critical_95, paired_z_score
from lottery_ai.bayesian_strategy import hierarchical_strategy_posterior
from lottery_ai.config import APP_NAME, APP_VERSION, GAMES
from lottery_ai.db import Database
from lottery_ai.null_benchmark import portfolio_null_prefix_expectations
from lottery_ai.portfolio import (
    _core_pool, _exact_frontier_numpy, _exact_frontier_python, _number_mask,
    _pairwise_overlap, normalize_policy_weights,
)


def test_v161_identity_and_small_sample_t_fix():
    assert APP_NAME == "Lottery AI"
    assert APP_VERSION == "V1.6.6"
    diffs = [0.2, 0.8, 0.1, 1.0, -0.1, 0.7, 0.3, 0.9]
    expected = mean(diffs) / (stdev(diffs) / math.sqrt(len(diffs)))
    assert paired_z_score(diffs) == pytest.approx(expected)
    assert paired_t_critical_95(8) > 1.96


def test_cross_source_same_draw_variant_counts_once_forward_wins():
    historical = {
        "source": "historical", "game": "649", "draw_date": "D1",
        "strategy": "balanced", "lines": 5, "variant": "balanced@5",
        "best_hit_edge": -1.0,
    }
    forward = dict(historical, source="forward", best_hit_edge=1.0)
    result = hierarchical_strategy_posterior([historical, forward], "649")
    item = result["variants"]["balanced@5"]
    assert item["historical"]["n"] == 0
    assert item["forward"]["n"] == 1
    assert item["effective_n"] == 1.0
    assert item["observed_weighted_mean"] == 1.0


def test_self_null_conditions_on_each_portfolio_structure():
    dispersed = [
        {"numbers": [1, 2, 3, 4, 5, 6]},
        {"numbers": [7, 8, 9, 10, 11, 12]},
        {"numbers": [13, 14, 15, 16, 17, 18]},
    ]
    concentrated = [
        {"numbers": [1, 2, 3, 4, 5, 6]},
        {"numbers": [1, 2, 3, 4, 7, 8]},
        {"numbers": [1, 2, 3, 4, 9, 10]},
    ]
    a = portfolio_null_prefix_expectations("649", dispersed, (3,))[3]
    b = portfolio_null_prefix_expectations("649", concentrated, (3,))[3]
    assert a["avg_hit"] == b["avg_hit"]  # same fixed ticket-level expectation
    assert a["coverage"] > b["coverage"]  # structure is explicitly conditioned on
    assert a["unique_numbers"] > b["unique_numbers"]


def test_db_judgment_is_unique_and_freeze_payload_is_immutable(tmp_path):
    db = Database(tmp_path / "lottery.db")
    freeze_id = db.save_freeze("649", "2026-09-19", "P1.0", "2026-09-16",
                               [{"numbers": [1,2,3,4,5,6]}], [], {"role": "production"})
    db.save_judgment(freeze_id, "649", "2026-09-19", 1, 0.5, 0.5, None, 0.7, {"v": 1})
    db.save_judgment(freeze_id, "649", "2026-09-19", 2, 0.8, 0.8, None, 0.7, {"v": 2})
    with db.connect() as con:
        rows = con.execute("SELECT * FROM judgments WHERE freeze_id=?", (freeze_id,)).fetchall()
        assert len(rows) == 1
        assert rows[0]["best_hit"] == 2
        with pytest.raises(Exception):
            con.execute("UPDATE freezes SET predictions_json='[]' WHERE id=?", (freeze_id,))
    assert db.verify_freeze_ledger()["ok"] is True


def _frontier_inputs(seed=161, n=10):
    rng = random.Random(seed)
    cfg = GAMES["649"]
    rows = []
    seen = set()
    while len(rows) < n:
        nums = tuple(sorted(rng.sample(range(1, cfg.max_number + 1), cfg.pick)))
        if nums in seen:
            continue
        seen.add(nums)
        rows.append({"rank": len(rows) + 1, "numbers": list(nums), "score": rng.uniform(40, 90)})
    masks = [_number_mask(r["numbers"]) for r in rows]
    overlaps = _pairwise_overlap(rows)
    core = _core_pool(rows, cfg)
    scores = [r["score"] for r in rows]
    lo, hi = min(scores), max(scores)
    denom = hi - lo or 1.0
    qualities = [0.15 + 0.85 * ((x - lo) / denom) for x in scores]
    rankvals = [0.10 + 0.90 * ((n - (i + 1)) / (n - 1)) for i in range(n)]
    corevals = [len(set(r["numbers"]) & core) / cfg.pick for r in rows]
    return cfg, masks, overlaps, core, qualities, rankvals, corevals


def test_numpy_frontier_matches_reference_exact_oracle():
    cfg, masks, overlaps, core, q, rv, cv = _frontier_inputs()
    weights = normalize_policy_weights(None)
    core_mask = _number_mask(core)
    py = _exact_frontier_python(masks, overlaps, core_mask, len(core), q, rv, cv, 10, cfg, weights)
    npv = _exact_frontier_numpy(masks, overlaps, core_mask, len(core), q, rv, cv, 10, cfg, weights)
    assert npv is not None
    assert {k: row[1] for k, row in py.items()} == {k: row[1] for k, row in npv.items()}


def test_explicit_data_path_wins_even_if_local_database_exists(tmp_path, monkeypatch):
    from lottery_ai.paths import resolve_data_dir
    app_base = tmp_path / "build"
    local = app_base / "data"
    local.mkdir(parents=True)
    (local / "lottery.db").write_bytes(b"x" * 4096)
    explicit = tmp_path / "explicit_data"
    monkeypatch.setenv("LOTTERY_AI_DATA", str(explicit))
    assert resolve_data_dir(app_base) == explicit.resolve()


def test_existing_local_database_wins_over_legacy_discovery(tmp_path, monkeypatch):
    from lottery_ai.paths import resolve_data_dir
    monkeypatch.delenv("LOTTERY_AI_DATA", raising=False)
    app_base = tmp_path / "Lottery_AI_V1.6.1"
    local = app_base / "data"
    local.mkdir(parents=True)
    (local / "lottery.db").write_bytes(b"local")
    legacy = tmp_path / "Old_Lottery_AI_V1.5" / "data"
    legacy.mkdir(parents=True)
    (legacy / "lottery.db").write_bytes(b"legacy" * 10000)
    assert resolve_data_dir(app_base) == local.resolve()


def test_old_unequal_budget_pc_evidence_is_excluded(tmp_path):
    db = Database(tmp_path / "lottery.db")
    target = "2026-09-19"
    p = db.save_freeze("649", target, "P1.0", "2026-09-16",
                       [{"numbers": [1,2,3,4,5,6]}], [], {"role": "production"})
    c = db.save_freeze("649", target, "C1.0", "2026-09-16",
                       [{"numbers": [7,8,9,10,11,12]}], [], {"role": "challenger"})
    db.save_judgment(p, "649", target, 1, 0.5, 0.5, None, 0.7, {})
    db.save_judgment(c, "649", target, 1, 0.6, 0.6, None, 0.7, {})
    assert db.paired_model_performance("649") == []
