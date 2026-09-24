from __future__ import annotations

import hashlib
import itertools
import math
import random
from array import array
from statistics import mean, median

try:
    import numpy as np
except Exception:  # exact Python fallback remains available
    np = None

from .config import (
    GAMES, PORTFOLIO_POLICY_WEIGHTS, PORTFOLIO_DATA_COLLECTION_N,
    PORTFOLIO_PROVISIONAL_N, PORTFOLIO_SCREENING_N, PORTFOLIO_CONFIRMATION_N,
)
from .evaluation import bootstrap_mean_ci, paired_sign_flip_test, benjamini_hochberg

POLICY_FEATURES = ("quality", "number_coverage", "diversity", "concentration", "rank_retention")


def _seed(label: str) -> int:
    return int.from_bytes(hashlib.sha256(str(label).encode("utf-8")).digest()[:8], "big") & 0x7FFFFFFF


def normalize_policy_weights(weights: dict | None = None) -> dict[str, float]:
    src = dict(PORTFOLIO_POLICY_WEIGHTS)
    src.update({k: float(v) for k, v in (weights or {}).items() if k in POLICY_FEATURES})
    src = {k: max(0.0, float(src.get(k, 0.0))) for k in POLICY_FEATURES}
    total = sum(src.values()) or 1.0
    return {k: src[k] / total for k in POLICY_FEATURES}


def portfolio_phase(n: int) -> dict:
    n = int(n or 0)
    if n < PORTFOLIO_DATA_COLLECTION_N:
        return {"phase": "DATA_COLLECTION", "confidence": "VERY LOW", "production_recommendation": False,
                "next_gate": PORTFOLIO_DATA_COLLECTION_N}
    if n < PORTFOLIO_PROVISIONAL_N:
        return {"phase": "EXPLORATORY", "confidence": "LOW", "production_recommendation": False,
                "next_gate": PORTFOLIO_PROVISIONAL_N}
    if n < PORTFOLIO_SCREENING_N:
        return {"phase": "PROVISIONAL", "confidence": "LOW-MEDIUM", "production_recommendation": True,
                "next_gate": PORTFOLIO_SCREENING_N}
    if n < PORTFOLIO_CONFIRMATION_N:
        return {"phase": "SCREENING", "confidence": "MEDIUM", "production_recommendation": True,
                "next_gate": PORTFOLIO_CONFIRMATION_N}
    return {"phase": "CONFIRMATION", "confidence": "EVIDENCE-BASED", "production_recommendation": True,
            "next_gate": None}


def _ticket_hit(game: str, ticket: dict, draw: dict) -> dict:
    actual = set(map(int, draw.get("numbers") or []))
    nums = set(map(int, ticket.get("numbers") or []))
    h = len(actual & nums)
    bonus = draw.get("bonus")
    bonus_hit = bonus is not None and int(bonus) in nums and int(bonus) not in actual
    return {"hits": h, "bonus_hit": bool(bonus_hit)}


def fixed_tier_payout_floor(game: str, ticket: dict, draw: dict) -> dict:
    """Conservative payout floor using only deterministic published fixed tiers.

    Pari-mutuel tiers and shared jackpots are explicitly unresolved until an official
    prize-breakdown amount is ingested. This avoids manufacturing ROI from guessed payouts.
    Free plays are valued at the base play price.
    """
    cfg = GAMES[game]
    r = _ticket_hit(game, ticket, draw)
    h, bh = r["hits"], r["bonus_hit"]
    payout = 0.0
    tier = "NO_FIXED_PRIZE"
    resolved = True
    if game == "649":
        if h == 3:
            payout, tier = 10.0, "3/6"
        elif h == 2 and bh:
            payout, tier = 5.0, "2/6+BONUS"
        elif h == 2:
            payout, tier = cfg.play_cost, "2/6 FREE PLAY"
        elif h >= 4:
            tier, resolved = ("6/6" if h == 6 else ("5/6+BONUS" if h == 5 and bh else f"{h}/6")), False
    else:
        if h == 4 and bh:
            tier, resolved = "4/7+BONUS", False
        elif h == 4:
            payout, tier = 20.0, "4/7"
        elif h == 3 and bh:
            payout, tier = 20.0, "3/7+BONUS"
        elif h == 3:
            payout, tier = cfg.play_cost, "3/7 FREE PLAY"
        elif h >= 5:
            tier, resolved = ("7/7" if h == 7 else (f"{h}/7+BONUS" if bh else f"{h}/7")), False
    return {**r, "payout_floor": float(payout), "tier": tier, "fully_resolved": bool(resolved)}


def _number_mask(nums):
    mask = 0
    for n in nums or []:
        mask |= 1 << (int(n) - 1)
    return mask


def _exact_frontier_python(num_masks, overlaps, core_mask, core_size, qualities, rankvals, corevals,
                           max_lines, cfg, weights):
    """Reference exact subset enumerator retained as a deterministic fallback/test oracle."""
    n = len(num_masks)
    best = {}
    size = 1 << n
    union_cache = array("Q", [0]) * size
    qsum_cache = array("d", [0.0]) * size
    rsum_cache = array("d", [0.0]) * size
    csum_cache = array("d", [0.0]) * size
    ovsum_cache = array("H", [0]) * size
    for mask in range(1, size):
        k = mask.bit_count()
        if k > max_lines:
            continue
        lsb = mask & -mask
        i = lsb.bit_length() - 1
        rest = mask ^ lsb
        union = union_cache[rest] | num_masks[i]
        qsum = qsum_cache[rest] + qualities[i]
        rsum = rsum_cache[rest] + rankvals[i]
        csum = csum_cache[rest] + corevals[i]
        ovsum = ovsum_cache[rest]
        rr = rest
        while rr:
            b = rr & -rr
            j = b.bit_length() - 1
            ovsum += overlaps[i][j]
            rr ^= b
        union_cache[mask] = union
        qsum_cache[mask] = qsum
        rsum_cache[mask] = rsum
        csum_cache[mask] = csum
        ovsum_cache[mask] = ovsum
        pair_count = k * (k - 1) / 2
        avg_ov = (ovsum / pair_count) if pair_count else 0.0
        core_density = csum / k
        core_coverage = (union & core_mask).bit_count() / max(1, core_size)
        f = {
            "quality": qsum / k,
            "number_coverage": union.bit_count() / cfg.max_number,
            "diversity": max(0.0, 1.0 - avg_ov / cfg.pick) if k >= 2 else 0.0,
            "diversity_applicable": k >= 2,
            "concentration": 0.65 * core_coverage + 0.35 * core_density,
            "rank_retention": rsum / k,
        }
        value = _fixed_k_selection_value(f, weights)
        prev = best.get(k)
        rank_guard = float(f["rank_retention"])
        if (prev is None or value > prev[0] + 1e-12
                or (abs(value - prev[0]) <= 1e-12 and rank_guard > prev[3] + 1e-12)
                or (abs(value - prev[0]) <= 1e-12 and abs(rank_guard - prev[3]) <= 1e-12
                    and (ovsum, mask) < (prev[2], prev[1]))):
            best[k] = (value, mask, ovsum, rank_guard)
    return best


def _bitcounts_u64(values):
    """Vectorized bit count compatible with NumPy versions lacking bitwise_count."""
    a = np.ascontiguousarray(values, dtype=np.uint64)
    bytes_view = a.view(np.uint8).reshape(-1, 8)
    lut = np.array([int(i).bit_count() for i in range(256)], dtype=np.uint8)
    return lut[bytes_view].sum(axis=1, dtype=np.uint16)


def _exact_frontier_numpy(num_masks, overlaps, core_mask, core_size, qualities, rankvals, corevals,
                          max_lines, cfg, weights):
    """Vectorized exact 2^N frontier; mathematically identical to the Python oracle."""
    if np is None:
        return None
    n = len(num_masks)
    size = 1 << n
    union = np.zeros(size, dtype=np.uint64)
    qsum = np.zeros(size, dtype=np.float64)
    rsum = np.zeros(size, dtype=np.float64)
    csum = np.zeros(size, dtype=np.float64)
    ovsum = np.zeros(size, dtype=np.uint16)
    kcount = np.zeros(size, dtype=np.uint8)

    # Subset doubling: target masks are exactly source masks plus the new highest bit.
    # This removes the ~1M Python-level subset loop while preserving exact enumeration.
    for i in range(n):
        block = 1 << i
        idx = np.arange(block, dtype=np.uint32)
        target = idx + block
        union[target] = union[idx] | np.uint64(num_masks[i])
        qsum[target] = qsum[idx] + float(qualities[i])
        rsum[target] = rsum[idx] + float(rankvals[i])
        csum[target] = csum[idx] + float(corevals[i])
        kcount[target] = kcount[idx] + 1
        if i:
            inc = np.zeros(block, dtype=np.uint16)
            for j in range(i):
                ov = int(overlaps[i][j])
                if ov:
                    inc += (((idx >> j) & 1).astype(np.uint16) * ov)
            ovsum[target] = ovsum[idx] + inc

    best = {}
    core_mask_u = np.uint64(core_mask)
    for k in range(1, max_lines + 1):
        idx = np.flatnonzero(kcount == k)
        if not len(idx):
            continue
        u = union[idx]
        union_count = _bitcounts_u64(u).astype(np.float64)
        core_count = _bitcounts_u64(u & core_mask_u).astype(np.float64)
        q = qsum[idx] / k
        rank_guard = rsum[idx] / k
        concentration = 0.65 * (core_count / max(1, core_size)) + 0.35 * (csum[idx] / k)
        pair_count = k * (k - 1) / 2.0
        avg_ov = (ovsum[idx].astype(np.float64) / pair_count) if pair_count else np.zeros(len(idx))
        diversity = np.maximum(0.0, 1.0 - avg_ov / cfg.pick) if k >= 2 else np.zeros(len(idx))
        value = (
            float(weights.get("quality", 0.0)) * q
            + float(weights.get("number_coverage", 0.0)) * (union_count / cfg.max_number)
            + float(weights.get("concentration", 0.0)) * concentration
        )
        if k >= 2:
            value = value + float(weights.get("diversity", 0.0)) * diversity
        rank_floor = 0.35
        penalty = np.maximum(0.0, (rank_floor - rank_guard) / rank_floor)
        value = value - float(weights.get("rank_retention", 0.0)) * penalty

        vmax = float(value.max())
        cand_pos = np.flatnonzero(np.abs(value - vmax) <= 1e-12)
        if len(cand_pos) > 1:
            g = rank_guard[cand_pos]
            gmax = float(g.max())
            cand_pos = cand_pos[np.abs(g - gmax) <= 1e-12]
        cand_masks = idx[cand_pos]
        if len(cand_masks) > 1:
            ovs = ovsum[cand_masks]
            min_ov = int(ovs.min())
            cand_masks = cand_masks[ovs == min_ov]
        mask = int(cand_masks.min())
        # Recompute scalar value with the same public helper for byte-for-byte policy semantics.
        pair_count_s = k * (k - 1) / 2
        avg_ov_s = (int(ovsum[mask]) / pair_count_s) if pair_count_s else 0.0
        f = {
            "quality": float(qsum[mask]) / k,
            "number_coverage": int(union[mask]).bit_count() / cfg.max_number,
            "diversity": max(0.0, 1.0 - avg_ov_s / cfg.pick) if k >= 2 else 0.0,
            "diversity_applicable": k >= 2,
            "concentration": 0.65 * ((int(union[mask]) & int(core_mask)).bit_count() / max(1, core_size)) + 0.35 * (float(csum[mask]) / k),
            "rank_retention": float(rsum[mask]) / k,
        }
        best[k] = (_fixed_k_selection_value(f, weights), mask, int(ovsum[mask]), float(f["rank_retention"]))
    return best


