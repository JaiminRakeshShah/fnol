"""Citations orchestration: read stored text and JSON, slice quotes, trace step 4."""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fnol_foundation.canonical import RestrictedValueError, digest
from fnol_foundation.stores import Stores
from fnol_intake.parse import file_sha256, read_source
from fnol_policy.select import PROCEDURE_ID
from fnol_policy.service import decision_from_store

from fnol_citations.guard import seal
from fnol_citations.slice import build_citations

STEP = "4"
ACTOR = "citations"


class CitationError(Exception):
    def __init__(self, error_code: str, message: str):
        super().__init__(message)
        self.error_code = error_code


def _now():
    return datetime.now(timezone.utc)


def load_procedure_text(policies_dir: Path, policy_ids: list[str], procedures: list[dict]):
    """Read wording files for the selected ids.

    When intake recorded a sha256, a file that no longer matches is not quoted.
    The returned text is used only to slice one line; it is not stored.
    """
    known = {row["source_id"]: row["sha256"] for row in procedures}
    texts: dict[str, str] = {}
    missing: list[str] = []
    for source_id in policy_ids:
        found = read_source(policies_dir, source_id)
        if found is None:
            missing.append(source_id)
            continue
        _path, data, text = found
        expected = known.get(source_id)
        if expected is not None and file_sha256(data) != expected:
            missing.append(source_id)
            continue
        texts[source_id] = text
    return texts, missing


def _trace(stores, *, trace_id, case_id, revision, citations, started, status, error_code=None):
    """One step-4 event. The row holds a hash of the quotes, not the file text."""
    stores.trace.append_event(
        trace_id=trace_id,
        span_id=uuid.uuid4().hex,
        step=STEP,
        actor=ACTOR,
        rule_version=PROCEDURE_ID,
        case_id=case_id,
        input_revision=None if revision is None else revision.revision,
        input_sha256=None if revision is None else revision.document_set_sha256,
        output_sha256=None if citations is None else digest(citations),
        duration_ms=int((time.perf_counter() - started) * 1000),
        status=status,
        error_code=error_code,
        started_at=_now(),
    )


def _cited(citations: list[dict], source_id) -> bool:
    return isinstance(source_id, str) and any(item["source_id"] == source_id for item in citations)


def run_citations(
    case_id: str,
    stores: Stores,
    *,
    policies_dir: Path,
    trace_id: str | None = None,
) -> dict:
    """Slice citations for one case from its latest input revision and tool snapshots.

    Policy wording comes from the files intake hashed. Case documents and tool
    payloads come from input.sqlite. A claims snapshot that was never stored
    (the claims call failed) produces no claims citation.
    """
    trace_id = trace_id or uuid.uuid4().hex
    started = time.perf_counter()
    revision = stores.input.get_revision(case_id)
    if revision is None:
        _trace(
            stores, trace_id=trace_id, case_id=case_id, revision=None, citations=None,
            started=started, status="error", error_code="revision_missing",
        )
        raise CitationError("revision_missing", f"no input revision for {case_id}")

    payload = revision.payload
    snapshot = stores.input.get_tool_payload(case_id, "policy")
    policy_payload = None if snapshot is None else snapshot["raw_json"]
    claims_row = stores.input.get_tool_payload(case_id, "claims")
    claims_payload = None if claims_row is None else claims_row["raw_json"]
    decision = decision_from_store(stores, case_id)
    policy_ids = list(decision["policy_ids"]) if decision else [PROCEDURE_ID]
    texts, missing_ids = load_procedure_text(
        policies_dir, policy_ids, stores.input.list_procedures(),
    )

    try:
        citations = seal(build_citations(
            case_id=case_id,
            revision=payload,
            policy_ids=policy_ids,
            procedure_text=texts,
            policy_payload=policy_payload,
            claims_payload=claims_payload,
        ))
    except RestrictedValueError:
        _trace(
            stores, trace_id=trace_id, case_id=case_id, revision=revision, citations=None,
            started=started, status="error", error_code="restricted_quote",
        )
        raise CitationError("restricted_quote", "restricted value refused") from None

    omissions = []
    if claims_payload is None:
        omissions.append({"tool": "claims", "reason": "unavailable"})
    if policy_payload is None:
        omissions.append({"tool": "policy", "reason": "unavailable"})
    for source_id in missing_ids:
        omissions.append({"source_id": source_id, "reason": "wording_unavailable"})
    intake_source = payload.get("intake_source")
    if intake_source and not _cited(citations, intake_source):
        omissions.append({"source_id": intake_source, "reason": "no_safe_excerpt"})
    for tool_payload in (policy_payload, claims_payload):
        if tool_payload is None:
            continue
        source_id = tool_payload.get("source_id")
        if isinstance(source_id, str) and source_id and not _cited(citations, source_id):
            omissions.append({"source_id": source_id, "reason": "no_safe_excerpt"})

    out = {
        "case_id": case_id,
        "input_revision": revision.revision,
        "policy_ids": policy_ids,
        "citations": citations,
    }
    if omissions:
        out["omissions"] = omissions
    _trace(
        stores, trace_id=trace_id, case_id=case_id, revision=revision, citations=citations,
        started=started, status="ok",
    )
    return out
