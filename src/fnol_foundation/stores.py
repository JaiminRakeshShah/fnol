"""SQLite input, output, and append-only trace stores.

Three files in one directory: input.sqlite, output.sqlite, and trace.sqlite.
FNOL_STATE_DIR overrides the default .state directory.
"""

import json
import os
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from fnol_foundation.canonical import assert_no_restricted, canonical, digest

TRACE_COLUMNS = (
    "event_id",
    "trace_id",
    "span_id",
    "parent_span_id",
    "case_id",
    "input_revision",
    "draft_id",
    "step",
    "actor",
    "rule_version",
    "started_at",
    "duration_ms",
    "attempt",
    "status",
    "error_code",
    "mock_http_status",
    "input_sha256",
    "output_sha256",
    "model_id",
    "input_tokens",
    "output_tokens",
    "shadow_narrative",
    "shadow_safety_status",
)

_TRACE_NOT_NULL = {"trace_id", "span_id", "step", "actor", "status"}
_TRACE_INTEGER = {"input_revision", "duration_ms", "attempt", "mock_http_status", "input_tokens", "output_tokens"}

INPUT_COLUMNS = (
    "intake_source",
    "account_text",
    "incident_timestamp",
    "policy_number",
    "vehicle_id",
    "loss_type",
    "driver_name",
    "driver_name_supplied",
    "incident_location",
    "incident_location_supplied",
    "injury_reported_raw",
    "injury_reported",
    "vehicle_drivable_raw",
    "vehicle_drivable",
    "referral_indicator",
    "loss_reference",
    "duplicates",
    "intake_sha256",
    "raw_intake",
    "intake_notes",
    "estimate_source_id",
    "estimate_sha256",
    "estimate_reference",
    "estimate_vehicle",
    "repair_amount",
    "estimate_prepared_by",
    "estimate_notes",
    "raw_estimate",
    "report_source_id",
    "report_sha256",
    "report_vehicle_reference",
    "report_incident_timestamp",
    "reported_loss_type",
    "report_notes",
    "raw_report",
)

BOOL_COLUMNS = {
    "driver_name_supplied",
    "incident_location_supplied",
    "injury_reported",
    "vehicle_drivable",
}

INPUT_SCHEMA = """
CREATE TABLE IF NOT EXISTS input_revisions (
  case_id TEXT NOT NULL,
  revision INTEGER NOT NULL,
  ingested_at TEXT NOT NULL,
  document_set_sha256 TEXT NOT NULL,
  intake_source TEXT,
  account_text TEXT,
  incident_timestamp TEXT,
  policy_number TEXT,
  vehicle_id TEXT,
  loss_type TEXT,
  driver_name TEXT,
  driver_name_supplied INTEGER,
  incident_location TEXT,
  incident_location_supplied INTEGER,
  injury_reported_raw TEXT,
  injury_reported INTEGER,
  vehicle_drivable_raw TEXT,
  vehicle_drivable INTEGER,
  referral_indicator TEXT,
  loss_reference TEXT,
  duplicates INTEGER NOT NULL DEFAULT 0,
  intake_sha256 TEXT,
  raw_intake TEXT,
  intake_notes TEXT,
  estimate_source_id TEXT,
  estimate_sha256 TEXT,
  estimate_reference TEXT,
  estimate_vehicle TEXT,
  repair_amount TEXT,
  estimate_prepared_by TEXT,
  estimate_notes TEXT,
  raw_estimate TEXT,
  report_source_id TEXT,
  report_sha256 TEXT,
  report_vehicle_reference TEXT,
  report_incident_timestamp TEXT,
  reported_loss_type TEXT,
  report_notes TEXT,
  raw_report TEXT,
  UNIQUE (case_id, revision)
);
CREATE TABLE IF NOT EXISTS procedure_sources (
  source_id TEXT PRIMARY KEY,
  sha256 TEXT NOT NULL,
  loaded_at TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS input_revisions_no_update
BEFORE UPDATE ON input_revisions
BEGIN
  SELECT RAISE(ABORT, 'input_revisions is append-only');
END;
CREATE TRIGGER IF NOT EXISTS input_revisions_no_delete
BEFORE DELETE ON input_revisions
BEGIN
  SELECT RAISE(ABORT, 'input_revisions is append-only');
END;
"""

OUTPUT_SCHEMA = """
CREATE TABLE IF NOT EXISTS drafts (
  draft_id TEXT PRIMARY KEY,
  case_id TEXT NOT NULL,
  input_revision INTEGER,
  draft_json TEXT NOT NULL,
  draft_hash TEXT NOT NULL,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL,
  review_id TEXT,
  outcome TEXT
);
CREATE TRIGGER IF NOT EXISTS drafts_body_immutable
BEFORE UPDATE ON drafts
WHEN OLD.draft_json IS NOT NEW.draft_json OR OLD.draft_hash IS NOT NEW.draft_hash
BEGIN
  SELECT RAISE(ABORT, 'draft_json and draft_hash are immutable');
END;
"""


