from __future__ import annotations

from statistics import mean, median

from .bonus import bonus_top_for_pick, normalize_bonus_payload
from .config import GAMES, PREDICTIVE_FACTORS

CHAMPION_SCHEMA_VERSION = "CHAMP1.7"
CHAMPION_CALIBRATION_MIN_SAMPLES = 30


def classify_rank_association(value: float | int | None) -> str:
    """Descriptive per-draw Spearman label; this is not a significance test."""
    rho = _safe_float(value, 0.0)
    if abs(rho) < 0.10:
        return "NEUTRAL"
    if 0.10 <= rho < 0.30:
        return "WEAK_POSITIVE"
    if -0.30 < rho <= -0.10:
        return "WEAK_NEGATIVE"
    return "POSITIVE" if rho >= 0.30 else "NEGATIVE"


def _placement_stage(diagnosis: str | None) -> str:
    if diagnosis == "WELL_RANKED":
        return "GOOD"
    if diagnosis == "UNDER_RANKED":
        return "WEAK"
    return "MIXED"


def _combined_ranking_stage(placement: str, association: str) -> str:
    """Backward-compatible single summary without overstating one good placement."""
    positive = association in {"WEAK_POSITIVE", "POSITIVE"}
    negative = association in {"WEAK_NEGATIVE", "NEGATIVE"}
    if placement == "GOOD" and positive:
        return "GOOD"
    if placement == "WEAK" and negative:
        return "WEAK"
    return "MIXED"


def _rankdata(values: list[float]) -> list[float]:
    """Average ranks for ties; ascending values receive smaller ranks."""
    indexed = sorted(enumerate(values), key=lambda x: (x[1], x[0]))
    ranks = [0.0] * len(values)
    i = 0
    while i < len(indexed):
        j = i + 1
        while j < len(indexed) and indexed[j][1] == indexed[i][1]:
            j += 1
        avg_rank = (i + 1 + j) / 2.0
        for k in range(i, j):
            ranks[indexed[k][0]] = avg_rank
        i = j
    return ranks


def _pearson(xs: list[float], ys: list[float]) -> float:
    if len(xs) < 3 or len(xs) != len(ys):
        return 0.0
    mx, my = mean(xs), mean(ys)
    dx = [x - mx for x in xs]
    dy = [y - my for y in ys]
    sx = sum(x * x for x in dx) ** 0.5
    sy = sum(y * y for y in dy) ** 0.5
    if sx == 0 or sy == 0:
        return 0.0
    return sum(a * b for a, b in zip(dx, dy)) / (sx * sy)


def _spearman(xs: list[float], ys: list[float]) -> float:
    if len(xs) < 3 or len(xs) != len(ys):
        return 0.0
    return _pearson(_rankdata(xs), _rankdata(ys))


