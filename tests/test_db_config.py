"""Config resolution and SQL helpers. No database required."""

import os
import unittest
from pathlib import Path
from unittest import mock

from fnol_foundation.db import _qmark_to_pyformat, database_url, namespace_suffix, schema_name
from fnol_foundation.migrate import split_sql


class DatabaseUrlTests(unittest.TestCase):
    def test_unset_means_sqlite(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("FNOL_DATABASE_URL", None)
            os.environ.pop("FNOL_DB_SECRET_ARN", None)
            os.environ.pop("FNOL_RDS_HOST", None)
            self.assertIsNone(database_url())

    def test_explicit_url_wins(self):
        with mock.patch.dict(
            os.environ,
            {"FNOL_DATABASE_URL": "postgresql://fnol:fnol@localhost/fnol", "FNOL_RDS_HOST": "other"},
            clear=False,
        ):
            self.assertEqual(database_url(), "postgresql://fnol:fnol@localhost/fnol")


class NamespaceTests(unittest.TestCase):
    def test_shared_uses_canonical_schema_names(self):
        with mock.patch.dict(os.environ, {"FNOL_PG_NAMESPACE": "shared"}, clear=False):
            self.assertEqual(namespace_suffix(Path("/tmp/state")), "")
            self.assertEqual(schema_name("input", Path("/tmp/state")), "input")

    def test_isolate_depends_on_the_anchor(self):
        with mock.patch.dict(os.environ, {"FNOL_PG_NAMESPACE": "isolate"}, clear=False):
            one = schema_name("trace", Path("/tmp/a"))
            two = schema_name("trace", Path("/tmp/b"))
            self.assertNotEqual(one, two)
            self.assertTrue(one.startswith("trace_"))


class SqlHelperTests(unittest.TestCase):
    def test_placeholders_skip_string_literals(self):
        self.assertEqual(_qmark_to_pyformat("SELECT '?' , ?"), "SELECT '?' , %s")

    def test_split_keeps_dollar_quotes(self):
        script = "CREATE FUNCTION f() RETURNS void AS $$\nBEGIN\n  PERFORM 1;\nEND;\n$$;\nSELECT 1;\n"
        parts = split_sql(script)
        self.assertEqual(len(parts), 2)
        self.assertIn("PERFORM 1;", parts[0])
        self.assertEqual(parts[1], "SELECT 1")


if __name__ == "__main__":
    unittest.main()
