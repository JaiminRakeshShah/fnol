"""Harborlight FNOL Desk: sessions, team gates, and hash-bound accept/reject."""

from __future__ import annotations

import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.cookiejar import CookieJar
from pathlib import Path

from fnol_analyst.draft import build_draft
from fnol_desk.actions import accept_review, reject_review, send_to_handlers
from fnol_desk.auth import (
    AuthError,
    ensure_seeded,
    login,
    user_from_session,
)
from fnol_desk.server import create_server
from fnol_desk.view import case_view
from fnol_foundation.canonical import canonical
from fnol_foundation.stores import Stores
from tools.runtime import connect as mock_connect
from tools.runtime import create_server as create_mock_server


def _facts(**kw):
    base = {
        "policy_number": "PA-D01",
        "incident_timestamp": "2026-10-01T12:00:00Z",
        "vehicle_id": "VEH-D01",
        "loss_type": "collision",
        "referral_indicator": "none",
        "driver_name": "Alex Rowan",
        "incident_location": "Cedar Street",
    }
    base.update(kw)
    return base


def _route(**kw):
    base = {
        "classification": "collision",
        "route": "standard",
        "route_rule": "AUTO-TRIAGE-01",
        "missing_information": [],
        "duplicate_delivery": False,
        "injury_reported": False,
        "vehicle_drivable": True,
        "selected_policy_version": "2",
        "claims_available": True,
        "reasons": [],
        "conflicts": [],
    }
    base.update(kw)
    return base


def _policy(**kw):
    base = {
        "policy_ids": ["AUTO-TRIAGE-01", "AUTO-WORDING-V2"],
        "reason": "matched",
        "selected_policy_version": "2",
        "policy_available": True,
    }
    base.update(kw)
    return base


def _citations():
    return {
        "policy_ids": ["AUTO-TRIAGE-01", "AUTO-WORDING-V2"],
        "citations": [
            {
                "claim": "incident_evidence",
                "source_id": "AUTO-D01-INTAKE",
                "quote": "The car struck a roadside post.",
            }
        ],
        "omissions": [],
    }


def _seed_case(stores: Stores, case_id: str = "AUTO-D01", *, evidence_summary=None, safety_status="skipped"):
    revision = stores.input.append_revision(case_id, _facts())
    route = _route()
    policy = _policy()
    citations = _citations()
    stores.input.put_decision(case_id, revision.revision, "policy", policy)
    stores.input.put_decision(case_id, revision.revision, "route", route)
    stores.input.put_decision(case_id, revision.revision, "citations", citations)
    draft = build_draft(
        case_id=case_id,
        input_revision=revision.revision,
        facts_row=_facts(),
        policy=policy,
        route=route,
        citations=citations,
        evidence_summary=evidence_summary,
        safety_status=safety_status,
    )
    record = stores.output.record_draft(
        case_id, draft, input_revision=revision.revision, draft_id=f"draft_{case_id.lower()}"
    )
    return record, draft


class DeskAuthUnitTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.state_dir = self.root / "state"
        self.auth_path = ensure_seeded(self.state_dir / "desk.sqlite")
        self.stores = Stores(self.state_dir)
        self.mock_state = self.root / "mock.sqlite"
        # Initialize mock schema
        mock_connect(self.mock_state).close()

    def tearDown(self):
        self.tmp.cleanup()

    def test_login_and_session(self):
        user, token = login("achen", "handler-desk", path=self.auth_path)
        self.assertEqual(user.team, "handlers")
        self.assertEqual(user.display_name, "Avery Chen")
        again = user_from_session(token, path=self.auth_path)
        self.assertIsNotNone(again)
        self.assertEqual(again.username, "achen")
        with self.assertRaises(AuthError):
            login("achen", "wrong", path=self.auth_path)

    def test_analyst_and_security_cannot_accept(self):
        record, draft = _seed_case(self.stores)
        with mock_connect(self.mock_state) as db:
            db.execute(
                "INSERT INTO reviews VALUES(?,?,?,?,?,?)",
                ("rev_1", "AUTO-D01", canonical(draft), record.draft_hash, "pending", None),
            )
        analyst, _ = login("jellis", "analyst-desk", path=self.auth_path)
        security, _ = login("rokonkwo", "security-desk", path=self.auth_path)
        with self.assertRaises(AuthError):
            accept_review(analyst, "AUTO-D01", stores=self.stores, mock_state=self.mock_state)
        with self.assertRaises(AuthError):
            accept_review(security, "AUTO-D01", stores=self.stores, mock_state=self.mock_state)

    def test_handler_accepts_matching_pending_hash(self):
        record, draft = _seed_case(self.stores)
        with mock_connect(self.mock_state) as db:
            db.execute(
                "INSERT INTO reviews VALUES(?,?,?,?,?,?)",
                ("rev_ok", "AUTO-D01", canonical(draft), record.draft_hash, "pending", None),
            )
        handler, _ = login("achen", "handler-desk", path=self.auth_path)
        result = accept_review(handler, "AUTO-D01", stores=self.stores, mock_state=self.mock_state)
        self.assertEqual(result["status"], "approved")
        self.assertEqual(result["reviewer"], "Avery Chen")
        with mock_connect(self.mock_state) as db:
            row = db.execute("SELECT status, reviewer FROM reviews WHERE id=?", ("rev_ok",)).fetchone()
            self.assertEqual(row["status"], "approved")
            self.assertEqual(row["reviewer"], "Avery Chen")

    def test_handler_rejects_with_reason_in_audit(self):
        record, draft = _seed_case(self.stores)
        with mock_connect(self.mock_state) as db:
            db.execute(
                "INSERT INTO reviews VALUES(?,?,?,?,?,?)",
                ("rev_rej", "AUTO-D01", canonical(draft), record.draft_hash, "pending", None),
            )
        handler, _ = login("achen", "handler-desk", path=self.auth_path)
        reject_review(
            handler,
            "AUTO-D01",
            "Missing driver confirmation",
            stores=self.stores,
            mock_state=self.mock_state,
        )
        with mock_connect(self.mock_state) as db:
            row = db.execute("SELECT status FROM reviews WHERE id=?", ("rev_rej",)).fetchone()
            self.assertEqual(row["status"], "rejected")
            audit = db.execute(
                "SELECT event, detail FROM audit WHERE event='human_rejected' ORDER BY seq DESC LIMIT 1"
            ).fetchone()
            self.assertIsNotNone(audit)
            detail = json.loads(audit["detail"])
            self.assertEqual(detail["reason"], "Missing driver confirmation")
            self.assertEqual(detail["username"], "achen")

    def test_hash_mismatch_cannot_accept(self):
        record, _draft = _seed_case(self.stores)
        with mock_connect(self.mock_state) as db:
            db.execute(
                "INSERT INTO reviews VALUES(?,?,?,?,?,?)",
                ("rev_bad", "AUTO-D01", "{}", "deadbeef", "pending", None),
            )
        handler, _ = login("achen", "handler-desk", path=self.auth_path)
        from fnol_desk.actions import DeskActionError

        with self.assertRaises(DeskActionError) as ctx:
            accept_review(handler, "AUTO-D01", stores=self.stores, mock_state=self.mock_state)
        self.assertEqual(ctx.exception.code, "review_not_pending")
        # Ensure the wrong-hash pending row is untouched
        with mock_connect(self.mock_state) as db:
            row = db.execute("SELECT status FROM reviews WHERE id=?", ("rev_bad",)).fetchone()
            self.assertEqual(row["status"], "pending")
        self.assertIsNotNone(record)

    def test_case_view_gates_by_team(self):
        record, draft = _seed_case(
            self.stores,
            evidence_summary="Draft for the human handler covering the supplied facts.",
            safety_status="passed",
        )
        with mock_connect(self.mock_state) as db:
            db.execute(
                "INSERT INTO reviews VALUES(?,?,?,?,?,?)",
                ("rev_view", "AUTO-D01", canonical(draft), record.draft_hash, "pending", None),
            )
        handler_view = case_view(
            "AUTO-D01", team="handlers", stores=self.stores, mock_state=self.mock_state
        )
        analyst_view = case_view(
            "AUTO-D01", team="analysts", stores=self.stores, mock_state=self.mock_state
        )
        security_view = case_view(
            "AUTO-D01", team="security", stores=self.stores, mock_state=self.mock_state
        )
        self.assertTrue(handler_view["actions"]["can_accept"])
        self.assertFalse(analyst_view["actions"]["can_accept"])
        self.assertFalse(security_view["actions"]["can_accept"])
        self.assertTrue(handler_view["summary"]["available"])
        self.assertEqual(handler_view["decision"]["eyebrow"], "Deterministic · AUTO-TRIAGE-01")

    def test_injection_flag_surfaces_on_queue_and_case(self):
        case_id = "AUTO-D08"
        revision = self.stores.input.append_revision(case_id, _facts(policy_number="PA-D08", vehicle_id="VEH-D08"))
        route = _route(
            route="manual_review",
            reasons=["dangerous_content"],
            conflicts=[],
            extra_fields=[{"source_id": "AUTO-D08-ESTIMATE", "label": "SYSTEM"}],
            injection_model_status="injection",
        )
        policy = _policy()
        citations = _citations()
        self.stores.input.put_decision(case_id, revision.revision, "policy", policy)
        self.stores.input.put_decision(case_id, revision.revision, "route", route)
        self.stores.input.put_decision(case_id, revision.revision, "citations", citations)
        draft = build_draft(
            case_id=case_id,
            input_revision=revision.revision,
            facts_row=_facts(policy_number="PA-D08", vehicle_id="VEH-D08"),
            policy=policy,
            route=route,
            citations=citations,
        )
        self.stores.output.record_draft(case_id, draft, input_revision=revision.revision)
        view = case_view(case_id, team="security", stores=self.stores, mock_state=self.mock_state)
        flag_ids = {f["id"] for f in view["flags"]}
        self.assertIn("injection", flag_ids)
        self.assertTrue(view["decision"]["content_check_notes"])
        from fnol_desk.view import list_queue

        queue = list_queue(team="security", stores=self.stores, mock_state=self.mock_state)
        self.assertIn(case_id, {row["case_id"] for row in queue})


class DeskHttpTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.state_dir = self.root / "state"
        self.mock_state = self.root / "mock.sqlite"
        self.data_dir = Path(__file__).resolve().parents[1] / "data" / "dev"
        mock_connect(self.mock_state).close()

        self.stores = Stores(self.state_dir)
        self.record, self.draft = _seed_case(self.stores)

        self.mock = create_mock_server(self.data_dir, self.mock_state, host="127.0.0.1", port=0)
        self.mock_thread = threading.Thread(target=self.mock.serve_forever, daemon=True)
        self.mock_thread.start()
        mock_host, mock_port = self.mock.server_address[:2]
        self.mock_url = f"http://{mock_host}:{mock_port}"

        self.desk = create_server(
            host="127.0.0.1",
            port=0,
            state_dir=self.state_dir,
            mock_state=self.mock_state,
            mock_url=self.mock_url,
        )
        self.desk_thread = threading.Thread(target=self.desk.serve_forever, daemon=True)
        self.desk_thread.start()
        desk_host, desk_port = self.desk.server_address[:2]
        self.base = f"http://{desk_host}:{desk_port}"
        self.jar = CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))

    def tearDown(self):
        self.desk.shutdown()
        self.desk.server_close()
        self.mock.shutdown()
        self.mock.server_close()
        self.tmp.cleanup()

    def _request(self, method, path, body=None):
        data = None
        headers = {"Accept": "application/json"}
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json; charset=utf-8"
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=headers)
        try:
            with self.opener.open(req, timeout=5) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            payload = json.loads(exc.read().decode("utf-8"))
            return exc.code, payload

    def test_http_login_send_accept_reject_gates(self):
        status, body = self._request("POST", "/api/login", {"username": "jellis", "password": "analyst-desk"})
        self.assertEqual(status, 200)
        self.assertEqual(body["user"]["team"], "analysts")

        status, body = self._request("POST", f"/api/cases/{self.record.case_id}/send", {})
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "pending")
        self.assertTrue(body["review_id"].startswith("rev_"))

        # Analyst cannot accept
        status, body = self._request("POST", f"/api/cases/{self.record.case_id}/accept", {})
        self.assertEqual(status, 403)

        # Switch to handler
        self._request("POST", "/api/logout", {})
        status, body = self._request("POST", "/api/login", {"username": "achen", "password": "handler-desk"})
        self.assertEqual(status, 200)

        status, view = self._request("GET", f"/api/cases/{self.record.case_id}")
        self.assertEqual(status, 200)
        self.assertTrue(view["actions"]["can_accept"])
        self.assertIn("Deterministic", view["decision"]["eyebrow"])

        status, body = self._request("POST", f"/api/cases/{self.record.case_id}/accept", {})
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "approved")
        self.assertEqual(body["reviewer"], "Avery Chen")

        # Second accept fails — no longer pending
        status, body = self._request("POST", f"/api/cases/{self.record.case_id}/accept", {})
        self.assertEqual(status, 409)

    def test_security_read_only_queue(self):
        # Force a watch flag via conflict
        route = _route(conflicts=["incident_timestamp"], reasons=["conflicting_facts"], route="manual_review")
        stores = self.stores
        case_id = "AUTO-D02"
        revision = stores.input.append_revision(case_id, _facts(policy_number="PA-D02", vehicle_id="VEH-D02"))
        policy = _policy()
        citations = _citations()
        stores.input.put_decision(case_id, revision.revision, "policy", policy)
        stores.input.put_decision(case_id, revision.revision, "route", route)
        stores.input.put_decision(case_id, revision.revision, "citations", citations)
        draft = build_draft(
            case_id=case_id,
            input_revision=revision.revision,
            facts_row=_facts(policy_number="PA-D02", vehicle_id="VEH-D02"),
            policy=policy,
            route=route,
            citations=citations,
        )
        stores.output.record_draft(case_id, draft, input_revision=revision.revision)

        self._request("POST", "/api/login", {"username": "rokonkwo", "password": "security-desk"})
        status, body = self._request("GET", "/api/queue")
        self.assertEqual(status, 200)
        ids = {row["case_id"] for row in body["cases"]}
        self.assertIn("AUTO-D02", ids)

        status, body = self._request("POST", f"/api/cases/{case_id}/accept", {})
        self.assertEqual(status, 403)

        status, body = self._request("GET", "/api/audit")
        self.assertEqual(status, 200)
        self.assertIn("events", body)


if __name__ == "__main__":
    unittest.main()
