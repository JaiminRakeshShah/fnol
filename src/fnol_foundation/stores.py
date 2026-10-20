"""SQLite input, output, and append-only trace stores.

Issue #1 names these files input.sqlite, output.sqlite, and trace.sqlite.
The issue title also says Postgres; this package has no database driver and
the acceptance criteria describe these SQLite files, so the schemas live here.
"""

import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from fnol_foundation.canonical import assert_no_restricted, canonical, digest

INPUT_SCHEMA = """
CREATE TABLE IF NOT EXISTS input_revisions (
  case_id TEXT NOT NULL,
  revision INTEGER NOT NULL,
  ingested_at TEXT NOT NULL,
  document_set_sha256 TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  UNIQUE (case_id, revision)
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

_TRACE_NOT_NULL = {"trace_id", "span_id", "step", "actor", "started_at", "status"}
_TRACE_INTEGER = {"input_revision", "duration_ms", "attempt", "mock_http_status", "input_tokens", "output_tokens"}


def _trace_column_sql(name):
    if name == "event_id":
        return "event_id TEXT PRIMARY KEY"
    if name in _TRACE_NOT_NULL:
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


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def connect(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=15)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
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


class InputStore:
    def __init__(self, path):
        self.path = Path(path)
        with connect(self.path) as db:
            db.executescript(INPUT_SCHEMA)

    def append_revision(self, case_id, payload, document_set_sha256=None, ingested_at=None):
        """Insert the next revision for case_id. Re-ingesting always increments."""
        if not isinstance(case_id, str) or not case_id:
            raise ValueError("case_id is required")
        if not isinstance(payload, dict):
            raise TypeError("payload must be a JSON object")
        assert_no_restricted(payload)
        payload_json = canonical(payload)
        sha = document_set_sha256 if document_set_sha256 is not None else digest(payload)
        if not isinstance(sha, str) or not sha:
            raise ValueError("document_set_sha256 must be a non-empty string")
        assert_no_restricted(sha)
        when = ingested_at or utc_now()
        with connect(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT COALESCE(MAX(revision), 0) FROM input_revisions WHERE case_id = ?",
                (case_id,),
            ).fetchone()
            revision = int(row[0]) + 1
            db.execute(
                """INSERT INTO input_revisions
                   (case_id, revision, ingested_at, document_set_sha256, payload_json)
                   VALUES (?, ?, ?, ?, ?)""",
                (case_id, revision, when, sha, payload_json),
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
            payload=json.loads(row["payload_json"]),
        )


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
        when = created_at or utc_now()
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
        """Insert one trace event. Updates and deletes are rejected by the schema."""
        event = {name: fields.get(name) for name in TRACE_COLUMNS}
        missing = [name for name in ("trace_id", "span_id", "step", "actor", "status") if not event[name]]
        if missing:
            raise ValueError("missing trace fields: " + ", ".join(missing))
        event["event_id"] = event["event_id"] or str(uuid.uuid4())
        event["started_at"] = event["started_at"] or utc_now()
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
    """The three foundation databases for one team-local state directory."""

    def __init__(self, directory):
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        self.directory = directory
        self.input = InputStore(directory / "input.sqlite")
        self.output = OutputStore(directory / "output.sqlite")
        self.trace = TraceStore(directory / "trace.sqlite")
