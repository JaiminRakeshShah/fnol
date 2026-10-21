"""Rules server orchestration: fetch claims → store → route → events."""
from __future__ import annotations

from typing import Any, Callable

from fnol_foundation.stores import Stores
from fnol_rules.bridges import FoundationEventBridge, FoundationInputBridge
from fnol_rules.claims import ClaimsFetchResult, fetch_claims
from fnol_rules.protocols import EventLog, InputStore
from fnol_rules.route import route
from fnol_rules.types import PolicyResult, RouteResult, StructuredFields


def run_rules(
    case_id: str,
    fields: StructuredFields,
    policy: PolicyResult,
    *,
    base_url: str,
    input_store: InputStore | None = None,
    event_log: EventLog | None = None,
    stores: Stores | None = None,
    fetch: Callable[..., ClaimsFetchResult] | None = None,
) -> RouteResult:
    """Fetch claims, persist canonical payload, route. Prefer `stores` when integrating."""
    if stores is not None:
        input_store = input_store or FoundationInputBridge(stores)
        event_log = event_log or FoundationEventBridge(stores)
    if input_store is None or event_log is None:
        raise TypeError("provide stores=... or both input_store= and event_log=")

    fetcher = fetch or fetch_claims
    result = fetcher(case_id, base_url)

    for attempt in result.attempts:
        detail: dict[str, Any] = {
            "tool": "claims",
            "attempt": attempt.attempt,
            "status": attempt.status,
        }
        if attempt.body and "error" in attempt.body:
            detail["error"] = attempt.body.get("error")
        event_log.append("tool_read", case_id, **detail)

    if result.raw_json is not None:
        input_store.put_claims(case_id, result.raw_json)
        event_log.append(
            "claims_stored",
            case_id,
            source_id=result.raw_json.get("source_id"),
            status=200,
        )

    return route(fields, policy, result.snapshot)
