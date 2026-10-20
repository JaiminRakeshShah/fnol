"""Rules ↔ foundation Stores integration."""
import tempfile
import unittest

from fnol_foundation.canonical import canonical
from fnol_foundation.stores import Stores
from fnol_rules.claims import ClaimsAttempt, ClaimsFetchResult
from fnol_rules.service import run_rules
from fnol_rules.types import ClaimsSnapshot, PolicyResult, StructuredFields


class FoundationBridgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.stores = Stores(self.tmp.name)

    def tearDown(self):
        self.stores.close()
        self.tmp.cleanup()

    def test_claims_land_in_input_tool_payloads_and_trace(self):
        raw = {
            "source_id": "AUTO-D01-CLAIMS",
            "existing_claims": [],
            "intake_deliveries": 1,
            "loss_reference": "auto-loss-D01",
        }

        def fake_fetch(case_id, base_url, **_kw):
            return ClaimsFetchResult(
                snapshot=ClaimsSnapshot(available=True, intake_deliveries=1),
                attempts=(ClaimsAttempt(1, 200, raw),),
                raw_json=raw,
            )

        fields = StructuredFields(
            loss_type="collision",
            vehicle_id="VEH-1",
            incident_timestamp="2026-10-01T12:00:00Z",
            driver_name="Alex",
            incident_location="Cedar",
            injury_reported=False,
            vehicle_drivable=True,
        )
        result = run_rules(
            "AUTO-D01",
            fields,
            PolicyResult("2"),
            base_url="http://example",
            stores=self.stores,
            fetch=fake_fetch,
        )
        self.assertEqual(result.route, "standard")
        stored = self.stores.input.get_tool_payload("AUTO-D01", "claims")
        self.assertIsNotNone(stored)
        self.assertEqual(canonical(stored["raw_json"]), canonical(raw))
        events = []
        import sqlite3
        with sqlite3.connect(self.stores.trace.path) as db:
            db.row_factory = sqlite3.Row
            events = db.execute(
                "SELECT step, actor, status, mock_http_status FROM trace_events"
            ).fetchall()
        self.assertTrue(events)
        self.assertEqual(events[0]["step"], "3")
        self.assertEqual(events[0]["actor"], "rules")
