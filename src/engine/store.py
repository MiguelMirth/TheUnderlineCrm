"""
SQLite store for the prospecting engine: runs, leads, events, API cache, spend ledger, CRM snapshot.

Stdlib sqlite3 with WAL and busy_timeout. No ORM. A connection opens per call,
so the FastAPI threads and the worker thread never share a connection.
Schema changes go in MIGRATIONS with a new version number.
"""
from __future__ import annotations

import json
import os
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator, Optional

SCHEMA_VERSION = 3

ACTIVE_RUN_STATUSES = ("queued", "running", "awaiting_enrich", "enriching")
# Statuses a run can be resumed from. Resume re-enters the saved stage.
RESUMABLE_RUN_STATUSES = ("interrupted", "budget_stopped", "error")
_LIVE_RUN_STATUSES = ("running", "enriching")

_ID_ALPHABET = "23456789abcdefghjkmnpqrstuvwxyz"

_SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('discovery', 'import')),
    preset_id TEXT NOT NULL,
    vertical_id TEXT NOT NULL,
    status TEXT NOT NULL,
    stage INTEGER NOT NULL DEFAULT 0,
    stage_name TEXT NOT NULL DEFAULT '',
    toggles_json TEXT NOT NULL,
    caps_json TEXT NOT NULL,
    brief TEXT NOT NULL DEFAULT '',
    reservation_json TEXT NOT NULL DEFAULT '{}',
    spend_json TEXT NOT NULL DEFAULT '{}',
    started_by TEXT NOT NULL,
    error TEXT NOT NULL DEFAULT '',
    cancel_requested INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS runs_status_created ON runs (status, created_at);

CREATE TABLE IF NOT EXISTS leads (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs (id),
    seq INTEGER NOT NULL,
    state TEXT NOT NULL,
    shelf_brand TEXT NOT NULL DEFAULT '',
    person_name TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '',
    email TEXT NOT NULL DEFAULT '',
    domain TEXT NOT NULL DEFAULT '',
    location TEXT NOT NULL DEFAULT '',
    vertical TEXT NOT NULL DEFAULT '',
    person_json TEXT NOT NULL DEFAULT '{}',
    gates_json TEXT NOT NULL DEFAULT '[]',
    llm_json TEXT,
    evidence_json TEXT NOT NULL DEFAULT '[]',
    cost_spent REAL NOT NULL DEFAULT 0,
    decided_by TEXT NOT NULL DEFAULT '',
    decided_at TEXT NOT NULL DEFAULT '',
    monday_item_id TEXT NOT NULL DEFAULT '',
    push_error TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (run_id, seq)
);
CREATE INDEX IF NOT EXISTS leads_run_state ON leads (run_id, state);
CREATE INDEX IF NOT EXISTS leads_email ON leads (email);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES runs (id),
    ts TEXT NOT NULL,
    level TEXT NOT NULL,
    message TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS events_run ON events (run_id, id);

CREATE TABLE IF NOT EXISTS api_cache (
    provider TEXT NOT NULL,
    op TEXT NOT NULL,
    key TEXT NOT NULL,
    payload TEXT NOT NULL,
    units REAL NOT NULL DEFAULT 0,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (provider, op, key)
);

CREATE TABLE IF NOT EXISTS ledger (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    month TEXT NOT NULL,
    provider TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('actual', 'refund')),
    units REAL NOT NULL,
    run_id TEXT,
    stage TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS ledger_month_provider ON ledger (month, provider);

