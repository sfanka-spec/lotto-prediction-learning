from __future__ import annotations

import hashlib
import math
import random
from statistics import mean, stdev

EXACT_SIGN_FLIP_MAX_N = 16

STRATEGY_PREFIXES = {
    "balanced_shadow": "S14BAL",
    "score_only": "S14SCORE",
    "focused": "S14FOCUS",
    "pure_coverage": "S14PURE",
    "concentrated": "S15CONC",
}


def _seed(label: str) -> int:
    return int.from_bytes(hashlib.sha256(label.encode("utf-8")).digest()[:8], "big") & 0x7FFFFFFF


def _safe_mean(values):
    values = list(values or [])
    return mean(values) if values else 0.0


def _linear_quantile(sorted_values: list[float], q: float) -> float:
    """Type-7 style linear quantile used for percentile-bootstrap endpoints."""
    if not sorted_values:
        raise ValueError("quantile requires at least one value")
    if q <= 0:
        return float(sorted_values[0])
    if q >= 1:
        return float(sorted_values[-1])
    pos = (len(sorted_values) - 1) * q
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return float(sorted_values[lo])
    frac = pos - lo
    return float(sorted_values[lo] * (1.0 - frac) + sorted_values[hi] * frac)


def bootstrap_mean_ci(values, reps: int = 2500, alpha: float = 0.05, seed_label: str = "bootstrap") -> dict:
    vals = [float(v) for v in values or []]
    if not 0 < float(alpha) < 1:
        raise ValueError("alpha must be between 0 and 1")
    if not vals:
        return {"n": 0, "mean": 0.0, "low": None, "high": None, "method": "percentile_interpolated"}
    if len(vals) == 1:
        return {"n": 1, "mean": vals[0], "low": vals[0], "high": vals[0], "method": "percentile_interpolated"}
    rng = random.Random(_seed(seed_label))
    n = len(vals)
    means = []
    for _ in range(max(200, int(reps))):
        means.append(sum(vals[rng.randrange(n)] for _ in range(n)) / n)
    means.sort()
    low = _linear_quantile(means, alpha / 2.0)
    high = _linear_quantile(means, 1.0 - alpha / 2.0)
    return {
        "n": n,
        "mean": round(mean(vals), 6),
        "low": round(low, 6),
        "high": round(high, 6),
        "method": "percentile_interpolated",
    }


def paired_sign_flip_test(diffs, reps: int = 12000, seed_label: str = "perm") -> dict:
    vals = [float(v) for v in diffs or []]
    n = len(vals)
    if not vals:
        return {
            "n": 0, "effective_n": 0, "mean_diff": 0.0,
            "p_two_sided": None, "effect_dz": None, "method": None,
        }

    observed_sum = abs(sum(vals))
    nonzero = [v for v in vals if abs(v) > 1e-12]
    effective_n = len(nonzero)
    if observed_sum <= 1e-12 or effective_n == 0:
        p = 1.0
        method = "exact_sign_flip" if effective_n <= EXACT_SIGN_FLIP_MAX_N else "monte_carlo_sign_flip"
        permutations = 1 if effective_n == 0 else (1 << effective_n if effective_n <= EXACT_SIGN_FLIP_MAX_N else max(500, int(reps)))
    elif effective_n <= EXACT_SIGN_FLIP_MAX_N:
        # Exhaustive sign enumeration gives an exact randomization p-value. Zero
        # differences are omitted because their sign contributes no information.
        total = 1 << effective_n
        extreme = 0
        tolerance = 1e-12
        for mask in range(total):
            signed_sum = 0.0
            for i, value in enumerate(nonzero):
                signed_sum += value if (mask >> i) & 1 else -value
            if abs(signed_sum) >= observed_sum - tolerance:
                extreme += 1
        p = extreme / total
        method = "exact_sign_flip"
        permutations = total
    else:
        rng = random.Random(_seed(seed_label))
        extreme = 1
        total = max(500, int(reps))
        for _ in range(total):
            signed_sum = sum(v if rng.random() < 0.5 else -v for v in nonzero)
            if abs(signed_sum) >= observed_sum - 1e-12:
                extreme += 1
        # Phipson-Smyth style +1 correction prevents a Monte-Carlo p-value of zero.
        p = extreme / (total + 1)
        method = "monte_carlo_sign_flip"
        permutations = total

    if n >= 2:
        sd = stdev(vals)
        dz = (mean(vals) / sd) if sd > 0 else (math.inf if mean(vals) != 0 else 0.0)
    else:
        dz = None
    return {
        "n": n,
        "effective_n": effective_n,
        "mean_diff": round(mean(vals), 6),
        "p_two_sided": round(float(p), 8),
        "effect_dz": None if dz is None else (round(float(dz), 6) if math.isfinite(dz) else (999.0 if dz > 0 else -999.0)),
        "method": method,
        "permutations": int(permutations),
    }