def _pairwise_overlap(rows: list[dict]) -> list[list[int]]:
    sets = [set(map(int, r.get("numbers") or [])) for r in rows]
    n = len(rows)
    return [[0 if i == j else len(sets[i] & sets[j]) for j in range(n)] for i in range(n)]


def _core_pool(rows: list[dict], cfg) -> set[int]:
    """Pre-draw model-consensus core derived only from the frozen rows.

    This is not a probability claim. It measures which numbers the model itself
    repeatedly retained across high-ranked/high-score tickets so Portfolio AI can
    distinguish useful concentration from accidental duplication.
    """
    if not rows:
        return set()
    scores = [float(r.get("score", 0.0)) for r in rows]
    lo, hi = min(scores), max(scores)
    denom = hi - lo or 1.0
    n = len(rows)
    mass = {}
    for i, r in enumerate(rows):
        q = 0.15 + 0.85 * max(0.0, min(1.0, (float(r.get("score", 0.0)) - lo) / denom))
        rank = int(r.get("rank", i + 1) or i + 1)
        rv = 0.10 + 0.90 * (1.0 if n <= 1 else max(0.0, min(1.0, (n-rank)/(n-1))))
        w = 0.65 * q + 0.35 * rv
        for num in r.get("numbers") or []:
            num = int(num)
            mass[num] = mass.get(num, 0.0) + w
    core_size = min(cfg.max_number, max(cfg.pick, cfg.pick * 2))
    return {num for num, _ in sorted(mass.items(), key=lambda kv: (-kv[1], kv[0]))[:core_size]}


def _subset_features(rows: list[dict], indices: list[int], cfg, overlap=None, core_pool=None) -> dict:
    chosen = [rows[i] for i in indices]
    k = len(chosen)
    if not k:
        return {x: 0.0 for x in POLICY_FEATURES} | {
            "unique_numbers": 0, "avg_score": 0.0, "avg_overlap": 0.0, "max_overlap": 0,
            "overlap_balance": 0.0, "core_pool": [], "diversity_applicable": False,
        }
    scores = [float(r.get("score", 0.0)) for r in rows]
    lo, hi = min(scores), max(scores)
    denom = hi - lo or 1.0
    all_q = [0.15 + 0.85 * max(0.0, min(1.0, (float(r.get("score", 0.0)) - lo) / denom)) for r in rows]
    q = [all_q[i] for i in indices]
    number_union = set()
    for i in indices:
        number_union.update(map(int, rows[i].get("numbers") or []))
    ovs = []
    if k >= 2:
        ovm = overlap or _pairwise_overlap(rows)
        for a, b in itertools.combinations(indices, 2):
            ovs.append(int(ovm[a][b]))
    avg_ov = mean(ovs) if ovs else 0.0
    max_ov = max(ovs) if ovs else 0
    diversity_applicable = k >= 2
    diversity = max(0.0, 1.0 - avg_ov / cfg.pick) if diversity_applicable else 0.0
    target_overlap = 1.5 if cfg.pick == 6 else 2.0
    overlap_balance = max(0.0, 1.0 - abs(avg_ov - target_overlap) / cfg.pick)
    n = len(rows)
    rank_values = []
    for i in indices:
        rank = int(rows[i].get("rank", i + 1) or i + 1)
        rank_values.append(0.10 + 0.90 * (1.0 if n <= 1 else max(0.0, min(1.0, (n - rank) / (n - 1)))))

    core = set(core_pool or _core_pool(rows, cfg))
    core_shares = []
    for i in indices:
        nums = set(map(int, rows[i].get("numbers") or []))
        core_shares.append(len(nums & core) / max(1, cfg.pick))
    core_density = mean(core_shares) if core_shares else 0.0
    core_coverage = len(number_union & core) / max(1, len(core))
    core_concentration = 0.65 * core_coverage + 0.35 * core_density

    # V1.5.0 used cumulative quality/rank mass divided by the full Top-20 mass.
    # That made utility nearly monotonic in line count and pushed the structural Auto
    # choice toward ~14/20 lines even without evidence. V1.5.1 uses per-ticket
    # averages, while concentration measures retention of the model-consensus core.
    return {
        "quality": mean(q),
        "number_coverage": len(number_union) / cfg.max_number,
        "diversity": diversity,
        "diversity_applicable": diversity_applicable,
        "concentration": core_concentration,
        "rank_retention": mean(rank_values) if rank_values else 0.0,
        "unique_numbers": len(number_union),
        "avg_score": mean(float(r.get("score", 0.0)) for r in chosen),
        "avg_overlap": avg_ov,
        "max_overlap": max_ov,
        "overlap_balance": overlap_balance,
        "core_density": core_density,
        "core_coverage": core_coverage,
        "core_pool": sorted(core),
    }


def _fixed_k_selection_value(features: dict, weights: dict) -> float:
    """Structural value used only to choose the best subset at a *fixed* k.

    V1.5.2 rewarded a one-line portfolio twice for being small: diversity was
    hard-coded to 1.0 and rank-retention was a direct positive term.  That made
    cross-budget efficiency collapse toward a single ticket.  V1.5.3 treats
    diversity as not applicable for k=1 and turns rank-retention into a lower
    quality guardrail: good ranks above the floor are not rewarded merely for
    buying fewer lines.
    """
    value = 0.0
    for key in ("quality", "number_coverage", "concentration"):
        value += float(weights.get(key, 0.0)) * float(features.get(key, 0.0))
    if bool(features.get("diversity_applicable", True)):
        value += float(weights.get("diversity", 0.0)) * float(features.get("diversity", 0.0))

    # Guardrail only: rank retention below this level is penalized, while strong
    # rank retention does not create a bonus that systematically favours k=1.
    rank_floor = 0.35
    rank_ret = float(features.get("rank_retention", 0.0))
    if rank_ret < rank_floor:
        value -= float(weights.get("rank_retention", 0.0)) * ((rank_floor - rank_ret) / rank_floor)
    return value


def _deployment_utility(features: dict, full_unique_numbers: int) -> float:
    """Budget-size utility for the diminishing-return curve.

    This is deliberately separate from the fixed-k selection score.  It answers
    "how much portfolio structure has been deployed?" rather than "which k-line
    subset is best?".  Rank retention is excluded from this cross-k utility so a
    smaller portfolio cannot win merely because it contains only top-ranked rows.
    """
    full_unique_numbers = max(1, int(full_unique_numbers or 0))
    coverage = min(1.0, float(features.get("unique_numbers", 0)) / full_unique_numbers)
    concentration = max(0.0, min(1.0, float(features.get("concentration", 0.0))))
    diversity = (max(0.0, min(1.0, float(features.get("diversity", 0.0))))
                 if bool(features.get("diversity_applicable", True)) else 0.0)
    # Coverage is the main deployment dimension; concentration keeps strong model
    # cores together; diversity is secondary and cannot score for a one-line set.
    return 0.55 * coverage + 0.30 * concentration + 0.15 * diversity


def _normalized_knee_scores(ks: list[int], values: dict[int, float]) -> dict[int, float]:
    """Classic chord/Kneedle-style scores with both axes normalized to [0, 1].

    V1.5.3 divided x and y only by their maxima.  That is not equivalent to
    min-max normalization when the first portfolio already has substantial utility;
    the positive y-intercept can systematically favour very small k.  Subtracting
    both endpoints makes the score measure curvature above the straight line joining
    the first and last affordable deployment levels.
    """
    ks = sorted(int(k) for k in ks)
    if not ks:
        return {}
    if len(ks) == 1:
        return {ks[0]: 0.0}
    k0, k1 = ks[0], ks[-1]
    v0 = float(values.get(k0, 0.0))
    v1 = float(values.get(k1, v0))
    dx = float(k1 - k0) or 1.0
    dy = v1 - v0
    # If the envelope has no measurable gain, extra lines add no structural value;
    # returning all-zero scores lets the deterministic tie-break choose the smallest k.
    if abs(dy) <= 1e-12:
        return {k: 0.0 for k in ks}
    out = {}
    for k in ks:
        x = (k - k0) / dx
        y = (float(values.get(k, v0)) - v0) / dy
        out[k] = y - x
    return out


