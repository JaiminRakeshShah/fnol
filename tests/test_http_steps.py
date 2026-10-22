"""HTTP step server and analyst transport switch."""

from __future__ import annotations

import json
import os
import threading
import unittest
from http.server import ThreadingHTTPServer
from unittest import mock

from fnol_analyst.http_steps import HttpStepClient
from fnol_analyst.servers import http_transport
from server.http_serve import create_server


class HttpStepServerTests(unittest.TestCase):
    def test_health_and_tool_post(self):
        def fake_policy(case_id=None):
            return {"case_count": 1, "policies": [{"case_id": case_id or "ALL", "ok": True}]}

        server = create_server("policy", {"start_policy": fake_policy}, host="127.0.0.1", port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        host, port = server.server_address[:2]
        try:
            client = HttpStepClient("policy", f"http://{host}:{port}")
            summary = client.call("start_policy", {"case_id": "AUTO-D01"})
            self.assertEqual(summary["policies"][0]["case_id"], "AUTO-D01")
        finally:
            server.shutdown()
            server.server_close()

    def test_http_transport_flag(self):
        with mock.patch.dict(os.environ, {"FNOL_STEP_TRANSPORT": "http"}, clear=False):
            self.assertTrue(http_transport())
        with mock.patch.dict(os.environ, {"FNOL_STEP_TRANSPORT": ""}, clear=False):
            os.environ.pop("FNOL_STEP_TRANSPORT", None)
            self.assertFalse(http_transport())


if __name__ == "__main__":
    unittest.main()
