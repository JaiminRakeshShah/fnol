"""Pure AUTO-TRIAGE-01 interval selection. No I/O."""
from __future__ import annotations

from datetime import datetime

PROCEDURE_ID = "AUTO-TRIAGE-01"


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def choose_version(policies: list[dict], incident_timestamp: str) -> tuple[dict | None, str]:
    """Half-open interval rule: effective_from <= incident < effective_to.

    Returns (row, "one") for exactly one match, (None, "zero") or (None, "multiple") otherwise.
    """
    incident = _parse(incident_timestamp)
    matches = [p for p in policies
               if _parse(p["effective_from"]) <= incident < _parse(p["effective_to"])]
    if len(matches) == 1:
        return matches[0], "one"
    return None, ("zero" if not matches else "multiple")


def decide(payload: dict, incident_timestamp: str, known_sources: set[str] | None = None) -> dict:
    """Turn a redacted policy snapshot into the Step 2 decision.

    known_sources is the set of procedure source ids intake loaded from the policies
    directory. A wording_source or endorsement that is not in that set is reported as
    missing and kept out of policy_ids so nothing cites text that does not exist.
    """
    row, reason = choose_version(payload.get("policies", []), incident_timestamp)
    result = {
        "source_id": payload.get("source_id"),
        "policy_number": payload.get("policy_number"),
        "vehicle_id": payload.get("vehicle_id"),
        "selected_policy_version": None,
        "reason": reason,
        "policy_ids": [PROCEDURE_ID],
        "missing_sources": [],
    }
    if row is None:
        return result
    wanted = [row.get("wording_source"), *row.get("endorsements", [])]
    wanted = [w for w in wanted if w]
    missing = [w for w in wanted if known_sources is not None and w not in known_sources]
    result["selected_policy_version"] = row["version"]
    result["wording_source"] = row.get("wording_source")
    result["endorsements"] = list(row.get("endorsements", []))
    result["missing_sources"] = missing
    if missing:
        result["reason"] = "wording_missing"
    else:
        result["policy_ids"] = [PROCEDURE_ID, *wanted]
    return result
