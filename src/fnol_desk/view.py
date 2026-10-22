"""Read-only queue and case view for the Harborlight FNOL Desk.

Joins the latest draft with route/policy/citations decisions and the mock
review row. The browser never joins those stores itself.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fnol_analyst.draft import (
    BOUNDARY,
    POLICY_REASON_TEXT,
    REASON_TEXT,
    _content_check_notes,
)
from fnol_foundation.stores import DraftRecord, Stores, connect
from tools.runtime import connect as mock_connect

ROOT = Path(__file__).resolve().parents[2]


def default_mock_state() -> Path:
    return ROOT / ".state" / "mock.sqlite"


def _display(value: Any) -> str:
    if value is None:
        return "Unknown"
    if value is True:
        return "Yes"
    if value is False:
        return "No"
    text = str(value).strip()
    return text if text else "Unknown"


def _reason_phrases(reasons: list[str]) -> list[str]:
    return [REASON_TEXT.get(item, item) for item in reasons]


def _referral_value(
    draft: dict[str, Any],
    route: dict[str, Any] | None,
    revision_payload: dict[str, Any] | None,
) -> str | None:
    route = route or {}
    for source in (revision_payload, route, draft.get("facts") if isinstance(draft.get("facts"), dict) else None):
        if not isinstance(source, dict):
            continue
        value = source.get("referral_indicator")
        if isinstance(value, str) and value.strip() and value.strip().lower() != "none":
            return value.strip()
    reasons = [r for r in (route.get("reasons") or []) if isinstance(r, str)]
    if "repair_amount_conflict" in reasons:
        return "repair_amount_conflict"
    return None


def _watch_flags(
    draft: dict[str, Any],
    route: dict[str, Any] | None,
    revision_payload: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    """Worded flags for the identity bar. Color is secondary to the label."""
    flags: list[dict[str, str]] = []
    route = route or {}
    facts = draft.get("facts") if isinstance(draft.get("facts"), dict) else {}
    injury = route.get("injury_reported")
    if injury is None:
        injury = facts.get("injury_reported")
    if injury is True:
        flags.append({"id": "injury", "tone": "urgent", "label": "Injury reported"})
    drivable = route.get("vehicle_drivable")
    if drivable is False:
        flags.append({"id": "not_drivable", "tone": "urgent", "label": "Vehicle not drivable"})
    reasons = [r for r in (route.get("reasons") or []) if isinstance(r, str)]
    if _referral_value(draft, route, revision_payload):
        flags.append(
            {
                "id": "referral",
                "tone": "watch",
                "label": "Referral indicator supplied — not a fraud finding",
            }
        )
    conflicts = [c for c in (route.get("conflicts") or []) if isinstance(c, str)]
    if conflicts or "conflicting_facts" in reasons:
        flags.append({"id": "conflict", "tone": "review", "label": "Sources disagree"})
    missing = [
        m
        for m in (route.get("missing_information") or draft.get("missing_information") or [])
        if isinstance(m, str)
    ]
    if missing:
        flags.append({"id": "missing", "tone": "review", "label": "Fields missing"})
    version = facts.get("selected_policy_version") if isinstance(facts, dict) else None
    if version is None and (
        "policy_version_null" in reasons
        or ("selected_policy_version" in route and route.get("selected_policy_version") is None)
    ):
        flags.append(
            {
                "id": "policy_period",
                "tone": "review",
                "label": "Policy interval needs a person",
            }
        )
    if draft.get("duplicate_delivery") is True or route.get("duplicate_delivery") is True:
        flags.append({"id": "duplicate", "tone": "watch", "label": "Duplicate intake delivery"})
    if route.get("claims_available") is False or "claims_unavailable" in reasons:
        flags.append({"id": "claims", "tone": "watch", "label": "Claims history unavailable"})
    if draft.get("safety_status") == "fallback":
        flags.append({"id": "safety", "tone": "watch", "label": "Summary safety fallback"})
    if "dangerous_content" in reasons:
        flags.append(
            {
                "id": "injection",
                "tone": "urgent",
                "label": "Suspected prompt injection — text not followed",
            }
        )
    routing = draft.get("routing") or route.get("route")
    if routing == "manual_review":
        flags.append({"id": "manual", "tone": "review", "label": "Manual review route"})
    seen: set[str] = set()
    out: list[dict[str, str]] = []
    for flag in flags:
        if flag["id"] in seen:
            continue
        seen.add(flag["id"])
        out.append(flag)
    return out


def _short_hash(full: str | None) -> str:
    if not full or not isinstance(full, str):
        return ""
    return full[:10]


def _review_for_case(mock_state: Path, case_id: str, draft_hash: str | None) -> dict[str, Any] | None:
    if not mock_state.exists():
        return None
    with mock_connect(mock_state) as db:
        # Prefer a pending review matching this draft hash; else latest for the case.
        if draft_hash:
            row = db.execute(
                """SELECT id, case_id, hash, status, reviewer FROM reviews
                   WHERE case_id = ? AND hash = ?
                   ORDER BY rowid DESC LIMIT 1""",
                (case_id, draft_hash),
            ).fetchone()
            if row:
                return dict(row)
        row = db.execute(
            """SELECT id, case_id, hash, status, reviewer FROM reviews
               WHERE case_id = ?
               ORDER BY rowid DESC LIMIT 1""",
            (case_id,),
        ).fetchone()
        return dict(row) if row else None


def _list_draft_rows(stores: Stores) -> list[DraftRecord]:
    """Latest draft per case, newest cases first."""
    with connect(stores.output.path) as db:
        rows = db.execute(
            """SELECT d.* FROM drafts d
               INNER JOIN (
                 SELECT case_id, MAX(created_at) AS max_created
                 FROM drafts GROUP BY case_id
               ) latest
               ON d.case_id = latest.case_id AND d.created_at = latest.max_created
               ORDER BY d.created_at DESC"""
        ).fetchall()
    # Resolve ties / multiples at same timestamp via OutputStore helper
    by_case: dict[str, DraftRecord] = {}
    for row in rows:
        record = stores.output._record(row)
        existing = by_case.get(record.case_id)
        if existing is None or record.created_at >= existing.created_at:
            by_case[record.case_id] = record
    return sorted(by_case.values(), key=lambda r: r.created_at, reverse=True)


def _decision_body(stores: Stores, case_id: str, revision: int | None, kind: str) -> dict[str, Any] | None:
    if revision is None:
        return None
    stored = stores.input.get_decision(case_id, revision, kind)
    if stored is None:
        return None
    body = stored.get("body")
    return body if isinstance(body, dict) else None


def _revision_payload(stores: Stores, case_id: str, revision: int | None) -> dict[str, Any] | None:
    if revision is None:
        return None
    rev = stores.input.get_revision(case_id, revision)
    if rev is None:
        return None
    return rev.payload if isinstance(rev.payload, dict) else None


def _queue_row(
    record: DraftRecord,
    route: dict[str, Any] | None,
    review: dict[str, Any] | None,
    revision_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    draft = record.draft
    facts = draft.get("facts") if isinstance(draft.get("facts"), dict) else {}
    flags = _watch_flags(draft, route, revision_payload)
    review_status = "none"
    if review:
        review_status = review.get("status") or "none"
    elif record.status == "in_review":
        review_status = "pending"
    elif record.outcome:
        review_status = record.outcome
    return {
        "case_id": record.case_id,
        "draft_id": record.draft_id,
        "policy_number": facts.get("policy_number"),
        "classification": draft.get("classification"),
        "routing": draft.get("routing"),
        "flags": flags,
        "flag_labels": [f["label"] for f in flags],
        "created_at": record.created_at,
        "waiting_since": record.created_at,
        "review_status": review_status,
        "review_id": (review or {}).get("id") or record.review_id,
        "draft_hash": record.draft_hash,
        "short_hash": _short_hash(record.draft_hash),
        "safety_status": draft.get("safety_status"),
        "watch": bool(flags),
    }


def list_queue(
    *,
    team: str,
    stores: Stores | None = None,
    mock_state: Path | None = None,
) -> list[dict[str, Any]]:
    stores = stores or Stores()
    mock_state = Path(mock_state) if mock_state is not None else default_mock_state()
    rows: list[dict[str, Any]] = []
    for record in _list_draft_rows(stores):
        route = _decision_body(stores, record.case_id, record.input_revision, "route")
        review = _review_for_case(mock_state, record.case_id, record.draft_hash)
        revision_payload = _revision_payload(stores, record.case_id, record.input_revision)
        row = _queue_row(record, route, review, revision_payload)
        if team == "handlers":
            # Handlers see drafts awaiting them, plus recently decided for context
            if row["review_status"] not in {"pending", "approved", "rejected", "none", "in_review"}:
                continue
            if row["review_status"] == "none" and record.status == "recorded":
                # Not yet sent — still list so they know work is coming; prefer pending
                pass
            rows.append(row)
        elif team == "analysts":
            rows.append(row)
        elif team == "security":
            if row["watch"] or row["review_status"] == "pending":
                rows.append(row)
        else:
            rows.append(row)
    # Handlers: pending first
    if team == "handlers":
        rows.sort(
            key=lambda r: (
                0 if r["review_status"] == "pending" else 1,
                r["waiting_since"] or "",
            )
        )
    return rows


def case_view(
    case_id: str,
    *,
    team: str,
    stores: Stores | None = None,
    mock_state: Path | None = None,
) -> dict[str, Any] | None:
    stores = stores or Stores()
    mock_state = Path(mock_state) if mock_state is not None else default_mock_state()
    record = stores.output.latest_draft(case_id)
    if record is None:
        return None
    draft = record.draft
    route = _decision_body(stores, case_id, record.input_revision, "route") or {}
    policy = _decision_body(stores, case_id, record.input_revision, "policy") or {}
    citations_decision = _decision_body(stores, case_id, record.input_revision, "citations") or {}
    revision_payload = _revision_payload(stores, case_id, record.input_revision) or {}
    review = _review_for_case(mock_state, case_id, record.draft_hash)

    facts = draft.get("facts") if isinstance(draft.get("facts"), dict) else {}
    missing = [
        m
        for m in (route.get("missing_information") or draft.get("missing_information") or [])
        if isinstance(m, str)
    ]
    follow_ups = draft.get("follow_up_questions") or []
    reasons = [r for r in (route.get("reasons") or []) if isinstance(r, str)]
    conflicts = [c for c in (route.get("conflicts") or []) if isinstance(c, str)]
    citations = draft.get("citations") or citations_decision.get("citations") or []
    referral = _referral_value(draft, route, revision_payload)

    version = facts.get("selected_policy_version")
    if version is None:
        version = route.get("selected_policy_version")
    policy_reason = policy.get("reason") if isinstance(policy.get("reason"), str) else None
    policy_note = None
    if version is None and policy_reason in POLICY_REASON_TEXT:
        policy_note = POLICY_REASON_TEXT[policy_reason]
    elif policy_reason == "wording_missing":
        policy_note = POLICY_REASON_TEXT[policy_reason]

    review_status = "none"
    if review:
        review_status = review.get("status") or "none"
    elif record.status == "in_review":
        review_status = "pending"

    hash_matches = bool(
        review
        and review.get("hash") == record.draft_hash
        and review.get("status") == "pending"
    )

    can_accept = team == "handlers" and hash_matches
    can_reject = can_accept
    can_send = team == "analysts" and review_status not in {"pending", "approved"}

    evidence_summary = draft.get("evidence_summary")
    safety_status = draft.get("safety_status") or "skipped"
    summary_available = (
        isinstance(evidence_summary, str)
        and evidence_summary.strip()
        and safety_status == "passed"
    )

    return {
        "case_id": case_id,
        "draft_id": record.draft_id,
        "input_revision": record.input_revision,
        "draft_hash": record.draft_hash,
        "short_hash": _short_hash(record.draft_hash),
        "created_at": record.created_at,
        "identity": {
            "case_id": case_id,
            "policy_number": facts.get("policy_number"),
            "vehicle_id": facts.get("vehicle_id"),
            "incident_timestamp": facts.get("incident_timestamp"),
            "classification": draft.get("classification"),
            "routing": draft.get("routing"),
            "review_status": review_status,
        },
        "flags": _watch_flags(draft, route, revision_payload),
        "decision": {
            "eyebrow": "Deterministic · AUTO-TRIAGE-01",
            "classification": draft.get("classification"),
            "routing": draft.get("routing") or route.get("route"),
            "route_rule": route.get("route_rule") or "AUTO-TRIAGE-01",
            "route_reasons": _reason_phrases(reasons),
            "route_reason_codes": reasons,
            "facts": {
                "policy_number": _display(facts.get("policy_number")),
                "vehicle_id": _display(facts.get("vehicle_id")),
                "incident_timestamp": _display(facts.get("incident_timestamp")),
                "injury_reported": _display(
                    route.get("injury_reported")
                    if "injury_reported" in route
                    else facts.get("injury_reported")
                ),
                "vehicle_drivable": _display(route.get("vehicle_drivable")),
                "referral_indicator": _display(referral) if referral else "None",
                "selected_policy_version": _display(version),
                "duplicate_delivery": _display(
                    draft.get("duplicate_delivery")
                    if "duplicate_delivery" in draft
                    else route.get("duplicate_delivery")
                ),
            },
            "conflicts": conflicts,
            "missing_information": missing,
            "follow_up_questions": follow_ups,
            "content_check_notes": _content_check_notes(route),
            "extra_fields": [
                {
                    "source_id": item.get("source_id"),
                    "label": item.get("label"),
                }
                for item in (route.get("extra_fields") or [])
                if isinstance(item, dict)
            ],
            "injection_model_status": route.get("injection_model_status"),
            "policy_version": version,
            "policy_note": policy_note,
            "policy_ids": draft.get("policy_ids") or policy.get("policy_ids") or [],
            "citations": [
                {
                    "claim": item.get("claim"),
                    "source_id": item.get("source_id"),
                    "quote": item.get("quote"),
                }
                for item in citations
                if isinstance(item, dict)
            ],
            "narrative": draft.get("narrative"),
        },
        "summary": {
            "eyebrow": "Draft for the handler",
            "available": summary_available,
            "text": evidence_summary if summary_available else None,
            "safety_status": safety_status,
            "empty_reason": _summary_empty_reason(evidence_summary, safety_status),
            "boundary": BOUNDARY,
        },
        "review": {
            "review_id": (review or {}).get("id") or record.review_id,
            "status": review_status,
            "reviewer": (review or {}).get("reviewer"),
            "hash_matches_pending": hash_matches,
        },
        "actions": {
            "can_accept": can_accept,
            "can_reject": can_reject,
            "can_send": can_send,
            "accept_label": f"Accept draft {_short_hash(record.draft_hash)}"
            if can_accept
            else "Accept",
            "handler_only_note": "Only a handler can accept or reject.",
        },
        "team": team,
    }


def _summary_empty_reason(evidence_summary: Any, safety_status: str) -> str | None:
    if isinstance(evidence_summary, str) and evidence_summary.strip() and safety_status == "passed":
        return None
    if safety_status == "skipped":
        return "No model summary was generated for this draft (AI path skipped)."
    if safety_status == "fallback":
        return "The model summary did not pass the safety scan; only the deterministic file stands."
    if evidence_summary is None or (isinstance(evidence_summary, str) and not evidence_summary.strip()):
        return "No handler summary is attached to this draft."
    return "Handler summary is unavailable."


def list_audit(*, mock_state: Path | None = None, limit: int = 200) -> list[dict[str, Any]]:
    mock_state = Path(mock_state) if mock_state is not None else default_mock_state()
    if not mock_state.exists():
        return []
    with mock_connect(mock_state) as db:
        rows = db.execute(
            "SELECT seq, at, event, case_id, detail FROM audit ORDER BY seq ASC"
        ).fetchall()
    out: list[dict[str, Any]] = []
    for row in rows[-limit:]:
        detail = row["detail"]
        try:
            detail_obj = json.loads(detail) if detail else {}
        except json.JSONDecodeError:
            detail_obj = {"raw": detail}
        out.append(
            {
                "seq": row["seq"],
                "at": row["at"],
                "event": row["event"],
                "case_id": row["case_id"],
                "detail": detail_obj,
            }
        )
    return out