def _annotate_diminishing_return_curve(frontier: dict[str, dict], play_cost: float) -> tuple[int, dict]:
    """Annotate exact-k portfolios and return the structural knee.

    The frontier consists of independently optimized exact-k subsets.  Therefore the
    reported marginal value is a *frontier spend-level difference*, not a literal
    instruction to keep the previous subset and add one ticket.  A monotone envelope
    is used because a budget ceiling may always leave money unspent.
    """
    if not frontier:
        return 0, {}
    ks = sorted(int(k) for k in frontier)
    full_unique = max(int((frontier[str(k)].get("features") or {}).get("unique_numbers", 0)) for k in ks)

    prev_env = 0.0
    env_by_k = {}
    for k in ks:
        item = frontier[str(k)]
        feats = item.get("features") or {}
        raw = _deployment_utility(feats, full_unique)
        env = max(prev_env, raw)
        marginal_gain = max(0.0, env - prev_env)
        marginal_per_dollar = marginal_gain / max(float(play_cost), 1e-12)
        item["deployment_utility"] = round(raw, 8)
        item["deployment_utility_envelope"] = round(env, 8)
        item["frontier_marginal_gain"] = round(marginal_gain, 8)
        item["marginal_deployment_gain"] = round(marginal_gain, 8)  # compatibility alias
        item["frontier_marginal_value_per_dollar"] = round(marginal_per_dollar, 8)
        item["marginal_value_per_dollar"] = round(marginal_per_dollar, 8)  # compatibility alias
        env_by_k[k] = env
        prev_env = env

    knee_scores = _normalized_knee_scores(ks, env_by_k)
    best_k = ks[0]
    best_score = knee_scores[best_k]
    for k in ks:
        knee_score = float(knee_scores[k])
        frontier[str(k)]["knee_score"] = round(knee_score, 8)
        if knee_score > best_score + 1e-12 or (abs(knee_score - best_score) <= 1e-12 and k < best_k):
            best_k, best_score = k, knee_score
    return best_k, {
        "method": "endpoint-normalized diminishing-return knee on monotone deployment utility",
        "knee_score": round(best_score, 8),
        "full_unique_numbers": full_unique,
        "knee_normalization": "MIN_MAX_ENDPOINTS",
        "marginal_semantics": "FRONTIER_SPEND_LEVEL_DIFFERENCE_NOT_NESTED_ADD_ONE",
    }

def _sweet_spot_under_cap(frontier: dict, max_lines: int) -> dict:
    """Return the global structural knee when affordable, otherwise a local knee.

    Once a budget can afford the global sweet spot, raising the ceiling does not
    change that recommendation.  When the cap is tighter, the same endpoint-normalized
    knee calculation is repeated over the affordable exact-k frontier only.
    """
    table = frontier.get("frontier") or {}
    global_auto = frontier.get("auto") or {}
    global_k = int(global_auto.get("lines") or 0)
    if global_k and global_k <= max_lines and str(global_k) in table:
        out = dict(table[str(global_k)])
        out["budget_knee_score"] = global_auto.get("knee_score")
        out["method"] = "global endpoint-normalized diminishing-return knee (affordable under cap)"
        return out

    ks = [k for k in range(1, max_lines + 1) if str(k) in table]
    if not ks:
        return {}
    env = {k: float(table[str(k)].get("deployment_utility_envelope", 0.0)) for k in ks}
    scores = _normalized_knee_scores(ks, env)
    best = ks[0]
    best_score = scores[best]
    for k in ks:
        score = float(scores[k])
        if score > best_score + 1e-12 or (abs(score - best_score) <= 1e-12 and k < best):
            best, best_score = k, score
    out = dict(table[str(best)])
    out["budget_knee_score"] = round(best_score, 8)
    out["method"] = "local endpoint-normalized diminishing-return knee because global knee exceeds budget cap"
    return out

def _dedupe_draw_records(records: list[dict]) -> list[dict]:
    """One effective portfolio-learning record per draw.

    Version upgrades can legitimately freeze BUD1.0 and BUD1.1 for the same future
    draw without mutating the old ledger entry. Statistical learning must still count
    that draw once, so the newest record wins for analysis.
    """
    by_draw = {}
    undated = []
    for r in records or []:
        if not isinstance(r, dict):
            continue
        d = str(r.get("draw_date") or (r.get("judgment") or {}).get("draw_date") or (r.get("decision") or {}).get("target_draw_date") or "")
        if d:
            current = by_draw.get(d)
            if current is None or int(r.get("id") or 0) >= int(current.get("id") or 0):
                by_draw[d] = r
        else:
            undated.append(r)
    return [by_draw[d] for d in sorted(by_draw)] + undated


def _score_percentile(rows: list[dict], idx: int) -> float:
    """Pre-draw score percentile, 0..1, where higher means stronger score rank."""
    if not rows:
        return 0.0
    score = float(rows[idx].get("score", 0.0))
    vals = [float(r.get("score", 0.0)) for r in rows]
    below = sum(1 for v in vals if v < score)
    equal = sum(1 for v in vals if v == score)
    return (below + 0.5 * equal) / max(1, len(vals))


