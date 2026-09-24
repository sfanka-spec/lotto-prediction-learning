from __future__ import annotations

import json
import math
from datetime import date, timedelta
from statistics import mean, median

from .analysis import FeatureEngine, paired_z_score, paired_t_critical_95
from .config import GAMES, MIN_PROMOTION_EVALS, BONUS_WEIGHTS, PREDICTIVE_FACTORS, normalize_main_weights
from .bonus import normalize_bonus_payload, main_bonus_consistency
from .champion import build_match_diagnostics, summarize_champion_records
from .portfolio import judge_frontier, learn_shadow_policy, portfolio_validation_summary, line_selection_learning
from .evaluation import sequential_sign_evalue


def next_draw_date(game_key: str, after: date) -> date:
    weekdays = set(GAMES[game_key].draw_weekdays)
    d = after + timedelta(days=1)
    while d.weekday() not in weekdays:
        d += timedelta(days=1)
    return d


def _corr(xs, ys):
    if len(xs) < 3:
        return 0.0
    mx, my = mean(xs), mean(ys)
    dx = [x-mx for x in xs]
    dy = [y-my for y in ys]
    sx = math.sqrt(sum(x*x for x in dx))
    sy = math.sqrt(sum(y*y for y in dy))
    if sx == 0 or sy == 0:
        return 0.0
    return sum(a*b for a,b in zip(dx,dy))/(sx*sy)


