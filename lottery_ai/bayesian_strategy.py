from __future__ import annotations

import json
import math
from collections import defaultdict
from statistics import mean

from .evaluation import benjamini_hochberg, paired_sign_flip_test
from .null_benchmark import portfolio_null_prefix_expectations


BAYESIAN_STRATEGY_VERSION = "BAYES1.1"
DEFAULT_HISTORICAL_DISCOUNT = 0.45
DEFAULT_LINE_COUNTS = (3, 5, 8, 10, 20)


def _safe_float(value, default=0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _normal_cdf(value: float) -> float:
    return 0.5 * (1.0 + math.erf(float(value) / math.sqrt(2.0)))


def _record_item_map(records) -> dict[str, dict]:
    out = {}
    for item in records or []:
        rec = (item or {}).get("record") or {}
        draw_date = str(rec.get("draw_date") or (item or {}).get("draw_date") or "")
        if draw_date and draw_date not in out:
            out[draw_date] = item
    return out


def _rank_metric(record: dict, line_count: int) -> dict | None:
    by_k = ((record or {}).get("rank_concentration") or {}).get("by_k") or {}
    row = by_k.get(str(int(line_count)))
    if not isinstance(row, dict):
        return None
    return {
        "best_hit": _safe_float(row.get("best_ticket_hit")),
        "coverage": _safe_float(row.get("cumulative_winner_coverage")),
        "wce": _safe_float(row.get("wce")),
    }


def _freeze_predictions(db, item: dict) -> list[dict]:
    freeze_id = (item or {}).get("freeze_id")
    if freeze_id is None or not hasattr(db, "freeze_by_id"):
        return []
    freeze = db.freeze_by_id(int(freeze_id))
    if not freeze:
        return []
    try:
        rows = json.loads(freeze.get("predictions_json") or "[]")
    except Exception:
        return []
    return rows if isinstance(rows, list) else []


def forward_strategy_observations(db, game: str,
                                  line_counts=DEFAULT_LINE_COUNTS,
                                  limit: int = 300) -> list[dict]:
    """Return frozen strategy performance minus *that portfolio's own* fair null.

    V1.6.0 paired each strategy with a highly diversified Random Control portfolio.
    That benchmark has a different overlap/coverage structure and can therefore create
    a systematic best-hit/coverage bias under a perfectly fair lottery. V1.6.1 uses
    the exact frozen portfolio as the conditioning object and asks how it performed
    relative to its own fair-lottery expectation.
    """
    prefixes = {
        "balanced": "P",
        "score_only": "S14SCORE",
        "focused": "S14FOCUS",
        "pure_coverage": "S14PURE",
        "concentrated": "S15CONC",
    }
    out = []
    for strategy, prefix in prefixes.items():
        by_date = _record_item_map(db.champion_learning_records(game, prefix=prefix, limit=limit))
        for draw_date in sorted(by_date):
            item = by_date[draw_date]
            record = (item or {}).get("record") or {}
            predictions = _freeze_predictions(db, item)
            if not predictions:
                continue
            nulls = portfolio_null_prefix_expectations(game, predictions, line_counts=line_counts)
            for k in line_counts:
                kk = min(max(1, int(k)), len(predictions))
                observed = _rank_metric(record, kk)
                null = nulls.get(kk)
                if not observed or not null:
                    continue
                out.append({
                    "source": "forward",
                    "game": game,
                    "draw_date": draw_date,
                    "strategy": strategy,
                    "lines": int(kk),
                    "variant": f"{strategy}@{int(kk)}",
                    "best_hit_edge": round(observed["best_hit"] - _safe_float(null.get("best_hit")), 8),
                    "coverage_edge": round(observed["coverage"] - _safe_float(null.get("coverage")), 8),
                    "wce_edge": round(observed["wce"] - _safe_float(null.get("wce")), 8),
                    "null_schema": null.get("schema"),
                    "null_method": null.get("method"),
                    "null_samples": null.get("samples"),
                })
    return out


def _source_summary(rows: list[dict], metric: str) -> dict:
    vals = [_safe_float(r.get(metric)) for r in rows]
    return {
        "n": len(vals),
        "mean": round(mean(vals), 8) if vals else None,
        "positive": sum(1 for value in vals if value > 0),
        "ties": sum(1 for value in vals if abs(value) <= 1e-9),
        "negative": sum(1 for value in vals if value < 0),
    }


def _direction(value, tolerance=1e-6) -> int:
    # Evidence assembled through deterministic MC can differ by tiny numerical noise.
    # Do not call microscopic machine-level differences a source conflict.
    if value is None or abs(float(value)) <= tolerance:
        return 0
    return 1 if float(value) > 0 else -1


def _sequential_sign_evalue(values) -> float:
    """Always-valid e-value from a mixture of positive sign alternatives.

    Under the null each non-zero paired edge has P(sign=+) = 0.5. A mixture of
    likelihood-ratio martingales remains an e-process, so repeated inspection does
    not inflate Type-I error in the usual optional-stopping way. Magnitudes are not
    used here; they are handled separately by the posterior and paired tests.
    """
    signs = [1 if float(v) > 1e-9 else 0 for v in values if abs(float(v)) > 1e-9]
    if not signs:
        return 1.0
    successes = sum(signs)
    failures = len(signs) - successes
    alternatives = (0.55, 0.60, 0.65, 0.70, 0.80, 0.90)
    ratios = []
    for q in alternatives:
        log_lr = successes * math.log(q / 0.5) + failures * math.log((1.0 - q) / 0.5)
        ratios.append(math.exp(min(700.0, log_lr)))
    return sum(ratios) / len(ratios)


def hierarchical_strategy_posterior(observations: list[dict], game: str,
                                    metric: str = "best_hit_edge",
                                    historical_discount: float = DEFAULT_HISTORICAL_DISCOUNT) -> dict:
    """Null-anchored research posterior with cross-source de-duplication.

    A physical draw/variant is one sample. If historical replay and a genuine pre-draw
    frozen record both exist for the same draw/variant, the frozen forward record wins.
    Variant p-values are BH-FDR adjusted, and repeated forward looks also carry a
    conservative summable alpha-spending diagnostic. Production remains unaffected.
    """
    historical_discount = max(0.0, min(1.0, float(historical_discount)))
    deduped: dict[tuple[str, str, str], dict] = {}
    for row in observations or []:
        if not isinstance(row, dict) or row.get(metric) is None or not row.get("variant"):
            continue
        source = "forward" if row.get("source") == "forward" else "historical"
        key = (str(row.get("game") or game), str(row.get("draw_date") or ""), str(row["variant"]))
        candidate = dict(row, source=source)
        previous = deduped.get(key)
        if previous is None or (source == "forward" and previous.get("source") != "forward"):
            deduped[key] = candidate
    rows = list(deduped.values())
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        grouped[str(row["variant"])].append(row)

    if not grouped:
        return {
            "schema": BAYESIAN_STRATEGY_VERSION,
            "game": game,
            "status": "NO_EVIDENCE",
            "metric": metric,
            "historical_discount": historical_discount,
            "historical_draws": 0,
            "forward_draws": 0,
            "variants": {},
            "research_leader": None,
            "production_impact": 0.0,
        }

    variant_means = []
    for variant_rows in grouped.values():
        vals = [_safe_float(r.get(metric)) for r in variant_rows]
        if vals:
            variant_means.append(mean(vals))
    grand_mean = mean(variant_means) if variant_means else 0.0
    shared_prior_mean = grand_mean / 3.0
    prior_n = 6.0
    prior_variance = 0.50

    results = {}
    raw_forward_p: dict[str, float | None] = {}
    for variant, variant_rows in sorted(grouped.items()):
        weighted = []
        for row in variant_rows:
            w = 1.0 if row["source"] == "forward" else historical_discount
            if w > 0:
                weighted.append((_safe_float(row.get(metric)), w))
        total_weight = sum(w for _, w in weighted)
        if total_weight <= 0:
            continue
        observed_mean = sum(value * w for value, w in weighted) / total_weight
        observed_variance = sum(w * (value - observed_mean) ** 2 for value, w in weighted) / total_weight
        observed_variance = max(0.25, observed_variance)
        prior_precision = prior_n / prior_variance
        likelihood_precision = total_weight / observed_variance
        posterior_variance = 1.0 / (prior_precision + likelihood_precision)
        posterior_mean = posterior_variance * (
            prior_precision * shared_prior_mean + likelihood_precision * observed_mean
        )
        posterior_sd = math.sqrt(posterior_variance)
        low = posterior_mean - 1.959963984540054 * posterior_sd
        high = posterior_mean + 1.959963984540054 * posterior_sd
        probability_positive = _normal_cdf(posterior_mean / posterior_sd) if posterior_sd > 0 else (1.0 if posterior_mean > 0 else 0.5)

        historical_rows = [r for r in variant_rows if r["source"] == "historical"]
        forward_rows = [r for r in variant_rows if r["source"] == "forward"]
        historical = _source_summary(historical_rows, metric)
        forward = _source_summary(forward_rows, metric)
        hd = _direction(historical.get("mean"))
        fd = _direction(forward.get("mean"))
        if hd and fd:
            consistency = "CONSISTENT" if hd == fd else "CONFLICT"
        elif hd or fd:
            consistency = "ONE_SOURCE_ONLY"
        else:
            consistency = "NEUTRAL"

        fvals = [_safe_float(r.get(metric)) for r in forward_rows]
        ftest = paired_sign_flip_test(fvals, seed_label=f"{game}|{variant}|{metric}|forward") if fvals else {
            "p_two_sided": None, "effect_dz": None, "method": None,
        }
        raw_forward_p[variant] = ftest.get("p_two_sided")
        forward_evalue = _sequential_sign_evalue(fvals)

        gate = "WAITING"
        grade = "D"
        if historical["n"] >= 12 and probability_positive >= 0.90 and posterior_mean > 0 and consistency != "CONFLICT":
            gate, grade = "HISTORICAL_CANDIDATE", "C"
        elif probability_positive <= 0.25:
            gate, grade = "NEGATIVE_OR_NO_EDGE", "C"
        elif total_weight >= 12:
            gate, grade = "OBSERVE", "C"

        first = variant_rows[0]
        results[variant] = {
            "strategy": first.get("strategy"),
            "lines": int(first.get("lines") or 0),
            "historical": historical,
            "forward": forward,
            "effective_n": round(total_weight, 4),
            "observed_weighted_mean": round(observed_mean, 8),
            "posterior_mean_edge": round(posterior_mean, 8),
            "credible_interval_95": {"low": round(low, 8), "high": round(high, 8)},
            "probability_edge_positive": round(probability_positive, 8),
            "source_consistency": consistency,
            "forward_p_two_sided": ftest.get("p_two_sided"),
            "forward_effect_dz": ftest.get("effect_dz"),
            "forward_test_method": ftest.get("method"),
            "forward_sequential_evalue": round(forward_evalue, 8),
            "gate": gate,
            "evidence_grade": grade,
        }

    fdr = benjamini_hochberg(raw_forward_p)
    for variant, item in results.items():
        n = int(item["forward"]["n"])
        q = fdr.get(variant)
        sequential_pass = float(item.get("forward_sequential_evalue") or 0.0) >= 20.0
        item["forward_fdr_q"] = q
        item["sequential_evalue_threshold"] = 20.0
        item["sequential_pass"] = sequential_pass

        # Forward grades require both cross-variant FDR control and an always-valid
        # e-process threshold for repeated looks. Historical replay can nominate
        # research candidates but never confirm.
        if (n >= 100 and item["probability_edge_positive"] >= 0.995
                and item["credible_interval_95"]["low"] > 0
                and item["source_consistency"] != "CONFLICT"
                and q is not None and q <= 0.01 and sequential_pass):
            item["gate"], item["evidence_grade"] = "FORWARD_CONFIRMATION", "A"
        elif (n >= 30 and item["probability_edge_positive"] >= 0.975
              and item["credible_interval_95"]["low"] > 0
              and item["source_consistency"] != "CONFLICT"
              and q is not None and q <= 0.05 and sequential_pass):
            item["gate"], item["evidence_grade"] = "FORWARD_SCREENING", "B"
        elif n > 0 and item["gate"] == "HISTORICAL_CANDIDATE":
            # Mixed evidence that has not passed the forward corrections stays research-only.
            item["gate"], item["evidence_grade"] = "OBSERVE", "C"

    ranked = sorted(
        results,
        key=lambda key: (
            results[key]["probability_edge_positive"],
            results[key]["posterior_mean_edge"],
            results[key]["forward"]["n"],
            -results[key]["lines"],
        ),
        reverse=True,
    )
    leader = ranked[0] if ranked else None
    historical_draws = len({r.get("draw_date") for r in rows if r.get("source") == "historical"})
    forward_draws = len({r.get("draw_date") for r in rows if r.get("source") == "forward"})
    return {
        "schema": BAYESIAN_STRATEGY_VERSION,
        "game": game,
        "status": "READY",
        "metric": metric,
        "historical_discount": historical_discount,
        "shared_prior_mean": round(shared_prior_mean, 8),
        "prior_effective_n": prior_n,
        "historical_draws": historical_draws,
        "forward_draws": forward_draws,
        "variants": results,
        "ranking": ranked,
        "research_leader": leader,
        "production_impact": 0.0,
        "promotion_allowed": False,
        "multiplicity_control": "BH-FDR across variants + always-valid sign e-process across repeated forward looks",
        "note": (
            "Research-only self-null comparison. Historical replay is discounted; genuine pre-draw freezes "
            "receive full weight and replace an overlapping historical sample for the same draw/variant. "
            "Each portfolio is evaluated against its own fair-lottery null; Random Control is not the Bayesian baseline. "
            "A posterior edge is not proof of lottery predictability or profitability."
        ),
    }
