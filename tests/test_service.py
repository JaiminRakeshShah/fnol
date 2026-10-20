"""run_rules orchestration with memory stores."""
from fnol_rules.canonical import canonical
from fnol_rules.claims import ClaimsAttempt, ClaimsFetchResult
from fnol_rules.memory import MemoryEventLog, MemoryInputStore
from fnol_rules.service import run_rules
from fnol_rules.types import ClaimsSnapshot, PolicyResult, StructuredFields


def _fields() -> StructuredFields:
    return StructuredFields(
        loss_type="collision",
        vehicle_id="VEH-1",
        incident_timestamp="2026-10-01T12:00:00Z",
        driver_name="Alex",
        incident_location="Cedar",
        injury_reported=False,
        vehicle_drivable=True,
    )


def test_stores_canonical_claims_and_logs_attempts():
    store = MemoryInputStore()
    log = MemoryEventLog()
    raw = {
        "source_id": "AUTO-D01-CLAIMS",
        "existing_claims": [],
        "intake_deliveries": 1,
        "loss_reference": "auto-loss-D01",
    }

    def fake_fetch(case_id, base_url, **_kw):
        return ClaimsFetchResult(
            snapshot=ClaimsSnapshot(
                existing_claims=[], intake_deliveries=1, available=True
            ),
            attempts=(ClaimsAttempt(attempt=1, status=200, body=raw),),
            raw_json=raw,
        )

    result = run_rules(
        "AUTO-D01",
        _fields(),
        PolicyResult(selected_policy_version="2"),
        base_url="http://example",
        input_store=store,
        event_log=log,
        fetch=fake_fetch,
    )

    assert result.route == "standard"
    assert store.claims["AUTO-D01"] == canonical(raw)
    assert log.events[0]["event"] == "tool_read"
    assert log.events[0]["tool"] == "claims"
    assert log.events[0]["status"] == 200
    assert "private_token" not in log.events[0]
    assert log.events[1]["event"] == "claims_stored"


def test_outage_skips_store_logs_each_attempt():
    store = MemoryInputStore()
    log = MemoryEventLog()

    def fake_fetch(case_id, base_url, **_kw):
        attempts = tuple(
            ClaimsAttempt(
                attempt=i,
                status=503,
                body={"error": "upstream_timeout", "retryable": True},
            )
            for i in range(1, 4)
        )
        return ClaimsFetchResult(
            snapshot=ClaimsSnapshot(available=False),
            attempts=attempts,
            raw_json=None,
        )

    result = run_rules(
        "AUTO-D07",
        _fields(),
        PolicyResult(selected_policy_version="2"),
        base_url="http://example",
        input_store=store,
        event_log=log,
        fetch=fake_fetch,
    )

    assert result.route == "manual_review"
    assert result.selected_policy_version == "2"
    assert "AUTO-D07" not in store.claims
    assert len([e for e in log.events if e["event"] == "tool_read"]) == 3
    assert all("private_token" not in e for e in log.events)
