from __future__ import annotations

from collections import Counter, defaultdict
from functools import lru_cache
from itertools import combinations
from math import comb, isfinite, sqrt
from statistics import stdev

from .fastmath import mean, pstdev

from .config import GAMES


_T95 = {
    1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365, 8: 2.306,
    9: 2.262, 10: 2.228, 11: 2.201, 12: 2.179, 13: 2.160, 14: 2.145, 15: 2.131, 16: 2.120,
    17: 2.110, 18: 2.101, 19: 2.093, 20: 2.086, 21: 2.080, 22: 2.074, 23: 2.069, 24: 2.064,
    25: 2.060, 26: 2.056, 27: 2.052, 28: 2.048, 29: 2.045, 30: 2.042, 40: 2.021, 60: 2.000,
    120: 1.980,
}


def paired_t_critical_95(n: int) -> float:
    """Two-sided 95% Student-t critical value for a paired sample size."""
    df = max(1, int(n) - 1)
    if df in _T95:
        return _T95[df]
    keys = sorted(_T95)
    if df > keys[-1]:
        # Smooth large-df Student-t approximation. This avoids the old artificial
        # df=120 -> 121 jump from 1.980 straight to 1.960 while remaining dependency-free.
        z = 1.959963984540054
        d = float(df)
        return z + (z**3 + z) / (4.0*d) + (5.0*z**5 + 16.0*z**3 + 3.0*z) / (96.0*d*d)
    lo = max(k for k in keys if k < df)
    hi = min(k for k in keys if k > df)
    frac = (df - lo) / (hi - lo)
    return _T95[lo] + frac * (_T95[hi] - _T95[lo])


def paired_z_score(diffs) -> float:
    """Backward-compatible name returning a paired Student-t statistic.

    V1.6.0 used population SD, which understated uncertainty at small n. V1.6.1
    uses sample SD (ddof=1). Callers should compare against paired_t_critical_95(n),
    not a fixed 1.96 threshold.
    """
    vals = [float(x) for x in diffs]
    if len(vals) < 2:
        return 0.0
    sd = stdev(vals)
    if not isfinite(sd) or sd <= 0.0:
        return 0.0
    md = mean(vals)
    t = md / (sd / sqrt(len(vals)))
    return float(t) if isfinite(t) else 0.0


def paired_t_significant_95(diffs) -> bool:
    vals = [float(x) for x in diffs]
    return len(vals) >= 2 and abs(paired_z_score(vals)) >= paired_t_critical_95(len(vals))


def clamp(x, lo=0.0, hi=100.0):
    return max(lo, min(hi, float(x)))


def minmax_map(values: dict[int, float], neutral=50.0) -> dict[int, float]:
    if not values:
        return {}
    lo, hi = min(values.values()), max(values.values())
    if hi <= lo:
        return {k: neutral for k in values}
    return {k: 100.0 * (v - lo) / (hi - lo) for k, v in values.items()}


@lru_cache(maxsize=8)
def exact_sum_distribution(max_number: int, pick: int) -> dict[int, int]:
    # Dynamic-programming exact combination counts: dp[k][sum].
    dp = [defaultdict(int) for _ in range(pick + 1)]
    dp[0][0] = 1
    for n in range(1, max_number + 1):
        for k in range(min(pick, n), 0, -1):
            for s, c in list(dp[k - 1].items()):
                dp[k][s + n] += c
    return dict(dp[pick])


@lru_cache(maxsize=8)
def exact_span_distribution(max_number: int, pick: int) -> dict[int, int]:
    out = {}
    # span = max-min; interior must contribute pick-2 values
    for span in range(pick - 1, max_number):
        interior = span - 1
        per_min = comb(interior, pick - 2) if interior >= pick - 2 else 0
        out[span] = (max_number - span) * per_min
    return out


@lru_cache(maxsize=8)
def exact_odd_distribution(max_number: int, pick: int) -> dict[int, int]:
    odds = (max_number + 1) // 2
    evens = max_number // 2
    out = {}
    for odd_count in range(pick + 1):
        even_count = pick - odd_count
        if odd_count <= odds and even_count <= evens:
            out[odd_count] = comb(odds, odd_count) * comb(evens, even_count)
    return out


def central_interval(dist: dict[int, int], mass=0.75):
    items = sorted(dist.items())
    total = sum(v for _, v in items)
    tails = (1 - mass) / 2
    lo_target, hi_target = tails * total, (1 - tails) * total
    cum = 0
    lo = items[0][0]
    hi = items[-1][0]
    for x, c in items:
        cum += c
        if cum >= lo_target:
            lo = x
            break
    cum = 0
    for x, c in items:
        cum += c
        if cum >= hi_target:
            hi = x
            break
    return lo, hi


