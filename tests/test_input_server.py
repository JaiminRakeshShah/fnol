"""The input MCP server accepts one call and the pipeline writes input.sqlite."""

import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from server.input_server import handle, serve
from fnol_intake.pipeline import start_ingestion

DEV_DOCUMENTS = ROOT / "data" / "dev" / "documents"
DEV_POLICIES = ROOT / "data" / "dev" / "policies"


def _transport(health, cases):
    def fetch(url):
        if url.endswith("/health"):
            return health
        if url.endswith("/v1/cases"):
            return cases
        raise AssertionError(url)

    return fetch


class InputServerTests(unittest.TestCase):
    def test_client_lists_one_start_tool(self):
        listed = handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        tools = listed["result"]["tools"]
        self.assertEqual([tool["name"] for tool in tools], ["start_ingestion"])
        self.assertEqual(tools[0]["inputSchema"]["properties"], {})

    def test_start_call_returns_the_sqlite_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            summary = start_ingestion(
                mock_url="http://mock",
                documents_dir=DEV_DOCUMENTS,
                policies_dir=DEV_POLICIES,
                state_dir_path=tmp,
                transport=_transport(
                    (200, {"status": "ok"}),
                    (200, {"cases": [{
                        "case_id": "AUTO-D01",
                        "intake_source": "AUTO-D01-INTAKE",
                        "documents": ["AUTO-D01-INTAKE", "AUTO-D01-ESTIMATE", "AUTO-D01-REPORT"],
                    }]}),
                ),
            )
            self.assertTrue(Path(summary["input_sqlite"]).is_file())
            self.assertEqual(summary["case_count"], 1)
            self.assertEqual(summary["duplicate_count"], 0)
            self.assertEqual(summary["revisions"], [{"case_id": "AUTO-D01", "revision": 1}])

    def test_stdio_call_uses_the_pipeline(self):
        import server.input_server as mcp_server

        original = mcp_server.start_ingestion
        mcp_server.start_ingestion = lambda: {"input_sqlite": "/state/input.sqlite", "case_count": 12, "revisions": []}
        try:
            incoming = io.StringIO(
                "\n".join([
                    json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}),
                    json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
                    json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "start_ingestion", "arguments": {}}}),
                ]) + "\n"
            )
            outgoing = io.StringIO()
            serve(stdin=incoming, stdout=outgoing)
        finally:
            mcp_server.start_ingestion = original
        lines = [json.loads(line) for line in outgoing.getvalue().splitlines()]
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[0]["result"]["serverInfo"]["name"], "fnol-input")
        body = json.loads(lines[1]["result"]["content"][0]["text"])
        self.assertEqual(body["input_sqlite"], "/state/input.sqlite")
        self.assertFalse(lines[1]["result"]["isError"])


if __name__ == "__main__":
    unittest.main()
