from __future__ import annotations

import random
from statistics import mean

from .config import GAMES, PREDICTIVE_FACTORS, normalize_main_weights
from .analysis import paired_z_score, paired_t_critical_95
from .engine import PredictionEngine
from .evaluation import bootstrap_mean_ci, paired_sign_flip_test
from .null_benchmark import portfolio_null_prefix_expectations


def walk_forward_test(game_key, draws, weights, eval_draws=30, candidate_count=1200, top_n=10, seed=123):
    cfg = GAMES[game_key]
    if len(draws) < max(60, eval_draws+20):
        return {"status":"insufficient_data", "needed":max(60,eval_draws+20), "have":len(draws)}
    start = max(50, len(draws)-eval_draws)
    per_draw=[]
    for i in range(start, len(draws)):
        history=draws[:i]
        actual=set(draws[i]["numbers"])
        engine=PredictionEngine(game_key, history, weights, seed=seed+i)
        preds=engine.generate(candidate_count=candidate_count, top_n=top_n)
        hits=[len(actual & set(p["numbers"])) for p in preds]
        per_draw.append({"date":draws[i]["draw_date"],"avg_hit":mean(hits),"best_hit":max(hits)})
    random_baseline=cfg.pick*cfg.pick/cfg.max_number
    avg=mean(x["avg_hit"] for x in per_draw)
    diffs=[x["avg_hit"]-random_baseline for x in per_draw]
    z=paired_z_score(diffs)
    return {
        "status":"ok", "n":len(per_draw), "avg_hit":avg,
        "avg_best_hit":mean(x["best_hit"] for x in per_draw),
        "random_baseline":random_baseline, "edge":avg-random_baseline,
        "z_score":z, "test_statistic":"paired_t", "critical_95":paired_t_critical_95(len(diffs)), "significant_95":abs(z)>=paired_t_critical_95(len(diffs)),
        "rows":per_draw,
    }


def shuffle_test(game_key, draws, weights, repeats=12, eval_draws=12, candidate_count=700):
    """Paired temporal-order placebo test.

    V1.6.0 compared one real mean with unrelated shuffled means and used a fixed
    0.03 threshold. V1.6.1 pairs every real target position with the mean placebo
    score for the same target position, then reports a paired CI and sign-flip p-value.
    """
    if len(draws) < 70:
        return {"status":"insufficient_data"}
    real = walk_forward_test(game_key, draws, weights, eval_draws=eval_draws,
                             candidate_count=candidate_count, top_n=8, seed=900)
    if real.get("status") != "ok":
        return real
    real_rows = list(real.get("rows") or [])
    if not real_rows:
        return {"status":"insufficient_data"}

    placebo_by_date = {str(row["date"]): [] for row in real_rows}
    base = list(draws)
    for r in range(max(4, int(repeats))):
        shuffled = list(base)
        random.Random(1000 + r).shuffle(shuffled)
        dates = sorted(d["draw_date"] for d in base)
        shuffled = [dict(d, draw_date=dates[i]) for i, d in enumerate(shuffled)]
        res = walk_forward_test(game_key, shuffled, weights, eval_draws=eval_draws,
                                candidate_count=candidate_count, top_n=8, seed=1000 + r)
        if res.get("status") != "ok":
            continue
        for row in res.get("rows") or []:
            ds = str(row.get("date"))
            if ds in placebo_by_date:
                placebo_by_date[ds].append(float(row.get("avg_hit", 0.0)))

    paired = []
    placebo_means = []
    for row in real_rows:
        ds = str(row.get("date"))
        vals = placebo_by_date.get(ds) or []
        if not vals:
            continue
        pv = mean(vals)
        rv = float(row.get("avg_hit", 0.0))
        paired.append(rv - pv)
        placebo_means.append(pv)
    if not paired:
        return {"status":"insufficient_data"}
    ci = bootstrap_mean_ci(paired, reps=3000, seed_label=f"{game_key}|shuffle|ci")
    perm = paired_sign_flip_test(paired, reps=20000, seed_label=f"{game_key}|shuffle|perm")
    low = ci.get("low")
    pval = perm.get("p_two_sided")
    supported = bool(low is not None and float(low) > 0 and pval is not None and float(pval) <= 0.05)
    return {
        "status":"ok",
        "n":len(paired),
        "repeats":max(4, int(repeats)),
        "real_avg_hit":mean(float(r.get("avg_hit",0.0)) for r in real_rows),
        "shuffle_avg_hit":mean(placebo_means),
        "temporal_advantage":mean(paired),
        "paired_ci95":ci,
        "p_two_sided":pval,
        "effect_dz":perm.get("effect_dz"),
        "test_method":perm.get("method"),
        "interpretation":"TEMPORAL SIGNAL POSSIBLE" if supported else "NO RELIABLE TEMPORAL EVIDENCE",
    }


