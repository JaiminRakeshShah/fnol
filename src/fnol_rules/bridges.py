"""Adapters from foundation Stores onto Rules InputStore / EventLog protocols."""
from __future__ import annotations

import uuid
from typing import Any

from fnol_foundation.stores import Stores


class FoundationInputBridge:
    """Writes claims snapshots into input.sqlite tool_payloads."""

    def __init__(self, stores: Stores) -> None:
        self._stores = stores

    def put_claims(self, case_id: str, raw_json: dict[str, Any]) -> None:
        self._stores.input.put_tool_payload(case_id, "claims", raw_json)


class FoundationEventBridge:
    """Appends Step-3 tool attempts onto the shared trace.sqlite flight recorder."""

    def __init__(self, stores: Stores, *, trace_id: str | None = None) -> None:
        self._stores = stores
        self.trace_id = trace_id or uuid.uuid4().hex

    def append(self, event: str, case_id: str = "", **detail: Any) -> None:
        status_code = detail.get("status")
        ok = status_code == 200 if status_code is not None else event != "tool_read"
        self._stores.trace.append_event(
            trace_id=self.trace_id,
            span_id=uuid.uuid4().hex,
            step="3",
            actor="rules",
            rule_version="AUTO-TRIAGE-01",
            status="ok" if ok else "error",
            case_id=case_id or None,
            attempt=detail.get("attempt"),
            mock_http_status=status_code,
            error_code=detail.get("error"),
        )
