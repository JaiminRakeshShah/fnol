"""Policy outage is a stored decision. Skipping the policy step is an error."""

import tempfile

from fnol_foundation.http import HttpAttempt
from fnol_foundation.stores import Stores
from fnol_policy.service import run_policy
from fnol_rules.claims import ClaimsAttempt, ClaimsFetchResult
from fnol_rules.pipeline import RulesError, start_routing
from fnol_rules.types import ClaimsSnapshot


def _claims_ok(case_id, base_url, **_kw):
    raw = {"source_id": "X-CLAIMS", "existing_claims": [], "intake_deliveries": 1}
    return ClaimsFetchResult(
        snapshot=ClaimsSnapshot(available=True, existing_claims=[], intake_deliveries=1),
        attempts=(ClaimsAttempt(1, 200, raw),),
        raw_json=raw,
    )


def test_policy_outage_is_manual_review_with_no_invented_version():
    def fetch(case_id, base_url):
        return (HttpAttempt(1, 503, {"error": "upstream_timeout"}, 3),), None

    with tempfile.TemporaryDirectory() as tmp:
        stores = Stores(tmp)
        revision = stores.input.append_revision(
            "AUTO-D01",
            {
                "loss_type": "collision",
                "vehicle_id": "VEH-D01",
                "incident_timestamp": "2026-10-01T12:00:00Z",
                "driver_name": "Alex",
                "incident_location": "Cedar",
                "injury_reported": False,
                "vehicle_drivable": True,
            },
            "sha",
            trace_id="trace-outage",
        )
        decision = run_policy(
            "AUTO-D01",
            "2026-10-01T12:00:00Z",
            base_url="http://mock",
            stores=stores,
            input_revision=revision.revision,
            trace_id="trace-outage",
            fetch=fetch,
        )
        assert decision["reason"] == "unavailable"
        assert decision["policy_available"] is False
        assert decision["selected_policy_version"] is None
        assert stores.input.get_tool_payload("AUTO-D01", "policy", revision.revision) is None
        summary = start_routing(case_id="AUTO-D01", mock_url="http://mock", state_dir_path=tmp, fetch=_claims_ok)

    row = summary["routes"][0]
    assert row["route"] == "manual_review"
    assert row["selected_policy_version"] is None
    assert "policy_unavailable" in row["reasons"]


def test_routing_without_a_policy_decision_is_an_error():
    with tempfile.TemporaryDirectory() as tmp:
        stores = Stores(tmp)
        stores.input.append_revision("AUTO-D01", {"loss_type": "collision"}, "sha", trace_id="t")
        try:
            start_routing(case_id="AUTO-D01", mock_url="http://mock", state_dir_path=tmp, fetch=_claims_ok)
        except RulesError as exc:
            assert exc.error_code == "policy_decision_missing"
        else:
            raise AssertionError("expected RulesError")