class LearningManager:
    def __init__(self, db):
        self.db = db

    def judge_new_draw(self, game_key: str, draw: dict):
        # V1.5 budget/portfolio decisions are judged independently from number-model
        # freezes. This remains active even if the old freeze was already judged by an
        # earlier build.
        self._judge_portfolio_decisions(game_key, draw)
        freezes = self.db.unjudged_freezes_for_date(game_key, draw["draw_date"])
        if not freezes:
            return []
        actual = set(draw["numbers"])
        results = []
        for f in freezes:
            preds = json.loads(f["predictions_json"])
            hits = [len(actual & set(p["numbers"])) for p in preds]
            raw_bonus = json.loads(f["bonus_rank_json"] or "[]")
            bonus_payload = normalize_bonus_payload(raw_bonus, preds)
            bonus_rank_hit = None
            bonus_rank_by_main = {}
            if draw.get("bonus") is not None:
                actual_bonus = int(draw["bonus"])
                for bound in bonus_payload.get("by_pick") or []:
                    main_rank = int(bound.get("main_rank", 0))
                    found = None
                    for i, item in enumerate(bound.get("ranking") or [], 1):
                        if int(item[0]) == actual_bonus:
                            found = i
                            break
                    bonus_rank_by_main[str(main_rank)] = found
                # Keep the existing DB column backward-compatible: it continues to
                # mean the conditional Bonus rank tied to Main Pick #1. Per-pick
                # ranks are preserved in details_json without a schema migration.
                bonus_rank_hit = bonus_rank_by_main.get("1")
            cfg = GAMES[game_key]
            random_baseline = cfg.pick * cfg.pick / cfg.max_number
            consistency = main_bonus_consistency(preds, bonus_payload, max_number=GAMES[game_key].max_number, expected_limit=10)
            details = {
                "hits": hits, "actual": sorted(actual), "model_version": f["model_version"],
                "bonus_conditional_rank_by_main_pick": bonus_rank_by_main,
                "main_bonus_consistency": consistency,
            }
            best_hit = max(hits) if hits else 0
            avg_hit = mean(hits) if hits else 0.0
            med_hit = median(hits) if hits else 0.0
            self.db.save_judgment(
                f["id"], game_key, draw["draw_date"], best_hit, avg_hit, med_hit,
                bonus_rank_hit, random_baseline, details
            )
            try:
                freeze_ctx = json.loads(f.get("factor_context_json") or "{}")
            except Exception:
                freeze_ctx = {}
            champion_diag = build_match_diagnostics(
                game_key, preds, draw, raw_bonus,
                candidate_number_profile=freeze_ctx.get("candidate_number_profile"),
            )
            self.db.save_champion_learning(
                f["id"], game_key, draw["draw_date"], f["model_version"], champion_diag
            )
            results.append(details | {
                "best_hit": best_hit, "avg_hit": avg_hit,
                "champion": champion_diag,
            })
            if str(f["model_version"]).startswith("C"):
                self._learn_challenger(game_key, preds, hits)
                if draw.get("bonus") is not None:
                    self._learn_bonus_challenger(game_key, draw)
        # Champion Match learning is a separate shadow track. It is recalculated from
        # immutable frozen Production diagnostics and has 0% Production influence.
        self._refresh_champion_shadow(game_key)
        self._maybe_promote(game_key)
        return results

    def _judge_portfolio_decisions(self, game_key: str, draw: dict):
        decided = self.db.unjudged_portfolio_decisions_for_date(game_key, draw["draw_date"])
        if not decided:
            return []
        out=[]
        for row in decided:
            try:
                decision=json.loads(row.get("decision_json") or "{}")
            except Exception:
                continue
            frozen_rows=decision.get("frozen_rows") or []
            if not frozen_rows:
                continue
            judgment=judge_frontier(game_key, frozen_rows, decision, draw)
            self.db.save_portfolio_judgment(
                row["id"], game_key, draw["draw_date"], row.get("model_version") or "BUD1.0", judgment
            )
            out.append(judgment)
        self._refresh_portfolio_shadow(game_key)
        return out

    def _refresh_portfolio_shadow(self, game_key: str):
        records=self.db.portfolio_learning_records(game_key,limit=250)
        learned=learn_shadow_policy(records)
        validation=portfolio_validation_summary(records)
        line_learning=line_selection_learning(records)
        self.db.set_state(f"portfolio_shadow_learning_{game_key}", learned)
        self.db.set_state(f"portfolio_validation_{game_key}", validation)
        self.db.set_state(f"portfolio_line_learning_{game_key}", line_learning)
        return {"learning":learned,"validation":validation,"line_learning":line_learning}

    def backfill_champion_diagnostics(self, game_key: str, draws: list[dict], limit: int = 60):
        """Backfill Champion diagnostics for already-judged legacy/current freezes.

        V1.2.4 needs this because a draw may already have been judged by V1.2.3 before
        the new Champion table existed. The original freeze is never changed.
        """
        if not draws:
            return 0
        by_date = {str(d.get("draw_date")): d for d in draws[-max(1, int(limit)):]}
        inserted = 0
        for draw_date, draw in by_date.items():
            for f in self.db.freezes_for_date(game_key, draw_date):
                version = str(f.get("model_version") or "")
                # Keep controls available for comparison, but only Production contributes
                # to the Champion Shadow profile below.
                try:
                    preds = json.loads(f.get("predictions_json") or "[]")
                    raw_bonus = json.loads(f.get("bonus_rank_json") or "[]")
                except Exception:
                    continue
                if not preds:
                    continue
                try:
                    freeze_ctx = json.loads(f.get("factor_context_json") or "{}")
                except Exception:
                    freeze_ctx = {}
                diag = build_match_diagnostics(
                    game_key, preds, draw, raw_bonus,
                    candidate_number_profile=freeze_ctx.get("candidate_number_profile"),
                )
                if self.db.save_champion_learning(
                    f["id"], game_key, draw_date, version, diag
                ):
                    inserted += 1
        self._refresh_champion_shadow(game_key)
        return inserted

    def _refresh_champion_shadow(self, game_key: str):
        """Build a conservative Champion-derived shadow profile.

        This is genuine post-draw learning, but deliberately isolated from Production.
        The profile is anchored to the current Production weights and only becomes more
        responsive as the number of evaluated Production draws grows.
        """
        records = self.db.champion_learning_records(game_key, prefix="P", limit=200)
        summary = summarize_champion_records(records)
        if not summary.get("n"):
            return None
        state_key = f"champion_shadow_signature_{game_key}"
        signature = summary.get("signature")
        if self.db.get_state(state_key) == signature:
            return summary

        cfg = GAMES[game_key]
        base_raw, _ = self.db.active_weights(game_key, "production", cfg.default_weights)
        base = normalize_main_weights(base_raw)
        old_shadow_raw, old_ver = self.db.active_weights(game_key, "champion_shadow", base)
        old_shadow = normalize_main_weights(old_shadow_raw)
        n = int(summary.get("n", 0))
        confidence = min(1.0, n / 30.0)
        mean_signal = summary.get("mean_component_signal") or {}
        raw = {}
        # Signals are already heavily evidence-damped per draw. This second sample-size
        # damping prevents early random winners from moving even the shadow profile much.
        for k in PREDICTIVE_FACTORS:
            shift = 0.75 * confidence * float(mean_signal.get(k, 0.0))
            raw[k] = max(0.02, min(0.45, base[k] * math.exp(shift)))
        total = sum(raw.values()) or 1.0
        new = {k: raw[k] / total for k in PREDICTIVE_FACTORS}
        new["monte_carlo"] = 0.0
        try:
            idx = int(str(old_ver).split(".")[-1]) + 1
        except Exception:
            idx = 1
        ver = f"CS1.{idx}"
        self.db.save_weights(
            game_key, "champion_shadow", ver, new,
            f"Champion Match shadow profile from {n} frozen Production draw(s); Production impact 0%",
            active=True,
        )
        self.db.add_learning_log(
            game_key, "champion_shadow", old_shadow, new,
            {
                "samples": n,
                "calibration": summary.get("calibration"),
                "mean_component_signal": mean_signal,
                "mean_component_delta": summary.get("mean_component_delta"),
                "bottlenecks": summary.get("bottlenecks"),
                "production_impact": 0.0,
            },
            "Champion Match shadow learning; frozen-score diagnostics only; Production unchanged",
        )
        self.db.set_state(state_key, signature)
        return summary

    def _learn_challenger(self, game_key, preds, hits):
        cfg = GAMES[game_key]
        old_raw, old_ver = self.db.active_weights(game_key, "challenger", cfg.default_weights)
        old = normalize_main_weights(old_raw)
        signal = {}
        for factor in PREDICTIVE_FACTORS:
            xs = [float(p.get("components",{}).get(factor,50)) for p in preds]
            c = _corr(xs, hits)
            signal[factor] = c
        # Very small bounded update. One draw can never swing the model strongly.
        # Diagnostic Monte Carlo is deliberately excluded from learning.
        lr = 0.025
        raw = {}
        for k in PREDICTIVE_FACTORS:
            w = old[k]
            multiplier = math.exp(lr * signal.get(k,0))
            raw[k] = max(0.04, min(0.35, w*multiplier))
        total = sum(raw.values()) or 1.0
        new = {k: raw[k]/total for k in PREDICTIVE_FACTORS}
        new["monte_carlo"] = 0.0
        # Version increments in learning log; active challenger snapshot is replaced.
        try:
            idx = int(old_ver.split(".")[-1]) + 1
        except Exception:
            idx = 1
        ver = f"C1.{idx}"
        self.db.save_weights(game_key, "challenger", ver, new,
                             "Adaptive update from prediction-vs-actual hit correlation", active=True)
        self.db.add_learning_log(game_key, "challenger", old, new, signal,
                                 "Small bounded update; Production unchanged")


    def _learn_bonus_challenger(self, game_key, draw):
        # Recreate the information set that existed before this draw.
        prior = [d for d in self.db.draws(game_key, era_only=True, model_ready=True) if d["draw_date"] < draw["draw_date"]]
        if len(prior) < 10:
            return
        fe = FeatureEngine(game_key, prior)
        actual = int(draw["bonus"])
        excluded = set(draw["numbers"])
        eligible = [n for n in fe.pool if n not in excluded]
        old, old_ver = self.db.active_weights(game_key, "bonus_challenger", BONUS_WEIGHTS)
        signal = {}
        actual_c = fe.bonus_components(actual)
        for factor in old:
            vals = sorted(fe.bonus_components(n)[factor] for n in eligible)
            if not vals:
                signal[factor]=0.0
                continue
            rank = sum(v <= actual_c[factor] for v in vals) / len(vals)
            signal[factor] = 2*(rank-.5)
        lr = 0.015
        raw = {k:max(0.08,min(0.75,w*math.exp(lr*signal.get(k,0)))) for k,w in old.items()}
        total=sum(raw.values())
        new={k:v/total for k,v in raw.items()}
        try: idx=int(old_ver.split(".")[-1])+1
        except Exception: idx=1
        ver=f"BC1.{idx}"
        self.db.save_weights(game_key,"bonus_challenger",ver,new,
                             "Bonus adaptive update from actual bonus factor percentiles",active=True)
        self.db.add_learning_log(game_key,"bonus_challenger",old,new,signal,
                                 "Bonus model learns separately from main-number model")

    def _maybe_promote(self, game_key):
        if not self.db.get_state("auto_promotion", False):
            return False
        pairs = self.db.paired_model_performance(game_key, limit=200)
        if len(pairs) < MIN_PROMOTION_EVALS:
            return False
        diffs = [c-p for _,p,c,_ in pairs]
        md = mean(diffs)
        z = paired_z_score(diffs)
        chall_mean = mean(c for _,_,c,_ in pairs)
        rb = [r for *_,r in pairs if r is not None]
        rb_mean = mean(rb) if rb else None
        # Promotion is repeatedly re-evaluated after new draws. Use sample-SD paired
        # t screening plus an always-valid sign e-process so optional stopping cannot
        # turn repeated checking into an automatic false promotion.
        sequential_e = sequential_sign_evalue(diffs)
        if (md > 0.015 and z >= paired_t_critical_95(len(diffs)) and sequential_e >= 20.0
                and (rb_mean is None or chall_mean > rb_mean + .01)):
            cfg = GAMES[game_key]
            cw_raw, cver = self.db.active_weights(game_key, "challenger", cfg.default_weights)
            pw_raw, pver = self.db.active_weights(game_key, "production", cfg.default_weights)
            cw = normalize_main_weights(cw_raw)
            pw = normalize_main_weights(pw_raw)
            try:
                idx = int(pver.split(".")[-1]) + 1
            except Exception:
                idx = 1
            new_pver = f"P1.{idx}"
            reason = f"Auto-promoted {cver}: paired z={z:.2f}, mean edge={md:.3f}"
            self.db.save_weights(game_key, "production", new_pver, cw, reason, active=True)
            self.db.add_learning_log(
                game_key,
                "production",
                pw,
                cw,
                {
                    "paired_z": round(float(z), 6),
                    "mean_edge": round(float(md), 6),
                    "challenger_mean": round(float(chall_mean), 6),
                    "random_baseline_mean": round(float(rb_mean), 6) if rb_mean is not None else None,
                    "promoted_from": cver,
                    "previous_production": pver,
                    "new_production": new_pver,
                },
                reason,
            )
            return True
        return False

    def freeze_next(self, game_key: str, draws: list[dict], production_preds, challenger_preds,
                    production_version: str, challenger_version: str,
                    production_bonus, challenger_bonus,
                    production_bonus_version: str | None = None,
                    challenger_bonus_version: str | None = None,
                    app_version: str | None = None,
                    production_context_extra: dict | None = None,
                    challenger_context_extra: dict | None = None):
        """Freeze Main + per-Main Bonus predictions with provenance, no DB migration.

        Bonus model/version metadata lives inside the existing factor_context_json
        column, preserving full backward compatibility with V1.0.x databases.
        """
        if not draws:
            return None
        last_date = date.fromisoformat(draws[-1]["draw_date"])
        target = next_draw_date(game_key, last_date)
        cutoff = draws[-1]["draw_date"]
        rows = (
            (production_version, production_preds, production_bonus, production_bonus_version, production_context_extra or {}),
            (challenger_version, challenger_preds, challenger_bonus, challenger_bonus_version, challenger_context_extra or {}),
        )
        batch = []
        for version, preds, bonus, bonus_version, context_extra in rows:
            context = {
                    "note":"Frozen before draw; no future data allowed",
                    "app_version": app_version,
                    "main_score_name":"Combination Score",
                    "bonus_score_name":"Bonus Conditional Score",
                    "bonus_binding_schema":"per_main_v1",
                    "bonus_model_version": bonus_version,
                    "bonus_bound_picks": len((bonus or {}).get("by_pick") or []) if isinstance(bonus, dict) else 1,
                    "bonus_rankings_frozen": True,
                    "coverage_engine": next((p.get("coverage_engine") for p in (preds or []) if isinstance(p, dict) and p.get("coverage_engine")), None),
                    "coverage_mode": next((p.get("coverage_mode") for p in (preds or []) if isinstance(p, dict) and p.get("coverage_mode")), None),
                    "coverage_portfolio_frozen": bool(any(isinstance(p, dict) and p.get("coverage_engine") for p in (preds or []))),
                }
            context.update(context_extra or {})
            batch.append({
                "game": game_key, "target_date": target.isoformat(), "model_version": version,
                "data_cutoff": cutoff, "predictions": preds, "bonus_rank": bonus,
                "factor_context": context,
            })
        # Production and Challenger belong to one logical pre-draw snapshot. A crash
        # cannot leave only one side committed.
        self.db.save_freeze_batch(batch)
        return target.isoformat()
