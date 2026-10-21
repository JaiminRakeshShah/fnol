"""GET /v1/cases/{case_id}/policy with at most three attempts."""
from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable

MAX_ATTEMPTS = 3  # AUTO-TRIAGE-01: retry at most twice, three total attempts


@dataclass(frozen=True)
class PolicyAttempt:
    attempt: int
    status: int | None          # None when no HTTP response arrived (connection/timeout)
    error: str | None = None


@dataclass(frozen=True)
class PolicyFetchResult:
    payload: dict[str, Any] | None   # still contains private_token; caller redacts
    status: str                       # ok | not_found | unavailable
    attempts: tuple[PolicyAttempt, ...]


def _default_get(url: str) -> tuple[int | None, dict[str, Any] | None, str | None]:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8")), None
    except urllib.error.HTTPError as exc:
        try:
            body = json.loads(exc.read().decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            body = {}
        return exc.code, body, body.get("error") or f"http_{exc.code}"
    except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError) as exc:
        return None, None, "connection_failed"


def fetch_policy(
    case_id: str,
    base_url: str,
    *,
    max_attempts: int = MAX_ATTEMPTS,
    get: Callable[[str], tuple[int | None, dict[str, Any] | None, str | None]] | None = None,
) -> PolicyFetchResult:
    """Fetch the policy snapshot. 404 is final; anything else retries up to max_attempts."""
    getter = get or _default_get
    url = f"{base_url.rstrip('/')}/v1/cases/{case_id}/policy"
    attempts: list[PolicyAttempt] = []
    for n in range(1, max_attempts + 1):
        status, body, error = getter(url)
        attempts.append(PolicyAttempt(attempt=n, status=status, error=error))
        if status == 200 and isinstance(body, dict):
            return PolicyFetchResult(payload=body, status="ok", attempts=tuple(attempts))
        if status == 404:
            return PolicyFetchResult(payload=None, status="not_found", attempts=tuple(attempts))
    return PolicyFetchResult(payload=None, status="unavailable", attempts=tuple(attempts))