def null_synthetic_test(game_key, draws, weights, repeats=5, eval_draws=10, candidate_count=600):
    """Generate synthetic fair-lottery histories and see how much 'edge' the same model can hallucinate."""
    cfg=GAMES[game_key]
    if len(draws)<70:
        return {"status":"insufficient_data"}
    rng=random.Random(404)
    null_edges=[]
    n=min(len(draws),400)
    for r in range(repeats):
        synthetic=[]
        for i in range(n):
            nums=sorted(rng.sample(range(1,cfg.max_number+1),cfg.pick))
            rest=[x for x in range(1,cfg.max_number+1) if x not in nums]
            bonus=rng.choice(rest)
            synthetic.append({"draw_date":f"2000-01-{(i%28)+1:02d}-{i:04d}","numbers":nums,"bonus":bonus})
        res=walk_forward_test(game_key,synthetic,weights,eval_draws=eval_draws,candidate_count=candidate_count,top_n=8,seed=500+r)
        if res.get("status")=="ok": null_edges.append(res["edge"])
    return {
        "status":"ok","null_mean_edge":mean(null_edges) if null_edges else None,
        "null_max_edge":max(null_edges) if null_edges else None,
        "repeats":len(null_edges)
    }


def random_control_walk_forward(game_key, draws, weights, eval_draws=20, candidate_count=900, top_n=8, seed=1600):
    """Paired historical Production vs frozen-style no-signal Random Control."""
    from .research_engine import RandomControlEngine
    if len(draws) < max(60, eval_draws + 20):
        return {"status": "insufficient_data", "needed": max(60, eval_draws + 20), "have": len(draws)}
    start = max(50, len(draws) - eval_draws)
    rows = []
    for i in range(start, len(draws)):
        history = draws[:i]
        actual = set(draws[i]["numbers"])
        prod = PredictionEngine(game_key, history, weights, seed=seed + i).generate(
            candidate_count=candidate_count, top_n=top_n
        )
        rnd = RandomControlEngine(game_key, seed=seed * 10 + i).generate(
            top_n=top_n, candidate_count=max(800, candidate_count)
        )
        ph = [len(actual & set(p["numbers"])) for p in prod]
        rh = [len(actual & set(p["numbers"])) for p in rnd]
        rows.append({
            "date": draws[i]["draw_date"],
            "production_avg": mean(ph), "random_avg": mean(rh),
            "production_best": max(ph), "random_best": max(rh),
        })
    diffs = [r["production_avg"] - r["random_avg"] for r in rows]
    z = paired_z_score(diffs)
    critical = paired_t_critical_95(len(diffs))
    return {
        "status": "ok", "n": len(rows),
        "production_avg": mean(r["production_avg"] for r in rows),
        "random_control_avg": mean(r["random_avg"] for r in rows),
        "production_minus_random": mean(diffs),
        "production_best": mean(r["production_best"] for r in rows),
        "random_control_best": mean(r["random_best"] for r in rows),
        "z_score": z,
        "test_statistic": "paired_t",
        "critical_95": critical,
        "significant_95": abs(z) >= critical,
        "interpretation": "HISTORICAL SCREENING SIGNAL - FORWARD CONFIRMATION REQUIRED" if z >= critical and mean(diffs) > 0 else "NO VERIFIED EDGE",
        "note": "Legacy structure-control diagnostic only; Bayesian strategy evidence uses self-null baselines in V1.6.1.",
    }



