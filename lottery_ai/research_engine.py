from __future__ import annotations

import hashlib
import random
from itertools import combinations
from math import comb
from .fastmath import mean

from .config import GAMES
from .regime import eligible_number_profile


def _clamp(x, lo=0.0, hi=100.0):
    return max(lo, min(hi, float(x)))


def stable_seed(game_key: str, target_date: str, label: str) -> int:
    raw = f"{game_key}|{target_date}|{label}|LotteryAI-V1.6.1".encode("utf-8")
    return int.from_bytes(hashlib.sha256(raw).digest()[:8], "big") & 0x7FFFFFFF


def crowd_proxy(combo):
    """Heuristic human-selection proxy; never a winning-probability model."""
    a = sorted(int(x) for x in combo)
    k = len(a)
    birthday_share = sum(n <= 31 for n in a) / max(1, k)
    consecutive = sum(1 for x, y in zip(a, a[1:]) if y - x == 1)
    same_last = k - len({n % 10 for n in a})
    gaps = [y - x for x, y in zip(a, a[1:])]
    repeated_gaps = len(gaps) - len(set(gaps)) if gaps else 0
    round_fives = sum(n % 5 == 0 for n in a)
    lucky_bias = sum(n in {3, 7, 8, 9, 11, 13, 21} for n in a)
    risk = 0.0
    risk += 48.0 * max(0.0, birthday_share - 0.50) / 0.50
    risk += 10.0 * min(2, consecutive)
    risk += 5.0 * min(3, same_last)
    risk += 5.0 * min(2, repeated_gaps)
    risk += 3.0 * max(0, round_fives - 1)
    risk += 2.0 * max(0, lucky_bias - 2)
    risk = _clamp(risk)
    label = "HIGH" if risk >= 55 else ("MEDIUM" if risk >= 25 else "LOW")
    return {
        "risk": label,
        "risk_score": round(risk, 2),
        "avoidance": round(100.0 - risk, 2),
        "birthday_share": round(birthday_share, 3),
        "consecutive_pairs": consecutive,
        "repeated_endings": same_last,
        "repeated_gaps": repeated_gaps,
    }


def portfolio_summary(rows, game_key):
    cfg = GAMES[game_key]
    if not rows:
        return {}
    sets = [set(r["numbers"]) for r in rows]
    ovs = [len(a & b) for a, b in combinations(sets, 2)]
    avg_ov = mean(ovs) if ovs else 0.0
    unique = len(set().union(*sets))
    crowd = [float(r.get("crowd_avoidance", 50.0)) for r in rows]
    return {
        "tickets": len(rows),
        "unique_numbers": unique,
        "pool_coverage_pct": round(100.0 * unique / cfg.max_number, 2),
        "avg_pair_overlap": round(avg_ov, 3),
        "max_pair_overlap": int(max(ovs) if ovs else 0),
        "diversity_score": round(_clamp(100.0 * (1.0 - avg_ov / max(1, cfg.pick))), 2),
        "mean_crowd_avoidance": round(mean(crowd), 2),
        "high_crowd_risk_tickets": sum(1 for r in rows if r.get("crowd_risk") == "HIGH"),
    }


class RandomControlEngine:
    """No-history frozen comparator with diversity matching for portfolio statistics."""
    def __init__(self, game_key: str, seed: int):
        self.game_key = game_key
        self.cfg = GAMES[game_key]
        self.rng = random.Random(seed)

    def generate(self, top_n=20, candidate_count=2500):
        pool = list(range(1, self.cfg.max_number + 1))
        seen, candidates = set(), []
        requested = max(int(top_n), int(candidate_count), 0)
        target = min(requested, comb(self.cfg.max_number, self.cfg.pick))
        max_attempts = max(10_000, target * 100) if target else 0
        attempts = 0
        stagnant = 0
        stagnation_limit = max(5_000, target * 20) if target else 0
        while len(candidates) < target and attempts < max_attempts and stagnant < stagnation_limit:
            attempts += 1
            combo = tuple(sorted(self.rng.sample(pool, self.cfg.pick)))
            if combo in seen:
                stagnant += 1
                continue
            stagnant = 0
            seen.add(combo)
            cp = crowd_proxy(combo)
            candidates.append({
                "numbers": combo, "score": 50.0, "components": {},
                "crowd_risk": cp["risk"], "crowd_avoidance": cp["avoidance"],
                "control_type": "uniform_random_diversity_matched", "nn_shadow": None,
            })
        selected = []
        while candidates and len(selected) < top_n:
            if not selected:
                idx = 0
            else:
                def key(i):
                    nums = set(candidates[i]["numbers"])
                    ovs = [len(nums & set(s["numbers"])) for s in selected]
                    return (max(ovs), mean(ovs), self.rng.random())
                idx = min(range(len(candidates)), key=key)
            selected.append(candidates.pop(idx))
        for i, row in enumerate(selected, 1):
            row["rank"] = i
        return selected


class ResearchPortfolioOptimizer:
    """Shadow-only optimizer using model quality, regime normalization and diversity.

    Crowd/sharing-risk is computed only for display/audit. It has zero ranking weight.
    """
    def __init__(self, game_key: str, all_draws: list[dict]):
        self.game_key = game_key
        self.cfg = GAMES[game_key]
        self.profile = eligible_number_profile(game_key, all_draws)

    def _regime_score(self, combo):
        vals = [self.profile.get(int(n), {}).get("research_score", 50.0) for n in combo]
        return mean(vals) if vals else 50.0

    def optimize(self, candidates: list[dict], top_n=20):
        pool = []
        for src in candidates:
            r = dict(src)
            r["numbers"] = tuple(int(n) for n in src["numbers"])
            model_score = float(src.get("score", 50.0))
            cp = crowd_proxy(r["numbers"])
            regime_score = self._regime_score(r["numbers"])
            r["model_score"] = round(model_score, 2)
            r["crowd_risk"] = cp["risk"]
            r["crowd_avoidance"] = cp["avoidance"]
            r["regime_score"] = round(regime_score, 2)
            # V1.2: sharing/crowd risk is advisory only. It must never decide which
            # combination is predicted. Keep it visible, but give it exactly 0%
            # ranking weight.
            r["research_base"] = 0.90 * model_score + 0.10 * regime_score
            pool.append(r)
        pool.sort(key=lambda r: r["research_base"], reverse=True)
        selected = []
        while pool and len(selected) < top_n:
            best_i, best_obj = 0, -1e9
            for i, r in enumerate(pool[:800]):
                if selected:
                    nums = set(r["numbers"])
                    ovs = [len(nums & set(s["numbers"])) for s in selected]
                    overlap_penalty = 3.5 * max(ovs) + 0.9 * mean(ovs)
                else:
                    overlap_penalty = 0.0
                obj = r["research_base"] - overlap_penalty
                if obj > best_obj:
                    best_i, best_obj = i, obj
            chosen = pool.pop(best_i)
            chosen["research_score"] = round(best_obj, 2)
            selected.append(chosen)
        selected.sort(key=lambda r: r["research_score"], reverse=True)
        for i, r in enumerate(selected, 1):
            r["rank"] = i
            # Keep a conventional score field for generic freeze/judge/UI code.
            r["score"] = r["research_score"]
        return selected
