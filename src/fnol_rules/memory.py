"""In-memory InputStore / EventLog for tests."""
from __future__ import annotations

from typing import Any

from fnol_rules.canonical import canonical


class MemoryInputStore:
    def __init__(self) -> None:
        self.claims: dict[str, str] = {}

    def put_claims(self, case_id: str, raw_json: dict[str, Any]) -> None:
        self.claims[case_id] = canonical(raw_json)


class MemoryEventLog:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def append(self, event: str, case_id: str = "", **detail: Any) -> None:
        self.events.append({"event": event, "case_id": case_id, **detail})