def feature_ablation_test(game_key, draws, weights, eval_draws=6, candidate_count=420, top_n=8, seed=2600):
    """Shadow-only leave-one-factor-out audit using identical candidate pools.

    A positive ``without_minus_full`` means historical average hit count improved
    when that factor was removed. That is a warning to investigate, not evidence
    that the factor is harmful in future draws. Small samples are labelled clearly.
    """
    min_needed = max(36, eval_draws + 24)
    if len(draws) < min_needed:
        return {"status": "insufficient_data", "needed": min_needed, "have": len(draws)}
    eff = normalize_main_weights(weights)
    start = max(30, len(draws) - eval_draws)
    factors = list(PREDICTIVE_FACTORS)
    full_hits = []
    ablated_hits = {f: [] for f in factors}
    for i in range(start, len(draws)):
        history = draws[:i]
        actual = set(draws[i]["numbers"])
        pair_seed = seed + i
        full = PredictionEngine(game_key, history, eff, seed=pair_seed).generate(
            candidate_count=candidate_count, top_n=top_n)
        full_hits.append(mean(len(actual & set(r["numbers"])) for r in full))
        for f in factors:
            w = dict(eff)
            w[f] = 0.0
            w = normalize_main_weights(w)
            rows = PredictionEngine(game_key, history, w, seed=pair_seed).generate(
                candidate_count=candidate_count, top_n=top_n)
            ablated_hits[f].append(mean(len(actual & set(r["numbers"])) for r in rows))
    baseline = mean(full_hits) if full_hits else 0.0
    details = []
    for f in factors:
        avg = mean(ablated_hits[f]) if ablated_hits[f] else 0.0
        delta = avg - baseline
        details.append({
            "factor": f,
            "full_avg_hit": round(baseline, 4),
            "without_factor_avg_hit": round(avg, 4),
            "without_minus_full": round(delta, 4),
            "screen": "INVESTIGATE" if delta >= 0.05 else ("SUPPORTIVE" if delta <= -0.05 else "NEUTRAL"),
        })
    details.sort(key=lambda x: x["without_minus_full"], reverse=True)
    return {
        "status": "ok",
        "n": len(full_hits),
        "sample_state": "LOW" if len(full_hits) < 20 else ("MEDIUM" if len(full_hits) < 50 else "HIGH"),
        "full_avg_hit": round(baseline, 4),
        "random_baseline": round(GAMES[game_key].pick * GAMES[game_key].pick / GAMES[game_key].max_number, 4),
        "factors": details,
        "interpretation": "SHADOW DIAGNOSTIC ONLY; positive removal delta is a review flag, not proof of future advantage.",
    }


def rank_stability_test(game_key, draws, weights, transitions=5, candidate_count=500, top_n=10, seed=3600):
    """Measure how much the selected portfolio moves after adding one historical draw.

    The before/after pair uses the same random candidate seed, isolating sensitivity
    to the newly added data rather than candidate-pool randomness.
    """
    if len(draws) < 32:
        return {"status": "insufficient_data", "needed": 32, "have": len(draws)}
    eff = normalize_main_weights(weights)
    start = max(30, len(draws) - transitions)
    rows = []
    for i in range(start, len(draws)):
        before_hist = draws[:i]
        after_hist = draws[:i+1]
        if len(before_hist) < 20:
            continue
        pair_seed = seed + i
        before = PredictionEngine(game_key, before_hist, eff, seed=pair_seed).generate(
            candidate_count=candidate_count, top_n=top_n)
        after = PredictionEngine(game_key, after_hist, eff, seed=pair_seed).generate(
            candidate_count=candidate_count, top_n=top_n)
        bset = {tuple(r["numbers"]) for r in before}
        aset = {tuple(r["numbers"]) for r in after}
        bnums = set().union(*(set(r["numbers"]) for r in before)) if before else set()
        anums = set().union(*(set(r["numbers"]) for r in after)) if after else set()
        retention = 100.0 * len(bset & aset) / max(1, min(len(bset), len(aset)))
        union = bnums | anums
        number_jaccard = 100.0 * len(bnums & anums) / max(1, len(union))
        top1_same = bool(before and after and tuple(before[0]["numbers"]) == tuple(after[0]["numbers"]))
        rows.append({
            "added_draw": draws[i]["draw_date"],
            "ticket_retention_pct": round(retention, 2),
            "number_pool_jaccard_pct": round(number_jaccard, 2),
            "top1_same": top1_same,
        })
    if not rows:
        return {"status": "insufficient_data", "needed": 32, "have": len(draws)}
    tr = mean(r["ticket_retention_pct"] for r in rows)
    nj = mean(r["number_pool_jaccard_pct"] for r in rows)
    t1 = 100.0 * mean(1.0 if r["top1_same"] else 0.0 for r in rows)
    # Exact ticket retention is naturally stricter than number-exposure stability.
    if nj >= 75 and tr >= 25:
        label = "HIGH"
    elif nj >= 60 and tr >= 10:
        label = "MEDIUM"
    else:
        label = "LOW"
    return {
        "status": "ok", "n": len(rows), "stability": label,
        "ticket_retention_pct": round(tr, 2),
        "number_pool_jaccard_pct": round(nj, 2),
        "top1_retention_pct": round(t1, 2),
        "rows": rows,
        "interpretation": "Sensitivity diagnostic only. Low stability means small data updates materially change the ranked portfolio.",
    }