def _trace_column_sql(name):
    if name == "event_id":
        return "event_id TEXT PRIMARY KEY"
    if name in _TRACE_NOT_NULL or name == "started_at":
        return f"{name} TEXT NOT NULL"
    if name in _TRACE_INTEGER:
        return f"{name} INTEGER"
    return f"{name} TEXT"


TRACE_SCHEMA = """
CREATE TABLE IF NOT EXISTS trace_events (
  """ + ", ".join(_trace_column_sql(name) for name in TRACE_COLUMNS) + """
);
CREATE TRIGGER IF NOT EXISTS trace_events_no_update
BEFORE UPDATE ON trace_events
BEGIN
  SELECT RAISE(ABORT, 'trace_events is append-only');
END;
CREATE TRIGGER IF NOT EXISTS trace_events_no_delete
BEFORE DELETE ON trace_events
BEGIN
  SELECT RAISE(ABORT, 'trace_events is append-only');
END;
"""


def state_dir():
    return Path(os.environ.get("FNOL_STATE_DIR", ".state"))


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def _as_text(value):
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def connect(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=15)
    db.row_factory = sqlite3.Row
    return db


@dataclass(frozen=True)
class Revision:
    case_id: str
    revision: int
    ingested_at: str
    document_set_sha256: str
    payload: dict


@dataclass(frozen=True)
class DraftRecord:
    draft_id: str
    case_id: str
    input_revision: int | None
    draft: dict
    draft_hash: str
    status: str
    created_at: str
    review_id: str | None
    outcome: str | None


def _bind_value(column, value):
    if column == "duplicates":
        return 1 if value else 0
    if column in BOOL_COLUMNS:
        if value is None:
            return None
        return 1 if value else 0
    return value


def _read_value(column, value):
    if column in BOOL_COLUMNS and value is not None:
        return bool(value)
    return value


def _row_payload(row):
    return {column: _read_value(column, row[column]) for column in INPUT_COLUMNS}


class InputStore:
    def __init__(self, path):
        self.path = Path(path)
        with connect(self.path) as db:
            existing = {row["name"] for row in db.execute("PRAGMA table_info(input_revisions)").fetchall()}
            if "payload_json" in existing:
                db.executescript("DROP TABLE IF EXISTS input_revisions;")
            db.executescript(INPUT_SCHEMA)
            names = {row["name"] for row in db.execute("PRAGMA table_info(input_revisions)").fetchall()}
            if "duplicates" not in names:
                db.execute("ALTER TABLE input_revisions ADD COLUMN duplicates INTEGER NOT NULL DEFAULT 0")

    def append_revision(self, case_id, payload, document_set_sha256=None, ingested_at=None):
        """Insert the next revision for case_id. Re-ingesting always increments."""
        if not isinstance(case_id, str) or not case_id:
            raise ValueError("case_id is required")
        if not isinstance(payload, dict):
            raise TypeError("payload must be a JSON object")
        assert_no_restricted(payload)
        sha = document_set_sha256 if document_set_sha256 is not None else digest(payload)
        if not isinstance(sha, str) or not sha:
            raise ValueError("document_set_sha256 must be a non-empty string")
        assert_no_restricted(sha)
        when = _as_text(ingested_at) or utc_now()
        columns = ["case_id", "revision", "ingested_at", "document_set_sha256", *INPUT_COLUMNS]
        placeholders = ", ".join("?" for _ in columns)
        with connect(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT COALESCE(MAX(revision), 0) FROM input_revisions WHERE case_id = ?",
                (case_id,),
            ).fetchone()
            revision = int(row[0]) + 1
            values = [case_id, revision, when, sha]
            values.extend(_bind_value(column, payload.get(column)) for column in INPUT_COLUMNS)
            db.execute(
                f"INSERT INTO input_revisions ({', '.join(columns)}) VALUES ({placeholders})",
                values,
            )
        return self.get_revision(case_id, revision)

    def get_revision(self, case_id, revision=None):
        with connect(self.path) as db:
            if revision is None:
                row = db.execute(
                    """SELECT * FROM input_revisions
                       WHERE case_id = ? ORDER BY revision DESC LIMIT 1""",
                    (case_id,),
                ).fetchone()
            else:
                row = db.execute(
                    "SELECT * FROM input_revisions WHERE case_id = ? AND revision = ?",
                    (case_id, revision),
                ).fetchone()
        if row is None:
            return None
        return Revision(
            case_id=row["case_id"],
            revision=row["revision"],
            ingested_at=row["ingested_at"],
            document_set_sha256=row["document_set_sha256"],
            payload=_row_payload(row),
        )

    def latest_loss_keys(self):
        """Latest revision of each case: case_id and loss_reference."""
        with connect(self.path) as db:
            rows = db.execute(
                """SELECT case_id, loss_reference
                   FROM input_revisions AS current
                   WHERE revision = (
                       SELECT MAX(revision) FROM input_revisions
                       WHERE case_id = current.case_id
                   )"""
            ).fetchall()
        return [{"case_id": row["case_id"], "loss_reference": row["loss_reference"]} for row in rows]

    def store_procedures(self, sources):
        """Replace the procedure-source table with this run's id and sha256 rows."""
        when = utc_now()
        assert_no_restricted(sources)
        with connect(self.path) as db:
            db.execute("DELETE FROM procedure_sources")
            db.executemany(
                "INSERT INTO procedure_sources (source_id, sha256, loaded_at) VALUES (?, ?, ?)",
                [(item["source_id"], item["sha256"], when) for item in sources],
            )

    def list_procedures(self):
        with connect(self.path) as db:
            rows = db.execute(
                "SELECT source_id, sha256, loaded_at FROM procedure_sources ORDER BY source_id"
            ).fetchall()
        return [{"source_id": row["source_id"], "sha256": row["sha256"], "loaded_at": row["loaded_at"]} for row in rows]


