"""Map intake Input DB revisions into Rules structured fields."""
from __future__ import annotations

from fnol_rules.types import SourceFacts, StructuredFields


def fields_from_payload(payload: dict) -> StructuredFields:
    """Build StructuredFields from an intake revision payload (no raw_text used for routing)."""
    loss_type = payload.get("loss_type") or "unsupported"
    injury = payload.get("injury_reported")
    drivable = payload.get("vehicle_drivable")

    intake = SourceFacts(
        loss_type=payload.get("loss_type"),
        vehicle_id=payload.get("vehicle_id"),
        incident_timestamp=payload.get("incident_timestamp"),
        driver_name=payload.get("driver_name"),
        incident_location=payload.get("incident_location"),
        injury_reported=injury,
        vehicle_drivable=drivable,
        referral_indicator=payload.get("referral_indicator"),
    )
    report = None
    if any(
        payload.get(k) is not None
        for k in ("report_vehicle_reference", "report_incident_timestamp", "reported_loss_type")
    ):
        report = SourceFacts(
            loss_type=payload.get("reported_loss_type"),
            vehicle_id=payload.get("report_vehicle_reference"),
            incident_timestamp=payload.get("report_incident_timestamp"),
        )
    estimate = None
    if payload.get("estimate_vehicle") is not None:
        estimate = SourceFacts(vehicle_id=payload.get("estimate_vehicle"))

    return StructuredFields(
        loss_type=loss_type,
        vehicle_id=payload.get("vehicle_id"),
        incident_timestamp=payload.get("incident_timestamp"),
        driver_name=payload.get("driver_name"),
        incident_location=payload.get("incident_location"),
        injury_reported=bool(injury) if injury is not None else False,
        vehicle_drivable=bool(drivable) if drivable is not None else True,
        referral_indicator=payload.get("referral_indicator"),
        intake=intake,
        report=report,
        estimate=estimate,
    )