def coverage_strategy_backtest(game_key, draws, weights, eval_draws=8, candidate_count=700, top_n=8, seed=4600):
    """Shadow-only same-budget comparison of portfolio selection strategies.

    Every historical target uses only prior draws. The four model strategies share the
    exact same scored candidate pool, isolating portfolio-selection effects from candidate RNG.
    """
    from .coverage import CoverageOptimizer, coverage_summary
    from .research_engine import RandomControlEngine
    min_needed = max(40, eval_draws + 25)
    if len(draws) < min_needed:
        return {"status":"insufficient_data", "needed":min_needed, "have":len(draws)}
    start = max(30, len(draws) - eval_draws)
    names = ("score_only", "balanced", "focused", "pure_coverage", "random")
    acc = {name: {"avg_hit":[], "best_hit":[], "ce":[]} for name in names}
    rows = []
    for i in range(start, len(draws)):
        history = draws[:i]
        actual = set(draws[i]["numbers"])
        engine = PredictionEngine(game_key, history, weights, seed=seed+i)
        candidates = engine.scored_candidates(candidate_count=candidate_count)
        draw_row = {"date": draws[i]["draw_date"]}
        for mode in ("score_only", "balanced", "focused", "pure_coverage"):
            portfolio = CoverageOptimizer(game_key, mode).optimize(candidates, top_n=top_n)
            hits = [len(actual & set(r["numbers"])) for r in portfolio]
            summ = coverage_summary(portfolio, game_key)
            acc[mode]["avg_hit"].append(mean(hits))
            acc[mode]["best_hit"].append(max(hits))
            acc[mode]["ce"].append(float(summ.get("coverage_efficiency", 0.0)))
            draw_row[mode] = {"avg_hit": round(mean(hits),4), "best_hit": max(hits), "ce": summ.get("coverage_efficiency")}
        rnd = RandomControlEngine(game_key, seed=seed*10+i).generate(top_n=top_n, candidate_count=max(700,candidate_count))
        rhits = [len(actual & set(r["numbers"])) for r in rnd]
        rs = coverage_summary(rnd, game_key)
        acc["random"]["avg_hit"].append(mean(rhits))
        acc["random"]["best_hit"].append(max(rhits))
        acc["random"]["ce"].append(float(rs.get("coverage_efficiency",0.0)))
        draw_row["random"] = {"avg_hit":round(mean(rhits),4), "best_hit":max(rhits), "ce":rs.get("coverage_efficiency")}
        rows.append(draw_row)
    result = {"status":"ok", "n":len(rows), "same_budget_lines":top_n, "strategies":{}}
    for name in names:
        result["strategies"][name] = {
            "avg_hit": round(mean(acc[name]["avg_hit"]),4),
            "avg_best_hit": round(mean(acc[name]["best_hit"]),4),
            "coverage_efficiency": round(mean(acc[name]["ce"]),2),
        }
    b = result["strategies"]["balanced"]
    t = result["strategies"]["score_only"]
    result["balanced_minus_topscore_avg_hit"] = round(b["avg_hit"] - t["avg_hit"],4)
    result["balanced_minus_topscore_ce"] = round(b["coverage_efficiency"] - t["coverage_efficiency"],2)
    result["interpretation"] = "SHADOW SAME-BUDGET PORTFOLIO TEST; coverage efficiency can improve without implying higher official draw probability."
    result["rows"] = rows
    return result


