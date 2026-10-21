"""JSON GET for case-scoped tools.

A transport failure or an HTTP 5xx is retried, up to three attempts total.
404 and every other 4xx stop on the first response.
"""

from __future__ import annotations

import json
import random
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable

from fnol_foundation.canonical import RESTRICTED_MARKERS
from fnol_hardening.backoff import backoff_seconds
from fnol_hardening.circuit import CircuitBreaker, CircuitOpenError, breaker_for, dependency_name
from fnol_hardening.privilege import authorize
from fnol_hardening.telemetry import log_span, new_span_id

MAX_ATTEMPTS = 3
_CASE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_ERROR_CODE = re.compile(r"^[A-Za-z0-9_]{1,64}$")
_TOOLS = frozenset({"policy", "claims"})

Get = Callable[[str], tuple[int, dict[str, Any] | None]]


@dataclass(frozen=True)
class HttpAttempt:
    attempt: int
    status: int
    body: dict[str, Any] | None
    duration_ms: int


def tool_url(base_url: str, case_id: str, tool: str) -> str:
    """Build one case-scoped tool URL. Rejects path characters in case_id."""
    if tool not in _TOOLS:
        raise ValueError("tool is not available")
    if not isinstance(case_id, str) or _CASE_ID.fullmatch(case_id) is None:
        raise ValueError("case_id is not a safe token")
    if not isinstance(base_url, str) or not base_url:
        raise ValueError("base_url is required")
    return f"{base_url.rstrip('/')}/v1/cases/{case_id}/{tool}"


def public_error(body: dict[str, Any] | None) -> str:
    """Short error code safe to store. Never the response message or a restricted value."""
    if not isinstance(body, dict):
        return "http_error"
    code = body.get("error")
    if not isinstance(code, str) or _ERROR_CODE.fullmatch(code) is None:
        return "http_error"
    if any(marker in code for marker in RESTRICTED_MARKERS):
        return "restricted_value"
    return code


def default_get(url: str, timeout: float = 10) -> tuple[int, dict[str, Any] | None]:
    request = urllib.request.Request(url, method="GET", headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, _object(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, _object(exc.read())
    except (urllib.error.URLError, TimeoutError, OSError):
        return 0, {"error": "transport_error"}


def _object(raw: bytes) -> dict[str, Any] | None:
    try:
        body = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return body if isinstance(body, dict) else None


def _retryable(status: int) -> bool:
    return status == 0 or status >= 500


def fetch_with_retries(
    url: str,
    *,
    max_attempts: int = MAX_ATTEMPTS,
    get: Get | None = None,
    sleeper: Callable[[float], None] | None = None,
    breaker: CircuitBreaker | None = None,
    rng: random.Random | None = None,
    base_delay: float = 0.05,
    trace_id: str | None = None,
) -> tuple[tuple[HttpAttempt, ...], dict[str, Any] | None]:
    """GET url. Retry transport errors and HTTP 5xx with exponential backoff and jitter.

    At most ``max_attempts`` calls (three by AUTO-TRIAGE-01). A 4xx stops
    immediately and does not count as a circuit failure. When the dependency
    circuit is open, the call returns at once with error ``circuit_open``
    instead of hanging. The caller then routes manual_review.
    """
    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")
    getter = get or default_get
    pause = sleeper or time.sleep
    circuit = breaker if breaker is not None else breaker_for(dependency_name(url))
    _authorize_tool_read(url)
    attempts: list[HttpAttempt] = []
    for number in range(1, max_attempts + 1):
        try:
            circuit_state = circuit.before_call()
        except CircuitOpenError:
            attempt = HttpAttempt(number, 0, {"error": "circuit_open"}, 0)
            attempts.append(attempt)
            _log_tool_attempt(
                url, attempt, circuit="open", backoff_ms=0, trace_id=trace_id, span_id=new_span_id()
            )
            break
        started = time.perf_counter()
        status, body = getter(url)
        if body is not None and not isinstance(body, dict):
            body = None
        duration_ms = int((time.perf_counter() - started) * 1000)
        attempt = HttpAttempt(number, status, body, duration_ms)
        attempts.append(attempt)
        if status == 200 and isinstance(body, dict):
            circuit.record_success()
            _log_tool_attempt(
                url, attempt, circuit=circuit.state, backoff_ms=0, trace_id=trace_id, span_id=new_span_id()
            )
            return tuple(attempts), body
        if not _retryable(status):
            _log_tool_attempt(
                url, attempt, circuit=circuit.state, backoff_ms=0, trace_id=trace_id, span_id=new_span_id()
            )
            break
        circuit.record_failure()
        delay = 0.0
        if number < max_attempts and circuit.state != "open":
            delay = backoff_seconds(number, base=base_delay, rng=rng)
            pause(delay)
        _log_tool_attempt(
            url,
            attempt,
            circuit=circuit.state,
            backoff_ms=int(delay * 1000),
            trace_id=trace_id,
            span_id=new_span_id(),
            circuit_state_before=circuit_state,
        )
        if number == max_attempts or circuit.state == "open":
            break
    return tuple(attempts), None


def _authorize_tool_read(url: str) -> None:
    """Policy and claims reads are the only tool GETs this client may make."""
    name = dependency_name(url)
    if name == "policy":
        authorize("policy", "read_policy")
    elif name == "claims":
        authorize("rules", "read_claims")


def _log_tool_attempt(
    url: str,
    attempt: HttpAttempt,
    *,
    circuit: str,
    backoff_ms: int,
    trace_id: str | None,
    span_id: str,
    circuit_state_before: str | None = None,
) -> None:
    log_span({
        "trace_id": trace_id or "",
        "span_id": span_id,
        "event": "tool_http",
        "actor": dependency_name(url),
        "status": "ok" if attempt.status == 200 else "error",
        "dependency": dependency_name(url),
        "attempt": attempt.attempt,
        "http_status": attempt.status,
        "duration_ms": attempt.duration_ms,
        "backoff_ms": backoff_ms,
        "circuit": circuit,
        "circuit_before": circuit_state_before,
        "error_code": None if attempt.status == 200 else public_error(attempt.body),
    })
