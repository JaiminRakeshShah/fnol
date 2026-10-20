"""Deterministic AUTO-TRIAGE-01 routing from structured fields only."""
from __future__ import annotations

from fnol_rules.types import (
    MISSING_SENTINEL,
    RULE_VERSION,
    SUPPORTED_LOSSES,
    ClaimsSnapshot,
    PolicyResult,
    RouteResult,
    SourceFacts,
    StructuredFields,
)


def _is_missing(value: str | None) -> bool:
    if value is None:
        return True
    text = value.strip()
    return text == "" or text.lower() == MISSING_SENTINEL


def _missing_information(fields: StructuredFields) -> list[str]:
    missing: list[str] = []
    if _is_missing(fields.driver_name):
        missing.append("driver_name")
    if _is_missing(fields.incident_location):
        missing.append("incident_location")
    return missing


def _sources(fields: StructuredFields) -> list[SourceFacts]:
    return [s for s in (fields.intake, fields.report, fields.estimate) if s is not None]


def _conflict(fields: StructuredFields) -> bool:
    """True when present sources disagree on vehicle, timestamp, or loss type."""
    srcs = _sources(fields)
    if len(srcs) < 2:
        return False

    def disagree(attr: str) -> bool:
        vals = [getattr(s, attr) for s in srcs if getattr(s, attr) is not None]
        return len(set(vals)) > 1

    return disagree("vehicle_id") or disagree("incident_timestamp") or disagree("loss_type")


def route(
    fields: StructuredFields,
    policy: PolicyResult,
    claims: ClaimsSnapshot,
) -> RouteResult:
    """Apply AUTO-TRIAGE-01 precedence. Never accepts raw_text."""
    classification = (
        fields.loss_type if fields.loss_type in SUPPORTED_LOSSES else "unsupported"
    )
    missing = _missing_information(fields)
    duplicate = (
        claims.available
        and (claims.intake_deliveries > 1 or len(claims.existing_claims) > 0)
    )

    manual = (
        classification == "unsupported"
        or bool(missing)
        or _conflict(fields)
        or not claims.available
        or not policy.policy_available
        or policy.selected_policy_version is None
    )

    if manual:
        chosen = "manual_review"
    elif fields.injury_reported or not fields.vehicle_drivable:
        chosen = "urgent"
    elif classification == "theft" or fields.referral_indicator == "repair_amount_conflict":
        chosen = "specialist"
    else:
        chosen = "standard"

    return RouteResult(
        classification=classification,
        route=chosen,
        route_rule=RULE_VERSION,
        missing_information=missing,
        duplicate_delivery=duplicate,
        injury_reported=fields.injury_reported,
        vehicle_drivable=fields.vehicle_drivable,
        selected_policy_version=policy.selected_policy_version,
        claims_available=claims.available,
    )
