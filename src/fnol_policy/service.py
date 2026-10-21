"""Policy server orchestration: fetch -> redact -> store snapshot -> decide -> trace."""
from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

from fnol_foundation.canonical import digest
from fnol_foundation.stores import Stores
from fnol_policy.fetch import PolicyFetchResult, fetch_policy
from fnol_policy.select import PROCEDURE_ID, decide

STEP = "2"
ACTOR = "policy"


class PolicyError(Exception):
    def __init__(self, error_code: str, message: str):
        super().__init__(message)
        self.error_code = error_code


def _now():
    return datetime.now(timezone.utc)


def known_sources(stores: Stores) -> set[str]:
    return {row["source_id"] for row in stores.input.list_procedures()}


def decision_from_store(stores: Stores, case_id: str) -> dict | None:
    """Rebuild the Step 2 decision from the stored snapshot without any HTTP call.

    Returns None when no policy snapshot or no input revision exists for the case.
    """
    revision = stores.input.get_revision(case_id)
    snapshot = stores.input.get_tool_payload(case_id, "policy")
    if revision is None or snapshot is None:
        return None
    ts = revision.payload.get("incident_timestamp")
    if not ts:
        return None
    result = decide(snapshot["raw_json"], ts, known_sources(stores))
    result["case_id"] = case_id
    result["input_revision"] = revision.revision
    result["snapshot_sha256"] = snapshot["sha256"]
    return result


def run_policy(
    case_id: str,
    stores: Stores,
    *,
    base_url: str,
    incident_timestamp: str | None = None,
    fetch: Callable[..., PolicyFetchResult] | None = None,
    trace_id: str | None = None,
) -> dict[str, Any]:
    """Select the single policy version in force at the incident timestamp.

    The timestamp is read from the latest input revision. An explicit
    incident_timestamp is only used when no revision exists (unit tests, ad hoc).
    Never returns private_token or the full policies array.
    """
    trace_id = trace_id or uuid.uuid4().hex
    revision = stores.input.get_revision(case_id)
    if revision is not None:
        incident_timestamp = revision.payload.get("incident_timestamp") or incident_timestamp
    if not incident_timestamp:
        raise PolicyError("incident_timestamp_missing", f"no incident_timestamp for {case_id}")
    input_sha = revision.document_set_sha256 if revision is not None else None
    input_revision = revision.revision if revision is not None else None

    started = time.perf_counter()
    result = (fetch or fetch_policy)(case_id, base_url)
    for attempt in result.attempts:
        stores.trace.append_event(
            trace_id=trace_id,
            span_id=uuid.uuid4().hex,
            step=STEP,
            actor=ACTOR,
            case_id=case_id,
            input_revision=input_revision,
            input_sha256=input_sha,
            attempt=attempt.attempt,
            mock_http_status=attempt.status,
            status="ok" if attempt.status == 200 else "error",
            error_code=attempt.error,
            started_at=_now(),
        )

    base = {
        "case_id": case_id,
        "input_revision": input_revision,
        "attempts": len(result.attempts),
        "selected_policy_version": None,
        "policy_ids": [PROCEDURE_ID],
        "missing_sources": [],
    }
    if result.payload is None:
        out = {**base, "reason": result.status}
        _trace_decision(stores, trace_id, case_id, input_revision, input_sha, out, started, ok=False)
        return out

    payload = dict(result.payload)
    payload.pop("private_token", None)
    snapshot_sha = stores.input.put_tool_payload(case_id, "policy", payload)  # also refuses restricted values

    out = {**base, **decide(payload, incident_timestamp, known_sources(stores)),
           "snapshot_sha256": snapshot_sha}
    _trace_decision(stores, trace_id, case_id, input_revision, input_sha, out, started, ok=True)
    return out


def _trace_decision(stores, trace_id, case_id, input_revision, input_sha, out, started, *, ok):
    stores.trace.append_event(
        trace_id=trace_id,
        span_id=uuid.uuid4().hex,
        step=STEP,
        actor=ACTOR,
        case_id=case_id,
        input_revision=input_revision,
        input_sha256=input_sha,
        output_sha256=digest(out),
        duration_ms=int((time.perf_counter() - started) * 1000),
        status="ok" if ok else "error",
        error_code=None if ok else out.get("reason"),
        started_at=_now(),
    )
