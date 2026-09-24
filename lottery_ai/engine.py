from __future__ import annotations

import random
from math import comb
from .fastmath import mean

from .analysis import FeatureEngine
from .config import GAMES, normalize_main_weights
from .coverage import CoverageOptimizer, coverage_summary, candidate_number_profile
from .integrity import candidate_pool_hash, candidate_universe_hash


def crowd_risk(combo):
    # Single source of truth with the Research UI proxy. This label is descriptive
    # sharing-risk only and never changes winning probability.
    from .research_engine import crowd_proxy
    return crowd_proxy(combo)["risk"]


def weighted_score(components, weights):
    return sum(weights.get(k,0)*components.get(k,50) for k in weights)


class PredictionEngine:
    def __init__(self, game_key, draws, weights, seed=42):
        self.game_key = game_key
        self.cfg = GAMES[game_key]
        self.draws = draws
        self.raw_weights = dict(weights or {})
        self.weights = normalize_main_weights(weights)
        self.features = FeatureEngine(game_key, draws)
        self.rng = random.Random(seed)
        self.last_portfolio_summary = {}
        self.last_candidate_number_profile = []

    def _scored_candidates(self, candidate_count=12000, neural_scores=None):
        """Generate and score legal candidates without deciding portfolio membership.

        V1.2.3 integrity rule: Main Combination Score is produced here and is never
        modified by the Coverage Optimizer. Portfolio selection happens afterwards.
        """
        seen = set()
        rows = []
        pool = list(range(1, self.cfg.max_number+1))
        requested = max(0, int(candidate_count))
        legal_total = comb(self.cfg.max_number, self.cfg.pick)
        target_count = min(requested, legal_total)
        if target_count == 0:
            self.last_candidate_generation = {
                "requested": requested, "target": target_count, "generated": 0,
                "guard_triggered": False,
            }
            return []
        # In today's games the legal universe is huge relative to 12k candidates, so
        # duplicates are rare. The guard prevents pathological/future filtered spaces
        # from spinning forever if the feasible universe becomes much smaller.
        max_attempts = max(10_000, target_count * 100)
        stagnation_limit = max(5_000, target_count * 20)
        attempts = 0
        stagnant = 0
        while len(rows) < target_count and attempts < max_attempts and stagnant < stagnation_limit:
            attempts += 1
            combo = tuple(sorted(self.rng.sample(pool, self.cfg.pick)))
            if combo in seen:
                stagnant += 1
                continue
            stagnant = 0
            seen.add(combo)
            c = self.features.component_scores(combo)
            prelim = weighted_score(c, self.weights)
            rows.append({"numbers": combo, "components": c, "prelim": prelim})
        self.last_candidate_generation = {
            "requested": requested, "target": target_count, "generated": len(rows),
            "guard_triggered": len(rows) < target_count, "attempts": attempts,
        }

        # Monte Carlo diagnostic: compare the six-factor Main score against several
        # independent reference slices. IMPORTANT: this percentile is derived from
        # the model score itself and therefore has 0% ranking weight. It is retained
        # only as a stability/context diagnostic, never as a second prediction vote.
        import bisect
        base_weights = {k:v for k,v in self.weights.items() if k != "monte_carlo"}
        norm = sum(base_weights.values()) or 1.0
        base_weights = {k:v/norm for k,v in base_weights.items()}
        for r in rows:
            r["base_score"] = weighted_score(r["components"], base_weights)
        runs = 8
        refs = []
        shuffled = rows[:]
        self.rng.shuffle(shuffled)
        chunk = min(len(shuffled), max(200, len(shuffled)//runs))
        for i in range(runs):
            start = i * chunk
            sample = shuffled[start:start+chunk]
            if len(sample) < 50:
                # Small candidate pools used in backtests can run past the one-time
                # partition. Build a fresh seeded reference slice rather than reusing
                # shuffled[:chunk] verbatim for multiple diagnostic replicates.
                sample = self.rng.sample(rows, chunk) if chunk < len(rows) else rows[:]
            refs.append(sorted(x["base_score"] for x in sample))
        for r in rows:
            ps=[]
            for vals in refs:
                ps.append(100.0 * bisect.bisect_right(vals, r["base_score"]) / len(vals))
            avgp = mean(ps) if ps else 50.0
            spread = (max(ps)-min(ps)) if ps else 0.0
            stability = max(0.0, min(100.0, avgp - 0.20*spread))
            r["components"]["monte_carlo"] = stability
            r["score"] = r["base_score"]
            r["monte_carlo_diagnostic"] = stability
            r["crowd_risk"] = crowd_risk(r["numbers"])
            if neural_scores:
                r["nn_shadow"] = mean(neural_scores.get(n,50) for n in r["numbers"])
            else:
                r["nn_shadow"] = None
        rows.sort(key=lambda r: (-r["score"], tuple(r["numbers"])))
        return rows

    def generate(self, candidate_count=12000, top_n=20, neural_scores=None, coverage_mode="balanced"):
        """Return a fixed-size portfolio.

        ``coverage_mode='balanced'`` remains the V1.2.3 official default. Other modes are
        research/benchmark modes and never auto-replace Production. ``score_only``
        reproduces simple Main-score ranking for baselines and candidate feeds.
        """
        rows = self._scored_candidates(candidate_count=candidate_count, neural_scores=neural_scores)
        self.last_candidate_number_profile = candidate_number_profile(rows, self.cfg.max_number)
        selected = CoverageOptimizer(self.game_key, coverage_mode).optimize(rows, top_n=top_n)

        # Display order is Combination Score descending. Portfolio membership itself was
        # determined by the optimizer, so rank remains a display rank rather than selection order.
        selected.sort(key=lambda r: (-float(r.get("score", 0.0)), tuple(r.get("numbers", []))))
        for rank, r in enumerate(selected, 1):
            r["rank"] = rank
            r["score"] = round(float(r["score"]), 2)
            r["components"] = {k: round(v,2) for k,v in r["components"].items()}
            if r.get("nn_shadow") is not None:
                r["nn_shadow"] = round(r["nn_shadow"],2)
            if r.get("portfolio_value") is not None:
                r["portfolio_value"] = round(float(r["portfolio_value"]), 2)
        self.last_portfolio_summary = coverage_summary(selected, self.game_key)
        return selected

    def generate_strategy_suite(self, candidate_count=12000, top_n=20, neural_scores=None,
                                modes=("balanced", "score_only", "focused", "pure_coverage", "concentrated")):
        """Generate several portfolio strategies from the exact same scored candidate pool.

        V1.4 uses this for fair same-budget shadow comparison. Main Combination Scores and
        components are calculated once, before any portfolio optimizer sees the candidates.
        The returned candidate-pool hash is frozen as provenance so later comparisons can
        verify that the strategies really shared the same pre-draw opportunity set.
        """
        rows = self._scored_candidates(candidate_count=candidate_count, neural_scores=neural_scores)
        pool_hash = candidate_pool_hash(rows)
        universe_hash = candidate_universe_hash(rows)
        number_profile = candidate_number_profile(rows, self.cfg.max_number)
        self.last_candidate_number_profile = number_profile
        portfolios = {}
        summaries = {}
        for mode in modes:
            selected = CoverageOptimizer(self.game_key, mode).optimize(rows, top_n=top_n)
            selected.sort(key=lambda r: (-float(r.get("score", 0.0)), tuple(r.get("numbers", []))))
            for rank, row in enumerate(selected, 1):
                row["rank"] = rank
                row["score"] = round(float(row.get("score", 0.0)), 2)
                row["components"] = {k: round(float(v), 2) for k, v in (row.get("components") or {}).items()}
                if row.get("nn_shadow") is not None:
                    row["nn_shadow"] = round(float(row["nn_shadow"]), 2)
                if row.get("portfolio_value") is not None:
                    row["portfolio_value"] = round(float(row["portfolio_value"]), 2)
            portfolios[mode] = selected
            summaries[mode] = coverage_summary(selected, self.game_key)
        return {
            "candidate_pool_hash": pool_hash,
            "candidate_universe_hash": universe_hash,
            "candidate_count": len(rows),
            "candidate_number_profile": number_profile,
            "portfolios": portfolios,
            "summaries": summaries,
        }

    def scored_candidates(self, candidate_count=12000, limit=None, neural_scores=None):
        """Public research helper returning Main-score-ranked candidates only."""
        rows = self._scored_candidates(candidate_count=candidate_count, neural_scores=neural_scores)
        if limit is not None:
            rows = rows[:max(0, int(limit))]
        return rows

    def bonus_rank(self, main_combo, limit=10, weights=None):
        return self.features.bonus_ranking(excluded=main_combo, limit=limit, weights=weights)

    def region_summary(self):
        return self.features.region_summary()
