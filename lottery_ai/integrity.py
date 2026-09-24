from __future__ import annotations

import hashlib
import json
from typing import Any


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def sha256_json(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def prediction_hash(predictions: list[dict] | None) -> str:
    compact = []
    for row in predictions or []:
        compact.append({
            "rank": int(row.get("rank", 0) or 0),
            "numbers": [int(n) for n in (row.get("numbers") or [])],
            "score": round(float(row.get("score", 0.0) or 0.0), 8),
            "components": {
                str(k): round(float(v), 8)
                for k, v in sorted((row.get("components") or {}).items())
                if isinstance(v, (int, float))
            },
            "coverage_mode": row.get("coverage_mode"),
            "coverage_engine": row.get("coverage_engine"),
        })
    return sha256_json(compact)


def candidate_universe_hash(candidates: list[dict] | None) -> str:
    """Hash only legal candidate combinations, independent of score/rank.

    Production and Challenger may score the same opportunities differently. This
    digest proves whether their underlying sampled candidate universe was identical.
    """
    combos = sorted(
        tuple(sorted(int(n) for n in (row.get("numbers") or [])))
        for row in (candidates or [])
    )
    return sha256_json([list(combo) for combo in combos])


def candidate_pool_hash(candidates: list[dict] | None) -> str:
    compact = [
        {
            "numbers": [int(n) for n in (row.get("numbers") or [])],
            "score": round(float(row.get("score", row.get("base_score", 0.0)) or 0.0), 8),
        }
        for row in (candidates or [])
    ]
    return sha256_json(compact)


def feature_snapshot_hash(predictions: list[dict] | None, weights: dict | None,
                          game: str, target: str, cutoff: str) -> str:
    payload = {
        "game": game,
        "target": target,
        "cutoff": cutoff,
        "weights": {str(k): round(float(v), 10) for k, v in sorted((weights or {}).items())},
        "features": [
            {
                "numbers": [int(n) for n in (row.get("numbers") or [])],
                "components": {
                    str(k): round(float(v), 8)
                    for k, v in sorted((row.get("components") or {}).items())
                    if isinstance(v, (int, float))
                },
            }
            for row in (predictions or [])
        ],
    }
    return sha256_json(payload)


def algorithm_hash(app_version: str, model_version: str, coverage_mode: str | None,
                   coverage_engine: str | None) -> str:
    return sha256_json({
        "app_version": app_version,
        "model_version": model_version,
        "coverage_mode": coverage_mode,
        "coverage_engine": coverage_engine,
    })


def build_freeze_integrity(*, predictions: list[dict], weights: dict | None,
                           game: str, target: str, cutoff: str,
                           app_version: str, model_version: str,
                           coverage_mode: str | None = None,
                           coverage_engine: str | None = None,
                           candidate_hash: str | None = None) -> dict:
    """Create freeze provenance plus the minimum inputs needed for later re-verification.

    The candidate pool itself is intentionally not embedded in the freeze because a 12k-row
    pool would materially bloat every record. Its digest is retained for provenance, but the
    verifier labels that layer NOT_VERIFIABLE unless an independent candidate snapshot exists.
    """
    normalized_weights = {
        str(k): round(float(v), 10) for k, v in sorted((weights or {}).items())
    }
    feature_inputs = {
        "weights": normalized_weights,
        "game": str(game),
        "target": str(target),
        "cutoff": str(cutoff),
    }
    algorithm_inputs = {
        "app_version": str(app_version),
        "model_version": str(model_version),
        "coverage_mode": coverage_mode,
        "coverage_engine": coverage_engine,
    }
    return {
        "schema": "INTEGRITY1.1",
        "prediction_sha256": prediction_hash(predictions),
        "feature_snapshot_sha256": feature_snapshot_hash(
            predictions, normalized_weights, game, target, cutoff
        ),
        "algorithm_sha256": algorithm_hash(**algorithm_inputs),
        "candidate_pool_sha256": candidate_hash,
        "verification_inputs": {
            "feature_snapshot": feature_inputs,
            "algorithm": algorithm_inputs,
        },
        "candidate_pool_verification": "RECORDED_ONLY" if candidate_hash else "NOT_PRESENT",
        "data_cutoff": str(cutoff),
        "target_draw_date": str(target),
        "post_draw_mutation_guard": True,
        "integrity_scope_note": (
            "Prediction, feature snapshot and algorithm descriptor can be re-hashed from the freeze. "
            "Candidate-pool SHA-256 is provenance-only unless an independent candidate snapshot is retained."
        ),
    }


def _layer(status: str, expected: str | None = None, actual: str | None = None,
           verifiable: bool | None = None, note: str | None = None) -> dict:
    out = {"status": status}
    if expected is not None:
        out["expected_sha256"] = expected
    if actual is not None:
        out["actual_sha256"] = actual
    if verifiable is not None:
        out["verifiable"] = bool(verifiable)
    if note:
        out["note"] = note
    return out


def verify_freeze_integrity(freeze: dict | None) -> dict:
    """Re-verify every layer that can be independently reconstructed from a freeze.

    Important semantic distinction:
    - PASS means a layer was actually re-hashed and matched.
    - NOT_VERIFIABLE means a digest exists but the source snapshot required to recompute it
      is intentionally not stored in this freeze.
    - LEGACY_NO_HASH means the older freeze predates that integrity field.
    """
    if not freeze:
        return {"status": "NO_FREEZE", "ok": False, "layers": {}}
    try:
        predictions = json.loads(freeze.get("predictions_json") or "[]")
    except Exception:
        return {
            "status": "INVALID_PREDICTIONS_JSON",
            "ok": False,
            "layers": {"prediction": _layer("INVALID_JSON", verifiable=False)},
        }
    try:
        ctx = json.loads(freeze.get("factor_context_json") or "{}")
    except Exception:
        ctx = {}

    saved = (ctx.get("integrity") or {}) if isinstance(ctx, dict) else {}
    if not isinstance(saved, dict) or not saved:
        actual_prediction = prediction_hash(predictions)
        return {
            "status": "LEGACY_NO_HASH",
            "ok": None,
            "fully_verifiable": False,
            "prediction_sha256": actual_prediction,
            "layers": {
                "prediction": _layer("LEGACY_NO_HASH", actual=actual_prediction, verifiable=False),
                "feature_snapshot": _layer("LEGACY_NO_HASH", verifiable=False),
                "algorithm": _layer("LEGACY_NO_HASH", verifiable=False),
                "candidate_pool": _layer("LEGACY_NO_HASH", verifiable=False),
            },
        }

    layers: dict[str, dict] = {}

    # 1) Frozen prediction payload: always reconstructable from predictions_json.
    expected_prediction = saved.get("prediction_sha256")
    actual_prediction = prediction_hash(predictions)
    if not expected_prediction:
        layers["prediction"] = _layer("LEGACY_NO_HASH", actual=actual_prediction, verifiable=False)
    elif actual_prediction == expected_prediction:
        layers["prediction"] = _layer("PASS", expected_prediction, actual_prediction, True)
    else:
        layers["prediction"] = _layer("MUTATION_DETECTED", expected_prediction, actual_prediction, True)

    verification_inputs = saved.get("verification_inputs") or {}

    # 2) Feature snapshot: V1.4.1+ stores weights/game/target/cutoff so this can be re-hashed.
    expected_feature = saved.get("feature_snapshot_sha256")
    finputs = verification_inputs.get("feature_snapshot") if isinstance(verification_inputs, dict) else None
    if not expected_feature:
        layers["feature_snapshot"] = _layer("LEGACY_NO_HASH", verifiable=False)
    elif isinstance(finputs, dict) and all(k in finputs for k in ("weights", "game", "target", "cutoff")):
        actual_feature = feature_snapshot_hash(
            predictions,
            finputs.get("weights") or {},
            str(finputs.get("game")),
            str(finputs.get("target")),
            str(finputs.get("cutoff")),
        )
        status = "PASS" if actual_feature == expected_feature else "MUTATION_DETECTED"
        layers["feature_snapshot"] = _layer(status, expected_feature, actual_feature, True)
    else:
        layers["feature_snapshot"] = _layer(
            "NOT_VERIFIABLE", expected_feature, verifiable=False,
            note="Legacy freeze lacks the feature verification inputs introduced in V1.4.1.",
        )

    # 3) Algorithm descriptor: V1.4.1+ stores the exact descriptor that produced the digest.
    expected_algorithm = saved.get("algorithm_sha256")
    ainputs = verification_inputs.get("algorithm") if isinstance(verification_inputs, dict) else None
    if not expected_algorithm:
        layers["algorithm"] = _layer("LEGACY_NO_HASH", verifiable=False)
    elif isinstance(ainputs, dict) and all(k in ainputs for k in ("app_version", "model_version")):
        actual_algorithm = algorithm_hash(
            str(ainputs.get("app_version")),
            str(ainputs.get("model_version")),
            ainputs.get("coverage_mode"),
            ainputs.get("coverage_engine"),
        )
        status = "PASS" if actual_algorithm == expected_algorithm else "MUTATION_DETECTED"
        layers["algorithm"] = _layer(status, expected_algorithm, actual_algorithm, True)
    else:
        layers["algorithm"] = _layer(
            "NOT_VERIFIABLE", expected_algorithm, verifiable=False,
            note="Legacy freeze lacks the algorithm verification inputs introduced in V1.4.1.",
        )

    # 4) Candidate pool: digest retained, full source pool intentionally not duplicated.
    candidate_expected = saved.get("candidate_pool_sha256")
    if candidate_expected:
        layers["candidate_pool"] = _layer(
            "NOT_VERIFIABLE", candidate_expected, verifiable=False,
            note="Digest recorded for provenance; the full pre-draw candidate pool is not embedded in the freeze.",
        )
    else:
        layers["candidate_pool"] = _layer("NOT_PRESENT", verifiable=False)

    mutation = any(v.get("status") == "MUTATION_DETECTED" for v in layers.values())
    verifiable = [v for v in layers.values() if v.get("verifiable") is True]
    all_verifiable_pass = bool(verifiable) and all(v.get("status") == "PASS" for v in verifiable)
    limitations = any(v.get("status") in {"NOT_VERIFIABLE", "LEGACY_NO_HASH"} for v in layers.values())

    if mutation:
        overall = "MUTATION_DETECTED"
        ok: bool | None = False
    elif all_verifiable_pass and limitations:
        overall = "PASS_WITH_LIMITATIONS"
        ok = True
    elif all_verifiable_pass:
        overall = "PASS"
        ok = True
    else:
        overall = "PARTIAL_UNVERIFIED"
        ok = None

    return {
        "status": overall,
        "ok": ok,
        "fully_verifiable": bool(all_verifiable_pass and not limitations),
        "schema": saved.get("schema"),
        "layers": layers,
        # Backward-compatible convenience fields used by existing UI/reporting.
        "expected_prediction_sha256": expected_prediction,
        "actual_prediction_sha256": actual_prediction,
        "feature_snapshot_sha256": saved.get("feature_snapshot_sha256"),
        "algorithm_sha256": saved.get("algorithm_sha256"),
        "candidate_pool_sha256": candidate_expected,
        "data_cutoff": saved.get("data_cutoff") or freeze.get("data_cutoff"),
        "integrity_scope_note": saved.get("integrity_scope_note"),
    }