CREATE TABLE IF NOT EXISTS crm_snapshot (
    board_id TEXT PRIMARY KEY,
    fetched_at TEXT NOT NULL,
    payload TEXT NOT NULL
);
"""

_MIGRATION_V2 = """
ALTER TABLE runs ADD COLUMN input_text TEXT NOT NULL DEFAULT '';
ALTER TABLE leads ADD COLUMN prior_state TEXT NOT NULL DEFAULT '';
"""

_MIGRATION_V3 = """
CREATE TABLE IF NOT EXISTS preset_settings (
    preset_id TEXT PRIMARY KEY,
    config_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""

# version -> SQL run once when upgrading from version - 1. Version 1 is the base schema.
MIGRATIONS: dict[int, str] = {1: _SCHEMA_V1, 2: _MIGRATION_V2, 3: _MIGRATION_V3}


class RunInProgress(RuntimeError):
    """Delete was asked for a run the worker still owns."""


class SchemaTooNew(RuntimeError):
    pass


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def new_run_id() -> str:
    return "r_" + "".join(secrets.choice(_ID_ALPHABET) for _ in range(6))


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _load(raw: Optional[str], default: Any) -> Any:
    if raw is None or raw == "":
        return default
    return json.loads(raw)


class Store:
    def __init__(self, path: str) -> None:
        self.path = path
        directory = os.path.dirname(os.path.abspath(path))
        os.makedirs(directory, exist_ok=True)
        self._init_schema()

    # -- connection ---------------------------------------------------------

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=5000")
            conn.execute("PRAGMA foreign_keys=ON")
            yield conn
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self.connect() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
            row = conn.execute("SELECT version FROM schema_version").fetchone()
            current = int(row["version"]) if row else 0
            if current > SCHEMA_VERSION:
                raise SchemaTooNew(f"database schema {current} is newer than this code ({SCHEMA_VERSION})")
            for version in range(current + 1, SCHEMA_VERSION + 1):
                conn.execute("BEGIN IMMEDIATE")
                try:
                    for stmt in _split_sql(MIGRATIONS[version]):
                        conn.execute(stmt)
                    conn.execute("DELETE FROM schema_version")
                    conn.execute("INSERT INTO schema_version (version) VALUES (?)", (version,))
                    conn.execute("COMMIT")
                except Exception:
                    conn.execute("ROLLBACK")
                    raise

    def schema_version(self) -> int:
        with self.connect() as conn:
            row = conn.execute("SELECT version FROM schema_version").fetchone()
            return int(row["version"]) if row else 0

    # -- runs ---------------------------------------------------------------

    def create_run(
        self,
        *,
        kind: str,
        preset_id: str,
        vertical_id: str,
        toggles: dict[str, Any],
        caps: dict[str, int],
        brief: str,
        started_by: str,
        reservation: dict[str, float],
        input_text: str = "",
    ) -> dict[str, Any]:
        ts = now_iso()
        with self.connect() as conn:
            for _ in range(10):
                run_id = new_run_id()
                exists = conn.execute("SELECT 1 FROM runs WHERE id = ?", (run_id,)).fetchone()
                if not exists:
                    break
            conn.execute(
                """
                INSERT INTO runs (id, kind, preset_id, vertical_id, status, stage, stage_name,
                    toggles_json, caps_json, brief, reservation_json, spend_json, started_by,
                    input_text, created_at, updated_at)
                VALUES (?, ?, ?, ?, 'queued', 0, 'Queued', ?, ?, ?, ?, '{}', ?, ?, ?, ?)
                """,
                (
                    run_id,
                    kind,
                    preset_id,
                    vertical_id,
                    _dump(toggles),
                    _dump(caps),
                    brief,
                    _dump(reservation),
                    started_by,
                    input_text,
                    ts,
                    ts,
                ),
            )
        self.add_event(run_id, "info", f"Queued by {started_by}")
        return self.get_run(run_id)  # type: ignore[return-value]

    def get_run(self, run_id: str) -> Optional[dict[str, Any]]:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        return _run_from_row(row) if row else None

    def list_runs(self, limit: int = 30) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM runs ORDER BY created_at DESC, id DESC LIMIT ?", (int(limit),)
            ).fetchall()
        return [_run_from_row(r) for r in rows]

    def claim_next_queued(self) -> Optional[dict[str, Any]]:
        """Atomically move the oldest queued run to running. FIFO by creation time."""
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                row = conn.execute(
                    "SELECT id FROM runs WHERE status = 'queued' ORDER BY created_at, id LIMIT 1"
                ).fetchone()
                if row is None:
                    conn.execute("COMMIT")
                    return None
                conn.execute(
                    "UPDATE runs SET status = 'running', updated_at = ? WHERE id = ?",
                    (now_iso(), row["id"]),
                )
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        return self.get_run(row["id"])

    def update_run(self, run_id: str, **fields: Any) -> None:
        """Set run columns. JSON columns are passed as Python objects and encoded here."""
        json_cols = {"toggles_json", "caps_json", "reservation_json", "spend_json"}
        assignments: list[str] = []
        values: list[Any] = []
        for key, value in fields.items():
            column = key
            if key in ("toggles", "caps", "reservation", "spend"):
                column = f"{key}_json"
            if column not in json_cols and column not in _RUN_COLUMNS:
                raise KeyError(f"unknown run column {key}")
            if column in json_cols:
                value = _dump(value)
            if column == "cancel_requested":
                value = 1 if value else 0
            assignments.append(f"{column} = ?")
            values.append(value)
        assignments.append("updated_at = ?")
        values.append(now_iso())
        values.append(run_id)
        with self.connect() as conn:
            conn.execute(f"UPDATE runs SET {', '.join(assignments)} WHERE id = ?", values)

    def set_status(self, run_id: str, status: str, *, stage: int | None = None, stage_name: str | None = None, error: str | None = None) -> None:
        fields: dict[str, Any] = {"status": status}
        if stage is not None:
            fields["stage"] = stage
        if stage_name is not None:
            fields["stage_name"] = stage_name
        if error is not None:
            fields["error"] = error
        self.update_run(run_id, **fields)

    def request_cancel(self, run_id: str) -> Optional[dict[str, Any]]:
        run = self.get_run(run_id)
        if run is None:
            return None
        status = run["status"]
        if status in ("queued", "awaiting_enrich", "interrupted", "budget_stopped", "error"):
            self.set_status(run_id, "cancelled", stage_name="Cancelled")
            self.add_event(run_id, "info", f"Cancelled while {status.replace('_', ' ')}")
        elif status in _LIVE_RUN_STATUSES:
            self.update_run(run_id, cancel_requested=True)
            self.add_event(run_id, "info", "Cancel requested; stops after the current stage")
        return self.get_run(run_id)

    def queue_resume(self, run_id: str) -> Optional[dict[str, Any]]:
        """Re-queue a resumable run. It re-enters its saved stage."""
        run = self.get_run(run_id)
        if run is None or run["status"] not in RESUMABLE_RUN_STATUSES:
            return run
        self.update_run(run_id, status="queued", error="", cancel_requested=False)
        self.add_event(run_id, "info", f"Resumed from stage {run['stage']} ({run['stage_name'] or 'start'})")
        return self.get_run(run_id)

    def recover_interrupted(self) -> int:
        """On process start, runs left live become interrupted so the operator can Resume."""
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT id FROM runs WHERE status IN (?, ?)", _LIVE_RUN_STATUSES
            ).fetchall()
        for row in rows:
            self.set_status(row["id"], "interrupted", stage_name="Interrupted", error="Process stopped during this run")
            self.add_event(row["id"], "warn", "Process stopped during this run. Resume to continue.")
        return len(rows)

    # -- events -------------------------------------------------------------

    def add_event(self, run_id: str, level: str, message: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO events (run_id, ts, level, message) VALUES (?, ?, ?, ?)",
                (run_id, now_iso(), level, message[:2000]),
            )

    def list_events(self, run_id: str, limit: int = 200) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM (SELECT * FROM events WHERE run_id = ? ORDER BY id DESC LIMIT ?) ORDER BY id",
                (run_id, int(limit)),
            ).fetchall()
        return [dict(r) for r in rows]

    # -- leads --------------------------------------------------------------

    def next_lead_seq(self, run_id: str) -> int:
        with self.connect() as conn:
            row = conn.execute("SELECT COALESCE(MAX(seq), 0) AS m FROM leads WHERE run_id = ?", (run_id,)).fetchone()
        return int(row["m"]) + 1

    def insert_lead(self, run_id: str, state: str, **fields: Any) -> dict[str, Any]:
        seq = self.next_lead_seq(run_id)
        lead_id = f"{run_id}-{seq:04d}"
        ts = now_iso()
        row = {
            "id": lead_id,
            "run_id": run_id,
            "seq": seq,
            "state": state,
            "shelf_brand": fields.get("shelf_brand", ""),
            "person_name": fields.get("person_name", ""),
            "title": fields.get("title", ""),
            "email": fields.get("email", ""),
            "domain": fields.get("domain", ""),
            "location": fields.get("location", ""),
            "vertical": fields.get("vertical", ""),
            "person_json": _dump(fields.get("person", {})),
            "gates_json": _dump(fields.get("gates", [])),
            "llm_json": None if fields.get("llm") is None else _dump(fields["llm"]),
            "evidence_json": _dump(fields.get("evidence", [])),
            "cost_spent": float(fields.get("cost_spent", 0) or 0),
            "created_at": ts,
            "updated_at": ts,
        }
        cols = ", ".join(row)
        marks = ", ".join("?" for _ in row)
        with self.connect() as conn:
            conn.execute(f"INSERT INTO leads ({cols}) VALUES ({marks})", list(row.values()))
        return self.get_lead(lead_id)  # type: ignore[return-value]

    def get_lead(self, lead_id: str) -> Optional[dict[str, Any]]:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM leads WHERE id = ?", (lead_id,)).fetchone()
        return _lead_from_row(row) if row else None

    def list_leads(self, run_id: str, states: Optional[list[str]] = None) -> list[dict[str, Any]]:
        with self.connect() as conn:
            if states:
                marks = ", ".join("?" for _ in states)
                rows = conn.execute(
                    f"SELECT * FROM leads WHERE run_id = ? AND state IN ({marks}) ORDER BY seq",
                    [run_id, *states],
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM leads WHERE run_id = ? ORDER BY seq", (run_id,)).fetchall()
        return [_lead_from_row(r) for r in rows]

    def count_leads(self, run_id: str) -> dict[str, int]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT state, COUNT(*) AS n FROM leads WHERE run_id = ? GROUP BY state", (run_id,)
            ).fetchall()
        return {r["state"]: int(r["n"]) for r in rows}

    def delete_run(self, run_id: str) -> bool:
        """
        Remove a run, its leads, and its log. Returns False when the id is unknown.
        Refuses while the worker may still be executing it. Ledger rows stay, so
        monthly spend does not shrink because a run was deleted.
        """
        blocked = ("queued", "running", "enriching")
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                row = conn.execute("SELECT status FROM runs WHERE id = ?", (run_id,)).fetchone()
                if row is None:
                    conn.execute("ROLLBACK")
                    return False
                if row["status"] in blocked:
                    conn.execute("ROLLBACK")
                    raise RunInProgress(f"This run is {row['status']}. Cancel it, then delete it.")
                conn.execute("DELETE FROM events WHERE run_id = ?", (run_id,))
                conn.execute("DELETE FROM leads WHERE run_id = ?", (run_id,))
                conn.execute("DELETE FROM runs WHERE id = ?", (run_id,))
                conn.execute("COMMIT")
            except RunInProgress:
                raise
            except Exception:
                conn.execute("ROLLBACK")
                raise
        return True

    def delete_leads(self, run_id: str) -> int:
        """Remove a run's leads before a re-run of its source stage. Only the source stage calls this."""
        with self.connect() as conn:
            cur = conn.execute("DELETE FROM leads WHERE run_id = ?", (run_id,))
            return int(cur.rowcount)

    def update_lead(self, lead_id: str, **fields: Any) -> None:
        allowed_json = {"person": "person_json", "gates": "gates_json", "llm": "llm_json", "evidence": "evidence_json"}
        allowed_plain = {
            "state", "prior_state", "shelf_brand", "person_name", "title", "email", "domain", "location", "vertical",
            "cost_spent", "decided_by", "decided_at", "monday_item_id", "push_error",
        }
        assignments: list[str] = []
        values: list[Any] = []
        for key, value in fields.items():
            if key in allowed_json:
                column, value = allowed_json[key], (None if value is None and key == "llm" else _dump(value))
            elif key in allowed_plain:
                column = key
            else:
                raise KeyError(f"unknown lead column {key}")
            assignments.append(f"{column} = ?")
            values.append(value)
        assignments.append("updated_at = ?")
        values.append(now_iso())
        values.append(lead_id)
        with self.connect() as conn:
            conn.execute(f"UPDATE leads SET {', '.join(assignments)} WHERE id = ?", values)

    # -- API cache ----------------------------------------------------------

    def cache_get(self, provider: str, op: str, key: str) -> Optional[dict[str, Any]]:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT payload, units, fetched_at FROM api_cache WHERE provider = ? AND op = ? AND key = ?",
                (provider, op, key),
            ).fetchone()
        if row is None:
            return None
        return {"payload": _load(row["payload"], None), "units": float(row["units"]), "fetched_at": row["fetched_at"]}

    def cache_put(self, provider: str, op: str, key: str, payload: Any, units: float = 0.0) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO api_cache (provider, op, key, payload, units, fetched_at) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT (provider, op, key) DO UPDATE SET
                    payload = excluded.payload, units = excluded.units, fetched_at = excluded.fetched_at
                """,
                (provider, op, key, _dump(payload), float(units), now_iso()),
            )

    # -- spend ledger -------------------------------------------------------

    def ledger_append(self, *, provider: str, units: float, month: str, run_id: str | None, stage: str, kind: str = "actual") -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO ledger (ts, month, provider, kind, units, run_id, stage) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (now_iso(), month, provider, kind, float(units), run_id, stage),
            )

    def ledger_between(self, provider: str, start_iso: str, end_iso: str) -> float:
        """Spend with start_iso <= ts < end_iso. Used for the Cursor cycle, which turns on the 13th."""
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT COALESCE(SUM(CASE WHEN kind = 'actual' THEN units ELSE -units END), 0) AS total
                FROM ledger WHERE provider = ? AND ts >= ? AND ts < ?
                """,
                (provider, start_iso, end_iso),
            ).fetchone()
        return float(row["total"])

    def ledger_total(self, provider: str, month: str) -> float:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT COALESCE(SUM(CASE WHEN kind = 'actual' THEN units ELSE -units END), 0) AS total
                FROM ledger WHERE provider = ? AND month = ?
                """,
                (provider, month),
            ).fetchone()
        return float(row["total"])

    def ledger_run_total(self, run_id: str, provider: str) -> float:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT COALESCE(SUM(CASE WHEN kind = 'actual' THEN units ELSE -units END), 0) AS total
                FROM ledger WHERE run_id = ? AND provider = ?
                """,
                (run_id, provider),
            ).fetchone()
        return float(row["total"])

    def reserved_total(self, provider: str) -> float:
        """Sum of the reservations held by runs that have not finished."""
        total = 0.0
        with self.connect() as conn:
            rows = conn.execute(
                f"SELECT reservation_json FROM runs WHERE status IN ({', '.join('?' for _ in ACTIVE_RUN_STATUSES)})",
                ACTIVE_RUN_STATUSES,
            ).fetchall()
        for row in rows:
            total += float((_load(row["reservation_json"], {}) or {}).get(provider, 0) or 0)
        return total

    # -- CRM snapshot -------------------------------------------------------

    def get_preset_settings(self, preset_id: str) -> Optional[dict[str, Any]]:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT config_json FROM preset_settings WHERE preset_id = ?", (preset_id,)
            ).fetchone()
        if row is None:
            return None
        loaded = _load(row["config_json"], None)
        return loaded if isinstance(loaded, dict) else None

    def put_preset_settings(self, preset_id: str, payload: dict[str, Any]) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO preset_settings (preset_id, config_json, updated_at) VALUES (?, ?, ?)
                ON CONFLICT (preset_id) DO UPDATE SET
                    config_json = excluded.config_json,
                    updated_at = excluded.updated_at
                """,
                (preset_id, _dump(payload), now_iso()),
            )

    def delete_preset_settings(self, preset_id: str) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM preset_settings WHERE preset_id = ?", (preset_id,))

    def crm_snapshot_get(self, board_id: str) -> Optional[dict[str, Any]]:
        with self.connect() as conn:
            row = conn.execute("SELECT fetched_at, payload FROM crm_snapshot WHERE board_id = ?", (board_id,)).fetchone()
        if row is None:
            return None
        return {"fetched_at": row["fetched_at"], "payload": _load(row["payload"], {})}

    def crm_snapshot_put(self, board_id: str, payload: dict[str, Any]) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO crm_snapshot (board_id, fetched_at, payload) VALUES (?, ?, ?)
                ON CONFLICT (board_id) DO UPDATE SET fetched_at = excluded.fetched_at, payload = excluded.payload
                """,
                (board_id, now_iso(), _dump(payload)),
            )

    # -- backup -------------------------------------------------------------

    def backup_to(self, dest_path: str) -> None:
        """Consistent copy of the live database (VACUUM INTO works while the app is writing)."""
        os.makedirs(os.path.dirname(os.path.abspath(dest_path)), exist_ok=True)
        with self.connect() as conn:
            conn.execute("VACUUM INTO ?", (dest_path,))