class FeatureEngine:
    def __init__(self, game_key: str, draws: list[dict]):
        self.game_key = game_key
        self.cfg = GAMES[game_key]
        self.draws = draws
        self.N = max(1, len(draws))
        self.pool = range(1, self.cfg.max_number + 1)
        self.num_sets = [set(d["numbers"]) for d in draws]
        self.bonus = [d.get("bonus") for d in draws]
        self._build_number_features()
        self._build_pair_features()
        self._build_historical_structure()
        self._sum_dist = exact_sum_distribution(self.cfg.max_number, self.cfg.pick)
        self._span_dist = exact_span_distribution(self.cfg.max_number, self.cfg.pick)
        self._odd_dist = exact_odd_distribution(self.cfg.max_number, self.cfg.pick)
        self._sum_modal = max(self._sum_dist.values()) if self._sum_dist else 1
        self._span_modal = max(self._span_dist.values()) if self._span_dist else 1
        self._odd_modal = max(self._odd_dist.values()) if self._odd_dist else 1

    def _counts_window(self, n_draws):
        sets = self.num_sets[-n_draws:] if n_draws else self.num_sets
        c = Counter()
        for s in sets:
            c.update(s)
        return c

    def _build_number_features(self):
        counts = {w: self._counts_window(w) for w in (10, 20, 50, 100)}
        allc = self._counts_window(None)
        freq_raw, recent_raw, gap_raw = {}, {}, {}
        for n in self.pool:
            # Rates are normalized by opportunity, then blended.
            # Bayesian shrinkage toward the fair-draw base rate prevents tiny windows
            # from turning random streaks into extreme "hot" or "cold" scores.
            base_p = self.cfg.pick / self.cfg.max_number
            def bayes_rate(count, opportunities, prior_strength):
                a = base_p * prior_strength
                b = (1-base_p) * prior_strength
                return (count + a) / (max(1,opportunities) + a + b)
            n10, n20, n50, n100 = (max(1,min(w,self.N)) for w in (10,20,50,100))
            f10 = bayes_rate(counts[10][n], n10, 18)
            f20 = bayes_rate(counts[20][n], n20, 20)
            f50 = bayes_rate(counts[50][n], n50, 28)
            f100 = bayes_rate(counts[100][n], n100, 35)
            fall = bayes_rate(allc[n], self.N, 50)
            freq_raw[n] = .10*f10 + .15*f20 + .25*f50 + .25*f100 + .25*fall
            recent_raw[n] = .50*f10 + .30*f20 + .20*f50

            gap = 0
            for s in reversed(self.num_sets):
                if n in s:
                    break
                gap += 1
            gap_raw[n] = gap

        self.frequency_score = minmax_map(freq_raw)
        self.recent_score = minmax_map(recent_raw)
        # Gap is intentionally a weak two-sided feature: extreme overdue is not automatically "due".
        gaps = list(gap_raw.values())
        mu = mean(gaps) if gaps else 0
        sd = pstdev(gaps) or 1
        self.gap_score = {n: clamp(65 - 12*abs((g-mu)/sd)) for n, g in gap_raw.items()}
        self.gap_value = gap_raw

        bonus_counts = Counter(b for b in self.bonus if b is not None)
        bonus_freq = {n: bonus_counts[n] / self.N for n in self.pool}
        self.bonus_frequency_score = minmax_map(bonus_freq)
        bonus_gaps = {}
        for n in self.pool:
            g = 0
            for b in reversed(self.bonus):
                if b == n:
                    break
                g += 1
            bonus_gaps[n] = g
        bvals = list(bonus_gaps.values())
        bmu = mean(bvals) if bvals else 0
        bsd = pstdev(bvals) or 1
        self.bonus_gap_score = {n: clamp(65 - 10*abs((g-bmu)/bsd)) for n,g in bonus_gaps.items()}

    def _build_pair_features(self):
        pair_count = Counter()
        single_count = Counter()
        for s in self.num_sets:
            single_count.update(s)
            for a, b in combinations(sorted(s), 2):
                pair_count[(a,b)] += 1
        self.pair_lift = {}
        # A draw samples k distinct numbers from an M-number pool without replacement.
        # The old N*pa*pb expectation implicitly treated the two number events as if
        # they were sampled with replacement, biasing fair-random pair lift below 1.
        # Keep the existing empirical-marginal design, but apply the finite-population
        # correction so the null expectation matches without-replacement sampling.
        k = int(self.cfg.pick)
        M = int(self.cfg.max_number)
        finite_population_correction = ((k - 1) * M / (k * (M - 1))) if k > 0 and M > 1 else 1.0
        for (a,b), obs in pair_count.items():
            pa = single_count[a] / self.N
            pb = single_count[b] / self.N
            exp = self.N * pa * pb * finite_population_correction
            lift = obs / exp if exp > 0 else 1.0
            # Heavy shrinkage toward 1 prevents sparse pairs from dominating.
            shrink = obs / (obs + 12)
            self.pair_lift[(a,b)] = 1 + shrink*(lift-1)

    def _build_historical_structure(self):
        self.hist_sums = [sum(s) for s in self.num_sets]
        self.hist_spans = [max(s)-min(s) for s in self.num_sets] if self.num_sets else []
        self.hist_odd = [sum(n % 2 for n in s) for s in self.num_sets]
        self.hist_gap_var = []
        self.joint_region_counts = Counter()
        for s in self.num_sets:
            a = sorted(s)
            gaps = [b-a for a,b in zip(a, a[1:])]
            self.hist_gap_var.append(pstdev(gaps) if len(gaps) > 1 else 0)
            self.joint_region_counts[self._joint_key(a)] += 1
        # These values are invariant for every candidate scored against this history.
        # Precompute once instead of re-scanning thousands of historical values per row.
        hv = self.hist_gap_var
        self._gap_var_mu = mean(hv) if hv else 0.0
        self._gap_var_sd = (pstdev(hv) or 1.0) if hv else 1.0
        self._joint_modal = max(self.joint_region_counts.values()) if self.joint_region_counts else 1

    def _joint_key(self, combo):
        a = sorted(combo)
        s = sum(a)
        span = max(a)-min(a)
        odd = sum(n%2 for n in a)
        low = sum(n <= self.cfg.max_number/2 for n in a)
        cons = min(2, sum(1 for x,y in zip(a,a[1:]) if y-x==1))
        # Coarse bins deliberately reduce overfitting.
        return (s//15, span//5, odd, low, cons)

    def joint_region_score(self, combo):
        if not self.joint_region_counts:
            return 50.0
        c = self.joint_region_counts.get(self._joint_key(combo),0)
        modal = self._joint_modal
        # Add-one smoothing keeps unseen bins from becoming impossible.
        return clamp(100*(c+1)/(modal+1))

    def number_quality(self, combo):
        return mean(self.frequency_score[n] for n in combo)

    def pair_score(self, combo):
        lifts = [self.pair_lift.get(tuple(sorted((a,b))), 1.0) for a,b in combinations(combo,2)]
        if not lifts:
            return 50.0
        avg = mean(lifts)
        # Moderate mapping: lift 1 -> 50, 1.25 -> 75, 0.75 -> 25.
        return clamp(50 + 100*(avg-1))

    def region_score(self, combo):
        s = sum(combo)
        span = max(combo)-min(combo)
        odd = sum(n % 2 for n in combo)
        # Normalize each exact mass by its precomputed modal mass.
        ss = 100 * self._sum_dist.get(s, 0) / self._sum_modal
        ps = 100 * self._span_dist.get(span, 0) / self._span_modal
        os = 100 * self._odd_dist.get(odd, 0) / self._odd_modal
        exact = .50*ss + .30*ps + .20*os
        # Exact marginals dominate; the empirical joint region is only a modest overlay.
        return clamp(.75*exact + .25*self.joint_region_score(combo))

    def structure_score(self, combo):
        a = sorted(combo)
        gaps = [b-a for a,b in zip(a, a[1:])]
        gap_var = pstdev(gaps) if len(gaps) > 1 else 0
        consecutive = sum(1 for g in gaps if g == 1)
        # Penalize only very extreme clustering; common patterns stay near neutral/high.
        cons_score = 100 if consecutive <= 1 else (72 if consecutive == 2 else 45)
        # Compare gap variance to historical centre with robust-ish z.
        mu, sd = self._gap_var_mu, self._gap_var_sd
        gv_score = clamp(90 - 16*abs((gap_var-mu)/sd))
        # Range occupancy: encourage non-extreme low/high split without requiring 50/50.
        midpoint = self.cfg.max_number / 2
        low = sum(n <= midpoint for n in combo)
        imbalance = abs(low - self.cfg.pick/2)
        balance_score = clamp(100 - 18*imbalance)
        return clamp(.45*gv_score + .30*balance_score + .25*cons_score)

    def component_scores(self, combo):
        return {
            "frequency": self.number_quality(combo),
            "gap": mean(self.gap_score[n] for n in combo),
            "structure": self.structure_score(combo),
            "pairs": self.pair_score(combo),
            "recent": mean(self.recent_score[n] for n in combo),
            "region": self.region_score(combo),
            "monte_carlo": 50.0,  # replaced with percentile after candidate generation
        }

    def region_summary(self):
        sd = exact_sum_distribution(self.cfg.max_number, self.cfg.pick)
        spd = exact_span_distribution(self.cfg.max_number, self.cfg.pick)
        return {
            "sum_50": central_interval(sd, .50),
            "sum_75": central_interval(sd, .75),
            "sum_90": central_interval(sd, .90),
            "span_75": central_interval(spd, .75),
            "expected_sum": self.cfg.pick * (self.cfg.max_number + 1) / 2,
        }

    def bonus_components(self, n):
        return {
            "bonus_frequency": self.bonus_frequency_score[n],
            "bonus_gap": self.bonus_gap_score[n],
            "recent": self.recent_score[n],
        }

    def bonus_ranking(self, excluded=(), limit=10, weights=None):
        excluded = set(excluded)
        weights = weights or {"bonus_frequency":.55,"bonus_gap":.20,"recent":.25}
        rows = []
        for n in self.pool:
            if n in excluded:
                continue
            c = self.bonus_components(n)
            score = sum(weights.get(k,0)*c[k] for k in c)
            rows.append((n, round(score,2)))
        return sorted(rows, key=lambda x: (-x[1], x[0]))[:limit]