def bayesian_strategy_walk_forward(game_key, draws, weights, eval_draws=24,
                                   candidate_count=520,
                                   line_counts=(3, 5, 8, 10, 20), seed=5600):
    """Leakage-safe historical evidence for Bayesian strategy comparison.

    Each historical target is generated from prior draws only.  Every strategy sees
    the exact same scored candidate pool, and every line count is evaluated as a
    prefix of the same frozen Top-20 portfolio.  That mirrors the live rank-
    concentration monitor instead of regenerating an easier portfolio for each k.
    """
    from .coverage import CoverageOptimizer

    # Historical evidence must not inherit weights tuned with later draws. Until
    # per-draw historical weight snapshots are available, use the immutable default
    # policy for every replay target. This is deliberately less adaptive but avoids
    # hyperparameter leakage from the present into the past.
    weights = normalize_main_weights(GAMES[game_key].default_weights)

    min_needed = 32
    if len(draws) < min_needed:
        return {"status": "insufficient_data", "needed": min_needed, "have": len(draws), "observations": []}
    available = max(1, len(draws) - 30)
    eval_draws = min(max(1, int(eval_draws)), available)
    start = max(30, len(draws) - eval_draws)
    ks = tuple(sorted({int(k) for k in line_counts if 1 <= int(k) <= 20}))
    modes = ("score_only", "balanced", "focused", "pure_coverage", "concentrated")
    observations = []

    def metrics(rows, actual, k):
        subset = list(rows or [])[:int(k)]
        if not subset:
            return {"avg_hit": 0.0, "best_hit": 0.0, "coverage": 0.0, "wce": 0.0}
        hits = [len(actual & set(map(int, row.get("numbers") or []))) for row in subset]
        union = set().union(*(set(map(int, row.get("numbers") or [])) for row in subset))
        coverage = len(actual & union)
        best = max(hits)
        return {
            "avg_hit": mean(hits),
            "best_hit": float(best),
            "coverage": float(coverage),
            "wce": float(best / coverage) if coverage else 0.0,
        }

    for i in range(start, len(draws)):
        history = draws[:i]
        actual = set(map(int, draws[i].get("numbers") or []))
        engine = PredictionEngine(game_key, history, weights, seed=seed + i)
        candidates = engine.scored_candidates(candidate_count=max(60, int(candidate_count)))
        portfolios = {
            mode: CoverageOptimizer(game_key, mode).optimize(candidates, top_n=20)
            for mode in modes
        }
        nulls = {
            mode: portfolio_null_prefix_expectations(game_key, portfolios[mode], ks)
            for mode in modes
        }
        for k in ks:
            for mode in modes:
                row_metric = metrics(portfolios[mode], actual, k)
                null_metric = nulls[mode][int(k)]
                observations.append({
                    "source": "historical",
                    "game": game_key,
                    "draw_date": str(draws[i].get("draw_date")),
                    "strategy": mode,
                    "lines": int(k),
                    "variant": f"{mode}@{int(k)}",
                    "null_method": null_metric.get("method"),
                    "best_hit_edge": round(row_metric["best_hit"] - null_metric["best_hit"], 8),
                    "avg_hit_edge": round(row_metric["avg_hit"] - null_metric["avg_hit"], 8),
                    "coverage_edge": round(row_metric["coverage"] - null_metric["coverage"], 8),
                    "wce_edge": round(row_metric["wce"] - null_metric["wce"], 8),
                })

    summary = {}
    for variant in sorted({row["variant"] for row in observations}):
        vals = [row for row in observations if row["variant"] == variant]
        summary[variant] = {
            "n": len(vals),
            "mean_best_hit_edge": round(mean(row["best_hit_edge"] for row in vals), 8),
            "mean_avg_hit_edge": round(mean(row["avg_hit_edge"] for row in vals), 8),
            "mean_coverage_edge": round(mean(row["coverage_edge"] for row in vals), 8),
            "mean_wce_edge": round(mean(row["wce_edge"] for row in vals), 8),
        }
    return {
        "status": "ok",
        "game": game_key,
        "n_draws": len({row["draw_date"] for row in observations}),
        "line_counts": list(ks),
        "strategies": list(modes),
        "candidate_count": int(candidate_count),
        "historical_weight_policy": "FIXED_DEFAULT_NO_FUTURE_WEIGHT_LEAKAGE",
        "summary": summary,
        "observations": observations,
        "note": "Historical walk-forward only; each target uses prior draws. Every portfolio is scored against its own fair-lottery self-null, removing Random Control structure bias.",
    }