def statistical_simulation_self_check(*, simulations: int = 60, sample_n: int = 20,
                                      bootstrap_reps: int = 800, alpha: float = 0.05,
                                      seed_label: str = "V1.4.1-self-check") -> dict:
    """Deterministic sanity simulation for CI coverage and sign-flip Type-I error.

    This is a validation aid, not a Production signal. The tolerances intentionally
    stay broad because finite simulation error is expected in a lightweight self-test.
    """
    simulations = max(10, int(simulations))
    sample_n = max(4, int(sample_n))
    rng = random.Random(_seed(seed_label))
    true_mean = 0.35
    covered = 0
    rejected = 0
    for i in range(simulations):
        sample = [rng.gauss(true_mean, 1.0) for _ in range(sample_n)]
        ci = bootstrap_mean_ci(sample, reps=bootstrap_reps, alpha=alpha, seed_label=f"{seed_label}|ci|{i}")
        if float(ci["low"]) <= true_mean <= float(ci["high"]):
            covered += 1

        null_diffs = [rng.gauss(0.0, 1.0) for _ in range(min(sample_n, EXACT_SIGN_FLIP_MAX_N))]
        test = paired_sign_flip_test(null_diffs, seed_label=f"{seed_label}|perm|{i}")
        if test["p_two_sided"] is not None and float(test["p_two_sided"]) < alpha:
            rejected += 1
    return {
        "schema": "STAT_SELF_CHECK1.0",
        "simulations": simulations,
        "sample_n": sample_n,
        "alpha": float(alpha),
        "bootstrap_nominal_coverage": round(1.0 - alpha, 4),
        "bootstrap_observed_coverage": round(covered / simulations, 4),
        "sign_flip_nominal_type1": round(alpha, 4),
        "sign_flip_observed_type1": round(rejected / simulations, 4),
        "bootstrap_pass": (covered / simulations) >= max(0.80, (1.0 - alpha) - 0.12),
        "sign_flip_pass": (rejected / simulations) <= alpha + 0.10,
    }


def sequential_sign_evalue(diffs, alternatives=(0.55, 0.60, 0.65, 0.70, 0.80, 0.90)) -> float:
    """Always-valid e-value for repeated inspection of paired-difference signs.

    Each fixed positive-sign alternative produces a likelihood-ratio martingale under
    P(sign=+)=0.5. Their equal mixture is still an e-process, so optional stopping /
    repeated looks do not require a fixed-horizon p-value correction.
    """
    vals = [float(v) for v in (diffs or []) if abs(float(v)) > 1e-9]
    if not vals:
        return 1.0
    successes = sum(v > 0 for v in vals)
    failures = len(vals) - successes
    ratios = []
    for q in alternatives:
        q = float(q)
        if not 0.5 < q < 1.0:
            continue
        log_lr = successes * math.log(q / 0.5) + failures * math.log((1.0 - q) / 0.5)
        ratios.append(math.exp(min(700.0, log_lr)))
    return float(sum(ratios) / len(ratios)) if ratios else 1.0


def benjamini_hochberg(pvalues: dict[str, float | None]) -> dict[str, float | None]:
    valid = sorted((float(p), key) for key, p in (pvalues or {}).items() if p is not None)
    m = len(valid)
    out = {key: None for key in (pvalues or {})}
    if not m:
        return out
    adjusted = [0.0] * m
    running = 1.0
    for i in range(m - 1, -1, -1):
        p, _ = valid[i]
        rank = i + 1
        running = min(running, p * m / rank)
        adjusted[i] = min(1.0, running)
    for (_, key), q in zip(valid, adjusted):
        out[key] = round(q, 8)
    return out


def _record_map(records):
    out = {}
    for item in records or []:
        rec = item.get("record") or {}
        d = str(rec.get("draw_date") or item.get("draw_date") or "")
        if d and d not in out:
            out[d] = rec
    return out


def _paired_records(prod_records, strategy_records):
    p = _record_map(prod_records)
    s = _record_map(strategy_records)
    rows = []
    for d in sorted(set(p) & set(s)):
        pr, sr = p[d], s[d]
        rows.append({
            "draw_date": d,
            "prod_avg_hit": float(pr.get("avg_hit", 0.0) or 0.0),
            "strategy_avg_hit": float(sr.get("avg_hit", 0.0) or 0.0),
            "prod_best_hit": float(pr.get("best_hit", 0.0) or 0.0),
            "strategy_best_hit": float(sr.get("best_hit", 0.0) or 0.0),
            "prod_coverage": float(pr.get("top_n_coverage", 0.0) or 0.0),
            "strategy_coverage": float(sr.get("top_n_coverage", 0.0) or 0.0),
            "prod_champion_rank": float(pr.get("champion_best_original_rank", 0.0) or 0.0),
            "strategy_champion_rank": float(sr.get("champion_best_original_rank", 0.0) or 0.0),
        })
    return rows


