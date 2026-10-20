"""Discover cases from the mock API and store one immutable input revision each."""

import json
import time
import uuid
import urllib.error
import urllib.request
from datetime import datetime, timezone

from fnol_foundation.canonical import digest

from fnol_intake.parse import (
    document_kind,
    file_sha256,
    labels_for,
    load_procedures,
    parse_document,
    read_source,
    supplied_value,
    yes_no,
)


class IntakeError(Exception):
    def __init__(self, error_code, message):
        super().__init__(message)
        self.error_code = error_code


class DocumentMissing(IntakeError):
    def __init__(self, missing):
        self.missing = missing
        pairs = ", ".join(f"{item['case_id']}:{item['source_id']}" for item in missing)
        super().__init__("document_missing", f"document_missing: {pairs}")


def default_transport(url, timeout=10):
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            body = json.loads(raw)
        except json.JSONDecodeError:
            body = {"error": "invalid_json"}
        return exc.code, body


def _url(mock_url, path):
    return mock_url.rstrip("/") + path


def _now():
    return datetime.now(timezone.utc)


def _span():
    return uuid.uuid4().hex


def run_intake(stores, mock_url, documents_dir, policies_dir, transport=None):
    """Load procedure sources once, then write one revision per case id.

    Case ids and document source ids come from GET /v1/cases. A listed source
    with no file fails the run with error_code document_missing and writes no
    revision for that case. Calling this again inserts the next revision.
    """
    fetch = transport or default_transport
    trace_id = uuid.uuid4().hex
    health_status, health = fetch(_url(mock_url, "/health"))
    stores.trace.append_event(
        trace_id=trace_id,
        span_id=_span(),
        step="1",
        actor="intake",
        status="ok" if health_status == 200 and health.get("status") == "ok" else "error",
        error_code=None if health_status == 200 and health.get("status") == "ok" else "health_failed",
        mock_http_status=health_status,
        started_at=_now(),
        attempt=1,
    )
    if health_status != 200 or health.get("status") != "ok":
        raise IntakeError("health_failed", "mock health check failed")

    cases_status, cases_body = fetch(_url(mock_url, "/v1/cases"))
    stores.trace.append_event(
        trace_id=trace_id,
        span_id=_span(),
        step="1",
        actor="intake",
        status="ok" if cases_status == 200 else "error",
        error_code=None if cases_status == 200 else "cases_unavailable",
        mock_http_status=cases_status,
        started_at=_now(),
        attempt=1,
    )
    if cases_status != 200 or not isinstance(cases_body.get("cases"), list):
        raise IntakeError("cases_unavailable", "case list was not available")

    procedures = load_procedures(policies_dir)
    stores.trace.append_event(
        trace_id=trace_id,
        span_id=_span(),
        step="1",
        actor="intake",
        status="ok",
        output_sha256=digest([{"sha256": item["sha256"], "source_id": item["source_id"]} for item in procedures]),
        started_at=_now(),
        attempt=1,
    )

    cases, duplicate_api_ids = _unique_cases(cases_body["cases"])
    loaded, missing = _read_cases(cases, documents_dir)
    if missing:
        for item in missing:
            stores.trace.append_event(
                trace_id=trace_id,
                span_id=_span(),
                step="1",
                actor="intake",
                status="error",
                case_id=item["case_id"],
                error_code="document_missing",
                started_at=_now(),
                attempt=1,
            )
        raise DocumentMissing(missing)

    payloads = [_payload(item, procedures, duplicate_api_ids) for item in loaded]
    _mark_duplicate_losses(payloads)
    revisions = []
    for payload in payloads:
        started = time.perf_counter()
        revision = stores.input.append_revision(
            payload["case_id"],
            payload,
            document_set_sha256=payload["document_set_sha256"],
        )
        stores.trace.append_event(
            trace_id=trace_id,
            span_id=_span(),
            step="1",
            actor="intake",
            status="ok",
            case_id=payload["case_id"],
            input_revision=revision.revision,
            output_sha256=revision.document_set_sha256,
            duration_ms=int((time.perf_counter() - started) * 1000),
            started_at=_now(),
            attempt=1,
        )
        revisions.append(revision)
    return {"trace_id": trace_id, "revisions": revisions, "procedure_sources": procedures}


