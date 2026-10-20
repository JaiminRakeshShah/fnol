"""Acceptance checks for the Postgres input, output, and trace schemas."""

import sys
import unittest
import uuid
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from fnol_foundation import RestrictedValueError, Stores, TRACE_COLUMNS, canonical, digest
from fnol_foundation.stores import database_url
from tools.runtime import canonical as mock_canonical
from tools.runtime import digest as mock_digest


class CanonicalTests(unittest.TestCase):
    def test_matches_mock_runtime(self):
        value = {"b": 1, "a": "café", "nested": {"z": None, "y": [3, 2]}, "flag": False}
        self.assertEqual(canonical(value), mock_canonical(value))
        self.assertEqual(digest(value), mock_digest(value))
        self.assertEqual(canonical(value), '{"a":"café","b":1,"flag":false,"nested":{"y":[3,2],"z":null}}')


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.stores = Stores(database_url(), prefix="t" + uuid.uuid4().hex[:8])

    def tearDown(self):
        self.stores.drop()
        self.stores.close()

    def test_creates_the_three_postgres_schemas(self):
        with self.stores.conn.transaction():
            rows = self.stores.conn.execute(
                "SELECT nspname FROM pg_namespace WHERE nspname = ANY(%s) ORDER BY nspname",
                (list(self.stores.schema_names),),
            ).fetchall()
        self.assertEqual([row["nspname"] for row in rows], sorted(self.stores.schema_names))
        self.assertTrue(self.stores.input_schema.endswith("input"))
        self.assertTrue(self.stores.output_schema.endswith("output"))
        self.assertTrue(self.stores.trace_schema.endswith("trace"))

    def test_reingest_increments_revision_and_keeps_the_prior_row(self):
        first = self.stores.input.append_revision("AUTO-D01", {"loss_type": "collision"}, "sha-a", "2026-10-01T00:00:00+00:00")
        second = self.stores.input.append_revision("AUTO-D01", {"loss_type": "collision"}, "sha-b", "2026-10-01T01:00:00+00:00")
        self.assertEqual(first.revision, 1)
        self.assertEqual(second.revision, 2)
        self.assertEqual(second.document_set_sha256, "sha-b")
        self.assertEqual(self.stores.input.get_revision("AUTO-D01").payload, {"loss_type": "collision"})
        self.assertEqual(self.stores.input.get_revision("AUTO-D01", 1).document_set_sha256, "sha-a")

    def test_unique_case_revision_is_enforced(self):
        self.stores.input.append_revision("AUTO-D01", {"n": 1})
        with self.assertRaises(psycopg.errors.UniqueViolation):
            with self.stores.conn.transaction():
                self.stores.conn.execute(
                    psycopg.sql.SQL(
                        """INSERT INTO {}
                           (case_id, revision, ingested_at, document_set_sha256, payload_json)
                           VALUES ('AUTO-D01', 1, NOW(), 'sha', '{{}}')"""
                    ).format(self.stores.input.table)
                )

    def test_input_revisions_cannot_be_updated_or_deleted(self):
        self.stores.input.append_revision("AUTO-D01", {"n": 1})
        with self.assertRaises(psycopg.errors.RaiseException):
            with self.stores.conn.transaction():
                self.stores.conn.execute(
                    psycopg.sql.SQL("UPDATE {} SET payload_json = '{{}}'").format(self.stores.input.table)
                )
        with self.assertRaises(psycopg.errors.RaiseException):
            with self.stores.conn.transaction():
                self.stores.conn.execute(psycopg.sql.SQL("DELETE FROM {}").format(self.stores.input.table))

    def test_document_hash_defaults_to_payload_digest(self):
        payload = {"vehicle_id": "VEH-D01"}
        row = self.stores.input.append_revision("AUTO-D01", payload)
        self.assertEqual(row.document_set_sha256, digest(payload))

    def test_trace_columns_match_the_agreed_schema(self):
        self.assertEqual(self.stores.trace.column_names(), TRACE_COLUMNS)

    def test_trace_is_append_only(self):
        event = self.stores.trace.append_event(
            trace_id="trace-1",
            span_id="span-1",
            step="1",
            actor="intake",
            status="ok",
            case_id="AUTO-D01",
            input_revision=1,
            started_at="2026-10-01T00:00:00+00:00",
            duration_ms=12,
        )
        self.assertEqual(event["step"], "1")
        self.assertEqual(event["duration_ms"], 12)
        with self.assertRaises(psycopg.errors.RaiseException):
            with self.stores.conn.transaction():
                self.stores.conn.execute(
                    psycopg.sql.SQL("UPDATE {} SET status = 'changed'").format(self.stores.trace.table)
                )
        with self.assertRaises(psycopg.errors.RaiseException):
            with self.stores.conn.transaction():
                self.stores.conn.execute(psycopg.sql.SQL("DELETE FROM {}").format(self.stores.trace.table))

    def test_draft_hash_matches_the_mock_and_body_stays_fixed(self):
        draft = {"case_id": "AUTO-D01", "summary": "Draft FNOL for human handler."}
        record = self.stores.output.record_draft("AUTO-D01", draft, input_revision=1, draft_id="draft_test")
        self.assertEqual(record.draft_hash, mock_digest(draft))
        updated = self.stores.output.update_status("draft_test", "pending", review_id="rev_1", outcome=None)
        self.assertEqual(updated.status, "pending")
        self.assertEqual(updated.review_id, "rev_1")
        self.assertEqual(updated.draft_hash, record.draft_hash)
        with self.assertRaises(psycopg.errors.RaiseException):
            with self.stores.conn.transaction():
                self.stores.conn.execute(
                    psycopg.sql.SQL("UPDATE {} SET draft_json = '{{}}' WHERE draft_id = 'draft_test'").format(
                        self.stores.output.table
                    )
                )

    def test_restricted_markers_are_refused(self):
        with self.assertRaises(RestrictedValueError):
            self.stores.input.append_revision("AUTO-D01", {"private_token": "secret"})
        with self.assertRaises(RestrictedValueError):
            self.stores.output.record_draft("AUTO-D01", {"note": "SYNTHETIC-PRIVATE-AUTO-D01"})
        with self.assertRaises(RestrictedValueError):
            self.stores.trace.append_event(
                trace_id="t",
                span_id="s",
                step="7",
                actor="shadow",
                status="ok",
                shadow_narrative="token SYNTHETIC-PRIVATE-AUTO-D01",
            )


if __name__ == "__main__":
    unittest.main()