def _rolling(rows, windows=(30, 50, 100)):
    out = {}
    for w in windows:
        sub = rows[-w:]
        if not sub:
            out[str(w)] = {"n": 0}
            continue
        out[str(w)] = {
            "n": len(sub),
            "avg_hit_delta": round(_safe_mean(r["strategy_avg_hit"] - r["prod_avg_hit"] for r in sub), 5),
            "best_hit_delta": round(_safe_mean(r["strategy_best_hit"] - r["prod_best_hit"] for r in sub), 5),
            "coverage_delta": round(_safe_mean(r["strategy_coverage"] - r["prod_coverage"] for r in sub), 5),
        }
    return out


def summarize_strategy_pairs(prod_records, strategy_records, label: str) -> dict:
    rows = _paired_records(prod_records, strategy_records)
    avg_diffs = [r["strategy_avg_hit"] - r["prod_avg_hit"] for r in rows]
    best_diffs = [r["strategy_best_hit"] - r["prod_best_hit"] for r in rows]
    coverage_diffs = [r["strategy_coverage"] - r["prod_coverage"] for r in rows]
    perm = paired_sign_flip_test(avg_diffs, seed_label=f"{label}|avg")
    ci = bootstrap_mean_ci(avg_diffs, seed_label=f"{label}|avg")
    return {
        "label": label,
        "n": len(rows),
        "avg_hit_delta": round(_safe_mean(avg_diffs), 6),
        "avg_hit_ci95": ci,
        "best_hit_delta": round(_safe_mean(best_diffs), 6),
        "coverage_delta": round(_safe_mean(coverage_diffs), 6),
        "p_two_sided": perm.get("p_two_sided"),
        "effect_dz": perm.get("effect_dz"),
        "permutation_method": perm.get("method"),
        "permutations": perm.get("permutations"),
        "rolling": _rolling(rows),
        "rows": rows,
    }


def strategy_validation_summary(db, game: str, limit: int = 250) -> dict:
    prod = db.champion_learning_records(game, prefix="P", limit=limit)
    comparisons = {}
    raw_p = {}
    for label, prefix in STRATEGY_PREFIXES.items():
        records = db.champion_learning_records(game, prefix=prefix, limit=limit)
        comp = summarize_strategy_pairs(prod, records, label)
        comparisons[label] = comp
        raw_p[label] = comp.get("p_two_sided")
    q = benjamini_hochberg(raw_p)
    for label, comp in comparisons.items():
        comp["fdr_q"] = q.get(label)
        n = int(comp.get("n", 0))
        qv = comp.get("fdr_q")
        effect = float(comp.get("avg_hit_delta", 0.0) or 0.0)
        if n >= 200 and qv is not None and qv <= 0.01 and abs(effect) > 0.015:
            gate = "CONFIRMATION_SIGNAL"
        elif n >= 100 and qv is not None and qv <= 0.05 and abs(effect) > 0.015:
            gate = "SCREENING_SIGNAL"
        elif n >= 30:
            gate = "OBSERVE"
        else:
            gate = "WAITING"
        comp["gate"] = gate
        # Avoid shipping long row payloads into the normal UI state.
        comp.pop("rows", None)

    # Production is Balanced. Positive values below mean Balanced covered more winners,
    # while positive concentration cost means Score-only achieved a better best ticket.
    score_rows = _paired_records(
        prod, db.champion_learning_records(game, prefix=STRATEGY_PREFIXES["score_only"], limit=limit)
    )
    coverage_gain = [r["prod_coverage"] - r["strategy_coverage"] for r in score_rows]
    concentration_cost = [r["strategy_best_hit"] - r["prod_best_hit"] for r in score_rows]
    tradeoff = {
        "n": len(score_rows),
        "balanced_coverage_gain_vs_score_only": round(_safe_mean(coverage_gain), 6),
        "balanced_concentration_cost_vs_score_only": round(_safe_mean(concentration_cost), 6),
        "coverage_gain_ci95": bootstrap_mean_ci(coverage_gain, seed_label=f"{game}|coverage_gain"),
        "concentration_cost_ci95": bootstrap_mean_ci(concentration_cost, seed_label=f"{game}|concentration_cost"),
    }
    return {
        "schema": "EVAL1.4.1",
        "game": game,
        "production_samples": len(prod),
        "comparisons": comparisons,
        "coverage_tradeoff": tradeoff,
        "multiple_testing": "Benjamini-Hochberg FDR across V1.4 strategy comparisons",
        "interpretation": "Research-only. Statistical significance does not establish lottery predictability.",
    }