def _unique_cases(cases):
    ordered = []
    seen = set()
    duplicates = []
    for case in cases:
        if not isinstance(case, dict) or not isinstance(case.get("case_id"), str):
            raise IntakeError("cases_unavailable", "case list entry is missing case_id")
        if not isinstance(case.get("documents"), list) or not isinstance(case.get("intake_source"), str):
            raise IntakeError("cases_unavailable", "case list entry is missing documents or intake_source")
        case_id = case["case_id"]
        if case_id in seen:
            duplicates.append(case_id)
            continue
        seen.add(case_id)
        ordered.append(case)
    return ordered, duplicates


def _read_cases(cases, documents_dir):
    loaded = []
    missing = []
    for case in cases:
        documents = []
        for source_id in case["documents"]:
            found = read_source(documents_dir, source_id) if isinstance(source_id, str) else None
            if found is None:
                missing.append({"case_id": case["case_id"], "source_id": str(source_id)})
                continue
            path, data, text = found
            documents.append({
                "source_id": source_id,
                "sha256": file_sha256(data),
                "raw_text": text,
                "path": path,
            })
        loaded.append({
            "case_id": case["case_id"],
            "intake_source": case["intake_source"],
            "documents": documents,
        })
    return loaded, missing


def _payload(item, procedures, duplicate_api_ids):
    raw_text = {}
    parsed_docs = []
    duplicate_fields = []
    intake_parsed = None
    estimate = None
    report = None
    for document in item["documents"]:
        kind = document_kind(document["source_id"], item["intake_source"])
        parsed = parse_document(document["raw_text"], labels_for(kind))
        duplicate_fields.extend(parsed["duplicate_fields"])
        raw_text[document["source_id"]] = document["raw_text"]
        entry = {
            "source_id": document["source_id"],
            "kind": kind,
            "sha256": document["sha256"],
            "fields": parsed["fields"],
            "unlabeled_lines": parsed["unlabeled_lines"],
        }
        parsed_docs.append(entry)
        if kind == "intake" and document["source_id"] == item["intake_source"]:
            intake_parsed = parsed
        elif kind == "estimate" and estimate is None:
            estimate = entry
        elif kind == "report" and report is None:
            report = entry
    if intake_parsed is None:
        intake_parsed = {"account_text": "", "fields": {}, "duplicate_fields": [], "unlabeled_lines": []}
    fields = intake_parsed["fields"]
    driver_name, driver_supplied = supplied_value(fields.get("driver_name"))
    location, location_supplied = supplied_value(fields.get("incident_location"))
    injury_raw, injury = yes_no(fields.get("injury_reported_raw"))
    drivable_raw, drivable = yes_no(fields.get("vehicle_drivable_raw"))
    document_set = [{"sha256": doc["sha256"], "source_id": doc["source_id"]} for doc in parsed_docs]
    return {
        "case_id": item["case_id"],
        "intake_source": item["intake_source"],
        "account_text": intake_parsed["account_text"],
        "incident_timestamp": fields.get("incident_timestamp"),
        "policy_number": fields.get("policy_number"),
        "vehicle_id": fields.get("vehicle_id"),
        "loss_type": fields.get("loss_type"),
        "driver_name": driver_name,
        "driver_name_supplied": driver_supplied,
        "incident_location": location,
        "incident_location_supplied": location_supplied,
        "injury_reported_raw": injury_raw,
        "injury_reported": injury,
        "vehicle_drivable_raw": drivable_raw,
        "vehicle_drivable": drivable,
        "referral_indicator": fields.get("referral_indicator"),
        "loss_reference": fields.get("loss_reference"),
        "duplicate_loss": False,
        "duplicate_case_ids": [],
        "duplicate_api_ids": list(duplicate_api_ids),
        "duplicate_fields": duplicate_fields,
        "raw_text": raw_text,
        "documents": parsed_docs,
        "estimate": None if estimate is None else {
            "source_id": estimate["source_id"],
            **estimate["fields"],
            "unlabeled_lines": estimate["unlabeled_lines"],
        },
        "report": None if report is None else {
            "source_id": report["source_id"],
            **report["fields"],
            "unlabeled_lines": report["unlabeled_lines"],
        },
        "procedure_sources": procedures,
        "document_set_sha256": digest(document_set),
    }


def _mark_duplicate_losses(payloads):
    groups = {}
    for payload in payloads:
        groups.setdefault(payload.get("loss_reference"), []).append(payload["case_id"])
    for payload in payloads:
        siblings = groups.get(payload.get("loss_reference"), [])
        if payload.get("loss_reference") and len(siblings) > 1:
            payload["duplicate_loss"] = True
            payload["duplicate_case_ids"] = sorted(siblings)
