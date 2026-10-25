"""Reviewer HTTP boundary. Local role header stands in for Easy Auth."""

from __future__ import annotations

import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from server.reviewer import create_server
from tools.runtime import connect


class ReviewerHttpTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = Path(self.tmp.name) / "mock.sqlite"
        with connect(self.state) as db:
            db.execute(
                "INSERT INTO reviews (id, case_id, draft, hash, status, reviewer) VALUES (?,?,?,?,?,?)",
                ("rev_1", "AUTO-D01", "{}", "abc", "pending", None),
            )
        self.server = create_server(host="127.0.0.1", port=0, state=self.state)
        # Disable role check for one path test via env on the handler — create_server
        # reads FNOL_REVIEWER_REQUIRE_ROLE at construction time.
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.host, self.port = self.server.server_address[:2]
        self.base = f"http://{self.host}:{self.port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.tmp.cleanup()

    def _request(self, method, path, roles="Claims.Reviewer", reviewer="alice"):
        headers = {"Accept": "application/json"}
        if roles is not None:
            headers["X-Fnol-Roles"] = roles
        if reviewer is not None:
            headers["X-Fnol-Reviewer"] = reviewer
        req = urllib.request.Request(self.base + path, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = json.loads(exc.read().decode("utf-8"))
            return exc.code, body

    def test_forbidden_without_role(self):
        status, body = self._request("GET", "/v1/pending", roles="")
        self.assertEqual(status, 403)
        self.assertEqual(body["error"], "forbidden")

    def test_pending_and_approve(self):
        status, rows = self._request("GET", "/v1/pending")
        self.assertEqual(status, 200)
        self.assertEqual(len(rows), 1)
        status, body = self._request("POST", "/v1/approve/rev_1")
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "approved")
        self.assertEqual(body["reviewer"], "alice")
        with connect(self.state) as db:
            row = db.execute("SELECT status, reviewer FROM reviews WHERE id=?", ("rev_1",)).fetchone()
        self.assertEqual(row["status"], "approved")
        self.assertEqual(row["reviewer"], "alice")


if __name__ == "__main__":
    unittest.main()
