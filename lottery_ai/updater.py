from __future__ import annotations

import csv
import io
import logging
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from .config import GAMES, DRAW_SCHEDULES
from .jackpot import WCLCJackpotProvider, jackpot_economics
from .regime import regime_for, current_regime
from .config import RESULT_GRACE_HOUR
from .timeutil import pacific_now
from .providers import (
    LottizenProvider, WCLCOfficialValidator, WCLCOfficialProvider,
    LotoQuebecOfficialProvider, AtlanticLotteryOfficialVerifier,
    WCLCOfficialHistoryProvider, WCLCSinceInceptionProvider, NationalLottery649HistoryProvider,
    OLGOfficialProvider, LottoDatabaseHistoryProvider, LottoNetHistoryProvider, GitHubCsvHistoryProvider,
    ProviderError, validate_draw_for_date,
)

logger = logging.getLogger(__name__)


def era_for(game_key: str, draw_date: str) -> str:
    return str(regime_for(game_key, draw_date)["name"])


class DataUpdater:
    def __init__(self, db):
        self.db = db
        # Legacy structured fallback is retained, but no longer the sole history path.
        self.history = LottizenProvider()
        self.wclc_validator = WCLCOfficialValidator()
        self.wclc = WCLCOfficialProvider()
        self.wclc_history = WCLCOfficialHistoryProvider()
        self.wclc_full_history = WCLCSinceInceptionProvider()
        self.archive649 = NationalLottery649HistoryProvider()
        self.lq = LotoQuebecOfficialProvider()
        self.alc = AtlanticLotteryOfficialVerifier()
        self.olg = OLGOfficialProvider()
        self.lottodb = LottoDatabaseHistoryProvider()
        self.lottonet = LottoNetHistoryProvider()
        self.github_history = GitHubCsvHistoryProvider()
        self.jackpot = WCLCJackpotProvider()

    # ---------- Draw calendar / history integrity ----------
    @staticmethod
    def _effective_today():
        now = pacific_now()
        # On a draw day, do not count tonight's draw as missing before results normally exist.
        return now.date(), now.hour

    @classmethod
    def expected_draw_dates(cls, game_key: str, end_date: date | None = None) -> list[str]:
        today, hour = cls._effective_today()
        end_date = end_date or today
        out = []
        if game_key == "649":
            sched = DRAW_SCHEDULES["649"]
            start = date.fromisoformat(sched["start"])
            twice_weekly = date.fromisoformat(sched["twice_weekly_start"])  # First Wednesday draw; Saturday schedule continued.
            d = start
            while d <= end_date:
                ok = (d.weekday() == 5) if d < twice_weekly else (d.weekday() in (2, 5))
                if ok:
                    if not (d == today and hour < RESULT_GRACE_HOUR):
                        out.append(d.isoformat())
                d += timedelta(days=1)
        else:
            sched = DRAW_SCHEDULES["max"]
            start = date.fromisoformat(sched["start"])
            twice_weekly = date.fromisoformat(sched["twice_weekly_start"])  # first Tuesday draw; Friday continued.
            d = start
            while d <= end_date:
                ok = (d.weekday() == 4) if d < twice_weekly else (d.weekday() in (1, 4))
                if ok:
                    if not (d == today and hour < RESULT_GRACE_HOUR):
                        out.append(d.isoformat())
                d += timedelta(days=1)
        return out

    def _canonical_expected_dates(self, game_key: str, end_date: date | None = None):
        """Prefer WCLC's official archive dates; extend with schedule dates after archive cutoff."""
        today, _ = self._effective_today()
        end_date = end_date or today
        official = self.db.get_state(f"official_calendar_{game_key}", []) or []
        official = sorted({str(x)[:10] for x in official if str(x)[:10] <= end_date.isoformat()})
        if official:
            last = official[-1]
            tail = [d for d in self.expected_draw_dates(game_key, end_date) if d > last]
            return sorted(set(official) | set(tail)), "WCLC OFFICIAL ARCHIVE"
        return self.expected_draw_dates(game_key, end_date), "SCHEDULE FALLBACK"

    def history_health(self, game_key: str) -> dict:
        base_expected, calendar_source = self._canonical_expected_dates(game_key)
        actual_rows = self.db.draws(game_key, era_only=False)
        actual = {d["draw_date"] for d in actual_rows}
        by_date = {d["draw_date"]: d for d in actual_rows}

        # When a complete official archive calendar is temporarily unavailable, the
        # weekday schedule is only a *provisional* calendar. Any off-schedule row that
        # has already been verified through an official-source path is treated as a
        # provisional special draw instead of contamination. This applies to both
        # LOTTO 6/49 and LOTTO MAX (holiday/special draw dates can occur).
        base_exp = set(base_expected)
        provisional_special_dates = []
        if calendar_source == "SCHEDULE FALLBACK":
            provisional_special_dates = sorted(
                d["draw_date"] for d in actual_rows
                if d.get("verified") and d["draw_date"] not in base_exp
            )
        exp = base_exp | set(provisional_special_dates)
        expected = sorted(exp)

        matched = len(exp & actual)
        missing = sorted(exp - actual)
        unexpected = sorted(actual - exp)
        invalid = sorted(
            d["draw_date"] for d in actual_rows
            if not validate_draw_for_date(game_key, d["draw_date"], d.get("numbers", []), d.get("bonus"))
        )
        unverified_unexpected = [d for d in unexpected if not by_date[d].get("verified")]
        verified_unexpected = [d for d in unexpected if by_date[d].get("verified")]
        unresolved_conflicts = self.db.get_state(f"history_unresolved_conflicts_{game_key}", []) or []
        completeness = matched / len(exp) if exp else 0.0

        # Diagnose common contamination patterns. Public files named merely "6/49"
        # may belong to another country's game or contain a date shifted by one day.
        # A same-six-numbers match on an adjacent legitimate draw is strong evidence
        # of a transcription/date-shift artifact; bonus agreement is recorded but is
        # not required because several public CSVs omit or corrupt the bonus column.
        shifted_duplicates = []
        strong_shifted_duplicates = []
        unexpected_details = []
        for ds in unexpected:
            row = by_date.get(ds) or {}
            shifted_to = None
            shift_strength = None
            try:
                d0 = date.fromisoformat(ds)
                for adj in (d0 - timedelta(days=1), d0 + timedelta(days=1)):
                    ads = adj.isoformat()
                    a = by_date.get(ads)
                    if not a or ads not in exp:
                        continue
                    same_main = tuple(sorted(map(int, a.get("numbers", [])))) == tuple(sorted(map(int, row.get("numbers", []))))
                    if not same_main:
                        continue
                    shifted_to = ads
                    ab = a.get("bonus")
                    rb = row.get("bonus")
                    if ab is not None and rb is not None and int(ab) == int(rb):
                        shift_strength = "EXACT"
                        strong_shifted_duplicates.append(ds)
                    else:
                        shift_strength = "MAIN_NUMBERS"
                    break
            except Exception:
                pass
            if shifted_to:
                shifted_duplicates.append(ds)
            raw = row.get("raw") or {}
            if shifted_to:
                classification = "ADJACENT_DATE_DUPLICATE"
            elif row.get("verified"):
                classification = "VERIFIED_OFFICIAL_OFF_CALENDAR"
            else:
                classification = "UNVERIFIED_OFF_SCHEDULE"
            unexpected_details.append({
                "date": ds, "source": row.get("source"), "verified": bool(row.get("verified")),
                "classification": classification,
                "shift_duplicate_of": shifted_to, "shift_strength": shift_strength,
                "provider_sources": raw.get("sources") if isinstance(raw, dict) else None,
                "provider_raw": raw.get("provider_raw") if isinstance(raw, dict) else None,
            })

        # Raw status describes what is physically stored. Model status describes the
        # audited set that can actually enter features/prediction/learning.
        issues = len(missing) + len(invalid) + len(unverified_unexpected) + len(unresolved_conflicts)
        if issues == 0 and not verified_unexpected:
            status = "COMPLETE"
        elif completeness >= 0.995:
            status = "WARNING"
        elif completeness >= 0.98:
            status = "NEAR COMPLETE"
        else:
            status = "INCOMPLETE"

        exclusions = set(invalid)
        exclusions.update(unresolved_conflicts)
        # Safety rule for every game: an unexpected/off-calendar historical row that
        # has no official verification is never allowed into model-ready history.
        # We retain it in the raw archive for provenance/audit, but quarantine it.
        exclusions.update(unverified_unexpected)

        # Archive/model-ready integrity must be measured against the all-time expected
        # calendar. Do NOT compare LOTTO MAX's current-era rows (MAX_52) with the full
        # 2009-present history; doing so produced the misleading ~3.5% score in V1.0.7.
        archive_model_rows = [d for d in actual_rows if d["draw_date"] not in exclusions]
        archive_model_dates = {d["draw_date"] for d in archive_model_rows}
        model_missing = sorted(exp - archive_model_dates)
        model_unexpected = sorted(archive_model_dates - exp)
        model_invalid = sorted(
            d["draw_date"] for d in archive_model_rows
            if not validate_draw_for_date(game_key, d["draw_date"], d.get("numbers", []), d.get("bonus"))
        )
        model_data_status = "CLEAN" if not (model_missing or model_unexpected or model_invalid or unresolved_conflicts) else "WARNING"

        # Current model-era metrics are separate. LOTTO MAX production intentionally
        # trains/evaluates only the current Lotto Max regime onward.
        era_rows = self.db.draws(game_key, era_only=True)
        model_rows = [d for d in era_rows if d["draw_date"] not in exclusions]
        model_era_count = len(model_rows)
        if game_key == "max":
            era_start = current_regime(game_key)["start"]
            era_expected = {d for d in exp if d >= era_start}
        else:
            era_expected = set(exp)
        era_model_dates = {d["draw_date"] for d in model_rows}
        era_missing = sorted(era_expected - era_model_dates)
        era_unexpected = sorted(era_model_dates - era_expected)
        era_coverage = (len(era_expected & era_model_dates) / len(era_expected)) if era_expected else 0.0

        integrity_denom = max(1, len(actual_rows))
        integrity_penalty = len(invalid) + len(unverified_unexpected) + len(unresolved_conflicts)
        integrity_score = max(0.0, 100.0 * (1.0 - integrity_penalty / integrity_denom))
        usable_denom = max(1, len(exp))
        usable_penalty = len(model_missing) + len(model_unexpected) + len(model_invalid) + len(unresolved_conflicts)
        usable_integrity = max(0.0, 100.0 * (1.0 - usable_penalty / usable_denom))
        unexpected_classes = {}
        for item in unexpected_details:
            cls_name = item.get("classification") or "UNCLASSIFIED"
            unexpected_classes[cls_name] = unexpected_classes.get(cls_name, 0) + 1

        return {
            "status": status,
            "model_data_status": model_data_status,
            "calendar_source": calendar_source,
            "calendar_base_expected": len(base_expected),
            "provisional_special_draws": len(provisional_special_dates),
            "provisional_special_dates": provisional_special_dates,
            "expected": len(expected),
            "stored": len(actual_rows),
            "unique_dates": len(actual),
            "matched": matched,
            "missing": len(missing),
            "missing_dates": missing,
            "missing_sample": missing[-12:],
            "extra": len(unexpected),
            "unexpected": len(unexpected),
            "unexpected_dates": unexpected,
            "unexpected_sample": unexpected[-12:],
            "unverified_unexpected": len(unverified_unexpected),
            "verified_unexpected": len(verified_unexpected),
            "shifted_duplicates": len(shifted_duplicates),
            "shifted_duplicate_dates": sorted(shifted_duplicates),
            "strong_shifted_duplicates": len(strong_shifted_duplicates),
            "strong_shifted_duplicate_dates": sorted(strong_shifted_duplicates),
            "unexpected_details": unexpected_details,
            "unexpected_classes": unexpected_classes,
            "invalid": len(invalid),
            "invalid_dates": invalid,
            "conflicts": len(unresolved_conflicts),
            "conflict_dates": sorted(unresolved_conflicts),
            "completeness": round(completeness, 6),
            "percent": round(completeness * 100, 2),
            "coverage_pct": round(completeness * 100, 2),
            "integrity_score": round(integrity_score, 3),
            "usable_integrity_score": round(usable_integrity, 3),
            "model_ready_archive_draws": len(archive_model_rows),
            "model_era_draws": model_era_count,
            "model_era_expected": len(era_expected),
            "model_era_coverage_pct": round(era_coverage * 100, 3),
            "model_era_missing_dates": era_missing,
            "model_era_unexpected_dates": era_unexpected,
            "model_missing_dates": model_missing,
            "model_unexpected_dates": model_unexpected,
            "model_invalid_dates": model_invalid,
            "model_exclusions": sorted(exclusions),
        }

    def audit_history(self, game_key: str) -> dict:
        health = self.history_health(game_key)
        exclusions = health.get("model_exclusions", [])
        self.db.set_state(f"model_exclusions_{game_key}", exclusions)
        audit = {
            "completed": datetime.now().isoformat(timespec="seconds"),
            "status": health["status"],
            "model_data_status": health.get("model_data_status"),
            "calendar_source": health.get("calendar_source"),
            "coverage_pct": health.get("coverage_pct"),
            "integrity_score": health.get("integrity_score"),
            "usable_integrity_score": health.get("usable_integrity_score"),
            "provisional_special_dates": health.get("provisional_special_dates", []),
            "missing_dates": health.get("missing_dates", []),
            "unexpected_dates": health.get("unexpected_dates", []),
            "unexpected_details": health.get("unexpected_details", []),
            "shifted_duplicate_dates": health.get("shifted_duplicate_dates", []),
            "strong_shifted_duplicate_dates": health.get("strong_shifted_duplicate_dates", []),
            "invalid_dates": health.get("invalid_dates", []),
            "conflict_dates": health.get("conflict_dates", []),
            "model_missing_dates": health.get("model_missing_dates", []),
            "model_unexpected_dates": health.get("model_unexpected_dates", []),
            "model_exclusions": exclusions,
        }
        self.db.set_state(f"history_audit_{game_key}", audit)
        return health

    @staticmethod
    def _fingerprint(d: dict):
        return tuple(sorted(map(int, d.get("numbers", [])))), int(d.get("bonus")) if d.get("bonus") is not None else None

    def _require_valid_record(self, game_key: str, record: dict, context: str) -> None:
        """Fail closed immediately before any clean-draw database write."""
        if not record or not record.get("date"):
            raise ProviderError(f"{context}: missing draw date")
        if not validate_draw_for_date(
            game_key, record["date"], record.get("numbers", []), record.get("bonus")
        ):
            self.db.save_raw(
                game_key, record.get("source", context), record.get("raw", record),
                "rejected", f"{context}: final date-aware validation failed"
            )
            raise ProviderError(
                f"{context}: rejected invalid draw {record.get('date')} "
                f"numbers={record.get('numbers')} bonus={record.get('bonus')}"
            )

    def _merge_history_records(self, game_key: str, records: list[dict]) -> dict:
        grouped = {}
        for d in records:
            if not d or not d.get("date") or not validate_draw_for_date(game_key, d.get("date"), d.get("numbers", []), d.get("bonus")):
                continue
            grouped.setdefault(d["date"], []).append(d)
        before = self.db.count_draws(game_key)
        conflicts = 0
        accepted = 0
        consensus = 0
        unresolved = set(self.db.get_state(f"history_unresolved_conflicts_{game_key}", []) or [])
        conflict_dates = []
        for draw_date, rows in sorted(grouped.items()):
            fps = {}
            for d in rows:
                fps.setdefault(self._fingerprint(d), []).append(d)
            existing = self.db.draw_by_date(game_key, draw_date)
            chosen_rows = None
            if len(fps) > 1:
                # An official WCLC since-inception row is canonical when recovery sources disagree.
                official_groups = [v for v in fps.values() if any(r.get("verified") for r in v)]
                if len(official_groups) == 1:
                    chosen_rows = official_groups[0]
                    conflicts += 1
                elif len(official_groups) > 1:
                    conflicts += 1
                    conflict_dates.append(draw_date)
                    unresolved.add(draw_date)
                    self.db.save_raw(game_key, "history consensus", rows, "conflict", "Official historical sources disagree")
                    continue
                elif existing and existing.get("verified"):
                    # Preserve an already verified current/official row.
                    unresolved.discard(draw_date)
                    continue
                else:
                    winner_fp, winner_rows = max(fps.items(), key=lambda kv: len({r.get("source") for r in kv[1]}))
                    source_count = len({r.get("source") for r in winner_rows})
                    runner = sorted((len({r.get("source") for r in v}) for v in fps.values()), reverse=True)
                    if source_count < 2 or (len(runner) > 1 and runner[0] == runner[1]):
                        conflicts += 1
                        conflict_dates.append(draw_date)
                        unresolved.add(draw_date)
                        self.db.save_raw(game_key, "history consensus", rows, "conflict", "Historical sources disagree")
                        continue
                    chosen_rows = winner_rows
                    consensus += 1
            else:
                chosen_rows = next(iter(fps.values()))
                source_count = len({r.get("source") for r in chosen_rows})
                if source_count >= 2:
                    consensus += 1

            chosen = chosen_rows[0]
            sources = sorted({r.get("source", "history") for r in chosen_rows})
            verified = any(bool(r.get("verified")) for r in chosen_rows)
            label = "History consensus: " + " + ".join(sources) if len(sources) >= 2 else sources[0]
            raw = {
                "history_sources": sources,
                "source_count": len(sources),
                "consensus": len(sources) >= 2,
                "official_verified": verified,
                "provider_raw": [r.get("raw") for r in chosen_rows[:3]],
            }
            self._require_valid_record(game_key, chosen, "history merge")
            self.db.save_raw(game_key, label, raw, "validated")
            self.db.upsert_draw(
                game_key, chosen["date"], era_for(game_key, chosen["date"]), chosen["numbers"], chosen.get("bonus"),
                label, chosen.get("source_url"), verified=verified, raw=raw,
            )
            unresolved.discard(draw_date)
            accepted += 1
        self.db.set_state(f"history_unresolved_conflicts_{game_key}", sorted(unresolved))
        after = self.db.count_draws(game_key)
        return {
            "added": max(0, after - before), "accepted": accepted, "conflicts": conflicts,
            "consensus": consensus, "conflict_dates": sorted(conflict_dates),
            "unresolved_conflicts": len(unresolved),
        }

    def repair_history(self, game_key: str, progress=None, force_full: bool = False) -> dict:
        health0 = self.history_health(game_key)
        small_db = self.db.count_draws(game_key) <= 50
        needs_official_refresh = health0.get("calendar_source") != "WCLC OFFICIAL ARCHIVE"

        # Do not stop merely because a fallback weekday calendar reports zero
        # missing draws. Both national games can contain official special/holiday
        # dates that a generic weekday schedule cannot reconstruct.
        issue_dates = set(health0.get("missing_dates", []))
        issue_dates.update(health0.get("unexpected_dates", []))
        issue_dates.update(health0.get("invalid_dates", []))
        issue_dates.update(health0.get("conflict_dates", []))

        if force_full or small_db:
            years = list(range(1982 if game_key == "649" else 2009, date.today().year + 1))
        else:
            years = sorted({int(x[:4]) for x in issue_dates})

        if not years and not force_full and not needs_official_refresh:
            health = self.audit_history(game_key)
            return {
                "ok": True, "added": 0,
                "message": "No scheduled gaps; integrity audit refreshed",
                "health": health, "sources": {},
            }

        records = []
        source_report = {}
        wanted = set(years)
        official_full_ok = False
        all_official = []

        # 1) Canonical official WCLC since-inception archive for BOTH games.
        # The official date list is authoritative; weekday schedules are fallback only.
        self.db.set_state(f"official_archive_attempt_{game_key}", {"at": datetime.now().isoformat(timespec="seconds")})
        try:
            all_official = self.wclc_full_history.fetch_all(game_key)
            archive_dates = sorted({d["date"] for d in all_official})
            archive_last = archive_dates[-1] if archive_dates else None
            archive_first = archive_dates[0] if archive_dates else None
            schedule_to_cutoff = set(
                self.expected_draw_dates(game_key, date.fromisoformat(archive_last))
            ) if archive_last else set()
            archive_schedule_coverage = (
                len(schedule_to_cutoff & set(archive_dates)) / len(schedule_to_cutoff)
            ) if schedule_to_cutoff else 0.0
            expected_first = str(DRAW_SCHEDULES[game_key]["start"])
            min_rows = {"649": 1000, "max": 700}[game_key]
            recent_enough = bool(archive_last) and date.fromisoformat(archive_last) >= date.today() - timedelta(days=90)
            # Do not require near-perfect weekday compatibility here: the reason for
            # preferring the official calendar is precisely that special/holiday
            # dates can differ from a hard-coded weekday schedule.
            calendar_accepted = (
                archive_first == expected_first
                and len(archive_dates) >= min_rows
                and recent_enough
            )
            if calendar_accepted:
                self.db.set_state(f"official_calendar_{game_key}", archive_dates)

            existing_dates = {d["draw_date"] for d in self.db.draws(game_key, era_only=False)}
            official_missing = set(archive_dates) - existing_dates
            target_years = set(wanted) | {int(x[:4]) for x in official_missing}
            if force_full or small_db:
                ds = all_official
            else:
                ds = [
                    d for d in all_official
                    if d["date"] in official_missing or int(d["date"][:4]) in target_years
                ]
            records.extend(ds)
            official_full_ok = bool(calendar_accepted)
            source_report["WCLC since inception"] = {
                "ok": True, "draws": len(ds), "archive_draws": len(all_official), "official": True,
                "calendar_accepted": calendar_accepted,
                "archive_first": archive_first, "archive_last": archive_last,
                "official_missing_before_merge": len(official_missing),
                "special_draw_dates": len(set(archive_dates) - schedule_to_cutoff),
                "schedule_coverage_through_archive_pct": round(100 * archive_schedule_coverage, 2),
            }
        except Exception as e:
            source_report["WCLC since inception"] = {"ok": False, "error": str(e), "official": True}

        # Re-evaluate gaps after an official calendar has been accepted. This is the
        # key step that turns genuine Super Draws into expected dates while leaving
        # foreign/date-shift artifacts unexpected and quarantined.
        health_after_calendar = self.history_health(game_key)
        recovery_dates = set(health_after_calendar.get("missing_dates", []))
        recovery_years = sorted({int(x[:4]) for x in recovery_dates})
        if not recovery_years:
            recovery_years = sorted(wanted)

        # 2-4) Third-party recovery sources are used only when gaps still need repair
        # or when WCLC full history could not be obtained. They remain non-authoritative.
        need_recovery_sources = bool(recovery_dates) or not official_full_ok
        if need_recovery_sources and recovery_years:
            try:
                gh = self.github_history.fetch_all(game_key)
                gh = [d for d in gh if int(d["date"][:4]) in set(recovery_years)]
                records.extend(gh)
                source_report["GitHub CSV"] = {
                    "ok": bool(gh), "draws": len(gh), "details": self.github_history.last_report,
                    **({} if gh else {"error": "No rows for requested years"}),
                }
            except Exception as e:
                source_report["GitHub CSV"] = {
                    "ok": False, "error": str(e),
                    "details": getattr(self.github_history, "last_report", {}),
                }

            try:
                ds = self.lottodb.fetch_years(game_key, recovery_years, progress=progress)
                records.extend(ds)
                source_report["LottoDatabase"] = {"ok": True, "draws": len(ds)}
            except Exception as e:
                source_report["LottoDatabase"] = {"ok": False, "error": str(e)}

            primary_dates = {d["date"] for d in records}
            expected_now, _ = self._canonical_expected_dates(game_key)
            existing = {d["draw_date"] for d in self.db.draws(game_key, era_only=False)}
            remaining = set(expected_now) - existing - primary_dates
            secondary_years = sorted({int(x[:4]) for x in remaining} | set(recovery_years[-2:]))
            try:
                ds = self.lottonet.fetch_years(game_key, secondary_years or recovery_years[-2:])
                records.extend(ds)
                source_report["Lotto.net"] = {"ok": True, "draws": len(ds)}
            except Exception as e:
                source_report["Lotto.net"] = {"ok": False, "error": str(e)}
        else:
            source_report["GitHub CSV"] = {"ok": True, "draws": 0, "skipped": True, "reason": "Official archive covers history; no gaps need third-party recovery"}
            source_report["LottoDatabase"] = {"ok": True, "draws": 0, "skipped": True, "reason": "No gaps"}
            source_report["Lotto.net"] = {"ok": True, "draws": 0, "skipped": True, "reason": "No gaps"}

        if game_key == "649" and not records and recovery_years:
            try:
                ds = self.archive649.fetch_all(min(recovery_years), max(recovery_years))
                records.extend(ds)
                source_report["National-Lottery"] = {"ok": True, "draws": len(ds)}
            except Exception as e:
                source_report["National-Lottery"] = {"ok": False, "error": str(e)}

        # Recent WCLC HTML remains a lightweight current-history cross-check and
        # covers the period after a lagging since-inception archive cutoff.
        current_year_needed = (
            not recovery_years or max(recovery_years) >= date.today().year - 1
            or (official_full_ok and all_official and all_official[-1]["date"][:4] != str(date.today().year))
        )
        if current_year_needed:
            try:
                ds = self.wclc_history.fetch_recent_draws(game_key)
                for d in ds:
                    d["verified"] = True
                records.extend(ds)
                source_report["WCLC recent history"] = {"ok": True, "draws": len(ds), "official": True}
            except Exception as e:
                source_report["WCLC recent history"] = {"ok": False, "error": str(e), "official": True}

        if records:
            merged = self._merge_history_records(game_key, records)
        else:
            merged = {
                "added": 0, "accepted": 0, "conflicts": 0, "consensus": 0,
                "conflict_dates": [],
                "unresolved_conflicts": len(self.db.get_state(f"history_unresolved_conflicts_{game_key}", []) or []),
            }

        health1 = self.audit_history(game_key)
        stamp = datetime.now().isoformat(timespec="seconds")
        self.db.set_state(f"history_repair_{game_key}", {
            "completed": stamp, "sources": source_report, "merge": merged, "health": health1,
        })
        msg = (
            f"History repair: +{merged['added']} draws; coverage {health1['coverage_pct']:.2f}%; "
            f"missing {health1['missing']}; unexpected {health1['unexpected']}; "
            f"raw integrity {health1['integrity_score']:.3f}%; "
            f"model integrity {health1.get('usable_integrity_score', 0):.3f}% "
            f"[{health1.get('model_data_status', '—')}]"
        )
        return {"ok": True, **merged, "health": health1, "sources": source_report, "message": msg}

    def initial_backfill(self, game_key: str, progress=None):
        return self.repair_history(game_key, progress=progress, force_full=True)

    # ---------- Latest draw / failover ----------
    @staticmethod
    def _same_draw(a, b):
        return bool(a and b and a.get("date") == b.get("date") and
                    tuple(sorted(a.get("numbers", []))) == tuple(sorted(b.get("numbers", []))) and
                    a.get("bonus") == b.get("bonus"))

    def update_latest(self, game_key: str):
        """BC-first official failover: WCLC -> OLG -> Loto-Québec -> history fallback."""
        source_status = {
            "WCLC": {"ok": False},
            "OLG": {"ok": False},
            "Loto-Québec": {"ok": False, "optional": True},
            "Atlantic Lottery": {"ok": False, "optional": True},
            "Historical fallback": {"ok": False},
        }
        official = []
        for name, provider in (("WCLC", self.wclc), ("OLG", self.olg), ("Loto-Québec", self.lq)):
            try:
                d = provider.latest(game_key)
                source_status[name] = {"ok": True, "date": d["date"]}
                official.append(d)
            except Exception as e:
                source_status[name] = {"ok": False, "error": str(e), "optional": name == "Loto-Québec"}
                logger.warning("Latest official source failed game=%s source=%s: %s", game_key, name, e)

        candidate = None
        if official:
            newest_date = max(x["date"] for x in official)
            same_date = [x for x in official if x["date"] == newest_date]
            # BC primary when it has the newest date; otherwise use newest available official result.
            candidate = next((x for x in same_date if x.get("source") == "WCLC official"), same_date[0])
        else:
            try:
                yr = date.today().year
                ds = self.lottodb.fetch_year(game_key, yr)
                candidate = ds[-1] if ds else None
                if candidate:
                    source_status["Historical fallback"] = {"ok": True, "date": candidate["date"]}
            except Exception as e:
                source_status["Historical fallback"] = {"ok": False, "error": str(e)}
                logger.warning("Latest historical fallback failed game=%s: %s", game_key, e)

        if not candidate:
            return {"updated": False, "verified": False, "status": "FAILED", "sources": source_status,
                    "message": "No provider returned a valid draw"}

        # Same-date official disagreement is a hard hold.
        same_date_official = [d for d in official if d.get("date") == candidate.get("date")]
        if any(not self._same_draw(d, candidate) for d in same_date_official):
            return {"updated": False, "verified": False, "status": "CONFLICT", "sources": source_status,
                    "message": "Official-source conflict detected; database left unchanged"}

        official_matches = sum(1 for d in same_date_official if self._same_draw(d, candidate))
        try:
            alc_ok = self.alc.verify(game_key, candidate)
            source_status["Atlantic Lottery"] = {"ok": bool(alc_ok), "match": bool(alc_ok), "optional": True}
        except Exception as e:
            source_status["Atlantic Lottery"] = {"ok": False, "error": str(e), "optional": True}
            logger.info("Optional Atlantic verification failed game=%s: %s", game_key, e)

        candidate_is_official = candidate.get("source") in ("WCLC official", "OLG official", "Loto-Québec official")
        verified = candidate_is_official or official_matches >= 1
        self._require_valid_record(game_key, candidate, "latest update")
        self.db.save_raw(game_key, candidate.get("source", "latest"), candidate.get("raw", candidate), "validated")
        src_label = candidate.get("source", "provider")
        if official_matches >= 2:
            src_label += f" + {official_matches} official confirmations"
        self.db.upsert_draw(
            game_key, candidate["date"], era_for(game_key, candidate["date"]), candidate["numbers"], candidate.get("bonus"),
            src_label, candidate.get("source_url"), verified=verified, raw=candidate.get("raw")
        )
        if game_key == "649" and (candidate.get("raw") or {}).get("gold_ball"):
            self.db.set_state("649_gold_ball", candidate["raw"]["gold_ball"])
        status = "SUCCESS" if candidate_is_official else ("FALLBACK SUCCESS" if verified else "UNVERIFIED FALLBACK")
        return {"updated": True, "verified": verified, "draw": candidate, "status": status,
                "sources": source_status, "official_matches": official_matches,
                "message": f"Latest draw updated via {candidate.get('source')}"}

    def update_jackpot(self, game_key: str):
        """Refresh latest official jackpot state; failure never blocks draw updates."""
        try:
            snap = self.jackpot.latest(game_key)
            self.db.save_jackpot_snapshot(game_key, snap)
            econ = jackpot_economics(game_key, snap)
            self.db.set_state(f"jackpot_economics_{game_key}", econ)
            refresh={"status":"CURRENT","ok":True,"checked_at":datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00","Z")}
            self.db.set_state(f"jackpot_refresh_{game_key}",refresh)
            return {"ok": True, "snapshot": snap, "economics": econ, "status": "SUCCESS"}
        except Exception as e:
            cached = self.db.latest_jackpot_snapshot(game_key)
            status="STALE" if cached else "FAILED"
            refresh={"status":status,"ok":False,"checked_at":datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00","Z"),"error":str(e)}
            self.db.set_state(f"jackpot_refresh_{game_key}",refresh)
            stale=dict(cached or {})
            if stale:
                stale["status"]="STALE"
                stale["refresh_error"]=str(e)
                stale["last_refresh_attempt"]=refresh["checked_at"]
            return {
                "ok": False, "status": status,
                "error": str(e), "snapshot": stale or None,
                "economics": jackpot_economics(game_key, stale) if stale else None,
            }

    def recover_gaps(self, game_key: str):
        # Target only years that have missing expected dates; current official update is handled separately.
        health = self.history_health(game_key)
        if health["missing"] == 0:
            return {"updated": False, "recovered": 0, "message": "No historical gaps detected", "ok": True}
        return self.repair_history(game_key, force_full=False)

    # ---------- Manual CSV fail-safe ----------
    def import_history_csv(self, game_key: str, path: str | Path) -> dict:
        path = Path(path)
        raw = path.read_bytes()
        decoded = None
        encoding_used = None
        for encoding in ("utf-8-sig", "gb18030", "cp1252"):
            try:
                decoded = raw.decode(encoding)
                encoding_used = encoding
                break
            except UnicodeDecodeError:
                continue
        if decoded is None:
            raise ProviderError("CSV encoding not recognized (tried UTF-8, GB18030 and CP1252)")

        rows = []
        skipped = 0
        reader = csv.DictReader(io.StringIO(decoded, newline=""))
        if not reader.fieldnames:
            raise ProviderError("CSV has no header")
        fields = {x.lower().strip(): x for x in reader.fieldnames if x is not None}
        date_col = fields.get("date") or fields.get("playdate") or fields.get("draw date") or fields.get("draw_date")
        if not date_col:
            raise ProviderError("CSV date column not recognized")
        cfg = GAMES[game_key]
        num_cols = []
        for i in range(1, cfg.pick + 1):
            col = fields.get(f"num{i}") or fields.get(f"no{i}") or fields.get(f"n{i}")
            if not col:
                raise ProviderError(f"CSV number column {i} not recognized")
            num_cols.append(col)
        bonus_col = fields.get("bonus") or fields.get("bonus number") or fields.get("bonus_number")
        if not bonus_col:
            raise ProviderError("CSV bonus column not recognized")

        for r in reader:
            raw_date = str(r.get(date_col, "")).strip()
            dt = None
            for fmt in ("%Y-%m-%d", "%B %d, %Y", "%b %d, %Y", "%m/%d/%Y", "%Y/%m/%d"):
                try:
                    dt = datetime.strptime(raw_date, fmt).date()
                    break
                except Exception:
                    pass
            if not dt:
                skipped += 1
                continue
            try:
                nums = [int(r[c]) for c in num_cols]
                bonus = int(r[bonus_col])
            except Exception:
                skipped += 1
                continue
            if not validate_draw_for_date(game_key, dt, nums, bonus):
                skipped += 1
                continue
            rows.append({"date": dt.isoformat(), "numbers": sorted(nums), "bonus": bonus,
                         "source": f"Manual CSV: {path.name}", "source_url": None,
                         "raw": {"import_file": str(path), "encoding": encoding_used}})
        if not rows:
            raise ProviderError(f"No valid lottery draws found in CSV ({skipped} row(s) skipped)")
        merged = self._merge_history_records(game_key, rows)
        health = self.audit_history(game_key)
        skipped_note = f"; {skipped} row(s) skipped" if skipped else ""
        return {"ok": True, **merged, "health": health, "skipped": skipped, "encoding": encoding_used,
                "message": (f"Imported {merged['added']} new draws; history completeness "
                            f"{health['percent']:.2f}%{skipped_note}; encoding {encoding_used}")}

    # ---------- Full update ----------
    def update_all(self, progress=None, force_history=False):
        started = datetime.now()
        report = {}
        total_added = 0
        latest_successes = 0
        for key in GAMES:
            report[key] = {}
            health_before = self.history_health(key)
            try:
                bootstrap_official = not bool(self.db.get_state(f"official_calendar_{key}", []) or [])
                should_repair = force_history or self.db.count_draws(key) <= 50
                # Bootstrap the official since-inception calendar once for each game so
                # missing/unexpected dates are judged against WCLC rather than assumptions.
                if not should_repair and not (self.db.get_state(f"official_calendar_{key}", []) or []):
                    att = self.db.get_state(f"official_archive_attempt_{key}", {}) or {}
                    ats = att.get("at")
                    if not ats:
                        should_repair = True
                    else:
                        try:
                            should_repair = datetime.now() - datetime.fromisoformat(ats) > timedelta(hours=24)
                        except Exception:
                            should_repair = True
                if not should_repair and health_before["status"] != "COMPLETE":
                    last = self.db.get_state(f"history_repair_{key}", {}) or {}
                    ts = last.get("completed")
                    if not ts:
                        should_repair = True
                    else:
                        try:
                            should_repair = datetime.now() - datetime.fromisoformat(ts) > timedelta(hours=24)
                        except Exception:
                            should_repair = True
                if should_repair:
                    hist = self.repair_history(key, progress=progress, force_full=(force_history or self.db.count_draws(key) <= 50 or bootstrap_official))
                    report[key]["history"] = hist
                    total_added += int(hist.get("added", 0))
                else:
                    report[key]["history"] = {"ok": True, "message": "History repair not due", "health": health_before}
            except Exception as e:
                report[key]["history_error"] = str(e)

            try:
                latest = self.update_latest(key)
                report[key]["latest"] = latest
                if latest.get("updated"):
                    latest_successes += 1
            except Exception as e:
                report[key]["latest_error"] = str(e)
            try:
                report[key]["jackpot"] = self.update_jackpot(key)
            except Exception as e:
                report[key]["jackpot"] = {"ok": False, "status": "FAILED", "error": str(e)}
            report[key]["history_health"] = self.audit_history(key)

        finished = datetime.now()
        if latest_successes == len(GAMES):
            overall = "SUCCESS"
        elif latest_successes:
            overall = "PARTIAL"
        else:
            overall = "FAILED"
        healths = [report[k]["history_health"] for k in GAMES]
        if all(h["status"] == "COMPLETE" for h in healths):
            history_status = "COMPLETE"
        elif any(h["status"] == "INCOMPLETE" for h in healths):
            history_status = "INCOMPLETE"
        else:
            history_status = "WARNING"
        # Redundancy is healthy when every game's selected current date had at least two official sources available.
        redundant = True
        for k in GAMES:
            src = ((report[k].get("latest") or {}).get("sources") or {})
            official_ok = sum(1 for n in ("WCLC", "OLG", "Loto-Québec") if (src.get(n) or {}).get("ok"))
            if official_ok < 2:
                redundant = False
        summary = {
            "status": overall,
            "latest_status": overall,
            "history_status": history_status,
            "redundancy_status": "HEALTHY" if redundant else "DEGRADED",
            "started_at": started.isoformat(timespec="seconds"),
            "finished_at": finished.isoformat(timespec="seconds"),
            "total_added": total_added,
            "games": report,
        }
        self.db.set_state("last_update", summary["finished_at"])
        self.db.set_state("last_update_report", summary)
        return summary

    def needs_poll(self, game_key: str) -> bool:
        now = pacific_now()
        cfg = GAMES[game_key]
        d = now.date()
        if d.weekday() in cfg.draw_weekdays and now.hour < RESULT_GRACE_HOUR:
            d = d - timedelta(days=1)
        while d.weekday() not in cfg.draw_weekdays:
            d -= timedelta(days=1)
        latest = self.db.latest_draw(game_key)
        if not latest:
            return True
        return latest["draw_date"] < d.isoformat()