class OutputStore:
    def __init__(self, path):
        self.path = Path(path)
        with connect(self.path) as db:
            db.executescript(OUTPUT_SCHEMA)

    def record_draft(self, case_id, draft, input_revision=None, draft_id=None, status="recorded", created_at=None):
        """Store a draft and the mock's hash of that exact object."""
        if not isinstance(case_id, str) or not case_id:
            raise ValueError("case_id is required")
        if not isinstance(draft, dict):
            raise TypeError("draft must be a JSON object")
        assert_no_restricted(draft)
        draft_json = canonical(draft)
        draft_hash = digest(draft)
        draft_id = draft_id or "draft_" + uuid.uuid4().hex[:12]
        when = _as_text(created_at) or utc_now()
        with connect(self.path) as db:
            db.execute(
                """INSERT INTO drafts
                   (draft_id, case_id, input_revision, draft_json, draft_hash, status, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (draft_id, case_id, input_revision, draft_json, draft_hash, status, when),
            )
        return self.get_draft(draft_id)

    def get_draft(self, draft_id):
        with connect(self.path) as db:
            row = db.execute("SELECT * FROM drafts WHERE draft_id = ?", (draft_id,)).fetchone()
        if row is None:
            return None
        return DraftRecord(
            draft_id=row["draft_id"],
            case_id=row["case_id"],
            input_revision=row["input_revision"],
            draft=json.loads(row["draft_json"]),
            draft_hash=row["draft_hash"],
            status=row["status"],
            created_at=row["created_at"],
            review_id=row["review_id"],
            outcome=row["outcome"],
        )

    def update_status(self, draft_id, status, review_id=None, outcome=None):
        """Record review progress. The draft body and hash stay as inserted."""
        assert_no_restricted({"status": status, "review_id": review_id, "outcome": outcome})
        with connect(self.path) as db:
            cur = db.execute(
                """UPDATE drafts
                   SET status = ?, review_id = COALESCE(?, review_id), outcome = COALESCE(?, outcome)
                   WHERE draft_id = ?""",
                (status, review_id, outcome, draft_id),
            )
            if cur.rowcount != 1:
                raise KeyError(draft_id)
        return self.get_draft(draft_id)


class TraceStore:
    def __init__(self, path):
        self.path = Path(path)
        with connect(self.path) as db:
            db.executescript(TRACE_SCHEMA)

    def append_event(self, **fields):
        """Insert one trace event. Updates and deletes are rejected by triggers."""
        event = {name: fields.get(name) for name in TRACE_COLUMNS}
        missing = [name for name in ("trace_id", "span_id", "step", "actor", "status") if not event[name]]
        if missing:
            raise ValueError("missing trace fields: " + ", ".join(missing))
        event["event_id"] = event["event_id"] or str(uuid.uuid4())
        event["started_at"] = _as_text(event["started_at"]) or utc_now()
        assert_no_restricted({key: value for key, value in event.items() if value is not None})
        columns = ", ".join(TRACE_COLUMNS)
        placeholders = ", ".join("?" for _ in TRACE_COLUMNS)
        with connect(self.path) as db:
            db.execute(
                f"INSERT INTO trace_events ({columns}) VALUES ({placeholders})",
                tuple(event[name] for name in TRACE_COLUMNS),
            )
        return self.get_event(event["event_id"])

    def get_event(self, event_id):
        with connect(self.path) as db:
            row = db.execute("SELECT * FROM trace_events WHERE event_id = ?", (event_id,)).fetchone()
        return None if row is None else {name: row[name] for name in TRACE_COLUMNS}

    def column_names(self):
        with connect(self.path) as db:
            rows = db.execute("PRAGMA table_info(trace_events)").fetchall()
        return tuple(row["name"] for row in rows)


class Stores:
    """The three SQLite files for one local state directory."""

    def __init__(self, directory=None):
        self.directory = Path(directory) if directory is not None else state_dir()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.input = InputStore(self.directory / "input.sqlite")
        self.output = OutputStore(self.directory / "output.sqlite")
        self.trace = TraceStore(self.directory / "trace.sqlite")

    def close(self):
        return None

    def drop(self):
        for path in (self.input.path, self.output.path, self.trace.path):
            path.unlink(missing_ok=True)
