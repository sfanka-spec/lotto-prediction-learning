import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .config import GAMES, GAME_REGIMES

SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS raw_ingest (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    game TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    source TEXT NOT NULL,
    payload_json TEXT,
    parse_status TEXT NOT NULL,
    error TEXT
);

CREATE TABLE IF NOT EXISTS draws (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    game TEXT NOT NULL,
    draw_date TEXT NOT NULL,
    era TEXT NOT NULL,
    numbers_json TEXT NOT NULL,
    bonus INTEGER,
    source TEXT NOT NULL,
    source_url TEXT,
    retrieved_at TEXT NOT NULL,
    verified INTEGER NOT NULL DEFAULT 0,
    raw_json TEXT,
    UNIQUE(game, draw_date)
);
CREATE INDEX IF NOT EXISTS idx_draws_game_date ON draws(game, draw_date);

CREATE TABLE IF NOT EXISTS model_weights (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    game TEXT NOT NULL,
    model_role TEXT NOT NULL,
    version TEXT NOT NULL,
    weights_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    reason TEXT,
    active INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS freezes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    game TEXT NOT NULL,
    target_draw_date TEXT NOT NULL,
    model_version TEXT NOT NULL,
    created_at TEXT NOT NULL,
    data_cutoff TEXT,
    predictions_json TEXT NOT NULL,
    bonus_rank_json TEXT,
    factor_context_json TEXT,
    judged INTEGER NOT NULL DEFAULT 0,
    UNIQUE(game, target_draw_date, model_version)
);

CREATE TABLE IF NOT EXISTS judgments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    freeze_id INTEGER NOT NULL,
    game TEXT NOT NULL,
    draw_date TEXT NOT NULL,
    best_hit INTEGER NOT NULL,
    avg_hit REAL NOT NULL,
    median_hit REAL NOT NULL,
    bonus_rank_hit INTEGER,
    random_baseline REAL,
    details_json TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(freeze_id) REFERENCES freezes(id)
);

CREATE TABLE IF NOT EXISTS freeze_ledger (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    freeze_id INTEGER NOT NULL UNIQUE,
    previous_hash TEXT,
    record_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(freeze_id) REFERENCES freezes(id)
);
CREATE INDEX IF NOT EXISTS idx_freeze_ledger_hash ON freeze_ledger(record_hash);

CREATE TABLE IF NOT EXISTS learning_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    game TEXT NOT NULL,
    created_at TEXT NOT NULL,
    model_role TEXT NOT NULL,
    old_weights_json TEXT NOT NULL,
    new_weights_json TEXT NOT NULL,
    signal_json TEXT,
    reason TEXT
);

CREATE TABLE IF NOT EXISTS champion_learning (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    freeze_id INTEGER NOT NULL UNIQUE,
    game TEXT NOT NULL,
    draw_date TEXT NOT NULL,
    model_version TEXT NOT NULL,
    record_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(freeze_id) REFERENCES freezes(id)
);
CREATE INDEX IF NOT EXISTS idx_champion_learning_game_date ON champion_learning(game, draw_date);


CREATE TABLE IF NOT EXISTS jackpot_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    game TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    source TEXT NOT NULL,
    snapshot_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_jackpot_snapshots_game_time ON jackpot_snapshots(game, observed_at);

CREATE TABLE IF NOT EXISTS portfolio_decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    game TEXT NOT NULL,
    target_draw_date TEXT NOT NULL,
    model_version TEXT NOT NULL,
    created_at TEXT NOT NULL,
    decision_json TEXT NOT NULL,
    judged INTEGER NOT NULL DEFAULT 0,
    UNIQUE(game, target_draw_date, model_version)
);
CREATE INDEX IF NOT EXISTS idx_portfolio_decisions_game_date ON portfolio_decisions(game, target_draw_date);

CREATE TABLE IF NOT EXISTS portfolio_learning (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    decision_id INTEGER NOT NULL UNIQUE,
    game TEXT NOT NULL,
    draw_date TEXT NOT NULL,
    model_version TEXT NOT NULL,
    judgment_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(decision_id) REFERENCES portfolio_decisions(id)
);
CREATE INDEX IF NOT EXISTS idx_portfolio_learning_game_date ON portfolio_learning(game, draw_date);

CREATE TABLE IF NOT EXISTS app_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""

