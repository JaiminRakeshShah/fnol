"""JSON HTTP for Bedrock. The bearer token is sent and never returned or logged."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Callable

from fnol_hardening.backoff import backoff_seconds
from fnol_hardening.circuit import CircuitOpenError, breaker_for
from fnol_hardening.privilege import PrivilegeError, action_for_http, authorize
from fnol_hardening.telemetry import log_span, new_span_id

MAX_ATTEMPTS = 3

Sleeper = Callable[[int], None]


def _default_sleeper(attempt: int) -> None:
    """Sleep exponential backoff with full jitter. ``attempt`` stays 1-based.

    Callers that inject a sleeper still receive the attempt number so they
    can count retries. The default sleeper turns that number into a delay.
    """
    time.sleep(backoff_seconds(attempt))


def _authorize_shadow(method: str, url: str) -> None:
    """Allow a model call. Refuse every claims-mock and payment action.

    ``action_for_http`` returns ``unsupported_operation`` for a Bedrock or
    local model URL. Any mapped copilot action, including payment, is denied
    before a socket opens.
    """
    action = action_for_http(method, url)
    if action != "unsupported_operation":
        raise PrivilegeError("shadow", action)
    authorize("shadow", "write_summary_slot")


def request_json(
    url: str,
    *,
    method: str,
    api_key: str,
    body: dict | None = None,
    extra_headers: dict[str, str] | None = None,
    timeout: float = 60,
    sleeper: Sleeper | None = None,
    max_attempts: int = MAX_ATTEMPTS,
    trace_id: str | None = None,
) -> tuple[int, dict[str, str], dict]:
    """Call url. Retry transport errors, 429, and HTTP 5xx at most three times.

    Backoff is exponential with jitter. The Bedrock circuit opens after
    repeated failures and then fails fast instead of hanging. The bearer
    token is never written to the span.
    """
    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")
    _authorize_shadow(method, url)
    pause = sleeper or _default_sleeper
    circuit = breaker_for("bedrock")
    last = (0, {}, {})
    for attempt in range(1, max_attempts + 1):
        span_id = new_span_id()
        try:
            circuit.before_call()
        except CircuitOpenError:
            _log_model_attempt(
                url, method, attempt, 0, "open", trace_id=trace_id, span_id=span_id, error="circuit_open"
            )
            return 0, {}, {"error": "circuit_open"}
        started = time.perf_counter()
        status, headers, payload = _once(
            url,
            method=method,
            api_key=api_key,
            body=body,
            extra_headers=extra_headers,
            timeout=timeout,
        )
        duration_ms = int((time.perf_counter() - started) * 1000)
        last = (status, headers, payload)
        if status == 200:
            circuit.record_success()
            _log_model_attempt(
                url, method, attempt, status, circuit.state, trace_id=trace_id,
                span_id=span_id, duration_ms=duration_ms,
            )
            return last
        if not _retryable(status) or attempt == max_attempts:
            if _retryable(status):
                circuit.record_failure()
            _log_model_attempt(
                url, method, attempt, status, circuit.state, trace_id=trace_id,
                span_id=span_id, duration_ms=duration_ms, error=f"http_{status}",
            )
            return last
        circuit.record_failure()
        _log_model_attempt(
            url, method, attempt, status, circuit.state, trace_id=trace_id,
            span_id=span_id, duration_ms=duration_ms, error=f"http_{status}",
        )
        if circuit.state == "open":
            return last
        pause(attempt)
    return last


def _log_model_attempt(
    url: str,
    method: str,
    attempt: int,
    status: int,
    circuit: str,
    *,
    trace_id: str | None,
    span_id: str,
    duration_ms: int = 0,
    error: str | None = None,
) -> None:
    log_span({
        "trace_id": trace_id or "",
        "span_id": span_id,
        "event": "tool_http",
        "actor": "shadow",
        "status": "ok" if status == 200 else "error",
        "dependency": "bedrock",
        "method": method,
        "host": url.split("/")[2] if "://" in url else "",
        "attempt": attempt,
        "http_status": status,
        "duration_ms": duration_ms,
        "circuit": circuit,
        "error_code": error,
    })


def _retryable(status: int) -> bool:
    return status == 0 or status == 429 or status >= 500


def _once(
    url: str,
    *,
    method: str,
    api_key: str,
    body: dict | None,
    extra_headers: dict[str, str] | None,
    timeout: float,
) -> tuple[int, dict[str, str], dict]:
    data = None if body is None else json.dumps(body).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }
    if data is not None:
        headers["Content-Type"] = "application/json"
    if extra_headers:
        headers.update(extra_headers)
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return _parsed(response.status, response.headers, response.read())
    except urllib.error.HTTPError as exc:
        return _parsed(exc.code, exc.headers, exc.read())
    except (urllib.error.URLError, TimeoutError, OSError):
        return 0, {}, {}


def _parsed(status: int, header_items, raw: bytes) -> tuple[int, dict[str, str], dict]:
    headers = {key.lower(): value for key, value in header_items.items()}
    if not raw:
        return status, headers, {}
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return status, headers, {}
    if not isinstance(parsed, dict):
        return status, headers, {}
    return status, headers, parsed
