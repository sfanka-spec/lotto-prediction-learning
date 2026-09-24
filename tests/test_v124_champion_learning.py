from datetime import date

from lottery_ai.champion import build_match_diagnostics
from lottery_ai.db import Database
from lottery_ai.learning import LearningManager
from lottery_ai.presentation import build_current_draw_snapshot


def _pred(rank, numbers, score, base=50.0):
    return {
        "rank": rank,
        "numbers": numbers,
        "score": score,
        "components": {
            "frequency": base + rank * 0.2,
            "gap": base - rank * 0.1,
            "structure": base + rank * 0.3,
            "pairs": base - rank * 0.2,
            "recent": base + rank * 0.1,
            "region": base,
            "monte_carlo": 50.0,
        },
    }


def _screenshot_like_preds():
    # Mirrors the aggregate pattern visible for 2026-09-12:
    # #1=0/6, #2=2/6, #3=1/6, best=3/6, overall coverage=5/6.
    rows = [
        _pred(1, [2, 4, 6, 8, 10, 12], 79.0),
        _pred(2, [1, 3, 8, 10, 12, 14], 78.5),
        _pred(3, [17, 6, 8, 10, 12, 14], 78.0),
        _pred(4, [20, 32, 4, 6, 8, 10], 77.8),
        _pred(5, [1, 17, 4, 6, 8, 10], 77.6),
        _pred(6, [3, 20, 4, 6, 8, 10], 77.4),
        _pred(7, [3, 17, 20, 4, 6, 8], 77.2),
    ]
    # Fill to 20 without ever using 26, and without creating another 3-hit ticket.
    fillers = [
        [1, 2, 4, 6, 8, 10], [3, 2, 4, 6, 8, 10], [17, 2, 4, 6, 8, 10],
        [20, 2, 4, 6, 8, 10], [32, 2, 4, 6, 8, 10], [1, 20, 2, 4, 6, 8],
        [3, 32, 2, 4, 6, 8], [17, 32, 2, 4, 6, 8], [1, 32, 2, 4, 6, 8],
        [3, 17, 2, 4, 6, 8], [20, 32, 2, 4, 6, 8], [1, 3, 2, 4, 6, 8],
        [17, 20, 2, 4, 6, 8],
    ]
    for i, nums in enumerate(fillers, 8):
        rows.append(_pred(i, nums, 77.0 - 0.1 * (i - 8)))
    assert len(rows) == 20
    return rows


def test_champion_diagnostics_matches_requested_ranking_and_gap():
    draw = {"draw_date": "2026-09-12", "numbers": [1, 3, 17, 20, 26, 32], "bonus": 5}
    preds = _screenshot_like_preds()
    diag = build_match_diagnostics("649", preds, draw, [])

    assert diag["best_hit"] == 3
    assert diag["champion_ranks"] == [7]
    assert diag["leaderboard"][0]["rank"] == 7
    assert diag["leaderboard"][0]["matched_numbers"] == [3, 17, 20]
    assert diag["top_n_coverage"] == 5
    assert diag["covered_winners"] == [1, 3, 17, 20, 32]
    assert diag["missed_winners"] == [26]
    assert diag["selection_miss"] == 1
    assert diag["combination_gap"] == 2
    assert diag["bottleneck"] == "COMBINATION_CONCENTRATION"
    assert diag["production_impact"] == 0.0


def test_tie_order_uses_bonus_then_frozen_score():
    draw = {"draw_date": "2026-09-12", "numbers": [1, 3, 17, 20, 26, 32], "bonus": 5}
    preds = [
        _pred(1, [1, 3, 4, 6, 8, 10], 90.0),
        _pred(2, [17, 20, 4, 6, 8, 10], 80.0),
    ]
    payload = {
        "schema": "per_main_v1",
        "by_pick": [
            {"main_rank": 1, "main_numbers": preds[0]["numbers"], "ranking": [[7, 80.0], [5, 70.0]]},
            {"main_rank": 2, "main_numbers": preds[1]["numbers"], "ranking": [[5, 81.0], [7, 70.0]]},
        ],
    }
    diag = build_match_diagnostics("649", preds, draw, payload)
    assert [r["rank"] for r in diag["leaderboard"][:2]] == [2, 1]
    assert diag["leaderboard"][0]["bonus_hit"] is True


def test_backfill_existing_judgment_and_snapshot(tmp_path):
    db = Database(tmp_path / "lottery.db")
    draw = {"draw_date": "2026-09-12", "numbers": [1, 3, 17, 20, 26, 32], "bonus": 5}
    db.upsert_draw("649", draw["draw_date"], "649_CLASSIC", draw["numbers"], draw["bonus"], "test", verified=True)
    preds = _screenshot_like_preds()
    db.save_freeze("649", draw["draw_date"], "P1.0", "2026-09-09", preds, [], {})
    f = db.official_freeze("649", draw["draw_date"])
    # Simulate V1.2.3 having judged it before Champion Learning existed.
    hits = [len(set(draw["numbers"]) & set(p["numbers"])) for p in preds]
    db.save_judgment(f["id"], "649", draw["draw_date"], max(hits), sum(hits) / len(hits), 1.0, None, 36 / 49, {"hits": hits})

    lm = LearningManager(db)
    assert lm.backfill_champion_diagnostics("649", db.draws("649", era_only=True), limit=60) == 1
    assert lm.backfill_champion_diagnostics("649", db.draws("649", era_only=True), limit=60) == 0

    rec = db.champion_learning_for_date("649", draw["draw_date"], prefix="P")
    assert rec is not None
    assert rec["record"]["best_hit"] == 3
    assert rec["record"]["top_n_coverage"] == 5

    snap = build_current_draw_snapshot(db, "649", today=date(2026, 9, 12))
    assert snap["champion_ranks"] == [7]
    assert snap["match_leaders"][0]["rank"] == 7
    assert snap["champion_learning_saved"] is True
    assert snap["selection_miss"] == 1
    assert snap["combination_gap"] == 2