def _line_role(rows: list[dict], selected_indices: list[int], idx: int, cfg, core_pool: set[int] | None = None) -> dict:
    """Assign an explainable PRE-DRAW role to one selected frozen line.

    Roles are descriptive labels only; they never use the draw result and never
    alter Combination Score.  They make post-draw line-level learning auditable.
    """
    core = set(core_pool or _core_pool(rows, cfg))
    nums = set(map(int, rows[idx].get("numbers") or []))
    peers = [set(map(int, rows[j].get("numbers") or [])) for j in selected_indices if j != idx]
    peer_union = set().union(*peers) if peers else set()
    unique_add = nums - peer_union
    avg_peer_overlap = mean(len(nums & p) for p in peers) if peers else 0.0
    core_share = len(nums & core) / max(1, cfg.pick)
    score_pct = _score_percentile(rows, idx)

    # Deterministic, interpretable labels.  CORE rewards model-consensus retention;
    # COVERAGE rewards marginal new numbers; DIVERSITY rewards low overlap.
    if not peers:
        role = "CORE" if (core_share >= 0.60 or score_pct >= 0.75) else "BALANCED"
    elif core_share >= 0.60 or (score_pct >= 0.75 and core_share >= 0.45):
        role = "CORE"
    elif len(unique_add) >= max(2, cfg.pick // 2):
        role = "COVERAGE"
    elif avg_peer_overlap <= 1.0:
        role = "DIVERSITY"
    else:
        role = "BALANCED"
    return {
        "role": role,
        "score_percentile": round(score_pct, 6),
        "core_share": round(core_share, 6),
        "marginal_unique_numbers": len(unique_add),
        "avg_overlap_to_selected": round(float(avg_peer_overlap), 6),
    }


def _choice_line_roles(rows: list[dict], selected_indices: list[int], cfg, core_pool: set[int] | None = None) -> list[dict]:
    out = []
    for idx in selected_indices:
        r = rows[idx]
        info = _line_role(rows, selected_indices, idx, cfg, core_pool=core_pool)
        out.append({
            "rank": int(r.get("rank", idx + 1)),
            "numbers": [int(n) for n in (r.get("numbers") or [])],
            "score": round(float(r.get("score", 0.0)), 6),
            **info,
        })
    return out


def _selection_outcome_key(outcome: dict) -> tuple:
    """Non-monetary post-draw comparison key used only for regret labels.

    It deliberately avoids unresolved jackpot/pari-mutuel money.  Bonus is used only
    as a same-main-hit tier tie-break (for example 5/6+Bonus outranks 5/6); it never
    lets an unresolved payout floor masquerade as exact money.
    """
    return (
        int(outcome.get("best_hit", 0)),
        int(bool(outcome.get("best_hit_bonus", False))),
        int(outcome.get("coverage", 0)),
        float(outcome.get("winner_concentration_efficiency", 0.0)),
        float(outcome.get("avg_hit", 0.0)),
        int(outcome.get("bonus_hit_count", 0)),
    )


def _postdraw_selection_oracle_frontier(rows: list[dict], draw: dict) -> dict[str, dict]:
    """Exact post-draw subset oracle for diagnostic/regret labels only.

    V1.5.3 chose the top-k tickets independently by ``payout_known``.  That had two
    problems: unresolved pari-mutuel tiers have only a lower-bound payout, and the
    independently best tickets are not necessarily the best *subset* for coverage or
    concentration.  This helper searches all frozen Top-20 subsets exactly and uses
    the same non-monetary outcome ordering as the replacement diagnostics.

    Nothing from this oracle is available before the draw and it never counts as
    forward performance or directly alters Production.
    """
    rows = list(rows or [])[:20]
    n = len(rows)
    if not n:
        return {}
    actual = set(map(int, draw.get("numbers") or []))
    bonus = draw.get("bonus")
    match_masks = []
    hits = []
    bonus_hits = []
    scores = []
    ranks = []
    for i, row in enumerate(rows):
        nums = set(map(int, row.get("numbers") or []))
        matched = nums & actual
        match_masks.append(_number_mask(matched))
        hits.append(len(matched))
        bonus_hits.append(bool(bonus is not None and int(bonus) in nums and int(bonus) not in actual))
        scores.append(float(row.get("score", 0.0)))
        ranks.append(int(row.get("rank", i + 1) or i + 1))

    size = 1 << n
    union_cache = array("Q", [0]) * size
    hit_sum_cache = array("H", [0]) * size
    max_hit_cache = array("B", [0]) * size
    best_bonus_cache = array("B", [0]) * size
    bonus_count_cache = array("B", [0]) * size
    score_sum_cache = array("d", [0.0]) * size
    rank_sum_cache = array("H", [0]) * size
    best: dict[int, tuple[tuple, float, int, int]] = {}

    for mask in range(1, size):
        lsb = mask & -mask
        i = lsb.bit_length() - 1
        rest = mask ^ lsb
        k = mask.bit_count()
        union = union_cache[rest] | match_masks[i]
        hit_sum = hit_sum_cache[rest] + hits[i]
        rest_max = max_hit_cache[rest]
        h = hits[i]
        if h > rest_max:
            max_hit = h
            best_bonus = 1 if bonus_hits[i] else 0
        elif h < rest_max:
            max_hit = rest_max
            best_bonus = best_bonus_cache[rest]
        else:
            max_hit = rest_max
            best_bonus = 1 if (best_bonus_cache[rest] or bonus_hits[i]) else 0
        bonus_count = bonus_count_cache[rest] + (1 if bonus_hits[i] else 0)
        score_sum = score_sum_cache[rest] + scores[i]
        rank_sum = rank_sum_cache[rest] + ranks[i]

        union_cache[mask] = union
        hit_sum_cache[mask] = hit_sum
        max_hit_cache[mask] = max_hit
        best_bonus_cache[mask] = best_bonus
        bonus_count_cache[mask] = bonus_count
        score_sum_cache[mask] = score_sum
        rank_sum_cache[mask] = rank_sum

        coverage = union.bit_count()
        wce = (max_hit / coverage) if coverage else 0.0
        avg_hit = hit_sum / k
        key = (int(max_hit), int(best_bonus), int(coverage), float(wce), float(avg_hit), int(bonus_count))
        prev = best.get(k)
        # Pre-draw score/rank are deterministic tie-breakers only after identical
        # post-draw outcome keys; they do not create the oracle label itself.
        if (prev is None or key > prev[0]
                or (key == prev[0] and score_sum > prev[1] + 1e-12)
                or (key == prev[0] and abs(score_sum - prev[1]) <= 1e-12 and rank_sum < prev[2])
                or (key == prev[0] and abs(score_sum - prev[1]) <= 1e-12 and rank_sum == prev[2] and mask < prev[3])):
            best[k] = (key, score_sum, rank_sum, mask)

    out = {}
    for k, (key, score_sum, rank_sum, mask) in best.items():
        idx = [i for i in range(n) if (mask >> i) & 1]
        out[str(k)] = {
            "lines": k,
            "selected_ranks": [ranks[i] for i in idx],
            "oracle_outcome_key": list(key),
            "oracle_tiebreak_score_sum": round(score_sum, 6),
            "oracle_method": "EXACT_NON_MONETARY_SUBSET_ORACLE",
        }
    return out


def _line_level_review(game: str, rows: list[dict], selected_ranks: list[int], draw: dict,
                       frozen_role_rows: list[dict] | None = None) -> dict:
    """Post-draw review of each chosen line plus one-at-a-time replacement regret.

    Each line is evaluated separately, but statistical sample size remains DRAW count.
    Replacement alternatives are post-draw counterfactual labels only and never count
    as forward predictions or production performance.
    """
    cfg = GAMES[game]
    rows = list(rows or [])
    by_rank = {int(r.get("rank", i + 1)): (i, r) for i, r in enumerate(rows)}
    ranks = [int(r) for r in (selected_ranks or []) if int(r) in by_rank]
    indices = [by_rank[r][0] for r in ranks]
    role_by_rank = {int(x.get("rank")): dict(x) for x in (frozen_role_rows or []) if isinstance(x, dict) and x.get("rank") is not None}
    if not role_by_rank:
        role_by_rank = {int(x["rank"]): x for x in _choice_line_roles(rows, indices, cfg)}

    actual = set(map(int, draw.get("numbers") or []))
    selected_sets = {r: set(map(int, by_rank[r][1].get("numbers") or [])) for r in ranks}
    reviews = []
    for rank in ranks:
        idx, ticket = by_rank[rank]
        rr = resolved_ticket_payout(game, ticket, draw)
        others_union = set().union(*(selected_sets[r] & actual for r in ranks if r != rank)) if len(ranks) > 1 else set()
        matched = sorted(selected_sets[rank] & actual)
        unique_matched = sorted((selected_sets[rank] & actual) - others_union)
        role = dict(role_by_rank.get(rank) or {})
        reviews.append({
            "rank": rank,
            "numbers": [int(n) for n in (ticket.get("numbers") or [])],
            "score": round(float(ticket.get("score", 0.0)), 6),
            "role": role.get("role", "BALANCED"),
            "score_percentile": role.get("score_percentile"),
            "core_share": role.get("core_share"),
            "marginal_unique_numbers_pre_draw": role.get("marginal_unique_numbers"),
            "avg_overlap_to_selected_pre_draw": role.get("avg_overlap_to_selected"),
            "hits": int(rr.get("hits", 0)),
            "matched_numbers": matched,
            "unique_winning_numbers_contributed": unique_matched,
            "unique_winner_contribution_count": len(unique_matched),
            "bonus_hit": bool(rr.get("bonus_hit")),
            "tier": rr.get("tier"),
            "payout_known": round(float(rr.get("payout_known", 0.0)), 2),
            "payout_status": "EXACT" if rr.get("fully_resolved") else "LOWER_BOUND",
        })

    # One-at-a-time replacement analysis: hold k-1 selected lines fixed and search
    # every unselected frozen line for the best post-draw selection outcome.
    unselected = [int(r.get("rank", i + 1)) for i, r in enumerate(rows) if int(r.get("rank", i + 1)) not in set(ranks)]
    base_tickets = [by_rank[r][1] for r in ranks]
    base_out = _portfolio_outcome(game, base_tickets, draw)
    repl = []
    for rank in ranks:
        kept = [r for r in ranks if r != rank]
        best_alt = None
        best_out = base_out
        for alt in unselected:
            candidate_ranks = kept + [alt]
            tickets = [by_rank[r][1] for r in candidate_ranks]
            out = _portfolio_outcome(game, tickets, draw)
            key = _selection_outcome_key(out)
            if best_alt is None or key > _selection_outcome_key(best_out) or (
                key == _selection_outcome_key(best_out) and alt < int(best_alt)
            ):
                best_alt = alt
                best_out = out
        improved = best_alt is not None and _selection_outcome_key(best_out) > _selection_outcome_key(base_out)
        repl.append({
            "selected_rank": rank,
            "best_replacement_rank": int(best_alt) if improved else None,
            "replace_would_improve": bool(improved),
            "best_hit_delta": int(best_out.get("best_hit", 0)) - int(base_out.get("best_hit", 0)) if improved else 0,
            "coverage_delta": int(best_out.get("coverage", 0)) - int(base_out.get("coverage", 0)) if improved else 0,
            "wce_delta": round(float(best_out.get("winner_concentration_efficiency", 0.0)) - float(base_out.get("winner_concentration_efficiency", 0.0)), 6) if improved else 0.0,
            "avg_hit_delta": round(float(best_out.get("avg_hit", 0.0)) - float(base_out.get("avg_hit", 0.0)), 6) if improved else 0.0,
        })

    return {
        "per_line": reviews,
        "replacement_review": repl,
        "replaceable_count": sum(1 for x in repl if x.get("replace_would_improve")),
        "note": "Per-line and replacement labels are post-draw diagnostics; effective statistical sample size remains one draw.",
    }


def line_selection_learning(records: list[dict]) -> dict:
    """Draw-level learning summary for selected-line roles and rank bands.

    Multiple selected lines from one draw are averaged within that draw before any
    cross-draw statistic is computed, preventing pseudo-replication.
    """
    records = _dedupe_draw_records(records)
    role_draws: dict[str, list[dict]] = {}
    band_draws: dict[str, list[dict]] = {}
    draw_count = 0
    replacement_rates = []
    for rec in records:
        jud = rec.get("judgment") if isinstance(rec, dict) else None
        if not isinstance(jud, dict):
            continue
        auto = jud.get("production_auto") or {}
        lr = auto.get("line_learning") or {}
        per = lr.get("per_line") or []
        if not per:
            continue
        draw_count += 1
        replacement_rates.append(float(lr.get("replaceable_count", 0)) / max(1, len(per)))
        grouped = {}
        bands = {}
        for x in per:
            role = str(x.get("role") or "BALANCED")
            grouped.setdefault(role, []).append(x)
            rank = int(x.get("rank") or 0)
            band = "1-5" if rank <= 5 else ("6-10" if rank <= 10 else ("11-15" if rank <= 15 else "16-20"))
            bands.setdefault(band, []).append(x)
        for role, xs in grouped.items():
            role_draws.setdefault(role, []).append({
                "mean_hits": mean(float(x.get("hits", 0)) for x in xs),
                "mean_unique_winner_contribution": mean(float(x.get("unique_winner_contribution_count", 0)) for x in xs),
                "prize_rate": mean(1.0 if float(x.get("payout_known", 0.0)) > 0 or x.get("payout_status") == "LOWER_BOUND" else 0.0 for x in xs),
            })
        for band, xs in bands.items():
            band_draws.setdefault(band, []).append({
                "mean_hits": mean(float(x.get("hits", 0)) for x in xs),
                "mean_unique_winner_contribution": mean(float(x.get("unique_winner_contribution_count", 0)) for x in xs),
            })

    def summarize(group):
        out = {}
        for key, vals in group.items():
            out[key] = {
                "draws": len(vals),
                "mean_hits_per_selected_line": round(mean(v["mean_hits"] for v in vals), 6),
                "mean_unique_winner_contribution": round(mean(v["mean_unique_winner_contribution"] for v in vals), 6),
            }
            if vals and "prize_rate" in vals[0]:
                out[key]["mean_draw_level_prize_rate"] = round(mean(v["prize_rate"] for v in vals), 6)
        return out

    return {
        "n": draw_count,
        "by_role": summarize(role_draws),
        "by_rank_band": summarize(band_draws),
        "mean_replaceable_fraction": round(mean(replacement_rates), 6) if replacement_rates else None,
        "production_impact": 0.0,
        **portfolio_phase(draw_count),
        "note": "Line learning is aggregated at draw level. Individual lines are diagnostic units, not independent statistical samples.",
    }


class PortfolioOptimizer:
    """Exact subset optimizer over a frozen Top-20.

    The search never invents/recombines numbers. It selects a subset of already-frozen
    Production tickets. With 20 tickets there are 1,048,575 non-empty subsets, small
    enough for an exact research search using bit masks and cheap structural metrics.
    """

    def __init__(self, game: str, policy_weights: dict | None = None):
        self.game = game
        self.cfg = GAMES[game]
        self.weights = normalize_policy_weights(policy_weights)

    def frontier(self, rows: list[dict], max_lines: int | None = None) -> dict:
        rows = [dict(r) for r in (rows or [])][:20]
        n = len(rows)
        if not n:
            return {"schema": "PORTFOLIO_FRONTIER1.3", "game": self.game, "lines": 0,
                    "policy_weights": self.weights, "frontier": {}, "auto": {"lines": 0, "cost": 0.0}}
        max_lines = min(n, max(1, int(max_lines or n)))
        num_masks = [_number_mask(r.get("numbers") or []) for r in rows]
        overlaps = _pairwise_overlap(rows)
        core = _core_pool(rows, self.cfg)
        scores = [float(r.get("score", 0.0)) for r in rows]
        lo, hi = min(scores), max(scores)
        denom = hi - lo or 1.0
        qualities = [0.15 + 0.85 * max(0.0, min(1.0, (s - lo) / denom)) for s in scores]
        rankvals = []
        corevals = []
        for i, r in enumerate(rows):
            rank = int(r.get("rank", i + 1) or i + 1)
            rankvals.append(0.10 + 0.90 * (1.0 if n <= 1 else max(0.0, min(1.0, (n - rank) / (n - 1)))))
            nums = set(map(int, r.get("numbers") or []))
            corevals.append(len(nums & core) / max(1, self.cfg.pick))

        # Exact best subset for every affordable line count. NumPy removes the
        # Python-level 2^20 loop; the reference enumerator remains as a fallback and
        # regression oracle. ``core_mask`` is deliberately computed once, not per subset.
        core_mask = _number_mask(core)
        best = _exact_frontier_numpy(
            num_masks, overlaps, core_mask, len(core), qualities, rankvals, corevals,
            max_lines, self.cfg, self.weights,
        )
        search_engine = "NUMPY_EXACT_SUBSET_V1"
        if best is None:
            best = _exact_frontier_python(
                num_masks, overlaps, core_mask, len(core), qualities, rankvals, corevals,
                max_lines, self.cfg, self.weights,
            )
            search_engine = "PYTHON_EXACT_SUBSET_FALLBACK"

        frontier = {}
        for k in sorted(best):
            value, mask, ovsum, rank_guard = best[k]
            indices = [i for i in range(n) if (mask >> i) & 1]
            feats = _subset_features(rows, indices, self.cfg, overlaps, core_pool=core)
            cost = round(k * float(self.cfg.play_cost), 2)
            item = {
                "lines": k,
                "cost": cost,
                "selected_ranks": [int(rows[i].get("rank", i + 1)) for i in indices],
                "selected_numbers": [list(map(int, rows[i].get("numbers") or [])) for i in indices],
                "policy_value": round(value, 8),
                "fixed_k_selection_value": round(value, 8),
                "rank_retention_mode": "GUARDRAIL_TIEBREAK",
                "features": {kk: (v if isinstance(v, bool) else round(float(v), 8) if isinstance(v, (int, float)) else v) for kk, v in feats.items()},
                "line_roles": _choice_line_roles(rows, indices, self.cfg, core_pool=core),
            }
            frontier[str(k)] = item

        # V1.5.3 separates two questions that V1.5.2 mixed together:
        # (1) which subset is best at a fixed k, and (2) how many lines are worth
        # deploying before marginal structure flattens.  The latter is now a
        # diminishing-return knee, not an arbitrary per-line penalty.
        auto_k, knee_meta = _annotate_diminishing_return_curve(frontier, float(self.cfg.play_cost))
        auto = dict(frontier[str(auto_k)])
        auto.update(knee_meta)
        auto["structural_efficiency"] = auto.get("deployment_utility_envelope", auto.get("deployment_utility", 0.0))
        return {
            "schema": "PORTFOLIO_FRONTIER1.3",
            "game": self.game,
            "lines": n,
            "play_cost": float(self.cfg.play_cost),
            "policy_weights": {k: round(v, 8) for k, v in self.weights.items()},
            "core_pool": sorted(core),
            "frontier": frontier,
            "auto": auto,
            "search_space": (1 << n) - 1,
            "search_engine": search_engine,
            "cross_k_method": "DIMINISHING_RETURN_KNEE",
            "rank_retention_policy": "GUARDRAIL_NOT_BONUS",
            "single_line_diversity_policy": "NOT_APPLICABLE_ZERO_CONTRIBUTION",
            "note": "Subsets are selected from frozen Top-20 only; no numbers are regenerated or recombined. Exact-k selection and budget-size selection use separate objectives.",
        }

    def for_budget(self, frontier: dict, budget: float, allow_unspent: bool = True) -> dict:
        budget = max(0.0, float(budget))
        play_cost = float(frontier.get("play_cost") or self.cfg.play_cost)
        max_lines = min(int(frontier.get("lines") or 0), int(budget // play_cost) if play_cost > 0 else 0)
        if max_lines <= 0:
            return {"budget": round(budget, 2), "lines": 0, "cost": 0.0, "unused": round(budget, 2),
                    "selected_ranks": [], "status": "NO_AFFORDABLE_PLAY"}
        choices = [frontier["frontier"][str(k)] for k in range(1, max_lines + 1) if str(k) in frontier.get("frontier", {})]
        if not choices:
            return {"budget": round(budget, 2), "lines": 0, "cost": 0.0, "unused": round(budget, 2),
                    "selected_ranks": [], "status": "NO_PORTFOLIO"}
        if allow_unspent:
            chosen = _sweet_spot_under_cap(frontier, max_lines) or choices[0]
            status = "STRUCTURAL_DIMINISHING_RETURN_SWEET_SPOT"
        else:
            chosen = choices[-1]
            status = "MAX_DEPLOYMENT_UNDER_CAP"
        out = dict(chosen)
        out.update({
            "budget": round(budget, 2),
            "unused": round(budget - float(chosen["cost"]), 2),
            "status": status,
        })
        return out


def resolved_ticket_payout(game: str, ticket: dict, draw: dict) -> dict:
    """Return the best known payout without inventing pari-mutuel values.

    ``draw['prize_breakdown']`` may contain exact per-winning-selection payouts keyed
    by tier (for example ``{'4/6': 100.9}``). If it is absent, unresolved pool/jackpot
    tiers remain unresolved and only the deterministic fixed-tier floor is counted.
    """
    base = fixed_tier_payout_floor(game, ticket, draw)
    out = dict(base)
    out["payout_known"] = float(base["payout_floor"])
    out["payout_source"] = "FIXED_TIER" if base["fully_resolved"] else "UNRESOLVED"
    breakdown = draw.get("prize_breakdown") or {}
    if not base["fully_resolved"]:
        raw = breakdown.get(base["tier"])
        try:
            if raw is not None:
                out["payout_known"] = float(raw)
                out["fully_resolved"] = True
                out["payout_source"] = "OFFICIAL_PRIZE_BREAKDOWN"
        except (TypeError, ValueError):
            pass
    return out


def _portfolio_outcome(game: str, tickets: list[dict], draw: dict) -> dict:
    results = [resolved_ticket_payout(game, t, draw) for t in tickets]
    hits = [int(r["hits"]) for r in results]
    actual = set(map(int, draw.get("numbers") or []))
    covered = set()
    for t in tickets:
        covered |= actual & set(map(int, t.get("numbers") or []))
    payout_floor = sum(float(r["payout_floor"]) for r in results)
    payout_known = sum(float(r.get("payout_known", r["payout_floor"])) for r in results)
    unresolved = sum(1 for r in results if not r.get("fully_resolved"))
    best_hit = max(hits) if hits else 0
    coverage = len(covered)
    wce = (best_hit / coverage) if coverage > 0 else 0.0
    best_hit_bonus = any(bool(r.get("bonus_hit")) and int(r.get("hits", 0)) == best_hit for r in results) if results else False
    bonus_hit_count = sum(1 for r in results if bool(r.get("bonus_hit")))
    return {
        "results": results,
        "hits": hits,
        "best_hit": best_hit,
        "best_hit_bonus": bool(best_hit_bonus),
        "bonus_hit_count": int(bonus_hit_count),
        "avg_hit": mean(hits) if hits else 0.0,
        "median_hit": median(hits) if hits else 0.0,
        "coverage": coverage,
        "winner_concentration_efficiency": wce,
        "payout_floor": payout_floor,
        "payout_known": payout_known,
        "unresolved": unresolved,
        "payout_status": "EXACT" if unresolved == 0 else "LOWER_BOUND",
    }


def _package_payout_for_ranks(game: str, ranks: list[int], draw: dict) -> dict:
    """Return *actual physical-purchase* payout only when explicitly supplied.

    A model-directed line is not the whole retail product:
    - LOTTO MAX: each $6 purchase contains the chosen line plus three terminal
      Quick Picks (and any applicable secondary draw entries).
    - LOTTO 6/49: each $3 play also carries a system-assigned Gold Ball selection.

    Therefore Main-number results alone can never prove exact purchase ROI.  If a
    caller later imports terminal/receipt results it may provide
    ``draw['package_payout_by_rank']`` mapping each frozen model rank to the total
    payout of that physical purchase.  Until every selected rank is present, package
    ROI remains NOT_AVAILABLE rather than silently treating companion outcomes as $0.
    """
    ranks = [int(r) for r in (ranks or [])]
    if not ranks:
        return {"status": "EXACT", "payout": 0.0, "covered_ranks": 0, "required_ranks": 0}
    raw = draw.get("package_payout_by_rank") or {}
    values = []
    for rank in ranks:
        v = raw.get(rank, raw.get(str(rank))) if isinstance(raw, dict) else None
        try:
            if v is None:
                raise ValueError
            values.append(float(v))
        except (TypeError, ValueError):
            return {
                "status": "NOT_AVAILABLE", "payout": None,
                "covered_ranks": len(values), "required_ranks": len(ranks),
            }
    return {"status": "EXACT", "payout": sum(values), "covered_ranks": len(values), "required_ranks": len(ranks)}


def evaluate_portfolio_choice(game: str, rows: list[dict], choice: dict, draw: dict,
                              seed_label: str = "portfolio-random", oracle_choice: dict | None = None) -> dict:
    by_rank = {int(r.get("rank", i + 1)): r for i, r in enumerate(rows or [])}
    ranks = [int(x) for x in choice.get("selected_ranks") or []]
    selected = [by_rank[r] for r in ranks if r in by_rank]
    outcome = _portfolio_outcome(game, selected, draw)
    hits = outcome["hits"]
    cost = len(selected) * float(GAMES[game].play_cost)
    payout_floor = outcome["payout_floor"]
    payout_known = outcome["payout_known"]
    unresolved = outcome["unresolved"]
    roi_floor = ((payout_floor - cost) / cost) if cost > 0 else 0.0
    roi_known = ((payout_known - cost) / cost) if cost > 0 else 0.0
    package = _package_payout_for_ranks(game, ranks, draw)
    package_payout = package.get("payout")
    package_roi = ((float(package_payout) - cost) / cost) if cost > 0 and package_payout is not None else None

    # Same-budget random control from the same frozen Top-20. Small subset spaces are
    # enumerated exactly; larger spaces use deterministic Monte Carlo.
    k = len(selected)
    all_rows = list(rows or [])
    random_avg_hits = []
    random_best_hits = []
    random_coverages = []
    random_wce = []
    random_payouts_floor = []
    random_payouts_known = []
    random_status_exact = []
    random_method = None
    random_subsets = 0
    if k and len(all_rows) >= k:
        total_combos = math.comb(len(all_rows), k)
        if total_combos <= 2000:
            subsets = itertools.combinations(range(len(all_rows)), k)
            random_method = "EXACT_ENUMERATION"
        else:
            rng = random.Random(_seed(f"{seed_label}|{game}|{draw.get('draw_date')}|{k}"))
            target = 500
            seen = set()
            sampled = []
            attempts = 0
            while len(sampled) < target and attempts < target * 20:
                attempts += 1
                idx = tuple(sorted(rng.sample(range(len(all_rows)), k)))
                if idx in seen:
                    continue
                seen.add(idx)
                sampled.append(idx)
            subsets = sampled
            random_method = "DETERMINISTIC_MONTE_CARLO"
        for idx in subsets:
            tickets = [all_rows[i] for i in idx]
            ro = _portfolio_outcome(game, tickets, draw)
            random_avg_hits.append(float(ro["avg_hit"]))
            random_best_hits.append(float(ro["best_hit"]))
            random_coverages.append(float(ro["coverage"]))
            random_wce.append(float(ro["winner_concentration_efficiency"]))
            random_payouts_floor.append(float(ro["payout_floor"]))
            random_payouts_known.append(float(ro["payout_known"]))
            random_status_exact.append(ro["payout_status"] == "EXACT")
            random_subsets += 1

    # Exact post-draw same-size *selection* oracle for regret labels only.  It uses
    # non-monetary match/coverage ordering so unresolved prize tiers are never treated
    # as zero-dollar truth, and it optimizes the subset jointly instead of ranking
    # tickets independently.
    if oracle_choice is None and k:
        oracle_choice = (_postdraw_selection_oracle_frontier(all_rows, draw) or {}).get(str(k))
    oracle_ranks = [int(x) for x in ((oracle_choice or {}).get("selected_ranks") or [])]
    oracle_tickets = [by_rank[r] for r in oracle_ranks if r in by_rank]
    oracle_outcome = _portfolio_outcome(game, oracle_tickets, draw) if oracle_tickets else {
        "payout_floor":0.0,"payout_known":0.0,"avg_hit":0.0,"best_hit":0,
        "best_hit_bonus":False,"bonus_hit_count":0,"coverage":0,
        "winner_concentration_efficiency":0.0,"unresolved":0,"payout_status":"EXACT"
    }
    oracle_method = (oracle_choice or {}).get("oracle_method") or "NONE"
    line_learning = _line_level_review(
        game, all_rows, ranks, draw, frozen_role_rows=choice.get("line_roles") or []
    ) if ranks else {"per_line": [], "replacement_review": [], "replaceable_count": 0}

    return {
        "lines": k,
        "cost": round(cost, 2),
        "selected_ranks": ranks,
        "best_hit": int(outcome["best_hit"]),
        "avg_hit": round(float(outcome["avg_hit"]), 6),
        "median_hit": round(float(outcome["median_hit"]), 6),
        "winning_number_coverage": int(outcome["coverage"]),
        "winner_concentration_efficiency": round(float(outcome["winner_concentration_efficiency"]), 6),
        # Backward-compatible aliases below refer ONLY to the model-directed Main
        # selections.  They are not the exact ROI of the retail purchase package.
        "payout_floor": round(payout_floor, 2),
        "payout_known": round(payout_known, 2),
        "payout_status": outcome["payout_status"],
        "roi_floor": round(roi_floor, 6),
        "roi_known": round(roi_known, 6) if outcome["payout_status"] == "EXACT" else None,
        "model_directed_payout_floor": round(payout_floor, 2),
        "model_directed_payout_known": round(payout_known, 2),
        "model_directed_payout_status": outcome["payout_status"],
        "model_directed_roi_floor": round(roi_floor, 6),
        "model_directed_roi_known": round(roi_known, 6) if outcome["payout_status"] == "EXACT" else None,
        "package_payout_status": package.get("status"),
        "package_payout_known": round(float(package_payout), 2) if package_payout is not None else None,
        "package_roi_known": round(float(package_roi), 6) if package_roi is not None else None,
        "package_payout_covered_ranks": int(package.get("covered_ranks") or 0),
        "package_payout_required_ranks": int(package.get("required_ranks") or 0),
        "any_prize": bool(payout_floor > 0.0 or unresolved > 0 or (package_payout or 0) > 0),
        "unresolved_parimutuel_or_jackpot_tickets": unresolved,
        "random_same_budget_avg_hit": round(mean(random_avg_hits), 6) if random_avg_hits else None,
        "random_same_budget_best_hit": round(mean(random_best_hits), 6) if random_best_hits else None,
        "random_same_budget_coverage": round(mean(random_coverages), 6) if random_coverages else None,
        "random_same_budget_wce": round(mean(random_wce), 6) if random_wce else None,
        "random_same_budget_payout_floor": round(mean(random_payouts_floor), 6) if random_payouts_floor else None,
        "random_same_budget_payout_known": round(mean(random_payouts_known), 6) if random_payouts_known and all(random_status_exact) else None,
        "random_control_method": random_method,
        "random_control_subsets": random_subsets,
        "oracle_same_budget_ranks": oracle_ranks,
        "oracle_same_budget_method": oracle_method,
        "oracle_same_budget_best_hit_bonus": bool(oracle_outcome.get("best_hit_bonus", False)),
        "oracle_same_budget_payout_floor": round(float(oracle_outcome["payout_floor"]), 2),
        "oracle_same_budget_payout_known": round(float(oracle_outcome["payout_known"]), 2),
        "oracle_same_budget_avg_hit": round(float(oracle_outcome["avg_hit"]), 6),
        "oracle_same_budget_best_hit": int(oracle_outcome["best_hit"]),
        "oracle_same_budget_coverage": int(oracle_outcome["coverage"]),
        "oracle_same_budget_wce": round(float(oracle_outcome["winner_concentration_efficiency"]), 6),
        "payout_regret_floor": round(max(0.0, float(oracle_outcome["payout_floor"]) - payout_floor), 2),
        "avg_hit_regret": round(max(0.0, float(oracle_outcome["avg_hit"]) - float(outcome["avg_hit"])), 6),
        "best_hit_regret": max(0, int(oracle_outcome["best_hit"]) - int(outcome["best_hit"])),
        "coverage_regret": max(0, int(oracle_outcome["coverage"]) - int(outcome["coverage"])),
        "line_learning": line_learning,
        "note": (
            "roi_floor/roi_known describe the model-directed Main selections only. Exact retail-package ROI "
            "requires package_payout_by_rank because LOTTO MAX companion Quick Picks and LOTTO 6/49 Gold Ball "
            "outcomes belong to the paid purchase but are not controlled by the number model. The oracle is an "
            "exact non-monetary same-size subset oracle used only for post-draw regret labels; unresolved prize "
            "money never defines the oracle."
        ),
    }


def judge_frontier(game: str, rows: list[dict], decision: dict, draw: dict) -> dict:
    result = {"schema": "PORTFOLIO_JUDGMENT1.2", "game": game, "draw_date": str(draw.get("draw_date")), "by_lines": {}, "shadow_by_lines": {}}
    prod_frontier = (decision.get("production_frontier") or {}).get("frontier", {})
    shadow_frontier = (decision.get("shadow_frontier") or {}).get("frontier", {})
    # One exact post-draw oracle search is shared by all Production/Shadow k values.
    oracle_frontier = _postdraw_selection_oracle_frontier(rows, draw)
    for k, choice in sorted(prod_frontier.items(), key=lambda kv: int(kv[0])):
        result["by_lines"][str(k)] = evaluate_portfolio_choice(
            game, rows, choice, draw, seed_label="prod", oracle_choice=oracle_frontier.get(str(k)))
    for k, choice in sorted(shadow_frontier.items(), key=lambda kv: int(kv[0])):
        result["shadow_by_lines"][str(k)] = evaluate_portfolio_choice(
            game, rows, choice, draw, seed_label="shadow", oracle_choice=oracle_frontier.get(str(k)))
    auto = (decision.get("production_frontier") or {}).get("auto") or {}
    ak = str(int(auto.get("lines") or 0)) if auto else "0"
    result["production_auto"] = evaluate_portfolio_choice(
        game, rows, auto, draw, seed_label="prod-auto", oracle_choice=oracle_frontier.get(ak)) if auto else None
    sauto = (decision.get("shadow_frontier") or {}).get("auto") or {}
    sk = str(int(sauto.get("lines") or 0)) if sauto else "0"
    result["shadow_auto"] = evaluate_portfolio_choice(
        game, rows, sauto, draw, seed_label="shadow-auto", oracle_choice=oracle_frontier.get(sk)) if sauto else None
    result["oracle_method"] = "EXACT_NON_MONETARY_SUBSET_ORACLE"
    return result


def learn_shadow_policy(records: list[dict], base_weights: dict | None = None) -> dict:
    """Conservative draw-level shadow learning from regret labels.

    Only draws that actually contain a frozen choice, an oracle label and frozen rows
    contribute to the effective sample count. V1.5.0 reported all stored records as n,
    which could overstate confidence when legacy/incomplete records were skipped.
    """
    base = normalize_policy_weights(base_weights)
    usable = [r for r in _dedupe_draw_records(records) if isinstance(r.get("judgment"), dict) and isinstance(r.get("decision"), dict)]
    signals = {k: [] for k in POLICY_FEATURES}
    contributing = 0
    for r in usable:
        dec = r.get("decision") or {}
        jud = r.get("judgment") or {}
        auto = (dec.get("production_frontier") or {}).get("auto") or {}
        auto_eval = jud.get("production_auto") or {}
        k = int(auto.get("lines") or 0)
        if not k:
            continue
        oracle_ranks = set(map(int, auto_eval.get("oracle_same_budget_ranks") or []))
        rows = dec.get("frozen_rows") or []
        if not rows or not oracle_ranks:
            continue
        game = r.get("game") or dec.get("game")
        if game not in GAMES:
            continue
        ov = _pairwise_overlap(rows)
        core = _core_pool(rows, GAMES[game])
        selected_set = set(map(int, auto.get("selected_ranks") or []))
        selected_idx = [i for i, rr in enumerate(rows) if int(rr.get("rank", i + 1)) in selected_set]
        oracle_idx = [i for i, rr in enumerate(rows) if int(rr.get("rank", i + 1)) in oracle_ranks]
        if not selected_idx or not oracle_idx:
            continue
        sf = _subset_features(rows, selected_idx, GAMES[game], ov, core_pool=core)
        of = _subset_features(rows, oracle_idx, GAMES[game], ov, core_pool=core)
        regret = (
            float(auto_eval.get("avg_hit_regret") or 0.0)
            + 0.5 * float(auto_eval.get("best_hit_regret") or 0.0)
            + 0.25 * float(auto_eval.get("coverage_regret") or 0.0)
            + min(1.0, float(auto_eval.get("payout_regret_floor") or 0.0) / 20.0)
        )
        scale = min(1.0, regret / 3.0)
        for f in POLICY_FEATURES:
            signals[f].append((float(of.get(f, 0.0)) - float(sf.get(f, 0.0))) * scale)
        contributing += 1

    n = contributing
    if not n:
        return {"n": 0, "stored_records": len(usable), "weights": base, **portfolio_phase(0),
                "signal": {k: 0.0 for k in POLICY_FEATURES}, "production_impact": 0.0}
    mean_signal = {k: (mean(v) if v else 0.0) for k, v in signals.items()}
    confidence = min(1.0, n / float(PORTFOLIO_SCREENING_N))
    raw = {}
    for k in POLICY_FEATURES:
        raw[k] = max(0.03, base[k] * math.exp(0.35 * confidence * mean_signal[k]))
    new = normalize_policy_weights(raw)
    return {
        "n": n,
        "stored_records": len(usable),
        "weights": new,
        "base_weights": base,
        "signal": {k: round(v, 8) for k, v in mean_signal.items()},
        **portfolio_phase(n),
        "production_impact": 0.0,
        "note": "Shadow policy learns from one valid regret signal per draw; incomplete legacy rows do not inflate n.",
    }


def portfolio_validation_summary(records: list[dict]) -> dict:
    """Same-draw, same-budget Production-vs-Shadow validation.

    V1.5.0 independently truncated Production and Shadow lists, which could misalign
    draws if a legacy record lacked one side. It also compared each policy's own Auto
    line count, which is not a same-budget test. V1.5.1 pairs inside each decision and
    evaluates Shadow at the Production Auto line count.
    """
    pairs = []
    for r in _dedupe_draw_records(records):
        jud = r.get("judgment") if isinstance(r, dict) else None
        dec = r.get("decision") if isinstance(r, dict) else None
        if not isinstance(jud, dict) or not isinstance(dec, dict):
            continue
        prod_auto = jud.get("production_auto") or {}
        k = int(prod_auto.get("lines") or 0)
        if not k:
            continue
        p = (jud.get("by_lines") or {}).get(str(k))
        s = (jud.get("shadow_by_lines") or {}).get(str(k))
        if not isinstance(p, dict) or not isinstance(s, dict):
            continue
        pairs.append((p, s, str(r.get("draw_date") or jud.get("draw_date") or "")))
    n = len(pairs)
    if not n:
        return {"n": 0, **portfolio_phase(0)}
    hit_diffs = [float(s.get("avg_hit", 0.0)) - float(p.get("avg_hit", 0.0)) for p, s, _ in pairs]
    best_diffs = [float(s.get("best_hit", 0.0)) - float(p.get("best_hit", 0.0)) for p, s, _ in pairs]
    wce_diffs = [float(s.get("winner_concentration_efficiency", 0.0)) - float(p.get("winner_concentration_efficiency", 0.0)) for p, s, _ in pairs]
    rnd_edges = [
        float(p.get("best_hit", 0.0)) - float(p.get("random_same_budget_best_hit", 0.0))
        for p, _, _ in pairs if p.get("random_same_budget_best_hit") is not None
    ]
    roi_floor = [float(p.get("model_directed_roi_floor", p.get("roi_floor", 0.0))) for p, _, _ in pairs]
    exact_roi = [float(p.get("package_roi_known")) for p, _, _ in pairs if p.get("package_roi_known") is not None]
    perm = paired_sign_flip_test(hit_diffs, seed_label="portfolio-shadow-vs-prod-same-budget")
    ci = bootstrap_mean_ci(hit_diffs, seed_label="portfolio-shadow-vs-prod-same-budget")
    phase = portfolio_phase(n)
    return {
        "n": n,
        **phase,
        "comparison": "same draw + same line count (Production Auto k)",
        "production_avg_hit": round(mean(float(p.get("avg_hit", 0.0)) for p, _, _ in pairs), 6),
        "shadow_avg_hit": round(mean(float(s.get("avg_hit", 0.0)) for _, s, _ in pairs), 6),
        "shadow_minus_production_avg_hit": round(mean(hit_diffs), 6),
        "shadow_minus_production_best_hit": round(mean(best_diffs), 6),
        "shadow_minus_production_wce": round(mean(wce_diffs), 6),
        "shadow_edge_ci95": ci,
        "shadow_edge_p_two_sided": perm.get("p_two_sided"),
        "production_vs_random_best_hit_edge": round(mean(rnd_edges), 6) if rnd_edges else None,
        "production_mean_model_directed_roi_floor": round(mean(roi_floor), 6) if roi_floor else None,
        "production_exact_package_roi_n": len(exact_roi),
        "production_mean_exact_package_roi": round(mean(exact_roi), 6) if exact_roi else None,
        # Legacy display aliases retained for callers written against BUD1.0/1.1.
        "production_mean_roi_floor": round(mean(roi_floor), 6) if roi_floor else None,
        "production_exact_roi_n": len(exact_roi),
        "production_mean_exact_roi": round(mean(exact_roi), 6) if exact_roi else None,
        "statistically_supported": bool(n >= PORTFOLIO_SCREENING_N and mean(hit_diffs) > 0 and (perm.get("p_two_sided") or 1.0) < 0.05),
        "note": "Effective sample size is paired draw count; same-budget comparisons never align different dates or different k.",
    }



def budget_frontier_learning(records: list[dict], game: str) -> dict:
    """Learn budget/line-count efficiency from forward-frozen draws.

    V1.5.4 makes the line-count comparison *paired by draw*.  Different k values
    cannot be ranked from different historical windows, and evidence grade is based
    on the number of draws that actually contain the same-budget Random comparator
    used by the selection test.  Sparse legacy rows remain visible through ``raw_n``
    but cannot inflate statistical confidence.
    """
    cfg = GAMES[game]
    usable = [r for r in _dedupe_draw_records(records) if isinstance(r.get("judgment"), dict)]

    def event_for(rec: dict, k: int) -> dict | None:
        ev = ((rec.get("judgment") or {}).get("by_lines") or {}).get(str(k))
        if isinstance(ev, dict) and int(ev.get("lines") or 0) == k:
            return ev
        return None

    def has_random_comparator(ev: dict | None) -> bool:
        if not isinstance(ev, dict):
            return False
        return ev.get("random_same_budget_best_hit") is not None or ev.get("random_same_budget_avg_hit") is not None

    raw_n_by_k = {k: sum(1 for rec in usable if event_for(rec, k) is not None) for k in range(1, 21)}
    comparator_n_by_k = {
        k: sum(1 for rec in usable if has_random_comparator(event_for(rec, k))) for k in range(1, 21)
    }
    present_ks = [k for k in range(1, 21) if raw_n_by_k[k] > 0]
    if not present_ks:
        return {
            "game": game, "n": 0, "stored_draws": len(usable), "comparison_cohort_n": 0,
            "by_lines": {}, "research_best_lines": None, "research_best_budget": None,
            "selection_evidence_grade": "D", "selection_supported": False,
            "evidence_note": "No forward-frozen budget outcomes yet.", **portfolio_phase(0),
        }

    max_comp_n = max(comparator_n_by_k.values()) if comparator_n_by_k else 0
    threshold = max(1, min(max_comp_n, PORTFOLIO_PROVISIONAL_N)) if max_comp_n else 1
    candidate_ks = [k for k in present_ks if comparator_n_by_k[k] >= threshold]

    # Every candidate k must be evaluated on the exact same draws, with the Random
    # comparator present on every one of those draws.  This prevents a k with an
    # easier/later historical window from winning merely because the cohorts differ.
    comparison_records = [
        rec for rec in usable
        if candidate_ks and all(has_random_comparator(event_for(rec, k)) for k in candidate_ks)
    ]
    comparison_n = len(comparison_records)

    def summarize(k: int, vals: list[dict], raw_n: int) -> dict:
        roi_floor = [float(v.get("roi_floor", 0.0)) for v in vals]
        exact_roi = [float(v.get("package_roi_known")) for v in vals if v.get("package_roi_known") is not None]
        avg_hit_edges = [
            float(v.get("avg_hit", 0.0)) - float(v.get("random_same_budget_avg_hit", 0.0))
            for v in vals if v.get("random_same_budget_avg_hit") is not None
        ]
        best_hit_edges = []
        edge_metric = "BEST_HIT"
        for v in vals:
            if v.get("random_same_budget_best_hit") is not None:
                best_hit_edges.append(float(v.get("best_hit", 0.0)) - float(v.get("random_same_budget_best_hit", 0.0)))
            elif v.get("random_same_budget_avg_hit") is not None:
                edge_metric = "AVG_HIT_LEGACY"
                best_hit_edges.append(float(v.get("avg_hit", 0.0)) - float(v.get("random_same_budget_avg_hit", 0.0)))
        coverage_edges = [
            float(v.get("winning_number_coverage", 0.0)) - float(v.get("random_same_budget_coverage", 0.0))
            for v in vals if v.get("random_same_budget_coverage") is not None
        ]
        wce_edges = [
            float(v.get("winner_concentration_efficiency", 0.0)) - float(v.get("random_same_budget_wce", 0.0))
            for v in vals if v.get("random_same_budget_wce") is not None
        ]
        payout_floor_edges = [
            float(v.get("payout_floor", 0.0)) - float(v.get("random_same_budget_payout_floor", 0.0))
            for v in vals if v.get("random_same_budget_payout_floor") is not None
        ]
        best_test = paired_sign_flip_test(best_hit_edges, seed_label=f"budget-best-edge-{game}-{k}") if best_hit_edges else {}
        return {
            "lines": k,
            "n": len(vals),
            "raw_n": int(raw_n),
            "edge_n": len(best_hit_edges),
            "cost_per_draw": round(k * float(cfg.play_cost), 2),
            "mean_roi_floor": round(mean(roi_floor), 6) if roi_floor else None,
            "median_roi_floor": round(median(roi_floor), 6) if roi_floor else None,
            "roi_floor_ci95": bootstrap_mean_ci(roi_floor, seed_label=f"budget-roi-floor-{game}-{k}") if roi_floor else None,
            "exact_roi_n": len(exact_roi),
            "exact_roi_complete": bool(vals) and len(exact_roi) == len(vals),
            "mean_exact_roi": round(mean(exact_roi), 6) if vals and len(exact_roi) == len(vals) else None,
            "mean_payout_floor": round(mean(float(v.get("payout_floor", 0.0)) for v in vals), 6) if vals else None,
            "any_prize_rate": round(mean(1.0 if v.get("any_prize") else 0.0 for v in vals), 6) if vals else None,
            "mean_best_hit": round(mean(float(v.get("best_hit", 0.0)) for v in vals), 6) if vals else None,
            "mean_avg_hit": round(mean(float(v.get("avg_hit", 0.0)) for v in vals), 6) if vals else None,
            "mean_winning_number_coverage": round(mean(float(v.get("winning_number_coverage", 0.0)) for v in vals), 6) if vals else None,
            "mean_wce": round(mean(float(v.get("winner_concentration_efficiency", 0.0)) for v in vals), 6) if vals else None,
            "mean_avg_hit_edge_vs_random": round(mean(avg_hit_edges), 6) if avg_hit_edges else None,
            "mean_best_hit_edge_vs_random": round(mean(best_hit_edges), 6) if best_hit_edges else None,
            "selection_edge_metric": edge_metric if best_hit_edges else None,
            "best_hit_edge_ci95": bootstrap_mean_ci(best_hit_edges, seed_label=f"budget-best-edge-{game}-{k}") if best_hit_edges else None,
            "best_hit_edge_p_two_sided": best_test.get("p_two_sided") if best_hit_edges else None,
            "mean_coverage_edge_vs_random": round(mean(coverage_edges), 6) if coverage_edges else None,
            "mean_wce_edge_vs_random": round(mean(wce_edges), 6) if wce_edges else None,
            "mean_payout_floor_edge_vs_random": round(mean(payout_floor_edges), 6) if payout_floor_edges else None,
            "unresolved_prize_draws": sum(1 for v in vals if int(v.get("unresolved_parimutuel_or_jackpot_tickets") or 0) > 0),
        }

    by_k: dict[str, dict] = {}
    raw_p = {}
    # Candidate line counts use the common comparison cohort.  Sparse/non-candidate
    # line counts are summarized from their own history for diagnostics only.
    for k in present_ks:
        if k in candidate_ks and comparison_records:
            vals = [event_for(rec, k) for rec in comparison_records]
            vals = [v for v in vals if v is not None]
        else:
            vals = [event_for(rec, k) for rec in usable]
            vals = [v for v in vals if v is not None]
        item = summarize(k, vals, raw_n_by_k[k])
        item["comparison_cohort"] = bool(k in candidate_ks and comparison_records)
        by_k[str(k)] = item
        if item["comparison_cohort"]:
            raw_p[str(k)] = item.get("best_hit_edge_p_two_sided")

    qvals = benjamini_hochberg(raw_p)
    for k, item in by_k.items():
        item["best_hit_edge_fdr_q"] = qvals.get(k) if item.get("comparison_cohort") else None

    if not candidate_ks or not comparison_records:
        return {
            "game": game,
            "n": 0,
            "stored_draws": len(usable),
            "comparison_cohort_n": 0,
            "common_n_across_line_counts": 0,
            "raw_max_n": max(raw_n_by_k.values()),
            "candidate_line_counts": candidate_ks,
            "by_lines": by_k,
            "research_best_lines": None,
            "research_best_budget": None,
            "research_best_roi_floor": None,
            "research_best_exact_roi": None,
            "budget_selection_objective": "NO_PAIRED_COMPARISON_COHORT",
            "monetary_comparable": False,
            "selection_evidence_grade": "D",
            "selection_supported": False,
            "auto_spend_research_ceiling": 0.0,
            "evidence_note": "Line counts do not yet share a common forward-draw cohort with same-budget Random controls; no budget ranking is allowed.",
            **portfolio_phase(0),
            "note": "Sparse legacy rows are diagnostic only and cannot inflate budget-selection evidence.",
        }

    eligible = [by_k[str(k)] for k in candidate_ks]
    monetary_comparable = bool(eligible) and all(bool(x.get("exact_roi_complete")) for x in eligible)
    if monetary_comparable:
        best = max(eligible, key=lambda x: (
            float(x.get("mean_exact_roi") if x.get("mean_exact_roi") is not None else -999.0),
            float(x.get("mean_best_hit_edge_vs_random") if x.get("mean_best_hit_edge_vs_random") is not None else -999.0),
            float(x.get("mean_wce_edge_vs_random") if x.get("mean_wce_edge_vs_random") is not None else -999.0),
            -float(x.get("cost_per_draw", 0.0)),
        ))
        objective = "EXACT_ROI"
    else:
        best = max(eligible, key=lambda x: (
            float(x.get("mean_best_hit_edge_vs_random") if x.get("mean_best_hit_edge_vs_random") is not None else -999.0),
            float(x.get("mean_wce_edge_vs_random") if x.get("mean_wce_edge_vs_random") is not None else -999.0),
            float(x.get("mean_coverage_edge_vs_random") if x.get("mean_coverage_edge_vs_random") is not None else -999.0),
            float(x.get("mean_avg_hit_edge_vs_random") if x.get("mean_avg_hit_edge_vs_random") is not None else -999.0),
            -float(x.get("cost_per_draw", 0.0)),
        ))
        objective = "SELECTION_EFFICIENCY_UNTIL_EXACT_PAYOUTS"

    # Confidence is tied to the actual comparator-bearing sample of the selected k,
    # not the largest sample available somewhere else in the table.
    evidence_n = int(best.get("edge_n") or 0)
    edge = best.get("mean_best_hit_edge_vs_random")
    qv = best.get("best_hit_edge_fdr_q")
    ci = best.get("best_hit_edge_ci95") or {}
    grade = "D"
    note = "Too few paired forward-frozen draws for a budget-efficiency claim."
    if evidence_n >= PORTFOLIO_CONFIRMATION_N:
        if edge is not None and edge > 0 and qv is not None and qv <= 0.01 and float(ci.get("low", -1e9)) >= 0:
            grade = "A"
            note = "Confirmed same-budget Best-Match selection evidence on a paired draw cohort after BH-FDR; profitability still requires exact payout data."
        elif edge is not None and edge > 0 and qv is not None and qv <= 0.05:
            grade = "B"
            note = "Positive same-budget selection evidence on a paired draw cohort after multiple-testing control; confirmation conditions are incomplete."
        else:
            grade = "C"
            note = "Large paired sample, but the learned budget choice has not established a robust same-budget edge."
    elif evidence_n >= PORTFOLIO_SCREENING_N:
        if edge is not None and edge > 0 and qv is not None and qv <= 0.05:
            grade = "B"
            note = "Screening evidence supports the selector versus same-budget random on the paired cohort after BH-FDR; keep it provisional."
        else:
            grade = "C"
            note = "Screening sample reached on the paired cohort, but FDR-adjusted support is not established."
    elif evidence_n >= PORTFOLIO_PROVISIONAL_N:
        grade = "C"
        note = "Provisional paired-cohort research candidate only; not an evidence-supported auto-spend decision."

    phase = portfolio_phase(evidence_n)
    supported = bool(evidence_n >= PORTFOLIO_SCREENING_N and grade in {"A", "B"})
    return {
        "game": game,
        "n": evidence_n,
        "stored_draws": len(usable),
        "comparison_cohort_n": comparison_n,
        "common_n_across_line_counts": comparison_n,
        "raw_max_n": max(raw_n_by_k.values()),
        "candidate_line_counts": candidate_ks,
        "by_lines": by_k,
        "research_best_lines": int(best["lines"]),
        "research_best_budget": round(float(best["cost_per_draw"]), 2),
        "research_best_roi_floor": best.get("mean_roi_floor"),
        "research_best_exact_roi": best.get("mean_exact_roi"),
        "budget_selection_objective": objective,
        "monetary_comparable": monetary_comparable,
        "selection_evidence_grade": grade,
        "selection_supported": supported,
        "auto_spend_research_ceiling": round(float(best["cost_per_draw"]), 2) if supported else 0.0,
        "evidence_note": note,
        **phase,
        "note": (
            "Budget learning is draw-level and line-count comparisons use one paired forward-draw cohort. "
            "Model-directed ROI floor is display-only until exact retail-package payouts are imported. "
            "Best-Match significance across compared line counts is BH-FDR adjusted. Evidence grade measures "
            "subset-selection support, not guaranteed profit."
        ),
    }
