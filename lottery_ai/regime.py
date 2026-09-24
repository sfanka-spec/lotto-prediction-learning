from __future__ import annotations

import math
from datetime import date

from .config import GAMES, GAME_REGIMES

# Backward-compatible public name; the source of truth lives in config.py.
REGIMES = GAME_REGIMES


def regime_for(game_key: str, draw_date: str | date):
    ds = draw_date.isoformat() if isinstance(draw_date, date) else str(draw_date)[:10]
    for r in REGIMES[game_key]:
        if ds >= r["start"] and (r["end"] is None or ds <= r["end"]):
            return dict(r)
    return dict(REGIMES[game_key][0])


def current_regime(game_key: str):
    return dict(REGIMES[game_key][-1])


def eligible_number_profile(game_key: str, all_draws: list[dict]):
    """Regime-normalized per-number history.

    Expected hits are summed draw-by-draw using pick / legal-pool-size, so newer
    Lotto Max numbers (51/52) are never treated as historically 'cold' merely
    because they did not exist in earlier regimes. This is descriptive/research
    evidence only, not a claim of predictive advantage.
    """
    cfg = GAMES[game_key]
    rows = {}
    for n in range(1, cfg.max_number + 1):
        eligible = hits = 0
        exp_hits = variance = 0.0
        for d in all_draws:
            reg = regime_for(game_key, d["draw_date"])
            if n > reg["max_number"]:
                continue
            eligible += 1
            p = cfg.pick / reg["max_number"]
            exp_hits += p
            variance += p * (1.0 - p)
            if n in set(d["numbers"]):
                hits += 1
        z = (hits - exp_hits) / math.sqrt(variance) if variance > 0 else 0.0
        ratio = hits / exp_hits if exp_hits > 0 else 1.0
        rows[n] = {
            "eligible_draws": eligible,
            "hits": hits,
            "expected_hits": round(exp_hits, 3),
            "observed_expected_ratio": round(ratio, 4),
            "z": round(z, 4),
        }
    # Convert z into a conservative 0..100 research rank; cap extremes so tiny
    # samples cannot dominate a research portfolio.
    zs = sorted((v["z"], n) for n, v in rows.items())
    rank = {n: i for i, (_, n) in enumerate(zs)}
    denom = max(1, len(zs) - 1)
    for n, v in rows.items():
        pct = 100.0 * rank[n] / denom
        eligible = v["eligible_draws"]
        reliability = min(1.0, eligible / 200.0)
        v["research_score"] = round(50.0 + (pct - 50.0) * reliability, 2)
    return rows


def regime_summary(game_key: str, all_draws: list[dict], model_draws: list[dict]):
    current = current_regime(game_key)
    counts = {r["name"]: 0 for r in REGIMES[game_key]}
    for d in all_draws:
        counts[regime_for(game_key, d["draw_date"])["name"]] += 1
    n = len(model_draws)
    if n < 100:
        sample_state = "LOW"
        neural_gate = "LOCKED / INSUFFICIENT DATA"
    elif n < 200:
        sample_state = "LIMITED"
        neural_gate = "SHADOW TRAINING ONLY"
    else:
        sample_state = "MATURE FOR EVALUATION"
        neural_gate = "ELIGIBLE FOR SHADOW EVALUATION"
    profile = eligible_number_profile(game_key, all_draws)
    strongest = sorted(profile.items(), key=lambda kv: abs(kv[1]["z"]), reverse=True)[:5]
    return {
        "current_regime": current["name"],
        "regime_start": current["start"],
        "pool": f"1-{current['max_number']}",
        "all_regime_counts": counts,
        "production_draws": n,
        "prior_draws_excluded": max(0, len(all_draws) - n) if game_key == "max" else 0,
        "sample_state": sample_state,
        "neural_gate": neural_gate,
        "strongest_normalized_deviations": [
            {"number": num, **vals} for num, vals in strongest
        ],
        "policy": (
            "Production uses current Lotto Max number-pool regime only; prior regimes remain research/reference data."
            if game_key == "max" else
            "6/49 uses one 1-49 number-pool regime; full audited history is eligible for Production features."
        ),
        "warning": "Regime deviations are descriptive research statistics, not proven predictive signals.",
    }
