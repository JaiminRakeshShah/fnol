"""Select the single policy interval that contains the incident timestamp.

Intervals include effective_from and exclude effective_to. Zero matches or more
than one match leave selected_policy_version null. This module does not guess.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def parse_utc(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def select_policy(incident_timestamp: object, payload: dict[str, Any]) -> dict[str, Any]:
    """Return the decision body for one redacted policy payload."""
    source_id = payload.get("source_id") if isinstance(payload.get("source_id"), str) else None
    policies = payload.get("policies")
    if not isinstance(policies, list):
        return _body(None, False, "malformed", None, [], source_id)
    incident = parse_utc(incident_timestamp)
    if incident is None:
        return _body(None, True, "unparsed", None, [], source_id)

    matches: list[dict[str, Any]] = []
    for item in policies:
        if not isinstance(item, dict):
            return _body(None, False, "malformed", None, [], source_id)
        start = parse_utc(item.get("effective_from"))
        end = parse_utc(item.get("effective_to"))
        if start is None or end is None:
            return _body(None, False, "malformed", None, [], source_id)
        if start <= incident < end:
            matches.append(item)

    if len(matches) == 0:
        return _body(None, True, "zero", None, [], source_id)
    if len(matches) > 1:
        return _body(None, True, "ambiguous", None, [], source_id)

    chosen = matches[0]
    version = chosen.get("version")
    wording = chosen.get("wording_source")
    endorsements = chosen.get("endorsements")
    if not isinstance(version, str) or not version:
        return _body(None, False, "malformed", None, [], source_id)
    if wording is not None and not isinstance(wording, str):
        return _body(None, False, "malformed", None, [], source_id)
    if not isinstance(endorsements, list) or not all(isinstance(item, str) for item in endorsements):
        return _body(None, False, "malformed", None, [], source_id)
    return _body(version, True, "matched", wording, list(endorsements), source_id)


def _body(version, available, reason, wording, endorsements, source_id) -> dict[str, Any]:
    return {
        "selected_policy_version": version,
        "policy_available": available,
        "reason": reason,
        "wording_source": wording,
        "endorsements": endorsements,
        "source_id": source_id,
    }
