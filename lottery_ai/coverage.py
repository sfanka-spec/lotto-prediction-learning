from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from itertools import combinations
from math import comb
from .fastmath import mean
from typing import Iterable

from .config import GAMES

COVERAGE_ENGINE_VERSION = "COV1.3"


@dataclass(frozen=True)
class CoverageWeights:
    quality: float
    pairs: float
    triples: float
    numbers: float
    diversity: float


MODE_WEIGHTS = {
    # Official/default mode: prediction quality stays dominant.
    "balanced": CoverageWeights(0.50, 0.20, 0.15, 0.10, 0.05),
    # Research-only compression mode: still keeps a quality guardrail.
    "focused": CoverageWeights(0.35, 0.25, 0.20, 0.10, 0.10),
    # Benchmark only. It intentionally gives coverage more weight than quality.
    "pure_coverage": CoverageWeights(0.10, 0.35, 0.30, 0.15, 0.10),
    # Research-only concentration guard: preserves score/core repetition instead of
    # aggressively spreading every Pair/Triple. Never auto-promotes directly.
    "concentrated": CoverageWeights(0.72, 0.10, 0.06, 0.04, 0.08),
}


def _pairs(numbers: Iterable[int]) -> frozenset[tuple[int, int]]:
    return frozenset(combinations(tuple(sorted(map(int, numbers))), 2))


def _triples(numbers: Iterable[int]) -> frozenset[tuple[int, int, int]]:
    return frozenset(combinations(tuple(sorted(map(int, numbers))), 3))


def _structure_signature(numbers: Iterable[int], max_number: int) -> tuple[int, int, int, int, int]:
    nums = tuple(sorted(map(int, numbers)))
    odd = sum(n % 2 for n in nums)
    low = sum(n <= max_number / 2 for n in nums)
    consecutive = sum(1 for a, b in zip(nums, nums[1:]) if b - a == 1)
    total = sum(nums)
    span = nums[-1] - nums[0] if nums else 0
    # Deliberately coarse bins so the diversity term does not become a hidden predictor.
    sum_bin = total // max(1, len(nums) * 5)
    span_bin = span // 5
    return odd, low, consecutive, sum_bin, span_bin


def _structure_novelty(sig, selected_sigs) -> float:
    if not selected_sigs:
        return 100.0
    # Hamming-distance-style structural novelty. A signature need not be unique to score well.
    best_similarity = 0.0
    for other in selected_sigs:
        same = sum(1 for a, b in zip(sig, other) if a == b)
        best_similarity = max(best_similarity, same / len(sig))
    return 100.0 * (1.0 - best_similarity)


def _overlap_penalty(numbers, selected_numbers, pick: int) -> float:
    if not selected_numbers:
        return 0.0
    s = set(numbers)
    overlaps = [len(s & set(x)) for x in selected_numbers]
    max_overlap = max(overlaps)
    avg_overlap = mean(overlaps)
    # Soft threshold: 6/49 tolerates <=2 shared; 7-number games tolerate <=3 shared.
    normal = 2 if pick <= 6 else 3
    excess = max(0, max_overlap - normal)
    # Strong penalty only when the candidate starts becoming a near-duplicate.
    return 7.5 * excess + 1.2 * max(0.0, avg_overlap - 1.25)


def _quality_floor(rows: list[dict], shortlist_size: int) -> list[dict]:
    if not rows:
        return []
    shortlist = rows[: min(shortlist_size, len(rows))]
    best = float(shortlist[0].get("score", 0.0))
    # Never buy coverage by accepting a clearly inferior Main score.
    floor = best - 12.0
    kept = [r for r in shortlist if float(r.get("score", 0.0)) >= floor]
    return kept or shortlist[:1]


def infer_core_pool(rows: list[dict], size: int) -> list[int]:
    """Research-only model-weighted core pool for focused compression.

    This does NOT claim the chosen numbers have higher official draw probability. It merely
    defines the conditional number pool inside which a covering design can be tested.
    """
    if not rows:
        return []
    weighted: dict[int, float] = {}
    top = rows[: min(800, len(rows))]
    min_score = min(float(r.get("score", 0.0)) for r in top)
    for r in top:
        w = max(0.001, float(r.get("score", 0.0)) - min_score + 0.5)
        for n in r.get("numbers", []):
            weighted[int(n)] = weighted.get(int(n), 0.0) + w
    return [n for n, _ in sorted(weighted.items(), key=lambda kv: (-kv[1], kv[0]))[:size]]