def backup_folder(db_path: str) -> str:
    return os.path.join(os.path.dirname(os.path.abspath(db_path)), "backups")


def write_daily_backup(store: "Store", db_path: str, *, day: str | None = None, keep: int = 14) -> str | None:
    """
    One VACUUM INTO copy per calendar day, under data/engine/backups/.
    Returns the new file path, or None when today's copy is already there.
    Older copies beyond `keep` are removed.
    """
    stamp = day or datetime.now().strftime("%Y-%m-%d")
    folder = backup_folder(db_path)
    os.makedirs(folder, exist_ok=True)
    dest = os.path.join(folder, f"underline-{stamp}.db")
    if not os.path.isfile(dest):
        store.backup_to(dest)
        written: str | None = dest
    else:
        written = None
    copies = sorted(
        name for name in os.listdir(folder) if name.startswith("underline-") and name.endswith(".db")
    )
    for name in copies[:-keep] if keep > 0 else copies:
        try:
            os.remove(os.path.join(folder, name))
        except OSError:
            pass
    return written


_RUN_COLUMNS = {
    "status", "stage", "stage_name", "error", "cancel_requested", "brief", "started_by",
}


def _split_sql(script: str) -> list[str]:
    return [s.strip() for s in script.split(";") if s.strip()]


def _run_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "kind": row["kind"],
        "preset_id": row["preset_id"],
        "vertical_id": row["vertical_id"],
        "status": row["status"],
        "stage": int(row["stage"]),
        "stage_name": row["stage_name"],
        "toggles": _load(row["toggles_json"], {}),
        "caps": _load(row["caps_json"], {}),
        "brief": row["brief"],
        "input_text": row["input_text"],
        "reservation": _load(row["reservation_json"], {}),
        "spend": _load(row["spend_json"], {}),
        "started_by": row["started_by"],
        "error": row["error"],
        "cancel_requested": bool(row["cancel_requested"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _lead_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "run_id": row["run_id"],
        "seq": int(row["seq"]),
        "state": row["state"],
        "prior_state": row["prior_state"],
        "shelf_brand": row["shelf_brand"],
        "person_name": row["person_name"],
        "title": row["title"],
        "email": row["email"],
        "domain": row["domain"],
        "location": row["location"],
        "vertical": row["vertical"],
        "person": _load(row["person_json"], {}),
        "gates": _load(row["gates_json"], []),
        "llm": _load(row["llm_json"], None),
        "evidence": _load(row["evidence_json"], []),
        "cost_spent": float(row["cost_spent"]),
        "decided_by": row["decided_by"],
        "decided_at": row["decided_at"],
        "monday_item_id": row["monday_item_id"],
        "push_error": row["push_error"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }
