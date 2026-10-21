"""Tests for the policy server (Step 2).

Run: uv run --locked pytest -q tests/test_policy_server.py

Spins up the real mock (tools/runtime.py) in-process on a free port with a temp copy of
the dev dataset, so the tool is exercised over HTTP exactly as in production. Two cases in
the temp dataset get policy faults injected (dev fixtures only fault `claims`).
"""
import asyncio
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "src"))

import runtime  # noqa: E402
from fnol_foundation.stores import Stores  # noqa: E402
from fnol_policy.fetch import PolicyAttempt, PolicyFetchResult, fetch_policy  # noqa: E402
from fnol_policy.pipeline import start_policy  # noqa: E402
from fnol_policy.select import choose_version, decide  # noqa: E402
from fnol_policy.service import decision_from_store, run_policy  # noqa: E402
from fnol_rules.pipeline import policy_result_for, start_routing  # noqa: E402
from fnol_rules.claims import ClaimsAttempt, ClaimsFetchResult  # noqa: E402
from fnol_rules.types import ClaimsSnapshot  # noqa: E402

TS = "2026-10-01T12:00:00Z"
TRANSIENT_CASE = "AUTO-D02"   # 503 twice, 200 on third attempt
PERSISTENT_CASE = "AUTO-D03"  # 503 forever
PROCEDURES = [{"source_id": s, "sha256": "x"} for s in
              ("AUTO-TRIAGE-01", "AUTO-WORDING-V1", "AUTO-WORDING-V2", "AUTO-END-GLASS-01")]


def _revision(case_id, ts=TS, **extra):
    base = {"loss_type": "collision", "vehicle_id": f"VEH-{case_id[-3:]}", "incident_timestamp": ts,
            "driver_name": "A", "driver_name_supplied": True, "incident_location": "B",
            "incident_location_supplied": True, "injury_reported": False, "vehicle_drivable": True,
            "referral_indicator": "none", "loss_reference": f"loss-{case_id}"}
    base.update(extra)
    return base


class ChooseVersionTests(unittest.TestCase):
    """Pure interval rule: effective_from inclusive, effective_to exclusive."""

    V1 = {"version": "1", "effective_from": "2026-01-01T00:00:00Z",
          "effective_to": "2026-09-01T00:00:00Z", "wording_source": "AUTO-WORDING-V1", "endorsements": []}
    V2 = {"version": "2", "effective_from": "2026-09-01T00:00:00Z",
          "effective_to": "2027-01-01T00:00:00Z", "wording_source": "AUTO-WORDING-V2", "endorsements": []}

    def test_one_match(self):
        row, reason = choose_version([self.V1, self.V2], TS)
        self.assertEqual((row["version"], reason), ("2", "one"))

    def test_start_is_inclusive(self):
        row, reason = choose_version([self.V1, self.V2], "2026-09-01T00:00:00Z")
        self.assertEqual((row["version"], reason), ("2", "one"))

    def test_end_is_exclusive(self):
        row, reason = choose_version([self.V1, self.V2], "2026-08-31T23:59:59Z")
        self.assertEqual((row["version"], reason), ("1", "one"))

    def test_zero_at_final_boundary(self):
        row, reason = choose_version([self.V1, self.V2], "2027-01-01T00:00:00Z")
        self.assertEqual((row, reason), (None, "zero"))

    def test_multiple_overlapping(self):
        reissue = {**self.V2, "version": "2-reissue"}
        row, reason = choose_version([self.V1, self.V2, reissue], TS)
        self.assertEqual((row, reason), (None, "multiple"))

    def test_empty_list_is_zero(self):
        self.assertEqual(choose_version([], TS), (None, "zero"))

    def test_decide_builds_policy_ids(self):
        out = decide({"policies": [self.V1, self.V2]}, TS, {"AUTO-TRIAGE-01", "AUTO-WORDING-V2"})
        self.assertEqual(out["policy_ids"], ["AUTO-TRIAGE-01", "AUTO-WORDING-V2"])
        self.assertEqual(out["reason"], "one")

    def test_decide_wording_missing(self):
        out = decide({"policies": [self.V1, self.V2]}, TS, {"AUTO-TRIAGE-01"})
        self.assertEqual(out["reason"], "wording_missing")
        self.assertEqual(out["selected_policy_version"], "2")  # version kept, wording not cited
        self.assertEqual(out["policy_ids"], ["AUTO-TRIAGE-01"])
        self.assertEqual(out["missing_sources"], ["AUTO-WORDING-V2"])

    def test_decide_null_version_cites_only_procedure(self):
        out = decide({"policies": [self.V1, self.V2]}, "2027-01-01T00:00:00Z", set())
        self.assertIsNone(out["selected_policy_version"])
        self.assertEqual(out["policy_ids"], ["AUTO-TRIAGE-01"])
        self.assertNotIn("wording_source", out)


