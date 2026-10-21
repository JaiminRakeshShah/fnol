"""Structured JSON logs with OpenTelemetry-style trace and span ids.

One JSON object per line. Restricted markers are redacted before the line
is written. Destinations: FNOL_LOG_PATH (append) and stderr when
FNOL_LOG_STDERR is unset or "1". Set FNOL_LOG_STDERR=0 to silence stderr.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import uuid
from datetime import datetime, timezone
from typing import Any

from fnol_foundation.canonical import RESTRICTED_MARKERS

_lock = threading.Lock()
_OMIT = frozenset({"shadow_narrative", "draft", "raw_json", "quote"})


def new_trace_id() -> str:
    return uuid.uuid4().hex


def new_span_id() -> str:
    return uuid.uuid4().hex[:16]


def _redact(value: Any) -> Any:
    if isinstance(value, str):
        redacted = value
        for marker in RESTRICTED_MARKERS:
            if marker in redacted:
                redacted = redacted.replace(marker, "[restricted]")
        return redacted
    if isinstance(value, dict):
        return {str(key): _redact(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redact(item) for item in value]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return _redact(str(value))


def log_span(fields: dict[str, Any]) -> dict[str, Any]:
    """Write one span. Returns the record that was logged."""
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "severity": "ERROR" if fields.get("status") == "error" else "INFO",
        "trace_id": fields.get("trace_id") or "",
        "span_id": fields.get("span_id") or new_span_id(),
        "parent_span_id": fields.get("parent_span_id"),
        "name": fields.get("event") or fields.get("name") or "span",
        "attributes": {},
    }
    attributes = {}
    for key, value in fields.items():
        if key in {"trace_id", "span_id", "parent_span_id", "event", "name"}:
            continue
        if key in _OMIT:
            attributes[key] = "[omitted]"
            continue
        attributes[key] = value
    record["attributes"] = _redact(attributes)
    line = json.dumps(record, sort_keys=True, ensure_ascii=False, default=str)
    _write(line)
    return record


def _write(line: str) -> None:
    path = os.environ.get("FNOL_LOG_PATH", "").strip()
    stderr_flag = os.environ.get("FNOL_LOG_STDERR", "1").strip()
    with _lock:
        if path:
            with open(path, "a", encoding="utf-8") as handle:
                handle.write(line + "\n")
        if stderr_flag != "0":
            sys.stderr.write(line + "\n")
            sys.stderr.flush()
