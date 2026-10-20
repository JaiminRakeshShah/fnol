"""Postgres input, output, and append-only trace stores.

Three schemas in one database: input.input_revisions, output.drafts, and
trace.trace_events. Connect with a Postgres DSN. FNOL_DATABASE_URL overrides
the local default.
"""

import json
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from fnol_foundation.canonical import assert_no_restricted, canonical, digest

DEFAULT_DSN = "postgresql://fnol@127.0.0.1:5432/fnol"

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


def database_url():
    return os.environ.get("FNOL_DATABASE_URL", DEFAULT_DSN)


def utc_now():
    return datetime.now(timezone.utc)


def _as_iso(value):
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _trace_column_sql(name):
    if name == "event_id":
        return "TEXT PRIMARY KEY"
    if name == "started_at":
        return "TIMESTAMPTZ NOT NULL"
    if name in _TRACE_NOT_NULL:
        return "TEXT NOT NULL"
    if name in _TRACE_INTEGER:
        return "INTEGER"
    return "TEXT"


class Stores:
    """One Postgres database with the input, output, and trace schemas."""

    def __init__(self, dsn=None, *, prefix=""):
        if prefix and not prefix.isidentifier():
            raise ValueError("schema prefix must be an identifier")
        self.dsn = dsn or database_url()
        self.schema_names = (f"{prefix}input", f"{prefix}output", f"{prefix}trace")
        self.input_schema, self.output_schema, self.trace_schema = self.schema_names
        self.conn = psycopg.connect(self.dsn, row_factory=dict_row, connect_timeout=5)
        self.conn.execute("SET TIME ZONE 'UTC'")
        self.conn.commit()
        self._ensure_schema()
        self.input = InputStore(self)
        self.output = OutputStore(self)
        self.trace = TraceStore(self)

    def close(self):
        self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()

    def drop(self):
        """Drop this store's schemas. Tests use a prefix so the shared schemas stay."""
        with self.conn.transaction():
            for name in self.schema_names:
                self.conn.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(name)))

    def _ensure_schema(self):
        input_schema = sql.Identifier(self.input_schema)
        output_schema = sql.Identifier(self.output_schema)
        trace_schema = sql.Identifier(self.trace_schema)
        revisions = sql.Identifier(self.input_schema, "input_revisions")
        drafts = sql.Identifier(self.output_schema, "drafts")
        events = sql.Identifier(self.trace_schema, "trace_events")
        trace_columns = sql.SQL(", ").join(
            sql.SQL("{} {}").format(sql.Identifier(name), sql.SQL(_trace_column_sql(name)))
            for name in TRACE_COLUMNS
        )
        statements = [
            sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(input_schema),
            sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(output_schema),
            sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(trace_schema),
            sql.SQL(
                """
                CREATE TABLE IF NOT EXISTS {} (
                  case_id TEXT NOT NULL,
                  revision INTEGER NOT NULL,
                  ingested_at TIMESTAMPTZ NOT NULL,
                  document_set_sha256 TEXT NOT NULL,
                  payload_json TEXT NOT NULL,
                  UNIQUE (case_id, revision)
                )
                """
            ).format(revisions),
            sql.SQL(
                """
                CREATE OR REPLACE FUNCTION {}.reject_mutation()
                RETURNS trigger LANGUAGE plpgsql AS $fn$
                BEGIN
                  RAISE EXCEPTION 'append-only';
                END;
                $fn$
                """
            ).format(input_schema),
            sql.SQL("DROP TRIGGER IF EXISTS revisions_no_update ON {}").format(revisions),
            sql.SQL(
                """
                CREATE TRIGGER revisions_no_update
                BEFORE UPDATE ON {}
                FOR EACH ROW EXECUTE FUNCTION {}.reject_mutation()
                """
            ).format(revisions, input_schema),
            sql.SQL("DROP TRIGGER IF EXISTS revisions_no_delete ON {}").format(revisions),
            sql.SQL(
                """
                CREATE TRIGGER revisions_no_delete
                BEFORE DELETE ON {}
                FOR EACH ROW EXECUTE FUNCTION {}.reject_mutation()
                """
            ).format(revisions, input_schema),
            sql.SQL(
                """
                CREATE TABLE IF NOT EXISTS {} (
                  draft_id TEXT PRIMARY KEY,
                  case_id TEXT NOT NULL,
                  input_revision INTEGER,
                  draft_json TEXT NOT NULL,
                  draft_hash TEXT NOT NULL,
                  status TEXT NOT NULL,
                  created_at TIMESTAMPTZ NOT NULL,
                  review_id TEXT,
                  outcome TEXT
                )
                """
            ).format(drafts),
            sql.SQL(
                """
                CREATE OR REPLACE FUNCTION {}.reject_body_change()
                RETURNS trigger LANGUAGE plpgsql AS $fn$
                BEGIN
                  IF NEW.draft_json IS DISTINCT FROM OLD.draft_json
                     OR NEW.draft_hash IS DISTINCT FROM OLD.draft_hash THEN
                    RAISE EXCEPTION 'draft body is immutable';
                  END IF;
                  RETURN NEW;
                END;
                $fn$
                """
            ).format(output_schema),
            sql.SQL("DROP TRIGGER IF EXISTS drafts_body_immutable ON {}").format(drafts),
            sql.SQL(
                """
                CREATE TRIGGER drafts_body_immutable
                BEFORE UPDATE ON {}
                FOR EACH ROW EXECUTE FUNCTION {}.reject_body_change()
                """
            ).format(drafts, output_schema),
            sql.SQL("CREATE TABLE IF NOT EXISTS {} ({})").format(events, trace_columns),
            sql.SQL(
                """
                CREATE OR REPLACE FUNCTION {}.reject_mutation()
                RETURNS trigger LANGUAGE plpgsql AS $fn$
                BEGIN
                  RAISE EXCEPTION 'append-only';
                END;
                $fn$
                """
            ).format(trace_schema),
            sql.SQL("DROP TRIGGER IF EXISTS trace_events_no_update ON {}").format(events),
            sql.SQL(
                """
                CREATE TRIGGER trace_events_no_update
                BEFORE UPDATE ON {}
                FOR EACH ROW EXECUTE FUNCTION {}.reject_mutation()
                """
            ).format(events, trace_schema),
            sql.SQL("DROP TRIGGER IF EXISTS trace_events_no_delete ON {}").format(events),
            sql.SQL(
                """
                CREATE TRIGGER trace_events_no_delete
                BEFORE DELETE ON {}
                FOR EACH ROW EXECUTE FUNCTION {}.reject_mutation()
                """
            ).format(events, trace_schema),
        ]
        with self.conn.transaction():
            for statement in statements:
                self.conn.execute(statement)


