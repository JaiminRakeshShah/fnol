"""AUTO-TRIAGE-01 precedence tests."""
from fnol_rules.route import route
from fnol_rules.types import (
    ClaimsSnapshot,
    PolicyResult,
    SourceFacts,
    StructuredFields,
)


def _fields(**kwargs) -> StructuredFields:
    base = dict(
        loss_type="collision",
        vehicle_id="VEH-1",
        incident_timestamp="2026-10-01T12:00:00Z",
        driver_name="Alex Rowan",
        incident_location="Cedar Street",
        injury_reported=False,
        vehicle_drivable=True,
        referral_indicator=None,
    )
    base.update(kwargs)
    return StructuredFields(**base)


def _policy(version="2", available=True) -> PolicyResult:
    return PolicyResult(selected_policy_version=version, policy_available=available)


def _claims(**kwargs) -> ClaimsSnapshot:
    base = dict(existing_claims=[], intake_deliveries=1, available=True)
    base.update(kwargs)
    return ClaimsSnapshot(**base)


def test_standard_happy_path():
    r = route(_fields(), _policy(), _claims())
    assert r.classification == "collision"
    assert r.route == "standard"
    assert r.route_rule == "AUTO-TRIAGE-01"
    assert r.missing_information == []
    assert r.duplicate_delivery is False


def test_unsupported_loss_manual_review():
    r = route(_fields(loss_type="flood"), _policy(), _claims())
    assert r.classification == "unsupported"
    assert r.route == "manual_review"


def test_missing_driver_and_location():
    r = route(
        _fields(driver_name="not supplied", incident_location="not supplied"),
        _policy(),
        _claims(),
    )
    assert r.route == "manual_review"
    assert r.missing_information == ["driver_name", "incident_location"]


def test_fact_conflict_across_sources():
    fields = _fields(
        intake=SourceFacts(loss_type="collision", vehicle_id="VEH-1",
                           incident_timestamp="2026-10-01T12:00:00Z"),
        report=SourceFacts(loss_type="collision", vehicle_id="VEH-OTHER",
                           incident_timestamp="2026-10-01T12:00:00Z"),
    )
    r = route(fields, _policy(), _claims())
    assert r.route == "manual_review"


def test_null_policy_version_manual_review():
    r = route(_fields(), _policy(version=None), _claims())
    assert r.route == "manual_review"
    assert r.selected_policy_version is None


def test_claims_outage_preserves_policy_version():
    r = route(_fields(), _policy(version="2"), _claims(available=False))
    assert r.route == "manual_review"
    assert r.selected_policy_version == "2"
    assert r.claims_available is False


def test_policy_unavailable_manual_review():
    r = route(_fields(), _policy(version="2", available=False), _claims())
    assert r.route == "manual_review"
    assert r.selected_policy_version == "2"


def test_injury_urgent():
    r = route(_fields(injury_reported=True), _policy(), _claims())
    assert r.route == "urgent"
    assert r.injury_reported is True


def test_non_drivable_urgent():
    r = route(_fields(vehicle_drivable=False), _policy(), _claims())
    assert r.route == "urgent"
    assert r.vehicle_drivable is False


def test_theft_specialist():
    r = route(_fields(loss_type="theft"), _policy(), _claims())
    assert r.classification == "theft"
    assert r.route == "specialist"


def test_repair_amount_conflict_specialist():
    r = route(
        _fields(referral_indicator="repair_amount_conflict"),
        _policy(),
        _claims(),
    )
    assert r.route == "specialist"


def test_duplicate_delivery_does_not_change_route():
    r = route(_fields(loss_type="glass"), _policy(), _claims(intake_deliveries=2))
    assert r.route == "standard"
    assert r.duplicate_delivery is True


def test_existing_claims_sets_duplicate():
    r = route(_fields(), _policy(), _claims(existing_claims=[{"id": "c1"}]))
    assert r.route == "standard"
    assert r.duplicate_delivery is True


def test_unknown_injury_and_drivable_stay_unknown():
    r = route(_fields(injury_reported=None, vehicle_drivable=None), _policy(), _claims())
    assert r.route == "standard"
    assert r.injury_reported is None
    assert r.vehicle_drivable is None


def test_wording_missing_keeps_the_selected_version():
    r = route(
        _fields(),
        PolicyResult(selected_policy_version="2", policy_available=False, reason="wording_missing"),
        _claims(),
    )
    assert r.route == "manual_review"
    assert r.selected_policy_version == "2"
    assert r.reasons == ["wording_missing"]


def test_repeated_label_is_manual_review():
    r = route(_fields(repeated_fields=("driver_name",)), _policy(), _claims())
    assert r.route == "manual_review"
    assert r.conflicts == ["driver_name"]
    assert "conflicting_facts" in r.reasons


def test_manual_review_preserves_injury_flags():
    r = route(
        _fields(injury_reported=True, driver_name="not supplied"),
        _policy(),
        _claims(),
    )
    assert r.route == "manual_review"
    assert r.injury_reported is True
    assert r.vehicle_drivable is True
