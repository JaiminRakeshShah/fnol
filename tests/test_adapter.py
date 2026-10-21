"""Intake payload → StructuredFields mapping."""
from fnol_rules.adapter import fields_from_payload
from fnol_rules.route import route
from fnol_rules.types import ClaimsSnapshot, PolicyResult


def test_maps_missing_sentinels_to_manual_review():
    fields = fields_from_payload({
        "loss_type": "collision",
        "vehicle_id": "VEH-D04",
        "incident_timestamp": "2026-10-01T12:00:00Z",
        "driver_name": "not supplied",
        "driver_name_supplied": False,
        "incident_location": "not supplied",
        "incident_location_supplied": False,
        "injury_reported": False,
        "vehicle_drivable": True,
        "referral_indicator": "none",
    })
    result = route(fields, PolicyResult("2"), ClaimsSnapshot(available=True))
    assert result.route == "manual_review"
    assert result.missing_information == ["driver_name", "incident_location"]


def test_unknown_booleans_are_not_coerced():
    fields = fields_from_payload({
        "loss_type": "collision",
        "vehicle_id": "VEH-1",
        "incident_timestamp": "2026-10-01T12:00:00Z",
        "driver_name": "Alex",
        "incident_location": "Cedar",
        "injury_reported": None,
        "vehicle_drivable": None,
    })
    assert fields.injury_reported is None
    assert fields.vehicle_drivable is None
    result = route(fields, PolicyResult("2"), ClaimsSnapshot(available=True))
    assert result.route == "standard"
    assert result.injury_reported is None
    assert result.vehicle_drivable is None


def test_repeated_driver_name_is_a_conflict():
    fields = fields_from_payload({
        "loss_type": "collision",
        "vehicle_id": "VEH-1",
        "incident_timestamp": "2026-10-01T12:00:00Z",
        "driver_name": "First Driver",
        "incident_location": "Cedar",
        "injury_reported": False,
        "vehicle_drivable": True,
        "repeated_fields": ["driver_name"],
    })
    result = route(fields, PolicyResult("2"), ClaimsSnapshot(available=True))
    assert result.route == "manual_review"
    assert result.conflicts == ["driver_name"]


def test_report_vehicle_conflict_manual_review():
    fields = fields_from_payload({
        "loss_type": "collision",
        "vehicle_id": "VEH-1",
        "incident_timestamp": "2026-10-01T12:00:00Z",
        "driver_name": "Alex",
        "incident_location": "Cedar",
        "injury_reported": False,
        "vehicle_drivable": True,
        "report_vehicle_reference": "VEH-OTHER",
        "report_incident_timestamp": "2026-10-01T12:00:00Z",
        "reported_loss_type": "collision",
    })
    result = route(fields, PolicyResult("2"), ClaimsSnapshot(available=True))
    assert result.route == "manual_review"
