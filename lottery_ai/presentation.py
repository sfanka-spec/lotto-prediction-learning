from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from .bonus import normalize_bonus_payload, bonus_top_for_pick
from .config import GAMES
from .champion import build_match_diagnostics

BC_TZ = ZoneInfo("America/Vancouver")


def bc_now() -> datetime:
    return datetime.now(BC_TZ)


def bc_today() -> date:
    return bc_now().date()


def format_bc_timestamp(value) -> str:
    """Format DB UTC/ISO timestamps in BC lottery time, preserving timezone label."""
    if not value:
        return ""
    try:
        text = str(value).strip()
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        local = dt.astimezone(BC_TZ)
        return local.strftime("%Y-%m-%d %H:%M:%S %Z")
    except Exception:
        return str(value)


def next_scheduled_on_or_after(game_key: str, start: date) -> date:
    weekdays = set(GAMES[game_key].draw_weekdays)
    d = start
    for _ in range(8):
        if d.weekday() in weekdays:
            return d
        d += timedelta(days=1)
    return d


def _load_freeze_payload(freeze):
    if not freeze:
        return [], {}
    try:
        preds = json.loads(freeze.get("predictions_json") or "[]")
    except Exception:
        preds = []
    try:
        raw_bonus = json.loads(freeze.get("bonus_rank_json") or "[]")
    except Exception:
        raw_bonus = []
    return preds, normalize_bonus_payload(raw_bonus, preds)


def build_current_draw_snapshot(db, game_key: str, today: date | None = None) -> dict:
    """Build a read-only UI snapshot for today's draw or the next scheduled draw.

    This never generates, changes or backfills a prediction. If a historical frozen
    prediction used the legacy Pick-#1-only Bonus schema, missing per-pick Bonus data
    stays missing so post-draw information can never leak backward into the freeze.
    """
    today = today or bc_today()
    cfg = GAMES[game_key]
    focus = next_scheduled_on_or_after(game_key, today)
    scheduled_today = focus == today
    result = db.draw_by_date(game_key, focus.isoformat())
    freeze = db.official_freeze(game_key, focus.isoformat())
    preds, bonus_payload = _load_freeze_payload(freeze)
    try:
        freeze_ctx = json.loads((freeze or {}).get("factor_context_json") or "{}")
    except Exception:
        freeze_ctx = {}

    snap = {
        "draw_date": focus.isoformat(),
        "scheduled_today": scheduled_today,
        "status": "NEXT_DRAW_WAITING",
        "result": result,
        "verified": bool(result and result.get("verified")),
        "prediction_locked": bool(freeze),
        "freeze_created": format_bc_timestamp(freeze.get("created_at")) if freeze else "",
        "freeze_id": int(freeze.get("id")) if freeze and freeze.get("id") is not None else None,
        "freeze_model_version": (freeze or {}).get("model_version"),
        "freeze_prediction_sha256": ((freeze_ctx.get("integrity") or {}).get("prediction_sha256")),
        "snapshot_consistency": "OK",
        "prediction_count": len(preds),
        "top3": [],
        "best_hit": None,
        "top_n_coverage": None,
        "top_n": len(preds),
        "champion_ranks": [],
        "champions": [],
        "match_leaders": [],
        "covered_winners": [],
        "missed_winners": [],
        "selection_miss": None,
        "combination_gap": None,
        "winner_concentration_efficiency": None,
        "bottleneck": None,
        "champion_best_original_rank": None,
        "champion_score_percentile": None,
        "score_hit_spearman": None,
        "ranking_diagnosis": None,
        "stage_diagnosis": {},
        "ticket_slots": None,
        "portfolio_unique_numbers": None,
        "number_pool_size": cfg.max_number,
        "portfolio_number_pool_pct": None,
        "rank_concentration": {},
        "candidate_number_ranking": {},
        "champion_learning_saved": False,
        "bonus_schema_legacy": bool(bonus_payload.get("legacy")),
    }
    if result:
        snap["status"] = "VERIFIED_RESULT" if result.get("verified") else "UNVERIFIED_RESULT"
    elif scheduled_today:
        snap["status"] = "AWAITING_OFFICIAL_RESULT"
    elif freeze:
        snap["status"] = "PREDICTION_LOCKED"

    if not (result and preds):
        return snap

    actual = set(int(n) for n in result.get("numbers") or [])
    actual_bonus = result.get("bonus")
    hits = []
    union = set()
    for pred in preds:
        rank = int(pred.get("rank", len(hits) + 1))
        nums = [int(n) for n in pred.get("numbers") or []]
        union.update(nums)
        main_hits = len(actual & set(nums))
        hits.append(main_hits)
        if rank <= 3:
            top_bonus = bonus_top_for_pick(bonus_payload, rank, preds)
            bonus_hit = None if top_bonus is None or actual_bonus is None else int(top_bonus) == int(actual_bonus)
            snap["top3"].append({
                "rank": rank,
                "main_hits": main_hits,
                "pick_size": cfg.pick,
                "top_bonus": top_bonus,
                "bonus_hit": bonus_hit,
            })
    diag = build_match_diagnostics(
        game_key, preds, result, bonus_payload,
        candidate_number_profile=freeze_ctx.get("candidate_number_profile"),
    )
    snap["best_hit"] = diag.get("best_hit")
    snap["top_n_coverage"] = diag.get("top_n_coverage")
    snap["ticket_slots"] = diag.get("ticket_slots")
    snap["portfolio_unique_numbers"] = diag.get("portfolio_unique_numbers")
    snap["number_pool_size"] = diag.get("number_pool_size") or cfg.max_number
    snap["portfolio_number_pool_pct"] = diag.get("portfolio_number_pool_pct")
    snap["rank_concentration"] = diag.get("rank_concentration") or {}
    snap["candidate_number_ranking"] = diag.get("candidate_number_ranking") or {}
    snap["champion_ranks"] = diag.get("champion_ranks") or []
    snap["champions"] = diag.get("champions") or []
    snap["match_leaders"] = (diag.get("leaderboard") or [])[:5]
    snap["covered_winners"] = diag.get("covered_winners") or []
    snap["missed_winners"] = diag.get("missed_winners") or []
    snap["selection_miss"] = diag.get("selection_miss")
    snap["combination_gap"] = diag.get("combination_gap")
    snap["winner_concentration_efficiency"] = diag.get("winner_concentration_efficiency")
    snap["bottleneck"] = diag.get("bottleneck")
    snap["champion_best_original_rank"] = diag.get("champion_best_original_rank")
    snap["champion_score_percentile"] = diag.get("champion_score_percentile")
    snap["score_hit_spearman"] = diag.get("score_hit_spearman")
    snap["ranking_diagnosis"] = diag.get("ranking_diagnosis")
    snap["stage_diagnosis"] = diag.get("stage_diagnosis") or {}
    try:
        saved = db.champion_learning_for_date(game_key, focus.isoformat(), prefix="P")
    except Exception:
        saved = None
    if saved and freeze and int(saved.get("freeze_id", -1)) != int(freeze.get("id", -2)):
        snap["snapshot_consistency"] = "CHAMPION_FREEZE_MISMATCH"
        snap["champion_learning_saved"] = False
    else:
        snap["champion_learning_saved"] = bool(saved)
    return snap
