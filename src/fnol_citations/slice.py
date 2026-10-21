"""Exact excerpts from stored raw text and raw JSON. No I/O."""

from __future__ import annotations

import json

from fnol_foundation.canonical import RestrictedValueError

from fnol_citations.guard import contains_restricted, reject_restricted_quote

CLAIM_PROCEDURE = "triage_and_potential_coverage"
CLAIM_INCIDENT = "incident_evidence"
CLAIM_CONFLICT = "fact_conflict"
CLAIM_REPAIR = "repair_amount_conflict"
CLAIM_HISTORY = "policy_or_claim_history"

# Field order is the preference order. The first safe member wins.
POLICY_JSON_KEYS = ("policies", "policy_number", "vehicle_id", "source_id")
CLAIMS_JSON_KEYS = ("existing_claims", "loss_reference", "intake_deliveries", "source_id")

# Structured disagreement the rules server already treats as a fact conflict.
# Each side is (payload field, raw-text field, source-id field, exact line prefix).
_CONFLICT_GROUPS = (
    (
        ("vehicle_id", "raw_intake", "intake_source", "Vehicle ID: "),
        ("report_vehicle_reference", "raw_report", "report_source_id", "Vehicle reference: "),
        ("estimate_vehicle", "raw_estimate", "estimate_source_id", "Vehicle: "),
    ),
    (
        ("incident_timestamp", "raw_intake", "intake_source", "Incident timestamp: "),
        ("report_incident_timestamp", "raw_report", "report_source_id", "Incident timestamp: "),
    ),
    (
        ("loss_type", "raw_intake", "intake_source", "Loss type: "),
        ("reported_loss_type", "raw_report", "report_source_id", "Reported loss type: "),
    ),
)


def json_member_quote(payload: dict, key: str) -> str:
    """One JSON member, sorted keys and standard spaces.

    The evaluator compares quotes to ``json.dumps(source, sort_keys=True)``,
    which keeps a space after ``:`` and ``,``. The stored snapshot is compact
    canonical JSON, so the quote is rendered again here. Stripping the outer
    braces leaves the member as it appears inside the full object, including
    when that object still has a sibling ``private_token`` key.
    """
    rendered = json.dumps({key: payload[key]}, sort_keys=True)
    if len(rendered) < 2 or not rendered.startswith("{") or not rendered.endswith("}"):
        raise ValueError("json member did not render as an object")
    return reject_restricted_quote(rendered[1:-1])


def first_json_quote(payload: dict | None, keys: tuple[str, ...]) -> str | None:
    """First preferred member whose rendered text passes the restricted-token guard."""
    if not payload:
        return None
    for key in keys:
        if key not in payload:
            continue
        try:
            return json_member_quote(payload, key)
        except RestrictedValueError:
            continue
    return None


def _usable(line: str) -> bool:
    text = line.strip()
    if not text or text.startswith("#") or text.startswith("Source ID:") or text.startswith("SYSTEM:"):
        return False
    return not contains_restricted(line)


def first_safe_line(raw: str) -> str | None:
    for line in raw.splitlines():
        if _usable(line):
            return line
    return None


def intake_quote(raw: str | None, account: str | None) -> str | None:
    """Account prose when it sits inside the stored file; otherwise a safe line."""
    if not raw:
        return None
    if account and not contains_restricted(account) and account in raw:
        return account
    if account:
        for part in account.splitlines():
            if part and not contains_restricted(part) and part in raw:
                return part
    return first_safe_line(raw)


def procedure_quote(source_id: str, text: str) -> str | None:
    """A short exact line from a procedure file.

    AUTO-TRIAGE-01 names the restricted marker in a later sentence. That
    sentence is never selected.
    """
    lines = text.splitlines()
    prefixes = ["Policy form:", "Endorsement:"]
    if source_id == "AUTO-TRIAGE-01":
        prefixes = ["Supported losses:", *prefixes]
    for prefix in prefixes:
        for line in lines:
            if line.startswith(prefix) and _usable(line):
                return line
    for line in lines:
        if _usable(line):
            return line
    return None


def repair_estimate_quote(raw: str | None) -> str | None:
    """The estimate line that shows a second amount, else the labeled repair amount.

    Instruction lines (``SYSTEM:``) are not evidence of the amount.
    """
    if not raw:
        return None
    usable = [line for line in raw.splitlines() if _usable(line)]
    for line in usable:
        if "XCR" in line and not line.startswith("Repair amount:"):
            return line
    for line in usable:
        if line.startswith("Repair amount:"):
            return line
    for line in usable:
        if line.startswith("Estimate reference:"):
            return line
    return None


def conflict_quotes(revision: dict) -> list[tuple[str, str]]:
    """Exact labeled lines from every source that disagrees on a fact."""
    found: list[tuple[str, str]] = []
    for group in _CONFLICT_GROUPS:
        present = []
        for field, raw_key, sid_key, prefix in group:
            value = revision.get(field)
            if value is None or value == "":
                continue
            present.append((str(value), raw_key, sid_key, prefix))
        if len({item[0] for item in present}) < 2:
            continue
        for value, raw_key, sid_key, prefix in present:
            source_id = revision.get(sid_key)
            raw = revision.get(raw_key) or ""
            line = prefix + value
            if isinstance(source_id, str) and line in raw.splitlines() and not contains_restricted(line):
                found.append((source_id, line))
    return found


def _tool_source_id(payload: dict, case_id: str, kind: str) -> str:
    source_id = payload.get("source_id")
    if isinstance(source_id, str) and source_id:
        return source_id
    return f"{case_id}-{kind}"


def build_citations(
    *,
    case_id: str,
    revision: dict,
    policy_ids: list[str],
    procedure_text: dict[str, str],
    policy_payload: dict | None,
    claims_payload: dict | None,
) -> list[dict]:
    """Citations for one case. Every quote has already passed the restricted-token guard.

    Report and estimate are included only when they are relevant: the estimate
    when ``referral_indicator`` is ``repair_amount_conflict``, and each
    disagreeing source when vehicle, timestamp, or loss type conflicts.
    Claims are omitted when ``claims_payload`` is missing.
    """
    citations: list[dict] = []
    seen: set[tuple[str, str]] = set()

    def add(claim: str, source_id: str | None, quote: str | None) -> None:
        if not source_id or not quote:
            return
        quote = reject_restricted_quote(quote)
        key = (source_id, quote)
        if key in seen:
            return
        seen.add(key)
        citations.append({"claim": claim, "source_id": source_id, "quote": quote})

    for source_id in policy_ids:
        text = procedure_text.get(source_id)
        if text:
            add(CLAIM_PROCEDURE, source_id, procedure_quote(source_id, text))

    add(
        CLAIM_INCIDENT,
        revision.get("intake_source"),
        intake_quote(revision.get("raw_intake"), revision.get("account_text")),
    )
    for source_id, quote in conflict_quotes(revision):
        add(CLAIM_CONFLICT, source_id, quote)
    if revision.get("referral_indicator") == "repair_amount_conflict":
        add(
            CLAIM_REPAIR,
            revision.get("estimate_source_id"),
            repair_estimate_quote(revision.get("raw_estimate")),
        )
    if policy_payload:
        add(
            CLAIM_HISTORY,
            _tool_source_id(policy_payload, case_id, "POLICY"),
            first_json_quote(policy_payload, POLICY_JSON_KEYS),
        )
    if claims_payload:
        add(
            CLAIM_HISTORY,
            _tool_source_id(claims_payload, case_id, "CLAIMS"),
            first_json_quote(claims_payload, CLAIMS_JSON_KEYS),
        )
    return citations