def candidate_number_profile(rows: list[dict], max_number: int, sample_size: int = 800) -> list[dict]:
    """Build a deterministic pre-draw number-support ranking from scored candidates.

    This is *not* a probability model and never changes a candidate score.  It is a
    compact diagnostic view of where the already-computed combination model places
    its support before the portfolio optimizer spreads/concentrates tickets.  Keeping
    the ranking in the freeze lets post-draw diagnostics distinguish number-ranking
    quality from ticket-portfolio coverage.
    """
    if max_number <= 0:
        return []
    ordered = sorted(
        (dict(r) for r in (rows or [])),
        key=lambda r: (-float(r.get("score", 0.0)), tuple(r.get("numbers", []))),
    )[:max(1, int(sample_size))]
    support = {n: 0.0 for n in range(1, int(max_number) + 1)}
    if ordered:
        min_score = min(float(r.get("score", 0.0)) for r in ordered)
        for pos, row in enumerate(ordered, 1):
            # Score separation carries most of the signal; the mild reciprocal-rank
            # term preserves ordering information when many scores are nearly tied.
            score_weight = max(0.001, float(row.get("score", 0.0)) - min_score + 0.5)
            rank_weight = 1.0 + 0.20 / (pos ** 0.5)
            w = score_weight * rank_weight
            for n in row.get("numbers", []):
                n = int(n)
                if 1 <= n <= max_number:
                    support[n] += w
    max_support = max(support.values()) if support else 0.0
    ranked = sorted(support.items(), key=lambda kv: (-kv[1], kv[0]))
    return [
        {
            "rank": i,
            "number": int(n),
            "support": round(float(v), 8),
            "support_index": round(100.0 * float(v) / max_support, 4) if max_support > 0 else 0.0,
        }
        for i, (n, v) in enumerate(ranked, 1)
    ]

def coverage_summary(rows: list[dict], game_key: str) -> dict:
    cfg = GAMES[game_key]
    if not rows:
        return {}
    number_sets = [set(map(int, r.get("numbers", []))) for r in rows]
    unique_numbers = set().union(*number_sets) if number_sets else set()
    pair_sets = [_pairs(s) for s in number_sets]
    triple_sets = [_triples(s) for s in number_sets]
    unique_pairs = set().union(*pair_sets) if pair_sets else set()
    unique_triples = set().union(*triple_sets) if triple_sets else set()
    pair_slots = len(rows) * comb(cfg.pick, 2)
    triple_slots = len(rows) * comb(cfg.pick, 3)
    max_number_slots = min(cfg.max_number, len(rows) * cfg.pick)
    number_eff = 100.0 * len(unique_numbers) / max(1, max_number_slots)
    pair_eff = 100.0 * len(unique_pairs) / max(1, pair_slots)
    triple_eff = 100.0 * len(unique_triples) / max(1, triple_slots)

    overlaps = []
    for i in range(len(number_sets)):
        for j in range(i + 1, len(number_sets)):
            overlaps.append(len(number_sets[i] & number_sets[j]))

    signatures = [_structure_signature(s, cfg.max_number) for s in number_sets]
    sig_unique = len(set(signatures))
    structure_diversity = 100.0 * sig_unique / max(1, len(signatures))
    avg_score = mean(float(r.get("score", 0.0)) for r in rows)
    ce = 0.35 * number_eff + 0.35 * pair_eff + 0.30 * triple_eff
    overlap_pen = 0.0
    if overlaps:
        normal = 2 if cfg.pick <= 6 else 3
        overlap_pen = 2.5 * max(0, max(overlaps) - normal) + 0.5 * max(0.0, mean(overlaps) - 1.25)
    portfolio_score = max(
        0.0,
        min(100.0, 0.50 * avg_score + 0.20 * pair_eff + 0.15 * triple_eff + 0.10 * number_eff + 0.05 * structure_diversity - overlap_pen),
    )

    lines_per_play = getattr(cfg, "lines_per_play", 1) or 1
    # A displayed/model-directed line is not the same as a terminal package line.
    # LOTTO MAX gives four selections for $6, but only one can be user-directed;
    # the other three are terminal Quick Picks. Therefore 20 model-directed rows
    # require 20 purchases, not five. Keep package metadata explicit so cost/ROI
    # accounting cannot accidentally divide model lines by four.
    model_directed_purchases = len(rows)
    companion_quick_picks = len(rows) * max(0, lines_per_play - 1)
    total_physical_lines = model_directed_purchases * lines_per_play
    return {
        "coverage_engine": COVERAGE_ENGINE_VERSION,
        "mode": next((r.get("coverage_mode") for r in rows if r.get("coverage_mode")), "legacy_or_unknown"),
        "tickets": len(rows),
        "lines": len(rows),
        "lines_per_play": lines_per_play,
        "equivalent_plays": float(model_directed_purchases),
        "model_directed_purchases": model_directed_purchases,
        "companion_quick_pick_lines_if_all": companion_quick_picks,
        "total_physical_lines_if_all": total_physical_lines,
        "model_directed_cost_if_all": round(model_directed_purchases * float(getattr(cfg, "play_cost", 0.0) or 0.0), 2),
        "unique_numbers": len(unique_numbers),
        "number_pool_size": cfg.max_number,
        "number_pool_coverage_pct": round(100.0 * len(unique_numbers) / cfg.max_number, 2),
        "number_efficiency_pct": round(number_eff, 2),
        "unique_pairs": len(unique_pairs),
        "pair_slots": pair_slots,
        "pair_reuse": pair_slots - len(unique_pairs),
        "pair_efficiency_pct": round(pair_eff, 2),
        "pair_pool_coverage_pct": round(100.0 * len(unique_pairs) / max(1, comb(cfg.max_number, 2)), 3),
        "unique_triples": len(unique_triples),
        "triple_slots": triple_slots,
        "triple_reuse": triple_slots - len(unique_triples),
        "triple_efficiency_pct": round(triple_eff, 2),
        "triple_pool_coverage_pct": round(100.0 * len(unique_triples) / max(1, comb(cfg.max_number, 3)), 3),
        "avg_pair_overlap": round(mean(overlaps), 3) if overlaps else 0.0,
        "max_pair_overlap": max(overlaps) if overlaps else 0,
        "structure_diversity_pct": round(structure_diversity, 2),
        "avg_combination_score": round(avg_score, 2),
        "coverage_efficiency": round(ce, 2),
        "portfolio_score": round(portfolio_score, 2),
    }