class FetchTests(unittest.TestCase):
    def test_connection_failure_is_three_attempts_then_unavailable(self):
        calls = []

        def dead(url):
            calls.append(url)
            return None, None, "connection_failed"

        res = fetch_policy("AUTO-D01", "http://127.0.0.1:1", get=dead)
        self.assertEqual(res.status, "unavailable")
        self.assertEqual(len(calls), 3)
        self.assertEqual([a.status for a in res.attempts], [None, None, None])

    def test_500_is_retried_not_raised(self):
        seq = iter([(500, {}, "http_500"), (200, {"policies": []}, None)])
        res = fetch_policy("AUTO-D01", "http://x", get=lambda url: next(seq))
        self.assertEqual((res.status, len(res.attempts)), ("ok", 2))

    def test_404_is_final(self):
        res = fetch_policy("NOPE", "http://x", get=lambda url: (404, {"error": "not_found"}, "not_found"))
        self.assertEqual((res.status, len(res.attempts)), ("not_found", 1))


class SelectPolicyTests(unittest.TestCase):
    """End-to-end against the real mock over HTTP, with an isolated state directory."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="policy-test-"))
        data_dir = cls.tmp / "data"
        data_dir.mkdir()
        dataset = json.loads((ROOT / "data" / "dev" / "dataset.json").read_text())
        for case in dataset["cases"]:
            if case["case_id"] == TRANSIENT_CASE:
                case["faults"] = {"policy": {"failures": 2}}
            if case["case_id"] == PERSISTENT_CASE:
                case["faults"] = {"policy": {"failures": "always"}}
        (data_dir / "dataset.json").write_text(json.dumps(dataset))

        cls.mock_state = cls.tmp / "mock.sqlite"
        cls.server = runtime.create_server(data_dir, cls.mock_state, port=0)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.mock_url = f"http://127.0.0.1:{cls.port}"

        cls.state = cls.tmp / "state"
        stores = Stores(cls.state)
        stores.input.store_procedures(PROCEDURES)
        for cid in ("AUTO-D01", "AUTO-D02", "AUTO-D03", "AUTO-D05", "AUTO-D09", "AUTO-D10"):
            stores.input.append_revision(cid, _revision(cid), document_set_sha256=f"sha-{cid}")
        stores.input.append_revision("AUTO-D06", _revision("AUTO-D06", ts="2027-01-01T00:00:00Z"), document_set_sha256="sha-D06")
        stores.input.append_revision("AUTO-D12", _revision("AUTO-D12", ts="2026-08-31T23:59:59Z"), document_set_sha256="sha-D12")

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _run(self, case_id, **kw):
        stores = Stores(self.state)
        try:
            return run_policy(case_id, stores, base_url=self.mock_url, **kw)
        finally:
            stores.close()

    def _assert_clean(self, out):
        blob = json.dumps(out)
        self.assertNotIn("private_token", blob)
        self.assertNotIn("SYNTHETIC-PRIVATE-", blob)
        self.assertNotIn("policies", out)

    def _snapshot(self, case_id):
        with sqlite3.connect(self.state / "input.sqlite") as db:
            row = db.execute("SELECT raw_json FROM tool_payloads WHERE case_id=? AND tool='policy'",
                             (case_id,)).fetchone()
        return row[0] if row else None

    def _trace(self, case_id):
        with sqlite3.connect(self.state / "trace.sqlite") as db:
            db.row_factory = sqlite3.Row
            return [dict(r) for r in db.execute(
                "SELECT * FROM trace_events WHERE case_id=? AND actor='policy' ORDER BY rowid", (case_id,))]

    def test_single_version_selected(self):
        out = self._run("AUTO-D01")
        self._assert_clean(out)
        self.assertEqual(out["selected_policy_version"], "2")
        self.assertEqual(out["reason"], "one")
        self.assertEqual(out["wording_source"], "AUTO-WORDING-V2")
        self.assertEqual(out["endorsements"], [])
        self.assertEqual(out["policy_ids"], ["AUTO-TRIAGE-01", "AUTO-WORDING-V2"])
        self.assertEqual(out["policy_number"], "PA-D01")
        self.assertEqual(out["vehicle_id"], "VEH-D01")
        self.assertEqual(out["source_id"], "AUTO-D01-POLICY")
        self.assertEqual(out["input_revision"], 1)

    def test_timestamp_comes_from_revision_not_argument(self):
        out = self._run("AUTO-D12", incident_timestamp=TS)  # argument says v2 window; revision says v1
        self.assertEqual((out["selected_policy_version"], out["wording_source"]), ("1", "AUTO-WORDING-V1"))

    def test_zero_match_returns_null(self):
        out = self._run("AUTO-D06")
        self._assert_clean(out)
        self.assertIsNone(out["selected_policy_version"])
        self.assertEqual(out["reason"], "zero")
        self.assertEqual(out["policy_ids"], ["AUTO-TRIAGE-01"])
        self.assertNotIn("wording_source", out)

    def test_multiple_match_returns_null(self):
        out = self._run("AUTO-D05")
        self._assert_clean(out)
        self.assertIsNone(out["selected_policy_version"])
        self.assertEqual(out["reason"], "multiple")
        self.assertEqual(out["policy_ids"], ["AUTO-TRIAGE-01"])

    def test_endorsements_passed_through(self):
        out = self._run("AUTO-D09")
        self.assertEqual(out["endorsements"], ["AUTO-END-GLASS-01"])
        self.assertEqual(out["policy_ids"], ["AUTO-TRIAGE-01", "AUTO-WORDING-V2", "AUTO-END-GLASS-01"])

    def test_snapshot_is_canonical_and_token_free(self):
        self._run("AUTO-D01")
        raw = self._snapshot("AUTO-D01")
        self.assertIsNotNone(raw)
        self.assertNotIn("private_token", raw)
        self.assertNotIn("SYNTHETIC-PRIVATE-", raw)
        self.assertEqual(raw, runtime.canonical(json.loads(raw)))
        self.assertIn('"policies":[', raw)  # full history kept for citations

    def test_trace_has_one_event_per_attempt_plus_decision(self):
        self._run(TRANSIENT_CASE)
        events = self._trace(TRANSIENT_CASE)
        attempts = [e for e in events if e["attempt"] is not None]
        self.assertEqual([e["mock_http_status"] for e in attempts], [503, 503, 200])
        self.assertEqual([e["error_code"] for e in attempts][:2], ["upstream_timeout", "upstream_timeout"])
        decision = [e for e in events if e["attempt"] is None]
        self.assertEqual(len(decision), 1)
        self.assertEqual(decision[0]["step"], "2")
        self.assertEqual(decision[0]["input_revision"], 1)
        self.assertEqual(decision[0]["input_sha256"], f"sha-{TRANSIENT_CASE}")
        self.assertIsNotNone(decision[0]["output_sha256"])
        blob = json.dumps(events)
        self.assertNotIn("SYNTHETIC-PRIVATE-", blob)

    def test_transient_fault_succeeds_on_third_attempt(self):
        out = self._run(TRANSIENT_CASE)  # counter already past the faults from the trace test or fresh
        self.assertEqual((out["selected_policy_version"], out["reason"]), ("2", "one"))

    def test_persistent_fault_stops_after_three_attempts(self):
        out = self._run(PERSISTENT_CASE)
        self.assertEqual(out["reason"], "unavailable")
        self.assertIsNone(out["selected_policy_version"])
        self.assertEqual(out["attempts"], 3)
        self.assertEqual(out["policy_ids"], ["AUTO-TRIAGE-01"])
        self.assertIsNone(self._snapshot(PERSISTENT_CASE))
        with sqlite3.connect(self.mock_state) as db:
            n = db.execute("SELECT n FROM calls WHERE case_id=? AND tool='policy'",
                           (PERSISTENT_CASE,)).fetchone()[0]
        self.assertEqual(n, 3, "mock must have seen exactly three attempts, never a fourth")

    def test_rules_reads_per_case_decision_from_store(self):
        self._run("AUTO-D01")
        self._run("AUTO-D06")
        stores = Stores(self.state)
        d01 = policy_result_for(stores, "AUTO-D01")
        d06 = policy_result_for(stores, "AUTO-D06")
        d03 = policy_result_for(stores, PERSISTENT_CASE)  # no snapshot stored
        self.assertEqual((d01.selected_policy_version, d01.policy_available), ("2", True))
        self.assertEqual((d06.selected_policy_version, d06.policy_available), (None, True))
        self.assertEqual((d03.selected_policy_version, d03.policy_available), (None, False))
        self.assertEqual(decision_from_store(stores, "AUTO-D01")["policy_ids"], ["AUTO-TRIAGE-01", "AUTO-WORDING-V2"])

        def claims_ok(case_id, base_url, **_kw):
            raw = {"source_id": f"{case_id}-CLAIMS", "existing_claims": [], "intake_deliveries": 1,
                   "loss_reference": f"loss-{case_id}"}
            return ClaimsFetchResult(snapshot=ClaimsSnapshot(available=True, intake_deliveries=1),
                                     attempts=(ClaimsAttempt(1, 200, raw),), raw_json=raw)

        routes = {r["case_id"]: r["route"] for r in start_routing(
            mock_url=self.mock_url, state_dir_path=self.state, fetch=claims_ok)["routes"]}
        self.assertEqual(routes["AUTO-D01"], "standard")
        self.assertEqual(routes["AUTO-D06"], "manual_review")   # zero intervals
        self.assertEqual(routes[PERSISTENT_CASE], "manual_review")  # policy service unavailable

    def test_exposed_over_mcp_stdio(self):
        """The tool is reachable through a real MCP client; result shape matches direct call."""
        from mcp.client import Client
        from mcp.client.stdio import StdioServerParameters

        params = StdioServerParameters(
            command=sys.executable, args=[str(ROOT / "server" / "policy_server.py")],
            env={**os.environ, "FNOL_MOCK_URL": self.mock_url, "FNOL_STATE_DIR": str(self.state)})

        async def go():
            async with Client(params) as client:
                names = [t.name for t in (await client.list_tools()).tools]
                res = await client.call_tool("select_policy", {"case_id": "AUTO-D09"})
                return names, res

        names, res = asyncio.run(go())
        self.assertEqual(names, ["select_policy"])
        self.assertFalse(res.is_error)
        out = res.structured_content or json.loads(res.content[0].text)
        decision = out["decisions"][0]
        self._assert_clean(decision)
        self.assertEqual(decision["selected_policy_version"], "2")
        self.assertEqual(decision["endorsements"], ["AUTO-END-GLASS-01"])


if __name__ == "__main__":
    unittest.main()
