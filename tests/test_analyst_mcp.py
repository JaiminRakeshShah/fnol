"""Stdio MCP client: timeouts and stderr on a stalled child."""

import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fnol_analyst.mcp import ServerError, StdioServer


class McpClientTests(unittest.TestCase):
    def test_timeout_includes_stderr_from_a_hanging_child(self):
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "hang.py"
            script.write_text(textwrap.dedent("""\
                import json
                import sys
                import time

                sys.stderr.write("child-ready\\n")
                sys.stderr.flush()
                for line in sys.stdin:
                    message = json.loads(line)
                    method = message.get("method")
                    if method == "initialize":
                        print(json.dumps({
                            "jsonrpc": "2.0",
                            "id": message["id"],
                            "result": {"serverInfo": {"name": "hang"}, "capabilities": {}},
                        }), flush=True)
                    elif method == "notifications/initialized":
                        continue
                    else:
                        time.sleep(60)
            """))
            server = StdioServer(
                "hang",
                [sys.executable, str(script)],
                timeout=0.4,
            )
            try:
                with self.assertRaises(ServerError) as caught:
                    server.list_tools()
                message = str(caught.exception)
                self.assertIn("timed out", message)
                self.assertIn("child-ready", message)
            finally:
                server.close()


if __name__ == "__main__":
    unittest.main()
