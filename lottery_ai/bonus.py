from __future__ import annotations

from typing import Any, Callable

BONUS_PAYLOAD_SCHEMA = "per_main_v1"
BONUS_SCORE_NAME = "Bonus Conditional Score"
MAIN_SCORE_NAME = "Combination Score"


def _normalize_ranking(ranking: Any) -> list[list[float]]:
    out: list[list[float]] = []
    for item in ranking or []:
        try:
            if isinstance(item, dict):
                number = int(item.get("number"))
                score = float(item.get("score", 0.0))
            else:
                number = int(item[0])
                score = float(item[1])
            out.append([number, round(score, 2)])
        except Exception:
            continue
    return out


def build_bonus_payload(
    predictions: list[dict],
    ranker: Callable[[list[int] | tuple[int, ...], int], list],
    limit: int = 10,
) -> dict:
    """Build a conditional Bonus ranking for every Main combination.

    The Bonus ranker is deliberately injected and never contributes to the Main
    optimizer. Main numbers are defensively excluded here even if the ranker
    already excludes them. The returned JSON is database-schema compatible with
    V1.1.0; only optional metadata fields are added.
    """
    by_pick = []
    for fallback_rank, pred in enumerate(predictions or [], 1):
        rank = int(pred.get("rank", fallback_rank))
        main = [int(n) for n in pred.get("numbers", [])]
        main_set = set(main)
        raw = ranker(main, max(limit + len(main), limit))
        ranking = [row for row in _normalize_ranking(raw) if int(row[0]) not in main_set]
        seen = set()
        clean = []
        for number, score in ranking:
            if number in seen or number in main_set:
                continue
            seen.add(number)
            clean.append([int(number), round(float(score), 2)])
            if len(clean) >= limit:
                break
        by_pick.append({
            "main_rank": rank,
            "main_numbers": main,
            "ranking": clean,
        })
    return {
        "schema": BONUS_PAYLOAD_SCHEMA,
        "score_name": BONUS_SCORE_NAME,
        "main_score_name": MAIN_SCORE_NAME,
        "ranking_limit": int(limit),
        "by_pick": by_pick,
    }


def normalize_bonus_payload(payload: Any, predictions: list[dict] | None = None) -> dict:
    """Normalize V1.1 per-main payloads and legacy V1.0.x Pick-#1-only lists.

    Normalization never invents missing bindings. This is important because an
    official frozen prediction must remain immutable after its data cutoff.
    """
    if isinstance(payload, dict) and payload.get("schema") == BONUS_PAYLOAD_SCHEMA:
        by_pick = []
        for item in payload.get("by_pick") or []:
            try:
                rank = int(item.get("main_rank"))
            except Exception:
                continue
            main = [int(n) for n in item.get("main_numbers") or []]
            ranking = _normalize_ranking(item.get("ranking") or [])
            by_pick.append({"main_rank": rank, "main_numbers": main, "ranking": ranking})
        # Keep duplicate ranks in the normalized form so the integrity audit can
        # detect them; sorting alone does not collapse or hide corruption.
        by_pick.sort(key=lambda x: x["main_rank"])
        return {
            "schema": BONUS_PAYLOAD_SCHEMA,
            "score_name": payload.get("score_name") or BONUS_SCORE_NAME,
            "main_score_name": payload.get("main_score_name") or MAIN_SCORE_NAME,
            "ranking_limit": payload.get("ranking_limit"),
            "by_pick": by_pick,
            "legacy": False,
        }

    legacy_ranking = _normalize_ranking(payload if isinstance(payload, list) else [])
    if legacy_ranking:
        main = []
        if predictions:
            main = [int(n) for n in predictions[0].get("numbers", [])]
        return {
            "schema": BONUS_PAYLOAD_SCHEMA,
            "score_name": BONUS_SCORE_NAME,
            "main_score_name": MAIN_SCORE_NAME,
            "ranking_limit": len(legacy_ranking),
            "by_pick": [{"main_rank": 1, "main_numbers": main, "ranking": legacy_ranking}],
            "legacy": True,
        }
    return {
        "schema": BONUS_PAYLOAD_SCHEMA,
        "score_name": BONUS_SCORE_NAME,
        "main_score_name": MAIN_SCORE_NAME,
        "ranking_limit": None,
        "by_pick": [],
        "legacy": False,
    }


def bonus_entry_for_pick(payload: Any, main_rank: int, predictions: list[dict] | None = None) -> dict | None:
    norm = normalize_bonus_payload(payload, predictions)
    for item in norm.get("by_pick") or []:
        if int(item.get("main_rank", -1)) == int(main_rank):
            return item
    return None


def bonus_top_for_pick(payload: Any, main_rank: int, predictions: list[dict] | None = None) -> int | None:
    """Return the frozen top Bonus for one Main Pick without backfilling anything."""
    entry = bonus_entry_for_pick(payload, main_rank, predictions)
    ranking = (entry or {}).get("ranking") or []
    return int(ranking[0][0]) if ranking else None


