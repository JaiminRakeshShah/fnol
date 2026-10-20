"""GET /v1/cases/{case_id}/claims with at most three attempts."""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable

from fnol_rules.types import ClaimsSnapshot

MAX_ATTEMPTS = 3


@dataclass(frozen=True)
class ClaimsAttempt:
    attempt: int
    status: int
    body: dict[str, Any] | None = None


@dataclass(frozen=True)
class ClaimsFetchResult:
    snapshot: ClaimsSnapshot
    attempts: tuple[ClaimsAttempt, ...]
    raw_json: dict[str, Any] | None = None


def _default_get(url: str) -> tuple[int, dict[str, Any]]:
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        try:
            body = json.loads(exc.read().decode())
        except (json.JSONDecodeError, UnicodeDecodeError):
            body = {"error": "http_error"}
        return exc.code, body


def fetch_claims(
    case_id: str,
    base_url: str,
    *,
    max_attempts: int = MAX_ATTEMPTS,
    get: Callable[[str], tuple[int, dict[str, Any]]] | None = None,
) -> ClaimsFetchResult:
    """Fetch claims; on retryable failure retry up to max_attempts then mark unavailable."""
    getter = get or _default_get
    url = f"{base_url.rstrip('/')}/v1/cases/{case_id}/claims"
    attempts: list[ClaimsAttempt] = []

    for n in range(1, max_attempts + 1):
        status, body = getter(url)
        attempts.append(ClaimsAttempt(attempt=n, status=status, body=body))
        if status == 200 and isinstance(body, dict):
            snap = ClaimsSnapshot(
                existing_claims=list(body.get("existing_claims") or []),
                intake_deliveries=int(body.get("intake_deliveries") or 0),
                source_id=body.get("source_id"),
                loss_reference=body.get("loss_reference"),
                available=True,
            )
            return ClaimsFetchResult(
                snapshot=snap,
                attempts=tuple(attempts),
                raw_json=body,
            )
        # 503 / upstream_timeout → retry; anything else still counts as an attempt
        if n == max_attempts:
            break

    return ClaimsFetchResult(
        snapshot=ClaimsSnapshot(available=False, existing_claims=[], intake_deliveries=0),
        attempts=tuple(attempts),
        raw_json=None,
    )