def overlap_matrix(rows: list[dict], limit: int = 12) -> list[list[int]]:
    rows = rows[: max(0, int(limit))]
    sets = [set(map(int, r.get("numbers", []))) for r in rows]
    return [[0 if i == j else len(sets[i] & sets[j]) for j in range(len(sets))] for i in range(len(sets))]


class CoverageOptimizer:
    """Mandel-inspired portfolio selector using combinatorial coverage.

    It never changes a candidate's Main Combination Score. It only decides which
    already-scored candidates coexist in a fixed-size portfolio.
    """

    def __init__(self, game_key: str, mode: str = "balanced"):
        if mode not in MODE_WEIGHTS and mode != "score_only":
            raise ValueError(f"Unknown coverage mode: {mode}")
        self.game_key = game_key
        self.cfg = GAMES[game_key]
        self.mode = mode
        self.weights = MODE_WEIGHTS.get(mode)

    def _prepare(self, rows: list[dict], top_n: int) -> tuple[list[dict], list[int] | None]:
        ordered = sorted(rows, key=lambda r: (-float(r.get("score", 0.0)), tuple(r.get("numbers", []))))
        if self.mode == "score_only":
            return ordered, None
        shortlist_size = max(400, min(2500, max(top_n * 80, 800)))
        shortlist = _quality_floor(ordered, shortlist_size)
        core_pool = None
        if self.mode in {"focused", "concentrated"}:
            core_size = (15 if self.cfg.pick == 6 else 18) if self.mode == "focused" else (12 if self.cfg.pick == 6 else 14)
            core_pool = infer_core_pool(shortlist, core_size)
            core = set(core_pool)
            fully_inside = [r for r in shortlist if set(r.get("numbers", [])) <= core]
            if len(fully_inside) >= max(top_n * 3, top_n + 5):
                shortlist = fully_inside
            else:
                shortlist.sort(
                    key=lambda r: (
                        -len(set(r.get("numbers", [])) & core),
                        -float(r.get("score", 0.0)),
                        tuple(r.get("numbers", [])),
                    )
                )
        return shortlist, core_pool

    def _marginal(self, row: dict, seen_numbers: set[int], seen_pairs: set, seen_triples: set,
                  selected_rows: list[dict], selected_sigs: list[tuple],
                  precomputed: dict | None = None) -> tuple[float, dict]:
        feat = precomputed or self._row_features(row)
        nums = tuple(feat["numbers"])
        p = feat["pairs"]
        t = feat["triples"]
        new_numbers = len(feat["numbers"] - seen_numbers)
        new_pairs = len(p - seen_pairs)
        new_triples = len(t - seen_triples)
        number_value = 100.0 * new_numbers / self.cfg.pick
        pair_value = 100.0 * new_pairs / max(1, comb(self.cfg.pick, 2))
        triple_value = 100.0 * new_triples / max(1, comb(self.cfg.pick, 3))
        sig = feat["signature"]
        diversity = _structure_novelty(sig, selected_sigs)
        quality = feat["score"]
        overlap_pen = _overlap_penalty(nums, [x.get("numbers", []) for x in selected_rows], self.cfg.pick)
        if self.mode == "concentrated":
            # Concentration research deliberately tolerates repeated high-quality/core
            # numbers. It still penalizes near-duplicates, but much less aggressively.
            overlap_pen *= 0.25
        w = self.weights
        value = (
            w.quality * quality
            + w.pairs * pair_value
            + w.triples * triple_value
            + w.numbers * number_value
            + w.diversity * diversity
            - overlap_pen
        )
        details = {
            "quality": round(quality, 3),
            "new_numbers": new_numbers,
            "new_pairs": new_pairs,
            "new_triples": new_triples,
            "number_value": round(number_value, 3),
            "pair_value": round(pair_value, 3),
            "triple_value": round(triple_value, 3),
            "structure_novelty": round(diversity, 3),
            "overlap_penalty": round(overlap_pen, 3),
        }
        return value, details

    def optimize(self, rows: list[dict], top_n: int) -> list[dict]:
        top_n = max(1, int(top_n))
        prepared, core_pool = self._prepare(rows, top_n)
        if self.mode == "score_only":
            selected = [dict(r) for r in prepared[:top_n]]
            for i, r in enumerate(selected, 1):
                r["selection_order"] = i
                r["portfolio_value"] = round(float(r.get("score", 0.0)), 2)
                r["coverage_mode"] = "score_only"
                r["coverage_engine"] = COVERAGE_ENGINE_VERSION
            return selected

        remaining = [dict(r) for r in prepared]
        # Pairs/triples/signatures are invariant during the greedy search; computing
        # them once avoids rebuilding the same combinatorial sets every round.
        feature_cache = {id(row): self._row_features(row) for row in remaining}
        selected: list[dict] = []
        seen_numbers: set[int] = set()
        seen_pairs: set = set()
        seen_triples: set = set()
        selected_sigs: list[tuple] = []

        while remaining and len(selected) < top_n:
            best_index = 0
            best_value = -1e18
            best_details = None
            best_key = None
            # Cap each greedy scan for speed while keeping a broad high-quality shortlist.
            scan = min(len(remaining), max(800, top_n * 60))
            for i, row in enumerate(remaining[:scan]):
                value, details = self._marginal(
                    row, seen_numbers, seen_pairs, seen_triples, selected, selected_sigs,
                    precomputed=feature_cache.get(id(row)),
                )
                key = (value, float(row.get("score", 0.0)), tuple(-n for n in row.get("numbers", [])))
                if best_key is None or key > best_key:
                    best_index, best_value, best_details, best_key = i, value, details, key
            row = remaining.pop(best_index)
            row["selection_order"] = len(selected) + 1
            row["portfolio_value"] = round(best_value, 2)
            row["coverage_gain"] = best_details or {}
            row["coverage_mode"] = self.mode
            row["coverage_engine"] = COVERAGE_ENGINE_VERSION
            if core_pool is not None:
                row["coverage_core_pool"] = list(core_pool)
            selected.append(row)
            feat = feature_cache.get(id(row)) or self._row_features(row)
            seen_numbers.update(feat["numbers"])
            seen_pairs.update(feat["pairs"])
            seen_triples.update(feat["triples"])
            selected_sigs.append(feat["signature"])

        # A cheap deterministic single-pass local swap. It improves the final set rather than
        # endlessly regenerating combinations. Skip tiny candidate pools to keep backtests fast.
        if len(prepared) >= 700 and len(selected) >= 3:
            selected = self._local_swap(selected, prepared)

        # Display order remains Main Combination Score, preserving familiar Top-Pick semantics.
        selected.sort(key=lambda r: (-float(r.get("score", 0.0)), tuple(r.get("numbers", []))))
        return selected

    def _row_features(self, row: dict) -> dict:
        numbers = frozenset(map(int, row.get("numbers", [])))
        return {
            "numbers": numbers,
            "pairs": _pairs(numbers),
            "triples": _triples(numbers),
            "signature": _structure_signature(numbers, self.cfg.max_number),
            "score": float(row.get("score", 0.0)),
        }

    def _build_portfolio_state(self, rows: list[dict]) -> dict:
        """Build reusable counters for exact local-swap objective evaluation.

        V1.2.2 rebuilt all Number/Pair/Triple unions and pairwise overlaps for every
        trial replacement. V1.2.3 builds them once per accepted portfolio state so a
        candidate trial only evaluates the delta caused by the one replaced row.
        """
        features = [self._row_features(r) for r in rows]
        number_counts = Counter()
        pair_counts = Counter()
        triple_counts = Counter()
        signature_counts = Counter()
        score_sum = 0.0
        for f in features:
            number_counts.update(f["numbers"])
            pair_counts.update(f["pairs"])
            triple_counts.update(f["triples"])
            signature_counts[f["signature"]] += 1
            score_sum += f["score"]

        n = len(features)
        pair_overlaps: list[tuple[int, int, int]] = []
        overlap_sum_by_index = [0] * n
        for i in range(n):
            for j in range(i + 1, n):
                ov = len(features[i]["numbers"] & features[j]["numbers"])
                pair_overlaps.append((i, j, ov))
                overlap_sum_by_index[i] += ov
                overlap_sum_by_index[j] += ov
        max_overlap_without_index = []
        for idx in range(n):
            max_overlap_without_index.append(
                max((ov for i, j, ov in pair_overlaps if i != idx and j != idx), default=0)
            )

        return {
            "features": features,
            "number_counts": number_counts,
            "pair_counts": pair_counts,
            "triple_counts": triple_counts,
            "signature_counts": signature_counts,
            "score_sum": score_sum,
            "overlap_total": sum(ov for _, _, ov in pair_overlaps),
            "overlap_sum_by_index": overlap_sum_by_index,
            "max_overlap_without_index": max_overlap_without_index,
        }

    @staticmethod
    def _unique_count_after_swap(counter: Counter, old_values, new_values) -> int:
        current_unique = len(counter)
        lost = sum(1 for value in old_values if counter[value] == 1)
        gained = sum(
            1
            for value in new_values
            if counter[value] - (1 if value in old_values else 0) == 0
        )
        return current_unique - lost + gained

    def _objective_from_parts(
        self, *, n: int, unique_numbers: int, unique_pairs: int, unique_triples: int,
        unique_signatures: int, score_sum: float, overlap_total: int, max_overlap: int
    ) -> float:
        if n <= 0:
            return -1e18
        number_slots = min(self.cfg.max_number, n * self.cfg.pick)
        pair_slots = n * comb(self.cfg.pick, 2)
        triple_slots = n * comb(self.cfg.pick, 3)
        overlap_slots = comb(n, 2)

        # Match coverage_summary() rounding exactly so V1.2.3 is a performance
        # refactor, not an objective-function change.
        avg_score = round(score_sum / n, 2)
        pair_eff = round(100.0 * unique_pairs / max(1, pair_slots), 2)
        triple_eff = round(100.0 * unique_triples / max(1, triple_slots), 2)
        num_eff = round(100.0 * unique_numbers / max(1, number_slots), 2)
        struct = round(100.0 * unique_signatures / n, 2)
        avg_overlap = round(overlap_total / overlap_slots, 3) if overlap_slots else 0.0

        w = self.weights
        normal = 2 if self.cfg.pick <= 6 else 3
        overlap_pen = 7.5 * max(0, max_overlap - normal) + 1.2 * max(0.0, avg_overlap - 1.25)
        if self.mode == "concentrated":
            overlap_pen *= 0.25
        return (
            w.quality * avg_score
            + w.pairs * pair_eff
            + w.triples * triple_eff
            + w.numbers * num_eff
            + w.diversity * struct
            - overlap_pen
        )

    def _objective_from_state(self, state: dict) -> float:
        features = state["features"]
        return self._objective_from_parts(
            n=len(features),
            unique_numbers=len(state["number_counts"]),
            unique_pairs=len(state["pair_counts"]),
            unique_triples=len(state["triple_counts"]),
            unique_signatures=len(state["signature_counts"]),
            score_sum=state["score_sum"],
            overlap_total=state["overlap_total"],
            max_overlap=max(
                (len(features[i]["numbers"] & features[j]["numbers"])
                 for i in range(len(features)) for j in range(i + 1, len(features))),
                default=0,
            ),
        )

    def _swap_objective(self, state: dict, idx: int, candidate: dict) -> float:
        features = state["features"]
        old = features[idx]
        cand = self._row_features(candidate)
        n = len(features)

        unique_numbers = self._unique_count_after_swap(
            state["number_counts"], old["numbers"], cand["numbers"]
        )
        unique_pairs = self._unique_count_after_swap(
            state["pair_counts"], old["pairs"], cand["pairs"]
        )
        unique_triples = self._unique_count_after_swap(
            state["triple_counts"], old["triples"], cand["triples"]
        )
        old_sig = old["signature"]
        new_sig = cand["signature"]
        unique_signatures = len(state["signature_counts"])
        if old_sig != new_sig:
            if state["signature_counts"][old_sig] == 1:
                unique_signatures -= 1
            if state["signature_counts"][new_sig] == 0:
                unique_signatures += 1

        new_overlaps = [
            len(cand["numbers"] & f["numbers"])
            for j, f in enumerate(features)
            if j != idx
        ]
        overlap_total = (
            state["overlap_total"]
            - state["overlap_sum_by_index"][idx]
            + sum(new_overlaps)
        )
        max_overlap = max(
            state["max_overlap_without_index"][idx],
            max(new_overlaps, default=0),
        )
        return self._objective_from_parts(
            n=n,
            unique_numbers=unique_numbers,
            unique_pairs=unique_pairs,
            unique_triples=unique_triples,
            unique_signatures=unique_signatures,
            score_sum=state["score_sum"] - old["score"] + cand["score"],
            overlap_total=overlap_total,
            max_overlap=max_overlap,
        )

    def _portfolio_objective(self, rows: list[dict]) -> float:
        if not rows:
            return -1e18
        return self._objective_from_state(self._build_portfolio_state(rows))

    def _local_swap(self, selected: list[dict], prepared: list[dict]) -> list[dict]:
        chosen = {tuple(r.get("numbers", [])) for r in selected}
        alternatives = [r for r in prepared if tuple(r.get("numbers", [])) not in chosen][:180]
        current = [dict(r) for r in selected]
        state = self._build_portfolio_state(current)
        current_obj = self._objective_from_state(state)
        # Protect the highest-score seed from being swapped out. This keeps the official portfolio
        # anchored to the strongest single-combination prediction.
        seed_combo = max(current, key=lambda r: float(r.get("score", 0.0))).get("numbers", [])
        for idx in range(len(current)):
            if tuple(current[idx].get("numbers", [])) == tuple(seed_combo):
                continue
            best_obj = current_obj
            best = None
            current_keys = {tuple(r.get("numbers", [])) for r in current}
            old_key = tuple(current[idx].get("numbers", []))
            for cand in alternatives:
                ctuple = tuple(cand.get("numbers", []))
                if ctuple in current_keys and ctuple != old_key:
                    continue
                obj = self._swap_objective(state, idx, cand)
                if obj > best_obj + 1e-9:
                    best_obj, best = obj, cand
            if best is not None:
                old = current[idx]
                current[idx] = dict(best)
                current[idx]["selection_order"] = old.get("selection_order", idx + 1)
                current[idx]["portfolio_value"] = round(best_obj, 2)
                current[idx]["coverage_mode"] = self.mode
                current[idx]["coverage_engine"] = COVERAGE_ENGINE_VERSION
                current[idx]["coverage_gain"] = {
                    "local_swap": True,
                    "portfolio_objective": round(best_obj, 3),
                    "evaluation": "incremental_exact",
                }
                current_obj = best_obj
                alternatives = [
                    a for a in alternatives
                    if tuple(a.get("numbers", [])) != tuple(best.get("numbers", []))
                ]
                alternatives.append(old)
                # Rebuild only after an accepted swap. Candidate trials themselves are incremental.
                state = self._build_portfolio_state(current)
        return current