def _revision_from_row(row):
    return Revision(
        case_id=row["case_id"],
        revision=row["revision"],
        ingested_at=_as_iso(row["ingested_at"]),
        document_set_sha256=row["document_set_sha256"],
        payload=json.loads(row["payload_json"]),
    )


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
    def __init__(self, stores):
        self.stores = stores
        self.table = sql.Identifier(stores.input_schema, "input_revisions")

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
        query = sql.SQL(
            """
            INSERT INTO {} (case_id, revision, ingested_at, document_set_sha256, payload_json)
            VALUES (
              %s,
              (SELECT COALESCE(MAX(revision), 0) + 1 FROM {} WHERE case_id = %s),
              %s, %s, %s
            )
            RETURNING *
            """
        ).format(self.table, self.table)
        with self.stores.conn.transaction():
            self.stores.conn.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (f"input:{self.stores.input_schema}:{case_id}",),
            )
            row = self.stores.conn.execute(query, (case_id, case_id, when, sha, payload_json)).fetchone()
        return _revision_from_row(row)

    def get_revision(self, case_id, revision=None):
        if revision is None:
            query = sql.SQL(
                "SELECT * FROM {} WHERE case_id = %s ORDER BY revision DESC LIMIT 1"
            ).format(self.table)
            params = (case_id,)
        else:
            query = sql.SQL(
                "SELECT * FROM {} WHERE case_id = %s AND revision = %s"
            ).format(self.table)
            params = (case_id, revision)
        with self.stores.conn.transaction():
            row = self.stores.conn.execute(query, params).fetchone()
        return None if row is None else _revision_from_row(row)


