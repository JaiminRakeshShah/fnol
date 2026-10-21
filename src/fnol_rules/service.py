"""Rules server orchestration: read policy decision, fetch claims, route, persist."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Callable

from fnol_foundation.canonical import RestrictedValueError, digest
from fnol_foundation.events import record_event
from fnol_foundation.http import public_error
from fnol_foundation.stores import Stores
from fnol_rules.claims import ClaimsFetchResult, fetch_claims
from fnol_rules.route import route
from fnol_rules.types import RULE_VERSION, ClaimsSnapshot, PolicyResult, RouteResult, StructuredFields


def policy_from_decision(decision: dict[str, Any]) -> PolicyResult:
    body = decision["body"]
    endorsements = body.get("endorsements") or ()
    return PolicyResult(
        selected_policy_version=body.get("selected_policy_version"),
        policy_available=bool(body.get("policy_available")),
        payload_sha256=decision.get("policy_sha256"),
        reason=body.get("reason"),
        wording_source=body.get("wording_source"),
        endorsements=tuple(endorsements),
        source_id=body.get("source_id"),
    )


def run_rules(
    case_id: str,
    fields: StructuredFields,
    policy: PolicyResult,
    *,
    base_url: str,
    stores: Stores,
    input_revision: int,
    trace_id: str,
    input_sha256: str | None = None,
    fetch: Callable[..., ClaimsFetchResult] | None = None,
) -> RouteResult:
    """Fetch claims, persist the canonical payload, route, and store the decision."""
    fetcher = fetch or fetch_claims
    result = fetcher(case_id, base_url)
    parent = None
    for attempt in result.attempts:
        parent = record_event(
            stores,
            trace_id=trace_id,
            parent_span_id=parent,
            step="3",
            event="tool_read",
            actor="rules",
            rule_version=RULE_VERSION,
            status="ok" if attempt.status == 200 else "error",
            case_id=case_id,
            input_revision=input_revision,
            attempt=attempt.attempt,
            mock_http_status=attempt.status,
            error_code=None if attempt.status == 200 else public_error(attempt.body),
            duration_ms=attempt.duration_ms,
            input_sha256=input_sha256,
        )

    snapshot = result.snapshot
    claims_sha = None
    if result.raw_json is not None and snapshot.available:
        try:
            claims_sha = stores.input.put_tool_payload(
                case_id, "claims", result.raw_json, input_revision
            )
        except RestrictedValueError:
            snapshot = ClaimsSnapshot(existing_claims=[], intake_deliveries=0, available=False)
            parent = record_event(
                stores,
                trace_id=trace_id,
                parent_span_id=parent,
                step="3",
                event="claims_refused",
                actor="rules",
                rule_version=RULE_VERSION,
                status="error",
                case_id=case_id,
                input_revision=input_revision,
                error_code="restricted_value",
                input_sha256=input_sha256,
            )
        else:
            parent = record_event(
                stores,
                trace_id=trace_id,
                parent_span_id=parent,
                step="3",
                event="claims_stored",
                actor="rules",
                rule_version=RULE_VERSION,
                status="ok",
                case_id=case_id,
                input_revision=input_revision,
                output_sha256=claims_sha,
                input_sha256=input_sha256,
            )

    routed = route(fields, policy, snapshot)
    body = asdict(routed)
    body["policy_sha256"] = policy.payload_sha256
    body["claims_sha256"] = claims_sha
    stores.input.put_decision(
        case_id,
        input_revision,
        "route",
        body,
        policy_sha256=policy.payload_sha256,
        claims_sha256=claims_sha,
    )
    record_event(
        stores,
        trace_id=trace_id,
        parent_span_id=parent,
        step="3",
        event="route_decision",
        actor="rules",
        rule_version=RULE_VERSION,
        status="ok",
        case_id=case_id,
        input_revision=input_revision,
        output_sha256=digest(body),
        input_sha256=input_sha256,
    )
    return routed
