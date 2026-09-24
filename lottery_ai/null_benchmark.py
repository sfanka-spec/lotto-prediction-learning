from __future__ import annotations

import hashlib
from functools import lru_cache
from math import sqrt

import numpy as np

from .config import GAMES

NULL_BENCHMARK_VERSION = "SELFNULL1.0"
DEFAULT_NULL_SAMPLES = 8192


def _stable_seed(label: str) -> int:
    return int.from_bytes(hashlib.sha256(str(label).encode("utf-8")).digest()[:8], "big") & 0x7FFFFFFF


def _canonical_tickets(rows) -> tuple[tuple[int, ...], ...]:
    return tuple(
        tuple(sorted(int(n) for n in (row.get("numbers") or [])))
        for row in (rows or [])
        if row.get("numbers")
    )


@lru_cache(maxsize=512)
def _cached_null(game: str, tickets: tuple[tuple[int, ...], ...], line_counts: tuple[int, ...],
                 samples: int) -> tuple[tuple[int, tuple], ...]:
    cfg = GAMES[game]
    n_numbers = int(cfg.max_number)
    pick = int(cfg.pick)
    samples = max(1024, int(samples))
    if not tickets:
        return tuple()

    ticket_matrix = np.zeros((n_numbers, len(tickets)), dtype=np.uint8)
    for j, ticket in enumerate(tickets):
        for number in ticket:
            if 1 <= int(number) <= n_numbers:
                ticket_matrix[int(number) - 1, j] = 1

    signature = f"{game}|{tickets}|{line_counts}|{samples}|{NULL_BENCHMARK_VERSION}"
    rng = np.random.default_rng(_stable_seed(signature))
    # Random-key sampling is exactly uniform over fixed-size subsets; the resulting
    # expectation is deterministic Monte Carlo, while avg-hit and union coverage use
    # their analytic fair-lottery expectations below.
    keys = rng.random((samples, n_numbers), dtype=np.float32)
    chosen = np.argpartition(keys, pick - 1, axis=1)[:, :pick]
    draw_matrix = np.zeros((samples, n_numbers), dtype=np.uint8)
    draw_matrix[np.arange(samples)[:, None], chosen] = 1
    hit_matrix = draw_matrix @ ticket_matrix

    out = []
    for k in line_counts:
        kk = min(max(1, int(k)), len(tickets))
        sub_hits = hit_matrix[:, :kk]
        best = sub_hits.max(axis=1).astype(np.float64)
        avg = sub_hits.mean(axis=1).astype(np.float64)
        union = ticket_matrix[:, :kk].any(axis=1).astype(np.uint8)
        coverage = (draw_matrix @ union).astype(np.float64)
        wce = np.divide(best, coverage, out=np.zeros_like(best), where=coverage > 0)

        exact_avg = pick * pick / n_numbers
        exact_coverage = pick * int(union.sum()) / n_numbers
        best_mean = float(best.mean())
        wce_mean = float(wce.mean())
        best_se = float(best.std(ddof=1) / sqrt(samples)) if samples > 1 else 0.0
        wce_se = float(wce.std(ddof=1) / sqrt(samples)) if samples > 1 else 0.0
        out.append((kk, (
            round(exact_avg, 10), round(best_mean, 10), round(exact_coverage, 10),
            round(wce_mean, 10), int(union.sum()), samples,
            round(best_se, 10), round(wce_se, 10),
        )))
    return tuple(out)


def portfolio_null_prefix_expectations(game: str, rows: list[dict], line_counts=(3, 5, 8, 10, 20),
                                       samples: int = DEFAULT_NULL_SAMPLES) -> dict[int, dict]:
    """Fair-lottery null expectation for each frozen portfolio prefix.

    Average ticket hits and cumulative winner coverage have analytic expectations.
    Best-ticket hit and WCE depend on the portfolio's overlap structure, so those two
    metrics use deterministic common-random-number Monte Carlo. This makes structurally
    concentrated and highly dispersed portfolios compare against *their own* null.
    """
    tickets = _canonical_tickets(rows)
    if not tickets:
        return {}
    ks = tuple(sorted({min(len(tickets), max(1, int(k))) for k in line_counts}))
    packed = _cached_null(str(game), tickets, ks, max(1024, int(samples)))
    result = {}
    for k, values in packed:
        avg_hit, best_hit, coverage, wce, union_size, sims, best_se, wce_se = values
        result[int(k)] = {
            "schema": NULL_BENCHMARK_VERSION,
            "method": "ANALYTIC_AVG_COVERAGE_PLUS_DETERMINISTIC_MC_BEST_WCE",
            "samples": int(sims),
            "unique_numbers": int(union_size),
            "avg_hit": float(avg_hit),
            "best_hit": float(best_hit),
            "coverage": float(coverage),
            "wce": float(wce),
            "best_hit_mc_se": float(best_se),
            "wce_mc_se": float(wce_se),
        }
    return result