class OutputStore:
    def __init__(self, stores):
        self.stores = stores
        self.table = sql.Identifier(stores.output_schema, "drafts")

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
        query = sql.SQL(
            """
            INSERT INTO {}
              (draft_id, case_id, input_revision, draft_json, draft_hash, status, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING *
            """
        ).format(self.table)
        with self.stores.conn.transaction():
            row = self.stores.conn.execute(
                query, (draft_id, case_id, input_revision, draft_json, draft_hash, status, when)
            ).fetchone()
        return _draft_from_row(row)

    def get_draft(self, draft_id):
        query = sql.SQL("SELECT * FROM {} WHERE draft_id = %s").format(self.table)
        with self.stores.conn.transaction():
            row = self.stores.conn.execute(query, (draft_id,)).fetchone()
        return None if row is None else _draft_from_row(row)

    def update_status(self, draft_id, status, review_id=None, outcome=None):
        """Record review progress. The draft body and hash stay as inserted."""
        assert_no_restricted({"status": status, "review_id": review_id, "outcome": outcome})
        query = sql.SQL(
            """
            UPDATE {}
            SET status = %s, review_id = COALESCE(%s, review_id), outcome = COALESCE(%s, outcome)
            WHERE draft_id = %s
            RETURNING *
            """
        ).format(self.table)
        with self.stores.conn.transaction():
            row = self.stores.conn.execute(query, (status, review_id, outcome, draft_id)).fetchone()
        if row is None:
            raise KeyError(draft_id)
        return _draft_from_row(row)


def _draft_from_row(row):
    return DraftRecord(
        draft_id=row["draft_id"],
        case_id=row["case_id"],
        input_revision=row["input_revision"],
        draft=json.loads(row["draft_json"]),
        draft_hash=row["draft_hash"],
        status=row["status"],
        created_at=_as_iso(row["created_at"]),
        review_id=row["review_id"],
        outcome=row["outcome"],
    )


class TraceStore:
    def __init__(self, stores):
        self.stores = stores
        self.table = sql.Identifier(stores.trace_schema, "trace_events")

    def append_event(self, **fields):
        """Insert one trace event. Updates and deletes are rejected by triggers."""
        event = {name: fields.get(name) for name in TRACE_COLUMNS}
        missing = [name for name in ("trace_id", "span_id", "step", "actor", "status") if not event[name]]
        if missing:
            raise ValueError("missing trace fields: " + ", ".join(missing))
        event["event_id"] = event["event_id"] or str(uuid.uuid4())
        event["started_at"] = event["started_at"] or utc_now()
        assert_no_restricted({key: value for key, value in event.items() if value is not None})
        query = sql.SQL("INSERT INTO {} ({}) VALUES ({}) RETURNING *").format(
            self.table,
            sql.SQL(", ").join(sql.Identifier(name) for name in TRACE_COLUMNS),
            sql.SQL(", ").join(sql.Placeholder() for _ in TRACE_COLUMNS),
        )
        with self.stores.conn.transaction():
            row = self.stores.conn.execute(query, tuple(event[name] for name in TRACE_COLUMNS)).fetchone()
        return _event_from_row(row)

    def get_event(self, event_id):
        query = sql.SQL("SELECT * FROM {} WHERE event_id = %s").format(self.table)
        with self.stores.conn.transaction():
            row = self.stores.conn.execute(query, (event_id,)).fetchone()
        return None if row is None else _event_from_row(row)

    def column_names(self):
        with self.stores.conn.transaction():
            rows = self.stores.conn.execute(
                """
                SELECT column_name FROM information_schema.columns
                WHERE table_schema = %s AND table_name = 'trace_events'
                ORDER BY ordinal_position
                """,
                (self.stores.trace_schema,),
            ).fetchall()
        return tuple(row["column_name"] for row in rows)


def _event_from_row(row):
    event = {name: row[name] for name in TRACE_COLUMNS}
    event["started_at"] = _as_iso(event["started_at"])
    return event