def _ranking_metrics(rows: list[dict], champions: list[dict]) -> dict:
    if not rows or not champions:
        return {
            "champion_best_original_rank": None,
            "champion_score_percentile": None,
            "score_hit_spearman": 0.0,
            "ranking_diagnosis": "NO_DATA",
        }
    best_champion = sorted(champions, key=lambda r: (int(r.get("rank", 999999)), -float(r.get("score", 0.0))))[0]
    best_rank = int(best_champion.get("rank", 0) or 0)
    champion_score = float(best_champion.get("score", 0.0) or 0.0)
    scores = [float(r.get("score", 0.0) or 0.0) for r in rows]
    hits = [float(r.get("main_hits", 0.0) or 0.0) for r in rows]
    percentile = 100.0 * sum(v <= champion_score for v in scores) / max(1, len(scores))
    rho = _spearman(scores, hits)
    n = len(rows)
    top_quarter = max(3, int((n + 3) // 4))
    if best_rank <= top_quarter:
        diagnosis = "WELL_RANKED"
    elif best_rank <= max(1, n // 2):
        diagnosis = "MID_RANKED"
    else:
        diagnosis = "UNDER_RANKED"
    by_rank = sorted(rows, key=lambda r: int(r.get("rank", 999999)))
    top5 = by_rank[:5]
    top10 = by_rank[:10]
    bottom10 = by_rank[-10:] if len(by_rank) >= 10 else by_rank
    return {
        "champion_best_original_rank": best_rank,
        "champion_score_percentile": round(percentile, 3),
        "score_hit_spearman": round(rho, 6),
        "top5_mean_hit": round(mean(float(r.get("main_hits", 0)) for r in top5), 6) if top5 else 0.0,
        "top10_mean_hit": round(mean(float(r.get("main_hits", 0)) for r in top10), 6) if top10 else 0.0,
        "bottom10_mean_hit": round(mean(float(r.get("main_hits", 0)) for r in bottom10), 6) if bottom10 else 0.0,
        "ranking_diagnosis": diagnosis,
    }

def _safe_float(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return float(default)


def _structure_metrics(numbers: list[int], max_number: int) -> dict:
    nums = sorted(int(n) for n in numbers)
    if not nums:
        return {
            "sum": 0,
            "span": 0,
            "odd": 0,
            "low": 0,
            "consecutive": 0,
            "mean_gap": 0.0,
        }
    gaps = [b - a for a, b in zip(nums, nums[1:])]
    return {
        "sum": sum(nums),
        "span": nums[-1] - nums[0],
        "odd": sum(n % 2 for n in nums),
        "low": sum(n <= max_number / 2 for n in nums),
        "consecutive": sum(g == 1 for g in gaps),
        "mean_gap": round(mean(gaps), 4) if gaps else 0.0,
    }


def _component_mean(rows: list[dict]) -> dict[str, float]:
    out = {}
    for factor in PREDICTIVE_FACTORS:
        vals = [
            _safe_float((r.get("components") or {}).get(factor), 50.0)
            for r in rows
            if factor in (r.get("components") or {})
        ]
        out[factor] = round(mean(vals), 4) if vals else 50.0
    return out


def _candidate_profile_numbers(profile) -> list[int]:
    out = []
    seen = set()
    for item in profile or []:
        try:
            n = int(item.get("number") if isinstance(item, dict) else item)
        except Exception:
            continue
        if n not in seen:
            seen.add(n)
            out.append(n)
    return out


def _rank_concentration_metrics(rows: list[dict], actual_set: set[int], cfg) -> dict:
    """Measure how quickly winners appear as we move down the frozen ticket ranking."""
    by_rank = sorted(rows, key=lambda r: int(r.get("rank", 999999)))
    if not by_rank:
        return {}
    requested = [3, 5, 8, 10, 20]
    ks = sorted({min(len(by_rank), k) for k in requested if min(len(by_rank), k) > 0})
    out = {}
    for k in ks:
        subset = by_rank[:k]
        number_union = set().union(*(set(map(int, r.get("numbers", []))) for r in subset)) if subset else set()
        winner_union = sorted(actual_set & number_union)
        cwc = len(winner_union)
        best = max((int(r.get("main_hits", 0)) for r in subset), default=0)
        random_expected = cfg.pick * (1.0 - (1.0 - cfg.pick / cfg.max_number) ** k)
        out[str(k)] = {
            "k": int(k),
            "cumulative_winner_coverage": int(cwc),
            "covered_winners": winner_union,
            "best_ticket_hit": int(best),
            "wce": round(best / cwc, 6) if cwc else 0.0,
            "unique_numbers": len(number_union),
            "number_pool_pct": round(100.0 * len(number_union) / cfg.max_number, 3),
            "theoretical_random_cwc": round(random_expected, 6),
            "cwc_edge_vs_theoretical_random": round(cwc - random_expected, 6),
        }
    front_keys = [str(k) for k in (3, 5, 10) if str(k) in out]
    edge = mean(out[k]["cwc_edge_vs_theoretical_random"] for k in front_keys) if front_keys else 0.0
    return {
        "by_k": out,
        "frontload_edge": round(float(edge), 6),
        "frontload_edge_normalized": round(float(edge) / max(1, cfg.pick), 6),
    }


def _candidate_number_metrics(profile, actual_set: set[int], cfg) -> dict:
    """Evaluate the frozen pre-draw number-support ranking independently of tickets."""
    ranked = [n for n in _candidate_profile_numbers(profile) if 1 <= n <= cfg.max_number]
    if not ranked:
        return {"available": False, "by_k": {}, "winner_rank_positions": {}}
    positions = {n: i for i, n in enumerate(ranked, 1)}
    out = {}
    for k in (10, 15, 20):
        kk = min(k, len(ranked))
        top = set(ranked[:kk])
        winners = sorted(actual_set & top)
        expected = cfg.pick * kk / cfg.max_number
        out[str(k)] = {
            "k": int(kk),
            "winner_coverage": len(winners),
            "covered_winners": winners,
            "pool_hit_rate": round(len(winners) / max(1, kk), 6),
            "theoretical_random_coverage": round(expected, 6),
            "coverage_edge_vs_theoretical_random": round(len(winners) - expected, 6),
        }
    return {
        "available": True,
        "ranked_numbers": ranked,
        "by_k": out,
        "winner_rank_positions": {str(n): positions.get(n) for n in sorted(actual_set)},
    }


def build_match_diagnostics(game_key: str, predictions: list[dict], draw: dict,
                            bonus_payload=None, candidate_number_profile=None) -> dict:
    """Compare a frozen pre-draw portfolio with one result.

    The function is intentionally diagnostic. It does not regenerate predictions and
    does not use post-draw information to rewrite any frozen score/component. Learning
    signals are derived from the components already stored inside the freeze.
    """
    cfg = GAMES[game_key]
    actual = sorted(int(n) for n in (draw.get("numbers") or []))
    actual_set = set(actual)
    actual_bonus = draw.get("bonus")
    preds = list(predictions or [])
    payload = normalize_bonus_payload(bonus_payload or [], preds)

    rows = []
    union = set()
    for pos, pred in enumerate(preds, 1):
        rank = int(pred.get("rank", pos))
        numbers = sorted(int(n) for n in (pred.get("numbers") or []))
        number_set = set(numbers)
        union.update(number_set)
        matched = sorted(actual_set & number_set)
        top_bonus = bonus_top_for_pick(payload, rank, preds)
        bonus_hit = None
        if actual_bonus is not None and top_bonus is not None:
            bonus_hit = int(top_bonus) == int(actual_bonus)
        rows.append({
            "rank": rank,
            "numbers": numbers,
            "main_hits": len(matched),
            "matched_numbers": matched,
            "score": round(_safe_float(pred.get("score"), 0.0), 4),
            "top_bonus": int(top_bonus) if top_bonus is not None else None,
            "bonus_hit": bonus_hit,
            "components": {
                k: round(_safe_float((pred.get("components") or {}).get(k), 50.0), 4)
                for k in PREDICTIVE_FACTORS
            },
            "structure": _structure_metrics(numbers, cfg.max_number),
        })

    # User-facing leaderboard rule: Main Match desc -> Bonus hit desc -> frozen score desc.
    # Unknown/missing legacy Bonus data never beats a confirmed hit and otherwise leaves
    # the original pre-draw Main score as the next tie breaker.
    leaderboard = sorted(
        rows,
        key=lambda r: (
            -int(r["main_hits"]),
            -(1 if r.get("bonus_hit") is True else 0),
            -float(r.get("score", 0.0)),
            int(r.get("rank", 999999)),
        ),
    )
    hits = [int(r["main_hits"]) for r in rows]
    best_hit = max(hits) if hits else 0
    champions = [r for r in leaderboard if int(r["main_hits"]) == best_hit]
    rest = [r for r in rows if int(r["main_hits"]) != best_hit]

    covered = sorted(actual_set & union)
    missed = sorted(actual_set - union)
    coverage_hit = len(covered)
    selection_miss = max(0, cfg.pick - coverage_hit)
    combination_gap = max(0, coverage_hit - best_hit)
    winner_concentration_efficiency = (best_hit / coverage_hit) if coverage_hit > 0 else 0.0
    winner_dispersion_loss = combination_gap
    ticket_slots = len(rows) * cfg.pick
    portfolio_unique_numbers = len(union)
    rank_concentration = _rank_concentration_metrics(rows, actual_set, cfg)
    candidate_number = _candidate_number_metrics(candidate_number_profile, actual_set, cfg)
    if selection_miss == 0 and combination_gap == 0:
        bottleneck = "NONE"
    elif combination_gap > selection_miss:
        bottleneck = "COMBINATION_CONCENTRATION"
    elif selection_miss > combination_gap:
        bottleneck = "NUMBER_SELECTION"
    else:
        bottleneck = "MIXED"

    champion_components = _component_mean(champions)
    rest_components = _component_mean(rest) if rest else dict(champion_components)
    component_delta = {
        k: round(champion_components[k] - rest_components[k], 4)
        for k in PREDICTIVE_FACTORS
    }
    avg_hit = mean(hits) if hits else 0.0
    # Evidence damping: a champion that barely separates from the portfolio should
    # contribute only a small shadow-learning signal. The raw deltas are still saved
    # for audit/display.
    separation = max(0.0, (best_hit - avg_hit) / max(1, cfg.pick))
    hit_strength = best_hit / max(1, cfg.pick)
    evidence = min(1.0, separation * (0.5 + hit_strength))
    component_signal = {
        k: round((component_delta[k] / 100.0) * evidence, 8)
        for k in PREDICTIVE_FACTORS
    }

    champion_structure = {}
    if champions:
        for field in ("sum", "span", "odd", "low", "consecutive", "mean_gap"):
            champion_structure[field] = round(
                mean(float((r.get("structure") or {}).get(field, 0.0)) for r in champions), 4
            )

    ranking = _ranking_metrics(rows, champions)
    candidate20 = ((candidate_number.get("by_k") or {}).get("20") or {}).get("winner_coverage")
    full_pool_coverage = portfolio_unique_numbers >= cfg.max_number
    placement_stage = _placement_stage(ranking.get("ranking_diagnosis"))
    association_stage = classify_rank_association(ranking.get("score_hit_spearman"))
    stage_diagnosis = {
        # Portfolio union coverage is a portfolio-construction diagnostic. It is not
        # number-selection evidence, especially when the portfolio spans the full pool.
        "number_selection": "NON_DIAGNOSTIC",
        "portfolio_coverage": "GOOD" if selection_miss <= 1 else "WEAK",
        "candidate_number_ranking": (
            "NOT_AVAILABLE" if candidate20 is None else
            ("GOOD" if int(candidate20) >= max(2, cfg.pick // 2) else "MIXED")
        ),
        "combination_concentration": "GOOD" if combination_gap <= 1 else "WEAK",
        "best_hit_placement": placement_stage,
        "global_rank_association": association_stage,
        # Retained for old consumers, but now requires placement and overall
        # association to point in the same direction before saying GOOD/WEAK.
        "ranking": _combined_ranking_stage(placement_stage, association_stage),
    }

    return {
        "schema_version": CHAMPION_SCHEMA_VERSION,
        "game": game_key,
        "draw_date": str(draw.get("draw_date") or ""),
        "actual": actual,
        "actual_bonus": int(actual_bonus) if actual_bonus is not None else None,
        "portfolio_size": len(rows),
        "pick_size": cfg.pick,
        "best_hit": int(best_hit),
        "avg_hit": round(float(avg_hit), 6),
        "median_hit": round(float(median(hits)), 6) if hits else 0.0,
        "ticket_slots": int(ticket_slots),
        "portfolio_unique_numbers": int(portfolio_unique_numbers),
        "number_pool_size": int(cfg.max_number),
        "portfolio_number_pool_pct": round(100.0 * portfolio_unique_numbers / cfg.max_number, 3),
        "full_pool_coverage": bool(full_pool_coverage),
        "top_n_coverage": int(coverage_hit),
        "portfolio_winner_coverage": int(coverage_hit),
        "covered_winners": covered,
        "missed_winners": missed,
        "selection_miss": int(selection_miss),
        "portfolio_miss": int(selection_miss),
        "combination_gap": int(combination_gap),
        "winner_dispersion_loss": int(winner_dispersion_loss),
        "winner_concentration_efficiency": round(float(winner_concentration_efficiency), 6),
        "bottleneck": bottleneck,
        "rank_concentration": rank_concentration,
        "candidate_number_ranking": candidate_number,
        "champion_count": len(champions),
        "champion_ranks": [int(r["rank"]) for r in champions],
        "champions": champions,
        "leaderboard": leaderboard,
        "champion_component_mean": champion_components,
        "rest_component_mean": rest_components,
        "champion_component_delta": component_delta,
        "champion_component_signal": component_signal,
        "champion_structure_mean": champion_structure,
        "champion_best_original_rank": ranking.get("champion_best_original_rank"),
        "champion_score_percentile": ranking.get("champion_score_percentile"),
        "score_hit_spearman": ranking.get("score_hit_spearman"),
        "top5_mean_hit": ranking.get("top5_mean_hit"),
        "top10_mean_hit": ranking.get("top10_mean_hit"),
        "bottom10_mean_hit": ranking.get("bottom10_mean_hit"),
        "ranking_diagnosis": ranking.get("ranking_diagnosis"),
        "stage_diagnosis": stage_diagnosis,
        "evidence_weight": round(evidence, 8),
        "production_impact": 0.0,
        "learning_policy": "SHADOW_ONLY",
    }


def summarize_champion_records(records: list[dict]) -> dict:
    parsed = []
    for item in records or []:
        rec = item.get("record") if isinstance(item, dict) else None
        if isinstance(rec, dict):
            parsed.append((item, rec))
    if not parsed:
        return {
            "n": 0,
            "min_samples": CHAMPION_CALIBRATION_MIN_SAMPLES,
            "calibration": "WAITING",
            "production_impact": 0.0,
        }

    n = len(parsed)
    deltas = {k: [] for k in PREDICTIVE_FACTORS}
    signals = {k: [] for k in PREDICTIVE_FACTORS}
    bottlenecks = {}
    for _, rec in parsed:
        bottlenecks[rec.get("bottleneck", "UNKNOWN")] = bottlenecks.get(rec.get("bottleneck", "UNKNOWN"), 0) + 1
        for k in PREDICTIVE_FACTORS:
            deltas[k].append(_safe_float((rec.get("champion_component_delta") or {}).get(k), 0.0))
            signals[k].append(_safe_float((rec.get("champion_component_signal") or {}).get(k), 0.0))

    mean_delta = {k: round(mean(v), 4) if v else 0.0 for k, v in deltas.items()}
    mean_signal = {k: round(mean(v), 8) if v else 0.0 for k, v in signals.items()}
    strongest = sorted(mean_delta.items(), key=lambda kv: (-abs(kv[1]), kv[0]))
    signature = f"{CHAMPION_SCHEMA_VERSION}:{n}:{max(int(item.get('id', 0)) for item, _ in parsed)}"
    def rolling_metrics(items):
        recs = [rec for _, rec in items]
        if not recs:
            return {"n": 0}
        def avg_optional(vals):
            vals = [float(v) for v in vals if v is not None]
            return round(mean(vals), 6) if vals else None
        cwc = {}
        bh = {}
        cand = {}
        for k in (3, 5, 10, 20):
            cwc[str(k)] = avg_optional([
                ((((r.get("rank_concentration") or {}).get("by_k") or {}).get(str(k)) or {}).get("cumulative_winner_coverage"))
                for r in recs
            ])
            bh[str(k)] = avg_optional([
                ((((r.get("rank_concentration") or {}).get("by_k") or {}).get(str(k)) or {}).get("best_ticket_hit"))
                for r in recs
            ])
        for k in (10, 15, 20):
            cand[str(k)] = avg_optional([
                ((((r.get("candidate_number_ranking") or {}).get("by_k") or {}).get(str(k)) or {}).get("winner_coverage"))
                for r in recs
            ])
        return {
            "n": len(recs),
            "avg_best_hit": avg_optional([r.get("best_hit") for r in recs]),
            "avg_portfolio_coverage": avg_optional([r.get("top_n_coverage") for r in recs]),
            "avg_combination_gap": avg_optional([r.get("combination_gap") for r in recs]),
            "avg_wce": avg_optional([r.get("winner_concentration_efficiency") for r in recs]),
            "avg_champion_rank": avg_optional([r.get("champion_best_original_rank") for r in recs]),
            "avg_spearman": avg_optional([r.get("score_hit_spearman") for r in recs]),
            "avg_frontload_edge": avg_optional([((r.get("rank_concentration") or {}).get("frontload_edge")) for r in recs]),
            "avg_cwc_at": cwc,
            "avg_best_hit_at": bh,
            "avg_candidate_number_coverage_at": cand,
        }

    out = {
        "n": n,
        "min_samples": CHAMPION_CALIBRATION_MIN_SAMPLES,
        "calibration": "CALIBRATED" if n >= CHAMPION_CALIBRATION_MIN_SAMPLES else "WAITING",
        "production_impact": 0.0,
        "avg_best_hit": round(mean(_safe_float(rec.get("best_hit")) for _, rec in parsed), 4),
        "avg_coverage": round(mean(_safe_float(rec.get("top_n_coverage")) for _, rec in parsed), 4),
        "avg_selection_miss": round(mean(_safe_float(rec.get("selection_miss")) for _, rec in parsed), 4),
        "avg_combination_gap": round(mean(_safe_float(rec.get("combination_gap")) for _, rec in parsed), 4),
        "avg_winner_concentration_efficiency": round(mean(_safe_float(rec.get("winner_concentration_efficiency"), 0.0) for _, rec in parsed), 6),
        "avg_champion_rank": round(mean(_safe_float(rec.get("champion_best_original_rank"), 0.0) for _, rec in parsed if rec.get("champion_best_original_rank") is not None), 4) if any(rec.get("champion_best_original_rank") is not None for _, rec in parsed) else None,
        "avg_score_hit_spearman": round(mean(_safe_float(rec.get("score_hit_spearman"), 0.0) for _, rec in parsed), 6),
        "under_ranked_count": sum(1 for _, rec in parsed if rec.get("ranking_diagnosis") == "UNDER_RANKED"),
        "bottlenecks": bottlenecks,
        "mean_component_delta": mean_delta,
        "mean_component_signal": mean_signal,
        "strongest_component_deltas": strongest,
        "signature": signature,
    }
    out["rolling"] = {
        "20": rolling_metrics(parsed[:20]),
        "50": rolling_metrics(parsed[:50]),
    }
    return out