class Database:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as con:
            con.executescript(SCHEMA)
            # Era labels are migrated from the centralized registry so a future rule
            # change has one source of truth.
            for game, regimes in GAME_REGIMES.items():
                for reg in regimes:
                    params = [reg["name"], game, reg["start"]]
                    sql = "UPDATE draws SET era=? WHERE game=? AND draw_date>=?"
                    if reg.get("end"):
                        sql += " AND draw_date<=?"
                        params.append(reg["end"])
                    con.execute(sql, params)
            # Older builds could create duplicate judgments during overlapping update
            # threads. Keep the newest row, then enforce one judgment per freeze.
            con.execute(
                "DELETE FROM judgments WHERE id NOT IN (SELECT MAX(id) FROM judgments GROUP BY freeze_id)"
            )
            con.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_judgments_freeze ON judgments(freeze_id)")
            # Prediction payload/provenance is immutable after a freeze. The judged bit
            # remains mutable because it is post-draw bookkeeping, not prediction data.
            con.executescript("""
                CREATE TRIGGER IF NOT EXISTS trg_freezes_immutable
                BEFORE UPDATE OF game,target_draw_date,model_version,created_at,data_cutoff,
                                 predictions_json,bonus_rank_json,factor_context_json ON freezes
                BEGIN
                    SELECT RAISE(ABORT, 'frozen prediction fields are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS trg_freeze_ledger_immutable_update
                BEFORE UPDATE ON freeze_ledger
                BEGIN
                    SELECT RAISE(ABORT, 'freeze ledger is append-only');
                END;
                CREATE TRIGGER IF NOT EXISTS trg_freeze_ledger_immutable_delete
                BEFORE DELETE ON freeze_ledger
                BEGIN
                    SELECT RAISE(ABORT, 'freeze ledger is append-only');
                END;
            """)
            self._backfill_freeze_ledger(con)

    @contextmanager
    def connect(self):
        con = sqlite3.connect(self.path, timeout=30)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys=ON")
        try:
            yield con
            con.commit()
        finally:
            con.close()

    @staticmethod
    def _freeze_record_hash(row, previous_hash=""):
        payload = {
            "id": int(row["id"]),
            "game": row["game"],
            "target_draw_date": row["target_draw_date"],
            "model_version": row["model_version"],
            "created_at": row["created_at"],
            "data_cutoff": row["data_cutoff"],
            "predictions_json": row["predictions_json"],
            "bonus_rank_json": row["bonus_rank_json"],
            "factor_context_json": row["factor_context_json"],
            "previous_hash": previous_hash or "",
        }
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    def _append_freeze_ledger(self, con, freeze_id):
        exists = con.execute("SELECT 1 FROM freeze_ledger WHERE freeze_id=?", (int(freeze_id),)).fetchone()
        if exists:
            return
        row = con.execute("SELECT * FROM freezes WHERE id=?", (int(freeze_id),)).fetchone()
        if not row:
            return
        prev = con.execute("SELECT record_hash FROM freeze_ledger ORDER BY id DESC LIMIT 1").fetchone()
        previous_hash = str(prev[0]) if prev else ""
        record_hash = self._freeze_record_hash(row, previous_hash)
        con.execute(
            "INSERT INTO freeze_ledger(freeze_id,previous_hash,record_hash,created_at) VALUES(?,?,?,?)",
            (int(freeze_id), previous_hash, record_hash, datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00","Z")),
        )

    def _backfill_freeze_ledger(self, con):
        rows = con.execute(
            "SELECT f.id FROM freezes f LEFT JOIN freeze_ledger l ON l.freeze_id=f.id "
            "WHERE l.freeze_id IS NULL ORDER BY f.id"
        ).fetchall()
        for row in rows:
            self._append_freeze_ledger(con, row[0])

    def verify_freeze_ledger(self):
        with self.connect() as con:
            rows = con.execute(
                """SELECT l.freeze_id AS ledger_freeze_id, l.previous_hash, l.record_hash,
                          f.id AS id, f.game, f.target_draw_date, f.model_version, f.created_at,
                          f.data_cutoff, f.predictions_json, f.bonus_rank_json, f.factor_context_json
                   FROM freeze_ledger l JOIN freezes f ON f.id=l.freeze_id ORDER BY l.id"""
            ).fetchall()
        previous_hash = ""
        for row in rows:
            if str(row["previous_hash"] or "") != previous_hash:
                return {"ok": False, "freeze_id": int(row["ledger_freeze_id"]), "reason": "chain_link_mismatch"}
            expected = self._freeze_record_hash(row, previous_hash)
            if expected != row["record_hash"]:
                return {"ok": False, "freeze_id": int(row["ledger_freeze_id"]), "reason": "record_hash_mismatch"}
            previous_hash = str(row["record_hash"])
        return {"ok": True, "count": len(rows), "head": previous_hash or None,
                "scope": "local tamper-evident chain; external anchoring is required for adversarial protection"}

    def save_raw(self, game, source, payload, parse_status="received", error=None):
        now = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00","Z")
        with self.connect() as con:
            con.execute(
                "INSERT INTO raw_ingest(game,observed_at,source,payload_json,parse_status,error) VALUES(?,?,?,?,?,?)",
                (game, now, source, json.dumps(payload) if payload is not None else None, parse_status, error)
            )

    def upsert_draw(self, game, draw_date, era, numbers, bonus, source, source_url=None,
                    verified=False, raw=None):
        payload = json.dumps(sorted(map(int, numbers)))
        now = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00","Z")
        with self.connect() as con:
            con.execute(
                """
                INSERT INTO draws(game, draw_date, era, numbers_json, bonus, source, source_url,
                                  retrieved_at, verified, raw_json)
                VALUES(?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(game, draw_date) DO UPDATE SET
                    era=CASE WHEN draws.verified=1 AND excluded.verified=0 THEN draws.era ELSE excluded.era END,
                    numbers_json=CASE WHEN draws.verified=1 AND excluded.verified=0 THEN draws.numbers_json ELSE excluded.numbers_json END,
                    bonus=CASE WHEN draws.verified=1 AND excluded.verified=0 THEN draws.bonus ELSE excluded.bonus END,
                    source=CASE WHEN draws.verified=1 AND excluded.verified=0 THEN draws.source ELSE excluded.source END,
                    source_url=CASE WHEN draws.verified=1 AND excluded.verified=0 THEN draws.source_url ELSE excluded.source_url END,
                    retrieved_at=CASE WHEN draws.verified=1 AND excluded.verified=0 THEN draws.retrieved_at ELSE excluded.retrieved_at END,
                    verified=MAX(draws.verified, excluded.verified),
                    raw_json=CASE WHEN draws.verified=1 AND excluded.verified=0 THEN draws.raw_json ELSE COALESCE(excluded.raw_json, draws.raw_json) END
                """,
                (game, str(draw_date), era, payload, bonus, source, source_url, now,
                 1 if verified else 0, json.dumps(raw) if raw is not None else None),
            )

    def draws(self, game, era_only=True, model_ready=False):
        q = "SELECT * FROM draws WHERE game=?"
        params = [game]
        if era_only:
            q += " AND draw_date >= ?"
            params.append(GAMES[game].era_start.isoformat())
        q += " ORDER BY draw_date ASC"
        with self.connect() as con:
            rows = con.execute(q, params).fetchall()
        excluded = set(self.get_state(f"model_exclusions_{game}", []) or []) if model_ready else set()
        out = []
        for r in rows:
            if r["draw_date"] in excluded:
                continue
            try:
                raw = json.loads(r["raw_json"]) if r["raw_json"] else None
            except Exception:
                raw = None
            out.append({
                "id": r["id"],
                "game": r["game"],
                "draw_date": r["draw_date"],
                "era": r["era"],
                "numbers": json.loads(r["numbers_json"]),
                "bonus": r["bonus"],
                "source": r["source"],
                "source_url": r["source_url"],
                "verified": bool(r["verified"]),
                "raw": raw,
            })
        return out

    def latest_draw(self, game):
        with self.connect() as con:
            r = con.execute("SELECT * FROM draws WHERE game=? ORDER BY draw_date DESC LIMIT 1", (game,)).fetchone()
        if not r:
            return None
        return {
            "draw_date": r["draw_date"], "numbers": json.loads(r["numbers_json"]),
            "bonus": r["bonus"], "source": r["source"], "verified": bool(r["verified"])
        }

    def count_draws(self, game):
        with self.connect() as con:
            return con.execute("SELECT COUNT(*) FROM draws WHERE game=?", (game,)).fetchone()[0]

    def draw_by_date(self, game, draw_date):
        with self.connect() as con:
            r = con.execute("SELECT * FROM draws WHERE game=? AND draw_date=?", (game, str(draw_date))).fetchone()
        if not r:
            return None
        return {
            "id": r["id"], "game": r["game"], "draw_date": r["draw_date"], "era": r["era"],
            "numbers": json.loads(r["numbers_json"]), "bonus": r["bonus"], "source": r["source"],
            "verified": bool(r["verified"]), "source_url": r["source_url"]
        }

    def count_draws_era(self, game, era):
        with self.connect() as con:
            return con.execute("SELECT COUNT(*) FROM draws WHERE game=? AND era=?", (game, era)).fetchone()[0]

    def set_state(self, key, value):
        now = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00","Z")
        with self.connect() as con:
            con.execute(
                "INSERT INTO app_state(key,value,updated_at) VALUES(?,?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                (key, json.dumps(value), now),
            )

    def get_state(self, key, default=None):
        with self.connect() as con:
            r = con.execute("SELECT value FROM app_state WHERE key=?", (key,)).fetchone()
        return json.loads(r[0]) if r else default

    def active_weights(self, game, role, defaults):
        with self.connect() as con:
            r = con.execute(
                "SELECT weights_json, version FROM model_weights WHERE game=? AND model_role=? AND active=1 "
                "ORDER BY id DESC LIMIT 1", (game, role)
            ).fetchone()
        if r:
            return json.loads(r["weights_json"]), r["version"]
        initial_versions = {
            "production": "P1.0",
            "challenger": "C1.0",
            "bonus_production": "BP1.0",
            "bonus_challenger": "BC1.0",
            "champion_shadow": "CS1.0",
        }
        version = initial_versions.get(role, "M1.0")
        self.save_weights(game, role, version, defaults, "Initial defaults", active=True)
        return dict(defaults), version

    def save_weights(self, game, role, version, weights, reason, active=False):
        now = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00","Z")
        with self.connect() as con:
            if active:
                con.execute("UPDATE model_weights SET active=0 WHERE game=? AND model_role=?", (game, role))
            con.execute(
                "INSERT INTO model_weights(game,model_role,version,weights_json,created_at,reason,active) VALUES(?,?,?,?,?,?,?)",
                (game, role, version, json.dumps(weights), now, reason, 1 if active else 0)
            )

    def add_learning_log(self, game, role, old_w, new_w, signal, reason):
        now = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00","Z")
        with self.connect() as con:
            con.execute(
                "INSERT INTO learning_log(game,created_at,model_role,old_weights_json,new_weights_json,signal_json,reason) VALUES(?,?,?,?,?,?,?)",
                (game, now, role, json.dumps(old_w), json.dumps(new_w), json.dumps(signal), reason)
            )

    def latest_learning(self, game, role=None):
        with self.connect() as con:
            if role is None:
                r = con.execute(
                    "SELECT * FROM learning_log WHERE game=? ORDER BY id DESC LIMIT 1", (game,)
                ).fetchone()
            else:
                r = con.execute(
                    "SELECT * FROM learning_log WHERE game=? AND model_role=? ORDER BY id DESC LIMIT 1",
                    (game, str(role))
                ).fetchone()
        return dict(r) if r else None

    def _save_freeze_in_connection(self, con, game, target_date, model_version, data_cutoff, predictions, bonus_rank, factor_context):
        now = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00","Z")
        con.execute(
            """INSERT OR IGNORE INTO freezes(game,target_draw_date,model_version,created_at,data_cutoff,
               predictions_json,bonus_rank_json,factor_context_json) VALUES(?,?,?,?,?,?,?,?)""",
            (game, str(target_date), model_version, now, data_cutoff, json.dumps(predictions),
             json.dumps(bonus_rank), json.dumps(factor_context))
        )
        row = con.execute(
            "SELECT id FROM freezes WHERE game=? AND target_draw_date=? AND model_version=?",
            (game, str(target_date), model_version),
        ).fetchone()
        if row:
            self._append_freeze_ledger(con, int(row[0]))
            return int(row[0])
        return None

    def save_freeze(self, game, target_date, model_version, data_cutoff, predictions, bonus_rank, factor_context):
        with self.connect() as con:
            return self._save_freeze_in_connection(
                con, game, target_date, model_version, data_cutoff, predictions, bonus_rank, factor_context
            )

    def save_freeze_batch(self, rows):
        """Atomically save a logical group of prediction freezes.

        Each row is a dict accepted by ``save_freeze``. Any failure rolls the whole
        batch back, preventing a half-written Production/Challenger/shadow group.
        """
        ids = []
        with self.connect() as con:
            con.execute("BEGIN IMMEDIATE")
            for row in rows or []:
                ids.append(self._save_freeze_in_connection(
                    con, row["game"], row["target_date"], row["model_version"], row.get("data_cutoff"),
                    row.get("predictions") or [], row.get("bonus_rank") or [], row.get("factor_context") or {}
                ))
        return ids

    def freeze_by_id(self, freeze_id):
        with self.connect() as con:
            row = con.execute("SELECT * FROM freezes WHERE id=?", (int(freeze_id),)).fetchone()
        return dict(row) if row else None

    def official_freeze(self, game, target_date):
        """Return the frozen Production prediction for a draw, if one exists."""
        with self.connect() as con:
            r = con.execute(
                """SELECT * FROM freezes
                   WHERE game=? AND target_draw_date=? AND model_version LIKE 'P%'
                   ORDER BY id DESC LIMIT 1""",
                (game, str(target_date))
            ).fetchone()
        return dict(r) if r else None

    def challenger_freeze(self, game, target_date):
        with self.connect() as con:
            r = con.execute(
                """SELECT * FROM freezes
                   WHERE game=? AND target_draw_date=? AND model_version LIKE 'C%'
                   ORDER BY id DESC LIMIT 1""",
                (game, str(target_date))
            ).fetchone()
        return dict(r) if r else None

    def random_freeze(self, game, target_date):
        with self.connect() as con:
            r = con.execute(
                """SELECT * FROM freezes
                   WHERE game=? AND target_draw_date=? AND model_version LIKE 'RND%'
                   ORDER BY id DESC LIMIT 1""",
                (game, str(target_date))
            ).fetchone()
        return dict(r) if r else None

    def research_freeze(self, game, target_date):
        with self.connect() as con:
            r = con.execute(
                """SELECT * FROM freezes
                   WHERE game=? AND target_draw_date=? AND model_version LIKE 'RES%'
                   ORDER BY id DESC LIMIT 1""",
                (game, str(target_date))
            ).fetchone()
        return dict(r) if r else None


    def freeze_by_prefix(self, game, target_date, prefix):
        with self.connect() as con:
            r = con.execute(
                """SELECT * FROM freezes
                   WHERE game=? AND target_draw_date=? AND model_version LIKE ?
                   ORDER BY id DESC LIMIT 1""",
                (game, str(target_date), str(prefix) + '%')
            ).fetchone()
        return dict(r) if r else None

    def strategy_freezes(self, game, target_date, prefixes):
        out = {}
        for label, prefix in (prefixes or {}).items():
            out[label] = self.freeze_by_prefix(game, target_date, prefix)
        return out

    def unjudged_freezes_for_date(self, game, draw_date):
        with self.connect() as con:
            return con.execute(
                "SELECT * FROM freezes WHERE game=? AND target_draw_date=? AND judged=0 ORDER BY id",
                (game, str(draw_date))
            ).fetchall()

    def save_judgment(self, freeze_id, game, draw_date, best_hit, avg_hit, median_hit,
                      bonus_rank_hit, random_baseline, details):
        now = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00","Z")
        with self.connect() as con:
            con.execute(
                """INSERT INTO judgments(freeze_id,game,draw_date,best_hit,avg_hit,median_hit,
                   bonus_rank_hit,random_baseline,details_json,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(freeze_id) DO UPDATE SET
                     game=excluded.game, draw_date=excluded.draw_date, best_hit=excluded.best_hit,
                     avg_hit=excluded.avg_hit, median_hit=excluded.median_hit,
                     bonus_rank_hit=excluded.bonus_rank_hit, random_baseline=excluded.random_baseline,
                     details_json=excluded.details_json, created_at=excluded.created_at""",
                (freeze_id, game, str(draw_date), best_hit, avg_hit, median_hit, bonus_rank_hit,
                 random_baseline, json.dumps(details), now)
            )
            con.execute("UPDATE freezes SET judged=1 WHERE id=?", (freeze_id,))

    def judgment_summary(self, game, limit=100):
        with self.connect() as con:
            rows = con.execute(
                "SELECT * FROM judgments WHERE game=? ORDER BY id DESC LIMIT ?", (game, limit)
            ).fetchall()
        if not rows:
            return None
        avg = sum(r["avg_hit"] for r in rows) / len(rows)
        best = sum(r["best_hit"] for r in rows) / len(rows)
        rb = [r["random_baseline"] for r in rows if r["random_baseline"] is not None]
        return {
            "n": len(rows),
            "mean_avg_hit": avg,
            "mean_best_hit": best,
            "random_baseline": sum(rb)/len(rb) if rb else None,
        }

    def paired_model_performance(self, game, limit=200):
        """Return paired Production/Challenger average-hit records by draw date."""
        with self.connect() as con:
            rows = con.execute(
                """
                SELECT j.draw_date, j.avg_hit, j.random_baseline, f.model_version, f.factor_context_json
                FROM judgments j JOIN freezes f ON j.freeze_id=f.id
                WHERE j.game=? ORDER BY j.draw_date DESC, j.id DESC
                """, (game,)
            ).fetchall()
        by = {}
        for r in rows:
            version = str(r["model_version"])
            try:
                ctx = json.loads(r["factor_context_json"] or "{}")
            except Exception:
                ctx = {}
            if version.startswith("P"):
                role = "production"
                eligible = bool(ctx.get("search_budget_equal_to_challenger") and ctx.get("candidate_universe_equal_to_challenger"))
            elif version.startswith("C"):
                role = "challenger"
                eligible = bool(ctx.get("search_budget_equal_to_production") and ctx.get("candidate_universe_equal_to_production"))
            else:
                # Random/Research shadow freezes must never be misclassified as Challenger.
                continue
            # Older P/C freezes used unequal search depth. They remain in the immutable
            # audit trail but cannot contribute to V1.6.1 promotion evidence.
            if not eligible:
                continue
            d = r["draw_date"]
            by.setdefault(d, {})[role] = float(r["avg_hit"])
            by[d]["random"] = r["random_baseline"]
        pairs = []
        for d in sorted(by, reverse=True):
            rec = by[d]
            if "production" in rec and "challenger" in rec:
                pairs.append((d, rec["production"], rec["challenger"], rec.get("random")))
            if len(pairs) >= limit:
                break
        return list(reversed(pairs))

    def paired_shadow_performance(self, game, shadow_prefix, limit=200):
        """Return paired Production vs a selected shadow role (RND/RES)."""
        with self.connect() as con:
            rows = con.execute(
                """
                SELECT j.draw_date, j.avg_hit, j.best_hit, f.model_version
                FROM judgments j JOIN freezes f ON j.freeze_id=f.id
                WHERE j.game=? ORDER BY j.draw_date DESC, j.id DESC
                """, (game,)
            ).fetchall()
        by = {}
        prefix = str(shadow_prefix)
        for r in rows:
            version = str(r["model_version"])
            role = "production" if version.startswith("P") else ("shadow" if version.startswith(prefix) else None)
            if role is None:
                continue
            by.setdefault(r["draw_date"], {})[role] = (float(r["avg_hit"]), float(r["best_hit"]))
        out = []
        for d in sorted(by, reverse=True):
            rec = by[d]
            if "production" in rec and "shadow" in rec:
                out.append((d, rec["production"][0], rec["shadow"][0], rec["production"][1], rec["shadow"][1]))
            if len(out) >= limit:
                break
        return list(reversed(out))

    def model_role_summary(self, game, prefix, limit=200):
        with self.connect() as con:
            rows = con.execute(
                """SELECT j.avg_hit, j.best_hit FROM judgments j
                   JOIN freezes f ON j.freeze_id=f.id
                   WHERE j.game=? AND f.model_version LIKE ?
                   ORDER BY j.draw_date DESC, j.id DESC LIMIT ?""",
                (game, str(prefix) + '%', limit)
            ).fetchall()
        if not rows:
            return None
        return {
            "n": len(rows),
            "avg_hit": sum(float(r["avg_hit"]) for r in rows) / len(rows),
            "best_hit": sum(float(r["best_hit"]) for r in rows) / len(rows),
        }

    def freezes_for_date(self, game, draw_date):
        with self.connect() as con:
            rows = con.execute(
                "SELECT * FROM freezes WHERE game=? AND target_draw_date=? ORDER BY id",
                (game, str(draw_date))
            ).fetchall()
        return [dict(r) for r in rows]

    def save_champion_learning(self, freeze_id, game, draw_date, model_version, record):
        """Persist post-draw Champion diagnostics without mutating the freeze.

        Returns True only for the first insertion of this freeze. Existing rows are
        refreshed in place so future diagnostic-schema enrichments are backfillable
        without creating duplicate learning samples.
        """
        now = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00","Z")
        payload = json.dumps(record)
        with self.connect() as con:
            existed = con.execute(
                "SELECT 1 FROM champion_learning WHERE freeze_id=?", (int(freeze_id),)
            ).fetchone() is not None
            con.execute(
                """INSERT INTO champion_learning(freeze_id,game,draw_date,model_version,record_json,created_at)
                   VALUES(?,?,?,?,?,?)
                   ON CONFLICT(freeze_id) DO UPDATE SET
                     game=excluded.game, draw_date=excluded.draw_date,
                     model_version=excluded.model_version, record_json=excluded.record_json""",
                (int(freeze_id), game, str(draw_date), str(model_version), payload, now)
            )
        return not existed

    def champion_learning_records(self, game, prefix="P", limit=200):
        with self.connect() as con:
            rows = con.execute(
                """SELECT * FROM champion_learning
                   WHERE game=? AND model_version LIKE ?
                   ORDER BY draw_date DESC, id DESC LIMIT ?""",
                (game, str(prefix) + '%', int(limit))
            ).fetchall()
        out=[]
        for r in rows:
            d=dict(r)
            try:
                d["record"] = json.loads(d.get("record_json") or "{}")
            except Exception:
                d["record"] = {}
            out.append(d)
        return out

    def champion_learning_for_date(self, game, draw_date, prefix="P"):
        with self.connect() as con:
            r = con.execute(
                """SELECT * FROM champion_learning
                   WHERE game=? AND draw_date=? AND model_version LIKE ?
                   ORDER BY id DESC LIMIT 1""",
                (game, str(draw_date), str(prefix) + '%')
            ).fetchone()
        if not r:
            return None
        d=dict(r)
        try:
            d["record"] = json.loads(d.get("record_json") or "{}")
        except Exception:
            d["record"] = {}
        return d


    def champion_learning_all_for_date(self, game, draw_date):
        with self.connect() as con:
            rows = con.execute(
                """SELECT * FROM champion_learning
                   WHERE game=? AND draw_date=? ORDER BY id DESC""",
                (game, str(draw_date))
            ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            try:
                d["record"] = json.loads(d.get("record_json") or "{}")
            except Exception:
                d["record"] = {}
            out.append(d)
        return out

    def recent_freezes(self, game, limit=10):
        with self.connect() as con:
            rows = con.execute(
                "SELECT * FROM freezes WHERE game=? ORDER BY target_draw_date DESC, id DESC LIMIT ?",
                (game, limit)
            ).fetchall()
        return [dict(r) for r in rows]

    def recent_judgments(self, game, limit=10):
        with self.connect() as con:
            rows = con.execute(
                """SELECT j.*, f.model_version FROM judgments j JOIN freezes f ON j.freeze_id=f.id
                   WHERE j.game=? ORDER BY j.draw_date DESC, j.id DESC LIMIT ?""",
                (game,limit)
            ).fetchall()
        return [dict(r) for r in rows]


    # ---------- V1.5 Jackpot / Portfolio decision memory ----------
    def save_jackpot_snapshot(self, game, snapshot):
        now = str((snapshot or {}).get("observed_at") or datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00","Z"))
        source = str((snapshot or {}).get("source") or "unknown")
        current = dict(snapshot or {})
        # History should record state changes, not every 30-minute refresh. V1.5.0
        # compared the full JSON including observed_at/raw_excerpt, so identical jackpot
        # values were inserted repeatedly and could clutter later history analysis.
        fingerprint_keys = (
            "jackpot_million", "classic_jackpot_million", "gold_ball_jackpot_million",
            "gold_balls_remaining", "maxplus_100k_count", "maxmillions_count",
            "jackpot_cap_million", "source_url",
        )
        def fp(obj):
            return json.dumps({k: (obj or {}).get(k) for k in fingerprint_keys}, sort_keys=True, separators=(",", ":"))
        inserted = True
        with self.connect() as con:
            last = con.execute("SELECT snapshot_json FROM jackpot_snapshots WHERE game=? ORDER BY id DESC LIMIT 1", (game,)).fetchone()
            if last:
                try:
                    previous = json.loads(last[0] or "{}")
                except Exception:
                    previous = {}
                if fp(previous) == fp(current):
                    inserted = False
            if inserted:
                con.execute("INSERT INTO jackpot_snapshots(game,observed_at,source,snapshot_json) VALUES(?,?,?,?)",
                            (game, now, source, json.dumps(current, sort_keys=True)))
        # Latest state/timestamp is still refreshed even when economic state is unchanged.
        self.set_state(f"jackpot_latest_{game}", current)
        return inserted

    def latest_jackpot_snapshot(self, game):
        state = self.get_state(f"jackpot_latest_{game}", None)
        if state:
            return state
        with self.connect() as con:
            r = con.execute("SELECT snapshot_json FROM jackpot_snapshots WHERE game=? ORDER BY id DESC LIMIT 1", (game,)).fetchone()
        if not r:
            return None
        try:
            return json.loads(r[0])
        except Exception:
            return None

    def jackpot_history(self, game, limit=200):
        with self.connect() as con:
            rows = con.execute("SELECT * FROM jackpot_snapshots WHERE game=? ORDER BY id DESC LIMIT ?", (game, int(limit))).fetchall()
        out=[]
        for r in rows:
            d=dict(r)
            try: d["snapshot"] = json.loads(d.get("snapshot_json") or "{}")
            except Exception: d["snapshot"] = {}
            out.append(d)
        return list(reversed(out))

    def save_portfolio_decision(self, game, target_draw_date, model_version, decision):
        now = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00","Z")
        payload = json.dumps(decision or {})
        with self.connect() as con:
            con.execute(
                """INSERT OR IGNORE INTO portfolio_decisions(game,target_draw_date,model_version,created_at,decision_json)
                   VALUES(?,?,?,?,?)""",
                (game, str(target_draw_date), str(model_version), now, payload)
            )
            r=con.execute("SELECT * FROM portfolio_decisions WHERE game=? AND target_draw_date=? AND model_version=?",
                          (game,str(target_draw_date),str(model_version))).fetchone()
        return dict(r) if r else None

    def portfolio_decision(self, game, target_draw_date, model_version_prefix="BUD"):
        with self.connect() as con:
            r=con.execute(
                """SELECT * FROM portfolio_decisions WHERE game=? AND target_draw_date=? AND model_version LIKE ?
                   ORDER BY id DESC LIMIT 1""",
                (game,str(target_draw_date),str(model_version_prefix)+"%")
            ).fetchone()
        if not r: return None
        d=dict(r)
        try: d["decision"] = json.loads(d.get("decision_json") or "{}")
        except Exception: d["decision"] = {}
        return d

    def unjudged_portfolio_decisions_for_date(self, game, draw_date):
        with self.connect() as con:
            rows=con.execute("SELECT * FROM portfolio_decisions WHERE game=? AND target_draw_date=? AND judged=0 ORDER BY id",
                             (game,str(draw_date))).fetchall()
        return [dict(r) for r in rows]

    def save_portfolio_judgment(self, decision_id, game, draw_date, model_version, judgment):
        now=datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00","Z")
        with self.connect() as con:
            con.execute(
                """INSERT INTO portfolio_learning(decision_id,game,draw_date,model_version,judgment_json,created_at)
                   VALUES(?,?,?,?,?,?)
                   ON CONFLICT(decision_id) DO UPDATE SET judgment_json=excluded.judgment_json""",
                (int(decision_id),game,str(draw_date),str(model_version),json.dumps(judgment or {}),now)
            )
            con.execute("UPDATE portfolio_decisions SET judged=1 WHERE id=?",(int(decision_id),))

    def portfolio_learning_records(self, game, limit=250):
        with self.connect() as con:
            rows=con.execute(
                """SELECT l.*, d.decision_json FROM portfolio_learning l
                   JOIN portfolio_decisions d ON l.decision_id=d.id
                   WHERE l.game=? ORDER BY l.draw_date DESC,l.id DESC LIMIT ?""",
                (game,int(limit))).fetchall()
        out=[]
        for r in rows:
            d=dict(r)
            try: d["judgment"] = json.loads(d.get("judgment_json") or "{}")
            except Exception: d["judgment"] = {}
            try: d["decision"] = json.loads(d.get("decision_json") or "{}")
            except Exception: d["decision"] = {}
            out.append(d)
        return list(reversed(out))
