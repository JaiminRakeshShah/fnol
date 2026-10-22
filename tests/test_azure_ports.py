"""Unit tests for Blob and Azure SQL switches. No live Azure required."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fnol_foundation import azure_sql, blobs
from fnol_foundation.stores import Stores
from fnol_intake.parse import load_procedures, read_source


ROOT = Path(__file__).resolve().parents[1]
DEV_DOCS = ROOT / "data" / "dev" / "documents"
DEV_POLICIES = ROOT / "data" / "dev" / "policies"


class BlobDiskFallbackTests(unittest.TestCase):
    def test_disk_read_source_unchanged(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("FNOL_BLOB_ACCOUNT", None)
            found = read_source(DEV_DOCS, "AUTO-D01-INTAKE")
        self.assertIsNotNone(found)
        path, data, text = found
        self.assertTrue(str(path).endswith("AUTO-D01-INTAKE.md"))
        self.assertIn("Policy number", text)
        self.assertEqual(data.decode("utf-8"), text)

    def test_disk_load_procedures(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("FNOL_BLOB_ACCOUNT", None)
            sources = load_procedures(DEV_POLICIES)
        ids = {row["source_id"] for row in sources}
        self.assertIn("AUTO-WORDING-V1", ids)
        self.assertTrue(all(row["sha256"] for row in sources))

    def test_blob_enabled_routes_to_blob_reader(self):
        with mock.patch.dict(os.environ, {"FNOL_BLOB_ACCOUNT": "acct"}, clear=False):
            with mock.patch.object(
                blobs,
                "_read_blob",
                return_value=("azure-blob://case-documents/X.md", b"hi", "hi"),
            ) as reader:
                found = read_source(DEV_DOCS, "X")
        self.assertEqual(found[2], "hi")
        reader.assert_called_once_with("case-documents", "X.md")

    def test_container_for_maps_directories(self):
        self.assertEqual(blobs.container_for(DEV_DOCS), "case-documents")
        self.assertEqual(blobs.container_for(DEV_POLICIES), "policy-wording")


class AzureSQLConfigTests(unittest.TestCase):
    def test_sql_disabled_by_default(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("FNOL_SQL_SERVER", None)
            self.assertFalse(azure_sql.sql_enabled())

    def test_schema_for_path(self):
        self.assertEqual(azure_sql.schema_for_path(".state/input.sqlite"), "input")
        self.assertEqual(azure_sql.schema_for_path("/tmp/output.sqlite"), "output")
        self.assertEqual(azure_sql.schema_for_path("mock.sqlite"), "enterprise")

    def test_sqlite_stores_still_work(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("FNOL_SQL_SERVER", None)
            with tempfile.TemporaryDirectory() as tmp:
                stores = Stores(tmp)
                rev = stores.input.append_revision(
                    "CASE-T",
                    {
                        "policy_number": "PA-T",
                        "incident_timestamp": "2026-01-01T00:00:00Z",
                        "vehicle_id": "VEH-T",
                        "loss_type": "collision",
                    },
                )
                self.assertEqual(rev.case_id, "CASE-T")
                self.assertEqual(rev.revision, 1)


if __name__ == "__main__":
    unittest.main()