def main_bonus_consistency(
    predictions: list[dict],
    payload: Any,
    max_number: int | None = None,
    expected_limit: int | None = None,
) -> dict:
    """Audit Main↔Bonus binding integrity without changing frozen data.

    Checks include:
      * one binding per Main rank
      * binding's stored Main numbers exactly match the frozen Main combination
      * no Bonus candidate appears inside its bound Main combination
      * Bonus candidates are unique and (optionally) within the legal number pool
      * every Main Pick has a frozen Bonus binding for V1.1 payloads

    Legacy V1.0.x Pick-#1-only payloads are reported as PARTIAL rather than FAIL.
    """
    norm = normalize_bonus_payload(payload, predictions)
    pred_map = {
        int(p.get("rank", i)): tuple(int(n) for n in p.get("numbers", []))
        for i, p in enumerate(predictions or [], 1)
    }
    errors: list[dict] = []
    warnings: list[dict] = []
    checked_bindings = 0
    missing_bindings: list[int] = []
    bound_ranks: set[int] = set()
    seen_ranks: set[int] = set()

    for item in norm.get("by_pick") or []:
        rank = int(item.get("main_rank", -1))
        if rank in seen_ranks:
            errors.append({"main_rank": rank, "reason": "duplicate_main_binding"})
        seen_ranks.add(rank)
        bound_ranks.add(rank)

        stored_main = tuple(int(n) for n in item.get("main_numbers") or [])
        expected_main = pred_map.get(rank)
        if expected_main is None:
            errors.append({"main_rank": rank, "reason": "unexpected_main_rank"})
            main_set = set(stored_main)
        else:
            main_set = set(expected_main)
            if stored_main and stored_main != expected_main:
                errors.append({
                    "main_rank": rank,
                    "reason": "main_numbers_mismatch",
                    "stored_main": list(stored_main),
                    "expected_main": list(expected_main),
                })

        seen_bonus: set[int] = set()
        ranking = item.get("ranking") or []
        for number, _score in ranking:
            number = int(number)
            checked_bindings += 1
            if number in seen_bonus:
                errors.append({"main_rank": rank, "bonus": number, "reason": "duplicate_bonus_candidate"})
            seen_bonus.add(number)
            if number in main_set:
                errors.append({"main_rank": rank, "bonus": number, "reason": "bonus_in_main"})
            if max_number is not None and not (1 <= number <= int(max_number)):
                errors.append({"main_rank": rank, "bonus": number, "reason": "bonus_out_of_range"})

        if expected_limit is not None and expected_main is not None and len(ranking) < int(expected_limit):
            warnings.append({
                "main_rank": rank,
                "reason": "short_bonus_ranking",
                "count": len(ranking),
                "expected": int(expected_limit),
            })

    for rank in sorted(pred_map):
        if rank not in bound_ranks:
            missing_bindings.append(rank)

    status = "FAIL" if errors else ("PARTIAL" if missing_bindings else "PASS")
    return {
        "status": status,
        "errors": errors,
        "warnings": warnings,
        "checked_bindings": checked_bindings,
        "bound_main_picks": len(bound_ranks & set(pred_map)),
        "total_main_picks": len(pred_map),
        "missing_bindings": missing_bindings,
        "legacy": bool(norm.get("legacy")),
        "score_name": norm.get("score_name") or BONUS_SCORE_NAME,
    }


def sanitize_and_complete_bonus_payload(
    predictions: list[dict],
    payload: Any,
    ranker: Callable[[list[int] | tuple[int, ...], int], list],
    limit: int = 10,
) -> dict:
    """Repair a *pre-freeze* payload without changing Main combinations.

    This helper remains for generation/tests and explicit migration tooling. It
    must NOT be used to silently rewrite or enrich an already frozen official
    prediction, because doing so would mix post-cutoff information into history.
    """
    norm = normalize_bonus_payload(payload, predictions)
    old = {int(x.get("main_rank", -1)): x for x in norm.get("by_pick") or []}
    derived = build_bonus_payload(predictions, ranker, limit=max(limit, 10))
    fresh = {int(x.get("main_rank", -1)): x for x in derived.get("by_pick") or []}
    out = []
    repaired = 0
    completed = 0
    for fallback_rank, pred in enumerate(predictions or [], 1):
        rank = int(pred.get("rank", fallback_rank))
        main = set(int(n) for n in pred.get("numbers", []))
        existing = old.get(rank)
        clean = []
        seen = set()
        if existing:
            for number, score in _normalize_ranking(existing.get("ranking") or []):
                if number in main:
                    repaired += 1
                    continue
                if number in seen:
                    continue
                seen.add(number)
                clean.append([number, score])
                if len(clean) >= limit:
                    break
        else:
            completed += 1
        for number, score in (fresh.get(rank, {}).get("ranking") or []):
            number = int(number)
            if number in main or number in seen:
                continue
            seen.add(number)
            clean.append([number, round(float(score), 2)])
            if len(clean) >= limit:
                break
        out.append({"main_rank": rank, "main_numbers": [int(n) for n in pred.get("numbers", [])], "ranking": clean})
    return {
        "schema": BONUS_PAYLOAD_SCHEMA,
        "score_name": BONUS_SCORE_NAME,
        "main_score_name": MAIN_SCORE_NAME,
        "ranking_limit": int(limit),
        "by_pick": out,
        "legacy": bool(norm.get("legacy")),
        "auto_reselected": repaired,
        "completed_bindings": completed,
    }
