"""Thin store interfaces — teammates plug in real Input DB / Event Log."""
from __future__ import annotations

from typing import Any, Protocol


class InputStore(Protocol):
    def put_claims(self, case_id: str, raw_json: dict[str, Any]) -> None: ...


class EventLog(Protocol):
    def append(self, event: str, case_id: str = "", **detail: Any) -> None: ...
